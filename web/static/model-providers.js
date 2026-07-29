/* Model provider list and connection editor. */
var modelProviderState = {
    providers: [],
    query: '',
    page: 1,
    pageSize: 10,
    editingId: null,
    discovered: [],
    selected: [],
    protocol: 'OPENAI_COMPATIBLE',
    endpoint: null,
    modelConfigs: {},
    modelTests: {},
};
var MODEL_DEFAULT_BODY_REFERENCE = JSON.stringify({
    thinking: {type: 'disabled'},
    temperature: 0,
    top_p: 0.8,
    max_tokens: 1024,
    response_format: {type: 'json_object'},
}, null, 2);

function modelProviderName(provider) {
    return provider.name || '未命名供应商';
}

function modelProviderProtocolLabel(protocol) {
    return protocol === 'ANTHROPIC' ? 'Anthropic' : 'OpenAI';
}

function modelProviderDefaultBodyText(defaultBody) {
    return defaultBody && !Array.isArray(defaultBody) && typeof defaultBody === 'object'
        && Object.keys(defaultBody).length
        ? JSON.stringify(defaultBody, null, 2)
        : '';
}

function filteredModelProviders() {
    return modelProviderState.providers.filter(function (provider) {
        var text = [provider.name, provider.website_url, provider.base_url, provider.protocol]
            .concat(provider.models || []).filter(Boolean).join(' ').toLowerCase();
        return !modelProviderState.query || text.includes(modelProviderState.query);
    });
}

function renderModelProviderRows() {
    var body = document.getElementById('model-provider-list-body');
    var count = document.getElementById('model-provider-count');
    if (!body || !count) return;
    var filteredProviders = filteredModelProviders();
    var pagination = globalPageSlice(filteredProviders, modelProviderState.page, modelProviderState.pageSize);
    var providers = pagination.items;
    modelProviderState.page = pagination.page;
    modelProviderState.pageSize = pagination.pageSize;
    count.textContent = modelProviderState.providers.length + ' 个供应商';
    renderGlobalListPagination('model-provider-pagination', pagination.total, pagination.page, pagination.pageSize, function (nextPage) {
        modelProviderState.page = nextPage;
        renderModelProviderRows();
    }, function (nextPageSize) {
        modelProviderState.page = 1;
        modelProviderState.pageSize = nextPageSize;
        renderModelProviderRows();
    }, '个供应商');
    if (!providers.length) {
        body.innerHTML = '<tr><td colspan="6"><div class="execution-empty"><strong>' +
            (modelProviderState.providers.length ? '没有匹配的模型供应商' : '尚未添加模型供应商') +
            '</strong></div></td></tr>';
        return;
    }
    body.innerHTML = providers.map(function (provider) {
        var website = provider.website_url
            ? '<a class="model-provider-website" href="' + escAttr(provider.website_url) + '" target="_blank" rel="noopener noreferrer">官网</a>'
            : '';
        var modelPreview = (provider.models || []).slice(0, 2).map(function (model) {
            return '<span class="model-provider-mini-model">' + esc(model) + '</span>';
        }).join('');
        var remaining = (provider.models || []).length - 2;
        if (remaining > 0) modelPreview += '<span class="model-provider-more">+' + remaining + '</span>';
        return '<tr>' +
            '<td><button class="execution-name-button" type="button" data-provider-edit="' + escAttr(provider.id) + '">' + esc(modelProviderName(provider)) + '</button>' + website + '</td>' +
            '<td><span class="model-provider-url" title="' + escAttr(provider.base_url) + '">' + esc(provider.base_url) + '</span></td>' +
            '<td><span class="model-provider-protocol is-' + escAttr(provider.protocol.toLowerCase()) + '">' + esc(modelProviderProtocolLabel(provider.protocol)) + '</span></td>' +
            '<td><div class="model-provider-model-preview">' + modelPreview + '</div></td>' +
            '<td>' + esc(formatDateTime(provider.updated_at)) + '</td>' +
            '<td><div class="execution-row-actions">' +
                '<button class="btn-icon" type="button" data-provider-edit="' + escAttr(provider.id) + '" title="编辑模型供应商" aria-label="编辑模型供应商">' + icon('edit') + '</button>' +
                '<button class="btn-icon" type="button" data-provider-delete="' + escAttr(provider.id) + '" title="删除模型供应商" aria-label="删除模型供应商">' + icon('trash') + '</button>' +
            '</div></td></tr>';
    }).join('');
    body.querySelectorAll('[data-provider-edit]').forEach(function (button) {
        button.addEventListener('click', function () {
            viewModelProviderEditor(button.getAttribute('data-provider-edit'));
        });
    });
    body.querySelectorAll('[data-provider-delete]').forEach(function (button) {
        button.addEventListener('click', function () {
            deleteModelProvider(button.getAttribute('data-provider-delete'));
        });
    });
}

