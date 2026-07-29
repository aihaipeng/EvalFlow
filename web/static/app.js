/* ===== API Client ===== */
async function apiResponsePayload(res) {
    var text = await res.text();
    var payload = null;
    if (text) {
        try { payload = JSON.parse(text); } catch (_error) { payload = null; }
    }
    if (!res.ok) {
        var detail = payload && payload.detail;
        if (Array.isArray(detail)) {
            detail = detail.map(function (item) { return item.msg || String(item); }).join('；');
        } else if (detail && typeof detail === 'object') {
            detail = detail.message || JSON.stringify(detail);
        }
        throw new Error(detail || text || res.statusText || ('HTTP ' + res.status));
    }
    return payload;
}

var API = {
    get: async function (url) {
        var res = await fetch(url);
        return apiResponsePayload(res);
    },
    post: async function (url, body, options) {
        var res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            signal: options && options.signal,
        });
        return apiResponsePayload(res);
    },
    put: async function (url, body) {
        var res = await fetch(url, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        return apiResponsePayload(res);
    },
    patch: async function (url, body) {
        var res = await fetch(url, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        return apiResponsePayload(res);
    },
    upload: async function (url, formData) {
        var res = await fetch(url, { method: 'POST', body: formData });
        return apiResponsePayload(res);
    },
    del: async function (url) {
        var res = await fetch(url, { method: 'DELETE' });
        return apiResponsePayload(res);
    },
};


/* ===== Toast ===== */
function showToast(msg, type) {
    var el = document.getElementById('toast');
    el.textContent = msg;
    el.className = 'toast ' + type;
    setTimeout(function () { el.classList.add('hidden'); }, 3000);
}

/* ===== DOM Refs ===== */
var contentArea = document.getElementById('content-area');
var fileInput = document.getElementById('file-input');

/* ===== State ===== */
var currentView = 'sets';
var browseFilename = null;
var browseFileMeta = null;  // {size, updated_at}
var browseSheet = null;
var setsPage = 1;
var setsPageSize = 20;
var setsSortBy = 'updated_at';
var setsSortDir = 'desc';
var setsNameQuery = '';
var casesPage = 1;
var casesPageSize = 50;
var importFiles = [];
var nameClickTimer = null;

function setSortMark(field) {
    if (setsSortBy !== field) return '';
    return '<span aria-hidden="true">' + (setsSortDir === 'asc' ? '▲' : '▼') + '</span>';
}

function icon(name) {
    return window.AppIcons ? window.AppIcons.icon(name) : '';
}

var THEME_STORAGE_KEY = 'agent-bench-theme';

function storedTheme() {
    try {
        var value = window.localStorage.getItem(THEME_STORAGE_KEY);
        return value === 'light' || value === 'dark' ? value : null;
    } catch (error) {
        return null;
    }
}

function preferredTheme() {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light';
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    var button = document.getElementById('theme-toggle');
    if (!button) return;

    var dark = theme === 'dark';
    var nextLabel = dark ? '白天模式' : '黑夜模式';
    button.setAttribute('aria-label', '切换到' + nextLabel);
    button.setAttribute('aria-pressed', String(dark));
    button.setAttribute('title', '切换到' + nextLabel);
    window.AppIcons.set(button.querySelector('.theme-toggle-icon'), dark ? 'sun' : 'moon');
    button.querySelector('.theme-toggle-label').textContent = nextLabel;
}

function initTheme() {
    applyTheme(storedTheme() || preferredTheme());

    document.getElementById('theme-toggle').addEventListener('click', function () {
        var current = document.documentElement.getAttribute('data-theme');
        var next = current === 'dark' ? 'light' : 'dark';
        try {
            window.localStorage.setItem(THEME_STORAGE_KEY, next);
        } catch (error) {
            // Theme switching still works when browser storage is unavailable.
        }
        applyTheme(next);
    });

    if (!window.matchMedia) return;
    var media = window.matchMedia('(prefers-color-scheme: dark)');
    var syncSystemTheme = function (event) {
        if (!storedTheme()) applyTheme(event.matches ? 'dark' : 'light');
    };
    if (media.addEventListener) media.addEventListener('change', syncSystemTheme);
    else if (media.addListener) media.addListener(syncSystemTheme);
}

function viewSets() {
    currentView = 'sets';
    if (window.TestSetManagement && typeof window.TestSetManagement.mount === 'function') {
        window.TestSetManagement.mount();
        return;
    }
    contentArea.innerHTML = '<div class="loading">正在加载测试集管理…</div>';
}

function init() {
    initTheme();
    viewSets();
}
init();

/* ===== Sidebar Navigation ===== */
document.querySelector('.sidebar-nav').addEventListener('click', function (e) {
    var item = e.target.closest('.sidebar-item');
    if (!item) return;
    document.querySelectorAll('.sidebar-item').forEach(function (el) { el.classList.remove('active'); });
    item.classList.add('active');
    var view = item.getAttribute('data-view');
    if (view !== 'sets' && window.TestSetManagement) window.TestSetManagement.unmount();
    if (view === 'sets') {
        setsPage = 1;
        viewSets();
    } else if (view === 'models') {
        viewModelProviders();
    } else if (view === 'workflows') {
        viewWorkflows();
    } else if (view === 'batch-runs') {
        viewBatchRuns();
    }
});

/* ========================================================================
   View: Test Set List
   ======================================================================== */
async function legacyViewSets() {
    currentView = 'sets';
    browseFilename = null;
    browseSheet = null;

    contentArea.innerHTML =
        '<div class="toolbar" id="sets-toolbar">' +
            '<button class="btn btn-sm" id="btn-import-inline">' + icon('import') + '导入</button>' +
            '<button class="btn btn-sm" id="btn-refresh">' + icon('refresh') + '刷新</button>' +
            '<input type="search" class="input toolbar-search" id="set-name-search" placeholder="按名称搜索..." value="' + escAttr(setsNameQuery) + '" />' +
            '<span class="toolbar-sep"></span>' +
            '<div class="toolbar-batch-actions">' +
                '<button class="btn btn-sm btn-danger" id="btn-delete-batch">' + icon('trash') + '删除</button>' +
            '</div>' +
        '</div>' +
        '<div class="table-wrap" id="sets-table-wrap">' +
            '<table class="table" id="sets-table">' +
                '<thead><tr>' +
                    '<th class="col-check" data-col="check"><input type="checkbox" id="check-all" title="全选" /></th>' +
                    '<th class="col-name" data-col="name">名称</th>' +
                    '<th class="col-desc" data-col="description">说明</th>' +
                    '<th class="col-address" data-col="address">地址</th>' +
                    '<th class="col-updated" data-col="updated">' +
                        '<button class="th-sort" data-set-sort="updated_at" type="button">更新时间 ' + setSortMark('updated_at') + '</button>' +
                    '</th>' +
                    '<th class="col-actions" data-col="actions">操作</th>' +
                '</tr></thead>' +
                '<tbody id="sets-tbody"></tbody>' +
            '</table>' +
        '</div>' +
        '<div id="sets-pagination" class="pagination"></div>';

    bindSetsEvents();
    await loadSets();
    initTableResize('sets-table', 'sets-table-wrap');
}

function bindSetsEvents() {
    document.getElementById('btn-refresh').addEventListener('click', async function () {
        setsPage = 1;
        await loadSets();
        showToast('已刷新', 'success');
    });

    document.getElementById('check-all').addEventListener('change', function () {
        var state = this.checked;
        document.querySelectorAll('#sets-tbody .row-check').forEach(function (c) {
            c.checked = state;
            updateRowSelected(c);
        });
        updateSetBatchDeleteState();
    });

    document.getElementById('btn-import-inline').addEventListener('click', function () {
        openImportModal();
    });

    document.getElementById('set-name-search').addEventListener('input', debounce(async function () {
        setsNameQuery = this.value.trim();
        setsPage = 1;
        await loadSets();
    }, 250));

    document.getElementById('btn-delete-batch').addEventListener('click', function () {
        var checked = getCheckedFilenames();
        if (checked.length === 0) {
            showToast('请先勾选要删除的测试集', 'error');
            return;
        }
        document.getElementById('delete-count').textContent = checked.length;
        document.getElementById('delete-overlay').classList.remove('hidden');
    });

    document.querySelectorAll('#sets-table .th-sort[data-set-sort]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            var nextSort = btn.getAttribute('data-set-sort');
            if (setsSortBy === nextSort) {
                setsSortDir = setsSortDir === 'asc' ? 'desc' : 'asc';
            } else {
                setsSortBy = nextSort;
                setsSortDir = 'desc';
            }
            setsPage = 1;
            await viewSets();
        });
    });
}

