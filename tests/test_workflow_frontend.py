import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_workflow_list_calls_only_new_structural_api():
    javascript = read("web/static/execution.js")

    assert "function viewWorkflows()" in javascript
    assert "function workflowCanvasSaveBody(draft)" in javascript
    assert "API.get('/api/workflows')" in javascript
    assert "API.post('/api/workflows', body)" in javascript
    assert "'/metadata'" in javascript
    assert "/api/workflow-drafts" not in javascript
    assert "global_variables" not in javascript


def test_api_client_handles_json_and_plain_text_errors_without_parse_failure():
    javascript = read("web/static/app.js")

    assert "async function apiResponsePayload(res)" in javascript
    assert "var text = await res.text();" in javascript
    assert "try { payload = JSON.parse(text); }" in javascript
    assert "detail.map(function (item)" in javascript
    assert "detail || text || res.statusText" in javascript


def test_canvas_matches_current_structural_contract():
    source = read("web/frontend/workflow-canvas.jsx")
    javascript = read("web/static/execution.js")

    assert "const INSERTABLE_TYPES = ['HTTP', 'LLM', 'SCRIPT'];" in source
    assert "const start = makeNode('START'" in source
    assert "const end = makeNode('END'" in source
    assert "START 输入" in source
    assert "Python 变量" in source
    assert "流式输出" not in source
    assert "llmMessages: cloneLlmMessages(DEFAULT_LLM_MESSAGES)" in source
    assert "context: {\n                messages:" in javascript
    assert "prompt: {system:" not in javascript
    assert "systemPrompt" not in source
    assert "userPrompt" not in source
    assert "全局变量" not in source
    assert "AGENT:" not in source


def test_workflow_canvas_follows_application_theme():
    source = read("web/frontend/workflow-canvas.jsx")
    styles = read("web/frontend/workflow-canvas.css")

    assert "function useDocumentTheme()" in source
    assert "new MutationObserver(() => setTheme(documentTheme()))" in source
    assert "colorMode={theme}" in source
    assert "theme === 'dark' ? '#3a4656' : '#c8d1de'" in source
    assert "theme === 'dark' ? 'rgba(15, 20, 27, 0.72)'" in source
    assert "--wf-node-bg: #ffffff;" in styles
    assert "--wf-node-bg: #20262e;" in styles
    assert "--wf-edge: #718096;" in styles
    assert "background: var(--wf-toolbar-bg);" in styles
    assert "stroke: var(--wf-edge);" in styles
    assert ':root[data-theme="dark"] .wf-inspector {' in styles
    assert ':root[data-theme="dark"] .wf-inspector-body input,' in styles
    assert ':root[data-theme="dark"] .wf-readonly-field,' in styles
    assert ':root[data-theme="dark"] .wf-node-variable-panel,' in styles
    assert ':root[data-theme="dark"] .wf-http-request-section {' in styles
    assert ':root[data-theme="dark"] .wf-http-table-row.is-heading,' in styles
    assert "background: #181e26;" in styles
    assert "--wf-button-bg: #ffffff;" in styles
    assert "--wf-button-bg: #20262e;" in styles
    assert ".wf-header-actions button,\n.wf-http-import-button," in styles
    assert ".wf-icon-button,\n.wf-header-popover > header button," in styles
    assert ".workflow-studio-shell button:focus-visible {" in styles
    assert ':root[data-theme="dark"] .wf-context-menu,' in styles
    assert ':root[data-theme="dark"] .wf-node-picker {' in styles
    assert "background: var(--wf-surface);" in styles
    assert ':root[data-theme="dark"] .wf-node-picker button > span:first-child {' in styles
    assert ':root[data-theme="dark"] .wf-menu-separator {' in styles
    assert ':root[data-theme="dark"] .wf-context-menu > button.is-danger {' in styles
    assert ".wf-execution-history-panel {" in styles
    assert ".wf-execution-history-summary:hover {\n    background: var(--wf-soft);" in styles
    assert ".wf-execution-history-empty {" in styles
    assert ':root[data-theme="dark"] .wf-node-test-badge {' in styles
    assert "background: #173d31;" in styles
    history_panel = styles[styles.index(".wf-execution-history-panel {"):styles.index("}", styles.index(".wf-execution-history-panel {"))]
    node_picker = styles[styles.index(".wf-node-picker {"):styles.index("}", styles.index(".wf-node-picker {"))]
    context_menu = styles[styles.index(".wf-context-menu {"):styles.index("}", styles.index(".wf-context-menu {"))]
    assert "background: var(--wf-surface);" in history_panel
    assert "background: var(--wf-surface);" in node_picker
    assert "background: var(--wf-surface);" in context_menu


