"""SQLite-backed terminal execution history for Batch tasks."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from execution.init_db import (
    DEFAULT_DATABASE_PATH,
    configure_sqlite_connection,
    database_initialize_lock_for,
    initialize_sqlite_pragmas,
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
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect(initialize=False) as connection:
                initialize_sqlite_pragmas(connection)
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS batch_execution_history (
                        id TEXT PRIMARY KEY,
                        batch_id TEXT NOT NULL,
                        execution_round_id TEXT,
                        workflow_id TEXT NOT NULL,
                        test_set_name TEXT NOT NULL,
                        workflow_name TEXT NOT NULL,
                        total_cases INTEGER NOT NULL CHECK(total_cases >= 0),
                        executed_cases INTEGER NOT NULL CHECK(executed_cases >= 0),
                        passed_cases INTEGER NOT NULL CHECK(passed_cases >= 0),
                        started_at TEXT NOT NULL,
                        finished_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(workflow_id)
                            REFERENCES workflow_structural_models(id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS batch_execution_history_by_batch
                        ON batch_execution_history(batch_id, finished_at DESC, created_at DESC, id DESC);
                    CREATE INDEX IF NOT EXISTS batch_execution_history_by_workflow
                        ON batch_execution_history(workflow_id);
                    """
                )
                connection.commit()
            self._initialized = True

    def record(self, batch: dict[str, Any], *, started_at: str) -> dict[str, Any]:
        finished_at = str(batch.get("finished_at") or "").strip()
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
        )
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
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO batch_execution_history (
                    id, batch_id, execution_round_id, workflow_id,
                    test_set_name, workflow_name, total_cases, executed_cases,
                    passed_cases, started_at, finished_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(record.values()),
            )
            connection.execute(
                """
                DELETE FROM batch_execution_history
                WHERE batch_id = ? AND id NOT IN (
                    SELECT id FROM batch_execution_history
                    WHERE batch_id = ?
                    ORDER BY finished_at DESC, created_at DESC, id DESC
                    LIMIT 10
                )
                """,
                (record["batch_id"], record["batch_id"]),
            )
            connection.commit()
        return record

    def list_recent(self, batch_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 10))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM batch_execution_history
                WHERE batch_id = ?
                ORDER BY finished_at DESC, created_at DESC, id DESC
                LIMIT ?
                """,
                (batch_id, safe_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_batch(self, batch_id: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM batch_execution_history WHERE batch_id = ?", (batch_id,)
            )
            connection.commit()
        return cursor.rowcount

    @contextmanager
    def _connect(self, *, initialize: bool = True) -> Iterator[sqlite3.Connection]:
        if initialize:
            self.initialize()
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        configure_sqlite_connection(connection, foreign_keys=True)
        try:
            yield connection
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