function getCheckedFilenames() {
    return Array.from(document.querySelectorAll('#sets-tbody .row-check:checked'))
        .map(function (c) { return c.getAttribute('data-filename'); });
}

function getAllFilenamesOnPage() {
    return Array.from(document.querySelectorAll('#sets-tbody .row-check'))
        .map(function (c) { return c.getAttribute('data-filename'); });
}

function updateRowSelected(cb) {
    var tr = cb.closest('tr');
    if (tr) {
        if (cb.checked) tr.classList.add('row-selected');
        else tr.classList.remove('row-selected');
    }
}

function updateSetBatchDeleteState() {
    var checked = getCheckedFilenames();
    var all = getAllFilenamesOnPage();
    var deleteBtn = document.getElementById('btn-delete-batch');
    if (deleteBtn) {
        deleteBtn.innerHTML = icon('trash') + (checked.length > 0 ? '删除 ' + checked.length : '删除');
    }
    var checkAll = document.getElementById('check-all');
    if (checkAll) {
        checkAll.checked = all.length > 0 && checked.length === all.length;
        checkAll.indeterminate = checked.length > 0 && checked.length < all.length;
    }
}

async function loadSets() {
    try {
        var data = await API.get(
            '/api/excel/sets?page=' + setsPage +
            '&page_size=' + setsPageSize +
            '&sort_by=' + encodeURIComponent(setsSortBy) +
            '&sort_dir=' + encodeURIComponent(setsSortDir) +
            '&name_query=' + encodeURIComponent(setsNameQuery)
        );
        renderSets(data.files);
        renderPagination('sets-pagination', data.total, data.page, data.page_size, function (newPage) {
            setsPage = newPage;
            loadSets();
        });
    } catch (e) {
        showToast('加载测试集失败: ' + e.message, 'error');
    }
}

