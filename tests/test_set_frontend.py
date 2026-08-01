from pathlib import Path


STATIC_DIR = Path(__file__).parents[1] / "web" / "static"


def test_test_set_modals_and_edit_controls_are_keyboard_accessible():
    source = (Path(__file__).parents[1] / "web" / "frontend" / "test-sets.jsx").read_text(encoding="utf-8")

    assert "function useModalAccessibility(onClose)" in source
    assert source.count('role="dialog" aria-modal="true"') == 3
    assert 'if (event.key === "Escape")' in source
    assert "returnFocus?.isConnected" in source
    assert 'title="编辑测试集名称"' in source
    assert 'title="编辑测试集说明"' in source
    assert "onDoubleClick" not in source[source.index('return <section className="ts-page"><div className="ts-detail-heading"'):]
    assert 'aria-label={`用例 ${(page - 1) * casePageSize + rowIndex + 1} ${column}`}' in source


def test_test_set_destructive_confirmations_use_application_modals():
    root = Path(__file__).parents[1]
    source = (root / "web" / "frontend" / "test-sets.jsx").read_text(encoding="utf-8")
    styles = (root / "web" / "frontend" / "test-sets.css").read_text(encoding="utf-8")

    assert "window.confirm" not in source
    assert "function ConfirmModal(" in source
    assert 'title="删除测试集"' in source
    assert 'title="删除字段"' in source
    assert "useModalAccessibility(onClose)" in source
    assert ".ts-confirm-modal-layer" in styles
    assert ".ts-btn.danger" in styles


def test_test_set_detail_defaults_to_twenty_editable_rows():
    source = (Path(__file__).parents[1] / "web" / "frontend" / "test-sets.jsx").read_text(encoding="utf-8")

    assert "const CASE_PAGE_SIZE = 20;" in source
    assert "const CASE_PAGE_SIZE = 50;" not in source


def test_excel_import_stays_in_the_browser_and_uses_database_api():
    root = Path(__file__).parents[1]
    source = (root / "web" / "frontend" / "test-sets.jsx").read_text(
        encoding="utf-8"
    )
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "await file.arrayBuffer()" in source
    assert "XLSX.read(" in source
    assert 'request("/api/test-sets"' in source
    assert "/api/excel" not in source
    assert "/api/excel" not in app_js
    assert "/api/testcases" not in app_js
    assert "API.upload" not in app_js


def test_database_test_set_tables_keep_shared_center_alignment():
    source = (Path(__file__).parents[1] / "web" / "frontend" / "test-sets.jsx").read_text(encoding="utf-8")
    source_css = (Path(__file__).parents[1] / "web" / "frontend" / "test-sets.css").read_text(encoding="utf-8")

    assert ".ts-table th,.ts-table td" in source_css
    assert "text-align:center" in source_css
    assert ".ts-table .ts-name{justify-content:center;margin:0 auto;color:var(--color-accent)}" in source_css
    assert ".ts-table .ts-actions{justify-content:center}" in source_css
    assert 'className="table execution-table management-list-table ts-table ts-list-table"' in source
    assert 'className="management-list-actions-head">操作</th>' in source
    assert 'className="management-list-actions-cell"' in source
    assert '<PageControls management total={state.total}' in source
    assert "--management-list-min-width: 960px;" in source_css


def test_test_set_list_refresh_preserves_rows_and_avoids_duplicate_initial_load():
    source = (Path(__file__).parents[1] / "web" / "frontend" / "test-sets.jsx").read_text(encoding="utf-8")

    assert "const initialQueryEffect = useRef(true);" in source
    assert "if (initialQueryEffect.current)" in source
    assert "initialQueryEffect.current = false;" in source
    assert "}, [query]);" in source
    assert "const requestId = ++loadRequestId.current;" in source
    assert "if (requestId !== loadRequestId.current) return;" in source
    assert 'disabled={loading} onClick={() => load(page, query)}' in source
    assert 'aria-busy={loading}' in source
    assert "loading && !state.items.length" in source
    assert "!!state.items.length && state.items.map" in source
    assert "!loading && state.items.map" not in source


def test_test_set_management_title_matches_other_management_pages():
    source_css = (Path(__file__).parents[1] / "web" / "frontend" / "test-sets.css").read_text(encoding="utf-8")

    title_rule = source_css[source_css.index(".ts-heading.execution-page-header h1 {"):]
    title_rule = title_rule[:title_rule.index("}")]
    header_rule = source_css[source_css.index(".ts-heading.execution-page-header {"):]
    header_rule = header_rule[:header_rule.index("}")]

    assert "font-size: 24px;" in title_rule
    assert "line-height: 1.2;" in title_rule
    assert "letter-spacing: -0.025em;" in title_rule
    assert "min-height: 52px;" in header_rule
    assert "margin-bottom: 14px;" in header_rule
    assert ".ts-heading.execution-page-header.management-page-header" not in source_css