def test_llm_inspector_supports_few_shot_drafts_and_run_only_validation():
    source = read("web/frontend/workflow-canvas.jsx")
    javascript = read("web/static/execution.js")
    styles = read("web/frontend/workflow-canvas.css")

    assert "消息按从上到下的顺序发送" not in source
    assert "SYSTEM -> USER -> (ASSISTANT -> USER)..." not in source
    assert ".wf-llm-context-intro" not in styles
    assert "const llmSaveAllowed = true;" in source
    assert "const llmRunReady = !isLlm || (" in source
    assert "llmErrors.size === 0" in source
    assert "modelParametersText: text" in source
    assert "parameters_text: data.modelParametersText || ''" in javascript
    assert 'className="wf-llm-message"' in source
    assert "wf-llm-message is-" not in source
    assert "has-error" not in source
    assert 'aria-invalid={Boolean(error)}' in source
    assert 'title={error || undefined}' in source
    assert "border-left: 3px solid #7b55c7;" in styles
    assert ".wf-llm-message.is-system" not in styles
    assert ".wf-llm-message.is-user" not in styles
    assert ".wf-llm-message.is-assistant" not in styles
    assert ".wf-llm-message.has-error" not in styles
    assert ".wf-llm-add-message" in styles
    assert "wf-llm-context-warning" not in source
    assert "wf-llm-context-warning" not in styles
    assert '<section className="wf-llm-context-section" aria-label="LLM 高级参数">' in source
    assert '<div><Settings2 size={15} /><strong>高级参数</strong></div>' in source


def test_canvas_uses_dify_style_drag_guides_without_alignment_actions_or_snapping():
    source = read("web/frontend/workflow-canvas.jsx")
    alignment = read("web/frontend/workflow-alignment.mjs")
    styles = read("web/frontend/workflow-canvas.css")

    assert "export const ALIGNMENT_GUIDE_THRESHOLD = 5;" in alignment
    assert "export function calculateAlignmentGuides(nodes, draggingNode" in alignment
    assert "onNodeDrag={(event, node) =>" in source
    assert "calculateAlignmentGuides(getNodes(), node)" in source
    assert "onNodeDragStop={() =>" in source
    assert "setAlignmentGuides(null);\n                        setSaveState('未保存');" in source
    assert '<AlignmentGuides guides={alignmentGuides} />' in source
    assert ".wf-alignment-guide.is-horizontal" in styles
    assert ".wf-alignment-guide.is-vertical" in styles
    assert "alignCanvasNodes" not in source
    assert "wf-alignment-actions" not in source
    assert "wf-alignment-actions" not in styles
    for label in ("左对齐", "水平居中", "右对齐", "顶部对齐", "垂直居中", "底部对齐"):
        assert f'aria-label="{label}"' not in source


def test_new_and_existing_workflows_open_at_readable_fit_view():
    source = read("web/frontend/workflow-canvas.jsx")

    assert "await fitView({padding: 0.16, duration: 0});" in source
    assert "INITIAL_OVERVIEW_SCALE" not in source
    assert "getViewport" not in source
    assert "setViewport" not in source
    assert "window.setTimeout(() => void fitInitialOverview(), 0);" in source
    assert 'minZoom={0.1}' in source


def test_workflow_canvas_and_controls_fit_standard_desktop():
    styles = read("web/frontend/workflow-canvas.css")

    assert "min-width: 960px;" in styles
    assert "min-width: 1180px;" not in styles
    assert ".wf-node-actions button {" in styles
    assert "width: 28px;" in styles


def test_business_node_context_menu_replaces_type_with_new_identity_and_preserved_edges():
    source = read("web/frontend/workflow-canvas.jsx")

    assert "function replaceCanvasNode(nodes, edges, currentNodeId, targetType)" in source
    assert "...makeNode(targetType, {...currentNode.position})" in source
    assert "source: edge.source === currentNodeId ? replacement.id : edge.source" in source
    assert "target: edge.target === currentNodeId ? replacement.id : edge.target" in source
    assert "<span>更换节点</span>" in source
    assert "excludeType={menu.nodeType}" in source
    assert "INSERTABLE_TYPES.includes(menu.nodeType)" in source
    assert "setSelectedNodeIds((current) => current.map" in source
    assert "setSaveState('未保存');" in source
    assert "节点运行期间不能更换类型" in source
    assert "wf-node-runtime" not in source