function renderSets(files) {
    var tbody = document.getElementById('sets-tbody');
    if (!files || files.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-hint">暂无测试集，请先导入</td></tr>';
        updateSetBatchDeleteState();
        return;
    }
    tbody.innerHTML = files.map(function (f) {
        var displayName = f.name || fileStem(f.filename);
        var updatedText = formatDateTime(f.updated_at);
        return '<tr>' +
            '<td class="col-check"><input type="checkbox" class="row-check" data-filename="' + escAttr(f.filename) + '" /></td>' +
            '<td class="col-name-cell" data-filename="' + escAttr(f.filename) + '" data-name="' + escAttr(displayName) + '" data-size-label="' + escAttr(formatSize(f.size)) + '" title="' + escAttr(displayName + '\\n' + f.filename) + '">' +
                '<span class="file-name file-link" data-filename="' + escAttr(f.filename) + '" title="' + escAttr(displayName) + '">' + esc(displayName) + '</span>' +
            '</td>' +
            '<td class="col-desc" data-filename="' + escAttr(f.filename) + '" data-description="' + escAttr(f.description || '') + '" title="' + escAttr(f.description || '未填写') + '">' +
                (f.description ? '<span class="set-description">' + esc(f.description) + '</span>' : '<span class="desc-empty">未填写</span>') +
            '</td>' +
            '<td class="col-address" title="' + escAttr(f.filename) + '">' +
                '<button class="list-meta-link set-file-link" type="button" data-filename="' + escAttr(f.filename) + '" title="打开原始文件所在目录">' + esc(f.filename) + '</button>' +
            '</td>' +
            '<td class="col-updated" title="' + escAttr(updatedText) + '">' + updatedText + '</td>' +
            '<td class="col-actions">' +
                '<div class="action-buttons action-buttons-single">' +
                    '<button class="btn-icon" data-action="delete" data-filename="' + escAttr(f.filename) + '" title="删除测试集" aria-label="删除测试集">' + icon('trash') + '</button>' +
                '</div>' +
            '</td>' +
        '</tr>';
    }).join('');

    // Filename click -> edit
    tbody.querySelectorAll('.file-link').forEach(function (link) {
        link.addEventListener('click', function () {
            var fname = link.getAttribute('data-filename');
            clearTimeout(nameClickTimer);
            nameClickTimer = setTimeout(function () {
                if (fname) viewBrowse(fname);
            }, 220);
        });
    });
    tbody.querySelectorAll('.set-file-link').forEach(bindSetFilenameLink);

    tbody.querySelectorAll('.col-name-cell').forEach(function (cell) {
        cell.addEventListener('dblclick', function (e) {
            e.preventDefault();
            e.stopPropagation();
            clearTimeout(nameClickTimer);
            startInlineNameEdit(cell);
        });
    });

    tbody.querySelectorAll('.col-desc').forEach(function (cell) {
        cell.addEventListener('dblclick', function (e) {
            e.preventDefault();
            e.stopPropagation();
            startInlineDescriptionEdit(cell);
        });
    });

    // Action buttons
    tbody.querySelectorAll('.btn-icon').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
            e.stopPropagation();
            var fname = btn.getAttribute('data-filename');
            if (confirm('确定删除测试集 "' + fname + '"？此操作不可恢复。')) {
                deleteSingleSet(fname);
            }
        });
    });

    // Checkbox
    tbody.querySelectorAll('.row-check').forEach(function (cb) {
        cb.addEventListener('change', function () {
            updateRowSelected(cb);
            updateSetBatchDeleteState();
        });
    });
    updateSetBatchDeleteState();
}

