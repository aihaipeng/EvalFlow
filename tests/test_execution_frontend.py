from pathlib import Path

from fastapi.testclient import TestClient

from web.app import app
from web import routes_workflows


STATIC_DIR = Path(__file__).parents[1] / "web" / "static"


def test_execution_assets_and_navigation_are_registered(tmp_path, monkeypatch):
    monkeypatch.setattr(
        routes_workflows,
        "DATABASE_PATH",
        tmp_path / "run_storage" / "agent_bench.sqlite3",
    )
    monkeypatch.setattr(routes_workflows, "_repository_instance", None)
    monkeypatch.setattr(routes_workflows, "_repository_path", None)
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    execution_js = (STATIC_DIR / "execution.js").read_text(encoding="utf-8")

    for view in ("targets", "workflows"):
        assert f'data-view="{view}"' in index_html
    assert "工作流管理" in index_html
    assert 'data-view="runs"' not in index_html
    assert "运行中心" not in index_html
    assert '<link rel="stylesheet" href="/execution.css" />' in index_html
    assert '<link rel="stylesheet" href="/assets/workflow-canvas.css?v=34" />' in index_html
    assert '<script src="/assets/workflow-canvas.js?v=34"></script>' in index_html
    assert '<script src="/execution.js"></script>' in index_html
    assert 'name="viewport"' not in index_html
    assert "viewTargets();" in app_js
    assert "viewWorkflows();" in app_js
    assert "viewRuns();" not in app_js
    assert "destroyToolCodeEditor" not in execution_js

    client = TestClient(app)
    assert client.get("/execution.css").status_code == 200
    assert client.get("/execution.js").status_code == 200
    assert client.get("/assets/workflow-canvas.css").status_code == 200
    assert client.get("/assets/workflow-canvas.js").status_code == 200
    font_response = client.get("/assets/fonts/DroidSansMonoSlashed.ttf")
    assert font_response.status_code == 200
    assert font_response.content[:4] == b"\x00\x01\x00\x00"
    assert client.get("/execution.css").headers["cache-control"] == (
        "no-cache, no-store, must-revalidate"
    )
    assert client.get("/api/workflows").status_code == 200
    assert client.get("/api/runs").status_code == 404
    assert client.get("/api/workflow-drafts").status_code == 404


def test_target_page_uses_complete_crud_api_and_validated_form():
    execution_js = (STATIC_DIR / "execution.js").read_text(encoding="utf-8")
    execution_css = (STATIC_DIR / "execution.css").read_text(encoding="utf-8")

    assert "function viewTargets()" in execution_js
    assert "function openTargetEditor(targetId)" in execution_js
    assert "function readTargetForm()" in execution_js
    assert "function deleteTarget(targetId)" in execution_js
    assert "API.get('/api/targets')" in execution_js
    assert "API.post('/api/targets', body)" in execution_js
    assert "API.put('/api/targets/'" in execution_js
    assert "API.del('/api/targets/'" in execution_js
    for element_id in (
        "target-name",
        "target-base-url",
        "target-path",
        "target-concurrency",
        "target-headers",
    ):
        assert element_id in execution_js
    assert "Headers 必须是合法 JSON 对象" in execution_js
    assert "Target 总并发必须是正整数" in execution_js
    assert ".execution-table-wrap" in execution_css
    assert ".execution-form-grid" in execution_css
    assert "@media (max-width: 760px)" not in execution_css


def test_workflow_list_uses_persistent_drafts_without_legacy_api():
    execution_js = (STATIC_DIR / "execution.js").read_text(encoding="utf-8")
    execution_css = (STATIC_DIR / "execution.css").read_text(encoding="utf-8")

    assert "function viewWorkflows()" in execution_js
    assert "function renderWorkflowTable()" in execution_js
    assert "persistent Workflow Studio" in execution_js
    assert "API.get('/api/workflows')" in execution_js
    assert "API.post('/api/workflows'" in execution_js
    assert "API.del('/api/workflows/'" not in execution_js
    assert "API.put('/api/workflows/bindings/'" not in execution_js
    assert "API.del('/api/workflows/bindings/'" not in execution_js
    assert "/api/workflow-drafts" not in execution_js
    assert "API.get('/api/workflows/'" in execution_js
    assert "API.put('/api/workflows/'" in execution_js
    assert "已持久化" in execution_js
    assert "id=\"workflow-search\"" in execution_js
    assert "id=\"workflow-status-filter\"" in execution_js
    assert "新增工作流" in execution_js
    assert "function openWorkflowCreateDialog()" in execution_js
    assert 'id="workflow-create-name"' in execution_js
    assert 'id="workflow-create-description"' in execution_js
    assert "名称不能为空" in execution_js
    assert "await openWorkflowEditor(null, {name: name, description: description})" in execution_js
    assert "createOnMount: false" in execution_js
    assert "onPersistMetadata: async function (metadata)" in execution_js
    assert "API.patch(" not in execution_js[execution_js.index("async function openWorkflowEditor"):]
    assert "window.AgentBenchWorkflowCanvas.mount" in execution_js
    assert ".workflow-row-actions" in execution_css
    assert ".workflow-valid" in execution_css
    assert ".workflow-invalid" in execution_css


