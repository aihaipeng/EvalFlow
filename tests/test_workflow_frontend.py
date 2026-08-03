import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    source = (ROOT / path).read_text(encoding="utf-8")
    if path == "web/frontend/workflow-canvas.jsx":
        implementation = (ROOT / "web/frontend/workflow-canvas-implementation.jsx").read_text(encoding="utf-8")
        return source + "\n" + implementation
    return source


def test_workflow_list_calls_only_new_structural_api():
    javascript = read("web/static/execution.js")

    assert "function viewWorkflows()" in javascript
    assert "function workflowCanvasSaveBody(draft)" in javascript
    assert "API.get('/api/workflows')" in javascript
    assert "API.post('/api/workflows' + validationQuery, body)" in javascript
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


def test_pane_node_picker_hides_existing_start_and_end_nodes():
    source = read("web/frontend/workflow-canvas.jsx")

    assert "excludeTypes={unavailableSystemTypes}" in source
    assert "unavailableSystemTypes={nodes" in source
    assert ".filter((node) => ['START', 'END'].includes(node.data.nodeType))" in source
    assert "nodes.some((node) => node.data.nodeType === type)" in source


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
    assert "--wf-variable-name: var(--color-success);" in styles
    assert "--wf-variable-value: #ffffff;" in styles
    assert "color: var(--wf-variable-name);" in styles
    assert "color: var(--wf-variable-value);" in styles
    assert "width: min(560px, calc(100% - 32px));" in styles
    assert "@font-face" not in styles
    assert "/assets/fonts/" not in styles
    assert "grid-template-columns: minmax(160px, 0.85fr) minmax(0, 1.6fr) 32px;" in styles
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
    assert "background: color-mix(in srgb, var(--color-success) 14%, var(--surface));" in styles
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
    assert "LLM_MESSAGE_HINTS" not in source
    assert "CircleHelp" not in source
    assert "为对话提供高层指导(通过${变量名}引用上下文)" in source
    assert "向模型提供指令、查询或任何基于文本的输入(通过${变量名}引用上下文)" in source
    assert "基于用户消息的模型回复(通过${变量名}引用上下文)" in source
    assert "min-height: 140px;" in styles
    assert "font-size: 14px;" in styles
    assert "const [expandedLlmMessageId, setExpandedLlmMessageId] = useState(null);" in source
    assert 'className="wf-llm-message-expand"' in source
    assert "<Maximize2 size={16} />" in source
    assert 'className="wf-llm-editor-overlay"' in source
    assert 'className="wf-llm-editor-dialog"' in source
    assert "function MarkdownPromptEditor({" in source
    assert "import {markdown} from '@codemirror/lang-markdown';" in source
    assert "templateVariableHighlighter" in source
    assert "createTemplateVariablePattern()" in source
    assert source.count("<MarkdownPromptEditor") == 2
    assert "updateLlmMessage(expandedLlmMessage.id, content)" in source
    assert "updateLlmMessage(expandedLlmMessage.id, event.target.value)" not in source
    assert "expandedLlmTriggerRef.current = event.currentTarget;" in source
    assert "expandedLlmTriggerRef.current?.focus();" in source
    assert "width: min(80vw, 1120px);" in styles
    assert "height: 75vh;" in styles
    assert "has-error" not in source
    assert "'aria-invalid': error ? 'true' : 'false'" in source
    assert 'title={error || undefined}' in source
    assert ".wf-markdown-editor .cm-template-variable" in styles
    assert ".wf-markdown-editor.is-expanded .cm-content" in styles
    assert ':root[data-theme="dark"] .wf-markdown-editor .cm-template-variable' in styles
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


