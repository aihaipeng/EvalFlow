from pathlib import Path

from fastapi.testclient import TestClient

from web.app import app


STATIC_DIR = Path(__file__).parents[1] / "web" / "static"


def test_model_provider_modal_supports_keyboard_and_focus_return():
    source = (STATIC_DIR / "model-providers.js").read_text(encoding="utf-8")

    assert "var modelProviderModalReturnFocus = null;" in source
    assert 'aria-labelledby="model-provider-config-title" tabindex="-1"' in source
    assert "if (event.key === 'Escape')" in source
    assert "if (event.key !== 'Tab') return;" in source
    assert "modelProviderModalReturnFocus = document.activeElement;" in source
    assert "modelProviderModalReturnFocus.focus();" in source


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
    assert '>OpenAI Chat Completions</option>' in source
    assert 'value="OPENAI_RESPONSES"' in source
    assert '>OpenAI Responses API</option>' in source
    assert '>Anthropic Claude Messages</option>' in source
    assert "function modelProviderProtocolLabel(protocol)" in source
    assert "protocol === 'OPENAI_RESPONSES'" in source
    assert 'class="model-provider-field model-provider-protocol-setting"' in source
    assert 'aria-label="查看协议选择帮助"' in source
    assert 'role="tooltip"><strong>如何选择协议？</strong>' in source
    assert "多数 OpenAI 兼容服务使用" in source
    assert "仅在文档明确支持 <code>/responses</code>" in source
    assert "文档出现 <code>/v1/messages</code>" in source
    assert "不确定时以供应商文档为准" not in source
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
    assert "<span>SSL Verify</span>" in source
    assert "验证 SSL 证书" not in source
    assert "skip_ssl_verify" not in source
    assert "model-provider-ssl-warning" not in source
    assert ">不安全</small>" not in source
    assert 'id="model-provider-add-model"' in source
    assert 'id="model-provider-discovered"' in source
    assert 'id="model-provider-manual"' in source
    assert "modelProviderState.selected.length" in source
    assert 'data-configure-provider-model=' in source
    assert 'data-test-provider-model=' in source
    assert "API.post('/api/model-providers/test-model'" in source
    assert "modelProviderState.modelTests[model] = result" in source
    assert "var testIcon = icon('play')" in source
    assert "model-provider-test-overlay" not in source
    assert 'id="model-config-context-window"' in source
    assert 'id="model-config-max-output"' in source
    assert 'id="model-config-default-body"' in source
    assert "var MODEL_DEFAULT_BODY_REFERENCES = {" in source
    assert "thinking: {type: 'disabled'}" in source
    assert "response_format: {type: 'json_object'}" in source
    assert "function modelProviderDefaultBodyText(defaultBody)" in source
    assert "modelProviderDefaultBodyReference(modelProviderState.protocol)" in source
    assert 'id="model-config-default-body-beautify"' in source
    assert 'aria-label="格式化默认 Body JSON"' in source
    assert "function beautifyProviderDefaultBody()" in source
    assert "默认 Body 不是合法 JSON" in source
    assert "model_configs: protocolChanged ? {} : JSON.parse(JSON.stringify(modelProviderState.modelConfigs))" in source
    assert "protocol: connection.protocol" in source
    assert "'MANUAL'" not in source
    assert "保存后将清空旧协议的模型配置和测试状态" in source
    assert "var protocolChanged = Boolean(modelProviderState.editingId)" in source
    assert "models: protocolChanged ? [] : modelProviderState.selected.slice()" in source
    assert "model_endpoint: protocolChanged ? null : modelProviderState.endpoint" in source
    change_handler = source[
        source.index("protocolSelect.addEventListener('change'"):
        source.index("document.getElementById('model-provider-proxy-mode').addEventListener('change'")
    ]
    assert "window.confirm" not in change_handler
    assert "openExecutionConfirm(" not in change_handler
    assert "applyModelProviderProtocolDraft(this, this.value)" in change_handler
    assert "openExecutionConfirm(" in source
    assert "'切换接口协议'" not in source
    assert "'保存协议变更'" in source
    assert "'确认保存'" in source
    assert "return persistModelProvider(body, true)" in source
    assert "await persistModelProvider(body, false)" in source
    assert "'删除模型供应商'" in source
    assert "function applyModelProviderProtocolDraft(select, nextProtocol)" in source
    assert "window.confirm" not in source
    assert "modelProviderState.selected = []" not in change_handler
    assert "modelProviderState.modelConfigs = {}" not in change_handler
    assert "modelProviderState.modelTests = {}" not in change_handler
    assert "modelProviderState.endpoint = null" not in change_handler


def test_model_provider_styles_use_existing_theme_contract_and_desktop_layout():
    source = (STATIC_DIR / "model-providers.css").read_text(encoding="utf-8")

    for token in ("var(--surface)", "var(--surface-muted)", "var(--border)", "var(--text-main)"):
        assert token in source
    assert ':root[data-theme="dark"]' in source
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)" in source
    assert "grid-template-columns: minmax(140px, 0.7fr) minmax(190px, 1.3fr)" in source
    assert ".model-provider-switch input:checked + .model-provider-switch-track" in source
    assert "top: 50%" in source
    assert "transform: translateY(-50%)" in source
    assert "border-color: var(--green)" in source
    assert "background: var(--green)" in source
    assert "transform: translate(16px, -50%)" in source
    assert ".model-provider-protocol.is-openai_responses" in source
    assert ".model-provider-proxy-help[open] .model-provider-proxy-help-panel" in source
    assert ".model-provider-protocol-setting > span:first-child" in source
    assert ".model-provider-protocol-help .model-provider-proxy-help-panel" in source
    assert ".model-provider-protocol-help .model-provider-proxy-help-panel section" in source
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
    assert 'id="model-provider-pagination" class="global-list-footer management-list-footer"' in source
    assert 'class="table execution-table management-list-table model-provider-table"' in source
    assert 'class="management-list-actions-head"' in source
    assert 'class="management-list-actions-cell"' in source
    assert "modelProviderState.page = 1" in source


def test_model_provider_rows_hide_internal_ids_and_center_value_containers():
    source = (STATIC_DIR / "model-providers.js").read_text(encoding="utf-8")
    provider_styles = (STATIC_DIR / "model-providers.css").read_text(encoding="utf-8")
    execution_styles = (STATIC_DIR / "execution.css").read_text(encoding="utf-8")

    assert '<div class="execution-id">' not in source
    assert ".execution-id" not in execution_styles
    assert "margin: 0 auto;" in provider_styles
    assert "justify-content: center;" in provider_styles


def test_model_provider_table_fits_standard_desktop_without_forced_scroll():
    styles = (STATIC_DIR / "model-providers.css").read_text(encoding="utf-8")

    assert "--management-list-min-width: 0px;" in styles
    assert "--management-list-actions-width: 96px;" in styles
    assert "min-width: 1000px;" not in styles
