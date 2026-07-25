import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {python} from '@codemirror/lang-python';
import {EditorState} from '@codemirror/state';
import {EditorView} from '@codemirror/view';
import {oneDark} from '@codemirror/theme-one-dark';
import dagre from '@dagrejs/dagre';
import {basicSetup} from 'codemirror';
import parseCurl from 'parse-curl';
import {Rnd} from 'react-rnd';
import {split as splitShellWords} from 'shellwords';
import {
    Background,
    BaseEdge,
    Controls,
    EdgeLabelRenderer,
    Handle,
    MarkerType,
    MiniMap,
    Position,
    ReactFlow,
    ReactFlowProvider,
    addEdge,
    getBezierPath,
    useEdgesState,
    useNodesState,
    useReactFlow,
} from '@xyflow/react';
import {
    ArrowLeft,
    Bot,
    BrainCircuit,
    Check,
    ChevronRight,
    CirclePlay,
    Clipboard,
    Code2,
    Copy,
    ExternalLink,
    Eye,
    FileText,
    Globe2,
    LayoutGrid,
    LoaderCircle,
    Play,
    Plus,
    Redo2,
    RefreshCw,
    Save,
    Search,
    Settings2,
    SlidersHorizontal,
    Sparkles,
    Square,
    Trash2,
    Upload,
    WandSparkles,
    Undo2,
    Variable,
    X,
    Zap,
} from 'lucide-react';
import '@xyflow/react/dist/style.css';
import './workflow-canvas.css';

const NODE_TYPES = {
    START: {label: '开始', caption: 'START', icon: CirclePlay, color: '#16803c', executable: false},
    HTTP: {label: 'HTTP', caption: 'HTTP', icon: Globe2, color: '#2563eb', executable: true},
    AGENT: {label: 'AGENT', caption: 'AGENT', icon: Bot, color: '#0f766e', executable: true},
    LLM: {label: 'LLM', caption: 'LLM', icon: BrainCircuit, color: '#7048c6', executable: true},
    SCRIPT: {label: 'SCRIPT', caption: 'SCRIPT', icon: Code2, color: '#c56a12', executable: true},
    END: {label: '结束', caption: 'END', icon: Check, color: '#3f4b5f', executable: false},
};

