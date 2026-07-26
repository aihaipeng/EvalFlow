import React, {useEffect, useMemo, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {
    ChevronRight,
    ChevronDown,
    Globe2,
    Play,
    Plus,
    Save,
    Settings2,
    Square,
    Trash2,
    Upload,
    Variable,
    WandSparkles,
    X,
} from 'lucide-react';
import './prototype.css';

const BODY_TYPES = ['none', 'form-data', 'x-www-form-urlencoded', 'raw'];
const HTTP_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'];

function makeRow(key = '', value = '') {
    return {id: crypto.randomUUID(), key, value};
}

function makeOutput(name = '', source = '', type = 'string') {
    return {id: crypto.randomUUID(), name, source, type};
}

function IconButton({label, children, danger = false, disabled = false, onClick}) {
    return (
        <button
            type="button"
            className={`icon-button${danger ? ' is-danger' : ''}`}
            aria-label={label}
            title={label}
            disabled={disabled}
            onClick={onClick}
        >
            {children}
        </button>
    );
}

function KeyValueTable({label, rows, onChange}) {
    const addRow = () => onChange([...rows, makeRow()]);
    const updateRow = (id, field, value) => {
        onChange(rows.map((row) => row.id === id ? {...row, [field]: value} : row));
    };
    const removeRow = (id) => onChange(rows.filter((row) => row.id !== id));

    return (
        <div className="kv-table" role="table" aria-label={`${label} key value table`}>
            <div className="kv-table-header" role="row">
                <span role="columnheader">key</span>
                <span role="columnheader">value</span>
                <IconButton label={`新增 ${label}`} onClick={addRow}><Plus size={15} /></IconButton>
            </div>
            <div className="kv-table-body" role="rowgroup">
                {rows.map((row, index) => (
                    <div className="kv-table-row" role="row" key={row.id}>
                        <input
                            role="cell"
                            aria-label={`${label} key ${index + 1}`}
                            value={row.key}
                            placeholder="key"
                            onChange={(event) => updateRow(row.id, 'key', event.target.value)}
                        />
                        <input
                            role="cell"
                            aria-label={`${label} value ${index + 1}`}
                            value={row.value}
                            placeholder="value"
                            onChange={(event) => updateRow(row.id, 'value', event.target.value)}
                        />
                        <IconButton label={`删除 ${label} ${index + 1}`} danger onClick={() => removeRow(row.id)}>
                            <Trash2 size={15} />
                        </IconButton>
                    </div>
                ))}
                {!rows.length && <div className="kv-empty">No entries</div>}
            </div>
        </div>
    );
}

function Accordion({title, count, tag, open, onToggle, children, icon = null}) {
    return (
        <section className={`accordion${open ? ' is-open' : ''}`}>
            <button type="button" className="accordion-trigger" aria-expanded={open} onClick={onToggle}>
                <span className="accordion-title">
                    {icon}
                    <strong>{title}</strong>
                    {typeof count === 'number' && <span className="count-badge">{count}</span>}
                    {tag && <span className="mode-badge">{tag}</span>}
                </span>
                <ChevronRight className="accordion-chevron" size={16} />
            </button>
            {open && <div className="accordion-panel">{children}</div>}
        </section>
    );
}

function Toggle({label, checked, onChange}) {
    return (
        <label className="toggle-field">
            <span>{label}</span>
            <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
            <i aria-hidden="true"><span /></i>
        </label>
    );
}

function MethodSelector() {
    const [value, setValue] = useState('POST');
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

    return (
        <div className="method-selector" ref={rootRef}>
            <button
                type="button"
                className="method-trigger"
                aria-label="请求方式"
                aria-haspopup="listbox"
                aria-expanded={open}
                onClick={() => setOpen((current) => !current)}
            >
                <span>{value}</span>
                <ChevronDown size={14} />
            </button>
            {open && (
                <div className="method-menu" role="listbox" aria-label="请求方式选项">
                    {HTTP_METHODS.map((method) => (
                        <button
                            type="button"
                            role="option"
                            aria-selected={value === method}
                            className={value === method ? 'is-selected' : ''}
                            key={method}
                            onClick={() => {
                                setValue(method);
                                setOpen(false);
                            }}
                        >
                            {method}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}

function HttpNodePrototype() {
    const [headersOpen, setHeadersOpen] = useState(true);
    const [paramsOpen, setParamsOpen] = useState(false);
    const [bodyOpen, setBodyOpen] = useState(true);
    const [requestOptionsOpen, setRequestOptionsOpen] = useState(true);
    const [executionOpen, setExecutionOpen] = useState(true);
    const [outputsOpen, setOutputsOpen] = useState(false);
    const [headers, setHeaders] = useState([
        makeRow('Content-Type', 'application/json'),
        makeRow('Authorization', 'Bearer ${api_token}'),
    ]);
    const [params, setParams] = useState([
        makeRow('page', '1'),
        makeRow('limit', '20'),
    ]);
    const [bodyType, setBodyType] = useState('form-data');
    const [bodyFields, setBodyFields] = useState([
        makeRow('question', '${question}'),
        makeRow('session_id', '${session_id}'),
    ]);
    const [rawBody, setRawBody] = useState('{\n  "question": "${question}",\n  "session_id": "${session_id}"\n}');
    const [proxyMode, setProxyMode] = useState('SYSTEM');
    const [redirects, setRedirects] = useState(true);
    const [sslVerify, setSslVerify] = useState(true);
    const [outputs, setOutputs] = useState([
        makeOutput('answer', 'response.body.answer', 'string'),
    ]);
    const activeBodyRows = useMemo(() => bodyType === 'form-data' || bodyType === 'x-www-form-urlencoded', [bodyType]);

    const beautifyRawBody = () => {
        try {
            setRawBody(JSON.stringify(JSON.parse(rawBody), null, 2));
        } catch (_error) {
            // The prototype intentionally keeps invalid user text unchanged.
        }
    };

    return (
        <main className="prototype-stage">
            <div className="prototype-label">HTTP NODE · UI PROTOTYPE</div>
            <article className="node-editor" aria-label="HTTP 节点高保真原型">
                <header className="editor-header">
                    <span className="node-icon"><Globe2 size={20} /></span>
                    <div className="editor-title">
                        <strong>HTTP 请求</strong>
                        <small>HTTP</small>
                    </div>
                    <div className="editor-actions">
                        <IconButton label="查看节点变量"><Variable size={16} /></IconButton>
                        <IconButton label="运行当前节点"><Play size={16} /></IconButton>
                        <IconButton label="中断当前节点" danger disabled><Square size={15} /></IconButton>
                        <IconButton label="保存当前节点"><Save size={16} /></IconButton>
                        <IconButton label="关闭"><X size={18} /></IconButton>
                    </div>
                </header>

                <nav className="editor-tabs" aria-label="节点页签">
                    <button type="button" className="is-active">设置</button>
                    <button type="button">日志</button>
                </nav>

                <div className="editor-scroll">
                    <section className="basic-config-section">
                        <div className="basic-grid">
                            <label><span>名称</span><input defaultValue="HTTP 请求" /></label>
                            <label><span>说明</span><input defaultValue="调用企业 Agent 服务" /></label>
                        </div>
                    </section>

                    <section className="request-config-section">
                        <div className="request-config-title"><Globe2 size={15} /><strong>请求设置</strong></div>
                        <section className="endpoint-section">
                            <div className="endpoint-row">
                                <strong>Endpoint</strong>
                                <MethodSelector />
                                <input aria-label="请求 URL" defaultValue="https://api.example.com/v1/chat/completions" />
                                <IconButton label="导入 cURL"><Upload size={16} /></IconButton>
                            </div>
                        </section>

                        <div className="request-sections">
                            <Accordion title="Headers" count={headers.length} open={headersOpen} onToggle={() => setHeadersOpen(!headersOpen)}>
                                <KeyValueTable label="Headers" rows={headers} onChange={setHeaders} />
                            </Accordion>

                            <Accordion title="Params" count={params.length} open={paramsOpen} onToggle={() => setParamsOpen(!paramsOpen)}>
                                <KeyValueTable label="Params" rows={params} onChange={setParams} />
                            </Accordion>

                            <Accordion title="Body" tag={bodyType} open={bodyOpen} onToggle={() => setBodyOpen(!bodyOpen)}>
                                <div className="body-panel">
                                    <div className="body-modes" role="radiogroup" aria-label="Body 类型">
                                        {BODY_TYPES.map((type) => (
                                            <label className={bodyType === type ? 'is-selected' : ''} key={type}>
                                                <input
                                                    type="radio"
                                                    name="body-type"
                                                    value={type}
                                                    checked={bodyType === type}
                                                    onChange={() => setBodyType(type)}
                                                />
                                                <i aria-hidden="true" />
                                                <span>{type}</span>
                                            </label>
                                        ))}
                                    </div>
                                    <div className="body-content">
                                        {activeBodyRows && <KeyValueTable label="Body" rows={bodyFields} onChange={setBodyFields} />}
                                        {bodyType === 'raw' && (
                                            <div className="raw-editor">
                                                <div className="raw-toolbar">
                                                    <span>JSON</span>
                                                    <button type="button" onClick={beautifyRawBody}><WandSparkles size={14} />Beautify</button>
                                                </div>
                                                <textarea aria-label="Raw Body" value={rawBody} onChange={(event) => setRawBody(event.target.value)} spellCheck="false" />
                                            </div>
                                        )}
                                        {bodyType === 'none' && <div className="body-empty">No request body</div>}
                                    </div>
                                </div>
                            </Accordion>

                            <Accordion
                                title="Request Options"
                                open={requestOptionsOpen}
                                onToggle={() => setRequestOptionsOpen(!requestOptionsOpen)}
                            >
                                <div className="request-options">
                                    <div className="options-fields">
                                        <label>
                                            <span>Proxy</span>
                                            <select value={proxyMode} onChange={(event) => setProxyMode(event.target.value)}>
                                                <option value="SYSTEM">SYSTEM</option>
                                                <option value="DIRECT">DIRECT</option>
                                                <option value="CUSTOM">CUSTOM</option>
                                            </select>
                                        </label>
                                        <label>
                                            <span>Response Body</span>
                                            <select defaultValue="AUTO">
                                                <option value="AUTO">AUTO</option>
                                                <option value="JSON">JSON</option>
                                                <option value="TEXT">TEXT</option>
                                                <option value="BINARY">BINARY</option>
                                            </select>
                                        </label>
                                    </div>
                                    {proxyMode === 'CUSTOM' && (
                                        <div className="custom-proxy">
                                            <label className="proxy-url"><span>Proxy URL</span><input placeholder="http://proxy.example.com:8080" /></label>
                                            <label><span>Username</span><input autoComplete="off" /></label>
                                            <label><span>Password</span><input type="password" autoComplete="new-password" /></label>
                                        </div>
                                    )}
                                    <div className="switch-row">
                                        <Toggle label="Redirects" checked={redirects} onChange={setRedirects} />
                                        <Toggle label="SSL Verify" checked={sslVerify} onChange={setSslVerify} />
                                    </div>
                                </div>
                            </Accordion>
                        </div>
                    </section>

                    <section className="shared-config-section">
                        <div className="shared-config-title"><Settings2 size={15} /><strong>运行配置</strong></div>
                        <Accordion title="超时与重试" open={executionOpen} onToggle={() => setExecutionOpen(!executionOpen)}>
                            <div className="execution-grid">
                                <label><span>单次超时（秒）</span><input type="number" min="0.001" step="0.1" defaultValue="600" /></label>
                                <label><span>最大重试次数</span><input type="number" min="0" max="10" step="1" defaultValue="0" /></label>
                                <label><span>重试间隔（秒）</span><input type="number" min="0" max="600" step="0.1" defaultValue="0" /></label>
                                <label><span>延迟执行（秒）</span><input type="number" min="0" max="600" step="0.1" defaultValue="0" /></label>
                            </div>
                        </Accordion>
                        <Accordion title="输出变量" open={outputsOpen} onToggle={() => setOutputsOpen(!outputsOpen)}>
                            <div className="output-config-list">
                                {outputs.map((output, index) => (
                                    <div className="output-config-row" key={output.id}>
                                        <label><span>变量名</span><input aria-label={`输出变量名 ${index + 1}`} value={output.name} onChange={(event) => setOutputs(outputs.map((item) => item.id === output.id ? {...item, name: event.target.value} : item))} /></label>
                                        <label><span>提取表达式</span><input aria-label={`输出变量来源 ${index + 1}`} value={output.source} onChange={(event) => setOutputs(outputs.map((item) => item.id === output.id ? {...item, source: event.target.value} : item))} /></label>
                                        <label className="output-type-field"><span>类型</span><select aria-label={`输出变量类型 ${index + 1}`} value={output.type} onChange={(event) => setOutputs(outputs.map((item) => item.id === output.id ? {...item, type: event.target.value} : item))}>
                                                {['string', 'integer', 'number', 'boolean', 'object', 'array', 'null'].map((type) => <option value={type} key={type}>{type}</option>)}
                                            </select></label>
                                        {index === 0 ? (
                                            <IconButton label="添加输出变量" onClick={() => setOutputs([...outputs, makeOutput()])}><Plus size={15} /></IconButton>
                                        ) : (
                                            <IconButton label={`删除输出变量 ${index + 1}`} danger onClick={() => setOutputs(outputs.filter((item) => item.id !== output.id))}><Trash2 size={15} /></IconButton>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </Accordion>
                    </section>
                </div>
            </article>
        </main>
    );
}

createRoot(document.getElementById('root')).render(<HttpNodePrototype />);