function bindSetFilenameLink(link) {
    if (!link) return;
    link.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        clearTimeout(nameClickTimer);
        var filename = link.getAttribute('data-filename');
        if (filename) openDir(filename);
    });
    link.addEventListener('dblclick', function (e) {
        e.preventDefault();
        e.stopPropagation();
    });
}

function renderNameCell(cell, name) {
    var filename = cell.getAttribute('data-filename') || '';
    var displayName = name || fileStem(filename);
    cell.setAttribute('data-name', displayName);
    cell.setAttribute('title', displayName + '\n' + filename);
    cell.innerHTML = '<span class="file-name file-link" data-filename="' + escAttr(filename) + '" title="' + escAttr(displayName) + '">' + esc(displayName) + '</span>';
    var link = cell.querySelector('.file-link');
    link.addEventListener('click', function () {
        clearTimeout(nameClickTimer);
        nameClickTimer = setTimeout(function () {
            if (filename) viewBrowse(filename);
        }, 220);
    });
}

function startInlineNameEdit(cell) {
    if (cell.classList.contains('editing-name')) return;

    var filename = cell.getAttribute('data-filename');
    var original = cell.getAttribute('data-name') || fileStem(filename);
    cell.classList.add('editing-name');
    cell.innerHTML =
        '<input type="text" class="input inline-name-input" value="' + escAttr(original) + '" />' +
        '<div class="file-meta">' + esc(filename) + '</div>' +
        '<div class="inline-desc-hint">Enter 保存，Esc 取消</div>';

    var input = cell.querySelector('.inline-name-input');
    var done = false;

    var finish = async function (save) {
        if (done) return;
        done = true;
        var next = save ? input.value.trim() : original;
        if (!next) next = original;
        cell.classList.remove('editing-name');
        renderNameCell(cell, next);
        if (save && next !== original) {
            try {
                await API.put('/api/excel/sets/' + encodeURIComponent(filename) + '/meta', {
                    name: next,
                });
                showToast('名称已保存', 'success');
            } catch (e) {
                renderNameCell(cell, original);
                showToast('保存名称失败: ' + e.message, 'error');
            }
        }
    };

    input.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            e.preventDefault();
            finish(false);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            finish(true);
        }
    });

    input.addEventListener('blur', function () {
        finish(true);
    });

    input.focus();
    input.select();
}

function renderDescriptionCell(cell, description) {
    cell.setAttribute('data-description', description || '');
    cell.setAttribute('title', description || '未填写');
    cell.innerHTML = description
        ? '<span class="set-description">' + esc(description) + '</span>'
        : '<span class="desc-empty">未填写</span>';
}

function startInlineDescriptionEdit(cell) {
    if (cell.classList.contains('editing-desc')) return;

    var filename = cell.getAttribute('data-filename');
    var original = cell.getAttribute('data-description') || '';
    cell.classList.add('editing-desc');
    cell.innerHTML =
        '<textarea class="input inline-desc-input" spellcheck="false">' + esc(original) + '</textarea>' +
        '<div class="inline-desc-hint">Enter 保存，Esc 取消</div>';

    var input = cell.querySelector('.inline-desc-input');
    var done = false;

    var finish = async function (save) {
        if (done) return;
        done = true;
        var next = save ? input.value.trim() : original;
        cell.classList.remove('editing-desc');
        renderDescriptionCell(cell, next);
        if (save && next !== original) {
            try {
                await API.put('/api/excel/sets/' + encodeURIComponent(filename) + '/meta', {
                    description: next,
                });
                showToast('说明已保存', 'success');
            } catch (e) {
                renderDescriptionCell(cell, original);
                showToast('保存说明失败: ' + e.message, 'error');
            }
        }
    };

    input.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            e.preventDefault();
            finish(false);
        } else if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            finish(true);
        }
    });

    input.addEventListener('blur', function () {
        finish(true);
    });

    input.focus();
    input.select();
}

async function openDir(filename) {
    try {
        await API.post('/api/excel/sets/' + encodeURIComponent(filename) + '/open-dir');
    } catch (e) {
        showToast('打开目录失败: ' + e.message, 'error');
    }
}

async function deleteSingleSet(filename) {
    try {
        await API.del('/api/excel/sets/' + encodeURIComponent(filename));
        showToast('已删除: ' + filename, 'success');
        await loadSets();
    } catch (e) {
        showToast('删除失败: ' + e.message, 'error');
    }
}

/* ========================================================================
   View: Case Browse
   ======================================================================== */