const INSERTABLE_TYPES = ['HTTP', 'AGENT', 'LLM', 'SCRIPT'];
const NODE_STATUSES = ['PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'TIMEOUT', 'CANCELLED'];
const HTTP_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'];
const HTTP_BODY_TYPES = ['none', 'form-data', 'x-www-form-urlencoded', 'raw'];
const OUTPUT_VARIABLE_TYPES = ['AUTO', 'STRING', 'INTEGER', 'NUMBER', 'BOOLEAN', 'OBJECT', 'ARRAY'];
const DEFAULT_AGENT_MAIN_PY = 'response = inputs';
const DEFAULT_SCRIPT_MAIN_PY = 'msg = "介绍一下自己"\nprint(msg)';
const LLM_PARAMETERS_REFERENCE = JSON.stringify({
    thinking: {type: 'disabled'},
    temperature: 0,
    top_p: 0.8,
    max_tokens: 1024,
    response_format: {type: 'json_object'},
}, null, 2);

function nodeId(type) {
    return window.crypto.randomUUID();
}

function rowId() {
    return `row_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

function formatExecutionDuration(value) {
    const durationMs = Math.max(0, Math.round(Number(value) || 0));
    return durationMs < 1000 ? `${durationMs}ms` : `${(durationMs / 1000).toFixed(1)}s`;
}

function formatRunDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '-- --:--:--';
    const pad = (part) => String(part).padStart(2, '0');
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function modelParametersEditorText(parameters) {
    const editableParameters = {...(parameters || {})};
    delete editableParameters.stream;
    return Object.keys(editableParameters).length
        ? JSON.stringify(editableParameters, null, 2)
        : '';
}

function normalizeTokenCount(value) {
    if (value === null || value === undefined || value === '') return null;
    const count = Number(value);
    return Number.isFinite(count) && count >= 0 ? Math.round(count) : null;
}

function streamingUsageFromResponse(responseBody) {
    const usage = {};
    String(responseBody || '').split(/\r?\n/).forEach((rawLine) => {
        const line = rawLine.trim();
        if (!line.startsWith('data:')) return;
        const data = line.slice(5).trim();
        if (!data || data === '[DONE]') return;
        try {
            const payload = JSON.parse(data);
            if (!isPlainObject(payload)) return;
            const candidates = [payload.usage];
            if (isPlainObject(payload.message)) candidates.push(payload.message.usage);
            candidates.forEach((candidate) => {
                if (isPlainObject(candidate)) Object.assign(usage, candidate);
            });
        } catch (_error) {
            // Raw streaming output can contain non-JSON provider events.
        }
    });
    return Object.keys(usage).length ? usage : null;
}

function formatRunTokenUsage(run) {
    const usage = isPlainObject(run?.usage)
        ? run.usage
        : streamingUsageFromResponse(run?.response_body) || {};
    const total = normalizeTokenCount(usage.total_tokens);
    if (total !== null) return `${total} tokens`;
    const pairs = [
        [normalizeTokenCount(usage.prompt_tokens), normalizeTokenCount(usage.completion_tokens)],
        [normalizeTokenCount(usage.input_tokens), normalizeTokenCount(usage.output_tokens)],
    ];
    const pair = pairs.find(([input, output]) => input !== null || output !== null);
    return pair ? `${(pair[0] || 0) + (pair[1] || 0)} tokens` : '-- tokens';
}

function cloneValue(value) {
    return JSON.parse(JSON.stringify(value));
}

function validateWorkflowGraph(nodes, edges) {
    if (!nodes.length) return 'Workflow 至少需要一个节点';
    const adjacency = new Map(nodes.map((node) => [node.id, new Set()]));
    const degree = new Map(nodes.map((node) => [node.id, 0]));
    const indegree = new Map(nodes.map((node) => [node.id, 0]));
    edges.forEach((edge) => {
        if (!adjacency.has(edge.source) || !adjacency.has(edge.target)) return;
        if (!adjacency.get(edge.source).has(edge.target)) {
            adjacency.get(edge.source).add(edge.target);
            indegree.set(edge.target, indegree.get(edge.target) + 1);
        }
        degree.set(edge.source, degree.get(edge.source) + 1);
        degree.set(edge.target, degree.get(edge.target) + 1);
    });
    const orphaned = nodes.length === 1 ? [] : nodes.filter((node) => degree.get(node.id) === 0);
    if (orphaned.length) {
        const labels = orphaned.map((node) => node.data?.label || node.id).join(', ');
        return `Workflow 存在游离节点: ${labels}`;
    }
    const pending = nodes.filter((node) => indegree.get(node.id) === 0).map((node) => node.id);
    const processed = new Set();
    while (pending.length) {
        const current = pending.pop();
        processed.add(current);
        adjacency.get(current).forEach((target) => {
            indegree.set(target, indegree.get(target) - 1);
            if (indegree.get(target) === 0) pending.push(target);
        });
    }
    if (processed.size !== nodes.length) {
        const labels = nodes.filter((node) => !processed.has(node.id)).map((node) => node.data?.label || node.id).join(', ');
        return `Workflow 存在循环依赖: ${labels}`;
    }
    return '';
}

function isPlainObject(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function modelProviderName(provider) {
    return provider?.name || '未命名供应商';
}

function modelReferenceStatus(providers, providerId, modelName) {
    if (!providerId && !modelName) return {state: 'empty', provider: null};
    const provider = providers.find((item) => item.id === providerId) || null;
    if (!provider || !(provider.models || []).includes(modelName)) {
        return {state: 'invalid', provider};
    }
    return {state: 'valid', provider};
}

function parameterDataText(value, pretty = false) {
    if (typeof value === 'string') return value;
    try {
        const serialized = JSON.stringify(value, null, pretty ? 2 : 0);
        return serialized === undefined ? String(value) : serialized;
    } catch (_error) {
        return String(value);
    }
}

function parameterDataSummary(value) {
    const text = parameterDataText(value).replace(/\s+/g, ' ').trim();
    return text.length > 180 ? `${text.slice(0, 177)}...` : text;
}

function hasBrowserTextSelection() {
    return Boolean(window.getSelection?.()?.toString());
}

async function copyTextToClipboard(text) {
    try {
        const response = await fetch('/api/local/clipboard', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({text}),
        });
        if (response.ok) return;
    } catch (_error) {
        // The local clipboard endpoint is unavailable outside the desktop app.
    }
    if (navigator.clipboard?.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return;
        } catch (_error) {
            // Some embedded browsers expose Clipboard API but deny write permission.
        }
    }
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    let copied = false;
    const handleCopy = (event) => {
        if (!event.clipboardData) return;
        event.clipboardData.setData('text/plain', text);
        event.preventDefault();
        copied = true;
        event.stopImmediatePropagation();
    };
    try {
        document.addEventListener('copy', handleCopy, true);
        textarea.focus();
        textarea.select();
        textarea.setSelectionRange(0, textarea.value.length);
        copied = document.execCommand('copy') || copied;
    } finally {
        document.removeEventListener('copy', handleCopy, true);
        textarea.remove();
    }
    if (copied) return;
    throw new Error('浏览器拒绝了复制操作');
}

function PythonCodeEditor({value, onChange}) {
    const hostRef = useRef(null);
    const viewRef = useRef(null);
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;

    useEffect(() => {
        if (!hostRef.current) return undefined;
        const view = new EditorView({
            parent: hostRef.current,
            state: EditorState.create({
                doc: value || '',
                extensions: [
                    basicSetup,
                    python(),
                    oneDark,
                    EditorView.lineWrapping,
                    EditorView.contentAttributes.of({
                        'aria-label': 'main.py',
                        spellcheck: 'false',
                    }),
                    EditorView.updateListener.of((update) => {
                        if (update.docChanged) {
                            onChangeRef.current(update.state.doc.toString());
                        }
                    }),
                ],
            }),
        });
        viewRef.current = view;
        return () => {
            view.destroy();
            viewRef.current = null;
        };
    }, []);

    useEffect(() => {
        const view = viewRef.current;
        const nextValue = value || '';
        if (!view || view.state.doc.toString() === nextValue) return;
        view.dispatch({
            changes: {from: 0, to: view.state.doc.length, insert: nextValue},
        });
    }, [value]);

    return <div className="wf-python-editor" ref={hostRef} />;
}

async function copyHttpLogContent(text, label) {
    try {
        await copyTextToClipboard(text);
        if (window.showToast) window.showToast(`已复制${label.replace(/^复制/, '')}`, 'success');
    } catch (error) {
        if (window.showToast) window.showToast(error instanceof Error ? error.message : '复制失败', 'error');
    }
}

function HttpLogCopyButton({text, label}) {
    return (
        <button
            type="button"
            className="wf-http-log-copy"
            title={label}
            aria-label={label}
            onClick={() => copyHttpLogContent(text, label)}
        >
            <Copy size={13} />
        </button>
    );
}

function HttpLogSection({title, text}) {
    return (
        <section className="wf-http-log-section">
            <header>
                <strong>{title}</strong>
                <HttpLogCopyButton text={text} label={`复制${title}`} />
            </header>
            <pre aria-label={`${title}内容`}>{text}</pre>
        </section>
    );
}

function rawHttpScalar(value) {
    if (value === undefined || value === null) return '';
    return typeof value === 'string' ? value : parameterDataText(value);
}

function appendHttpParameters(searchParams, values) {
    if (!values || typeof values !== 'object' || Array.isArray(values)) return;
    Object.entries(values).forEach(([key, value]) => {
        const entries = Array.isArray(value) ? value : [value];
        entries.forEach((entry) => searchParams.append(key, rawHttpScalar(entry)));
    });
}

function rawHttpRequestUrl(request) {
    const url = String(request?.url || '');
    const params = request?.params;
    if (!params || typeof params !== 'object' || Array.isArray(params) || !Object.keys(params).length) return url;
    try {
        const parsed = new URL(url);
        appendHttpParameters(parsed.searchParams, params);
        parsed.hash = '';
        return parsed.toString();
    } catch (_error) {
        const searchParams = new URLSearchParams();
        appendHttpParameters(searchParams, params);
        const query = searchParams.toString();
        return query ? `${url}${url.includes('?') ? '&' : '?'}${query}` : url;
    }
}

function rawHttpRequestBody(request) {
    const bodyType = String(request?.body_type || 'NONE').toUpperCase();
    if (bodyType === 'NONE' || request?.body === undefined || request?.body === null) return '';
    if (bodyType === 'FORM_DATA' || bodyType === 'FORM_URLENCODED') {
        if (typeof request.body === 'string') return request.body;
        const form = new URLSearchParams();
        appendHttpParameters(form, request.body);
        return form.toString();
    }
    return rawHttpScalar(request.body);
}

function rawHttpRequest(request) {
    const method = String(request?.method || 'GET').toUpperCase();
    const requestLine = `${method} ${rawHttpRequestUrl(request)} HTTP/1.1`;
    const headers = request?.headers && typeof request.headers === 'object' && !Array.isArray(request.headers)
        ? Object.entries(request.headers).map(([key, value]) => {
            const headerValue = Array.isArray(value)
                ? value.map((item) => rawHttpScalar(item)).join(', ')
                : rawHttpScalar(value);
            return `${key}: ${headerValue}`;
        })
        : [];
    return [requestLine, ...headers, '', rawHttpRequestBody(request)].join('\n');
}

function HttpRequestLogSection({request}) {
    const rawText = rawHttpRequest(request);
    return <HttpLogSection title="request" text={rawText} />;
}

function runResultSummary(run) {
    if (run.status === 'RUNNING') {
        const liveText = typeof run.response_body === 'string'
            ? run.response_body.replace(/\s+/g, ' ').trim()
            : '';
        if (!liveText) return '正在接收原始响应…';
        return liveText.length > 160 ? `${liveText.slice(0, 157)}...` : liveText;
    }
    const value = ['FAILED', 'INTERRUPTED'].includes(run.status) ? run.error?.message : run.output;
    const text = parameterDataText(value).replace(/\s+/g, ' ').trim();
    if (!text) return '无最终结果';
    return text.length > 160 ? `${text.slice(0, 157)}...` : text;
}

function emptyMappingRow() {
    return {id: rowId(), name: '', type: 'AUTO', value: '', pythonVariable: ''};
}

function emptyKeyValueRow(key = '', value = '') {
    return {id: rowId(), key, value};
}

function defaultHttpConfig() {
    return {
        method: 'POST',
        url: '',
        headers: [emptyKeyValueRow('Content-Type', 'application/json')],
        params: [],
        bodyType: 'none',
        bodyText: '',
        bodyFields: [],
        followRedirects: true,
        proxyMode: 'SYSTEM',
        proxyUrl: '',
        proxyUsername: '',
        proxyPassword: '',
        verifySsl: true,
        responseBodyType: 'json',
    };
}

function optionValues(args, names) {
    const values = [];
    args.forEach((arg, index) => {
        if (names.includes(arg) && args[index + 1] !== undefined) values.push(args[index + 1]);
        const matchedName = names.find((name) => arg.startsWith(`${name}=`));
        if (matchedName) values.push(arg.slice(matchedName.length + 1));
    });
    return values;
}

function splitKeyValue(value, separator) {
    const index = value.indexOf(separator);
    return index < 0
        ? emptyKeyValueRow(value, '')
        : emptyKeyValueRow(value.slice(0, index), value.slice(index + separator.length));
}

function parseCurlRequest(command) {
    const source = command.trim().replace(/^\$\s+/, '');
    if (!/^curl(?:\.exe)?\s/i.test(source)) throw new Error('请输入有效的 cURL 命令');
    const args = splitShellWords(source);
    const normalized = source
        .replace(/--data-raw(?=\s|=)/g, '--data')
        .replace(/--data-binary(?=\s|=)/g, '--data')
        .replace(/--data-urlencode(?=\s|=)/g, '--data');
    const parsed = parseCurl(normalized);
    if (!parsed?.url) throw new Error('cURL 命令缺少有效的 HTTP URL');

    let url;
    try {
        url = new URL(parsed.url);
    } catch {
        throw new Error('cURL URL 无效');
    }
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error('cURL 仅支持 HTTP 或 HTTPS URL');

    const params = Array.from(url.searchParams.entries(), ([key, value]) => emptyKeyValueRow(key, value));
    url.search = '';
    url.hash = '';

    const explicitHeaders = optionValues(args, ['-H', '--header'])
        .map((value) => splitKeyValue(value, ':'))
        .map((row) => ({...row, key: row.key.trim(), value: row.value.trim()}));
    const headers = [...explicitHeaders];
    Object.entries(parsed.header || {}).forEach(([key, value]) => {
        if (!headers.some((row) => row.key.toLowerCase() === key.toLowerCase())) {
            headers.push(emptyKeyValueRow(key, String(value)));
        }
    });

    const contentType = headers.find((row) => row.key.toLowerCase() === 'content-type')?.value.toLowerCase() || '';
    const formValues = optionValues(args, ['-F', '--form', '--form-string']);
    const binaryValues = optionValues(args, ['--data-binary']);
    const explicitMethods = optionValues(args, ['-X', '--request']);
    const compactMethod = args.find((arg) => /^-X[^-]/.test(arg))?.slice(2);
    const rawBody = parsed.body || '';
    let bodyType = 'none';
    let bodyText = '';
    let bodyFields = [];
    let binaryFileName = '';

    if (formValues.length) {
        bodyType = 'form-data';
        bodyFields = formValues.map((value) => splitKeyValue(value, '='));
    } else if (binaryValues.some((value) => value.startsWith('@'))) {
        bodyType = 'binary';
        binaryFileName = binaryValues.find((value) => value.startsWith('@')).slice(1);
    } else if (rawBody && contentType.includes('application/x-www-form-urlencoded')) {
        bodyType = 'x-www-form-urlencoded';
        bodyFields = Array.from(new URLSearchParams(rawBody).entries(), ([key, value]) => emptyKeyValueRow(key, value));
    } else if (rawBody) {
        bodyType = 'raw';
        bodyText = rawBody;
    }

    const explicitMethod = explicitMethods[explicitMethods.length - 1] || compactMethod;
    const inferredMethod = !explicitMethod && bodyType !== 'none' && parsed.method === 'GET'
        ? 'POST'
        : parsed.method;
    return {
        method: String(explicitMethod || inferredMethod || 'GET').toUpperCase(),
        url: url.toString(),
        headers,
        params,
        bodyType,
        bodyText,
        bodyFields,
        binaryFileName,
    };
}

function makeNode(type, position, overrides = {}) {
    const meta = NODE_TYPES[type];
    return {
        id: nodeId(type),
        type: 'workflowNode',
        position,
        data: {
            nodeType: type,
            label: meta.label,
            description: '',
            status: 'PENDING',
            executionDurationMs: 0,
            timeoutMs: 120000,
            retryCount: 0,
            retryIntervalMs: 0,
            outputVariables: [emptyMappingRow()],
            parameterRecords: [],
            ...(type === 'HTTP' ? {httpConfig: defaultHttpConfig()} : {}),
            ...(type === 'LLM' ? {
                providerId: '',
                modelName: '',
                systemPrompt: '',
                userPrompt: '',
                modelParameters: {},
            } : {}),
            ...(type === 'AGENT' ? {mainPy: DEFAULT_AGENT_MAIN_PY} : {}),
            ...(type === 'SCRIPT' ? {mainPy: DEFAULT_SCRIPT_MAIN_PY} : {}),
            ...overrides,
        },
    };
}

function makeEdge(source, target, overrides = {}) {
    return {
        id: window.crypto.randomUUID(),
        source,
        target,
        type: 'insertable',
        markerEnd: {type: MarkerType.ArrowClosed, width: 16, height: 16, color: '#9aa8ba'},
        ...overrides,
    };
}

function layoutGraph(nodes, edges) {
    const graph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
    graph.setGraph({rankdir: 'LR', ranksep: 78, nodesep: 56, marginx: 40, marginy: 40});
    nodes.forEach((node) => graph.setNode(node.id, {width: 236, height: 112}));
    edges.forEach((edge) => graph.setEdge(edge.source, edge.target));
    dagre.layout(graph);
    return nodes.map((node) => {
        const point = graph.node(node.id);
        return {
            ...node,
            position: {x: point.x - 118, y: point.y - 56},
        };
    });
}

function initialGraph() {
    const request = makeNode('HTTP', {x: 360, y: 280}, {label: '调用业务接口'});
    const llm = makeNode('LLM', {x: 675, y: 100}, {label: '模型质量判断'});
    const script = makeNode('SCRIPT', {x: 675, y: 420}, {label: '规则校验'});
    return {
        nodes: [request, llm, script],
        edges: [
            makeEdge(request.id, llm.id),
            makeEdge(request.id, script.id),
        ],
    };
}

function graphFromDraft(draft) {
    if (!draft?.nodes?.length) return initialGraph();
    const needsLayout = draft.nodes.every((stored) => !stored.position);
    const nodes = draft.nodes.map((stored) => {
        const type = stored.data?.nodeType || 'SCRIPT';
        const defaults = makeNode(type, stored.position || {x: 0, y: 0});
        const storedData = cloneValue(stored.data || {});
        if (type === 'SCRIPT' && Array.isArray(storedData.outputVariables)) {
            storedData.outputVariables = storedData.outputVariables.map((row) => (
                row?.name && !row.pythonVariable && row.value
                    ? {...row, pythonVariable: row.name, value: ''}
                    : row
            ));
        }
        return {
            ...defaults,
            ...cloneValue(stored),
            id: stored.id,
            position: cloneValue(stored.position || {x: 0, y: 0}),
            data: {
                ...defaults.data,
                ...storedData,
                status: 'PENDING',
                executionDurationMs: 0,
                runHistory: [],
                executionId: null,
                isDirty: false,
            },
        };
    });
    const loadedEdges = cloneValue(draft.edges || []);
    return {nodes: needsLayout ? layoutGraph(nodes, loadedEdges) : nodes, edges: loadedEdges};
}

function serializableNode(node) {
    const data = cloneValue(node.data || {});
    for (const key of ('status executionDurationMs runHistory executionId savedAt isDirty'.split(' '))) {
        delete data[key];
    }
    return {
        id: node.id,
        type: node.type || 'workflowNode',
        position: cloneValue(node.position),
        data,
    };
}

function serializableEdge(edge) {
    return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: edge.type || 'insertable',
        markerEnd: cloneValue(edge.markerEnd || {}),
    };
}

function WorkflowNode({data, selected}) {
    const meta = NODE_TYPES[data.nodeType] || NODE_TYPES.SCRIPT;
    const Icon = meta.icon;
    const status = NODE_STATUSES.includes(data.status) ? data.status : 'PENDING';
    const statusClass = status.toLowerCase();
    const executionDuration = formatExecutionDuration(data.executionDurationMs);
    const running = status === 'RUNNING';
    return (
        <article className={`wf-node ${selected ? 'is-selected' : ''} is-${statusClass}`} style={{'--node-accent': meta.color}}>
            {data.nodeType !== 'START' && <Handle type="target" position={Position.Left} className="wf-handle" />}
            <header className="wf-node-header">
                <span className="wf-node-icon"><Icon size={17} strokeWidth={2} /></span>
                <span className="wf-node-caption">{meta.caption}</span>
                <span className="wf-node-actions">
                    <button type="button" disabled={running} title="运行" aria-label={`运行 ${data.label}`} onClick={(event) => {event.stopPropagation(); data.onRun?.();}}><Play size={13} /></button>
                    <button type="button" disabled={!running} className="is-danger" title="中断" aria-label={`中断 ${data.label}`} onClick={(event) => {event.stopPropagation(); data.onInterrupt?.();}}><Square size={12} /></button>
                </span>
            </header>
            <strong className="wf-node-title">{data.label}</strong>
            <footer className="wf-node-footer">
                <span className={`wf-node-status is-${statusClass}`}><i />{status}</span>
                <span className="wf-node-meta">
                    {meta.executable && <span className="wf-node-runtime">{data.nodeType === 'LLM' ? 'Gateway' : 'Python'}</span>}
                    {data.savedAt && !data.isDirty && <span className="wf-node-saved-state"><Check size={10} />已保存</span>}
                    <span className={`wf-node-execution is-${statusClass}`} aria-label={`执行耗时 ${executionDuration}`}>
                        <LoaderCircle className="wf-execution-spinner" size={12} />
                        <span>{executionDuration}</span>
                    </span>
                </span>
            </footer>
            {data.nodeType !== 'END' && <Handle type="source" position={Position.Right} className="wf-handle" />}
        </article>
    );
}

function NodePicker({onSelect, compact = false, includeSystem = false}) {
    const types = includeSystem ? ['START', 'END', ...INSERTABLE_TYPES] : INSERTABLE_TYPES;
    return (
        <div className={`wf-node-picker ${compact ? 'is-compact' : ''}`} role="menu">
            {types.map((type) => {
                const meta = NODE_TYPES[type];
                const Icon = meta.icon;
                return (
                    <button type="button" key={type} onClick={() => onSelect(type)} role="menuitem">
                        <span style={{'--picker-accent': meta.color}}><Icon size={16} /></span>
                        <span><strong>{meta.label}</strong>{meta.caption !== meta.label && <small>{meta.caption}</small>}</span>
                    </button>
                );
            })}
        </div>
    );
}

function InsertableEdge({id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, data}) {
    const [path, labelX, labelY] = getBezierPath({sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition});
    return (
        <>
            <BaseEdge id={id} path={path} markerEnd={markerEnd} className="wf-edge-path" />
            <EdgeLabelRenderer>
                <div className="wf-edge-action" style={{transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`}}>
                    <button type="button" className="wf-edge-plus nodrag nopan" title="快速插入节点" aria-label="快速插入节点" onClick={(event) => {event.stopPropagation(); data.onToggleInsert(id);}}>
                        <Plus size={14} />
                    </button>
                    {data.insertOpen && (
                        <div className="wf-edge-picker nodrag nopan">
                            <NodePicker compact onSelect={(type) => data.onInsert(id, type)} />
                        </div>
                    )}
                </div>
            </EdgeLabelRenderer>
        </>
    );
}

const nodeTypes = {workflowNode: WorkflowNode};
const edgeTypes = {insertable: InsertableEdge};