def test_node_save_is_scoped_and_dirty_inspector_exit_requires_a_choice():
    source = read("web/frontend/workflow-canvas.jsx")
    javascript = read("web/static/execution.js")

    save_node = source[
        source.index("const saveNode = useCallback"):
        source.index("const applyWorkflowNodeRuns")
    ]
    inspector_exit = source[
        source.index("const finishInspectorExit = useCallback"):
        source.index("const canUndo")
    ]
    assert "options.onPersistNode" in save_node
    assert "const nodeForSave = trimTrailingEmptyLlmNodeMessages(node);" in save_node
    assert "node: serializableNode(nodeForSave)" in save_node
    assert "const cleanedItem = trimTrailingEmptyLlmNodeMessages(item);" in save_node
    assert "persistDraft" not in save_node
    assert "const nodesForSave = nodes.map(trimTrailingEmptyLlmNodeMessages);" in source
    assert "nodes: nodesForSave.map(serializableNode)" in source
    assert "const cleanedNode = trimTrailingEmptyLlmNodeMessages(node);" in source
    assert "activeNode?.data.isDirty" in inspector_exit
    assert "setNodeLeaveRequest(request);" in inspector_exit
    assert "editorNodeBaselineRef.current" in inspector_exit
    assert "cloneValue(baseline.data)" in inspector_exit
    assert "const saved = await saveNode(request.nodeId);" in inspector_exit
    assert "if (!saved) return false;" in inspector_exit
    assert "const openInspector = useCallback" in source
    assert "editorNodeId !== nodeId" in source
    assert 'title="保存节点修改？"' in source
    assert 'secondaryLabel="不保存"' in source
    assert "options.onPersistNode = async function (draft)" in javascript
    assert "'/nodes/' + encodeURIComponent(draft.node.id)" in javascript
    assert "nodes: [nodeWrite]" in javascript
    assert "edges: []" in javascript


def test_explicit_workflow_save_requests_structure_validation_only():
    source = read("web/frontend/workflow-canvas.jsx")
    javascript = read("web/static/execution.js")

    save = source[source.index("const save = useCallback"):source.index("useEffect", source.index("const save = useCallback"))]
    assert "persistDraft({validateStructure: true})" in save
    assert "var validationQuery = draft.validateStructure ? '?validate_structure=true' : '';" in javascript
    assert "persistDraft({forNodeRun: true})" in source


def test_running_workflow_nodes_increment_elapsed_time_from_started_at():
    source = read("web/frontend/workflow-canvas.jsx")
    timing = read("web/frontend/workflow-execution-timing.mjs")

    assert "resetWorkflowNodeForRun, workflowNodeExecutionDuration, workflowNodeLiveDuration" in source
    assert "if (run?.status !== 'RUNNING') return reportedDurationMs;" in timing
    assert "const startedAtMs = new Date(run.started_at).getTime();" in timing
    assert "Math.max(reportedDurationMs, previousDurationMs, nowMs - startedAtMs)" in timing
    assert "executionDurationMs: workflowNodeExecutionDuration(run, node.data.executionDurationMs)" in source
    assert "executionStartedAt: run.status === 'RUNNING' ? run.started_at : null" in source
    assert "const nowMs = workflowRunRef.current.startedAtMs + workflowElapsedMs;" in source
    assert "const liveDurationMs = workflowNodeLiveDuration(node.data, nowMs);" in source
    assert "executionDurationMs: liveDurationMs" in source


def test_starting_a_workflow_resets_every_node_to_pending():
    source = read("web/frontend/workflow-canvas.jsx")

    assert "import {resetWorkflowNodeForRun, workflowNodeExecutionDuration, workflowNodeLiveDuration}" in source
    run_all = source[source.index("const runAll = useCallback"):source.index("const deleteElements")]
    assert "setNodes((current) => current.map(resetWorkflowNodeForRun));" in run_all


def test_closing_canvas_keeps_workflow_running_in_background():
    source = read("web/frontend/workflow-canvas.jsx")
    styles = read("web/frontend/workflow-canvas.css")

    close = source[source.index("const performClose = useCallback(() => {"):source.index("const closeInspector")]
    assert "studioClosedRef.current = true;" in close
    assert "interruptWorkflow" not in close
    assert "const close = useCallback(() => {" in source
    assert "performClose();" in close
    assert "if (studioClosedRef.current) return;" in source
    assert ".wf-node-status.is-running i {\n    background: var(--color-accent);\n}" in styles
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


