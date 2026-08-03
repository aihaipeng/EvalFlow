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
    del: async function (url) {
        var res = await fetch(url, { method: 'DELETE' });
        return apiResponsePayload(res);
    },
};


/* ===== Toast ===== */
var TOAST_DURATION_MS = 5000;

function ensureToastContainer() {
    var container = document.getElementById('toast-container');
    if (container) return container;
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    container.setAttribute('aria-live', 'polite');
    container.setAttribute('aria-relevant', 'additions');
    document.body.appendChild(container);
    return container;
}

function showToast(msg, type) {
    var container = ensureToastContainer();
    var el = document.createElement('div');
    var tone = type === 'error' ? 'error' : 'success';
    el.textContent = msg;
    el.className = 'toast ' + tone;
    el.setAttribute('role', tone === 'error' ? 'alert' : 'status');
    el.setAttribute('aria-atomic', 'true');
    container.appendChild(el);
    setTimeout(function () {
        el.classList.add('is-leaving');
        setTimeout(function () { el.remove(); }, 300);
    }, TOAST_DURATION_MS);
}

/* ===== DOM Refs ===== */
var contentArea = document.getElementById('content-area');

/* ===== State ===== */
var currentView = 'sets';
var featureAssetLoads = {};

function icon(name) {
    return window.AppIcons ? window.AppIcons.icon(name) : '';
}

function featureNavigationItem(view) {
    return document.querySelector('.sidebar-item[data-view="' + view + '"]');
}

function loadFeatureStylesheet(view, url) {
    var id = 'feature-style-' + view;
    if (document.getElementById(id)) return Promise.resolve();
    return new Promise(function (resolve, reject) {
        var link = document.createElement('link');
        link.id = id;
        link.rel = 'stylesheet';
        link.href = url;
        link.onload = resolve;
        link.onerror = function () {
            link.remove();
            reject(new Error('样式资源加载失败'));
        };
        document.head.appendChild(link);
    });
}

function loadFeatureScript(view, url) {
    var id = 'feature-script-' + view;
    if (document.getElementById(id)) return Promise.resolve();
    return new Promise(function (resolve, reject) {
        var script = document.createElement('script');
        script.id = id;
        script.type = 'module';
        script.src = url;
        script.onload = resolve;
        script.onerror = function () {
            script.remove();
            reject(new Error('脚本资源加载失败'));
        };
        document.body.appendChild(script);
    });
}

function ensureFeatureAssets(view) {
    if (featureAssetLoads[view]) return featureAssetLoads[view];
    var item = featureNavigationItem(view);
    var stylesheet = item && item.getAttribute('data-feature-css');
    var script = item && item.getAttribute('data-feature-js');
    if (!script) return Promise.resolve();
    featureAssetLoads[view] = (stylesheet ? loadFeatureStylesheet(view, stylesheet) : Promise.resolve())
        .then(function () { return loadFeatureScript(view, script); })
        .catch(function (error) {
            delete featureAssetLoads[view];
            throw error;
        });
    return featureAssetLoads[view];
}

