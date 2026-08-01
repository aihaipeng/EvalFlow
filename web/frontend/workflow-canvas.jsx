import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {python} from '@codemirror/lang-python';
import {EditorState} from '@codemirror/state';
import {EditorView} from '@codemirror/view';
import {oneDark} from '@codemirror/theme-one-dark';
import dagre from '@dagrejs/dagre';
import * as Dialog from '@radix-ui/react-dialog';
import {basicSetup} from 'codemirror';
import parseCurl from 'parse-curl';
import {Rnd} from 'react-rnd';
import {split as splitShellWords} from 'shellwords';
import {workflowNodeExecutionDuration} from './workflow-execution-timing.mjs';
import {clampInspectorPosition} from './workflow-inspector-layout.mjs';
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
    useViewport,
} from '@xyflow/react';
import {
    ArrowLeft,
    BrainCircuit,
    Check,
    ChevronDown,
    ChevronRight,
    CircleHelp,
    CirclePlay,
    Clipboard,
    Code2,
    Copy,
    ExternalLink,
    Eye,
    FileClock,
    FileText,
    Globe2,
    LayoutGrid,
    LoaderCircle,
    MessageSquareText,
    Pencil,
    Play,
    Plus,
    Redo2,
    RefreshCw,
    Save,
    Search,
    Settings2,
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
import {calculateAlignmentGuides} from './workflow-alignment.mjs';

const NODE_TYPES = {
    START: {label: '开始', caption: 'START', icon: CirclePlay, color: '#16803c', executable: false},
    HTTP: {label: 'HTTP', caption: 'HTTP', icon: Globe2, color: '#2563eb', executable: true, runtime: 'HTTP'},
    LLM: {label: 'LLM', caption: 'LLM', icon: BrainCircuit, color: '#7048c6', executable: true, runtime: 'Gateway'},
    SCRIPT: {label: 'SCRIPT', caption: 'SCRIPT', icon: Code2, color: '#c56a12', executable: true, runtime: 'Python'},
    END: {label: '结束', caption: 'END', icon: Check, color: '#3f4b5f', executable: false},
};

const INSERTABLE_TYPES = ['HTTP', 'LLM', 'SCRIPT'];
const NODE_STATUSES = ['PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'TIMEOUT', 'INTERRUPTED'];
const HTTP_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'];
const HTTP_BODY_TYPES = ['none', 'form-data', 'x-www-form-urlencoded', 'raw'];
const OUTPUT_VARIABLE_TYPES = ['string', 'integer', 'number', 'boolean', 'object', 'array', 'null'];

function documentTheme() {
    return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
}

function useDocumentTheme() {
    const [theme, setTheme] = useState(documentTheme);

    useEffect(() => {
        const root = document.documentElement;
        const observer = new MutationObserver(() => setTheme(documentTheme()));
        observer.observe(root, {attributes: true, attributeFilter: ['data-theme']});
        return () => observer.disconnect();
    }, []);

    return theme;
}

const DEFAULT_SCRIPT_MAIN_PY = 'msg = "介绍一下自己"\nprint(msg)';
const MODEL_PROTOCOL_LABELS = {
    OPENAI_COMPATIBLE: 'OpenAI Chat Completions',
    OPENAI_RESPONSES: 'OpenAI Responses API',
    ANTHROPIC: 'Anthropic Claude Messages',
};
const LLM_PARAMETERS_REFERENCES = {
    OPENAI_COMPATIBLE: {
        temperature: 0,
        top_p: 0.8,
        max_tokens: 1024,
        response_format: {type: 'json_object'},
    },
    OPENAI_RESPONSES: {
        reasoning: {effort: 'medium'},
        max_output_tokens: 1024,
        text: {format: {type: 'json_object'}},
    },
    ANTHROPIC: {
        temperature: 0,
        top_p: 0.8,
        max_tokens: 1024,
        thinking: {type: 'disabled'},
    },
};
const MODEL_PROTOCOL_FORBIDDEN_FIELDS = {
    OPENAI_COMPATIBLE: ['input', 'instructions', 'max_output_tokens', 'system', 'anthropic_version'],
    OPENAI_RESPONSES: ['messages', 'max_tokens', 'max_completion_tokens', 'response_format', 'system', 'stop_sequences'],
    ANTHROPIC: ['input', 'instructions', 'max_output_tokens', 'max_completion_tokens', 'response_format', 'reasoning', 'reasoning_effort', 'text', 'seed', 'frequency_penalty', 'presence_penalty', 'logprobs', 'top_logprobs'],
};

function modelProtocolLabel(protocol) {
    return MODEL_PROTOCOL_LABELS[protocol] || protocol || '未知协议';
}

function llmParametersReference(protocol) {
    return JSON.stringify(
        LLM_PARAMETERS_REFERENCES[protocol] || LLM_PARAMETERS_REFERENCES.OPENAI_COMPATIBLE,
        null,
        2,
    );
}

function modelParametersProtocolError(protocol, parameters) {
    if (!parameters || Array.isArray(parameters) || typeof parameters !== 'object') return '';
    const forbidden = new Set(MODEL_PROTOCOL_FORBIDDEN_FIELDS[protocol] || []);
    const incompatible = Object.keys(parameters).filter((field) => forbidden.has(field)).sort();
    return incompatible.length
        ? `${modelProtocolLabel(protocol)} 不支持参数：${incompatible.join('、')}。请移除其他协议的字段后重试`
        : '';
}
const DEFAULT_LLM_MESSAGES = [
    {role: 'SYSTEM', content: ''},
    {role: 'USER', content: ''},
];
const LLM_MESSAGE_HINTS = {
    SYSTEM: '可为空；执行时自动省略空 SYSTEM',
    USER: '最终一条 USER 是模型本次需要回答的内容',
    ASSISTANT: '用于告诉模型期望的回答方式或格式',
};

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
    const starts = nodes.filter((node) => node.data?.nodeType === 'START');
    const ends = nodes.filter((node) => node.data?.nodeType === 'END');
    const business = nodes.filter((node) => INSERTABLE_TYPES.includes(node.data?.nodeType));
    if (starts.length !== 1) return 'Workflow 必须恰好包含一个 START';
    if (ends.length !== 1) return 'Workflow 必须恰好包含一个 END';
    if (!business.length) return 'Workflow 至少包含一个 SCRIPT、LLM 或 HTTP 业务节点';
    const adjacency = new Map(nodes.map((node) => [node.id, new Set()]));
    const indegree = new Map(nodes.map((node) => [node.id, 0]));
    const outdegree = new Map(nodes.map((node) => [node.id, 0]));
    const pairs = new Set();
    edges.forEach((edge) => {
        if (!adjacency.has(edge.source) || !adjacency.has(edge.target)) return;
        if (edge.source === edge.target) return;
        const pair = `${edge.source}:${edge.target}`;
        if (pairs.has(pair)) return;
        pairs.add(pair);
        if (!adjacency.get(edge.source).has(edge.target)) {
            adjacency.get(edge.source).add(edge.target);
            indegree.set(edge.target, indegree.get(edge.target) + 1);
            outdegree.set(edge.source, outdegree.get(edge.source) + 1);
        }
    });
    if (edges.some((edge) => !adjacency.has(edge.source) || !adjacency.has(edge.target))) return '连线两端必须属于当前 Workflow';
    if (edges.some((edge) => edge.source === edge.target)) return 'Workflow 不允许自环';
    if (pairs.size !== edges.length) return 'Workflow 不允许重复连线';
    const roots = nodes.filter((node) => indegree.get(node.id) === 0);
    const leaves = nodes.filter((node) => outdegree.get(node.id) === 0);
    if (roots.length !== 1 || roots[0].id !== starts[0].id) return 'START 必须是唯一根节点且不能有入边';
    if (leaves.length !== 1 || leaves[0].id !== ends[0].id) return 'END 必须是唯一叶节点且不能有出边';
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

function cloneLlmMessages(messages = DEFAULT_LLM_MESSAGES) {
    const normalized = Array.isArray(messages) && messages.length ? messages : DEFAULT_LLM_MESSAGES;
    return normalized.map((message) => ({
        id: message.id || rowId(),
        role: message.role,
        content: message.content || '',
        fixed: Boolean(message.fixed),
    }));
}

function llmMessagesFromContext(context) {
    const messages = Array.isArray(context?.messages) ? context.messages : DEFAULT_LLM_MESSAGES;
    return cloneLlmMessages(messages).map((message, index) => ({
        ...message,
        fixed: index < 2,
    }));
}

function llmMessagesForStructural(messages) {
    const normalized = cloneLlmMessages(messages);
    return normalized.map((message) => ({
        role: message.role,
        content: message.content || '',
    }));
}

function nextLlmRole(messages) {
    return messages.length <= 2 || messages.at(-1)?.role === 'USER' ? 'ASSISTANT' : 'USER';
}

function llmMessageErrors(messages) {
    const errors = new Map();
    messages.forEach((message, index) => {
        if (index >= 2) {
            const expected = index % 2 === 0 ? 'ASSISTANT' : 'USER';
            if (message.role !== expected) errors.set(message.id, `此处必须是 ${expected}`);
        }
        if (message.role !== 'SYSTEM' && !String(message.content || '').trim()) {
            errors.set(message.id, message.role === 'USER' ? 'USER 消息不能为空' : 'Few-shot 示例回答不能为空');
        }
    });
    const last = messages.at(-1);
    if (!last || last.role !== 'USER') {
        if (last) errors.set(last.id, '上下文必须以 USER 消息结束后才能运行');
    } else if (!String(last.content || '').trim()) {
        errors.set(last.id, '最后一条 USER 消息不能为空');
    }
    return errors;
}

function isPlainObject(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function variableScopeNodes(nodes, edges, targetNodeId) {
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    if (!nodeById.has(targetNodeId)) return [];
    const parents = new Map(nodes.map((node) => [node.id, []]));
    edges.forEach((edge) => {
        if (parents.has(edge.target) && nodeById.has(edge.source)) {
            parents.get(edge.target).push(edge.source);
        }
    });
    const included = new Set([targetNodeId]);
    const pending = [targetNodeId];
    while (pending.length) {
        const current = pending.pop();
        (parents.get(current) || []).forEach((parentId) => {
            if (included.has(parentId)) return;
            included.add(parentId);
            pending.push(parentId);
        });
    }
    const indegree = new Map(Array.from(included, (nodeId) => [nodeId, 0]));
    const children = new Map(Array.from(included, (nodeId) => [nodeId, []]));
    edges.forEach((edge) => {
        if (!included.has(edge.source) || !included.has(edge.target)) return;
        children.get(edge.source).push(edge.target);
        indegree.set(edge.target, indegree.get(edge.target) + 1);
    });
    const ready = nodes.filter((node) => included.has(node.id) && indegree.get(node.id) === 0);
    const ordered = [];
    while (ready.length) {
        const current = ready.shift();
        ordered.push(current);
        children.get(current.id).forEach((childId) => {
            indegree.set(childId, indegree.get(childId) - 1);
            if (indegree.get(childId) === 0) ready.push(nodeById.get(childId));
        });
    }
    return ordered;
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

function runResultSummary(run) {
    if (run.status === 'RUNNING') {
        const liveText = typeof run.response_body === 'string'
            ? run.response_body.replace(/\s+/g, ' ').trim()
            : '';
        if (!liveText) return '正在接收原始响应…';
        return liveText.length > 160 ? `${liveText.slice(0, 157)}...` : liveText;
    }
    const value = ['FAILED', 'TIMEOUT', 'INTERRUPTED'].includes(run.status) ? run.error?.message : run.output;
    const text = parameterDataText(value).replace(/\s+/g, ' ').trim();
    if (!text) return '无最终结果';
    return text.length > 160 ? `${text.slice(0, 157)}...` : text;
}

function emptyMappingRow() {
    return {id: rowId(), name: '', type: 'string', value: ''};
}

function friendlyNodeError(error, fallback = '节点执行失败') {
    if (!error) return fallback;
    const message = error.message || fallback;
    const suggestion = error.details?.suggestion;
    return suggestion ? `${message}。${suggestion}` : message;
}

function nodeExecutionHistoryRun(execution) {
    return {
        ...execution,
        id: execution.node_execution_id || execution.test_id || rowId(),
        output: execution.outputs,
        response_body: typeof execution.response === 'string'
            ? execution.response
            : JSON.stringify(execution.response ?? ''),
    };
}

function nodeTestValueText(value, type) {
    if (type === 'string') return String(value ?? '');
    if (value === undefined) return type === 'null' ? 'null' : '';
    if (typeof value === 'string') return value;
    return JSON.stringify(value);
}

function parseNodeTestValue(row) {
    const type = row.type || 'string';
    const text = String(row.valueText ?? '');
    if (type === 'string') return text;
    if (type === 'boolean') {
        if (text === 'true') return true;
        if (text === 'false') return false;
        throw new Error(`变量 ${row.name} 的 boolean 值必须是 true 或 false`);
    }
    if (type === 'null') {
        if (text.trim() === 'null') return null;
        throw new Error(`变量 ${row.name} 的 null 值必须是 null`);
    }
    let value;
    try {
        value = JSON.parse(text);
    } catch (_error) {
        throw new Error(`变量 ${row.name} 不是合法的 ${type} 值`);
    }
    const valid = (
        (type === 'integer' && Number.isInteger(value))
        || (type === 'number' && typeof value === 'number' && Number.isFinite(value))
        || (type === 'object' && isPlainObject(value))
        || (type === 'array' && Array.isArray(value))
    );
    if (!valid) throw new Error(`变量 ${row.name} 的值与类型 ${type} 不匹配`);
    return value;
}

function emptyStartInput() {
    return {id: rowId(), name: '', type: 'string', value: ''};
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
        responseBodyType: 'auto',
        successStatuses: ['200-299'],
        retryNonIdempotent: false,
        retryStatuses: [408, 429, 500, 502, 503, 504],
    };
}

function parseHttpJsonTemplate(text) {
    let inString = false;
    let escaped = false;
    let normalized = '';
    for (let index = 0; index < String(text || '').length;) {
        const character = text[index];
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
        const reference = text.slice(index).match(/^\$\{[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[0-9]+\])*\}/);
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
            timeoutSeconds: 600,
            retryCount: 0,
            retryIntervalSeconds: 0,
            delaySeconds: 0,
            outputVariables: [emptyMappingRow()],
            parameterRecords: [],
            ...(type === 'START' ? {startInputs: [emptyStartInput()]} : {}),
            ...(type === 'HTTP' ? {httpConfig: defaultHttpConfig()} : {}),
            ...(type === 'LLM' ? {
                providerId: '',
                modelName: '',
                llmMessages: cloneLlmMessages(DEFAULT_LLM_MESSAGES),
                modelParameters: {},
                modelParametersText: '',
            } : {}),
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
    const start = makeNode('START', {x: 150, y: 280}, {label: '开始'});
    const script = makeNode('SCRIPT', {x: 465, y: 280}, {label: '规则校验'});
    const end = makeNode('END', {x: 780, y: 280}, {label: '结束'});
    return {
        nodes: [start, script, end],
        edges: [
            makeEdge(start.id, script.id),
            makeEdge(script.id, end.id),
        ],
    };
}

function replaceCanvasNode(nodes, edges, currentNodeId, targetType) {
    const currentNode = nodes.find((node) => node.id === currentNodeId);
    if (!currentNode || !INSERTABLE_TYPES.includes(currentNode.data?.nodeType)) return null;
    if (!INSERTABLE_TYPES.includes(targetType) || targetType === currentNode.data.nodeType) return null;
    const replacement = {
        ...makeNode(targetType, {...currentNode.position}),
        selected: Boolean(currentNode.selected),
    };
    return {
        oldNodeId: currentNodeId,
        newNodeId: replacement.id,
        nodes: nodes.map((node) => node.id === currentNodeId ? replacement : node),
        edges: edges.map((edge) => ({
            ...edge,
            source: edge.source === currentNodeId ? replacement.id : edge.source,
            target: edge.target === currentNodeId ? replacement.id : edge.target,
        })),
    };
}

function graphFromDraft(draft) {
    if (!draft?.nodes?.length) return initialGraph();
    const needsLayout = draft.nodes.every((stored) => !stored.position);
    const nodes = draft.nodes.map((stored) => {
        const type = stored.data?.nodeType || 'SCRIPT';
        const defaults = makeNode(type, stored.position || {x: 0, y: 0});
        const storedData = cloneValue(stored.data || {});
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
    for (const key of ('status executionDurationMs runHistory executionId savedAt isDirty temporaryRun nodeTestActive nodeTestId nodeTestStartedAt'.split(' '))) {
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

const WorkflowNode = React.memo(function WorkflowNode({data, selected}) {
    const meta = NODE_TYPES[data.nodeType] || NODE_TYPES.SCRIPT;
    const Icon = meta.icon;
    const status = NODE_STATUSES.includes(data.status) ? data.status : 'PENDING';
    const statusClass = status.toLowerCase();
    const executionDuration = formatExecutionDuration(data.executionDurationMs);
    const testRunning = Boolean(data.nodeTestActive);
    return (
        <article className={`wf-node ${selected ? 'is-selected' : ''} is-${statusClass}`} style={{'--node-accent': meta.color}}>
            {data.nodeType !== 'START' && <Handle type="target" position={Position.Left} className="wf-handle" />}
            <header className="wf-node-header">
                <span className="wf-node-icon"><Icon size={17} strokeWidth={2} /></span>
                <span className="wf-node-caption">{meta.caption}</span>
                <span className="wf-node-actions">
                    <button type="button" title="配置" aria-label={`配置 ${data.label}`} onClick={(event) => {event.stopPropagation(); data.onConfigure?.();}}><Settings2 size={13} /></button>
                    {data.nodeType !== 'END' && <button type="button" title="日志" aria-label={`查看 ${data.label} 日志`} onClick={(event) => {event.stopPropagation(); data.onOpenLogs?.();}}><FileText size={13} /></button>}
                    {data.nodeType !== 'END' && <button type="button" disabled={testRunning} title="运行" aria-label={`运行 ${data.label}`} onClick={(event) => {event.stopPropagation(); data.onRun?.();}}><Play size={13} /></button>}
                </span>
            </header>
            <strong className="wf-node-title">{data.label}</strong>
            <footer className="wf-node-footer">
                <span className={`wf-node-status is-${statusClass}`}><i />{status}</span>
                <span className="wf-node-meta">
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
});

function NodePicker({onSelect, compact = false, includeSystem = false, excludeType = null}) {
    const types = (includeSystem ? ['START', 'END', ...INSERTABLE_TYPES] : INSERTABLE_TYPES)
        .filter((type) => type !== excludeType);
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

function ContextMenu({menu, canPaste, canReplace, onAction, onAdd, onReplace}) {
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
                {menu.nodeType !== 'END' && <button type="button" onClick={() => onAction('run-node')}><Play size={15} /><span>运行此步骤</span></button>}
                {INSERTABLE_TYPES.includes(menu.nodeType) && (
                    <div className={`wf-context-submenu-trigger ${submenuOpen ? 'is-open' : ''}`}>
                        <button type="button" disabled={!canReplace} aria-expanded={submenuOpen} onClick={() => setSubmenuOpen((open) => !open)}><RefreshCw size={15} /><span>更换节点</span><ChevronRight size={14} /></button>
                        {canReplace && (
                            <div className="wf-context-submenu">
                                <NodePicker compact excludeType={menu.nodeType} onSelect={(type) => onReplace(menu.nodeId, type)} />
                            </div>
                        )}
                    </div>
                )}
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

function AlignmentGuides({guides}) {
    const {x, y, zoom} = useViewport();
    if (!guides) return null;
    return (
        <div className="wf-alignment-guides" aria-hidden="true">
            {guides.horizontal && (
                <span
                    className="wf-alignment-guide is-horizontal"
                    style={{
                        top: guides.horizontal.top * zoom + y,
                        left: guides.horizontal.left * zoom + x,
                        width: guides.horizontal.width * zoom,
                    }}
                />
            )}
            {guides.vertical && (
                <span
                    className="wf-alignment-guide is-vertical"
                    style={{
                        top: guides.vertical.top * zoom + y,
                        left: guides.vertical.left * zoom + x,
                        height: guides.vertical.height * zoom,
                    }}
                />
            )}
        </div>
    );
}

function NodeTestVariablesDialog({dialog, onRowsChange, onCancel, onSubmit}) {
    if (!dialog) return null;
    const updateRow = (id, patch) => onRowsChange(dialog.rows.map((row) => (
        row.id === id ? {...row, ...patch} : row
    )));
    const removeRow = (id) => onRowsChange(dialog.rows.filter((row) => row.id !== id));
    const addRow = () => onRowsChange(dialog.rows.concat({
        id: rowId(), name: '', type: 'string', valueText: '',
    }));
    return (
        <Dialog.Root open onOpenChange={(open) => !open && onCancel()}>
            <Dialog.Portal>
                <Dialog.Overlay className="wf-node-test-overlay" />
                <Dialog.Content className="wf-node-test-dialog" aria-describedby={undefined}>
                <header>
                    <div><Dialog.Title asChild><strong id="wf-node-test-title">临时测试变量</strong></Dialog.Title><span>{dialog.nodeLabel}</span></div>
                    <Dialog.Close asChild><button type="button" title="关闭" aria-label="关闭临时测试变量"><X size={16} /></button></Dialog.Close>
                </header>
                <div className="wf-node-test-variable-heading"><span>变量名</span><span>类型</span><span>值</span><span /></div>
                <div className="wf-node-test-variable-list">
                    {dialog.rows.map((row, index) => (
                        <div className="wf-node-test-variable-row" key={row.id}>
                            <input aria-label={`测试变量名 ${index + 1}`} value={row.name} onChange={(event) => updateRow(row.id, {name: event.target.value})} />
                            <select aria-label={`测试变量类型 ${index + 1}`} value={row.type} onChange={(event) => {
                                const type = event.target.value;
                                updateRow(row.id, {type});
                            }}>
                                {OUTPUT_VARIABLE_TYPES.map((type) => <option value={type} key={type}>{type}</option>)}
                            </select>
                            <input aria-label={`测试变量值 ${index + 1}`} value={row.valueText} onChange={(event) => updateRow(row.id, {valueText: event.target.value})} />
                            <button type="button" className="is-danger" onClick={() => removeRow(row.id)} title="删除变量" aria-label={`删除测试变量 ${index + 1}`}><Trash2 size={14} /></button>
                        </div>
                    ))}
                    {!dialog.rows.length && <div className="wf-node-test-variable-empty">暂无变量</div>}
                </div>
                <footer>
                    <button type="button" className="wf-node-test-add" onClick={addRow}><Plus size={14} />添加变量</button>
                    <span />
                    <button type="button" onClick={onCancel}><X size={14} />取消</button>
                    <button type="button" className="is-primary" onClick={onSubmit}><Play size={14} />运行</button>
                </footer>
                </Dialog.Content>
            </Dialog.Portal>
        </Dialog.Root>
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
                                        <span><i />{modelProtocolLabel(provider.protocol)}</span>
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

function NodeRunHistory({runs, nodeType, temporaryRun = null}) {
    const [expandedRunId, setExpandedRunId] = useState(null);
    const visibleRuns = temporaryRun ? [temporaryRun, ...runs.slice(0, 10)] : runs.slice(0, 10);
    if (!visibleRuns.length) return <div className="wf-node-log-empty">暂无运行日志</div>;
    return (
        <div className="wf-llm-run-list">
            {visibleRuns.map((run) => {
                const expanded = expandedRunId === run.id;
                const finalAttempt = run.logs?.attempts?.[Math.max(0, (run.attempt_count || 1) - 1)] || null;
                const consoleContent = finalAttempt?.console?.map((item) => item.content || '').join('') || '';
                const requestContent = run.request ? parameterDataText(run.request, true) : '';
                const responseContent = run.response === null || run.response === undefined
                    ? ''
                    : typeof run.response === 'string' ? run.response : parameterDataText(run.response, true);
                const inputsContent = run.inputs && Object.keys(run.inputs).length
                    ? parameterDataText(run.inputs, true)
                    : '';
                const outputsContent = run.outputs && Object.keys(run.outputs).length
                    ? parameterDataText(run.outputs, true)
                    : '';
                const errorDetails = run.error?.details ? parameterDataText(run.error.details, true) : '';
                const errorContent = run.error ? parameterDataText(run.error, true) : '';
                return (
                    <article className={`wf-llm-run is-${String(run.status || 'FAILED').toLowerCase()}`} key={run.id}>
                        <button type="button" className={`wf-llm-run-summary ${nodeType === 'LLM' ? 'has-token-usage' : ''} ${run.isTemporary ? 'is-temporary' : ''}`} aria-expanded={expanded} onClick={() => setExpandedRunId(expanded ? null : run.id)}>
                            <ChevronRight className={expanded ? 'is-open' : ''} size={15} />
                            <time>{formatRunDate(run.finished_at || run.started_at)}</time>
                            {run.isTemporary && <span className="wf-node-test-badge">临时</span>}
                            <strong>{run.status}</strong>
                            <span className="wf-llm-run-duration">{formatExecutionDuration(run.duration_ms)}</span>
                            {nodeType === 'LLM' && <span className="wf-llm-run-token">{formatRunTokenUsage(run)}</span>}
                            <span className="wf-llm-run-result">{runResultSummary(run)}</span>
                        </button>
                        {expanded && (
                            <div className="wf-llm-run-detail">
                                {nodeType === 'HTTP' ? (
                                    <>
                                        {inputsContent && <HttpLogSection title="inputs" text={inputsContent} />}
                                        {requestContent && <HttpLogSection title="request" text={requestContent} />}
                                        {responseContent && <HttpLogSection title="response" text={responseContent} />}
                                        {outputsContent && <HttpLogSection title="outputs" text={outputsContent} />}
                                    </>
                                ) : nodeType === 'SCRIPT' || nodeType === 'START' ? (
                                    <>
                                        {inputsContent && <HttpLogSection title="inputs" text={inputsContent} />}
                                        {nodeType === 'SCRIPT' && consoleContent && <HttpLogSection title="console" text={consoleContent} />}
                                        {nodeType === 'SCRIPT' && finalAttempt?.traceback && <HttpLogSection title="traceback" text={finalAttempt.traceback} />}
                                        {outputsContent && <HttpLogSection title="outputs" text={outputsContent} />}
                                    </>
                                ) : (
                                    <>
                                        {inputsContent && <HttpLogSection title="inputs" text={inputsContent} />}
                                        {requestContent && <HttpLogSection title="request" text={requestContent} />}
                                        {responseContent && <HttpLogSection title="response" text={responseContent} />}
                                        {outputsContent && <HttpLogSection title="outputs" text={outputsContent} />}
                                    </>
                                )}
                                {errorContent && <HttpLogSection title="error" text={errorContent} />}
                                {!errorContent && errorDetails && <HttpLogSection title="error details" text={errorDetails} />}
                            </div>
                        )}
                    </article>
                );
            })}
        </div>
    );
}

function HttpMethodSelector({value, onChange}) {
    const [open, setOpen] = useState(false);
    const rootRef = useRef(null);

    useEffect(() => {
        if (!open) return undefined;
        const closeFromPointer = (event) => {
            if (!rootRef.current?.contains(event.target)) setOpen(false);
        };
        const closeFromKeyboard = (event) => {
            if (event.key === 'Escape') setOpen(false);
        };
        document.addEventListener('pointerdown', closeFromPointer);
        document.addEventListener('keydown', closeFromKeyboard);
        return () => {
            document.removeEventListener('pointerdown', closeFromPointer);
            document.removeEventListener('keydown', closeFromKeyboard);
        };
    }, [open]);

    const options = HTTP_METHODS.includes(value) ? HTTP_METHODS : [value, ...HTTP_METHODS];
    return (
        <div className="wf-http-method-selector" ref={rootRef}>
            <button type="button" className="wf-http-method-trigger" aria-label="请求方式" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((current) => !current)}>
                <span>{value}</span><ChevronDown size={14} />
            </button>
            {open && (
                <div className="wf-http-method-menu" role="listbox" aria-label="请求方式选项">
                    {options.map((method) => (
                        <button type="button" role="option" aria-selected={method === value} className={method === value ? 'is-selected' : ''} key={method} onClick={() => {onChange(method); setOpen(false);}}>{method}</button>
                    ))}
                </div>
            )}
        </div>
    );
}

function HttpAccordion({title, count, tag, open, onToggle, isLast = false, children}) {
    return (
        <section className={`wf-http-accordion ${isLast ? 'is-last' : ''}`}>
            <button type="button" className="wf-http-accordion-trigger" aria-expanded={open} onClick={onToggle}>
                <span><strong>{title}</strong>{typeof count === 'number' && <i>{count}</i>}{tag && <i>{tag}</i>}</span>
                <ChevronRight className={open ? 'is-open' : ''} size={15} />
            </button>
            {open && <div className="wf-http-accordion-panel">{children}</div>}
        </section>
    );
}

function HttpKeyValueTable({label, rows, onAdd, onUpdate, onRemove}) {
    return (
        <div className="wf-http-table" role="table" aria-label={`${label} key value table`}>
            <div className="wf-http-table-row is-heading" role="row">
                <span role="columnheader">key</span><span role="columnheader">value</span>
                <button type="button" className="wf-inline-icon-button" onClick={onAdd} title={`新增 ${label}`} aria-label={`新增 ${label}`}><Plus size={14} /></button>
            </div>
            <div role="rowgroup">
                {rows.map((row, index) => (
                    <div className="wf-http-table-row" role="row" key={row.id}>
                        <input role="cell" aria-label={`${label} key ${index + 1}`} value={row.key} onChange={(event) => onUpdate(row.id, {key: event.target.value})} />
                        <input role="cell" aria-label={`${label} value ${index + 1}`} value={row.value} onChange={(event) => onUpdate(row.id, {value: event.target.value})} />
                        <button type="button" className="wf-inline-icon-button is-danger" onClick={() => onRemove(row.id)} title={`删除 ${label}`} aria-label={`删除 ${label} ${index + 1}`}><Trash2 size={14} /></button>
                    </div>
                ))}
            </div>
        </div>
    );
}

function HttpToggle({label, checked, onChange}) {
    return (
        <label className="wf-http-toggle">
            <span>{label}</span>
            <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
            <i aria-hidden="true"><span /></i>
        </label>
    );
}

const Inspector = React.memo(function Inspector({
    node,
    providers,
    providerLoadState,
    providerLoadError,
    onRefreshProviders,
    onLoadVariables,
    initialTab = 'settings',
    onChange,
    onRun,
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
    const [bodyOpen, setBodyOpen] = useState(true);
    const [requestOptionsOpen, setRequestOptionsOpen] = useState(true);
    const [bodyMessage, setBodyMessage] = useState('');
    const [modelParametersText, setModelParametersText] = useState('');
    const [modelParametersError, setModelParametersError] = useState('');
    const [advancedOpen, setAdvancedOpen] = useState(false);
    const [llmContextOpen, setLlmContextOpen] = useState(true);
    const [variablesOpen, setVariablesOpen] = useState(false);
    const [variableGroups, setVariableGroups] = useState([]);
    const [variableLoadState, setVariableLoadState] = useState('idle');
    const [variableLoadError, setVariableLoadError] = useState('');
    const [editorScale, setEditorScale] = useState(1);
    const editorRndRef = useRef(null);
    const editorBaseSizeRef = useRef(null);
    const onLoadVariablesRef = useRef(onLoadVariables);
    const variableDeclarationRevision = JSON.stringify(node?.data.outputVariables || []);
    const temporaryOutputRevision = JSON.stringify(node?.data.temporaryRun?.outputs || {});
    useEffect(() => {
        onLoadVariablesRef.current = onLoadVariables;
    }, [onLoadVariables]);
    useEffect(() => {
        setTab(initialTab);
        setCurlPanelOpen(false);
        setCurlText('');
        setCurlError('');
        setHeadersOpen(true);
        setParamsOpen(true);
        setBodyOpen(true);
        setRequestOptionsOpen(true);
        setBodyMessage('');
        setSelectedParameterIndex(null);
        setModelParametersText(node?.data.modelParametersText ?? modelParametersEditorText(node?.data.modelParameters));
        setModelParametersError('');
        setAdvancedOpen(false);
        setLlmContextOpen(true);
        setVariablesOpen(false);
        setVariableGroups([]);
        setVariableLoadState('idle');
        setVariableLoadError('');
        editorBaseSizeRef.current = null;
        setEditorScale(1);
    }, [node?.id, initialTab]);
    useEffect(() => {
        if (!variablesOpen || !node) return undefined;
        let cancelled = false;
        const timer = window.setTimeout(async () => {
            setVariableLoadState('loading');
            setVariableLoadError('');
            try {
                const groups = await onLoadVariablesRef.current();
                if (cancelled) return;
                setVariableGroups(Array.isArray(groups) ? groups : []);
                setVariableLoadState('ready');
            } catch (error) {
                if (cancelled) return;
                setVariableGroups([]);
                setVariableLoadState('error');
                setVariableLoadError(error instanceof Error ? error.message : '变量加载失败');
            }
        }, 80);
        return () => {
            cancelled = true;
            window.clearTimeout(timer);
        };
    }, [node?.id, temporaryOutputRevision, variableDeclarationRevision, variablesOpen]);
    if (!node) return null;
    const meta = NODE_TYPES[node.data.nodeType] || NODE_TYPES.SCRIPT;
    const Icon = meta.icon;
    const isHttp = node.data.nodeType === 'HTTP';
    const isLlm = node.data.nodeType === 'LLM';
    const isScript = node.data.nodeType === 'SCRIPT';
    const isStart = node.data.nodeType === 'START';
    const isEnd = node.data.nodeType === 'END';
    const showCodeEditor = meta.executable && !isHttp && !isLlm;
    const showParametersTab = false;
    const showOutputVariables = meta.executable;
    const modelReference = modelReferenceStatus(
        providers,
        node.data.providerId || '',
        node.data.modelName || '',
    );
    const selectedModelProtocol = modelReference.provider?.protocol || 'OPENAI_COMPATIBLE';
    const protocolParametersError = isLlm && modelReference.state === 'valid'
        ? modelParametersProtocolError(selectedModelProtocol, node.data.modelParameters)
        : '';
    const llmMessages = isLlm ? cloneLlmMessages(node.data.llmMessages) : [];
    const llmErrors = llmMessageErrors(llmMessages);
    const llmRunReady = !isLlm || (
        modelReference.state === 'valid'
        && !modelParametersError
        && !protocolParametersError
        && llmErrors.size === 0
    );
    const llmSaveAllowed = true;
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
    const constrainEditorPosition = (ref, position) => {
        const parent = ref?.parentElement;
        if (!parent) return position;
        return clampInspectorPosition({
            x: position.x,
            y: position.y,
            width: ref.offsetWidth,
            height: ref.offsetHeight,
            parentWidth: parent.clientWidth,
            parentHeight: parent.clientHeight,
        });
    };
    const finishEditorResize = (event, direction, ref, _delta, position) => {
        updateEditorScale(event, direction, ref);
        editorRndRef.current?.updatePosition(
            constrainEditorPosition(ref, position),
        );
    };
    const finishEditorDrag = (_event, data) => {
        if (!data.node) return;
        editorRndRef.current?.updatePosition(
            constrainEditorPosition(data.node, {x: data.x, y: data.y}),
        );
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
    const startInputs = Array.isArray(node.data.startInputs) && node.data.startInputs.length
        ? node.data.startInputs
        : [emptyStartInput()];
    const updateLlmMessage = (id, content) => onChange({
        llmMessages: llmMessages.map((message) => message.id === id ? {...message, content} : message),
    });
    const addLlmMessage = () => onChange({
        llmMessages: llmMessages.concat({
            id: rowId(),
            role: nextLlmRole(llmMessages),
            content: '',
            fixed: false,
        }),
    });
    const removeLastLlmMessage = () => {
        if (llmMessages.length <= 2) return;
        onChange({llmMessages: llmMessages.slice(0, -1)});
    };
    const updateModelParameters = (text) => {
        setModelParametersText(text);
        if (!text.trim()) {
            setModelParametersError('');
            onChange({modelParameters: {}, modelParametersText: ''});
            return;
        }
        try {
            const parsed = JSON.parse(text);
            if (!isPlainObject(parsed)) throw new Error('高级参数必须是 JSON 对象');
            delete parsed.stream;
            setModelParametersError('');
            onChange({modelParameters: parsed, modelParametersText: text});
        } catch (error) {
            setModelParametersError(error instanceof SyntaxError ? '高级参数不是合法 JSON' : error.message);
            onChange({modelParametersText: text});
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
            updateModelParameters(JSON.stringify(parsed, null, 2));
        } catch (error) {
            setModelParametersError(error instanceof SyntaxError ? '高级参数不是合法 JSON' : error.message);
        }
    };
    const toggleVariables = () => setVariablesOpen((open) => !open);
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
    const updateStartInput = (id, patch) => onChange({
        startInputs: startInputs.map((row) => row.id === id ? {...row, ...patch} : row),
    });
    const addStartInput = () => onChange({startInputs: startInputs.concat(emptyStartInput())});
    const removeStartInput = (id) => {
        const remaining = startInputs.filter((row) => row.id !== id);
        onChange({startInputs: remaining.length ? remaining : [emptyStartInput()]});
    };
    const httpKeyValueSection = (label, collection, open, setOpen) => (
        <HttpAccordion title={label} count={httpConfig[collection].length} open={open} onToggle={() => setOpen((current) => !current)}>
            <HttpKeyValueTable
                label={label}
                rows={httpConfig[collection]}
                onAdd={() => addHttpRow(collection)}
                onUpdate={(id, patch) => updateHttpRow(collection, id, patch)}
                onRemove={(id) => removeHttpRow(collection, id)}
            />
        </HttpAccordion>
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
            const formatted = JSON.stringify(parseHttpJsonTemplate(httpConfig.bodyText), null, 2);
            updateHttpConfig({bodyText: formatted});
            setBodyMessage('');
        } catch (error) {
            setBodyMessage(`JSON 格式错误：${error instanceof Error ? error.message : '无法解析'}`);
        }
    };
    const bodyFieldRows = () => (
        <HttpKeyValueTable
            label="Body"
            rows={httpConfig.bodyFields}
            onAdd={() => addHttpRow('bodyFields')}
            onUpdate={(id, patch) => updateHttpRow('bodyFields', id, patch)}
            onRemove={(id) => removeHttpRow('bodyFields', id)}
        />
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
            ref={editorRndRef}
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
            onResizeStop={finishEditorResize}
            onDragStop={finishEditorDrag}
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
                        {node.data.nodeType !== 'END' && <button type="button" disabled={!llmRunReady || node.data.nodeTestActive} onClick={onRun} title={llmRunReady ? '运行' : '请选择有效模型、补全上下文并修正高级参数'} aria-label="运行当前节点"><Play size={15} /></button>}
                        <button type="button" disabled={!llmSaveAllowed} className={node.data.savedAt && !node.data.isDirty ? 'is-saved' : ''} onClick={onSave} title={llmSaveAllowed ? (node.data.savedAt && !node.data.isDirty ? `已保存 ${node.data.savedAt}` : '保存') : '请修正高级参数'} aria-label="保存当前节点"><Save size={15} /></button>
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
                    {!isEnd && <button type="button" className={tab === 'logs' ? 'is-active' : ''} onClick={() => setTab('logs')}>日志</button>}
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
                                    </div>
                                    <section className="wf-llm-context-section" aria-label="LLM 上下文">
                                        <button type="button" className="wf-llm-context-heading" aria-expanded={llmContextOpen} onClick={() => setLlmContextOpen((open) => !open)}>
                                            <div><MessageSquareText size={15} /><strong>上下文</strong></div>
                                            <span>{llmMessages.length} 条消息 <ChevronRight className={llmContextOpen ? 'is-open' : ''} size={15} /></span>
                                        </button>
                                        {llmContextOpen && (
                                            <div className="wf-llm-context-content">
                                                <div className="wf-llm-message-list">
                                                    {llmMessages.map((message, index) => {
                                                        const isLast = index === llmMessages.length - 1;
                                                        const error = llmErrors.get(message.id);
                                                        return (
                                                            <article className="wf-llm-message" key={message.id}>
                                                                <header>
                                                                    <div className="wf-llm-message-role">
                                                                        <strong>{message.role}</strong>
                                                                        <span title={LLM_MESSAGE_HINTS[message.role] || ''}><CircleHelp size={13} /></span>
                                                                    </div>
                                                                    <div className="wf-llm-message-tools">
                                                                        <span>{String(message.content || '').length} 字符</span>
                                                                        {!message.fixed && (
                                                                            <button type="button" disabled={!isLast} onClick={removeLastLlmMessage} title={isLast ? `删除 ${message.role} 消息` : '只能从最后一条消息开始删除'} aria-label={`删除 ${message.role} 消息`}><X size={14} /></button>
                                                                        )}
                                                                    </div>
                                                                </header>
                                                                <textarea
                                                                    aria-label={`${message.role} 消息内容`}
                                                                    aria-invalid={Boolean(error)}
                                                                    title={error || undefined}
                                                                    value={message.content || ''}
                                                                    placeholder={message.role === 'SYSTEM'
                                                                        ? '输入模型的角色、目标和约束；留空时执行请求不发送 SYSTEM'
                                                                        : message.role === 'ASSISTANT'
                                                                            ? '输入期望的示例回答'
                                                                            : '输入用户消息，支持直接引用 ${变量名}'}
                                                                    onChange={(event) => updateLlmMessage(message.id, event.target.value)}
                                                                />
                                                            </article>
                                                        );
                                                    })}
                                                </div>
                                                <button type="button" className="wf-llm-add-message" onClick={addLlmMessage}>
                                                    <Plus size={15} />
                                                    <strong>添加消息</strong>
                                                    <span>下一条 {nextLlmRole(llmMessages)}</span>
                                                </button>
                                            </div>
                                        )}
                                    </section>
                                    <section className="wf-llm-context-section" aria-label="LLM 高级参数">
                                        <button type="button" className="wf-llm-context-heading" aria-expanded={advancedOpen} onClick={() => setAdvancedOpen((open) => !open)}>
                                            <div><Settings2 size={15} /><strong>高级参数</strong></div>
                                            <span>JSON <ChevronRight className={advancedOpen ? 'is-open' : ''} size={15} /></span>
                                        </button>
                                        {(advancedOpen || modelParametersError) && (
                                            <div className="wf-llm-json-editor">
                                                <div className="wf-llm-json-toolbar">
                                                    <span>JSON</span>
                                                    <button type="button" onClick={beautifyModelParameters} title="格式化模型高级参数 JSON" aria-label="格式化模型高级参数 JSON"><WandSparkles size={13} />Beautify</button>
                                                </div>
                                                <textarea aria-label="模型高级参数 JSON" spellCheck="false" value={modelParametersText} placeholder={llmParametersReference(selectedModelProtocol)} onChange={(event) => updateModelParameters(event.target.value)} />
                                            </div>
                                        )}
                                        {(modelParametersError || protocolParametersError) && <span className="wf-model-parameters-error" role="alert">{modelParametersError || protocolParametersError}</span>}
                                    </section>
                                </section>
                            )}
                            {isStart && (
                                <section className="wf-config-section wf-editor-full-row">
                                    <div className="wf-config-title"><Variable size={15} /><strong>START 输入</strong></div>
                                    <div className="wf-config-panel wf-output-variable-list">
                                        {startInputs.map((row, index) => (
                                            <div className="wf-output-variable-row wf-start-input-row" key={row.id}>
                                                <label><span>变量名</span><input aria-label={`START 变量名 ${index + 1}`} value={row.name} onChange={(event) => updateStartInput(row.id, {name: event.target.value})} /></label>
                                                <label><span>类型</span><select aria-label={`START 变量类型 ${index + 1}`} value={row.type} onChange={(event) => updateStartInput(row.id, {type: event.target.value})}>{OUTPUT_VARIABLE_TYPES.map((type) => <option value={type} key={type}>{type}</option>)}</select></label>
                                                <label><span>值</span><input aria-label={`START 变量值 ${index + 1}`} value={row.value} onChange={(event) => updateStartInput(row.id, {value: event.target.value})} placeholder={row.type === 'string' ? '输入文本' : '输入 JSON 值'} /></label>
                                                {index === 0 ? (
                                                    <button type="button" className="wf-inline-icon-button" onClick={addStartInput} title="添加 START 输入" aria-label="添加 START 输入"><Plus size={15} /></button>
                                                ) : (
                                                    <button type="button" className="wf-inline-icon-button is-danger" onClick={() => removeStartInput(row.id)} title="删除 START 输入" aria-label={`删除 START 输入 ${index + 1}`}><Trash2 size={15} /></button>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                </section>
                            )}
                            {isHttp && (
                                <section className="wf-http-request-section wf-editor-full-row">
                                    <div className="wf-http-request-title"><Globe2 size={15} /><strong>请求设置</strong></div>
                                    <div className="wf-http-endpoint-row">
                                        <strong>Endpoint</strong>
                                        <HttpMethodSelector value={httpConfig.method} onChange={(method) => updateHttpConfig({method})} />
                                        <input
                                            aria-label="请求 URL"
                                            value={httpConfig.url}
                                            onChange={(event) => updateHttpConfig({url: event.target.value})}
                                            onBlur={(event) => updateHttpConfig({url: event.currentTarget.value.trim()})}
                                            placeholder="https://"
                                        />
                                        <button type="button" className="wf-http-import-button" title="导入 cURL" aria-label="导入 cURL" aria-expanded={curlPanelOpen} onClick={() => {setCurlPanelOpen((open) => !open); setCurlError('');}}><Upload size={15} /></button>
                                    </div>
                                    {curlPanelOpen && (
                                        <div className="wf-curl-import-panel">
                                            <textarea aria-label="cURL 命令" value={curlText} onChange={(event) => {setCurlText(event.target.value); setCurlError('');}} spellCheck="false" placeholder="curl https://api.example.com" />
                                            <div className="wf-curl-import-actions">
                                                {curlError && <span role="alert">{curlError}</span>}
                                                <button type="button" onClick={() => setCurlPanelOpen(false)}><X size={14} />取消</button>
                                                <button type="button" className="is-primary" onClick={applyCurlImport}><Check size={14} />应用</button>
                                            </div>
                                        </div>
                                    )}
                                    <div className="wf-http-request-groups">
                                        {httpKeyValueSection('Headers', 'headers', headersOpen, setHeadersOpen)}
                                        {httpKeyValueSection('Params', 'params', paramsOpen, setParamsOpen)}
                                        <HttpAccordion title="Body" tag={httpConfig.bodyType} open={bodyOpen} onToggle={() => setBodyOpen((open) => !open)}>
                                            <div className="wf-http-body-panel">
                                            <div className="wf-http-body-types" role="radiogroup" aria-label="Body 类型">
                                                {HTTP_BODY_TYPES.map((type) => (
                                                    <label key={type}>
                                                        <input type="radio" name={`http-body-${node.id}`} value={type} checked={httpConfig.bodyType === type} onChange={() => {updateHttpConfig({bodyType: type}); setBodyMessage('');}} />
                                                        <i />
                                                        <span>{type}</span>
                                                    </label>
                                                ))}
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
                                                {httpConfig.bodyType === 'none' && <div className="wf-http-body-empty">No request body</div>}
                                            </div>
                                        </HttpAccordion>
                                        <HttpAccordion title="Request Options" open={requestOptionsOpen} onToggle={() => setRequestOptionsOpen((open) => !open)} isLast>
                                            <div className="wf-http-request-options">
                                                <div className="wf-http-option-fields">
                                                    <label><span>Proxy</span><select aria-label="Proxy 模式" value={httpConfig.proxyMode} onChange={(event) => updateHttpConfig({proxyMode: event.target.value})}><option value="SYSTEM">SYSTEM</option><option value="DIRECT">DIRECT</option><option value="CUSTOM">CUSTOM</option></select></label>
                                                    <label><span>Response Body</span><select aria-label="响应 Body 类型" value={httpConfig.responseBodyType} onChange={(event) => updateHttpConfig({responseBodyType: event.target.value})}><option value="auto">AUTO</option><option value="json">JSON</option><option value="text">TEXT</option><option value="binary">BINARY</option></select></label>
                                                </div>
                                                {httpConfig.proxyMode === 'CUSTOM' && (
                                                    <div className="wf-http-custom-proxy">
                                                        <label className="is-url"><span>Proxy URL</span><input aria-label="Proxy URL" value={httpConfig.proxyUrl} onChange={(event) => updateHttpConfig({proxyUrl: event.target.value})} placeholder="http://proxy.example.com:8080" /></label>
                                                        <label><span>Username</span><input aria-label="Proxy 用户名" value={httpConfig.proxyUsername} onChange={(event) => updateHttpConfig({proxyUsername: event.target.value})} /></label>
                                                        <label><span>Password</span><input aria-label="Proxy 密码" type="password" value={httpConfig.proxyPassword} onChange={(event) => updateHttpConfig({proxyPassword: event.target.value})} /></label>
                                                    </div>
                                                )}
                                                <div className="wf-http-toggle-row">
                                                    <HttpToggle label="Redirects" checked={httpConfig.followRedirects} onChange={(followRedirects) => updateHttpConfig({followRedirects})} />
                                                    <HttpToggle label="SSL Verify" checked={httpConfig.verifySsl} onChange={(verifySsl) => updateHttpConfig({verifySsl})} />
                                                </div>
                                            </div>
                                        </HttpAccordion>
                                    </div>
                                </section>
                            )}
                            {showCodeEditor && (
                                <section className="wf-embedded-code-editor wf-editor-full-row">
                                    <div className="wf-code-meta"><span>main.py</span><span>Python</span></div>
                                    <PythonCodeEditor
                                        value={node.data.mainPy ?? DEFAULT_SCRIPT_MAIN_PY}
                                        onChange={(mainPy) => onChange({mainPy})}
                                    />
                                </section>
                            )}
                            {meta.executable && <section className="wf-config-section wf-editor-full-row">
                                <div className="wf-config-title"><Settings2 size={15} /><strong>运行配置</strong></div>
                                {meta.executable && <button type="button" aria-expanded={retryOpen} onClick={() => setRetryOpen((open) => !open)}><span>超时与重试</span><ChevronRight className={retryOpen ? 'is-open' : ''} size={15} /></button>}
                                {meta.executable && retryOpen && (
                                    <div className="wf-config-panel wf-retry-grid">
                                        <label><span>单次超时（秒）</span><input type="number" min="0.001" step="0.1" value={node.data.timeoutSeconds ?? 600} onChange={(event) => onChange({timeoutSeconds: Number(event.target.value)})} /></label>
                                        <label><span>最大重试次数</span><input type="number" min="0" max="10" step="1" value={node.data.retryCount ?? 0} onChange={(event) => onChange({retryCount: Number(event.target.value)})} /></label>
                                        <label><span>重试间隔（秒）</span><input type="number" min="0" max="600" step="0.1" value={node.data.retryIntervalSeconds ?? 0} onChange={(event) => onChange({retryIntervalSeconds: Number(event.target.value)})} /></label>
                                        <label><span>延迟执行（秒）</span><input type="number" min="0" max="600" step="0.1" value={node.data.delaySeconds ?? 0} onChange={(event) => onChange({delaySeconds: Number(event.target.value)})} /></label>
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
                                                        <label><span>{isScript ? 'Python 变量' : '提取表达式'}</span><input aria-label={`输出变量来源 ${index + 1}`} value={row.value || ''} onChange={(event) => updateOutputVariable(row.id, {value: event.target.value})} /></label>
                                                        <label><span>类型</span><select aria-label={`输出变量类型 ${index + 1}`} value={row.type || 'string'} onChange={(event) => updateOutputVariable(row.id, {type: event.target.value})}>{OUTPUT_VARIABLE_TYPES.map((type) => <option value={type} key={type}>{type}</option>)}</select></label>
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
                            </section>}
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
                        <NodeRunHistory runs={node.data.runHistory || []} nodeType={node.data.nodeType} temporaryRun={node.data.temporaryRun || null} />
                    </div>
                )}
              </aside>
            </div>
        </Rnd>
    );
});

function WorkflowStudio({options}) {
    const theme = useDocumentTheme();
    const graph = useMemo(() => graphFromDraft(options.draft), [options.draft]);
    const [nodes, setNodes, onNodesChange] = useNodesState(graph.nodes);
    const [edges, setEdges, onEdgesChange] = useEdgesState(graph.edges);
    const [selectedNodeIds, setSelectedNodeIds] = useState([]);
    const [selectedEdgeIds, setSelectedEdgeIds] = useState([]);
    const [editorNodeId, setEditorNodeId] = useState(null);
    const [editorInitialTab, setEditorInitialTab] = useState('settings');
    const [contextMenu, setContextMenu] = useState(null);
    const [insertEdgeId, setInsertEdgeId] = useState(null);
    const [clipboard, setClipboard] = useState(null);
    const [marquee, setMarquee] = useState(null);
    const [alignmentGuides, setAlignmentGuides] = useState(null);
    const [nodeSaveNotice, setNodeSaveNotice] = useState(null);
    const [historyOpen, setHistoryOpen] = useState(false);
    const [workflowHistory, setWorkflowHistory] = useState([]);
    const [historyLoadState, setHistoryLoadState] = useState('idle');
    const [expandedWorkflowExecutionId, setExpandedWorkflowExecutionId] = useState(null);
    const [historyNodeExecutions, setHistoryNodeExecutions] = useState({});
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
        name: options.name || '未命名工作流',
        description: String(options.description ?? options.draft?.description ?? ''),
    });
    const metadataDraft = useRef({...savedMetadata.current});
    const pasteSequence = useRef(0);
    const marqueeRef = useRef(null);
    const initialLayoutDone = useRef(false);
    const undoStack = useRef([]);
    const redoStack = useRef([]);
    const providerLoadSequence = useRef(0);
    const [historyTick, setHistoryTick] = useState(0);
    const [workflowRunState, setWorkflowRunState] = useState('IDLE');
    const [workflowElapsedMs, setWorkflowElapsedMs] = useState(0);
    const [nodeTestDialog, setNodeTestDialog] = useState(null);
    const workflowRunRef = useRef({active: false, interruptRequested: false, startedAtMs: 0, runId: null});
    const workflowElapsedTimer = useRef(null);
    const nodeTestWorkflowIdRef = useRef(options.id || window.crypto.randomUUID());
    const nodeTestSourcesRef = useRef(new Map());
    const nodeTestTimersRef = useRef(new Map());
    const hiddenNodeTestsRef = useRef(new Set());
    const studioClosedRef = useRef(false);
    const canvasRef = useRef(null);
    const {screenToFlowPosition, fitView, getNodes} = useReactFlow();

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
        const name = String(metadata?.name ?? workflowName);
        const description = String(metadata?.description ?? workflowDescription);
        if (!name.trim()) throw new Error('Workflow 名称不能为空');
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
                forNodeRun,
            });
            workflowIdRef.current = saved.id;
            nodeTestWorkflowIdRef.current = saved.id;
            setWorkflowId(saved.id);
            savedMetadata.current = {
                name: saved.name ?? name,
                description: saved.description ?? description,
            };
            metadataDraft.current = {...savedMetadata.current};
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
    }, [edges, nodes, options, setNodes, workflowDescription, workflowName]);

    const persistMetadata = useCallback(async (nextName, nextDescription) => {
        const name = String(nextName);
        const description = String(nextDescription);
        if (!name.trim()) {
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
                metadataDraft.current = {...savedMetadata.current};
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

    const commitWorkflowName = useCallback(async (nextName = workflowName) => {
        if (nameEditCancelled.current) {
            nameEditCancelled.current = false;
            metadataDraft.current.name = savedMetadata.current.name;
            setWorkflowName(savedMetadata.current.name);
            setNameEditing(false);
            return;
        }
        if (!nextName.trim()) {
            setWorkflowName(savedMetadata.current.name);
            setNameEditing(false);
            if (window.showToast) window.showToast('Workflow 名称不能为空', 'error');
            return;
        }
        if (await persistMetadata(nextName, workflowDescription)) setNameEditing(false);
    }, [persistMetadata, workflowDescription, workflowName]);

    const commitWorkflowDescription = useCallback(async (nextDescription = workflowDescription) => {
        if (descriptionEditCancelled.current) {
            descriptionEditCancelled.current = false;
            metadataDraft.current.description = savedMetadata.current.description;
            setWorkflowDescription(savedMetadata.current.description);
            setDescriptionEditing(false);
            return;
        }
        if (await persistMetadata(workflowName, nextDescription)) setDescriptionEditing(false);
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

    const onNodesChangeSafe = useCallback((changes) => {
        if (changes.some((change) => change.type === 'remove')) recordHistory();
        onNodesChange(changes);
    }, [onNodesChange, recordHistory]);

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

    const stopNodeTestTimer = useCallback((nodeId) => {
        const timer = nodeTestTimersRef.current.get(nodeId);
        if (timer !== undefined) window.clearInterval(timer);
        nodeTestTimersRef.current.delete(nodeId);
    }, []);

    const resetNodeTestDisplay = useCallback((nodeId) => {
        stopNodeTestTimer(nodeId);
        setNodes((current) => current.map((node) => {
            if (node.id !== nodeId) return node;
            const latest = node.data.runHistory?.[0] || null;
            return {
                ...node,
                data: {
                    ...node.data,
                    temporaryRun: null,
                    nodeTestActive: false,
                    nodeTestId: null,
                    nodeTestStartedAt: null,
                    status: latest?.status || 'PENDING',
                    executionDurationMs: latest?.duration_ms || 0,
                },
            };
        }));
    }, [setNodes, stopNodeTestTimer]);

    const applyNodeTestSnapshot = useCallback((nodeId, testId, snapshot, terminal = false) => {
        if (hiddenNodeTestsRef.current.has(nodeId)) {
            if (terminal) {
                hiddenNodeTestsRef.current.delete(nodeId);
                resetNodeTestDisplay(nodeId);
            }
            return;
        }
        const run = nodeExecutionHistoryRun({
            ...snapshot,
            test_id: `temporary-${testId}`,
            isTemporary: true,
        });
        setNodes((current) => current.map((node) => node.id === nodeId ? {
            ...node,
            data: {
                ...node.data,
                temporaryRun: run,
                nodeTestActive: !terminal,
                nodeTestId: terminal ? null : testId,
                status: snapshot.status || (terminal ? 'FAILED' : 'RUNNING'),
                executionDurationMs: snapshot.duration_ms ?? node.data.executionDurationMs ?? 0,
            },
        } : node));
        if (terminal) stopNodeTestTimer(nodeId);
    }, [resetNodeTestDisplay, setNodes, stopNodeTestTimer]);

    const startNodeTest = useCallback(async (nodeId, context) => {
        const node = nodes.find((item) => item.id === nodeId);
        if (!node || node.data.nodeType === 'END' || node.data.nodeTestActive) return;
        if (typeof options.serializeNode !== 'function') {
            if (window.showToast) window.showToast('节点序列化入口不可用', 'error');
            return;
        }
        hiddenNodeTestsRef.current.delete(nodeId);
        const transientWorkflowId = workflowIdRef.current || nodeTestWorkflowIdRef.current;
        const startedAt = Date.now();
        setNodes((current) => current.map((item) => item.id === nodeId ? {
            ...item,
            data: {
                ...item.data,
                status: 'RUNNING',
                executionDurationMs: 0,
                nodeTestActive: true,
                nodeTestStartedAt: startedAt,
                temporaryRun: nodeExecutionHistoryRun({
                    test_id: `temporary-pending-${nodeId}`,
                    node_id: nodeId,
                    type: item.data.nodeType,
                    status: 'RUNNING',
                    started_at: new Date().toISOString(),
                    finished_at: null,
                    duration_ms: 0,
                    attempt_count: 0,
                    inputs: context,
                    outputs: {},
                    error: null,
                    isTemporary: true,
                }),
            },
        } : item));
        stopNodeTestTimer(nodeId);
        nodeTestTimersRef.current.set(nodeId, window.setInterval(() => {
            setNodes((current) => current.map((item) => (
                item.id === nodeId && item.data.nodeTestActive
                    ? {...item, data: {...item.data, executionDurationMs: Date.now() - startedAt}}
                    : item
            )));
        }, 100));
        try {
            const response = await fetch(`/api/workflows/${encodeURIComponent(transientWorkflowId)}/node-tests`, {
                method: 'POST',
                headers: {'content-type': 'application/json', accept: 'application/json'},
                body: JSON.stringify({node: options.serializeNode(serializableNode(node)), context}),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) {
                const detail = Array.isArray(payload.detail)
                    ? payload.detail.map((item) => item.msg || String(item)).join('；')
                    : payload.detail;
                throw new Error(detail || `HTTP ${response.status}`);
            }
            const testId = payload.test_id;
            applyNodeTestSnapshot(nodeId, testId, payload.snapshot, false);
            setNodes((current) => current.map((item) => item.id === nodeId ? {
                ...item, data: {...item.data, nodeTestStartedAt: startedAt},
            } : item));
            const source = new EventSource(`/api/workflows/${encodeURIComponent(transientWorkflowId)}/node-tests/${encodeURIComponent(testId)}/events`);
            nodeTestSourcesRef.current.set(nodeId, {source, testId, workflowId: transientWorkflowId});
            const readEvent = (event, terminal) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.snapshot) {
                        applyNodeTestSnapshot(nodeId, testId, data.snapshot, terminal);
                        if (terminal && data.snapshot.status === 'FAILED' && window.showToast) {
                            window.showToast(friendlyNodeError(data.snapshot.error, '节点临时测试失败'), 'error');
                        }
                    }
                } catch (_error) {
                    if (terminal) applyNodeTestSnapshot(nodeId, testId, {
                        node_id: nodeId,
                        type: node.data.nodeType,
                        status: 'FAILED',
                        started_at: new Date(startedAt).toISOString(),
                        finished_at: new Date().toISOString(),
                        duration_ms: Date.now() - startedAt,
                        attempt_count: 0,
                        inputs: context,
                        outputs: {},
                        error: {code: 'NODE_TEST_STREAM_ERROR', message: '临时测试终态无法解析', details: null},
                    }, true);
                }
                if (terminal) {
                    source.close();
                    nodeTestSourcesRef.current.delete(nodeId);
                }
            };
            source.addEventListener('snapshot', (event) => readEvent(event, false));
            source.addEventListener('complete', (event) => readEvent(event, true));
            source.addEventListener('interrupted', (event) => readEvent(event, true));
            source.onerror = () => {
                if (source.readyState !== EventSource.CLOSED) return;
                source.close();
                nodeTestSourcesRef.current.delete(nodeId);
            };
        } catch (error) {
            stopNodeTestTimer(nodeId);
            applyNodeTestSnapshot(nodeId, `failed-${nodeId}`, {
                node_id: nodeId,
                type: node.data.nodeType,
                status: 'FAILED',
                started_at: new Date(startedAt).toISOString(),
                finished_at: new Date().toISOString(),
                duration_ms: Date.now() - startedAt,
                attempt_count: 0,
                inputs: context,
                outputs: {},
                error: {code: 'NODE_TEST_REQUEST_FAILED', message: error instanceof Error ? error.message : '节点临时测试启动失败', details: null},
            }, true);
            if (window.showToast) window.showToast(error instanceof Error ? error.message : '节点临时测试启动失败', 'error');
        }
    }, [applyNodeTestSnapshot, nodes, options, setNodes, stopNodeTestTimer]);

    const requestNodeTest = useCallback((nodeId) => {
        const node = nodes.find((item) => item.id === nodeId);
        if (!node || node.data.nodeType === 'END' || node.data.nodeTestActive) return;
        closeMenus();
        if (node.data.nodeType === 'START') {
            void startNodeTest(nodeId, {});
            return;
        }
        const start = nodes.find((item) => item.data.nodeType === 'START');
        const rows = (start?.data.startInputs || []).filter((row) => row.name).map((row) => ({
            id: rowId(),
            name: row.name,
            type: row.type || 'string',
            valueText: nodeTestValueText(row.value, row.type || 'string'),
        }));
        setNodeTestDialog({nodeId, nodeLabel: node.data.label, rows});
    }, [closeMenus, nodes, startNodeTest]);

    const submitNodeTestDialog = useCallback(() => {
        if (!nodeTestDialog) return;
        try {
            const context = {};
            nodeTestDialog.rows.forEach((row) => {
                if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(row.name)) {
                    throw new Error('临时测试变量名格式无效');
                }
                if (Object.prototype.hasOwnProperty.call(context, row.name)) {
                    throw new Error(`临时测试变量名重复: ${row.name}`);
                }
                context[row.name] = parseNodeTestValue(row);
            });
            const nodeId = nodeTestDialog.nodeId;
            setNodeTestDialog(null);
            void startNodeTest(nodeId, context);
        } catch (error) {
            if (window.showToast) window.showToast(error instanceof Error ? error.message : '临时测试变量无效', 'error');
        }
    }, [nodeTestDialog, startNodeTest]);

    const interruptNodeTest = useCallback(async (nodeId) => {
        const active = nodeTestSourcesRef.current.get(nodeId);
        if (!active) return false;
        try {
            const response = await fetch(`/api/workflows/${encodeURIComponent(active.workflowId)}/node-tests/${encodeURIComponent(active.testId)}/cancel`, {
                method: 'POST', headers: {accept: 'application/json'},
            });
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(payload.detail || `HTTP ${response.status}`);
            }
            return true;
        } catch (error) {
            if (window.showToast) window.showToast(error instanceof Error ? error.message : '节点临时测试中断失败', 'error');
            return false;
        }
    }, []);

    const loadNodeRuns = useCallback(async (id, activeWorkflowId = workflowId) => {
        if (!activeWorkflowId) return [];
        try {
            const runResponse = await fetch(`/api/workflows/${encodeURIComponent(activeWorkflowId)}/runs`, {
                headers: {accept: 'application/json'},
            });
            const runPayload = await runResponse.json().catch(() => ({}));
            if (!runResponse.ok) throw new Error(runPayload.detail || `HTTP ${runResponse.status}`);
            const executions = Array.isArray(runPayload.executions) ? runPayload.executions : [];
            if (!executions.length) return [];
            const nodePayloads = await Promise.all(executions.map(async (execution) => {
                const response = await fetch(`/api/workflows/${encodeURIComponent(activeWorkflowId)}/runs/${encodeURIComponent(execution.id)}/nodes`, {headers: {accept: 'application/json'}});
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
                return payload.executions || [];
            }));
            const runs = nodePayloads.flatMap((items) => items.filter((execution) => execution.node_id === id).map(nodeExecutionHistoryRun)).slice(0, 10);
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

    const loadLatestWorkflowNodeExecutions = useCallback(async () => {
        if (!workflowIdRef.current) return [];
        const runsResponse = await fetch(
            `/api/workflows/${encodeURIComponent(workflowIdRef.current)}/runs`,
            {headers: {accept: 'application/json'}, cache: 'no-store'},
        );
        const runsPayload = await runsResponse.json().catch(() => ({}));
        if (!runsResponse.ok) throw new Error(runsPayload.detail || `HTTP ${runsResponse.status}`);
        const latestWorkflowExecution = Array.isArray(runsPayload.executions)
            ? runsPayload.executions[0]
            : null;
        if (!latestWorkflowExecution) return [];
        const nodesResponse = await fetch(
            `/api/workflows/${encodeURIComponent(workflowIdRef.current)}/runs/${encodeURIComponent(latestWorkflowExecution.id)}/nodes`,
            {headers: {accept: 'application/json'}, cache: 'no-store'},
        );
        const nodesPayload = await nodesResponse.json().catch(() => ({}));
        if (!nodesResponse.ok) throw new Error(nodesPayload.detail || `HTTP ${nodesResponse.status}`);
        return Array.isArray(nodesPayload.executions) ? nodesPayload.executions : [];
    }, []);

    const loadNodeVariables = useCallback(async (id) => {
        const visible = variableScopeNodes(nodes, edges, id);
        const latestNodeExecutions = await loadLatestWorkflowNodeExecutions();
        const executionByNodeId = new Map(
            latestNodeExecutions.map((execution) => [execution.node_id, execution]),
        );
        const groups = [];
        const start = nodes.find((node) => node.data.nodeType === 'START');
        if (start) groups.push({id: 'start-inputs', label: 'START', variables: (start.data.startInputs || []).filter((row) => row.name).map((row) => ({name: row.name, value: row.value, available: true}))});
        visible.forEach((node) => {
            const latestExecution = executionByNodeId.get(node.id);
            const temporaryOutputs = isPlainObject(node.data.temporaryRun?.outputs)
                ? node.data.temporaryRun.outputs
                : null;
            const persistedOutputs = isPlainObject(latestExecution?.outputs)
                ? latestExecution.outputs
                : {};
            const executionOutputs = temporaryOutputs || persistedOutputs;
            const variables = (node.data.outputVariables || []).filter((row) => row.name).map((row) => {
                const available = Object.prototype.hasOwnProperty.call(executionOutputs, row.name);
                return {
                    name: row.name,
                    value: available ? executionOutputs[row.name] : null,
                    path: row.value || null,
                    available,
                };
            });
            if (variables.length) groups.push({id: node.id, label: node.data.label || node.data.nodeType, variables});
        });
        return groups;
    }, [edges, loadLatestWorkflowNodeExecutions, nodes]);

    useEffect(() => {
        const targetNode = nodes.find((node) => node.id === editorNodeId);
        if (options.executionEnabled && ['START', 'HTTP', 'LLM', 'SCRIPT'].includes(targetNode?.data.nodeType) && workflowId) {
            loadNodeRuns(targetNode.id);
        }
    }, [editorNodeId, loadNodeRuns, options.executionEnabled, workflowId]);

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
            const historyRun = nodeExecutionHistoryRun(run);
            return {...node, data: {...node.data, status: run.status, executionDurationMs: workflowNodeExecutionDuration(run, node.data.executionDurationMs), executionId: run.status === 'RUNNING' ? run.node_execution_id : null, runHistory: [historyRun].concat((node.data.runHistory || []).filter((item) => item.id !== run.node_execution_id)).slice(0, 10)}};
        }));
    }, [setNodes]);

    const loadWorkflowHistory = useCallback(async () => {
        if (!workflowIdRef.current) return [];
        setHistoryLoadState('loading');
        try {
            const response = await fetch(`/api/workflows/${encodeURIComponent(workflowIdRef.current)}/runs`, {headers: {accept: 'application/json'}});
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
            const executions = Array.isArray(payload.executions) ? payload.executions.slice(0, 10) : [];
            setWorkflowHistory(executions);
            setHistoryLoadState('ready');
            return executions;
        } catch (error) {
            setHistoryLoadState('error');
            if (window.showToast) window.showToast(error instanceof Error ? error.message : '执行历史加载失败', 'error');
            return [];
        }
    }, []);

    const toggleWorkflowExecution = useCallback(async (executionId) => {
        if (expandedWorkflowExecutionId === executionId) {
            setExpandedWorkflowExecutionId(null);
            return;
        }
        setExpandedWorkflowExecutionId(executionId);
        if (historyNodeExecutions[executionId] || !workflowIdRef.current) return;
        try {
            const response = await fetch(`/api/workflows/${encodeURIComponent(workflowIdRef.current)}/runs/${encodeURIComponent(executionId)}/nodes`, {headers: {accept: 'application/json'}});
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
            const visibleExecutions = Array.isArray(payload.executions)
                ? payload.executions.filter((execution) => execution.type !== 'END')
                : [];
            setHistoryNodeExecutions((current) => ({...current, [executionId]: visibleExecutions}));
        } catch (error) {
            if (window.showToast) window.showToast(error instanceof Error ? error.message : '节点执行记录加载失败', 'error');
        }
    }, [expandedWorkflowExecutionId, historyNodeExecutions]);

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
        if (!options.executionEnabled) {
            if (window.showToast) window.showToast('Workflow 执行接口尚未接入', 'error');
            return;
        }
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
            workflowState.runId = startedPayload.execution.id;
            let run = startedPayload.execution;
            let pollDelayMs = 250;
            while (!['SUCCESS', 'FAILED', 'INTERRUPTED'].includes(run.status)) {
                await new Promise((resolve) => window.setTimeout(resolve, pollDelayMs));
                if (studioClosedRef.current) return;
                const [runResponse, nodesResponse] = await Promise.all([
                    fetch(`/api/workflows/${encodeURIComponent(activeWorkflowId)}/runs/${encodeURIComponent(workflowState.runId)}`, {headers: {accept: 'application/json'}}),
                    fetch(`/api/workflows/${encodeURIComponent(activeWorkflowId)}/runs/${encodeURIComponent(workflowState.runId)}/nodes`, {headers: {accept: 'application/json'}}),
                ]);
                const runPayload = await runResponse.json().catch(() => ({}));
                const nodesPayload = await nodesResponse.json().catch(() => ({}));
                if (!runResponse.ok) throw new Error(runPayload.detail || `HTTP ${runResponse.status}`);
                run = runPayload.execution;
                if (nodesResponse.ok) applyWorkflowNodeRuns(nodesPayload.executions || []);
                pollDelayMs = Math.min(2000, Math.round(pollDelayMs * 1.5));
            }
            let finalNodeExecutions = [];
            const finalNodesResponse = await fetch(`/api/workflows/${encodeURIComponent(activeWorkflowId)}/runs/${encodeURIComponent(workflowState.runId)}/nodes`, {headers: {accept: 'application/json'}});
            if (finalNodesResponse.ok) {
                const finalNodesPayload = await finalNodesResponse.json().catch(() => ({}));
                finalNodeExecutions = finalNodesPayload.executions || [];
                applyWorkflowNodeRuns(finalNodeExecutions);
            }
            setWorkflowRunState(run.status);
            setWorkflowElapsedMs(Date.now() - workflowState.startedAtMs);
            const failedNode = finalNodeExecutions.find((execution) => execution.status === 'FAILED' || execution.status === 'TIMEOUT');
            const resultMessage = run.status === 'SUCCESS'
                ? 'Workflow 执行完成'
                : run.status === 'INTERRUPTED'
                    ? 'Workflow 已中断'
                    : friendlyNodeError(failedNode?.error || run.error, 'Workflow 执行失败');
            if (window.showToast) window.showToast(resultMessage, run.status === 'SUCCESS' ? 'success' : 'error');
            await loadWorkflowHistory();
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
    }, [applyWorkflowNodeRuns, closeMenus, edges, loadWorkflowHistory, nodes, options.executionEnabled, persistDraft, setNodes]);

    const deleteElements = useCallback((nodeIds = [], edgeIds = []) => {
        const nodeIdSet = new Set(nodeIds);
        const edgeIdSet = new Set(edgeIds);
        if (!nodeIdSet.size && !edgeIdSet.size) return;
        nodeIds.forEach((nodeId) => {
            const active = nodeTestSourcesRef.current.get(nodeId);
            if (active) void interruptNodeTest(nodeId);
        });
        recordHistory();
        setNodes((current) => current.filter((node) => !nodeIdSet.has(node.id)));
        setEdges((current) => current.filter((edge) => (
            !edgeIdSet.has(edge.id) && !nodeIdSet.has(edge.source) && !nodeIdSet.has(edge.target)
        )));
        setEditorNodeId((current) => nodeIdSet.has(current) ? null : current);
        setSelectedNodeIds((current) => current.filter((id) => !nodeIdSet.has(id)));
        setSelectedEdgeIds((current) => current.filter((id) => !edgeIdSet.has(id)));
        closeMenus();
    }, [closeMenus, interruptNodeTest, recordHistory, setEdges, setNodes]);

    const deleteNodes = useCallback((ids) => deleteElements(ids, []), [deleteElements]);
    const deleteEdges = useCallback((ids) => deleteElements([], ids), [deleteElements]);

    const deleteNode = useCallback((id) => deleteNodes([id]), [deleteNodes]);

    const replaceNode = useCallback((id, targetType) => {
        const currentNode = nodes.find((node) => node.id === id);
        if (!currentNode || !INSERTABLE_TYPES.includes(currentNode.data.nodeType)) return;
        if (workflowRunRef.current.active || currentNode.data.nodeTestActive) {
            if (window.showToast) window.showToast('节点运行期间不能更换类型', 'error');
            return;
        }
        const replacement = replaceCanvasNode(nodes, edges, id, targetType);
        if (!replacement) return;
        recordHistory();
        stopNodeTestTimer(id);
        nodeTestSourcesRef.current.delete(id);
        hiddenNodeTestsRef.current.delete(id);
        setNodes(replacement.nodes);
        setEdges(replacement.edges);
        setEditorNodeId((current) => current === id ? null : current);
        setSelectedNodeIds((current) => current.map((nodeId) => nodeId === id ? replacement.newNodeId : nodeId));
        setSaveState('未保存');
        closeMenus();
        if (window.showToast) window.showToast(`节点已更换为 ${targetType}`, 'success');
    }, [closeMenus, edges, nodes, recordHistory, setEdges, setNodes, stopNodeTestTimer]);

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
            onConfigure: () => {
                setEditorInitialTab('settings');
                setEditorNodeId(node.id);
            },
            onRun: () => requestNodeTest(node.id),
            onOpenLogs: () => {
                setEditorInitialTab('logs');
                setEditorNodeId(node.id);
            },
        },
    })), [nodes, requestNodeTest]);

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
        if (action === 'run-node' && contextMenu?.nodeId) requestNodeTest(contextMenu.nodeId);
        if (action === 'copy-node' && contextMenu?.nodeId) copyNode(contextMenu.nodeId);
        if (action === 'delete-node' && contextMenu?.nodeId) deleteNode(contextMenu.nodeId);
        if (action === 'delete-edge' && contextMenu?.edgeId) deleteEdges([contextMenu.edgeId]);
        if (action !== 'paste-node') setContextMenu(null);
    }, [contextMenu, copyNode, deleteEdges, deleteNode, interruptWorkflow, pasteNode, requestNodeTest, runAll]);

    const autoLayout = useCallback(() => {
        recordHistory();
        setNodes((current) => layoutGraph(current, edges));
        window.setTimeout(() => fitView({padding: 0.16, duration: 450}), 0);
    }, [edges, fitView, recordHistory, setNodes]);

    const fitInitialOverview = useCallback(async () => {
        await fitView({padding: 0.16, duration: 0});
    }, [fitView]);

    useEffect(() => {
        if (initialLayoutDone.current) return;
        initialLayoutDone.current = true;
        if (!options.draft?.nodes?.length) {
            setNodes((current) => layoutGraph(current, edges));
        }
        window.setTimeout(() => void fitInitialOverview(), 0);
    }, [edges, fitInitialOverview, options.draft, setNodes]);

    const save = useCallback(async () => {
        try {
            await persistDraft();
            if (window.showToast) window.showToast('Workflow 已保存', 'success');
        } catch (error) {
            if (window.showToast) window.showToast(error instanceof Error ? error.message : 'Workflow 保存失败', 'error');
        }
    }, [persistDraft]);

    useEffect(() => {
        const onStudioKeyDown = (event) => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
                event.preventDefault();
                void save();
            }
        };
        window.addEventListener('keydown', onStudioKeyDown);
        return () => window.removeEventListener('keydown', onStudioKeyDown);
    }, [save]);

    const close = useCallback(() => {
        if (saveState === '未保存' || saveState === '保存失败') {
            if (!window.confirm('工作流有尚未保存的修改，确定离开吗？')) return;
        }
        studioClosedRef.current = true;
        nodeTestSourcesRef.current.forEach((_active, nodeId) => {
            hiddenNodeTestsRef.current.add(nodeId);
            void interruptNodeTest(nodeId);
        });
        timers.current.forEach((timer) => {
            window.clearTimeout(timer);
            window.clearInterval(timer);
        });
        if (options.onClose) options.onClose();
        if (workflowElapsedTimer.current !== null) window.clearInterval(workflowElapsedTimer.current);
    }, [interruptNodeTest, options, saveState]);

    const closeInspector = useCallback(() => {
        if (editorNodeId) {
            const active = nodeTestSourcesRef.current.get(editorNodeId);
            if (active) {
                hiddenNodeTestsRef.current.add(editorNodeId);
                void interruptNodeTest(editorNodeId);
            } else {
                resetNodeTestDisplay(editorNodeId);
            }
        }
        setEditorNodeId(null);
    }, [editorNodeId, interruptNodeTest, resetNodeTestDisplay]);

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
                            maxLength={200}
                            onChange={(event) => {metadataDraft.current.name = event.target.value; setWorkflowName(event.target.value); setSaveState('未保存');}}
                            onBlur={(event) => commitWorkflowName(metadataDraft.current.name === workflowName ? event.currentTarget.value : metadataDraft.current.name)}
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
                            title="编辑工作流名称"
                            aria-label={`编辑工作流名称：${workflowName}`}
                            onClick={() => {metadataDraft.current.name = workflowName; setNameEditing(true);}}
                        ><span>{workflowName}</span><Pencil size={13} /></button>
                    )}
                    <div className={`wf-header-description ${descriptionEditing ? 'is-editing' : ''}`}>
                        <FileText size={15} />
                        {descriptionEditing ? (
                            <div className="wf-description-editor">
                                <textarea
                                    autoFocus
                                    value={workflowDescription}
                                    maxLength={4000}
                                    rows={5}
                                    onChange={(event) => {metadataDraft.current.description = event.target.value; setWorkflowDescription(event.target.value); setSaveState('未保存');}}
                                    onBlur={(event) => commitWorkflowDescription(metadataDraft.current.description === workflowDescription ? event.currentTarget.value : metadataDraft.current.description)}
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
                                aria-label="编辑工作流说明"
                                title="编辑工作流说明"
                                onClick={() => {metadataDraft.current.description = workflowDescription; setDescriptionEditing(true);}}
                            ><span>{workflowDescription || '添加工作流说明'}</span><Pencil size={13} /></button>
                        )}
                    </div>
                </div>
                <div className="wf-header-actions">
                    {workflowRunState !== 'IDLE' && <span className={`wf-workflow-timer is-${workflowRunState.toLowerCase()}`} aria-label={`Workflow 执行耗时 ${formatExecutionDuration(workflowElapsedMs)}`}><LoaderCircle size={13} />{formatExecutionDuration(workflowElapsedMs)}</span>}
                    <button type="button" disabled={!options.executionEnabled || workflowRunState === 'RUNNING'} className="wf-secondary-button" onClick={runAll} title={options.executionEnabled ? '运行 Workflow' : '执行接口尚未接入'}><Play size={15} />运行</button>
                    <button type="button" disabled={!workflowId} className={historyOpen ? 'is-active' : ''} onClick={async () => {const next = !historyOpen; setHistoryOpen(next); if (next) await loadWorkflowHistory();}}><FileClock size={15} />历史</button>
                    <button type="button" disabled={workflowRunState !== 'RUNNING'} className="wf-danger-button" onClick={interruptWorkflow}><Square size={14} />中断</button>
                    <button type="button" className="wf-primary-button" onClick={save}><Save size={15} />保存</button>
                </div>
            </header>
            <main className="wf-canvas-wrap" ref={canvasRef}>
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
                {historyOpen && (
                    <aside className="wf-execution-history-panel" aria-label="最近 10 次执行历史">
                        <header><strong>执行历史</strong><span>最近 10 次</span><button type="button" onClick={() => setHistoryOpen(false)} title="关闭执行历史" aria-label="关闭执行历史"><X size={15} /></button></header>
                        {historyLoadState === 'loading' && <div className="wf-execution-history-empty"><LoaderCircle className="is-spinning" size={15} />正在加载</div>}
                        {historyLoadState === 'ready' && !workflowHistory.length && <div className="wf-execution-history-empty">暂无执行记录</div>}
                        <div className="wf-execution-history-list">
                            {workflowHistory.map((execution) => {
                                const expanded = expandedWorkflowExecutionId === execution.id;
                                const nodeExecutions = historyNodeExecutions[execution.id] || [];
                                return (
                                    <article className={`is-${String(execution.status).toLowerCase()}`} key={execution.id}>
                                        <button type="button" className="wf-execution-history-summary" aria-expanded={expanded} onClick={() => toggleWorkflowExecution(execution.id)}>
                                            <ChevronRight className={expanded ? 'is-open' : ''} size={14} />
                                            <time>{formatRunDate(execution.started_at || execution.created_at)}</time>
                                            <strong>{execution.status}</strong>
                                            <span>{formatExecutionDuration(execution.duration_ms)}</span>
                                        </button>
                                        {expanded && (
                                            <div className="wf-execution-history-detail">
                                                <HttpLogSection title="context.final" text={parameterDataText(execution.context?.final || {}, true)} />
                                                <HttpLogSection title="node executions" text={parameterDataText(nodeExecutions, true)} />
                                                {execution.error && <HttpLogSection title="error" text={parameterDataText(execution.error, true)} />}
                                            </div>
                                        )}
                                    </article>
                                );
                            })}
                        </div>
                    </aside>
                )}
                <ReactFlow
                    colorMode={theme}
                    nodes={decoratedNodes}
                    edges={decoratedEdges}
                    nodeTypes={nodeTypes}
                    edgeTypes={edgeTypes}
                    onNodesChange={onNodesChangeSafe}
                    onEdgesChange={onEdgesChange}
                    onConnect={(connection) => {
                        recordHistory();
                        setEdges((current) => addEdge(makeEdge(connection.source, connection.target, connection), current));
                    }}
                    onNodeDragStart={() => {
                        recordHistory();
                        setAlignmentGuides(null);
                    }}
                    onNodeDrag={(event, node) => {
                        setAlignmentGuides(calculateAlignmentGuides(getNodes(), node));
                    }}
                    onNodeDragStop={() => {
                        setAlignmentGuides(null);
                        setSaveState('未保存');
                    }}
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
                        setEditorInitialTab('settings');
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
                            nodeType: node.data.nodeType,
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
                    minZoom={0.1}
                    maxZoom={1.8}
                    selectionOnDrag={false}
                    selectionKeyCode="Control"
                    multiSelectionKeyCode="Control"
                    panOnScroll
                    zoomOnDoubleClick={false}
                    deleteKeyCode="Backspace"
                    proOptions={{hideAttribution: true}}
                >
                    <Background color={theme === 'dark' ? '#3a4656' : '#c8d1de'} gap={20} size={1.2} />
                    <AlignmentGuides guides={alignmentGuides} />
                    <MiniMap pannable zoomable nodeColor={(node) => NODE_TYPES[node.data.nodeType]?.color || '#64748b'} maskColor={theme === 'dark' ? 'rgba(15, 20, 27, 0.72)' : 'rgba(238, 242, 247, 0.76)'} />
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
                    canReplace={Boolean(
                        contextMenu?.kind === 'node'
                        && INSERTABLE_TYPES.includes(contextMenu.nodeType)
                        && workflowRunState !== 'RUNNING'
                        && !nodes.find((node) => node.id === contextMenu.nodeId)?.data.nodeTestActive
                    )}
                    onAction={contextAction}
                    onAdd={(type) => contextMenu?.flowPosition && addNodeAt(type, contextMenu.flowPosition)}
                    onReplace={replaceNode}
                />
                <NodeTestVariablesDialog
                    dialog={nodeTestDialog}
                    onRowsChange={(rows) => setNodeTestDialog((current) => current ? {...current, rows} : current)}
                    onCancel={() => setNodeTestDialog(null)}
                    onSubmit={submitNodeTestDialog}
                />
                <Inspector
                    key={`${editorNodeId || 'none'}:${editorInitialTab}`}
                    node={editorNode}
                    providers={modelProviders}
                    providerLoadState={providerLoadState}
                    providerLoadError={providerLoadError}
                    onRefreshProviders={loadModelProviders}
                    onLoadVariables={() => editorNodeId ? loadNodeVariables(editorNodeId) : []}
                    initialTab={editorInitialTab}
                    onRun={() => editorNodeId && requestNodeTest(editorNodeId)}
                    onSave={() => editorNodeId && saveNode(editorNodeId)}
                    onClose={closeInspector}
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
