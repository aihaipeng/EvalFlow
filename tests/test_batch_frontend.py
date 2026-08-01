from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "web" / "static"
BATCH_SOURCE = ROOT / "web" / "frontend" / "batch-runs.jsx"
BATCH_API = ROOT / "web" / "frontend" / "batch-api.ts"
DIALOG_SOURCE = ROOT / "web" / "frontend" / "components" / "dialog.jsx"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_legacy_case_detail_modal_supports_escape_focus_trap_and_focus_return():
    javascript = read(STATIC_DIR / "execution.js")

    assert "var executionModalReturnFocus = null;" in javascript
    assert "function executionModalFocusableElements(overlay)" in javascript
    assert "if (event.key === 'Escape')" in javascript
    assert "if (event.key !== 'Tab') return;" in javascript
    assert "executionModalReturnFocus = document.activeElement;" in javascript
    assert "executionModalReturnFocus.focus();" in javascript


def test_batch_frontend_uses_typed_database_and_workflow_apis():
    html = read(STATIC_DIR / "index.html")
    source = read(BATCH_SOURCE)
    api = read(BATCH_API)

    assert 'data-view="batch-runs"' in html
    assert 'data-feature-js="__VITE_BATCH_RUNS_JS__"' in html
    assert 'from "./batch-api"' in source
    assert 'from "react-hook-form"' in source
    assert 'from "zod"' in source
    assert 'from "openapi-fetch"' in api
    assert 'import type { components, paths } from "./generated/openapi"' in api
    for endpoint in (
        'http.GET("/api/test-sets"',
        'http.GET("/api/workflows")',
        'http.POST("/api/batch-runs/preview"',
        'http.POST("/api/batch-runs/{batch_id}/start"',
        'http.GET("/api/batch-runs/{batch_id}/copy-name"',
    ):
        assert endpoint in api
    assert "/api/excel/" not in source
    assert "sheet_name" not in source
    assert "header_mode" not in source


def test_batch_list_preserves_management_and_execution_contracts():
    source = read(BATCH_SOURCE)
    detail = read(STATIC_DIR / "execution.js")
    styles = read(STATIC_DIR / "execution.css")

    for heading in ("任务", "测试集", "工作流", "执行进度", "通过率", "启动时间", "结束时间", "操作"):
        assert f"<th>{heading}</th>" in source or heading == "操作"
    assert 'className="table execution-table management-list-table batch-table"' in source
    assert 'id="batch-pagination"' in source
    assert "[10, 20, 50, 100]" in source
    assert 'aria-label="启动任务"' in source
    assert 'aria-label="停止任务"' in source
    assert 'aria-label="查看执行历史"' in source
    assert 'aria-label="编辑任务"' in source
    assert 'aria-label="定时任务设置"' in source
    assert 'aria-label="拷贝任务"' in source
    assert 'aria-label="删除任务"' in source
    assert 'window.viewBatchDetail(batch.id)' in source
    assert "async function viewBatchDetail" in detail
    assert "var BATCH_DETAIL_POLL_INTERVAL_MS = 1000;" in detail
    assert ".batch-progress.is-active > div::after" in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles


def test_batch_schedule_modal_persists_real_schedule():
    source = read(BATCH_SOURCE)
    api = read(BATCH_API)
    styles = read(STATIC_DIR / "execution.css")

    assert "function ScheduleModal" in source
    assert "saveBatchSchedule(batch.id, body)" in source
    assert "next_run_at: _nextRunAt" in source
    for cadence in ("ONCE", "DAILY", "WEEKLY", "MONTHLY"):
        assert f'value="{cadence}"' in source
    for policy in ("SKIP", "QUEUE"):
        assert f'value="{policy}"' in source
    assert '"Asia/Shanghai"' in source
    assert 'http.PUT("/api/batch-runs/{batch_id}/schedule"' in api
    assert ".batch-schedule-grid" in styles