function ContextMenu({menu, canPaste, onAction, onAdd}) {
    const [submenuOpen, setSubmenuOpen] = useState(false);
    useEffect(() => setSubmenuOpen(false), [menu?.kind, menu?.x, menu?.y]);
    if (!menu) return null;
    if (menu.kind === 'edge') {
        return (
            <div className="wf-context-menu" style={{left: menu.x, top: menu.y}} role="menu" data-testid="edge-context-menu">
                <button type="button" className="is-danger" onClick={() => onAction('delete-edge')}><Trash2 size={15} /><span>删除连线</span></button>
            </div>
        );
    }
    if (menu.kind === 'node') {
        return (
            <div className="wf-context-menu" style={{left: menu.x, top: menu.y}} role="menu" data-testid="node-context-menu">
                <button type="button" onClick={() => onAction('run-node')}><Play size={15} /><span>运行此步骤</span></button>
                <button type="button" className="is-danger" onClick={() => onAction('interrupt-node')}><Square size={15} /><span>中断此步骤</span></button>
                <button type="button" onClick={() => onAction('copy-node')}><Copy size={15} /><span>拷贝</span></button>
                <div className="wf-menu-separator" />
                <button type="button" className="is-danger" onClick={() => onAction('delete-node')}><Trash2 size={15} /><span>删除</span></button>
            </div>
        );
    }
    return (
        <div className="wf-context-menu" style={{left: menu.x, top: menu.y}} role="menu" data-testid="pane-context-menu">
            <div className={`wf-context-submenu-trigger ${submenuOpen ? 'is-open' : ''}`}>
                <button type="button" aria-expanded={submenuOpen} onClick={() => setSubmenuOpen((open) => !open)}><Plus size={15} /><span>添加节点</span><ChevronRight size={14} /></button>
                <div className="wf-context-submenu"><NodePicker onSelect={onAdd} includeSystem /></div>
            </div>
            <button type="button" onClick={() => onAction('test-run')}><Zap size={15} /><span>测试运行</span></button>
            <button type="button" className="is-danger" onClick={() => onAction('interrupt-workflow')}><Square size={15} /><span>中断测试</span></button>
            <button type="button" disabled={!canPaste} onClick={() => onAction('paste-node')}><Clipboard size={15} /><span>粘贴节点</span></button>
        </div>
    );
}

function ModelSelector({
    providers,
    loadState,
    loadError,
    providerId,
    modelName,
    onSelect,
    onRefresh,
}) {
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState('');
    const [collapsed, setCollapsed] = useState(() => new Set());
    const reference = modelReferenceStatus(providers, providerId, modelName);
    const normalizedQuery = query.trim().toLowerCase();
    const groups = providers.map((provider) => {
        const providerMatches = [provider.name, provider.base_url, provider.protocol]
            .filter(Boolean)
            .join(' ')
            .toLowerCase()
            .includes(normalizedQuery);
        const models = (provider.models || []).filter((model) => (
            !normalizedQuery || providerMatches || model.toLowerCase().includes(normalizedQuery)
        ));
        return {...provider, filteredModels: models};
    }).filter((provider) => provider.filteredModels.length);
    const toggleProvider = (id) => setCollapsed((current) => {
        const next = new Set(current);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
    });
    const selectionLabel = reference.state === 'valid'
        ? `${modelProviderName(reference.provider)} / ${modelName}`
        : reference.state === 'invalid'
            ? `${modelName || '未知模型'}（模型已失效）`
            : '选择模型';

    return (
        <div className={`wf-model-selector ${reference.state === 'invalid' ? 'is-invalid' : ''}`}>
            <button
                type="button"
                className="wf-model-select-trigger"
                aria-haspopup="listbox"
                aria-expanded={open}
                onClick={() => setOpen((current) => !current)}
            >
                <BrainCircuit size={15} />
                <span>{selectionLabel}</span>
                <ChevronRight className={open ? 'is-open' : ''} size={15} />
            </button>
            {reference.state === 'invalid' && <span className="wf-model-invalid" role="alert">模型已失效</span>}
            {open && (
                <div className="wf-model-picker" role="listbox" aria-label="选择已有模型">
                    <div className="wf-model-picker-search">
                        <Search size={14} />
                        <input autoFocus type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索供应商或模型" aria-label="搜索供应商或模型" />
                        <button type="button" onClick={onRefresh} title="刷新模型列表" aria-label="刷新模型列表"><RefreshCw size={14} /></button>
                    </div>
                    <div className="wf-model-picker-groups">
                        {loadState === 'loading' && <div className="wf-model-picker-empty"><LoaderCircle className="is-spinning" size={15} />正在加载</div>}
                        {loadState === 'error' && <div className="wf-model-picker-empty is-error">{loadError || '模型列表加载失败'}</div>}
                        {loadState === 'ready' && groups.map((provider) => {
                            const isCollapsed = collapsed.has(provider.id);
                            return (
                                <section className="wf-model-provider-group" key={provider.id}>
                                    <button type="button" className="wf-model-provider-heading" aria-expanded={!isCollapsed} onClick={() => toggleProvider(provider.id)}>
                                        <ChevronRight className={isCollapsed ? '' : 'is-open'} size={14} />
                                        <strong>{modelProviderName(provider)}</strong>
                                        <span><i />已连接</span>
                                    </button>
                                    {!isCollapsed && provider.filteredModels.map((model) => {
                                        const selected = provider.id === providerId && model === modelName;
                                        return (
                                            <button
                                                type="button"
                                                role="option"
                                                aria-selected={selected}
                                                className={`wf-model-option ${selected ? 'is-selected' : ''}`}
                                                key={model}
                                                onClick={() => {
                                                    onSelect(provider.id, model);
                                                    setOpen(false);
                                                    setQuery('');
                                                }}
                                            >
                                                <BrainCircuit size={14} />
                                                <span>{model}</span>
                                                {selected && <Check size={15} />}
                                            </button>
                                        );
                                    })}
                                </section>
                            );
                        })}
                        {loadState === 'ready' && !groups.length && <div className="wf-model-picker-empty">没有匹配的模型</div>}
                    </div>
                </div>
            )}
        </div>
    );
}

function NodeRunHistory({runs, nodeType}) {
    const [expandedRunId, setExpandedRunId] = useState(null);
    const [copiedRunId, setCopiedRunId] = useState(null);
    const copyResetTimerRef = useRef(null);
    useEffect(() => () => {
        if (copyResetTimerRef.current !== null) window.clearTimeout(copyResetTimerRef.current);
    }, []);
    const copyConsole = async (event, runId, text) => {
        event.stopPropagation();
        try {
            await copyTextToClipboard(text);
            setCopiedRunId(runId);
            if (copyResetTimerRef.current !== null) window.clearTimeout(copyResetTimerRef.current);
            copyResetTimerRef.current = window.setTimeout(() => setCopiedRunId(null), 1600);
            if (window.showToast) window.showToast('控制台已复制', 'success');
        } catch (error) {
            if (window.showToast) window.showToast(error instanceof Error ? error.message : '复制失败', 'error');
        }
    };
    if (!runs.length) return <div className="wf-node-log-empty">暂无运行日志</div>;
    return (
        <div className="wf-llm-run-list">
            {runs.slice(0, 10).map((run) => {
                const expanded = expandedRunId === run.id;
                const scriptConsole = typeof run.console === 'string' && run.console
                    ? run.console
                    : `${run.stdout || ''}${run.stderr || ''}`;
                const requestContent = run.request_body && Object.keys(run.request_body).length
                    ? parameterDataText(run.request_body, true)
                    : '';
                const tracebackContent = run.error?.traceback || '';
                return (
                    <article className={`wf-llm-run is-${String(run.status || 'FAILED').toLowerCase()}`} key={run.id}>
                        <button type="button" className={`wf-llm-run-summary ${nodeType === 'LLM' ? 'has-token-usage' : ''}`} aria-expanded={expanded} onClick={() => setExpandedRunId(expanded ? null : run.id)}>
                            <ChevronRight className={expanded ? 'is-open' : ''} size={15} />
                            <time>{formatRunDate(run.finished_at || run.started_at)}</time>
                            <strong>{run.status}</strong>
                            <span className="wf-llm-run-duration">{formatExecutionDuration(run.duration_ms)}</span>
                            {nodeType === 'LLM' && <span className="wf-llm-run-token">{formatRunTokenUsage(run)}</span>}
                            <span className="wf-llm-run-result">{runResultSummary(run)}</span>
                        </button>
                        {expanded && (
                            <div className="wf-llm-run-detail">
                                {nodeType === 'HTTP' ? (
                                    <>
                                        {requestContent && <HttpRequestLogSection request={run.request_body} />}
                                        {run.response_body && <HttpLogSection title="response" text={run.response_body} />}
                                    </>
                                ) : nodeType === 'SCRIPT' ? (
                                    <div className="wf-script-console-wrap">
                                        <button
                                            type="button"
                                            className="wf-script-console-copy"
                                            onClick={(event) => copyConsole(event, run.id, scriptConsole)}
                                            title={copiedRunId === run.id ? '已复制' : '复制控制台'}
                                            aria-label={`复制控制台 ${formatRunDate(run.finished_at || run.started_at)}`}
                                        >
                                            {copiedRunId === run.id ? <Check size={14} /> : <Copy size={14} />}
                                        </button>
                                        <textarea
                                            className="wf-script-console"
                                            aria-label="Script 原始控制台"
                                            readOnly
                                            value={scriptConsole}
                                            onPointerDown={(event) => event.stopPropagation()}
                                            onCopy={(event) => event.stopPropagation()}
                                        />
                                    </div>
                                ) : (
                                    <>
                                        <div className="wf-llm-run-meta">
                                            <span>{run.provider_name ? `${run.provider_name} / ${run.model_name || '未知模型'}` : nodeType}</span>
                                            {run.http_status && <span>HTTP {run.http_status}</span>}
                                            {run.request_id && <code>{run.request_id}</code>}
                                        </div>
                                        {requestContent && <HttpLogSection title="request" text={requestContent} />}
                                        {run.stdout && <section><strong>原始 stdout</strong><pre>{run.stdout}</pre></section>}
                                        {run.response_body && <HttpLogSection title="response" text={run.response_body} />}
                                        {run.stderr && <section className="is-error"><strong>原始 stderr</strong><pre>{run.stderr}</pre></section>}
                                        {tracebackContent && <section className="is-error"><strong>错误 traceback</strong><pre>{tracebackContent}</pre></section>}
                                    </>
                                )}
                            </div>
                        )}
                    </article>
                );
            })}
        </div>
    );
}