async function loadModelProviders() {
    try {
        var data = await API.get('/api/model-providers');
        modelProviderState.providers = data.providers || [];
        renderModelProviderRows();
    } catch (error) {
        showToast('加载模型供应商失败: ' + error.message, 'error');
    }
}

function viewModelProviders() {
    currentView = 'model-providers';
    modelProviderState.editingId = null;
    contentArea.innerHTML =
        '<section class="execution-page model-provider-page" aria-labelledby="model-provider-title">' +
            '<header class="execution-page-header"><div><h1 id="model-provider-title">供应商管理</h1></div><span class="execution-count" id="model-provider-count">0 个供应商</span></header>' +
            '<div class="toolbar execution-toolbar" id="model-provider-toolbar">' +
                '<button class="btn btn-primary" id="btn-model-provider-add" type="button">' + icon('add') + '新增模型</button>' +
                '<button class="btn" id="btn-model-provider-refresh" type="button">' + icon('refresh') + '刷新</button>' +
                '<span class="toolbar-sep"></span>' +
                '<input class="input toolbar-search" id="model-provider-search" type="search" placeholder="搜索供应商、地址或模型..." aria-label="搜索模型供应商" />' +
            '</div>' +
            '<div class="table-wrap execution-table-wrap"><table class="table execution-table model-provider-table">' +
                '<thead><tr><th>供应商</th><th>BASE_URL</th><th>协议</th><th>模型</th><th>更新时间</th><th>操作</th></tr></thead>' +
                '<tbody id="model-provider-list-body"></tbody>' +
            '</table></div>' +
            '<div id="model-provider-pagination" class="global-list-footer"></div>' +
        '</section>';
    document.getElementById('btn-model-provider-add').addEventListener('click', function () {
        viewModelProviderEditor(null);
    });
    document.getElementById('btn-model-provider-refresh').addEventListener('click', loadModelProviders);
    document.getElementById('model-provider-search').addEventListener('input', function () {
        modelProviderState.query = this.value.trim().toLowerCase();
        modelProviderState.page = 1;
        renderModelProviderRows();
    });
    loadModelProviders();
}

