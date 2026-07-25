from fastapi.testclient import TestClient
import time

from execution.workflows import WorkflowRepository, WorkflowRunRecord
from web import routes_workflows
from web.app import app


WORKFLOW_ID = "123e4567-e89b-42d3-a456-426614174000"
START_ID = "2f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44"
SCRIPT_ID = "550e8400-e29b-41d4-a716-446655440000"
END_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"


def workflow_payload(name="API test") -> dict:
    return {
        "workflow_id": WORKFLOW_ID,
        "name": name,
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


def patch_database(tmp_path, monkeypatch):
    database = tmp_path / "workflow.sqlite3"
    monkeypatch.setattr(routes_workflows, "DATABASE_PATH", database)
    monkeypatch.setattr(routes_workflows, "_repository_instance", None)
    monkeypatch.setattr(routes_workflows, "_repository_path", None)
    return database


def test_workflow_api_crud_uses_new_contract(tmp_path, monkeypatch):
    patch_database(tmp_path, monkeypatch)
    client = TestClient(app)

    created = client.post("/api/workflows", json=workflow_payload())

    assert created.status_code == 200
    assert created.json()["workflow"]["workflow_id"] == WORKFLOW_ID
    assert client.get("/api/workflows").json()["workflows"][0]["name"] == "API test"
    updated = client.put(f"/api/workflows/{WORKFLOW_ID}", json=workflow_payload("Updated"))
    assert updated.status_code == 200
    assert updated.json()["workflow"]["name"] == "Updated"
    assert client.delete(f"/api/workflows/{WORKFLOW_ID}").status_code == 204
    assert client.get(f"/api/workflows/{WORKFLOW_ID}").status_code == 404


def test_workflow_api_rejects_path_and_body_id_mismatch(tmp_path, monkeypatch):
    patch_database(tmp_path, monkeypatch)
    client = TestClient(app)
    assert client.post("/api/workflows", json=workflow_payload()).status_code == 200
    body = workflow_payload()
    body["workflow_id"] = "6ba7b810-9dad-41d1-80b4-00c04fd430c8"

    response = client.put(f"/api/workflows/{WORKFLOW_ID}", json=body)

    assert response.status_code == 422


def test_workflow_api_blocks_delete_after_run_and_lists_runs(tmp_path, monkeypatch):
    database = patch_database(tmp_path, monkeypatch)
    client = TestClient(app)
    assert client.post("/api/workflows", json=workflow_payload()).status_code == 200
    repository = WorkflowRepository(database)
    repository.create_workflow_run(
        WorkflowRunRecord(
            run_id="6ba7b810-9dad-41d1-80b4-00c04fd430c8",
            workflow_id=WORKFLOW_ID,
        )
    )

    assert client.get(f"/api/workflows/{WORKFLOW_ID}/runs").json()["runs"][0]["run_id"] == "6ba7b810-9dad-41d1-80b4-00c04fd430c8"
    assert client.delete(f"/api/workflows/{WORKFLOW_ID}").status_code == 409


def test_workflow_run_api_executes_multi_node_workflow_to_terminal_state(tmp_path, monkeypatch):
    patch_database(tmp_path, monkeypatch)
    routes_workflows._active_runs.clear()
    routes_workflows._active_workflow_runs.clear()
    with TestClient(app) as client:
        assert client.post("/api/workflows", json=workflow_payload()).status_code == 200
        started = client.post(f"/api/workflows/{WORKFLOW_ID}/runs")
        assert started.status_code == 202
        run_id = started.json()["run"]["run_id"]
        run = None
        for _ in range(100):
            run = client.get(f"/api/workflows/{WORKFLOW_ID}/runs/{run_id}").json()["run"]
            if run["status"] in {"SUCCESS", "FAILED", "CANCELLED"}:
                break
            time.sleep(0.01)
        assert run["status"] == "SUCCESS"
        node_runs = client.get(f"/api/workflows/{WORKFLOW_ID}/runs/{run_id}/nodes").json()["runs"]
        assert [item["type"] for item in node_runs] == ["START", "SCRIPT"]
        assert node_runs[-1]["outputs"] == {"result": "ok"}
