import inspect
import sqlite3

import pytest
from pydantic import BaseModel

import execution.workflow_structural_models as workflow_module
from execution.node_structural_models import NODE_STRUCTURAL_ADAPTER
from execution.workflow_structural_models import (
    WORKFLOW_STRUCTURAL_COLUMN_DESCRIPTIONS,
    WORKFLOW_STRUCTURAL_TABLE_DESCRIPTIONS,
    WorkflowStructuralModel,
    WorkflowStructuralRepository,
    WorkflowStructuralRepositoryError,
    WorkflowNameConflictError,
)


WORKFLOW_ID = "123e4567-e89b-42d3-a456-426614174000"
OTHER_WORKFLOW_ID = "223e4567-e89b-42d3-a456-426614174000"
START_ID = "2f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44"
SCRIPT_ID = "550e8400-e29b-41d4-a716-446655440000"
END_ID = "8d9e6679-7425-40de-944b-e07fc1f90ae7"
EDGE_ONE_ID = "9d9e6679-7425-40de-944b-e07fc1f90ae7"
EDGE_TWO_ID = "ad9e6679-7425-40de-944b-e07fc1f90ae7"


def node_models(*, script_name="规则校验", output_name="result"):
    execution = {
        "timeout_seconds": 30,
        "max_attempts": 0,
        "retry_interval_seconds": 0,
        "delay_seconds": 0,
    }
    return [
        NODE_STRUCTURAL_ADAPTER.validate_python(
            {
                "id": START_ID,
                "type": "START",
                "name": "开始",
                "description": "",
                "inputs": [{"name": "question", "type": "string", "value": "请审核"}],
            }
        ),
        NODE_STRUCTURAL_ADAPTER.validate_python(
            {
                "id": SCRIPT_ID,
                "type": "SCRIPT",
                "name": script_name,
                "description": "",
                "script": "result = context['question']",
                "execution": execution,
                "outputs": [{"name": output_name, "type": "string", "source": "result"}],
            }
        ),
        NODE_STRUCTURAL_ADAPTER.validate_python(
            {"id": END_ID, "type": "END", "name": "结束", "description": ""}
        ),
    ]


def workflow_payload(*, workflow_id=WORKFLOW_ID, name="质量检测", nodes=None):
    nodes = nodes or node_models()
    return WorkflowStructuralModel(
        id=workflow_id,
        name=name,
        description="本机开发验证",
        nodes=[
            {"node_id": nodes[0].id, "position_x": 10, "position_y": 20},
            {"node_id": nodes[1].id, "position_x": 260, "position_y": 20},
            {"node_id": nodes[2].id, "position_x": 510, "position_y": 20},
        ],
        edges=[
            {"id": EDGE_ONE_ID, "source_node_id": nodes[0].id, "target_node_id": nodes[1].id},
            {"id": EDGE_TWO_ID, "source_node_id": nodes[1].id, "target_node_id": nodes[2].id},
        ],
    )


def test_every_workflow_class_and_field_has_documentation():
    classes = [
        cls
        for _, cls in inspect.getmembers(workflow_module, inspect.isclass)
        if cls.__module__ == workflow_module.__name__
    ]
    assert classes
    for cls in classes:
        assert inspect.getdoc(cls), f"{cls.__name__} 缺少类说明"
        if issubclass(cls, BaseModel):
            for field_name, field in cls.model_fields.items():
                assert field.description, f"{cls.__name__}.{field_name} 缺少字段说明"


