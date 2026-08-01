from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web" / "static"
FRONTEND = ROOT / "web" / "frontend"


def test_shared_lucide_registry_loads_before_frontend_modules():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    icons = (STATIC / "assets" / "icons.js").read_text(encoding="utf-8")

    assert html.index('/assets/icons.js') < html.index('/model-providers.js')
    assert html.index('/assets/icons.js') < html.index('/app.js')
    for name in ("plus", "refresh", "pencil", "trash", "eye", "save", "search", "settings"):
        assert f'"{name}"' in icons
    assert "global.AppIcons" in icons
    assert "Lucide icons v0.468.0, ISC License" in icons


def test_legacy_bitmap_and_symbol_button_icons_are_removed():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    providers = (FRONTEND / "model-providers.jsx").read_text(encoding="utf-8")
    test_sets = (FRONTEND / "test-sets.jsx").read_text(encoding="utf-8")

    assert "ICON_DATA" not in app
    assert "data:image/png" not in app
    assert "icon-img" not in app
    for symbol in ("＋", "⌁", "⌕", "⟳", "⚙", "←", "→", "▶"):
        assert symbol not in test_sets
    for symbol in ("⚙", "▶", "✓"):
        assert symbol not in providers


def test_same_actions_use_same_semantic_icons_across_modules():
    execution = (STATIC / "execution.js").read_text(encoding="utf-8")
    providers = (FRONTEND / "model-providers.jsx").read_text(encoding="utf-8")
    test_sets = (FRONTEND / "test-sets.jsx").read_text(encoding="utf-8")

    assert "icon('add')" in execution and '<Icon name="add"/>' in providers
    assert "icon('refresh')" in execution and '<Icon name="refresh"/>' in providers
    assert "icon('trash')" in execution and '<Icon name="trash"/>' in providers
    assert "icon('save')" in execution and '<Icon name="save"/>' in providers
    assert "<Plus className=\"ui-icon\" />" in test_sets
    assert "<RefreshCw className=\"ui-icon\" />" in test_sets
    assert "<Trash2 className=\"ui-icon\" />" in test_sets
    assert "<Save className=\"ui-icon\" />" in test_sets