def test_canvas_node_tests_are_ephemeral_and_independent_from_workflow_runs():
    source = read("web/frontend/workflow-canvas.jsx")
    javascript = read("web/static/execution.js")

    assert "function NodeTestVariablesDialog" in source
    assert "options.serializeNode = workflowCanvasNode" in javascript
    assert "/node-tests`" in source
    assert "/node-tests/${encodeURIComponent(testId)}/events" in source
    assert "/node-tests/${encodeURIComponent(active.testId)}/cancel" in source
    assert "onRun: () => requestNodeTest(node.id)" in source
    assert "onInterrupt: () => interruptNodeTest(node.id)" not in source
    assert 'aria-label={`中断 ${data.label}`}' not in source
    assert 'aria-label="中断当前节点"' not in source
    assert "onAction('interrupt-node')" not in source
    assert "onClick={interruptWorkflow}" in source
    assert "interruptNodeTest" in source
    assert "run.isTemporary" in source
    assert "temporaryRun={node.data.temporaryRun || null}" in source
    assert "data.nodeType !== 'END'" in source
    assert "onRun: runAll" not in source
    assert "friendlyNodeError(data.snapshot.error, '节点临时测试失败')" in source
    assert "friendlyNodeError(failedNode?.error || run.error, 'Workflow 执行失败')" in source


def test_running_workflow_nodes_increment_elapsed_time_from_started_at():
    source = read("web/frontend/workflow-canvas.jsx")
    timing = read("web/frontend/workflow-execution-timing.mjs")

    assert "import {workflowNodeExecutionDuration} from './workflow-execution-timing.mjs';" in source
    assert "if (run?.status !== 'RUNNING') return reportedDurationMs;" in timing
    assert "const startedAtMs = new Date(run.started_at).getTime();" in timing
    assert "Math.max(reportedDurationMs, previousDurationMs, nowMs - startedAtMs)" in timing
    assert "executionDurationMs: workflowNodeExecutionDuration(run, node.data.executionDurationMs)" in source


def test_closing_canvas_keeps_workflow_running_in_background():
    source = read("web/frontend/workflow-canvas.jsx")
    styles = read("web/frontend/workflow-canvas.css")

    close = source[source.index("const close = useCallback(() => {"):source.index("const closeInspector")]
    assert "studioClosedRef.current = true;" in close
    assert "interruptWorkflow" not in close
    assert "if (studioClosedRef.current) return;" in source
    assert ".wf-node-status.is-running i {\n    background: #2563eb;\n}" in styles
    assert ".wf-node-runtime" not in styles
    node_execution = styles[styles.index(".wf-node-execution {"):styles.index("}", styles.index(".wf-node-execution {"))]
    assert "font-size: 11px;" in node_execution


def test_canvas_header_omits_execution_directory_button():
    source = read("web/frontend/workflow-canvas.jsx")

    assert "openExecutionDirectory" not in source
    assert "FolderOpen" not in source
    assert ">执行记录</button>" not in source
    assert "<FileClock size={15} />历史" in source


def test_llm_run_log_omits_provider_and_model_metadata_caption():
    source = read("web/frontend/workflow-canvas.jsx")
    styles = read("web/frontend/workflow-canvas.css")

    assert "`${run.model.provider_id} / ${run.model.model_name}`" not in source
    assert "wf-llm-run-meta" not in source
    assert ".wf-llm-run-meta" not in styles


def test_http_log_prints_execution_model_request_without_reconstruction():
    source = read("web/frontend/workflow-canvas.jsx")

    assert "const requestContent = run.request ? parameterDataText(run.request, true) : '';" in source
    assert '{requestContent && <HttpLogSection title="request" text={requestContent} />}' in source
    assert "function rawHttpRequest(" not in source
    assert "function rawHttpRequestBody(" not in source
    assert "function HttpRequestLogSection(" not in source


def test_available_variables_use_latest_node_execution_outputs():
    source = read("web/frontend/workflow-canvas.jsx")

    assert "const loadLatestWorkflowNodeExecutions = useCallback" in source
    assert "cache: 'no-store'" in source
    assert "latestNodeExecutions.map((execution) => [execution.node_id, execution])" in source
    assert "const persistedOutputs = isPlainObject(latestExecution?.outputs)" in source
    assert "Object.prototype.hasOwnProperty.call(executionOutputs, row.name)" in source
    assert "value: available ? executionOutputs[row.name] : null" in source


