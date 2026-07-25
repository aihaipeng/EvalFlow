/* Target management and the persistent Workflow Studio. */
var executionState = {
    targets: [],
    workflows: [],
    editingTargetId: null,
};

function executionEmpty(title, actionLabel, actionId) {
    return '<div class="execution-empty">' +
        '<strong>' + esc(title) + '</strong>' +
        (actionLabel ? '<button class="btn btn-primary btn-sm" id="' + actionId + '">' + icon('add') + esc(actionLabel) + '</button>' : '') +
    '</div>';
}

function executionErrorMessage(error) {
    var message = error && error.message ? error.message : String(error || '请求失败');
    return message === '[object Object]' ? '请求参数校验失败' : message;
}

function ensureExecutionModal() {
    var overlay = document.getElementById('execution-overlay');
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.id = 'execution-overlay';
    overlay.className = 'overlay hidden';
    overlay.innerHTML = '<div class="modal execution-modal" role="dialog" aria-modal="true" aria-labelledby="execution-modal-title">' +
        '<div class="modal-header" id="execution-modal-title"></div>' +
        '<div class="modal-body" id="execution-modal-body"></div>' +
        '<div class="modal-footer">' +
            '<button class="btn btn-secondary" id="execution-modal-cancel" type="button">取消</button>' +
            '<button class="btn btn-primary" id="execution-modal-save" type="button">保存</button>' +
        '</div>' +
    '</div>';
    document.body.appendChild(overlay);
    overlay.addEventListener('click', function (event) {
        if (event.target === overlay) closeExecutionModal();
    });
    overlay.querySelector('#execution-modal-cancel').addEventListener('click', closeExecutionModal);
    return overlay;
}

function closeExecutionModal() {
    var overlay = document.getElementById('execution-overlay');
    if (overlay) overlay.classList.add('hidden');
}

function openExecutionModal(title, bodyHtml, onSave, saveLabel) {
    var overlay = ensureExecutionModal();
    overlay.querySelector('#execution-modal-title').textContent = title;
    overlay.querySelector('#execution-modal-body').innerHTML = bodyHtml;
    var save = overlay.querySelector('#execution-modal-save');
    save.textContent = saveLabel || '保存';
    save.disabled = false;
    save.onclick = async function () {
        save.disabled = true;
        try {
            await onSave();
        } finally {
            save.disabled = false;
        }
    };
    overlay.classList.remove('hidden');
    var focusable = overlay.querySelector('input, select, textarea');
    if (focusable) focusable.focus();
}

function targetAddress(target) {
    return String(target.base_url || '').replace(/\/$/, '') + String(target.path || '');
}

function renderTargetTable() {
    var body = document.getElementById('target-list-body');
    var count = document.getElementById('target-count');
    if (!body || !count) return;
    count.textContent = executionState.targets.length + ' 个 Target';
    if (!executionState.targets.length) {
        body.innerHTML = '<tr><td colspan="7">' + executionEmpty('尚未配置 Target', '新增 Target', 'target-empty-add') + '</td></tr>';
        var emptyAdd = document.getElementById('target-empty-add');
        if (emptyAdd) emptyAdd.addEventListener('click', function () { openTargetEditor(); });
        return;
    }
    body.innerHTML = executionState.targets.map(function (target) {
        return '<tr>' +
            '<td><button class="execution-name-button" type="button" data-target-edit="' + esc(target.id) + '">' + esc(target.name) + '</button>' +
                '<div class="execution-id">' + esc(target.id) + '</div></td>' +
            '<td><code class="target-address">' + esc(targetAddress(target)) + '</code></td>' +
            '<td><span class="execution-badge execution-badge-neutral">' + esc(target.method) + '</span></td>' +
            '<td>' + Object.keys(target.headers || {}).length + '</td>' +
            '<td>' + target.target_total_concurrency + '</td>' +
            '<td>' + esc(formatDateTime(target.updated_at)) + '</td>' +
            '<td><div class="execution-row-actions">' +
                '<button class="btn-icon" type="button" data-target-edit="' + esc(target.id) + '" title="编辑 Target" aria-label="编辑 Target">' + icon('edit') + '</button>' +
                '<button class="btn-icon" type="button" data-target-delete="' + esc(target.id) + '" title="删除 Target" aria-label="删除 Target">' + icon('trash') + '</button>' +
            '</div></td>' +
        '</tr>';
    }).join('');
    body.querySelectorAll('[data-target-edit]').forEach(function (button) {
        button.addEventListener('click', function () { openTargetEditor(button.getAttribute('data-target-edit')); });
    });
    body.querySelectorAll('[data-target-delete]').forEach(function (button) {
        button.addEventListener('click', function () { deleteTarget(button.getAttribute('data-target-delete')); });
    });
}

