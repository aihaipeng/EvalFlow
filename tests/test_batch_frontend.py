import hashlib
from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[1] / "web" / "static"


def test_execution_modal_supports_escape_focus_trap_and_focus_return():
    javascript = (STATIC_DIR / "execution.js").read_text(encoding="utf-8")

    assert "var executionModalReturnFocus = null;" in javascript
    assert "function executionModalFocusableElements(overlay)" in javascript
    assert "if (event.key === 'Escape')" in javascript
    assert "if (event.key !== 'Tab') return;" in javascript
    assert "executionModalReturnFocus = document.activeElement;" in javascript
    assert "executionModalReturnFocus.focus();" in javascript


def test_batch_frontend_uses_database_test_sets_and_saved_workflows():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    javascript = (STATIC_DIR / "execution.js").read_text(encoding="utf-8")
    styles = (STATIC_DIR / "execution.css").read_text(encoding="utf-8")

    assert 'data-view="batch-runs"' in html
    assert "batchListRequestId" in javascript
    assert "workflowListRequestId" in javascript
    assert "if (requestId !== executionState.batchListRequestId) return;" in javascript
    assert "if (requestId !== executionState.workflowListRequestId) return;" in javascript
    assert "if (currentView !== 'batch-runs') return;" in javascript
    assert "renderBatchTable();\n    document.getElementById('btn-batch-add')" in javascript
    assert '/assets/icons.js?v=' in html
    assert "API.get('/api/test-sets?page=1&page_size=200')" in javascript
    assert "API.get('/api/workflows')" in javascript
    assert 'id="batch-test-set"' in javascript
    assert 'id="batch-workflow"' in javascript
    assert 'id="batch-description"' not in javascript
    assert 'id="batch-failure-retry-count"' in javascript
    assert 'id="batch-call-order"' in javascript
    assert '<option value="SEQUENTIAL">顺序</option>' in javascript
    assert '<option value="REVERSE">逆序</option>' in javascript
    assert '<option value="RANDOM">随机</option>' in javascript
    assert 'id="batch-sheet"' not in javascript
    assert 'id="batch-header-mode"' not in javascript
    assert "/api/excel/" not in javascript
    assert "filename:" not in javascript
    assert "sheet_name:" not in javascript
    assert "header_mode:" not in javascript
    assert "test_set_id: document.getElementById('batch-test-set').value" in javascript
    assert "source: 'TEST_SET'" in javascript
    assert '>测试集字段</option>' in javascript
    assert 'aria-label="测试集字段"' in javascript
    assert '<input class="input" data-variable-value' in javascript
    assert 'placeholder="例如 col_1"' in javascript
    assert '<select class="input" data-variable-value aria-label="测试集字段">' not in javascript
    assert "正在读取测试集字段..." in javascript
    assert 'id="batch-preview-meta"' not in javascript
    assert "description: document.getElementById('batch-description').value" not in javascript
    assert "sourceBatch.description || ''" not in javascript
    assert "sourceConfig.test_set_id" in javascript
    assert "sourceConfig.workflow_id" in javascript
    assert "sourceConfig.case_concurrency" in javascript
    assert "sourceConfig.failure_retry_count || 0" in javascript
    assert "sourceConfig.call_order || 'SEQUENTIAL'" in javascript
    assert "variables: variables" in javascript
    assert "call_order: document.getElementById('batch-call-order').value" in javascript
    assert "evaluation_rules: evaluationRules" in javascript
    assert "failure_retry_count: Number(document.getElementById('batch-failure-retry-count').value)" in javascript
    assert "if (executionState.batchCreating) return;" in javascript
    assert "executionState.batchCreating = false;" in javascript
    assert "executionState.batchConfigMode === 'edit'" in javascript
    assert "await API.put('/api/batch-runs/'" in javascript
    assert "sourceConfig.name + '_copy'" not in javascript
    assert "'/copy-name'" in javascript
    assert "mode === 'copy' ? copyName : sourceConfig.name" in javascript
    assert "mode === 'edit' ? '编辑任务' : mode === 'copy' ? '拷贝任务' : '创建任务'" in javascript
    assert "executionState.batches.length + ' 个任务'" in javascript
    assert "}, '个任务');" in javascript
    assert "classList.add('is-batch-config')" in javascript
    assert ".execution-modal.is-batch-config {\n    width: min(1180px, calc(100vw - 48px));" in styles
    assert "function openExecutionConfirm(title, bodyHtml, onConfirm, confirmLabel)" in javascript
    assert ".execution-modal.is-confirm" in styles
    assert ".execution-confirm-copy" in styles