function Inspector({
    node,
    providers,
    providerLoadState,
    providerLoadError,
    onRefreshProviders,
    onLoadVariables,
    initialTab = 'settings',
    onChange,
    onRun,
    onInterrupt,
    onSave,
    onClose,
}) {
    const [tab, setTab] = useState(initialTab);
    const [retryOpen, setRetryOpen] = useState(false);
    const [mappingOpen, setMappingOpen] = useState(false);
    const [selectedParameterIndex, setSelectedParameterIndex] = useState(null);
    const [curlPanelOpen, setCurlPanelOpen] = useState(false);
    const [curlText, setCurlText] = useState('');
    const [curlError, setCurlError] = useState('');
    const [headersOpen, setHeadersOpen] = useState(true);
    const [paramsOpen, setParamsOpen] = useState(true);
    const [bodyMessage, setBodyMessage] = useState('');
    const [modelParametersText, setModelParametersText] = useState('');
    const [modelParametersError, setModelParametersError] = useState('');
    const [advancedOpen, setAdvancedOpen] = useState(false);
    const [variablesOpen, setVariablesOpen] = useState(false);
    const [variableGroups, setVariableGroups] = useState([]);
    const [variableLoadState, setVariableLoadState] = useState('idle');
    const [variableLoadError, setVariableLoadError] = useState('');
    const [editorScale, setEditorScale] = useState(1);
    const editorBaseSizeRef = useRef(null);
    useEffect(() => {
        setTab(initialTab);
        setCurlPanelOpen(false);
        setCurlText('');
        setCurlError('');
        setHeadersOpen(true);
        setParamsOpen(true);
        setBodyMessage('');
        setSelectedParameterIndex(null);
        setModelParametersText(modelParametersEditorText(node?.data.modelParameters));
        setModelParametersError('');
        setAdvancedOpen(false);
        setVariablesOpen(false);
        setVariableGroups([]);
        setVariableLoadState('idle');
        setVariableLoadError('');
        editorBaseSizeRef.current = null;
        setEditorScale(1);
    }, [node?.id, initialTab]);
    if (!node) return null;
    const meta = NODE_TYPES[node.data.nodeType] || NODE_TYPES.SCRIPT;
    const Icon = meta.icon;
    const isHttp = node.data.nodeType === 'HTTP';
    const isLlm = node.data.nodeType === 'LLM';
    const isScript = node.data.nodeType === 'SCRIPT';
    const showCodeEditor = meta.executable && !isHttp && !isLlm;
    const showParametersTab = !isHttp && !isLlm && !isScript;
    const streamEnabled = isLlm && node.data.modelParameters?.stream === true;
    const showOutputVariables = !isLlm || !streamEnabled;
    const modelReference = modelReferenceStatus(
        providers,
        node.data.providerId || '',
        node.data.modelName || '',
    );
    const llmConfigurationValid = !isLlm || (
        modelReference.state === 'valid'
        && !modelParametersError
        && Boolean(String(node.data.userPrompt || '').trim())
    );
    const httpConfig = {...defaultHttpConfig(), ...(node.data.httpConfig || {})};
    const width = Math.min(Math.round(760 * 1.4), window.innerWidth - 56);
    const height = Math.min(Math.round(640 * 1.4), window.innerHeight - 58 - 28);
    const legacyOutputVariable = node.data.outputVariable
        || (Array.isArray(node.data.variables) ? node.data.variables[0] : null)
        || emptyMappingRow();
    const outputVariables = Array.isArray(node.data.outputVariables) && node.data.outputVariables.length
        ? node.data.outputVariables
        : [legacyOutputVariable];
    const parameterRecords = Array.isArray(node.data.parameterRecords)
        ? node.data.parameterRecords
        : [];
    const selectedParameter = selectedParameterIndex === null
        ? null
        : parameterRecords[selectedParameterIndex] || null;
    const updateEditorScale = (_event, _direction, ref) => {
        if (!editorBaseSizeRef.current) {
            editorBaseSizeRef.current = {width: ref.offsetWidth, height: ref.offsetHeight};
        }
        const base = editorBaseSizeRef.current;
        const widthScale = ref.offsetWidth / base.width;
        const heightScale = ref.offsetHeight / base.height;
        const nextScale = Math.max(0.75, Math.min(1.35, Math.min(widthScale, heightScale)));
        setEditorScale(Number(nextScale.toFixed(3)));
    };
    const resizeHandleClasses = {
        top: 'wf-resize-handle wf-resize-top',
        right: 'wf-resize-handle wf-resize-right',
        bottom: 'wf-resize-handle wf-resize-bottom',
        left: 'wf-resize-handle wf-resize-left',
        topRight: 'wf-resize-handle wf-resize-ne',
        bottomRight: 'wf-resize-handle wf-resize-se',
        bottomLeft: 'wf-resize-handle wf-resize-sw',
        topLeft: 'wf-resize-handle wf-resize-nw',
    };
    const updateHttpConfig = (patch) => onChange({httpConfig: {...httpConfig, ...patch}});
    const updateHttpRow = (collection, id, patch) => {
        updateHttpConfig({
            [collection]: httpConfig[collection].map((row) => row.id === id ? {...row, ...patch} : row),
        });
    };
    const addHttpRow = (collection) => updateHttpConfig({
        [collection]: httpConfig[collection].concat(emptyKeyValueRow()),
    });
    const removeHttpRow = (collection, id) => updateHttpConfig({
        [collection]: httpConfig[collection].filter((row) => row.id !== id),
    });
    const updateModelParameters = (text) => {
        setModelParametersText(text);
        if (!text.trim()) {
            const emptyParameters = {};
            if (streamEnabled) emptyParameters.stream = true;
            setModelParametersError('');
            onChange({modelParameters: emptyParameters});
            return;
        }
        try {
            const parsed = JSON.parse(text);
            if (!isPlainObject(parsed)) throw new Error('高级参数必须是 JSON 对象');
            delete parsed.stream;
            if (streamEnabled) parsed.stream = true;
            setModelParametersError('');
            onChange({modelParameters: parsed});
        } catch (error) {
            setModelParametersError(error instanceof SyntaxError ? '高级参数不是合法 JSON' : error.message);
        }
    };
    const beautifyModelParameters = () => {
        if (!modelParametersText.trim()) {
            setModelParametersError('');
            return;
        }
        try {
            const parsed = JSON.parse(modelParametersText);
            if (!isPlainObject(parsed)) throw new Error('高级参数必须是 JSON 对象');
            delete parsed.stream;
            updateModelParameters(JSON.stringify(parsed, null, 2));
        } catch (error) {
            setModelParametersError(error instanceof SyntaxError ? '高级参数不是合法 JSON' : error.message);
        }
    };
    const setStreamMode = (enabled) => {
        const next = {...(node.data.modelParameters || {})};
        if (enabled) next.stream = true;
        else delete next.stream;
        setModelParametersText(modelParametersEditorText(next));
        setModelParametersError('');
        onChange({modelParameters: next});
    };
    const toggleVariables = async () => {
        if (variablesOpen) {
            setVariablesOpen(false);
            return;
        }
        setVariablesOpen(true);
        setVariableLoadState('loading');
        setVariableLoadError('');
        try {
            const groups = await onLoadVariables();
            setVariableGroups(Array.isArray(groups) ? groups : []);
            setVariableLoadState('ready');
        } catch (error) {
            setVariableGroups([]);
            setVariableLoadState('error');
            setVariableLoadError(error instanceof Error ? error.message : '变量加载失败');
        }
    };
    const updateOutputVariable = (id, patch) => onChange({
        outputVariables: outputVariables.map((row) => row.id === id ? {...row, ...patch} : row),
    });
    const addOutputVariable = () => onChange({
        outputVariables: outputVariables.concat(emptyMappingRow()),
    });
    const removeOutputVariable = (id) => {
        const remaining = outputVariables.filter((row) => row.id !== id);
        onChange({outputVariables: remaining.length ? remaining : [emptyMappingRow()]});
    };
    const httpKeyValueSection = (label, collection, open, setOpen) => (
        <section className="wf-http-kv-section">
            <div className="wf-http-kv-heading">
                <button type="button" className="wf-http-collapse-button" aria-expanded={open} onClick={() => setOpen((current) => !current)}>
                    <ChevronRight className={open ? 'is-open' : ''} size={14} /><strong>{label}</strong>
                </button>
                <span>key</span>
                <span>value</span>
                <button type="button" className="wf-inline-icon-button" onClick={() => {setOpen(true); addHttpRow(collection);}} title={`新增 ${label}`} aria-label={`新增 ${label}`}><Plus size={14} /></button>
            </div>
            {open && (
                <div className="wf-http-kv-rows">
                    {httpConfig[collection].map((row, index) => (
                        <div className="wf-http-kv-row" key={row.id}>
                            <span aria-hidden="true" />
                            <input aria-label={`${label} key ${index + 1}`} value={row.key} onChange={(event) => updateHttpRow(collection, row.id, {key: event.target.value})} />
                            <input aria-label={`${label} value ${index + 1}`} value={row.value} onChange={(event) => updateHttpRow(collection, row.id, {value: event.target.value})} />
                            <button type="button" className="wf-inline-icon-button is-danger" onClick={() => removeHttpRow(collection, row.id)} title={`删除 ${label}`} aria-label={`删除 ${label} ${index + 1}`}><Trash2 size={14} /></button>
                        </div>
                    ))}
                </div>
            )}
        </section>
    );
    const applyCurlImport = () => {
        try {
            const imported = parseCurlRequest(curlText);
            onChange({httpConfig: imported});
            setCurlError('');
            setCurlPanelOpen(false);
        } catch (error) {
            setCurlError(error instanceof Error ? error.message : 'cURL 导入失败');
        }
    };
    const beautifyJsonBody = () => {
        try {
            const formatted = JSON.stringify(JSON.parse(httpConfig.bodyText), null, 2);
            updateHttpConfig({bodyText: formatted});
            setBodyMessage('');
        } catch (error) {
            setBodyMessage(`JSON 格式错误：${error instanceof Error ? error.message : '无法解析'}`);
        }
    };
    const bodyFieldRows = () => (
        <div className="wf-http-body-fields">
            <div className="wf-http-kv-heading is-body">
                <span />
                <span>key</span>
                <span>value</span>
                <button type="button" className="wf-inline-icon-button" onClick={() => addHttpRow('bodyFields')} title="新增 Body 字段" aria-label="新增 Body 字段"><Plus size={14} /></button>
            </div>
            {httpConfig.bodyFields.map((row, index) => (
                <div className="wf-http-kv-row" key={row.id}>
                    <span aria-hidden="true" />
                    <input aria-label={`Body key ${index + 1}`} value={row.key} onChange={(event) => updateHttpRow('bodyFields', row.id, {key: event.target.value})} />
                    <input aria-label={`Body value ${index + 1}`} value={row.value} onChange={(event) => updateHttpRow('bodyFields', row.id, {value: event.target.value})} />
                    <button type="button" className="wf-inline-icon-button is-danger" onClick={() => removeHttpRow('bodyFields', row.id)} title="删除 Body 字段" aria-label={`删除 Body 字段 ${index + 1}`}><Trash2 size={14} /></button>
                </div>
            ))}
        </div>
    );
    const copyVariableValue = async (variable) => {
        if (!variable.available) return;
        try {
            await copyTextToClipboard(parameterDataText(variable.value, true));
            if (window.showToast) window.showToast(`已复制变量 ${variable.name}`, 'success');
        } catch (error) {
            if (window.showToast) window.showToast(error instanceof Error ? error.message : '复制失败', 'error');
        }
    };
    return (
        <Rnd
            className="wf-node-editor-rnd"
            default={{x: (window.innerWidth - width) / 2, y: (window.innerHeight - 58 - height) / 2, width, height}}
            minWidth={560}
            minHeight={420}
            maxWidth="calc(100% - 28px)"
            maxHeight="calc(100% - 28px)"
            bounds="parent"
            dragHandleClassName="wf-node-editor-drag-handle"
            cancel="button,input,textarea,.wf-inspector-tabs,.wf-inspector-body"
            resizeHandleClasses={resizeHandleClasses}
            onResize={updateEditorScale}
            onResizeStop={updateEditorScale}
        >
            <div
                className="wf-inspector-scale-shell"
                style={{
                    width: `${100 / editorScale}%`,
                    height: `${100 / editorScale}%`,
                    transform: `scale(${editorScale})`,
                }}
            >
              <aside className="wf-inspector" aria-label="节点配置">
                <header className="wf-node-editor-drag-handle">
                    <span className="wf-inspector-icon" style={{'--node-accent': meta.color}}><Icon size={18} /></span>
                    <div className="wf-inspector-title"><strong>{node.data.label}</strong><small>{meta.caption}</small></div>
                    <div className="wf-inspector-actions">
                        <button type="button" className={variablesOpen ? 'is-active' : ''} onClick={toggleVariables} title="变量" aria-label="查看节点变量"><Variable size={15} /></button>
                        <button type="button" disabled={!llmConfigurationValid || node.data.status === 'RUNNING'} onClick={onRun} title={llmConfigurationValid ? '运行' : '请选择有效模型、填写用户提示词并修正高级参数'} aria-label="运行当前节点"><Play size={15} /></button>
                        <button type="button" disabled={node.data.status !== 'RUNNING'} className="is-danger" onClick={onInterrupt} title="中断当前节点" aria-label="中断当前节点"><Square size={15} /></button>
                        <button type="button" disabled={!llmConfigurationValid} className={node.data.savedAt && !node.data.isDirty ? 'is-saved' : ''} onClick={onSave} title={llmConfigurationValid ? (node.data.savedAt && !node.data.isDirty ? `已保存 ${node.data.savedAt}` : '保存') : '请选择有效模型、填写用户提示词并修正高级参数'} aria-label="保存当前节点"><Save size={15} /></button>
                        <button type="button" onClick={onClose} title="关闭" aria-label="关闭"><X size={17} /></button>
                    </div>
                </header>
                {variablesOpen && (
                    <aside className="wf-node-variable-panel" aria-label="节点可用变量">
                        <header><strong>可用变量</strong><button type="button" onClick={() => setVariablesOpen(false)} title="关闭变量" aria-label="关闭变量"><X size={15} /></button></header>
                        {variableLoadState === 'loading' && <div className="wf-node-variable-empty"><LoaderCircle className="is-spinning" size={15} />正在加载</div>}
                        {variableLoadState === 'error' && <div className="wf-node-variable-empty is-error">{variableLoadError}</div>}
                        {variableLoadState === 'ready' && variableGroups.map((group) => (
                            <section key={group.id}>
                                <strong>{group.label}</strong>
                                <div className="wf-node-variable-heading"><span>变量名</span><span>变量值</span><span /></div>
                                {(group.variables || []).map((variable) => (
                                    <div className="wf-node-variable-row" key={`${group.id}-${variable.name}`}>
                                        <code>{variable.name}</code>
                                        <span className={!variable.available ? 'is-empty' : ''}>{variable.available ? parameterDataText(variable.value) : '尚无值'}</span>
                                        <button type="button" disabled={!variable.available} onClick={() => copyVariableValue(variable)} title={variable.available ? `复制 ${variable.name} 的值` : '尚无值'} aria-label={`复制变量值 ${variable.name}`}><Copy size={13} /></button>
                                    </div>
                                ))}
                                {!(group.variables || []).length && <div className="wf-node-variable-group-empty">无变量</div>}
                            </section>
                        ))}
                    </aside>
                )}
                <div className="wf-inspector-tabs">
                    <button type="button" className={tab === 'settings' ? 'is-active' : ''} onClick={() => setTab('settings')}>设置</button>
                    {showParametersTab && <button type="button" className={tab === 'parameters' ? 'is-active' : ''} onClick={() => setTab('parameters')}>参数</button>}
                    <button type="button" className={tab === 'logs' ? 'is-active' : ''} onClick={() => setTab('logs')}>日志</button>
                </div>
                {tab === 'settings' ? (
                    <div className="wf-inspector-body">
                        <div className="wf-editor-form-grid">
                            <label><span>名称</span><input value={node.data.label} onChange={(event) => onChange({label: event.target.value})} /></label>
                            <label><span>说明</span><input value={node.data.description || ''} onChange={(event) => onChange({description: event.target.value})} placeholder="添加节点说明" /></label>
                            {isLlm && (
                                <section className="wf-llm-model-section wf-editor-full-row">
                                    <div className="wf-llm-section-title"><BrainCircuit size={15} /><strong>模型配置</strong></div>
                                    <div className="wf-llm-model-row">
                                        <label className="wf-llm-model-field">
                                            <span>模型</span>
                                            <ModelSelector
                                                providers={providers}
                                                loadState={providerLoadState}
                                                loadError={providerLoadError}
                                                providerId={node.data.providerId || ''}
                                                modelName={node.data.modelName || ''}
                                                onRefresh={onRefreshProviders}
                                                onSelect={(providerId, modelName) => onChange({providerId, modelName})}
                                            />
                                        </label>
                                        <div className="wf-llm-stream-field">
                                            <span>流式输出</span>
                                            <label className="wf-llm-stream-switch">
                                                <input type="checkbox" role="switch" aria-label="流式输出" checked={streamEnabled} onChange={(event) => setStreamMode(event.target.checked)} />
                                                <i aria-hidden="true"><span /></i>
                                            </label>
                                        </div>
                                    </div>
                                    <label className="wf-llm-prompt-field">
                                        <span>系统提示词</span>
                                        <textarea aria-label="系统提示词" value={node.data.systemPrompt || ''} onChange={(event) => onChange({systemPrompt: event.target.value})} />
                                    </label>
                                    <label className="wf-llm-prompt-field is-user">
                                        <span>用户提示词</span>
                                        <textarea aria-label="用户提示词" value={node.data.userPrompt || ''} onChange={(event) => onChange({userPrompt: event.target.value})} />
                                    </label>
                                    <div className="wf-llm-advanced">
                                        <button type="button" aria-expanded={advancedOpen} onClick={() => setAdvancedOpen((open) => !open)}><span>高级参数</span><ChevronRight className={advancedOpen ? 'is-open' : ''} size={15} /></button>
                                        {(advancedOpen || modelParametersError) && (
                                            <div className="wf-llm-json-editor">
                                                <div className="wf-llm-json-toolbar">
                                                    <span>JSON</span>
                                                    <button type="button" onClick={beautifyModelParameters} title="格式化模型高级参数 JSON" aria-label="格式化模型高级参数 JSON"><WandSparkles size={13} />Beautify</button>
                                                </div>
                                                <textarea aria-label="模型高级参数 JSON" spellCheck="false" value={modelParametersText} placeholder={LLM_PARAMETERS_REFERENCE} onChange={(event) => updateModelParameters(event.target.value)} />
                                            </div>
                                        )}
                                        {modelParametersError && <span className="wf-model-parameters-error" role="alert">{modelParametersError}</span>}
                                    </div>
                                </section>
                            )}
                            {isHttp && (
                                <section className="wf-http-api-section wf-editor-full-row">
                                    <div className="wf-http-api-row">
                                        <strong>API</strong>
                                        <select aria-label="请求方式" value={httpConfig.method} onChange={(event) => updateHttpConfig({method: event.target.value})}>
                                            {!HTTP_METHODS.includes(httpConfig.method) && <option value={httpConfig.method}>{httpConfig.method}</option>}
                                            {HTTP_METHODS.map((method) => <option key={method} value={method}>{method}</option>)}
                                        </select>
                                        <input aria-label="请求 URL" value={httpConfig.url} onChange={(event) => updateHttpConfig({url: event.target.value})} placeholder="https://" />
                                        <button type="button" className="wf-http-import-button" title="导入 cURL" aria-label="导入 cURL" aria-expanded={curlPanelOpen} onClick={() => {setCurlPanelOpen((open) => !open); setCurlError('');}}><Upload size={15} /></button>
                                    </div>
                                    {curlPanelOpen && (
                                        <div className="wf-curl-import-panel">
                                            <textarea aria-label="cURL 命令" value={curlText} onChange={(event) => {setCurlText(event.target.value); setCurlError('');}} spellCheck="false" placeholder="curl https://api.example.com" />
                                            <div className="wf-curl-import-actions">
                                                {curlError && <span role="alert">{curlError}</span>}
                                                <button type="button" onClick={() => setCurlPanelOpen(false)}>取消</button>
                                                <button type="button" className="is-primary" onClick={applyCurlImport}>应用</button>
                                            </div>
                                        </div>
                                    )}
                                    {httpKeyValueSection('HEADERS', 'headers', headersOpen, setHeadersOpen)}
                                    {httpKeyValueSection('PARAMS', 'params', paramsOpen, setParamsOpen)}
                                    <section className="wf-http-body-section">
                                        <div className="wf-http-body-heading">
                                            <strong>BODY</strong>
                                            <div className="wf-http-body-types" role="radiogroup" aria-label="Body 类型">
                                                {HTTP_BODY_TYPES.map((type) => (
                                                    <label key={type}>
                                                        <input type="radio" name={`http-body-${node.id}`} value={type} checked={httpConfig.bodyType === type} onChange={() => {updateHttpConfig({bodyType: type}); setBodyMessage('');}} />
                                                        <i />
                                                        <span>{type}</span>
                                                    </label>
                                                ))}
                                            </div>
                                        </div>
                                        {(httpConfig.bodyType === 'form-data' || httpConfig.bodyType === 'x-www-form-urlencoded') && bodyFieldRows()}
                                        {httpConfig.bodyType === 'raw' && (
                                            <div className="wf-http-code-editor">
                                                <div className="wf-http-code-toolbar">
                                                    <span>JSON</span>
                                                    <button type="button" onClick={beautifyJsonBody} title="格式化 JSON"><WandSparkles size={13} />Beautify</button>
                                                </div>
                                                <textarea aria-label="Raw Body" value={httpConfig.bodyText} onChange={(event) => {updateHttpConfig({bodyText: event.target.value}); setBodyMessage('');}} spellCheck="false" />
                                                {bodyMessage && <span className="wf-http-body-error" role="alert">{bodyMessage}</span>}
                                            </div>
                                        )}
                                    </section>
                                    <section className="wf-http-network-section">
                                        <div className="wf-http-kv-heading"><strong>NETWORK</strong></div>
                                        <div className="wf-http-network-grid">
                                            <label><span>Proxy</span><select aria-label="Proxy 模式" value={httpConfig.proxyMode} onChange={(event) => updateHttpConfig({proxyMode: event.target.value})}><option value="SYSTEM">System</option><option value="DIRECT">Direct</option><option value="CUSTOM">Custom</option></select></label>
                                            {httpConfig.proxyMode === 'CUSTOM' && <>
                                                <label><span>Proxy URL</span><input aria-label="Proxy URL" value={httpConfig.proxyUrl} onChange={(event) => updateHttpConfig({proxyUrl: event.target.value})} placeholder="http://proxy.example.com:8080" /></label>
                                                <label><span>用户名</span><input aria-label="Proxy 用户名" value={httpConfig.proxyUsername} onChange={(event) => updateHttpConfig({proxyUsername: event.target.value})} /></label>
                                                <label><span>密码</span><input aria-label="Proxy 密码" type="password" value={httpConfig.proxyPassword} onChange={(event) => updateHttpConfig({proxyPassword: event.target.value})} /></label>
                                            </>}
                                            <label><span>响应格式</span><select aria-label="响应 Body 类型" value={httpConfig.responseBodyType} onChange={(event) => updateHttpConfig({responseBodyType: event.target.value})}><option value="json">JSON</option><option value="text">Text</option><option value="binary">Binary</option></select></label>
                                            <label className="wf-http-checkbox"><input type="checkbox" checked={httpConfig.followRedirects} onChange={(event) => updateHttpConfig({followRedirects: event.target.checked})} /><span>跟随重定向</span></label>
                                            <label className="wf-http-checkbox"><input type="checkbox" checked={httpConfig.verifySsl} onChange={(event) => updateHttpConfig({verifySsl: event.target.checked})} /><span>验证 SSL 证书</span></label>
                                        </div>
                                    </section>
                                </section>
                            )}
                            {showCodeEditor && (
                                <section className="wf-embedded-code-editor wf-editor-full-row">
                                    <div className="wf-code-meta"><span>main.py</span><span>Python</span></div>
                                    <PythonCodeEditor
                                        value={node.data.mainPy ?? (isScript ? DEFAULT_SCRIPT_MAIN_PY : DEFAULT_AGENT_MAIN_PY)}
                                        onChange={(mainPy) => onChange({mainPy})}
                                    />
                                </section>
                            )}
                            <section className="wf-config-section wf-editor-full-row">
                                <div className="wf-config-title"><Settings2 size={15} /><strong>运行配置</strong></div>
                                <button type="button" aria-expanded={retryOpen} onClick={() => setRetryOpen((open) => !open)}><span>超时与重试</span><ChevronRight className={retryOpen ? 'is-open' : ''} size={15} /></button>
                                {retryOpen && (
                                    <div className="wf-config-panel wf-retry-grid">
                                        <label><span>单次超时（ms）</span><input type="number" min="1" step="1" value={node.data.timeoutMs ?? 120000} onChange={(event) => onChange({timeoutMs: Number(event.target.value)})} /></label>
                                        <label><span>最大重试次数</span><input type="number" min="0" max="10" step="1" value={node.data.retryCount ?? 0} onChange={(event) => onChange({retryCount: Number(event.target.value)})} /></label>
                                        <label><span>重试间隔（ms）</span><input type="number" min="0" max="600000" step="1" value={node.data.retryIntervalMs ?? 0} onChange={(event) => onChange({retryIntervalMs: Number(event.target.value)})} /></label>
                                    </div>
                                )}
                                {showOutputVariables && (
                                    <>
                                        <button type="button" aria-expanded={mappingOpen} onClick={() => setMappingOpen((open) => !open)}><span>输出变量</span><ChevronRight className={mappingOpen ? 'is-open' : ''} size={15} /></button>
                                        {mappingOpen && (
                                            <div className="wf-config-panel wf-output-variable-list">
                                                {outputVariables.map((row, index) => (
                                                    <div className="wf-output-variable-row" key={row.id}>
                                                        <label><span>变量名</span><input aria-label={`输出变量名 ${index + 1}`} value={row.name} onChange={(event) => updateOutputVariable(row.id, {name: event.target.value})} /></label>
                                                        {isHttp && (
                                                            <label><span>提取表达式</span><input aria-label={`输出变量 ${index + 1}`} value={row.value || ''} onChange={(event) => updateOutputVariable(row.id, {value: event.target.value})} /></label>
                                                        )}
                                                        <label><span>类型</span><select aria-label={`输出变量类型 ${index + 1}`} value={row.type || 'AUTO'} onChange={(event) => updateOutputVariable(row.id, {type: event.target.value})}>{OUTPUT_VARIABLE_TYPES.map((type) => <option value={type} key={type}>{type}</option>)}</select></label>
                                                        {index === 0 ? (
                                                            <button type="button" className="wf-inline-icon-button" onClick={addOutputVariable} title="添加输出变量" aria-label="添加输出变量"><Plus size={15} /></button>
                                                        ) : (
                                                            <button type="button" className="wf-inline-icon-button is-danger" onClick={() => removeOutputVariable(row.id)} title="删除输出变量" aria-label={`删除输出变量 ${index + 1}`}><Trash2 size={15} /></button>
                                                        )}
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </>
                                )}
                            </section>
                        </div>
                    </div>
                ) : tab === 'parameters' && showParametersTab ? (
                    <div className="wf-inspector-body wf-parameter-panel">
                        <div className="wf-parameter-table" role="table" aria-label="节点运行参数">
                            <div className="wf-parameter-row wf-parameter-heading" role="row">
                                <span role="columnheader">source</span>
                                <span role="columnheader">name</span>
                                <span role="columnheader">data</span>
                            </div>
                            {parameterRecords.map((record, index) => (
                                <div className="wf-parameter-row" role="row" key={record.id || `${record.source}:${record.name}:${index}`}>
                                    <code role="cell">{record.source || '—'}</code>
                                    <span role="cell">{record.name || '—'}</span>
                                    <div className="wf-parameter-data-cell" role="cell">
                                        <code title={parameterDataSummary(record.data)}>{parameterDataSummary(record.data) || '—'}</code>
                                        <button type="button" onClick={() => setSelectedParameterIndex(index)} title="查看完整数据" aria-label={`查看 ${record.source || '未知来源'} ${record.name || '未命名参数'} 完整数据`}><Eye size={14} /></button>
                                    </div>
                                </div>
                            ))}
                            {!parameterRecords.length && <div className="wf-parameter-empty">当前节点尚无运行参数</div>}
                        </div>
                        {selectedParameter && (
                            <section className="wf-parameter-detail" aria-label="参数完整数据">
                                <header>
                                    <div><strong>{selectedParameter.source || '未知来源'}</strong><span>{selectedParameter.name || '未命名参数'}</span></div>
                                    <div>
                                        {selectedParameter.artifact?.href && (
                                            <a href={selectedParameter.artifact.href} target="_blank" rel="noreferrer" title="打开完整 Artifact"><ExternalLink size={14} />Artifact</a>
                                        )}
                                        <button type="button" onClick={() => setSelectedParameterIndex(null)} title="关闭详情" aria-label="关闭参数详情"><X size={15} /></button>
                                    </div>
                                </header>
                                <pre>{parameterDataText(selectedParameter.data, true)}</pre>
                            </section>
                        )}
                    </div>
                ) : (
                    <div className="wf-inspector-body wf-node-log-panel">
                        <NodeRunHistory runs={node.data.runHistory || []} nodeType={node.data.nodeType} />
                    </div>
                )}
              </aside>
            </div>
        </Rnd>
    );
}

function WorkflowStudio({options}) {
    const graph = useMemo(() => graphFromDraft(options.draft), [options.draft]);
    const [nodes, setNodes, onNodesChange] = useNodesState(graph.nodes);
    const [edges, setEdges, onEdgesChange] = useEdgesState(graph.edges);
    const [selectedNodeIds, setSelectedNodeIds] = useState([]);
    const [selectedEdgeIds, setSelectedEdgeIds] = useState([]);
    const [editorNodeId, setEditorNodeId] = useState(null);
    const [contextMenu, setContextMenu] = useState(null);
    const [insertEdgeId, setInsertEdgeId] = useState(null);
    const [clipboard, setClipboard] = useState(null);
    const [headerPanel, setHeaderPanel] = useState(null);
    const [marquee, setMarquee] = useState(null);
    const [globalVariables, setGlobalVariables] = useState(() => options.draft?.global_variables?.length
        ? cloneValue(options.draft.global_variables)
        : [emptyMappingRow()]);
    const [nodeSaveNotice, setNodeSaveNotice] = useState(null);
    const [workflowName, setWorkflowName] = useState(options.name || '未命名工作流');
    const [workflowDescription, setWorkflowDescription] = useState(
        options.description ?? options.draft?.description ?? '',
    );
    const [nameEditing, setNameEditing] = useState(false);
    const [descriptionEditing, setDescriptionEditing] = useState(false);
    const [workflowId, setWorkflowId] = useState(options.id || null);
    const [saveState, setSaveState] = useState(options.id ? '已保存' : '未保存');
    const [modelProviders, setModelProviders] = useState([]);
    const [providerLoadState, setProviderLoadState] = useState('loading');
    const [providerLoadError, setProviderLoadError] = useState('');
    const timers = useRef([]);
    const workflowIdRef = useRef(options.id || null);
    const creationAttempted = useRef(false);
    const creationPromise = useRef(null);
    const nameEditCancelled = useRef(false);
    const descriptionEditCancelled = useRef(false);
    const savedMetadata = useRef({
        name: (options.name || '未命名工作流').trim(),
        description: String(options.description ?? options.draft?.description ?? '').trim(),
    });
    const pasteSequence = useRef(0);
    const marqueeRef = useRef(null);
    const initialLayoutDone = useRef(false);
    const undoStack = useRef([]);
    const redoStack = useRef([]);
    const providerLoadSequence = useRef(0);
    const [historyTick, setHistoryTick] = useState(0);
    const [workflowRunState, setWorkflowRunState] = useState('IDLE');
    const [workflowElapsedMs, setWorkflowElapsedMs] = useState(0);
    const workflowRunRef = useRef({active: false, interruptRequested: false, startedAtMs: 0, runId: null});
    const workflowElapsedTimer = useRef(null);
    const {screenToFlowPosition, fitView} = useReactFlow();

    const loadModelProviders = useCallback(async () => {
        const sequence = providerLoadSequence.current + 1;
        providerLoadSequence.current = sequence;
        setProviderLoadState('loading');
        setProviderLoadError('');
        try {
            const response = await fetch('/api/model-providers', {
                headers: {accept: 'application/json'},
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
            if (providerLoadSequence.current !== sequence) return;
            setModelProviders(Array.isArray(payload.providers) ? payload.providers : []);
            setProviderLoadState('ready');
        } catch (error) {
            if (providerLoadSequence.current !== sequence) return;
            setModelProviders([]);
            setProviderLoadState('error');
            setProviderLoadError(error instanceof Error ? error.message : '模型列表加载失败');
        }
    }, []);

    useEffect(() => {
        loadModelProviders();
    }, [loadModelProviders]);

    const persistDraft = useCallback(async ({forNodeRun = false, metadata = null} = {}) => {
        if (!options.onPersist) throw new Error('Workflow 持久化入口不可用');
        const pendingCreation = creationPromise.current;
        if (pendingCreation) await pendingCreation;
        const name = String(metadata?.name ?? workflowName).trim();
        const description = String(metadata?.description ?? workflowDescription).trim();
        if (!name) throw new Error('Workflow 名称不能为空');
        if (!forNodeRun) {
            const graphError = validateWorkflowGraph(nodes, edges);
            if (graphError) {
                setSaveState('保存失败');
                throw new Error(graphError);
            }
        }
        if (!forNodeRun) setSaveState('正在保存');
        try {
            const saved = await options.onPersist({
                id: workflowIdRef.current,
                name,
                description,
                nodes: nodes.map(serializableNode),
                edges: edges.map(serializableEdge),
                global_variables: cloneValue(globalVariables),
                forNodeRun,
            });
            workflowIdRef.current = saved.id;
            setWorkflowId(saved.id);
            savedMetadata.current = {
                name: saved.name ?? name,
                description: saved.description ?? description,
            };
            if (!forNodeRun) {
                setSaveState('已保存');
                setNodes((current) => current.map((node) => ({
                    ...node,
                    data: {...node.data, isDirty: false},
                })));
            }
            return saved.id;
        } catch (error) {
            if (!forNodeRun) setSaveState('保存失败');
            throw error;
        }
    }, [edges, globalVariables, nodes, options, setNodes, workflowDescription, workflowName]);

    const persistMetadata = useCallback(async (nextName, nextDescription) => {
        const name = String(nextName).trim();
        const description = String(nextDescription).trim();
        if (!name) {
            if (window.showToast) window.showToast('Workflow 名称不能为空', 'error');
            return false;
        }
        setSaveState('正在保存');
        try {
            if (creationPromise.current) await creationPromise.current;
            if (!workflowIdRef.current) {
                await persistDraft({forNodeRun: true, metadata: {name, description}});
            } else {
                if (!options.onPersistMetadata) throw new Error('Workflow 元数据持久化入口不可用');
                const saved = await options.onPersistMetadata({
                    id: workflowIdRef.current,
                    name,
                    description,
                });
                workflowIdRef.current = saved.id;
                setWorkflowId(saved.id);
                savedMetadata.current = {
                    name: saved.name ?? name,
                    description: saved.description ?? description,
                };
            }
            setWorkflowName(savedMetadata.current.name);
            setWorkflowDescription(savedMetadata.current.description);
            setSaveState('已保存');
            return true;
        } catch (error) {
            setSaveState('保存失败');
            if (window.showToast) {
                window.showToast(error instanceof Error ? error.message : 'Workflow 元数据保存失败', 'error');
            }
            return false;
        }
    }, [options, persistDraft]);

    const commitWorkflowName = useCallback(async () => {
        if (nameEditCancelled.current) {
            nameEditCancelled.current = false;
            setWorkflowName(savedMetadata.current.name);
            setNameEditing(false);
            return;
        }
        if (!workflowName.trim()) {
            setWorkflowName(savedMetadata.current.name);
            setNameEditing(false);
            if (window.showToast) window.showToast('Workflow 名称不能为空', 'error');
            return;
        }
        if (await persistMetadata(workflowName, workflowDescription)) setNameEditing(false);
    }, [persistMetadata, workflowDescription, workflowName]);

    const commitWorkflowDescription = useCallback(async () => {
        if (descriptionEditCancelled.current) {
            descriptionEditCancelled.current = false;
            setWorkflowDescription(savedMetadata.current.description);
            setDescriptionEditing(false);
            return;
        }
        if (await persistMetadata(workflowName, workflowDescription)) setDescriptionEditing(false);
    }, [persistMetadata, workflowDescription, workflowName]);

    useEffect(() => {
        if (!options.createOnMount || workflowIdRef.current || creationAttempted.current) return;
        creationAttempted.current = true;
        setSaveState('正在创建');
        const pending = persistDraft({forNodeRun: true});
        creationPromise.current = pending;
        pending
            .then(() => setSaveState('已保存'))
            .catch((error) => {
                setSaveState('创建失败');
                if (window.showToast) {
                    window.showToast(error instanceof Error ? error.message : 'Workflow 创建失败', 'error');
                }
            })
            .finally(() => {
                if (creationPromise.current === pending) creationPromise.current = null;
            });
    }, [options.createOnMount, persistDraft]);

    const closeMenus = useCallback(() => {
        setContextMenu(null);
        setInsertEdgeId(null);
    }, []);

    const recordHistory = useCallback(() => {
        undoStack.current.push({nodes: cloneValue(nodes), edges: cloneValue(edges)});
        if (undoStack.current.length > 50) undoStack.current.shift();
        redoStack.current = [];
        setHistoryTick((value) => value + 1);
    }, [edges, nodes]);

    const undo = useCallback(() => {
        const previous = undoStack.current.pop();
        if (!previous) return;
        redoStack.current.push({nodes: cloneValue(nodes), edges: cloneValue(edges)});
        setNodes(previous.nodes);
        setEdges(previous.edges);
        setEditorNodeId((current) => previous.nodes.some((node) => node.id === current) ? current : null);
        closeMenus();
        setHistoryTick((value) => value + 1);
    }, [closeMenus, edges, nodes, setEdges, setNodes]);

    const redo = useCallback(() => {
        const next = redoStack.current.pop();
        if (!next) return;
        undoStack.current.push({nodes: cloneValue(nodes), edges: cloneValue(edges)});
        setNodes(next.nodes);
        setEdges(next.edges);
        setEditorNodeId((current) => next.nodes.some((node) => node.id === current) ? current : null);
        closeMenus();
        setHistoryTick((value) => value + 1);
    }, [closeMenus, edges, nodes, setEdges, setNodes]);

    const addNodeAt = useCallback((type, position) => {
        recordHistory();
        const next = {...makeNode(type, position), selected: true};
        setNodes((current) => current.map((node) => ({...node, selected: false})).concat(next));
        closeMenus();
        return next;
    }, [closeMenus, recordHistory, setNodes]);

    const loadNodeRuns = useCallback(async (id, activeWorkflowId = workflowId) => {
        if (!activeWorkflowId) return [];
        try {
            const runResponse = await fetch(`/api/workflows/${encodeURIComponent(activeWorkflowId)}/runs`, {
                headers: {accept: 'application/json'},
            });
            const runPayload = await runResponse.json().catch(() => ({}));
            if (!runResponse.ok) throw new Error(runPayload.detail || `HTTP ${runResponse.status}`);
            const latest = Array.isArray(runPayload.runs) ? runPayload.runs[0] : null;
            if (!latest) return [];
            const response = await fetch(`/api/workflows/${encodeURIComponent(activeWorkflowId)}/runs/${encodeURIComponent(latest.run_id)}/nodes`, {headers: {accept: 'application/json'}});
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
            const runs = (payload.runs || []).filter((run) => run.node_id === id).map((run) => ({...run, id: run.node_run_id, output: run.outputs, response_body: typeof run.response === 'string' ? run.response : JSON.stringify(run.response || '')}));
            setNodes((current) => current.map((node) => node.id === id ? {
                ...node,
                data: {
                    ...node.data,
                    runHistory: runs,
                    status: runs[0]?.status || 'PENDING',
                    executionDurationMs: runs[0]?.duration_ms || 0,
                },
            } : node));
            return runs;
        } catch (error) {
            if (window.showToast) window.showToast(error instanceof Error ? error.message : '节点日志加载失败', 'error');
            return [];
        }
    }, [setNodes, workflowId]);

    const loadNodeVariables = useCallback(async (id) => {
        const targetIndex = nodes.findIndex((node) => node.id === id);
        const visible = targetIndex < 0 ? [] : nodes.slice(0, targetIndex + 1);
        const groups = [];
        if (globalVariables.length) groups.push({id: 'start-inputs', label: 'START', variables: globalVariables.filter((row) => row.name).map((row) => ({name: row.name, value: row.value, available: true}))});
        visible.forEach((node) => {
            const variables = (node.data.outputVariables || []).filter((row) => row.name).map((row) => ({name: row.name, value: null, path: row.value || null, available: false}));
            if (variables.length) groups.push({id: node.id, label: node.data.label || node.data.nodeType, variables});
        });
        return groups;
    }, [globalVariables, nodes]);

    useEffect(() => {
        const targetNode = nodes.find((node) => node.id === editorNodeId);
        if (['HTTP', 'AGENT', 'LLM', 'SCRIPT'].includes(targetNode?.data.nodeType) && workflowId) {
            loadNodeRuns(targetNode.id);
        }
    }, [editorNodeId, loadNodeRuns, workflowId]);

    const saveNode = useCallback(async (id) => {
        const savedAt = new Date().toLocaleTimeString('zh-CN', {hour12: false});
        const node = nodes.find((item) => item.id === id);
        if (!node) return;
        try {
            await persistDraft();
        } catch (error) {
            if (window.showToast) window.showToast(error instanceof Error ? error.message : '节点保存失败', 'error');
            return;
        }
        const noticeId = rowId();
        setNodes((current) => current.map((item) => item.id === id ? {
            ...item,
            data: {...item.data, savedAt, isDirty: false},
        } : item));
        setNodeSaveNotice({id: noticeId, label: node.data.label, savedAt});
        const timer = window.setTimeout(() => {
            setNodeSaveNotice((current) => current?.id === noticeId ? null : current);
        }, 2400);
        timers.current.push(timer);
    }, [nodes, persistDraft, setNodes]);

    const applyWorkflowNodeRuns = useCallback((runs) => {
        const byNode = new Map((runs || []).map((run) => [run.node_id, run]));
        setNodes((current) => current.map((node) => {
            const run = byNode.get(node.id);
            if (!run) return node;
            const historyRun = {...run, id: run.node_run_id, output: run.outputs, response_body: typeof run.response === 'string' ? run.response : JSON.stringify(run.response || '')};
            return {...node, data: {...node.data, status: run.status, executionDurationMs: run.duration_ms || 0, executionId: run.status === 'RUNNING' ? run.node_run_id : null, runHistory: [historyRun].concat((node.data.runHistory || []).filter((item) => item.id !== run.node_run_id)).slice(0, 10)}};
        }));
    }, [setNodes]);

    const interruptWorkflow = useCallback(async () => {
        const state = workflowRunRef.current;
        if (!state.active || !state.runId || !workflowIdRef.current) return false;
        state.interruptRequested = true;
        try {
            const response = await fetch(`/api/workflows/${encodeURIComponent(workflowIdRef.current)}/runs/${encodeURIComponent(state.runId)}/cancel`, {method: 'POST', headers: {accept: 'application/json'}});
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
            return true;
        } catch (error) {
            if (window.showToast) window.showToast(error instanceof Error ? error.message : 'Workflow 中断失败', 'error');
            return false;
        }
    }, []);

    const runAll = useCallback(async () => {
        if (workflowRunRef.current.active) return;
        const graphError = validateWorkflowGraph(nodes, edges);
        if (graphError) {
            if (window.showToast) window.showToast(graphError, 'error');
            return;
        }
        closeMenus();
        let activeWorkflowId;
        const workflowState = workflowRunRef.current;
        workflowState.active = true;
        workflowState.interruptRequested = false;
        workflowState.startedAtMs = Date.now();
        workflowState.runId = null;
        setWorkflowRunState('RUNNING');
        setWorkflowElapsedMs(0);
        if (workflowElapsedTimer.current !== null) window.clearInterval(workflowElapsedTimer.current);
        workflowElapsedTimer.current = window.setInterval(() => {
            setWorkflowElapsedMs(Date.now() - workflowState.startedAtMs);
        }, 100);
        setNodes((current) => current.map((node) => ({
            ...node,
            data: {...node.data, status: 'PENDING', executionId: null, executionDurationMs: 0},
        })));
        try {
            activeWorkflowId = await persistDraft();
            const startedResponse = await fetch(`/api/workflows/${encodeURIComponent(activeWorkflowId)}/runs`, {method: 'POST', headers: {accept: 'application/json'}});
            const startedPayload = await startedResponse.json().catch(() => ({}));
            if (!startedResponse.ok) throw new Error(startedPayload.detail || `HTTP ${startedResponse.status}`);
            workflowState.runId = startedPayload.run.run_id;
            let run = startedPayload.run;
            while (!['SUCCESS', 'FAILED', 'CANCELLED'].includes(run.status)) {
                await new Promise((resolve) => window.setTimeout(resolve, 250));
                const [runResponse, nodesResponse] = await Promise.all([
                    fetch(`/api/workflows/${encodeURIComponent(activeWorkflowId)}/runs/${encodeURIComponent(workflowState.runId)}`, {headers: {accept: 'application/json'}}),
                    fetch(`/api/workflows/${encodeURIComponent(activeWorkflowId)}/runs/${encodeURIComponent(workflowState.runId)}/nodes`, {headers: {accept: 'application/json'}}),
                ]);
                const runPayload = await runResponse.json().catch(() => ({}));
                const nodesPayload = await nodesResponse.json().catch(() => ({}));
                if (!runResponse.ok) throw new Error(runPayload.detail || `HTTP ${runResponse.status}`);
                run = runPayload.run;
                if (nodesResponse.ok) applyWorkflowNodeRuns(nodesPayload.runs || []);
            }
            setWorkflowRunState(run.status);
            setWorkflowElapsedMs(Date.now() - workflowState.startedAtMs);
            if (window.showToast) window.showToast(run.status === 'SUCCESS' ? 'Workflow 执行完成' : run.status === 'CANCELLED' ? 'Workflow 已中断' : run.error?.message || 'Workflow 执行失败', run.status === 'SUCCESS' ? 'success' : 'error');
        } catch (error) {
            setWorkflowRunState('FAILED');
            if (window.showToast) window.showToast(error instanceof Error ? error.message : 'Workflow 执行失败', 'error');
        } finally {
            workflowState.active = false;
            workflowState.runId = null;
            if (workflowElapsedTimer.current !== null) {
                window.clearInterval(workflowElapsedTimer.current);
                workflowElapsedTimer.current = null;
            }
            setWorkflowElapsedMs(Date.now() - workflowState.startedAtMs);
        }
    }, [applyWorkflowNodeRuns, closeMenus, edges, nodes, persistDraft, setNodes]);

    const deleteElements = useCallback((nodeIds = [], edgeIds = []) => {
        const nodeIdSet = new Set(nodeIds);
        const edgeIdSet = new Set(edgeIds);
        if (!nodeIdSet.size && !edgeIdSet.size) return;
        recordHistory();
        setNodes((current) => current.filter((node) => !nodeIdSet.has(node.id)));
        setEdges((current) => current.filter((edge) => (
            !edgeIdSet.has(edge.id) && !nodeIdSet.has(edge.source) && !nodeIdSet.has(edge.target)
        )));
        setEditorNodeId((current) => nodeIdSet.has(current) ? null : current);
        setSelectedNodeIds((current) => current.filter((id) => !nodeIdSet.has(id)));
        setSelectedEdgeIds((current) => current.filter((id) => !edgeIdSet.has(id)));
        closeMenus();
    }, [closeMenus, recordHistory, setEdges, setNodes]);

    const deleteNodes = useCallback((ids) => deleteElements(ids, []), [deleteElements]);
    const deleteEdges = useCallback((ids) => deleteElements([], ids), [deleteElements]);

    const deleteNode = useCallback((id) => deleteNodes([id]), [deleteNodes]);

    const copyNodes = useCallback((ids) => {
        const idSet = new Set(ids);
        const copiedNodes = nodes.filter((node) => idSet.has(node.id)).map((node) => ({
            ...node,
            position: {...node.position},
            data: cloneValue(node.data),
            selected: false,
        }));
        if (!copiedNodes.length) return;
        const copiedEdges = edges.filter((edge) => idSet.has(edge.source) && idSet.has(edge.target)).map((edge) => cloneValue(edge));
        setClipboard({nodes: copiedNodes, edges: copiedEdges});
        pasteSequence.current = 0;
        closeMenus();
    }, [closeMenus, edges, nodes]);

    const copyNode = useCallback((id) => copyNodes([id]), [copyNodes]);

    const pasteClipboard = useCallback((origin = null) => {
        if (!clipboard?.nodes?.length) return;
        recordHistory();
        pasteSequence.current += 1;
        const minX = Math.min(...clipboard.nodes.map((node) => node.position.x));
        const minY = Math.min(...clipboard.nodes.map((node) => node.position.y));
        const offsetX = origin ? origin.x - minX : pasteSequence.current * 42;
        const offsetY = origin ? origin.y - minY : pasteSequence.current * 42;
        const idMap = new Map();
        const pastedNodes = clipboard.nodes.map((source) => {
            const newId = nodeId(source.data.nodeType);
            idMap.set(source.id, newId);
            const {measured, dragging, ...rest} = source;
            return {
                ...rest,
                id: newId,
                position: {x: source.position.x + offsetX, y: source.position.y + offsetY},
                data: cloneValue(source.data),
                selected: true,
            };
        });
        const pastedEdges = clipboard.edges.map((source) => {
            const {id, source: oldSource, target: oldTarget, ...edgeOptions} = cloneValue(source);
            return makeEdge(idMap.get(oldSource), idMap.get(oldTarget), edgeOptions);
        });
        setNodes((current) => current.map((node) => ({...node, selected: false})).concat(pastedNodes));
        setEdges((current) => current.concat(pastedEdges));
        setSelectedNodeIds(pastedNodes.map((node) => node.id));
        closeMenus();
    }, [clipboard, closeMenus, recordHistory, setEdges, setNodes]);

    const pasteNode = useCallback(() => {
        if (contextMenu?.flowPosition) pasteClipboard(contextMenu.flowPosition);
    }, [contextMenu, pasteClipboard]);

    const insertNode = useCallback((edgeId, type) => {
        const edge = edges.find((item) => item.id === edgeId);
        if (!edge) return;
        const source = nodes.find((node) => node.id === edge.source);
        const target = nodes.find((node) => node.id === edge.target);
        if (!source || !target) return;
        recordHistory();
        const next = makeNode(type, {
            x: (source.position.x + target.position.x) / 2,
            y: (source.position.y + target.position.y) / 2 + 130,
        });
        next.selected = true;
        setNodes((current) => current.map((node) => ({...node, selected: false})).concat(next));
        setEdges((current) => current.filter((item) => item.id !== edgeId).concat(
            makeEdge(source.id, next.id),
            makeEdge(next.id, target.id),
        ));
        setInsertEdgeId(null);
    }, [edges, nodes, recordHistory, setEdges, setNodes]);

    const decoratedEdges = useMemo(() => edges.map((edge) => ({
        ...edge,
        data: {
            ...edge.data,
            insertOpen: insertEdgeId === edge.id,
            onToggleInsert: (id) => setInsertEdgeId((current) => current === id ? null : id),
            onInsert: insertNode,
        },
    })), [edges, insertEdgeId, insertNode]);

    const decoratedNodes = useMemo(() => nodes.map((node) => ({
        ...node,
        data: {
            ...node.data,
            onRun: runAll,
            onInterrupt: interruptWorkflow,
        },
    })), [interruptWorkflow, nodes, runAll]);

    const editorNode = nodes.find((node) => node.id === editorNodeId) || null;

    const handleNodeClick = useCallback((event, node) => {
        closeMenus();
        if (!event.ctrlKey && !event.metaKey) return;
        const nextSelection = new Set(selectedNodeIds);
        if (nextSelection.has(node.id)) nextSelection.delete(node.id);
        else nextSelection.add(node.id);
        setNodes((current) => current.map((item) => ({
            ...item,
            selected: nextSelection.has(item.id),
        })));
    }, [closeMenus, selectedNodeIds, setNodes]);

    const handleKeyboard = useCallback((event) => {
        const target = event.target;
        const isTextEntry = target instanceof HTMLElement && (
            target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
        );
        if (isTextEntry) return;
        const selectedIds = nodes.filter((node) => node.selected).map((node) => node.id);
        const selectedEdges = edges.filter((edge) => edge.selected).map((edge) => edge.id);
        const control = event.ctrlKey || event.metaKey;
        const key = event.key.toLowerCase();
        if (control && key === 'c' && hasBrowserTextSelection()) return;
        if (control && key === 'z') {
            event.preventDefault();
            if (event.shiftKey) redo();
            else undo();
            return;
        }
        if (control && key === 'y') {
            event.preventDefault();
            redo();
            return;
        }
        if (control && key === 'c' && selectedIds.length) {
            event.preventDefault();
            copyNodes(selectedIds);
            return;
        }
        if (control && key === 'v' && clipboard?.nodes?.length) {
            event.preventDefault();
            pasteClipboard();
            return;
        }
        if ((event.key === 'Delete' || event.key === 'Backspace') && (selectedIds.length || selectedEdges.length)) {
            event.preventDefault();
            deleteElements(selectedIds, selectedEdges);
        }
    }, [clipboard, copyNodes, deleteElements, edges, nodes, pasteClipboard, redo, undo]);

    const handleCopy = useCallback((event) => {
        if (hasBrowserTextSelection()) return;
        const target = event.target;
        if (target instanceof HTMLElement && (
            target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
        )) return;
        const selectedIds = nodes.filter((node) => node.selected).map((node) => node.id);
        if (!selectedIds.length) return;
        event.preventDefault();
        event.clipboardData?.setData('text/plain', 'agent-bench-workflow-nodes');
        copyNodes(selectedIds);
    }, [copyNodes, nodes]);

    const handlePaste = useCallback((event) => {
        const target = event.target;
        if (target instanceof HTMLElement && (
            target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
        )) return;
        if (!clipboard?.nodes?.length) return;
        event.preventDefault();
        pasteClipboard();
    }, [clipboard, pasteClipboard]);

    const handleMarqueeStart = useCallback((event) => {
        if ((!event.ctrlKey && !event.metaKey) || event.button !== 0) return;
        if (!(event.target instanceof HTMLElement) || !event.target.classList.contains('react-flow__pane')) return;
        const canvas = event.currentTarget.querySelector('.wf-canvas-wrap');
        if (!canvas) return;
        const canvasRect = canvas.getBoundingClientRect();
        const next = {
            pointerId: event.pointerId,
            startClientX: event.clientX,
            startClientY: event.clientY,
            clientX: event.clientX,
            clientY: event.clientY,
            canvasLeft: canvasRect.left,
            canvasTop: canvasRect.top,
        };
        event.preventDefault();
        event.stopPropagation();
        event.currentTarget.setPointerCapture?.(event.pointerId);
        marqueeRef.current = next;
        setMarquee(next);
    }, []);

    const handleMarqueeMove = useCallback((event) => {
        if (!marqueeRef.current || marqueeRef.current.pointerId !== event.pointerId) return;
        event.preventDefault();
        const next = {...marqueeRef.current, clientX: event.clientX, clientY: event.clientY};
        marqueeRef.current = next;
        setMarquee(next);
    }, []);

    const handleMarqueeEnd = useCallback((event) => {
        const current = marqueeRef.current;
        if (!current || current.pointerId !== event.pointerId) return;
        event.preventDefault();
        event.stopPropagation();
        const left = Math.min(current.startClientX, event.clientX);
        const right = Math.max(current.startClientX, event.clientX);
        const top = Math.min(current.startClientY, event.clientY);
        const bottom = Math.max(current.startClientY, event.clientY);
        const matched = new Set();
        if (right - left >= 4 && bottom - top >= 4) {
            document.querySelectorAll('.react-flow__node').forEach((element) => {
                const rect = element.getBoundingClientRect();
                if (rect.right >= left && rect.left <= right && rect.bottom >= top && rect.top <= bottom) {
                    const id = element.getAttribute('data-id');
                    if (id) matched.add(id);
                }
            });
        }
        setNodes((items) => items.map((node) => ({...node, selected: node.selected || matched.has(node.id)})));
        event.currentTarget.releasePointerCapture?.(event.pointerId);
        marqueeRef.current = null;
        setMarquee(null);
    }, [setNodes]);

    const contextAction = useCallback((action) => {
        if (action === 'test-run') runAll();
        if (action === 'interrupt-workflow') interruptWorkflow();
        if (action === 'paste-node') pasteNode();
        if (action === 'run-node' && contextMenu?.nodeId) runAll();
        if (action === 'interrupt-node' && contextMenu?.nodeId) interruptWorkflow();
        if (action === 'copy-node' && contextMenu?.nodeId) copyNode(contextMenu.nodeId);
        if (action === 'delete-node' && contextMenu?.nodeId) deleteNode(contextMenu.nodeId);
        if (action === 'delete-edge' && contextMenu?.edgeId) deleteEdges([contextMenu.edgeId]);
        if (action !== 'paste-node') setContextMenu(null);
    }, [contextMenu, copyNode, deleteEdges, deleteNode, interruptWorkflow, pasteNode, runAll]);

    const autoLayout = useCallback(() => {
        recordHistory();
        setNodes((current) => layoutGraph(current, edges));
        window.setTimeout(() => fitView({padding: 0.16, duration: 450}), 0);
    }, [edges, fitView, recordHistory, setNodes]);

    useEffect(() => {
        if (initialLayoutDone.current) return;
        initialLayoutDone.current = true;
        if (!options.draft?.nodes?.length) {
            setNodes((current) => layoutGraph(current, edges));
        }
        window.setTimeout(() => fitView({padding: 0.16, duration: 0}), 0);
    }, [edges, fitView, options.draft, setNodes]);

    const save = useCallback(async () => {
        try {
            await persistDraft();
            if (window.showToast) window.showToast('Workflow 草稿已保存', 'success');
        } catch (error) {
            if (window.showToast) window.showToast(error instanceof Error ? error.message : 'Workflow 保存失败', 'error');
        }
    }, [persistDraft]);

    const close = useCallback(() => {
        if (workflowRunRef.current.active) void interruptWorkflow();
        timers.current.forEach((timer) => {
            window.clearTimeout(timer);
            window.clearInterval(timer);
        });
        if (options.onClose) options.onClose();
        if (workflowElapsedTimer.current !== null) window.clearInterval(workflowElapsedTimer.current);
    }, [interruptWorkflow, options]);

    const canUndo = historyTick >= 0 && undoStack.current.length > 0;
    const canRedo = historyTick >= 0 && redoStack.current.length > 0;

    return (
        <div className="workflow-studio-shell" tabIndex={0} aria-label="工作流画布" onKeyDown={handleKeyboard} onCopy={handleCopy} onPaste={handlePaste} onPointerDownCapture={handleMarqueeStart} onPointerMoveCapture={handleMarqueeMove} onPointerUpCapture={handleMarqueeEnd} onContextMenu={(event) => event.preventDefault()}>
            <header className="wf-studio-header">
                <div className="wf-header-left">
                    <button type="button" className="wf-icon-button" onClick={close} title="返回工作流管理" aria-label="返回工作流管理"><ArrowLeft size={18} /></button>
                    <span className="wf-header-divider" />
                    <span className="wf-workflow-mark"><Sparkles size={17} /></span>
                    {nameEditing ? (
                        <input
                            autoFocus
                            value={workflowName}
                            maxLength={120}
                            onChange={(event) => {setWorkflowName(event.target.value); setSaveState('未保存');}}
                            onBlur={commitWorkflowName}
                            onKeyDown={(event) => {
                                if (event.key === 'Enter') event.currentTarget.blur();
                                if (event.key === 'Escape') {
                                    nameEditCancelled.current = true;
                                    event.currentTarget.blur();
                                }
                            }}
                            aria-label="工作流名称"
                        />
                    ) : (
                        <button
                            type="button"
                            className="wf-workflow-name"
                            onDoubleClick={() => setNameEditing(true)}
                        >{workflowName}</button>
                    )}
                    <span className="wf-save-state"><i />{saveState}</span>
                </div>
                <div className={`wf-header-description ${descriptionEditing ? 'is-editing' : ''}`}>
                    <FileText size={15} />
                    {descriptionEditing ? (
                        <div className="wf-description-editor">
                            <textarea
                                autoFocus
                                value={workflowDescription}
                                maxLength={2000}
                                rows={5}
                                onChange={(event) => {setWorkflowDescription(event.target.value); setSaveState('未保存');}}
                                onBlur={commitWorkflowDescription}
                                onKeyDown={(event) => {
                                    if (event.key === 'Escape') {
                                        descriptionEditCancelled.current = true;
                                        event.currentTarget.blur();
                                    }
                                }}
                                aria-label="工作流说明"
                            />
                        </div>
                    ) : (
                        <button
                            type="button"
                            aria-label="工作流说明"
                            onDoubleClick={() => setDescriptionEditing(true)}
                        >{workflowDescription || '添加工作流说明'}</button>
                    )}
                </div>
                <div className="wf-header-actions">
                    {workflowRunState !== 'IDLE' && <span className={`wf-workflow-timer is-${workflowRunState.toLowerCase()}`} aria-label={`Workflow 执行耗时 ${formatExecutionDuration(workflowElapsedMs)}`}><LoaderCircle size={13} />{formatExecutionDuration(workflowElapsedMs)}</span>}
                    <button type="button" disabled={workflowRunState === 'RUNNING'} className="wf-secondary-button" onClick={runAll}><Play size={15} />运行</button>
                    <button type="button" className={headerPanel === 'variables' ? 'is-active' : ''} onClick={() => setHeaderPanel((current) => current === 'variables' ? null : 'variables')}><SlidersHorizontal size={15} />全局变量</button>
                    <button type="button" disabled={workflowRunState !== 'RUNNING'} className="wf-danger-button" onClick={interruptWorkflow}><Square size={14} />中断</button>
                    <button type="button" className="wf-primary-button" onClick={save}><Save size={15} />保存</button>
                </div>
            </header>
            <main className="wf-canvas-wrap">
                {marquee && (
                    <div className="wf-selection-marquee" style={{
                        left: Math.min(marquee.startClientX, marquee.clientX) - marquee.canvasLeft,
                        top: Math.min(marquee.startClientY, marquee.clientY) - marquee.canvasTop,
                        width: Math.abs(marquee.clientX - marquee.startClientX),
                        height: Math.abs(marquee.clientY - marquee.startClientY),
                    }} />
                )}
                {nodeSaveNotice && (
                    <div className="wf-node-save-toast" role="status"><Check size={15} /><span>{nodeSaveNotice.label} 已保存</span><time>{nodeSaveNotice.savedAt}</time></div>
                )}
                {headerPanel === 'variables' && (
                    <aside className="wf-header-popover" aria-label="工作流全局变量">
                        <header>
                            <strong>全局变量</strong>
                            <button type="button" onClick={() => setHeaderPanel(null)} title="关闭" aria-label="关闭顶部面板"><X size={16} /></button>
                        </header>
                        <div className="wf-global-parameters">
                                <div className="wf-mapping-label-row"><span>变量名</span><span>变量</span><span /></div>
                                {globalVariables.map((row, index) => (
                                    <div className="wf-mapping-value-row" key={row.id}>
                                        <input aria-label={`全局变量名 ${index + 1}`} value={row.name} onChange={(event) => setGlobalVariables((current) => current.map((item) => item.id === row.id ? {...item, name: event.target.value} : item))} />
                                        <input aria-label={`全局变量 ${index + 1}`} value={row.value} onChange={(event) => setGlobalVariables((current) => current.map((item) => item.id === row.id ? {...item, value: event.target.value} : item))} />
                                        {index === 0 ? (
                                            <button type="button" className="wf-inline-icon-button" onClick={() => setGlobalVariables((current) => current.concat(emptyMappingRow()))} title="新增全局变量" aria-label="新增全局变量"><Plus size={15} /></button>
                                        ) : (
                                            <button type="button" className="wf-inline-icon-button is-danger" onClick={() => setGlobalVariables((current) => current.filter((item) => item.id !== row.id))} title="删除全局变量" aria-label={`删除全局变量 ${index + 1}`}><Trash2 size={15} /></button>
                                        )}
                                    </div>
                                ))}
                        </div>
                    </aside>
                )}
                <ReactFlow
                    nodes={decoratedNodes}
                    edges={decoratedEdges}
                    nodeTypes={nodeTypes}
                    edgeTypes={edgeTypes}
                    onNodesChange={onNodesChange}
                    onEdgesChange={onEdgesChange}
                    onConnect={(connection) => {
                        recordHistory();
                        setEdges((current) => addEdge(makeEdge(connection.source, connection.target, connection), current));
                    }}
                    onNodeDragStart={recordHistory}
                    onPaneClick={closeMenus}
                    onNodeClick={handleNodeClick}
                    onSelectionChange={({nodes: selectedNodes, edges: selectedEdges}) => {
                        setSelectedNodeIds(selectedNodes.map((node) => node.id));
                        setSelectedEdgeIds(selectedEdges.map((edge) => edge.id));
                    }}
                    onEdgeClick={(event, edge) => {
                        event.stopPropagation();
                        document.querySelector('.workflow-studio-shell')?.focus();
                        setNodes((current) => current.map((node) => ({...node, selected: false})));
                        setEdges((current) => current.map((item) => ({...item, selected: item.id === edge.id})));
                        setSelectedNodeIds([]);
                        setSelectedEdgeIds([edge.id]);
                        closeMenus();
                    }}
                    onNodeDoubleClick={(event, node) => {
                        event.preventDefault();
                        closeMenus();
                        setEditorNodeId(node.id);
                    }}
                    onPaneContextMenu={(event) => {
                        event.preventDefault();
                        const flowPosition = screenToFlowPosition({x: event.clientX, y: event.clientY});
                        setContextMenu({
                            kind: 'pane',
                            x: Math.max(8, Math.min(event.clientX, window.innerWidth - 480)),
                            y: Math.max(66, Math.min(event.clientY, window.innerHeight - 235)),
                            flowPosition,
                        });
                        setInsertEdgeId(null);
                    }}
                    onNodeContextMenu={(event, node) => {
                        event.preventDefault();
                        if (!node.selected) {
                            setNodes((current) => current.map((item) => ({...item, selected: item.id === node.id})));
                        }
                        setContextMenu({
                            kind: 'node',
                            nodeId: node.id,
                            x: Math.max(8, Math.min(event.clientX, window.innerWidth - 205)),
                            y: Math.max(66, Math.min(event.clientY, window.innerHeight - 155)),
                        });
                        setInsertEdgeId(null);
                    }}
                    onEdgeContextMenu={(event, edge) => {
                        event.preventDefault();
                        event.stopPropagation();
                        document.querySelector('.workflow-studio-shell')?.focus();
                        setNodes((current) => current.map((node) => ({...node, selected: false})));
                        setEdges((current) => current.map((item) => ({...item, selected: item.id === edge.id})));
                        setSelectedNodeIds([]);
                        setSelectedEdgeIds([edge.id]);
                        setContextMenu({
                            kind: 'edge',
                            edgeId: edge.id,
                            x: Math.max(8, Math.min(event.clientX, window.innerWidth - 205)),
                            y: Math.max(66, Math.min(event.clientY, window.innerHeight - 110)),
                        });
                        setInsertEdgeId(null);
                    }}
                    fitView
                    fitViewOptions={{padding: 0.16}}
                    minZoom={0.35}
                    maxZoom={1.8}
                    selectionOnDrag={false}
                    selectionKeyCode="Control"
                    multiSelectionKeyCode="Control"
                    panOnScroll
                    zoomOnDoubleClick={false}
                    deleteKeyCode={null}
                    proOptions={{hideAttribution: true}}
                >
                    <Background color="#c8d1de" gap={20} size={1.2} />
                    <MiniMap pannable zoomable nodeColor={(node) => NODE_TYPES[node.data.nodeType]?.color || '#64748b'} maskColor="rgba(238, 242, 247, 0.76)" />
                    <Controls showInteractive={false} />
                    <div className="wf-floating-toolbar">
                        <button type="button" disabled={!canUndo} onClick={undo} title="回退" aria-label="回退"><Undo2 size={16} /></button>
                        <button type="button" disabled={!canRedo} onClick={redo} title="前进" aria-label="前进"><Redo2 size={16} /></button>
                        <span />
                        <button type="button" onClick={autoLayout} title="自动布局" aria-label="自动布局"><LayoutGrid size={16} /></button>
                    </div>
                </ReactFlow>
                <ContextMenu
                    menu={contextMenu}
                    canPaste={Boolean(clipboard?.nodes?.length)}
                    onAction={contextAction}
                    onAdd={(type) => contextMenu?.flowPosition && addNodeAt(type, contextMenu.flowPosition)}
                />
                <Inspector
                    key={editorNodeId || 'none'}
                    node={editorNode}
                    providers={modelProviders}
                    providerLoadState={providerLoadState}
                    providerLoadError={providerLoadError}
                    onRefreshProviders={loadModelProviders}
                    onLoadVariables={() => editorNodeId ? loadNodeVariables(editorNodeId) : []}
                    onRun={() => window.showToast && window.showToast('请使用画布右上角运行 Workflow', 'error')}
                    onInterrupt={() => window.showToast && window.showToast('请使用画布右上角中断 Workflow', 'error')}
                    onSave={() => editorNodeId && saveNode(editorNodeId)}
                    onClose={() => setEditorNodeId(null)}
                    onChange={(patch) => setNodes((current) => current.map((node) => node.id === editorNodeId ? {...node, data: {...node.data, ...patch, isDirty: true}} : node))}
                />
            </main>
        </div>
    );
}

let activeRoot = null;
let activeContainer = null;

function unmount() {
    if (activeRoot) activeRoot.unmount();
    if (activeContainer) activeContainer.remove();
    activeRoot = null;
    activeContainer = null;
    document.body.classList.remove('workflow-studio-open');
}

function mount(options = {}) {
    unmount();
    activeContainer = document.createElement('div');
    activeContainer.id = 'workflow-studio-root';
    document.body.appendChild(activeContainer);
    document.body.classList.add('workflow-studio-open');
    activeRoot = createRoot(activeContainer);
    activeRoot.render(
        <React.StrictMode>
            <ReactFlowProvider><WorkflowStudio options={options} /></ReactFlowProvider>
        </React.StrictMode>,
    );
}

window.AgentBenchWorkflowCanvas = {mount, unmount};
