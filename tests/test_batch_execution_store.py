from pathlib import Path
from uuid import uuid4

import pytest

from execution.batch_execution_store import BatchExecutionError, BatchExecutionStore


def _documents():
    batch_id = str(uuid4())
    case_id = str(uuid4())
    batch = {
        "id": batch_id,
        "status": "QUEUED",
        "created_at": "2026-07-27T00:00:00.000Z",
        "finished_at": None,
        "error": None,
    }
    case = {
        "id": case_id,
        "batch_execution_id": batch_id,
        "case_id": "C-1",
        "row_number": 1,
        "status": "QUEUED",
        "finished_at": None,
        "error": None,
    }
    return batch, case


def test_batch_store_atomically_persists_database_snapshot_and_case_facts(tmp_path: Path) -> None:
    batch, case = _documents()
    store = BatchExecutionStore(tmp_path / "batch")
    snapshot = {"id": "set-1", "columns": ["question"], "cases": [{"id": "C-1", "values": {"question": "hello"}}]}

    store.create(batch, [case], snapshot)
    snapshot["cases"][0]["values"]["question"] = "changed"

    assert store.get(batch["id"]) == batch
    assert store.get_case(batch["id"], case["id"]) == case
    assert store.list_cases(batch["id"]) == [case]
    root = store.batch_root(batch["id"])
    assert not list((root / "input").glob("source.*"))
    assert BatchExecutionStore._read(root / "input" / "snapshot.json")["cases"][0]["values"]["question"] == "hello"


def test_batch_store_recovers_running_batch_without_starting_queued_cases(tmp_path: Path) -> None:
    batch, running = _documents()
    queued = {**running, "id": str(uuid4()), "case_id": "C-2", "row_number": 2}
    batch["status"] = "RUNNING"
    running["status"] = "RUNNING"
    store = BatchExecutionStore(tmp_path / "batch")
    store.create(batch, [running, queued], {"columns": ["question"]})

    assert store.recover_incomplete() == 1

    recovered = store.get(batch["id"])
    cases = {item["case_id"]: item for item in store.list_cases(batch["id"])}
    assert recovered["status"] == "INTERRUPTED"
    assert recovered["error"]["code"] == "PROCESS_RESTARTED"
    assert cases["C-1"]["status"] == "INTERRUPTED"
    assert cases["C-2"]["status"] == "QUEUED"


def test_batch_store_deletes_terminal_batch_but_rejects_running_batch(tmp_path: Path) -> None:
    batch, case = _documents()
    store = BatchExecutionStore(tmp_path / "batch")
    store.create(batch, [case], {"columns": ["question"]})
    batch["status"] = "RUNNING"
    store.write_batch(batch)

    with pytest.raises(BatchExecutionError, match="运行中的 Batch"):
        store.delete(batch["id"])
    batch["status"] = "INTERRUPTED"
    store.write_batch(batch)
    assert store.delete(batch["id"])["id"] == batch["id"]
    assert store.get(batch["id"]) is None


def test_batch_store_sorts_cases_by_frozen_call_number(tmp_path: Path) -> None:
    batch, first = _documents()
    first["call_number"] = 2
    second = {
        **first,
        "id": str(uuid4()),
        "case_id": "C-2",
        "row_number": 2,
        "call_number": 1,
    }
    store = BatchExecutionStore(tmp_path / "batch")
    store.create(batch, [first, second], {"columns": ["question"]})

    assert [case["case_id"] for case in store.list_cases(batch["id"])] == ["C-2", "C-1"]