def test_workflow_editor_uses_fullscreen_react_flow_canvas():
    execution_js = (STATIC_DIR / "execution.js").read_text(encoding="utf-8")
    canvas_jsx = (
        STATIC_DIR.parent / "frontend" / "workflow-canvas.jsx"
    ).read_text(encoding="utf-8")
    canvas_css = (
        STATIC_DIR.parent / "frontend" / "workflow-canvas.css"
    ).read_text(encoding="utf-8")
    assert "function openWorkflowEditor(workflowId, initialMetadata)" in execution_js
    assert "window.AgentBenchWorkflowCanvas.mount" in execution_js
    assert "API.get('/api/tools')" not in execution_js[
        execution_js.index("async function openWorkflowEditor(workflowId, initialMetadata)"):
    ]
    for token in (
        "ReactFlow",
        "ReactFlowProvider",
        "MiniMap",
        "Controls",
        "onPaneContextMenu",
        "onNodeContextMenu",
        "onNodeDoubleClick",
        "onSelectionChange",
        "onConnect",
        "fitView",
    ):
        assert token in canvas_jsx
    assert "position: fixed" in canvas_css
    assert "min-width: 1180px" in canvas_css
    assert "wf-node-editor-rnd" in canvas_css
    assert "wf-resize-se" in canvas_css
    assert "Math.round(760 * 1.4)" in canvas_jsx
    assert 'selectionKeyCode="Control"' in canvas_jsx
    assert 'multiSelectionKeyCode="Control"' in canvas_jsx
    assert "event.key === 'Delete'" in canvas_jsx
    assert "event.key === 'Backspace'" in canvas_jsx
    assert "copyNodes(selectedIds)" in canvas_jsx
    assert "function hasBrowserTextSelection()" in canvas_jsx
    assert "control && key === 'c' && hasBrowserTextSelection()" in canvas_jsx
    assert "if (hasBrowserTextSelection()) return" in canvas_jsx
    assert "pasteClipboard()" in canvas_jsx
    assert "const handleNodeClick" in canvas_jsx
    assert 'tabIndex={0}' in canvas_jsx
    assert 'onKeyDown={handleKeyboard}' in canvas_jsx
    assert 'onCopy={handleCopy}' in canvas_jsx
    assert 'onPaste={handlePaste}' in canvas_jsx
    assert 'onPointerDownCapture={handleMarqueeStart}' in canvas_jsx
    assert 'onPointerMoveCapture={handleMarqueeMove}' in canvas_jsx
    assert 'onPointerUpCapture={handleMarqueeEnd}' in canvas_jsx
    assert ".wf-selection-marquee" in canvas_css
    assert "layoutGraph(current, edges)" in canvas_jsx
    assert "dagre.layout(graph)" in canvas_jsx
    assert "undoStack.current" in canvas_jsx
    assert "redoStack.current" in canvas_jsx
    assert "if (control && key === 'z')" in canvas_jsx
    assert 'title="回退"' in canvas_jsx
    assert 'title="前进"' in canvas_jsx
    assert "全局变量" in canvas_jsx
    assert "const [nameEditing, setNameEditing]" in canvas_jsx
    assert "const [descriptionEditing, setDescriptionEditing]" in canvas_jsx
    assert "const persistMetadata = useCallback" in canvas_jsx
    assert "options.onPersistMetadata" in canvas_jsx
    assert "options.createOnMount" in canvas_jsx
    assert 'onDoubleClick={() => setNameEditing(true)}' in canvas_jsx
    assert 'onBlur={commitWorkflowName}' in canvas_jsx
    assert "if (event.key === 'Enter') event.currentTarget.blur()" in canvas_jsx
    assert 'onDoubleClick={() => setDescriptionEditing(true)}' in canvas_jsx
    assert 'onBlur={commitWorkflowDescription}' in canvas_jsx
    assert 'aria-label="工作流说明"' in canvas_jsx
    assert "添加工作流说明" in canvas_jsx
    assert 'title="双击修改工作流名称"' not in canvas_jsx
    assert ".wf-header-description" in canvas_css
    assert ".wf-description-editor" in canvas_css
    assert "color-scheme: light" in canvas_css
    assert "background: #f6f8fb" in canvas_css
    assert "background: #fff" in canvas_css
    assert "color: #172033" in canvas_css
    assert "grid-template-columns: minmax(330px, 1fr) minmax(260px, 500px) minmax(430px, 1fr)" in canvas_css
    assert "wf-inspector-footer" not in canvas_jsx
    assert "重试次数" in canvas_jsx
    assert "输出变量" in canvas_jsx
    assert "变量名" in canvas_jsx
    assert "outputVariables: [emptyMappingRow()]" in canvas_jsx
    assert "const legacyOutputVariable = node.data.outputVariable" in canvas_jsx
    assert "const addOutputVariable = ()" in canvas_jsx
    assert "const removeOutputVariable = (id)" in canvas_jsx
    assert 'aria-label={`输出变量名 ${index + 1}`}' in canvas_jsx
    assert "const OUTPUT_VARIABLE_TYPES = ['AUTO', 'STRING', 'INTEGER', 'NUMBER', 'BOOLEAN', 'OBJECT', 'ARRAY']" in canvas_jsx
    assert "return {id: rowId(), name: '', type: 'AUTO', value: '', pythonVariable: ''}" in canvas_jsx
    assert "isHttp && (" in canvas_jsx
    assert "set_val" not in canvas_jsx
    assert 'aria-label={`输出变量类型 ${index + 1}`}' in canvas_jsx
    assert "value={row.type || 'AUTO'}" in canvas_jsx
    assert 'aria-label={`输出变量 ${index + 1}`}' in canvas_jsx
    assert 'aria-label="添加输出变量"' in canvas_jsx
    assert 'aria-label={`删除输出变量 ${index + 1}`}' in canvas_jsx
    assert "onClick={addOutputVariable}" in canvas_jsx
    assert "onClick={() => removeOutputVariable(row.id)}" in canvas_jsx
    assert "mappingRows('parameters'" not in canvas_jsx
    assert "新增变量名" not in canvas_jsx
    assert "parameterRecords: []" in canvas_jsx
    assert "function parameterDataSummary(value)" in canvas_jsx
    assert "正在接收原始响应…" in canvas_jsx
    assert "text.length > 180" in canvas_jsx
    assert "const NODE_STATUSES = ['PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'TIMEOUT', 'CANCELLED']" in canvas_jsx
    assert "function validateWorkflowGraph(nodes, edges)" in canvas_jsx
    assert "Workflow 存在游离节点" in canvas_jsx
    assert "Workflow 存在循环依赖" in canvas_jsx
    assert "const orphaned = nodes.length === 1 ? []" in canvas_jsx
    assert canvas_jsx.count("validateWorkflowGraph(nodes, edges)") >= 3
    assert "const persistDraft = useCallback(async ({forNodeRun = false, metadata = null} = {})" in canvas_jsx
    assert "const activeWorkflowId = await persistDraft({forNodeRun: true})" not in canvas_jsx
    assert "if (!forNodeRun)" in canvas_jsx
    assert "draft.forNodeRun ? '?for_node_run=true' : ''" not in execution_js
    assert "status: 'PENDING'" in canvas_jsx
    assert "setWorkflowRunState('RUNNING')" in canvas_jsx
    assert "SUCCESS" in canvas_jsx
    assert "function formatExecutionDuration(value)" in canvas_jsx
    assert "executionDurationMs: 0" in canvas_jsx
    assert "Date.now() - workflowState.startedAtMs" in canvas_jsx
    assert "window.setInterval" in canvas_jsx
    assert 'aria-label={`执行耗时 ${executionDuration}`}' in canvas_jsx
    assert 'className="wf-execution-spinner"' in canvas_jsx
    assert 'aria-label={`运行 ${data.label}`}' in canvas_jsx
    assert 'aria-label={`查看 ${data.label} 日志`}' in canvas_jsx
    assert "data.onOpenLogs?.()" in canvas_jsx
    assert 'aria-label={`参数 ${data.label}`}' not in canvas_jsx
    assert "data.onOpenParameters?.()" not in canvas_jsx
    assert 'aria-label="运行当前节点"' in canvas_jsx
    assert 'aria-label="打开当前节点参数"' not in canvas_jsx
    assert 'aria-label="保存当前节点"' in canvas_jsx
    assert "onRun={() => window.showToast && window.showToast('请使用画布右上角运行 Workflow', 'error')}" in canvas_jsx
    assert "onSave={() => editorNodeId && saveNode(editorNodeId)}" in canvas_jsx
    assert "setNodeSaveNotice" in canvas_jsx
    assert "wf-node-saved-state" in canvas_jsx
    assert "setEditorInitialTab('logs')" in canvas_jsx
    assert "setEditorInitialTab('settings')" in canvas_jsx
    assert 'initialTab={editorInitialTab}' in canvas_jsx
    assert "setTab(initialTab)" in canvas_jsx
    assert "const isScript = node.data.nodeType === 'SCRIPT'" in canvas_jsx
    assert "const showParametersTab = !isHttp && !isLlm && !isScript" in canvas_jsx
    assert "showParametersTab && <button type=\"button\" className={tab === 'parameters'" in canvas_jsx
    assert "tab === 'parameters' && showParametersTab" in canvas_jsx
    assert 'role="columnheader">source' in canvas_jsx
    assert 'role="columnheader">name' in canvas_jsx
    assert 'role="columnheader">data' in canvas_jsx
    assert "当前节点尚无运行参数" in canvas_jsx
    assert "parameterDataText(selectedParameter.data, true)" in canvas_jsx
    assert "selectedParameter.artifact?.href" in canvas_jsx
    assert ".wf-node-actions" in canvas_css
    assert ".wf-node-status.is-success" in canvas_css
    assert "border-top: 3px solid var(--node-accent)" not in canvas_css
    assert ".wf-node.is-selected" in canvas_css
    assert "border-color: #16a34a" in canvas_css
    assert "outline: 2px solid #16a34a" in canvas_css
    assert "linear-gradient(135deg, #eafaf0 0%, #ffffff 52%, #f0fdf4 100%)" in canvas_css
    assert ".wf-node-status.is-failed" in canvas_css
    assert ".wf-node-execution.is-running .wf-execution-spinner" in canvas_css
    assert "animation: wf-execution-spin 0.8s linear infinite" in canvas_css
    assert "@keyframes wf-execution-spin" in canvas_css
    assert ".wf-inspector-actions" in canvas_css
    assert ".wf-node-save-toast" in canvas_css
    assert ".wf-node-log-panel" in canvas_css
    assert ".wf-parameter-table" in canvas_css
    assert ".wf-parameter-detail" in canvas_css
    assert "grid-template-columns: minmax(180px, 0.9fr) minmax(150px, 0.7fr) minmax(0, 2fr)" in canvas_css
    assert ".wf-retry-grid" in canvas_css
    assert ".wf-mapping-value-row" in canvas_css
    assert ".wf-output-variable-row" in canvas_css
    assert ".wf-output-variable-list" in canvas_css
    assert "grid-template-columns: minmax(190px, 0.9fr) minmax(260px, 1.35fr) minmax(150px, 0.65fr) 32px" in canvas_css
    assert "grid-template-columns: 64px minmax(0, 1fr)" in canvas_css
    assert "white-space: nowrap" in canvas_css
    assert "@media" not in canvas_css