async function viewBrowse(filename) {
    currentView = 'browse';
    browseFilename = filename;
    browseFileMeta = null;
    browseSheet = null;
    casesPage = 1;

    contentArea.innerHTML =
        '<div class="breadcrumb set-edit-header">' +
            '<button class="btn btn-sm" id="btn-back">' + icon('back') + '返回</button>' +
            '<button class="btn btn-sm btn-primary" id="btn-save-set-meta">' + icon('edit') + '保存</button>' +
            '<span class="breadcrumb-title set-edit-header-title" id="browse-set-title">' + esc(fileStem(filename)) + '</span>' +
            '<span class="breadcrumb-meta set-edit-file-meta" id="browse-file-meta"></span>' +
        '</div>' +
        '<div class="edit-section set-edit-summary">' +
            '<div class="edit-section-title">测试集信息</div>' +
            '<div class="set-edit-grid">' +
                '<div class="form-row-horizontal set-edit-field">' +
                    '<label class="form-label-h" for="set-name-input">名称</label>' +
                    '<input type="text" class="input" id="set-name-input" placeholder="输入测试集名称..." />' +
                '</div>' +
                '<div class="form-row-horizontal set-edit-field">' +
                    '<label class="form-label-h" for="set-description-input">说明</label>' +
                    '<input type="text" class="input set-description-input" id="set-description-input" placeholder="填写用途、覆盖范围或注意事项..." />' +
                '</div>' +
            '</div>' +
        '</div>' +
        '<div id="browse-sheet-tabs" class="sheet-tabs">' +
            '<span class="sheet-tabs-empty">加载中...</span>' +
        '</div>' +
        '<div class="table-wrap" id="browse-table-wrap">' +
            '<table class="table" id="browse-table">' +
                '<thead><tr>' +
                    '<th data-col="id">case_id</th>' +
                    '<th data-col="q">question</th>' +
                '</tr></thead>' +
                '<tbody id="browse-tbody"></tbody>' +
            '</table>' +
        '</div>' +
        '<div id="cases-pagination" class="pagination"></div>';

    document.getElementById('btn-back').addEventListener('click', function () { viewSets(); });
    document.getElementById('btn-save-set-meta').addEventListener('click', function () {
        saveSetMeta();
    });
    try {
        try {
            var metaData = await API.get('/api/excel/sets/' + encodeURIComponent(filename) + '/meta');
            document.getElementById('set-name-input').value = metaData.name || fileStem(filename);
            document.getElementById('browse-set-title').textContent = metaData.name || fileStem(filename);
            document.getElementById('set-description-input').value = metaData.description || '';
        } catch (e) { /* ignore */ }

        // Load sheets (with row counts) and file metadata
        var sheetData = await API.get('/api/excel/sheets?filename=' + encodeURIComponent(filename));
        var sheets = sheetData.sheets;
        if (!sheets || sheets.length === 0) {
            document.getElementById('browse-sheet-tabs').innerHTML = '<span class="sheet-tabs-empty">该文件没有 Sheet</span>';
            return;
        }

        // Get file metadata from sets API
        try {
            var setsData = await API.get('/api/excel/sets?page=1&page_size=200');
            var found = (setsData.files || []).filter(function (f) { return f.filename === filename; });
            if (found.length > 0) {
                browseFileMeta = { size: found[0].size, updated_at: found[0].updated_at, description: found[0].description || '', name: found[0].name || fileStem(filename) };
                document.getElementById('browse-file-meta').textContent =
                    found[0].filename + ' · ' + formatSize(found[0].size);
            }
        } catch (e) { /* ignore */ }

        browseSheet = sheets[0].name;
        renderBrowseSheetTabs(sheets, browseSheet);
        await loadCases();
        initTableResize('browse-table', 'browse-table-wrap');
    } catch (e) {
        showToast('加载 Sheet 失败: ' + e.message, 'error');
    }
}

