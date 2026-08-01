/* Workflow Structural Model UI. */
var BATCH_DETAIL_POLL_INTERVAL_MS = 1000;
var executionModalReturnFocus = null;

var executionState = {
    workflows: [],
    workflowPage: 1,
    workflowPageSize: 10,
    workflowListRequestId: 0,
    batchDetailPageSize: 10,
    batchDetailSort: null,
    batchDetailSortDirection: 'asc',
    batchDetailResultFilter: '',
    batchDetailStateFilter: '',
    batchDetailSearch: '',
    batchDetailSearchTimer: null,
    batchDetailRequestId: 0,
    batchDetailRenderKey: '',
    batchPoll: null,
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
        : resolvedSaveLabel.includes('创建') ? 'add'
        : resolvedSaveLabel.includes('关闭') ? 'close' : 'save';
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
        body.innerHTML = '<tr><td colspan="4">' + executionEmpty('尚未创建工作流', '新建工作流', 'workflow-empty-add') + '</td></tr>';
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
    var requestId = ++executionState.workflowListRequestId;
    try {
        var payload = await API.get('/api/workflows');
        if (requestId !== executionState.workflowListRequestId) return;
        executionState.workflows = payload.workflows || [];
        if (currentView !== 'workflows') return;
        renderWorkflowTable();
    } catch (error) {
        if (requestId !== executionState.workflowListRequestId || currentView !== 'workflows') return;
        showToast(executionErrorMessage(error), 'error');
    }
}

function viewWorkflows() {
    currentView = 'workflows';
    contentArea.innerHTML =
        '<section class="execution-page" aria-labelledby="workflows-title">' +
            '<header class="execution-page-header management-page-header"><div class="management-page-title"><h1 id="workflows-title">工作流管理</h1><span class="management-page-description">编排并验证工作流</span></div><span class="execution-count" id="workflow-count">0 个工作流</span></header>' +
            '<div class="toolbar execution-toolbar management-list-toolbar" id="workflows-toolbar">' +
                '<button class="btn btn-primary" id="btn-workflow-add" type="button">' + icon('add') + '新建工作流</button>' +
                '<button class="btn" id="btn-workflow-refresh" type="button">' + icon('refresh') + '刷新</button>' +
            '</div>' +
            '<div class="table-wrap execution-table-wrap management-list-wrap"><table class="table execution-table management-list-table workflow-table"><thead><tr><th>名称</th><th>说明</th><th>更新时间</th><th class="management-list-actions-head">操作</th></tr></thead><tbody id="workflow-list-body"></tbody></table></div>' +
            '<div id="workflow-pagination" class="global-list-footer management-list-footer"></div>' +
        '</section>';
    document.getElementById('btn-workflow-add').addEventListener('click', function () { openWorkflowCanvas(); });
    document.getElementById('btn-workflow-refresh').addEventListener('click', loadWorkflows);
    renderWorkflowTable();
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





function viewBatchRuns() {
    if (window.BatchRunManagement && typeof window.BatchRunManagement.mount === 'function') {
        window.BatchRunManagement.mount();
        return;
    }
    if (typeof window.viewBatchRunsWithAssets === 'function') window.viewBatchRunsWithAssets();
}

async function viewBatchDetail(batchId, page, pageSize, roundId, options) {
    var enteringDetail = currentView !== 'batch-detail';
    currentView = 'batch-detail';
    if (executionState.batchPoll) clearTimeout(executionState.batchPoll);
    executionState.batchPoll = null;
    options = options || {};
    var requestId = ++executionState.batchDetailRequestId;
    if (enteringDetail) {
        executionState.batchDetailRenderKey = '';
        contentArea.innerHTML = '<section class="execution-page batch-detail">' +
            '<header class="execution-page-header batch-detail-header"><div class="batch-detail-title"><button class="btn btn-sm" id="batch-back">' + icon('back') + '返回</button><h1>任务详情</h1></div></header>' +
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
            if (isLatestRound && ['RUNNING', 'STOPPING'].includes(batch.status)) executionState.batchPoll = setTimeout(function () {
                if (currentView === 'batch-detail') viewBatchDetail(batchId, page, pageSize, roundId, {preservePosition: true});
            }, BATCH_DETAIL_POLL_INTERVAL_MS);
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
        if (isLatestRound && ['RUNNING', 'STOPPING'].includes(batch.status)) executionState.batchPoll = setTimeout(function () {
            if (currentView === 'batch-detail') viewBatchDetail(batchId, page, pageSize, roundId, {preservePosition: true});
        }, BATCH_DETAIL_POLL_INTERVAL_MS);
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
        {label: 'Error', value: 'Error', kind: 'result', tone: 'error', icon: 'alert', count: summary.Error || 0},
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
    if (/interrupted|已停止|已中断|INTERRUPTED/i.test(rawMessage)) {
        return {message: '工作流已被中断，未完成的节点已停止。'};
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