def test_workflow_canvas_has_required_context_menus_and_edge_insert():
    canvas_jsx = (
        STATIC_DIR.parent / "frontend" / "workflow-canvas.jsx"
    ).read_text(encoding="utf-8")
    canvas_css = (
        STATIC_DIR.parent / "frontend" / "workflow-canvas.css"
    ).read_text(encoding="utf-8")

    for label in (
        "添加节点",
        "测试运行",
        "粘贴节点",
        "运行此步骤",
        "拷贝",
        "删除",
        "删除连线",
    ):
        assert label in canvas_jsx
    for node_type in ("START", "HTTP", "AGENT", "LLM", "SCRIPT", "END"):
        assert f"{node_type}:" in canvas_jsx
    assert "const INSERTABLE_TYPES = ['HTTP', 'AGENT', 'LLM', 'SCRIPT']" in canvas_jsx
    assert "Large Language Model" not in canvas_jsx
    assert "Python Script" not in canvas_jsx
    assert "function InsertableEdge" in canvas_jsx
    assert "wf-edge-plus" in canvas_jsx
    assert "onToggleInsert" in canvas_jsx
    assert "onInsert" in canvas_jsx
    assert "onEdgeClick" in canvas_jsx
    assert "onEdgeContextMenu" in canvas_jsx
    assert "selectedEdgeIds" in canvas_jsx
    assert "deleteElements(selectedIds, selectedEdges)" in canvas_jsx
    assert "includeSystem" in canvas_jsx
    assert ".wf-context-menu" in canvas_css
    assert ".wf-edge-picker" in canvas_css