async function saveSetMeta() {
    if (!browseFilename) return;
    var btn = document.getElementById('btn-save-set-meta');
    var nameInput = document.getElementById('set-name-input');
    var descInput = document.getElementById('set-description-input');
    if (!btn || !nameInput || !descInput) return;
    var name = nameInput.value.trim();
    if (!name) {
        showToast('名称不能为空', 'error');
        nameInput.focus();
        return;
    }
    btn.disabled = true;
    try {
        var metaData = await API.put('/api/excel/sets/' + encodeURIComponent(browseFilename) + '/meta', {
            name: name,
            description: descInput.value.trim(),
        });
        document.getElementById('browse-set-title').textContent = metaData.name || name;
        showToast('测试集信息已保存', 'success');
    } catch (e) {
        showToast('保存测试集信息失败: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
    }
}

function renderBrowseSheetTabs(sheets, activeName) {
    var container = document.getElementById('browse-sheet-tabs');
    container.innerHTML = sheets.map(function (s) {
        var cls = 'sheet-tab' + (s.name === activeName ? ' active' : '');
        return '<span class="' + cls + '" data-sheet="' + escAttr(s.name) + '">' +
            esc(s.name) + ' <span class="sheet-tab-count">(' + (s.rows || 0) + ')</span>' +
        '</span>';
    }).join('');

    container.querySelectorAll('.sheet-tab').forEach(function (tab) {
        tab.addEventListener('click', async function () {
            var sheetName = tab.getAttribute('data-sheet');
            if (sheetName === browseSheet) return;
            browseSheet = sheetName;
            casesPage = 1;
            container.querySelectorAll('.sheet-tab').forEach(function (t) { t.classList.remove('active'); });
            tab.classList.add('active');
            await loadCases();
        });
    });
}

async function loadCases() {
    try {
        var data = await API.get(
            '/api/testcases?filename=' + encodeURIComponent(browseFilename) +
            '&sheet=' + encodeURIComponent(browseSheet) +
            '&page=' + casesPage + '&page_size=' + casesPageSize
        );
        renderCases(data.cases);
        renderPagination('cases-pagination', data.total, data.page, data.page_size, function (newPage) {
            casesPage = newPage;
            loadCases();
        });
    } catch (e) {
        showToast('加载用例失败: ' + e.message, 'error');
    }
}

function renderCases(cases) {
    var tbody = document.getElementById('browse-tbody');
    if (!cases || cases.length === 0) {
        tbody.innerHTML = '<tr><td colspan="2" class="empty-hint">该 Sheet 中没有有效用例</td></tr>';
        return;
    }
    tbody.innerHTML = cases.map(function (c) {
        return '<tr><td>' + esc(c.case_id) + '</td><td>' + esc(c.question) + '</td></tr>';
    }).join('');
}

/* ========================================================================
   Shared Management List Pagination
   ======================================================================== */
var GLOBAL_PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

function normalizeGlobalPageSize(pageSize) {
    var parsed = parseInt(pageSize, 10);
    return GLOBAL_PAGE_SIZE_OPTIONS.includes(parsed) ? parsed : GLOBAL_PAGE_SIZE_OPTIONS[0];
}

function globalPageSlice(items, page, pageSize) {
    var normalizedSize = normalizeGlobalPageSize(pageSize);
    var total = items.length;
    var totalPages = Math.max(1, Math.ceil(total / normalizedSize));
    var normalizedPage = Math.min(Math.max(parseInt(page, 10) || 1, 1), totalPages);
    var start = (normalizedPage - 1) * normalizedSize;
    return {
        items: items.slice(start, start + normalizedSize),
        page: normalizedPage,
        pageSize: normalizedSize,
        total: total,
        totalPages: totalPages,
    };
}

function renderGlobalListPagination(containerId, total, page, pageSize, onPageChange, onPageSizeChange, unitLabel) {
    var container = document.getElementById(containerId);
    if (!container) return;
    var normalizedSize = normalizeGlobalPageSize(pageSize);
    var totalPages = Math.max(1, Math.ceil(total / normalizedSize));
    var normalizedPage = Math.min(Math.max(parseInt(page, 10) || 1, 1), totalPages);
    var options = GLOBAL_PAGE_SIZE_OPTIONS.map(function (size) {
        return '<option value="' + size + '"' + (size === normalizedSize ? ' selected' : '') + '>' + size + '</option>';
    }).join('');
    container.innerHTML =
        '<div class="global-page-summary"><span>共 ' + total + ' ' + esc(unitLabel || '条') + '</span>' +
            '<label>每页 <select class="input global-page-size" aria-label="每页展示数量">' + options + '</select></label></div>' +
        '<div class="global-pagination">' +
            '<button type="button" aria-label="上一页" title="上一页" data-global-page="' + (normalizedPage - 1) + '"' + (normalizedPage <= 1 ? ' disabled' : '') + '>' + icon('previous') + '</button>' +
            '<span>' + normalizedPage + ' / ' + totalPages + '</span>' +
            '<button type="button" aria-label="下一页" title="下一页" data-global-page="' + (normalizedPage + 1) + '"' + (normalizedPage >= totalPages ? ' disabled' : '') + '>' + icon('next') + '</button>' +
        '</div>';
    container.querySelectorAll('[data-global-page]').forEach(function (button) {
        button.addEventListener('click', function () {
            var nextPage = parseInt(button.getAttribute('data-global-page'), 10);
            if (nextPage >= 1 && nextPage <= totalPages && nextPage !== normalizedPage) onPageChange(nextPage);
        });
    });
    container.querySelector('.global-page-size').addEventListener('change', function () {
        onPageSizeChange(normalizeGlobalPageSize(this.value));
    });
}

function renderPagination(containerId, total, page, pageSize, onChange) {
    renderGlobalListPagination(containerId, total, page, pageSize, onChange, function (nextPageSize) {
        if (containerId === 'sets-pagination') setsPageSize = nextPageSize;
        if (containerId === 'cases-pagination') casesPageSize = nextPageSize;
        onChange(1);
    }, '条');
}

/* ========================================================================
   Import Modal
   ======================================================================== */
var importOverlay = document.getElementById('import-overlay');
var importFileInput = document.getElementById('import-file-input');
var importFileList = document.getElementById('import-file-list');
var importDescInput = document.getElementById('import-desc-input');
var importSaveBtn = document.getElementById('btn-import-save');

function openImportModal() {
    importFiles = [];
    importFileInput.value = '';
    importDescInput.value = '';
    renderImportFiles();
    importOverlay.classList.remove('hidden');
}

function closeImportModal() {
    importOverlay.classList.add('hidden');
    importFiles = [];
    importFileInput.value = '';
    renderImportFiles();
}

function renderImportFiles() {
    if (!importFileList) return;
    if (importFiles.length === 0) {
        importFileList.innerHTML = '<div class="import-empty">尚未选择测试集</div>';
        return;
    }
    importFileList.innerHTML = importFiles.map(function (file, idx) {
        return '<div class="import-file-item">' +
            '<div class="import-file-main">' +
                '<span class="import-file-name">' + esc(file.name) + '</span>' +
                '<span class="import-file-size">' + formatSize(file.size) + '</span>' +
            '</div>' +
            '<button class="btn-icon import-file-remove" data-index="' + idx + '" title="移除" aria-label="移除">' + icon('trash') + '</button>' +
        '</div>';
    }).join('');

    importFileList.querySelectorAll('.import-file-remove').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var idx = parseInt(btn.getAttribute('data-index'), 10);
            if (!Number.isNaN(idx)) {
                importFiles.splice(idx, 1);
                renderImportFiles();
            }
        });
    });
}

