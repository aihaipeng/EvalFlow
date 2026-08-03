import json
from pathlib import Path


STATIC_DIR = Path(__file__).parents[1] / "web" / "static"


def test_test_set_modals_and_edit_controls_are_keyboard_accessible():
    source = (Path(__file__).parents[1] / "web" / "frontend" / "test-sets.jsx").read_text(encoding="utf-8")

    assert 'from "@radix-ui/react-dialog"' in source
    assert 'from "@radix-ui/react-alert-dialog"' in source
    assert source.count("<Dialog.Root") == 2
    assert source.count("<AlertDialog.Root") == 2
    assert "function useModalAccessibility" not in source
    assert 'aria-labelledby="ts-save-modal-title"' in source
    assert 'aria-labelledby="ts-column-settings-title"' in source
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
    assert "<AlertDialog.Content" in source
    assert ".ts-confirm-modal-layer" in styles
    assert "btn-danger" in source


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
    assert 'import("@fortune-sheet/react")' in source
    assert 'import("xlsx")' in source
    assert 'import("@fortune-sheet/react/dist/index.css")' in source
    assert 'import { Workbook } from "@fortune-sheet/react"' not in source
    assert 'import * as XLSX from "xlsx"' not in source
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


def test_test_set_list_omits_summary_metric_cards():
    source = (Path(__file__).parents[1] / "web" / "frontend" / "test-sets.jsx").read_text(
        encoding="utf-8"
    )

    list_view = source[source.index("function ListView("):source.index("function SaveModal(")]
    assert "<Metrics items=" not in list_view
    assert '<span className="execution-count">{state.total} 个测试集</span>' in list_view


def test_test_set_detail_uses_consistent_semantic_title():
    root = Path(__file__).parents[1]
    source = (root / "web" / "frontend" / "test-sets.jsx").read_text(encoding="utf-8")
    source_css = (root / "web" / "frontend" / "test-sets.css").read_text(encoding="utf-8")

    assert '<h1 className="ts-detail-name-heading">' in source
    title_rule = source_css[source_css.index(".ts-detail-name-heading {"):]
    title_rule = title_rule[:title_rule.index("}")]
    assert "font-size: 20px;" in title_rule
    assert "font-weight: 700;" in title_rule


def test_test_set_react_root_unmounts_before_other_navigation_views():
    root = Path(__file__).parents[1]
    source = (root / "web" / "frontend" / "test-sets.jsx").read_text(encoding="utf-8")
    app_js = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert "function unmount()" in source
    assert "root.unmount();" in source
    assert "root = null;" in source
    assert "window.currentView = \"sets\";" in source
    assert "window.TestSetManagement = { mount, unmount, requestLeave: () => requestLeaveHandler() };" in source
    assert "if (view !== 'sets' && window.TestSetManagement) window.TestSetManagement.unmount();" in app_js