def test_business_nodes_use_seconds_for_timeout_retry_interval_and_initial_delay():
    source = read("web/frontend/workflow-canvas.jsx")
    javascript = read("web/static/execution.js")

    assert "单次超时（秒）" in source
    assert "重试间隔（秒）" in source
    assert "延迟执行（秒）" in source
    assert "timeoutSeconds: 600" in source
    assert "node.execution ? node.execution.timeout_seconds : 600" in javascript
    assert "retryIntervalSeconds: 0" in source
    assert "delaySeconds: 0" in source
    assert "timeout_seconds: timeoutSeconds" in javascript
    assert "retry_interval_seconds: retryIntervalSeconds" in javascript
    assert "delay_seconds: delaySeconds" in javascript
    assert "node.execution.timeout_seconds" in javascript
    assert "node.execution.retry_interval_seconds" in javascript
    assert "node.execution.delay_seconds" in javascript
    assert "timeout_ms" not in javascript
    assert "delay_ms" not in javascript
    assert "available: false" not in source


def test_http_inspector_uses_approved_request_settings_layout():
    source = read("web/frontend/workflow-canvas.jsx")
    styles = read("web/frontend/workflow-canvas.css")

    for label in ("请求设置", "Endpoint", "Headers", "Params", "Body", "Request Options"):
        assert label in source
    assert "function HttpMethodSelector" in source
    assert "function HttpAccordion" in source
    assert "function HttpKeyValueTable" in source
    assert "function HttpToggle" in source
    assert "wf-http-request-section" in styles
    assert "wf-http-accordion.is-last" in styles
    assert ".wf-http-api-section" not in styles
    assert ".wf-http-network-section" not in styles
    assert ">API<" not in source


def test_node_inspector_stays_inside_canvas_after_resize_and_drag():
    source = read("web/frontend/workflow-canvas.jsx")

    assert "import {clampInspectorPosition}" in source
    assert "const editorRndRef = useRef(null);" in source
    assert "ref={editorRndRef}" in source
    assert "onResizeStop={finishEditorResize}" in source
    assert "onDragStop={finishEditorDrag}" in source
    assert "parentWidth: parent.clientWidth" in source
    assert "parentHeight: parent.clientHeight" in source


def test_http_toggles_match_provider_switch_with_green_checked_feedback():
    styles = read("web/frontend/workflow-canvas.css")

    assert '.wf-http-toggle input:checked + i {' in styles
    assert ':root[data-theme="dark"] .wf-http-toggle input:checked + i {' in styles
    assert "--wf-switch-on: #2ea44f;" in styles
    assert "--wf-switch-on: #3fb950;" in styles
    assert "height: 18px;" in styles
    assert "border-radius: 9px;" in styles
    assert "width: 12px;" in styles
    assert "height: 12px;" in styles
    assert "transform: translateX(16px);" in styles
    assert "background: var(--wf-switch-on);" in styles
    assert ".wf-http-toggle:active > i" in styles


def test_http_url_trims_on_blur_and_workflow_serialization():
    source = read("web/frontend/workflow-canvas.jsx")
    javascript = read("web/static/execution.js")

    assert "onBlur={(event) => updateHttpConfig({url: event.currentTarget.value.trim()})}" in source
    assert "url: String(config.url || '').trim()" in javascript
    assert ">NETWORK<" not in source


def test_http_hidden_options_and_json_values_round_trip_without_type_loss():
    source = read("web/frontend/workflow-canvas.jsx")
    javascript = read("web/static/execution.js")

    assert "successStatuses: ['200-299']" in source
    assert "retryNonIdempotent: false" in source
    assert "retryStatuses: [408, 429, 500, 502, 503, 504]" in source
    assert "function workflowHttpValueRow(row)" in javascript
    assert "originalValue: row.value" in javascript
    assert "row.value === row.originalText" in javascript
    assert "params: (node.request.params || []).map(workflowHttpValueRow)" in javascript
    assert "successStatuses: node.response.success_statuses.slice()" in javascript
    assert "retryStatuses: node.execution.retry_statuses.slice()" in javascript
    assert "params: filteredHttpValueRows(config.params" in javascript
    assert "retry_non_idempotent: Boolean(config.retryNonIdempotent)" in javascript


def test_node_inspector_enforces_shared_control_and_section_rules():
    styles = read("web/frontend/workflow-canvas.css")

    assert "--wf-control-gap: 10px" in styles
    assert "--wf-compact-select-width: 96px" in styles
    assert "--wf-section-divider: #dfe5ed" in styles
    assert ".wf-inspector select {\n    color-scheme: light;" in styles
    assert ".wf-http-request-section + .wf-config-section" in styles
    assert ".wf-llm-model-section + .wf-config-section" in styles
    assert ".wf-output-variable-row select {\n    width: var(--wf-compact-select-width);" in styles
    assert "grid-template-columns: minmax(150px, 0.8fr) var(--wf-compact-select-width)" in styles


