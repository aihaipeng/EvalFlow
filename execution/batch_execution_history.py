"""SQLite-backed terminal execution history for Batch tasks."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from sqlalchemy import and_, delete, insert, select

from execution.database_schema import batch_execution_history

from execution.init_db import (
    DEFAULT_DATABASE_PATH,
    database_read_connection,
    database_transaction,
    database_initialize_lock_for,
    upgrade_database,
)
from execution.workflow_execution_store import utc_execution_time


class BatchExecutionHistoryRepository:
    """Persist the latest terminal execution attempts for each Batch task."""

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

    def record(
        self,
        batch: dict[str, Any],
        *,
        started_at: str,
        finished_at: str | None = None,
        deduplicate: bool = False,
    ) -> dict[str, Any]:
        finished_at = str(finished_at or batch.get("finished_at") or "").strip()
        if not finished_at:
            raise ValueError("任务历史缺少结束时间")
        workflow = batch.get("workflow") if isinstance(batch.get("workflow"), dict) else {}
        input_snapshot = batch.get("input") if isinstance(batch.get("input"), dict) else {}
        summary = batch.get("summary") if isinstance(batch.get("summary"), dict) else {}
        workflow_id = str(workflow.get("id") or "").strip()
        if not workflow_id:
            raise ValueError("任务历史缺少工作流 ID")
        executed_cases = max(0, int(summary.get("success") or 0)) + max(
            0, int(summary.get("failed") or 0)
        ) + max(0, int(summary.get("interrupted") or 0))
        record = {
            "id": str(uuid4()),
            "batch_id": str(batch["id"]),
            "execution_round_id": batch.get("execution_round_id"),
            "workflow_id": workflow_id,
            "test_set_name": str(input_snapshot.get("test_set_name") or ""),
            "workflow_name": str(workflow.get("name") or ""),
            "total_cases": max(0, int(batch.get("total_cases") or 0)),
            "executed_cases": executed_cases,
            "passed_cases": max(0, int(summary.get("success") or 0)),
            "started_at": started_at,
            "finished_at": finished_at,
            "created_at": utc_execution_time(),
        }
        with self._transaction(immediate=True) as connection:
            if deduplicate:
                same_round = (
                    batch_execution_history.c.execution_round_id.is_(None)
                    if record["execution_round_id"] is None
                    else batch_execution_history.c.execution_round_id
                    == record["execution_round_id"]
                )
                existing = connection.execute(
                    select(batch_execution_history)
                    .where(
                        and_(
                            batch_execution_history.c.batch_id == record["batch_id"],
                            same_round,
                        )
                    )
                    .limit(1)
                ).mappings().first()
                if existing is not None:
                    return dict(existing)
            connection.execute(insert(batch_execution_history).values(**record))
            retained_ids = (
                select(batch_execution_history.c.id)
                .where(batch_execution_history.c.batch_id == record["batch_id"])
                .order_by(
                    batch_execution_history.c.finished_at.desc(),
                    batch_execution_history.c.created_at.desc(),
                    batch_execution_history.c.id.desc(),
                )
                .limit(10)
            )
            connection.execute(
                delete(batch_execution_history).where(
                    and_(
                        batch_execution_history.c.batch_id == record["batch_id"],
                        batch_execution_history.c.id.not_in(retained_ids),
                    )
                )
            )
        return record

    def list_recent(self, batch_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 10))
        with self._connect() as connection:
            rows = connection.execute(
                select(batch_execution_history)
                .where(batch_execution_history.c.batch_id == batch_id)
                .order_by(
                    batch_execution_history.c.finished_at.desc(),
                    batch_execution_history.c.created_at.desc(),
                    batch_execution_history.c.id.desc(),
                )
                .limit(safe_limit)
            ).mappings().all()
        return [dict(row) for row in rows]

    def delete_batch(self, batch_id: str) -> int:
        with self._transaction() as connection:
            cursor = connection.execute(
                delete(batch_execution_history).where(
                    batch_execution_history.c.batch_id == batch_id
                )
            )
        return cursor.rowcount

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
            self.database_path, initialize=False, immediate=immediate
        ) as connection:
            yield connection
