from pathlib import Path


STATIC_DIR = Path(__file__).parents[1] / "web" / "static"


def test_sidebar_exposes_accessible_theme_toggle():
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert 'class="sidebar-footer"' in index_html
    assert 'id="theme-toggle"' in index_html
    assert 'aria-label="切换到黑夜模式"' in index_html
    assert 'aria-pressed="false"' in index_html


def test_theme_follows_system_until_user_selects_a_persisted_override():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "var THEME_STORAGE_KEY = 'agent-bench-theme'" in app_js
    assert "window.localStorage.getItem(THEME_STORAGE_KEY)" in app_js
    assert "window.localStorage.setItem(THEME_STORAGE_KEY, next)" in app_js
    assert "window.matchMedia('(prefers-color-scheme: dark)')" in app_js
    assert "media.addEventListener('change', syncSystemTheme)" in app_js
    assert "if (!storedTheme()) applyTheme(event.matches ? 'dark' : 'light')" in app_js
    assert "document.documentElement.setAttribute('data-theme', theme)" in app_js
    assert "initTheme();" in app_js


def test_dark_theme_uses_semantic_surfaces_for_selected_scope():
    style_css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")

    assert ':root[data-theme="dark"]' in style_css
    assert "--page-bg: #111315" in style_css
    assert "background: var(--page-bg)" in style_css
    assert "background: var(--input-bg)" in style_css
    assert "background: var(--surface-muted)" in style_css
    assert "background: var(--surface-selected)" in style_css
    assert "border-bottom: 1px solid var(--row-border)" in style_css
    assert "border-bottom: 1px solid var(--strong-row-border)" in style_css
    assert "box-shadow: inset 0 -1px 0 var(--row-inset)" in style_css
    assert "color: var(--text-main)" in style_css
    assert ".theme-toggle" in style_css


def test_image_icon_buttons_use_transparent_theme_aware_interaction_states():
    style_css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")

    assert "--icon-button-text: #111827" in style_css
    assert "--icon-button-text: #ffffff" in style_css
    assert "--icon-button-hover-bg: rgba(15, 23, 42, 0.08)" in style_css
    assert "--icon-button-hover-bg: rgba(255, 255, 255, 0.10)" in style_css
    assert ".btn:has(.ui-icon),\n.btn-icon:has(.ui-icon) {" in style_css
    assert "background: transparent;\n    color: var(--icon-button-text);" in style_css
    assert "background: var(--icon-button-hover-bg);" in style_css
    assert "transform: translateY(-1px);" in style_css
    assert "background: var(--icon-button-active-bg);" in style_css
    assert "transform: scale(0.96);" in style_css
    assert ".btn:has(.ui-icon):disabled:hover" in style_css
    assert ".btn-icon:has(.ui-icon):disabled:hover" in style_css
    assert "@media (hover: none)" not in style_css
