from pathlib import Path


def test_batch_frontend_exposes_creation_mapping_progress_and_recovery():
    static = Path(__file__).resolve().parents[1] / "web" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    javascript = (static / "execution.js").read_text(encoding="utf-8")
    styles = (static / "execution.css").read_text(encoding="utf-8")

    assert 'data-view="batch-runs"' in html
    assert "function viewBatchRuns()" in javascript
    assert "/api/batch-runs/preview" in javascript
    assert "await loadBatchPreview(sourceBatch);" in javascript
    assert "batchPreviewRequestId" in javascript
    assert "正在读取表头..." in javascript
    assert "id=\"batch-header-mode\"" in javascript
    assert "header_mode: document.getElementById('batch-header-mode').value" in javascript
    assert "document.getElementById('batch-case-id').addEventListener('change', function () { loadBatchPreview(); })" in javascript
    assert "case_id_column" in javascript
    assert "header === selectedCaseIdHeader ? ''" in javascript
    assert "case_concurrency" in javascript
    assert "retry_failed" in javascript
    assert "workflow_execution_ids" in javascript
    assert 'data-batch-edit="' in javascript
    assert "openBatchCreate(button.getAttribute('data-batch-edit'))" in javascript
    assert "sourceBatch ? '编辑 Run 配置' : '创建批量 Run'" in javascript
    assert "sourceBatch ? '创建新 Run' : '创建'" in javascript
    assert "sourceBatch.input.case_id_column" in javascript
    assert "sourceBatch.case_concurrency" in javascript
    assert "sourceMappings.get(header)" in javascript
    assert 'id="batch-rule-add"' in javascript
    assert "function renderBatchEvaluationRules(rules, headers)" in javascript
    assert "evaluation_rules: evaluationRules" in javascript
    assert "sourceBatch.evaluation_rules || []" in javascript
    assert "batchVerdictSummary(batch)" in javascript
    assert "item.execution_status || item.status" in javascript
    assert "batchVerdictLabel(caseRun.verdict)" in javascript
    assert "execution ? execution.result : {}" in javascript
    assert "document.getElementById('btn-batch-add').addEventListener('click', function () { openBatchCreate(); })" in javascript
    assert "classList.add('is-batch-config')" in javascript
    assert ".execution-modal.is-batch-config {\n    width: min(1180px, calc(100vw - 48px));" in styles
    assert ".execution-modal.is-batch-config { width: calc(100vw - 16px); }" in styles
    assert ".batch-evaluation-rule label[hidden] { display: none; }" in styles
    assert ".batch-evaluation-rule .input { width: 100%; min-width: 0; }" in styles
