/* Workflow Structural Model UI. */
var BATCH_LIST_POLL_BASE_MS = 5000;
var BATCH_LIST_POLL_MAX_MS = 10000;
var BATCH_LIST_POLL_BACKOFF_STEP_MS = 2500;
var BATCH_LIST_UNCHANGED_THRESHOLD = 3;
var BATCH_DETAIL_POLL_INTERVAL_MS = 1000;
var executionModalReturnFocus = null;

var executionState = {
    workflows: [],
    batches: [],
    workflowPage: 1,
    workflowPageSize: 10,
    batchPage: 1,
    batchPageSize: 10,
    batchDetailPageSize: 10,
    batchDetailSort: null,
    batchDetailSortDirection: 'asc',
    batchDetailResultFilter: '',
    batchDetailStateFilter: '',
    batchDetailSearch: '',
    batchDetailSearchTimer: null,
    batchDetailRequestId: 0,
    batchDetailRenderKey: '',
    batchCreating: false,
    batchConfigMode: 'create',
    batchConfigTaskId: null,
    batchSchedules: {},
    batchPoll: null,
    batchListPollSignature: null,
    batchListUnchangedPolls: 0,
    batchListPollIntervalMs: BATCH_LIST_POLL_BASE_MS,
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

function executionModalFocusableElements(overlay) {
    return Array.from(overlay.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
        .filter(function (element) { return element.offsetParent !== null; });
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
    overlay.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            event.preventDefault();
            closeExecutionModal();
            return;
        }
        if (event.key !== 'Tab') return;
        var focusable = executionModalFocusableElements(overlay);
        if (!focusable.length) {
            event.preventDefault();
            overlay.querySelector('.execution-modal').focus();
            return;
        }
        var first = focusable[0];
        var last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    });
    overlay.querySelector('#execution-modal-cancel').addEventListener('click', closeExecutionModal);
    return overlay;
}

function closeExecutionModal() {
    var overlay = document.getElementById('execution-overlay');
    if (overlay) overlay.classList.add('hidden');
    if (executionModalReturnFocus && executionModalReturnFocus.isConnected) executionModalReturnFocus.focus();
    executionModalReturnFocus = null;
}

function openExecutionModal(title, bodyHtml, onSave, saveLabel) {
    var overlay = ensureExecutionModal();
    executionModalReturnFocus = document.activeElement;
    overlay.querySelector('.execution-modal').tabIndex = -1;
    overlay.querySelector('.execution-modal').classList.remove('is-batch-config', 'is-batch-schedule', 'is-batch-history', 'is-case-detail', 'is-confirm');
    overlay.querySelector('#execution-modal-title').textContent = title;
    overlay.querySelector('#execution-modal-body').innerHTML = bodyHtml;
    var save = overlay.querySelector('#execution-modal-save');
    overlay.querySelector('#execution-modal-cancel').style.display = '';
    var resolvedSaveLabel = saveLabel || '保存';
    var actionIcon = resolvedSaveLabel.includes('删除') ? 'trash'
        : resolvedSaveLabel.includes('确认') || resolvedSaveLabel.includes('切换') ? 'check'
        : resolvedSaveLabel.includes('创建') ? 'add' : 'save';
    save.innerHTML = icon(actionIcon) + esc(resolvedSaveLabel);
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
    var focusable = executionModalFocusableElements(overlay);
    (focusable[0] || overlay.querySelector('.execution-modal')).focus();
}

function openExecutionConfirm(title, bodyHtml, onConfirm, confirmLabel) {
    openExecutionModal(title, '<div class="execution-confirm-copy">' + bodyHtml + '</div>', async function () {
        var confirmed = await onConfirm();
        if (confirmed !== false) closeExecutionModal();
    }, confirmLabel || '确认');
    document.querySelector('.execution-modal').classList.add('is-confirm');
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
            '<td class="management-list-primary" title="' + escAttr(workflow.name) + '"><button class="execution-name-button" type="button" data-workflow-open="' + esc(workflow.id) + '">' + esc(workflow.name) + '</button></td>' +
            '<td class="management-list-text workflow-description-cell" title="' + escAttr(workflow.description || '—') + '">' + esc(workflow.description || '—') + '</td>' +
            '<td class="management-list-time">' + esc(formatDateTime(workflow.updated_at)) + '</td>' +
            '<td class="management-list-actions-cell"><div class="management-list-row-actions execution-row-actions">' +
                '<button class="btn-icon" type="button" data-workflow-copy="' + esc(workflow.id) + '" title="拷贝工作流" aria-label="拷贝工作流">' + icon('copy') + '</button>' +
                '<button class="btn-icon" type="button" data-workflow-delete="' + esc(workflow.id) + '" title="删除工作流" aria-label="删除工作流">' + icon('trash') + '</button>' +
            '</div></td></tr>';
    }).join('');
    body.querySelectorAll('[data-workflow-open]').forEach(function (button) {
        button.addEventListener('click', function () { openWorkflowCanvas(button.getAttribute('data-workflow-open')); });
    });
    body.querySelectorAll('[data-workflow-copy]').forEach(function (button) {
        button.addEventListener('click', function () { copyWorkflow(button.getAttribute('data-workflow-copy'), button); });
    });
    body.querySelectorAll('[data-workflow-delete]').forEach(function (button) {
        button.addEventListener('click', function () { deleteWorkflow(button.getAttribute('data-workflow-delete')); });
    });
}

async function copyWorkflow(workflowId, button) {
    button.disabled = true;
    try {
        var payload = await API.post('/api/workflows/' + encodeURIComponent(workflowId) + '/copy', {});
        showToast('已拷贝为“' + payload.workflow.workflow.name + '”', 'success');
        await loadWorkflows();
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
        button.disabled = false;
    }
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
            '<header class="execution-page-header management-page-header"><div class="management-page-title"><h1 id="workflows-title">工作流管理</h1><span class="management-page-description">编排并验证工作流</span></div><span class="execution-count" id="workflow-count">0 个工作流</span></header>' +
            '<div class="toolbar execution-toolbar management-list-toolbar" id="workflows-toolbar">' +
                '<button class="btn btn-primary" id="btn-workflow-add" type="button">' + icon('add') + '新增工作流</button>' +
                '<button class="btn" id="btn-workflow-refresh" type="button">' + icon('refresh') + '刷新</button>' +
            '</div>' +
            '<div class="table-wrap execution-table-wrap management-list-wrap"><table class="table execution-table management-list-table workflow-table"><thead><tr><th>名称</th><th>说明</th><th>更新时间</th><th class="management-list-actions-head">操作</th></tr></thead><tbody id="workflow-list-body"></tbody></table></div>' +
            '<div id="workflow-pagination" class="global-list-footer management-list-footer"></div>' +
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
    var done = Math.max(0, Number(summary.success) || 0) + Math.max(0, Number(summary.failed) || 0);
    var total = batch.total_cases || 0;
    var percent = total ? Math.round(done * 100 / total) : 0;
    var activeClass = ['RUNNING', 'STOPPING'].includes(batch.status) ? ' is-active' : '';
    return '<div class="batch-progress' + activeClass + '"><div><span style="width:' + percent + '%"></span></div>' +
        '<small>' + done + ' / ' + total + '</small></div>';
}

function renderBatchPassRate(batch) {
    var summary = batch.summary || {};
    var pass = Math.max(0, Number(summary.success) || 0);
    var executed = pass + Math.max(0, Number(summary.failed) || 0);
    if (!executed) return '<span class="batch-pass-rate is-empty">—</span>';
    var rate = pass * 100 / executed;
    var rounded = Math.round(rate * 10) / 10;
    var label = Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1);
    var tone = rate > 90 ? 'good' : rate >= 60 ? 'warning' : 'bad';
    return '<span class="batch-pass-rate is-' + tone + '" title="Pass ' + pass + ' / 已执行 ' + executed + '">' + label + '%</span>';
}

function batchTableDateTime(value) {
    return esc(formatDateTime(value) || '—');
}


