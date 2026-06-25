#!/usr/bin/env python3
"""
Check OpenCode Sessions Tool
Query OpenCode API for session history, progress, and build details.
READ-ONLY - does not trigger new builds.
"""
import sys
import json
import os
from pathlib import Path

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib'))
from opencode_client import OpenCodeClient


def _session_timestamp(session: dict, key: str) -> str | int | float:
    """Return OpenCode session timestamps across old and current API shapes."""
    time_info = session.get("time")
    if isinstance(time_info, dict) and time_info.get(key) is not None:
        return time_info.get(key)

    legacy_key = "lastActivity" if key == "updated" else "created"
    return session.get(legacy_key, "")


def _project_root() -> Path:
    return Path(__file__).parent.parent.resolve()


def _iter_opencode_log_entries(session_id: str) -> list[dict]:
    """Read Jarvis-side OpenCode JSONL logs for a session."""
    log_dir = _project_root() / "logs" / "opencode"
    if not log_dir.exists():
        return []

    entries: list[dict] = []
    for log_file in sorted(log_dir.glob("opencode-*.jsonl")):
        try:
            with log_file.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("session_id") == session_id:
                        entries.append(entry)
        except OSError:
            continue
    return entries


def _summarize_opencode_logs(session_id: str) -> dict:
    """
    Return useful Jarvis-side details for an OpenCode session.

    OpenCode's /session endpoint can be metadata-only on current builds, while
    Jarvis logs the original task, model, response preview, duration, and status.
    """
    entries = _iter_opencode_log_entries(session_id)
    if not entries:
        return {}

    summary: dict = {
        "event_count": len(entries),
        "events": [entry.get("event") for entry in entries if entry.get("event")],
    }

    for entry in entries:
        event = entry.get("event")
        if event == "session_start":
            summary.update({
                "task": entry.get("task"),
                "task_type": entry.get("task_type"),
                "model": entry.get("model"),
                "jarvis_session": (entry.get("context") or {}).get("jarvis_session")
                if isinstance(entry.get("context"), dict)
                else None,
            })
        elif event == "message_received":
            response_info = entry.get("response_info") or {}
            summary.update({
                "response_preview": entry.get("response_preview"),
                "response_length": entry.get("response_length"),
                "duration_ms": entry.get("duration_ms"),
                "model_used": response_info.get("model_used"),
                "tokens": response_info.get("tokens"),
                "has_error": entry.get("has_error"),
            })
        elif event == "session_complete":
            summary.update({
                "success": entry.get("success"),
                "result_summary": entry.get("result_summary"),
                "error": entry.get("error"),
            })

    return {k: v for k, v in summary.items() if v is not None}


def _attach_log_summary(session: dict) -> dict:
    """Attach Jarvis-side log summary to a session dict when available."""
    session_id = session.get("id") or session.get("sessionId")
    if not session_id:
        return session
    log_summary = _summarize_opencode_logs(session_id)
    if log_summary:
        session = dict(session)
        session["jarvis_log_summary"] = log_summary
    return session


def main():
    """Check OpenCode sessions via API."""
    try:
        # Read arguments
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        
        session_id = args.get('session_id')
        limit = args.get('limit', 5)
        
        # Initialize OpenCode client
        try:
            client = OpenCodeClient()
        except Exception as e:
            return {
                "ok": False,
                "speech": "OpenCode server is not running. Start it with: systemctl --user start opencode",
                "error": f"Connection failed: {str(e)}"
            }
        
        # Check health
        health = client.health_check()
        if not health.get("healthy"):
            return {
                "ok": False,
                "speech": "OpenCode server is not responding properly",
                "error": "Health check failed"
            }
        
        # Get specific session or list all sessions
        if session_id:
            # Get detailed session info
            try:
                session = client.get_session(session_id)
            except Exception as e:
                return {
                    "ok": False,
                    "speech": f"Session {session_id} not found",
                    "error": str(e)
                }
            session = _attach_log_summary(session)
            
            # Build speech summary
            title = session.get('title', 'Untitled')
            agent = session.get('agent', 'unknown')
            msg_count = len(session.get('messages', []))
            
            speech = f"OpenCode session: {title}. Agent: {agent}. {msg_count} messages in conversation."
            log_summary = session.get("jarvis_log_summary") or {}
            if log_summary:
                duration_ms = log_summary.get("duration_ms")
                if isinstance(duration_ms, (int, float)):
                    speech += f" Jarvis log duration: {duration_ms / 1000:.0f} seconds."
                if log_summary.get("success") is not None:
                    speech += f" Completed: {bool(log_summary.get('success'))}."
                preview = str(log_summary.get("response_preview") or "").strip()
                if preview:
                    speech += f" Result preview: {preview[:240]}"
            
            # Add token info if available
            if 'metadata' in session and 'tokensUsed' in session['metadata']:
                tokens = session['metadata']['tokensUsed']
                speech += f" Tokens used: {tokens}."
            
            result = {
                "ok": True,
                "speech": speech,
                "data": {
                    "session": session
                }
            }
            
        else:
            # List recent sessions
            try:
                sessions = client.list_sessions()
                if not isinstance(sessions, list):
                    sessions = []
            except Exception as e:
                return {
                    "ok": False,
                    "speech": "Failed to retrieve OpenCode sessions",
                    "error": str(e)
                }
            
            if not sessions:
                return {
                    "ok": True,
                    "speech": "No OpenCode sessions found. Use the opencode tool to build something.",
                    "data": {"sessions": []}
                }
            
            # Sort by last activity (most recent first). OpenCode 1.14 uses
            # time.updated/time.created; older builds used top-level fields.
            sessions.sort(key=lambda s: _session_timestamp(s, "updated"), reverse=True)
            
            # Limit results
            sessions = [_attach_log_summary(s) for s in sessions[:limit]]
            
            # Build speech summary
            speech = f"Found {len(sessions)} recent OpenCode session(s): "
            summaries = []
            for s in sessions[:3]:  # Only mention top 3 in speech
                title = s.get('title', 'Untitled')
                agent = s.get('agent', 'unknown')
                summaries.append(f"{title} ({agent} mode)")
            
            speech += ", ".join(summaries)
            
            if len(sessions) > 3:
                speech += f" and {len(sessions) - 3} more"
            
            result = {
                "ok": True,
                "speech": speech,
                "data": {
                    "sessions": sessions,
                    "count": len(sessions)
                }
            }
        
        print(json.dumps(result))
        return result
        
    except Exception as e:
        error_result = {
            "ok": False,
            "speech": f"Failed to check OpenCode sessions: {str(e)}",
            "error": str(e)
        }
        print(json.dumps(error_result))
        return error_result


if __name__ == "__main__":
    main()
