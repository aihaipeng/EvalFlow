"""Shared execution values and atomic JSON persistence."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from execution.workflow_values import strict_json_clone


DEFAULT_EXECUTION_ROOT = (
    Path(__file__).resolve().parents[1] / "run_storage" / "workflow_executions"
)
TERMINAL_WORKFLOW_STATUSES = {"SUCCESS", "FAILED", "INTERRUPTED"}
TERMINAL_NODE_STATUSES = {"SUCCESS", "FAILED", "TIMEOUT", "INTERRUPTED"}


def remove_execution_tree(path: Path) -> None:
    """Remove deep execution trees without Windows MAX_PATH truncation."""

    target: str | Path = (
        f"\\\\?\\{path.resolve()}" if os.name == "nt" else path
    )
    for attempt in range(6):
        try:
            shutil.rmtree(target)
            break
        except OSError:
            if attempt == 5:
                raise
            time.sleep(0.01)


def seconds_to_milliseconds(value: float) -> int:
    """把 Structural Model 的秒值统一舍入为执行器使用的整数毫秒。"""

    return max(0, round(value * 1000))


def utc_execution_time() -> str:
    """返回 Workflow Execution 使用的 UTC ISO-8601 毫秒时间。"""

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def local_execution_time() -> str:
    """返回 Node Execution 使用的本机时区秒级时间。"""

    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def execution_error(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


class WorkflowExecutionError(RuntimeError):
    """Workflow 无法启动、读取、持久化或满足执行状态机时的领域错误。"""


def _uuid(value: str, label: str) -> str:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise WorkflowExecutionError(f"{label} 必须是 UUID") from exc
    if parsed.version != 4:
        raise WorkflowExecutionError(f"{label} 必须是 UUIDv4")
    return str(parsed)


class WorkflowExecutionStore:
    """使用原子 JSON 文件持久化 Workflow 和 Node Execution 客观事实。"""

    def __init__(self, root: str | Path = DEFAULT_EXECUTION_ROOT):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()

    def workflow_root(self, workflow_id: str, *, create: bool = False) -> Path:
        path = self.root / _uuid(workflow_id, "workflow_id")
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def execution_root(
        self,
        workflow_id: str,
        execution_id: str,
        *,
        create: bool = False,
    ) -> Path:
        path = self.workflow_root(workflow_id, create=create) / _uuid(
            execution_id, "execution_id"
        )
        if create:
            (path / "nodes").mkdir(parents=True, exist_ok=True)
        return path

    def create(self, document: dict[str, Any]) -> None:
        path = self.execution_root(document["workflow_id"], document["id"], create=True)
        target = path / "workflow.json"
        if target.exists():
            raise WorkflowExecutionError(f"Workflow Execution 已存在: {document['id']}")
        with self._write_lock:
            self._atomic_write(target, document)

    def write_workflow(self, document: dict[str, Any]) -> None:
        target = (
            self.execution_root(document["workflow_id"], document["id"])
            / "workflow.json"
        )
        if not target.is_file():
            raise WorkflowExecutionError(f"Workflow Execution 不存在: {document['id']}")
        with self._write_lock:
            self._atomic_write(target, document)

    def write_node(self, document: dict[str, Any]) -> None:
        target = (
            self.execution_root(
                document["workflow_id"],
                document["workflow_execution_id"],
                create=True,
            )
            / "nodes"
            / f"{_uuid(document['node_execution_id'], 'node_execution_id')}.json"
        )
        with self._write_lock:
            self._atomic_write(target, document)

    def get_workflow(
        self, workflow_id: str, execution_id: str
    ) -> dict[str, Any] | None:
        path = self.execution_root(workflow_id, execution_id) / "workflow.json"
        return self._read(path) if path.is_file() else None

    def get_nodes(self, workflow_id: str, execution_id: str) -> list[dict[str, Any]]:
        directory = self.execution_root(workflow_id, execution_id) / "nodes"
        if not directory.is_dir():
            return []
        nodes = [self._read(path) for path in directory.glob("*.json")]
        return sorted(
            nodes,
            key=lambda item: (
                item.get("started_at") or "",
                item["node_execution_id"],
            ),
        )

    def list(self, workflow_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        root = self.workflow_root(workflow_id)
        if not root.is_dir():
            return []
        documents = []
        for path in root.glob("*/workflow.json"):
            try:
                documents.append(self._read(path))
            except (OSError, json.JSONDecodeError, WorkflowExecutionError):
                continue
        documents.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return documents[:limit]

    def delete_workflow_root(self, workflow_id: str) -> None:
        staged = self.stage_workflow_root_deletion(workflow_id)
        self.finalize_workflow_root_deletion(staged)

    def stage_workflow_root_deletion(self, workflow_id: str) -> Path | None:
        root = self.workflow_root(workflow_id)
        if not root.is_dir():
            return None
        staged = self.root / f".deleting-{_uuid(workflow_id, 'workflow_id')}-{uuid4()}"
        with self._write_lock:
            os.replace(root, staged)
        return staged

    def restore_workflow_root_deletion(
        self, workflow_id: str, staged: Path | None
    ) -> None:
        if staged is None or not staged.exists():
            return
        root = self.workflow_root(workflow_id)
        with self._write_lock:
            if root.exists():
                raise WorkflowExecutionError(
                    f"Workflow Execution 目录恢复冲突: {workflow_id}"
                )
            os.replace(staged, root)

    def finalize_workflow_root_deletion(self, staged: Path | None) -> None:
        if staged is not None and staged.is_dir():
            remove_execution_tree(staged)

    def recover_incomplete(self) -> int:
        recovered = 0
        for path in self.root.glob("*/*/workflow.json"):
            try:
                workflow = self._read(path)
            except (OSError, json.JSONDecodeError, WorkflowExecutionError):
                continue
            if workflow.get("status") not in {"PENDING", "RUNNING"}:
                continue
            now = utc_execution_time()
            for node_path in path.parent.joinpath("nodes").glob("*.json"):
                node = self._read(node_path)
                if node.get("status") in {"PENDING", "RUNNING"}:
                    node["status"] = "FAILED"
                    node["finished_at"] = local_execution_time()
                    node["error"] = execution_error(
                        "RUNTIME_LOST", "服务重启导致节点运行时丢失"
                    )
                    node.setdefault("transitions", []).append(
                        {"status": "FAILED", "at": now, "reason": "RUNTIME_LOST"}
                    )
                    self._atomic_write(node_path, node)
            workflow["status"] = "FAILED"
            workflow["finished_at"] = now
            workflow["error"] = execution_error(
                "PROCESS_RESTARTED", "服务重启，未完成执行不自动续跑"
            )
            self._atomic_write(path, workflow)
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
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise WorkflowExecutionError(f"Execution JSON 根必须是 object: {path}")
        return payload

    @staticmethod
    def _atomic_write(path: Path, document: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(
            strict_json_clone(document),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
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
            if temporary.exists():
                temporary.unlink()
