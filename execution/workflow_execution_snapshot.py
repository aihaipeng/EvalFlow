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


def record_from_snapshot(
    snapshot: dict[str, Any], start_inputs: dict[str, Any]
) -> WorkflowStructuralRecord:
    """Rebuild a validated record and apply one Case's START values."""

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
        declared = {item["name"] for item in start_items[0]["node"].get("inputs", [])}
        unknown = sorted(set(start_inputs) - declared)
        if unknown:
            raise WorkflowExecutionError(f"批量输入未在 START 中声明: {', '.join(unknown)}")
        for item in start_items[0]["node"].get("inputs", []):
            if item["name"] in start_inputs:
                item["value"] = strict_json_clone(start_inputs[item["name"]])

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
