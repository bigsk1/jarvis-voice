#!/usr/bin/env python3
"""Regression coverage for wide Markdown tables in Canvas pages."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANVAS_ROOT = PROJECT_ROOT / "jarvis-canvas"


def test_canvas_mounts_markdown_tables_in_a_horizontal_scroll_region():
    canvas_js = (CANVAS_ROOT / "client" / "static" / "js" / "canvas.js").read_text(
        encoding="utf-8"
    )

    assert "function setupScrollableTables(root = document)" in canvas_js
    assert "querySelectorAll?.('.page-content table')" in canvas_js
    assert "table.closest('.canvas-table-scroll')" in canvas_js
    assert "scroll.className = 'canvas-table-scroll'" in canvas_js
    assert "scroll.setAttribute('role', 'region')" in canvas_js
    assert "scroll.setAttribute('aria-label', 'Scrollable table')" in canvas_js
    assert "scroll.tabIndex = 0" in canvas_js
    assert "setupScrollableTables(pageView);" in canvas_js


def test_canvas_constrains_wide_tables_and_wraps_links_outside_tables():
    canvas_css = (CANVAS_ROOT / "client" / "static" / "css" / "canvas.css").read_text(
        encoding="utf-8"
    )

    assert ".page-content .canvas-table-scroll {" in canvas_css
    assert "overflow-x: auto;" in canvas_css
    assert "overscroll-behavior-x: contain;" in canvas_css
    assert ".page-content .canvas-table-scroll::-webkit-scrollbar {" in canvas_css
    assert "height: 10px;" in canvas_css
    assert ".page-content .canvas-table-scroll table {" in canvas_css
    assert "width: max-content;" in canvas_css
    assert "min-width: 100%;" in canvas_css
    assert "overflow-wrap: anywhere;" in canvas_css
    assert ".page-content .canvas-table-scroll a {" in canvas_css
    assert "overflow: visible !important;" in canvas_css
