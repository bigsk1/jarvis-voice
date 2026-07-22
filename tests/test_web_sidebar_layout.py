"""Structural regression coverage for the Jarvis Web sidebar scroll layout."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_CSS = ROOT / "jarvis-web" / "client" / "css" / "main.css"


def _rule(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]+)\}}", css)
    assert match is not None, f"Missing CSS rule for {selector}"
    return match.group(1)


def test_desktop_sidebar_is_wider_and_has_one_scroll_owner_per_tab():
    css = MAIN_CSS.read_text(encoding="utf-8")

    assert "width: 350px" in _rule(css, ".sidebar")
    assert "overflow: hidden" in _rule(css, ".sidebar-content")
    assert "display: flex" in _rule(css, "#tab-conversations.tab-content.active")
    tools_rule = _rule(css, "#tab-tools.tab-content.active")
    assert "overflow-x: hidden" in tools_rule
    assert "overflow-y: auto" in tools_rule

    history_rule = _rule(css, ".history-list")
    assert "flex: 1" in history_rule
    assert "min-height: 0" in history_rule
    assert "overflow-x: hidden" in history_rule
    assert "overflow-y: auto" in history_rule
    assert "max-height" not in history_rule