async function loadTargets() {
    try {
        var data = await API.get('/api/targets');
        executionState.targets = data.targets || [];
        renderTargetTable();
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
    }
}

function viewTargets() {
    currentView = 'targets';
    contentArea.innerHTML =
        '<section class="execution-page" aria-labelledby="targets-title">' +
            '<header class="execution-page-header">' +
                '<div><h1 id="targets-title">Target 管理</h1><p>企业 Agent FastAPI 环境与共享请求并发</p></div>' +
                '<span class="execution-count" id="target-count">0 个 Target</span>' +
            '</header>' +
            '<div class="toolbar execution-toolbar">' +
                '<button class="btn btn-primary" id="btn-target-add" type="button">' + icon('add') + '新增 Target</button>' +
                '<button class="btn" id="btn-target-refresh" type="button">' + icon('refresh') + '刷新</button>' +
            '</div>' +
            '<div class="table-wrap execution-table-wrap"><table class="table execution-table" id="targets-table">' +
                '<thead><tr><th>名称</th><th>请求地址</th><th>方法</th><th>Headers</th><th>总并发</th><th>更新时间</th><th>操作</th></tr></thead>' +
                '<tbody id="target-list-body"></tbody>' +
            '</table></div>' +
        '</section>';
    document.getElementById('btn-target-add').addEventListener('click', function () { openTargetEditor(); });
    document.getElementById('btn-target-refresh').addEventListener('click', loadTargets);
    loadTargets();
}

function targetFormHtml(target) {
    target = target || {
        name: '', base_url: 'http://127.0.0.1:9000', path: '/api/agent/invoke',
        method: 'POST', headers: {}, target_total_concurrency: 1,
    };
    return '<div class="execution-form-grid">' +
        '<label class="form-row"><span class="form-label">名称</span><input class="input" id="target-name" maxlength="120" value="' + esc(target.name) + '" /></label>' +
        '<label class="form-row"><span class="form-label">HTTP 方法</span><select class="input" id="target-method" disabled><option value="POST">POST</option></select></label>' +
        '<label class="form-row form-row-full"><span class="form-label">Base URL</span><input class="input" id="target-base-url" value="' + esc(target.base_url) + '" /></label>' +
        '<label class="form-row form-row-full"><span class="form-label">Path</span><input class="input" id="target-path" value="' + esc(target.path) + '" /></label>' +
        '<label class="form-row"><span class="form-label">Target 总并发</span><input class="input" id="target-concurrency" type="number" min="1" step="1" value="' + target.target_total_concurrency + '" /></label>' +
        '<label class="form-row form-row-full"><span class="form-label">Headers（JSON 对象）</span><textarea class="input execution-code-input" id="target-headers" rows="5">' + esc(JSON.stringify(target.headers || {}, null, 2)) + '</textarea></label>' +
        '<div class="execution-form-error form-row-full hidden" id="target-form-error" role="alert"></div>' +
    '</div>';
}

