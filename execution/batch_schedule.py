"""Persistent schedules for reusable Batch tasks."""

from __future__ import annotations

import json
import logging
from calendar import monthrange
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.events import EVENT_JOB_MISSED
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import and_, delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from execution.batch_execution_store import BatchExecutionError, BatchExecutionStore
from execution.batch_inputs import BatchInputService
from execution.batch_scheduler import BatchScheduler
from execution.database_schema import batch_schedules
from execution.init_db import (
    DEFAULT_DATABASE_PATH,
    database_read_connection,
    database_transaction,
    database_initialize_lock_for,
    upgrade_database,
)


logger = logging.getLogger(__name__)

SCHEDULE_CADENCES = {"ONCE", "DAILY", "WEEKLY", "MONTHLY"}
OVERLAP_POLICIES = {"SKIP", "QUEUE"}
WEEKDAYS = {"0", "1", "2", "3", "4", "5", "6"}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _parse_run_time(value: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("执行时间格式无效") from exc
    return parsed.replace(second=0, microsecond=0)


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"不支持的时区: {name}") from exc


def next_schedule_at(schedule: dict[str, Any], after: datetime) -> datetime | None:
    after = after.astimezone(UTC)
    timezone = _timezone(schedule["timezone"])
    local_after = after.astimezone(timezone)
    cadence = schedule["cadence"]
    if cadence == "ONCE":
        try:
            local_run_at = datetime.fromisoformat(schedule["run_at"])
        except ValueError as exc:
            raise ValueError("一次性执行时间格式无效") from exc
        if local_run_at.tzinfo is None:
            local_run_at = local_run_at.replace(tzinfo=timezone)
        candidate = local_run_at.astimezone(UTC)
        return candidate if candidate > after else None

    run_time = _parse_run_time(schedule["run_time"])
    if cadence == "DAILY":
        candidate = datetime.combine(local_after.date(), run_time, timezone)
        if candidate <= local_after:
            candidate += timedelta(days=1)
        return candidate.astimezone(UTC)

    if cadence == "WEEKLY":
        weekdays = set(schedule["weekdays"])
        for offset in range(8):
            candidate_date = local_after.date() + timedelta(days=offset)
            if str(candidate_date.isoweekday() % 7) not in weekdays:
                continue
            candidate = datetime.combine(candidate_date, run_time, timezone)
            if candidate > local_after:
                return candidate.astimezone(UTC)
        raise ValueError("无法计算每周任务的下次执行时间")

    if cadence == "MONTHLY":
        year, month = local_after.year, local_after.month
        month_day = int(schedule["month_day"])
        for _ in range(24):
            if month_day <= monthrange(year, month)[1]:
                candidate = datetime.combine(date(year, month, month_day), run_time, timezone)
                if candidate > local_after:
                    return candidate.astimezone(UTC)
            month = 1 if month == 12 else month + 1
            year += 1 if month == 1 else 0
        raise ValueError("无法计算每月任务的下次执行时间")

    raise ValueError(f"不支持的调度方式: {cadence}")


