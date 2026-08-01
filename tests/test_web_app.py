import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from execution import WorkflowExecutionError
from execution.node_structural_models import NODE_STRUCTURAL_ADAPTER
from web.app import app, create_app
from web.workflow_services import WorkflowServices, get_workflow_services


def test_sidebar_navigation_uses_keyboard_reachable_buttons():
    root = Path(__file__).resolve().parents[1]
    html = (root / "web" / "static" / "index.html").read_text(encoding="utf-8")
    javascript = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")
    styles = (root / "web" / "static" / "style.css").read_text(encoding="utf-8")

    assert html.count('<button type="button" class="sidebar-item') == 4
    assert 'aria-current="page"' in html
    assert "item.setAttribute('aria-current', 'page');" in javascript
    assert ".sidebar-item:focus-visible" in styles
    assert "@media (max-width: 1040px)" in styles
    assert ":root { --sidebar-w: 64px; }" in styles
    assert "height: 100dvh;" in styles
    assert "min-height: 720px;" not in styles


def test_large_feature_bundles_load_only_when_their_directory_is_opened():
    root = Path(__file__).resolve().parents[1]
    html = (root / "web" / "static" / "index.html").read_text(encoding="utf-8")
    javascript = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")
    test_sets = (root / "web" / "frontend" / "test-sets.jsx").read_text(encoding="utf-8")

    assert 'data-feature-css="/assets/test-sets.css?v=' in html
    assert 'data-feature-js="/assets/test-sets.js?v=' in html
    assert 'data-feature-css="/assets/workflow-canvas.css?v=' in html
    assert 'data-feature-js="/assets/workflow-canvas.js?v=' in html
    assert '<link rel="stylesheet" href="/assets/test-sets.css' not in html
    assert '<link rel="stylesheet" href="/assets/workflow-canvas.css' not in html
    assert '<script src="/assets/test-sets.js' not in html
    assert '<script src="/assets/workflow-canvas.js' not in html
    assert "function ensureFeatureAssets(view)" in javascript
    assert "loadFeatureStylesheet(view, stylesheet)" in javascript
    assert ".then(function () { return loadFeatureScript(view, script); })" in javascript
    assert "delete featureAssetLoads[view];" in javascript
    assert "viewWorkflowsWithAssets();" in javascript
    assert "document.querySelector('.sidebar-item.active" not in test_sets


def test_async_api_routes_are_limited_to_real_async_network_io():
    web_dir = Path(__file__).resolve().parents[1] / "web"
    async_routes: set[tuple[str, str]] = set()

    for route_path in web_dir.glob("routes_*.py"):
        tree = ast.parse(route_path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if not any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr in {"get", "post", "put", "delete", "patch"}
                for decorator in node.decorator_list
            ):
                continue
            async_routes.add((route_path.name, node.name))
            assert any(
                isinstance(child, (ast.Await, ast.AsyncWith))
                for child in ast.walk(node)
            )

    assert async_routes == {
        ("routes_model_providers.py", "fetch_models"),
        ("routes_model_providers.py", "test_latency"),
        ("routes_model_providers.py", "test_model_availability"),
    }


def test_index_serves_frontend():
    client = TestClient(app)
    response = client.get("/")
    favicon = client.get("/assets/favicon.png")
    styles = (Path(__file__).resolve().parents[1] / "web" / "static" / "style.css").read_text(encoding="utf-8")

    assert response.status_code == 200
    assert "EvalFlow" in response.text
    assert "Agent Bench" not in response.text
    assert 'class="sidebar-brand" aria-label="EvalFlow"' in response.text
    assert '<span class="sidebar-brand-eval">Eval</span><span class="sidebar-brand-flow">Flow</span>' in response.text
    assert "justify-content: center;\n    padding: 0 20px;" in styles
    assert "letter-spacing: 0;\n    text-align: center;" in styles
    assert '.sidebar-brand-wordmark {' in styles
    assert 'transform: skewX(-8deg);' in styles
    assert 'sidebar-brand-arrow' not in response.text
    assert '.sidebar-brand-arrow {' not in styles
    assert '<link rel="icon" type="image/png" sizes="100x100" href="/assets/favicon.png" />' in response.text
    assert favicon.status_code == 200
    assert favicon.headers["content-type"] == "image/png"
    assert favicon.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_global_toasts_stack_at_top_center_for_five_seconds():
    static_dir = Path(__file__).resolve().parents[1] / "web" / "static"
    index_html = (static_dir / "index.html").read_text(encoding="utf-8")
    app_js = (static_dir / "app.js").read_text(encoding="utf-8")
    styles = (static_dir / "style.css").read_text(encoding="utf-8")

    assert 'id="toast-container" class="toast-container"' in index_html
    assert 'id="toast"' not in index_html
    assert "var TOAST_DURATION_MS = 5000;" in app_js
    assert "container.appendChild(el);" in app_js
    assert "el.setAttribute('role', tone === 'error' ? 'alert' : 'status');" in app_js
    assert ".toast-container {" in styles
    assert "top: 24px;" in styles
    assert "left: 50%;" in styles
    assert "transform: translateX(-50%);" in styles
    assert "width: max-content;" in styles
    assert "align-items: center;" in styles
    assert "flex-direction: column;" in styles
    assert "z-index: 20000;" in styles
    toast_rule = styles[styles.index(".toast {"):]
    toast_rule = toast_rule[:toast_rule.index("}")]
    assert "width: fit-content;" in toast_rule
    assert "max-width: min(420px, calc(100vw - 48px));" in toast_rule
    assert "bottom:" not in toast_rule
    assert "pointer-events: auto;" not in toast_rule


