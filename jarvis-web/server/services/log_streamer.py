"""
Log Streamer Service - Tails multiple JSONL log files and streams to WebSocket clients.
"""

import json
import time
import threading
from datetime import datetime
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass, asdict

# Get project root
JARVIS_ROOT = Path(__file__).parent.parent.parent.parent


@dataclass
class LogEntry:
    """Structured log entry for frontend display."""
    source: str          # 'llm', 'tool', 'opencode', 'thinking'
    timestamp: str       # ISO format
    level: str           # 'info', 'success', 'warning', 'error'
    title: str           # Short summary
    details: dict        # Full parsed data
    raw: str             # Original line (for debugging)
    
    def to_dict(self):
        return asdict(self)


class LogStreamer:
    """
    Tails multiple log files and broadcasts parsed entries via callback.
    """
    
    # Log source configurations
    # NOTE: Paths are relative to JARVIS_ROOT
    LOG_SOURCES = {
        'llm': {
            'pattern': 'logs/llm-calls-{date}.jsonl',  # Direct in logs/
            'enabled': True,
            'parse': '_parse_llm_entry'
        },
        'tool': {
            'pattern': 'logs/tools/tool-calls-{date}.jsonl',
            'enabled': True,
            'parse': '_parse_tool_entry'
        },
        'workflow': {
            'pattern': 'logs/workflows-{date}.jsonl',
            'enabled': True,
            'parse': '_parse_workflow_entry'
        },
        'opencode': {
            'pattern': 'logs/opencode/opencode-{date}.jsonl',
            'enabled': False,  # Enable on demand
            'parse': '_parse_opencode_entry'
        },
        'feedback': {
            'pattern': 'logs/feedback/feedback-{date}.jsonl',
            'enabled': True,  # Enable by default for WebUI feedback feature
            'parse': '_parse_feedback_entry'
        }
    }
    
    def __init__(self, callback: Callable[[LogEntry], None]):
        """
        Initialize streamer with a callback that receives LogEntry objects.
        
        Args:
            callback: Function to call with each new log entry
        """
        self.callback = callback
        self._running = False
        self._threads: dict[str, threading.Thread] = {}
        self._file_positions: dict[str, int] = {}
        self._enabled_sources: dict[str, bool] = {
            source: config['enabled'] 
            for source, config in self.LOG_SOURCES.items()
        }
    
    def start(self, sources: list[str] | None = None):
        """Start tailing log files."""
        if self._running:
            return
        
        self._running = True
        
        # Determine which sources to tail
        if sources:
            active_sources = [s for s in sources if s in self.LOG_SOURCES]
        else:
            active_sources = list(self.LOG_SOURCES.keys())
        
        for source in active_sources:
            if self._enabled_sources.get(source, False):
                thread = threading.Thread(
                    target=self._tail_file,
                    args=(source,),
                    daemon=True
                )
                thread.start()
                self._threads[source] = thread
    
    def stop(self):
        """Stop all tailing threads."""
        self._running = False
        self._threads.clear()
        self._file_positions.clear()
    
    def set_source_enabled(self, source: str, enabled: bool):
        """Enable or disable a log source."""
        if source in self.LOG_SOURCES:
            self._enabled_sources[source] = enabled
    
    def get_enabled_sources(self) -> dict[str, bool]:
        """Get current enabled state of all sources."""
        return self._enabled_sources.copy()
    
    def _get_log_path(self, source: str) -> Path:
        """Get the current log file path for a source."""
        config = self.LOG_SOURCES[source]
        today = datetime.now().strftime('%Y-%m-%d')
        pattern = config['pattern'].format(date=today)
        return JARVIS_ROOT / pattern
    
    def _tail_file(self, source: str):
        """Tail a single log file, parsing and broadcasting new entries."""
        config = self.LOG_SOURCES[source]
        parse_method = getattr(self, config['parse'])
        
        current_date = datetime.now().strftime('%Y-%m-%d')
        reported_missing = False
        
        print(f"[LOG_STREAMER] Starting tail for {source}")
        
        while self._running:
            try:
                # Check if date changed (new log file)
                new_date = datetime.now().strftime('%Y-%m-%d')
                if new_date != current_date:
                    current_date = new_date
                    self._file_positions.pop(source, None)
                    reported_missing = False
                
                log_path = self._get_log_path(source)
                
                if not log_path.exists():
                    if not reported_missing:
                        print(f"[LOG_STREAMER] {source}: Waiting for {log_path}")
                        reported_missing = True
                    time.sleep(2)
                    continue
                
                reported_missing = False
                
                # Get current position or start from end
                if source not in self._file_positions:
                    # Start from end of file (only show new entries)
                    self._file_positions[source] = log_path.stat().st_size
                
                with open(log_path, 'r') as f:
                    f.seek(self._file_positions[source])
                    
                    for line in f:
                        if not self._running:
                            break
                        
                        line = line.strip()
                        if not line:
                            continue
                        
                        try:
                            entry = parse_method(line, source)
                            if entry and self._enabled_sources.get(source, False):
                                self.callback(entry)
                        except Exception as e:
                            # Send raw line on parse error
                            entry = LogEntry(
                                source=source,
                                timestamp=datetime.now().isoformat(),
                                level='error',
                                title=f'Parse error: {str(e)[:50]}',
                                details={'error': str(e)},
                                raw=line[:500]
                            )
                            self.callback(entry)
                    
                    self._file_positions[source] = f.tell()
                
                time.sleep(0.5)  # Poll interval
                
            except Exception as e:
                print(f"[LOG_STREAMER] Error tailing {source}: {e}")
                time.sleep(2)
    
    def _parse_llm_entry(self, line: str, source: str) -> LogEntry | None:
        """Parse LLM call log entry."""
        try:
            data = json.loads(line)
            
            model = data.get('model', 'unknown')
            provider = data.get('provider', '')
            input_tokens = self._safe_number(data.get('input_tokens'), 0)
            output_tokens = self._safe_number(data.get('output_tokens'), 0)
            total_tokens = self._safe_number(data.get('total_tokens'), input_tokens + output_tokens)
            cost = self._safe_number(data.get('cost_usd'), 0.0)
            duration = self._safe_number(data.get('duration_ms'), 0.0)  # Correct field name
            success = data.get('success', True)
            
            # Check response for tool info
            response = data.get('response', {})
            response_type = response.get('type', 'text')
            tool_name = response.get('tool_name')
            
            level = 'success' if success else 'error'
            
            # Format duration nicely
            if duration >= 1000:
                duration_str = f"{duration/1000:.1f}s"
            else:
                duration_str = f"{duration:.0f}ms"
            
            # Format title
            title = f"{provider}/{model} → {total_tokens} tokens"
            if cost > 0:
                title += f" (${cost:.4f})"
            if duration > 0:
                title += f" [{duration_str}]"
            
            # Add tool indicator
            if response_type == 'tool_call' and tool_name:
                title += f" 🔧{tool_name}"
            
            return LogEntry(
                source=source,
                timestamp=data.get('timestamp', datetime.now().isoformat()),
                level=level,
                title=title,
                details={
                    'model': model,
                    'provider': provider,
                    'input_tokens': input_tokens,
                    'output_tokens': output_tokens,
                    'total_tokens': total_tokens,
                    'cost_usd': cost,
                    'duration_ms': duration,
                    'response_type': response_type,
                    'tool_called': tool_name or 'none',
                    'mode': data.get('mode', 'unknown')
                },
                raw=line
            )
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _safe_number(value, default=0):
        """Normalize nullable log numeric fields before title formatting."""
        if value is None:
            return default
        try:
            return float(value) if isinstance(default, float) else int(value)
        except (TypeError, ValueError):
            return default
    
    def _parse_tool_entry(self, line: str, source: str) -> LogEntry | None:
        """Parse tool call log entry."""
        try:
            data = json.loads(line)
            
            tool = data.get('tool', 'unknown')
            # Support both legacy and current tool log schema:
            # - legacy: {args, success, error}
            # - current: {arguments, result:{ok,error,speech}, duration_ms}
            args = data.get('args')
            if args is None:
                args = data.get('arguments', {})
            if not isinstance(args, dict):
                args = {}

            result_obj = data.get('result', {})
            if not isinstance(result_obj, dict):
                result_obj = {}

            success = data.get('success')
            if success is None:
                success = result_obj.get('ok', True)

            duration = data.get('duration_ms', 0)
            error = data.get('error', '') or result_obj.get('error', '')
            
            level = 'success' if success else 'error'
            
            # Format duration nicely
            if duration >= 1000:
                duration_str = f"{duration/1000:.1f}s"
            else:
                duration_str = f"{duration:.0f}ms"
            
            title = f"{tool} → {duration_str}"
            title += " ✓" if success else f" ✗ {error[:40]}"
            
            return LogEntry(
                source=source,
                timestamp=data.get('timestamp', datetime.now().isoformat()),
                level=level,
                title=title,
                details={
                    'tool': tool,
                    'success': success,
                    'duration_ms': duration,
                    # Keep full args object for expandable details view
                    'args': args,
                    # Helpful at-a-glance key for tools like canvas/create-update
                    'action': args.get('action') if isinstance(args, dict) else None,
                    'result_preview': (result_obj.get('speech') or str(result_obj))[:300],
                    'error': error,
                    'mode': data.get('mode', 'unknown')
                },
                raw=line
            )
        except json.JSONDecodeError:
            return None
    
    def _parse_workflow_entry(self, line: str, source: str) -> LogEntry | None:
        """Parse workflow execution log entry."""
        try:
            data = json.loads(line)
            
            workflow_id = data.get('workflow_id', 'unknown')
            workflow_name = data.get('workflow_name', workflow_id)
            result = data.get('result', {})
            success = result.get('ok', False)
            duration = data.get('duration_ms', 0)
            steps = result.get('steps_completed', 0)
            tools = result.get('tools_used', [])
            
            level = 'success' if success else 'error'
            
            # Format duration nicely
            if duration >= 1000:
                duration_str = f"{duration/1000:.1f}s"
            else:
                duration_str = f"{duration:.0f}ms"
            
            title = f"🔄 {workflow_name} ({steps} steps) → {duration_str}"
            title += " ✓" if success else " ✗"
            
            return LogEntry(
                source=source,
                timestamp=data.get('timestamp', datetime.now().isoformat()),
                level=level,
                title=title,
                details={
                    'workflow_id': workflow_id,
                    'workflow_name': workflow_name,
                    'success': success,
                    'duration_ms': duration,
                    'steps_completed': steps,
                    'tools_used': tools,
                    'query': data.get('user_query', ''),
                    'speech': result.get('speech', '')[:200],
                    'mode': data.get('mode', 'unknown')
                },
                raw=line
            )
        except json.JSONDecodeError:
            return None
    
    def _parse_opencode_entry(self, line: str, source: str) -> LogEntry | None:
        """Parse OpenCode session log entry."""
        try:
            data = json.loads(line)
            
            event = data.get('event', 'unknown')
            session_id = data.get('session_id', '')[:8]
            status = data.get('status', '')
            
            level = 'info'
            if status == 'completed':
                level = 'success'
            elif status in ('failed', 'error'):
                level = 'error'
            elif status == 'running':
                level = 'warning'
            
            title = f"[{session_id}] {event}"
            if status:
                title += f" → {status}"
            
            return LogEntry(
                source=source,
                timestamp=data.get('timestamp', datetime.now().isoformat()),
                level=level,
                title=title,
                details={
                    'session_id': session_id,
                    'event': event,
                    'status': status,
                    'task': data.get('task', '')[:100],
                    'workspace': data.get('workspace', '')
                },
                raw=line
            )
        except json.JSONDecodeError:
            return None
    
    def _parse_feedback_entry(self, line: str, source: str) -> LogEntry | None:
        """Parse feedback log entry."""
        try:
            data = json.loads(line)
            
            rating = data.get('rating', 0)
            query = data.get('query', '')[:50]
            
            level = 'success' if rating >= 4 else 'warning' if rating >= 2 else 'error'
            
            stars = '⭐' * rating + '☆' * (5 - rating)
            title = f"{stars} {query}..."
            
            return LogEntry(
                source=source,
                timestamp=data.get('timestamp', datetime.now().isoformat()),
                level=level,
                title=title,
                details={
                    'rating': rating,
                    'query': data.get('query', ''),
                    'feedback': data.get('feedback', ''),
                    'tools_used': data.get('tools_used', []),
                    'mode': data.get('mode', 'unknown')
                },
                raw=line
            )
        except json.JSONDecodeError:
            return None


# Singleton instance for the app
_streamer_instance: LogStreamer | None = None


def get_log_streamer(callback: Callable[[LogEntry], None]) -> LogStreamer:
    """Get or create the log streamer singleton."""
    global _streamer_instance
    if _streamer_instance is None:
        _streamer_instance = LogStreamer(callback)
    return _streamer_instance


def stop_log_streamer():
    """Stop the log streamer if running."""
    global _streamer_instance
    if _streamer_instance:
        _streamer_instance.stop()
        _streamer_instance = None
