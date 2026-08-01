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


def test_batch_store_keeps_case_cache_isolated_and_current(tmp_path: Path, monkeypatch) -> None:
    batch, case = _documents()
    store = BatchExecutionStore(tmp_path / "batch")
    store.create(batch, [case], {"columns": ["question"]})

    def unexpected_disk_read(_path):
        raise AssertionError("cached case listing should not read case files")

    monkeypatch.setattr(store, "_read", unexpected_disk_read)
    listed = store.list_cases(batch["id"])
    listed[0]["status"] = "MUTATED_BY_CALLER"
    assert store.list_cases(batch["id"])[0]["status"] == "QUEUED"

    case["status"] = "SUCCESS"
    store.write_case(case)
    assert store.list_cases(batch["id"])[0]["status"] == "SUCCESS"


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

    with pytest.raises(BatchExecutionError, match="活动中的 Batch"):
        store.delete(batch["id"])
    batch["status"] = "INTERRUPTED"
    store.write_batch(batch)
    assert store.delete(batch["id"])["id"] == batch["id"]
    assert store.get(batch["id"]) is None


def test_batch_store_recovers_stopping_batch_as_stopped(tmp_path: Path) -> None:
    batch, running = _documents()
    queued = {**running, "id": str(uuid4()), "case_id": "C-2", "row_number": 2}
    batch["status"] = "STOPPING"
    batch["execution_mode"] = "BATCH"
    running["status"] = "RUNNING"
    running["execution_status"] = "RUNNING"
    store = BatchExecutionStore(tmp_path / "batch")
    store.create(batch, [running, queued], {"columns": ["question"]})

    assert store.recover_incomplete() == 1

    recovered = store.get(batch["id"])
    cases = {item["case_id"]: item for item in store.list_cases(batch["id"])}
    assert recovered["status"] == "STOPPED"
    assert recovered["execution_mode"] is None
    assert recovered["summary"]["running"] == 0
    assert recovered["summary"]["interrupted"] == 1
    assert recovered["summary"]["queued"] == 1
    assert cases["C-1"]["status"] == "INTERRUPTED"
    assert cases["C-2"]["status"] == "QUEUED"


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


def test_batch_store_lazily_adds_round_identity_to_legacy_execution(tmp_path: Path) -> None:
    batch, case = _documents()
    batch.update(
        {
            "status": "SUCCESS",
            "started_at": "2026-07-27 08:00:00",
            "finished_at": "2026-07-27 08:01:00",
        }
    )
    store = BatchExecutionStore(tmp_path / "batch")
    store.create(batch, [case], {"columns": ["question"]})

    rounds = store.list_rounds(batch["id"])

    assert len(rounds) == 1
    assert rounds[0]["execution_round_number"] == 1
    assert rounds[0]["execution_round_id"]
    assert store.get(batch["id"])["execution_round_id"] == rounds[0]["execution_round_id"]


def test_batch_store_treats_individually_started_cases_as_a_round(tmp_path: Path) -> None:
    batch, case = _documents()
    case["status"] = "SUCCESS"
    case["workflow_execution_ids"] = [str(uuid4())]
    store = BatchExecutionStore(tmp_path / "batch")
    store.create(batch, [case], {"columns": ["question"]})

    rounds = store.list_rounds(batch["id"])

    assert len(rounds) == 1
    assert rounds[0]["execution_round_number"] == 1
    assert rounds[0]["execution_round_id"]


def test_batch_store_queries_only_requested_page_and_reuses_result_index(tmp_path: Path) -> None:
    batch, template = _documents()
    cases = []
    for index in range(30):
        verdict = "PASS" if index % 3 == 0 else "FAIL" if index % 3 == 1 else "ERROR"
        cases.append(
            {
                **template,
                "id": str(uuid4()),
                "case_id": f"C-{index + 1}",
                "row_number": index + 1,
                "call_number": index + 1,
                "status": "SUCCESS" if verdict == "PASS" else "FAILED",
                "execution_status": "SUCCESS" if verdict != "ERROR" else "FAILED",
                "evaluation": {"verdict": verdict},
                "source_values": {"question": f"question-{index + 1}"},
            }
        )
    store = BatchExecutionStore(tmp_path / "batch")
    store.create(batch, cases, {"columns": ["question"]})

    first = store.query_cases(batch["id"], page=1, page_size=4, result="Pass")
    directory = store.batch_root(batch["id"]) / "cases"
    first_index = store._case_query_cache[directory]
    second = store.query_cases(batch["id"], page=2, page_size=4, result="Pass")

    assert len(first["cases"]) == 4
    assert len(second["cases"]) == 4
    assert first["total"] == 10
    assert first["total_all"] == 30
    assert first["summary"] == {
        "Pass": 10,
        "Failed": 10,
        "Error": 10,
        "Running": 0,
        "Pending": 0,
    }
    assert store._case_query_cache[directory] is first_index

    updated = cases[0]
    updated["evaluation"] = {"verdict": "FAIL"}
    updated["status"] = "FAILED"
    store.write_case(updated)
    assert directory not in store._case_query_cache
    refreshed = store.query_cases(batch["id"], page=1, page_size=4, result="Pass")
    assert refreshed["total"] == 9


def test_batch_store_filters_running_and_pending_as_execution_states(tmp_path: Path) -> None:
    batch, running = _documents()
    running.update({"status": "RUNNING", "execution_status": "RUNNING"})
    pending = {
        **running,
        "id": str(uuid4()),
        "case_id": "C-2",
        "row_number": 2,
        "status": "QUEUED",
        "execution_status": "NOT_STARTED",
    }
    store = BatchExecutionStore(tmp_path / "batch")
    store.create(batch, [running, pending], {"columns": ["question"]})

    running_query = store.query_cases(
        batch["id"], page=1, page_size=10, state="Running"
    )
    pending_query = store.query_cases(
        batch["id"], page=1, page_size=10, state="Pending"
    )

    assert [case["case_id"] for case in running_query["cases"]] == ["C-1"]
    assert [case["case_id"] for case in pending_query["cases"]] == ["C-2"]
    assert running_query["summary"] == {
        "Pass": 0,
        "Failed": 0,
        "Error": 0,
        "Running": 1,
        "Pending": 1,
    }
