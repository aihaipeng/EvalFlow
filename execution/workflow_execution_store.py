"""Shared execution values and atomic JSON persistence."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone
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

    def __init__(
        self,
        root: str | Path = DEFAULT_EXECUTION_ROOT,
        archive_root: str | Path | None = None,
    ):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.archive_root = (
            Path(archive_root).resolve()
            if archive_root is not None
            else self.root.parent / "workflow_archives"
        )
        self.archive_root.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self._archive_index: dict[str, dict[str, tuple[Path, str]]] = {}

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
        if path.is_file():
            return self._read(path)
        return self._read_archived_document(workflow_id, execution_id, "workflow.json")

    def get_nodes(self, workflow_id: str, execution_id: str) -> list[dict[str, Any]]:
        directory = self.execution_root(workflow_id, execution_id) / "nodes"
        if directory.is_dir():
            nodes = [self._read(path) for path in directory.glob("*.json")]
        else:
            nodes = self._read_archived_nodes(workflow_id, execution_id)
        return sorted(
            nodes,
            key=lambda item: (
                item.get("started_at") or "",
                item["node_execution_id"],
            ),
        )

    def list(self, workflow_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        root = self.workflow_root(workflow_id)
        candidates: dict[str, tuple[str, dict[str, Any] | None, Path | None]] = {}
        if root.is_dir():
            for path in root.glob("*/workflow.json"):
                try:
                    document = self._read(path)
                except (OSError, json.JSONDecodeError, WorkflowExecutionError):
                    continue
                candidates[document["id"]] = (
                    document.get("created_at") or "",
                    document,
                    None,
                )
        for execution_id, (archive_path, created_at) in self._archive_index_for(
            workflow_id
        ).items():
            candidates.setdefault(execution_id, (created_at, None, archive_path))
        ordered = sorted(candidates.items(), key=lambda item: item[1][0], reverse=True)
        documents = []
        for execution_id, (_created_at, document, archive_path) in ordered:
            if len(documents) >= limit:
                break
            if document is None and archive_path is not None:
                document = self._read_archive_document(
                    archive_path, execution_id, "workflow.json"
                )
            if document is not None:
                documents.append(document)
        return documents

    def archive_expired(
        self,
        *,
        retention_days: int | None = 7,
        retention_seconds: float | None = None,
        max_executions: int | None = None,
        now: datetime | None = None,
    ) -> int:
        """Archive expired terminal executions in grouped ZIP files.

        Archives are immutable batches. A manifest is published before the hot
        execution directories are removed, so an interrupted archival leaves
        the original execution readable and can be retried safely.
        """

        if retention_seconds is not None:
            if retention_seconds < 0:
                raise WorkflowExecutionError("retention_seconds 不能小于 0")
            retention = timedelta(seconds=retention_seconds)
        else:
            if retention_days is None or retention_days < 0:
                raise WorkflowExecutionError("retention_days 不能小于 0")
            retention = timedelta(days=retention_days)
        if max_executions is not None and max_executions <= 0:
            raise WorkflowExecutionError("max_executions 必须大于 0")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise WorkflowExecutionError("now 必须包含时区")
        cutoff = current.astimezone(timezone.utc) - retention
        candidates: list[tuple[datetime, datetime, Path, dict[str, Any]]] = []
        for path in self.root.glob("*/*/workflow.json"):
            try:
                document = self._read(path)
                created_at = self._parse_execution_time(document.get("created_at"))
                terminal_at = self._parse_execution_time(
                    document.get("finished_at") or document.get("created_at")
                )
            except (OSError, json.JSONDecodeError, WorkflowExecutionError):
                continue
            if (
                document.get("status") not in TERMINAL_WORKFLOW_STATUSES
                or terminal_at > cutoff
            ):
                continue
            candidates.append((terminal_at, created_at, path.parent, document))
        candidates.sort(key=lambda item: item[0])
        if max_executions is not None:
            candidates = candidates[:max_executions]
        groups: dict[tuple[str, str, str], list[tuple[Path, dict[str, Any]]]] = {}
        for _terminal_at, created_at, root, document in candidates:
            trigger = document.get("trigger") or {}
            batch_id = trigger.get("batch_execution_id") if trigger.get("type") == "BATCH" else None
            group = (
                _uuid(document["workflow_id"], "workflow_id"),
                created_at.date().isoformat(),
                _uuid(batch_id, "batch_execution_id") if batch_id else "manual",
            )
            groups.setdefault(group, []).append((root, document))
        archived = 0
        for (workflow_id, date, batch_id), executions in groups.items():
            archived += self._archive_group(workflow_id, date, batch_id, executions)
        return archived

    def recover_interrupted_archives(self) -> dict[str, int]:
        """Converge safe leftovers from an interrupted archive publication.

        This runs before the application accepts new executions. It only removes
        a hot execution after its manifest and archived workflow JSON validate.
        Unverifiable ZIP files stay on disk for manual inspection.
        """

        recovered = {"temporary_files": 0, "orphan_archives": 0, "hot_duplicates": 0}
        with self._write_lock:
            for root in (self.root, self.archive_root):
                for path in root.rglob(".*.tmp"):
                    if path.is_file():
                        path.unlink(missing_ok=True)
                        recovered["temporary_files"] += 1
            for path in self.root.glob(".deleting-*"):
                if path.is_dir():
                    remove_execution_tree(path)
                    recovered["temporary_files"] += 1

            manifests = list(self.archive_root.glob("**/manifest-*.json"))
            referenced_archives: set[Path] = set()
            valid_manifests: list[tuple[dict[str, Any], list[str]]] = []
            for path in manifests:
                try:
                    manifest = self._read(path)
                    archive_path = self._manifest_archive_path(path, manifest)
                    referenced_archives.add(archive_path)
                    execution_ids = self._validated_manifest_execution_ids(
                        archive_path, manifest
                    )
                except (KeyError, OSError, json.JSONDecodeError, WorkflowExecutionError, zipfile.BadZipFile):
                    continue
                valid_manifests.append((manifest, execution_ids))

            for path in self.archive_root.glob("**/executions-*.zip"):
                if path in referenced_archives:
                    continue
                try:
                    with zipfile.ZipFile(path) as archive:
                        execution_ids = {
                            name.split("/", maxsplit=1)[0]
                            for name in archive.namelist()
                            if name.endswith("/workflow.json")
                        }
                except zipfile.BadZipFile:
                    continue
                if execution_ids and all(
                    self.execution_root(path.parents[2].name, execution_id).is_dir()
                    for execution_id in execution_ids
                ):
                    path.unlink()
                    recovered["orphan_archives"] += 1

            for manifest, execution_ids in valid_manifests:
                workflow_id = manifest["workflow_id"]
                for execution_id in execution_ids:
                    root = self.execution_root(workflow_id, execution_id)
                    if root.is_dir():
                        remove_execution_tree(root)
                        recovered["hot_duplicates"] += 1
            self._archive_index.clear()
        return recovered

    def delete_workflow_root(self, workflow_id: str) -> None:
        staged = self.stage_workflow_root_deletion(workflow_id)
        self.finalize_workflow_root_deletion(staged)
        self.delete_archived_workflow(workflow_id)

    def delete_archived_workflow(self, workflow_id: str) -> None:
        workflow_id = _uuid(workflow_id, "workflow_id")
        root = self.archive_root / workflow_id
        if root.is_dir():
            with self._write_lock:
                remove_execution_tree(root)
                self._archive_index.pop(workflow_id, None)

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

    def _archive_group(
        self,
        workflow_id: str,
        date: str,
        batch_id: str,
        executions: list[tuple[Path, dict[str, Any]]],
    ) -> int:
        target = self.archive_root / workflow_id / f"date={date}" / f"batch={batch_id}"
        archive_id = uuid4().hex
        archive_name = f"executions-{archive_id}.zip"
        temporary = target / f".{archive_name}.tmp"
        archive_path = target / archive_name
        manifest_path = target / f"manifest-{archive_id}.json"
        target.mkdir(parents=True, exist_ok=True)
        with self._write_lock:
            try:
                with zipfile.ZipFile(
                    temporary,
                    mode="w",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=6,
                ) as archive:
                    for root, document in executions:
                        for source in root.rglob("*.json"):
                            archive.write(source, source.relative_to(root.parent).as_posix())
                os.replace(temporary, archive_path)
                manifest = {
                    "version": 2,
                    "archive": archive_name,
                    "workflow_id": workflow_id,
                    "date": date,
                    "batch_execution_id": None if batch_id == "manual" else batch_id,
                    "created_at": utc_execution_time(),
                    "executions": [
                        {
                            "id": document["id"],
                            "status": document.get("status"),
                            "created_at": document.get("created_at"),
                            "started_at": document.get("started_at"),
                            "finished_at": document.get("finished_at"),
                            "duration_ms": document.get("duration_ms"),
                        }
                        for _root, document in executions
                    ],
                }
                self._atomic_write(manifest_path, manifest)
                self._archive_index.pop(workflow_id, None)
                for root, _document in executions:
                    remove_execution_tree(root)
            finally:
                temporary.unlink(missing_ok=True)
        return len(executions)

    def _read_archived_document(
        self, workflow_id: str, execution_id: str, suffix: str
    ) -> dict[str, Any] | None:
        archive_path = self._archive_location(workflow_id, execution_id)
        if archive_path is None:
            return None
        return self._read_archive_document(archive_path, execution_id, suffix)

    @staticmethod
    def _read_archive_document(
        archive_path: Path, execution_id: str, suffix: str
    ) -> dict[str, Any] | None:
        name = f"{_uuid(execution_id, 'execution_id')}/{suffix}"
        try:
            with zipfile.ZipFile(archive_path) as archive:
                raw = archive.read(name).decode("utf-8")
        except KeyError:
            return None
        return WorkflowExecutionStore._parse_document(raw, archive_path / name)

    def _read_archived_nodes(
        self, workflow_id: str, execution_id: str
    ) -> list[dict[str, Any]]:
        archive_path = self._archive_location(workflow_id, execution_id)
        if archive_path is None:
            return []
        prefix = f"{_uuid(execution_id, 'execution_id')}/nodes/"
        with zipfile.ZipFile(archive_path) as archive:
            return [
                self._parse_document(archive.read(name).decode("utf-8"), archive_path / name)
                for name in archive.namelist()
                if name.startswith(prefix) and name.endswith(".json")
            ]

    def _archive_location(
        self, workflow_id: str, execution_id: str
    ) -> Path | None:
        execution_id = _uuid(execution_id, "execution_id")
        entry = self._archive_index_for(workflow_id).get(execution_id)
        return entry[0] if entry is not None else None

    def _archive_index_for(
        self, workflow_id: str
    ) -> dict[str, tuple[Path, str]]:
        workflow_id = _uuid(workflow_id, "workflow_id")
        with self._write_lock:
            cached = self._archive_index.get(workflow_id)
            if cached is not None:
                return cached
            root = self.archive_root / workflow_id
            index: dict[str, tuple[Path, str]] = {}
            if root.is_dir():
                for path in root.glob("**/manifest-*.json"):
                    try:
                        manifest = self._read(path)
                        archive_path = self._manifest_archive_path(path, manifest)
                        executions = manifest.get("executions")
                        if not isinstance(executions, list):
                            raise WorkflowExecutionError(
                                "归档 manifest 的 executions 非法"
                            )
                        for item in executions:
                            if not isinstance(item, dict):
                                continue
                            execution_id = _uuid(item["id"], "execution_id")
                            legacy_workflow = item.get("workflow")
                            created_at = item.get("created_at")
                            if not created_at and isinstance(legacy_workflow, dict):
                                created_at = legacy_workflow.get("created_at")
                            index[execution_id] = (archive_path, str(created_at or ""))
                    except (
                        KeyError,
                        OSError,
                        json.JSONDecodeError,
                        WorkflowExecutionError,
                    ):
                        continue
            self._archive_index[workflow_id] = index
            return index

    @staticmethod
    def _manifest_archive_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
        archive_name = manifest.get("archive")
        if not isinstance(archive_name, str) or Path(archive_name).name != archive_name:
            raise WorkflowExecutionError("归档 manifest 的 archive 非法")
        archive_path = manifest_path.parent / archive_name
        if not archive_path.is_file():
            raise WorkflowExecutionError("归档 manifest 指向的 ZIP 不存在")
        return archive_path

    @staticmethod
    def _validated_manifest_execution_ids(
        archive_path: Path, manifest: dict[str, Any]
    ) -> list[str]:
        workflow_id = _uuid(manifest["workflow_id"], "workflow_id")
        executions = manifest.get("executions")
        if not isinstance(executions, list):
            raise WorkflowExecutionError("归档 manifest 的 executions 非法")
        execution_ids = [_uuid(item["id"], "execution_id") for item in executions]
        with zipfile.ZipFile(archive_path) as archive:
            for execution_id in execution_ids:
                document = WorkflowExecutionStore._parse_document(
                    archive.read(f"{execution_id}/workflow.json").decode("utf-8"),
                    archive_path / execution_id / "workflow.json",
                )
                if (
                    document.get("id") != execution_id
                    or document.get("workflow_id") != workflow_id
                    or document.get("status") not in TERMINAL_WORKFLOW_STATUSES
                ):
                    raise WorkflowExecutionError("归档 ZIP 与 manifest 不一致")
        return execution_ids

    @staticmethod
    def _parse_execution_time(value: Any) -> datetime:
        if not isinstance(value, str):
            raise WorkflowExecutionError("Workflow Execution created_at 必须是 ISO-8601 字符串")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise WorkflowExecutionError("Workflow Execution created_at 非法") from exc
        if parsed.tzinfo is None:
            raise WorkflowExecutionError("Workflow Execution created_at 必须包含时区")
        return parsed.astimezone(timezone.utc)

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
        return WorkflowExecutionStore._parse_document(raw, path)

    @staticmethod
    def _parse_document(raw: str, path: Path) -> dict[str, Any]:
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
            separators=(",", ":"),
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


class WorkflowExecutionRetentionScheduler:
    """Run local execution archival periodically for one application lifespan."""

    def __init__(
        self,
        store: WorkflowExecutionStore,
        *,
        retention_seconds: float = 15 * 60,
        interval_seconds: float = 5 * 60,
        max_executions_per_pass: int = 100,
        retention_days: int | None = None,
    ) -> None:
        if retention_days is not None:
            if retention_days < 0:
                raise WorkflowExecutionError("retention_days 不能小于 0")
            retention_seconds = retention_days * 24 * 60 * 60
        if retention_seconds < 0:
            raise WorkflowExecutionError("retention_seconds 不能小于 0")
        if interval_seconds <= 0:
            raise WorkflowExecutionError("interval_seconds 必须大于 0")
        if max_executions_per_pass <= 0:
            raise WorkflowExecutionError("max_executions_per_pass 必须大于 0")
        self.store = store
        self.retention_seconds = retention_seconds
        self.interval_seconds = interval_seconds
        self.max_executions_per_pass = max_executions_per_pass
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.last_error: str | None = None
        self.last_recovery: dict[str, int] | None = None

    def start(self) -> int:
        with self._lock:
            if self._thread is not None:
                return 0
            self.last_recovery = self.store.recover_interrupted_archives()
            archived = self.run_once()
            self._thread = threading.Thread(
                target=self._run,
                daemon=True,
                name="workflow-execution-retention",
            )
            self._thread.start()
        return archived

    def run_once(self) -> int:
        archived = self.store.archive_expired(
            retention_days=None,
            retention_seconds=self.retention_seconds,
            max_executions=self.max_executions_per_pass,
        )
        self.last_error = None
        return archived

    def shutdown(self, *, wait_seconds: float = 10) -> None:
        self._stop_event.set()
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0, wait_seconds))
            if thread.is_alive():
                raise WorkflowExecutionError("Execution Retention Scheduler 未能及时终止")

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001 - retry on the next interval
                self.last_error = str(exc)
