"""Excel-to-START mapping and immutable Batch document creation."""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from execution.batch_execution_store import BatchExecutionError, BatchExecutionStore
from execution.workflow_execution_snapshot import record_from_snapshot, snapshot_record
from execution.workflow_execution_store import utc_execution_time
from execution.workflow_structural_models import WorkflowStructuralRepository
from execution.workflow_values import strict_json_clone
from storage.excel import ExcelSheetRepository, ExcelSheetSnapshot


_TARGET_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


def _case_id(value: Any, *, row_number: int) -> str:
    if value is None or isinstance(value, (dict, list, bool)):
        raise BatchExecutionError(f"Excel 第 {row_number} 行 case_id 必须是非空文本或数值")
    result = str(value).strip()
    if not result:
        raise BatchExecutionError(f"Excel 第 {row_number} 行 case_id 不能为空")
    return result


def _mapping_targets(
    snapshot: dict[str, Any], headers: tuple[str, ...], mappings: list[dict[str, str]]
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    starts = [item["node"] for item in snapshot["nodes"] if item["node"]["type"] == "START"]
    if len(starts) != 1:
        raise BatchExecutionError("批量 Workflow 必须恰好包含一个 START")
    defaults = {item["name"]: item["value"] for item in starts[0].get("inputs", [])}
    normalized = []
    sources: set[str] = set()
    targets: set[str] = set()
    for mapping in mappings:
        source = str(mapping.get("source", ""))
        target = str(mapping.get("target", ""))
        if source not in headers:
            raise BatchExecutionError(f"映射源列不存在: {source}")
        if not _TARGET_PATH.fullmatch(target):
            raise BatchExecutionError(f"映射目标路径无效: {target}")
        root = target.split(".", 1)[0]
        if root not in defaults:
            raise BatchExecutionError(f"映射目标未在 START 中声明: {root}")
        if source in sources:
            raise BatchExecutionError(f"Excel 列不能重复映射: {source}")
        if target in targets or any(
            target.startswith(existing + ".") or existing.startswith(target + ".")
            for existing in targets
        ):
            raise BatchExecutionError(f"映射目标冲突: {target}")
        sources.add(source)
        targets.add(target)
        normalized.append({"source": source, "target": target})
    if not normalized:
        raise BatchExecutionError("至少需要配置一个 Excel 字段映射")
    return normalized, strict_json_clone(defaults)


def _start_inputs(
    values: dict[str, Any], mappings: list[dict[str, str]], defaults: dict[str, Any]
) -> dict[str, Any]:
    roots = {mapping["target"].split(".", 1)[0] for mapping in mappings}
    result = {root: deepcopy(defaults[root]) for root in roots}
    for mapping in mappings:
        parts = mapping["target"].split(".")
        if len(parts) == 1:
            result[parts[0]] = strict_json_clone(values[mapping["source"]])
            continue
        current = result[parts[0]]
        if not isinstance(current, dict):
            raise BatchExecutionError(f"嵌套映射要求 START 变量为 object: {parts[0]}")
        for part in parts[1:-1]:
            child = current.get(part)
            if child is None:
                child = {}
                current[part] = child
            if not isinstance(child, dict):
                raise BatchExecutionError(f"映射路径经过的值不是 object: {mapping['target']}")
            current = child
        current[parts[-1]] = strict_json_clone(values[mapping["source"]])
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BatchInputService:
    """Freeze one Excel Sheet, its mapping, and the current Workflow structure."""

    def __init__(
        self,
        workflow_repository: WorkflowStructuralRepository,
        store: BatchExecutionStore,
    ):
        self.workflow_repository = workflow_repository
        self.store = store

    def preview(
        self,
        source_path: str | Path,
        sheet_name: str,
        header_mode: str = "AUTO",
    ) -> ExcelSheetSnapshot:
        return ExcelSheetRepository(source_path, sheet_name, header_mode).read_snapshot()

    def create(
        self,
        *,
        name: str,
        source_path: str | Path,
        sheet_name: str,
        workflow_id: str,
        case_id_column: str,
        mappings: list[dict[str, str]],
        case_concurrency: int,
        header_mode: str = "AUTO",
        evaluation_rules: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        source = Path(source_path).resolve()
        sheet = self.preview(source, sheet_name, header_mode)
        if case_id_column not in sheet.headers:
            raise BatchExecutionError(f"case_id 列不存在: {case_id_column}")
        if not sheet.rows:
            raise BatchExecutionError("Sheet 没有可执行数据行")
        if not 1 <= case_concurrency <= 32:
            raise BatchExecutionError("Case 并发数必须在 1 到 32 之间")
        record = self.workflow_repository.get(workflow_id)
        if record is None:
            raise BatchExecutionError(f"Workflow 不存在: {workflow_id}")
        workflow_snapshot = snapshot_record(record)
        normalized_mappings, defaults = _mapping_targets(
            workflow_snapshot, sheet.headers, mappings
        )
        batch_id = str(uuid4())
        created_at = utc_execution_time()
        cases = []
        rules = strict_json_clone(evaluation_rules or [])
        seen: set[str] = set()
        for row in sheet.rows:
            external_id = _case_id(row.values[case_id_column], row_number=row.row_number)
            if external_id in seen:
                raise BatchExecutionError(f"case_id 重复: {external_id}")
            seen.add(external_id)
            start_inputs = _start_inputs(row.values, normalized_mappings, defaults)
            record_from_snapshot(workflow_snapshot, start_inputs)
            cases.append(
                {
                    "id": str(uuid4()),
                    "batch_execution_id": batch_id,
                    "case_id": external_id,
                    "row_number": row.row_number,
                    "status": "QUEUED",
                    "execution_status": "NOT_STARTED",
                    "verdict": "NOT_EVALUATED",
                    "evaluation": {"verdict": "NOT_EVALUATED", "rules": []},
                    "source_values": strict_json_clone(row.values),
                    "start_inputs": start_inputs,
                    "workflow_execution_ids": [],
                    "created_at": created_at,
                    "started_at": None,
                    "finished_at": None,
                    "error": None,
                }
            )
        batch = {
            "id": batch_id,
            "name": name.strip() or f"{source.stem} / {record.workflow.name}",
            "status": "QUEUED",
            "input": {
                "filename": source.name,
                "sheet_name": sheet_name,
                "sha256": _sha256(source),
                "headers": list(sheet.headers),
                "case_id_column": case_id_column,
                "header_mode": sheet.header_mode,
            },
            "workflow": {
                "id": workflow_id,
                "name": record.workflow.name,
                "structural_snapshot": workflow_snapshot,
            },
            "mappings": normalized_mappings,
            "evaluation_rules": rules,
            "case_concurrency": case_concurrency,
            "total_cases": len(cases),
            "summary": {
                "queued": len(cases), "running": 0, "success": 0, "failed": 0,
                "interrupted": 0, "pass": 0, "fail": 0, "error": 0,
                "not_evaluated": len(cases),
            },
            "created_at": created_at,
            "started_at": None,
            "finished_at": None,
            "error": None,
        }
        self.store.create(
            batch,
            cases,
            source,
            {
                "headers": list(sheet.headers),
                "rows": [
                    {"row_number": row.row_number, "values": row.values} for row in sheet.rows
                ],
            },
        )
        return batch