function modelProviderEditorMarkup(provider) {
    var isEditing = Boolean(provider);
    return '<section class="model-provider-editor" aria-labelledby="model-provider-editor-title">' +
        '<header class="model-provider-editor-header">' +
            '<button class="btn btn-sm" id="model-provider-back" type="button">' + icon('back') + '返回</button>' +
            '<div class="model-provider-editor-heading"><span>MODEL PROVIDER</span><h1 id="model-provider-editor-title">' + (isEditing ? '编辑模型供应商' : '新增模型供应商') + '</h1></div>' +
            '<button id="model-provider-save" type="button" class="btn btn-primary model-provider-header-save">' + icon('save') + '保存</button>' +
        '</header>' +
        '<form id="model-provider-form" class="model-provider-form">' +
            '<label class="model-provider-field"><span>供应商名称 <small>选填</small></span><input class="input" id="model-provider-name" maxlength="120" placeholder="例如：企业模型网关" value="' + escAttr(provider && provider.name || '') + '" /></label>' +
            '<label class="model-provider-field"><span>官网链接 <small>选填</small></span><input class="input" id="model-provider-website" type="url" maxlength="2048" placeholder="https://example.com" value="' + escAttr(provider && provider.website_url || '') + '" /></label>' +
            '<label class="model-provider-field"><span>API Key <b>*</b></span><span class="model-provider-key-wrap"><input class="input" id="model-provider-api-key" type="password" maxlength="4096" autocomplete="off" required placeholder="输入 API Key" value="' + escAttr(provider && provider.api_key || '') + '" /><button id="model-provider-key-toggle" class="model-provider-key-toggle" type="button" aria-label="显示 API Key" title="显示 API Key">' + icon('eye') + '</button></span></label>' +
            '<label class="model-provider-field"><span>BASE_URL <b>*</b></span><input class="input" id="model-provider-base-url" type="url" maxlength="2048" required placeholder="https://api.example.com" value="' + escAttr(provider && provider.base_url || '') + '" /></label>' +
            '<label class="model-provider-field"><span>协议 <b>*</b></span><select class="input" id="model-provider-protocol"><option value="OPENAI_COMPATIBLE"' + ((provider && provider.protocol) === 'ANTHROPIC' ? '' : ' selected') + '>OpenAI</option><option value="ANTHROPIC"' + ((provider && provider.protocol) === 'ANTHROPIC' ? ' selected' : '') + '>Anthropic</option></select></label>' +
            '<div class="model-provider-field model-provider-proxy-setting"><span>代理模式 <b>*</b><details class="model-provider-proxy-help"><summary aria-label="查看代理模式配置帮助" title="代理模式配置帮助">?</summary>' +
                '<div class="model-provider-proxy-help-panel" role="tooltip"><strong>如何选择代理模式？</strong>' +
                    '<section><b>SYSTEM</b><span>遵循系统的 HTTP_PROXY / HTTPS_PROXY / NO_PROXY，适合作为默认选择。</span></section>' +
                    '<section><b>DIRECT</b><span>忽略系统代理和 VPN 注入的代理变量，直接连接目标服务。</span></section>' +
                    '<section><b>CUSTOM</b><span>始终使用下方填写的 HTTP(S) 或 SOCKS5 代理。</span></section>' +
                    '<p>SSL 证书验证独立于代理模式；仅在可信的自签名服务联调时关闭。</p>' +
                '</div></details></span><div class="model-provider-proxy-control">' +
                '<select class="input" id="model-provider-proxy-mode" aria-label="代理模式"><option value="SYSTEM"' + ((provider && provider.proxy_mode) === 'DIRECT' || (provider && provider.proxy_mode) === 'CUSTOM' ? '' : ' selected') + '>SYSTEM</option><option value="DIRECT"' + ((provider && provider.proxy_mode) === 'DIRECT' ? ' selected' : '') + '>DIRECT</option><option value="CUSTOM"' + ((provider && provider.proxy_mode) === 'CUSTOM' ? ' selected' : '') + '>CUSTOM</option></select>' +
                '<label class="model-provider-switch model-provider-ssl-setting"><input id="model-provider-verify-ssl" type="checkbox" role="switch"' + (!provider || provider.verify_ssl !== false ? ' checked' : '') + ' /><span class="model-provider-switch-track" aria-hidden="true"></span><span>验证 SSL 证书</span><small class="model-provider-ssl-warning" id="model-provider-ssl-warning" hidden>不安全</small></label>' +
            '</div></div>' +
            '<section class="model-provider-proxy-fields' + ((provider && provider.proxy_mode) === 'CUSTOM' ? '' : ' is-hidden') + '" id="model-provider-proxy-fields">' +
                '<label class="model-provider-field"><span>代理地址 <b>*</b></span><input class="input" id="model-provider-proxy-url" maxlength="2048" placeholder="http://proxy.corp.com:8080" value="' + escAttr(provider && provider.proxy_url || '') + '" /></label>' +
                '<label class="model-provider-field"><span>代理用户名 <small>选填</small></span><input class="input" id="model-provider-proxy-username" maxlength="512" autocomplete="off" value="' + escAttr(provider && provider.proxy_username || '') + '" /></label>' +
                '<label class="model-provider-field"><span>代理密码 <small>选填</small></span><input class="input" id="model-provider-proxy-password" type="password" maxlength="4096" autocomplete="off" value="' + escAttr(provider && provider.proxy_password || '') + '" /></label>' +
            '</section>' +
        '</form>' +
        '<div class="model-provider-actions">' +
            '<button id="model-provider-latency" type="button" class="btn" data-default-label="测速" data-button-icon="gauge">' + icon('gauge') + '测速</button>' +
            '<button id="model-provider-fetch" type="button" class="btn btn-primary" data-default-label="获取模型" data-button-icon="refresh">' + icon('refresh') + '获取模型</button>' +
            '<button id="model-provider-add-model" type="button" class="btn"' + (isEditing ? '' : ' disabled') + '>' + icon('add') + '添加模型</button>' +
        '</div>' +
        '<section class="model-provider-status" aria-label="连接状态">' +
            '<div class="model-provider-status-main"><span class="model-provider-status-mark" aria-hidden="true"></span><div><span>连接状态</span><strong id="model-provider-status-title">等待测试</strong></div></div>' +
            '<div class="model-provider-metric"><span>访问延迟</span><strong id="model-provider-latency-value">--</strong></div>' +
            '<div class="model-provider-metric model-provider-metric-wide"><span>协议 / 模型端点</span><strong id="model-provider-protocol-value">' + esc(provider ? modelProviderProtocolLabel(provider.protocol) : '--') + '</strong><small id="model-provider-endpoint-value">' + esc(provider && provider.model_endpoint || '尚未获取模型') + '</small></div>' +
            '<div class="model-provider-metric"><span>发现模型</span><strong id="model-provider-model-count">0</strong></div>' +
        '</section>' +
        '<section id="model-provider-chooser" class="model-provider-chooser is-hidden" aria-label="添加模型">' +
            '<label><span>已发现模型</span><select class="input" id="model-provider-discovered" disabled><option value="">暂无可选模型</option></select></label>' +
            '<span class="model-provider-chooser-or">或</span>' +
            '<label><span>手工模型名称</span><input class="input" id="model-provider-manual" maxlength="200" placeholder="例如：deepseek-chat" /></label>' +
            '<button id="model-provider-confirm-model" type="button" class="btn btn-primary">' + icon('add') + '确认添加</button>' +
        '</section>' +
        '<section class="model-provider-selected" aria-labelledby="model-provider-selected-title">' +
            '<header><h2 id="model-provider-selected-title">已添加模型</h2><span id="model-provider-selected-count">0 个</span></header>' +
            '<div id="model-provider-selected-list"></div>' +
        '</section>' +
    '</section>';
}

