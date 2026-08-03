"""Database test-set mapping and immutable Batch document creation."""

from __future__ import annotations

import random
import re
from secrets import randbits
from typing import Any
from uuid import uuid4

from execution.batch_execution_store import BatchExecutionError, BatchExecutionStore
from execution.test_sets import TestSetRecord, TestSetRepository
from execution.workflow_execution_snapshot import record_from_snapshot, snapshot_record
from execution.workflow_execution_store import utc_execution_time
from execution.workflow_structural_models import (
    WorkflowStructuralRepository,
    WorkflowStructuralRepositoryError,
    validate_workflow_graph,
)
from execution.workflow_values import (
    WorkflowOutputTypeError,
    convert_output,
    strict_json_clone,
)


_CONTEXT_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_VARIABLE_TYPES = {"string", "number", "integer", "boolean", "object", "array", "null"}
_CALL_ORDERS = {"SEQUENTIAL", "REVERSE", "RANDOM"}


def _normalize_variables(
    columns: tuple[str, ...], variables: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Validate Run-owned variable mappings before freezing the Batch."""

    if not variables:
        raise BatchExecutionError("至少需要配置一个变量注入")
    normalized: list[dict[str, Any]] = []
    keys: set[str] = set()
    for index, variable in enumerate(variables, start=1):
        source = str(variable.get("source", "")).upper()
        key = str(variable.get("key", "")).strip()
        value = variable.get("value")
        value_type = str(variable.get("type", ""))
        if source not in {"CUSTOM", "TEST_SET"}:
            raise BatchExecutionError(
                f"变量 {index} 的 source 必须是 CUSTOM 或 TEST_SET"
            )
        if not _CONTEXT_KEY.fullmatch(key):
            raise BatchExecutionError(f"变量 {index} 的 key 格式无效")
        if key in keys:
            raise BatchExecutionError(f"变量 key 不能重复: {key}")
        if value_type not in _VARIABLE_TYPES:
            raise BatchExecutionError(f"变量 {index} 的 type 无效")
        if source == "TEST_SET":
            if not isinstance(value, str):
                raise BatchExecutionError(f"变量 {index} 的测试集字段不存在: {value}")
            value = value.strip()
            if value not in columns:
                raise BatchExecutionError(f"变量 {index} 的测试集字段不存在: {value}")
        else:
            if value_type == "null":
                value = "null"
            if not isinstance(value, str):
                raise BatchExecutionError(f"变量 {index} 的自定义 value 必须是文本")
            try:
                convert_output(value, value_type)
            except WorkflowOutputTypeError as exc:
                raise BatchExecutionError(
                    f"变量 {index} 的自定义 value 与 {value_type} 不匹配: {exc}"
                ) from exc
        keys.add(key)
        normalized.append(
            {"source": source, "key": key, "value": value, "type": value_type}
        )
    return normalized


def _start_inputs(
    values: dict[str, Any], variables: list[dict[str, Any]]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for variable in variables:
        raw_value = (
            values[variable["value"]]
            if variable["source"] == "TEST_SET"
            else variable["value"]
        )
        try:
            result[variable["key"]] = convert_output(raw_value, variable["type"])
        except WorkflowOutputTypeError as exc:
            label = "测试集字段" if variable["source"] == "TEST_SET" else "自定义 value"
            raise BatchExecutionError(
                f"变量 {variable['key']} 的{label}无法转换为 {variable['type']}: {exc}"
            ) from exc
    return strict_json_clone(result)


def _ordered_cases(
    record: TestSetRecord, call_order: str
) -> tuple[str, int | None, list[Any]]:
    normalized_order = str(call_order).upper()
    if normalized_order not in _CALL_ORDERS:
        raise BatchExecutionError("调用顺序必须是 SEQUENTIAL、REVERSE 或 RANDOM")
    cases = list(record.cases)
    random_seed = None
    if normalized_order == "REVERSE":
        cases.reverse()
    elif normalized_order == "RANDOM":
        random_seed = randbits(63)
        random.Random(random_seed).shuffle(cases)
    return normalized_order, random_seed, cases


def _test_set_snapshot(
    record: TestSetRecord,
    ordered_cases: list[Any],
    call_order: str,
    random_seed: int | None,
) -> dict[str, Any]:
    return {
        "id": record.id,
        "name": record.name,
        "description": record.description,
        "columns": [column.key for column in record.columns],
        "call_order": {"mode": call_order, "random_seed": random_seed},
        "cases": [
            {
                "id": case.id,
                "position": case.position,
                "call_number": call_number,
                "values": strict_json_clone(case.values),
            }
            for call_number, case in enumerate(ordered_cases, start=1)
        ],
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


class BatchInputService:
    """Own reusable Batch task configuration and prepare immutable execution rounds."""

    def __init__(
        self,
        workflow_repository: WorkflowStructuralRepository,
        test_set_repository: TestSetRepository,
        store: BatchExecutionStore,
    ):
        self.workflow_repository = workflow_repository
        self.test_set_repository = test_set_repository
        self.store = store

    def preview(self, test_set_id: str) -> TestSetRecord:
        record = self.test_set_repository.get(test_set_id)
        if record is None:
            raise BatchExecutionError(f"测试集不存在: {test_set_id}")
        return record

    def create(
        self,
        *,
        name: str,
        test_set_id: str,
        workflow_id: str,
        variables: list[dict[str, Any]],
        case_concurrency: int,
        failure_retry_count: int = 0,
        description: str = "",
        call_order: str = "SEQUENTIAL",
        evaluation_rules: list[dict[str, Any]] | None = None,
        case_display_column: str | None = None,
        rule_display_column: str | None = None,
    ) -> dict[str, Any]:
        batch_id = str(uuid4())
        created_at = utc_execution_time()
        configuration, prepared = self._prepare_configuration(
            name=name,
            description=description,
            test_set_id=test_set_id,
            workflow_id=workflow_id,
            variables=variables,
            case_concurrency=case_concurrency,
            failure_retry_count=failure_retry_count,
            call_order=call_order,
            evaluation_rules=evaluation_rules,
            case_display_column=case_display_column,
            rule_display_column=rule_display_column,
        )
        batch, cases, input_snapshot = self._execution_round(
            batch_id=batch_id,
            task_created_at=created_at,
            round_number=1,
            configuration=configuration,
            prepared=prepared,
        )
        self.store.create(batch, cases, input_snapshot)
        return batch

    def update(
        self,
        batch_id: str,
        **values: Any,
    ) -> dict[str, Any]:
        batch = self.store.get(batch_id)
        if batch is None:
            raise BatchExecutionError(f"任务不存在: {batch_id}")
        configuration, _prepared = self._prepare_configuration(**values)
        return self.store.write_configuration(
            batch_id,
            configuration,
            updated_at=utc_execution_time(),
        )

    def prepare_execution(self, batch_id: str) -> dict[str, Any]:
        batch = self.store.get(batch_id)
        if batch is None:
            raise BatchExecutionError(f"任务不存在: {batch_id}")
        if batch.get("status") in {"RUNNING", "STOPPING"}:
            raise BatchExecutionError("活动中的任务不能重复启动")
        batch = self.store.ensure_round_identity(batch)
        source = batch.get("configuration") or self._legacy_configuration(batch)
        configuration, prepared = self._prepare_configuration(**source)
        has_execution = self.store.has_execution(batch)
        round_number = int(batch.get("execution_round_number", 1)) + (
            1 if has_execution else 0
        )
        next_batch, cases, input_snapshot = self._execution_round(
            batch_id=batch_id,
            task_created_at=batch.get("created_at") or utc_execution_time(),
            round_number=round_number,
            configuration=configuration,
            prepared=prepared,
        )
        next_batch["updated_at"] = batch.get("updated_at") or next_batch["created_at"]
        self.store.replace_current(
            next_batch,
            cases,
            input_snapshot,
            archive_current=has_execution,
        )
        return next_batch

    def _prepare_configuration(
        self,
        *,
        name: str,
        test_set_id: str,
        workflow_id: str,
        variables: list[dict[str, Any]],
        case_concurrency: int,
        failure_retry_count: int = 0,
        description: str = "",
        call_order: str = "SEQUENTIAL",
        evaluation_rules: list[dict[str, Any]] | None = None,
        case_display_column: str | None = None,
        rule_display_column: str | None = None,
        **_ignored: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        test_set = self.preview(test_set_id)
        if not test_set.cases:
            raise BatchExecutionError("测试集没有可执行用例")
        if not 1 <= case_concurrency <= 32:
            raise BatchExecutionError("Case 并发数必须在 1 到 32 之间")
        if (
            not isinstance(failure_retry_count, int)
            or isinstance(failure_retry_count, bool)
            or not 0 <= failure_retry_count <= 10
        ):
            raise BatchExecutionError("失败重试次数必须在 0 到 10 之间")
        workflow_record = self.workflow_repository.get(workflow_id)
        if workflow_record is None:
            raise BatchExecutionError(f"工作流不存在: {workflow_id}")
        try:
            validate_workflow_graph(
                workflow_record.workflow,
                workflow_record.node_models,
            )
        except WorkflowStructuralRepositoryError as exc:
            raise BatchExecutionError(f"工作流尚未配置完整: {exc}") from exc
        columns = tuple(column.key for column in test_set.columns)
        display_columns = {
            "case": self._display_column(columns, case_display_column, "用例列"),
            "rule": self._display_column(
                columns, rule_display_column, "规则列", allow_empty=True
            ),
        }
        workflow_snapshot = snapshot_record(workflow_record)
        normalized_variables = _normalize_variables(columns, variables)
        normalized_call_order, random_seed, ordered_cases = _ordered_cases(
            test_set, call_order
        )
        rules = strict_json_clone(evaluation_rules or [])
        configuration = {
            "name": name.strip() or f"{test_set.name} / {workflow_record.workflow.name}",
            "description": description.strip(),
            "test_set_id": test_set.id,
            "test_set_name": test_set.name,
            "workflow_id": workflow_id,
            "workflow_name": workflow_record.workflow.name,
            "variables": normalized_variables,
            "evaluation_rules": rules,
            "case_concurrency": case_concurrency,
            "failure_retry_count": failure_retry_count,
            "call_order": normalized_call_order,
            "case_display_column": display_columns["case"],
            "rule_display_column": display_columns["rule"],
            "updated_at": utc_execution_time(),
        }
        return configuration, {
            "test_set": test_set,
            "workflow_snapshot": workflow_snapshot,
            "ordered_cases": ordered_cases,
            "random_seed": random_seed,
            "display_columns": display_columns,
            "columns": columns,
        }

    def _execution_round(
        self,
        *,
        batch_id: str,
        task_created_at: str,
        round_number: int,
        configuration: dict[str, Any],
        prepared: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        test_set = prepared["test_set"]
        workflow_snapshot = prepared["workflow_snapshot"]
        ordered_cases = prepared["ordered_cases"]
        random_seed = prepared["random_seed"]
        display_columns = prepared["display_columns"]
        columns = prepared["columns"]
        created_at = utc_execution_time()
        cases = []
        for call_number, test_case in enumerate(ordered_cases, start=1):
            start_inputs = _start_inputs(test_case.values, configuration["variables"])
            record_from_snapshot(workflow_snapshot, start_inputs)
            cases.append(
                {
                    "id": str(uuid4()),
                    "batch_execution_id": batch_id,
                    "case_id": test_case.id,
                    "row_number": test_case.position + 1,
                    "call_number": call_number,
                    "status": "QUEUED",
                    "execution_status": "NOT_STARTED",
                    "verdict": "NOT_EVALUATED",
                    "evaluation": {"verdict": "NOT_EVALUATED", "rules": []},
                    "source_values": strict_json_clone(test_case.values),
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
            "name": configuration["name"],
            "description": configuration["description"],
            "configuration": strict_json_clone(configuration),
            "execution_configuration": strict_json_clone(configuration),
            "execution_round_id": str(uuid4()),
            "execution_round_number": round_number,
            "status": "QUEUED",
            "input": {
                "test_set_id": test_set.id,
                "test_set_name": test_set.name,
                "columns": list(columns),
                "display_columns": display_columns,
                "updated_at": test_set.updated_at,
                "call_order": {
                    "mode": configuration["call_order"],
                    "random_seed": random_seed,
                },
            },
            "workflow": {
                "id": configuration["workflow_id"],
                "name": configuration["workflow_name"],
                "structural_snapshot": workflow_snapshot,
            },
            "variables": strict_json_clone(configuration["variables"]),
            "evaluation_rules": strict_json_clone(configuration["evaluation_rules"]),
            "case_concurrency": configuration["case_concurrency"],
            "failure_retry_count": configuration["failure_retry_count"],
            "total_cases": len(cases),
            "summary": {
                "queued": len(cases),
                "running": 0,
                "success": 0,
                "failed": 0,
                "interrupted": 0,
                "pass": 0,
                "fail": 0,
                "error": 0,
                "not_evaluated": len(cases),
            },
            "created_at": task_created_at,
            "execution_created_at": created_at,
            "updated_at": configuration["updated_at"],
            "started_at": None,
            "finished_at": None,
            "error": None,
        }
        return (
            batch,
            cases,
            _test_set_snapshot(
                test_set, ordered_cases, configuration["call_order"], random_seed
            ),
        )

    @staticmethod
    def _legacy_configuration(batch: dict[str, Any]) -> dict[str, Any]:
        display = batch.get("input", {}).get("display_columns", {})
        call_order = batch.get("input", {}).get("call_order", {})
        return {
            "name": batch.get("name", ""),
            "description": batch.get("description", ""),
            "test_set_id": batch["input"]["test_set_id"],
            "workflow_id": batch["workflow"]["id"],
            "variables": batch.get("variables", []),
            "case_concurrency": batch.get("case_concurrency", 1),
            "failure_retry_count": batch.get("failure_retry_count", 0),
            "call_order": call_order.get("mode", "SEQUENTIAL"),
            "evaluation_rules": batch.get("evaluation_rules", []),
            "case_display_column": display.get("case"),
            "rule_display_column": display.get("rule"),
        }

    @staticmethod
    def _display_column(
        columns: tuple[str, ...],
        value: str | None,
        label: str,
        *,
        allow_empty: bool = False,
    ) -> str | None:
        if value is None or (allow_empty and value == ""):
            return None if allow_empty else columns[0]
        if value not in columns:
            raise BatchExecutionError(f"{label}不存在于测试集字段中: {value}")
        return value
