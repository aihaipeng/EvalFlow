from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[1] / "web" / "static"


def test_batch_frontend_uses_database_test_sets_and_saved_workflows():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    javascript = (STATIC_DIR / "execution.js").read_text(encoding="utf-8")
    styles = (STATIC_DIR / "execution.css").read_text(encoding="utf-8")

    assert 'data-view="batch-runs"' in html
    assert "API.get('/api/test-sets?page=1&page_size=200')" in javascript
    assert "API.get('/api/workflows')" in javascript
    assert 'id="batch-test-set"' in javascript
    assert 'id="batch-workflow"' in javascript
    assert 'id="batch-description"' in javascript
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
    assert "description: document.getElementById('batch-description').value" in javascript
    assert "sourceBatch.description || ''" in javascript
    assert "sourceBatch.input.test_set_id" in javascript
    assert "sourceBatch.workflow.id" in javascript
    assert "sourceBatch.case_concurrency" in javascript
    assert "sourceBatch.input.call_order ? sourceBatch.input.call_order.mode : 'SEQUENTIAL'" in javascript
    assert "variables: variables" in javascript
    assert "call_order: document.getElementById('batch-call-order').value" in javascript
    assert "evaluation_rules: evaluationRules" in javascript
    assert "if (executionState.batchCreating) return;" in javascript
    assert "executionState.batchCreating = false;" in javascript
    assert "classList.add('is-batch-config')" in javascript
    assert ".execution-modal.is-batch-config {\n    width: min(1180px, calc(100vw - 48px));" in styles


def test_batch_list_and_details_hide_status_and_verdict_columns():
    javascript = (STATIC_DIR / "execution.js").read_text(encoding="utf-8")

    list_view = javascript[
        javascript.index("function renderBatchTable()"):
        javascript.index("async function openBatchCreate")
    ]
    detail_view = javascript[
        javascript.index("async function viewBatchDetail"):
        javascript.index("async function openBatchCaseDetail")
    ]
    case_detail = javascript[javascript.index("async function openBatchCaseDetail"):]

    assert '<th>名称</th><th>说明</th><th>测试集</th><th>工作流</th><th>进度</th>' in list_view
    assert 'class="batch-description"' in list_view
    assert "batch.description || ''" in list_view
    assert '<th>状态</th>' not in list_view
    assert '<th>测试判定</th>' not in list_view
    assert "batch.input.test_set_name" in list_view
    assert "batch.input.filename" not in list_view
    assert "用例序号" in detail_view
    assert "执行状态" not in detail_view
    assert "测试判定" not in detail_view
    assert "batch-summary" not in detail_view
    assert "执行状态" not in case_detail
    assert "测试判定" not in case_detail
    assert "校验明细" not in case_detail
    assert "工作流结果" in case_detail
    assert "batchStatusLabel" not in javascript
    assert "batchVerdictLabel" not in javascript


def test_management_navigation_labels_icons_pagination_and_alignment_are_consistent():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    javascript = (STATIC_DIR / "execution.js").read_text(encoding="utf-8")
    styles = (STATIC_DIR / "execution.css").read_text(encoding="utf-8")
    global_styles = (STATIC_DIR / "style.css").read_text(encoding="utf-8")

    for label in ("测试集管理", "供应商管理", "工作流管理", "运行调度"):
        assert f"<span>{label}</span>" in html
    assert html.count('class="sidebar-icon"') == 4
    assert "📋" not in html and "◉" not in html and "◇" not in html and "▶" not in html
    assert ".sidebar-icon .ui-icon" in global_styles
    assert "stroke-width: 1.8" in global_styles
    assert "var GLOBAL_PAGE_SIZE_OPTIONS = [10, 20, 50, 100];" in app_js
    assert 'id="workflow-pagination" class="global-list-footer"' in javascript
    assert 'id="batch-pagination" class="global-list-footer"' in javascript
    assert 'id="batch-case-pagination" class="global-list-footer"' in javascript
    assert ".execution-table th,\n.execution-table td {\n    text-align: center;" in styles
    assert ".batch-progress {\n    display: grid;\n    width: 150px;\n    margin: 0 auto;" in styles
    assert ".batch-row-actions {\n    display: inline-flex;\n    align-items: center;\n    justify-content: center;" in styles

def test_batch_run_config_uses_confirmed_impeccable_layout():
    javascript = (STATIC_DIR / "execution.js").read_text(encoding="utf-8")
    styles = (STATIC_DIR / "execution.css").read_text(encoding="utf-8")

    config_view = javascript[
        javascript.index("var body =", javascript.index("async function openBatchCreate")):
        javascript.index("openExecutionModal(sourceBatch", javascript.index("async function openBatchCreate"))
    ]

    assert 'class="batch-config-card" aria-label="基础配置"' in config_view
    field_order = [
        'id="batch-name"',
        'id="batch-description"',
        'id="batch-test-set"',
        'id="batch-workflow"',
        'id="batch-call-order"',
        'id="batch-concurrency"',
    ]
    assert [config_view.index(field) for field in field_order] == sorted(
        config_view.index(field) for field in field_order
    )
    assert '<span>执行顺序</span>' in config_view
    assert '<span>并发数</span>' in config_view
    assert '测试集概览' not in config_view
    assert 'batch-preview-meta' not in config_view
    assert ".batch-config-card {" in styles
    assert ".batch-run-options {" not in styles
    assert ".batch-field-wide {" not in styles
    assert ".batch-description {" in styles
    assert "grid-template-columns: 72px minmax(220px, 360px);" in styles
    assert ".batch-create-grid label > span {" in styles
    assert "text-align: right;" in styles

def test_batch_variable_and_evaluation_sections_use_management_table_layout():
    javascript = (STATIC_DIR / "execution.js").read_text(encoding="utf-8")
    styles = (STATIC_DIR / "execution.css").read_text(encoding="utf-8")

    config_view = javascript[
        javascript.index("var body =", javascript.index("async function openBatchCreate")):
        javascript.index("openExecutionModal(sourceBatch", javascript.index("async function openBatchCreate"))
    ]
    variable_view = javascript[
        javascript.index("function renderBatchVariables"):
        javascript.index("function addBatchVariable")
    ]
    evaluation_view = javascript[
        javascript.index("function renderBatchEvaluationRules"):
        javascript.index("function addBatchEvaluationRule")
    ]

    assert 'class="batch-section-heading"><strong>变量注入</strong><span>' in config_view
    assert 'class="batch-section-heading"><strong>结果校验</strong></div>' in config_view
    assert "全部校验点通过时，用例才通过" not in config_view
    assert ">类型</span>" in variable_view
    assert ">类型</span>" in evaluation_view
    assert ">Type</span>" not in variable_view
    assert ">Type</span>" not in evaluation_view
    assert '<label><span>结果路径</span>' not in evaluation_view
    assert '<label><span>运算符</span>' not in evaluation_view
    assert '<label><span>预期值</span>' not in evaluation_view
    assert '<span class="batch-mobile-label">结果路径</span>' in evaluation_view
    assert '<span class="batch-mobile-label">运算符</span>' in evaluation_view
    assert '<span class="batch-mobile-label">预期值</span>' in evaluation_view
    assert ".batch-section-heading strong {" in styles
    assert "font-size: 16px;" in styles
    assert ".batch-variable-table," in styles
    assert "overflow-x: auto;" in styles
    assert "border: 1px solid var(--border);" in styles
    assert ".batch-variable-row:hover," in styles
