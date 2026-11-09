"""Resolve and validate the database mode shared by dashboard routes."""

from flask import Response, current_app, jsonify, request


def get_request_mode() -> str:
    """Use an explicit selection or the server's startup mode."""
    mode = request.args.get("mode", current_app.config.get("JARVIS_STARTUP_MODE", "cloud"))
    if mode not in {"cloud", "local"}:
        raise ValueError("mode must be cloud or local")
    return mode


def validate_request_mode() -> tuple[Response, int] | None:
    """Reject invalid modes before any database, provider, or child work starts."""
    try:
        get_request_mode()
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return None