async function viewModelProviderEditor(providerId) {
    currentView = 'model-provider-editor';
    var provider = null;
    if (providerId) {
        try {
            provider = (await API.get('/api/model-providers/' + encodeURIComponent(providerId))).provider;
        } catch (error) {
            showToast('读取模型供应商失败: ' + error.message, 'error');
            return;
        }
    }
    modelProviderState.editingId = providerId;
    modelProviderState.discovered = [];
    modelProviderState.selected = provider ? (provider.models || []).slice() : [];
    modelProviderState.protocol = provider ? provider.protocol : 'OPENAI_COMPATIBLE';
    modelProviderState.endpoint = provider ? provider.model_endpoint : null;
    modelProviderState.modelConfigs = provider ? JSON.parse(JSON.stringify(provider.model_configs || {})) : {};
    modelProviderState.modelTests = {};
    contentArea.innerHTML = modelProviderEditorMarkup(provider);
    bindModelProviderEditor();
    renderSelectedProviderModels();
}

function bindModelProviderEditor() {
    document.getElementById('model-provider-back').addEventListener('click', viewModelProviders);
    document.getElementById('model-provider-key-toggle').addEventListener('click', toggleModelProviderKey);
    document.getElementById('model-provider-protocol').addEventListener('change', function () {
        modelProviderState.protocol = this.value;
        document.getElementById('model-provider-protocol-value').textContent = modelProviderProtocolLabel(this.value);
        renderSelectedProviderModels();
    });
    document.getElementById('model-provider-proxy-mode').addEventListener('change', syncModelProviderProxyFields);
    document.getElementById('model-provider-verify-ssl').addEventListener('change', syncModelProviderSslWarning);
    document.getElementById('model-provider-latency').addEventListener('click', testModelProviderLatency);
    document.getElementById('model-provider-fetch').addEventListener('click', fetchProviderModels);
    document.getElementById('model-provider-add-model').addEventListener('click', toggleProviderModelChooser);
    document.getElementById('model-provider-confirm-model').addEventListener('click', addSelectedProviderModel);
    document.getElementById('model-provider-save').addEventListener('click', saveModelProvider);
    syncModelProviderProxyFields();
    syncModelProviderSslWarning();
}