function renderBatchTable() {
    var body = document.getElementById('batch-list-body');
    var count = document.getElementById('batch-count');
    if (!body || !count) return;
    count.textContent = executionState.batches.length + ' 个任务';
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
    }, '个任务');
    if (!executionState.batches.length) {
        body.innerHTML = '<tr><td colspan="8">' + executionEmpty('尚未创建任务', '创建任务', 'batch-empty-add') + '</td></tr>';
        document.getElementById('batch-empty-add').addEventListener('click', function () { openBatchCreate(); });
        return;
    }
    body.innerHTML = pagination.items.map(function (batch) {
        var action;
        if (batch.status === 'STOPPING') {
            action = '<button class="btn-icon is-stopping" type="button" disabled title="正在等待运行中的工作流结束" aria-label="正在停止">' + icon('stop') + '</button>';
        } else if (batch.status === 'RUNNING' && batch.execution_mode === 'SINGLE_CASE') {
            action = '<button class="btn-icon" type="button" disabled title="单条用例执行中" aria-label="单条用例执行中">' + icon('play') + '</button>';
        } else if (batch.status === 'RUNNING') {
            action = '<button class="btn-icon" data-batch-cancel="' + batch.id + '" title="停止任务" aria-label="停止任务">' + icon('stop') + '</button>';
        } else {
            action = '<button class="btn-icon" data-batch-start="' + batch.id + '" title="启动任务" aria-label="启动任务">' + icon('play') + '</button>';
        }
        var history = '<button class="btn-icon" data-batch-history="' + batch.id + '" title="查看执行历史" aria-label="查看执行历史">' + icon('history') + '</button>';
        var edit = '<button class="btn-icon" data-batch-edit="' + batch.id + '" title="编辑任务" aria-label="编辑任务">' + icon('edit') + '</button>';
        var scheduleConfig = executionState.batchSchedules[batch.id];
        var schedule = '<button class="btn-icon' + (scheduleConfig && scheduleConfig.enabled ? ' is-scheduled' : '') + '" data-batch-schedule="' + batch.id + '" title="定时任务设置" aria-label="定时任务设置">' + icon('alarm-clock') + '</button>';
        var copy = '<button class="btn-icon" data-batch-copy="' + batch.id + '" title="拷贝任务" aria-label="拷贝任务">' + icon('copy') + '</button>';
        var remove = ['RUNNING', 'STOPPING'].includes(batch.status)
            ? '<button class="btn-icon" type="button" disabled title="任务运行中，暂不可删除" aria-label="删除任务（暂不可用）">' + icon('trash') + '</button>'
            : '<button class="btn-icon" data-batch-delete="' + batch.id + '" title="删除任务" aria-label="删除任务">' + icon('trash') + '</button>';
        return '<tr>' +
            '<td class="management-list-primary batch-table-primary" title="' + escAttr(batch.name) + '"><button class="execution-name-button" data-batch-open="' + batch.id + '">' + esc(batch.name) + '</button></td>' +
            '<td class="management-list-text batch-table-text" title="' + escAttr(batch.input.test_set_name) + '">' + esc(batch.input.test_set_name) + '</td>' +
            '<td class="management-list-text batch-table-text" title="' + escAttr(batch.workflow.name) + '">' + esc(batch.workflow.name) + '</td>' +
            '<td>' + batchProgress(batch) + '</td>' +
            '<td>' + renderBatchPassRate(batch) + '</td>' +
            '<td class="management-list-time batch-time-cell">' + batchTableDateTime(batch.started_at) + '</td>' +
            '<td class="management-list-time batch-time-cell">' + batchTableDateTime(batch.finished_at) + '</td>' +
            '<td class="management-list-actions-cell batch-actions-cell"><div class="management-list-row-actions batch-row-actions">' + action + history + edit + schedule + copy + remove + '</div></td>' +
        '</tr>';
    }).join('');
    body.querySelectorAll('[data-batch-open]').forEach(function (button) { button.addEventListener('click', function () { viewBatchDetail(button.getAttribute('data-batch-open')); }); });
    body.querySelectorAll('[data-batch-history]').forEach(function (button) { button.addEventListener('click', function () { openBatchHistory(button.getAttribute('data-batch-history')); }); });
    body.querySelectorAll('[data-batch-edit]').forEach(function (button) { button.addEventListener('click', function () { openBatchCreate(button.getAttribute('data-batch-edit'), 'edit'); }); });
    body.querySelectorAll('[data-batch-schedule]').forEach(function (button) { button.addEventListener('click', function () { openBatchSchedule(button.getAttribute('data-batch-schedule')); }); });
    body.querySelectorAll('[data-batch-copy]').forEach(function (button) { button.addEventListener('click', function () { openBatchCreate(button.getAttribute('data-batch-copy'), 'copy'); }); });
    body.querySelectorAll('[data-batch-start]').forEach(function (button) { button.addEventListener('click', function () { batchCommand(button, button.getAttribute('data-batch-start'), 'start', {}); }); });
    body.querySelectorAll('[data-batch-cancel]').forEach(function (button) { button.addEventListener('click', function () { batchCommand(button, button.getAttribute('data-batch-cancel'), 'cancel', {}); }); });
    body.querySelectorAll('[data-batch-delete]').forEach(function (button) { button.addEventListener('click', function () { confirmBatchDelete(button.getAttribute('data-batch-delete')); }); });
}

function renderBatchHistory(history) {
    if (!history.length) {
        return '<div class="batch-history-empty"><strong>暂无执行历史</strong><span>任务完整执行或停止后，这里会保留最近 10 次记录。</span></div>';
    }
    return '<div class="batch-history-intro"><strong>最近 ' + history.length + ' 次完整执行</strong><span>手动执行单条用例不会单独生成历史。</span></div>' +
        '<div class="table-wrap batch-history-table-wrap"><table class="table execution-table batch-history-table"><thead><tr><th>测试集</th><th>工作流</th><th>执行进度</th><th>通过率</th><th>启动时间</th><th>结束时间</th></tr></thead><tbody>' +
        history.map(function (item) {
            var summary = {success: item.passed_cases, failed: Math.max(0, item.executed_cases - item.passed_cases)};
            return '<tr><td class="batch-table-text" title="' + escAttr(item.test_set_name) + '">' + esc(item.test_set_name) + '</td>' +
                '<td class="batch-table-text" title="' + escAttr(item.workflow_name) + '">' + esc(item.workflow_name) + '</td>' +
                '<td>' + batchProgress({total_cases: item.total_cases, summary: summary}) + '</td>' +
                '<td>' + renderBatchPassRate({summary: summary}) + '</td>' +
                '<td class="batch-time-cell">' + batchTableDateTime(item.started_at) + '</td>' +
                '<td class="batch-time-cell">' + batchTableDateTime(item.finished_at) + '</td></tr>';
        }).join('') + '</tbody></table></div>';
}

async function openBatchHistory(batchId) {
    try {
        var batch = executionState.batches.find(function (item) { return item.id === batchId; });
        var payload = await API.get('/api/batch-runs/' + encodeURIComponent(batchId) + '/history');
        openExecutionModal((batch ? batch.name + ' · ' : '') + '执行历史', renderBatchHistory(payload.history || []), async function () { closeExecutionModal(); }, '关闭');
        document.querySelector('.execution-modal').classList.add('is-batch-history');
        document.getElementById('execution-modal-cancel').style.display = 'none';
        document.getElementById('execution-modal-save').innerHTML = icon('close') + '关闭';
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
    }
}

function batchScheduleDefaults() {
    return {
        enabled: true,
        cadence: 'DAILY',
        run_at: '',
        run_time: '09:00',
        weekdays: ['1', '2', '3', '4', '5'],
        month_day: 1,
        timezone: 'Asia/Shanghai',
        overlap_policy: 'SKIP',
    };
}

function batchScheduleWeekdays(selected) {
    var labels = [['1', '一'], ['2', '二'], ['3', '三'], ['4', '四'], ['5', '五'], ['6', '六'], ['0', '日']];
    return labels.map(function (item) {
        return '<label><input type="checkbox" name="batch-schedule-weekday" value="' + item[0] + '" ' + (selected.includes(item[0]) ? 'checked' : '') + ' /><span>周' + item[1] + '</span></label>';
    }).join('');
}

