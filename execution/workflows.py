"""New Workflow persistence records and SQLite repository."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from execution.targets import DEFAULT_DATABASE_PATH
from execution.workflow_contract import (
    ERROR_CODES,
    NodeStatus,
    NodeType,
    WorkflowDefinition,
    _ContractModel,
    ensure_strict_json,
    validate_uuid4,
)


# Asia/Shanghai has a fixed UTC+08:00 offset and Windows Python installations
# do not always bundle the IANA time-zone database.
SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")
_LOCK_GUARD = threading.Lock()
_INITIALIZE_LOCKS: dict[Path, threading.Lock] = {}


def workflow_now() -> str:
    return datetime.now(SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")


class WorkflowRepositoryError(RuntimeError):
    pass


class WorkflowRunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RuntimeErrorRecord(_ContractModel):
    code: str
    message: str = Field(min_length=1)
    node_run_id: str | None = None
    details: dict[str, Any] | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        if value not in ERROR_CODES:
            raise ValueError("Unknown workflow error code")
        return value

    @field_validator("node_run_id")
    @classmethod
    def validate_node_run_id(cls, value: str | None) -> str | None:
        return validate_uuid4(value, field_name="error.node_run_id") if value else None

    @field_validator("details")
    @classmethod
    def validate_details(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return ensure_strict_json(value) if value is not None else None


class WorkflowRecord(WorkflowDefinition):
    created_at: str = Field(default_factory=workflow_now)
    updated_at: str = Field(default_factory=workflow_now)


class WorkflowRunRecord(_ContractModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    workflow_id: str
    status: WorkflowRunStatus = WorkflowRunStatus.PENDING
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    error: RuntimeErrorRecord | None = None

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        return validate_uuid4(value, field_name="workflow_run.run_id")

    @field_validator("workflow_id")
    @classmethod
    def validate_workflow_id(cls, value: str) -> str:
        return validate_uuid4(value, field_name="workflow_run.workflow_id")

    @field_validator("status", mode="before")
    @classmethod
    def parse_status(cls, value: WorkflowRunStatus | str) -> WorkflowRunStatus:
        return value if isinstance(value, WorkflowRunStatus) else WorkflowRunStatus(value)

    @model_validator(mode="after")
    def validate_state(self):
        terminal = {WorkflowRunStatus.SUCCESS, WorkflowRunStatus.FAILED, WorkflowRunStatus.CANCELLED}
        if self.status in terminal and self.finished_at is None:
            raise ValueError("Terminal WorkflowRun requires finished_at")
        if self.status in {WorkflowRunStatus.SUCCESS, WorkflowRunStatus.PENDING, WorkflowRunStatus.RUNNING} and self.error is not None:
            raise ValueError("Successful or active WorkflowRun cannot contain an error")
        if self.status in {WorkflowRunStatus.FAILED, WorkflowRunStatus.CANCELLED} and self.error is None:
            raise ValueError("Failed or cancelled WorkflowRun requires an error")
        return self


class NodeRunRecord(_ContractModel):
    run_id: str
    node_run_id: str = Field(default_factory=lambda: str(uuid4()))
    node_id: str
    type: NodeType
    status: NodeStatus = NodeStatus.PENDING
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    attempt_count: int = Field(default=0, ge=0)
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    model: dict[str, Any] | None = None
    network: dict[str, Any] | None = None
    request: dict[str, Any] | None = None
    redirects: list[dict[str, Any]] = Field(default_factory=list)
    response: Any = None
    usage: dict[str, Any] | None = None
    usage_errors: list[dict[str, Any]] = Field(default_factory=list)
    error: RuntimeErrorRecord | None = None

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        return validate_uuid4(value, field_name="node_run.run_id")

    @field_validator("node_run_id")
    @classmethod
    def validate_node_run_id(cls, value: str) -> str:
        return validate_uuid4(value, field_name="node_run.node_run_id")

    @field_validator("node_id")
    @classmethod
    def validate_node_id(cls, value: str) -> str:
        return validate_uuid4(value, field_name="node_run.node_id")

    @field_validator("type", mode="before")
    @classmethod
    def parse_type(cls, value: NodeType | str) -> NodeType:
        return value if isinstance(value, NodeType) else NodeType(value)

    @field_validator("status", mode="before")
    @classmethod
    def parse_status(cls, value: NodeStatus | str) -> NodeStatus:
        return value if isinstance(value, NodeStatus) else NodeStatus(value)

    @field_validator("inputs", "outputs", "model", "network", "request", "redirects", "response", "usage", "usage_errors", mode="before")
    @classmethod
    def validate_json_fields(cls, value: Any) -> Any:
        return ensure_strict_json(value)

    @model_validator(mode="after")
    def validate_state(self):
        active = {NodeStatus.PENDING, NodeStatus.RUNNING}
        terminal = {NodeStatus.SUCCESS, NodeStatus.FAILED, NodeStatus.TIMEOUT, NodeStatus.CANCELLED}
        if self.status in active and self.error is not None:
            raise ValueError("Active NodeRun cannot contain an error")
        if self.status in terminal and self.finished_at is None:
            raise ValueError("Terminal NodeRun requires finished_at")
        if self.status in {NodeStatus.FAILED, NodeStatus.TIMEOUT, NodeStatus.CANCELLED} and self.error is None:
            raise ValueError("Failed, timed out, or cancelled NodeRun requires an error")
        if self.status == NodeStatus.SUCCESS and self.error is not None:
            raise ValueError("Successful NodeRun cannot contain an error")
        return self


class WorkflowRepository:
    """Repository for the new incompatible Workflow protocol."""

    def __init__(self, database_path: str | Path = DEFAULT_DATABASE_PATH):
        self.database_path = Path(database_path).resolve()
        with _LOCK_GUARD:
            self._initialize_lock = _INITIALIZE_LOCKS.setdefault(self.database_path, threading.Lock())
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect(initialize=False) as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_definitions_v2 (
                        workflow_id TEXT PRIMARY KEY,
                        definition_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_runs_v2 (
                        run_id TEXT PRIMARY KEY,
                        workflow_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        started_at TEXT,
                        finished_at TEXT,
                        duration_ms INTEGER,
                        error_json TEXT,
                        FOREIGN KEY(workflow_id) REFERENCES workflow_definitions_v2(workflow_id)
                            ON DELETE RESTRICT
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_node_runs_v2 (
                        node_run_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        node_id TEXT NOT NULL,
                        type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        started_at TEXT,
                        finished_at TEXT,
                        duration_ms INTEGER,
                        attempt_count INTEGER NOT NULL,
                        inputs_json TEXT NOT NULL,
                        outputs_json TEXT NOT NULL,
                        model_json TEXT,
                        network_json TEXT,
                        request_json TEXT,
                        redirects_json TEXT NOT NULL,
                        response_json TEXT,
                        usage_json TEXT,
                        usage_errors_json TEXT NOT NULL,
                        error_json TEXT,
                        FOREIGN KEY(run_id) REFERENCES workflow_runs_v2(run_id)
                            ON DELETE CASCADE
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS workflow_runs_v2_by_workflow ON workflow_runs_v2(workflow_id, started_at DESC, run_id DESC)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS workflow_node_runs_v2_by_run ON workflow_node_runs_v2(run_id, node_id, started_at ASC, node_run_id ASC)"
                )
                now = workflow_now()
                connection.execute(
                    "UPDATE workflow_node_runs_v2 SET status = 'CANCELLED', finished_at = ?, error_json = ? WHERE status IN ('PENDING', 'RUNNING')",
                    (now, _dump({"code": "NODE_CANCELLED_BY_FAIL_FAST", "message": "Process restarted while node was active"})),
                )
                connection.execute(
                    "UPDATE workflow_runs_v2 SET status = 'FAILED', finished_at = ?, error_json = ? WHERE status IN ('PENDING', 'RUNNING')",
                    (now, _dump({"code": "WORKFLOW_PROCESS_RESTARTED", "message": "Process restarted while WorkflowRun was active"})),
                )
                connection.commit()
            self._initialized = True

    def create_workflow(self, record: WorkflowRecord) -> WorkflowRecord:
        with self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO workflow_definitions_v2(workflow_id, definition_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (record.workflow_id, _dump(record.model_dump(mode="json", exclude={"created_at", "updated_at"})), record.created_at, record.updated_at),
                )
            except sqlite3.IntegrityError as exc:
                raise WorkflowRepositoryError("Workflow already exists") from exc
            connection.commit()
        return record

    def get_workflow(self, workflow_id: str) -> WorkflowRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM workflow_definitions_v2 WHERE workflow_id = ?", (workflow_id,)).fetchone()
        return self._workflow_from_row(row) if row else None

    def list_workflows(self) -> list[WorkflowRecord]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM workflow_definitions_v2 ORDER BY updated_at DESC, workflow_id DESC").fetchall()
        return [self._workflow_from_row(row) for row in rows]

    def update_workflow(self, record: WorkflowRecord) -> WorkflowRecord:
        record.updated_at = workflow_now()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE workflow_definitions_v2 SET definition_json = ?, updated_at = ? WHERE workflow_id = ?",
                (_dump(record.model_dump(mode="json", exclude={"created_at", "updated_at"})), record.updated_at, record.workflow_id),
            )
            connection.commit()
        if cursor.rowcount == 0:
            raise WorkflowRepositoryError("Workflow does not exist")
        return record

    def delete_workflow(self, workflow_id: str) -> bool:
        with self._connect() as connection:
            run_count = connection.execute("SELECT COUNT(*) FROM workflow_runs_v2 WHERE workflow_id = ?", (workflow_id,)).fetchone()[0]
            if run_count:
                raise WorkflowRepositoryError("Workflow with run history cannot be deleted")
            cursor = connection.execute("DELETE FROM workflow_definitions_v2 WHERE workflow_id = ?", (workflow_id,))
            connection.commit()
        return cursor.rowcount > 0

    def create_workflow_run(self, record: WorkflowRunRecord) -> WorkflowRunRecord:
        with self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO workflow_runs_v2(run_id, workflow_id, status, started_at, finished_at, duration_ms, error_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (record.run_id, record.workflow_id, record.status, record.started_at, record.finished_at, record.duration_ms, _dump_optional(record.error)),
                )
            except sqlite3.IntegrityError as exc:
                raise WorkflowRepositoryError("WorkflowRun cannot be created") from exc
            connection.commit()
        return record

    def update_workflow_run(self, record: WorkflowRunRecord) -> WorkflowRunRecord:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE workflow_runs_v2 SET status = ?, started_at = ?, finished_at = ?, duration_ms = ?, error_json = ? WHERE run_id = ? AND workflow_id = ?",
                (record.status, record.started_at, record.finished_at, record.duration_ms, _dump_optional(record.error), record.run_id, record.workflow_id),
            )
            connection.commit()
        if cursor.rowcount == 0:
            raise WorkflowRepositoryError("WorkflowRun does not exist")
        return record

    def get_workflow_run(self, run_id: str) -> WorkflowRunRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM workflow_runs_v2 WHERE run_id = ?", (run_id,)).fetchone()
        return self._workflow_run_from_row(row) if row else None

    def list_workflow_runs(self, workflow_id: str) -> list[WorkflowRunRecord]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM workflow_runs_v2 WHERE workflow_id = ? ORDER BY started_at DESC, run_id DESC", (workflow_id,)).fetchall()
        return [self._workflow_run_from_row(row) for row in rows]

    def create_node_run(self, record: NodeRunRecord) -> NodeRunRecord:
        values = _node_run_values(record)
        with self._connect() as connection:
            try:
                connection.execute(
                    """INSERT INTO workflow_node_runs_v2(node_run_id, run_id, node_id, type, status, started_at, finished_at,
                    duration_ms, attempt_count, inputs_json, outputs_json, model_json, network_json,
                    request_json, redirects_json, response_json, usage_json, usage_errors_json, error_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    values,
                )
            except sqlite3.IntegrityError as exc:
                raise WorkflowRepositoryError("NodeRun cannot be created") from exc
            connection.commit()
        return record

    def update_node_run(self, record: NodeRunRecord) -> NodeRunRecord:
        values = _node_run_values(record)
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE workflow_node_runs_v2 SET node_id = ?, type = ?, status = ?, started_at = ?, finished_at = ?,
                duration_ms = ?, attempt_count = ?, inputs_json = ?, outputs_json = ?, model_json = ?,
                network_json = ?, request_json = ?, redirects_json = ?, response_json = ?, usage_json = ?,
                usage_errors_json = ?, error_json = ? WHERE node_run_id = ? AND run_id = ?""",
                values[2:19] + (values[0], values[1]),
            )
            connection.commit()
        if cursor.rowcount == 0:
            raise WorkflowRepositoryError("NodeRun does not exist")
        return record

    def list_node_runs(self, run_id: str) -> list[NodeRunRecord]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM workflow_node_runs_v2 WHERE run_id = ? ORDER BY started_at ASC, node_run_id ASC", (run_id,)).fetchall()
        return [self._node_run_from_row(row) for row in rows]

    @contextmanager
    def _connect(self, *, initialize: bool = True):
        if initialize:
            self.initialize()
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _workflow_from_row(row: sqlite3.Row) -> WorkflowRecord:
        data = _load(row["definition_json"])
        data.update(created_at=row["created_at"], updated_at=row["updated_at"])
        return WorkflowRecord.model_validate(data)

    @staticmethod
    def _workflow_run_from_row(row: sqlite3.Row) -> WorkflowRunRecord:
        return WorkflowRunRecord.model_validate(
            {
                "run_id": row["run_id"], "workflow_id": row["workflow_id"], "status": row["status"],
                "started_at": row["started_at"], "finished_at": row["finished_at"],
                "duration_ms": row["duration_ms"], "error": _load_optional(row["error_json"]),
            }
        )

    @staticmethod
    def _node_run_from_row(row: sqlite3.Row) -> NodeRunRecord:
        return NodeRunRecord.model_validate(
            {
                "node_run_id": row["node_run_id"], "run_id": row["run_id"], "node_id": row["node_id"],
                "type": row["type"], "status": row["status"], "started_at": row["started_at"],
                "finished_at": row["finished_at"], "duration_ms": row["duration_ms"], "attempt_count": row["attempt_count"],
                "inputs": _load(row["inputs_json"]), "outputs": _load(row["outputs_json"]),
                "model": _load_optional(row["model_json"]), "network": _load_optional(row["network_json"]),
                "request": _load_optional(row["request_json"]), "redirects": _load(row["redirects_json"]),
                "response": _load_optional(row["response_json"]), "usage": _load_optional(row["usage_json"]),
                "usage_errors": _load(row["usage_errors_json"]), "error": _load_optional(row["error_json"]),
            }
        )


def _node_run_values(record: NodeRunRecord) -> tuple[Any, ...]:
    return (
        record.node_run_id, record.run_id, record.node_id, record.type, record.status,
        record.started_at, record.finished_at, record.duration_ms, record.attempt_count,
        _dump(record.inputs), _dump(record.outputs), _dump_optional(record.model),
        _dump_optional(record.network), _dump_optional(record.request), _dump(record.redirects),
        _dump_optional(record.response), _dump_optional(record.usage), _dump(record.usage_errors),
        _dump_optional(record.error),
    )


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _dump_optional(value: Any) -> str | None:
    return _dump(value.model_dump(mode="json") if hasattr(value, "model_dump") else value) if value is not None else None


def _load(value: str) -> Any:
    return json.loads(value)


def _load_optional(value: str | None) -> Any:
    return _load(value) if value is not None else None