def normalize_schedule(values: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    cadence = str(values.get("cadence") or "DAILY").upper()
    overlap_policy = str(values.get("overlap_policy") or "SKIP").upper()
    timezone = str(values.get("timezone") or "Asia/Shanghai")
    weekdays = sorted(
        {str(value) for value in values.get("weekdays") or [] if str(value) in WEEKDAYS},
        key=int,
    )
    schedule = {
        "enabled": bool(values.get("enabled")),
        "cadence": cadence,
        "run_at": str(values.get("run_at") or ""),
        "run_time": str(values.get("run_time") or "09:00"),
        "weekdays": weekdays,
        "month_day": int(values.get("month_day") or 1),
        "timezone": timezone,
        "overlap_policy": overlap_policy,
    }
    if cadence not in SCHEDULE_CADENCES:
        raise ValueError("调度方式无效")
    if overlap_policy not in OVERLAP_POLICIES:
        raise ValueError("任务重叠策略无效")
    _timezone(timezone)
    if not schedule["enabled"]:
        return schedule
    if cadence == "ONCE" and not schedule["run_at"]:
        raise ValueError("请选择一次性任务的执行时间")
    if cadence != "ONCE":
        _parse_run_time(schedule["run_time"])
    if cadence == "WEEKLY" and not weekdays:
        raise ValueError("每周任务至少选择一天")
    if cadence == "MONTHLY" and not 1 <= schedule["month_day"] <= 31:
        raise ValueError("每月日期必须在 1 到 31 之间")
    if next_schedule_at(schedule, now) is None:
        raise ValueError("一次性执行时间必须晚于当前时间")
    return schedule


class BatchScheduleRepository:
    def __init__(self, database_path: str | Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = Path(database_path).resolve()
        self._initialize_lock = database_initialize_lock_for(self.database_path)
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            upgrade_database(self.database_path)
            self._initialized = True

    def save(
        self,
        batch_id: str,
        values: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = (now or _utc_now()).astimezone(UTC)
        schedule = normalize_schedule(values, now=now)
        next_run = next_schedule_at(schedule, now) if schedule["enabled"] else None
        timestamp = _utc_iso(now)
        statement = sqlite_insert(batch_schedules).values(
            batch_id=batch_id,
            enabled=int(schedule["enabled"]),
            cadence=schedule["cadence"],
            run_at=schedule["run_at"],
            run_time=schedule["run_time"],
            weekdays_json=json.dumps(schedule["weekdays"]),
            month_day=schedule["month_day"],
            timezone=schedule["timezone"],
            overlap_policy=schedule["overlap_policy"],
            next_run_at=_utc_iso(next_run) if next_run else None,
            last_run_at=None,
            last_error=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[batch_schedules.c.batch_id],
            set_={
                "enabled": statement.excluded.enabled,
                "cadence": statement.excluded.cadence,
                "run_at": statement.excluded.run_at,
                "run_time": statement.excluded.run_time,
                "weekdays_json": statement.excluded.weekdays_json,
                "month_day": statement.excluded.month_day,
                "timezone": statement.excluded.timezone,
                "overlap_policy": statement.excluded.overlap_policy,
                "next_run_at": statement.excluded.next_run_at,
                "last_error": None,
                "updated_at": statement.excluded.updated_at,
            },
        )
        with self._transaction() as connection:
            connection.execute(statement)
        return self.get(batch_id) or {}

    def get(self, batch_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                select(batch_schedules).where(batch_schedules.c.batch_id == batch_id)
            ).mappings().first()
        return self._row(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                select(batch_schedules).order_by(batch_schedules.c.updated_at.desc())
            ).mappings().all()
        return [self._row(row) for row in rows]

    def list_due(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        timestamp = _utc_iso((now or _utc_now()).astimezone(UTC))
        with self._connect() as connection:
            rows = connection.execute(
                select(batch_schedules)
                .where(
                    and_(
                        batch_schedules.c.enabled == 1,
                        batch_schedules.c.next_run_at.is_not(None),
                        batch_schedules.c.next_run_at <= timestamp,
                    )
                )
                .order_by(batch_schedules.c.next_run_at, batch_schedules.c.batch_id)
            ).mappings().all()
        return [self._row(row) for row in rows]

    def complete_occurrence(
        self,
        batch_id: str,
        *,
        now: datetime | None = None,
        error: str | None = None,
        executed: bool,
        expected_next_run_at: str | None = None,
    ) -> dict[str, Any] | None:
        now = (now or _utc_now()).astimezone(UTC)
        with self._transaction(immediate=True) as connection:
            row = connection.execute(
                select(batch_schedules).where(batch_schedules.c.batch_id == batch_id)
            ).mappings().first()
            if row is None:
                return None
            schedule = self._row(row)
            if (
                expected_next_run_at is not None
                and schedule.get("next_run_at") != expected_next_run_at
            ):
                return schedule
            if schedule["cadence"] == "ONCE":
                enabled = False
                next_run = None
            else:
                enabled = schedule["enabled"]
                next_run = next_schedule_at(schedule, now) if enabled else None
            occurrence = batch_schedules.c.batch_id == batch_id
            if expected_next_run_at is not None:
                occurrence = and_(
                    occurrence,
                    batch_schedules.c.next_run_at == expected_next_run_at,
                )
            connection.execute(
                update(batch_schedules)
                .where(occurrence)
                .values(
                    enabled=int(enabled),
                    next_run_at=_utc_iso(next_run) if next_run else None,
                    last_run_at=(
                        _utc_iso(now) if executed else schedule.get("last_run_at")
                    ),
                    last_error=error,
                    updated_at=_utc_iso(now),
                )
            )
        return self.get(batch_id)

    def recover_missed(self, *, now: datetime | None = None) -> int:
        now = (now or _utc_now()).astimezone(UTC)
        schedules = self.list_due(now=now)
        for schedule in schedules:
            self.complete_occurrence(
                schedule["batch_id"],
                now=now,
                error="应用关闭期间错过执行，已跳过",
                executed=False,
                expected_next_run_at=schedule["next_run_at"],
            )
        return len(schedules)

    def delete(self, batch_id: str) -> int:
        with self._transaction() as connection:
            cursor = connection.execute(
                delete(batch_schedules).where(batch_schedules.c.batch_id == batch_id)
            )
        return cursor.rowcount

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        try:
            data["weekdays"] = json.loads(data.pop("weekdays_json"))
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"调度计划星期配置数据损坏: {data.get('batch_id', '?')}") from exc
        return data

    @contextmanager
    def _connect(self, *, initialize: bool = True) -> Iterator[Any]:
        if initialize:
            self.initialize()
        with database_read_connection(self.database_path, initialize=False) as connection:
            yield connection

    @contextmanager
    def _transaction(self, *, immediate: bool = False) -> Iterator[Any]:
        self.initialize()
        with database_transaction(
            self.database_path,
            initialize=False,
            immediate=immediate,
        ) as connection:
            yield connection


class BatchScheduleManager:
    def __init__(
        self,
        repository: BatchScheduleRepository,
        store: BatchExecutionStore,
        inputs: BatchInputService,
        scheduler: BatchScheduler,
        *,
        poll_interval_seconds: float = 0.5,
        misfire_grace_time_seconds: int = 60,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.repository = repository
        self.store = store
        self.inputs = inputs
        self.scheduler = scheduler
        self.poll_interval_seconds = max(0.05, poll_interval_seconds)
        self.misfire_grace_time_seconds = max(1, int(misfire_grace_time_seconds))
        self.now = now
        self._scheduler: BackgroundScheduler | None = None

    def start(self) -> int:
        recovered = self.repository.recover_missed(now=self.now())
        if self._scheduler and self._scheduler.running:
            return recovered
        self._scheduler = BackgroundScheduler(
            timezone=UTC,
            daemon=True,
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": self.misfire_grace_time_seconds,
            },
        )
        self._scheduler.add_listener(self._handle_job_missed, EVENT_JOB_MISSED)
        self._scheduler.start()
        self.refresh()
        return recovered

    def refresh(self, batch_id: str | None = None) -> None:
        """Synchronize persisted next occurrences into APScheduler date jobs."""

        scheduler = self._scheduler
        if scheduler is None or not scheduler.running:
            return
        schedules = [self.repository.get(batch_id)] if batch_id else self.repository.list()
        for schedule in schedules:
            if not schedule:
                if batch_id:
                    job_id = self._job_id(batch_id)
                    if scheduler.get_job(job_id):
                        scheduler.remove_job(job_id)
                continue
            job_id = self._job_id(schedule["batch_id"])
            if not schedule["enabled"] or not schedule["next_run_at"]:
                if scheduler.get_job(job_id):
                    scheduler.remove_job(job_id)
                continue
            run_date = _parse_utc(schedule["next_run_at"])
            if run_date <= self.now().astimezone(UTC):
                run_date = self.now().astimezone(UTC) + timedelta(seconds=self.poll_interval_seconds)
            scheduler.add_job(
                self._run_occurrence,
                DateTrigger(run_date=run_date, timezone=UTC),
                args=[schedule["batch_id"]],
                id=job_id,
                replace_existing=True,
            )

    @staticmethod
    def _job_id(batch_id: str) -> str:
        return f"batch-schedule:{batch_id}"

    def _run_occurrence(self, batch_id: str) -> None:
        try:
            self.run_due()
        except Exception:
            logger.exception("定时任务触发失败: %s", batch_id)
        finally:
            self.refresh()

    def _handle_job_missed(self, event: Any) -> None:
        job_id = str(getattr(event, "job_id", ""))
        prefix = "batch-schedule:"
        if not job_id.startswith(prefix):
            return
        batch_id = job_id[len(prefix) :]
        logger.warning("定时任务超过执行宽限，重新挂载持久计划: %s", batch_id)
        try:
            self.refresh(batch_id)
        except Exception:
            logger.exception("重新挂载错过的定时任务失败: %s", batch_id)

    def run_due(self, *, now: datetime | None = None) -> int:
        now = (now or self.now()).astimezone(UTC)
        triggered = 0
        for schedule in self.repository.list_due(now=now):
            batch_id = schedule["batch_id"]
            batch = self.store.get(batch_id)
            if batch is None:
                self.repository.delete(batch_id)
                continue
            if batch.get("status") in {"RUNNING", "STOPPING"}:
                if schedule["overlap_policy"] == "QUEUE":
                    continue
                self.repository.complete_occurrence(
                    batch_id,
                    now=now,
                    error="上一次任务仍在运行，本次执行已跳过",
                    executed=False,
                    expected_next_run_at=schedule["next_run_at"],
                )
                continue
            try:
                self.scheduler.start(batch_id)
            except (BatchExecutionError, ValueError) as exc:
                logger.exception("定时任务启动失败: %s", batch_id)
                self.repository.complete_occurrence(
                    batch_id,
                    now=now,
                    error=str(exc),
                    executed=False,
                    expected_next_run_at=schedule["next_run_at"],
                )
                continue
            self.repository.complete_occurrence(
                batch_id,
                now=now,
                error=None,
                executed=True,
                expected_next_run_at=schedule["next_run_at"],
            )
            triggered += 1
        return triggered

    def shutdown(self, *, wait_seconds: float = 10) -> None:
        scheduler = self._scheduler
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=wait_seconds > 0)
        self._scheduler = None