function readTargetForm() {
    var name = document.getElementById('target-name').value.trim();
    var baseUrl = document.getElementById('target-base-url').value.trim();
    var path = document.getElementById('target-path').value.trim();
    var concurrency = Number(document.getElementById('target-concurrency').value);
    if (!name) throw new Error('名称不能为空');
    if (!baseUrl) throw new Error('Base URL 不能为空');
    if (!path) throw new Error('Path 不能为空');
    if (!Number.isInteger(concurrency) || concurrency < 1) throw new Error('Target 总并发必须是正整数');
    var headers;
    try {
        headers = JSON.parse(document.getElementById('target-headers').value || '{}');
    } catch (error) {
        throw new Error('Headers 必须是合法 JSON 对象');
    }
    if (!headers || Array.isArray(headers) || typeof headers !== 'object') throw new Error('Headers 必须是 JSON 对象');
    Object.keys(headers).forEach(function (key) {
        if (typeof headers[key] !== 'string') throw new Error('Header 值必须是字符串：' + key);
    });
    return {
        name: name, base_url: baseUrl, path: path, method: 'POST', headers: headers,
        target_total_concurrency: concurrency,
    };
}

function showTargetFormError(message) {
    var error = document.getElementById('target-form-error');
    error.textContent = message;
    error.classList.remove('hidden');
}

function openTargetEditor(targetId) {
    var target = executionState.targets.find(function (item) { return item.id === targetId; });
    executionState.editingTargetId = target ? target.id : null;
    openExecutionModal(target ? '编辑 Target' : '新增 Target', targetFormHtml(target), async function () {
        var body;
        try {
            body = readTargetForm();
        } catch (error) {
            showTargetFormError(error.message);
            return;
        }
        try {
            if (executionState.editingTargetId) {
                await API.put('/api/targets/' + encodeURIComponent(executionState.editingTargetId), body);
            } else {
                await API.post('/api/targets', body);
            }
            closeExecutionModal();
            showToast(target ? 'Target 已更新' : 'Target 已创建', 'success');
            await loadTargets();
        } catch (error) {
            showTargetFormError(executionErrorMessage(error));
        }
    });
}

async function deleteTarget(targetId) {
    var target = executionState.targets.find(function (item) { return item.id === targetId; });
    if (!target || !window.confirm('确定删除 Target“' + target.name + '”吗？')) return;
    try {
        await API.del('/api/targets/' + encodeURIComponent(targetId));
        showToast('Target 已删除', 'success');
        await loadTargets();
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
    }
}

function filteredWorkflows() {
    var search = document.getElementById('workflow-search');
    var query = search ? search.value.trim().toLowerCase() : '';
    return executionState.workflows.filter(function (workflow) {
        return !query || (workflow.name + ' ' + (workflow.description || '')).toLowerCase().includes(query);
    });
}

function renderWorkflowTable() {
    var body = document.getElementById('workflow-list-body');
    var count = document.getElementById('workflow-count');
    if (!body || !count) return;
    var workflows = filteredWorkflows();
    count.textContent = executionState.workflows.length + ' 个 Workflow';
    if (!workflows.length) {
        body.innerHTML = '<tr><td colspan="5">' + executionEmpty(
            executionState.workflows.length ? '没有匹配的 Workflow' : '尚未创建 Workflow',
            executionState.workflows.length ? '' : '新建 Workflow', 'workflow-empty-add'
        ) + '</td></tr>';
        var emptyAdd = document.getElementById('workflow-empty-add');
        if (emptyAdd) emptyAdd.addEventListener('click', openWorkflowCreateDialog);
        return;
    }
    body.innerHTML = workflows.map(function (workflow) {
        return '<tr><td><button class="execution-name-button" type="button" data-workflow-edit="' + esc(workflow.id) + '">' + esc(workflow.name) + '</button>' +
            '<div class="execution-id">' + esc(workflow.id) + '</div></td>' +
            '<td>' + esc(workflow.description || '—') + '</td>' +
            '<td><span class="execution-badge workflow-valid">已持久化</span></td>' +
            '<td>' + esc(formatDateTime(workflow.updated_at)) + '</td>' +
            '<td><button class="btn-icon" type="button" data-workflow-edit="' + esc(workflow.id) + '" title="编辑 Workflow">' + icon('edit') + '</button></td></tr>';
    }).join('');
    body.querySelectorAll('[data-workflow-edit]').forEach(function (button) {
        button.addEventListener('click', function () { openWorkflowEditor(button.getAttribute('data-workflow-edit')); });
    });
}

