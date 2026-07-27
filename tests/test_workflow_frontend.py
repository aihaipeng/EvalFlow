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
    assert "wf-llm-message is-" in source
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


def test_new_and_existing_workflows_open_at_sixty_seven_percent_of_fit_view():
    source = read("web/frontend/workflow-canvas.jsx")

    assert "const INITIAL_OVERVIEW_SCALE = 0.67;" in source
    assert "await fitView({padding: 0.16, duration: 0});" in source
    assert "zoom: viewport.zoom * ratio" in source
    assert "centerX - (centerX - viewport.x) * ratio" in source
    assert "window.setTimeout(() => void fitInitialOverview(), 0);" in source
    assert 'minZoom={0.1}' in source


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
    assert "<span className=\"wf-node-runtime\">{meta.runtime}</span>" in source


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


def test_built_workflow_assets_exist_and_are_nonempty():
    script = ROOT / "web/static/assets/workflow-canvas.js"
    styles = ROOT / "web/static/assets/workflow-canvas.css"

    assert script.stat().st_size > 500_000
    assert styles.stat().st_size > 20_000


def test_workflow_bundle_uses_cache_busting_version():
    html = read("web/static/index.html")
    build_script = read("scripts/build-workflow.mjs")

    assert re.search(r'/assets/workflow-canvas\.js\?v=[0-9a-f]{12}', html)
    assert re.search(r'/execution\.js\?v=[0-9a-f]{12}', html)
    assert 'createHash("sha256")' in build_script
    assert 'indexContent.replace(' in build_script
    assert 'versionedWorkflowIndex.replace(' in build_script
