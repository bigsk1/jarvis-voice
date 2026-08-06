"""Structural regression coverage for the Jarvis Web sidebar scroll layout."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_CSS = ROOT / "jarvis-web" / "client" / "css" / "main.css"
APP_JS = ROOT / "jarvis-web" / "client" / "js" / "app.js"


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


def test_tool_hover_tooltip_is_portaled_above_chat_stacking_contexts():
    css = MAIN_CSS.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")
    method_start = app_js.index("\n  _setupToolHoverTooltips(container) {")
    method_end = app_js.index("\n  /**\n   * Render a single tool item", method_start)
    method = app_js[method_start:method_end]

    assert "document.body.appendChild(portal);" in method
    assert "portal.textContent = tooltip.textContent || '';" in method
    assert "container.onscroll = hide;" in method
    assert "tooltip.style.display = 'block';" not in method
    assert "z-index: 10050" in _rule(css, ".tool-item-tooltip-portal")

    render_start = app_js.index("\n  _renderToolItem(tool) {")
    render_end = app_js.index("\n  /**\n   * Get emoji for tool", render_start)
    render_method = app_js[render_start:render_end]
    assert "tooltipText || tool.name" in render_method
