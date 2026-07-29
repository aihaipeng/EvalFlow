from pathlib import Path


STATIC_DIR = Path(__file__).parents[1] / "web" / "static"


def test_faq_navigation_view_code_and_styles_are_removed():
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    style_css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")

    assert 'data-view="faq"' not in index_html
    assert "❓ FAQ" not in index_html
    assert "FAQ_ITEMS" not in app_js
    assert "function icon(name)" in app_js
    assert "view === 'faq'" not in app_js
    assert "function viewFaq" not in app_js
    assert "function renderFaqItems" not in app_js
    assert ".faq-page" not in style_css
    assert ".faq-item" not in style_css
