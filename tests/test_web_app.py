from fastapi.testclient import TestClient

from web.app import app


def test_index_serves_frontend():
    client = TestClient(app)
    response = client.get("/")
    favicon = client.get("/assets/favicon.png")

    assert response.status_code == 200
    assert "Agent Bench" in response.text
    assert '<link rel="icon" type="image/png" sizes="100x100" href="/assets/favicon.png" />' in response.text
    assert favicon.status_code == 200
    assert favicon.headers["content-type"] == "image/png"
    assert favicon.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_index_loads_new_workflow_structural_studio():
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert 'data-view="workflows"' in response.text
    assert "/assets/workflow-canvas.js" in response.text
    assert "/assets/workflow-canvas.css" in response.text


def test_new_workflow_structural_route_is_registered_and_legacy_drafts_are_not():
    client = TestClient(app)

    assert client.get("/api/workflows").status_code == 200
    assert client.get("/api/workflow-drafts").status_code == 404


def test_testcases_rejects_path_traversal_filename():
    response = TestClient(app).get(
        "/api/testcases",
        params={"filename": "../config", "sheet": "Sheet1"},
    )

    assert response.status_code == 400