async function loadWorkflows() {
    try {
        var data = await API.get('/api/workflows');
        executionState.workflows = (data.workflows || []).map(normalizeWorkflowRecord);
        renderWorkflowTable();
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
    }
}

function viewWorkflows() {
    currentView = 'workflows';
    contentArea.innerHTML =
        '<section class="execution-page workflow-management-page" aria-label="工作流管理">' +
            '<div class="toolbar execution-toolbar" id="workflows-toolbar">' +
                '<button class="btn btn-sm btn-primary" id="btn-workflow-add" type="button">' + icon('add') + '新增工作流</button>' +
                '<button class="btn btn-sm" id="btn-workflow-refresh" type="button">' + icon('refresh') + '刷新</button>' +
                '<input type="search" class="input toolbar-search" id="workflow-search" placeholder="按名称搜索..." aria-label="搜索工作流" />' +
                '<select class="input toolbar-control" id="workflow-status-filter" aria-label="筛选工作流状态" disabled><option>已持久化</option></select>' +
                '<span class="toolbar-sep"></span><span class="execution-count workflow-list-count" id="workflow-count">0 个 Workflow</span>' +
            '</div>' +
            '<div class="table-wrap" id="workflows-table-wrap"><table class="table workflow-table" id="workflows-table">' +
                '<thead><tr><th>名称</th><th>说明</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead>' +
                '<tbody id="workflow-list-body"></tbody>' +
            '</table></div>' +
        '</section>';
    document.getElementById('btn-workflow-add').addEventListener('click', openWorkflowCreateDialog);
    document.getElementById('btn-workflow-refresh').addEventListener('click', loadWorkflows);
    document.getElementById('workflow-search').addEventListener('input', renderWorkflowTable);
    loadWorkflows();
}

function workflowCreateFormHtml() {
    return '<div class="execution-form-grid">' +
        '<label class="form-row form-row-full"><span class="form-label">名称 <b class="required">*</b></span><input class="input" id="workflow-create-name" maxlength="120" autocomplete="off" /></label>' +
        '<label class="form-row form-row-full"><span class="form-label">说明</span><textarea class="input execution-code-input" id="workflow-create-description" maxlength="2000" rows="5"></textarea></label>' +
        '<div class="execution-form-error form-row-full hidden" id="workflow-create-error" role="alert"></div>' +
    '</div>';
}

function showWorkflowCreateError(message) {
    var error = document.getElementById('workflow-create-error');
    error.textContent = message;
    error.classList.remove('hidden');
}

function openWorkflowCreateDialog() {
    openExecutionModal('新增工作流', workflowCreateFormHtml(), async function () {
        var nameInput = document.getElementById('workflow-create-name');
        var name = nameInput.value.trim();
        var description = document.getElementById('workflow-create-description').value.trim();
        if (!name) {
            showWorkflowCreateError('名称不能为空');
            nameInput.focus();
            return;
        }
        closeExecutionModal();
        await openWorkflowEditor(null, {name: name, description: description});
    }, '创建');
}

function rememberWorkflow(workflow) {
    workflow = normalizeWorkflowRecord(workflow);
    var existingIndex = executionState.workflows.findIndex(function (item) {
        return item.id === workflow.id;
    });
    if (existingIndex >= 0) executionState.workflows[existingIndex] = workflow;
    else executionState.workflows.unshift(workflow);
}

function normalizeWorkflowRecord(workflow) {
    return Object.assign({}, workflow, {id: workflow.workflow_id || workflow.id});
}

function outputType(value) {
    var normalized = String(value || 'string').toLowerCase();
    return ['string', 'number', 'integer', 'boolean', 'object', 'array', 'null'].includes(normalized) ? normalized : 'string';
}

function outputDefinitions(data, http) {
    return (data.outputVariables || []).filter(function (row) { return String(row.name || '').trim(); }).map(function (row) {
        var output = {name: String(row.name).trim().toLowerCase(), type: outputType(row.type)};
        if (http) output.path = String(row.value || '$.response.body').trim();
        return output;
    });
}

