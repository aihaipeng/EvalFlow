from pathlib import Path

from fastapi.testclient import TestClient

from web.app import app


STATIC_DIR = Path(__file__).parents[1] / "web" / "static"


def test_model_provider_navigation_and_assets_are_registered():
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert 'data-view="models"><span class="sidebar-icon"' in index_html
    assert '<span>供应商管理</span>' in index_html
    assert '<link rel="stylesheet" href="/model-providers.css" />' in index_html
    assert '<script src="/model-providers.js"></script>' in index_html
    assert "viewModelProviders();" in app_js
    for asset in ("/model-providers.css", "/model-providers.js"):
        response = TestClient(app).get(asset)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache, no-store, must-revalidate"


def test_model_provider_frontend_implements_management_and_connection_flow():
    source = (STATIC_DIR / "model-providers.js").read_text(encoding="utf-8")

    assert "API.get('/api/model-providers')" in source
    assert "API.post('/api/model-providers', body)" in source
    assert "API.put('/api/model-providers/'" in source
    assert "API.del('/api/model-providers/'" in source
    assert "API.post('/api/model-providers/latency', payload)" in source
    assert "API.post('/api/model-providers/models', payload)" in source
    assert 'id="btn-model-provider-add"' in source
    assert 'id="model-provider-api-key" type="password"' in source
    assert 'id="model-provider-base-url" type="url"' in source
    assert "未测试" not in source
    assert source.count('id="model-provider-save"') == 1
    assert source.index('id="model-provider-save"') < source.index('id="model-provider-form"')
    assert 'id="model-provider-protocol"' in source
    assert '>OpenAI</option>' in source
    assert '>Anthropic</option>' in source
    assert "function modelProviderProtocolLabel(protocol)" in source
    assert 'id="model-provider-proxy-mode"' in source
    assert '>SYSTEM</option>' in source
    assert '>DIRECT</option>' in source
    assert '>CUSTOM</option>' in source
    assert 'id="model-provider-proxy-url"' in source
    assert 'id="model-provider-proxy-username"' in source
    assert 'id="model-provider-proxy-password" type="password"' in source
    assert 'id="model-provider-verify-ssl" type="checkbox" role="switch"' in source
    assert 'model-provider-switch model-provider-ssl-setting' in source
    assert 'class="model-provider-switch-track"' in source
    assert 'class="model-provider-proxy-control"' in source
    assert 'class="model-provider-proxy-help"' in source
    assert 'role="tooltip"' in source
    assert "如何选择代理模式？" in source
    assert "HTTP_PROXY / HTTPS_PROXY / NO_PROXY" in source
    assert "SSL 证书验证独立于代理模式" in source
    assert "verify_ssl: connection.verify_ssl" in source
    assert "skip_ssl_verify" not in source
    assert "syncModelProviderSslWarning" in source
    assert 'id="model-provider-add-model"' in source
    assert 'id="model-provider-discovered"' in source
    assert 'id="model-provider-manual"' in source
    assert "modelProviderState.selected.length" in source
    assert 'data-configure-provider-model=' in source
    assert 'data-test-provider-model=' in source
    assert "API.post('/api/model-providers/test-model'" in source
    assert "modelProviderState.modelTests[model] = result" in source
    assert "test.available ? '✓' : '!'" in source
    assert "model-provider-test-overlay" not in source
    assert 'id="model-config-context-window"' in source
    assert 'id="model-config-max-output"' in source
    assert 'id="model-config-default-body"' in source
    assert "var MODEL_DEFAULT_BODY_REFERENCE = JSON.stringify({" in source
    assert "thinking: {type: 'disabled'}" in source
    assert "response_format: {type: 'json_object'}" in source
    assert "function modelProviderDefaultBodyText(defaultBody)" in source
    assert "escAttr(MODEL_DEFAULT_BODY_REFERENCE)" in source
    assert 'id="model-config-default-body-beautify"' in source
    assert 'aria-label="格式化默认 Body JSON"' in source
    assert "function beautifyProviderDefaultBody()" in source
    assert "默认 Body 不是合法 JSON" in source
    assert "model_configs: JSON.parse(JSON.stringify(modelProviderState.modelConfigs))" in source
    assert "protocol: connection.protocol" in source
    assert "'MANUAL'" not in source


def test_model_provider_styles_use_existing_theme_contract_and_desktop_layout():
    source = (STATIC_DIR / "model-providers.css").read_text(encoding="utf-8")

    for token in ("var(--surface)", "var(--surface-muted)", "var(--border)", "var(--text-main)"):
        assert token in source
    assert ':root[data-theme="dark"]' in source
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)" in source
    assert "grid-template-columns: minmax(140px, 0.7fr) minmax(190px, 1.3fr)" in source
    assert ".model-provider-switch input:checked + .model-provider-switch-track" in source
    assert ".model-provider-proxy-help[open] .model-provider-proxy-help-panel" in source
    assert ".model-provider-config-json-header" in source
    assert ".model-provider-json-beautify" in source
    assert ".model-provider-config-json textarea::placeholder" in source
    assert ".model-provider-config-json textarea.input" in source
    config_textarea_rule = source[
        source.index(".model-provider-config-json textarea.input"):
        source.index("}", source.index(".model-provider-config-json textarea.input"))
    ]
    assert "min-height: 280px" in config_textarea_rule
    placeholder_rule = source[
        source.index(".model-provider-config-json textarea::placeholder"):
        source.index("}", source.index(".model-provider-config-json textarea::placeholder"))
    ]
    assert "font-style: italic" in placeholder_rule
    assert "@media" not in source


def test_model_provider_list_uses_shared_pagination():
    source = (STATIC_DIR / "model-providers.js").read_text(encoding="utf-8")

    assert "page: 1" in source
    assert "pageSize: 10" in source
    assert "globalPageSlice(filteredProviders" in source
    assert 'id="model-provider-pagination" class="global-list-footer"' in source
    assert "modelProviderState.page = 1" in source


def test_model_provider_rows_hide_internal_ids_and_center_value_containers():
    source = (STATIC_DIR / "model-providers.js").read_text(encoding="utf-8")
    provider_styles = (STATIC_DIR / "model-providers.css").read_text(encoding="utf-8")
    execution_styles = (STATIC_DIR / "execution.css").read_text(encoding="utf-8")

    assert '<div class="execution-id">' not in source
    assert ".execution-id" not in execution_styles
    assert "margin: 0 auto;" in provider_styles
    assert "justify-content: center;" in provider_styles
