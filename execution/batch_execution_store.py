"""Atomic JSON persistence for Batch and Case execution facts."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from execution.workflow_execution_store import (
    execution_error,
    remove_execution_tree,
    utc_execution_time,
)
from execution.workflow_values import strict_json_clone


DEFAULT_BATCH_EXECUTION_ROOT = (
    Path(__file__).resolve().parents[1] / "run_storage" / "batch_executions"
)
BATCH_TERMINAL_STATUSES = {"SUCCESS", "COMPLETED_WITH_ERRORS", "INTERRUPTED"}
CASE_TERMINAL_STATUSES = {"SUCCESS", "FAILED", "INTERRUPTED"}


class BatchExecutionError(RuntimeError):
    """Batch facts cannot be created, read, or updated safely."""


def _uuid(value: str, label: str) -> str:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise BatchExecutionError(f"{label} 必须是 UUID") from exc
    if parsed.version != 4:
        raise BatchExecutionError(f"{label} 必须是 UUIDv4")
    return str(parsed)


class BatchExecutionStore:
    """Persist one immutable input snapshot and independently mutable Case facts."""

    def __init__(self, root: str | Path = DEFAULT_BATCH_EXECUTION_ROOT):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()

    def batch_root(self, batch_id: str) -> Path:
        return self.root / _uuid(batch_id, "batch_id")

    def create(
        self,
        batch: dict[str, Any],
        cases: list[dict[str, Any]],
        input_snapshot: dict[str, Any],
    ) -> None:
        target = self.batch_root(batch["id"])
        if target.exists():
            raise BatchExecutionError(f"Batch Execution 已存在: {batch['id']}")
        temporary = self.root / f".creating-{batch['id']}-{uuid4()}"
        try:
            (temporary / "cases").mkdir(parents=True)
            input_dir = temporary / "input"
            input_dir.mkdir()
            self._atomic_write(temporary / "batch.json", batch)
            self._atomic_write(input_dir / "snapshot.json", input_snapshot)
            for case in cases:
                self._atomic_write(
                    temporary / "cases" / f"{_uuid(case['id'], 'case_run_id')}.json",
                    case,
                )
            with self._write_lock:
                if target.exists():
                    raise BatchExecutionError(f"Batch Execution 已存在: {batch['id']}")
                for attempt in range(6):
                    try:
                        os.replace(temporary, target)
                        break
                    except PermissionError:
                        if attempt == 5:
                            raise
                        time.sleep(0.01)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def write_batch(self, batch: dict[str, Any]) -> None:
        target = self.batch_root(batch["id"]) / "batch.json"
        if not target.is_file():
            raise BatchExecutionError(f"Batch Execution 不存在: {batch['id']}")
        with self._write_lock:
            self._atomic_write(target, batch)

    def write_case(self, case: dict[str, Any]) -> None:
        target = (
            self.batch_root(case["batch_execution_id"])
            / "cases"
            / f"{_uuid(case['id'], 'case_run_id')}.json"
        )
        if not target.is_file():
            raise BatchExecutionError(f"Case Run 不存在: {case['id']}")
        with self._write_lock:
            self._atomic_write(target, case)

    def get(self, batch_id: str) -> dict[str, Any] | None:
        path = self.batch_root(batch_id) / "batch.json"
        return self._read(path) if path.is_file() else None

    def get_case(self, batch_id: str, case_run_id: str) -> dict[str, Any] | None:
        path = self.batch_root(batch_id) / "cases" / f"{_uuid(case_run_id, 'case_run_id')}.json"
        return self._read(path) if path.is_file() else None

    def list(self) -> list[dict[str, Any]]:
        documents = []
        for path in self.root.glob("*/batch.json"):
            try:
                documents.append(self._read(path))
            except (OSError, json.JSONDecodeError, BatchExecutionError):
                continue
        return sorted(documents, key=lambda item: item.get("created_at") or "", reverse=True)

    def list_cases(self, batch_id: str) -> list[dict[str, Any]]:
        directory = self.batch_root(batch_id) / "cases"
        if not directory.is_dir():
            return []
        cases = [self._read(path) for path in directory.glob("*.json")]
        return sorted(
            cases,
            key=lambda item: (
                item.get("call_number", item["row_number"]),
                item["id"],
            ),
        )

    def delete(self, batch_id: str) -> dict[str, Any]:
        batch = self.get(batch_id)
        if batch is None:
            raise BatchExecutionError(f"Batch Execution 不存在: {batch_id}")
        if batch.get("status") == "RUNNING":
            raise BatchExecutionError("运行中的 Batch 不能删除，请先取消并等待终态")
        root = self.batch_root(batch_id)
        with self._write_lock:
            remove_execution_tree(root)
        return batch

    def recover_incomplete(self) -> int:
        recovered = 0
        for batch in self.list():
            if batch.get("status") != "RUNNING":
                continue
            now = utc_execution_time()
            for case in self.list_cases(batch["id"]):
                if case.get("status") == "RUNNING":
                    case.update(
                        {
                            "status": "INTERRUPTED",
                            "execution_status": "INTERRUPTED",
                            "finished_at": now,
                            "error": execution_error(
                                "PROCESS_RESTARTED", "服务重启，活动 Case 未自动续跑"
                            ),
                        }
                    )
                    self.write_case(case)
            batch.update(
                {
                    "status": "INTERRUPTED",
                    "finished_at": now,
                    "error": execution_error(
                        "PROCESS_RESTARTED", "服务重启，Batch 未自动续跑"
                    ),
                }
            )
            self.write_batch(batch)
            recovered += 1
        return recovered

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        for attempt in range(6):
            try:
                raw = path.read_text(encoding="utf-8")
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.01)
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise BatchExecutionError(f"Batch JSON 根必须是 object: {path}")
        return document

    @staticmethod
    def _atomic_write(path: Path, document: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(
            strict_json_clone(document), ensure_ascii=False, allow_nan=False, indent=2
        ) + "\n"
        temporary = path.with_name(f".{uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            for attempt in range(6):
                try:
                    os.replace(temporary, path)
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.01)
        finally:
            temporary.unlink(missing_ok=True)
