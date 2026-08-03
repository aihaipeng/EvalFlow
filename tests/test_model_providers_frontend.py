from pathlib import Path

from fastapi.testclient import TestClient

from web.app import app


ROOT = Path(__file__).parents[1]
STATIC_DIR = ROOT / "web" / "static"
SOURCE = ROOT / "web" / "frontend" / "model-providers.jsx"
API_SOURCE = ROOT / "web" / "frontend" / "model-provider-api.ts"
DIALOG_SOURCE = ROOT / "web" / "frontend" / "components" / "dialog.jsx"


def test_model_provider_react_bundle_is_registered_and_served():
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    source = SOURCE.read_text(encoding="utf-8")
    rendered = TestClient(app).get("/").text

    assert 'data-view="models"' in index_html
    assert '<span>供应商管理</span>' in index_html
    assert '<link rel="stylesheet" href="/model-providers.css" />' in index_html
    assert 'data-feature-js="__VITE_MODEL_PROVIDERS_JS__"' in index_html
    assert "/assets/vite/model-providers-" in rendered
    assert 'from "react"' in source
    assert 'from "@tanstack/react-query"' in source
    assert "QueryClientProvider" in source
    assert "useQuery" in source and "useMutation" in source
    response = TestClient(app).get("/model-providers.css")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, no-store, must-revalidate"


def test_model_provider_react_page_preserves_management_and_connection_contracts():
    source = SOURCE.read_text(encoding="utf-8")
    api = API_SOURCE.read_text(encoding="utf-8")

    for endpoint in (
        'http.GET("/api/model-providers")',
        'http.POST("/api/model-providers", { body })',
        'http.POST("/api/model-providers/latency"',
        'http.POST("/api/model-providers/models"',
        'http.POST("/api/model-providers/test-model"',
    ):
        assert endpoint in api
    assert 'from "openapi-fetch"' in api
    assert 'import type { components, paths } from "./generated/openapi"' in api
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
        'value="SYSTEM"',
        'value="DIRECT"',
        'value="CUSTOM"',
        "SSL 证书校验",
    ):
        assert value in source
    assert "verify_ssl: form.verify_ssl" in source
    assert "skip_ssl_verify" not in source
    assert "model_endpoint: endpoint" in source
    assert "model_configs: changed ? {}" in source
    assert 'className="model-provider-validation-heading"' in source
    assert '<span>推理端点</span>' not in source
    assert '{endpoint(form.protocol, form.base_url) || "请填写接口地址"}' in source
    assert "凭证与网络设置" not in source
    assert 'role="table"' in source
    assert 'role="columnheader"' in source
    assert 'label: "Unknown"' in source
    assert 'label: "Active"' in source
    assert 'label: "Inactive"' in source
    assert 'className="model-provider-model-state-label"' in source
    assert "disabled={isTesting}" in source
    assert "aria-busy={isTesting}" in source
    assert 'className="model-provider-test-spinner"' in source


def test_model_provider_places_protocol_before_api_key_and_aligns_model_columns():
    source = SOURCE.read_text(encoding="utf-8")
    styles = (STATIC_DIR / "model-providers.css").read_text(encoding="utf-8")

    protocol = source.index('id="model-provider-protocol"')
    base_url = source.index('id="model-provider-base-url"')
    api_key = source.index('id="model-provider-api-key"')
    proxy = source.index('id="model-provider-proxy-mode"')
    assert protocol < base_url < api_key < proxy
    assert "--model-provider-model-columns:" in styles
    assert ".model-provider-selected-head > span:first-child" in styles
    assert "padding-left: 38px;" in styles
    assert ".model-provider-selected-head > span:nth-child(2) { text-align: center; }" in styles
    assert ".model-provider-selected-head > span:nth-child(3)" in styles
    assert "padding-left: 13px;" in styles
    assert ".model-provider-selected-head > span:last-child { text-align: center; }" in styles
    assert ".model-provider-model-protocol" in styles
    assert "text-align: center;" in styles
    assert ".model-provider-model-actions {" in styles
    assert "justify-content: center;" in styles
    assert "grid-template-columns: minmax(140px, 1fr) max-content;" in styles


def test_model_provider_config_dialog_keeps_keyboard_and_focus_contract():
    source = SOURCE.read_text(encoding="utf-8")
    dialog = DIALOG_SOURCE.read_text(encoding="utf-8")

    assert 'import { ConfirmDialog, ModalDialog } from "./components/dialog"' in source
    assert "<ModalDialog" in source
    assert "<ConfirmDialog" in source
    assert 'from "@radix-ui/react-dialog"' in dialog
    assert 'from "@radix-ui/react-alert-dialog"' in dialog
    assert 'event.key === "Escape"' not in source
    assert 'event.key !== "Tab"' not in source
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
    status_cards = source[source.index("/* Connection verification follows"):source.index("/* Supplier workspace")]
    assert "min-height: 76px;" in status_cards
    assert "background: var(--surface);" in status_cards
    assert "border: 1px solid var(--border);" in status_cards
    assert "color: var(--text-main);" in status_cards
    assert "background: #171e28;" not in status_cards
    assert "0 0 16px" not in status_cards


def test_model_provider_list_uses_shared_management_visual_contract():
    source = SOURCE.read_text(encoding="utf-8")

    assert 'className="table execution-table management-list-table model-provider-table"' in source
    assert 'className="management-list-actions-head"' in source
    assert 'className="management-list-time"' in source
    assert 'id="model-provider-pagination"' in source
    assert 'from "./components/pagination"' in source
    assert "window.ModelProviderManagement = { mount, unmount }" in source