def test_index_loads_new_workflow_structural_studio():
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert 'data-view="targets"' not in response.text
    assert 'data-view="workflows"' in response.text
    assert "/assets/workflow-canvas.js" in response.text
    assert "/assets/workflow-canvas.css" in response.text


def test_frontend_no_longer_exposes_target_management():
    static_dir = Path(__file__).resolve().parents[1] / "web" / "static"
    app_js = (static_dir / "app.js").read_text(encoding="utf-8")
    execution_js = (static_dir / "execution.js").read_text(encoding="utf-8")

    assert "viewTargets" not in app_js
    assert "viewTargets" not in execution_js
    assert "/api/targets" not in execution_js


def test_new_workflow_structural_route_is_registered_and_legacy_drafts_are_not(
    tmp_path,
):
    application = create_app(
        database_path=tmp_path / "agent-bench.sqlite3",
        execution_root=tmp_path / "workflow-executions",
    )
    with TestClient(application) as client:
        assert client.get("/api/workflows").status_code == 200
        assert client.get("/api/targets").status_code == 404
        assert client.get("/api/workflow-drafts").status_code == 404


def test_legacy_server_excel_routes_are_not_registered(tmp_path):
    application = create_app(
        database_path=tmp_path / "agent-bench.sqlite3",
        execution_root=tmp_path / "workflow-executions",
    )
    legacy_paths = {
        "/api/config/current",
        "/api/excel/refresh",
        "/api/excel/sets",
        "/api/excel/sets/{filename}",
        "/api/excel/sets/{filename}/meta",
        "/api/excel/sets/{filename}/open-dir",
        "/api/excel/sheets",
        "/api/excel/upload",
        "/api/testcases",
    }

    with TestClient(application) as client:
        paths = set(client.get("/openapi.json").json()["paths"])

    assert paths.isdisjoint(legacy_paths)


def test_workflow_services_follow_fastapi_lifespan(tmp_path):
    database = tmp_path / "agent-bench.sqlite3"
    application = create_app(
        database_path=database,
        execution_root=tmp_path / "workflow-executions",
    )

    assert not hasattr(application.state, "workflow_services")
    with TestClient(application):
        services = application.state.workflow_services
        assert services.database_path == database.resolve()
        assert database.is_file()
    assert not hasattr(application.state, "workflow_services")

    with pytest.raises(WorkflowExecutionError, match="Manager 已关闭"):
        services.manager.start(str(uuid4()))
    script = NODE_STRUCTURAL_ADAPTER.validate_python(
        {
            "id": str(uuid4()),
            "type": "SCRIPT",
            "name": "关闭验证",
            "description": "",
            "script": "result = None",
            "outputs": [],
        }
    )
    with pytest.raises(WorkflowExecutionError, match="Manager 已关闭"):
        services.node_test_manager.start(str(uuid4()), script, {})


def test_workflow_service_dependency_is_stable_per_app_and_isolated_between_apps(
    tmp_path,
):
    first_app = create_app(
        database_path=tmp_path / "first.sqlite3",
        execution_root=tmp_path / "first-executions",
    )
    second_app = create_app(
        database_path=tmp_path / "second.sqlite3",
        execution_root=tmp_path / "second-executions",
    )

    with TestClient(first_app), TestClient(second_app):
        request = SimpleNamespace(app=first_app)
        with ThreadPoolExecutor(max_workers=8) as pool:
            resolved = list(
                pool.map(lambda _index: get_workflow_services(request), range(32))
            )
        assert all(item is first_app.state.workflow_services for item in resolved)
        assert first_app.state.workflow_services is not second_app.state.workflow_services


def test_workflow_services_attempt_both_managers_when_shutdown_fails(
    tmp_path, monkeypatch
):
    services = WorkflowServices(
        tmp_path / "agent-bench.sqlite3",
        tmp_path / "workflow-executions",
    )
    attempted = []

    def fail_node_tests(*, wait_seconds):
        attempted.append(("node-tests", wait_seconds))
        raise RuntimeError("node shutdown failed")

    def close_workflows(*, wait_seconds):
        attempted.append(("workflows", wait_seconds))

    monkeypatch.setattr(services.node_test_manager, "shutdown", fail_node_tests)
    monkeypatch.setattr(services.manager, "shutdown", close_workflows)

    with pytest.raises(WorkflowExecutionError, match="node shutdown failed"):
        services.shutdown(wait_seconds=3)
    assert attempted == [("node-tests", 3), ("workflows", 3)]