function syncModelProviderProxyFields() {
    var mode = document.getElementById('model-provider-proxy-mode').value;
    var fields = document.getElementById('model-provider-proxy-fields');
    var url = document.getElementById('model-provider-proxy-url');
    fields.classList.toggle('is-hidden', mode !== 'CUSTOM');
    url.required = mode === 'CUSTOM';
}

function syncModelProviderSslWarning() {
    var verify = document.getElementById('model-provider-verify-ssl').checked;
    document.getElementById('model-provider-ssl-warning').hidden = verify;
}

function toggleModelProviderKey() {
    var input = document.getElementById('model-provider-api-key');
    var button = document.getElementById('model-provider-key-toggle');
    var visible = input.type === 'text';
    input.type = visible ? 'password' : 'text';
    button.innerHTML = icon(visible ? 'eye' : 'eye-off');
    button.setAttribute('aria-label', visible ? '显示 API Key' : '隐藏 API Key');
    button.title = button.getAttribute('aria-label');
}

function readModelProviderConnection() {
    var form = document.getElementById('model-provider-form');
    if (!form.reportValidity()) return null;
    return {
        api_key: document.getElementById('model-provider-api-key').value,
        base_url: document.getElementById('model-provider-base-url').value.trim(),
        protocol: document.getElementById('model-provider-protocol').value,
        proxy_mode: document.getElementById('model-provider-proxy-mode').value,
        proxy_url: document.getElementById('model-provider-proxy-url').value.trim() || null,
        proxy_username: document.getElementById('model-provider-proxy-username').value.trim() || null,
        proxy_password: document.getElementById('model-provider-proxy-password').value || null,
        verify_ssl: document.getElementById('model-provider-verify-ssl').checked,
    };
}

function setModelProviderButtonBusy(button, busy, busyLabel) {
    button.disabled = busy;
    var label = busy ? busyLabel : button.dataset.defaultLabel;
    button.innerHTML = icon(busy ? 'refresh' : button.dataset.buttonIcon) + esc(label);
    button.classList.toggle('is-busy', busy);
}

function setModelProviderStatus(label, state, title) {
    document.getElementById('model-provider-status-title').textContent = title;
}

async function testModelProviderLatency() {
    var payload = readModelProviderConnection();
    if (!payload) return;
    var button = document.getElementById('model-provider-latency');
    setModelProviderButtonBusy(button, true, '测速中');
    setModelProviderStatus('测试中', 'idle', '正在访问 BASE_URL');
    try {
        var result = await API.post('/api/model-providers/latency', payload);
        document.getElementById('model-provider-latency-value').textContent = result.latency_ms + ' ms';
        setModelProviderStatus('可连接', 'success', '可达 · HTTP ' + result.status_code);
        showToast('测速完成：' + result.latency_ms + ' ms', 'success');
    } catch (error) {
        document.getElementById('model-provider-latency-value').textContent = '--';
        setModelProviderStatus('连接失败', 'error', '连接失败');
        showToast(error.message, 'error');
    } finally {
        setModelProviderButtonBusy(button, false, '');
    }
}

function renderDiscoveredProviderModels() {
    var select = document.getElementById('model-provider-discovered');
    select.innerHTML = '<option value="">' + (modelProviderState.discovered.length ? '选择一个模型' : '暂无可选模型') + '</option>' +
        modelProviderState.discovered.map(function (model) {
            var label = model.owned_by ? model.id + ' · ' + model.owned_by : model.id;
            return '<option value="' + escAttr(model.id) + '">' + esc(label) + '</option>';
        }).join('');
    select.disabled = modelProviderState.discovered.length === 0;
    document.getElementById('model-provider-model-count').textContent = String(modelProviderState.discovered.length);
}