def test_node_history_loads_only_in_logs_tab_without_overwriting_canvas_status():
    source = read("web/frontend/workflow-canvas.jsx")

    assert "onLoadRunsRef.current = onLoadRuns;" in source
    assert "if (tab !== 'logs' || !node) return;" in source
    assert "void onLoadRunsRef.current();" in source
    assert "loadNodeRuns(targetNode.id);" not in source
    assert "/nodes/${encodeURIComponent(id)}/runs" in source
    assert "/runs/${encodeURIComponent(execution.id)}/nodes" not in source
    assert "status: runs[0]?.status || 'PENDING'" not in source
    assert "executionDurationMs: runs[0]?.duration_ms || 0" not in source


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
    assert "--wf-switch-on: var(--color-success);" in styles
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


def test_executable_nodes_share_compact_output_variable_field_order():
    source = read("web/frontend/workflow-canvas.jsx")
    styles = read("web/frontend/workflow-canvas.css")

    assert "const showOutputVariables = meta.executable;" in source
    assert 'className="wf-inspector" aria-label="节点配置" data-node-type={node.data.nodeType}' in source
    assert 'data-node-type={node.data.nodeType}' in source
    name_field = source.index('data-output-field="name"')
    source_field = source.index('data-output-field="source"')
    type_field = source.index('data-output-field="type"')
    action = source.index('className="wf-inline-icon-button"', type_field)
    assert name_field < source_field < type_field < action
    assert ".wf-output-variable-row label {" in styles
    assert "grid-template-columns: max-content minmax(0, 1fr);" in styles[styles.index(".wf-output-variable-row label {"):]
    assert "gap: var(--wf-control-gap);" in styles[styles.index(".wf-output-variable-row label {"):]


def test_all_node_fields_follow_visible_text_width_and_start_type_is_last():
    source = read("web/frontend/workflow-canvas.jsx")
    styles = read("web/frontend/workflow-canvas.css")

    assert ".wf-inspector-body label {" in styles
    assert "grid-template-columns: max-content minmax(0, 1fr);" in styles[styles.index(".wf-inspector-body label {"):]
    start_name = source.index('data-start-field="name"')
    start_value = source.index('data-start-field="value"')
    start_type = source.index('data-start-field="type"')
    assert start_name < start_value < start_type


def test_variable_type_changes_preserve_existing_user_input():
    source = read("web/frontend/workflow-canvas.jsx")

    assert "updateRow(row.id, {type});" in source
    assert "updateStartInput(row.id, {type: event.target.value})" in source
    assert "updateOutputVariable(row.id, {type: event.target.value})" in source
    assert "valueText: type === 'null' ? 'null' : row.valueText" not in source
    assert "{type: event.target.value, value: ''}" not in source


def test_available_variables_include_dag_ancestors_current_draft_and_temporary_outputs():
    source = read("web/frontend/workflow-canvas.jsx")

    assert "function variableScopeNodes(nodes, edges, targetNodeId)" in source
    assert "const visible = variableScopeNodes(nodes, edges, id)" in source
    assert "node.data.temporaryRun?.outputs" in source
    assert "const executionOutputs = temporaryOutputs || persistedOutputs" in source
    assert "const toggleVariables = () => setVariablesOpen((open) => !open)" in source
    assert "if (!variablesOpen || !node) return undefined" in source


def test_end_node_is_only_a_user_visible_workflow_marker():
    source = read("web/frontend/workflow-canvas.jsx")
    adapter = read("web/static/execution.js")

    assert "const isEnd = node.data.nodeType === 'END';" in source
    assert "const showOutputVariables = meta.executable;" in source
    assert "{data.nodeType !== 'END' && <button type=\"button\" title=\"日志\"" in source
    assert "{!isEnd && <button type=\"button\" className={tab === 'logs'" in source
    assert "{meta.executable && <section className=\"wf-config-section wf-editor-full-row\">" in source
    assert "payload.executions.filter((execution) => execution.type !== 'END')" in source
    assert "isEnd ? '最终结果' : '运行配置'" not in source
    assert "isEnd ? '结果字段' : '输出变量'" not in source
    assert "if (data.nodeType === 'END') return common;" in adapter