function renderFeatureLoadError(label, retry) {
    contentArea.innerHTML = '<div class="execution-empty"><strong>' + esc(label + '加载失败') + '</strong>' +
        '<button class="btn btn-primary btn-sm" id="feature-load-retry" type="button">' + icon('retry') + '重新加载</button></div>';
    document.getElementById('feature-load-retry').addEventListener('click', retry);
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
    var nextLabel = dark ? '白天模式' : '夜间模式';
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

async function viewSets() {
    currentView = 'sets';
    if (window.TestSetManagement && typeof window.TestSetManagement.mount === 'function') {
        window.TestSetManagement.mount();
        return;
    }
    contentArea.innerHTML = '<div class="loading">正在加载测试集管理…</div>';
    try {
        await ensureFeatureAssets('sets');
        if (currentView !== 'sets') return;
        if (!window.TestSetManagement || typeof window.TestSetManagement.mount !== 'function') throw new Error('测试集资源未注册');
        window.TestSetManagement.mount();
    } catch (error) {
        if (currentView === 'sets') renderFeatureLoadError('测试集管理', viewSets);
    }
}

async function viewWorkflowsWithAssets() {
    currentView = 'workflows';
    contentArea.innerHTML = '<div class="loading">正在加载工作流管理…</div>';
    try {
        await ensureFeatureAssets('workflows');
        if (currentView === 'workflows') viewWorkflows();
    } catch (error) {
        if (currentView === 'workflows') renderFeatureLoadError('工作流管理', viewWorkflowsWithAssets);
    }
}

async function viewModelProvidersWithAssets() {
    currentView = 'models';
    contentArea.innerHTML = '<div class="loading">正在加载供应商管理…</div>';
    try {
        await ensureFeatureAssets('models');
        if (currentView !== 'models') return;
        if (!window.ModelProviderManagement) throw new Error('供应商管理资源未注册');
        window.ModelProviderManagement.mount();
    } catch (error) {
        if (currentView === 'models') renderFeatureLoadError('供应商管理', viewModelProvidersWithAssets);
    }
}

async function viewBatchRunsWithAssets() {
    currentView = 'batch-runs';
    contentArea.innerHTML = '<div class="loading">正在加载任务调度…</div>';
    try {
        await ensureFeatureAssets('batch-runs');
        if (currentView !== 'batch-runs') return;
        if (!window.BatchRunManagement) throw new Error('任务调度资源未注册');
        window.BatchRunManagement.mount();
    } catch (error) {
        if (currentView === 'batch-runs') renderFeatureLoadError('任务调度', viewBatchRunsWithAssets);
    }
}

function init() {
    initTheme();
    viewSets();
}
init();

/* ===== Sidebar Navigation ===== */
document.querySelector('.sidebar-nav').addEventListener('click', async function (e) {
    var item = e.target.closest('.sidebar-item');
    if (!item) return;
    var view = item.getAttribute('data-view');
    if (view === currentView) return;
    if (currentView === 'sets' && window.TestSetManagement && typeof window.TestSetManagement.requestLeave === 'function') {
        var canLeave = await window.TestSetManagement.requestLeave();
        if (!canLeave) return;
    }
    document.querySelectorAll('.sidebar-item').forEach(function (el) {
        el.classList.remove('active');
        el.removeAttribute('aria-current');
    });
    item.classList.add('active');
    item.setAttribute('aria-current', 'page');
    if (view !== 'sets' && window.TestSetManagement) window.TestSetManagement.unmount();
    if (view !== 'models' && window.ModelProviderManagement) window.ModelProviderManagement.unmount();
    if (view !== 'batch-runs' && window.BatchRunManagement) window.BatchRunManagement.unmount();
    if (view === 'sets') {
        viewSets();
    } else if (view === 'models') {
        viewModelProvidersWithAssets();
    } else if (view === 'workflows') {
        viewWorkflowsWithAssets();
    } else if (view === 'batch-runs') {
        viewBatchRunsWithAssets();
    }
});

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

/* ========================================================================
   Column / Sidebar Resize
   ======================================================================== */

function enableTableColumnResize(root) {
    (root || document).querySelectorAll('table.table').forEach(function (table) {
        if (table.dataset.columnResizeReady === 'true') return;
        var headers = Array.from(table.querySelectorAll('thead th'));
        if (!headers.length) return;
        table.dataset.columnResizeReady = 'true';
        var equalize = table.classList.contains('management-list-table');
        var colgroup = document.createElement('colgroup');
        var colCount = headers.length;
        var baseWidth = equalize
            ? Math.max(80, Math.floor(table.clientWidth / colCount))
            : 0;
        headers.forEach(function (header, index) {
            var col = document.createElement('col');
            if (equalize) {
                // 均分：最后一列吸收取整余数，避免总和超出容器产生横向滚动条
                col.style.width = (index === colCount - 1
                    ? Math.max(80, table.clientWidth - baseWidth * (colCount - 1))
                    : baseWidth) + 'px';
            } else {
                col.style.width = Math.max(80, header.getBoundingClientRect().width) + 'px';
            }
            colgroup.appendChild(col);
        });
        table.insertBefore(colgroup, table.firstChild);
        table.style.tableLayout = 'fixed';
        if (equalize) return;
        headers.forEach(function (header, index) {
            var handle = document.createElement('span');
            handle.className = 'table-column-resize';
            handle.title = '拖动调整列宽';
            header.appendChild(handle);
            handle.addEventListener('mousedown', function (event) {
                var startX = event.clientX;
                var startWidth = colgroup.children[index].getBoundingClientRect().width;
                document.body.classList.add('resizing');
                var move = function (moveEvent) {
                    var width = Math.max(80, startWidth + moveEvent.clientX - startX);
                    colgroup.children[index].style.width = width + 'px';
                };
                var stop = function () {
                    document.body.classList.remove('resizing');
                    document.removeEventListener('mousemove', move);
                    document.removeEventListener('mouseup', stop);
                };
                document.addEventListener('mousemove', move);
                document.addEventListener('mouseup', stop);
                event.preventDefault();
                event.stopPropagation();
            });
        });
    });
}

enableTableColumnResize(document);
new MutationObserver(function (records) {
    records.forEach(function (record) {
        record.addedNodes.forEach(function (node) {
            if (node.nodeType === 1) enableTableColumnResize(node);
        });
    });
}).observe(document.body, {childList: true, subtree: true});

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

/* ========================================================================
   Helpers
   ======================================================================== */

function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function escAttr(s) {
    return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function formatDateTime(value) {
    if (!value) return '';
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value).replace('T', ' ');
    var pad = function (part) { return String(part).padStart(2, '0'); };
    return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()) + ' ' +
        pad(date.getHours()) + ':' + pad(date.getMinutes()) + ':' + pad(date.getSeconds());
}
