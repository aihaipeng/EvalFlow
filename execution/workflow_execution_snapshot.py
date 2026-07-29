"""Workflow structural snapshots used by manual and batch executions."""

from __future__ import annotations

from typing import Any

from execution.node_structural_models import NODE_STRUCTURAL_ADAPTER
from execution.workflow_execution_store import WorkflowExecutionError
from execution.workflow_structural_models import (
    WorkflowStructuralModel,
    WorkflowStructuralRecord,
    validate_workflow_graph,
)
from execution.workflow_values import strict_json_clone


def snapshot_record(record: WorkflowStructuralRecord) -> dict[str, Any]:
    bindings = {binding.node_id: binding for binding in record.workflow.nodes}
    return {
        "workflow": {
            "id": record.workflow.id,
            "name": record.workflow.name,
            "description": record.workflow.description,
        },
        "nodes": [
            {
                "node": node.model_dump(mode="json"),
                "position_x": bindings[node.id].position_x,
                "position_y": bindings[node.id].position_y,
            }
            for node in record.node_models
        ],
        "edges": [edge.model_dump(mode="json") for edge in record.workflow.edges],
    }


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise WorkflowExecutionError("批量变量不是严格 JSON 值")


def record_from_snapshot(
    snapshot: dict[str, Any], start_inputs: dict[str, Any]
) -> WorkflowStructuralRecord:
    """Rebuild a validated record and materialize one Case's injected Context."""

    try:
        document = strict_json_clone(snapshot)
        workflow_data = document["workflow"]
        node_items = document["nodes"]
        edges = document["edges"]
        if not isinstance(workflow_data, dict) or not isinstance(node_items, list):
            raise TypeError
        start_items = [item for item in node_items if item.get("node", {}).get("type") == "START"]
        if len(start_items) != 1:
            raise WorkflowExecutionError("批量 Workflow 快照必须恰好包含一个 START")
        inputs = start_items[0]["node"].setdefault("inputs", [])
        declared = {item["name"]: item for item in inputs}
        for name, value in start_inputs.items():
            materialized = strict_json_clone(value)
            if name in declared:
                declared[name]["type"] = _json_type(materialized)
                declared[name]["value"] = materialized
            else:
                inputs.append({"name": name, "type": _json_type(materialized), "value": materialized})

        nodes = [NODE_STRUCTURAL_ADAPTER.validate_python(item["node"]) for item in node_items]
        workflow = WorkflowStructuralModel.model_validate(
            {
                **workflow_data,
                "nodes": [
                    {
                        "node_id": item["node"]["id"],
                        "position_x": item["position_x"],
                        "position_y": item["position_y"],
                    }
                    for item in node_items
                ],
                "edges": edges,
            }
        )
    except WorkflowExecutionError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkflowExecutionError(f"批量 Workflow 快照无效: {exc}") from exc
    record = WorkflowStructuralRecord(
        workflow=workflow,
        node_models=nodes,
        created_at="snapshot",
        updated_at="snapshot",
    )
    validate_workflow_graph(record.workflow, record.node_models)
    return record