def test_built_workflow_assets_exist_and_are_nonempty():
    output = ROOT / "web" / "static" / "assets" / "vite"
    manifest = json.loads((output / ".vite" / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["web/frontend/workflow-canvas.jsx"]
    implementation = manifest["web/frontend/workflow-canvas-implementation.jsx"]
    script = output / entry["file"]
    implementation_script = output / implementation["file"]
    styles = output / implementation["css"][0]

    assert script.stat().st_size < 500_000
    assert implementation_script.stat().st_size > 500_000
    assert entry["dynamicImports"] == ["web/frontend/workflow-canvas-implementation.jsx"]
    assert styles.stat().st_size > 20_000


def test_workflow_list_entry_defers_heavy_canvas_dependencies():
    entry = (ROOT / "web/frontend/workflow-canvas.jsx").read_text(encoding="utf-8")

    assert "import('./workflow-canvas-implementation.jsx')" in entry
    assert "@xyflow/react" not in entry
    assert "@codemirror/" not in entry
    assert "window.AgentBenchWorkflowCanvas = {mount, unmount};" in entry


def test_workflow_bundle_uses_cache_busting_version():
    html = read("web/static/index.html")
    vite = read("vite.config.mjs")
    app = read("web/app.py")

    assert 'data-feature-css="__VITE_WORKFLOW_CANVAS_CSS__"' in html
    assert 'data-feature-js="__VITE_WORKFLOW_CANVAS_JS__"' in html
    assert re.search(r'/execution\.js\?v=[0-9a-f]{12}', html)
    assert 'entryFileNames: "[name]-[hash].js"' in vite
    assert 'assetFileNames: "[name]-[hash][extname]"' in vite
    assert '"workflow-canvas": resolve("web/frontend/workflow-canvas.jsx")' in vite
    assert "VITE_MANIFEST_PATH" in app
    assert "_render_index_html" in app


def test_llm_advanced_parameters_are_protocol_specific():
    source = read("web/frontend/workflow-canvas.jsx")

    assert "OPENAI_COMPATIBLE: 'OpenAI Chat Completions'" in source
    assert "OPENAI_RESPONSES: 'OpenAI Responses API'" in source
    assert "ANTHROPIC: 'Anthropic Claude Messages'" in source
    assert "function llmParametersReference(protocol)" in source
    assert "function modelParametersProtocolError(protocol, parameters)" in source
    assert "placeholder={llmParametersReference(selectedModelProtocol)}" in source
    assert "&& !protocolParametersError" in source


def test_workflow_header_groups_description_with_title_and_shows_save_state():
    source = read("web/frontend/workflow-canvas.jsx")
    styles = read("web/frontend/workflow-canvas.css")

    header = source[source.index('<header className="wf-studio-header">'):source.index('<main className="wf-canvas-wrap"')]
    left = header[header.index('<div className="wf-header-left">'):header.index('<div className="wf-header-actions">')]

    assert 'className={`wf-header-description ${descriptionEditing ? \'is-editing\' : \'\'}`}' in left
    assert 'className="wf-save-state"' in header
    assert 'data-state={saveState}' in header
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
    assert "import * as Dialog from '@radix-ui/react-dialog';" in source
    assert "<Dialog.Root open onOpenChange={(open) => !open && onCancel()}>" in source
    assert "<Dialog.Content" in source
    assert "function useDialogAccessibility" not in source


def test_node_save_button_does_not_keep_a_persistent_saved_background():
    source = read("web/frontend/workflow-canvas.jsx")
    styles = read("web/frontend/workflow-canvas.css")

    inspector = source[source.index('<aside className="wf-inspector"'):source.index("{variablesOpen &&", source.index('<aside className="wf-inspector"'))]
    assert 'aria-label="保存"' in inspector
    assert "`已保存 ${node.data.savedAt}`" in inspector
    assert "className={node.data.savedAt && !node.data.isDirty ? 'is-saved' : ''}" not in inspector
    assert ".wf-inspector-actions button.is-saved" not in styles
    assert "setNodeSaveNotice" in source
    assert "wf-node-saved-state" not in source
    assert ".wf-node-saved-state" not in styles
