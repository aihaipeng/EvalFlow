/* Workflow Structural Model UI. */
var executionState = {
    workflows: [],
    batches: [],
    batchPoll: null,
    batchPreviewRequestId: 0,
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
    overlay.querySelector('#execution-modal-cancel').style.display = '';
    save.textContent = saveLabel || '保存';
    save.disabled = false;
    save.onclick = async function () {
        save.disabled = true;
        try {
            await onSave();
        } catch (error) {
            showToast(executionErrorMessage(error), 'error');
        } finally {
            save.disabled = false;
        }
    };
    overlay.classList.remove('hidden');
    var focusable = overlay.querySelector('input, select, textarea');
    if (focusable) focusable.focus();
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

function parseHttpJsonTemplate(text) {
    var inString = false;
    var escaped = false;
    var normalized = '';
    for (var index = 0; index < String(text || '').length;) {
        var character = text[index];
        if (inString) {
            normalized += character;
            if (escaped) escaped = false;
            else if (character === '\\') escaped = true;
            else if (character === '"') inString = false;
            index += 1;
            continue;
        }
        if (character === '"') {
            inString = true;
            normalized += character;
            index += 1;
            continue;
        }
        var reference = text.slice(index).match(/^\$\{[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[0-9]+\])*\}/);
        if (reference) {
            normalized += JSON.stringify(reference[0]);
            index += reference[0].length;
            continue;
        }
        normalized += character;
        index += 1;
    }
    return JSON.parse(normalized);
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
            bodyText: bodyType === 'raw'
                ? (node.request.body.template_text != null ? node.request.body.template_text : JSON.stringify(node.request.body.content, null, 2))
                : '',
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
    if (data.nodeType === 'END') return Object.assign(common, {outputs: outputBindings(node)});
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
        var bodyTemplateText = null;
        if (bodyType === 'raw') {
            try { parseHttpJsonTemplate(config.bodyText); } catch (_error) { throw new Error(data.label + ' 的 Raw Body 必须是合法 JSON 模板'); }
            bodyTemplateText = String(config.bodyText || '');
        } else if (bodyType === 'form_data' || bodyType === 'form_urlencoded') {
            bodyContent = filteredHttpValueRows(config.bodyFields, data.label + ' Body');
        }
        return Object.assign(common, {
            request: {
                method: config.method, url: String(config.url || '').trim(), follow_redirects: Boolean(config.followRedirects),
                headers: filteredKeyValueRows(config.headers, data.label + ' Header'),
                params: filteredHttpValueRows(config.params, data.label + ' Query'),
                body: {type: bodyType || 'none', content: bodyContent, template_text: bodyTemplateText},
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

function batchStatusLabel(status) {
    return {
        QUEUED: '待启动', RUNNING: '运行中', SUCCESS: '成功',
        COMPLETED_WITH_ERRORS: '部分失败', INTERRUPTED: '已中断',
    }[status] || status;
}

function batchStatusClass(status) {
    return 'batch-status batch-status-' + String(status || '').toLowerCase().replaceAll('_', '-');
}

function batchVerdictLabel(verdict) {
    return {PASS: '通过', FAIL: '不通过', ERROR: '校验错误', NOT_EVALUATED: '未校验'}[verdict] || verdict || '未校验';
}

function batchVerdictClass(verdict) {
    return 'batch-verdict is-' + String(verdict || 'NOT_EVALUATED').toLowerCase().replaceAll('_', '-');
}

function batchProgress(batch) {
    var summary = batch.summary || {};
    var done = (summary.success || 0) + (summary.failed || 0) + (summary.interrupted || 0);
    var total = batch.total_cases || 0;
    var percent = total ? Math.round(done * 100 / total) : 0;
    return '<div class="batch-progress"><div><span style="width:' + percent + '%"></span></div>' +
        '<small>' + done + ' / ' + total + '</small></div>';
}

function batchVerdictSummary(batch) {
    var summary = batch.summary || {};
    if (!(batch.evaluation_rules || []).length) return '<span class="batch-verdict is-not-evaluated">未校验</span>';
    return '<span class="batch-verdict is-pass">通过 ' + (summary.pass || 0) + '</span>' +
        '<span class="batch-verdict is-fail">不通过 ' + (summary.fail || 0) + '</span>' +
        '<span class="batch-verdict is-error">错误 ' + (summary.error || 0) + '</span>';
}

function renderBatchTable() {
    var body = document.getElementById('batch-list-body');
    var count = document.getElementById('batch-count');
    if (!body || !count) return;
    count.textContent = executionState.batches.length + ' 个 Run';
    if (!executionState.batches.length) {
        body.innerHTML = '<tr><td colspan="8">' + executionEmpty('尚未创建批量 Run', '创建 Run', 'batch-empty-add') + '</td></tr>';
        document.getElementById('batch-empty-add').addEventListener('click', function () { openBatchCreate(); });
        return;
    }
    body.innerHTML = executionState.batches.map(function (batch) {
        var action = batch.status === 'QUEUED'
            ? '<button class="btn btn-sm btn-primary" data-batch-start="' + batch.id + '">启动</button>'
            : batch.status === 'RUNNING'
                ? '<button class="btn btn-sm btn-danger" data-batch-cancel="' + batch.id + '">取消</button>'
                : batch.status === 'INTERRUPTED'
                    ? '<button class="btn btn-sm" data-batch-resume="' + batch.id + '">恢复</button>'
                    : batch.status === 'COMPLETED_WITH_ERRORS'
                        ? '<button class="btn btn-sm" data-batch-retry="' + batch.id + '">重试失败</button>' : '';
        var edit = '<button class="btn-icon" data-batch-edit="' + batch.id + '" title="编辑并创建新 Run" aria-label="编辑并创建新 Run">' + icon('edit') + '</button>';
        var remove = batch.status === 'RUNNING' ? '' : '<button class="btn-icon" data-batch-delete="' + batch.id + '" title="删除 Run" aria-label="删除 Run">' + icon('trash') + '</button>';
        return '<tr>' +
            '<td><button class="execution-name-button" data-batch-open="' + batch.id + '">' + esc(batch.name) + '</button></td>' +
            '<td>' + esc(batch.input.filename + ' / ' + batch.input.sheet_name) + '</td>' +
            '<td>' + esc(batch.workflow.name) + '</td>' +
            '<td><span class="' + batchStatusClass(batch.status) + '">' + batchStatusLabel(batch.status) + '</span></td>' +
            '<td>' + batchProgress(batch) + '</td>' +
            '<td><div class="batch-verdicts">' + batchVerdictSummary(batch) + '</div></td>' +
            '<td>' + esc(formatDateTime(batch.created_at)) + '</td>' +
            '<td><div class="batch-row-actions"><button class="btn-icon" data-batch-open="' + batch.id + '" title="查看详情" aria-label="查看详情">' + icon('browse') + '</button>' + edit + action + remove + '</div></td>' +
        '</tr>';
    }).join('');
    body.querySelectorAll('[data-batch-open]').forEach(function (button) {
        button.addEventListener('click', function () { viewBatchDetail(button.getAttribute('data-batch-open')); });
    });
    body.querySelectorAll('[data-batch-edit]').forEach(function (button) {
        button.addEventListener('click', function () { openBatchCreate(button.getAttribute('data-batch-edit')); });
    });
    body.querySelectorAll('[data-batch-start]').forEach(function (button) {
        button.addEventListener('click', function () { batchCommand(button, button.getAttribute('data-batch-start'), 'start', {}); });
    });
    body.querySelectorAll('[data-batch-cancel]').forEach(function (button) {
        button.addEventListener('click', function () { batchCommand(button, button.getAttribute('data-batch-cancel'), 'cancel', {}); });
    });
    body.querySelectorAll('[data-batch-resume]').forEach(function (button) {
        button.addEventListener('click', function () { batchCommand(button, button.getAttribute('data-batch-resume'), 'resume', {retry_failed: false}); });
    });
    body.querySelectorAll('[data-batch-retry]').forEach(function (button) {
        button.addEventListener('click', function () { batchCommand(button, button.getAttribute('data-batch-retry'), 'resume', {retry_failed: true}); });
    });
    body.querySelectorAll('[data-batch-delete]').forEach(function (button) {
        button.addEventListener('click', function () { confirmBatchDelete(button.getAttribute('data-batch-delete')); });
    });
}

function confirmBatchDelete(batchId) {
    var batch = executionState.batches.find(function (item) { return item.id === batchId; });
    if (!batch) return;
    openExecutionModal('删除 Run', '<p>确定删除“<strong>' + esc(batch.name) + '</strong>”及其 Batch/Case 输入快照吗？</p>', async function () {
        await API.del('/api/batch-runs/' + encodeURIComponent(batchId));
        closeExecutionModal();
        showToast('Run 已删除', 'success');
        await loadBatchRuns();
    }, '删除');
}

async function batchCommand(button, batchId, command, body) {
    button.disabled = true;
    try {
        await API.post('/api/batch-runs/' + encodeURIComponent(batchId) + '/' + command, body);
        showToast(command === 'cancel' ? '已请求取消 Run' : 'Run 已进入调度', 'success');
        await loadBatchRuns();
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
    } finally {
        button.disabled = false;
    }
}

async function loadBatchRuns() {
    try {
        var payload = await API.get('/api/batch-runs');
        executionState.batches = payload.batches || [];
        renderBatchTable();
        scheduleBatchPoll(executionState.batches.some(function (batch) { return batch.status === 'RUNNING'; }));
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
    }
}

function scheduleBatchPoll(active) {
    if (executionState.batchPoll) clearTimeout(executionState.batchPoll);
    executionState.batchPoll = null;
    if (active && currentView === 'batch-runs') {
        executionState.batchPoll = setTimeout(loadBatchRuns, 1000);
    }
}

function viewBatchRuns() {
    currentView = 'batch-runs';
    scheduleBatchPoll(false);
    contentArea.innerHTML =
        '<section class="execution-page" aria-labelledby="batch-title">' +
            '<header class="execution-page-header"><div><h1 id="batch-title">运行调度</h1><p>按 Excel 行并发执行已保存的 Workflow</p></div><span class="execution-count" id="batch-count">0 个 Run</span></header>' +
            '<div class="toolbar execution-toolbar"><button class="btn btn-primary" id="btn-batch-add">' + icon('add') + '创建 Run</button><button class="btn" id="btn-batch-refresh">' + icon('refresh') + '刷新</button></div>' +
            '<div class="table-wrap execution-table-wrap"><table class="table execution-table batch-table"><thead><tr><th>名称</th><th>测试集 / Sheet</th><th>Workflow</th><th>状态</th><th>进度</th><th>测试判定</th><th>创建时间</th><th>操作</th></tr></thead><tbody id="batch-list-body"></tbody></table></div>' +
        '</section>';
    document.getElementById('btn-batch-add').addEventListener('click', function () { openBatchCreate(); });
    document.getElementById('btn-batch-refresh').addEventListener('click', loadBatchRuns);
    loadBatchRuns();
}

async function openBatchCreate(sourceBatchId) {
    try {
        var requests = [
            API.get('/api/excel/sets?page=1&page_size=200'),
            API.get('/api/workflows'),
        ];
        if (sourceBatchId) requests.push(API.get('/api/batch-runs/' + encodeURIComponent(sourceBatchId)));
        var values = await Promise.all(requests);
        var files = values[0].files || [];
        var workflows = values[1].workflows || [];
        var sourceBatch = values[2] ? values[2].batch : null;
        if (!files.length || !workflows.length) {
            showToast(!files.length ? '请先导入测试集' : '请先创建 Workflow', 'error');
            return;
        }
        var body =
            '<div class="batch-create-grid">' +
                '<label>名称<input class="input" id="batch-name" maxlength="200" placeholder="默认使用测试集和 Workflow 名称" /></label>' +
                '<label>测试集<select class="input" id="batch-file">' + files.map(function (file) { return '<option value="' + esc(file.filename) + '">' + esc(file.name) + '</option>'; }).join('') + '</select></label>' +
                '<label>Sheet<select class="input" id="batch-sheet"></select></label>' +
                '<label>Workflow<select class="input" id="batch-workflow">' + workflows.map(function (workflow) { return '<option value="' + workflow.id + '">' + esc(workflow.name) + '</option>'; }).join('') + '</select></label>' +
                '<label>首行模式<select class="input" id="batch-header-mode"><option value="AUTO">自动识别</option><option value="HEADER">第一行是表头</option><option value="DATA">第一行是数据</option></select></label>' +
                '<label>Case ID 列<select class="input" id="batch-case-id" disabled><option>正在读取表头...</option></select></label>' +
                '<label>Case 并发数<input class="input" id="batch-concurrency" type="number" min="1" max="32" value="4" /></label>' +
            '</div><div class="batch-preview-actions"><button class="btn btn-sm" id="batch-preview" type="button">刷新预览</button><span id="batch-preview-meta">正在读取数据...</span></div>' +
            '<div id="batch-mapping" class="batch-mapping-empty">正在读取表头和样例数据...</div>' +
            '<section class="batch-evaluation"><header><strong>结果校验</strong><button class="btn btn-sm" id="batch-rule-add" type="button">' + icon('add') + '添加规则</button></header><div id="batch-evaluation-rules"></div></section>' +
            '<div id="batch-sample"></div>';
        openExecutionModal(sourceBatch ? '编辑 Run 配置' : '创建批量 Run', body, createBatchFromModal, sourceBatch ? '创建新 Run' : '创建');
        document.querySelector('.execution-modal').classList.add('is-batch-config');
        document.getElementById('execution-modal-save').disabled = true;
        document.getElementById('batch-file').addEventListener('change', function () { loadBatchSheets(); });
        document.getElementById('batch-sheet').addEventListener('change', function () { loadBatchPreview(); });
        document.getElementById('batch-workflow').addEventListener('change', function () { loadBatchPreview(); });
        document.getElementById('batch-header-mode').addEventListener('change', function () { loadBatchPreview(); });
        document.getElementById('batch-case-id').addEventListener('change', function () { loadBatchPreview(); });
        document.getElementById('batch-preview').addEventListener('click', function () { loadBatchPreview(); });
        document.getElementById('batch-rule-add').addEventListener('click', function () { addBatchEvaluationRule(); });
        if (sourceBatch) {
            var fileSelect = document.getElementById('batch-file');
            var workflowSelect = document.getElementById('batch-workflow');
            if (!Array.from(fileSelect.options).some(function (option) { return option.value === sourceBatch.input.filename; })) throw new Error('原 Run 的测试集已不存在');
            if (!Array.from(workflowSelect.options).some(function (option) { return option.value === sourceBatch.workflow.id; })) throw new Error('原 Run 的 Workflow 已不存在');
            document.getElementById('batch-name').value = sourceBatch.name;
            fileSelect.value = sourceBatch.input.filename;
            workflowSelect.value = sourceBatch.workflow.id;
            document.getElementById('batch-header-mode').value = sourceBatch.input.header_mode;
            document.getElementById('batch-concurrency').value = sourceBatch.case_concurrency;
        }
        await loadBatchSheets(sourceBatch);
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
    }
}

function batchRuleDrafts() {
    return Array.from(document.querySelectorAll('.batch-evaluation-rule')).map(function (row) {
        return {
            name: row.querySelector('[data-rule-name]').value,
            actual_path: row.querySelector('[data-rule-actual]').value,
            operator: row.querySelector('[data-rule-operator]').value,
            expected: {
                source: row.querySelector('[data-rule-source]').value,
                value: null,
                literal_text: row.querySelector('[data-rule-literal]').value,
                column: row.querySelector('[data-rule-source]').value === 'EXCEL' ? row.querySelector('[data-rule-column]').value : null,
            },
        };
    });
}

function renderBatchEvaluationRules(rules, headers) {
    var container = document.getElementById('batch-evaluation-rules');
    if (!container) return;
    container.dataset.headers = JSON.stringify(headers || []);
    if (!(rules || []).length) {
        container.innerHTML = '<div class="batch-evaluation-empty">暂无校验规则</div>';
        return;
    }
    var operators = [
        ['EQ', '等于'], ['NE', '不等于'], ['CONTAINS', '包含'], ['REGEX', '正则'],
        ['EXISTS', '存在'], ['GT', '大于'], ['GTE', '大于等于'], ['LT', '小于'],
        ['LTE', '小于等于'], ['JSON_EQUAL', 'JSON 相等'],
    ];
    container.innerHTML = rules.map(function (rule, index) {
        var expected = rule.expected || {source: 'LITERAL', value: '', column: null};
        var literalText = expected.literal_text !== undefined
            ? expected.literal_text
            : typeof expected.value === 'string' ? JSON.stringify(expected.value) : JSON.stringify(expected.value === undefined ? null : expected.value);
        return '<div class="batch-evaluation-rule" data-rule-index="' + index + '">' +
            '<label><span>名称</span><input class="input" data-rule-name value="' + esc(rule.name || '') + '" /></label>' +
            '<label><span>结果路径</span><input class="input" data-rule-actual value="' + esc(rule.actual_path || '') + '" placeholder="例如 answer.text" /></label>' +
            '<label><span>运算符</span><select class="input" data-rule-operator>' + operators.map(function (item) { return '<option value="' + item[0] + '" ' + (item[0] === rule.operator ? 'selected' : '') + '>' + item[1] + '</option>'; }).join('') + '</select></label>' +
            '<label><span>预期来源</span><select class="input" data-rule-source><option value="LITERAL" ' + (expected.source !== 'EXCEL' ? 'selected' : '') + '>固定值</option><option value="EXCEL" ' + (expected.source === 'EXCEL' ? 'selected' : '') + '>Excel 列</option></select></label>' +
            '<label class="batch-rule-expected-literal"><span>预期 JSON</span><input class="input" data-rule-literal value="' + esc(literalText) + '" /></label>' +
            '<label class="batch-rule-expected-column"><span>预期列</span><select class="input" data-rule-column>' + (headers || []).map(function (header) { return '<option value="' + esc(header) + '" ' + (header === expected.column ? 'selected' : '') + '>' + esc(header) + '</option>'; }).join('') + '</select></label>' +
            '<button class="btn-icon" type="button" data-rule-delete title="删除规则" aria-label="删除规则">' + icon('trash') + '</button>' +
        '</div>';
    }).join('');
    container.querySelectorAll('.batch-evaluation-rule').forEach(function (row) {
        var source = row.querySelector('[data-rule-source]');
        var sync = function () {
            row.querySelector('.batch-rule-expected-literal').hidden = source.value === 'EXCEL';
            row.querySelector('.batch-rule-expected-column').hidden = source.value !== 'EXCEL';
        };
        source.addEventListener('change', sync);
        row.querySelector('[data-rule-delete]').addEventListener('click', function () {
            var remaining = batchRuleDrafts().filter(function (_item, index) { return index !== Number(row.dataset.ruleIndex); });
            renderBatchEvaluationRules(remaining, JSON.parse(container.dataset.headers || '[]'));
        });
        sync();
    });
}

function addBatchEvaluationRule() {
    var container = document.getElementById('batch-evaluation-rules');
    var headers = JSON.parse(container.dataset.headers || '[]');
    var rules = batchRuleDrafts();
    rules.push({name: '', actual_path: '', operator: 'EQ', expected: {source: 'LITERAL', value: null, literal_text: 'null', column: null}});
    renderBatchEvaluationRules(rules, headers);
}

async function loadBatchSheets(sourceBatch) {
    var select = document.getElementById('batch-sheet');
    var caseId = document.getElementById('batch-case-id');
    select.disabled = true;
    caseId.disabled = true;
    caseId.innerHTML = '<option>正在读取表头...</option>';
    document.getElementById('execution-modal-save').disabled = true;
    document.getElementById('batch-preview-meta').textContent = '正在读取 Sheet...';
    try {
        var filename = document.getElementById('batch-file').value;
        var payload = await API.get('/api/excel/sheets?filename=' + encodeURIComponent(filename));
        var sheets = payload.sheets || [];
        if (!sheets.length) throw new Error('测试集没有可用 Sheet');
        select.innerHTML = sheets.map(function (sheet) {
            return '<option value="' + esc(sheet.name) + '">' + esc(sheet.name) + '</option>';
        }).join('');
        if (sourceBatch && sheets.some(function (sheet) { return sheet.name === sourceBatch.input.sheet_name; })) select.value = sourceBatch.input.sheet_name;
        select.disabled = false;
        await loadBatchPreview(sourceBatch);
    } catch (error) {
        select.innerHTML = '<option>读取失败</option>';
        caseId.innerHTML = '<option>读取失败</option>';
        document.getElementById('batch-preview-meta').textContent = '读取失败';
        document.getElementById('batch-mapping').className = 'batch-mapping-empty';
        document.getElementById('batch-mapping').textContent = executionErrorMessage(error);
        showToast(executionErrorMessage(error), 'error');
    }
}

async function loadBatchPreview(sourceBatch) {
    var filename = document.getElementById('batch-file').value;
    var sheetName = document.getElementById('batch-sheet').value;
    if (!filename || !sheetName || document.getElementById('batch-sheet').disabled) return;
    var requestId = ++executionState.batchPreviewRequestId;
    var previewButton = document.getElementById('batch-preview');
    var caseIdSelect = document.getElementById('batch-case-id');
    var saveButton = document.getElementById('execution-modal-save');
    var evaluationDrafts = sourceBatch ? (sourceBatch.evaluation_rules || []) : batchRuleDrafts();
    var previousCaseId = sourceBatch ? sourceBatch.input.case_id_column : (caseIdSelect.disabled ? '' : caseIdSelect.value);
    previewButton.disabled = true;
    caseIdSelect.disabled = true;
    saveButton.disabled = true;
    document.getElementById('batch-preview-meta').textContent = '正在读取表头和样例...';
    try {
        var values = await Promise.all([
            API.post('/api/batch-runs/preview', {
                filename: filename,
                sheet_name: sheetName,
                header_mode: document.getElementById('batch-header-mode').value,
            }),
            API.get('/api/workflows/' + encodeURIComponent(document.getElementById('batch-workflow').value)),
        ]);
        if (requestId !== executionState.batchPreviewRequestId) return;
        var preview = values[0];
        var start = (values[1].workflow.node_models || []).find(function (node) { return node.type === 'START'; });
        var inputs = (start && start.inputs) || [];
        var objectRoot = inputs.length === 1 && inputs[0].type === 'object' ? inputs[0].name : '';
        document.getElementById('batch-preview-meta').textContent = preview.total_rows + ' 行 · ' + preview.headers.length + ' 列 · ' + (preview.header_mode === 'HEADER' ? '首行为表头' : '首行为数据');
        caseIdSelect.innerHTML = preview.headers.map(function (header) { return '<option value="' + esc(header) + '">' + esc(header) + '</option>'; }).join('');
        var idIndex = preview.headers.findIndex(function (header) { return ['case_id', 'case id', '用例id', '用例编号', 'id'].includes(header.toLowerCase()); });
        if (previousCaseId && preview.headers.includes(previousCaseId)) caseIdSelect.value = previousCaseId;
        else if (idIndex >= 0) caseIdSelect.selectedIndex = idIndex;
        caseIdSelect.disabled = false;
        var selectedCaseIdHeader = caseIdSelect.value;
        var sourceMappings = new Map((sourceBatch && sourceBatch.mappings || []).map(function (item) { return [item.source, item.target]; }));
        var mapping = document.getElementById('batch-mapping');
        mapping.className = 'batch-mapping';
        mapping.innerHTML = '<div class="batch-mapping-head"><span>启用</span><span>Excel 列</span><span>START 变量或对象字段</span></div>' + preview.headers.map(function (header) {
            var direct = inputs.find(function (input) { return input.name === header; });
            var target = sourceBatch ? (sourceMappings.get(header) || '') : (header === selectedCaseIdHeader ? '' : (direct ? direct.name : (objectRoot ? objectRoot + '.' + header : '')));
            return '<label class="batch-mapping-row"><input type="checkbox" data-map-enabled ' + (target ? 'checked' : '') + ' /><span>' + esc(header) + '</span><input class="input" data-map-target value="' + esc(target) + '" placeholder="例如 input.' + esc(header) + '" /></label>';
        }).join('');
        var sample = preview.sample_rows || [];
        document.getElementById('batch-sample').innerHTML = '<div class="batch-sample-wrap"><table class="table"><thead><tr><th>Excel 行</th>' + preview.headers.map(function (header) { return '<th>' + esc(header) + '</th>'; }).join('') + '</tr></thead><tbody>' + sample.slice(0, 5).map(function (row) {
            return '<tr><td>' + row.row_number + '</td>' + preview.headers.map(function (header) { var value = row.values[header]; return '<td>' + esc(value === null ? 'null' : typeof value === 'object' ? JSON.stringify(value) : String(value)) + '</td>'; }).join('') + '</tr>';
        }).join('') + '</tbody></table></div>';
        renderBatchEvaluationRules(evaluationDrafts, preview.headers);
        saveButton.disabled = false;
    } catch (error) {
        if (requestId !== executionState.batchPreviewRequestId) return;
        caseIdSelect.innerHTML = '<option>读取失败</option>';
        document.getElementById('batch-preview-meta').textContent = '读取失败';
        document.getElementById('batch-mapping').className = 'batch-mapping-empty';
        document.getElementById('batch-mapping').textContent = executionErrorMessage(error);
        showToast(executionErrorMessage(error), 'error');
    } finally {
        if (requestId === executionState.batchPreviewRequestId) previewButton.disabled = false;
    }
}

async function createBatchFromModal() {
    var rows = Array.from(document.querySelectorAll('.batch-mapping-row'));
    if (!rows.length) throw new Error('请先读取并预览测试集');
    var mappings = rows.filter(function (row) { return row.querySelector('[data-map-enabled]').checked; }).map(function (row) {
        return {source: row.querySelector('span').textContent, target: row.querySelector('[data-map-target]').value.trim()};
    });
    if (!mappings.length || mappings.some(function (mapping) { return !mapping.target; })) throw new Error('请至少完成一个有效字段映射');
    var evaluationRules = batchRuleDrafts().map(function (rule, index) {
        if (!rule.name.trim()) throw new Error('校验规则 ' + (index + 1) + ' 的名称不能为空');
        if (!rule.actual_path.trim()) throw new Error('校验规则 ' + (index + 1) + ' 的结果路径不能为空');
        var expected;
        if (rule.expected.source === 'EXCEL') {
            if (!rule.expected.column) throw new Error('校验规则 ' + (index + 1) + ' 必须选择预期列');
            expected = {source: 'EXCEL', value: null, column: rule.expected.column};
        } else {
            var value;
            try { value = JSON.parse(rule.expected.literal_text); } catch (_error) { throw new Error('校验规则 ' + (index + 1) + ' 的固定预期值不是合法 JSON'); }
            expected = {source: 'LITERAL', value: value, column: null};
        }
        return {name: rule.name.trim(), actual_path: rule.actual_path.trim(), operator: rule.operator, expected: expected};
    });
    var payload = await API.post('/api/batch-runs', {
        name: document.getElementById('batch-name').value,
        filename: document.getElementById('batch-file').value,
        sheet_name: document.getElementById('batch-sheet').value,
        workflow_id: document.getElementById('batch-workflow').value,
        case_id_column: document.getElementById('batch-case-id').value,
        mappings: mappings,
        case_concurrency: Number(document.getElementById('batch-concurrency').value),
        header_mode: document.getElementById('batch-header-mode').value,
        evaluation_rules: evaluationRules,
    });
    closeExecutionModal();
    showToast('Run 已创建，确认后可手工启动', 'success');
    await loadBatchRuns();
    return payload;
}

async function viewBatchDetail(batchId, page) {
    currentView = 'batch-detail';
    scheduleBatchPoll(false);
    page = page || 1;
    try {
        var values = await Promise.all([
            API.get('/api/batch-runs/' + encodeURIComponent(batchId)),
            API.get('/api/batch-runs/' + encodeURIComponent(batchId) + '/cases?page=' + page + '&page_size=50'),
        ]);
        var batch = values[0].batch;
        var cases = values[1].cases || [];
        var summary = batch.summary || {};
        contentArea.innerHTML = '<section class="execution-page batch-detail">' +
            '<header class="execution-page-header"><div><button class="btn btn-sm" id="batch-back">' + icon('back') + '返回</button><h1>' + esc(batch.name) + '</h1><p>' + esc(batch.input.filename + ' / ' + batch.input.sheet_name + ' · ' + batch.workflow.name) + '</p></div><span class="' + batchStatusClass(batch.status) + '">' + batchStatusLabel(batch.status) + '</span></header>' +
            '<div class="batch-summary">' + ['pass', 'fail', 'error', 'not_evaluated'].map(function (key) { return '<div><strong>' + (summary[key] || 0) + '</strong><span>' + ({pass: '通过', fail: '不通过', error: '校验错误', not_evaluated: '未校验'}[key]) + '</span></div>'; }).join('') + '</div>' +
            '<div class="table-wrap execution-table-wrap"><table class="table execution-table batch-case-table"><thead><tr><th>Case ID</th><th>Excel 行</th><th>执行状态</th><th>测试判定</th><th>执行次数</th><th>开始时间</th><th>结束时间</th><th>详情</th></tr></thead><tbody>' + cases.map(function (item) { return '<tr><td>' + esc(item.case_id) + '</td><td>' + item.row_number + '</td><td><span class="' + batchStatusClass(item.execution_status || item.status) + '">' + batchStatusLabel(item.execution_status || item.status) + '</span></td><td><span class="' + batchVerdictClass(item.verdict) + '">' + batchVerdictLabel(item.verdict) + '</span></td><td>' + item.workflow_execution_ids.length + '</td><td>' + esc(formatDateTime(item.started_at)) + '</td><td>' + esc(formatDateTime(item.finished_at)) + '</td><td><button class="btn-icon" data-case-open="' + item.id + '" title="查看 Case" aria-label="查看 Case">' + icon('browse') + '</button></td></tr>'; }).join('') + '</tbody></table></div><div id="batch-case-pagination" class="pagination"></div>' +
        '</section>';
        document.getElementById('batch-back').addEventListener('click', viewBatchRuns);
        document.querySelectorAll('[data-case-open]').forEach(function (button) { button.addEventListener('click', function () { openBatchCaseDetail(batch, button.getAttribute('data-case-open')); }); });
        renderPagination('batch-case-pagination', values[1].total, values[1].page, values[1].page_size, function (nextPage) { viewBatchDetail(batchId, nextPage); });
        if (batch.status === 'RUNNING') executionState.batchPoll = setTimeout(function () { viewBatchDetail(batchId, page); }, 1000);
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
    }
}

async function openBatchCaseDetail(batch, caseRunId) {
    try {
        var payload = await API.get('/api/batch-runs/' + encodeURIComponent(batch.id) + '/cases/' + encodeURIComponent(caseRunId));
        var caseRun = payload.case;
        var execution = null;
        if (caseRun.workflow_execution_ids.length) {
            execution = (await API.get('/api/workflows/' + encodeURIComponent(batch.workflow.id) + '/runs/' + encodeURIComponent(caseRun.workflow_execution_ids[caseRun.workflow_execution_ids.length - 1]))).execution;
        }
        openExecutionModal('Case ' + caseRun.case_id,
            '<div class="batch-case-detail"><dl><dt>Excel 行</dt><dd>' + caseRun.row_number + '</dd><dt>执行状态</dt><dd>' + batchStatusLabel(caseRun.execution_status || caseRun.status) + '</dd><dt>测试判定</dt><dd>' + batchVerdictLabel(caseRun.verdict) + '</dd></dl><h3>映射输入</h3><pre>' + esc(JSON.stringify(caseRun.start_inputs, null, 2)) + '</pre><h3>Workflow 结果</h3><pre>' + esc(JSON.stringify(execution ? execution.result : {}, null, 2)) + '</pre><h3>校验明细</h3><pre>' + esc(JSON.stringify(caseRun.evaluation || {verdict: 'NOT_EVALUATED', rules: []}, null, 2)) + '</pre><h3>最终 Context</h3><pre>' + esc(JSON.stringify(execution ? execution.context.final : {}, null, 2)) + '</pre><h3>错误</h3><pre>' + esc(JSON.stringify(caseRun.error || (execution && execution.error) || null, null, 2)) + '</pre></div>',
            async function () { closeExecutionModal(); }, '关闭');
        document.getElementById('execution-modal-cancel').style.display = 'none';
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
    }
}