def test_available_variables_include_dag_ancestors_current_draft_and_temporary_outputs():
    source = read("web/frontend/workflow-canvas.jsx")

    assert "function variableScopeNodes(nodes, edges, targetNodeId)" in source
    assert "const visible = variableScopeNodes(nodes, edges, id)" in source
    assert "node.data.temporaryRun?.outputs" in source
    assert "const executionOutputs = temporaryOutputs || persistedOutputs" in source
    assert "const toggleVariables = () => setVariablesOpen((open) => !open)" in source
    assert "if (!variablesOpen || !node) return undefined" in source


def test_end_node_exposes_explicit_workflow_result_mappings():
    source = read("web/frontend/workflow-canvas.jsx")
    adapter = read("web/static/execution.js")

    assert "const isEnd = node.data.nodeType === 'END';" in source
    assert "const showOutputVariables = meta.executable || isEnd;" in source
    assert "isEnd ? '最终结果' : '运行配置'" in source
    assert "isEnd ? '结果字段' : '输出变量'" in source
    assert "isEnd ? 'Context 路径' : '提取表达式'" in source
    assert "if (data.nodeType === 'END') return Object.assign(common, {outputs: outputBindings(node)});" in adapter


def test_built_workflow_assets_exist_and_are_nonempty():
    script = ROOT / "web/static/assets/workflow-canvas.js"
    styles = ROOT / "web/static/assets/workflow-canvas.css"

    assert script.stat().st_size > 500_000
    assert styles.stat().st_size > 20_000


def test_workflow_bundle_uses_cache_busting_version():
    html = read("web/static/index.html")
    build_script = read("scripts/build-workflow.mjs")

    assert re.search(r'/assets/workflow-canvas\.css\?v=[0-9a-f]{12}', html)
    assert re.search(r'/assets/workflow-canvas\.js\?v=[0-9a-f]{12}', html)
    assert re.search(r'/execution\.js\?v=[0-9a-f]{12}', html)
    assert 'createHash("sha256")' in build_script
    assert 'indexContent.replace(' in build_script
    assert 'versionedWorkflowIndex.replace(' in build_script


def test_llm_advanced_parameters_are_protocol_specific():
    source = read("web/frontend/workflow-canvas.jsx")

    assert "OPENAI_COMPATIBLE: 'OpenAI Chat Completions'" in source
    assert "OPENAI_RESPONSES: 'OpenAI Responses API'" in source
    assert "ANTHROPIC: 'Anthropic Claude Messages'" in source
    assert "function llmParametersReference(protocol)" in source
    assert "function modelParametersProtocolError(protocol, parameters)" in source
    assert "placeholder={llmParametersReference(selectedModelProtocol)}" in source
    assert "&& !protocolParametersError" in source


def test_workflow_header_groups_description_with_title_and_hides_saved_marker():
    source = read("web/frontend/workflow-canvas.jsx")
    styles = read("web/frontend/workflow-canvas.css")

    header = source[source.index('<header className="wf-studio-header">'):source.index('<main className="wf-canvas-wrap"')]
    left = header[header.index('<div className="wf-header-left">'):header.index('<div className="wf-header-actions">')]

    assert 'className={`wf-header-description ${descriptionEditing ? \'is-editing\' : \'\'}`}' in left
    assert 'className="wf-save-state"' not in header
    assert "metadataDraft.current.name === workflowName ? event.currentTarget.value : metadataDraft.current.name" in left
    assert "metadataDraft.current.description === workflowDescription ? event.currentTarget.value : metadataDraft.current.description" in left
    assert "metadataDraft.current.name = event.target.value" in left
    assert "metadataDraft.current.description = event.target.value" in left
    assert "grid-template-columns: minmax(420px, 1fr) minmax(500px, auto);" in styles


def test_workflow_editing_has_explicit_keyboard_reachable_entries():
    source = read("web/frontend/workflow-canvas.jsx")

    assert 'title="编辑工作流名称"' in source
    assert 'title="编辑工作流说明"' in source
    assert 'aria-label={`配置 ${data.label}`}' in source
    assert "data.onConfigure?.();" in source
    assert "onConfigure: () =>" in source
    assert "function useDialogAccessibility(onClose, active = true)" in source
    assert 'className="wf-node-test-dialog" role="dialog"' in source