function executionDefinition(data) {
    return {
        timeout_ms: Math.max(1, Math.round(Number(data.timeoutMs) || 120000)),
        max_attempts: Math.max(0, Math.min(10, Math.round(Number(data.retryCount) || 0))),
        delay_ms: Math.max(0, Math.min(600000, Math.round(Number(data.retryIntervalMs) || 0))),
    };
}

function canvasNodeToContract(node, globalVariables) {
    var data = node.data || {};
    var type = String(data.nodeType || '').toUpperCase();
    var base = {id: node.id, type: type, name: String(data.label || type).trim(), description: String(data.description || '').trim()};
    if (type === 'START') {
        base.inputs = (globalVariables || []).filter(function (row) { return String(row.name || '').trim(); }).map(function (row) {
            return {name: String(row.name).trim().toLowerCase(), type: outputType(row.type), data: row.value};
        });
        return base;
    }
    if (type === 'END') return base;
    if (type === 'SCRIPT') {
        base.script = String(data.mainPy || '');
        base.execution = executionDefinition(data);
        base.outputs = outputDefinitions(data, false);
        return base;
    }
    if (type === 'LLM') {
        var parameters = Object.assign({}, data.modelParameters || {});
        var stream = parameters.stream === true;
        delete parameters.stream;
        base.model = {provider_id: String(data.providerId || '').trim(), model_name: String(data.modelName || '').trim()};
        base.prompt = {system: String(data.systemPrompt || ''), user: String(data.userPrompt || '')};
        base.generation = {stream: stream, parameters: parameters};
        base.execution = executionDefinition(data);
        base.outputs = outputDefinitions(data, false).slice(0, 1);
        return base;
    }
    if (type === 'HTTP') {
        var config = data.httpConfig || {};
        var bodyType = String(config.bodyType || 'none').replace(/-/g, '_');
        var content = null;
        if (bodyType === 'raw') {
            try { content = JSON.parse(config.bodyText || ''); } catch (_error) { content = String(config.bodyText || ''); }
        } else if (bodyType === 'form_data' || bodyType === 'form_urlencoded') {
            content = (config.bodyFields || []).map(function (row) { return {key: row.key || '', value: row.value || ''}; });
        }
        base.request = {
            method: String(config.method || 'GET').toUpperCase(),
            url: String(config.url || ''),
            follow_redirects: config.followRedirects !== false,
            headers: (config.headers || []).filter(function (row) { return row.key; }).map(function (row) { return {key: row.key, value: String(row.value || '')}; }),
            params: (config.params || []).filter(function (row) { return row.key; }).map(function (row) { return {key: row.key, value: row.value}; }),
            body: {type: bodyType, content: content},
        };
        base.network = {proxy: {mode: String(config.proxyMode || 'SYSTEM').toUpperCase(), url: String(config.proxyMode || 'SYSTEM').toUpperCase() === 'CUSTOM' ? String(config.proxyUrl || '') : null, username: String(config.proxyMode || 'SYSTEM').toUpperCase() === 'CUSTOM' ? String(config.proxyUsername || '') || null : null, password: String(config.proxyMode || 'SYSTEM').toUpperCase() === 'CUSTOM' ? String(config.proxyPassword || '') || null : null}, verify_ssl: config.verifySsl !== false};
        base.response = {body_type: String(config.responseBodyType || 'json')};
        base.execution = executionDefinition(data);
        base.outputs = outputDefinitions(data, true);
        return base;
    }
    throw new Error('当前 Workflow 契约暂不支持节点类型: ' + type);
}

function canvasDraftToContract(draft) {
    var workflowId = draft.id || window.crypto.randomUUID();
    return {
        workflow_id: workflowId,
        name: draft.name,
        description: draft.description || '',
        nodes: (draft.nodes || []).map(function (node) { return canvasNodeToContract(node, draft.global_variables || []); }),
        edges: (draft.edges || []).map(function (edge) { return {edge_id: edge.id, source: edge.source, target: edge.target}; }),
    };
}