def test_test_set_react_root_unmounts_before_other_navigation_views():
    root = Path(__file__).parents[1]
    source = (root / "web" / "frontend" / "test-sets.jsx").read_text(encoding="utf-8")
    app_js = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert "function unmount()" in source
    assert "root.unmount();" in source
    assert "root = null;" in source
    assert "window.currentView = \"sets\";" in source
    assert "window.TestSetManagement = { mount, unmount };" in source
    assert "if (view !== 'sets' && window.TestSetManagement) window.TestSetManagement.unmount();" in app_js


def test_test_set_list_name_has_no_leading_icon():
    root = Path(__file__).parents[1]
    source = (root / "web" / "frontend" / "test-sets.jsx").read_text(encoding="utf-8")
    source_css = (root / "web" / "frontend" / "test-sets.css").read_text(encoding="utf-8")

    list_row = source[source.index("state.items.map((item)"):source.index("<PageControls management total={state.total}")]
    assert "<i>▦</i>" not in list_row
    assert ".ts-name i{" not in source_css


def test_manual_case_is_inserted_first_and_auto_saves_on_row_blur():
    root = Path(__file__).parents[1]
    source = (root / "web" / "frontend" / "test-sets.jsx").read_text(
        encoding="utf-8"
    )
    source_css = (root / "web" / "frontend" / "test-sets.css").read_text(
        encoding="utf-8"
    )

    assert 'const nextCases = [pendingCase, ...draft.cases];' in source
    assert 'className={`ts-new-case-row${pendingCaseError ? " error" : ""}`}' in source
    assert "!pendingCaseRowRef.current?.contains(event.relatedTarget)" in source
    assert "void savePendingCase();" in source
    assert "内容已保留，请修改后再次点击行外或重试" in source
    assert ".ts-new-case-row {" in source_css
    new_row_styles = source_css[source_css.index(".ts-new-case-row {"):]
    new_row_styles = new_row_styles[:new_row_styles.index("}")]
    assert "background: #eff6ff;" in new_row_styles
    assert "outline:" not in new_row_styles


def test_blank_manual_case_is_removed_without_saving():
    source = (
        Path(__file__).parents[1] / "web" / "frontend" / "test-sets.jsx"
    ).read_text(encoding="utf-8")

    blank_check = 'if (isBlankCase(pendingCase)) {'
    save_request = 'const savePromise = request(`/api/test-sets/${draft.id}`'

    assert 'draft.columns.every((column) => !String(testCase.values[column] ?? "").trim())' in source
    assert blank_check in source
    assert source.index(blank_check) < source.index(save_request)
    assert 'setPendingCase(null);' in source[source.index(blank_check):source.index(save_request)]


def test_test_set_metadata_uses_inline_blur_save_without_replacing_case_draft():
    source = (
        Path(__file__).parents[1] / "web" / "frontend" / "test-sets.jsx"
    ).read_text(encoding="utf-8")

    assert 'request(`/api/test-sets/${draft.id}/metadata`' in source
    assert 'metadataDraftRef.current.name === draft.name ? event.currentTarget.value : metadataDraftRef.current.name' in source
    assert 'metadataDraftRef.current.description === draft.description ? event.currentTarget.value : metadataDraftRef.current.description' in source
    assert 'metadataDraftRef.current.name = event.target.value' in source
    assert 'metadataDraftRef.current.description = event.target.value' in source
    assert 'setDraft((current) => current ? { ...current, ...metadata } : payload.test_set);' in source
    assert 'toast("测试集名称不能为空", "error")' in source


def test_management_lists_use_names_as_the_only_edit_entry():
    root = Path(__file__).parents[1]
    test_sets = (root / "web" / "frontend" / "test-sets.jsx").read_text(encoding="utf-8")
    providers = (root / "web" / "static" / "model-providers.js").read_text(encoding="utf-8")
    workflows = (root / "web" / "static" / "execution.js").read_text(encoding="utf-8")

    list_row = test_sets[test_sets.index("state.items.map((item)"):test_sets.index("<PageControls management total={state.total}")]
    provider_row = providers[providers.index("body.innerHTML = providers.map"):providers.index("body.querySelectorAll('[data-provider-edit]')")]
    workflow_row = workflows[workflows.index("body.innerHTML = pagination.items.map"):workflows.index("body.querySelectorAll('[data-workflow-open]')")]

    assert list_row.count('onOpen(item.id)') == 1
    assert "<strong>{item.name}</strong>" not in list_row
    assert provider_row.count("data-provider-edit") == 1
    assert workflow_row.count("data-workflow-open") == 1
    assert workflow_row.count("data-workflow-copy") == 1
    assert 'title="拷贝工作流" aria-label="拷贝工作流"' in workflow_row
