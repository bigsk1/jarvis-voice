#!/usr/bin/env python3
"""
Service Logger
Tracks all background service actions for debugging and Jarvis awareness.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any


class ServiceLogger:
    """Logger for background service actions."""
    
    def __init__(self, service_name: str, log_dir: str = None):
        """
        Initialize service logger.
        
        Args:
            service_name: Name of the service (follow_up, self_healing, reminder_scheduler)
            log_dir: Directory for log files (default: PROJECT_ROOT/logs/services)
        """
        self.service_name = service_name
        
        if log_dir is None:
            # Default to project root logs/services
            project_root = Path(__file__).parent.parent.resolve()
            log_dir = project_root / "logs" / "services"
        
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Current log file (daily rotation)
        today = datetime.now().strftime("%Y-%m-%d")
        self.log_file = self.log_dir / f"{service_name}-{today}.jsonl"
        
        # Also keep a human-readable log
        self.text_log_file = self.log_dir / f"{service_name}-{today}.log"
    
    def log_startup(self, mode: str, config: dict[str, Any] = None):
        """Log service startup."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "service": self.service_name,
            "event": "startup",
            "mode": mode,
            "config": config or {}
        }
        self._write_log(log_entry, f"Service started in {mode} mode")
    
    def log_action(self, action: str, details: dict[str, Any], success: bool = True):
        """
        Log a service action.
        
        Args:
            action: Action type (follow_up, auto_resolve, trigger_reminder, etc.)
            details: Action details (alert_id, title, etc.)
            success: Whether action succeeded
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "service": self.service_name,
            "event": "action",
            "action": action,
            "success": success,
            "details": details
        }
        
        # Build human-readable message
        if action == "follow_up":
            msg = f"Follow-up #{details.get('follow_up_count', 0)} for alert {details.get('alert_id')}: {details.get('title')}"
        elif action == "auto_resolve":
            msg = f"Auto-resolved alert {details.get('alert_id')}: {details.get('title')}"
        elif action == "url_check":
            status = "✅ UP" if success else "⏳ DOWN"
            msg = f"URL check {status}: {details.get('url')} (alert {details.get('alert_id')})"
        elif action == "trigger_reminder":
            msg = f"Triggered reminder {details.get('reminder_id')}: {details.get('title')}"
        else:
            msg = f"{action}: {details}"
        
        self._write_log(log_entry, msg)
    
    def log_error(self, error: str, details: dict[str, Any] = None):
        """Log an error."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "service": self.service_name,
            "event": "error",
            "error": error,
            "details": details or {}
        }
        self._write_log(log_entry, f"❌ ERROR: {error}")
    
    def log_check(self, found: int, details: dict[str, Any] = None):
        """Log a periodic check."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "service": self.service_name,
            "event": "check",
            "found": found,
            "details": details or {}
        }
        
        # Only log if something was found (reduce noise)
        if found > 0:
            msg = f"Check: Found {found} item(s)"
            self._write_log(log_entry, msg)
        else:
            # Still write JSON log for auditing, but not text log
            self._write_json_log(log_entry)
    
    def log_shutdown(self, stats: dict[str, Any] = None):
        """Log service shutdown."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "service": self.service_name,
            "event": "shutdown",
            "stats": stats or {}
        }
        self._write_log(log_entry, f"Service stopped. Stats: {stats}")
    
    def _write_log(self, log_entry: dict[str, Any], text_message: str):
        """Write to both JSON and text logs."""
        self._write_json_log(log_entry)
        self._write_text_log(text_message)
    
    def _write_json_log(self, log_entry: dict[str, Any]):
        """Write JSON log entry."""
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    
    def _write_text_log(self, message: str):
        """Write human-readable log entry."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        with open(self.text_log_file, 'a') as f:
            f.write(f"[{timestamp}] {message}\n")
    
    def get_recent_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent log entries."""
        if not self.log_file.exists():
            return []
        
        logs = []
        with open(self.log_file, 'r') as f:
            for line in f:
                if line.strip():
                    logs.append(json.loads(line))
        
        # Return most recent first
        return logs[-limit:][::-1]
    
    def get_logs_by_event(self, event: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get logs for a specific event type."""
        if not self.log_file.exists():
            return []
        
        logs = []
        with open(self.log_file, 'r') as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    if entry.get("event") == event:
                        logs.append(entry)
        
        return logs[-limit:][::-1]
    
    def get_error_logs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent error logs."""
        return self.get_logs_by_event("error", limit)
    
    def get_stats(self) -> dict[str, Any]:
        """Get statistics about service actions."""
        if not self.log_file.exists():
            return {
                "service": self.service_name,
                "total_actions": 0,
                "total_errors": 0,
                "actions": {}
            }
        
        stats = {
            "service": self.service_name,
            "total_actions": 0,
            "total_errors": 0,
            "successful_actions": 0,
            "failed_actions": 0,
            "actions": {},
            "last_error": None
        }
        
        with open(self.log_file, 'r') as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    event = entry.get("event")
                    
                    if event == "action":
                        stats["total_actions"] += 1
                        action = entry.get("action", "unknown")
                        
                        if action not in stats["actions"]:
                            stats["actions"][action] = {
                                "count": 0,
                                "success": 0,
                                "failed": 0
                            }
                        
                        stats["actions"][action]["count"] += 1
                        
                        if entry.get("success", True):
                            stats["successful_actions"] += 1
                            stats["actions"][action]["success"] += 1
                        else:
                            stats["failed_actions"] += 1
                            stats["actions"][action]["failed"] += 1
                    
                    elif event == "error":
                        stats["total_errors"] += 1
                        stats["last_error"] = {
                            "timestamp": entry.get("timestamp"),
                            "error": entry.get("error")
                        }
        
        return stats


def get_logger(service_name: str) -> ServiceLogger:
    """Get a service logger instance."""
    return ServiceLogger(service_name)

