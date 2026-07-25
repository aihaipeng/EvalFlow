import pytest

from execution.workflows import (
    NodeRunRecord,
    RuntimeErrorRecord,
    WorkflowRecord,
    WorkflowRepository,
    WorkflowRepositoryError,
    WorkflowRunRecord,
)


WORKFLOW_ID = "123e4567-e89b-42d3-a456-426614174000"
START_ID = "2f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44"
SCRIPT_ID = "550e8400-e29b-41d4-a716-446655440000"
END_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"


def workflow_payload() -> dict:
    return {
        "workflow_id": WORKFLOW_ID,
        "name": "Repository test",
        "description": "",
        "nodes": [
            {"id": START_ID, "type": "START", "name": "Start", "description": "", "inputs": []},
            {
                "id": SCRIPT_ID,
                "type": "SCRIPT",
                "name": "Script",
                "description": "",
                "script": "set_val('result', 'ok')",
                "execution": {"timeout_ms": 1000, "max_attempts": 0, "delay_ms": 0},
                "outputs": [{"name": "result", "type": "string"}],
            },
            {"id": END_ID, "type": "END", "name": "End", "description": ""},
        ],
        "edges": [
            {"edge_id": "4c1f2e3d-6b7a-48c9-9d01-23456789abcd", "source": START_ID, "target": SCRIPT_ID},
            {"edge_id": "5d2e3f4a-7b8c-49d0-a123-456789abcdef", "source": SCRIPT_ID, "target": END_ID},
        ],
    }


def test_repository_retains_new_workflow_and_terminal_node_run_after_restart(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    repository = WorkflowRepository(database)
    workflow = repository.create_workflow(WorkflowRecord.model_validate(workflow_payload()))
    workflow_run = repository.create_workflow_run(
        WorkflowRunRecord(
            run_id="6ba7b810-9dad-41d1-80b4-00c04fd430c8",
            workflow_id=workflow.workflow_id,
        )
    )
    node_run = repository.create_node_run(
        NodeRunRecord(
            node_run_id="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            run_id=workflow_run.run_id,
            node_id=SCRIPT_ID,
            type="SCRIPT",
        )
    )
    completed = NodeRunRecord.model_validate(
        {
            **node_run.model_dump(mode="json"),
            "status": "SUCCESS",
            "started_at": "2026-07-25 10:00:00",
            "finished_at": "2026-07-25 10:00:01",
            "duration_ms": 1000,
            "attempt_count": 1,
            "outputs": {"result": "ok"},
        }
    )
    repository.update_node_run(completed)

    restarted = WorkflowRepository(database)
    restored = restarted.get_workflow(WORKFLOW_ID)
    runs = restarted.list_node_runs(workflow_run.run_id)

    assert restored is not None
    assert restored.nodes[1].script == "set_val('result', 'ok')"
    assert runs[0].status == "SUCCESS"
    assert runs[0].outputs == {"result": "ok"}
    assert runs[0].request is None


def test_repository_rejects_delete_when_run_history_exists(tmp_path):
    repository = WorkflowRepository(tmp_path / "workflow.sqlite3")
    workflow = repository.create_workflow(WorkflowRecord.model_validate(workflow_payload()))
    repository.create_workflow_run(
        WorkflowRunRecord(
            run_id="6ba7b810-9dad-41d1-80b4-00c04fd430c8",
            workflow_id=workflow.workflow_id,
        )
    )

    with pytest.raises(WorkflowRepositoryError, match="run history"):
        repository.delete_workflow(workflow.workflow_id)


def test_repository_persists_workflow_run_failure_error(tmp_path):
    repository = WorkflowRepository(tmp_path / "workflow.sqlite3")
    workflow = repository.create_workflow(WorkflowRecord.model_validate(workflow_payload()))
    record = WorkflowRunRecord(
        run_id="6ba7b810-9dad-41d1-80b4-00c04fd430c8",
        workflow_id=workflow.workflow_id,
    )
    repository.create_workflow_run(record)
    failed = WorkflowRunRecord(
        run_id=record.run_id,
        workflow_id=record.workflow_id,
        status="FAILED",
        started_at="2026-07-25 10:00:00",
        finished_at="2026-07-25 10:00:01",
        duration_ms=1000,
        error=RuntimeErrorRecord(code="CONTEXT_VARIABLE_NOT_FOUND", message="missing result"),
    )
    repository.update_workflow_run(failed)

    restored = repository.get_workflow_run(record.run_id)

    assert restored is not None
    assert restored.status == "FAILED"
    assert restored.error.code == "CONTEXT_VARIABLE_NOT_FOUND"


def test_repository_rejects_run_for_unknown_workflow(tmp_path):
    repository = WorkflowRepository(tmp_path / "workflow.sqlite3")

    with pytest.raises(WorkflowRepositoryError):
        repository.create_workflow_run(
            WorkflowRunRecord(
                run_id="6ba7b810-9dad-41d1-80b4-00c04fd430c8",
                workflow_id=WORKFLOW_ID,
            )
        )


def test_repository_recovers_incomplete_run_after_process_restart(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    repository = WorkflowRepository(database)
    workflow = repository.create_workflow(WorkflowRecord.model_validate(workflow_payload()))
    run = repository.create_workflow_run(
        WorkflowRunRecord(
            run_id="6ba7b810-9dad-41d1-80b4-00c04fd430c8",
            workflow_id=workflow.workflow_id,
        )
    )
    repository.create_node_run(
        NodeRunRecord(
            node_run_id="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            run_id=run.run_id,
            node_id=SCRIPT_ID,
            type="SCRIPT",
        )
    )

    restarted = WorkflowRepository(database)
    restored_run = restarted.get_workflow_run(run.run_id)
    restored_node = restarted.list_node_runs(run.run_id)[0]

    assert restored_run.status == "FAILED"
    assert restored_run.error.code == "WORKFLOW_PROCESS_RESTARTED"
    assert restored_node.status == "CANCELLED"
    assert restored_node.error.code == "NODE_CANCELLED_BY_FAIL_FAST"