async function fetchProviderModels() {
    var payload = readModelProviderConnection();
    if (!payload) return;
    var button = document.getElementById('model-provider-fetch');
    var addButton = document.getElementById('model-provider-add-model');
    setModelProviderButtonBusy(button, true, '获取中');
    addButton.disabled = true;
    setModelProviderStatus('探测中', 'idle', '正在探测模型协议');
    try {
        var result = await API.post('/api/model-providers/models', payload);
        modelProviderState.discovered = result.models || [];
        modelProviderState.protocol = result.protocol;
        modelProviderState.endpoint = result.endpoint;
        renderDiscoveredProviderModels();
        document.getElementById('model-provider-protocol-value').textContent = modelProviderProtocolLabel(result.protocol);
        document.getElementById('model-provider-endpoint-value').textContent = result.endpoint;
        document.getElementById('model-provider-latency-value').textContent = result.latency_ms + ' ms';
        setModelProviderStatus('已连接', 'success', '模型列表已获取');
        showToast('已获取 ' + modelProviderState.discovered.length + ' 个模型', 'success');
    } catch (error) {
        modelProviderState.discovered = [];
        modelProviderState.endpoint = null;
        renderDiscoveredProviderModels();
        document.getElementById('model-provider-protocol-value').textContent = modelProviderProtocolLabel(modelProviderState.protocol);
        document.getElementById('model-provider-endpoint-value').textContent = '自动获取失败';
        setModelProviderStatus('需手工配置', 'error', '可手工添加模型');
        showToast(error.message, 'error');
    } finally {
        setModelProviderButtonBusy(button, false, '');
        addButton.disabled = false;
    }
}

function toggleProviderModelChooser() {
    document.getElementById('model-provider-chooser').classList.toggle('is-hidden');
}

function addSelectedProviderModel() {
    var manual = document.getElementById('model-provider-manual').value.trim();
    var discovered = document.getElementById('model-provider-discovered').value;
    var modelId = manual || discovered;
    if (!modelId) {
        showToast('请选择或输入模型名称', 'error');
        return;
    }
    if (modelProviderState.selected.includes(modelId)) {
        showToast('该模型已经添加', 'error');
        return;
    }
    modelProviderState.selected.push(modelId);
    document.getElementById('model-provider-manual').value = '';
    document.getElementById('model-provider-discovered').value = '';
    renderSelectedProviderModels();
    showToast('已添加模型 ' + modelId, 'success');
}

function renderSelectedProviderModels() {
    var list = document.getElementById('model-provider-selected-list');
    document.getElementById('model-provider-selected-count').textContent = modelProviderState.selected.length + ' 个';
    if (!modelProviderState.selected.length) {
        list.innerHTML = '<div class="model-provider-empty">暂无已添加模型</div>';
        return;
    }
    list.innerHTML = modelProviderState.selected.map(function (model) {
        var config = modelProviderState.modelConfigs[model] || {};
        var test = modelProviderState.modelTests[model];
        var metadata = [];
        if (config.context_window) metadata.push('上下文 ' + config.context_window);
        if (config.max_output_tokens) metadata.push('最大输出 ' + config.max_output_tokens);
        var testState = test ? (test.available ? ' is-success' : ' is-error') : '';
        var testIcon = icon('play');
        var testTitle = test ? (test.available ? '模型可用' : '模型不可用') : '测试 ' + model;
        return '<div class="model-provider-selected-row"><span class="model-provider-model-mark">M</span><strong>' + esc(model) + '</strong>' +
            '<span>' + esc(metadata.join(' · ') || modelProviderProtocolLabel(modelProviderState.protocol)) + '</span>' +
            '<button class="model-provider-test-button' + testState + '" type="button" data-test-provider-model="' + escAttr(model) + '" title="' + escAttr(testTitle) + '" aria-label="测试 ' + escAttr(model) + '">' + testIcon + '</button>' +
            '<button class="model-provider-config-button" type="button" data-configure-provider-model="' + escAttr(model) + '" title="配置 ' + escAttr(model) + '" aria-label="配置 ' + escAttr(model) + '">' + icon('settings') + '</button>' +
            '<button class="model-provider-remove-button" type="button" data-remove-provider-model="' + escAttr(model) + '" title="移除 ' + escAttr(model) + '" aria-label="移除 ' + escAttr(model) + '">' + icon('trash') + '</button></div>';
    }).join('');
    list.querySelectorAll('[data-test-provider-model]').forEach(function (button) {
        button.addEventListener('click', function () {
            testProviderModel(button.getAttribute('data-test-provider-model'), button);
        });
    });
    list.querySelectorAll('[data-configure-provider-model]').forEach(function (button) {
        button.addEventListener('click', function () {
            openProviderModelConfig(button.getAttribute('data-configure-provider-model'));
        });
    });
    list.querySelectorAll('[data-remove-provider-model]').forEach(function (button) {
        button.addEventListener('click', function () {
            var model = button.getAttribute('data-remove-provider-model');
            modelProviderState.selected = modelProviderState.selected.filter(function (item) { return item !== model; });
            delete modelProviderState.modelConfigs[model];
            delete modelProviderState.modelTests[model];
            renderSelectedProviderModels();
        });
    });
}