function batchScheduleForm(batch, config) {
    var scheduleStatus = config.enabled && config.next_run_at
        ? '下次执行：' + batchTableDateTime(config.next_run_at)
        : config.enabled ? '等待计算下次执行时间' : '定时任务已关闭';
    return '<div class="batch-schedule-intro"><strong>' + esc(batch.name) + '</strong><span>' + esc(scheduleStatus) + '</span></div>' +
        '<label class="batch-schedule-enabled"><input id="batch-schedule-enabled" type="checkbox" ' + (config.enabled ? 'checked' : '') + ' /><span><strong>启用定时任务</strong><small>关闭后保留配置，但不会标记为启用。</small></span></label>' +
        '<fieldset id="batch-schedule-fields"><div class="batch-schedule-grid">' +
            '<label><span>调度方式</span><select class="input" id="batch-schedule-cadence"><option value="ONCE" ' + (config.cadence === 'ONCE' ? 'selected' : '') + '>仅执行一次</option><option value="DAILY" ' + (config.cadence === 'DAILY' ? 'selected' : '') + '>每天</option><option value="WEEKLY" ' + (config.cadence === 'WEEKLY' ? 'selected' : '') + '>每周</option><option value="MONTHLY" ' + (config.cadence === 'MONTHLY' ? 'selected' : '') + '>每月</option></select></label>' +
            '<label><span>时区</span><select class="input" id="batch-schedule-timezone"><option value="Asia/Shanghai" ' + (config.timezone === 'Asia/Shanghai' ? 'selected' : '') + '>Asia/Shanghai</option><option value="UTC" ' + (config.timezone === 'UTC' ? 'selected' : '') + '>UTC</option><option value="Asia/Tokyo" ' + (config.timezone === 'Asia/Tokyo' ? 'selected' : '') + '>Asia/Tokyo</option><option value="Europe/London" ' + (config.timezone === 'Europe/London' ? 'selected' : '') + '>Europe/London</option><option value="America/Los_Angeles" ' + (config.timezone === 'America/Los_Angeles' ? 'selected' : '') + '>America/Los_Angeles</option></select></label>' +
            '<label data-schedule-cadence="ONCE"><span>执行时间</span><input class="input" id="batch-schedule-run-at" type="datetime-local" value="' + escAttr(config.run_at) + '" /></label>' +
            '<label data-schedule-cadence="DAILY WEEKLY MONTHLY"><span>执行时间</span><input class="input" id="batch-schedule-run-time" type="time" value="' + escAttr(config.run_time) + '" /></label>' +
            '<div class="batch-schedule-weekdays" data-schedule-cadence="WEEKLY"><span>执行星期</span><div>' + batchScheduleWeekdays(config.weekdays) + '</div></div>' +
            '<label data-schedule-cadence="MONTHLY"><span>每月日期</span><input class="input" id="batch-schedule-month-day" type="number" min="1" max="31" value="' + escAttr(config.month_day) + '" /></label>' +
            '<label><span>任务重叠</span><select class="input" id="batch-schedule-overlap"><option value="SKIP" ' + (config.overlap_policy === 'SKIP' ? 'selected' : '') + '>跳过本次执行</option><option value="QUEUE" ' + (config.overlap_policy === 'QUEUE' ? 'selected' : '') + '>等待上次任务结束</option></select></label>' +
        '</div></fieldset>';
}

function updateBatchScheduleForm() {
    var cadence = document.getElementById('batch-schedule-cadence').value;
    document.querySelectorAll('[data-schedule-cadence]').forEach(function (element) {
        element.hidden = !element.dataset.scheduleCadence.split(' ').includes(cadence);
    });
    document.getElementById('batch-schedule-fields').disabled = !document.getElementById('batch-schedule-enabled').checked;
}

function readBatchScheduleForm() {
    return {
        enabled: document.getElementById('batch-schedule-enabled').checked,
        cadence: document.getElementById('batch-schedule-cadence').value,
        run_at: document.getElementById('batch-schedule-run-at').value,
        run_time: document.getElementById('batch-schedule-run-time').value,
        weekdays: Array.from(document.querySelectorAll('input[name="batch-schedule-weekday"]:checked')).map(function (input) { return input.value; }),
        month_day: Number(document.getElementById('batch-schedule-month-day').value),
        timezone: document.getElementById('batch-schedule-timezone').value,
        overlap_policy: document.getElementById('batch-schedule-overlap').value,
    };
}

function validateBatchSchedule(config) {
    if (!config.enabled) return;
    if (config.cadence === 'ONCE' && !config.run_at) throw new Error('请选择一次性任务的执行时间');
    if (['DAILY', 'WEEKLY', 'MONTHLY'].includes(config.cadence) && !config.run_time) throw new Error('请选择任务执行时间');
    if (config.cadence === 'WEEKLY' && !config.weekdays.length) throw new Error('每周任务至少选择一天');
    if (config.cadence === 'MONTHLY' && (config.month_day < 1 || config.month_day > 31)) throw new Error('每月日期必须在 1 到 31 之间');
}

function openBatchSchedule(batchId) {
    var batch = executionState.batches.find(function (item) { return item.id === batchId; });
    if (!batch) return;
    var config = Object.assign(batchScheduleDefaults(), executionState.batchSchedules[batchId] || {});
    if (!['ONCE', 'DAILY', 'WEEKLY', 'MONTHLY'].includes(config.cadence)) config.cadence = 'DAILY';
    config.weekdays = Array.from(config.weekdays || []);
    openExecutionModal('定时任务设置', batchScheduleForm(batch, config), async function () {
        var nextConfig = readBatchScheduleForm();
        validateBatchSchedule(nextConfig);
        var result = await API.put('/api/batch-runs/' + encodeURIComponent(batchId) + '/schedule', nextConfig);
        executionState.batchSchedules[batchId] = result.schedule;
        closeExecutionModal();
        renderBatchTable();
        showToast('定时任务设置已保存', 'success');
    }, '保存设置');
    document.querySelector('.execution-modal').classList.add('is-batch-schedule');
    document.getElementById('batch-schedule-enabled').addEventListener('change', updateBatchScheduleForm);
    document.getElementById('batch-schedule-cadence').addEventListener('change', updateBatchScheduleForm);
    updateBatchScheduleForm();
}

function confirmBatchDelete(batchId) {
    var batch = executionState.batches.find(function (item) { return item.id === batchId; });
    if (!batch) return;
    openExecutionModal('删除任务', '<p>确定删除“<strong>' + esc(batch.name) + '</strong>”及其全部执行记录吗？</p>', async function () {
        await API.del('/api/batch-runs/' + encodeURIComponent(batchId));
        closeExecutionModal();
        showToast('任务已删除', 'success');
        await loadBatchRuns();
    }, '删除');
}

async function batchCommand(button, batchId, command, body) {
    var commandAccepted = false;
    button.disabled = true;
    if (command === 'cancel') {
        button.classList.add('is-stopping');
        button.title = '正在等待运行中的工作流结束';
        button.setAttribute('aria-label', '正在停止');
    }
    try {
        await API.post('/api/batch-runs/' + encodeURIComponent(batchId) + '/' + command, body);
        commandAccepted = true;
        showToast(command === 'cancel' ? '已停止派发，正在等待运行中的工作流结束' : command === 'resume' ? '已继续执行未运行用例' : '任务已进入调度', 'success');
        await loadBatchRuns();
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
    } finally {
        if (command !== 'cancel' || !commandAccepted) {
            button.disabled = false;
            button.classList.remove('is-stopping');
        }
    }
}

async function loadBatchRuns() {
    try {
        var payload = await API.get('/api/batch-runs');
        executionState.batches = payload.batches || [];
        executionState.batchSchedules = {};
        executionState.batches.forEach(function (batch) {
            if (batch.schedule) executionState.batchSchedules[batch.id] = batch.schedule;
        });
        renderBatchTable();
        updateBatchListPolling(executionState.batches);
        scheduleBatchPoll(executionState.batches.some(function (batch) { return ['RUNNING', 'STOPPING'].includes(batch.status); }));
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
    }
}

function resetBatchListPolling() {
    executionState.batchListPollSignature = null;
    executionState.batchListUnchangedPolls = 0;
    executionState.batchListPollIntervalMs = BATCH_LIST_POLL_BASE_MS;
}

function updateBatchListPolling(batches) {
    var signature = JSON.stringify(batches);
    if (executionState.batchListPollSignature === null || signature !== executionState.batchListPollSignature) {
        executionState.batchListUnchangedPolls = 0;
        executionState.batchListPollIntervalMs = BATCH_LIST_POLL_BASE_MS;
    } else {
        executionState.batchListUnchangedPolls += 1;
        if (executionState.batchListUnchangedPolls >= BATCH_LIST_UNCHANGED_THRESHOLD) {
            executionState.batchListPollIntervalMs = Math.min(
                BATCH_LIST_POLL_MAX_MS,
                executionState.batchListPollIntervalMs + BATCH_LIST_POLL_BACKOFF_STEP_MS
            );
        }
    }
    executionState.batchListPollSignature = signature;
}

function scheduleBatchPoll(active) {
    if (executionState.batchPoll) clearTimeout(executionState.batchPoll);
    executionState.batchPoll = null;
    if (active && currentView === 'batch-runs') {
        executionState.batchPoll = setTimeout(loadBatchRuns, executionState.batchListPollIntervalMs);
    }
}

