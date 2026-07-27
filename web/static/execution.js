/* Target management and Workflow Structural Model UI. */
var executionState = {
    targets: [],
    editingTargetId: null,
    workflows: [],
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

function workflowOutputRows(outputs) {
    var rows = (outputs || []).map(function (output) {
        return {id: crypto.randomUUID(), name: output.name, type: output.type, value: output.source};
    });
    return rows.length ? rows : [{id: crypto.randomUUID(), name: '', type: 'string', value: ''}];
}

function workflowLlmMessages(messages) {
    var source = messages && messages.length ? messages : [
        {role: 'SYSTEM', content: ''},
        {role: 'USER', content: ''},
    ];
    return source.map(function (message) {
        return {
            id: crypto.randomUUID(),
            role: message.role,
            content: message.content || '',
            fixed: false,
        };
    }).map(function (message, index) {
        message.fixed = index < 2;
        return message;
    });
}

function workflowHttpValueRow(row) {
    var text = typeof row.value === 'string' ? row.value : JSON.stringify(row.value);
    return {
        id: crypto.randomUUID(),
        key: row.key,
        value: text,
        originalValue: row.value,
        originalText: text,
    };
}

function workflowHttpRowValue(row) {
    if (
        Object.prototype.hasOwnProperty.call(row, 'originalValue')
        && row.value === row.originalText
    ) return row.originalValue;
    return row.value;
}

function workflowNodeData(node) {
    var base = {
        nodeType: node.type,
        label: node.name,
        description: node.description || '',
        timeoutSeconds: node.execution ? node.execution.timeout_seconds : 600,
        retryCount: node.execution && node.execution.max_attempts || 0,
        retryIntervalSeconds: node.execution ? node.execution.retry_interval_seconds : 0,
        delaySeconds: node.execution ? node.execution.delay_seconds : 0,
        outputVariables: workflowOutputRows(node.outputs),
        parameterRecords: [],
    };
    if (node.type === 'START') {
        base.startInputs = (node.inputs || []).map(function (input) {
            return {
                id: crypto.randomUUID(), name: input.name, type: input.type,
                value: input.type === 'string' ? input.value : JSON.stringify(input.value),
            };
        });
        if (!base.startInputs.length) base.startInputs = [{id: crypto.randomUUID(), name: '', type: 'string', value: ''}];
    } else if (node.type === 'SCRIPT') {
        base.mainPy = node.script;
    } else if (node.type === 'LLM') {
        base.providerId = node.model.provider_id;
        base.modelName = node.model.model_name;
        base.llmMessages = workflowLlmMessages(node.context && node.context.messages);
        base.modelParameters = node.generation.parameters || {};
        base.modelParametersText = node.generation.parameters_text || '';
    } else if (node.type === 'HTTP') {
        var bodyType = {form_data: 'form-data', form_urlencoded: 'x-www-form-urlencoded'}[node.request.body.type] || node.request.body.type;
        base.httpConfig = {
            method: node.request.method,
            url: node.request.url,
            headers: (node.request.headers || []).map(function (row) { return {id: crypto.randomUUID(), key: row.key, value: row.value}; }),
            params: (node.request.params || []).map(workflowHttpValueRow),
            bodyType: bodyType,
            bodyText: bodyType === 'raw' ? JSON.stringify(node.request.body.content, null, 2) : '',
            bodyFields: ['form-data', 'x-www-form-urlencoded'].indexOf(bodyType) >= 0
                ? (node.request.body.content || []).map(workflowHttpValueRow) : [],
            followRedirects: node.request.follow_redirects,
            proxyMode: node.network.proxy.mode,
            proxyUrl: node.network.proxy.url || '',
            proxyUsername: node.network.proxy.username || '',
            proxyPassword: node.network.proxy.password || '',
            verifySsl: node.network.verify_ssl,
            responseBodyType: String(node.response.mode || 'AUTO').toLowerCase(),
            successStatuses: node.response.success_statuses.slice(),
            retryNonIdempotent: node.execution.retry_non_idempotent,
            retryStatuses: node.execution.retry_statuses.slice(),
        };
    }
    return base;
}

function workflowRecordToCanvas(record) {
    var structural = record.workflow;
    var bindings = new Map((structural.nodes || []).map(function (item) { return [item.node_id, item]; }));
    return {
        id: structural.id,
        name: structural.name,
        description: structural.description,
        draft: {
            description: structural.description,
            nodes: (record.node_models || []).map(function (node) {
                var binding = bindings.get(node.id);
                return {
                    id: node.id,
                    type: 'workflowNode',
                    position: {x: binding.position_x, y: binding.position_y},
                    data: workflowNodeData(node),
                };
            }),
            edges: (structural.edges || []).map(function (edge) {
                return {id: edge.id, source: edge.source_node_id, target: edge.target_node_id, type: 'insertable'};
            }),
        },
    };
}

function parseStartValue(row) {
    var text = String(row.value === undefined || row.value === null ? '' : row.value);
    if (row.type === 'string') return text;
    if (row.type === 'null') {
        if (text.trim() && text.trim() !== 'null') throw new Error('START 变量 ' + row.name + ' 的 null 值必须填写 null 或留空');
        return null;
    }
    var value;
    try { value = JSON.parse(text); } catch (_error) { throw new Error('START 变量 ' + row.name + ' 的值不是合法 JSON'); }
    var valid = (
        (row.type === 'integer' && Number.isInteger(value)) ||
        (row.type === 'number' && typeof value === 'number' && Number.isFinite(value)) ||
        (row.type === 'boolean' && typeof value === 'boolean') ||
        (row.type === 'object' && value && typeof value === 'object' && !Array.isArray(value)) ||
        (row.type === 'array' && Array.isArray(value))
    );
    if (!valid) throw new Error('START 变量 ' + row.name + ' 的值与类型 ' + row.type + ' 不匹配');
    return value;
}

function outputBindings(node) {
    return (node.data.outputVariables || []).filter(function (row) {
        return String(row.name || '').trim() || String(row.value || '').trim();
    }).map(function (row) {
        if (!String(row.name || '').trim()) throw new Error(node.data.label + ' 的输出变量名不能为空');
        if (!String(row.value || '').trim()) throw new Error(node.data.label + ' 的输出 source 不能为空');
        return {name: row.name, type: row.type || 'string', source: row.value};
    });
}

function filteredKeyValueRows(rows, label) {
    return (rows || []).filter(function (row) { return row.key || row.value; }).map(function (row) {
        if (!row.key) throw new Error(label + ' 的 key 不能为空');
        return {key: row.key, value: row.value};
    });
}

function filteredHttpValueRows(rows, label) {
    return (rows || []).filter(function (row) { return row.key || row.value; }).map(function (row) {
        if (!row.key) throw new Error(label + ' 的 key 不能为空');
        return {key: row.key, value: workflowHttpRowValue(row)};
    });
}

function workflowCanvasNode(node) {
    var data = node.data || {};
    var common = {id: node.id, type: data.nodeType, name: data.label, description: data.description || ''};
    if (!String(common.name || '').trim()) throw new Error('节点名称不能为空');
    if (data.nodeType === 'START') {
        var inputs = (data.startInputs || []).filter(function (row) { return row.name || String(row.value || '').trim(); }).map(function (row) {
            if (!String(row.name || '').trim()) throw new Error('START 变量名不能为空');
            return {name: row.name, type: row.type, value: parseStartValue(row)};
        });
        return Object.assign(common, {inputs: inputs});
    }
    if (data.nodeType === 'END') return common;
    var timeoutSeconds = Number(data.timeoutSeconds);
    var maxAttempts = Number(data.retryCount);
    var retryIntervalSeconds = Number(data.retryIntervalSeconds);
    var delaySeconds = Number(data.delaySeconds);
    if (!Number.isFinite(timeoutSeconds) || timeoutSeconds < 0.001) throw new Error(data.label + ' 的单次超时必须大于等于 0.001 秒');
    if (!Number.isInteger(maxAttempts) || maxAttempts < 0 || maxAttempts > 10) throw new Error(data.label + ' 的最大重试次数必须是 0 到 10 的整数');
    if (!Number.isFinite(retryIntervalSeconds) || retryIntervalSeconds < 0 || retryIntervalSeconds > 600) throw new Error(data.label + ' 的重试间隔必须是 0 到 600 秒');
    if (!Number.isFinite(delaySeconds) || delaySeconds < 0 || delaySeconds > 600) throw new Error(data.label + ' 的延迟执行必须是 0 到 600 秒');
    var execution = {
        timeout_seconds: timeoutSeconds,
        max_attempts: maxAttempts,
        retry_interval_seconds: retryIntervalSeconds,
        delay_seconds: delaySeconds,
    };
    if (data.nodeType === 'SCRIPT') {
        return Object.assign(common, {script: data.mainPy || '', execution: execution, outputs: outputBindings(node)});
    }
    if (data.nodeType === 'LLM') {
        var parameters = Object.assign({}, data.modelParameters || {});
        delete parameters.stream;
        return Object.assign(common, {
            model: {provider_id: data.providerId || '', model_name: data.modelName || ''},
            context: {
                messages: (data.llmMessages && data.llmMessages.length ? data.llmMessages : workflowLlmMessages([])).map(function (message) {
                    return {role: message.role, content: message.content || ''};
                }),
            },
            generation: {parameters: parameters, parameters_text: data.modelParametersText || ''}, execution: execution, outputs: outputBindings(node),
        });
    }
    if (data.nodeType === 'HTTP') {
        var config = data.httpConfig || {};
        var bodyType = {'form-data': 'form_data', 'x-www-form-urlencoded': 'form_urlencoded'}[config.bodyType] || config.bodyType;
        var bodyContent = null;
        if (bodyType === 'raw') {
            try { bodyContent = JSON.parse(config.bodyText); } catch (_error) { throw new Error(data.label + ' 的 Raw Body 必须是合法 JSON'); }
        } else if (bodyType === 'form_data' || bodyType === 'form_urlencoded') {
            bodyContent = filteredHttpValueRows(config.bodyFields, data.label + ' Body');
        }
        return Object.assign(common, {
            request: {
                method: config.method, url: String(config.url || '').trim(), follow_redirects: Boolean(config.followRedirects),
                headers: filteredKeyValueRows(config.headers, data.label + ' Header'),
                params: filteredHttpValueRows(config.params, data.label + ' Query'),
                body: {type: bodyType || 'none', content: bodyContent},
            },
            network: {proxy: {
                mode: config.proxyMode || 'SYSTEM',
                url: config.proxyMode === 'CUSTOM' ? config.proxyUrl || null : null,
                username: config.proxyMode === 'CUSTOM' ? config.proxyUsername || null : null,
                password: config.proxyMode === 'CUSTOM' ? config.proxyPassword || null : null,
            }, verify_ssl: config.verifySsl !== false},
            response: {
                mode: String(config.responseBodyType || 'auto').toUpperCase(),
                success_statuses: config.successStatuses || ['200-299'],
            },
            execution: Object.assign(execution, {
                retry_non_idempotent: Boolean(config.retryNonIdempotent),
                retry_statuses: config.retryStatuses || [408, 429, 500, 502, 503, 504],
            }),
            outputs: outputBindings(node),
        });
    }
    throw new Error('不支持的节点类型: ' + data.nodeType);
}

function workflowCanvasSaveBody(draft) {
    return {
        name: draft.name,
        description: draft.description || '',
        nodes: (draft.nodes || []).map(function (node) {
            return {node: workflowCanvasNode(node), position_x: node.position.x, position_y: node.position.y};
        }),
        edges: (draft.edges || []).map(function (edge) {
            return {id: edge.id, source_node_id: edge.source, target_node_id: edge.target};
        }),
    };
}

function renderWorkflowTable() {
    var body = document.getElementById('workflow-list-body');
    var count = document.getElementById('workflow-count');
    if (!body || !count) return;
    count.textContent = executionState.workflows.length + ' 个 Workflow';
    if (!executionState.workflows.length) {
        body.innerHTML = '<tr><td colspan="4">' + executionEmpty('尚未创建 Workflow', '新增 Workflow', 'workflow-empty-add') + '</td></tr>';
        document.getElementById('workflow-empty-add').addEventListener('click', function () { openWorkflowCanvas(); });
        return;
    }
    body.innerHTML = executionState.workflows.map(function (workflow) {
        return '<tr>' +
            '<td><button class="execution-name-button" type="button" data-workflow-open="' + esc(workflow.id) + '">' + esc(workflow.name) + '</button></td>' +
            '<td class="workflow-description-cell">' + esc(workflow.description || '—') + '</td>' +
            '<td>' + esc(formatDateTime(workflow.updated_at)) + '</td>' +
            '<td><div class="execution-row-actions">' +
                '<button class="btn-icon" type="button" data-workflow-open="' + esc(workflow.id) + '" title="编辑 Workflow" aria-label="编辑 Workflow">' + icon('edit') + '</button>' +
                '<button class="btn-icon" type="button" data-workflow-delete="' + esc(workflow.id) + '" title="删除 Workflow" aria-label="删除 Workflow">' + icon('trash') + '</button>' +
            '</div></td></tr>';
    }).join('');
    body.querySelectorAll('[data-workflow-open]').forEach(function (button) {
        button.addEventListener('click', function () { openWorkflowCanvas(button.getAttribute('data-workflow-open')); });
    });
    body.querySelectorAll('[data-workflow-delete]').forEach(function (button) {
        button.addEventListener('click', function () { deleteWorkflow(button.getAttribute('data-workflow-delete')); });
    });
}

async function loadWorkflows() {
    try {
        var payload = await API.get('/api/workflows');
        executionState.workflows = payload.workflows || [];
        renderWorkflowTable();
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
    }
}

function viewWorkflows() {
    currentView = 'workflows';
    contentArea.innerHTML =
        '<section class="execution-page" aria-labelledby="workflows-title">' +
            '<header class="execution-page-header"><div><h1 id="workflows-title">Workflow 管理</h1><p>开发、保存和手动验证工作流结构</p></div><span class="execution-count" id="workflow-count">0 个 Workflow</span></header>' +
            '<div class="toolbar execution-toolbar" id="workflows-toolbar">' +
                '<button class="btn btn-primary" id="btn-workflow-add" type="button">' + icon('add') + '新增 Workflow</button>' +
                '<button class="btn" id="btn-workflow-refresh" type="button">' + icon('refresh') + '刷新</button>' +
            '</div>' +
            '<div class="table-wrap execution-table-wrap"><table class="table execution-table workflow-table"><thead><tr><th>名称</th><th>说明</th><th>更新时间</th><th>操作</th></tr></thead><tbody id="workflow-list-body"></tbody></table></div>' +
        '</section>';
    document.getElementById('btn-workflow-add').addEventListener('click', function () { openWorkflowCanvas(); });
    document.getElementById('btn-workflow-refresh').addEventListener('click', loadWorkflows);
    loadWorkflows();
}

async function openWorkflowCanvas(workflowId) {
    if (!window.AgentBenchWorkflowCanvas) {
        showToast('Workflow 画布资源未加载', 'error');
        return;
    }
    var options = {name: '未命名工作流', description: '', draft: null, createOnMount: false, executionEnabled: true};
    try {
        if (workflowId) {
            var payload = await API.get('/api/workflows/' + encodeURIComponent(workflowId));
            options = workflowRecordToCanvas(payload.workflow);
            options.executionEnabled = true;
        }
        options.onPersist = async function (draft) {
            var body = workflowCanvasSaveBody(draft);
            var result = draft.id
                ? await API.put('/api/workflows/' + encodeURIComponent(draft.id), body)
                : await API.post('/api/workflows', body);
            var record = result.workflow;
            return {id: record.workflow.id, name: record.workflow.name, description: record.workflow.description};
        };
        options.onPersistMetadata = async function (metadata) {
            var result = await API.put('/api/workflows/' + encodeURIComponent(metadata.id) + '/metadata', {
                name: metadata.name, description: metadata.description,
            });
            var record = result.workflow;
            return {id: record.workflow.id, name: record.workflow.name, description: record.workflow.description};
        };
        options.serializeNode = workflowCanvasNode;
        options.onClose = function () {
            window.AgentBenchWorkflowCanvas.unmount();
            viewWorkflows();
        };
        window.AgentBenchWorkflowCanvas.mount(options);
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
    }
}

function deleteWorkflow(workflowId) {
    var workflow = executionState.workflows.find(function (item) { return item.id === workflowId; });
    if (!workflow) return;
    openExecutionModal(
        '删除 Workflow',
        '<p>确定删除 Workflow“<strong>' + esc(workflow.name) + '</strong>”吗？</p><p class="info-text" style="margin-top:8px">当前节点和连线将一并删除。</p>',
        async function () {
            try {
                await API.del('/api/workflows/' + encodeURIComponent(workflowId));
                closeExecutionModal();
                showToast('Workflow 已删除', 'success');
                await loadWorkflows();
            } catch (error) {
                showToast(executionErrorMessage(error), 'error');
            }
        },
        '删除'
    );
}