function contractToCanvasDraft(workflow) {
    var start = (workflow.nodes || []).find(function (node) { return node.type === 'START'; });
    return {
        name: workflow.name,
        description: workflow.description || '',
        nodes: (workflow.nodes || []).map(function (node) {
            var data = {nodeType: node.type, label: node.name, description: node.description || '', timeoutMs: node.execution ? node.execution.timeout_ms : 120000, retryCount: node.execution ? node.execution.max_attempts : 0, retryIntervalMs: node.execution ? node.execution.delay_ms : 0};
            if (node.type === 'SCRIPT') { data.mainPy = node.script; data.outputVariables = (node.outputs || []).map(function (item) { return {id: window.crypto.randomUUID(), name: item.name, type: item.type, value: ''}; }); }
            if (node.type === 'LLM') { data.providerId = node.model.provider_id; data.modelName = node.model.model_name; data.systemPrompt = node.prompt.system; data.userPrompt = node.prompt.user; data.modelParameters = Object.assign({}, node.generation.parameters, {stream: node.generation.stream}); data.outputVariables = (node.outputs || []).map(function (item) { return {id: window.crypto.randomUUID(), name: item.name, type: item.type, value: ''}; }); }
            if (node.type === 'HTTP') { data.httpConfig = {method: node.request.method, url: node.request.url, headers: node.request.headers, params: node.request.params, bodyType: node.request.body.type.replace(/_/g, '-'), bodyText: typeof node.request.body.content === 'string' ? node.request.body.content : JSON.stringify(node.request.body.content, null, 2), bodyFields: Array.isArray(node.request.body.content) ? node.request.body.content : [], followRedirects: node.request.follow_redirects !== false, proxyMode: node.network.proxy.mode, proxyUrl: node.network.proxy.url || '', proxyUsername: node.network.proxy.username || '', proxyPassword: node.network.proxy.password || '', verifySsl: node.network.verify_ssl !== false, responseBodyType: node.response.body_type}; data.outputVariables = (node.outputs || []).map(function (item) { return {id: window.crypto.randomUUID(), name: item.name, type: item.type, value: item.path}; }); }
            return {id: node.id, type: 'workflowNode', data: data};
        }),
        edges: (workflow.edges || []).map(function (edge) { return {id: edge.edge_id, source: edge.source, target: edge.target, type: 'insertable'}; }),
        global_variables: start ? (start.inputs || []).map(function (item) { return {id: window.crypto.randomUUID(), name: item.name, type: item.type, value: item.data}; }) : [],
    };
}

async function openWorkflowEditor(workflowId, initialMetadata) {
    currentView = 'workflows';
    if (!window.AgentBenchWorkflowCanvas) {
        showToast('工作流画布资源加载失败', 'error');
        return;
    }
    var workflow = null;
    if (workflowId) {
        try {
            workflow = (await API.get('/api/workflows/' + encodeURIComponent(workflowId))).workflow;
        } catch (error) {
            showToast(executionErrorMessage(error), 'error');
            return;
        }
    }
    window.AgentBenchWorkflowCanvas.mount({
        id: workflowId || null,
        name: workflow ? workflow.name : initialMetadata.name,
        description: workflow ? workflow.description : initialMetadata.description,
        draft: workflow ? contractToCanvasDraft(workflow) : null,
        createOnMount: false,
        onPersist: async function (draft) {
            var body = canvasDraftToContract(draft);
            var data = draft.id
                ? await API.put('/api/workflows/' + encodeURIComponent(draft.id), body)
                : await API.post('/api/workflows', body);
            workflow = normalizeWorkflowRecord(data.workflow);
            rememberWorkflow(workflow);
            return workflow;
        },
        onPersistMetadata: async function (metadata) {
            var body = Object.assign({}, workflow, {name: metadata.name, description: metadata.description});
            delete body.created_at;
            delete body.updated_at;
            var data = await API.put('/api/workflows/' + encodeURIComponent(metadata.id), body);
            workflow = normalizeWorkflowRecord(data.workflow);
            rememberWorkflow(workflow);
            return workflow;
        },
        onClose: function () {
            window.setTimeout(function () {
                window.AgentBenchWorkflowCanvas.unmount();
                viewWorkflows();
            }, 0);
        },
    });
}