def test_initialize_creates_only_structural_tables_with_documented_columns(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    repository = WorkflowStructuralRepository(database)
    repository.initialize()

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        tables = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        foreign_keys = connection.execute("PRAGMA foreign_key_list(workflow_edges)").fetchall()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        for table, descriptions in WORKFLOW_STRUCTURAL_COLUMN_DESCRIPTIONS.items():
            columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            assert columns == set(descriptions)

    assert set(WORKFLOW_STRUCTURAL_TABLE_DESCRIPTIONS) <= tables
    assert "node_structural_models" in tables
    assert not any("execution" in table or "log" in table for table in tables)
    assert foreign_keys
    assert integrity == "ok"


def test_repository_round_trips_complete_workflow_after_restart(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    nodes = node_models()
    workflow = workflow_payload(nodes=nodes)
    created = WorkflowStructuralRepository(database).create(
        workflow, nodes, timestamp="2026-07-26T10:00:00.000+00:00"
    )

    restored = WorkflowStructuralRepository(database).get(WORKFLOW_ID)

    assert created.workflow.name == "质量检测"
    assert restored is not None
    assert restored.workflow == workflow
    assert [node.type for node in restored.node_models] == ["START", "SCRIPT", "END"]
    assert restored.node_models[1].script == "result = context['question']"
    assert restored.created_at == "2026-07-26T10:00:00.000+00:00"
    assert restored.updated_at == "2026-07-26T10:00:00.000+00:00"


def test_update_atomically_replaces_nodes_edges_and_preserves_created_at(tmp_path):
    repository = WorkflowStructuralRepository(tmp_path / "workflow.sqlite3")
    nodes = node_models()
    repository.create(workflow_payload(nodes=nodes), nodes, timestamp="2026-07-26T10:00:00.000+00:00")
    updated_nodes = node_models(script_name="新规则")
    updated = workflow_payload(nodes=updated_nodes)
    updated.description = "已修改"

    saved = repository.update(updated, updated_nodes, timestamp="2026-07-26T11:00:00.000+00:00")

    assert saved.node_models[1].name == "新规则"
    assert saved.workflow.description == "已修改"
    assert saved.created_at == "2026-07-26T10:00:00.000+00:00"
    assert saved.updated_at == "2026-07-26T11:00:00.000+00:00"


def test_duplicate_name_update_rolls_back_all_node_and_workflow_changes(tmp_path):
    repository = WorkflowStructuralRepository(tmp_path / "workflow.sqlite3")
    first_nodes = node_models()
    repository.create(workflow_payload(nodes=first_nodes), first_nodes)

    second_nodes = node_models()
    id_map = {
        START_ID: "3f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44",
        SCRIPT_ID: "650e8400-e29b-41d4-a716-446655440000",
        END_ID: "9d9e6679-7425-40de-944b-e07fc1f90ae7",
    }
    second_payloads = []
    for node in second_nodes:
        payload = node.model_dump(mode="json")
        payload["id"] = id_map[node.id]
        second_payloads.append(NODE_STRUCTURAL_ADAPTER.validate_python(payload))
    second = workflow_payload(workflow_id=OTHER_WORKFLOW_ID, name="另一流程", nodes=second_payloads)
    second.edges[0].id = "bd9e6679-7425-40de-944b-e07fc1f90ae7"
    second.edges[1].id = "cd9e6679-7425-40de-944b-e07fc1f90ae7"
    repository.create(second, second_payloads)

    changed = workflow_payload(nodes=node_models(script_name="不应保存"), name="另一流程")
    with pytest.raises(
        WorkflowNameConflictError,
        match="Workflow 名称已存在，请使用其他名称",
    ):
        repository.update(changed, node_models(script_name="不应保存"))

    restored = repository.get(WORKFLOW_ID)
    assert restored.workflow.name == "质量检测"
    assert restored.node_models[1].name == "规则校验"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda workflow, nodes: (
                nodes.pop(),
                workflow.nodes.pop(),
                workflow.edges.pop(),
            ),
            "END",
        ),
        (lambda workflow, nodes: workflow.edges.clear(), "START"),
        (
            lambda workflow, nodes: workflow.edges.append(
                workflow.edges[0].model_copy(
                    update={
                        "id": "dd9e6679-7425-40de-944b-e07fc1f90ae7",
                        "source_node_id": SCRIPT_ID,
                        "target_node_id": START_ID,
                    }
                )
            ),
            "根节点|有向环",
        ),
        (
            lambda workflow, nodes: nodes[1].outputs.append(
                nodes[1].outputs[0].model_copy(update={"name": "question"})
            ),
            "Context 变量名",
        ),
    ],
)
def test_repository_rejects_invalid_graphs_without_writes(tmp_path, mutate, message):
    repository = WorkflowStructuralRepository(tmp_path / "workflow.sqlite3")
    nodes = node_models()
    workflow = workflow_payload(nodes=nodes)
    mutate(workflow, nodes)

    with pytest.raises(WorkflowStructuralRepositoryError, match=message):
        repository.create(workflow, nodes)

    assert repository.list() == []


def test_delete_cascades_workflow_nodes_bindings_and_edges(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    repository = WorkflowStructuralRepository(database)
    nodes = node_models()
    repository.create(workflow_payload(nodes=nodes), nodes)

    assert repository.delete(WORKFLOW_ID)
    assert not repository.delete(WORKFLOW_ID)
    with sqlite3.connect(database) as connection:
        counts = {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "workflow_structural_models",
                "workflow_node_bindings",
                "workflow_edges",
                "node_structural_models",
            )
        }
    assert counts == {table: 0 for table in counts}
