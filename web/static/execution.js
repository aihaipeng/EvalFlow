/* Workflow Structural Model UI. */
var executionState = {
    workflows: [],
    batches: [],
    workflowPage: 1,
    workflowPageSize: 10,
    batchPage: 1,
    batchPageSize: 10,
    batchDetailPageSize: 10,
    batchCreating: false,
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
            '<button class="btn btn-secondary" id="execution-modal-cancel" type="button">' + icon('close') + '取消</button>' +
            '<button class="btn btn-primary" id="execution-modal-save" type="button">' + icon('save') + '保存</button>' +
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
    var resolvedSaveLabel = saveLabel || '保存';
    save.innerHTML = icon(resolvedSaveLabel.includes('创建') ? 'add' : 'save') + esc(resolvedSaveLabel);
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
    count.textContent = executionState.workflows.length + ' 个工作流';
    var pagination = globalPageSlice(executionState.workflows, executionState.workflowPage, executionState.workflowPageSize);
    executionState.workflowPage = pagination.page;
    executionState.workflowPageSize = pagination.pageSize;
    renderGlobalListPagination('workflow-pagination', pagination.total, pagination.page, pagination.pageSize, function (nextPage) {
        executionState.workflowPage = nextPage;
        renderWorkflowTable();
    }, function (nextPageSize) {
        executionState.workflowPage = 1;
        executionState.workflowPageSize = nextPageSize;
        renderWorkflowTable();
    }, '个工作流');
    if (!executionState.workflows.length) {
        body.innerHTML = '<tr><td colspan="4">' + executionEmpty('尚未创建工作流', '新增工作流', 'workflow-empty-add') + '</td></tr>';
        document.getElementById('workflow-empty-add').addEventListener('click', function () { openWorkflowCanvas(); });
        return;
    }
    body.innerHTML = pagination.items.map(function (workflow) {
        return '<tr>' +
            '<td><button class="execution-name-button" type="button" data-workflow-open="' + esc(workflow.id) + '">' + esc(workflow.name) + '</button></td>' +
            '<td class="workflow-description-cell">' + esc(workflow.description || '—') + '</td>' +
            '<td>' + esc(formatDateTime(workflow.updated_at)) + '</td>' +
            '<td><div class="execution-row-actions">' +
                '<button class="btn-icon" type="button" data-workflow-open="' + esc(workflow.id) + '" title="编辑工作流" aria-label="编辑工作流">' + icon('edit') + '</button>' +
                '<button class="btn-icon" type="button" data-workflow-delete="' + esc(workflow.id) + '" title="删除工作流" aria-label="删除工作流">' + icon('trash') + '</button>' +
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
            '<header class="execution-page-header"><div><h1 id="workflows-title">工作流管理</h1><p>开发、保存和手动验证工作流结构</p></div><span class="execution-count" id="workflow-count">0 个工作流</span></header>' +
            '<div class="toolbar execution-toolbar" id="workflows-toolbar">' +
                '<button class="btn btn-primary" id="btn-workflow-add" type="button">' + icon('add') + '新增工作流</button>' +
                '<button class="btn" id="btn-workflow-refresh" type="button">' + icon('refresh') + '刷新</button>' +
            '</div>' +
            '<div class="table-wrap execution-table-wrap"><table class="table execution-table workflow-table"><thead><tr><th>名称</th><th>说明</th><th>更新时间</th><th>操作</th></tr></thead><tbody id="workflow-list-body"></tbody></table></div>' +
            '<div id="workflow-pagination" class="global-list-footer"></div>' +
        '</section>';
    document.getElementById('btn-workflow-add').addEventListener('click', function () { openWorkflowCanvas(); });
    document.getElementById('btn-workflow-refresh').addEventListener('click', loadWorkflows);
    loadWorkflows();
}

async function openWorkflowCanvas(workflowId) {
    if (!window.AgentBenchWorkflowCanvas) {
        showToast('工作流画布资源未加载', 'error');
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
        '删除工作流',
        '<p>确定删除工作流“<strong>' + esc(workflow.name) + '</strong>”吗？</p><p class="info-text" style="margin-top:8px">当前节点和连线将一并删除。</p>',
        async function () {
            try {
                await API.del('/api/workflows/' + encodeURIComponent(workflowId));
                closeExecutionModal();
                showToast('工作流已删除', 'success');
                await loadWorkflows();
            } catch (error) {
                showToast(executionErrorMessage(error), 'error');
            }
        },
        '删除'
    );
}





function batchProgress(batch) {
    var summary = batch.summary || {};
    var done = (summary.success || 0) + (summary.failed || 0) + (summary.interrupted || 0);
    var total = batch.total_cases || 0;
    var percent = total ? Math.round(done * 100 / total) : 0;
    return '<div class="batch-progress"><div><span style="width:' + percent + '%"></span></div>' +
        '<small>' + done + ' / ' + total + '</small></div>';
}


function renderBatchTable() {
    var body = document.getElementById('batch-list-body');
    var count = document.getElementById('batch-count');
    if (!body || !count) return;
    count.textContent = executionState.batches.length + ' 个 Run';
    var pagination = globalPageSlice(executionState.batches, executionState.batchPage, executionState.batchPageSize);
    executionState.batchPage = pagination.page;
    executionState.batchPageSize = pagination.pageSize;
    renderGlobalListPagination('batch-pagination', pagination.total, pagination.page, pagination.pageSize, function (nextPage) {
        executionState.batchPage = nextPage;
        renderBatchTable();
    }, function (nextPageSize) {
        executionState.batchPage = 1;
        executionState.batchPageSize = nextPageSize;
        renderBatchTable();
    }, '个 Run');
    if (!executionState.batches.length) {
        body.innerHTML = '<tr><td colspan="6">' + executionEmpty('尚未创建批量 Run', '创建 Run', 'batch-empty-add') + '</td></tr>';
        document.getElementById('batch-empty-add').addEventListener('click', function () { openBatchCreate(); });
        return;
    }
    body.innerHTML = pagination.items.map(function (batch) {
        var action = batch.status === 'QUEUED'
            ? '<button class="btn btn-sm btn-primary" data-batch-start="' + batch.id + '">' + icon('play') + '启动</button>'
            : batch.status === 'RUNNING'
                ? '<button class="btn btn-sm btn-danger" data-batch-cancel="' + batch.id + '">' + icon('stop') + '取消</button>'
                : batch.status === 'INTERRUPTED'
                    ? '<button class="btn btn-sm" data-batch-resume="' + batch.id + '">' + icon('play') + '恢复</button>'
                    : batch.status === 'COMPLETED_WITH_ERRORS'
                        ? '<button class="btn btn-sm" data-batch-retry="' + batch.id + '">' + icon('retry') + '重试失败</button>' : '';
        var edit = '<button class="btn-icon" data-batch-edit="' + batch.id + '" title="编辑并创建新 Run" aria-label="编辑并创建新 Run">' + icon('edit') + '</button>';
        var remove = batch.status === 'RUNNING' ? '' : '<button class="btn-icon" data-batch-delete="' + batch.id + '" title="删除 Run" aria-label="删除 Run">' + icon('trash') + '</button>';
        return '<tr>' +
            '<td><button class="execution-name-button" data-batch-open="' + batch.id + '">' + esc(batch.name) + '</button></td>' +
            '<td>' + esc(batch.input.test_set_name) + '</td>' +
            '<td>' + esc(batch.workflow.name) + '</td>' +
            '<td>' + batchProgress(batch) + '</td>' +
            '<td>' + esc(formatDateTime(batch.created_at)) + '</td>' +
            '<td><div class="batch-row-actions"><button class="btn-icon" data-batch-open="' + batch.id + '" title="查看详情" aria-label="查看详情">' + icon('browse') + '</button>' + edit + action + remove + '</div></td>' +
        '</tr>';
    }).join('');
    body.querySelectorAll('[data-batch-open]').forEach(function (button) { button.addEventListener('click', function () { viewBatchDetail(button.getAttribute('data-batch-open')); }); });
    body.querySelectorAll('[data-batch-edit]').forEach(function (button) { button.addEventListener('click', function () { openBatchCreate(button.getAttribute('data-batch-edit')); }); });
    body.querySelectorAll('[data-batch-start]').forEach(function (button) { button.addEventListener('click', function () { batchCommand(button, button.getAttribute('data-batch-start'), 'start', {}); }); });
    body.querySelectorAll('[data-batch-cancel]').forEach(function (button) { button.addEventListener('click', function () { batchCommand(button, button.getAttribute('data-batch-cancel'), 'cancel', {}); }); });
    body.querySelectorAll('[data-batch-resume]').forEach(function (button) { button.addEventListener('click', function () { batchCommand(button, button.getAttribute('data-batch-resume'), 'resume', {retry_failed: false}); }); });
    body.querySelectorAll('[data-batch-retry]').forEach(function (button) { button.addEventListener('click', function () { batchCommand(button, button.getAttribute('data-batch-retry'), 'resume', {retry_failed: true}); }); });
    body.querySelectorAll('[data-batch-delete]').forEach(function (button) { button.addEventListener('click', function () { confirmBatchDelete(button.getAttribute('data-batch-delete')); }); });
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
            '<header class="execution-page-header"><div><h1 id="batch-title">运行调度</h1><p>按数据库测试集用例并发执行已保存的工作流</p></div><span class="execution-count" id="batch-count">0 个 Run</span></header>' +
            '<div class="toolbar execution-toolbar"><button class="btn btn-primary" id="btn-batch-add">' + icon('add') + '创建 Run</button><button class="btn" id="btn-batch-refresh">' + icon('refresh') + '刷新</button></div>' +
            '<div class="table-wrap execution-table-wrap"><table class="table execution-table batch-table"><thead><tr><th>名称</th><th>测试集</th><th>工作流</th><th>进度</th><th>创建时间</th><th>操作</th></tr></thead><tbody id="batch-list-body"></tbody></table></div>' +
            '<div id="batch-pagination" class="global-list-footer"></div>' +
        '</section>';
    document.getElementById('btn-batch-add').addEventListener('click', function () { openBatchCreate(); });
    document.getElementById('btn-batch-refresh').addEventListener('click', loadBatchRuns);
    loadBatchRuns();
}

async function openBatchCreate(sourceBatchId) {
    try {
        var requests = [
            API.get('/api/test-sets?page=1&page_size=200'),
            API.get('/api/workflows'),
        ];
        if (sourceBatchId) requests.push(API.get('/api/batch-runs/' + encodeURIComponent(sourceBatchId)));
        var values = await Promise.all(requests);
        var testSets = values[0].items || [];
        var workflows = values[1].workflows || [];
        var sourceBatch = values[2] ? values[2].batch : null;
        if (!testSets.length || !workflows.length) {
            showToast(!testSets.length ? '请先创建测试集' : '请先创建工作流', 'error');
            return;
        }
        var body =
            '<div class="batch-create-grid">' +
                '<label>名称<input class="input" id="batch-name" maxlength="200" placeholder="默认使用测试集和工作流名称" /></label>' +
                '<label>测试集<select class="input" id="batch-test-set">' + testSets.map(function (testSet) { return '<option value="' + esc(testSet.id) + '">' + esc(testSet.name) + '</option>'; }).join('') + '</select></label>' +
                '<label>工作流<select class="input" id="batch-workflow">' + workflows.map(function (workflow) { return '<option value="' + workflow.id + '">' + esc(workflow.name) + '</option>'; }).join('') + '</select></label>' +
                '<label>Case 并发数<input class="input" id="batch-concurrency" type="number" min="1" max="32" value="4" /></label>' +
            '</div><div class="batch-dataset-meta" id="batch-preview-meta">正在读取测试集字段...</div>' +
            '<section class="batch-variable-injection"><header><div><strong>变量注入</strong><span>注入到工作流 Context，节点可通过 context["变量名"] 读取</span></div><button class="btn btn-sm" id="batch-variable-add" type="button">' + icon('add') + '添加变量</button></header><div class="batch-variable-table" id="batch-variables"><div class="batch-variable-empty">正在读取测试集字段...</div></div></section>' +
            '<section class="batch-evaluation"><header><div><strong>结果校验</strong><span>全部校验点通过时，用例才通过</span></div><button class="btn btn-sm" id="batch-rule-add" type="button">' + icon('add') + '添加规则</button></header><div class="batch-evaluation-table" id="batch-evaluation-rules"></div></section>';
        openExecutionModal(sourceBatch ? '编辑 Run 配置' : '创建批量 Run', body, createBatchFromModal, sourceBatch ? '创建新 Run' : '创建');
        document.querySelector('.execution-modal').classList.add('is-batch-config');
        document.getElementById('execution-modal-save').disabled = true;
        document.getElementById('batch-test-set').addEventListener('change', function () { loadBatchPreview(); });
        document.getElementById('batch-variable-add').addEventListener('click', addBatchVariable);
        document.getElementById('batch-rule-add').addEventListener('click', function () { addBatchEvaluationRule(); });
        if (sourceBatch) {
            var testSetSelect = document.getElementById('batch-test-set');
            var workflowSelect = document.getElementById('batch-workflow');
            if (!Array.from(testSetSelect.options).some(function (option) { return option.value === sourceBatch.input.test_set_id; })) throw new Error('原 Run 的测试集已不存在');
            if (!Array.from(workflowSelect.options).some(function (option) { return option.value === sourceBatch.workflow.id; })) throw new Error('原 Run 的工作流已不存在');
            document.getElementById('batch-name').value = sourceBatch.name;
            testSetSelect.value = sourceBatch.input.test_set_id;
            workflowSelect.value = sourceBatch.workflow.id;
            document.getElementById('batch-concurrency').value = sourceBatch.case_concurrency;
        }
        await loadBatchPreview(sourceBatch);
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
    }
}

function batchVariableDrafts() {
    return Array.from(document.querySelectorAll('.batch-variable-row')).map(function (row) {
        return {
            source: row.querySelector('[data-variable-source]').value,
            key: row.querySelector('[data-variable-key]').value,
            value: row.querySelector('[data-variable-value]').value,
            type: row.querySelector('[data-variable-type]').value,
        };
    });
}

function batchVariableValueControl(variable, headers) {
    if (variable.source === 'TEST_SET') {
        var options = (headers || []).map(function (header) {
            return '<option value="' + esc(header) + '"' + (variable.value === header ? ' selected' : '') + '>' + esc(header) + '</option>';
        }).join('');
        return '<select class="input" data-variable-value aria-label="测试集字段">' + options + '</select>';
    }
    if (variable.type === 'null') return '<input class="input" data-variable-value value="null" disabled aria-label="null 值" />';
    if (variable.type === 'boolean') return '<select class="input" data-variable-value><option value="true" ' + (variable.value === 'true' ? 'selected' : '') + '>true</option><option value="false" ' + (variable.value === 'false' ? 'selected' : '') + '>false</option></select>';
    if (variable.type === 'object' || variable.type === 'array') {
        var placeholder = variable.type === 'object' ? '{"field":"value"}' : '["item"]';
        return '<textarea class="input" data-variable-value rows="2" spellcheck="false" placeholder="' + esc(placeholder) + '">' + esc(variable.value) + '</textarea>';
    }
    return '<input class="input" data-variable-value value="' + esc(variable.value) + '" placeholder="' + (variable.type === 'string' ? '输入变量值' : '输入 JSON 数值') + '" />';
}

function renderBatchVariables(variables, headers) {
    var container = document.getElementById('batch-variables');
    if (!container) return;
    container.dataset.headers = JSON.stringify(headers || []);
    if (!variables.length) {
        container.innerHTML = '<div class="batch-variable-empty">尚未配置变量。添加变量后，可选择测试集字段或填写自定义值。</div>';
        return;
    }
    var types = ['string', 'number', 'integer', 'boolean', 'object', 'array', 'null'];
    container.innerHTML = '<div class="batch-variable-head"><span>#</span><span>Source</span><span>Key</span><span>Value</span><span>Type</span><span></span></div>' + variables.map(function (variable, index) {
        return '<div class="batch-variable-row" data-variable-index="' + index + '">' +
            '<span class="batch-variable-index">' + (index + 1) + '</span>' +
            '<label><span class="batch-mobile-label">Source</span><select class="input" data-variable-source><option value="TEST_SET" ' + (variable.source === 'TEST_SET' ? 'selected' : '') + '>测试集字段</option><option value="CUSTOM" ' + (variable.source === 'CUSTOM' ? 'selected' : '') + '>自定义</option></select></label>' +
            '<label><span class="batch-mobile-label">Key</span><input class="input" data-variable-key value="' + esc(variable.key) + '" placeholder="例如 question" /></label>' +
            '<label><span class="batch-mobile-label">Value</span>' + batchVariableValueControl(variable, headers) + '</label>' +
            '<label><span class="batch-mobile-label">Type</span><select class="input" data-variable-type>' + types.map(function (type) { return '<option value="' + type + '" ' + (variable.type === type ? 'selected' : '') + '>' + type + '</option>'; }).join('') + '</select></label>' +
            '<button class="btn-icon" type="button" data-variable-delete title="删除变量" aria-label="删除变量">' + icon('trash') + '</button>' +
        '</div>';
    }).join('');
    container.querySelectorAll('.batch-variable-row').forEach(function (row) {
        var rerender = function (changed) {
            var rows = batchVariableDrafts();
            var current = rows[Number(row.dataset.variableIndex)];
            current[changed] = row.querySelector('[data-variable-' + changed + ']').value;
            if (changed === 'source') current.value = '';
            if (changed === 'type' && current.type === 'null') current.value = 'null';
            renderBatchVariables(rows, headers);
        };
        row.querySelector('[data-variable-source]').addEventListener('change', function () { rerender('source'); });
        row.querySelector('[data-variable-type]').addEventListener('change', function () { rerender('type'); });
        row.querySelector('[data-variable-delete]').addEventListener('click', function () {
            renderBatchVariables(batchVariableDrafts().filter(function (_item, rowIndex) { return rowIndex !== Number(row.dataset.variableIndex); }), headers);
        });
    });
}

function addBatchVariable() {
    var container = document.getElementById('batch-variables');
    if (!container) return;
    var variables = batchVariableDrafts();
    var headers = JSON.parse(container.dataset.headers || '[]');
    variables.push({source: 'TEST_SET', key: '', value: headers[0] || '', type: 'string'});
    renderBatchVariables(variables, headers);
}

function batchRuleDrafts() {
    return Array.from(document.querySelectorAll('.batch-evaluation-rule')).map(function (row) {
        return {
            result_path: row.querySelector('[data-rule-result-path]').value,
            operator: row.querySelector('[data-rule-operator]').value,
            expected_value: row.querySelector('[data-rule-expected-value]').value,
            type: row.querySelector('[data-rule-type]').value,
        };
    });
}

function renderBatchEvaluationRules(rules) {
    var container = document.getElementById('batch-evaluation-rules');
    if (!container) return;
    if (!(rules || []).length) {
        container.innerHTML = '<div class="batch-evaluation-empty">暂无校验规则</div>';
        return;
    }
    var operators = [
        ['EQ', '等于'], ['NE', '不等于'], ['CONTAINS', '包含'], ['REGEX', '正则'],
        ['EXISTS', '存在'], ['GT', '大于'], ['GTE', '大于等于'], ['LT', '小于'],
        ['LTE', '小于等于'], ['JSON_EQUAL', 'JSON 相等'],
    ];
    var types = ['string', 'number', 'integer', 'boolean', 'object', 'array', 'null'];
    container.innerHTML = '<div class="batch-evaluation-head"><span>#</span><span>结果路径</span><span>运算符</span><span>预期值</span><span>Type</span><span></span></div>' + rules.map(function (rule, index) {
        return '<div class="batch-evaluation-rule" data-rule-index="' + index + '">' +
            '<span class="batch-evaluation-index">' + (index + 1) + '</span>' +
            '<label><span>结果路径</span><input class="input" data-rule-result-path value="' + esc(rule.result_path || '') + '" placeholder="例如 context.final_answer.status" /></label>' +
            '<label><span>运算符</span><select class="input" data-rule-operator>' + operators.map(function (item) { return '<option value="' + item[0] + '" ' + (item[0] === rule.operator ? 'selected' : '') + '>' + item[1] + '</option>'; }).join('') + '</select></label>' +
            '<label><span>预期值</span><input class="input" data-rule-expected-value value="' + esc(rule.expected_value || '') + '" placeholder="例如 PASS" /></label>' +
            '<label><span>Type</span><select class="input" data-rule-type>' + types.map(function (type) { return '<option value="' + type + '" ' + (type === rule.type ? 'selected' : '') + '>' + type + '</option>'; }).join('') + '</select></label>' +
            '<button class="btn-icon" type="button" data-rule-delete title="删除规则" aria-label="删除规则">' + icon('trash') + '</button>' +
        '</div>';
    }).join('');
    container.querySelectorAll('.batch-evaluation-rule').forEach(function (row) {
        row.querySelector('[data-rule-delete]').addEventListener('click', function () {
            var remaining = batchRuleDrafts().filter(function (_item, index) { return index !== Number(row.dataset.ruleIndex); });
            renderBatchEvaluationRules(remaining);
        });
    });
}

function addBatchEvaluationRule() {
    var rules = batchRuleDrafts();
    rules.push({result_path: '', operator: 'EQ', expected_value: '', type: 'string'});
    renderBatchEvaluationRules(rules);
}


async function loadBatchPreview(sourceBatch) {
    var testSetId = document.getElementById('batch-test-set').value;
    if (!testSetId) return;
    var requestId = ++executionState.batchPreviewRequestId;
    var saveButton = document.getElementById('execution-modal-save');
    var variableContainer = document.getElementById('batch-variables');
    var variablesReady = variableContainer.dataset.ready === 'true';
    var evaluationContainer = document.getElementById('batch-evaluation-rules');
    var evaluationReady = evaluationContainer.dataset.ready === 'true';
    var variableDrafts = variablesReady ? batchVariableDrafts() : ((sourceBatch && sourceBatch.variables) || []);
    var evaluationDrafts = evaluationReady ? batchRuleDrafts() : ((sourceBatch && sourceBatch.evaluation_rules) || []);
    saveButton.disabled = true;
    document.getElementById('batch-preview-meta').textContent = '正在读取测试集字段...';
    try {
        var preview = await API.post('/api/batch-runs/preview', {test_set_id: testSetId});
        if (requestId !== executionState.batchPreviewRequestId) return;
        variableDrafts = variableDrafts.map(function (variable) {
            var source = variable.source;
            var value = source === 'TEST_SET' && !preview.headers.includes(variable.value) ? (preview.headers[0] || '') : variable.value;
            return {source: source, key: variable.key, value: value, type: variable.type};
        });
        document.getElementById('batch-preview-meta').textContent = preview.total_rows + ' 条用例 · ' + preview.headers.length + ' 个字段';
        renderBatchVariables(variableDrafts, preview.headers);
        variableContainer.dataset.ready = 'true';
        renderBatchEvaluationRules(evaluationDrafts);
        evaluationContainer.dataset.ready = 'true';
        saveButton.disabled = false;
    } catch (error) {
        if (requestId !== executionState.batchPreviewRequestId) return;
        document.getElementById('batch-preview-meta').textContent = '读取失败';
        variableContainer.innerHTML = '<div class="batch-variable-empty">' + esc(executionErrorMessage(error)) + '</div>';
        showToast(executionErrorMessage(error), 'error');
    }
}

async function createBatchFromModal() {
    if (executionState.batchCreating) return;
    executionState.batchCreating = true;
    try {
    var variables = batchVariableDrafts().map(function (variable, index) {
        if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(variable.key.trim())) throw new Error('变量 ' + (index + 1) + ' 的 Key 只能包含字母、数字和下划线，且不能以数字开头');
        if (!variable.value && variable.type !== 'null') throw new Error('变量 ' + (index + 1) + ' 的 Value 不能为空');
        return {source: variable.source, key: variable.key.trim(), value: variable.value, type: variable.type};
    });
    if (!variables.length) throw new Error('请至少配置一个变量注入');
    var evaluationRules = batchRuleDrafts().map(function (rule, index) {
        if (!rule.result_path.trim().startsWith('context.')) throw new Error('校验规则 ' + (index + 1) + ' 的结果路径必须以 context. 开头');
        if (!rule.expected_value.trim() && rule.type !== 'null') throw new Error('校验规则 ' + (index + 1) + ' 的预期值不能为空');
        return {
            result_path: rule.result_path.trim(),
            operator: rule.operator,
            expected_value: rule.type === 'null' ? 'null' : rule.expected_value,
            type: rule.type,
        };
    });
    var payload = await API.post('/api/batch-runs', {
        name: document.getElementById('batch-name').value,
        test_set_id: document.getElementById('batch-test-set').value,
        workflow_id: document.getElementById('batch-workflow').value,
        variables: variables,
        case_concurrency: Number(document.getElementById('batch-concurrency').value),
        evaluation_rules: evaluationRules,
    });
    closeExecutionModal();
    showToast('Run 已创建，确认后可手工启动', 'success');
    await loadBatchRuns();
    return payload;

    } finally {
        executionState.batchCreating = false;
    }
}

async function viewBatchDetail(batchId, page, pageSize) {
    currentView = 'batch-detail';
    scheduleBatchPoll(false);
    page = page || 1;
    pageSize = normalizeGlobalPageSize(pageSize || executionState.batchDetailPageSize);
    executionState.batchDetailPageSize = pageSize;
    try {
        var values = await Promise.all([
            API.get('/api/batch-runs/' + encodeURIComponent(batchId)),
            API.get('/api/batch-runs/' + encodeURIComponent(batchId) + '/cases?page=' + page + '&page_size=' + pageSize),
        ]);
        var batch = values[0].batch;
        var cases = values[1].cases || [];
        contentArea.innerHTML = '<section class="execution-page batch-detail">' +
            '<header class="execution-page-header"><div><button class="btn btn-sm" id="batch-back">' + icon('back') + '返回</button><h1>' + esc(batch.name) + '</h1><p>' + esc(batch.input.test_set_name + ' · ' + batch.workflow.name) + '</p></div></header>' +
            '<div class="table-wrap execution-table-wrap"><table class="table execution-table batch-case-table"><thead><tr><th>用例序号</th><th>执行次数</th><th>开始时间</th><th>结束时间</th><th>详情</th></tr></thead><tbody>' + cases.map(function (item) { return '<tr><td>' + item.row_number + '</td><td>' + item.workflow_execution_ids.length + '</td><td>' + esc(formatDateTime(item.started_at)) + '</td><td>' + esc(formatDateTime(item.finished_at)) + '</td><td><button class="btn-icon" data-case-open="' + item.id + '" title="查看用例" aria-label="查看用例">' + icon('browse') + '</button></td></tr>'; }).join('') + '</tbody></table></div><div id="batch-case-pagination" class="global-list-footer"></div>' +
        '</section>';
        document.getElementById('batch-back').addEventListener('click', viewBatchRuns);
        document.querySelectorAll('[data-case-open]').forEach(function (button) { button.addEventListener('click', function () { openBatchCaseDetail(batch, button.getAttribute('data-case-open')); }); });
        renderGlobalListPagination('batch-case-pagination', values[1].total, values[1].page, values[1].page_size, function (nextPage) {
            viewBatchDetail(batchId, nextPage, pageSize);
        }, function (nextPageSize) {
            executionState.batchDetailPageSize = nextPageSize;
            viewBatchDetail(batchId, 1, nextPageSize);
        }, '条用例');
        if (batch.status === 'RUNNING') executionState.batchPoll = setTimeout(function () { viewBatchDetail(batchId, page, pageSize); }, 1000);
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
        openExecutionModal('用例 ' + caseRun.row_number,
            '<div class="batch-case-detail"><dl><dt>用例序号</dt><dd>' + caseRun.row_number + '</dd></dl><h3>映射输入</h3><pre>' + esc(JSON.stringify(caseRun.start_inputs, null, 2)) + '</pre><h3>工作流结果</h3><pre>' + esc(JSON.stringify(execution ? execution.result : {}, null, 2)) + '</pre><h3>最终 Context</h3><pre>' + esc(JSON.stringify(execution ? execution.context.final : {}, null, 2)) + '</pre><h3>错误</h3><pre>' + esc(JSON.stringify(caseRun.error || (execution && execution.error) || null, null, 2)) + '</pre></div>',
            async function () { closeExecutionModal(); }, '关闭');
        document.getElementById('execution-modal-cancel').style.display = 'none';
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
    }
}
