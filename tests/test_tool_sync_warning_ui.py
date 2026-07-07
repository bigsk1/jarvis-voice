"""Structural coverage for the persistent Tool RAG sync warning handshake."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sync_cli_records_failure_and_success_outcomes():
    source = (ROOT / "bin" / "sync-tools.py").read_text(encoding="utf-8")
    assert "record_tool_sync_failure" in source
    assert "record_tool_sync_success" in source
    assert "count_usable_tool_embeddings" in source
    assert "_record_sync_outcome(mode)" in source


def test_web_status_exposes_only_persisted_failed_sync_state():
    source = (ROOT / "jarvis-web" / "server" / "routes" / "api.py").read_text(encoding="utf-8")
    assert "read_tool_sync_status" in source
    assert "tool_sync_status.get('status') == 'failed'" in source
    assert "'tool_sync_warning': tool_sync_warning" in source


def test_web_warning_is_persistent_dismissible_and_disconnect_safe():
    app_js = (ROOT / "jarvis-web" / "client" / "js" / "app.js").read_text(encoding="utf-8")
    utils_js = (ROOT / "jarvis-web" / "client" / "js" / "utils.js").read_text(encoding="utf-8")
    css = (ROOT / "jarvis-web" / "client" / "css" / "main.css").read_text(encoding="utf-8")

    assert "if (!this._connectionConnected) return" in app_js
    assert "status.tool_sync_warning" in app_js
    assert "jarvis_tool_sync_warning_dismissed_" in app_js
    assert "Connection loss is not Tool RAG evidence" in app_js
    assert "Utils.persistentToast" in app_js
    assert "persistentToast(message" in utils_js
    assert "toast-close" in css