async function testProviderModel(model, button) {
    var connection = readModelProviderConnection();
    if (!connection) return;
    var config = modelProviderState.modelConfigs[model] || {};
    button.disabled = true;
    button.classList.add('is-busy');
    button.innerHTML = icon('refresh');
    try {
        var result = await API.post('/api/model-providers/test-model', {
            api_key: connection.api_key,
            base_url: connection.base_url,
            protocol: connection.protocol,
            proxy_mode: connection.proxy_mode,
            proxy_url: connection.proxy_mode === 'CUSTOM' ? connection.proxy_url : null,
            proxy_username: connection.proxy_mode === 'CUSTOM' ? connection.proxy_username : null,
            proxy_password: connection.proxy_mode === 'CUSTOM' ? connection.proxy_password : null,
            verify_ssl: connection.verify_ssl,
            model_name: model,
            default_body: config.default_body || {},
        });
        modelProviderState.modelTests[model] = result;
        var httpStatus = result.status_code == null ? '' : ' · HTTP ' + result.status_code;
        var latency = result.latency_ms == null ? '' : ' · ' + result.latency_ms + ' ms';
        showToast(model + (result.available ? ' 可用' : ' 不可用') + httpStatus + latency, result.available ? 'success' : 'error');
    } catch (error) {
        modelProviderState.modelTests[model] = {
            available: false,
            status_code: null,
            latency_ms: null,
            error: error.message,
        };
        showToast(model + ' 不可用 · ' + error.message, 'error');
    } finally {
        renderSelectedProviderModels();
    }
}

function openProviderModelConfig(model) {
    var current = modelProviderState.modelConfigs[model] || {};
    var defaultBodyText = modelProviderDefaultBodyText(current.default_body);
    var overlay = document.createElement('div');
    overlay.id = 'model-provider-config-overlay';
    overlay.className = 'overlay';
    overlay.innerHTML = '<div class="modal modal-wide model-provider-config-modal" role="dialog" aria-modal="true" aria-labelledby="model-provider-config-title">' +
        '<div class="modal-header" id="model-provider-config-title">模型配置 · ' + esc(model) + '</div>' +
        '<div class="modal-body model-provider-config-body">' +
            '<label class="model-provider-field"><span>上下文窗口 <small>仅元数据</small></span><input class="input" id="model-config-context-window" type="number" min="1" step="1" placeholder="例如 128000" value="' + escAttr(current.context_window || '') + '" /></label>' +
            '<label class="model-provider-field"><span>最大输出 Token <small>仅元数据</small></span><input class="input" id="model-config-max-output" type="number" min="1" step="1" placeholder="例如 8192" value="' + escAttr(current.max_output_tokens || '') + '" /></label>' +
            '<div class="model-provider-field model-provider-config-json"><div class="model-provider-config-json-header"><span>默认 Body JSON <small>运行时可被节点高级参数覆盖</small></span><button class="model-provider-json-beautify" id="model-config-default-body-beautify" type="button" title="格式化默认 Body JSON" aria-label="格式化默认 Body JSON">' + icon('braces') + 'Beautify</button></div><textarea class="input" id="model-config-default-body" aria-label="默认 Body JSON" spellcheck="false" placeholder="' + escAttr(MODEL_DEFAULT_BODY_REFERENCE) + '">' + esc(defaultBodyText) + '</textarea></div>' +
        '</div>' +
        '<div class="modal-footer"><button class="btn btn-secondary" id="model-config-cancel" type="button">' + icon('close') + '取消</button><button class="btn btn-primary" id="model-config-save" type="button">' + icon('save') + '保存</button></div>' +
    '</div>';
    document.body.appendChild(overlay);
    document.getElementById('model-config-default-body-beautify').addEventListener('click', beautifyProviderDefaultBody);
    document.getElementById('model-config-cancel').addEventListener('click', closeProviderModelConfig);
    document.getElementById('model-config-save').addEventListener('click', function () {
        saveProviderModelConfig(model);
    });
}

