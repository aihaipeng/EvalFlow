"""Atomic JSON persistence for Batch and Case execution facts."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from copy import deepcopy
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
BATCH_TERMINAL_STATUSES = {
    "SUCCESS", "COMPLETED_WITH_ERRORS", "STOPPED", "INTERRUPTED",
}
CASE_TERMINAL_STATUSES = {"SUCCESS", "FAILED", "INTERRUPTED"}


def summarize_case_runs(cases: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "queued": 0, "running": 0, "success": 0, "failed": 0, "interrupted": 0,
        "pass": 0, "fail": 0, "error": 0, "not_evaluated": 0,
    }
    for case in cases:
        counts[case["status"].lower()] += 1
        counts[case.get("verdict", "NOT_EVALUATED").lower()] += 1
    return counts


def batch_case_result(case: dict[str, Any]) -> str | None:
    if (
        case.get("status") in {"QUEUED", "RUNNING", "INTERRUPTED"}
        or case.get("execution_status") in {"NOT_STARTED", "RUNNING", "INTERRUPTED"}
    ):
        return None
    evaluation = case.get("evaluation") if isinstance(case.get("evaluation"), dict) else {}
    if case.get("execution_status") == "SUCCESS" and evaluation.get("verdict") == "FAIL":
        return "Failed"
    if case.get("execution_status") == "SUCCESS" and evaluation.get("verdict") == "ERROR":
        return "Error"
    if case.get("execution_status") == "SUCCESS":
        return "Pass"
    return "Error"


def batch_case_execution_state(case: dict[str, Any]) -> str | None:
    if case.get("status") == "RUNNING" or case.get("execution_status") == "RUNNING":
        return "Running"
    if case.get("status") == "QUEUED" or case.get("execution_status") == "NOT_STARTED":
        return "Pending"
    return None


def batch_case_search_text(case: dict[str, Any]) -> str:
    values = case.get("source_values") if isinstance(case.get("source_values"), dict) else {}
    return " ".join(
        str(value)
        for value in (
            case.get("case_id"),
            case.get("row_number"),
            *values.keys(),
            *values.values(),
        )
        if value is not None
    ).lower()


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
        self._case_cache: dict[Path, dict[str, dict[str, Any]]] = {}
        self._case_query_cache: dict[Path, dict[str, Any]] = {}

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
                case_directory = target / "cases"
                self._case_cache[case_directory] = {
                    case["id"]: deepcopy(case) for case in cases
                }
                self._case_query_cache.pop(case_directory, None)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def write_batch(self, batch: dict[str, Any]) -> None:
        target = self.batch_root(batch["id"]) / "batch.json"
        if not target.is_file():
            raise BatchExecutionError(f"Batch Execution 不存在: {batch['id']}")
        with self._write_lock:
            self._atomic_write(target, batch)

    def replace_current(
        self,
        batch: dict[str, Any],
        cases: list[dict[str, Any]],
        input_snapshot: dict[str, Any],
        *,
        archive_current: bool,
    ) -> None:
        root = self.batch_root(batch["id"])
        if not (root / "batch.json").is_file():
            raise BatchExecutionError(f"任务不存在: {batch['id']}")
        staging = root / f".p-{uuid4().hex[:8]}"
        try:
            (staging / "cases").mkdir(parents=True)
            (staging / "input").mkdir()
            self._atomic_write(staging / "input" / "snapshot.json", input_snapshot)
            for case in cases:
                self._atomic_write(
                    staging / "cases" / f"{_uuid(case['id'], 'case_run_id')}.json",
                    case,
                )
            with self._write_lock:
                if archive_current:
                    self._archive_current(root)
                previous_cases = root / f".pc-{uuid4().hex[:8]}"
                previous_input = root / f".pi-{uuid4().hex[:8]}"
                os.replace(root / "cases", previous_cases)
                os.replace(root / "input", previous_input)
                try:
                    os.replace(staging / "cases", root / "cases")
                    os.replace(staging / "input", root / "input")
                    self._atomic_write(root / "batch.json", batch)
                    case_directory = root / "cases"
                    self._case_cache[case_directory] = {
                        case["id"]: deepcopy(case) for case in cases
                    }
                    self._case_query_cache.pop(case_directory, None)
                except Exception:
                    remove_execution_tree(root / "cases")
                    remove_execution_tree(root / "input")
                    os.replace(previous_cases, root / "cases")
                    os.replace(previous_input, root / "input")
                    raise
                finally:
                    remove_execution_tree(previous_cases)
                    remove_execution_tree(previous_input)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def _archive_current(self, root: Path) -> None:
        current = self._read(root / "batch.json")
        round_id = _uuid(current.get("execution_round_id"), "execution_round_id")
        target = root / "rounds" / round_id
        if target.exists():
            raise BatchExecutionError(f"执行轮次已归档: {round_id}")
        temporary = root / "rounds" / f".a-{uuid4().hex[:8]}"
        try:
            (temporary / "cases").mkdir(parents=True)
            (temporary / "input").mkdir()
            self._atomic_write(temporary / "batch.json", current)
            snapshot = root / "input" / "snapshot.json"
            if snapshot.is_file():
                self._atomic_write(
                    temporary / "input" / "snapshot.json", self._read(snapshot)
                )
            for case in self.list_cases(current["id"]):
                self._atomic_write(
                    temporary / "cases" / f"{_uuid(case['id'], 'case_run_id')}.json",
                    case,
                )
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

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
            cached = self._case_cache.get(target.parent)
            if cached is not None:
                cached[case["id"]] = deepcopy(case)
            self._case_query_cache.pop(target.parent, None)

    def get(self, batch_id: str) -> dict[str, Any] | None:
        path = self.batch_root(batch_id) / "batch.json"
        return self._read(path) if path.is_file() else None

    def ensure_round_identity(self, batch: dict[str, Any]) -> dict[str, Any]:
        if not self.has_execution(batch) or batch.get("execution_round_id"):
            return batch
        batch["execution_round_id"] = str(uuid4())
        batch["execution_round_number"] = int(
            batch.get("execution_round_number", 1)
        )
        self.write_batch(batch)
        return batch

    def has_execution(self, batch: dict[str, Any]) -> bool:
        if batch.get("started_at") is not None:
            return True
        return any(
            case.get("workflow_execution_ids")
            or case.get("status") not in {None, "QUEUED"}
            for case in self.list_cases(batch["id"])
        )

    def get_case(
        self, batch_id: str, case_run_id: str, round_id: str | None = None
    ) -> dict[str, Any] | None:
        directory = self._round_root(batch_id, round_id) / "cases"
        normalized_id = _uuid(case_run_id, "case_run_id")
        with self._write_lock:
            cached = self._case_cache.get(directory)
            if cached is not None and normalized_id in cached:
                return deepcopy(cached[normalized_id])
        path = directory / f"{normalized_id}.json"
        return self._read(path) if path.is_file() else None

    def get_round(self, batch_id: str, round_id: str | None = None) -> dict[str, Any] | None:
        if round_id is None:
            return self.get(batch_id)
        current = self.get(batch_id)
        if current and current.get("execution_round_id") == round_id:
            return current
        path = self.batch_root(batch_id) / "rounds" / _uuid(round_id, "round_id") / "batch.json"
        return self._read(path) if path.is_file() else None

    def list_rounds(self, batch_id: str) -> list[dict[str, Any]]:
        current = self.get(batch_id)
        if current is None:
            raise BatchExecutionError(f"任务不存在: {batch_id}")
        current = self.ensure_round_identity(current)
        rounds = []
        if self.has_execution(current):
            rounds.append(current)
        directory = self.batch_root(batch_id) / "rounds"
        if directory.is_dir():
            for path in directory.glob("*/batch.json"):
                try:
                    rounds.append(self._read(path))
                except (OSError, json.JSONDecodeError, BatchExecutionError):
                    continue
        return sorted(
            rounds,
            key=lambda item: int(item.get("execution_round_number", 0)),
            reverse=True,
        )

    def list(self) -> list[dict[str, Any]]:
        documents = []
        for path in self.root.glob("*/batch.json"):
            try:
                documents.append(self._read(path))
            except (OSError, json.JSONDecodeError, BatchExecutionError):
                continue
        return sorted(documents, key=lambda item: item.get("created_at") or "", reverse=True)

    def list_cases(
        self, batch_id: str, round_id: str | None = None
    ) -> list[dict[str, Any]]:
        directory = self._round_root(batch_id, round_id) / "cases"
        with self._write_lock:
            cached = self._cached_cases(directory)
            index = self._case_query_index(directory, cached)
            return [deepcopy(cached[case_id]) for case_id in index["ordered_ids"]]

    def query_cases(
        self,
        batch_id: str,
        round_id: str | None = None,
        *,
        page: int,
        page_size: int,
        result: str | None = None,
        state: str | None = None,
        search: str = "",
    ) -> dict[str, Any]:
        directory = self._round_root(batch_id, round_id) / "cases"
        with self._write_lock:
            cached = self._cached_cases(directory)
            index = self._case_query_index(directory, cached)
            if state is not None:
                candidate_ids = index["state_ids"].get(state, ())
            elif result is not None:
                candidate_ids = index["result_ids"].get(result, ())
            else:
                candidate_ids = index["ordered_ids"]
            normalized_search = search.strip().lower()
            if normalized_search:
                candidate_ids = [
                    case_id
                    for case_id in candidate_ids
                    if normalized_search in index["search_texts"][case_id]
                ]
            total = len(candidate_ids)
            start = (page - 1) * page_size
            page_ids = candidate_ids[start : start + page_size]
            cases = [deepcopy(cached[case_id]) for case_id in page_ids]
            return {
                "cases": cases,
                "total": total,
                "total_all": len(index["ordered_ids"]),
                "summary": dict(index["summary"]),
            }

    def _cached_cases(self, directory: Path) -> dict[str, dict[str, Any]]:
        if not directory.is_dir():
            return {}
        cached = self._case_cache.get(directory)
        if cached is None:
            cached = {
                case["id"]: case
                for case in (self._read(path) for path in directory.glob("*.json"))
            }
            self._case_cache[directory] = cached
        return cached

    def _case_query_index(
        self, directory: Path, cached: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        index = self._case_query_cache.get(directory)
        if index is not None:
            return index
        ordered_ids = tuple(
            case["id"]
            for case in sorted(
                cached.values(),
                key=lambda item: (
                    item.get("call_number", item["row_number"]),
                    item["id"],
                ),
            )
        )
        result_ids = {name: [] for name in ("Pass", "Failed", "Error")}
        state_ids = {name: [] for name in ("Running", "Pending")}
        search_texts = {}
        for case_id in ordered_ids:
            case = cached[case_id]
            case_result = batch_case_result(case)
            if case_result is not None:
                result_ids[case_result].append(case_id)
            execution_state = batch_case_execution_state(case)
            if execution_state is not None:
                state_ids[execution_state].append(case_id)
            search_texts[case_id] = batch_case_search_text(case)
        index = {
            "ordered_ids": ordered_ids,
            "result_ids": {key: tuple(value) for key, value in result_ids.items()},
            "state_ids": {key: tuple(value) for key, value in state_ids.items()},
            "summary": {
                **{key: len(value) for key, value in result_ids.items()},
                **{key: len(value) for key, value in state_ids.items()},
            },
            "search_texts": search_texts,
        }
        self._case_query_cache[directory] = index
        return index

    def _round_root(self, batch_id: str, round_id: str | None) -> Path:
        root = self.batch_root(batch_id)
        if round_id is None:
            return root
        current = self.get(batch_id)
        if current and current.get("execution_round_id") == round_id:
            return root
        return root / "rounds" / _uuid(round_id, "round_id")

    def delete(self, batch_id: str) -> dict[str, Any]:
        batch = self.get(batch_id)
        if batch is None:
            raise BatchExecutionError(f"Batch Execution 不存在: {batch_id}")
        if batch.get("status") in {"RUNNING", "STOPPING"}:
            raise BatchExecutionError("活动中的 Batch 不能删除，请先停止并等待用例结束")
        root = self.batch_root(batch_id)
        with self._write_lock:
            remove_execution_tree(root)
            self._case_cache = {
                directory: cases
                for directory, cases in self._case_cache.items()
                if root not in directory.parents and directory != root
            }
            self._case_query_cache = {
                directory: index
                for directory, index in self._case_query_cache.items()
                if root not in directory.parents and directory != root
            }
        return batch

    def recover_incomplete(self) -> int:
        recovered = 0
        for batch in self.list():
            if batch.get("status") not in {"RUNNING", "STOPPING"}:
                continue
            was_stopping = batch.get("status") == "STOPPING"
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
                    "status": "STOPPED" if was_stopping else "INTERRUPTED",
                    "execution_mode": None,
                    "summary": summarize_case_runs(self.list_cases(batch["id"])),
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