def test_http_node_editor_has_api_import_and_body_controls():
    canvas_jsx = (
        STATIC_DIR.parent / "frontend" / "workflow-canvas.jsx"
    ).read_text(encoding="utf-8")
    canvas_css = (
        STATIC_DIR.parent / "frontend" / "workflow-canvas.css"
    ).read_text(encoding="utf-8")

    assert "type === 'HTTP' ? {httpConfig: defaultHttpConfig()}" in canvas_jsx
    assert "headers: [emptyKeyValueRow('Content-Type', 'application/json')]" in canvas_jsx
    assert "function parseCurlRequest(command)" in canvas_jsx
    assert "parseCurl(normalized)" in canvas_jsx
    assert "splitShellWords(source)" in canvas_jsx
    assert "!explicitMethod && bodyType !== 'none' && parsed.method === 'GET'" in canvas_jsx
    assert "onChange({httpConfig: imported})" in canvas_jsx
    assert "node.data.nodeType === 'HTTP'" in canvas_jsx
    assert 'aria-label="请求方式"' in canvas_jsx
    assert 'aria-label="请求 URL"' in canvas_jsx
    assert 'aria-label="导入 cURL"' in canvas_jsx
    assert '><Upload size={15} /></button>' in canvas_jsx
    assert "['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']" in canvas_jsx
    assert "httpKeyValueSection('HEADERS', 'headers'" in canvas_jsx
    assert "httpKeyValueSection('PARAMS', 'params'" in canvas_jsx
    assert "['none', 'form-data', 'x-www-form-urlencoded', 'raw']" in canvas_jsx
    assert "JSON.stringify(JSON.parse(httpConfig.bodyText), null, 2)" in canvas_jsx
    assert "JSON 格式错误" in canvas_jsx
    assert "Beautify" in canvas_jsx
    assert 'aria-label="Proxy 模式"' in canvas_jsx
    assert 'aria-label="跟随重定向"' not in canvas_jsx
    assert 'aria-label="验证 SSL 证书"' not in canvas_jsx
    assert ".wf-http-api-row" in canvas_css
    assert "grid-template-columns: 70px 96px minmax(180px, 1fr) 34px" in canvas_css
    assert "padding-left: 20px" in canvas_css
    assert ".wf-http-kv-heading" in canvas_css
    assert ".wf-http-body-types" in canvas_css
    assert ".wf-http-code-toolbar" in canvas_css
    assert ".wf-http-code-editor" in canvas_css
    assert "const showCodeEditor = meta.executable && !isHttp && !isLlm" in canvas_jsx
    assert "const showParametersTab = !isHttp && !isLlm && !isScript" in canvas_jsx
    assert "{showCodeTab && <button" not in canvas_jsx
    assert "nodeType === 'HTTP' ? (" in canvas_jsx
    assert "function HttpLogSection({title, text})" in canvas_jsx
    assert '<HttpLogCopyButton text={text} label={`复制${title}`} />' in canvas_jsx
    assert 'pre aria-label={`${title}内容`}' in canvas_jsx
    assert "function HttpRequestLogSection({request})" in canvas_jsx
    assert "function rawHttpRequest(request)" in canvas_jsx
    assert "`${method} ${rawHttpRequestUrl(request)} HTTP/1.1`" in canvas_jsx
    assert "return [requestLine, ...headers, '', rawHttpRequestBody(request)].join('\\n')" in canvas_jsx
    assert 'return <HttpLogSection title="request" text={rawText} />' in canvas_jsx
    assert "<HttpRequestLogSection request={run.request} />" in canvas_jsx
    assert '<HttpLogSection title="response" text={responseContent} />' in canvas_jsx
    assert '<HttpLogSection title="request" text={requestContent} />' in canvas_jsx
    assert "复制字段路径" not in canvas_jsx
    assert "复制字段值" not in canvas_jsx
    for selector in (
        ".wf-http-log-section > header",
        ".wf-http-log-copy",
        ".wf-http-log-section > pre",
    ):
        assert selector in canvas_css
    assert "wf-http-postman" not in canvas_jsx
    assert "wf-http-postman" not in canvas_css
    assert "-webkit-user-select: text" in canvas_css
    assert "user-select: text" in canvas_css
    assert ".wf-http-log-section > pre::selection" in canvas_css
    http_log_title_rule = canvas_css[
        canvas_css.index(".wf-http-log-section > header > strong"):
        canvas_css.index(".wf-http-log-copy")
    ]
    assert "font-size: 14px" in http_log_title_rule
    assert "font-weight: 700" in http_log_title_rule
    raw_log_start = canvas_css.index(".wf-llm-run-detail > section > pre")
    raw_log_rule = canvas_css[raw_log_start:canvas_css.index("}", raw_log_start)]
    assert "font-size: var(--wf-raw-log-font-size)" in raw_log_rule
    http_log_branch = canvas_jsx[
        canvas_jsx.index("{nodeType === 'HTTP' ? ("):
        canvas_jsx.index(") : nodeType === 'SCRIPT' || nodeType === 'START' ? (")
    ]
    for excluded in ("wf-llm-run-meta", "run.stdout", "run.stderr", "tracebackContent"):
        assert excluded not in http_log_branch


