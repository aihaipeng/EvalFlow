from pathlib import Path

from sqlalchemy import insert

from execution.batch_execution_history import BatchExecutionHistoryRepository
from execution.database_schema import workflow_structural_models
from execution.init_db import database_transaction
from execution.workflow_structural_models import WorkflowStructuralRepository


def _workflow(database_path: Path, workflow_id: str = "11111111-1111-4111-8111-111111111111") -> WorkflowStructuralRepository:
    repository = WorkflowStructuralRepository(database_path)
    repository.initialize()
    with database_transaction(database_path) as connection:
        connection.execute(
            insert(workflow_structural_models).values(
                id=workflow_id,
                name="History Workflow",
                description="",
                created_at="2026-07-31T00:00:00Z",
                updated_at="2026-07-31T00:00:00Z",
            )
        )
    return repository


def _batch(index: int, workflow_id: str) -> dict:
    return {
        "id": "batch-1",
        "execution_round_id": f"round-{index}",
        "workflow": {"id": workflow_id, "name": "Workflow Snapshot"},
        "input": {"test_set_name": "Test Set Snapshot"},
        "total_cases": 20,
        "summary": {"success": index, "failed": 10 - index},
        "finished_at": f"2026-07-31T00:{index:02d}:30Z",
    }


def test_history_keeps_latest_ten_and_deletes_with_batch(tmp_path: Path):
    database_path = tmp_path / "database.sqlite3"
    workflow_id = "11111111-1111-4111-8111-111111111111"
    _workflow(database_path, workflow_id)
    repository = BatchExecutionHistoryRepository(database_path)

    for index in range(12):
        repository.record(
            _batch(index, workflow_id), started_at=f"2026-07-31T00:{index:02d}:00Z"
        )

    history = repository.list_recent("batch-1")
    assert len(history) == 10
    assert history[0]["execution_round_id"] == "round-11"
    assert history[-1]["execution_round_id"] == "round-2"
    assert history[0]["executed_cases"] == 11
    assert repository.delete_batch("batch-1") == 10
    assert repository.list_recent("batch-1") == []


def test_history_is_deleted_by_workflow_foreign_key(tmp_path: Path):
    database_path = tmp_path / "database.sqlite3"
    workflow_id = "11111111-1111-4111-8111-111111111111"
    workflow_repository = _workflow(database_path, workflow_id)
    repository = BatchExecutionHistoryRepository(database_path)
    repository.record(_batch(1, workflow_id), started_at="2026-07-31T00:01:00Z")

    assert workflow_repository.delete(workflow_id) is True
    assert repository.list_recent("batch-1") == []


def test_history_deduplicates_legacy_null_execution_round(tmp_path: Path):
    database_path = tmp_path / "legacy-null.sqlite3"
    workflow_id = "11111111-1111-4111-8111-111111111111"
    _workflow(database_path, workflow_id)
    repository = BatchExecutionHistoryRepository(database_path)
    batch = _batch(1, workflow_id)
    batch["execution_round_id"] = None

    first = repository.record(
        batch,
        started_at="2026-07-31T00:01:00Z",
        deduplicate=True,
    )
    second = repository.record(
        batch,
        started_at="2026-07-31T00:01:00Z",
        deduplicate=True,
    )

    assert second["id"] == first["id"]
    assert len(repository.list_recent("batch-1")) == 1