function viewBatchRuns() {
    currentView = 'batch-runs';
    executionState.batchDetailRequestId += 1;
    executionState.batchDetailRenderKey = '';
    scheduleBatchPoll(false);
    resetBatchListPolling();
    contentArea.innerHTML =
        '<section class="execution-page" aria-labelledby="batch-title">' +
            '<header class="execution-page-header management-page-header"><div class="management-page-title"><h1 id="batch-title">任务调度</h1><span class="management-page-description">执行任务并追踪结果</span></div><span class="execution-count" id="batch-count">0 个 Run</span></header>' +
            '<div class="toolbar execution-toolbar management-list-toolbar"><button class="btn btn-primary" id="btn-batch-add">' + icon('add') + '创建任务</button><button class="btn" id="btn-batch-refresh">' + icon('refresh') + '刷新</button></div>' +
            '<div class="table-wrap execution-table-wrap management-list-wrap batch-table-wrap"><table class="table execution-table management-list-table batch-table"><thead><tr><th>名称</th><th>测试集</th><th>工作流</th><th>执行进度</th><th>通过率</th><th>启动时间</th><th>结束时间</th><th class="management-list-actions-head batch-actions-head">操作</th></tr></thead><tbody id="batch-list-body"></tbody></table></div>' +
            '<div id="batch-pagination" class="global-list-footer management-list-footer"></div>' +
        '</section>';
    document.getElementById('btn-batch-add').addEventListener('click', function () { openBatchCreate(); });
    document.getElementById('btn-batch-refresh').addEventListener('click', function () {
        resetBatchListPolling();
        loadBatchRuns();
    });
    loadBatchRuns();
}

async function openBatchCreate(sourceBatchId, mode) {
    try {
        mode = mode || 'create';
        var requests = [
            API.get('/api/test-sets?page=1&page_size=200'),
            API.get('/api/workflows'),
        ];
        if (sourceBatchId) {
            requests.push(API.get('/api/batch-runs/' + encodeURIComponent(sourceBatchId)));
            if (mode === 'copy') requests.push(API.get('/api/batch-runs/' + encodeURIComponent(sourceBatchId) + '/copy-name'));
        }
        var values = await Promise.all(requests);
        var testSets = values[0].items || [];
        var workflows = values[1].workflows || [];
        var sourceBatch = values[2] ? values[2].batch : null;
        var copyName = mode === 'copy' && values[3] ? values[3].name : null;
        var sourceConfig = sourceBatch ? batchEditableConfig(sourceBatch) : null;
        if (!testSets.length || !workflows.length) {
            showToast(!testSets.length ? '请先创建测试集' : '请先创建工作流', 'error');
            return;
        }
        var body =
            '<section class="batch-config-card" aria-label="基础配置">' +
                '<div class="batch-create-grid">' +
                    '<label><span>名称</span><input class="input" id="batch-name" maxlength="200" placeholder="默认使用测试集和工作流名称" /></label>' +
                    '<label><span>失败重试</span><input class="input" id="batch-failure-retry-count" type="number" min="0" max="10" value="0" /></label>' +
                    '<label><span>测试集</span><select class="input" id="batch-test-set">' + testSets.map(function (testSet) { return '<option value="' + esc(testSet.id) + '">' + esc(testSet.name) + '</option>'; }).join('') + '</select></label>' +
                    '<label><span>工作流</span><select class="input" id="batch-workflow">' + workflows.map(function (workflow) { return '<option value="' + workflow.id + '">' + esc(workflow.name) + '</option>'; }).join('') + '</select></label>' +
                    '<label><span>用例列</span><select class="input" id="batch-case-display-column"></select></label>' +
                    '<label><span>规则列</span><select class="input" id="batch-rule-display-column"></select></label>' +
                    '<label><span>执行顺序</span><select class="input" id="batch-call-order"><option value="SEQUENTIAL">顺序</option><option value="REVERSE">逆序</option><option value="RANDOM">随机</option></select></label>' +
                    '<label><span>并发数</span><input class="input" id="batch-concurrency" type="number" min="1" max="32" value="4" /></label>' +
                '</div>' +
            '</section>' +
            '<section class="batch-variable-injection"><header><div class="batch-section-heading"><strong>变量注入</strong><span>注入到工作流 Context，节点可通过 context["变量名"] 读取</span></div><button class="btn btn-sm" id="batch-variable-add" type="button" disabled>' + icon('add') + '添加变量</button></header><div class="batch-variable-table" id="batch-variables"><div class="batch-variable-empty">正在读取测试集字段...</div></div></section>' +
            '<section class="batch-evaluation"><header><div class="batch-section-heading"><strong>结果校验</strong><span>从工作流 Context 中获取变量，路径填写 action_match 等价于 context.action_match</span></div><button class="btn btn-sm" id="batch-rule-add" type="button" disabled>' + icon('add') + '添加规则</button></header><div class="batch-evaluation-table" id="batch-evaluation-rules"></div></section>';
        executionState.batchConfigMode = mode;
        executionState.batchConfigTaskId = sourceBatchId || null;
        openExecutionModal(mode === 'edit' ? '编辑任务' : mode === 'copy' ? '拷贝任务' : '创建任务', body, createBatchFromModal, '保存');
        document.querySelector('.execution-modal').classList.add('is-batch-config');
        document.getElementById('execution-modal-save').disabled = true;
        document.getElementById('batch-test-set').addEventListener('change', function () { loadBatchPreview(); });
        document.getElementById('batch-variable-add').addEventListener('click', addBatchVariable);
        document.getElementById('batch-rule-add').addEventListener('click', function () { addBatchEvaluationRule(); });
        if (sourceBatch) {
            var testSetSelect = document.getElementById('batch-test-set');
            var workflowSelect = document.getElementById('batch-workflow');
            if (!Array.from(testSetSelect.options).some(function (option) { return option.value === sourceConfig.test_set_id; })) throw new Error('任务配置的测试集已不存在');
            if (!Array.from(workflowSelect.options).some(function (option) { return option.value === sourceConfig.workflow_id; })) throw new Error('任务配置的工作流已不存在');
            document.getElementById('batch-name').value = mode === 'copy' ? copyName : sourceConfig.name;
            document.getElementById('batch-failure-retry-count').value = sourceConfig.failure_retry_count || 0;
            testSetSelect.value = sourceConfig.test_set_id;
            workflowSelect.value = sourceConfig.workflow_id;
            document.getElementById('batch-call-order').value = sourceConfig.call_order || 'SEQUENTIAL';
            document.getElementById('batch-concurrency').value = sourceConfig.case_concurrency;
        }
        await loadBatchPreview(sourceConfig);
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
    }
}

function batchEditableConfig(batch) {
    var configuration = batch.configuration || {};
    var displayColumns = batch.input.display_columns || {};
    return {
        name: configuration.name || batch.name,
        test_set_id: configuration.test_set_id || batch.input.test_set_id,
        workflow_id: configuration.workflow_id || batch.workflow.id,
        variables: configuration.variables || batch.variables || [],
        evaluation_rules: configuration.evaluation_rules || batch.evaluation_rules || [],
        case_concurrency: configuration.case_concurrency || batch.case_concurrency || 1,
        failure_retry_count: configuration.failure_retry_count !== undefined ? configuration.failure_retry_count : (batch.failure_retry_count || 0),
        call_order: configuration.call_order || (batch.input.call_order && batch.input.call_order.mode) || 'SEQUENTIAL',
        case_display_column: configuration.case_display_column || displayColumns.case,
        rule_display_column: configuration.rule_display_column || displayColumns.rule,
    };
}

function batchVariableDrafts() {
    return Array.from(document.querySelectorAll('.batch-variable-row')).map(function (row) {
        return {
            source: row.querySelector('[data-variable-source]').value,
            key: row.querySelector('[data-variable-key]').value,
            value: row.querySelector('[data-variable-value]').value,
            type: row.querySelector('[data-variable-type]').value,
            is_new: row.classList.contains('is-new'),
        };
    });
}