def test_node_setting_section_headings_use_theme_contrast():
    canvas_css = (
        STATIC_DIR.parent / "frontend" / "workflow-canvas.css"
    ).read_text(encoding="utf-8")

    inspector_start = canvas_css.index(".wf-inspector {")
    inspector_block = canvas_css[inspector_start:canvas_css.index("}", inspector_start)]
    assert "--wf-heading: #111827" in inspector_block
    assert canvas_css.count("--wf-heading:") == 1
    for selector in (
        ".wf-inspector-body label > span",
        ".wf-llm-section-title",
        ".wf-llm-stream-field > span",
        ".wf-llm-advanced > button",
        ".wf-http-api-row > strong,",
        ".wf-http-collapse-button",
        ".wf-http-kv-heading > span,",
        ".wf-config-title",
        ".wf-config-section > button",
        ".wf-output-variable-row label > span",
    ):
        rule = canvas_css[
            canvas_css.index(selector):canvas_css.index("}", canvas_css.index(selector))
        ]
        assert "color: var(--wf-heading)" in rule


def test_canvas_defines_tool_nodes_only_inside_workflow():
    canvas_jsx = (
        STATIC_DIR.parent / "frontend" / "workflow-canvas.jsx"
    ).read_text(encoding="utf-8")
    canvas_css = (
        STATIC_DIR.parent / "frontend" / "workflow-canvas.css"
    ).read_text(encoding="utf-8")
    build_script = (
        STATIC_DIR.parents[1] / "scripts" / "build-workflow.mjs"
    ).read_text(encoding="utf-8")

    assert "const DEFAULT_AGENT_MAIN_PY = 'response = inputs'" in canvas_jsx
    assert "const DEFAULT_SCRIPT_MAIN_PY = 'msg = \"介绍一下自己\"\\nprint(msg)'" in canvas_jsx
    assert "function PythonCodeEditor({value, onChange})" in canvas_jsx
    assert 'font-family: "Droid Sans Mono Slashed"' in canvas_css
    assert 'src: url("/assets/fonts/DroidSansMonoSlashed.ttf") format("truetype")' in canvas_css
    assert 'external: ["/assets/*"]' in build_script
    assert "font-family: Inter, -apple-system, BlinkMacSystemFont, \"Segoe UI\", sans-serif" in canvas_css
    editor_start = canvas_css.index(".wf-python-editor .cm-editor {")
    editor_block = canvas_css[editor_start:canvas_css.index("}", editor_start)]
    assert 'font-family: Consolas, "SFMono-Regular", monospace' in editor_block
    assert "Droid Sans Mono Slashed" not in editor_block
    assert "font-family: var(--wf-font-family) !important" not in canvas_css
    assert "font-size: 16px" in canvas_css
    assert "--wf-heading: #111827" in canvas_css
    assert "grid-template-rows: auto 540px" in canvas_css
    assert "height: 540px" in canvas_css
    for title_selector in (
        ".wf-inspector header strong",
        ".wf-inspector-tabs button",
        ".wf-inspector-body label > span",
        ".wf-llm-section-title",
        ".wf-http-api-row > strong",
        ".wf-config-title",
    ):
        start = canvas_css.index(title_selector)
        title_block = canvas_css[start:canvas_css.index("}", start)]
        assert "color: var(--wf-heading)" in title_block
    inspector_start = canvas_css.index(".wf-inspector {")
    inspector_block = canvas_css[inspector_start:canvas_css.index("}", inspector_start)]
    for declaration in (
        '--wf-raw-log-background: #000000',
        '--wf-raw-log-color: #e3e8ef',
        '--wf-raw-log-font-family: Consolas, "SFMono-Regular", monospace',
        '--wf-raw-log-font-size: 14.3px',
        '--wf-raw-log-line-height: 1.6',
    ):
        assert declaration in inspector_block
    for log_selector in (
        ".wf-llm-run-detail > section > pre {",
        "textarea.wf-script-console {",
    ):
        start = canvas_css.index(log_selector)
        log_block = canvas_css[start:canvas_css.index("}", start)]
        assert "background: var(--wf-raw-log-background)" in log_block
        assert "color: var(--wf-raw-log-color)" in log_block
        assert "font-family: var(--wf-raw-log-font-family)" in log_block
        assert "font-size: var(--wf-raw-log-font-size)" in log_block
        assert "line-height: var(--wf-raw-log-line-height)" in log_block
    assert "grid-template-columns: 18px 130px 66px 80px minmax(0, 1fr)" in canvas_css
    run_summary_typography = canvas_css[
        canvas_css.index(".wf-llm-run-summary time,"):
        canvas_css.index(".wf-llm-run-summary strong")
    ]
    assert "font-size: 14px" in run_summary_typography
    result_start = canvas_css.index(".wf-llm-run-result {")
    result_block = canvas_css[result_start:canvas_css.index("}", result_start)]
    assert "font-size: 14px" in result_block
    assert "text-overflow: ellipsis" in result_block
    assert "white-space: nowrap" in result_block
    assert "python()" in canvas_jsx
    assert "oneDark" in canvas_jsx
    assert "EditorView.updateListener.of" in canvas_jsx
    assert "value={node.data.mainPy ?? (isScript ? DEFAULT_SCRIPT_MAIN_PY : DEFAULT_AGENT_MAIN_PY)}" in canvas_jsx
    assert "wf-embedded-code-editor wf-editor-full-row" in canvas_jsx
    assert canvas_jsx.index("wf-embedded-code-editor wf-editor-full-row") < canvas_jsx.index("wf-config-section wf-editor-full-row")
    assert ".wf-python-editor .cm-editor" in canvas_css
    assert "onChange={(mainPy) => onChange({mainPy})}" in canvas_jsx
    assert "makeNode(type, position)" in canvas_jsx
    assert "type === 'HTTP' ? {httpConfig: defaultHttpConfig()}" in canvas_jsx
    for removed in (
        "/api/tool-templates",
        "工具模板",
        "发布为工具模板",
        "toolTemplates",
        "templateLoadState",
        "templateDefinition",
        "httpConfigFromTemplate",
        "publishNode",
    ):
        assert removed not in canvas_jsx
    assert ".wf-template-popover" not in canvas_css
    assert ".wf-template-list" not in canvas_css


