#!/usr/bin/env python3
"""
OpenCode Activity Logger
Captures detailed OpenCode session activity for troubleshooting and monitoring.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any


class OpenCodeLogger:
    """Logger for OpenCode session activity."""
    
    def __init__(self, log_dir: str = None):
        """
        Initialize OpenCode logger.
        
        Args:
            log_dir: Directory for log files (default: PROJECT_ROOT/logs/opencode)
        """
        if log_dir is None:
            # Default to project root logs/opencode
            project_root = Path(__file__).parent.parent.resolve()
            log_dir = project_root / "logs" / "opencode"
        
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Current log file (daily rotation)
        today = datetime.now().strftime("%Y-%m-%d")
        self.log_file = self.log_dir / f"opencode-{today}.jsonl"
    
    def log_session_start(
        self,
        session_id: str,
        task: str,
        task_type: str = "general",
        model: dict[str, str] | None = None,
        context: dict[str, Any] | None = None
    ):
        """Log when an OpenCode session starts."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event": "session_start",
            "session_id": session_id,
            "task": task,
            "task_type": task_type,
            "model": model,
            "context": context
        }
        self._write_log(log_entry)
    
    def log_message_sent(
        self,
        session_id: str,
        message: str,
        message_type: str = "task",  # "system", "context", "task"
        no_reply: bool = False
    ):
        """Log messages sent to OpenCode."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event": "message_sent",
            "session_id": session_id,
            "message_type": message_type,
            "message_preview": message[:200] + "..." if len(message) > 200 else message,
            "message_length": len(message),
            "no_reply": no_reply
        }
        self._write_log(log_entry)
    
    def log_message_received(
        self,
        session_id: str,
        response: dict[str, Any],
        duration_ms: float | None = None
    ):
        """Log responses received from OpenCode."""
        # Extract key info from response
        response_info = {
            "has_content": "content" in response or "parts" in response,
            "has_error": "error" in response,
            "message_id": response.get("info", {}).get("id") if isinstance(response.get("info"), dict) else None,
            "model_used": response.get("info", {}).get("modelID") if isinstance(response.get("info"), dict) else None,
            "tokens": response.get("info", {}).get("tokens", {}) if isinstance(response.get("info"), dict) else None,
        }
        
        # Extract actual response content from OpenCode's parts array
        response_text = None
        if "parts" in response and isinstance(response["parts"], list):
            # OpenCode returns parts with different types: step-start, text, step-finish
            # We want the "text" type parts
            text_parts = []
            for part in response["parts"]:
                if isinstance(part, dict) and part.get("type") == "text" and "text" in part:
                    text_parts.append(part["text"])
            if text_parts:
                response_text = "\n".join(text_parts)
        elif "content" in response:
            response_text = str(response["content"])
        
        # Preview response (first 500 chars)
        response_preview = None
        if response_text:
            response_preview = response_text[:500] + "..." if len(response_text) > 500 else response_text
        
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event": "message_received",
            "session_id": session_id,
            "response_info": response_info,
            "response_preview": response_preview,
            "response_length": len(response_text) if response_text else 0,
            "duration_ms": duration_ms,
            "has_error": response_info["has_error"]
        }
        self._write_log(log_entry)

    def log_progress(
        self,
        session_id: str,
        progress: dict[str, Any],
    ):
        """Log one normalized live progress event from OpenCode."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event": "progress",
            "session_id": session_id,
            "phase": progress.get("phase"),
            "status": progress.get("status"),
            "opencode_event": progress.get("event_type"),
            "tool": progress.get("opencode_tool"),
            "tool_status": progress.get("tool_status"),
            "progress_percent": progress.get("progress"),
        }
        self._write_log(log_entry)
    
    def log_session_complete(
        self,
        session_id: str,
        success: bool,
        result_summary: str | None = None,
        error: str | None = None
    ):
        """Log when an OpenCode session completes."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event": "session_complete",
            "session_id": session_id,
            "success": success,
            "result_summary": result_summary,
            "error": error
        }
        self._write_log(log_entry)
    
    def log_error(
        self,
        session_id: str | None,
        error_type: str,
        error_message: str,
        context: dict[str, Any] | None = None
    ):
        """Log errors during OpenCode operations."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event": "error",
            "session_id": session_id,
            "error_type": error_type,
            "error_message": error_message,
            "context": context
        }
        self._write_log(log_entry)
    
    def _write_log(self, entry: dict[str, Any]):
        """Write log entry to file."""
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    
    def get_session_logs(self, session_id: str) -> list:
        """Get all logs for a specific session."""
        if not self.log_file.exists():
            return []
        
        logs = []
        with open(self.log_file, 'r') as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    if entry.get("session_id") == session_id:
                        logs.append(entry)
        
        return logs
    
    def get_recent_logs(self, limit: int = 20) -> list:
        """Get recent OpenCode activity."""
        if not self.log_file.exists():
            return []
        
        logs = []
        with open(self.log_file, 'r') as f:
            for line in f:
                if line.strip():
                    logs.append(json.loads(line))
        
        # Return most recent first
        return logs[-limit:][::-1]


def get_opencode_logger() -> OpenCodeLogger:
    """Get singleton OpenCode logger instance."""
    return OpenCodeLogger()
