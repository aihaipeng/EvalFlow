from pathlib import Path


STATIC_DIR = Path(__file__).parents[1] / "web" / "static"


def test_set_storage_identifiers_open_their_existing_directories():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    style_css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")

    assert 'class="list-meta-link set-file-link"' in app_js
    assert "tbody.querySelectorAll('.set-file-link').forEach(bindSetFilenameLink)" in app_js
    assert "if (filename) openDir(filename)" in app_js
    assert "e.stopPropagation()" in app_js
    assert ".list-meta-link" in style_css
    assert "font-size: 11px" in style_css
    assert '<th class="col-address" data-col="address">地址</th>' in app_js
    assert app_js.count('class="action-buttons action-buttons-single"') == 1
    assert 'data-action="edit"' not in app_js
    assert 'data-action="open-dir"' not in app_js
    assert app_js.count('data-action="delete"') == 1
    assert "--set-data-col-w: calc((100% - 36px) / 5)" in style_css
    assert ".action-buttons-single" in style_css


def test_set_list_declares_its_sort_marker_before_initial_render():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "function setSortMark(field)" in app_js
    assert "setsSortDir === 'asc' ? '▲' : '▼'" in app_js
    assert app_js.index("function setSortMark(field)") < app_js.index("function viewSets()")


def test_set_editor_uses_one_row_fields_and_compact_header_metadata():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    style_css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")

    assert 'class="breadcrumb set-edit-header"' in app_js
    assert 'class="breadcrumb-title set-edit-header-title"' in app_js
    assert 'class="breadcrumb-meta set-edit-file-meta"' in app_js
    assert app_js.count('class="form-row-horizontal set-edit-field"') == 2
    assert 'type="text" class="input set-description-input"' in app_js
    assert '<textarea class="input set-description-input"' not in app_js
    assert "found[0].filename + ' · ' + formatSize(found[0].size)" in app_js
    assert ".set-edit-grid" in style_css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in style_css


def test_batch_action_groups_shift_left_and_set_checkboxes_share_a_size():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    style_css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")

    assert app_js.count('class="toolbar-batch-actions"') == 1
    sets_toolbar = app_js[
        app_js.index('id="sets-toolbar"') : app_js.index("function bindSetsEvents")
    ]
    set_actions = sets_toolbar[sets_toolbar.index('class="toolbar-batch-actions"') :]
    assert 'id="btn-delete-batch"' in set_actions
    assert ".toolbar-batch-actions" in style_css
    assert "margin-right: 40px" in style_css
    assert 'input[type="checkbox"].row-check,\n#check-all {' in style_css
    assert "width: 16px;\n    height: 16px;" in style_css


def test_set_batch_delete_button_tracks_the_current_page_selection_count():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "function updateSetBatchDeleteState()" in app_js
    assert "var checked = getCheckedFilenames();" in app_js
    assert "var all = getAllFilenamesOnPage();" in app_js
    assert (
        "deleteBtn.innerHTML = icon('trash') + "
        "(checked.length > 0 ? '删除 ' + checked.length : '删除');"
    ) in app_js
    assert "checkAll.checked = all.length > 0 && checked.length === all.length" in app_js
    assert (
        "checkAll.indeterminate = checked.length > 0 && checked.length < all.length"
        in app_js
    )
    assert app_js.count("updateSetBatchDeleteState();") >= 4


def test_case_list_headers_and_rows_are_centered():
    style_css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")

    assert "#browse-table th,\n#browse-table td {\n    text-align: center;\n}" in style_css


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
