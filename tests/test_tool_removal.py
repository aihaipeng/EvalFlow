from pathlib import Path

from fastapi.testclient import TestClient

from web.app import app


ROOT = Path(__file__).parents[1]


def test_tool_template_page_assets_and_api_are_removed():
    index_html = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
    client = TestClient(app)

    assert 'data-view="tools"' not in index_html
    assert "/tool-templates.js" not in index_html
    assert "viewToolTemplates" not in app_js
    assert client.get("/tool-templates.js").status_code == 404
    assert client.get("/api/tool-templates").status_code == 404


def test_template_repository_and_migration_files_are_absent():
    removed_paths = [
        "tool_registry",
        "web/tool_templates.py",
        "web/tool_template_archives.py",
        "web/routes_tool_templates.py",
        "web/tool_execution.py",
        "scripts/migrate_tool_registry.py",
    ]

    for relative_path in removed_paths:
        assert not (ROOT / relative_path).exists()


def test_generic_workflow_execution_kernel_remains_available():
    assert (ROOT / "execution" / "tool_runtime.py").is_file()
    assert (ROOT / "execution" / "tool_worker.py").is_file()
    assert (ROOT / "web" / "tool_runtime.py").is_file()
    assert (ROOT / "web" / "tool_worker.py").is_file()
    assert (ROOT / "web" / "run_stream.py").is_file()
