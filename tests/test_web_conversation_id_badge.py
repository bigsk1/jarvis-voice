"""Structural coverage for the Jarvis Web conversation ID badge."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_CSS = ROOT / "jarvis-web" / "client" / "css" / "main.css"


def _rule(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]+)\}}", css)
    assert match is not None, f"Missing CSS rule for {selector}"
    return match.group(1)


def test_conversation_id_stays_discreet_until_hovered():
    css = MAIN_CSS.read_text(encoding="utf-8")

    default_rule = _rule(css, ".conv-id-badge")
    assert "color: var(--text-muted, #666)" in default_rule
    assert "opacity: 0.5" in default_rule

    hover_rule = _rule(css, ".conv-id-badge:hover")
    assert "opacity: 1" in hover_rule
    assert "color: var(--text-primary, #e2e8f0)" in hover_rule
