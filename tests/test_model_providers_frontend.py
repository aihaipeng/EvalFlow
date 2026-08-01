from pathlib import Path

from fastapi.testclient import TestClient

from web.app import app


ROOT = Path(__file__).parents[1]
STATIC_DIR = ROOT / "web" / "static"
SOURCE = ROOT / "web" / "frontend" / "model-providers.jsx"


def test_model_provider_react_bundle_is_registered_and_served():
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    source = SOURCE.read_text(encoding="utf-8")

    assert 'data-view="models"' in index_html
    assert '<span>供应商管理</span>' in index_html
    assert '<link rel="stylesheet" href="/model-providers.css" />' in index_html
    assert '/assets/model-providers.js?v=' in index_html
    assert 'from "react"' in source
    assert 'from "@tanstack/react-query"' in source
    assert "QueryClientProvider" in source
    assert "useQuery" in source and "useMutation" in source
    for asset in ("/model-providers.css", "/assets/model-providers.js"):
        response = TestClient(app).get(asset)
        assert response.status_code == 200
        if asset.endswith(".css"):
            assert response.headers["cache-control"] == "no-cache, no-store, must-revalidate"
        else:
            assert response.headers["content-type"].startswith("text/javascript")


def test_model_provider_react_page_preserves_management_and_connection_contracts():
    source = SOURCE.read_text(encoding="utf-8")

    for endpoint in (
        'api.get("/api/model-providers")',
        'api.post("/api/model-providers",body)',
        'api.post("/api/model-providers/latency"',
        'api.post("/api/model-providers/models"',
        'api.post("/api/model-providers/test-model"',
    ):
        assert endpoint in source
    for field in (
        'id="btn-model-provider-add"',
        'id="model-provider-api-key"',
        'id="model-provider-base-url"',
        'id="model-provider-protocol"',
        'id="model-provider-proxy-mode"',
        'id="model-provider-verify-ssl"',
        'id="model-provider-add-model"',
        'id="model-provider-discovered"',
        'id="model-provider-manual"',
        'id="model-provider-save"',
    ):
        assert field in source
    for value in (
        "OpenAI Chat Completions",
        "OpenAI Responses API",
        "Anthropic Claude Messages",
        "SYSTEM",
        "DIRECT",
        "CUSTOM",
        "SSL Verify",
    ):
        assert value in source
    assert "verify_ssl: form.verify_ssl" in source
    assert "skip_ssl_verify" not in source
    assert "model_endpoint:endpoint" in source
    assert "model_configs:changed?{}" in source


def test_model_provider_config_dialog_keeps_keyboard_and_focus_contract():
    source = SOURCE.read_text(encoding="utf-8")

    assert 'role="dialog" aria-modal="true"' in source
    assert 'aria-labelledby="model-provider-config-title" tabIndex="-1"' in source
    assert 'event.key === "Escape"' in source
    assert 'event.key !== "Tab"' in source
    assert "returnFocus.current?.isConnected" in source
    assert 'id="model-config-default-body-beautify"' in source
    assert "默认 Body 不是合法 JSON" in source


def test_model_provider_styles_keep_existing_theme_and_desktop_contract():
    source = (STATIC_DIR / "model-providers.css").read_text(encoding="utf-8")

    for token in ("var(--surface)", "var(--surface-muted)", "var(--border)", "var(--text-main)"):
        assert token in source
    assert ':root[data-theme="dark"]' in source
    assert ".model-provider-workspace" in source
    assert "@media (max-width: 980px)" in source
    assert "@media (max-width: 680px)" in source
    assert ".model-provider-switch input:checked + .model-provider-switch-track" in source
    assert '.model-provider-status[data-state="success"]' in source
    assert '.model-provider-status[data-state="error"]' in source


def test_model_provider_list_uses_shared_management_visual_contract():
    source = SOURCE.read_text(encoding="utf-8")

    assert 'className="table execution-table management-list-table model-provider-table"' in source
    assert 'className="management-list-actions-head"' in source
    assert 'className="management-list-time"' in source
    assert 'id="model-provider-pagination"' in source
    assert "[10,20,50,100]" in source
    assert "window.ModelProviderManagement={mount,unmount}" in source
