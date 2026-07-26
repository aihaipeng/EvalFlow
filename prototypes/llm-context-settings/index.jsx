import React, {useMemo, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {
    BrainCircuit,
    ChevronDown,
    ChevronRight,
    CircleHelp,
    Copy,
    MessageSquareText,
    Play,
    Plus,
    Save,
    Settings2,
    Sparkles,
    Square,
    Variable,
    X,
} from 'lucide-react';

import './prototype.css';

const DEFAULT_MESSAGES = [
    {
        id: 'system',
        role: 'SYSTEM',
        content: '你是一名企业 Agent 质量评估助手。请严格依据用户提供的内容回答。',
        fixed: true,
    },
    {
        id: 'user',
        role: 'USER',
        content: '请判断以下回答是否满足测试用例：\n\n测试用例：${question}\n实际回答：${agent_response}',
        fixed: true,
    },
];

const roleMeta = {
    SYSTEM: {hint: '可为空；执行时自动省略空 SYSTEM'},
    USER: {hint: '最终一条 USER 是模型本次需要回答的内容'},
    ASSISTANT: {hint: '用于告诉模型期望的回答方式或格式'},
};

function nextRole(messages) {
    return messages.length <= 2 || messages.at(-1)?.role === 'USER' ? 'ASSISTANT' : 'USER';
}

function validateMessages(messages) {
    const errors = new Map();
    const last = messages.at(-1);
    messages.forEach((message, index) => {
        if (message.role !== 'SYSTEM' && !message.content.trim()) {
            errors.set(message.id, message.role === 'USER' ? 'USER 消息不能为空' : 'Few-shot 示例回答不能为空');
        }
        if (index >= 2) {
            const expected = index % 2 === 0 ? 'ASSISTANT' : 'USER';
            if (message.role !== expected) errors.set(message.id, `此处必须是 ${expected}`);
        }
    });
    if (!last || last.role !== 'USER') {
        if (last) errors.set(last.id, '上下文必须以 USER 消息结束后才能运行');
    } else if (!last.content.trim()) {
        errors.set(last.id, '最后一条 USER 消息不能为空');
    }
    return errors;
}

function IconButton({children, label, disabled = false, danger = false, onClick}) {
    return (
        <button
            type="button"
            className={`icon-button${danger ? ' danger' : ''}`}
            aria-label={label}
            title={label}
            disabled={disabled}
            onClick={onClick}
        >
            {children}
        </button>
    );
}

function MessageCard({message, isLast, error, onChange, onRemove}) {
    const textareaRef = useRef(null);
    const meta = roleMeta[message.role];
    return (
        <article className={`context-message role-${message.role.toLowerCase()}${error ? ' has-error' : ''}`} data-message-role={message.role}>
            <header>
                <div className="message-identity">
                    <strong>{message.role}</strong>
                    <span className="help-anchor" title={meta.hint}><CircleHelp size={13} /></span>
                </div>
                <div className="message-tools">
                    <span className="character-count">{message.content.length} 字符</span>
                    {!message.fixed && (
                        <IconButton label={isLast ? `删除 ${message.role} 消息` : '只能从最后一条消息开始删除'} disabled={!isLast} danger onClick={onRemove}>
                            <X size={14} />
                        </IconButton>
                    )}
                </div>
            </header>
            <textarea
                ref={textareaRef}
                aria-label={`${message.role} 消息内容`}
                value={message.content}
                placeholder={message.role === 'SYSTEM'
                    ? '输入模型的角色、目标和约束；留空时执行请求不发送 SYSTEM'
                    : message.role === 'ASSISTANT'
                        ? '输入期望的示例回答'
                        : '输入用户消息，支持直接引用 ${变量名}'}
                onChange={(event) => onChange(event.target.value)}
            />
        </article>
    );
}

function ContextEditor({messages, setMessages, showValidation, setShowValidation}) {
    const [contextOpen, setContextOpen] = useState(true);
    const errors = useMemo(() => validateMessages(messages), [messages]);
    const role = nextRole(messages);
    const updateMessage = (id, content) => {
        setMessages((current) => current.map((message) => message.id === id ? {...message, content} : message));
        setShowValidation(false);
    };
    const addMessage = () => {
        const newRole = nextRole(messages);
        setMessages((current) => current.concat({
            id: `message-${Date.now()}`,
            role: newRole,
            content: '',
            fixed: false,
        }));
        setShowValidation(false);
        window.setTimeout(() => {
            document.querySelector('.context-message:last-of-type textarea')?.focus();
            document.querySelector('.context-message:last-of-type')?.scrollIntoView({behavior: 'smooth', block: 'center'});
        }, 30);
    };
    const removeLast = () => {
        setMessages((current) => current.length > 2 ? current.slice(0, -1) : current);
        setShowValidation(false);
    };
    return (
        <section className="context-section section-block">
            <button type="button" className="context-toggle section-heading" aria-expanded={contextOpen} onClick={() => setContextOpen((open) => !open)}>
                <div><MessageSquareText size={16} /><strong>上下文</strong></div>
                <span><small>{messages.length} 条消息</small><ChevronRight className={contextOpen ? 'open' : ''} size={15} /></span>
            </button>
            {contextOpen && (
                <div className="context-content">
                    <div className="context-intro">
                        <p>消息按从上到下的顺序发送。通过 ASSISTANT 与 USER 消息构建 Few-shot 示例。</p>
                        <span>固定顺序：SYSTEM → USER → (ASSISTANT → USER)...</span>
                    </div>
                    <div className="message-list">
                        {messages.map((message, index) => (
                            <MessageCard
                                key={message.id}
                                message={message}
                        isLast={index === messages.length - 1}
                                error={showValidation ? errors.get(message.id) : ''}
                                onChange={(content) => updateMessage(message.id, content)}
                                onRemove={removeLast}
                            />
                        ))}
                    </div>
                    <button type="button" className="add-message" onClick={addMessage}>
                        <Plus size={15} />
                        <strong>添加消息</strong>
                        <span>下一条 {role}</span>
                    </button>
                    {showValidation && errors.size > 0 && (
                        <div className="execution-warning" role="alert">
                            当前草稿可以保存，但需补全标记的消息后才能运行：{[...errors.values()][0]}。
                        </div>
                    )}
                </div>
            )}
        </section>
    );
}

function ToggleRow({label, checked, onChange}) {
    return (
        <label className="toggle-row">
            <span>{label}</span>
            <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
            <i><span /></i>
        </label>
    );
}

function App() {
    const [messages, setMessages] = useState(DEFAULT_MESSAGES);
    const [advancedOpen, setAdvancedOpen] = useState(false);
    const [outputOpen, setOutputOpen] = useState(true);
    const [showValidation, setShowValidation] = useState(false);
    const [toast, setToast] = useState('');
    const [stopped, setStopped] = useState(false);
    const errors = useMemo(() => validateMessages(messages), [messages]);

    const notify = (message) => {
        setToast(message);
        window.clearTimeout(window.__llmPrototypeToast);
        window.__llmPrototypeToast = window.setTimeout(() => setToast(''), 2400);
    };
    const run = () => {
        setShowValidation(true);
        if (errors.size) {
            notify('上下文未完成，已定位需要处理的消息');
            window.setTimeout(() => document.querySelector('.context-message.has-error')?.scrollIntoView({behavior: 'smooth', block: 'center'}), 30);
            return;
        }
        setStopped(false);
        notify(`运行校验通过，将发送 ${messages.filter((message) => message.content.trim()).length} 条消息`);
    };

    return (
        <main className="prototype-stage">
            <div className="canvas-context" aria-hidden="true">
                <span className="canvas-kicker">WORKFLOW STUDIO</span>
                <strong>Agent 质量判断</strong>
                <p>LLM 节点上下文编辑器高保真原型</p>
            </div>
            <section className="inspector" aria-label="LLM 节点设置原型">
                <header className="inspector-header">
                    <span className="node-icon"><BrainCircuit size={18} /></span>
                    <div className="inspector-title"><strong>模型质量判断</strong><small>LLM</small></div>
                    <div className="header-actions">
                        <IconButton label="查看节点变量"><Variable size={15} /></IconButton>
                        <IconButton label="运行当前节点" onClick={run}><Play size={15} /></IconButton>
                        <IconButton label="中断当前节点" danger disabled={stopped} onClick={() => setStopped(true)}><Square size={15} /></IconButton>
                        <IconButton label="保存草稿" onClick={() => notify('草稿已保存；空消息将在执行时校验')}><Save size={15} /></IconButton>
                        <IconButton label="关闭原型"><X size={17} /></IconButton>
                    </div>
                </header>
                <nav className="tabs"><button className="active" type="button">设置</button><button type="button">日志</button></nav>
                <div className="inspector-body">
                    <section className="basic-fields">
                        <label><span>名称</span><input defaultValue="模型质量判断" /></label>
                        <label><span>说明</span><input defaultValue="判断 Agent 回复是否满足测试用例" /></label>
                    </section>

                    <section className="model-section section-block">
                        <div className="section-heading"><div><BrainCircuit size={16} /><strong>模型配置</strong></div></div>
                        <label className="model-field"><span>模型</span><button type="button" className="model-select"><span className="provider-mark">D</span><strong>deepseek-chat</strong><small>DeepSeek · OpenAI</small><ChevronDown size={15} /></button></label>
                        <ContextEditor messages={messages} setMessages={setMessages} showValidation={showValidation} setShowValidation={setShowValidation} />
                        <div className="advanced">
                            <button type="button" aria-expanded={advancedOpen} onClick={() => setAdvancedOpen((open) => !open)}>
                                <span><Sparkles size={15} /><strong>高级参数</strong></span>
                                <ChevronRight className={advancedOpen ? 'open' : ''} size={15} />
                            </button>
                            {advancedOpen && <div className="json-editor"><div><span>JSON</span><button type="button">Beautify</button></div><textarea aria-label="高级参数 JSON" defaultValue={'{\n  "temperature": 0.2\n}'} /></div>}
                        </div>
                    </section>

                    <section className="runtime-section section-block">
                        <div className="section-heading"><div><Settings2 size={16} /><strong>运行配置</strong></div></div>
                        <div className="runtime-grid">
                            <label><span>单次超时</span><div><input type="number" defaultValue="600" /><i>秒</i></div></label>
                            <label><span>重试次数</span><input type="number" defaultValue="0" /></label>
                            <label><span>重试间隔</span><div><input type="number" defaultValue="0" /><i>秒</i></div></label>
                            <label><span>延迟执行</span><div><input type="number" defaultValue="0" /><i>秒</i></div></label>
                        </div>
                        <div className="runtime-toggle"><ToggleRow label="记录原始响应" checked={true} onChange={() => {}} /></div>
                        <button type="button" className="output-toggle" aria-expanded={outputOpen} onClick={() => setOutputOpen((open) => !open)}><span><Variable size={15} />输出变量</span><ChevronRight className={outputOpen ? 'open' : ''} size={15} /></button>
                        {outputOpen && (
                            <div className="output-row">
                                <label><span>变量名</span><input defaultValue="answer" /></label>
                                <label className="source"><span>提取表达式</span><input defaultValue="response.choices[-1].message.content" /></label>
                                <label className="type"><span>类型</span><select defaultValue="string"><option>string</option><option>number</option><option>boolean</option><option>object</option><option>array</option></select></label>
                                <IconButton label="复制变量引用"><Copy size={14} /></IconButton>
                            </div>
                        )}
                    </section>
                </div>
            </section>
            {toast && <div className="toast" role="status">{toast}</div>}
        </main>
    );
}

createRoot(document.getElementById('root')).render(<App />);