def test_batch_list_and_details_hide_status_and_verdict_columns():
    javascript = (STATIC_DIR / "execution.js").read_text(encoding="utf-8")
    styles = (STATIC_DIR / "execution.css").read_text(encoding="utf-8")

    batch_list = javascript[
        javascript.index("function batchProgress"):
        javascript.index("async function openBatchCreate")
    ]
    list_view = javascript[
        javascript.index("function renderBatchTable()"):
        javascript.index("async function openBatchCreate")
    ]
    detail_view = javascript[
        javascript.index("async function viewBatchDetail"):
        javascript.index("async function openBatchCaseDetail")
    ]
    case_detail = javascript[javascript.index("function batchCaseDetailValue"):]

    assert "caseRunsById[caseRun.id] = caseRun" in javascript
    assert "openBatchCaseDetail(batch, caseRunId, roundId, caseRunsById[caseRunId])" in javascript
    assert "async function openBatchCaseDetail(batch, caseRunId, roundId, caseRunSnapshot)" in case_detail
    assert "var caseRun = caseRunSnapshot;" in case_detail
    assert "if (!caseRun)" in case_detail

    expected_batch_headers = '<th>名称</th><th>测试集</th><th>工作流</th><th>执行进度</th><th>通过率</th><th>启动时间</th><th>结束时间</th><th class="management-list-actions-head batch-actions-head">操作</th>'
    assert expected_batch_headers in list_view
    assert '<colgroup>' not in list_view
    assert "if (table.classList.contains('management-list-table')) return;" in (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert '<th>说明</th>' not in list_view
    assert 'class="batch-description"' not in list_view
    assert "batch.description || ''" not in list_view
    assert '<th>状态</th>' not in list_view
    assert '<th>测试判定</th>' not in list_view
    assert '<th>结果</th>' not in list_view
    assert "batch.input.test_set_name" in list_view
    assert "batch.input.filename" not in list_view
    assert "function batchRunResultCounts" not in batch_list
    assert "function renderBatchRunResults" not in batch_list
    assert "function renderBatchPassRate" in batch_list
    assert "var done = Math.max(0, Number(summary.success) || 0) + Math.max(0, Number(summary.failed) || 0);" in batch_list
    assert "summary.running" not in batch_list[batch_list.index("function batchProgress"):batch_list.index("function renderBatchPassRate")]
    assert "summary.interrupted" not in batch_list[batch_list.index("function batchProgress"):batch_list.index("function renderBatchPassRate")]
    assert "['RUNNING', 'STOPPING'].includes(batch.status) ? ' is-active' : ''" in batch_list
    assert 'class="batch-progress\' + activeClass + \'"' in batch_list
    assert "pass + Math.max(0, Number(summary.failed) || 0)" in batch_list
    assert "Number(summary.interrupted)" not in batch_list[batch_list.index("function renderBatchPassRate"):batch_list.index("function batchTableDateTime")]
    assert "if (!executed)" in batch_list
    assert "pass * 100 / executed" in batch_list
    assert "Pass ' + pass + ' / 已执行 ' + executed" in batch_list
    assert "pass * 100 / total" not in batch_list
    assert "rate > 90 ? 'good' : rate >= 60 ? 'warning' : 'bad'" in batch_list
    assert "var BATCH_LIST_POLL_BASE_MS = 5000;" in javascript
    assert "var BATCH_LIST_POLL_MAX_MS = 10000;" in javascript
    assert "var BATCH_LIST_POLL_BACKOFF_STEP_MS = 2500;" in javascript
    assert "var BATCH_LIST_UNCHANGED_THRESHOLD = 3;" in javascript
    assert "var BATCH_DETAIL_POLL_INTERVAL_MS = 1000;" in javascript
    assert "executionState.batchListUnchangedPolls >= BATCH_LIST_UNCHANGED_THRESHOLD" in javascript
    assert "executionState.batchListPollIntervalMs + BATCH_LIST_POLL_BACKOFF_STEP_MS" in javascript
    assert "setTimeout(loadBatchRuns, executionState.batchListPollIntervalMs)" in javascript
    assert javascript.count("}, BATCH_DETAIL_POLL_INTERVAL_MS);") == 2
    assert "renderBatchRunResults(batch)" not in list_view
    assert "renderBatchPassRate(batch)" in list_view
    assert 'colspan="8"' in list_view
    assert "batchTableDateTime(batch.started_at)" in list_view
    assert "batchTableDateTime(batch.finished_at)" in list_view
    assert "batchTableDateTime(batch.created_at)" not in list_view
    assert "batchTableDateTime(batch.updated_at)" not in list_view
    assert list_view.index("batch.started_at") < list_view.index("batch.finished_at")
    assert 'class="management-list-actions-cell batch-actions-cell"' in list_view
    assert 'data-batch-history="' in list_view
    assert "icon('history')" in list_view
    assert 'aria-label="删除任务（暂不可用）"' in list_view
    assert 'title="任务运行中，暂不可删除"' in list_view
    assert "openBatchHistory(button.getAttribute('data-batch-history'))" in list_view
    assert "'/api/batch-runs/' + encodeURIComponent(batchId) + '/history'" in javascript
    assert '<th>测试集</th><th>工作流</th><th>执行进度</th><th>通过率</th><th>启动时间</th><th>结束时间</th>' in javascript
    assert '手动执行单条用例不会单独生成历史' in javascript
    assert ".execution-modal.is-batch-history {" in styles
    assert 'class="table-wrap execution-table-wrap management-list-wrap batch-table-wrap"' in list_view
    assert "--management-list-actions-width: 114px;" in styles
    assert ".batch-table th:nth-child(4) { width: calc((100% - var(--management-list-actions-width)) * .18); }" in styles
    assert ".batch-table th:nth-child(5) { width: calc((100% - var(--management-list-actions-width)) * .09); }" in styles
    assert "title=\"' + escAttr(batch.name) + '\"" in list_view
    assert "title=\"' + escAttr(batch.input.test_set_name) + '\"" in list_view
    assert "title=\"' + escAttr(batch.workflow.name) + '\"" in list_view
    assert "overflow-wrap: anywhere;" in styles
    assert "white-space: normal;" in styles[styles.index(".batch-table-primary,"):styles.index("}", styles.index(".batch-table-primary,"))]
    assert "width: calc(100% + 656px);" not in styles
    assert "min-width: 1638px;" not in styles
    assert "overflow-x: hidden;" not in styles
    assert ".batch-table td:nth-child(3) {" in styles
    first_columns_rule = styles[styles.index(".batch-table th:nth-child(1),"):]
    first_columns_rule = first_columns_rule[:first_columns_rule.index("}")]
    assert "padding-inline: 4px;" in first_columns_rule
    assert ".batch-table.management-list-table.table td.management-list-actions-cell {\n    padding-inline: 4px;" in styles
    name_button_rule = styles[styles.index(".batch-table .execution-name-button {"):]
    name_button_rule = name_button_rule[:name_button_rule.index("}")]
    assert "justify-content: center;" in name_button_rule
    assert "text-align: center;" in name_button_rule
    assert "@media (max-width: 1599px)" not in styles
    assert "--management-list-min-width: 860px;" in styles
    assert ".batch-table .batch-progress {" in styles
    assert "grid-template-columns: minmax(64px, 1fr) 64px;" in styles
    assert ".batch-table .batch-row-actions .btn-icon {" in styles
    assert "width: 34px;" in styles
    time_cell_styles = styles[styles.index(".batch-time-cell {"):styles.index("}", styles.index(".batch-time-cell {"))]
    assert "font-size: 14px;" in time_cell_styles
    assert "line-height: 1.4;" in time_cell_styles
    assert "white-space: normal;" in time_cell_styles
    assert ".batch-run-results" not in styles
    assert ".batch-run-result {" not in styles
    assert "background: var(--case-result-bg);" in styles
    assert "color: var(--case-result-fg);" in styles
    assert ".batch-case-result.is-pass,\n.batch-result-card.is-pass {" in styles
    assert ".batch-case-result.is-failed,\n.batch-result-card.is-failed {" in styles
    assert "linear-gradient(115deg" not in styles
    assert 'title="查看详情"' not in list_view
    assert 'aria-label="查看详情"' not in list_view
    assert 'class="btn-icon" data-batch-start=' in list_view
    assert 'title="启动任务" aria-label="启动任务"' in list_view
    assert 'data-batch-schedule=' in list_view
    assert "icon('alarm-clock')" in list_view
    assert list_view.index('data-batch-schedule=') < list_view.index('data-batch-copy=')
    assert "batch.status === 'STOPPING'" in list_view
    assert 'class="btn-icon is-stopping" type="button" disabled' in list_view
    assert 'title="正在等待运行中的工作流结束"' in list_view
    assert "batch.execution_mode === 'SINGLE_CASE'" in list_view
    assert 'data-batch-resume=' not in list_view
    assert 'title="停止任务" aria-label="停止任务"' in list_view
    assert "['RUNNING', 'STOPPING'].includes(batch.status)" in list_view
    assert 'title="编辑任务" aria-label="编辑任务"' in list_view
    assert 'title="拷贝任务" aria-label="拷贝任务"' in list_view
    assert "' + action + history + edit + schedule + copy + remove + '" in list_view
    assert "if (command === 'cancel')" in javascript
    assert "button.classList.add('is-stopping')" in javascript
    assert "已停止派发，正在等待运行中的工作流结束" in javascript
    assert "if (command !== 'cancel' || !commandAccepted)" in javascript
    assert ".batch-table .batch-row-actions .btn-icon.is-stopping:disabled {" in styles
    assert "opacity: 0.48;" in styles
    assert '<th>用例</th><th>规则</th>' in detail_view
    assert '<th>详情</th>' not in detail_view
    assert '<th class="batch-case-actions-head">操作</th>' in detail_view
    assert "用例序号" not in detail_view
    assert "开始时间" not in detail_view
    assert "启动时间" not in detail_view
    assert "结束时间" not in detail_view
    assert ".batch-detail-title {\n    display: flex;\n    min-width: 0;\n    align-items: center;\n    gap: 14px;" in styles
    assert "font-size: 20px;\n    font-weight: 400;\n    line-height: 34px;" in styles
    assert "开始于" not in detail_view
    assert "结束于" not in detail_view
    assert 'id="batch-case-display-column"' in javascript
    assert 'id="batch-rule-display-column"' in javascript
    assert "optional ? '<option value=\"\">不选择</option>' : ''" in javascript
    assert "optional ? '' : (preview.headers[0] || '')" in javascript
    assert "case_display_column:" in javascript
    assert "rule_display_column:" in javascript
    assert "function batchCaseResult" in detail_view
    assert "return ''" in detail_view
    assert "['QUEUED', 'RUNNING', 'INTERRUPTED'].includes(caseRun.status)" in detail_view
    assert "['NOT_STARTED', 'RUNNING', 'INTERRUPTED'].includes(caseRun.execution_status)" in detail_view
    assert "var previousScrollTop = options.preservePosition ? contentArea.scrollTop : 0;" in detail_view
    assert "contentArea.scrollTop = previousScrollTop;" in detail_view
    assert "contentArea.querySelector('.batch-case-table-wrap')" in detail_view
    assert "nextTableWrap.scrollTop = previousTableScrollTop;" in detail_view
    assert "nextTableWrap.scrollLeft = previousTableScrollLeft;" in detail_view
    assert "searchInput.focus({preventScroll: true});" in detail_view
    assert "var requestId = ++executionState.batchDetailRequestId;" in detail_view
    assert "if (requestId !== executionState.batchDetailRequestId || currentView !== 'batch-detail') return;" in detail_view
    assert "executionState.batchDetailRequestId += 1;" in javascript
    assert "var enteringDetail = currentView !== 'batch-detail';" in detail_view
    assert "cachedBatch ? cachedBatch.name : '任务详情'" in detail_view
    assert 'class="execution-loading" role="status">正在加载用例...' in detail_view
    assert "var renderKey = JSON.stringify([" in detail_view
    assert "renderKey === executionState.batchDetailRenderKey" in detail_view
    assert "executionState.batchDetailRenderKey = renderKey;" in detail_view
    assert "viewBatchDetail(batchId, 1, pageSize, roundId, {preservePosition: true})" in detail_view
    assert "viewBatchDetail(batchId, page, pageSize, roundId, {preservePosition: true})" in detail_view
    assert "if (currentView === 'batch-detail') viewBatchDetail(batchId, page, pageSize, roundId, {preservePosition: true});" in detail_view
    assert "function openBatchStartMode(batchId)" in javascript
    assert 'value="FULL" checked' in javascript
    assert 'value="RESUME"' in javascript
    assert 'value="RETRY_FAILED"' in javascript
    assert "API.post('/api/batch-runs/' + encodeURIComponent(batchId) + '/start', {mode: mode})" in javascript
    assert "var values = await API.get('/api/batch-runs/' + encodeURIComponent(batchId) + '/cases' + caseQuery);" in detail_view
    assert "var batch = values.batch;" in detail_view
    assert "Promise.all([" not in detail_view
    assert "batchRoundQuery" not in detail_view
    assert 'data-batch-sort="count"' in detail_view
    assert 'data-batch-sort="duration"' in detail_view
    assert 'id="batch-result-filter"' not in detail_view
    assert 'class="batch-result-card is-' in detail_view
    assert 'batch-result-card-label' in detail_view
    assert "option.label) + ' ('" not in detail_view
    assert detail_view.index("{label: 'Pass'") < detail_view.index("{label: 'Failed'")
    assert detail_view.index("{label: 'Failed'") < detail_view.index("{label: 'Error'")
    assert "{label: 'Interrupt'" not in detail_view
    assert "{label: 'None'" not in detail_view
    assert 'id="batch-case-search"' in detail_view
    assert 'data-full-value="' in detail_view
    assert "searchInput.parentElement.dataset.fullValue = searchInput.value;" in detail_view
    assert ".batch-case-controls {\n    display: grid;\n    gap: 12px;" in styles
    assert "grid-template-columns: repeat(5, minmax(0, 1fr));" in styles
    assert "grid-template-rows: auto minmax(0, 1fr);" in styles
    assert "min-height: 116px;" in styles
    assert "font-size: 36px;" in styles
    assert "text-transform: uppercase;" in styles
    assert ".batch-result-card.is-error { --status-card-border: #6f2aca; --status-card-fg: #ceb2ff; }" in styles
    assert ".batch-result-cards { grid-template-columns: repeat(3, minmax(0, 1fr)); }" in styles
    assert ".batch-result-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }" in styles
    assert ".batch-case-search {\n    order: -1;\n    justify-self: start;" in styles
    search_styles = styles[styles.index(".batch-case-search {"):]
    search_styles = search_styles[:search_styles.index("}")]
    assert "margin-top" not in search_styles
    assert ".batch-case-search:focus-within {" in styles
    assert '.batch-case-search[data-full-value]:not([data-full-value=""]):hover::after {' in styles
    assert "width: 0;\n    min-width: 0;\n    flex: 1;" in styles
    assert "text-overflow: ellipsis;\n    white-space: nowrap;" in styles
    assert ".batch-case-search .input:focus-visible {\n    border-color: transparent;\n    outline: none;\n    box-shadow: none;" in styles
    assert 'data-case-filter="' in detail_view
    assert 'data-filter-kind="' in detail_view
    assert "batchDetailStateFilter: ''" in javascript
    assert "&state=" in detail_view
    assert "function batchCaseExecutionStatus" in detail_view
    assert "return 'Running'" in detail_view
    assert "return 'Pending'" in detail_view
    assert 'class="batch-case-execution-state is-' in detail_view
    assert "kind: 'state', tone: 'running'" in detail_view
    assert "kind: 'state', tone: 'pending'" in detail_view
    assert ".batch-case-execution-state.is-running" in styles
    assert ".batch-case-execution-state.is-pending" in styles
    assert 'id="batch-round-select"' not in detail_view
    assert 'id="batch-detail-save"' not in detail_view
    assert "'/rounds'" not in detail_view
    assert "round_id=" in detail_view
    assert "isLatestRound" in detail_view
    assert "icon('arrow-up-down')" in detail_view
    assert "icon('filter')" not in detail_view
    assert "data-case-delete" not in detail_view
    assert "删除用例" not in detail_view
    assert "data-case-toggle" not in detail_view
    assert "data-case-start" in detail_view
    assert "中断用例" not in detail_view
    assert "'/cancel'" not in detail_view
    assert "var batchActive = ['RUNNING', 'STOPPING'].includes(batch.status)" in detail_view
    assert '<th>执行状态</th>' not in detail_view
    assert "测试判定" not in detail_view
    assert "batch-summary" not in detail_view
    assert "执行状态" not in case_detail
    assert "测试判定" not in case_detail
    assert "校验明细" not in case_detail
    assert "工作流结果" not in case_detail
    assert "batchStatusLabel" not in javascript
    assert "batchVerdictLabel" not in javascript
    assert "batchCaseResultLabel" in detail_view
    assert "batch-case-result-mark" in detail_view
    case_first_column = styles[styles.index(".batch-case-table th:first-child,"):]
    case_first_column = case_first_column[:case_first_column.index("}")]
    case_second_column = styles[styles.index(".batch-case-table th:nth-child(2),"):]
    case_second_column = case_second_column[:case_second_column.index("}")]
    assert "text-align: center;" in case_first_column
    assert "text-align: center;" in case_second_column
    assert "{label: 'Failed', value: 'Failed', kind: 'result', tone: 'failed', icon: 'close'" in detail_view
    assert "{label: 'Error', value: 'Error', kind: 'result', tone: 'error', icon: 'alert'" in detail_view


def test_batch_schedule_modal_persists_real_schedule_and_is_validated():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    javascript = (STATIC_DIR / "execution.js").read_text(encoding="utf-8")
    styles = (STATIC_DIR / "execution.css").read_text(encoding="utf-8")
    icons = (STATIC_DIR / "assets" / "icons.js").read_text(encoding="utf-8")
    schedule = javascript[
        javascript.index("function batchScheduleDefaults"):
        javascript.index("function confirmBatchDelete")
    ]

    assert "batchSchedules: {}" in javascript
    assert 'id="batch-schedule-enabled"' in schedule
    assert 'id="batch-schedule-cadence"' in schedule
    assert 'value="ONCE"' in schedule
    assert 'value="DAILY"' in schedule
    assert 'value="WEEKLY"' in schedule
    assert 'value="MONTHLY"' in schedule
    assert 'value="CRON"' not in schedule
    assert 'id="batch-schedule-timezone"' in schedule
    assert 'id="batch-schedule-run-at"' in schedule
    assert 'id="batch-schedule-run-time"' in schedule
    assert 'name="batch-schedule-weekday"' in schedule
    assert 'id="batch-schedule-month-day"' in schedule
    assert 'id="batch-schedule-cron"' not in schedule
    assert 'id="batch-schedule-start-date"' not in schedule
    assert 'id="batch-schedule-end-date"' not in schedule
    assert 'id="batch-schedule-overlap"' in schedule
    assert 'id="batch-schedule-misfire"' not in schedule
    assert "每周任务至少选择一天" in schedule
    assert "Cron 表达式" not in schedule
    assert "生效日期" not in schedule
    assert "结束日期" not in schedule
    assert "错过执行" not in schedule
    assert "API.put('/api/batch-runs/' + encodeURIComponent(batchId) + '/schedule', nextConfig)" in schedule
    assert "executionState.batchSchedules[batchId] = result.schedule" in schedule
    assert "定时任务设置已保存" in schedule
    assert "当前仅保存到页面会话" not in schedule
    assert "下次执行：" in schedule
    assert "localStorage" not in schedule
    assert "if (batch.schedule) executionState.batchSchedules[batch.id] = batch.schedule;" in javascript
    assert "lucide-alarm-clock" in icons
    icons_hash = hashlib.sha256((STATIC_DIR / "assets" / "icons.js").read_bytes()).hexdigest()[:12]
    assert f'/assets/icons.js?v={icons_hash}' in html
    assert ".execution-modal.is-batch-schedule" in styles
    assert ".batch-schedule-grid" in styles
    assert ".batch-schedule-grid > [hidden] { display: none; }" in styles


def test_batch_case_detail_leads_with_actionable_diagnosis_and_defers_raw_debug_data():
    javascript = (STATIC_DIR / "execution.js").read_text(encoding="utf-8")
    styles = (STATIC_DIR / "execution.css").read_text(encoding="utf-8")
    icons = (STATIC_DIR / "assets" / "icons.js").read_text(encoding="utf-8")
    case_detail = javascript[javascript.index("function batchCaseDetailValue"):]

    assert "function batchCaseDetailModel" in case_detail
    assert "function batchCaseComparisonRows" in case_detail
    assert "function batchCaseProblemNode" in case_detail
    assert "期望与实际" not in case_detail
    assert "结果校验" in case_detail
    assert "row.message === '实际值不符合预期' ? '' : row.message" in case_detail
    assert "问题节点" in case_detail
    assert "建议处理" not in case_detail
    assert '<dt>用例</dt>' not in case_detail
    assert '<dt>规则</dt>' not in case_detail
    assert 'class="batch-case-context"' not in case_detail
    assert "工作流已正常执行，失败来自结果校验。" in case_detail
    assert "节点未能连接目标服务，未获得有效响应。" in case_detail
    assert "目标服务在限定时间内没有返回结果。" in case_detail
    assert "function batchCaseRawErrorMessage" in case_detail
    assert "rawErrorSummary: batchCaseRawErrorMessage(rawError)" in case_detail
    assert "报错概览" in case_detail
    assert "function batchCaseCanvasNodeType" in case_detail
    assert "['START', 'HTTP', 'LLM', 'SCRIPT', 'END']" in case_detail
    assert "model.failureNodeType = 'Evaluation'" not in case_detail
    assert "model.failureNodeType = 'Workflow'" not in case_detail
    assert "batch-case-overview" not in case_detail
    assert 'aria-label="用例概览"' not in case_detail
    assert "function renderBatchCaseOverview" not in case_detail
    assert "用户主动中断" not in case_detail
    assert "model.errorSummary = '用例尚未执行'" in case_detail
    assert "showFailureOverview = model.result === 'Error' || model.result === 'Failed'" not in case_detail
    assert "batch-case-outcome-metric" in case_detail
    assert "batch-case-modal-header" in case_detail
    assert "batch-case-modal-title" in case_detail
    assert "batch-case-modal-meta" in case_detail
    assert "function renderBatchCaseDetailHeader" in case_detail
    assert '<div class="batch-case-modal-title"><strong>用例详情</strong></div>' in case_detail
    assert "batch-case-result is-' + model.result.toLowerCase()" not in case_detail
    assert "batchCaseResultLabel(model.result)" not in case_detail
    assert "renderBatchCaseDetailHeader(caseRun)" in case_detail
    assert "batch-case-outcome-main" not in case_detail
    assert "batch-case-outcome-icon" not in case_detail
    assert "batch-case-outcome-title" not in case_detail
    assert "batch-case-outcome-meta" not in case_detail
    assert "<header><h3 id=\"batch-case-node-title\">问题节点</h3><p>工作流停在此处</p></header>" in case_detail
    assert "batch-case-problem-error" in case_detail
    assert "esc(model.rawErrorSummary)" in case_detail
    assert "耗时 " in case_detail
    assert "执行次数 " in case_detail
    assert ".batch-case-overview" not in styles
    assert ".batch-case-modal-header" in styles
    assert ".batch-case-modal-title" in styles
    assert ".batch-case-modal-meta" in styles
    assert ".batch-case-outcome-meta" not in styles
    assert ".batch-case-outcome-main" in styles
    assert ".batch-case-problem-error" in styles
    problem_node_cells = styles[styles.index(".batch-case-problem-node dl > div {"):]
    problem_node_cells = problem_node_cells[:problem_node_cells.index("}")]
    assert "display: grid;" in problem_node_cells
    assert "grid-template-columns: auto minmax(0, 1fr);" in problem_node_cells
    problem_node_values = styles[styles.index(".batch-case-problem-node dd {"):]
    problem_node_values = problem_node_values[:problem_node_values.index("}")]
    assert "text-align: center;" in problem_node_values
    problem_error = styles[styles.index(".batch-case-problem-error {"):]
    problem_error = problem_error[:problem_error.index("}")]
    assert "grid-template-columns: auto minmax(0, 1fr);" in problem_error
    assert "align-items: center;" in problem_error
    assert "font-weight: 400;" in styles
    assert "font-weight: 500;" in styles
    assert "border-radius: 4px;" in styles
    assert "哪里失败" not in case_detail
    assert "String(rule.name || '').trim() || batchRuleDisplayPath(rule.result_path) || '—'" in case_detail
    assert "esc(row.path)" not in case_detail
    comparison_cells = styles[styles.index(".batch-case-comparison-table th,"):]
    comparison_cells = comparison_cells[:comparison_cells.index("}")]
    assert "text-align: center;" in comparison_cells
    assert "vertical-align: middle;" in comparison_cells
    assert "(passed ? 'Pass' : 'Failed')" in case_detail
    assert "row.status === 'FAIL' ? 'Failed' : row.status === 'PASS' ? 'Pass' : 'Error'" not in case_detail
    assert "diagnostic_summary" in case_detail
    assert "batchCaseResult(caseRun) === 'Error'" in case_detail
    assert '<section class="batch-case-debug"' in case_detail
    assert '<section class="batch-case-debug" aria-label="用例调试信息">' in case_detail
    assert "调试数据" not in case_detail
    assert "batch-case-debug-title" not in case_detail
    assert '<details><summary>' in case_detail
    assert '<details open' not in case_detail
    assert "仅在进一步排查时查看" not in case_detail
    assert "最终 Context" not in case_detail
    assert '<span>Context</span>' in case_detail
    assert "映射输入" not in case_detail
    assert "function batchCaseContextText" in case_detail
    assert "normalized = JSON.parse(value)" in case_detail
    assert 'id="batch-case-copy-context"' not in case_detail
    assert 'aria-label="复制上下文"' not in case_detail
    assert "navigator.clipboard.writeText" not in case_detail
    assert "上下文已复制" not in case_detail
    assert "batch-case-selectable-log" in case_detail
    assert "pre.addEventListener('keydown'" in case_detail
    assert "event.preventDefault()" in case_detail
    assert "range.selectNodeContents(pre)" in case_detail
    assert '"copy": "<svg' in icons
    assert "lucide-copy" in icons
    assert "modal.classList.add('is-case-detail', 'is-' + model.tone)" in case_detail
    assert "batchCaseResultLabel(model.result)" not in case_detail
    assert ".execution-modal.is-case-detail" in styles
    assert ".batch-case-comparison-table" in styles
    assert ".batch-case-next-action" not in styles
    assert ".batch-case-debug details + details" in styles
    assert ".batch-case-debug > header" not in styles
    debug_section = styles[styles.index(".batch-case-debug {"):]
    debug_section = debug_section[:debug_section.index("}")]
    assert "padding: 0 24px;" in debug_section
    assert ".batch-case-debug details:last-child" not in styles
    assert ".batch-case-debug-toolbar" not in styles
    assert ".batch-case-selectable-log" in styles


def test_management_navigation_labels_icons_pagination_and_alignment_are_consistent():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    javascript = (STATIC_DIR / "execution.js").read_text(encoding="utf-8")
    styles = (STATIC_DIR / "execution.css").read_text(encoding="utf-8")
    global_styles = (STATIC_DIR / "style.css").read_text(encoding="utf-8")

    for label in ("测试集管理", "供应商管理", "工作流管理", "任务调度"):
        assert f"<span>{label}</span>" in html
    assert html.count('class="sidebar-icon"') == 4
    assert "📋" not in html and "◉" not in html and "◇" not in html and "▶" not in html
    assert ".sidebar-icon .ui-icon" in global_styles
    assert "stroke-width: 1.8" in global_styles
    sidebar_item_styles = global_styles[global_styles.index(".sidebar-item {", global_styles.index("/* impeccable:polish-start */")):]
    sidebar_item_styles = sidebar_item_styles[:sidebar_item_styles.index("}")]
    assert "font-size: 16px;" in sidebar_item_styles
    assert "font-weight: 600;" in sidebar_item_styles
    active_sidebar_styles = global_styles[global_styles.index(".sidebar-item.active {", global_styles.index("/* impeccable:polish-start */")):]
    active_sidebar_styles = active_sidebar_styles[:active_sidebar_styles.index("}")]
    assert "font-weight: 700;" in active_sidebar_styles
    assert "var GLOBAL_PAGE_SIZE_OPTIONS = [10, 20, 50, 100];" in app_js
    assert 'id="workflow-pagination" class="global-list-footer management-list-footer"' in javascript
    assert 'id="batch-pagination" class="global-list-footer management-list-footer"' in javascript
    assert 'id="batch-case-pagination" class="global-list-footer"' in javascript
    assert ".execution-table th,\n.execution-table td {\n    text-align: center;" in styles
    assert ".batch-progress {\n    display: grid;\n    width: 220px;\n    margin: 0 auto;" in styles
    assert "height: 8px;" in styles
    assert "background: #14b8a6;" in styles
    progress_label_styles = styles[styles.index(".batch-progress small {"):styles.index("}", styles.index(".batch-progress small {"))]
    assert "font-size: 14px;" in progress_label_styles
    assert "line-height: 1.3;" in progress_label_styles
    assert "white-space: nowrap;" in progress_label_styles
    assert ".batch-progress.is-active > div::after" in styles
    assert "animation: batch-progress-wave 24s cubic-bezier(0.16, 1, 0.3, 1) infinite;" in styles
    assert "100% { opacity: 0; transform: scaleX(1); }" in styles
    assert "drop-shadow" not in styles[styles.index(".batch-progress.is-active > div::after"):styles.index("@media (prefers-reduced-motion: reduce)")]
    assert "@media (prefers-reduced-motion: reduce)" in styles
    assert ".batch-row-actions {\n    display: inline-grid;" in styles
    assert "grid-template-columns: repeat(3, 34px);" in styles
    assert "--management-list-actions-width: 114px;" in styles
    assert "function enableTableColumnResize" in app_js
    assert "table-column-resize" in app_js
    assert "table.classList.contains('management-list-table')" in app_js
    assert ".table-column-resize" in global_styles
    assert ".table-column-resize::before" in global_styles
    assert ".management-list-wrap.table-wrap" in global_styles
    assert ".management-list-table.table" in global_styles
    management_time_styles = global_styles[global_styles.index(".management-list-time {"):]
    management_time_styles = management_time_styles[:management_time_styles.index("}")]
    assert "font-size: 14px;" in management_time_styles
    assert "position: sticky;" in global_styles[global_styles.index(".management-list-table.table th.management-list-actions-head,"):]
    assert ".management-list-footer.global-list-footer" in global_styles
    assert 'class="table execution-table management-list-table workflow-table"' in javascript
    assert 'class="table execution-table management-list-table batch-table"' in javascript
    assert 'class="management-list-actions-head batch-actions-head"' in javascript


def test_top_level_management_lists_share_batch_list_contract_without_detail_tables():
    javascript = (STATIC_DIR / "execution.js").read_text(encoding="utf-8")
    providers = (STATIC_DIR.parent / "frontend" / "model-providers.jsx").read_text(encoding="utf-8")
    test_sets = (STATIC_DIR.parent / "frontend" / "test-sets.jsx").read_text(encoding="utf-8")
    global_styles = (STATIC_DIR / "style.css").read_text(encoding="utf-8")

    assert javascript.count('class="table execution-table management-list-table') == 2
    assert providers.count('className="table execution-table management-list-table') == 1
    assert test_sets.count('className="table execution-table management-list-table') == 1
    assert 'class="management-list-time"' in javascript
    assert 'className="management-list-time"' in providers
    assert 'className="management-list-time ts-time"' in test_sets
    assert javascript.count("management-list-toolbar") == 2
    assert providers.count("management-list-toolbar") == 1
    assert test_sets.count("management-list-toolbar") == 1
    assert javascript.count('class="execution-page-header management-page-header"') == 2
    assert providers.count('className="execution-page-header management-page-header"') == 1
    assert test_sets.count('className="ts-heading execution-page-header management-page-header"') == 1
    assert "开发、保存和手动验证工作流结构" not in javascript
    assert "按数据库测试集用例并发执行已保存的工作流" not in javascript
    assert "从 Excel 选择内容创建测试集，后续用例统一存储在数据库中。" not in test_sets
    assert '<span class="management-page-description">编排并验证工作流</span>' in javascript
    assert '<span class="management-page-description">执行任务并追踪结果</span>' in javascript
    assert '<span className="management-page-description">配置模型接入与连接</span>' in providers
    assert '<span className="management-page-description">维护测试字段与用例</span>' in test_sets
    assert "overflow: auto;" in global_styles[global_styles.index(".management-list-wrap.table-wrap"):]
    assert "position: sticky;" in global_styles[global_styles.index(".management-list-table.table th.management-list-actions-head,"):]
    assert 'class="table execution-table batch-case-table"' in javascript
    assert 'className="ts-table"' in test_sets

def test_batch_run_config_uses_confirmed_impeccable_layout():
    javascript = (STATIC_DIR / "execution.js").read_text(encoding="utf-8")
    styles = (STATIC_DIR / "execution.css").read_text(encoding="utf-8")

    config_view = javascript[
        javascript.index("var body =", javascript.index("async function openBatchCreate")):
        javascript.index("executionState.batchConfigMode = mode", javascript.index("async function openBatchCreate"))
    ]

    assert 'class="batch-config-card" aria-label="基础配置"' in config_view
    field_order = [
        'id="batch-name"',
        'id="batch-failure-retry-count"',
        'id="batch-test-set"',
        'id="batch-workflow"',
        'id="batch-case-display-column"',
        'id="batch-rule-display-column"',
        'id="batch-call-order"',
        'id="batch-concurrency"',
    ]
    assert [config_view.index(field) for field in field_order] == sorted(
        config_view.index(field) for field in field_order
    )
    assert '<span>执行顺序</span>' in config_view
    assert '<span>并发数</span>' in config_view
    assert '<span>失败重试</span>' in config_view
    assert '测试集概览' not in config_view
    assert 'batch-preview-meta' not in config_view
    assert ".batch-config-card {" in styles
    assert ".batch-run-options {" not in styles
    assert ".batch-field-wide {" not in styles
    assert ".batch-description {" not in styles
    assert "grid-template-columns: 72px minmax(220px, 360px);" in styles
    assert ".batch-create-grid label > span {" in styles
    assert "text-align: right;" in styles

def test_batch_variable_and_evaluation_sections_use_management_table_layout():
    javascript = (STATIC_DIR / "execution.js").read_text(encoding="utf-8")
    styles = (STATIC_DIR / "execution.css").read_text(encoding="utf-8")

    config_view = javascript[
        javascript.index("var body =", javascript.index("async function openBatchCreate")):
        javascript.index("executionState.batchConfigMode = mode", javascript.index("async function openBatchCreate"))
    ]
    variable_view = javascript[
        javascript.index("function renderBatchVariables"):
        javascript.index("function addBatchVariable")
    ]
    evaluation_view = javascript[
        javascript.index("function renderBatchEvaluationRules"):
        javascript.index("function addBatchEvaluationRule")
    ]
    variable_add = javascript[
        javascript.index("function addBatchVariable"):
        javascript.index("function batchRuleDrafts")
    ]
    evaluation_add = javascript[
        javascript.index("function addBatchEvaluationRule"):
        javascript.index("async function loadBatchPreview")
    ]

    assert 'class="batch-section-heading"><strong>变量注入</strong><span>' in config_view
    assert 'class="batch-section-heading"><strong>结果校验</strong><span>' in config_view
    assert 'id="batch-variable-add" type="button" disabled' in config_view
    assert 'id="batch-rule-add" type="button" disabled' in config_view
    assert '从工作流 Context 中获取变量，路径填写 action 等价于 context["action"]' in config_view
    assert "全部校验点通过时，用例才通过" not in config_view
    assert ">类型</span>" in variable_view
    assert ">类型</span>" in evaluation_view
    assert ">来源</span>" in variable_view
    assert ">Source</span>" not in variable_view
    assert ">Type</span>" not in variable_view
    assert ">Type</span>" not in evaluation_view
    assert '<label><span>结果路径</span>' not in evaluation_view
    assert '<label><span>运算符</span>' not in evaluation_view
    assert '<label><span>预期值</span>' not in evaluation_view
    assert '<span class="batch-mobile-label">结果路径</span>' not in evaluation_view
    assert '<span class="batch-mobile-label">校验项</span>' in evaluation_view
    assert '<span class="batch-mobile-label">路径</span>' in evaluation_view
    assert 'placeholder="例如 action_match"' in evaluation_view
    assert 'placeholder="例如 context.final_answer.status"' not in evaluation_view
    assert 'data-rule-name' in evaluation_view
    assert '<span class="batch-mobile-label">运算符</span>' in evaluation_view
    assert '<span class="batch-mobile-label">预期值</span>' in evaluation_view
    assert "['NOT_EMPTY', '不为空']" in evaluation_view
    assert "rule.operator === 'NOT_EMPTY'" in evaluation_view
    assert "ignoresExpected ? 'disabled' : ''" in evaluation_view
    assert "renderBatchEvaluationRules(batchRuleDrafts())" in evaluation_view
    assert javascript.count("is_new: row.classList.contains('is-new')") == 2
    assert "variables.unshift(" in variable_add
    assert "rules.unshift(" in evaluation_add
    assert "[data-variable-key]').focus()" in variable_add
    assert "[data-rule-result-path]').focus()" in evaluation_add
    assert ".batch-section-heading strong {" in styles
    assert "font-size: 16px;" in styles
    assert ".batch-variable-table," in styles
    assert "overflow-x: auto;" in styles
    assert "border: 1px solid var(--border);" in styles
    assert ".batch-variable-row:hover," in styles
    assert ".batch-variable-row.is-new," in styles
    assert "background: #eff6ff;" in styles
    new_row_styles = styles[styles.index(".batch-variable-row.is-new,"):]
    new_row_styles = new_row_styles[:new_row_styles.index("}")]
    assert "outline:" not in new_row_styles
    assert "variableAddButton.disabled = false" in javascript
    assert "ruleAddButton.disabled = false" in javascript
