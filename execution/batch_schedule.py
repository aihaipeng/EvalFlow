"""Persistent schedules for reusable Batch tasks."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from calendar import monthrange
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from execution.batch_execution_store import BatchExecutionError, BatchExecutionStore
from execution.batch_inputs import BatchInputService
from execution.batch_scheduler import BatchScheduler
from execution.init_db import (
    DEFAULT_DATABASE_PATH,
    configure_sqlite_connection,
    database_initialize_lock_for,
    initialize_sqlite_pragmas,
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
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect(initialize=False) as connection:
                initialize_sqlite_pragmas(connection)
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS batch_schedules (
                        batch_id TEXT PRIMARY KEY,
                        enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
                        cadence TEXT NOT NULL,
                        run_at TEXT NOT NULL,
                        run_time TEXT NOT NULL,
                        weekdays_json TEXT NOT NULL,
                        month_day INTEGER NOT NULL,
                        timezone TEXT NOT NULL,
                        overlap_policy TEXT NOT NULL,
                        next_run_at TEXT,
                        last_run_at TEXT,
                        last_error TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS batch_schedules_due
                        ON batch_schedules(enabled, next_run_at);
                    """
                )
                connection.commit()
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
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO batch_schedules (
                    batch_id, enabled, cadence, run_at, run_time, weekdays_json,
                    month_day, timezone, overlap_policy, next_run_at, last_run_at,
                    last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                ON CONFLICT(batch_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    cadence = excluded.cadence,
                    run_at = excluded.run_at,
                    run_time = excluded.run_time,
                    weekdays_json = excluded.weekdays_json,
                    month_day = excluded.month_day,
                    timezone = excluded.timezone,
                    overlap_policy = excluded.overlap_policy,
                    next_run_at = excluded.next_run_at,
                    last_error = NULL,
                    updated_at = excluded.updated_at
                """,
                (
                    batch_id,
                    int(schedule["enabled"]),
                    schedule["cadence"],
                    schedule["run_at"],
                    schedule["run_time"],
                    json.dumps(schedule["weekdays"]),
                    schedule["month_day"],
                    schedule["timezone"],
                    schedule["overlap_policy"],
                    _utc_iso(next_run) if next_run else None,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
        return self.get(batch_id) or {}

    def get(self, batch_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM batch_schedules WHERE batch_id = ?", (batch_id,)
            ).fetchone()
        return self._row(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM batch_schedules ORDER BY updated_at DESC"
            ).fetchall()
        return [self._row(row) for row in rows]

    def list_due(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        timestamp = _utc_iso((now or _utc_now()).astimezone(UTC))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM batch_schedules
                WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?
                ORDER BY next_run_at, batch_id
                """,
                (timestamp,),
            ).fetchall()
        return [self._row(row) for row in rows]

    def complete_occurrence(
        self,
        batch_id: str,
        *,
        now: datetime | None = None,
        error: str | None = None,
        executed: bool,
    ) -> dict[str, Any] | None:
        now = (now or _utc_now()).astimezone(UTC)
        schedule = self.get(batch_id)
        if schedule is None:
            return None
        if schedule["cadence"] == "ONCE":
            enabled = False
            next_run = None
        else:
            enabled = schedule["enabled"]
            next_run = next_schedule_at(schedule, now) if enabled else None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE batch_schedules
                SET enabled = ?, next_run_at = ?, last_run_at = ?, last_error = ?, updated_at = ?
                WHERE batch_id = ?
                """,
                (
                    int(enabled),
                    _utc_iso(next_run) if next_run else None,
                    _utc_iso(now) if executed else schedule.get("last_run_at"),
                    error,
                    _utc_iso(now),
                    batch_id,
                ),
            )
            connection.commit()
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
            )
        return len(schedules)

    def delete(self, batch_id: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM batch_schedules WHERE batch_id = ?", (batch_id,)
            )
            connection.commit()
        return cursor.rowcount

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        data["weekdays"] = json.loads(data.pop("weekdays_json"))
        return data

    @contextmanager
    def _connect(self, *, initialize: bool = True) -> Iterator[sqlite3.Connection]:
        if initialize:
            self.initialize()
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        configure_sqlite_connection(connection)
        try:
            yield connection
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()


class BatchScheduleManager:
    def __init__(
        self,
        repository: BatchScheduleRepository,
        store: BatchExecutionStore,
        inputs: BatchInputService,
        scheduler: BatchScheduler,
        *,
        poll_interval_seconds: float = 0.5,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.repository = repository
        self.store = store
        self.inputs = inputs
        self.scheduler = scheduler
        self.poll_interval_seconds = max(0.05, poll_interval_seconds)
        self.now = now
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> int:
        recovered = self.repository.recover_missed(now=self.now())
        if self._thread and self._thread.is_alive():
            return recovered
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="batch-schedule-manager",
        )
        self._thread.start()
        return recovered

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
                )
                continue
            try:
                if not (
                    batch.get("status") == "QUEUED" and self.store.has_execution(batch)
                ):
                    self.inputs.prepare_execution(batch_id)
                self.scheduler.start(batch_id)
            except (BatchExecutionError, ValueError) as exc:
                logger.exception("定时任务启动失败: %s", batch_id)
                self.repository.complete_occurrence(
                    batch_id,
                    now=now,
                    error=str(exc),
                    executed=False,
                )
                continue
            self.repository.complete_occurrence(
                batch_id,
                now=now,
                error=None,
                executed=True,
            )
            triggered += 1
        return triggered

    def shutdown(self, *, wait_seconds: float = 10) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread:
            thread.join(timeout=max(0, wait_seconds))
            if thread.is_alive():
                raise BatchExecutionError("定时任务调度器未能及时终止")
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.wait(self.poll_interval_seconds):
            try:
                self.run_due()
            except Exception:
                logger.exception("定时任务轮询失败")
