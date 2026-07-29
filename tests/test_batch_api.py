import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from web.app import create_app


def _workflow_body(name: str = "Batch API Workflow") -> dict:
    start_id, script_id, end_id = (str(uuid4()) for _ in range(3))
    return {
        "name": name, "description": "",
        "nodes": [
            {"node": {"id": start_id, "type": "START", "name": "START", "description": "", "inputs": [{"name": "input", "type": "object", "value": {}}]}, "position_x": 0, "position_y": 0},
            {"node": {"id": script_id, "type": "SCRIPT", "name": "SCRIPT", "description": "", "script": 'result = context["question"].upper()', "outputs": [{"name": "answer", "type": "string", "source": "result"}]}, "position_x": 200, "position_y": 0},
            {"node": {"id": end_id, "type": "END", "name": "END", "description": "", "outputs": [{"name": "answer", "type": "string", "source": "answer"}]}, "position_x": 400, "position_y": 0},
        ],
        "edges": [
            {"id": str(uuid4()), "source_node_id": start_id, "target_node_id": script_id},
            {"id": str(uuid4()), "source_node_id": script_id, "target_node_id": end_id},
        ],
    }


def _create_workflow(client: TestClient, body: dict | None = None) -> str:
    response = client.post("/api/workflows", json=body or _workflow_body())
    assert response.status_code == 201, response.text
    return response.json()["workflow"]["workflow"]["id"]


def _create_test_set(client: TestClient, name: str = "数据库测试集") -> str:
    response = client.post("/api/test-sets", json={
        "name": name, "description": "", "columns": ["question", "expected"],
        "cases": [
            {"id": "case-1", "values": {"question": "hello", "expected": "HELLO"}},
            {"id": "case-2", "values": {"question": "world", "expected": "WORLD"}},
        ],
    })
    assert response.status_code == 201, response.text
    return response.json()["test_set"]["id"]


def _batch_body(test_set_id: str, workflow_id: str, name: str = "API Run") -> dict:
    return {
        "name": name, "test_set_id": test_set_id, "workflow_id": workflow_id,
        "variables": [{"source": "TEST_SET", "key": "question", "value": "question", "type": "string"}],
        "case_concurrency": 2,
        "evaluation_rules": [],
    }


def test_batch_api_previews_database_set_creates_starts_and_traces_cases(tmp_path: Path):
    application = create_app(database_path=tmp_path / "database.sqlite3", execution_root=tmp_path / "workflow-executions")
    with TestClient(application) as client:
        workflow_id = _create_workflow(client)
        test_set_id = _create_test_set(client)

        preview = client.post("/api/batch-runs/preview", json={"test_set_id": test_set_id})
        assert preview.status_code == 200, preview.text
        assert preview.json()["test_set_id"] == test_set_id
        assert preview.json()["headers"] == ["question", "expected"]
        assert preview.json()["total_rows"] == 2
        assert "sheet_name" not in preview.json()
        assert "header_mode" not in preview.json()

        created = client.post("/api/batch-runs", json=_batch_body(test_set_id, workflow_id))
        assert created.status_code == 201, created.text
        batch = created.json()["batch"]
        batch_id = batch["id"]
        assert batch["input"]["test_set_id"] == test_set_id
        assert batch["input"]["test_set_name"] == "数据库测试集"
        assert "filename" not in batch["input"]
        assert "sheet_name" not in batch["input"]

        started = client.post(f"/api/batch-runs/{batch_id}/start")
        assert started.status_code == 202, started.text
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            batch = client.get(f"/api/batch-runs/{batch_id}").json()["batch"]
            if batch["status"] == "SUCCESS":
                break
            time.sleep(0.03)
        assert batch["summary"]["success"] == 2
        cases = client.get(f"/api/batch-runs/{batch_id}/cases").json()["cases"]
        assert [case["case_id"] for case in cases] == ["case-1", "case-2"]
        assert [case["row_number"] for case in cases] == [1, 2]
        assert all(len(case["workflow_execution_ids"]) == 1 for case in cases)

        assert client.delete(f"/api/batch-runs/{batch_id}").status_code == 200
        assert client.delete(f"/api/workflows/{workflow_id}").status_code == 200


def test_batch_api_rejects_legacy_excel_fields_and_unknown_test_set_mapping(tmp_path: Path):
    application = create_app(database_path=tmp_path / "database.sqlite3", execution_root=tmp_path / "workflow-executions")
    with TestClient(application) as client:
        workflow_id = _create_workflow(client)
        test_set_id = _create_test_set(client)
        legacy = client.post("/api/batch-runs/preview", json={"filename": "cases.xlsx", "sheet_name": "Cases"})
        assert legacy.status_code == 422
        invalid = client.post("/api/batch-runs", json={
            **_batch_body(test_set_id, workflow_id),
            "variables": [{"source": "TEST_SET", "key": "question", "value": "missing", "type": "string"}],
        })
        assert invalid.status_code == 400
        assert "测试集字段不存在" in invalid.text


def test_edit_run_uses_latest_test_set_and_workflow_but_preserves_original_snapshot(tmp_path: Path):
    application = create_app(database_path=tmp_path / "database.sqlite3", execution_root=tmp_path / "workflow-executions")
    with TestClient(application) as client:
        workflow_body = _workflow_body()
        workflow_id = _create_workflow(client, workflow_body)
        test_set_id = _create_test_set(client)
        original = client.post("/api/batch-runs", json=_batch_body(test_set_id, workflow_id, "Original Run"))
        assert original.status_code == 201, original.text
        original_id = original.json()["batch"]["id"]

        test_set = client.get(f"/api/test-sets/{test_set_id}").json()["test_set"]
        test_set["cases"][0]["values"]["question"] = "changed"
        updated_set = client.put(f"/api/test-sets/{test_set_id}", json={
            "name": "数据库测试集 v2", "description": "", "columns": test_set["columns"],
            "cases": [{"id": case["id"], "values": case["values"]} for case in test_set["cases"]],
        })
        assert updated_set.status_code == 200

        workflow_body["name"] = "Batch API Workflow v2"
        script = next(item["node"] for item in workflow_body["nodes"] if item["node"]["type"] == "SCRIPT")
        script["script"] = 'result = "v2:" + context["question"]'
        assert client.put(f"/api/workflows/{workflow_id}", json=workflow_body).status_code == 200

        edited = client.post("/api/batch-runs", json=_batch_body(test_set_id, workflow_id, "Edited Run"))
        assert edited.status_code == 201, edited.text
        edited_batch = edited.json()["batch"]
        original_batch = client.get(f"/api/batch-runs/{original_id}").json()["batch"]
        assert edited_batch["workflow"]["name"] == "Batch API Workflow v2"
        assert edited_batch["input"]["test_set_name"] == "数据库测试集 v2"
        assert original_batch["workflow"]["name"] == "Batch API Workflow"
        assert original_batch["input"]["test_set_name"] == "数据库测试集"
        original_case = client.get(f"/api/batch-runs/{original_id}/cases").json()["cases"][0]
        edited_case = client.get(f"/api/batch-runs/{edited_batch['id']}/cases").json()["cases"][0]
        assert original_case["source_values"]["question"] == "hello"
        assert edited_case["source_values"]["question"] == "changed"