function beautifyProviderDefaultBody() {
    var editor = document.getElementById('model-config-default-body');
    var source = editor.value.trim();
    if (!source) return;
    try {
        var parsed = JSON.parse(source);
        if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
            throw new Error('默认 Body 必须是 JSON 对象');
        }
        editor.value = JSON.stringify(parsed, null, 2);
    } catch (error) {
        showToast(error instanceof SyntaxError ? '默认 Body 不是合法 JSON' : error.message, 'error');
    }
}

function closeProviderModelConfig() {
    var overlay = document.getElementById('model-provider-config-overlay');
    if (overlay) overlay.remove();
}

function readPositiveOptionalInteger(id, label) {
    var raw = document.getElementById(id).value.trim();
    if (!raw) return null;
    var value = Number(raw);
    if (!Number.isInteger(value) || value < 1) throw new Error(label + '必须是大于 0 的整数');
    return value;
}

function saveProviderModelConfig(model) {
    try {
        var defaultBody = JSON.parse(document.getElementById('model-config-default-body').value || '{}');
        if (!defaultBody || Array.isArray(defaultBody) || typeof defaultBody !== 'object') {
            throw new Error('默认 Body 必须是 JSON 对象');
        }
        modelProviderState.modelConfigs[model] = {
            context_window: readPositiveOptionalInteger('model-config-context-window', '上下文窗口'),
            max_output_tokens: readPositiveOptionalInteger('model-config-max-output', '最大输出 Token'),
            default_body: defaultBody,
        };
        closeProviderModelConfig();
        renderSelectedProviderModels();
        showToast('模型配置已更新，保存供应商后生效', 'success');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function saveModelProvider() {
    var connection = readModelProviderConnection();
    if (!connection) return;
    if (!modelProviderState.selected.length) {
        showToast('至少添加一个模型', 'error');
        return;
    }
    var body = {
        name: document.getElementById('model-provider-name').value.trim() || null,
        website_url: document.getElementById('model-provider-website').value.trim() || null,
        api_key: connection.api_key,
        base_url: connection.base_url,
        protocol: connection.protocol,
        proxy_mode: connection.proxy_mode,
        proxy_url: connection.proxy_mode === 'CUSTOM' ? connection.proxy_url : null,
        proxy_username: connection.proxy_mode === 'CUSTOM' ? connection.proxy_username : null,
        proxy_password: connection.proxy_mode === 'CUSTOM' ? connection.proxy_password : null,
        verify_ssl: connection.verify_ssl,
        model_endpoint: modelProviderState.endpoint,
        models: modelProviderState.selected.slice(),
        model_configs: JSON.parse(JSON.stringify(modelProviderState.modelConfigs)),
    };
    var button = document.getElementById('model-provider-save');
    button.disabled = true;
    try {
        if (modelProviderState.editingId) {
            await API.put('/api/model-providers/' + encodeURIComponent(modelProviderState.editingId), body);
        } else {
            await API.post('/api/model-providers', body);
        }
        showToast(modelProviderState.editingId ? '模型供应商已更新' : '模型供应商已创建', 'success');
        viewModelProviders();
    } catch (error) {
        showToast('保存模型供应商失败: ' + error.message, 'error');
        button.disabled = false;
    }
}

async function deleteModelProvider(providerId) {
    var provider = modelProviderState.providers.find(function (item) { return item.id === providerId; });
    if (!provider || !window.confirm('确定删除模型供应商“' + modelProviderName(provider) + '”吗？')) return;
    try {
        await API.del('/api/model-providers/' + encodeURIComponent(providerId));
        showToast('模型供应商已删除', 'success');
        await loadModelProviders();
    } catch (error) {
        showToast('删除模型供应商失败: ' + error.message, 'error');
    }
}