def test_built_test_set_entry_defers_excel_dependencies():
    root = Path(__file__).parents[1]
    output = root / "web" / "static" / "assets" / "vite"
    manifest = json.loads((output / ".vite" / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["web/frontend/test-sets.jsx"]
    script = output / entry["file"]

    assert script.stat().st_size < 500_000
    assert "node_modules/@fortune-sheet/react/dist/index.esm.js" in entry["dynamicImports"]
    assert "node_modules/xlsx/xlsx.mjs" in entry["dynamicImports"]


def test_test_set_list_name_has_no_leading_icon():
    root = Path(__file__).parents[1]
    source = (root / "web" / "frontend" / "test-sets.jsx").read_text(encoding="utf-8")
    source_css = (root / "web" / "frontend" / "test-sets.css").read_text(encoding="utf-8")

    list_row = source[source.index("state.items.map((item)"):source.index("<PageControls management total={state.total}")]
    assert "<i>▦</i>" not in list_row
    assert ".ts-name i{" not in source_css


def test_manual_case_is_inserted_first_as_unsaved_draft_on_row_blur():
    root = Path(__file__).parents[1]
    source = (root / "web" / "frontend" / "test-sets.jsx").read_text(
        encoding="utf-8"
    )
    source_css = (root / "web" / "frontend" / "test-sets.css").read_text(
        encoding="utf-8"
    )

    assert 'const nextCases = [pendingCase, ...draft.cases];' in source
    assert 'className="ts-new-case-row"' in source
    assert "!pendingCaseRowRef.current?.contains(event.relatedTarget)" in source
    assert "commitPendingCaseDraft();" in source
    assert 'setDraft((current) => ({ ...current, cases: nextCases }));' in source
    assert '<span>未保存</span>' in source
    assert "savePendingCase" not in source
    assert ".ts-new-case-row {" in source_css
    new_row_styles = source_css[source_css.index(".ts-new-case-row {"):]
    new_row_styles = new_row_styles[:new_row_styles.index("}")]
    assert "background: #eff6ff;" in new_row_styles
    assert "outline:" not in new_row_styles


def test_blank_manual_case_is_removed_without_saving():
    source = (
        Path(__file__).parents[1] / "web" / "frontend" / "test-sets.jsx"
    ).read_text(encoding="utf-8")

    blank_check = 'if (isBlankCaseValues(pendingCase.values, draft.columns)) {'
    assert blank_check in source
    draft_start = source.index("function commitPendingCaseDraft()")
    draft_function = source[draft_start:source.index("async function save()", draft_start)]
    assert 'setPendingCase(null);' in draft_function
    assert 'request(' not in draft_function


def test_test_set_import_and_save_filter_blank_cases():
    source = (
        Path(__file__).parents[1] / "web" / "frontend" / "test-sets.jsx"
    ).read_text(encoding="utf-8")

    assert "function isBlankCaseValues(values, columns)" in source
    assert "function filterBlankCases(cases, columns)" in source
    assert "return { columns, cases: filterBlankCases(cases, columns) };" in source
    assert "cases: filterBlankCases(dataset.cases, dataset.columns)" in source
    assert "cases: filterBlankCases([...target.cases, ...appended], target.columns)" in source
    assert "const nonBlankCases = filterBlankCases(cases, draft.columns);" in source


def test_test_set_metadata_blur_keeps_draft_until_explicit_save():
    source = (
        Path(__file__).parents[1] / "web" / "frontend" / "test-sets.jsx"
    ).read_text(encoding="utf-8")

    assert 'request(`/api/test-sets/${draft.id}/metadata`' not in source
    assert 'onBlur={() => setEditingName(false)}' in source
    assert 'onBlur={() => setEditingDescription(false)}' in source
    assert 'request(`/api/test-sets/${draft.id}`, { method: "PUT", body: writeBody(nextCases) })' in source
    assert 'disabled={saving || !dirty}' in source
    assert 'toast("测试集名称不能为空", "error")' in source


def test_test_set_navigation_waits_for_unsaved_leave_decision():
    root = Path(__file__).parents[1]
    source = (root / "web" / "frontend" / "test-sets.jsx").read_text(encoding="utf-8")
    app_source = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert "function UnsavedChangesModal" in source
    assert "不保存并离开" in source
    assert "保存并离开" in source
    assert "requestLeave: () => requestLeaveHandler()" in source
    assert "await window.TestSetManagement.requestLeave()" in app_source
    assert "if (!canLeave) return;" in app_source
    assert "if (view === currentView) return;" in app_source


def test_management_lists_use_names_as_the_only_edit_entry():
    root = Path(__file__).parents[1]
    test_sets = (root / "web" / "frontend" / "test-sets.jsx").read_text(encoding="utf-8")
    providers = (root / "web" / "frontend" / "model-providers.jsx").read_text(encoding="utf-8")
    workflows = (root / "web" / "static" / "execution.js").read_text(encoding="utf-8")

    list_row = test_sets[test_sets.index("state.items.map((item)"):test_sets.index("<PageControls management total={state.total}")]
    provider_start = providers.index("rows.map((provider)")
    provider_row = providers[provider_start:providers.index("<Pagination", provider_start)]
    workflow_row = workflows[workflows.index("body.innerHTML = pagination.items.map"):workflows.index("body.querySelectorAll('[data-workflow-open]')")]

    assert list_row.count('onOpen(item.id)') == 1
    assert "<strong>{item.name}</strong>" not in list_row
    assert provider_row.count("onEdit(provider.id)") == 1
    assert workflow_row.count("data-workflow-open") == 1
    assert workflow_row.count("data-workflow-copy") == 1
    assert 'title="拷贝工作流" aria-label="拷贝工作流"' in workflow_row