function batchVariableValueControl(variable, headers) {
    if (variable.source === 'TEST_SET') {
        return '<input class="input" data-variable-value value="' + esc(variable.value) + '" placeholder="例如 col_1" aria-label="测试集字段" />';
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
    container.innerHTML = '<div class="batch-variable-head"><span>#</span><span>来源</span><span>Key</span><span>Value</span><span>类型</span><span></span></div>' + variables.map(function (variable, index) {
        return '<div class="batch-variable-row' + (variable.is_new ? ' is-new' : '') + '" data-variable-index="' + index + '">' +
            '<span class="batch-variable-index">' + (index + 1) + '</span>' +
            '<label><span class="batch-mobile-label">来源</span><select class="input" data-variable-source><option value="TEST_SET" ' + (variable.source === 'TEST_SET' ? 'selected' : '') + '>测试集字段</option><option value="CUSTOM" ' + (variable.source === 'CUSTOM' ? 'selected' : '') + '>自定义</option></select></label>' +
            '<label><span class="batch-mobile-label">Key</span><input class="input" data-variable-key value="' + esc(variable.key) + '" placeholder="例如 question" /></label>' +
            '<label><span class="batch-mobile-label">Value</span>' + batchVariableValueControl(variable, headers) + '</label>' +
            '<label><span class="batch-mobile-label">类型</span><select class="input" data-variable-type>' + types.map(function (type) { return '<option value="' + type + '" ' + (variable.type === type ? 'selected' : '') + '>' + type + '</option>'; }).join('') + '</select></label>' +
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
    variables.forEach(function (variable) { variable.is_new = false; });
    variables.unshift({source: 'TEST_SET', key: '', value: headers[0] || '', type: 'string', is_new: true});
    renderBatchVariables(variables, headers);
    var newRow = container.querySelector('.batch-variable-row.is-new');
    if (newRow) newRow.querySelector('[data-variable-key]').focus();
}

function batchRuleDrafts() {
    return Array.from(document.querySelectorAll('.batch-evaluation-rule')).map(function (row) {
        return {
            name: row.querySelector('[data-rule-name]').value,
            result_path: row.querySelector('[data-rule-result-path]').value,
            operator: row.querySelector('[data-rule-operator]').value,
            expected_value: row.querySelector('[data-rule-expected-value]').value,
            type: row.querySelector('[data-rule-type]').value,
            is_new: row.classList.contains('is-new'),
        };
    });
}

function batchRuleDisplayPath(path) {
    return String(path || '').replace(/^context\./, '');
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
        ['EXISTS', '存在'], ['NOT_EMPTY', '不为空'], ['GT', '大于'], ['GTE', '大于等于'], ['LT', '小于'],
        ['LTE', '小于等于'], ['JSON_EQUAL', 'JSON 相等'],
    ];
    var types = ['string', 'number', 'integer', 'boolean', 'object', 'array', 'null'];
    container.innerHTML = '<div class="batch-evaluation-head"><span>#</span><span>校验项</span><span>路径</span><span>运算符</span><span>预期值</span><span>类型</span><span></span></div>' + rules.map(function (rule, index) {
        var ignoresExpected = rule.operator === 'NOT_EMPTY';
        return '<div class="batch-evaluation-rule' + (rule.is_new ? ' is-new' : '') + '" data-rule-index="' + index + '">' +
            '<span class="batch-evaluation-index">' + (index + 1) + '</span>' +
            '<label><span class="batch-mobile-label">校验项</span><input class="input" data-rule-name value="' + esc(rule.name || '') + '" placeholder="选填" /></label>' +
            '<label><span class="batch-mobile-label">路径</span><input class="input" data-rule-result-path value="' + esc(batchRuleDisplayPath(rule.result_path)) + '" placeholder="例如 action_match" /></label>' +
            '<label><span class="batch-mobile-label">运算符</span><select class="input" data-rule-operator>' + operators.map(function (item) { return '<option value="' + item[0] + '" ' + (item[0] === rule.operator ? 'selected' : '') + '>' + item[1] + '</option>'; }).join('') + '</select></label>' +
            '<label><span class="batch-mobile-label">预期值</span><input class="input" data-rule-expected-value value="' + esc(ignoresExpected ? '' : (rule.expected_value || '')) + '" placeholder="' + (ignoresExpected ? '无需填写' : '例如 PASS') + '" ' + (ignoresExpected ? 'disabled' : '') + ' /></label>' +
            '<label><span class="batch-mobile-label">类型</span><select class="input" data-rule-type ' + (ignoresExpected ? 'disabled' : '') + '>' + types.map(function (type) { return '<option value="' + type + '" ' + (type === rule.type ? 'selected' : '') + '>' + type + '</option>'; }).join('') + '</select></label>' +
            '<button class="btn-icon" type="button" data-rule-delete title="删除规则" aria-label="删除规则">' + icon('trash') + '</button>' +
        '</div>';
    }).join('');
    container.querySelectorAll('.batch-evaluation-rule').forEach(function (row) {
        row.querySelector('[data-rule-operator]').addEventListener('change', function () {
            renderBatchEvaluationRules(batchRuleDrafts());
        });
        row.querySelector('[data-rule-delete]').addEventListener('click', function () {
            var remaining = batchRuleDrafts().filter(function (_item, index) { return index !== Number(row.dataset.ruleIndex); });
            renderBatchEvaluationRules(remaining);
        });
    });
}

function addBatchEvaluationRule() {
    var rules = batchRuleDrafts();
    rules.forEach(function (rule) { rule.is_new = false; });
    rules.unshift({name: '', result_path: '', operator: 'EQ', expected_value: '', type: 'string', is_new: true});
    renderBatchEvaluationRules(rules);
    var newRow = document.querySelector('.batch-evaluation-rule.is-new');
    if (newRow) newRow.querySelector('[data-rule-result-path]').focus();
}


async function loadBatchPreview(sourceConfig) {
    var testSetId = document.getElementById('batch-test-set').value;
    if (!testSetId) return;
    var requestId = ++executionState.batchPreviewRequestId;
    var saveButton = document.getElementById('execution-modal-save');
    var variableAddButton = document.getElementById('batch-variable-add');
    var ruleAddButton = document.getElementById('batch-rule-add');
    var variableContainer = document.getElementById('batch-variables');
    var variablesReady = variableContainer.dataset.ready === 'true';
    var evaluationContainer = document.getElementById('batch-evaluation-rules');
    var evaluationReady = evaluationContainer.dataset.ready === 'true';
    var variableDrafts = variablesReady ? batchVariableDrafts() : ((sourceConfig && sourceConfig.variables) || []);
    var evaluationDrafts = evaluationReady ? batchRuleDrafts() : ((sourceConfig && sourceConfig.evaluation_rules) || []);
    saveButton.disabled = true;
    variableAddButton.disabled = true;
    ruleAddButton.disabled = true;
    try {
        var preview = await API.post('/api/batch-runs/preview', {test_set_id: testSetId});
        if (requestId !== executionState.batchPreviewRequestId) return;
        variableDrafts = variableDrafts.map(function (variable) {
            var source = variable.source;
            var value = source === 'TEST_SET' && !preview.headers.includes(variable.value) ? (preview.headers[0] || '') : variable.value;
            return {source: source, key: variable.key, value: value, type: variable.type};
        });
        renderBatchVariables(variableDrafts, preview.headers);
        variableContainer.dataset.ready = 'true';
        renderBatchEvaluationRules(evaluationDrafts);
        evaluationContainer.dataset.ready = 'true';
        var displayColumns = sourceConfig ? {case: sourceConfig.case_display_column, rule: sourceConfig.rule_display_column} : {};
        [['case', 'batch-case-display-column'], ['rule', 'batch-rule-display-column']].forEach(function (item) {
            var select = document.getElementById(item[1]);
            var selected = select.value || displayColumns[item[0]] || preview.headers[0] || '';
            select.innerHTML = preview.headers.map(function (header) { return '<option value="' + esc(header) + '">' + esc(header) + '</option>'; }).join('');
            select.value = preview.headers.includes(selected) ? selected : (preview.headers[0] || '');
        });
        saveButton.disabled = false;
        variableAddButton.disabled = false;
        ruleAddButton.disabled = false;
    } catch (error) {
        if (requestId !== executionState.batchPreviewRequestId) return;
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
        if (!rule.result_path.trim()) throw new Error('校验规则 ' + (index + 1) + ' 的路径不能为空');
        if (rule.operator !== 'NOT_EMPTY' && !rule.expected_value.trim() && rule.type !== 'null') throw new Error('校验规则 ' + (index + 1) + ' 的预期值不能为空');
        return {
            name: rule.name.trim(),
            result_path: rule.result_path.trim(),
            operator: rule.operator,
            expected_value: rule.operator === 'NOT_EMPTY' ? '' : rule.type === 'null' ? 'null' : rule.expected_value,
            type: rule.operator === 'NOT_EMPTY' ? 'string' : rule.type,
        };
    });
    var requestBody = {
        name: document.getElementById('batch-name').value,
        test_set_id: document.getElementById('batch-test-set').value,
        workflow_id: document.getElementById('batch-workflow').value,
        variables: variables,
        case_concurrency: Number(document.getElementById('batch-concurrency').value),
        failure_retry_count: Number(document.getElementById('batch-failure-retry-count').value),
        call_order: document.getElementById('batch-call-order').value,
        evaluation_rules: evaluationRules,
        case_display_column: document.getElementById('batch-case-display-column').value,
        rule_display_column: document.getElementById('batch-rule-display-column').value,
    };
    var payload = executionState.batchConfigMode === 'edit'
        ? await API.put('/api/batch-runs/' + encodeURIComponent(executionState.batchConfigTaskId), requestBody)
        : await API.post('/api/batch-runs', requestBody);
    closeExecutionModal();
    showToast(executionState.batchConfigMode === 'edit' ? '任务已保存，下次执行时生效' : '任务已创建', 'success');
    await loadBatchRuns();
    return payload;

    } finally {
        executionState.batchCreating = false;
    }
}