def test_batch_case_detail_leads_with_actionable_diagnosis_and_defers_raw_data():
    javascript = read(STATIC_DIR / "execution.js")

    assert "function batchCaseDetailModel" in javascript
    assert "function batchCaseProblemNode" in javascript
    assert "问题节点" in javascript
    assert "工作流停在此处" in javascript
    assert "期望值" in javascript and "实际值" in javascript
    assert "错误与节点日志" in javascript
    assert "batch-case-debug-content" in javascript
    assert "<details" in javascript


def test_management_navigation_and_lists_share_visual_contract():
    html = read(STATIC_DIR / "index.html")
    batch = read(BATCH_SOURCE)
    providers = read(ROOT / "web" / "frontend" / "model-providers.jsx")
    test_sets = read(ROOT / "web" / "frontend" / "test-sets.jsx")
    workflow = read(STATIC_DIR / "execution.js")
    global_styles = read(STATIC_DIR / "style.css")

    for label in ("测试集管理", "供应商管理", "工作流管理", "任务调度"):
        assert f"<span>{label}</span>" in html
    assert 'className="table execution-table management-list-table batch-table"' in batch
    assert 'className="table execution-table management-list-table model-provider-table"' in providers
    assert 'className="table execution-table management-list-table' in test_sets
    assert 'class="table execution-table management-list-table workflow-table"' in workflow
    assert ".management-list-wrap.table-wrap" in global_styles
    assert ".management-list-footer.global-list-footer" in global_styles


def test_batch_config_uses_schema_validation_and_inline_accessible_errors():
    source = read(BATCH_SOURCE)
    styles = read(STATIC_DIR / "execution.css")

    assert "const batchConfigSchema = z.object" in source
    assert "resolver: zodResolver(batchConfigSchema)" in source
    assert "formState: { errors }" in source
    for field_id in (
        "batch-name-error",
        "batch-failure-retry-count-error",
        "batch-test-set-error",
        "batch-workflow-error",
        "batch-concurrency-error",
    ):
        assert field_id in source
    assert source.count('className="batch-field-error"') == 5
    assert source.count('role="alert"') >= 5
    assert 'aria-invalid={Boolean(errors.name)}' in source
    assert ".batch-field-error" in styles
    assert '.batch-create-grid [aria-invalid="true"]' in styles


def test_batch_config_keeps_confirmed_layout_and_business_fields():
    source = read(BATCH_SOURCE)
    styles = read(STATIC_DIR / "execution.css")

    fields = [
        'id="batch-name"',
        'id="batch-failure-retry-count"',
        'id="batch-test-set"',
        'id="batch-workflow"',
        'id="batch-case-display-column"',
        'id="batch-rule-display-column"',
        'id="batch-call-order"',
        'id="batch-concurrency"',
    ]
    assert [source.index(field) for field in fields] == sorted(source.index(field) for field in fields)
    assert 'className="batch-config-card" aria-label="基础配置"' in source
    assert "测试集概览" not in source
    assert ".batch-config-card" in styles
    assert "grid-template-columns: 72px minmax(220px, 360px);" in styles


def test_batch_variable_and_evaluation_sections_keep_business_validation():
    source = read(BATCH_SOURCE)
    styles = read(STATIC_DIR / "execution.css")

    assert "function VariableRows" in source
    assert "function RuleRows" in source
    assert 'className="batch-section-heading"' in source
    assert "变量注入" in source
    assert "结果校验" in source
    assert "请至少配置一个变量注入" in source
    assert "Key 格式无效" in source
    assert "校验规则 ${i + 1} 的路径不能为空" in source
    assert 'placeholder="例如 action_match"' in source
    assert ".batch-variable-table," in styles
    assert ".batch-variable-row:hover," in styles


def test_batch_dialogs_use_project_radix_wrapper():
    source = read(BATCH_SOURCE)
    dialog = read(DIALOG_SOURCE)

    assert 'import { ConfirmDialog, ModalDialog } from "./components/dialog"' in source
    assert "<ModalDialog" in source
    assert "<ConfirmDialog" in source
    assert 'from "@radix-ui/react-dialog"' in dialog
    assert 'from "@radix-ui/react-alert-dialog"' in dialog
    assert "executionModalFocusableElements" not in source
