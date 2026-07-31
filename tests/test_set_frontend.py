from pathlib import Path


STATIC_DIR = Path(__file__).parents[1] / "web" / "static"


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
    source_css = (Path(__file__).parents[1] / "web" / "frontend" / "test-sets.css").read_text(encoding="utf-8")

    assert ".ts-table th,.ts-table td" in source_css
    assert "text-align:center" in source_css
    assert ".ts-table .ts-name{justify-content:center;margin:0 auto}" in source_css
    assert ".ts-table .ts-actions{justify-content:center}" in source_css


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

    list_row = source[source.index("state.items.map((item)"):source.index("<PageControls total={state.total}")]
    assert "<i>▦</i>" not in list_row
    assert ".ts-name i{" not in source_css
