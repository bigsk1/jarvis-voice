"""
Flask Error Logger - Shared error logging for all Flask-based UIs.

Logs HTTP errors (4xx/5xx) to JSONL files with daily rotation.
Matches the same format as the FastAPI RequestLoggingMiddleware
in api/server.py so all error logs are grep-able with the same patterns.

Usage (one line in any Flask app):
    from flask_error_logger import setup_error_logging
    setup_error_logging(app, 'web-ui')

This creates: logs/web-ui/errors-YYYY-MM-DD.jsonl
"""
import json
import time
from datetime import datetime
from pathlib import Path
from flask import Flask, request, g


# Project root
JARVIS_ROOT = Path(__file__).parent.parent
LOGS_DIR = JARVIS_ROOT / "logs"


def setup_error_logging(app: Flask, service_name: str, log_dir: Path = None):
    """
    Add error logging to a Flask app.
    
    Logs all 4xx/5xx responses to logs/{service_name}/errors-YYYY-MM-DD.jsonl
    
    Args:
        app: Flask application instance
        service_name: Name for log subfolder (e.g. 'web-ui', 'memory-ui')
        log_dir: Override log directory (default: logs/{service_name})
    """
    service_log_dir = log_dir or (LOGS_DIR / service_name)
    service_log_dir.mkdir(parents=True, exist_ok=True)
    
    # Skip logging for health check and static paths
    skip_paths = {"/api/health", "/api/status", "/metrics"}
    skip_extensions = {".css", ".js", ".ico", ".png", ".jpg", ".svg", ".woff", ".woff2", ".mp4", ".webm"}
    
    def _write_log(entry: dict):
        """Write a JSONL log entry."""
        try:
            date_str = datetime.now().strftime("%Y-%m-%d")
            log_file = service_log_dir / f"errors-{date_str}.jsonl"
            with open(log_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"⚠️  [{service_name}] Failed to write error log: {e}")
    
    def _start_timer():
        """Record request start time."""
        g._request_start_time = time.time()
    
    def _log_errors(response):
        """Log 4xx and 5xx responses."""
        # Skip health checks and static files
        if request.path in skip_paths:
            return response
        if any(request.path.endswith(ext) for ext in skip_extensions):
            return response
        
        status_code = response.status_code
        if status_code >= 400:
            duration_ms = (time.time() - getattr(g, '_request_start_time', time.time())) * 1000
            
            entry = {
                "timestamp": datetime.now().isoformat(),
                "service": service_name,
                "method": request.method,
                "path": request.path,
                "query": request.query_string.decode("utf-8") or None,
                "status": status_code,
                "duration_ms": round(duration_ms, 2),
                "client_ip": request.remote_addr or "unknown",
            }
            
            # Include response body for API errors (truncated)
            if request.path.startswith("/api/"):
                try:
                    body = response.get_data(as_text=True)[:500]
                    entry["response_body"] = body
                except:
                    pass
            
            _write_log(entry)
        
        return response
    
    # Register hooks with Flask (function-call style so linter sees them as accessed)
    app.before_request(_start_timer)
    app.after_request(_log_errors)
    
    # NOTE: We intentionally don't register @app.errorhandler(Exception) here.
    # Each Flask app already has its own @app.errorhandler(500) which converts
    # exceptions into 500 responses. The @app.after_request hook above then
    # catches those 500 responses and logs them. Tracebacks for unhandled
    # exceptions still appear in the tmux session stderr (Flask's default).
    
    print(f"📋 [{service_name}] Error logging → {service_log_dir}/errors-*.jsonl")
