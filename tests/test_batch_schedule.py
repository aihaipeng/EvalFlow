import threading
import time
from datetime import UTC, datetime, timedelta

from apscheduler.triggers.date import DateTrigger

from execution.batch_schedule import (
    BatchScheduleManager,
    BatchScheduleRepository,
    next_schedule_at,
)


def _schedule(**values):
    return {
        "enabled": True,
        "cadence": "DAILY",
        "run_at": "",
        "run_time": "09:00",
        "weekdays": ["1", "2", "3", "4", "5"],
        "month_day": 1,
        "timezone": "Asia/Shanghai",
        "overlap_policy": "SKIP",
        **values,
    }


def test_next_schedule_time_supports_daily_weekly_and_monthly_boundaries():
    after = datetime(2026, 1, 30, 2, 0, tzinfo=UTC)

    daily = next_schedule_at(_schedule(), after)
    weekly = next_schedule_at(_schedule(cadence="WEEKLY", weekdays=["1"]), after)
    monthly = next_schedule_at(
        _schedule(cadence="MONTHLY", month_day=31),
        datetime(2026, 2, 1, 2, 0, tzinfo=UTC),
    )

    assert daily == datetime(2026, 1, 31, 1, 0, tzinfo=UTC)
    assert weekly == datetime(2026, 2, 2, 1, 0, tzinfo=UTC)
    assert monthly == datetime(2026, 3, 31, 1, 0, tzinfo=UTC)


def test_repository_persists_schedule_and_skips_missed_restart_runs(tmp_path):
    repository = BatchScheduleRepository(tmp_path / "database.sqlite3")
    saved = repository.save(
        "batch-1",
        _schedule(),
        now=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
    )

    recovered = repository.recover_missed(
        now=datetime(2026, 1, 3, 4, 0, tzinfo=UTC)
    )
    current = repository.get("batch-1")

    assert saved["next_run_at"] == "2026-01-01T01:00:00.000Z"
    assert recovered == 1
    assert current["next_run_at"] == "2026-01-04T01:00:00.000Z"
    assert current["last_run_at"] is None
    assert current["last_error"] == "应用关闭期间错过执行，已跳过"


class _Store:
    def __init__(self, status="QUEUED"):
        self.batch = {"id": "batch-1", "status": status}

    def get(self, batch_id):
        return self.batch if batch_id == "batch-1" else None

    @staticmethod
    def has_execution(batch):
        return True


class _Inputs:
    def __init__(self):
        self.prepared = []

    def prepare_execution(self, batch_id):
        self.prepared.append(batch_id)


class _Scheduler:
    def __init__(self):
        self.started = []

    def start(self, batch_id):
        self.started.append(batch_id)


def test_due_once_schedule_starts_task_and_disables_itself(tmp_path):
    repository = BatchScheduleRepository(tmp_path / "database.sqlite3")
    repository.save(
        "batch-1",
        _schedule(
            cadence="ONCE",
            run_at="2026-01-01T09:00:01",
            timezone="UTC",
        ),
        now=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
    )
    store, inputs, scheduler = _Store(), _Inputs(), _Scheduler()
    manager = BatchScheduleManager(repository, store, inputs, scheduler)

    triggered = manager.run_due(now=datetime(2026, 1, 1, 9, 0, 2, tzinfo=UTC))
    current = repository.get("batch-1")

    assert triggered == 1
    assert scheduler.started == ["batch-1"]
    assert inputs.prepared == []
    assert current["enabled"] is False
    assert current["next_run_at"] is None
    assert current["last_run_at"] == "2026-01-01T09:00:02.000Z"


def test_due_terminal_schedule_delegates_exactly_one_prepare_to_scheduler(tmp_path):
    repository = BatchScheduleRepository(tmp_path / "terminal.sqlite3")
    repository.save(
        "batch-1",
        _schedule(cadence="ONCE", run_at="2026-01-01T09:00:01", timezone="UTC"),
        now=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
    )
    store, inputs, scheduler = _Store(status="SUCCESS"), _Inputs(), _Scheduler()

    BatchScheduleManager(repository, store, inputs, scheduler).run_due(
        now=datetime(2026, 1, 1, 9, 0, 2, tzinfo=UTC)
    )

    assert scheduler.started == ["batch-1"]
    assert inputs.prepared == []


