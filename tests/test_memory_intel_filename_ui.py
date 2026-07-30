"""UI contract for canonical Intel filenames in Jarvis Memory."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = PROJECT_ROOT / "jarvis-memory" / "client" / "index.html"
MEMORY_CSS = PROJECT_ROOT / "jarvis-memory" / "client" / "css" / "memory.css"


def test_create_intel_modal_explains_and_validates_kebab_case():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="intelFilenameHelp"' in html
    assert "Snake_case underscores are not allowed." in html
    assert 'aria-describedby="intelFilenameHelp"' in html
    assert 'pattern="[a-z0-9]+(-[a-z0-9]+)*(\\.(md|txt))?"' in html


def test_form_help_has_quiet_supporting_text_style():
    css = MEMORY_CSS.read_text(encoding="utf-8")

    assert ".form-help {" in css
    assert "color: var(--text-muted);" in css
