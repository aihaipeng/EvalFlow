from pathlib import Path
from uuid import uuid4

from execution.batch_execution_store import BatchExecutionStore


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
        "row_number": 2,
        "status": "QUEUED",
        "finished_at": None,
        "error": None,
    }
    return batch, case


def test_batch_store_atomically_persists_input_and_case_facts(tmp_path: Path) -> None:
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"original excel bytes")
    batch, case = _documents()
    store = BatchExecutionStore(tmp_path / "batch")

    store.create(batch, [case], source, {"headers": ["case_id"]})
    source.write_bytes(b"changed")

    assert store.get(batch["id"]) == batch
    assert store.get_case(batch["id"], case["id"]) == case
    assert store.list_cases(batch["id"]) == [case]
    root = store.batch_root(batch["id"])
    assert (root / "input" / "source.xlsx").read_bytes() == b"original excel bytes"
    assert BatchExecutionStore._read(root / "input" / "snapshot.json") == {
        "headers": ["case_id"]
    }


def test_batch_store_recovers_running_batch_without_starting_queued_cases(tmp_path: Path) -> None:
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"excel")
    batch, running = _documents()
    queued = {**running, "id": str(uuid4()), "case_id": "C-2", "row_number": 3}
    batch["status"] = "RUNNING"
    running["status"] = "RUNNING"
    store = BatchExecutionStore(tmp_path / "batch")
    store.create(batch, [running, queued], source, {"headers": ["case_id"]})

    assert store.recover_incomplete() == 1

    recovered = store.get(batch["id"])
    cases = {item["case_id"]: item for item in store.list_cases(batch["id"])}
    assert recovered["status"] == "INTERRUPTED"
    assert recovered["error"]["code"] == "PROCESS_RESTARTED"
    assert cases["C-1"]["status"] == "INTERRUPTED"
    assert cases["C-2"]["status"] == "QUEUED"


def test_batch_store_deletes_terminal_batch_but_rejects_running_batch(tmp_path: Path) -> None:
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"excel")
    batch, case = _documents()
    store = BatchExecutionStore(tmp_path / "batch")
    store.create(batch, [case], source, {"headers": ["case_id"]})
    batch["status"] = "RUNNING"
    store.write_batch(batch)

    import pytest
    from execution.batch_execution_store import BatchExecutionError

    with pytest.raises(BatchExecutionError, match="运行中的 Batch"):
        store.delete(batch["id"])
    batch["status"] = "INTERRUPTED"
    store.write_batch(batch)
    assert store.delete(batch["id"])["id"] == batch["id"]
    assert store.get(batch["id"]) is None
