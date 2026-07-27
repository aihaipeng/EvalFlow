import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from openpyxl import Workbook

from web import files as web_files
from web.app import create_app


def _excel(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Cases"
    sheet.append(["id", "question"])
    sheet.append(["C-1", "hello"])
    sheet.append(["C-2", "world"])
    workbook.save(path)
    workbook.close()


def _workflow_body() -> dict:
    start_id, script_id, end_id = (str(uuid4()) for _ in range(3))
    return {
        "name": "Batch API Workflow",
        "description": "",
        "nodes": [
            {
                "node": {
                    "id": start_id,
                    "type": "START",
                    "name": "START",
                    "description": "",
                    "inputs": [{"name": "input", "type": "object", "value": {}}],
                },
                "position_x": 0,
                "position_y": 0,
            },
            {
                "node": {
                    "id": script_id,
                    "type": "SCRIPT",
                    "name": "SCRIPT",
                    "description": "",
                    "script": 'result = context["input"]["question"].upper()',
                    "outputs": [{"name": "answer", "type": "string", "source": "result"}],
                },
                "position_x": 200,
                "position_y": 0,
            },
            {
                "node": {
                    "id": end_id,
                    "type": "END",
                    "name": "END",
                    "description": "",
                    "outputs": [{"name": "answer", "type": "string", "source": "answer"}],
                },
                "position_x": 400,
                "position_y": 0,
            },
        ],
        "edges": [
            {"id": str(uuid4()), "source_node_id": start_id, "target_node_id": script_id},
            {"id": str(uuid4()), "source_node_id": script_id, "target_node_id": end_id},
        ],
    }


def test_batch_api_previews_creates_starts_and_traces_cases(tmp_path, monkeypatch):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    _excel(inputs / "cases.xlsx")
    monkeypatch.setattr(web_files, "INPUTS_DIR", inputs)
    application = create_app(
        database_path=tmp_path / "database.sqlite3",
        execution_root=tmp_path / "workflow-executions",
    )
    with TestClient(application) as client:
        workflow_response = client.post("/api/workflows", json=_workflow_body())
        assert workflow_response.status_code == 201, workflow_response.text
        workflow_id = workflow_response.json()["workflow"]["workflow"]["id"]

        preview = client.post(
            "/api/batch-runs/preview",
            json={"filename": "cases.xlsx", "sheet_name": "Cases"},
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["headers"] == ["id", "question"]
        assert preview.json()["header_mode"] == "HEADER"
        assert preview.json()["total_rows"] == 2

        created = client.post(
            "/api/batch-runs",
            json={
                "name": "API Batch",
                "filename": "cases.xlsx",
                "sheet_name": "Cases",
                "workflow_id": workflow_id,
                "case_id_column": "id",
                "mappings": [{"source": "question", "target": "input.question"}],
                "case_concurrency": 2,
                "evaluation_rules": [
                    {
                        "name": "answer differs from source",
                        "actual_path": "answer",
                        "operator": "NE",
                        "expected": {"source": "EXCEL", "value": None, "column": "question"},
                    }
                ],
            },
        )
        assert created.status_code == 201, created.text
        batch_id = created.json()["batch"]["id"]
        assert created.json()["batch"]["status"] == "QUEUED"
        assert client.get("/api/batch-runs").json()["batches"][0]["workflow"] == {
            "id": workflow_id,
            "name": "Batch API Workflow",
        }

        started = client.post(f"/api/batch-runs/{batch_id}/start")
        assert started.status_code == 202, started.text
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            batch = client.get(f"/api/batch-runs/{batch_id}").json()["batch"]
            if batch["status"] == "SUCCESS":
                break
            time.sleep(0.03)
        assert batch["summary"]["success"] == 2
        assert batch["summary"]["pass"] == 2

        case_response = client.get(f"/api/batch-runs/{batch_id}/cases")
        assert case_response.status_code == 200
        cases = case_response.json()["cases"]
        assert [case["case_id"] for case in cases] == ["C-1", "C-2"]
        assert {case["status"] for case in cases} == {"SUCCESS"}
        assert {case["execution_status"] for case in cases} == {"SUCCESS"}
        assert {case["verdict"] for case in cases} == {"PASS"}
        assert all(case["evaluation"]["rules"][0]["expected_source"] == "EXCEL" for case in cases)
        assert all(len(case["workflow_execution_ids"]) == 1 for case in cases)

        blocked_delete = client.delete(f"/api/workflows/{workflow_id}")
        assert blocked_delete.status_code == 409
        deleted_batch = client.delete(f"/api/batch-runs/{batch_id}")
        assert deleted_batch.status_code == 200
        assert client.get(f"/api/batch-runs/{batch_id}").status_code == 404
        assert client.delete(f"/api/workflows/{workflow_id}").status_code == 200


def test_batch_api_rejects_path_traversal_and_unknown_mapping(tmp_path, monkeypatch):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    _excel(inputs / "cases.xlsx")
    monkeypatch.setattr(web_files, "INPUTS_DIR", inputs)
    application = create_app(
        database_path=tmp_path / "database.sqlite3",
        execution_root=tmp_path / "workflow-executions",
    )
    with TestClient(application) as client:
        traversal = client.post(
            "/api/batch-runs/preview",
            json={"filename": "../cases.xlsx", "sheet_name": "Cases"},
        )
        assert traversal.status_code == 400


def test_batch_edit_creates_new_run_with_latest_workflow_and_preserves_original(
    tmp_path, monkeypatch
):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    _excel(inputs / "cases.xlsx")
    monkeypatch.setattr(web_files, "INPUTS_DIR", inputs)
    application = create_app(
        database_path=tmp_path / "database.sqlite3",
        execution_root=tmp_path / "workflow-executions",
    )
    with TestClient(application) as client:
        workflow_body = _workflow_body()
        created_workflow = client.post("/api/workflows", json=workflow_body)
        assert created_workflow.status_code == 201
        workflow_id = created_workflow.json()["workflow"]["workflow"]["id"]
        batch_body = {
            "name": "Original Run",
            "filename": "cases.xlsx",
            "sheet_name": "Cases",
            "workflow_id": workflow_id,
            "case_id_column": "id",
            "mappings": [{"source": "question", "target": "input.question"}],
            "case_concurrency": 1,
        }
        original = client.post("/api/batch-runs", json=batch_body)
        assert original.status_code == 201
        original_id = original.json()["batch"]["id"]

        workflow_body["name"] = "Batch API Workflow v2"
        script = next(
            item["node"] for item in workflow_body["nodes"]
            if item["node"]["type"] == "SCRIPT"
        )
        script["script"] = 'result = "v2:" + context["input"]["question"]'
        updated_workflow = client.put(
            f"/api/workflows/{workflow_id}", json=workflow_body
        )
        assert updated_workflow.status_code == 200, updated_workflow.text

        edited = client.post(
            "/api/batch-runs",
            json={**batch_body, "name": "Edited Run", "case_concurrency": 2},
        )
        assert edited.status_code == 201, edited.text
        edited_batch = edited.json()["batch"]
        original_batch = client.get(f"/api/batch-runs/{original_id}").json()["batch"]

        assert edited_batch["id"] != original_id
        assert edited_batch["status"] == "QUEUED"
        assert edited_batch["case_concurrency"] == 2
        assert edited_batch["workflow"]["name"] == "Batch API Workflow v2"
        assert original_batch["workflow"]["name"] == "Batch API Workflow"
        original_script = next(
            item["node"] for item in original_batch["workflow"]["structural_snapshot"]["nodes"]
            if item["node"]["type"] == "SCRIPT"
        )
        edited_script = next(
            item["node"] for item in edited_batch["workflow"]["structural_snapshot"]["nodes"]
            if item["node"]["type"] == "SCRIPT"
        )
        assert original_script["script"].endswith(".upper()")
        assert edited_script["script"].startswith('result = "v2:"')
