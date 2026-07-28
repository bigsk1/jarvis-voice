#!/usr/bin/env python3
"""Jarvis Memory scheduled-task form UI regressions."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = PROJECT_ROOT / "jarvis-memory" / "client" / "index.html"
MEMORY_CSS = PROJECT_ROOT / "jarvis-memory" / "client" / "css" / "memory.css"


def test_post_run_notifications_are_exposed_as_a_form_group():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert (
        '<fieldset class="form-group form-fieldset" style="margin-top: 18px;">'
        in html
    )
    assert '<legend class="form-label">Post-Run Notifications</legend>' in html
    assert '<label class="form-label">Post-Run Notifications</label>' not in html


def test_datetime_input_uses_dark_native_browser_controls():
    css = MEMORY_CSS.read_text(encoding="utf-8")

    assert '.form-input[type="datetime-local"]' in css
    assert "color-scheme: dark;" in css


def test_execution_mode_is_display_only_and_explains_mode_ownership():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="scheduledTaskExecutionMode" disabled' in html
    assert "Schedules belong to the currently selected Jarvis mode." in html
