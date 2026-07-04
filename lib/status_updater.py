#!/usr/bin/env python3
"""
Jarvis Status Updater - Voice progress updates during long-running tasks.

Provides real-time voice feedback without blocking task execution.
Handles rate limiting, error deduplication, and collision prevention.
"""

import os
import re
import signal
import sys
import time
import threading
import subprocess
import contextvars
import uuid
from pathlib import Path
from typing import Any
from collections.abc import Callable

# Add lib to path
sys.path.insert(0, os.path.dirname(__file__))
from config_loader import get_config_value, get_int
from status_phrases import StatusPhrases
from status_llm import StatusSummarizer
from status_activity_logger import log_status_event


class StatusUpdater:
    """
    Manages voice status updates during long-running tasks.
    
    Features:
    - Rate limiting (min interval between updates)
    - Priority system (errors bypass rate limit)
    - Collision detection (don't overlap with final output)
    - Background TTS (non-blocking)
    - Error deduplication
    """
    
    def __init__(self, mode: str = 'cloud', speech_callback: Callable[[str], None] | None = None):
        """
        Initialize status updater.
        
        Args:
            mode: 'cloud' or 'local' - determines TTS script
            speech_callback: Optional callback for status messages. If provided,
                             messages are sent to callback instead of local TTS.
                             Useful for web UI to emit via WebSocket.
        """
        self.mode = mode
        self.project_root = Path(__file__).parent.parent.resolve()
        self.speech_callback = speech_callback
        self._log_event = log_status_event
        
        # Config
        self.enabled = get_config_value('STATUS_UPDATES_ENABLED', 'false').lower() == 'true'
        self.interval = get_int('STATUS_UPDATE_INTERVAL', 20)
        self.debounce_ms = max(0, get_int('STATUS_UPDATE_DEBOUNCE_MS', 250))
        self.llm_deadline_ms = max(
            self.debounce_ms,
            get_int('STATUS_LLM_DEADLINE_MS', 1000),
        )
        self.style = get_config_value('JARVIS_RESPONSE_STYLE', 'casual')
        
        # State
        self.last_update_time: float = 0
        self.task_complete: bool = False
        self.task_start_time: float = 0
        self.current_tool: str | None = None
        self.turn_number: int = 0
        
        # Error tracking
        self.recent_errors: list[tuple] = []  # [(error_key, timestamp), ...]
        self.error_cooldown = 30  # Don't repeat same error within 30s
        self.spoken_errors_count = 0
        self.max_spoken_errors = 2  # Max errors to speak per task
        
        # Thread safety
        self._lock = threading.RLock()
        self._speaking = False
        self._speech_process: subprocess.Popen | None = None
        self._status_request_id = 0
        self._pending_status: dict[int, threading.Event] = {}
        self._llm_semaphore = threading.Semaphore(1)
        self._task_id = uuid.uuid4().hex
        self._metrics = self._empty_metrics()
        
        # Phrase generator
        self.phrases = StatusPhrases()
        
        # LLM summarizer for dynamic status (falls back to phrases)
        # Create new instance to get config loaded at this point (not cached singleton)
        self.summarizer = StatusSummarizer()
        
        # Background update thread (for long tasks)
        self._background_thread: threading.Thread | None = None
        self._stop_background = threading.Event()
        
        # Store last tool context for dynamic summaries
        self._last_context: str | None = None
    
    def reset(self):
        """Reset for new task."""
        with self._lock:
            self.task_complete = False
            self.task_start_time = time.time()
            self.last_update_time = 0
            self.current_tool = None
            self.turn_number = 0
            self.recent_errors.clear()
            self.spoken_errors_count = 0
            self._stop_background.clear()
            self._last_context = None
            self._cancel_pending_status_locked()
            self._cancel_speech_locked()
            self.phrases.reset_recent()
            self._task_id = uuid.uuid4().hex
            self._metrics = self._empty_metrics()
            task_id = self._task_id
        self._log_event('turn_started', mode=self.mode, task_id=task_id)

    @staticmethod
    def _empty_metrics() -> dict[str, int]:
        return {
            'status_requests': 0,
            'rate_limited': 0,
            'llm_started': 0,
            'llm_completed': 0,
            'llm_discarded': 0,
            'llm_skipped_busy': 0,
            'dynamic_emitted': 0,
            'fallback_emitted': 0,
            'static_emitted': 0,
        }
    
    def mark_complete(self):
        """Signal that task is done - suppress further updates."""
        with self._lock:
            was_complete = self.task_complete
            self.task_complete = True
            self._stop_background.set()
            self._cancel_pending_status_locked()
            self._cancel_speech_locked()
            summary = dict(self._metrics)
            summary['llm_in_flight'] = max(0, summary['llm_started'] - summary['llm_completed'])
            task_id = self._task_id
        if not was_complete:
            self._log_event(
                'turn_completed',
                mode=self.mode,
                task_id=task_id,
                **summary,
            )
    
    def update(
        self,
        category: str = 'progress',
        tool_name: str | None = None,
        priority: str = 'normal',
        custom_message: str | None = None,
        context: dict[str, Any] | None = None
    ) -> bool:
        """
        Queue a status update.
        
        Args:
            category: Phrase category ('progress', 'searching', 'building', etc.)
            tool_name: Optional tool name for specific messages
            priority: 'normal', 'high' (errors bypass rate limit)
            custom_message: Override phrase selection with custom message
            context: Optional context dict
        
        Returns:
            True if update was queued, False if skipped
        """
        if not self.enabled:
            return False
        
        with self._lock:
            if self.task_complete:
                return False

            self._metrics['status_requests'] = self._metrics.get('status_requests', 0) + 1
            
            now = time.time()
            
            # Rate limiting (unless high priority)
            if priority != 'high':
                time_since_last = now - self.last_update_time
                if time_since_last < self.interval:
                    self._metrics['rate_limited'] += 1
                    self._log_event(
                        'status_rate_limited',
                        mode=self.mode,
                        task_id=self._task_id,
                        tool=tool_name,
                        category=category,
                        seconds_since_emit=round(time_since_last, 3),
                    )
                    return False
            
            # Get message - try LLM first (if enabled), then fall back to static phrases
            if custom_message:
                message = custom_message
            elif self.summarizer.is_enabled():
                # Try dynamic LLM summary
                # Build context from available info (explicit context, tool name, category)
                effective_tool = tool_name or self.current_tool
                event_type = self._status_event_type(category, context)
                
                # Use explicit context if available, otherwise build minimal context
                if context:
                    llm_context = self._build_minimal_context(effective_tool, category, context)
                    self._last_context = llm_context
                elif self._last_context:
                    llm_context = self._last_context
                else:
                    # Build context from tool name and category for LLM to work with
                    llm_context = self._build_minimal_context(effective_tool, category, context)
                
                fallback = self.phrases.get_phrase(
                    category=category,
                    tool_name=effective_tool,
                    style=self.style
                )
                self._queue_dynamic_status(
                    context=llm_context,
                    tool_name=effective_tool,
                    event_type=event_type,
                    fallback=fallback,
                )
                message = None
            else:
                message = self.phrases.get_phrase(
                    category=category,
                    tool_name=tool_name or self.current_tool,
                    style=self.style
                )
            
            # Reserve only the current tool here. The rate-limit clock starts
            # when a phrase actually wins the debounce/deadline race; a status
            # suppressed by fast completion must not silence the next tool.
            if tool_name:
                self.current_tool = tool_name
        
        # Static/custom status is also debounced so a fast tool can complete
        # before speech begins. Dynamic status is queued above and races its
        # short deadline without holding the tool execution path.
        if message:
            self._queue_static_status(message)
        return True
    
    def update_with_context(
        self,
        context: str,
        category: str = 'progress',
        tool_name: str | None = None,
        priority: str = 'normal'
    ) -> bool:
        """
        Update with tool output context for LLM-based dynamic summary.
        
        Args:
            context: Tool output, logs, or current state to summarize
            category: Phrase category (fallback if LLM fails)
            tool_name: Tool name for context
            priority: 'normal' or 'high'
        
        Returns:
            True if update was queued, False if skipped
        """
        return self.update(
            category=category,
            tool_name=tool_name,
            priority=priority,
            context={'detail': context},
        )
    
    def set_context(self, context: str):
        """Set the current tool context for dynamic summaries."""
        self._last_context = self._sanitize_status_text(context, 300)
    
    def update_error(
        self,
        error_type: str = 'retry',
        error_message: str | None = None,
        is_server_error: bool = False
    ) -> bool:
        """
        Handle error status update with deduplication.
        
        Args:
            error_type: 'retry', 'server', 'fatal'
            error_message: Original error message (for deduplication)
            is_server_error: True for HTTP 500, etc. (speaks immediately)
        
        Returns:
            True if error was spoken, False if deduplicated/skipped
        """
        if not self.enabled:
            return False
        
        with self._lock:
            if self.task_complete:
                return False
            
            # Check max errors
            if self.spoken_errors_count >= self.max_spoken_errors:
                return False
            
            # Deduplicate
            if error_message and not self._should_speak_error(error_message):
                return False
            
            self.spoken_errors_count += 1
        
        # Select category and priority
        if is_server_error:
            category = 'server_error'
            priority = 'high'
        else:
            category = 'error_retry'
            priority = 'normal'
        
        return self.update(
            category=category,
            priority=priority,
            context={
                'phase': 'retrying',
                'error': error_message,
            },
        )
    
    def _should_speak_error(self, error_message: str) -> bool:
        """Check if this error should be spoken (not a repeat)."""
        error_key = self._normalize_error(error_message)
        now = time.time()
        
        # Check if same error spoken recently
        for prev_error, timestamp in self.recent_errors:
            if prev_error == error_key and now - timestamp < self.error_cooldown:
                return False
        
        # Track this error
        self.recent_errors.append((error_key, now))
        # Keep last 10 errors
        self.recent_errors = self.recent_errors[-10:]
        
        return True
    
    def _normalize_error(self, error_message: str) -> str:
        """Normalize error message for deduplication."""
        # Handle list input
        if isinstance(error_message, list):
            error_message = str(error_message[0]) if error_message else ""
        # Remove specific details, keep error type
        msg = str(error_message).lower()
        # Remove numbers, URLs, IDs
        import re
        msg = re.sub(r'\d+', 'N', msg)
        msg = re.sub(r'https?://\S+', 'URL', msg)
        msg = re.sub(r'[a-f0-9-]{36}', 'UUID', msg)
        return msg[:100]  # Truncate
    
    @staticmethod
    def _status_event_type(category: str, context: dict[str, Any] | None) -> str:
        phase = str((context or {}).get('phase') or '').strip().lower()
        if phase in {'retrying', 'error'} or 'error' in category:
            return 'error'
        if phase in {'wrapping_up', 'complete'} or category == 'near_complete':
            return 'complete'
        if phase in {'starting', 'start'} or category in {'task_start', 'searching', 'fetching'}:
            return 'start'
        return 'progress'

    @staticmethod
    def _sanitize_status_text(value: Any, max_chars: int = 120) -> str:
        text = re.sub(r'\s+', ' ', str(value or '')).strip()
        text = re.sub(
            r'(?i)(api[_ -]?key|password|token|secret|authorization|cookie)\s*[:=]\s*\S+',
            r'\1=[redacted]',
            text,
        )
        text = re.sub(r'https?://([^/?#\s]+)[^\s]*', r'https://\1', text)
        return text[:max_chars].rstrip()

    def _safe_argument_summary(self, arguments: Any) -> str:
        if not isinstance(arguments, dict):
            return ''
        allowed = {
            'action', 'city', 'date', 'duration', 'file', 'file_path',
            'filename', 'format', 'location', 'model', 'name', 'path',
            'provider', 'query', 'resolution', 'symbol', 'task',
            'task_type', 'ticker', 'time', 'topic', 'url',
        }
        blocked = {
            'authorization', 'body', 'content', 'cookie', 'credentials',
            'data', 'headers', 'image', 'images', 'password', 'secret',
            'token', 'api_key', 'apikey', 'audio', 'base64',
        }
        parts = []
        for key, value in arguments.items():
            normalized = str(key).strip().lower()
            if normalized not in allowed or any(marker in normalized for marker in blocked):
                continue
            if isinstance(value, (str, int, float, bool)):
                safe_value = self._sanitize_status_text(value, 80)
            elif isinstance(value, list) and all(isinstance(item, (str, int, float, bool)) for item in value[:3]):
                safe_value = ', '.join(self._sanitize_status_text(item, 35) for item in value[:3])
            else:
                continue
            if safe_value:
                parts.append(f'{str(key)[:30]}={safe_value}')
            if len(parts) >= 5:
                break
        return '; '.join(parts)[:220]

    def _build_minimal_context(self, tool_name: str | None, category: str, context: dict[str, Any] | None) -> str:
        """Build minimal context for LLM when no explicit context is set."""
        parts = []
        
        # Tool name mapping to human-readable descriptions
        tool_descriptions = {
            'opencode': 'Building code project with AI coding assistant',
            'mcp_brave_search_brave_web_search': 'Searching the web for information',
            'mcp_brave_search_brave_local_search': 'Searching for local businesses',
            'mcp_brave_search_brave_news_search': 'Searching for news articles',
            'mcp_fetch_fetch': 'Fetching data from a website',
            'mcp_playwright_browser_navigate': 'Navigating to a webpage',
            'mcp_playwright_browser_snapshot': 'Taking a snapshot of a webpage',
            'weather': 'Getting weather information',
            'get_time': 'Getting the current time',
            'remember': 'Saving something to memory',
            'search_memory': 'Searching through memories',
            'semantic_recall': 'Recalling memories semantically',
            'crypto_price': 'Getting cryptocurrency prices',
            'api_call': 'Making an API request',
        }
        
        # Category descriptions
        category_descriptions = {
            'task_start': 'Starting a new task',
            'building': 'Building/coding something',
            'searching': 'Searching for information',
            'fetching': 'Fetching data',
            'multi_turn': 'Working through multiple steps',
            'progress': 'Making progress on the task',
            'near_complete': 'Almost finished with the task',
            'long_wait': 'Task is taking longer than expected',
            'error_retry': 'Encountered an issue, trying again',
        }
        
        # Add tool description if available
        if tool_name:
            if tool_name in tool_descriptions:
                parts.append(tool_descriptions[tool_name])
            elif 'search' in tool_name.lower():
                parts.append('Searching for information')
            elif 'brave' in tool_name.lower():
                parts.append('Searching the web')
            elif 'memory' in tool_name.lower() or 'recall' in tool_name.lower():
                parts.append('Working with memory')
            elif 'fetch' in tool_name.lower() or 'playwright' in tool_name.lower():
                parts.append('Fetching web content')
            else:
                parts.append(f'Running {tool_name}')
        
        # Add category description
        if category in category_descriptions:
            parts.append(category_descriptions[category])
        
        safe_args = self._safe_argument_summary((context or {}).get('arguments'))
        if safe_args:
            parts.append(f'Details: {safe_args}')

        previous = self._sanitize_status_text((context or {}).get('previous_outcome'), 120)
        if previous:
            parts.append(f'Previous step: {previous}')

        error = self._sanitize_status_text((context or {}).get('error'), 100)
        if error:
            parts.append(f'Issue: {error}')

        detail = self._sanitize_status_text((context or {}).get('detail'), 160)
        if detail:
            parts.append(detail)

        # Add turn info if available
        if self.turn_number > 1:
            parts.append(f'Step {self.turn_number} of multi-step task')
        
        # Add elapsed time context
        elapsed = self.get_elapsed()
        if elapsed > 30:
            parts.append(f'Been working for {int(elapsed)} seconds')
        
        return ('\n'.join(parts) if parts else 'Working on a task')[:500]

    def _cancel_pending_status_locked(self):
        self._status_request_id += 1
        for cancel_event in self._pending_status.values():
            cancel_event.set()
        self._pending_status.clear()

    def _new_status_request_locked(self) -> tuple[int, threading.Event]:
        self._cancel_pending_status_locked()
        request_id = self._status_request_id
        cancel_event = threading.Event()
        self._pending_status[request_id] = cancel_event
        return request_id, cancel_event

    def _claim_status(self, request_id: int, message: str, source: str) -> bool:
        with self._lock:
            cancel_event = self._pending_status.get(request_id)
            if self.task_complete or not cancel_event or cancel_event.is_set():
                return False
            cancel_event.set()
            self._pending_status.pop(request_id, None)
            self.last_update_time = time.time()
            metric = {
                'dynamic': 'dynamic_emitted',
                'fallback': 'fallback_emitted',
                'static': 'static_emitted',
            }[source]
            self._metrics[metric] = self._metrics.get(metric, 0) + 1
            task_id = self._task_id
        self._log_event(
            'phrase_emitted',
            mode=self.mode,
            task_id=task_id,
            request_id=request_id,
            source=source,
            message=message,
        )
        self._speak_async(message)
        return True

    def _queue_static_status(self, message: str):
        with self._lock:
            request_id, cancel_event = self._new_status_request_locked()

        def emit_after_debounce():
            if not cancel_event.wait(self.debounce_ms / 1000):
                self._claim_status(request_id, message, 'static')

        threading.Thread(target=emit_after_debounce, daemon=True).start()

    def _queue_dynamic_status(
        self,
        *,
        context: str,
        tool_name: str | None,
        event_type: str,
        fallback: str,
    ):
        with self._lock:
            request_id, cancel_event = self._new_status_request_locked()
            metrics = self._metrics
            task_id = self._task_id
        started = time.monotonic()
        config_context = contextvars.copy_context()

        def wait_for_earliest_emit():
            remaining = (started + self.debounce_ms / 1000) - time.monotonic()
            return cancel_event.wait(max(0, remaining)) if remaining > 0 else cancel_event.is_set()

        def generate_dynamic():
            if not self._llm_semaphore.acquire(blocking=False):
                with self._lock:
                    metrics['llm_skipped_busy'] += 1
                self._log_event(
                    'status_llm_skipped_busy',
                    mode=self.mode,
                    task_id=task_id,
                    request_id=request_id,
                    tool=tool_name,
                    event_type=event_type,
                )
                return
            message = None
            llm_started_at = time.monotonic()
            with self._lock:
                metrics['llm_started'] += 1
                call_index = metrics['llm_started']
            self._log_event(
                'status_llm_started',
                mode=self.mode,
                task_id=task_id,
                request_id=request_id,
                call_index=call_index,
                provider=getattr(self.summarizer, 'provider', None),
                model=getattr(self.summarizer, 'model', None),
                tool=tool_name,
                event_type=event_type,
            )
            try:
                message = self.summarizer.summarize(
                    context,
                    tool_name=tool_name,
                    event_type=event_type,
                    call_metadata={
                        'mode': self.mode,
                        'status_task_id': task_id,
                        'status_request_id': request_id,
                        'status_call_index': call_index,
                        'status_tool': tool_name,
                        'status_event_type': event_type,
                    },
                )
            except Exception as exc:
                print(f"[StatusUpdater] Dynamic status failed: {exc}", file=sys.stderr)
            finally:
                with self._lock:
                    metrics['llm_completed'] += 1
                self._llm_semaphore.release()
            self._log_event(
                'status_llm_completed',
                mode=self.mode,
                task_id=task_id,
                request_id=request_id,
                call_index=call_index,
                duration_ms=round((time.monotonic() - llm_started_at) * 1000, 2),
                had_phrase=bool(message),
            )
            if wait_for_earliest_emit():
                with self._lock:
                    metrics['llm_discarded'] += 1
                    discard_reason = 'turn_complete' if self.task_complete else 'superseded_or_fallback'
                self._log_event(
                    'status_llm_discarded',
                    mode=self.mode,
                    task_id=task_id,
                    request_id=request_id,
                    call_index=call_index,
                    reason=discard_reason,
                    had_phrase=bool(message),
                )
                return
            if not self._claim_status(
                request_id,
                message or fallback,
                'dynamic' if message else 'fallback',
            ):
                with self._lock:
                    metrics['llm_discarded'] += 1
                    discard_reason = 'turn_complete' if self.task_complete else 'superseded_or_fallback'
                self._log_event(
                    'status_llm_discarded',
                    mode=self.mode,
                    task_id=task_id,
                    request_id=request_id,
                    call_index=call_index,
                    reason=discard_reason,
                    had_phrase=bool(message),
                )

        def deadline_fallback():
            remaining = (started + self.llm_deadline_ms / 1000) - time.monotonic()
            if not cancel_event.wait(max(0, remaining)):
                self._claim_status(request_id, fallback, 'fallback')

        threading.Thread(target=lambda: config_context.run(generate_dynamic), daemon=True).start()
        threading.Thread(target=deadline_fallback, daemon=True).start()
    
    def _speak_async(self, message: str):
        """Speak message in background thread."""
        def speak():
            with self._lock:
                if self.task_complete:
                    return
                self._speaking = True
            
            try:
                self._speak(message, blocking=True)
            finally:
                with self._lock:
                    self._speaking = False
        
        thread = threading.Thread(target=speak, daemon=True)
        thread.start()
    
    def _cancel_speech_locked(self):
        process = self._speech_process
        self._speech_process = None
        if not process or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                process.terminate()
            except ProcessLookupError:
                pass

    def _speak(self, message: str, blocking: bool = False):
        """Speak via TTS script or callback."""
        # If callback is set, use it instead of local TTS
        if self.speech_callback:
            try:
                self.speech_callback(message)
            except Exception as e:
                print(f"[StatusUpdater] Callback error: {e}", file=sys.stderr)
            return
        
        # Local TTS via script
        script_name = 'say-status-local.sh' if self.mode == 'local' else 'say-status.sh'
        script = self.project_root / 'bin' / script_name
        
        if not script.exists():
            # Fallback to main say script
            script = self.project_root / 'bin' / ('say-local.sh' if self.mode == 'local' else 'say.sh')
        
        blocking_arg = 'true' if blocking else 'false'

        try:
            process = subprocess.Popen(
                [str(script), message, blocking_arg],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            with self._lock:
                if self.task_complete:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except (ProcessLookupError, PermissionError):
                        process.terminate()
                    return
                self._cancel_speech_locked()
                self._speech_process = process
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    process.terminate()
            finally:
                with self._lock:
                    if self._speech_process is process:
                        self._speech_process = None
        except Exception as e:
            # Log but don't crash
            print(f"[StatusUpdater] TTS error: {e}", file=sys.stderr)
    
    def set_speech_callback(self, callback: Callable[[str], None] | None):
        """Set or clear the speech callback for web/external TTS."""
        self.speech_callback = callback
    
    def start_background_updates(
        self,
        tool_name: str | None = None,
        category: str = 'progress',
        interval_override: int | None = None,
        session_id: str | None = None
    ):
        """
        Start background thread that emits periodic updates.
        
        Useful for long-running tools like OpenCode.
        
        Args:
            tool_name: Tool name for specific phrases
            category: Base category for updates
            interval_override: Override default interval
            session_id: OpenCode session ID for live progress polling
        """
        if not self.enabled:
            return
        
        self._stop_background.clear()
        with self._lock:
            initial_context = self._last_context
        
        def background_loop():
            interval = interval_override or self.interval
            update_count = 0
            
            while not self._stop_background.wait(interval):
                if self.task_complete:
                    break
                
                update_count += 1
                
                # Try to get live context from OpenCode session
                context = None
                if session_id and tool_name == 'opencode':
                    context = self._poll_opencode_session(session_id)
                
                # If we have context, use LLM summarization
                effective_context = context or initial_context
                
                # Progress through categories
                if update_count >= 4:
                    cat = 'near_complete'
                elif update_count >= 2:
                    cat = 'long_wait' if update_count % 2 == 0 else category
                else:
                    cat = category
                
                self.update(
                    category=cat,
                    tool_name=tool_name,
                    context={
                        'phase': 'running',
                        'detail': effective_context,
                    },
                )
        
        self._background_thread = threading.Thread(target=background_loop, daemon=True)
        self._background_thread.start()
    
    def _poll_opencode_session(self, session_id: str) -> str | None:
        """
        Poll OpenCode session for current progress.
        
        Args:
            session_id: OpenCode session ID
        
        Returns:
            Context string with recent activity, or None
        """
        try:
            import requests
            opencode_url = get_config_value('OPENCODE_BASE_URL', 'http://localhost:4096')
            server_password = get_config_value('OPENCODE_SERVER_PASSWORD', '').strip()
            server_username = get_config_value('OPENCODE_SERVER_USERNAME', 'opencode').strip() or 'opencode'

            request_kwargs: dict[str, Any] = {'timeout': 3}
            if server_password:
                request_kwargs['auth'] = (server_username, server_password)
            
            response = requests.get(
                f'{opencode_url}/session/{session_id}',
                **request_kwargs,
            )
            
            if response.status_code != 200:
                return None
            
            session = response.json()
            
            # Extract recent messages/activity
            messages = session.get('messages', [])
            if not messages:
                return None
            
            # Get last 2-3 messages for context
            recent = messages[-3:]
            context_parts = []
            
            for msg in recent:
                # Extract meaningful content
                if msg.get('type') == 'tool_call':
                    tool = msg.get('tool', {})
                    context_parts.append(f"Running: {tool.get('name', 'tool')}")
                elif msg.get('type') == 'tool_result':
                    result = msg.get('result', '')
                    if isinstance(result, str):
                        context_parts.append(result[:200])
                elif msg.get('content'):
                    content = msg.get('content', '')
                    if isinstance(content, str):
                        context_parts.append(content[:200])
            
            return '\n'.join(context_parts) if context_parts else None
            
        except Exception:
            # Silently fail - just use static phrases
            return None
    
    def stop_background_updates(self):
        """Stop background update thread."""
        self._stop_background.set()
        if self._background_thread and self._background_thread.is_alive():
            self._background_thread.join(timeout=1)
    
    def set_turn(self, turn_number: int):
        """Update turn number for multi-turn tracking."""
        with self._lock:
            if turn_number != self.turn_number:
                self._last_context = None
            self.turn_number = turn_number
    
    def is_enabled(self) -> bool:
        """Check if status updates are enabled."""
        return self.enabled
    
    def get_elapsed(self) -> float:
        """Get elapsed time since task start."""
        return time.time() - self.task_start_time


# Singleton instance
_instance: StatusUpdater | None = None


def get_status_updater(mode: str = 'cloud') -> StatusUpdater:
    """Get singleton StatusUpdater instance."""
    global _instance
    if _instance is None or _instance.mode != mode:
        _instance = StatusUpdater(mode)
    return _instance


def status_update(
    category: str = 'progress',
    tool_name: str | None = None,
    priority: str = 'normal',
    custom_message: str | None = None
) -> bool:
    """Convenience function for status update."""
    updater = get_status_updater()
    return updater.update(category, tool_name, priority, custom_message)


if __name__ == "__main__":
    # Test status updater
    print("=== Status Updater Test ===\n")
    
    # Force enable for testing
    os.environ['STATUS_UPDATES_ENABLED'] = 'true'
    os.environ['STATUS_UPDATE_INTERVAL'] = '3'  # Short interval for testing
    
    updater = StatusUpdater(mode='cloud')
    updater.enabled = True  # Force enable
    updater.interval = 3
    
    print(f"Enabled: {updater.enabled}")
    print(f"Interval: {updater.interval}s")
    print(f"Style: {updater.style}")
    print()
    
    # Simulate task
    print("Starting simulated task...")
    updater.reset()
    
    # Task start
    updater.update(category='task_start')
    print("  [task_start update sent]")
    
    time.sleep(1)
    
    # Progress (should be rate limited)
    result = updater.update(category='progress')
    print(f"  [progress update: {'sent' if result else 'rate limited'}]")
    
    time.sleep(3)
    
    # Progress (should go through)
    result = updater.update(category='progress')
    print(f"  [progress update: {'sent' if result else 'rate limited'}]")
    
    # Error (high priority)
    result = updater.update_error(error_message="Connection timeout")
    print(f"  [error update: {'sent' if result else 'deduplicated'}]")
    
    # Same error again (should be deduplicated)
    result = updater.update_error(error_message="Connection timeout")
    print(f"  [same error: {'sent' if result else 'deduplicated'}]")
    
    # Mark complete
    updater.mark_complete()
    print("\nTask marked complete.")
    
    # Try update after complete (should be blocked)
    result = updater.update(category='progress')
    print(f"Post-complete update: {'sent' if result else 'blocked'}")