def test_overlap_policy_skips_or_queues_while_task_is_active(tmp_path):
    now = datetime(2026, 1, 1, 9, 0, 2, tzinfo=UTC)
    store, inputs, scheduler = _Store(status="RUNNING"), _Inputs(), _Scheduler()

    skip_repository = BatchScheduleRepository(tmp_path / "skip.sqlite3")
    skip_repository.save(
        "batch-1",
        _schedule(cadence="ONCE", run_at="2026-01-01T09:00:01", timezone="UTC"),
        now=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
    )
    BatchScheduleManager(skip_repository, store, inputs, scheduler).run_due(now=now)

    queue_repository = BatchScheduleRepository(tmp_path / "queue.sqlite3")
    queue_repository.save(
        "batch-1",
        _schedule(
            cadence="ONCE",
            run_at="2026-01-01T09:00:01",
            timezone="UTC",
            overlap_policy="QUEUE",
        ),
        now=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
    )
    BatchScheduleManager(queue_repository, store, inputs, scheduler).run_due(now=now)

    skipped = skip_repository.get("batch-1")
    queued = queue_repository.get("batch-1")
    assert skipped["enabled"] is False
    assert skipped["last_error"] == "上一次任务仍在运行，本次执行已跳过"
    assert queued["enabled"] is True
    assert queued["next_run_at"] == "2026-01-01T09:00:01.000Z"
    assert scheduler.started == []


def test_occurrence_completion_does_not_overwrite_concurrent_schedule_edit(tmp_path):
    repository = BatchScheduleRepository(tmp_path / "concurrent-edit.sqlite3")
    repository.save(
        "batch-1",
        _schedule(cadence="ONCE", run_at="2026-01-01T09:00:01", timezone="UTC"),
        now=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
    )
    entered = threading.Event()
    release = threading.Event()

    class BlockingScheduler:
        def start(self, batch_id):
            entered.set()
            assert release.wait(3)

    manager = BatchScheduleManager(
        repository,
        _Store(),
        _Inputs(),
        BlockingScheduler(),
    )
    thread = threading.Thread(
        target=lambda: manager.run_due(
            now=datetime(2026, 1, 1, 9, 0, 2, tzinfo=UTC)
        )
    )
    thread.start()
    assert entered.wait(2)

    saved = repository.save(
        "batch-1",
        _schedule(cadence="ONCE", run_at="2026-01-02T09:00:00", timezone="UTC"),
        now=datetime(2026, 1, 1, 9, 0, 3, tzinfo=UTC),
    )
    release.set()
    thread.join(timeout=3)

    current = repository.get("batch-1")
    assert not thread.is_alive()
    assert saved["next_run_at"] == "2026-01-02T09:00:00.000Z"
    assert current and current["enabled"] is True
    assert current["next_run_at"] == saved["next_run_at"]
    assert current["last_error"] is None


def test_apscheduler_triggers_persisted_date_job_without_custom_poll_thread(tmp_path):
    repository = BatchScheduleRepository(tmp_path / "apscheduler.sqlite3")
    run_at = datetime.now(UTC) + timedelta(milliseconds=350)
    repository.save(
        "batch-1",
        _schedule(cadence="ONCE", run_at=run_at.isoformat(), timezone="UTC"),
    )
    store, inputs, scheduler = _Store(), _Inputs(), _Scheduler()
    manager = BatchScheduleManager(
        repository, store, inputs, scheduler, poll_interval_seconds=0.05
    )

    manager.start()
    deadline = time.monotonic() + 2
    while not scheduler.started and time.monotonic() < deadline:
        time.sleep(0.02)
    manager.shutdown()

    assert scheduler.started == ["batch-1"]
    assert repository.get("batch-1")["enabled"] is False


def test_apscheduler_requeues_persisted_job_after_executor_misfire(tmp_path):
    repository = BatchScheduleRepository(tmp_path / "misfire.sqlite3")
    run_at = datetime.now(UTC) + timedelta(milliseconds=700)
    repository.save(
        "batch-1",
        _schedule(cadence="ONCE", run_at=run_at.isoformat(), timezone="UTC"),
    )
    store, inputs, scheduler = _Store(), _Inputs(), _Scheduler()
    manager = BatchScheduleManager(
        repository,
        store,
        inputs,
        scheduler,
        poll_interval_seconds=0.05,
        misfire_grace_time_seconds=1,
    )
    release = threading.Event()

    def block_executor():
        assert release.wait(5)

    manager.start()
    try:
        block_at = datetime.now(UTC) + timedelta(milliseconds=100)
        for index in range(10):
            manager._scheduler.add_job(
                block_executor,
                DateTrigger(run_date=block_at, timezone=UTC),
                id=f"block-{index}",
            )
        time.sleep(2.2)
        release.set()
        deadline = time.monotonic() + 3
        while not scheduler.started and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        release.set()
        manager.shutdown()

    current = repository.get("batch-1")
    assert scheduler.started == ["batch-1"]
    assert current and current["enabled"] is False
    assert current["next_run_at"] is None
