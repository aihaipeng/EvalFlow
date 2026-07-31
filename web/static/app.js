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
function showToast(msg, type) {
    var el = document.getElementById('toast');
    el.textContent = msg;
    el.className = 'toast ' + type;
    setTimeout(function () { el.classList.add('hidden'); }, 3000);
}

/* ===== DOM Refs ===== */
var contentArea = document.getElementById('content-area');

/* ===== State ===== */
var currentView = 'sets';

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