async function viewBatchDetail(batchId, page, pageSize, roundId, options) {
    var enteringDetail = currentView !== 'batch-detail';
    currentView = 'batch-detail';
    scheduleBatchPoll(false);
    options = options || {};
    var requestId = ++executionState.batchDetailRequestId;
    if (enteringDetail) {
        executionState.batchDetailRenderKey = '';
        var cachedBatch = executionState.batches.find(function (item) { return item.id === batchId; });
        contentArea.innerHTML = '<section class="execution-page batch-detail">' +
            '<header class="execution-page-header batch-detail-header"><div class="batch-detail-title"><button class="btn btn-sm" id="batch-back">' + icon('back') + '返回</button><h1>' + esc(cachedBatch ? cachedBatch.name : '任务详情') + '</h1></div></header>' +
            '<div class="execution-loading" role="status">正在加载用例...</div>' +
        '</section>';
        document.getElementById('batch-back').addEventListener('click', viewBatchRuns);
    }
    page = page || 1;
    pageSize = normalizeGlobalPageSize(pageSize || executionState.batchDetailPageSize);
    executionState.batchDetailPageSize = pageSize;
    try {
        var roundQuery = roundId ? '&round_id=' + encodeURIComponent(roundId) : '';
        var caseQuery = '?page=' + page + '&page_size=' + pageSize + roundQuery +
            (executionState.batchDetailResultFilter ? '&result=' + encodeURIComponent(executionState.batchDetailResultFilter) : '') +
            (executionState.batchDetailStateFilter ? '&state=' + encodeURIComponent(executionState.batchDetailStateFilter) : '') +
            (executionState.batchDetailSearch ? '&q=' + encodeURIComponent(executionState.batchDetailSearch) : '');
        var values = await API.get('/api/batch-runs/' + encodeURIComponent(batchId) + '/cases' + caseQuery);
        if (requestId !== executionState.batchDetailRequestId || currentView !== 'batch-detail') return;
        var batch = values.batch;
        var isLatestRound = !roundId;
        var cases = values.cases || [];
        var renderKey = JSON.stringify([
            batch.id,
            batch.status,
            batch.started_at,
            batch.finished_at,
            values,
            executionState.batchDetailSort,
            executionState.batchDetailSortDirection,
            executionState.batchDetailResultFilter,
            executionState.batchDetailStateFilter,
            executionState.batchDetailSearch,
        ]);
        if (options.preservePosition && renderKey === executionState.batchDetailRenderKey) {
            if (isLatestRound && ['RUNNING', 'STOPPING'].includes(batch.status)) executionState.batchPoll = setTimeout(function () { viewBatchDetail(batchId, page, pageSize, roundId, {preservePosition: true}); }, BATCH_DETAIL_POLL_INTERVAL_MS);
            return;
        }
        executionState.batchDetailRenderKey = renderKey;
        if (executionState.batchDetailSort) {
            var sortKey = executionState.batchDetailSort;
            var direction = executionState.batchDetailSortDirection === 'asc' ? 1 : -1;
            cases.sort(function (left, right) { return direction * (batchCaseSortValue(left, sortKey) - batchCaseSortValue(right, sortKey)); });
        }
        var displayColumns = batch.input.display_columns || {case: (batch.input.columns || [])[0], rule: (batch.input.columns || [])[0]};
        var filterOptions = batchCaseFilterOptions(values.summary || {});
        var previousScrollTop = options.preservePosition ? contentArea.scrollTop : 0;
        var previousScrollLeft = options.preservePosition ? contentArea.scrollLeft : 0;
        var previousTableWrap = options.preservePosition ? contentArea.querySelector('.batch-case-table-wrap') : null;
        var previousTableScrollTop = previousTableWrap ? previousTableWrap.scrollTop : 0;
        var previousTableScrollLeft = previousTableWrap ? previousTableWrap.scrollLeft : 0;
        var activeElement = document.activeElement;
        var restoreSearchFocus = options.preservePosition && activeElement && activeElement.id === 'batch-case-search';
        var searchSelectionStart = restoreSearchFocus ? activeElement.selectionStart : null;
        var searchSelectionEnd = restoreSearchFocus ? activeElement.selectionEnd : null;
        contentArea.innerHTML = '<section class="execution-page batch-detail">' +
            '<header class="execution-page-header batch-detail-header"><div class="batch-detail-title"><button class="btn btn-sm" id="batch-back">' + icon('back') + '返回</button><h1>' + esc(batch.name) + '</h1></div></header>' +
            '<section class="batch-case-controls" aria-label="用例筛选"><div class="batch-result-cards">' + filterOptions.map(function (option) { var selected = option.kind === 'state' ? executionState.batchDetailStateFilter === option.value : executionState.batchDetailResultFilter === option.value; var filterLabel = option.kind === 'state' ? '执行状态' : '结果'; return '<button type="button" class="batch-result-card is-' + option.tone + (selected ? ' is-active' : '') + '" data-case-filter="' + esc(option.value) + '" data-filter-kind="' + option.kind + '" aria-label="按' + filterLabel + ' ' + esc(option.label) + ' 筛选" aria-pressed="' + (selected ? 'true' : 'false') + '"><span class="batch-result-card-label">' + icon(option.icon) + '<span>' + esc(option.label) + '</span></span><strong>' + option.count + '</strong></button>'; }).join('') + '</div><label class="batch-case-search" data-full-value="' + esc(executionState.batchDetailSearch) + '">' + icon('search') + '<input class="input" id="batch-case-search" value="' + esc(executionState.batchDetailSearch) + '" placeholder="搜索用例或规则" /></label></section>' +
            '<div class="table-wrap execution-table-wrap batch-case-table-wrap"><table class="table execution-table batch-case-table"><thead><tr><th>用例</th><th>规则</th><th><button class="table-head-action" data-batch-sort="count" title="按执行次数排序">执行次数' + icon('arrow-up-down') + '</button></th><th><button class="table-head-action" data-batch-sort="duration" title="按耗时排序">耗时' + icon('arrow-up-down') + '</button></th><th>结果</th><th class="batch-case-actions-head">操作</th></tr></thead><tbody>' + cases.map(function (item) { var result = batchCaseResult(item); var executionStatus = batchCaseExecutionStatus(item); var batchActive = ['RUNNING', 'STOPPING'].includes(batch.status); var canStartCase = isLatestRound && !batchActive && item.status !== 'RUNNING'; var operations = '<button class="btn-icon" data-case-open="' + item.id + '" title="查看用例详情">' + icon('browse') + '</button>' + (canStartCase ? '<button class="btn-icon" data-case-start="' + item.id + '" title="执行用例" aria-label="执行用例">' + icon('play') + '</button>' : ''); var resultCell = result ? '<span class="batch-case-result is-' + result.toLowerCase() + '"><i class="batch-case-result-mark" aria-hidden="true"></i><span>' + esc(batchCaseResultLabel(result)) + '</span></span>' : executionStatus ? '<span class="batch-case-execution-state is-' + executionStatus.toLowerCase() + '">' + executionStatus + '</span>' : '<span class="batch-case-empty-result">—</span>'; return '<tr><td class="batch-case-primary">' + esc(batchDisplayValue(item.source_values, displayColumns.case)) + '</td><td>' + esc(batchDisplayValue(item.source_values, displayColumns.rule)) + '</td><td>' + item.workflow_execution_ids.length + '</td><td>' + esc(batchCaseDuration(item)) + '</td><td>' + resultCell + '</td><td class="batch-case-actions-cell"><span class="batch-case-row-actions">' + (operations || '—') + '</span></td></tr>'; }).join('') + '</tbody></table></div><div id="batch-case-pagination" class="global-list-footer"></div>' +
        '</section>';
        document.getElementById('batch-back').addEventListener('click', viewBatchRuns);
        document.querySelectorAll('[data-case-start]').forEach(function (button) { button.addEventListener('click', async function () { button.disabled = true; try { await API.post('/api/batch-runs/' + batchId + '/cases/' + button.dataset.caseStart + '/start', {}); await viewBatchDetail(batchId, page, pageSize, roundId); } catch (error) { showToast(executionErrorMessage(error), 'error'); button.disabled = false; } }); });
        document.querySelectorAll('[data-batch-sort]').forEach(function (button) { button.addEventListener('click', function () { var next = button.dataset.batchSort; executionState.batchDetailSortDirection = executionState.batchDetailSort === next && executionState.batchDetailSortDirection === 'asc' ? 'desc' : 'asc'; executionState.batchDetailSort = next; viewBatchDetail(batchId, page, pageSize, roundId); }); });
        document.querySelectorAll('[data-case-filter]').forEach(function (button) { button.addEventListener('click', function () { var next = button.dataset.caseFilter; if (button.dataset.filterKind === 'state') { executionState.batchDetailStateFilter = executionState.batchDetailStateFilter === next ? '' : next; executionState.batchDetailResultFilter = ''; } else { executionState.batchDetailResultFilter = executionState.batchDetailResultFilter === next ? '' : next; executionState.batchDetailStateFilter = ''; } viewBatchDetail(batchId, 1, pageSize, roundId); }); });
        var searchInput = document.getElementById('batch-case-search');
        searchInput.addEventListener('input', function () {
            searchInput.parentElement.dataset.fullValue = searchInput.value;
            executionState.batchDetailSearch = searchInput.value.trim();
            if (executionState.batchDetailSearchTimer) clearTimeout(executionState.batchDetailSearchTimer);
            executionState.batchDetailSearchTimer = setTimeout(function () { viewBatchDetail(batchId, 1, pageSize, roundId, {preservePosition: true}); }, 220);
        });
        var caseRunsById = {};
        cases.forEach(function (caseRun) { caseRunsById[caseRun.id] = caseRun; });
        document.querySelectorAll('[data-case-open]').forEach(function (button) { button.addEventListener('click', function () { var caseRunId = button.getAttribute('data-case-open'); openBatchCaseDetail(batch, caseRunId, roundId, caseRunsById[caseRunId]); }); });
        renderGlobalListPagination('batch-case-pagination', values.total, values.page, values.page_size, function (nextPage) {
            viewBatchDetail(batchId, nextPage, pageSize, roundId);
        }, function (nextPageSize) {
            executionState.batchDetailPageSize = nextPageSize;
            viewBatchDetail(batchId, 1, nextPageSize, roundId);
        }, '条用例');
        if (options.preservePosition) {
            contentArea.scrollTop = previousScrollTop;
            contentArea.scrollLeft = previousScrollLeft;
            var nextTableWrap = contentArea.querySelector('.batch-case-table-wrap');
            if (nextTableWrap) {
                nextTableWrap.scrollTop = previousTableScrollTop;
                nextTableWrap.scrollLeft = previousTableScrollLeft;
            }
            if (restoreSearchFocus) {
                searchInput.focus({preventScroll: true});
                searchInput.setSelectionRange(searchSelectionStart, searchSelectionEnd);
            }
        }
        if (isLatestRound && ['RUNNING', 'STOPPING'].includes(batch.status)) executionState.batchPoll = setTimeout(function () { viewBatchDetail(batchId, page, pageSize, roundId, {preservePosition: true}); }, BATCH_DETAIL_POLL_INTERVAL_MS);
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
    }
}