async function getExistingSetNames() {
    var names = new Set();
    var page = 1;
    var pageSize = 200;
    var total = 0;
    do {
        var data = await API.get(
            '/api/excel/sets?page=' + page +
            '&page_size=' + pageSize +
            '&sort_by=updated_at&sort_dir=desc'
        );
        (data.files || []).forEach(function (file) {
            names.add(file.filename);
        });
        total = data.total || 0;
        page++;
    } while (names.size < total);
    return names;
}

importFileInput.addEventListener('change', function () {
    var selected = Array.from(importFileInput.files || []);
    selected.forEach(function (file) {
        var existing = importFiles.findIndex(function (item) { return item.name === file.name; });
        if (existing >= 0) importFiles[existing] = file;
        else importFiles.push(file);
    });
    importFileInput.value = '';
    renderImportFiles();
});

document.getElementById('btn-import-cancel').addEventListener('click', closeImportModal);

importOverlay.addEventListener('click', function (e) {
    if (e.target === importOverlay) closeImportModal();
});

importSaveBtn.addEventListener('click', async function () {
    if (importFiles.length === 0) {
        showToast('请先选择要导入的测试集', 'error');
        return;
    }

    importSaveBtn.disabled = true;
    var description = importDescInput.value.trim();
    var imported = 0;
    var failed = 0;

    try {
        var existingNames = await getExistingSetNames();
        var duplicateNames = importFiles
            .map(function (file) { return file.name; })
            .filter(function (name, idx, arr) {
                return existingNames.has(name) && arr.indexOf(name) === idx;
            });
        if (duplicateNames.length > 0) {
            var message = '以下同名测试集已存在，继续导入会覆盖：\n\n' +
                duplicateNames.join('\n') +
                '\n\n是否继续覆盖？';
            if (!confirm(message)) {
                importSaveBtn.disabled = false;
                return;
            }
        }
    } catch (e) {
        importSaveBtn.disabled = false;
        showToast('检查同名测试集失败: ' + e.message, 'error');
        return;
    }

    for (var i = 0; i < importFiles.length; i++) {
        var file = importFiles[i];
        var formData = new FormData();
        formData.append('file', file);
        try {
            var uploadData = await API.upload('/api/excel/upload', formData);
            var filename = uploadData.filename || file.name;
            await API.put('/api/excel/sets/' + encodeURIComponent(filename) + '/meta', {
                description: description,
            });
            imported++;
        } catch (e) {
            failed++;
        }
    }

    importSaveBtn.disabled = false;
    closeImportModal();
    setsPage = 1;
    await loadSets();
    showToast('已导入 ' + imported + ' 个' + (failed > 0 ? '，失败 ' + failed + ' 个' : ''), failed > 0 ? 'error' : 'success');
});