def test_llm_node_uses_saved_models_and_framework_independent_parameters():
    canvas_jsx = (
        STATIC_DIR.parent / "frontend" / "workflow-canvas.jsx"
    ).read_text(encoding="utf-8")
    canvas_css = (
        STATIC_DIR.parent / "frontend" / "workflow-canvas.css"
    ).read_text(encoding="utf-8")

    assert "...(type === 'LLM' ? {" in canvas_jsx
    assert "systemPrompt: ''" in canvas_jsx
    assert "userPrompt: ''" in canvas_jsx
    assert "modelParameters: {}" in canvas_jsx
    assert "fetch('/api/model-providers'" in canvas_jsx
    assert "function ModelSelector(" in canvas_jsx
    assert 'placeholder="搜索供应商或模型"' in canvas_jsx
    assert 'role="option"' in canvas_jsx
    assert "onSelect(provider.id, model)" in canvas_jsx
    assert "模型已失效" in canvas_jsx
    assert 'aria-label="模型高级参数 JSON"' in canvas_jsx
    assert "const LLM_PARAMETERS_REFERENCE = JSON.stringify({" in canvas_jsx
    assert "thinking: {type: 'disabled'}" in canvas_jsx
    assert "response_format: {type: 'json_object'}" in canvas_jsx
    assert "placeholder={LLM_PARAMETERS_REFERENCE}" in canvas_jsx
    assert "function modelParametersEditorText(parameters)" in canvas_jsx
    assert "if (!text.trim())" in canvas_jsx
    assert "const beautifyModelParameters = () =>" in canvas_jsx
    assert 'aria-label="格式化模型高级参数 JSON"' in canvas_jsx
    assert ".wf-llm-json-toolbar" in canvas_css
    assert ".wf-llm-json-editor > textarea::placeholder" in canvas_css
    llm_json_editor_start = canvas_css.index(".wf-llm-json-editor {")
    llm_json_editor_rule = canvas_css[
        llm_json_editor_start:canvas_css.index("}", llm_json_editor_start)
    ]
    assert "min-height: 314px" in llm_json_editor_rule
    assert "grid-template-rows: 34px minmax(280px, 1fr)" in llm_json_editor_rule
    llm_json_textarea_start = canvas_css.index(".wf-llm-json-editor > textarea {")
    llm_json_textarea_rule = canvas_css[
        llm_json_textarea_start:canvas_css.index("}", llm_json_textarea_start)
    ]
    assert "min-height: 280px" in llm_json_textarea_rule
    llm_placeholder_rule = canvas_css[
        canvas_css.index(".wf-llm-json-editor > textarea::placeholder"):
        canvas_css.index("}", canvas_css.index(".wf-llm-json-editor > textarea::placeholder"))
    ]
    assert "font-style: italic" in llm_placeholder_rule
    assert 'aria-label="系统提示词"' in canvas_jsx
    assert 'aria-label="用户提示词"' in canvas_jsx
    assert 'aria-label="插入提示词变量"' not in canvas_jsx
    assert "insertPromptVariable" not in canvas_jsx
    assert "if (!isPlainObject(parsed))" in canvas_jsx
    assert "delete parsed.stream" in canvas_jsx
    assert "onChange({modelParameters: parsed})" in canvas_jsx
    assert "请选择有效模型、填写用户提示词并修正高级参数" in canvas_jsx
    assert "const showCodeEditor = meta.executable && !isHttp && !isLlm" in canvas_jsx
    assert "{showCodeTab && <button" not in canvas_jsx
    assert "<NodeRunHistory runs={node.data.runHistory || []} nodeType={node.data.nodeType} />" in canvas_jsx
    assert ".slice(0, 10)" in canvas_jsx
    assert "formatRunDate(run.finished_at || run.started_at)" in canvas_jsx
    assert "function formatRunTokenUsage(run)" in canvas_jsx
    assert "function streamingUsageFromResponse(responseBody)" in canvas_jsx
    assert "streamingUsageFromResponse(run?.response_body) || {}" in canvas_jsx
    assert "if (isPlainObject(payload.message)) candidates.push(payload.message.usage)" in canvas_jsx
    assert "normalizeTokenCount(usage.total_tokens)" in canvas_jsx
    assert "normalizeTokenCount(usage.prompt_tokens)" in canvas_jsx
    assert "normalizeTokenCount(usage.completion_tokens)" in canvas_jsx
    assert "normalizeTokenCount(usage.input_tokens)" in canvas_jsx
    assert "normalizeTokenCount(usage.output_tokens)" in canvas_jsx
    assert "nodeType === 'LLM' && <span className=\"wf-llm-run-token\"" in canvas_jsx
    assert "formatRunTokenUsage(run)" in canvas_jsx
    assert '<HttpLogSection title="response" text={responseContent} />' in canvas_jsx
    assert '<HttpLogSection title="inputs" text={inputsContent} />' in canvas_jsx
    assert '<HttpLogSection title="outputs" text={outputsContent} />' in canvas_jsx
    assert "nodeType === 'SCRIPT' || nodeType === 'START'" in canvas_jsx
    assert "['START', 'HTTP', 'AGENT', 'LLM', 'SCRIPT'].includes" in canvas_jsx
    assert "event.clipboardData.setData('text/plain', text)" in canvas_jsx
    assert "event.stopImmediatePropagation()" in canvas_jsx
    assert "fetch('/api/local/clipboard'" in canvas_jsx
    assert canvas_jsx.index("fetch('/api/local/clipboard'") < canvas_jsx.index("navigator.clipboard?.writeText")
    assert "user-select: text" in canvas_css
    assert "run.response" in canvas_jsx
    assert '<HttpLogSection title="request" text={requestContent} />' in canvas_jsx
    assert "原始 response" not in canvas_jsx
    assert "error details" in canvas_jsx
    assert "输入快照" not in canvas_jsx
    assert "Token usage" not in canvas_jsx
    assert 'role="switch" aria-label="流式输出"' in canvas_jsx
    assert "checked={streamEnabled}" in canvas_jsx
    assert "setStreamMode(event.target.checked)" in canvas_jsx
    assert "const showOutputVariables = !isLlm || !streamEnabled" in canvas_jsx
    assert "{showOutputVariables && (" in canvas_jsx
    assert "fetch(`/api/workflows/${encodeURIComponent(activeWorkflowId)}/runs`" in canvas_jsx
    assert "/cancel`" in canvas_jsx
    assert 'aria-label="查看节点变量"' in canvas_jsx
    assert 'aria-label="节点可用变量"' in canvas_jsx
    assert "copyTextToClipboard(parameterDataText(variable.value, true))" in canvas_jsx
    assert "await navigator.clipboard.writeText(text)" in canvas_jsx
    assert "catch (_error)" in canvas_jsx
    assert "textarea.setSelectionRange(0, textarea.value.length)" in canvas_jsx
    assert "document.execCommand('copy')" in canvas_jsx
    assert 'aria-label={`复制变量值 ${variable.name}`}' in canvas_jsx
    assert "disabled={!variable.available}" in canvas_jsx
    assert "全局变量" in canvas_jsx
    assert "/variables`" not in canvas_jsx
    assert "const activeWorkflowId = await persistDraft({forNodeRun: true});" not in canvas_jsx
    assert "activeWorkflowId = await persistDraft();" in canvas_jsx
    assert "/api/workflows/${encodeURIComponent(activeWorkflowId)}/runs" in canvas_jsx
    assert "['START', 'HTTP', 'AGENT', 'LLM', 'SCRIPT'].includes(targetNode?.data.nodeType)" in canvas_jsx
    assert "apiKey" not in canvas_jsx
    assert "api_key" not in canvas_jsx
    assert "model_kwargs" not in canvas_jsx
    assert ".wf-model-picker" in canvas_css
    assert ".wf-model-provider-group" in canvas_css
    assert ".wf-model-option.is-selected" in canvas_css
    assert ".wf-llm-prompt-field" in canvas_css
    assert ".wf-inspector-body .wf-llm-stream-switch" in canvas_css
    assert "width: 34px" in canvas_css
    assert "height: 19px" in canvas_css
    assert "grid-template-columns: none" in canvas_css
    assert "className=\"wf-llm-model-row\"" in canvas_jsx
    assert ".wf-llm-model-row" in canvas_css
    assert "grid-template-columns: minmax(0, 1fr) max-content" in canvas_css
    assert "grid-template-columns: max-content 34px" in canvas_css
    assert ".wf-llm-stream-field > span" in canvas_css
    assert "min-height: 19px" in canvas_css
    assert "font-weight: 700" in canvas_css
    assert ".wf-llm-stream-control" not in canvas_css
    assert ".wf-llm-run-summary" in canvas_css
    assert ".wf-llm-run-summary.has-token-usage" in canvas_css
    assert "grid-template-columns: 18px 130px 66px 80px 112px minmax(0, 1fr)" in canvas_css
    assert ".wf-llm-run-token" in canvas_css
    assert ".wf-llm-run-detail" in canvas_css
    assert ".wf-node-variable-panel" in canvas_css
    assert ".wf-node-variable-row button" in canvas_css
    assert "minmax(0, 1.6fr) 28px" in canvas_css
    assert "const [editorScale, setEditorScale] = useState(1)" in canvas_jsx
    assert "const editorBaseSizeRef = useRef(null)" in canvas_jsx
    assert "const updateEditorScale = (_event, _direction, ref)" in canvas_jsx
    assert "onResize={updateEditorScale}" in canvas_jsx
    assert "onResizeStop={updateEditorScale}" in canvas_jsx
    assert "className=\"wf-inspector-scale-shell\"" in canvas_jsx
    assert "transform: `scale(${editorScale})`" in canvas_jsx
    assert ".wf-inspector-scale-shell" in canvas_css
    assert "@media" not in canvas_css