function batchCaseResultLabel(result) {
    return result ? String(result).toUpperCase() : '—';
}

function batchCaseFilterOptions(summary) {
    return [
        {label: 'Pass', value: 'Pass', kind: 'result', tone: 'pass', icon: 'check', count: summary.Pass || 0},
        {label: 'Failed', value: 'Failed', kind: 'result', tone: 'failed', icon: 'close', count: summary.Failed || 0},
        {label: 'Error', value: 'Error', kind: 'result', tone: 'error', icon: 'close', count: summary.Error || 0},
        {label: 'Running', value: 'Running', kind: 'state', tone: 'running', icon: 'refresh', count: summary.Running || 0},
        {label: 'Pending', value: 'Pending', kind: 'state', tone: 'pending', icon: 'gauge', count: summary.Pending || 0},
    ];
}

function batchDisplayValue(values, column) {
    var value = values && column ? values[column] : null;
    if (value === null || value === undefined || value === '') return '—';
    return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

function batchCaseDuration(caseRun) {
    if (!caseRun.started_at || !caseRun.finished_at) return '—';
    var milliseconds = new Date(caseRun.finished_at).getTime() - new Date(caseRun.started_at).getTime();
    if (!Number.isFinite(milliseconds) || milliseconds < 0) return '—';
    return milliseconds < 1000 ? milliseconds + ' ms' : (milliseconds / 1000).toFixed(1) + ' s';
}

function batchCaseSortValue(caseRun, key) {
    if (key === 'count') return caseRun.workflow_execution_ids.length;
    if (!caseRun.started_at || !caseRun.finished_at) return -1;
    return new Date(caseRun.finished_at).getTime() - new Date(caseRun.started_at).getTime();
}

function batchCaseResult(caseRun) {
    if (['QUEUED', 'RUNNING', 'INTERRUPTED'].includes(caseRun.status) || ['NOT_STARTED', 'RUNNING', 'INTERRUPTED'].includes(caseRun.execution_status)) return '';
    if (caseRun.execution_status === 'SUCCESS' && caseRun.evaluation && caseRun.evaluation.verdict === 'FAIL') return 'Failed';
    if (caseRun.execution_status === 'SUCCESS' && caseRun.evaluation && caseRun.evaluation.verdict === 'ERROR') return 'Error';
    if (caseRun.execution_status === 'SUCCESS') return 'Pass';
    return 'Error';
}

function batchCaseExecutionStatus(caseRun) {
    if (caseRun.status === 'RUNNING' || caseRun.execution_status === 'RUNNING') return 'Running';
    if (caseRun.status === 'QUEUED' || caseRun.execution_status === 'NOT_STARTED') return 'Pending';
    return '';
}

function batchCaseDetailValue(value) {
    if (value === null || value === undefined || value === '') return '—';
    if (typeof value === 'string') return value;
    return JSON.stringify(value);
}

function batchCaseComparisonRows(caseRun, execution) {
    var rules = caseRun.evaluation && Array.isArray(caseRun.evaluation.rules) ? caseRun.evaluation.rules : [];
    var summary = execution && execution.result && execution.result.diagnostic_summary;
    var observed = summary && summary.observed && typeof summary.observed === 'object' ? summary.observed : {};
    var expected = summary && summary.expected && typeof summary.expected === 'object' ? summary.expected : {};
    var resultKeys = {
        root_cause_match: 'root_cause',
        risk_level_match: 'risk_level',
        action_match: 'recommended_action',
    };
    return rules.slice().sort(function (left, right) {
        return (left.status === 'PASS' ? 1 : 0) - (right.status === 'PASS' ? 1 : 0);
    }).map(function (rule) {
        var ruleKey = String(rule.result_path || '').replace(/^context\./, '').split('.').pop();
        var businessKey = resultKeys[ruleKey];
        return {
            label: String(rule.name || '').trim() || batchRuleDisplayPath(rule.result_path) || '—',
            expected: businessKey && Object.prototype.hasOwnProperty.call(expected, businessKey) ? expected[businessKey] : rule.expected,
            actual: businessKey && Object.prototype.hasOwnProperty.call(observed, businessKey) ? observed[businessKey] : rule.actual,
            status: rule.status || 'ERROR',
            message: rule.message || '',
        };
    });
}

function batchCaseNodeName(node) {
    return node && node.structural_snapshot && node.structural_snapshot.name
        ? node.structural_snapshot.name
        : node && node.type ? node.type : '未知节点';
}

function batchCaseProblemNode(nodes, result) {
    if (!Array.isArray(nodes)) return null;
    var statuses = ['FAILED', 'TIMEOUT', 'INTERRUPTED'];
    return nodes.find(function (node) { return statuses.includes(node.status); }) || null;
}

function batchCaseCanvasNodeType(node) {
    var type = String(node && node.type ? node.type : '').toUpperCase();
    return ['START', 'HTTP', 'LLM', 'SCRIPT', 'END'].includes(type) ? type : '—';
}

function batchCaseErrorInfo(error) {
    if (!error) return {message: ''};
    var details = typeof error === 'object' && error.details && typeof error.details === 'object' ? error.details : {};
    var rawMessage = typeof error === 'string' ? error : error.message || details.message || error.code || JSON.stringify(error);
    if (/connecterror|connection|unexpected_eof|ssl/i.test(rawMessage)) {
        return {message: '节点未能连接目标服务，未获得有效响应。'};
    }
    if (/timeout|timed out|超时/i.test(rawMessage)) {
        return {message: '目标服务在限定时间内没有返回结果。'};
    }
    return {message: rawMessage};
}

function batchCaseRawErrorMessage(error) {
    if (!error) return '—';
    if (typeof error === 'string') return error;
    if (error.message) return error.message;
    try {
        return JSON.stringify(error);
    } catch (_error) {
        return String(error);
    }
}

function batchCaseDetailModel(caseRun, execution, nodeExecutions) {
    var result = batchCaseResult(caseRun);
    var comparisons = batchCaseComparisonRows(caseRun, execution);
    var failedRules = comparisons.filter(function (rule) { return rule.status !== 'PASS'; });
    var problemNode = batchCaseProblemNode(nodeExecutions, result);
    var rawError = problemNode && problemNode.error ? problemNode.error : caseRun.error || (execution && execution.error);
    var errorInfo = batchCaseErrorInfo(rawError);
    var model = {
        result: result,
        tone: result ? result.toLowerCase() : caseRun.status === 'RUNNING' ? 'running' : 'not-run',
        icon: result === 'Pass' ? 'check' : result ? 'close' : 'gauge',
        comparisons: comparisons,
        failedRules: failedRules,
        problemNode: problemNode,
        errorInfo: errorInfo,
        rawErrorSummary: batchCaseRawErrorMessage(rawError),
        failureNodeName: problemNode ? batchCaseNodeName(problemNode) : '—',
        failureNodeType: batchCaseCanvasNodeType(problemNode),
        errorSummary: errorInfo.message || '—',
    };
    if (result === 'Failed') {
        model.title = failedRules.length === 1 ? failedRules[0].label + '不符合预期' : failedRules.length + ' 项规则未通过';
        model.description = '工作流已正常执行，失败来自结果校验。';
        model.failureNodeName = '结果校验';
        model.failureNodeType = '—';
        model.errorSummary = failedRules.length ? failedRules.map(function (rule) { return rule.label; }).join('、') + ' 未通过' : model.description;
    } else if (result === 'Error') {
        model.title = problemNode ? '节点“' + batchCaseNodeName(problemNode) + '”执行失败' : '工作流执行失败';
        model.description = errorInfo.message || '系统未能完成这条用例。';
        if (!problemNode) {
            model.failureNodeName = '工作流执行';
            model.failureNodeType = '—';
        }
    } else if (result === 'Pass') {
        model.title = '全部规则校验通过';
        model.description = '';
        model.failureNodeName = '—';
        model.failureNodeType = '—';
        model.errorSummary = '无报错';
    } else {
        model.title = caseRun.status === 'RUNNING' ? '用例正在执行' : '用例等待执行';
        model.description = caseRun.status === 'RUNNING' ? '结果将在工作流执行和规则校验完成后生成。' : '调度尚未开始执行这条用例。';
        model.failureNodeName = '—';
        model.failureNodeType = '—';
        model.errorSummary = '用例尚未执行';
    }
    return model;
}

function renderBatchCaseComparisons(model) {
    if (!model.comparisons.length) return '';
    return '<section class="batch-case-comparisons" aria-labelledby="batch-case-comparison-title">' +
        '<header><div><h3 id="batch-case-comparison-title">结果校验</h3></div></header>' +
        '<div class="batch-case-comparison-table"><table><thead><tr><th>校验项</th><th>期望值</th><th>实际值</th><th>结果</th></tr></thead><tbody>' +
        model.comparisons.map(function (row) {
            var passed = row.status === 'PASS';
            var state = passed ? 'pass' : 'failed';
            var detailMessage = row.message === '实际值不符合预期' ? '' : row.message;
            return '<tr class="is-' + state + '"><td><strong>' + esc(row.label) + '</strong></td>' +
                '<td><span class="batch-case-value">' + esc(batchCaseDetailValue(row.expected)) + '</span></td>' +
                '<td><span class="batch-case-value">' + esc(batchCaseDetailValue(row.actual)) + '</span>' +
                (detailMessage ? '<small>' + esc(detailMessage) + '</small>' : '') + '</td>' +
                '<td><span class="batch-case-rule-status is-' + state + '">' + (passed ? 'Pass' : 'Failed') + '</span></td></tr>';
        }).join('') + '</tbody></table></div></section>';
}

function renderBatchCaseProblemNode(model) {
    if (!model.problemNode) return '';
    var node = model.problemNode;
    return '<section class="batch-case-problem-node" aria-labelledby="batch-case-node-title"><header><h3 id="batch-case-node-title">问题节点</h3><p>工作流停在此处</p></header>' +
        '<dl><div><dt>节点</dt><dd>' + esc(batchCaseNodeName(node)) + '</dd></div><div><dt>类型</dt><dd>' + esc(node.type || '—') + '</dd></div>' +
        '<div><dt>状态</dt><dd>' + esc(node.status || '—') + '</dd></div><div><dt>尝试次数</dt><dd>' + esc(String(node.attempt_count || 0)) + '</dd></div></dl>' +
        '<div class="batch-case-problem-error"><span>报错概览</span><pre class="batch-case-selectable-log" tabindex="0">' + esc(model.rawErrorSummary) + '</pre></div></section>';
}

function batchCaseContextText(value) {
    var normalized = value;
    if (typeof value === 'string') {
        try {
            normalized = JSON.parse(value);
        } catch (_error) {
            return value;
        }
    }
    try {
        var formatted = JSON.stringify(normalized, null, 2);
        return formatted === undefined ? String(value === null || value === undefined ? '' : value) : formatted;
    } catch (_error) {
        return String(value === null || value === undefined ? '' : value);
    }
}

function renderBatchCaseDebugDetails(caseRun, execution, model) {
    var error = caseRun.error || (execution && execution.error) || null;
    var contextText = batchCaseContextText(execution && execution.context ? execution.context.final : {});
    return '<section class="batch-case-debug" aria-label="用例调试信息">' +
        '<details><summary>' + icon('database') + '<span>Context</span></summary><div class="batch-case-debug-content"><pre class="batch-case-selectable-log" tabindex="0">' + esc(contextText) + '</pre></div></details>' +
        '<details><summary>' + icon('alert') + '<span>错误与节点日志</span></summary><pre class="batch-case-selectable-log" tabindex="0">' + esc(JSON.stringify({error: error, problem_node: model.problemNode}, null, 2)) + '</pre></details></section>';
}

function renderBatchCaseDetailHeader(caseRun) {
    return '<div class="batch-case-modal-header"><div class="batch-case-modal-title"><strong>用例详情</strong></div><div class="batch-case-modal-meta"><span class="batch-case-outcome-metric">耗时 ' + esc(batchCaseDuration(caseRun)) + '</span><span class="batch-case-outcome-metric">执行次数 ' + caseRun.workflow_execution_ids.length + '</span></div></div>';
}

function renderBatchCaseDetail(batch, caseRun, execution, nodeExecutions, model) {
    model = model || batchCaseDetailModel(caseRun, execution, nodeExecutions);
    return '<div class="batch-case-detail is-' + esc(model.tone) + '">' +
        renderBatchCaseComparisons(model) + renderBatchCaseProblemNode(model) + renderBatchCaseDebugDetails(caseRun, execution, model) + '</div>';
}

async function openBatchCaseDetail(batch, caseRunId, roundId, caseRunSnapshot) {
    try {
        var caseRun = caseRunSnapshot;
        if (!caseRun) {
            var roundQuery = roundId ? '?round_id=' + encodeURIComponent(roundId) : '';
            var payload = await API.get('/api/batch-runs/' + encodeURIComponent(batch.id) + '/cases/' + encodeURIComponent(caseRunId) + roundQuery);
            caseRun = payload.case;
        }
        var execution = null;
        var nodeExecutions = [];
        if (caseRun.workflow_execution_ids.length) {
            var executionId = caseRun.workflow_execution_ids[caseRun.workflow_execution_ids.length - 1];
            execution = (await API.get('/api/workflows/' + encodeURIComponent(batch.workflow.id) + '/runs/' + encodeURIComponent(executionId))).execution;
            if (batchCaseResult(caseRun) === 'Error') {
                try {
                    nodeExecutions = (await API.get('/api/workflows/' + encodeURIComponent(batch.workflow.id) + '/runs/' + encodeURIComponent(executionId) + '/nodes')).executions || [];
                } catch (_error) {
                    nodeExecutions = [];
                }
            }
        }
        var model = batchCaseDetailModel(caseRun, execution, nodeExecutions);
        openExecutionModal('用例详情', renderBatchCaseDetail(batch, caseRun, execution, nodeExecutions, model),
            async function () { closeExecutionModal(); }, '关闭');
        var modal = document.querySelector('.execution-modal');
        modal.classList.add('is-case-detail', 'is-' + model.tone);
        document.getElementById('execution-modal-title').innerHTML = renderBatchCaseDetailHeader(caseRun);
        document.getElementById('execution-modal-cancel').style.display = 'none';
        document.querySelectorAll('.batch-case-selectable-log').forEach(function (pre) {
            pre.addEventListener('keydown', function (event) {
                if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'a') return;
                event.preventDefault();
                var range = document.createRange();
                range.selectNodeContents(pre);
                var selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
            });
        });
    } catch (error) {
        showToast(executionErrorMessage(error), 'error');
    }
}