/* ========================================================================
   Delete Modal
   ======================================================================== */
var deleteOverlay = document.getElementById('delete-overlay');

document.getElementById('btn-delete-cancel').addEventListener('click', function () {
    deleteOverlay.classList.add('hidden');
});

deleteOverlay.addEventListener('click', function (e) {
    if (e.target === deleteOverlay) deleteOverlay.classList.add('hidden');
});

document.getElementById('btn-delete-confirm').addEventListener('click', async function () {
    var checked = getCheckedFilenames();
    var btn = document.getElementById('btn-delete-confirm');
    btn.disabled = true;
    var deleted = 0, failed = 0;
    for (var i = 0; i < checked.length; i++) {
        try {
            await API.del('/api/excel/sets/' + encodeURIComponent(checked[i]));
            deleted++;
        } catch (e) { failed++; }
    }
    btn.disabled = false;
    deleteOverlay.classList.add('hidden');
    showToast('已删除 ' + deleted + ' 个' + (failed > 0 ? '，失败 ' + failed + ' 个' : ''), failed > 0 ? 'error' : 'success');
    setsPage = 1;
    await loadSets();
});

/* ========================================================================
   Column / Sidebar Resize
   ======================================================================== */

// Sidebar resize
(function () {
    var sidebar = document.querySelector('.sidebar');
    if (!sidebar) return;

    var handle = document.createElement('div');
    handle.className = 'sidebar-resize';
    sidebar.appendChild(handle);

    var startX, startW;
    handle.addEventListener('mousedown', function (e) {
        startX = e.clientX;
        startW = sidebar.offsetWidth;
        handle.classList.add('resizing');
        document.body.classList.add('resizing');
        e.preventDefault();
    });

    document.addEventListener('mousemove', function (e) {
        if (!handle.classList.contains('resizing')) return;
        var dx = e.clientX - startX;
        var newW = Math.max(140, Math.min(400, startW + dx));
        sidebar.style.width = newW + 'px';
        sidebar.style.minWidth = newW + 'px';
    });

    document.addEventListener('mouseup', function () {
        handle.classList.remove('resizing');
        document.body.classList.remove('resizing');
    });
})();

// Table column resize — also resizes corresponding td cells
function initTableResize(tableId, wrapId) {
    var table = document.getElementById(tableId);
    var wrap = document.getElementById(wrapId);
    if (!table || !wrap) return;

    var headers = table.querySelectorAll('th[data-col]');
    headers.forEach(function (th, colIdx) {
        if (th.querySelector('.resize-handle')) return;

        var handle = document.createElement('div');
        handle.className = 'resize-handle';
        th.appendChild(handle);

        var startX, startW;
        handle.addEventListener('mousedown', function (e) {
            startX = e.clientX;
            startW = th.offsetWidth;
            handle.classList.add('resizing');
            document.body.classList.add('resizing');
            e.preventDefault();
            e.stopPropagation();
        });

        var onMove = function (e) {
            if (!handle.classList.contains('resizing')) return;
            var dx = e.clientX - startX;
            var newW = Math.max(40, startW + dx);
            th.style.width = newW + 'px';
            th.style.minWidth = newW + 'px';
            // Sync td cells in the same column
            var rows = table.querySelectorAll('tbody tr');
            rows.forEach(function (row) {
                var td = row.children[colIdx];
                if (td) {
                    td.style.width = newW + 'px';
                    td.style.minWidth = newW + 'px';
                }
            });
        };

        var onUp = function () {
            handle.classList.remove('resizing');
            document.body.classList.remove('resizing');
        };

        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    });
}

/* ========================================================================
   Helpers
   ======================================================================== */

function debounce(fn, delay) {
    var timer = null;
    return function () {
        var ctx = this;
        var args = arguments;
        clearTimeout(timer);
        timer = setTimeout(function () {
            fn.apply(ctx, args);
        }, delay);
    };
}

function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function escAttr(s) {
    return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    return (bytes / 1024).toFixed(1) + ' KB';
}

function formatDateTime(value) {
    if (!value) return '';
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value).replace('T', ' ');
    var pad = function (part) { return String(part).padStart(2, '0'); };
    return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()) + ' ' +
        pad(date.getHours()) + ':' + pad(date.getMinutes()) + ':' + pad(date.getSeconds());
}

function fileStem(filename) {
    return String(filename || '').replace(/\.[^.]+$/, '');
}
