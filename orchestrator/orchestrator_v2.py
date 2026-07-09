#!/usr/bin/env python3
"""
Jarvis Voice Assistant - Main Orchestrator (v2)
Enhanced with LLM-based routing and confirmation flow.
"""
import os
import sys
import json
import time
import re
from pathlib import Path
from typing import Any
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import (
    load_config,
    get_int,
    get_float,
    get_config_value,
    DEFAULT_JARVIS_QA_WORD_LIMIT,
    DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT,
)
from time_utils import safe_iso_to_local_datetime, parse_utc_timestamp, now_utc
from memory_db import get_memory_db, is_eligible_for_auto_memory_inject
from model_catalog import get_provider_fallback_model
from status_updater import StatusUpdater
from security_utils import sanitize_for_speech

from router_v2 import LLMRouter, ProviderRouteInput
from context_assembler import ContextAssembler
from response_formatter import ResponseFormatter
from executor import ToolExecutor
from workflow_loader import WorkflowLoader
from pipeline_executor import PipelineExecutor


SINGLE_CALL_TOOLS = frozenset({
    # Expensive/side-effecting tools that should complete once per user request.
    # Cap is based on prior *attempts* in this request (see tool_call_counts below).
    # Failed first attempts still block a second try for these tools — intentional
    # for side-effecting generators; canvas uses separate success-aware caps instead.
    "generate_video",
    "generate_image",
    "generate_music",
    "send_email",
    "opencode",
})

def _sanitize_error_for_speech(error) -> str:
    """
    Sanitize technical error messages for voice output.

    Handles common HTTP/runtime failures, strips sensitive connection details,
    and converts noisy internal exceptions into short speech-safe phrases.
    """
    # Handle list input
    if isinstance(error, list):
        error = str(error[0]) if error else "Unknown error"
    error = str(error)

    if not error:
        return "an unknown error occurred"
    
    error_lower = error.lower()

    if "third-party content" in error_lower:
        return "the provider blocked the request under its third-party-content guardrails"
    if "input blocked" in error_lower or "guardrail" in error_lower:
        return "the provider blocked the request under its safety guardrails"
    
    # Map common errors to friendly messages
    if "400" in error or "bad request" in error_lower:
        return "the service returned an error"
    if "401" in error or "unauthorized" in error_lower:
        return "authentication failed"
    if "403" in error or "forbidden" in error_lower:
        return "access was denied"
    if "404" in error or "not found" in error_lower:
        return "the resource was not found"
    if "429" in error or "rate limit" in error_lower:
        return "too many requests, try again later"
    if "500" in error or "internal server error" in error_lower:
        return "the service encountered an error"
    if "502" in error or "bad gateway" in error_lower:
        return "the service is temporarily unavailable"
    if "503" in error or "service unavailable" in error_lower:
        return "the service is temporarily unavailable"
    if "timeout" in error_lower:
        return "the request timed out"
    if "connection" in error_lower and ("refused" in error_lower or "error" in error_lower):
        return "couldn't connect to the service"
    if "session" in error_lower or "transport" in error_lower:
        return "connection issue with the service"
    
    # Handle Python-specific errors (internal bugs - should never be spoken)
    if "nonetype" in error_lower or "'nonetype'" in error_lower:
        return "encountered an unexpected response"
    if "keyerror" in error_lower or "key error" in error_lower:
        return "missing data in the response"
    if "typeerror" in error_lower or "type error" in error_lower:
        return "encountered an unexpected data format"
    if "attributeerror" in error_lower or "attribute error" in error_lower:
        return "encountered an unexpected response format"
    if "indexerror" in error_lower or "index error" in error_lower:
        return "no results were returned"
    if "valueerror" in error_lower or "value error" in error_lower:
        return "received invalid data"
    if "not subscriptable" in error_lower:
        return "received an empty response"
    if "traceback" in error_lower or "line " in error_lower:
        return "there was an internal error"
    
    # Remove URLs, IPs, and session IDs from error if no pattern matched
    sanitized = re.sub(r'https?://[^\s]+', '', error)
    sanitized = re.sub(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?', '', sanitized)
    sanitized = re.sub(r'session[Ii]d[=:][^\s&]+', '', sanitized)
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    
    # If sanitized is too long or still technical, use generic message
    if len(sanitized) > 100 or not sanitized:
        return "there was a technical error"
    
    return sanitized


def _format_terminal_tool_failure(
    tool_name: str,
    error: Any,
    arguments: dict[str, Any] | None = None,
) -> str:
    """Build truthful user-facing speech for a non-retryable tool failure."""
    error_text = str(error or "Unknown error")
    error_lower = error_text.lower()
    arguments = arguments or {}
    provider = str(arguments.get("provider") or "the selected provider").strip().lower()
    provider_label = {
        "gemini": "Gemini",
        "xai": "xAI",
        "openai": "OpenAI",
    }.get(provider, "The selected provider")
    artifact = {
        "generate_video": "video",
        "generate_image": "image",
        "generate_music": "audio",
    }.get(tool_name, "output")

    if "third-party content" in error_lower:
        guidance = (
            "Try a different source image or manually select another video provider."
            if tool_name == "generate_video"
            else "Try different source material or manually select another provider."
        )
        return (
            f"{provider_label} blocked this request under its third-party-content guardrails. "
            f"No {artifact} was generated. {guidance}"
        )
    if "input blocked" in error_lower or "guardrail" in error_lower:
        return (
            f"{provider_label} blocked this request under its safety guardrails. "
            "No output was generated. Try different source material or revise the request."
        )

    friendly_error = _sanitize_error_for_speech(error_text).rstrip(".")
    display_name = tool_name.replace("_", " ").strip().capitalize() or "Tool"
    return f"{display_name} failed because {friendly_error}."


WEB_UPLOAD_VISION_ANALYSIS_PREFIX = "[User uploaded an image. Vision analysis:"
WEB_UPLOAD_MULTI_IMAGE_VISION_ANALYSIS_PREFIX = "[User uploaded multiple images"


def _request_has_web_vision_analysis(text: str) -> bool:
    """Detect web UI upload flow where pre-vision text is already in the prompt."""
    haystack = text or ""
    return (
        WEB_UPLOAD_VISION_ANALYSIS_PREFIX in haystack
        or WEB_UPLOAD_MULTI_IMAGE_VISION_ANALYSIS_PREFIX in haystack
    )


def _server_side_tool_call_count(server_side_tools: dict | None) -> int:
    """Count provider-native tool calls from usage metadata."""
    if not isinstance(server_side_tools, dict):
        return 0
    total = 0
    for count in server_side_tools.values():
        try:
            total += max(0, int(count))
        except (TypeError, ValueError):
            continue
    return total


def _has_client_side_search_tool_hint(text: str) -> bool:
    """Detect UI tool hints that should be tested instead of provider-native search."""
    if "[CONTEXT - Tool preference" not in (text or ""):
        return False
    hinted_search_tools = (
        "brave_llm_context",
        "mcp_brave_search_",
        "serpapi_",
        "crawl_url",
    )
    return any(tool in text for tool in hinted_search_tools)


class Orchestrator:
    """Main orchestration with LLM-based routing, error recovery, and retry logic."""

    DIRECT_SPEECH_TOOLS = {'status_recap', 'generate_music', 'phone_call', 'create_reminder'}

    _TRACE_SENSITIVE_KEY_PARTS = (
        "api_key",
        "apikey",
        "authorization",
        "auth",
        "bearer",
        "cookie",
        "password",
        "secret",
        "session",
        "token",
    )

    @staticmethod
    def _has_usage_data(usage: dict | None) -> bool:
        """Return True when usage contains meaningful metering or prompt provenance."""
        if not isinstance(usage, dict):
            return False
        numeric_keys = (
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cost_usd",
            "cache_creation_tokens",
            "cache_read_tokens",
            "cache_savings_usd",
        )
        if any((usage.get(key) or 0) > 0 for key in numeric_keys):
            return True
        return bool(
            usage.get("server_side_tools")
            or usage.get("router_prompt_version")
        )

    def _attach_router_prompt_usage(self, usage: dict) -> dict:
        """Stamp usage with the request's initial hash-validated prompt version."""
        router_prompt_version = getattr(self.router, "system_prompt_version", None)
        if router_prompt_version:
            usage.setdefault("router_prompt_version", router_prompt_version)
        return usage

    @classmethod
    def _sanitize_tool_trace_value(
        cls,
        value: Any,
        *,
        depth: int = 0,
        max_depth: int = 3,
        max_string: int = 300,
        max_items: int = 20,
    ) -> Any:
        """Keep trace arguments useful for reflection while avoiding secrets/bloat."""
        if depth > max_depth:
            return "[max depth]"

        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= max_items:
                    sanitized["__truncated__"] = f"{len(value) - max_items} more item(s)"
                    break
                key_str = str(key)
                lowered = key_str.lower()
                if any(part in lowered for part in cls._TRACE_SENSITIVE_KEY_PARTS):
                    sanitized[key_str] = "[redacted]"
                else:
                    sanitized[key_str] = cls._sanitize_tool_trace_value(
                        item,
                        depth=depth + 1,
                        max_depth=max_depth,
                        max_string=max_string,
                        max_items=max_items,
                    )
            return sanitized

        if isinstance(value, list):
            items = [
                cls._sanitize_tool_trace_value(
                    item,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_string=max_string,
                    max_items=max_items,
                )
                for item in value[:max_items]
            ]
            if len(value) > max_items:
                items.append(f"[truncated {len(value) - max_items} more item(s)]")
            return items

        if isinstance(value, tuple):
            return cls._sanitize_tool_trace_value(
                list(value),
                depth=depth,
                max_depth=max_depth,
                max_string=max_string,
                max_items=max_items,
            )

        if isinstance(value, str):
            return value if len(value) <= max_string else value[: max_string - 15].rstrip() + "... [truncated]"

        if value is None or isinstance(value, (bool, int, float)):
            return value

        text = str(value)
        return text if len(text) <= max_string else text[: max_string - 15].rstrip() + "... [truncated]"
    
    def __init__(self, mode='cloud', provider_override=None, model_override=None):
        """
        Initialize orchestrator.
        
        Args:
            mode: 'cloud' or 'local'
            provider_override: Optional LLM provider override (for web UI)
            model_override: Optional model override (for web UI)
        """
        self.mode = mode
        self._provider_override = provider_override
        self._model_override = model_override
        load_config(mode)
        
        # Self-play intentionally writes learning data only to its selected
        # mode. Do not let an unattended test run cross-sync the other mode's
        # Memory database during orchestrator startup.
        if os.environ.get("JARVIS_SELF_PLAY", "").strip().lower() != "true":
            try:
                from auto_sync_memory import auto_sync_on_startup
                auto_sync_on_startup(mode, verbose=False)
            except Exception:
                # Non-critical - continue if sync fails
                pass
        
        # Get shared tool registry singleton (includes MCP discovery)
        # This prevents duplicate MCP containers across multiple Orchestrator instances
        from tool_schema import get_tool_registry
        self.registry = get_tool_registry(mode=mode)
        
        # Pass shared registry to router and executor
        self.router = LLMRouter(
            mode, 
            registry=self.registry,
            provider_override=self._provider_override,
            model_override=self._model_override
        )
        self.prompt_override = getattr(self.router, "prompt_override", None)
        self.executor = ToolExecutor(mode, registry=self.registry)
        self.executor.set_cancel_check(self._is_cancelled)
        self.max_retries = 1  # Maximum retry attempts
        
        # Workflow orchestration (explicit commands like /research, /note)
        self.workflow_loader = WorkflowLoader(explicit_only=True)
        self.pipeline_executor = PipelineExecutor(mode, self.executor)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")  # Unique session ID
        self.executor.set_session_context(jarvis_session_id=self.session_id)
        self.timezone = ZoneInfo(get_config_value("JARVIS_TIMEZONE", "America/Los_Angeles"))
        
        # Auto-context configuration
        self.auto_context_enabled = get_config_value('AUTO_CONTEXT_ENABLED', 'true').lower() == 'true'
        self.auto_context_window = get_int('AUTO_CONTEXT_WINDOW', 3)
        self.auto_context_minutes = get_int('AUTO_CONTEXT_MINUTES', 10)
        self.context_assembler = ContextAssembler(
            timezone_obj=self.timezone,
            auto_context_window=self.auto_context_window,
            auto_context_minutes=self.auto_context_minutes,
            safe_iso_to_local_datetime=self._safe_iso_to_local_datetime,
            format_age_seconds=self._format_age_seconds,
            format_gap_for_prompt=self._format_gap_for_prompt,
            conversation_has_text_summary_for_ref=self._conversation_has_text_summary_for_ref,
            stash_ref_from_result=self._stash_ref_from_result,
            get_memory_db_fn=get_memory_db,
            now_utc_fn=now_utc,
            parse_utc_timestamp_fn=parse_utc_timestamp,
        )
        self.response_formatter = ResponseFormatter(
            provider=self.router.provider,
            prompt_override=getattr(self, "prompt_override", None),
            extract_useful_data_fn=self._extract_useful_data,
        )
        
        # Status updates for voice progress feedback
        self.status_updater = StatusUpdater(mode)
        
        # Progress callback for real-time tool execution events (WebSocket)
        self.progress_callback = None
        # Cancel check callback - returns True if processing should be cancelled
        self.cancel_check = None
        # Web conversation ID for tracking web UI chat sessions (stored in metadata)
        self.web_conversation_id = None
        self._last_experience_id = None
        self._previous_experience_id_for_correction = None
        # Internal repair/meta passes can disable learning to avoid polluting experiences.
        self.learning_enabled = True
    
    def set_status_callback(self, callback):
        """Set callback for status updates (for web UI to emit via WebSocket)."""
        self.status_updater.set_speech_callback(callback)
    
    def set_progress_callback(self, callback):
        """Set callback for progress events (tool start/complete, turn info).
        
        Callback will be called with:
        - tool_start(tool_name, turn, max_turns, args)
        - tool_complete(tool_name, duration_ms, success, error=None)
        - routing(message)
        """
        self.progress_callback = callback
    
    def set_web_conversation_id(self, conversation_id: str):
        """Set web UI conversation ID for tracking in metadata.
        
        This allows filtering conversations by web chat session when searching.
        Only set this for web UI requests, not CLI/voice.
        """
        self.web_conversation_id = conversation_id
        self.executor.set_session_context(
            jarvis_session_id=self.session_id,
            web_conversation_id=conversation_id
        )
    
    def set_cancel_check(self, callback):
        """Set callback to check if processing should be cancelled.
        
        Callback should return True if cancellation is requested.
        Checked between turns and before tool execution.
        """
        self.cancel_check = callback

    def set_learning_enabled(self, enabled: bool):
        """Enable or disable intelligence experience recording for this orchestrator run."""
        self.learning_enabled = bool(enabled)
    
    def _is_cancelled(self) -> bool:
        """Check if processing has been cancelled."""
        if self.cancel_check:
            try:
                return bool(self.cancel_check())
            except Exception:
                return False
        return False
    
    def _emit_progress(self, event_type: str, **kwargs):
        """Emit progress event if callback is set."""
        if getattr(self, "progress_callback", None):
            try:
                self.progress_callback(event_type, **kwargs)
            except Exception as e:
                if sys.stdout.isatty():
                    print(f"⚠️ Progress callback error: {e}")

    def _tool_freshness_ttl_seconds(self, tool_name: str) -> int | None:
        """
        TTL hint for how long a tool result should be considered authoritative.
        """
        ttl_map = {
            "crypto_price": 120,
            "stock_price": 120,
            "weather": 600,
            "get_time": 60,
        }
        return ttl_map.get(tool_name)

    @staticmethod
    def _config_bool(name: str, default: bool = False) -> bool:
        value = str(get_config_value(name, str(default))).strip().lower()
        return value in {"1", "true", "yes", "on"}

    @staticmethod
    def _config_int(name: str, default: int) -> int:
        try:
            return int(str(get_config_value(name, str(default))).strip())
        except (TypeError, ValueError):
            return default

    def _xai_native_continuation_allowed(self) -> bool:
        provider = getattr(getattr(self, "router", None), "provider", None)
        return (
            getattr(self.router, "provider_type", "") == "xai"
            and self._config_bool("XAI_SEARCH", False)
            and self._config_bool("XAI_STORE_MESSAGES", False)
            and self._config_bool("XAI_NATIVE_CONTINUATION", False)
            and bool(getattr(provider, "enable_search", False))
            and bool(getattr(provider, "xai_client", None))
            and str(get_config_value("XAI_CONTINUATION_CONTEXT_MODE", "structural")).strip().lower() == "structural"
        )

    def _provider_server_side_tools_available(self) -> bool:
        """Return True when the active router provider can run native server-side tools."""
        router = getattr(self, "router", None)
        if router is None:
            return False

        provider_type = getattr(router, "provider_type", "") or ""
        provider = getattr(router, "provider", None)

        if provider_type == "xai":
            return (
                self._config_bool("XAI_SEARCH", False)
                and bool(getattr(provider, "enable_search", False))
                and bool(getattr(provider, "xai_client", None))
            )
        if provider_type == "openai":
            from openai_responses_adapter import openai_env_bool, openai_responses_router_enabled

            return (
                openai_responses_router_enabled()
                and openai_env_bool("OPENAI_RESPONSES_SERVER_SIDE_TOOLS", False)
            )
        if provider_type == "anthropic":
            return self._config_bool("ANTHROPIC_SEARCH", False)
        return False

    def _xai_provider_result_max_chars(self) -> int:
        return max(800, self._config_int("XAI_CONTINUATION_RESULT_MAX_CHARS", 6000))

    def _xai_previous_response_max_age_days(self) -> int:
        return max(1, self._config_int("XAI_PREVIOUS_RESPONSE_MAX_AGE_DAYS", 25))

    def _safe_iso_to_local_datetime(self, iso_text: str):
        """Parse ISO timestamp string and normalize to local timezone."""
        return safe_iso_to_local_datetime(iso_text, self.timezone)

    def _get_context_assembler(self) -> ContextAssembler:
        """Lazily build the context assembler for tests that bypass __init__ via __new__."""
        assembler = getattr(self, "context_assembler", None)
        if assembler is not None:
            return assembler

        if not hasattr(self, "timezone"):
            self.timezone = ZoneInfo(get_config_value("JARVIS_TIMEZONE", "America/Los_Angeles"))
        if not hasattr(self, "auto_context_window"):
            self.auto_context_window = get_int("AUTO_CONTEXT_WINDOW", 3)
        if not hasattr(self, "auto_context_minutes"):
            self.auto_context_minutes = get_int("AUTO_CONTEXT_MINUTES", 10)

        assembler = ContextAssembler(
            timezone_obj=self.timezone,
            auto_context_window=self.auto_context_window,
            auto_context_minutes=self.auto_context_minutes,
            safe_iso_to_local_datetime=self._safe_iso_to_local_datetime,
            format_age_seconds=self._format_age_seconds,
            format_gap_for_prompt=self._format_gap_for_prompt,
            conversation_has_text_summary_for_ref=self._conversation_has_text_summary_for_ref,
            stash_ref_from_result=self._stash_ref_from_result,
            get_memory_db_fn=get_memory_db,
            now_utc_fn=now_utc,
            parse_utc_timestamp_fn=parse_utc_timestamp,
        )
        self.context_assembler = assembler
        return assembler

    def _get_response_formatter(self) -> ResponseFormatter:
        """Lazily build the response formatter for tests that bypass __init__ via __new__."""
        formatter = getattr(self, "response_formatter", None)
        if formatter is not None:
            return formatter

        provider = getattr(getattr(self, "router", None), "provider", None)
        prompt_override = getattr(self, "prompt_override", None)
        formatter = ResponseFormatter(
            provider=provider,
            prompt_override=prompt_override,
            extract_useful_data_fn=self._extract_useful_data,
        )
        self.response_formatter = formatter
        return formatter

    def _xai_continuation_fallback_reason(self, continuation: dict[str, Any] | None) -> str | None:
        """Return None when stored xAI continuation metadata is usable for this turn."""
        if not self._xai_native_continuation_allowed():
            return "disabled"
        if not continuation:
            return "missing_continuation"
        if continuation.get("provider") != "xai":
            return "provider_mismatch"
        if not continuation.get("response_id"):
            return "missing_response_id"
        if not continuation.get("tool_call_id"):
            return "missing_tool_call_id"
        model = continuation.get("model")
        current_model = getattr(getattr(self, "router", None), "model_name", None)
        if not model or not current_model or model != current_model:
            return "model_mismatch"
        created_raw = continuation.get("response_created_at_iso")
        created_dt = self._safe_iso_to_local_datetime(created_raw)
        if not created_dt:
            return "missing_response_created_at"
        max_age = timedelta(days=self._xai_previous_response_max_age_days())
        if datetime.now(self.timezone) - created_dt > max_age:
            return "response_id_expired"
        if not continuation.get("result_message"):
            return "missing_result_message"
        return None

    def _build_xai_structural_route_input(
        self,
        *,
        retrieval_query: str,
        continuation: dict[str, Any],
        turn_notice: str | None = None,
    ) -> ProviderRouteInput:
        delta_enabled = self._config_bool("XAI_CONTINUATION_DELTA_MESSAGE", False)
        result_message = continuation["result_message"]
        if turn_notice and not delta_enabled:
            result_message = f"{turn_notice}\n{result_message}"
        messages: list[dict[str, Any]] = [
            {
                "role": "tool",
                "content": result_message,
                "tool_call_id": continuation["tool_call_id"],
                "id": continuation["tool_call_id"],
            }
        ]
        if delta_enabled:
            message_lines = []
            if turn_notice:
                message_lines.append(turn_notice)
            message_lines.append(
                "Continue the original Jarvis request. Use the completed tool result above. "
                "Choose the next required tool only if the original request is not complete; "
                "otherwise answer directly."
            )
            messages.append({
                "role": "user",
                "content": "\n".join(message_lines),
            })
        return ProviderRouteInput(
            tool_retrieval_query=retrieval_query,
            messages=messages,
            system_prompt=None,
            previous_response_id=continuation["response_id"],
            continuation_mode=(
                "stored_with_delta"
                if delta_enabled
                else "stored_structural"
            ),
        )

    def _build_xai_provider_continuation(
        self,
        *,
        route: dict[str, Any],
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        duration_ms: int,
    ) -> dict[str, Any] | None:
        response_id = route.get("response_id")
        tool_call_id = route.get("tool_call_id") or route.get("id")
        if not response_id or not tool_call_id:
            return None
        created_at = route.get("response_created_at_iso") or datetime.now(self.timezone).isoformat()
        created_dt = self._safe_iso_to_local_datetime(created_at) or datetime.now(self.timezone)
        expires_at = created_dt + timedelta(days=30)
        safe_until = created_dt + timedelta(days=self._xai_previous_response_max_age_days())
        result_message, result_meta = self._get_context_assembler().build_provider_tool_result_message(
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            tool_call_id=tool_call_id,
            duration_ms=duration_ms,
            max_chars=self._xai_provider_result_max_chars(),
        )
        return {
            "provider": "xai",
            "response_id": response_id,
            "model": route.get("response_model") or getattr(self.router, "model_name", None),
            "model_alias": get_config_value("XAI_MODEL", getattr(self.router, "model_name", "")),
            "response_created_at_iso": created_dt.isoformat(),
            "response_expires_at_iso": expires_at.isoformat(),
            "safe_until_iso": safe_until.isoformat(),
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "result_message": result_message,
            "result_meta": result_meta,
        }

    def _openai_provider_result_max_chars(self) -> int:
        return max(800, self._config_int("OPENAI_RESPONSES_RESULT_MAX_CHARS", 6000))

    def _openai_previous_response_max_age_days(self) -> int:
        return max(1, self._config_int("OPENAI_PREVIOUS_RESPONSE_MAX_AGE_DAYS", 25))

    def _openai_responses_tracking_enabled(self) -> bool:
        """Track OpenAI response ids whenever Responses tool routing is enabled."""
        if getattr(getattr(self, "router", None), "provider_type", "") != "openai":
            return False
        from openai_responses_adapter import openai_responses_router_enabled

        return openai_responses_router_enabled()

    def _openai_native_continuation_allowed(self) -> bool:
        if not self._openai_responses_tracking_enabled():
            return False
        from openai_responses_adapter import openai_responses_inflight_continuation_enabled

        return openai_responses_inflight_continuation_enabled()

    def _openai_continuation_fallback_reason(self, continuation: dict[str, Any] | None) -> str | None:
        """Return None when OpenAI Responses continuation metadata is usable for this turn."""
        if not self._openai_native_continuation_allowed():
            return "disabled"
        if not continuation:
            return "missing_continuation"
        if continuation.get("provider") != "openai":
            return "provider_mismatch"
        if not continuation.get("response_id"):
            return "missing_response_id"
        if not continuation.get("tool_call_id"):
            return "missing_tool_call_id"
        model = continuation.get("model")
        current_model = getattr(getattr(self, "router", None), "model_name", None)
        if not model or not current_model or model != current_model:
            return "model_mismatch"
        created_raw = continuation.get("response_created_at_iso")
        created_dt = self._safe_iso_to_local_datetime(created_raw)
        if not created_dt:
            return "missing_response_created_at"
        max_age = timedelta(days=self._openai_previous_response_max_age_days())
        if datetime.now(self.timezone) - created_dt > max_age:
            return "response_id_expired"
        if not continuation.get("result_message"):
            return "missing_result_message"
        return None

    def _build_openai_responses_route_input(
        self,
        *,
        retrieval_query: str,
        continuation: dict[str, Any],
        turn_notice: str | None = None,
    ) -> ProviderRouteInput:
        delta_enabled = self._config_bool("OPENAI_RESPONSES_CONTINUATION_DELTA_MESSAGE", False)
        result_message = continuation["result_message"]
        if turn_notice and not delta_enabled:
            result_message = f"{turn_notice}\n{result_message}"
        items: list[dict[str, Any]] = [
            {
                "type": "function_call_output",
                "call_id": continuation["tool_call_id"],
                "output": result_message,
            }
        ]
        if delta_enabled:
            message_lines = []
            if turn_notice:
                message_lines.append(turn_notice)
            message_lines.append(
                "Continue the original Jarvis request. Use the completed tool result above. "
                "Choose the next required tool only if the original request is not complete; "
                "otherwise answer directly."
            )
            items.append({
                "role": "user",
                "content": "\n".join(message_lines),
            })
        mode = (
            "responses_with_delta"
            if delta_enabled
            else "responses_structural"
        )
        return ProviderRouteInput(
            tool_retrieval_query=retrieval_query,
            messages=[],
            system_prompt=None,
            previous_response_id=continuation["response_id"],
            continuation_mode=mode,
            responses_continuation_input=items,
        )

    @staticmethod
    def _build_turn_limit_notice(turn_num: int, max_turns: int) -> str | None:
        turns_remaining = max_turns - turn_num
        if turns_remaining <= 5:
            return (
                f"[TURN {turn_num + 1}/{max_turns} - {turns_remaining} turns remaining. "
                "Prioritize finishing critical tasks like canvas/remember before limit!]"
            )
        if turn_num > 0:
            return f"[Turn {turn_num + 1}/{max_turns}]"
        return None

    def _build_openai_provider_continuation(
        self,
        *,
        route: dict[str, Any],
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        duration_ms: int,
    ) -> dict[str, Any] | None:
        response_id = route.get("response_id")
        tool_call_id = route.get("tool_call_id") or route.get("id")
        if not response_id or not tool_call_id:
            return None
        created_at = route.get("response_created_at_iso") or datetime.now(self.timezone).isoformat()
        created_dt = self._safe_iso_to_local_datetime(created_at) or datetime.now(self.timezone)
        expires_at = created_dt + timedelta(days=30)
        safe_until = created_dt + timedelta(days=self._openai_previous_response_max_age_days())
        result_message, result_meta = self._get_context_assembler().build_provider_tool_result_message(
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            tool_call_id=tool_call_id,
            duration_ms=duration_ms,
            max_chars=self._openai_provider_result_max_chars(),
        )
        return {
            "provider": "openai",
            "response_id": response_id,
            "model": route.get("response_model") or getattr(self.router, "model_name", None),
            "model_alias": get_config_value("OPENAI_MODEL", getattr(self.router, "model_name", "")),
            "response_created_at_iso": created_dt.isoformat(),
            "response_expires_at_iso": expires_at.isoformat(),
            "safe_until_iso": safe_until.isoformat(),
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "result_message": result_message,
            "result_meta": result_meta,
        }

    def _format_age_seconds(self, seconds: float | int | None) -> str:
        """Human-friendly age text."""
        if seconds is None:
            return "unknown"
        try:
            s = int(max(0, seconds))
            if s < 60:
                return f"{s}s"
            m, rem = divmod(s, 60)
            if m < 60:
                return f"{m}m {rem}s"
            h, m = divmod(m, 60)
            return f"{h}h {m}m"
        except Exception:
            return "unknown"

    def _format_gap_for_prompt(self, seconds: float | int | None) -> str:
        """Compact human-friendly text for resumed conversation gaps."""
        if seconds is None:
            return "unknown"
        try:
            s = int(max(0, seconds))
            if s < 3600:
                return self._format_age_seconds(s)
            if s < 86400:
                h = round(s / 3600)
                return f"{h}h"
            if s < 86400 * 14:
                d = round(s / 86400)
                return f"{d}d"
            if s < 86400 * 60:
                w = round(s / (86400 * 7))
                return f"{w}w"
            months = round(s / (86400 * 30))
            return f"{months}mo"
        except Exception:
            return "unknown"

    def _extract_primary_lookup_key(self, tool_name: str, arguments: dict | None) -> str | None:
        """Extract primary lookup key from common live-data tools."""
        if not isinstance(arguments, dict):
            return None
        if tool_name == "crypto_price":
            v = arguments.get("coin")
            if v is not None:
                return str(v).strip().lower()
            coins = arguments.get("coins")
            if isinstance(coins, list):
                normalized = [str(item).strip().lower() for item in coins if str(item).strip()]
                return ",".join(normalized) if normalized else None
            if coins is not None:
                return str(coins).strip().lower()
            return None
        if tool_name == "stock_price":
            v = arguments.get("symbol")
            return str(v).strip().upper() if v is not None else None
        if tool_name == "weather":
            v = arguments.get("location")
            return str(v).strip().lower() if v is not None else None
        return None

    def _format_available_tool_contract(self, tool_names: list[str]) -> str:
        """Compact exact tool-name/schema hint for retry prompts."""
        lines: list[str] = []
        for tool_name in tool_names:
            tool = self.registry.get_tool(tool_name)
            if not tool:
                lines.append(f"- {tool_name}")
                continue
            schema = tool.parameters or {}
            properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
            required = set(schema.get("required", [])) if isinstance(schema, dict) else set()
            if properties:
                params = ", ".join(
                    f"{name}{'*' if name in required else ''}"
                    for name in properties.keys()
                )
            else:
                params = "no parameters"
            lines.append(f"- {tool_name}: {params}")
        return "\n".join(lines)

    def _query_explicitly_requests_refresh(self, transcript: str) -> bool:
        """Detect explicit user intent to refresh/recheck live data."""
        text = (transcript or "").lower()
        refresh_terms = [
            "refresh", "recheck", "check again", "update", "updated",
            "latest again", "run again", "try again", "re-run", "rerun"
        ]
        return any(term in text for term in refresh_terms)

    @staticmethod
    def _successful_canvas_write_calls(conversation_context: list) -> list[dict]:
        successful: list[dict] = []
        for ctx in conversation_context:
            if ctx.get("tool") != "canvas":
                continue
            arguments = ctx.get("arguments") if isinstance(ctx.get("arguments"), dict) else {}
            action = str(arguments.get("action") or "create").strip().lower()
            if action not in {"create", "append", "update"}:
                continue
            result = ctx.get("result") if isinstance(ctx.get("result"), dict) else {}
            if result.get("ok"):
                successful.append(ctx)
        return successful

    def _is_canvas_success_cap(
        self,
        arguments: dict,
        conversation_context: list,
        request_kind: str,
    ) -> tuple[bool, str]:
        """
        Export-only, success-aware Canvas write cap.

        Send-to-Canvas exports may perform one successful create/append/update. Failed
        writes and read/list/open calls do not count, so the model can inspect or
        self-correct before the write. Normal Canvas workflows are not capped.
        """
        if request_kind != "canvas_export":
            return False, ""

        action = str(arguments.get("action") or "create").strip().lower()
        if action not in {"create", "append", "update"}:
            return False, ""

        successful = self._successful_canvas_write_calls(conversation_context)
        if successful:
            return True, "canvas page already written for this export request"

        return False, ""

    def _is_fresh_same_target_recall(
        self,
        transcript: str,
        tool_name: str,
        arguments: dict,
        conversation_context: list
    ) -> bool:
        """
        True when same live-data tool+target was already called recently and is still fresh.
        """
        ttl = self._tool_freshness_ttl_seconds(tool_name)
        if ttl is None:
            return False
        if self._query_explicitly_requests_refresh(transcript):
            return False

        current_key = self._extract_primary_lookup_key(tool_name, arguments)
        now = datetime.now(self.timezone)
        for ctx in reversed(conversation_context):
            if ctx.get("tool") != tool_name:
                continue
            prev_result = ctx.get("result", {})
            if not prev_result.get("ok", False):
                continue
            prev_args = ctx.get("arguments", {})
            prev_key = self._extract_primary_lookup_key(tool_name, prev_args)
            # Different lookup target (e.g., BTC then ETH) should be allowed.
            if current_key and prev_key and current_key != prev_key:
                continue
            meta = ctx.get("meta", {}) if isinstance(ctx, dict) else {}
            dt_local = self._safe_iso_to_local_datetime(meta.get("executed_at_iso"))
            if dt_local is None:
                # If no timestamp metadata, err on allowing.
                return False
            age_seconds = int(max(0, (now - dt_local).total_seconds()))
            return age_seconds <= ttl
        return False
    
    def _maybe_collect_feedback(self, result: dict[str, Any], transcript: str) -> dict[str, Any]:
        """
        Optionally collect feedback based on random chance (configured via env).
        This enables the evolution/feedback system for both CLI and WebUI.
        
        Uses FEEDBACK_RANDOM_ENABLED and FEEDBACK_RANDOM_CHANCE from config.
        """
        import random
        from config_loader import get_config_value, get_float
        
        # Check if random feedback is enabled
        random_enabled = get_config_value('FEEDBACK_RANDOM_ENABLED', 'false').lower() == 'true'
        if not random_enabled:
            return result
        
        # Check random chance
        random_chance = get_float('FEEDBACK_RANDOM_CHANCE', 0.0)
        if random.random() >= random_chance:
            return result
        
        # Feedback triggered - collect it
        try:
            from feedback import FeedbackCollector
            
            if sys.stdout.isatty():
                print("🎲 Random feedback collection triggered")
            
            collector = FeedbackCollector(self.mode)
            
            # Get tools used
            tools_used = result.get("tools_used", [])
            if isinstance(tools_used, str):
                tools_used = [tools_used]
            
            num_tools = len(self.registry.list_tools())
            
            # Get system prompt from router
            system_prompt = self.router.system_prompt if hasattr(self.router, 'system_prompt') else None
            
            # @TOOL_CONFIG: feedback relevant tools — keyword-to-tool mapping for feedback context
            tool_descriptions = {}
            relevant_tools = set(tools_used)
            query_lower = transcript.lower()
            if "time" in query_lower:
                relevant_tools.add("get_time")
            if "weather" in query_lower:
                relevant_tools.add("weather")
            if "bitcoin" in query_lower or "crypto" in query_lower or "price" in query_lower:
                relevant_tools.add("crypto_price")
            if "memory" in query_lower or "remember" in query_lower:
                relevant_tools.update(["semantic_recall", "search_memory", "remember"])
            
            for tool_name in relevant_tools:
                try:
                    tool = self.registry.get_tool(tool_name)
                    if tool:
                        tool_descriptions[tool_name] = tool.description
                except:
                    pass
            
            # Build config context
            response_style = get_config_value('JARVIS_RESPONSE_STYLE', 'auto')
            qa_word_limit = int(get_config_value('JARVIS_QA_WORD_LIMIT', str(DEFAULT_JARVIS_QA_WORD_LIMIT)))
            multi_turn_word_limit = int(get_config_value('JARVIS_MULTI_TURN_WORD_LIMIT', str(DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT)))
            style_explanations = {
                'casual': f'Short voice-friendly output. Tool confirmations stay at 35 words max, Q&A is capped at {qa_word_limit}, multi-turn summaries at {multi_turn_word_limit}.',
                'auto': f'Smart mode. Search tools get condensed (no URLs), complex tools keep full details. Q&A cap is {qa_word_limit}, multi-turn cap is {multi_turn_word_limit}.',
                'detailed': 'FULL LLM response preserved. URLs ARE INCLUDED. Verbose output is EXPECTED and CORRECT.'
            }
            style_explanation = style_explanations.get(response_style, 'Unknown style')
            
            if self.auto_context_enabled:
                interface_line = f"Interface: cli/voice (auto-context enabled, last {self.auto_context_window} conversations within {self.auto_context_minutes} minutes)"
            else:
                interface_line = "Interface: cli/voice (no prior conversation context)"
            
            config_context = f"""
{interface_line}
Auto-Context: {'Enabled' if self.auto_context_enabled else 'Disabled'} (window={self.auto_context_window}, minutes={self.auto_context_minutes})
Response Style: {response_style}
  → Style Behavior: {style_explanation}
Tools Available: {num_tools}
Mode: {self.mode}
"""
            
            feedback = collector.collect(
                query=transcript,
                result=result,
                tools_used=tools_used,
                num_tools=num_tools,
                system_prompt=system_prompt,
                tool_descriptions=tool_descriptions,
                intelligence_insights=result.get("intelligence_context", ""),
                config_context=config_context,
                session_id=self.session_id
            )
            
            # Add feedback to result
            result["feedback"] = feedback
            
            # Update experience from feedback if applicable
            rating = feedback.get('rating')
            experience_id = result.get('experience_id', -1)
            
            if rating is not None and experience_id > 0:
                try:
                    from intelligence_hooks import update_experience_from_feedback
                    update_experience_from_feedback(
                        experience_id=experience_id,
                        feedback_rating=rating,
                        feedback_summary=feedback.get('summary'),
                        feedback_details={
                            'positive': feedback.get('positive', ''),
                            'issues': feedback.get('issues', []),
                            'suggestions': feedback.get('suggestions', []),
                            'tool_ratings': feedback.get('tool_ratings', {}),
                            'analysis': feedback.get('analysis', ''),
                        }
                    )
                except Exception as e:
                    if sys.stdout.isatty():
                        print(f"⚠️ Failed to update experience from feedback: {e}")
            
        except Exception as e:
            if sys.stdout.isatty():
                print(f"⚠️ Feedback collection failed: {e}")
        
        return result
    
    def process(self, transcript: str, retry_count: int = 0, error_context: str = None,
                conversation_history: list = None, excluded_tools: list = None,
                tool_overrides: dict[str, dict] | None = None,
                vision_pre_analyzed: bool = False,
                request_kind: str = '',
                tool_rag_limit: int | None = None,
                _retry_state: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Process user transcript and execute tools or respond.
        Supports multi-turn tool execution until task is complete.
        
        Args:
            transcript: User's spoken input (from STT)
            retry_count: Current retry attempt (for error recovery)
            error_context: Previous error information (for retry)
            conversation_history: Optional list of previous messages for context
                                  [{role: 'user'|'assistant', content: str}, ...]
                                  If provided, used instead of auto_context from memory_db.
            excluded_tools: Optional list of tool names to exclude from this request.
            tool_overrides: Optional dict of {tool_name: {param: value}} to force-override
                           LLM-chosen arguments before tool execution. Used by web UI to
                           enforce user-selected parameters (e.g. aspect_ratio, duration)
                           that the LLM may otherwise ignore.
                           Used by web app to block tools that don't make sense in web context.
            vision_pre_analyzed: When True (web upload analyze flow), skip provider-native
                           server-side tools for this request because vision text is already
                           injected. No-op for providers without native tools (Ollama, etc.).
            request_kind: Optional recognized request type. The Web UI uses
                           ``canvas_export`` for its Send-to-Canvas action.
            tool_rag_limit: Optional one-request cap for final Tool RAG schemas.
            _retry_state: Internal only. Carries in-flight orchestrator state across
                         recursive tool-failure retries so UI events and accumulated
                         results stay consistent within one user request.
            
        Returns:
            dict: Response for TTS
            {
                "speech": "Text to speak",
                "ok": bool,
                "data": {...} (optional),
                "error": str (optional)
            }
        """
        # SECURITY: Sanitize user input
        try:
            from security_utils import sanitize_user_input
            transcript, security_info = sanitize_user_input(transcript)
            
            # Log security events (don't block, but audit)
            if security_info.get("injection_detected"):
                # Could add to a security audit log here TODO: add a security audit log and block risky inputs?
                pass
        except ImportError:
            # security_utils not available, continue without sanitization
            pass
        
        # Store tool overrides for this request
        self._tool_overrides = tool_overrides or {}
        self.executor.set_excluded_tools(excluded_tools or [])
        
        # Reset status updater for new task
        self.status_updater.reset()
        
        # Check for explicit workflow commands (e.g., /research, /note, /health)
        # These bypass normal LLM routing and execute a predefined pipeline
        workflow_result = self._try_workflow(transcript)
        if workflow_result:
            return workflow_result
        
        # Auto-inject recent conversation context
        auto_context_source = "none"
        self._previous_experience_id_for_correction = None
        if conversation_history:
            self._previous_experience_id_for_correction = self._previous_experience_id_from_history(conversation_history)
            # Use provided conversation history (from web app)
            enhanced_transcript = self._format_conversation_context(transcript, conversation_history)
            auto_context_source = "provided_history"
        elif self.auto_context_enabled:
            # Fall back to memory_db auto_context (terminal/TUI mode)
            enhanced_transcript = self._build_conversation_context(transcript)
            auto_context_source = "auto_context"
            self._previous_experience_id_for_correction = (
                self._resolve_previous_experience_id_for_auto_context()
                or self._last_experience_id
            )
        else:
            enhanced_transcript = transcript
            self._previous_experience_id_for_correction = self._last_experience_id
        
        # Debug: Show what's being sent to LLM
        if os.environ.get('JARVIS_DEBUG') and enhanced_transcript != transcript:
            print("\n" + "="*80, file=sys.stderr)
            print("DEBUG: Enhanced Transcript Being Sent to LLM:", file=sys.stderr)
            print("="*80, file=sys.stderr)
            print(enhanced_transcript, file=sys.stderr)
            print("="*80 + "\n", file=sys.stderr)
        
        # Pre-fetch available tool names for insight filtering
        # DB enabled=1 minus Web UI blocked tools minus profile overrides (false)
        try:
            from memory_db import get_memory_db
            from tool_profiles import load_active_profile_overrides

            db = get_memory_db()
            names = db.get_enabled_tool_names() if hasattr(db, 'get_enabled_tool_names') else []
            excluded = set(excluded_tools or [])
            for tname, en in load_active_profile_overrides().items():
                if en is False:
                    excluded.add(tname)
            available_tool_names = [n for n in names if n not in excluded]
        except Exception:
            available_tool_names = []  # Fallback: no filtering
        
        # Auto-inject relevant memories (semantic search + recency weighting)
        # Works for CLI, WebUI, wake word - all go through orchestrator.process()
        memory_bundle = self._get_relevant_memories_bundle(transcript)
        memory_context = memory_bundle.get("context", "")
        memory_meta = memory_bundle.get("meta", {})
        if memory_context:
            enhanced_transcript = f"{memory_context}\n\n{enhanced_transcript}"
        
        # Inject learned insights from self-learning intelligence
        learning_context, applied_insights = self._get_learning_insights(transcript, available_tool_names)
        if learning_context:
            enhanced_transcript = f"{learning_context}\n\n{enhanced_transcript}"
        combined_intelligence_context = "\n\n".join(
            block.strip()
            for block in [learning_context, memory_context]
            if block and block.strip()
        )
        client_search_hint_active = _has_client_side_search_tool_hint(enhanced_transcript)
        if _retry_state and "vision_pre_analyzed" in _retry_state:
            vision_pre_analyzed_active = bool(_retry_state.get("vision_pre_analyzed"))
        else:
            vision_pre_analyzed_active = bool(
                vision_pre_analyzed or _request_has_web_vision_analysis(transcript)
            )
        routing_provenance = {
            "router_prompt": {
                "version": getattr(self.router, "system_prompt_version", None),
            },
            "auto_context": {
                "enabled": bool(self.auto_context_enabled),
                "source": auto_context_source,
                "applied": auto_context_source != "none" and enhanced_transcript != transcript,
            },
            "memory_injection": memory_meta,
            "learning_insights": {
                "injected": bool(learning_context),
                "insight_count": len(applied_insights),
                "insight_descriptions": [
                    str(insight.get("description", ""))[:160]
                    for insight in applied_insights[:5]
                ],
            },
        }
        if vision_pre_analyzed_active and self._provider_server_side_tools_available():
            routing_provenance["vision_pre_analyzed_disable_native_tools"] = True
        
        # Multi-turn context tracking
        max_turns = get_int('MAX_TOOL_TURNS', 15)  # Configurable, default 15 for deep research
        if (
            getattr(self.router, "provider_type", "") == "openai"
            and self._openai_responses_tracking_enabled()
        ):
            from openai_responses_adapter import openai_env_bool as _oar_ss_bool

            native_search_request_budget = self._config_int(
                "OPENAI_RESPONSES_SERVER_SIDE_MAX_TOOL_CALLS", 0
            )
            if not _oar_ss_bool("OPENAI_RESPONSES_SERVER_SIDE_TOOLS", False):
                native_search_request_budget = 0
        else:
            native_search_request_budget = get_int(
                'XAI_SERVER_SIDE_MAX_SEARCHES_PER_REQUEST',
                get_int('XAI_SERVER_SIDE_MAX_TOOL_TURNS', 0),
            )
        retry_state = _retry_state or {}
        conversation_context = retry_state.get("conversation_context") or []
        tools_used = retry_state.get("tools_used") or []
        accumulated_data = retry_state.get("accumulated_data") or {}
        tool_trace = retry_state.get("tool_trace") or []
        seen_successful_tool_calls = retry_state.get("seen_successful_tool_calls") or set()
        blocked_duplicate_calls = retry_state.get("blocked_duplicate_calls") or {}
        tool_call_counts = retry_state.get("tool_call_counts") or {}
        duplicate_recovery_attempts = retry_state.get("duplicate_recovery_attempts", 0)
        max_duplicate_recovery_attempts = retry_state.get("max_duplicate_recovery_attempts", 2)
        xai_store_messages_enabled = (
            getattr(self.router, "provider_type", "") == "xai"
            and str(get_config_value("XAI_STORE_MESSAGES", "false")).strip().lower()
            in {"1", "true", "yes", "on"}
        )
        xai_native_continuation_enabled = self._xai_native_continuation_allowed()
        xai_previous_response_id = (
            retry_state.get("xai_previous_response_id")
            if xai_store_messages_enabled
            else None
        )
        xai_provider_continuation = (
            retry_state.get("xai_provider_continuation")
            if xai_store_messages_enabled
            else None
        )
        xai_text_fallback_retry_used = bool(retry_state.get("xai_text_fallback_retry_used"))
        openai_responses_tracking_enabled = self._openai_responses_tracking_enabled()
        openai_native_continuation_enabled = self._openai_native_continuation_allowed()
        openai_previous_response_id = (
            retry_state.get("openai_previous_response_id")
            if openai_responses_tracking_enabled
            else None
        )
        openai_provider_continuation = (
            retry_state.get("openai_provider_continuation")
            if openai_responses_tracking_enabled
            else None
        )
        openai_text_fallback_retry_used = bool(retry_state.get("openai_text_fallback_retry_used"))

        # If retrying, augment transcript with error context
        if error_context and retry_count > 0:
            enhanced_transcript = f"{enhanced_transcript}\n\n===PREVIOUS ATTEMPT FAILED WITH ERROR===: {error_context}\nPlease try again with corrected parameters or check logs if needed."
        
        # Track usage info across all turns
        total_usage = retry_state.get("total_usage") or {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            # Calls and peak logical context are per user turn. Unlike total_tokens,
            # peak_context_tokens does not double-count repeated prompt history.
            "model_calls": 0,
            "peak_context_tokens": 0,
            "cost_usd": 0.0,
            # has_unknown_cost is set when any turn used subscription/compute-metered
            # billing (e.g. Ollama Cloud) where per-token dollar cost is unknown.
            "has_unknown_cost": False,
            "cost_known": True,
            "billing_mode": None,
            # input_estimated is set when any turn's input tokens were approximated
            # because the provider (e.g. Ollama Cloud) omitted prompt_eval_count.
            "input_estimated": False,
            "cache_creation_tokens": 0,
            "cache_creation_5m_tokens": 0,
            "cache_creation_1h_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_cost_usd": 0.0,
            "cache_read_cost_usd": 0.0,
            "cache_cost_usd": 0.0,
            "cache_savings_usd": 0.0,
            "server_side_tools": {}  # Track xAI native search usage
        }
        # Web conversation history already persists usage, so storing the
        # compact version here preserves prompt provenance without copying the
        # much larger routing provenance payload onto every message.
        self._attach_router_prompt_usage(total_usage)
        
        # Track thinking from first turn (for display)
        first_thinking = retry_state.get("first_thinking")
        
        # Track available tools from first routing (for intelligence reflection)
        available_tools = retry_state.get("available_tools") or []
        
        start_turn_num = int(retry_state.get("start_turn_num", 0) or 0)
        start_turn_num = max(0, min(start_turn_num, max_turns))

        # Multi-turn loop
        for turn_num in range(start_turn_num, max_turns):
            # Check for cancellation at start of each turn
            if self._is_cancelled():
                self._emit_progress('routing', message='Processing cancelled')
                return {
                    "ok": True,
                    "speech": f"Processing stopped after {turn_num} turn(s). Results so far:\n\n" + 
                               (conversation_context[-1].get('summary', 'No results yet.') if conversation_context else 'No results yet.'),
                    "tools_used": tools_used,
                    "data": accumulated_data,
                    "usage": total_usage if any(total_usage.values()) else None,
                    "thinking": first_thinking,
                    "cancelled": True
                }
            
            # Build context for this turn
            if turn_num == 0 and not conversation_context:
                # First turn in a fresh request: use original transcript
                turn_input = enhanced_transcript
            else:
                # Subsequent turns and retries: provide context from previous tools
                turn_input = self._build_turn_context(enhanced_transcript, conversation_context)

            if blocked_duplicate_calls:
                recent_blocks = list(blocked_duplicate_calls.values())[-3:]
                guard_lines = [
                    "DUPLICATE TOOL GUARD:",
                    "- One or more attempted tool calls were blocked in this request.",
                    "- The exact blocked call signatures below are unavailable for the rest of this in-flight request.",
                    "- You must either answer directly from the existing results or choose a clearly different tool call.",
                    "- Repeating a blocked call again will end the task with the duplicate safeguard fallback.",
                ]
                for blocked in recent_blocks:
                    guard_lines.append(
                        f"- Blocked exact call: tool={blocked['tool']}, reason={blocked['reason']}, args={blocked['args_json']}"
                    )
                turn_input = f"{turn_input}\n\n" + "\n".join(guard_lines)
            
            # Inject turn limit awareness (helps LLM prioritize finishing critical tasks)
            turn_notice = self._build_turn_limit_notice(turn_num, max_turns)
            if turn_notice:
                turn_input = f"{turn_notice}\n\n{turn_input}"
            
            # Route using LLM
            if os.environ.get('JARVIS_DEBUG'):
                print(f"DEBUG: About to route turn {turn_num}", file=sys.stderr)
            native_search_used = _server_side_tool_call_count(total_usage.get("server_side_tools"))
            native_search_remaining = (
                native_search_request_budget - native_search_used
                if native_search_request_budget > 0
                else None
            )
            disable_server_side_tools = (
                client_search_hint_active
                or (native_search_remaining is not None and native_search_remaining <= 0)
                or (
                    vision_pre_analyzed_active
                    and self._provider_server_side_tools_available()
                )
            )
            if disable_server_side_tools:
                if (
                    vision_pre_analyzed_active
                    and self._provider_server_side_tools_available()
                    and not client_search_hint_active
                    and not (
                        native_search_remaining is not None
                        and native_search_remaining <= 0
                    )
                ):
                    reason = (
                        "Web upload vision analysis is already attached to this request."
                    )
                elif client_search_hint_active:
                    reason = "A client-side search tool was selected in the UI."
                else:
                    reason = "The provider-native search budget is exhausted."
                turn_input = (
                    "[NATIVE SEARCH DISABLED]\n"
                    f"{reason} Use results already gathered, choose a client-side search tool, "
                    "or answer directly.\n\n"
                    f"{turn_input}"
                )
            route_payload: str | ProviderRouteInput = turn_input
            route_previous_response_id = None
            continuation_fallback_reason = None
            used_openai_structural = False
            if (
                openai_native_continuation_enabled
                and turn_num > 0
                and not blocked_duplicate_calls
                and not disable_server_side_tools
            ):
                oai_reason = self._openai_continuation_fallback_reason(openai_provider_continuation)
                if oai_reason is None and openai_provider_continuation:
                    route_payload = self._build_openai_responses_route_input(
                        retrieval_query=enhanced_transcript,
                        continuation=openai_provider_continuation,
                        turn_notice=turn_notice,
                    )
                    used_openai_structural = True
                    route_previous_response_id = openai_provider_continuation.get("response_id")
                elif oai_reason and openai_native_continuation_enabled:
                    routing_provenance["openai_continuation_fallback_reason"] = oai_reason
            elif (
                blocked_duplicate_calls
                and openai_native_continuation_enabled
            ):
                routing_provenance["openai_continuation_fallback_reason"] = "duplicate_guard_active"
            elif disable_server_side_tools and openai_native_continuation_enabled:
                routing_provenance["openai_continuation_fallback_reason"] = "server_side_tools_disabled"

            if (
                not used_openai_structural
                and xai_native_continuation_enabled
                and turn_num > 0
                and not blocked_duplicate_calls
                and not disable_server_side_tools
            ):
                continuation_fallback_reason = self._xai_continuation_fallback_reason(xai_provider_continuation)
                if continuation_fallback_reason is None and xai_provider_continuation:
                    route_payload = self._build_xai_structural_route_input(
                        retrieval_query=enhanced_transcript,
                        continuation=xai_provider_continuation,
                        turn_notice=turn_notice,
                    )
                    route_previous_response_id = xai_provider_continuation.get("response_id")
                elif continuation_fallback_reason and xai_native_continuation_enabled:
                    # Keep this diagnostic in logs; the provider still receives the normal text fallback.
                    routing_provenance["xai_continuation_fallback_reason"] = continuation_fallback_reason
            elif blocked_duplicate_calls and xai_native_continuation_enabled:
                routing_provenance["xai_continuation_fallback_reason"] = "duplicate_guard_active"
            elif disable_server_side_tools and xai_native_continuation_enabled:
                routing_provenance["xai_continuation_fallback_reason"] = "server_side_tools_disabled"
            route = self.router.route(
                route_payload,
                excluded_tools=excluded_tools,
                typo_hint_source=transcript,
                disable_server_side_tools=disable_server_side_tools,
                routing_provenance=routing_provenance,
                server_side_max_tool_turns=(
                    native_search_remaining
                    if native_search_remaining is not None and native_search_remaining > 0
                    else None
                ),
                previous_response_id=route_previous_response_id,
                tool_rag_limit=tool_rag_limit,
            )
            if (
                route.get("intent") == "error"
                and isinstance(route_payload, ProviderRouteInput)
                and getattr(route_payload, "responses_continuation_input", None)
                and route.get("openai_continuation_error")
                and route_previous_response_id
                and not openai_text_fallback_retry_used
            ):
                openai_text_fallback_retry_used = True
                openai_previous_response_id = None
                openai_provider_continuation = None
                routing_provenance["openai_continuation_fallback_reason"] = (
                    "previous_response_error"
                    if "previous_response" in str(route.get("provider_error_raw", "")).lower()
                    else "openai_structural_error"
                )
                route = self.router.route(
                    turn_input,
                    excluded_tools=excluded_tools,
                    typo_hint_source=transcript,
                    disable_server_side_tools=disable_server_side_tools,
                    routing_provenance=routing_provenance,
                    server_side_max_tool_turns=(
                        native_search_remaining
                        if native_search_remaining is not None and native_search_remaining > 0
                        else None
                    ),
                    previous_response_id=None,
                    tool_rag_limit=tool_rag_limit,
                )
            elif (
                route.get("intent") == "error"
                and route_previous_response_id
                and not xai_text_fallback_retry_used
                and route.get("xai_continuation_error")
            ):
                xai_text_fallback_retry_used = True
                xai_previous_response_id = None
                xai_provider_continuation = None
                routing_provenance["xai_continuation_fallback_reason"] = (
                    "previous_response_not_found"
                    if "previous_response" in str(route.get("provider_error_raw", "")).lower()
                    else "stored_continuation_error"
                )
                route = self.router.route(
                    turn_input,
                    excluded_tools=excluded_tools,
                    typo_hint_source=transcript,
                    disable_server_side_tools=disable_server_side_tools,
                    routing_provenance=routing_provenance,
                    server_side_max_tool_turns=(
                        native_search_remaining
                        if native_search_remaining is not None and native_search_remaining > 0
                        else None
                    ),
                    previous_response_id=None,
                    tool_rag_limit=tool_rag_limit,
                )
            if os.environ.get('JARVIS_DEBUG'):
                print(f"DEBUG: Routing complete, intent={route.get('intent')}", file=sys.stderr)
            
            # Accumulate usage info if available
            if route.get("usage_info"):
                usage = route["usage_info"]
                call_tokens = usage.get("total_tokens")
                if not isinstance(call_tokens, (int, float)):
                    call_tokens = (
                        (usage.get("input_tokens") or 0)
                        + (usage.get("output_tokens") or 0)
                    )
                total_usage["model_calls"] = total_usage.get("model_calls", 0) + 1
                total_usage["peak_context_tokens"] = max(
                    total_usage.get("peak_context_tokens", 0), call_tokens
                )
                if usage.get("input_tokens"):
                    total_usage["input_tokens"] += usage["input_tokens"]
                if usage.get("output_tokens"):
                    total_usage["output_tokens"] += usage["output_tokens"]
                if usage.get("total_tokens"):
                    total_usage["total_tokens"] += usage["total_tokens"]
                # Sum only numeric known costs; flag unknown/subscription usage
                # (e.g. Ollama Cloud) instead of coercing None to $0.
                if isinstance(usage.get("cost_usd"), (int, float)):
                    total_usage["cost_usd"] += usage["cost_usd"]
                if usage.get("billing_mode"):
                    total_usage["billing_mode"] = usage["billing_mode"]
                if usage.get("cost_known") is False or usage.get("billing_mode") in {
                    "ollama_cloud_subscription",
                    "xai_oauth_subscription",
                }:
                    total_usage["has_unknown_cost"] = True
                    total_usage["cost_known"] = False
                if usage.get("input_estimated"):
                    total_usage["input_estimated"] = True
                # Accumulate cache metrics
                if usage.get("cache_creation_tokens"):
                    total_usage["cache_creation_tokens"] += usage["cache_creation_tokens"]
                if usage.get("cache_creation_5m_tokens"):
                    total_usage["cache_creation_5m_tokens"] += usage["cache_creation_5m_tokens"]
                if usage.get("cache_creation_1h_tokens"):
                    total_usage["cache_creation_1h_tokens"] += usage["cache_creation_1h_tokens"]
                if usage.get("cache_read_tokens"):
                    total_usage["cache_read_tokens"] += usage["cache_read_tokens"]
                if usage.get("cache_write_cost_usd"):
                    total_usage["cache_write_cost_usd"] += usage["cache_write_cost_usd"]
                if usage.get("cache_read_cost_usd"):
                    total_usage["cache_read_cost_usd"] += usage["cache_read_cost_usd"]
                if usage.get("cache_cost_usd"):
                    total_usage["cache_cost_usd"] += usage["cache_cost_usd"]
                if usage.get("cache_savings_usd"):
                    total_usage["cache_savings_usd"] += usage["cache_savings_usd"]
                # Accumulate xAI server-side tools usage
                if usage.get("server_side_tools"):
                    for tool_name, count in usage["server_side_tools"].items():
                        total_usage["server_side_tools"][tool_name] = total_usage["server_side_tools"].get(tool_name, 0) + count

                if not usage.get("total_tokens"):
                    total_usage["total_tokens"] = (
                        total_usage["input_tokens"]
                        + total_usage["output_tokens"]
                        + total_usage["cache_creation_tokens"]
                        + total_usage["cache_read_tokens"]
                    )
            
            # Capture thinking from first turn (for display)
            if turn_num == 0 and route.get("thinking") and not first_thinking:
                first_thinking = route["thinking"]
            
            # Capture available tools from first turn (for intelligence reflection)
            if turn_num == 0 and route.get("available_tools"):
                available_tools = route["available_tools"]
            
            # Handle tool execution
            if route["intent"] == "tool":
                tool_name = route["tool_name"]
                arguments = route["arguments"]
                route_response_id = (
                    route.get("response_id")
                    if (
                        xai_store_messages_enabled
                        or openai_responses_tracking_enabled
                    )
                    else None
                )
                
                # Apply forced overrides from web UI (e.g. aspect_ratio, duration)
                # The LLM generates the creative prompt, but technical params are
                # enforced from the user's explicit modal selections
                if self._tool_overrides and tool_name in self._tool_overrides:
                    overrides = self._tool_overrides[tool_name]
                    if sys.stdout.isatty():
                        print(f"📌 Applying forced overrides for {tool_name}: {overrides}")
                    arguments.update(overrides)
                
                # Emit routing progress
                self._emit_progress('routing',
                    message=f"Using {tool_name}..." if turn_num == 0 else f"Turn {turn_num + 1}: using {tool_name}..."
                )
                
                # Detect duplicate tool calls (same tool, similar/empty args)
                current_call = (tool_name, json.dumps(arguments, sort_keys=True))
                is_exact_duplicate = current_call in seen_successful_tool_calls
                is_fresh_same_target_recall = self._is_fresh_same_target_recall(
                    transcript, tool_name, arguments, conversation_context
                )
                is_canvas_capped, canvas_cap_reason = (
                    self._is_canvas_success_cap(arguments, conversation_context, request_kind)
                    if tool_name == "canvas"
                    else (False, "")
                )

                # @TOOL_CONFIG: single-call cap — expensive tools limited to
                # one attempt per request (including failed attempts).
                is_over_cap = (
                    tool_name in SINGLE_CALL_TOOLS
                    and tool_call_counts.get(tool_name, 0) >= 1
                )

                if is_exact_duplicate or is_over_cap or is_fresh_same_target_recall or is_canvas_capped:
                    if is_exact_duplicate:
                        reason = "exact duplicate"
                    elif is_canvas_capped:
                        reason = canvas_cap_reason
                    elif is_over_cap:
                        reason = f"{tool_name} already called (max 1)"
                    else:
                        reason = f"{tool_name} already has fresh result for same target"
                    if sys.stdout.isatty():
                        print(f"⚠️  Duplicate/capped tool call detected: {tool_name} ({reason})")
                        print(f"   Blocking exact call and giving the model a recovery turn")

                    blocked_duplicate_calls[current_call] = {
                        "tool": tool_name,
                        "reason": reason,
                        "args_json": json.dumps(arguments, sort_keys=True),
                    }
                    duplicate_recovery_attempts += 1

                    executed_at = datetime.now(self.timezone)
                    conversation_context.append({
                        "tool": "duplicate_guard",
                        "arguments": {
                            "blocked_tool": tool_name,
                            "blocked_arguments": arguments,
                            "reason": reason,
                        },
                        "result": {
                            "ok": False,
                            "speech": f"Blocked duplicate tool call for {tool_name}.",
                            "error": (
                                f"Duplicate guard blocked tool '{tool_name}' ({reason}). "
                                "Answer directly from existing results or choose a different tool."
                            ),
                            "data": {
                                "blocked_tool": tool_name,
                                "blocked_arguments": arguments,
                                "reason": reason,
                            }
                        },
                        "speech": (
                            f"Duplicate guard blocked tool '{tool_name}' ({reason}). "
                            "Answer directly from existing results or choose a different tool."
                        ),
                        "meta": {
                            "executed_at_iso": executed_at.isoformat(),
                            "executed_at_local": executed_at.strftime("%Y-%m-%d %H:%M:%S %Z"),
                            "freshness": "duplicate_guard",
                            "ttl_seconds": None,
                            "source": "duplicate_guard",
                            "authoritative_live": False
                        }
                    })

                    if duplicate_recovery_attempts <= max_duplicate_recovery_attempts and (turn_num + 1) < max_turns:
                        self._emit_progress(
                            'routing',
                            message=(
                                f"Blocked repeated {tool_name} call. "
                                "Trying to recover with the results already gathered..."
                            )
                        )
                        continue

                    # Generate intelligent summary using accumulated data (not just tool list!)
                    # This ensures the user gets actual research results, not just "I used tools"
                    final_speech = self._synthesize_duplicate_prevented_response(
                        transcript, tools_used, accumulated_data, conversation_context
                    )

                    completed_any_tool = bool(tools_used)

                    self._log_conversation(
                        transcript,
                        final_speech,
                        tools_used,
                        success=completed_any_tool,
                    )

                    # Mark status updates complete
                    self.status_updater.mark_complete()

                    return {
                        "speech": final_speech,
                        "ok": completed_any_tool,
                        "tools_used": tools_used,
                        "data": accumulated_data,
                        "duplicate_prevented": True,
                        **(
                            {}
                            if completed_any_tool
                            else {"error": "No tool completed before duplicate prevention stopped the request."}
                        ),
                        "usage": total_usage if self._has_usage_data(total_usage) else None,
                        "server_side_tools": total_usage.get("server_side_tools", {})
                    }
                
                # Only print if in interactive mode
                if sys.stdout.isatty():
                    turn_marker = f" (turn {turn_num + 1})" if turn_num > 0 else ""
                    print(f"🔧 Executing tool: {tool_name}{turn_marker}")
                    print(f"📝 Arguments: {json.dumps(arguments, indent=2)}")
                
                # Status update before tool execution
                self.status_updater.set_turn(turn_num + 1)
                previous_status_outcome = None
                if conversation_context:
                    previous_item = conversation_context[-1]
                    previous_result = previous_item.get("result")
                    previous_result_speech = (
                        previous_result.get("speech")
                        if isinstance(previous_result, dict)
                        else None
                    )
                    previous_status_outcome = (
                        previous_item.get("speech")
                        or previous_result_speech
                    )
                status_context = {
                    'phase': 'starting',
                    'arguments': arguments,
                    'previous_outcome': previous_status_outcome,
                }
                
                # @TOOL_CONFIG: status update categories — route tools to UI status messages
                if tool_name == 'opencode':
                    # OpenCode is long-running - start background updates
                    self.status_updater.update(
                        category='building',
                        tool_name=tool_name,
                        context=status_context,
                    )
                    # Background OpenCode updates fall back to initial context + static/LLM phrases, not live session logs TODO: in /docs/FUTURE_ENHANCEMENTS.md
                    self.status_updater.start_background_updates(tool_name=tool_name, category='building')
                elif 'search' in tool_name or 'brave' in tool_name:
                    self.status_updater.update(category='searching', tool_name=tool_name, context=status_context)
                elif 'fetch' in tool_name or 'playwright' in tool_name:
                    self.status_updater.update(category='fetching', tool_name=tool_name, context=status_context)
                elif tool_name == 'weather':
                    self.status_updater.update(category='fetching', tool_name=tool_name, context=status_context)
                elif 'memory' in tool_name or 'recall' in tool_name:
                    # Memory tools are fast, skip status
                    pass
                elif turn_num >= 2:
                    # Multi-turn progress
                    self.status_updater.update(category='multi_turn', tool_name=tool_name, context=status_context)
                else:
                    # Default: acknowledge any other tool at first turn
                    if turn_num == 0:
                        self.status_updater.update(category='task_start', tool_name=tool_name, context=status_context)
                
                # Check for cancellation before executing tool
                if self._is_cancelled():
                    self._emit_progress('routing', message='Processing cancelled')
                    return {
                        "ok": True,
                        "speech": f"Stopped before {tool_name}. Results so far:\n\n" + 
                                   (conversation_context[-1].get('summary', 'No results yet.') if conversation_context else 'No results yet.'),
                        "tools_used": tools_used,
                        "data": accumulated_data,
                        "usage": total_usage if any(total_usage.values()) else None,
                        "thinking": first_thinking,
                        "cancelled": True
                    }
                
                # Track this tool call for unique IDs in progress events
                call_index = tool_call_counts.get(tool_name, 0)
                tool_call_counts[tool_name] = call_index + 1
                
                # Emit progress: tool starting (with call_index for duplicate tracking)
                self._emit_progress('tool_start', 
                    tool=tool_name, 
                    turn=turn_num + 1, 
                    max_turns=max_turns,
                    args=arguments,
                    call_index=call_index
                )
                
                # Execute the tool with timing
                tool_start_time = time.time()
                result = self.executor.execute(tool_name, arguments)
                tool_duration_ms = int((time.time() - tool_start_time) * 1000)
                tool_trace.append({
                    "tool": tool_name,
                    "ok": bool(result.get("ok")) if isinstance(result, dict) else False,
                    "arguments": self._sanitize_tool_trace_value(arguments),
                    "duration_ms": tool_duration_ms,
                    "error": str(result.get("error", ""))[:500] if isinstance(result, dict) and result.get("error") else None,
                    "speech": str(result.get("speech", ""))[:500] if isinstance(result, dict) else "",
                })
                
                # Stop background updates after tool completes
                if tool_name == 'opencode':
                    self.status_updater.stop_background_updates()
                
                if result["ok"]:
                    # Emit progress: tool completed successfully
                    self._emit_progress('tool_complete',
                        tool=tool_name,
                        duration_ms=tool_duration_ms,
                        success=True,
                        call_index=call_index
                    )
                    
                    # Success - add to context and continue
                    if sys.stdout.isatty():
                        print(f"✅ Tool succeeded ({tool_duration_ms}ms)")
                        print(f"📊 Tool result: {json.dumps(result.get('data', {}), indent=2)[:200]}...")
                    
                    # Track tool execution
                    tools_used.append(tool_name)
                    seen_successful_tool_calls.add(current_call)
                    
                    # Aggregate data - handle multiple calls to same tool
                    tool_data = result.get("data", {})
                    if tool_name in accumulated_data:
                        # Convert to list if not already, then append
                        existing = accumulated_data[tool_name]
                        if not isinstance(existing, list):
                            accumulated_data[tool_name] = [existing]
                        accumulated_data[tool_name].append(tool_data)
                    else:
                        accumulated_data[tool_name] = tool_data
                    
                    # Add to conversation context for next turn
                    # Store full result (including speech and data) so LLM can see all information
                    result_data = result.get("data", {}) if isinstance(result, dict) else {}
                    source_hint = "tool"
                    if isinstance(result_data, dict):
                        source_hint = (
                            result_data.get("source")
                            or result_data.get("provider")
                            or result_data.get("daily_forecast_provider")
                            or "tool"
                        )
                    executed_at = datetime.now(self.timezone)
                    ttl_seconds = self._tool_freshness_ttl_seconds(tool_name)
                    tool_meta = {
                        "executed_at_iso": executed_at.isoformat(),
                        "executed_at_local": executed_at.strftime("%Y-%m-%d %H:%M:%S %Z"),
                        "freshness": "live_tool_call",
                        "ttl_seconds": ttl_seconds,
                        "source": source_hint,
                        "authoritative_live": ttl_seconds is not None
                    }
                    if route_response_id:
                        if xai_store_messages_enabled:
                            tool_meta["xai_response_id"] = route_response_id
                            xai_previous_response_id = route_response_id
                        if openai_responses_tracking_enabled:
                            tool_meta["openai_response_id"] = route_response_id
                            openai_previous_response_id = route_response_id
                    if route.get("tool_call_id"):
                        if xai_store_messages_enabled:
                            tool_meta["xai_tool_call_id"] = route["tool_call_id"]
                        if openai_responses_tracking_enabled:
                            tool_meta["openai_tool_call_id"] = route["tool_call_id"]
                    context_item = {
                        "tool": tool_name,
                        "arguments": arguments,
                        "result": result,  # Store full result, not just data
                        "speech": result.get("speech", ""),
                        "meta": tool_meta
                    }
                    provider_continuation = None
                    if xai_store_messages_enabled and route_response_id:
                        provider_continuation = self._build_xai_provider_continuation(
                            route=route,
                            tool_name=tool_name,
                            arguments=arguments,
                            result=result,
                            duration_ms=tool_duration_ms,
                        )
                        if provider_continuation:
                            context_item["provider_continuation"] = provider_continuation
                            xai_provider_continuation = provider_continuation
                            xai_previous_response_id = provider_continuation["response_id"]
                    openai_cont = None
                    if openai_responses_tracking_enabled and route_response_id:
                        openai_cont = self._build_openai_provider_continuation(
                            route=route,
                            tool_name=tool_name,
                            arguments=arguments,
                            result=result,
                            duration_ms=tool_duration_ms,
                        )
                        if openai_cont:
                            context_item["openai_provider_continuation"] = openai_cont
                            openai_provider_continuation = openai_cont
                            openai_previous_response_id = openai_cont["response_id"]
                    conversation_context.append(context_item)

                    if tool_name == "stash":
                        summary_args, summary_result = self._maybe_auto_summarize_stash_result(
                            result,
                            arguments,
                            transcript,
                            accumulated_data,
                        )
                        if summary_result:
                            self._add_auto_summary_context(
                                summary_args,
                                summary_result,
                                tools_used,
                                accumulated_data,
                                conversation_context,
                                seen_successful_tool_calls,
                            )
                    
                    # Continue to next turn (LLM will decide if more tools needed)
                    continue
                    
                else:
                    # Failure - check if we should retry
                    error = result.get("error", "Unknown error")
                    speech = result.get("speech", f"Failed to execute {tool_name}")
                    if sys.stdout.isatty():
                        print(f"❌ Tool failed ({tool_duration_ms}ms): {error}")
                    
                    # Emit progress: tool failed
                    self._emit_progress('tool_complete',
                        tool=tool_name,
                        duration_ms=tool_duration_ms,
                        success=False,
                        error=str(error)[:200],  # Truncate long errors
                        call_index=call_index
                    )
                    
                    # Status update on error
                    is_server_error = '500' in str(error) or 'Internal Server Error' in str(error)
                    is_single_call_failure = tool_name in SINGLE_CALL_TOOLS
                    if not is_single_call_failure:
                        self.status_updater.update_error(
                            error_type='server' if is_server_error else 'retry',
                            error_message=error,
                            is_server_error=is_server_error
                        )

                    # Preserve failed executions as authoritative context. Retry and
                    # duplicate-recovery paths must never infer success from an absent
                    # result merely because failed tools are excluded from tools_used.
                    failed_at = datetime.now(self.timezone)
                    conversation_context.append({
                        "tool": tool_name,
                        "arguments": arguments,
                        "result": result,
                        "speech": speech,
                        "meta": {
                            "executed_at_iso": failed_at.isoformat(),
                            "executed_at_local": failed_at.strftime("%Y-%m-%d %H:%M:%S %Z"),
                            "freshness": "failed_tool_call",
                            "ttl_seconds": None,
                            "source": "tool_failure",
                            "authoritative_live": False,
                        },
                    })

                    # Expensive or side-effecting tools are intentionally limited to
                    # one attempt. Do not invite an LLM retry that the single-call cap
                    # will reject, and never switch a user-selected provider silently.
                    if is_single_call_failure:
                        final_speech = _format_terminal_tool_failure(tool_name, error, arguments)
                        attempted_tools = list(dict.fromkeys([*tools_used, tool_name]))
                        self._log_conversation(transcript, final_speech, attempted_tools, success=False)
                        self.status_updater.mark_complete()
                        return {
                            "speech": final_speech,
                            "ok": False,
                            "error": error,
                            "tool_name": tool_name,
                            "tool_args": arguments,
                            "tools_used": attempted_tools,
                            "tool_trace": tool_trace,
                            "retries": retry_count,
                            "terminal_failure": True,
                        }
                    
                    # Emit progress: retrying
                    if retry_count < self.max_retries:
                        self._emit_progress('routing',
                            message=f"Tool failed, trying another approach... (retry {retry_count + 1}/{self.max_retries})"
                        )
                    
                    # Retry if we haven't exceeded max retries
                    if retry_count < self.max_retries:
                        if sys.stdout.isatty():
                            print(f"🔄 Attempting retry {retry_count + 1}/{self.max_retries}...")
                        
                        # Build error context for retry
                        error_context = f"Tool '{tool_name}' failed with: {error}. Arguments used: {json.dumps(arguments)}"
                        error_lower = str(error).lower()
                        if (
                            available_tools
                            and (
                                error_lower == "tool not found"
                                or "required" in error_lower
                                or "missing" in error_lower
                                or "invalid" in error_lower
                            )
                        ):
                            error_context += (
                                "\n\nUse ONLY one of these exact tool names and exact argument keys on retry:\n"
                                f"{self._format_available_tool_contract(available_tools)}\n"
                                "Do not invent aliases or wrapper names."
                            )

                        # Recursive retry with error context
                        return self.process(
                            transcript,
                            retry_count + 1,
                            error_context,
                            conversation_history=conversation_history,
                            excluded_tools=excluded_tools,
                            tool_overrides=tool_overrides,
                            vision_pre_analyzed=vision_pre_analyzed_active,
                            request_kind=request_kind,
                            _retry_state={
                                "vision_pre_analyzed": vision_pre_analyzed_active,
                                "conversation_context": conversation_context,
                                "tools_used": tools_used,
                                "accumulated_data": accumulated_data,
                                "seen_successful_tool_calls": seen_successful_tool_calls,
                                "blocked_duplicate_calls": blocked_duplicate_calls,
                                "tool_call_counts": tool_call_counts,
                                "duplicate_recovery_attempts": duplicate_recovery_attempts,
                                "max_duplicate_recovery_attempts": max_duplicate_recovery_attempts,
                                "total_usage": total_usage,
                                "first_thinking": first_thinking,
                                "available_tools": available_tools,
                                "tool_trace": tool_trace,
                                "xai_previous_response_id": xai_previous_response_id,
                                "xai_provider_continuation": xai_provider_continuation,
                                "xai_text_fallback_retry_used": xai_text_fallback_retry_used,
                                "openai_previous_response_id": openai_previous_response_id,
                                "openai_provider_continuation": openai_provider_continuation,
                                "openai_text_fallback_retry_used": openai_text_fallback_retry_used,
                                "start_turn_num": turn_num + 1,
                            }
                        )
                    
                    # Max retries exceeded - sanitize error for voice output
                    friendly_error = _sanitize_error_for_speech(error)
                    speech_clean = (speech or "").strip()
                    if speech_clean:
                        final_speech = speech_clean
                        if friendly_error and friendly_error.lower() not in speech_clean.lower():
                            final_speech = f"{final_speech} {friendly_error.capitalize()}."
                        elif not final_speech.endswith((".", "!", "?")):
                            final_speech += "."
                    else:
                        final_speech = f"{friendly_error.capitalize()}."
                    
                    # Auto-log failed conversation
                    self._log_conversation(transcript, final_speech, tools_used, success=False)
                    
                    # Mark status updates complete
                    self.status_updater.mark_complete()
                    
                    return {
                        "speech": final_speech,
                        "ok": False,
                        "error": error,
                        "tool_name": tool_name,
                        "tool_args": arguments,
                        "tools_used": tools_used or [tool_name],
                        "tool_trace": tool_trace,
                        "retries": retry_count
                    }
            
            # Handle Q&A (task complete - LLM decided to respond directly)
            elif route["intent"] == "qa":
                # Status update: near complete (if tools were used)
                if tools_used:
                    self.status_updater.update(
                        category='near_complete',
                        context={'phase': 'wrapping_up'},
                    )
                
                # @TOOL_CONFIG: direct speech bypass — tools whose speech is used as-is (LLM won't reformat)
                last_tool = tools_used[-1] if tools_used else None
                use_direct_speech = False
                
                if last_tool in self.DIRECT_SPEECH_TOOLS and conversation_context:
                    # Use the tool's speech directly instead of LLM's reformulation
                    last_ctx = conversation_context[-1]
                    tool_speech = last_ctx.get("speech", "") or last_ctx.get("result", {}).get("speech", "")
                    if tool_speech:
                        raw_speech = tool_speech
                        use_direct_speech = True  # Skip further formatting!
                        if sys.stdout.isatty():
                            print(f"🎯 Using {last_tool}'s direct speech (bypassing LLM reformatting)")
                    else:
                        raw_speech = route.get("text_response", "I'm not sure how to respond.")
                else:
                    raw_speech = route.get("text_response", "I'm not sure how to respond.")
                
                # Apply response style formatting (for ALL responses, not just multi-turn)
                # UNLESS we're using direct speech from a tool (to avoid LLM mangling numbers)
                response_style = get_config_value('JARVIS_RESPONSE_STYLE', 'casual').lower()
                
                if use_direct_speech:
                    # Direct speech tools: use their speech verbatim, no LLM reformatting
                    speech = raw_speech
                elif response_style == 'casual':
                    # Format for voice (short & sweet)
                    if turn_num > 0:
                        # Multi-turn: summarize all tool results
                        speech = self._format_multi_turn_summary(transcript, tools_used, accumulated_data, raw_speech)
                    else:
                        # Single-turn: condense the LLM's verbose response
                        speech = self._format_single_turn_casual(transcript, raw_speech)
                elif response_style == 'auto':
                    # Smart mode: decide based on tool type and complexity
                    speech = self._format_auto_mode(transcript, tools_used, accumulated_data, raw_speech, turn_num)
                else:
                    # Detailed mode - use LLM's raw response
                    speech = raw_speech
                
                if sys.stdout.isatty():
                    turn_marker = f" after {len(tools_used)} tool(s)" if turn_num > 0 else ""
                    print(f"💬 Task complete{turn_marker}: {speech}")
                
                token_info = total_usage if self._has_usage_data(total_usage) else None
                
                # Build response
                response = {
                    "speech": speech,
                    "raw_llm_response": raw_speech,  # Original LLM response before voice formatting
                    "ok": True,
                    "tools_used": tools_used,
                    "data": accumulated_data,
                    "tool_trace": tool_trace,
                    "available_tools": available_tools,  # Tools LLM could choose from
                    "intelligence_context": combined_intelligence_context,
                    "routing_provenance": routing_provenance,
                    "response_style": response_style,
                    "qa_word_limit": int(get_config_value('JARVIS_QA_WORD_LIMIT', str(DEFAULT_JARVIS_QA_WORD_LIMIT))),
                    "multi_turn_word_limit": int(get_config_value('JARVIS_MULTI_TURN_WORD_LIMIT', str(DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT))),
                }
                
                # Add token info to response if available (cloud only)
                if token_info:
                    response["usage"] = token_info

                # Include native provider tool usage even if token info is omitted.
                # The Web UI uses this for the server-side tool toast.
                if total_usage.get("server_side_tools"):
                    server_tools = total_usage["server_side_tools"]
                    total_searches = sum(server_tools.values())
                    tool_summary = ", ".join(f"{k.replace('SERVER_SIDE_TOOL_', '').lower()}={v}" for k, v in server_tools.items())
                    if sys.stdout.isatty():
                        print(f"🔍 xAI native search: {total_searches} call(s) [{tool_summary}]")
                    response["server_side_tools"] = server_tools
                
                # Add thinking to response if available
                if first_thinking:
                    response["thinking"] = first_thinking
                
                # Record experience for self-learning (returns experience_id for feedback linking)
                experience_id = self._record_learning_experience(transcript, tools_used, response, conversation_context, applied_insights)
                if experience_id > 0:
                    response["experience_id"] = experience_id

                # Auto-log conversation after experience_id is known (wake-word linkage)
                self._log_conversation(
                    transcript,
                    speech,
                    tools_used,
                    success=True,
                    token_info=token_info,
                    experience_id=experience_id if experience_id > 0 else None,
                )
                
                # Mark status updates complete before final TTS
                self.status_updater.mark_complete()
                
                # Maybe collect feedback (random chance based on env config)
                return self._maybe_collect_feedback(response, transcript)
            
            # Handle routing errors
            else:
                error = route.get("error", "Unknown routing error")
                speech = route.get("text_response", "Sorry, I had trouble understanding that.")
                if sys.stdout.isatty():
                    print(f"❌ Routing error: {error}")
                
                # Auto-log error
                self._log_conversation(transcript, speech, tools_used, success=False)
                
                # Mark status updates complete
                self.status_updater.mark_complete()
                
                return {
                    "speech": speech,
                    "ok": False,
                    "error": error
                }
        
        # Safety: Max turns reached (after loop completes)
        # Generate intelligent summary of what was accomplished
        response_style = get_config_value('JARVIS_RESPONSE_STYLE', 'casual').lower()
        
        if response_style == 'casual' or response_style == 'auto':
            # Casual and auto both format max turns summary
            final_speech = self._format_max_turns_summary(transcript, tools_used, accumulated_data, max_turns)
        else:
            # Detailed mode: verbose fallback
            final_speech = f"Reached complexity limit after {len(tools_used)} actions. Tools used: {', '.join(tools_used)}. Please review the results or let me know if you'd like me to continue."
        
        if sys.stdout.isatty():
            print(f"⚠️  Max turns ({max_turns}) reached")
        
        self._log_conversation(transcript, final_speech, tools_used, success=True)
        
        # Mark status updates complete
        self.status_updater.mark_complete()
        
        result = {
            "speech": final_speech,
            "ok": True,
            "tools_used": tools_used,
            "data": accumulated_data,
            "tool_trace": tool_trace,
            "max_turns_reached": True,
            "usage": total_usage if self._has_usage_data(total_usage) else None,
            "server_side_tools": total_usage.get("server_side_tools", {})
        }
        
        # Maybe collect feedback (random chance based on env config)
        return self._maybe_collect_feedback(result, transcript)
    
    def _synthesize_duplicate_prevented_response(
        self, 
        user_query: str, 
        tools_used: list, 
        accumulated_data: dict,
        conversation_context: list
    ) -> str:
        """
        Synthesize a proper response when duplicate tool detection triggers.
        
        Instead of just saying "I used X tools", actually summarize the research
        results and answer the user's question using the accumulated data.
        
        Args:
            user_query: Original user request
            tools_used: List of tools that were executed
            accumulated_data: Results from all tools
            conversation_context: Full conversation history with results
            
        Returns:
            Synthesized speech response that actually answers the user's question
        """
        try:
            def _query_wants_artifact_update(text: str) -> bool:
                lowered = (text or "").lower()
                artifact_terms = [
                    "save to canvas", "save it to canvas", "update canvas", "update the canvas",
                    "put it on canvas", "add to canvas", "save to the page", "update the page",
                    "update the doc", "save the doc", "create a canvas page", "make a canvas page",
                    "save this", "write this up", "document this", "create slides", "update slides"
                ]
                return any(term in lowered for term in artifact_terms)

            def _is_generic_artifact_confirmation(tool_name: str, text: str) -> bool:
                if not text or not isinstance(text, str):
                    return False
                lowered = text.strip().lower()
                if not lowered:
                    return False
                if tool_name == "canvas":
                    return bool(re.match(r"^(updated|saved|created)\b.+\b(canvas|page)\.?\s*$", lowered))
                return bool(re.match(r"^(updated|saved|created)\b.+\b(doc|page|canvas|slides|presentation|stash)\.?\s*$", lowered))

            def _extract_text_from_payload(payload: Any) -> str:
                if isinstance(payload, str):
                    return payload.strip()
                if isinstance(payload, list):
                    parts = []
                    for item in payload:
                        text = _extract_text_from_payload(item)
                        if text:
                            parts.append(text)
                    return "\n".join(parts).strip()
                if isinstance(payload, dict):
                    if isinstance(payload.get("text"), str):
                        return payload["text"].strip()
                    for key in ("parts", "content"):
                        if key in payload:
                            text = _extract_text_from_payload(payload.get(key))
                            if text:
                                return text
                return ""

            def _is_machine_like_speech(text: str) -> bool:
                """Detect raw JSON or machine-formatted tool payloads."""
                if not text or not isinstance(text, str):
                    return True
                s = text.strip()
                if not s:
                    return True
                if s.startswith("{") or s.startswith("["):
                    return True
                if '\\"url\\":' in s or '"url":' in s:
                    return True
                if '\\"title\\":' in s or '"title":' in s:
                    return True
                if re.match(r"^(Read|Listed|Found)\s+\d+(\.\d+)?\s+\w+", s):
                    return True
                if re.match(r"^Read\s+\d+\s+bytes\s+from\s+.+", s):
                    return True
                if re.match(r"^Listed\s+\d+\s+(files|items|results)", s):
                    return True
                # Heuristic for payload-like snippets
                if s.count("{") >= 2 and s.count(":") >= 3:
                    return True
                return False

            def _is_unhelpful_duplicate_speech(text: str) -> bool:
                """Detect terse tool-confirmation text that is bad as a final duplicate fallback."""
                if not text or not isinstance(text, str):
                    return True
                s = text.strip()
                if not s:
                    return True
                if re.match(r"^Read\s+.+\.(md|txt|srt|pdf|json|csv|html?)$", s, flags=re.IGNORECASE):
                    return True
                if re.match(r"^Blocked duplicate tool call for\b", s, flags=re.IGNORECASE):
                    return True
                if "duplicate guard blocked tool" in s.lower():
                    return True
                if re.match(r"^(Saved|Created|Updated|Listed|Found)\b.+\b(stash|file|files|items|results)\b", s, flags=re.IGNORECASE):
                    return True
                return False

            def _build_duplicate_safeguard_fallback() -> str:
                """Provide a deterministic fallback when LLM synthesis is weak or unavailable."""
                youtube_data = accumulated_data.get("youtube_transcript")
                if isinstance(youtube_data, list) and youtube_data:
                    youtube_data = youtube_data[-1]
                if isinstance(youtube_data, dict):
                    title = youtube_data.get("video_title") or "the YouTube video"
                    saved_formats = []
                    if youtube_data.get("srt_saved"):
                        saved_formats.append("SRT")
                    if youtube_data.get("md_saved"):
                        saved_formats.append("markdown")
                    formats_text = ""
                    if saved_formats:
                        if len(saved_formats) == 1:
                            formats_text = f" and saved a {saved_formats[0]} copy to stash"
                        else:
                            formats_text = f" and saved {saved_formats[0]} and {saved_formats[1]} copies to stash"
                    return (
                        f"Duplicate tool detection triggered. I got the transcript for {title}{formats_text}. "
                        "I have not answered your full question yet because the model tried to reread the same file instead of summarizing it. "
                        "Reply again and I will continue from the transcript."
                    )

                stash_data = accumulated_data.get("stash")
                if isinstance(stash_data, list) and stash_data:
                    stash_data = stash_data[-1]
                if isinstance(stash_data, dict):
                    name = stash_data.get("name") or "the file"
                    return (
                        f"Duplicate tool detection triggered. I already read {name}, but the model tried to read it again instead of summarizing it. "
                        "Reply again and I will continue from what I already have."
                    )

                if "canvas" in [t.lower() for t in tools_used] and _query_wants_artifact_update(user_query):
                    return "Duplicate tool detection triggered after saving the work to Canvas. Reply again if you want me to continue from the saved results."

                return "Duplicate tool detection triggered. I stopped the repeated tool call. Reply again and I will continue from the results gathered so far."

            # If OpenCode already returned a useful build summary, prefer that
            # over later status/verification tools like check_opencode_sessions.
            if conversation_context:
                for ctx in reversed(conversation_context):
                    if ctx.get("tool") != "opencode":
                        continue
                    result = ctx.get("result", {}) if isinstance(ctx, dict) else {}
                    opencode_result = (
                        (result.get("data", {}) or {}).get("opencode_result", {})
                        if isinstance(result, dict)
                        else {}
                    )
                    extracted = _extract_text_from_payload(opencode_result)
                    if extracted and not _is_machine_like_speech(extracted):
                        return extracted.strip()

                    op_speech = (result or {}).get("speech") or ctx.get("speech") or ""
                    if (
                        isinstance(op_speech, str)
                        and op_speech.strip()
                        and not _is_machine_like_speech(op_speech)
                    ):
                        return op_speech.strip()

            # If we already have clear tool speech, prefer it over re-synthesis.
            # This avoids hallucinated contradictions when duplicate prevention triggers.
            if conversation_context:
                for failed_ctx in reversed(conversation_context):
                    if not isinstance(failed_ctx, dict) or failed_ctx.get("tool") == "duplicate_guard":
                        continue
                    failed_result = failed_ctx.get("result", {})
                    if isinstance(failed_result, dict) and failed_result.get("ok") is False:
                        return _format_terminal_tool_failure(
                            failed_ctx.get("tool", "tool"),
                            failed_result.get("error") or failed_result.get("speech"),
                            failed_ctx.get("arguments"),
                        )

                last_ctx = {}
                last_result = {}
                last_tool = ""
                last_speech = ""
                for candidate_ctx in reversed(conversation_context):
                    candidate_tool = candidate_ctx.get("tool", "") if isinstance(candidate_ctx, dict) else ""
                    if candidate_tool == "duplicate_guard":
                        continue
                    candidate_result = candidate_ctx.get("result", {}) if isinstance(candidate_ctx, dict) else {}
                    candidate_speech = (
                        (candidate_result or {}).get("speech")
                        or candidate_ctx.get("speech")
                        or ""
                    )
                    if candidate_speech:
                        last_ctx = candidate_ctx
                        last_result = candidate_result
                        last_tool = candidate_tool
                        last_speech = candidate_speech
                        break
                last_speech = (
                    (last_result or {}).get("speech")
                    or (last_ctx.get("speech") if isinstance(last_ctx, dict) else "")
                    or last_speech
                    or ""
                )
                if _is_generic_artifact_confirmation(last_tool, last_speech) and not _query_wants_artifact_update(user_query):
                    last_speech = ""
                if (
                    isinstance(last_speech, str)
                    and last_speech.strip()
                    and not _is_unhelpful_duplicate_speech(last_speech)
                    and not _is_machine_like_speech(last_speech)
                ):
                    return last_speech.strip()

            # If duplicate fallback is reached with a long stash artifact but
            # no condensed summary, create the summary now instead of relying
            # only on a head/tail excerpt.
            self._maybe_backfill_stash_summary_for_synthesis(
                user_query,
                tools_used,
                accumulated_data,
                conversation_context,
            )

            # Extract useful data from accumulated results
            extracted_data = self._extract_useful_data(accumulated_data)
            
            # Check for canvas content in conversation context (research may be there)
            canvas_content = ""
            for ctx in conversation_context:
                if ctx.get("tool") == "canvas":
                    result = ctx.get("result", {})
                    canvas_content = result.get("data", {}).get("content", "")[:2000]
                    if canvas_content:
                        break
            
            # Use LLM to synthesize a proper answer
            context = f"""User asked: "{user_query}"

Tools executed: {', '.join(set(tools_used))}

GATHERED DATA:
{extracted_data}

{f"CANVAS CONTENT (research results):{chr(10)}{canvas_content}" if canvas_content else ""}

IMPORTANT: The task completed but tried to call a duplicate tool. 
You MUST synthesize a proper answer using the data above.

CRITICAL RULES:
1. MAX 300 WORDS - but ACTUALLY ANSWER the user's question
2. If you found relevant info (camera models, prices, specs, comparisons) - INCLUDE IT
3. Reference the Canvas page if detailed results were saved there
4. DO NOT say "I used tools" or mention tool counts - just answer!
5. If data is in Canvas, say "I've saved the full comparison to Canvas. Here's the summary: ..."

GOOD EXAMPLES:
- "I've saved the camera comparison to Canvas. Top picks: Reolink E1 Pro at $45 (4MP, local storage), Wyze Cam V3 at $35 (night vision, SD card), and Eufy 2K at $50 (no subscription, HomeKit). All wired power with free local recording."
- "Research complete and saved to Canvas. Based on reviews, the best no-subscription cameras are..."

BAD EXAMPLES:
- "I've completed the task using 2 tools: canvas, brave_search" (WRONG - answer the question!)
- "Task done." (WRONG - provide actual findings!)

Your synthesized response:"""
            
            response = self.router.provider.chat(
                context, 
                system_prompt=self._apply_qa_prompt_overrides(
                    "Synthesize research results into a helpful answer. MAX 150 words. "
                    "Answer the user's actual question using the data provided."
                )
            )
            if (
                not response
                or self._looks_like_provider_error_text(response)
                or _is_unhelpful_duplicate_speech(response)
            ):
                return _build_duplicate_safeguard_fallback()
            return response.strip()
            
        except Exception as e:
            # Fallback: still try to be useful
            if sys.stdout.isatty():
                print(f"⚠️ Failed to synthesize duplicate response: {e}", file=sys.stderr)
            
            # Better fallback than just "I used X tools"
            return _build_duplicate_safeguard_fallback()

    def _format_natural_response(self, user_query: str, tool_name: str, tool_result: dict[str, Any]) -> str:
        """
        Use LLM to format tool results into natural conversational speech.
        
        Args:
            user_query: Original user question
            tool_name: Name of the tool that was executed
            tool_result: The tool's result dict
            
        Returns:
            Natural language response
        """
        return self._get_response_formatter().format_natural_response(user_query, tool_name, tool_result)

    @staticmethod
    def _looks_like_provider_error_text(text: str) -> bool:
        """Detect provider error strings accidentally returned as normal formatter output."""
        return ResponseFormatter.looks_like_provider_error_text(text)

    @staticmethod
    def _stash_ref_from_result(data: dict, arguments: dict | None = None) -> str:
        """Resolve a stash:// ref from stash result data or read arguments."""
        if not isinstance(data, dict):
            return ""
        arguments = arguments or {}
        stash_ref = data.get("ref") or data.get("stash_ref") or ""
        if not stash_ref and arguments.get("space_id") and arguments.get("file_id"):
            stash_ref = f"stash://{arguments.get('space_id')}/{arguments.get('file_id')}"
        return str(stash_ref).strip()

    @staticmethod
    def _has_text_summarizer_summary_for_ref(accumulated_data: dict, stash_ref: str) -> bool:
        """Return True if accumulated text_summarizer data already summarizes this stash ref."""
        if not stash_ref or not isinstance(accumulated_data, dict):
            return False
        summaries = accumulated_data.get("text_summarizer")
        if summaries is None:
            return False
        if not isinstance(summaries, list):
            summaries = [summaries]
        for item in summaries:
            if not isinstance(item, dict) or not item.get("summary"):
                continue
            source = item.get("source")
            if isinstance(source, dict) and source.get("stash_ref") == stash_ref:
                return True
        return False

    @staticmethod
    def _conversation_has_text_summary_for_ref(conversation_context: list, stash_ref: str) -> bool:
        """Check turn context for a prior text_summarizer result for the same stash ref."""
        if not stash_ref:
            return False
        for ctx in conversation_context or []:
            if not isinstance(ctx, dict) or ctx.get("tool") != "text_summarizer":
                continue
            result = ctx.get("result", {}) if isinstance(ctx.get("result"), dict) else {}
            data = result.get("data", {}) if isinstance(result.get("data"), dict) else {}
            source = data.get("source", {}) if isinstance(data.get("source"), dict) else {}
            if data.get("summary") and source.get("stash_ref") == stash_ref:
                return True
        return False

    def _maybe_auto_summarize_stash_result(
        self,
        stash_result: dict,
        stash_arguments: dict,
        user_query: str,
        accumulated_data: dict,
    ) -> tuple[dict[str, Any], dict[str, Any]] | tuple[None, None]:
        """
        Automatically condense long stash reads so later turns use a real summary.

        This is intentionally limited to long text stash reads. It prevents the
        router from repeatedly trying to re-read the same artifact just because
        the turn context preview had to be truncated.
        """
        enabled = str(get_config_value("STASH_AUTO_SUMMARIZE_AFTER_READ", "true")).lower()
        if enabled not in {"1", "true", "yes", "on"}:
            return None, None
        if not hasattr(self, "executor") or self.executor is None:
            return None, None
        if not isinstance(stash_result, dict) or not stash_result.get("ok", True):
            return None, None

        data = stash_result.get("data", {})
        if not isinstance(data, dict):
            return None, None
        content = data.get("content")
        if not isinstance(content, str):
            return None, None

        min_chars = get_int("STASH_AUTO_SUMMARIZE_MIN_CHARS", get_int("TEXT_SUMMARIZER_LLM_MIN_CHARS", 4000))
        if len(content) < min_chars:
            return None, None

        stash_ref = self._stash_ref_from_result(data, stash_arguments)
        if not stash_ref or self._has_text_summarizer_summary_for_ref(accumulated_data, stash_ref):
            return None, None

        summary_args = {
            "operation": "summarize",
            "method": "auto",
            "stash_ref": stash_ref,
            "num_sentences": 12,
            "summary_style": "detailed",
            "max_words": get_int("STASH_AUTO_SUMMARY_MAX_WORDS", 700),
            "focus": f"Extract the details needed to answer this request: {str(user_query)[:500]}",
        }

        try:
            self._emit_progress(
                "tool_start",
                tool="text_summarizer",
                args={"operation": "summarize", "stash_ref": stash_ref},
                auto=True,
            )
            result = self.executor.execute("text_summarizer", summary_args, skip_permission_check=True)
            self._emit_progress(
                "tool_complete",
                tool="text_summarizer",
                success=bool(result.get("ok")),
                auto=True,
            )
        except Exception as e:
            if sys.stdout.isatty():
                print(f"⚠️ Auto text_summarizer failed for stash read: {e}", file=sys.stderr)
            return None, None

        if not isinstance(result, dict) or not result.get("ok"):
            return None, None
        return summary_args, result

    def _add_auto_summary_context(
        self,
        summary_args: dict[str, Any],
        summary_result: dict[str, Any],
        tools_used: list,
        accumulated_data: dict,
        conversation_context: list,
        seen_successful_tool_calls: set | None = None,
    ) -> None:
        """Record an automatic text_summarizer result like any other successful tool result."""
        tools_used.append("text_summarizer")
        if seen_successful_tool_calls is not None:
            seen_successful_tool_calls.add(("text_summarizer", json.dumps(summary_args, sort_keys=True)))

        tool_data = summary_result.get("data", {})
        if "text_summarizer" in accumulated_data:
            existing = accumulated_data["text_summarizer"]
            if not isinstance(existing, list):
                accumulated_data["text_summarizer"] = [existing]
            accumulated_data["text_summarizer"].append(tool_data)
        else:
            accumulated_data["text_summarizer"] = tool_data

        executed_at = datetime.now(self.timezone)
        conversation_context.append({
            "tool": "text_summarizer",
            "arguments": summary_args,
            "result": summary_result,
            "speech": summary_result.get("speech", ""),
            "meta": {
                "executed_at_iso": executed_at.isoformat(),
                "executed_at_local": executed_at.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "freshness": "derived_tool_call",
                "ttl_seconds": None,
                "source": "text_summarizer",
                "authoritative_live": False,
                "auto": True,
            }
        })

    def _maybe_backfill_stash_summary_for_synthesis(
        self,
        user_query: str,
        tools_used: list,
        accumulated_data: dict,
        conversation_context: list,
    ) -> None:
        """
        Last-chance summary backfill for older paths that hit duplicate fallback
        before a long stash artifact was condensed.
        """
        stash_data = accumulated_data.get("stash") if isinstance(accumulated_data, dict) else None
        if stash_data is None:
            return
        stash_items = stash_data if isinstance(stash_data, list) else [stash_data]

        for item in reversed(stash_items):
            if not isinstance(item, dict):
                continue
            summary_args, summary_result = self._maybe_auto_summarize_stash_result(
                {"ok": True, "data": item},
                {},
                user_query,
                accumulated_data,
            )
            if summary_result:
                self._add_auto_summary_context(
                    summary_args,
                    summary_result,
                    tools_used,
                    accumulated_data,
                    conversation_context,
                )
                return

    def _apply_qa_prompt_overrides(self, base_prompt: str) -> str:
        """Apply model-specific QA overlays to synthesis-style prompts."""
        return self._get_response_formatter().apply_qa_prompt_overrides(base_prompt)

    def _xai_tts_style_tags_enabled(self) -> bool:
        """Return True when final speech may include xAI TTS style tags."""
        return self._get_response_formatter().xai_tts_style_tags_enabled()

    def _xai_tts_style_tags_instruction(self) -> str:
        """Small, final-speech-only instruction for xAI expressive TTS tags."""
        return self._get_response_formatter().xai_tts_style_tags_instruction()
    
    def _format_auto_mode(self, user_query: str, tools_used: list, accumulated_data: dict, raw_response: str, turn_num: int) -> str:
        """
        Smart auto mode: Adapt response formatting based on tool type and complexity.
        
        FLOW:
        - Multi-turn (turn_num > 0) → ALWAYS uses _format_multi_turn_summary() for ALL tools
        - Single-turn (turn_num == 0) → Checks tool category to decide formatting:
          - SEARCH_TOOLS → Condense (remove URLs, summarize)
          - SIMPLE_TOOLS → Keep if short (≤25 words), condense if longer
          - COMPLEX_TOOLS → Keep detailed if long (>75 words), condense if short
          - Unlisted tools → Default to condense
        
        NOTE: The tool categories below only affect SINGLE-TURN responses.
        Multi-turn always summarizes all tool results together.
        
        Args:
            user_query: Original user request
            tools_used: List of tool names executed (first tool checked for single-turn)
            accumulated_data: Results from all tools
            raw_response: Verbose response from LLM
            turn_num: Current turn number (0 = single-turn, >0 = multi-turn)
            
        Returns:
            Formatted response for TTS
        """
        return self._get_response_formatter().format_auto_mode(
            user_query,
            tools_used,
            accumulated_data,
            raw_response,
            turn_num,
        )
    
    def _format_single_turn_casual(self, user_query: str, raw_response: str) -> str:
        """
        Format Q&A or single-tool response for voice output (casual/auto mode).
        Uses JARVIS_QA_WORD_LIMIT (default: 75 words).
        
        Called by:
        - Casual mode: Always (for both Q&A and single-tool responses)
        - Auto mode: For search tools, simple tools when long, and default fallback
        
        NOTE: This is the FINAL formatting before TTS. The LLM prompt includes rules to:
        - Strip stash:// references (say "saved to stash" instead)
        - Strip long URLs (say domain only or "link saved")
        - Simplify file paths to just filename
        These rules only apply HERE (final speech), not to internal LLM processing.
        See rules 7-9 in the prompt below. Added 2026-02-02.
        
        Args:
            user_query: Original user request
            raw_response: Verbose response from LLM
            
        Returns:
            Voice-friendly version (condensed, no stash refs/long URLs)
        """
        return self._get_response_formatter().format_single_turn_casual(user_query, raw_response)
    
    def _format_multi_turn_summary(self, user_query: str, tools_used: list, accumulated_data: dict, llm_response: str) -> str:
        """
        Format multi-turn (multiple tools) results for voice output.
        Uses JARVIS_MULTI_TURN_WORD_LIMIT (default: 75 words).
        
        Called when turn_num > 0 (task used multiple tools across multiple LLM turns).
        Summarizes ALL tool results together into a concise spoken summary.
        
        NOTE: This is the FINAL formatting before TTS. The LLM prompt includes rules to:
        - Strip stash:// references (say "saved to stash" instead)
        - Strip long URLs (say domain only or "link saved")
        - Simplify file paths to just filename
        These rules only apply HERE (final speech), not to internal LLM processing.
        See rules 6-8 in the prompt below. Added 2026-02-02.
        
        Args:
            user_query: Original user request
            tools_used: List of ALL tool names executed (all turns)
            accumulated_data: Results from ALL tools (all turns combined)
            llm_response: LLM's final synthesized response
            
        Returns:
            Concise voice-friendly summary bounded by
            JARVIS_MULTI_TURN_WORD_LIMIT (using the shared config_loader baseline
            when unset)
        """
        return self._get_response_formatter().format_multi_turn_summary(
            user_query,
            tools_used,
            accumulated_data,
            llm_response,
        )
    
    def _format_max_turns_summary(self, user_query: str, tools_used: list, accumulated_data: dict, max_turns: int) -> str:
        """
        Create intelligent summary when max turns is reached.
        BEST EFFORT MODE: Extract and present whatever useful data was gathered.
        Uses JARVIS_MULTI_TURN_WORD_LIMIT (same as _format_multi_turn_summary).

        Args:
            user_query: Original user request
            tools_used: List of tool names executed
            accumulated_data: Results from all tools
            max_turns: The limit that was hit
            
        Returns:
            Voice-friendly explanation of progress and next steps
        """
        return self._get_response_formatter().format_max_turns_summary(
            user_query,
            tools_used,
            accumulated_data,
            max_turns,
        )
    
    # Fallback only: long stash reads should normally be condensed through text_summarizer first.
    def _excerpt_for_synthesis(self, text: str, max_chars: int = 8000) -> str:
        """Keep enough of long text artifacts for fallback synthesis without flooding the prompt."""
        return self._get_context_assembler().excerpt_for_synthesis(text, max_chars=max_chars)

    def _extract_useful_data(self, accumulated_data: dict) -> str:
        """
        Extract the most useful/relevant data from accumulated tool results.
        Handles arrays (repeated tool calls) and extracts titles, descriptions, key info.
        
        Args:
            accumulated_data: Dict of tool_name -> result or [results]
            
        Returns:
            Formatted string of extracted useful data
        """
        return self._get_context_assembler().extract_useful_data(
            accumulated_data,
            has_text_summarizer_summary_for_ref=self._has_text_summarizer_summary_for_ref,
        )
    
    def _format_conversation_context(self, current_query: str, history: list) -> str:
        """
        Format provided conversation history as context for the LLM.
        Used by web app to pass its own conversation history.
        
        Args:
            current_query: User's current question/request
            history: List of previous messages [{role: str, content: str, timestamp?: str, tools_used: list, tool_results: dict}, ...]
            
        Returns:
            Enhanced query with conversation context
        """
        return self._get_context_assembler().format_conversation_context(current_query, history)

    def _previous_experience_id_from_history(self, history: list | None) -> int | None:
        """Find the most recent assistant experience ID in provided history."""
        for msg in reversed(history or []):
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            exp_id = msg.get("experience_id")
            if exp_id is None and isinstance(msg.get("data"), dict):
                exp_id = msg["data"].get("experience_id")
            try:
                exp_id_int = int(exp_id)
            except (TypeError, ValueError):
                continue
            if exp_id_int > 0:
                return exp_id_int
        return None

    def _resolve_previous_experience_id_for_auto_context(self) -> int | None:
        """Resolve prior experience_id from recent conversation logs (wake-word/CLI)."""
        try:
            db = get_memory_db()
            within_minutes = get_int('AUTO_CONTEXT_MINUTES', 10)
            exp_id = db.get_previous_experience_id_from_recent_conversations(
                within_minutes=within_minutes,
                session_id=self.session_id,
            )
            if not exp_id:
                exp_id = db.get_previous_experience_id_from_recent_conversations(
                    within_minutes=within_minutes,
                    session_id=None,
                )
            db.close()
            return exp_id
        except Exception:
            return None
    
    def _try_workflow(self, transcript: str) -> dict[str, Any] | None:
        """
        Check if transcript matches an explicit workflow command.
        
        Workflows are triggered by explicit commands like /research, /note, /health.
        If matched, executes the workflow pipeline and returns the result.
        If no match, returns None to continue with normal LLM routing.
        """
        try:
            workflow = self.workflow_loader.match(transcript)
            if not workflow:
                return None
            
            workflow.get("name", workflow.get("id"))
            
            # Status callback to use the existing status updater
            def status_callback(msg: str):
                self.status_updater.update(category='progress', custom_message=msg)
            
            # Execute the workflow pipeline
            result = self.pipeline_executor.execute(
                workflow, 
                transcript, 
                status_callback=status_callback
            )
            
            # Return in standard orchestrator response format
            response = {
                "ok": result.get("ok", False),
                "speech": result.get("speech", "Workflow complete."),
                "data": result.get("data", {}),
                "tools_used": result.get("tools_used", []),
                "workflow_executed": workflow.get("id")
            }
            
            # Include usage tracking if available (from LLM calls in workflow)
            if result.get("usage"):
                response["usage"] = result["usage"]
            
            # Pass through server-side tool usage (xAI web_search, x_search, etc.)
            if result.get("server_side_tools"):
                response["server_side_tools"] = result["server_side_tools"]
            
            return response
            
        except Exception as e:
            # If workflow execution fails, log but don't crash - fall back to normal routing
            print(f"Workflow execution error: {e}", file=sys.stderr)
            return None
    
    def _build_conversation_context(self, current_query: str) -> str:
        """
        Auto-inject recent conversation history for context awareness.
        
        This gives Jarvis "short-term memory" of recent interactions, enabling:
        - Natural follow-up responses ("you just said it was hot!")
        - Awareness of recently used tools
        - Learning from recent failures
        - Continued multi-step workflows
        
        Args:
            current_query: User's current question/request
            
        Returns:
            Enhanced query with recent conversation context (if any relevant)
        """
        return self._get_context_assembler().build_conversation_context(current_query)
    
    def _build_turn_context(self, original_query: str, conversation_context: list) -> str:
        """
        Build context string for subsequent turns in multi-turn conversation.
        
        Args:
            original_query: The user's original request
            conversation_context: List of previous tool executions and results
            
        Returns:
            Formatted context string for the LLM
        """
        return self._get_context_assembler().build_turn_context(original_query, conversation_context)

    def _tool_context_max_chars(self, tool_name: str) -> int:
        """Return the LLM-context preview budget for a tool result."""
        return self._get_context_assembler().tool_context_max_chars(tool_name)

    def _truncate_preview_text(self, value: Any, max_chars: int) -> str:
        """Truncate preview text without changing the original stored result."""
        return self._get_context_assembler().truncate_preview_text(value, max_chars)

    def _preview_key_rank(self, key: str, value: Any) -> tuple[int, int, str]:
        """Prioritize handles and compact scalar fields ahead of bulky payloads."""
        return self._get_context_assembler().preview_key_rank(key, value)

    def _preview_string_limit(self, parent_key: str) -> int:
        return self._get_context_assembler().preview_string_limit(parent_key)

    def _build_preview_value(
        self,
        value: Any,
        parent_key: str = "",
        depth: int = 0,
        max_depth: int = 3,
    ) -> Any:
        """Build a compact, JSON-safe preview for LLM context."""
        return self._get_context_assembler().build_preview_value(
            value,
            parent_key=parent_key,
            depth=depth,
            max_depth=max_depth,
        )

    def _build_llm_result_context_preview(self, tool_name: str, result: dict[str, Any]) -> tuple[str, int, int, bool]:
        """
        Build a valid JSON preview for later LLM turns while keeping the full result untouched.
        Returns (preview_text, full_result_chars, preview_chars, preview_truncated).
        """
        return self._get_context_assembler().build_llm_result_context_preview(tool_name, result)
    
    def _get_relevant_memories_bundle(self, transcript: str) -> dict[str, Any]:
        """
        Fetch memories semantically relevant to the current query.
        Injected into context so LLM doesn't need to call search_memory/semantic_recall.
        
        Applies recency weighting: more recent memories rank slightly higher.
        Older memories (60+ days) fade in relevance; recently used/updated stay higher.
        Importance is preserved for conflict resolution (user preferences override defaults).
        
        Works for CLI, WebUI, and wake word - all entry points use orchestrator.process().
        """
        enabled = get_config_value('AUTO_MEMORY_INJECTION_ENABLED', 'true').lower() == 'true'
        if not enabled:
            return {
                "context": "",
                "meta": {
                    "enabled": False,
                    "injected": False,
                    "threshold": None,
                    "limit": 0,
                    "candidate_count": 0,
                    "injected_count": 0,
                    "top_candidates": [],
                }
            }
        try:
            db = get_memory_db()
            limit = get_int('AUTO_MEMORY_LIMIT', 8)
            threshold = get_float('AUTO_MEMORY_SIMILARITY_THRESHOLD', 0.42)
            recency_enabled = get_config_value('AUTO_MEMORY_RECENCY_ENABLED', 'true').lower() == 'true'
            addressing_limit = get_int('AUTO_MEMORY_ALWAYS_INCLUDE_LIMIT', 2)
            type_filter_enabled = get_config_value('AUTO_MEMORY_TYPE_FILTER_ENABLED', 'true').lower() == 'true'
            transcript_lower = transcript.lower()

            def _include_memory(row: dict) -> bool:
                if not type_filter_enabled:
                    return True
                return is_eligible_for_auto_memory_inject(row)

            def _is_intel_source(source: str) -> bool:
                return bool(source and str(source).startswith('intel/'))

            def _is_curated_intel(source: str) -> bool:
                return source in {
                    'intel/jarvis-tool-knowledge.md',
                    'intel/jarvis-learned-lessons.md',
                }

            def _is_tooling_query(text: str) -> bool:
                tooling_terms = [
                    'tool', 'tools', 'provider', 'model', 'workflow', 'scheduler',
                    'memory', 'intel', 'prompt', 'cache', 'retry', 'error', 'errors',
                    'failed', 'failure', 'bug', 'issue', 'issues', 'quirk', 'limitation',
                    'limitations', 'parameter', 'params', 'api', 'orchestrator', 'routing',
                ]
                return any(term in text for term in tooling_terms)
            
            # Always-include ONLY addressing/response-style (call me sir, tone, language)
            # Topic-specific prefs (dog, Spotify) go through semantic search only
            # Skip "no preference" values - user said forget/stop, don't inject those
            NO_PREFERENCE_VALUES = frozenset([
                'no specific preference', 'no preference', 'none', 'nothing',
                'n/a', 'na', 'forget', 'remove', 'delete'
            ])
            def _is_no_preference(val: str) -> bool:
                v = (val or '').strip().lower()
                if not v:
                    return True
                if v in NO_PREFERENCE_VALUES:
                    return True
                if 'no specific' in v or 'no preference' in v:
                    return True
                return False

            seen_keys: set[str] = set()
            merged: list[tuple[float, int, dict, str]] = []  # (score, importance, memory, source)
            if addressing_limit > 0:
                for m in db.get_addressing_preferences(limit=addressing_limit):
                    key = m.get('key', '')
                    value = m.get('value', '')
                    if (
                        key
                        and key not in seen_keys
                        and not _is_no_preference(value)
                        and _include_memory(m)
                    ):
                        seen_keys.add(key)
                        merged.append((1.1, m.get('importance', 5), m, 'always'))

            # Curated intel should have a better chance to surface for technical/tooling queries,
            # especially when exact tool names or provider quirks are involved.
            if _is_tooling_query(transcript_lower):
                intel_keyword_matches = [
                    m for m in db.fts_search(
                        transcript,
                        limit=max(limit * (4 if type_filter_enabled else 1), 12),
                    )
                    if _is_intel_source(m.get('source', ''))
                ]
                for m in intel_keyword_matches:
                    key = m.get('key', '')
                    if key and key in seen_keys:
                        continue
                    if not _include_memory(m):
                        continue
                    if key:
                        seen_keys.add(key)
                    source_name = m.get('source', '')
                    score = 1.08 if _is_curated_intel(source_name) else 0.96
                    merged.append((score, m.get('importance', 5), m, 'intel'))
            
            # Semantic search: cast a slightly wider net, then keep rows with adjusted >= threshold
            # (AUTO_MEMORY_SIMILARITY_THRESHOLD applies to the recency-weighted score, not raw embed alone).
            candidate_limit = min(limit * (5 if type_filter_enabled else 2), 50)
            candidate_threshold = min(threshold - 0.05, 0.30)
            memories = db.semantic_search(
                query=transcript,
                limit=candidate_limit,
                similarity_threshold=candidate_threshold
            )
            
            semantic_candidates = []

            # Apply recency weighting to semantic results
            now = datetime.now()
            for m in memories:
                key = m.get('key', '')
                if key and key in seen_keys:
                    continue
                if not _include_memory(m):
                    continue
                sim = m.get('similarity', 0)
                importance = m.get('importance', 5)
                recency_factor = 1.0
                source_name = m.get('source', '')
                if recency_enabled:
                    updated = m.get('updated_at') or m.get('created_at')
                    if updated:
                        try:
                            if isinstance(updated, str):
                                ts = datetime.fromisoformat(updated.replace('Z', '+00:00'))
                            else:
                                ts = updated
                            ts_naive = ts.replace(tzinfo=None) if getattr(ts, 'tzinfo', None) else ts
                            days_old = (now - ts_naive).days
                            if days_old <= 7:
                                recency_factor = 1.0
                            elif days_old <= 30:
                                recency_factor = 0.97
                            elif days_old <= 60:
                                recency_factor = 0.94
                            elif days_old <= 120:
                                recency_factor = 0.90
                            else:
                                recency_factor = 0.85
                        except (ValueError, TypeError, AttributeError):
                            pass
                adjusted = sim * recency_factor
                if _is_intel_source(source_name):
                    adjusted += 0.05
                    if _is_curated_intel(source_name):
                        adjusted += 0.07
                semantic_candidates.append({
                    "key": key,
                    "category": m.get("category", ""),
                    "source": source_name,
                    "bucket": 'intel' if _is_intel_source(source_name) else 'semantic',
                    "score": round(float(adjusted or 0), 3),
                    "similarity": round(float(sim or 0), 3),
                })
                if adjusted >= threshold:
                    if key:
                        seen_keys.add(key)
                    merged.append((adjusted, importance, m, 'intel' if _is_intel_source(source_name) else 'semantic'))
            
            # Sort by score desc, then importance desc; take top N
            merged.sort(key=lambda x: (x[0], x[1]), reverse=True)
            top = merged[:limit]

            top_candidates = []
            for candidate in semantic_candidates[: min(max(limit, 3), 5)]:
                top_candidates.append(candidate)
            for rank_score, _, m, source in merged[: min(max(limit, 3), 5)]:
                candidate = {
                    "key": m.get("key", ""),
                    "category": m.get("category", ""),
                    "source": m.get("source", ""),
                    "bucket": source,
                    "score": round(float(rank_score or 0), 3),
                    "similarity": round(float(m.get("similarity") or 0), 3),
                }
                if not any(existing.get("key") == candidate["key"] for existing in top_candidates):
                    top_candidates.append(candidate)
                if len(top_candidates) >= min(max(limit, 3), 5):
                    break

            if not top:
                return {
                    "context": "",
                    "meta": {
                        "enabled": True,
                        "injected": False,
                        "threshold": threshold,
                        "limit": limit,
                        "candidate_count": len(semantic_candidates),
                        "injected_count": 0,
                        "top_candidates": top_candidates,
                    }
                }
            
            memory_lines = []
            price_like_query = any(
                token in transcript_lower
                for token in ["price", "btc", "bitcoin", "eth", "ethereum", "crypto", "stock", "ticker", "quote", "gold", "tsla", "aapl"]
            )

            def _is_price_like_memory(key: str, value: str) -> bool:
                text = f"{key} {value}".lower()
                keywords = ["price", "btc", "bitcoin", "crypto", "stock", "ticker", "quote", "coin", "market cap", "gold", "tsla", "aapl"]
                return any(k in text for k in keywords)

            for rank_score, _, m, source in top:
                key = m.get('key', '')
                value = m.get('value', '')
                if _is_no_preference(value):
                    continue  # User said forget/no preference - don't show
                cat = m.get('category', '')
                source_name = m.get('source', '')
                updated = m.get('updated_at') or m.get('created_at')
                saved_at_local = "unknown"
                age_minutes = None
                if updated:
                    try:
                        dt = self._safe_iso_to_local_datetime(str(updated))
                        if dt:
                            saved_at_local = dt.strftime("%Y-%m-%d %H:%M:%S %Z")
                            age_minutes = int((datetime.now(self.timezone) - dt).total_seconds() // 60)
                    except Exception:
                        pass
                # match_hint: rank_score is what we sorted on; embed = raw cosine when present
                raw_embed = float(m.get("similarity") or 0)
                if source == "always":
                    match_hint = f"pinned_pref rank={rank_score:.2f}"
                elif source == "intel":
                    # Intel via semantic search carries similarity; FTS intel hits do not
                    if raw_embed > 0:
                        match_hint = f"intel_semantic embed={raw_embed:.2f} rank={rank_score:.2f}"
                    elif _is_curated_intel(source_name):
                        match_hint = f"intel_curated rank={rank_score:.2f}"
                    else:
                        match_hint = f"intel_kw rank={rank_score:.2f}"
                else:
                    match_hint = f"semantic embed={raw_embed:.2f} rank={rank_score:.2f}"
                staleness_hint = ""
                if price_like_query and _is_price_like_memory(key, value):
                    if age_minutes is not None and age_minutes > 60:
                        staleness_hint = "STALE_FOR_LIVE_PRICE_QUERIES"
                    else:
                        staleness_hint = "recent_price_context"
                age_text = f"{age_minutes}m" if age_minutes is not None else "unknown"
                memory_lines.append(
                    f"- {key}: {value} "
                    f"(category: {cat}, {match_hint}, saved_at: {saved_at_local}, age: {age_text}"
                    f"{', source: ' + source_name if source_name else ''}"
                    f"{', staleness: ' + staleness_hint if staleness_hint else ''})"
                )
            if not memory_lines:
                return {
                    "context": "",
                    "meta": {
                    "enabled": True,
                    "injected": False,
                    "threshold": threshold,
                    "limit": limit,
                    "candidate_count": len(semantic_candidates),
                    "injected_count": 0,
                    "top_candidates": top_candidates,
                }
            }
            lines = [
                "=== RELEVANT STORED KNOWLEDGE (use directly when relevant) ===",
                "Lines tagged pinned_pref are address/tone preferences (e.g. call me sir)—honor those over your defaults when they apply.",
                "Other lines are semantic matches for this query (not necessarily instructions); use when relevant and ignore if off-topic or stale.",
                "If this block already answers the question, use it directly. Call search_memory or semantic_recall only if you need broader recall than what is shown here.",
                "Freshness note: For live market/weather questions, newer live tool calls outrank older stored memory.",
                f"Higher rank = stronger fit. embed = cosine; rank = similarity after recency (semantic rows need adjusted rank ≥ {threshold:.2f}).",
                ""
            ] + memory_lines + ["==="]
            return {
                "context": "\n".join(lines) + "\n\n",
                "meta": {
                    "enabled": True,
                    "injected": True,
                    "threshold": threshold,
                    "limit": limit,
                    "candidate_count": len(semantic_candidates),
                    "injected_count": len(memory_lines),
                    "top_candidates": top_candidates,
                }
            }
        except Exception as e:
            if os.environ.get('JARVIS_DEBUG'):
                print(f"⚠️ Auto-memory injection failed: {e}", file=sys.stderr)
            return {
                "context": "",
                "meta": {
                    "enabled": enabled,
                    "injected": False,
                    "threshold": None,
                    "limit": 0,
                    "candidate_count": 0,
                    "injected_count": 0,
                    "top_candidates": [],
                    "error": str(e),
                }
            }

    def _get_relevant_memories(self, transcript: str) -> str:
        """Backward-compatible wrapper returning only the injected memory block."""
        return self._get_relevant_memories_bundle(transcript).get("context", "")
    
    def _get_learning_insights(self, transcript: str, available_tools: list[str] = None) -> tuple[str, list[dict]]:
        """
        Get learned insights to inform routing decisions.
        
        Args:
            transcript: User's query
            available_tools: List of currently available tool names (for filtering)
        
        Returns:
            Tuple of (formatted_prompt_string, list_of_applied_insights)
            The insights list is used later to track if they were helpful.
        """
        try:
            from intelligence_hooks import get_routing_insights, format_insights_for_prompt
            
            insights = get_routing_insights(transcript)
            
            # Only include if we have meaningful insights
            if insights.get('insights') and insights.get('confidence', 0) > 0.3:
                # Pass available_tools to filter out insights for blocked/unavailable tools
                formatted = format_insights_for_prompt(insights, available_tools)
                # Return both formatted string and raw insights for tracking
                return formatted, insights.get('insights', [])
        except Exception as e:
            # Don't let insight failures affect the main flow
            if os.environ.get('JARVIS_DEBUG'):
                print(f"⚠️ Learning insights failed: {e}", file=sys.stderr)
        
        return "", []
    
    def _record_learning_experience(
        self,
        transcript: str,
        tools_used: list,
        result: dict,
        conversation_context: list,
        applied_insights: list = None
    ) -> int:
        """
        Record interaction for self-learning intelligence.
        Non-blocking - failures are logged but don't affect response.
        
        Args:
            transcript: User's query
            tools_used: List of tools executed
            result: Final result dict
            conversation_context: Conversation history
            applied_insights: List of insights that were shown to LLM (for tracking)
            
        Returns:
            Experience ID if recorded, -1 otherwise
        """
        if not self.learning_enabled:
            return -1

        try:
            from intelligence_hooks import record_interaction, track_insight_outcomes

            learning_result = result
            if self.web_conversation_id or self.session_id:
                learning_result = dict(result)
                if self.web_conversation_id:
                    learning_result["web_conversation_id"] = self.web_conversation_id
                if self.session_id:
                    learning_result["jarvis_session_id"] = self.session_id
            
            experience_id = record_interaction(
                query=transcript,
                tools_used=tools_used,
                result=learning_result,
                conversation_context=conversation_context
            )

            previous_experience_id = getattr(self, "_previous_experience_id_for_correction", None)
            if previous_experience_id and previous_experience_id != experience_id:
                try:
                    from intelligence_hooks import (
                        extract_user_correction_signals,
                        record_user_correction_shadow_candidate,
                        update_experience_from_user_correction,
                    )

                    signals = extract_user_correction_signals(transcript)
                    if signals.get("is_correction"):
                        correction_metadata = {
                            "current_experience_id": experience_id,
                            "previous_experience_id": previous_experience_id,
                            "jarvis_session_id": self.session_id,
                            "web_conversation_id": self.web_conversation_id,
                        }
                        mode = get_config_value("USER_CORRECTION_LEARNING_MODE", "shadow").strip().lower()
                        if mode in {"apply", "enabled", "true", "1", "on"}:
                            update_experience_from_user_correction(
                                previous_experience_id,
                                transcript,
                                signals=signals,
                                metadata={**correction_metadata, "mode": mode},
                            )
                        else:
                            record_user_correction_shadow_candidate(
                                current_experience_id=experience_id,
                                previous_experience_id=previous_experience_id,
                                correction_query=transcript,
                                signals=signals,
                                metadata={**correction_metadata, "mode": mode or "shadow"},
                            )
                            if os.environ.get("JARVIS_DEBUG"):
                                print(
                                    f"🧠 User correction shadow candidate: current={experience_id}, "
                                    f"previous={previous_experience_id}, "
                                    f"categories={signals.get('categories')}",
                                    file=sys.stderr,
                                )
                except Exception as correction_err:
                    if os.environ.get('JARVIS_DEBUG'):
                        print(f"⚠️ User correction detection failed: {correction_err}", file=sys.stderr)

            if experience_id > 0:
                self._last_experience_id = experience_id
            
            # Track insight usage if insights were applied
            if applied_insights:
                track_insight_outcomes(
                    insights=applied_insights,
                    tools_used=tools_used,
                    result=learning_result
                )
            
            return experience_id
        except Exception as e:
            # Don't let learning failures affect the main flow
            if os.environ.get('JARVIS_DEBUG'):
                print(f"⚠️ Learning recording failed: {e}", file=sys.stderr)
            return -1
    
    def _log_conversation(self, user_query: str, response: str, tools_used: list, success: bool = True, 
                          execution_time_ms: float = None, token_info: dict = None,
                          experience_id: int | None = None):
        """Auto-log conversation to memory database with metadata."""
        try:
            # Build metadata
            metadata = {
                "mode": self.mode,
                "provider": getattr(self.router, 'provider_type', 'unknown'),
                "model": getattr(self.router, 'model_name', 'unknown')
            }
            
            # Add timing if available
            if execution_time_ms is not None:
                metadata["execution_time_ms"] = round(execution_time_ms, 2)
            
            # Add token/cost info for metered providers. Ollama Cloud tokens are
            # persisted too (with has_unknown_cost), so cumulative token totals
            # include hosted Ollama usage instead of being silently dropped.
            provider = metadata.get("provider", "")
            if token_info and provider in ["openai", "anthropic", "ollama"]:
                metadata.update(token_info)
            if token_info and token_info.get("server_side_tools"):
                server_side_tools = dict(token_info.get("server_side_tools") or {})
                metadata["server_side_tools"] = server_side_tools
                metadata["server_side_tool_calls"] = _server_side_tool_call_count(server_side_tools)
                if provider == "xai":
                    metadata["xai_search_calls"] = metadata["server_side_tool_calls"]
                    metadata["xai_search_tools"] = list(server_side_tools.keys())
            
            # Add tool count
            metadata["tool_count"] = len(tools_used)
            
            # Add web conversation ID if this is a web UI request
            if self.web_conversation_id:
                metadata["web_conversation_id"] = self.web_conversation_id

            if experience_id and int(experience_id) > 0:
                metadata["experience_id"] = int(experience_id)
            
            db = get_memory_db()
            db.log_conversation(
                user_query=user_query,
                jarvis_response=response,
                tools_used=tools_used,
                session_id=self.session_id,
                success=success,
                metadata=metadata
            )
            db.close()
        except Exception as e:
            # Silently fail - don't break the main flow
            if sys.stdout.isatty():
                print(f"⚠️ Failed to log conversation: {e}", file=sys.stderr)


def main():
    """CLI interface."""
    if len(sys.argv) < 2:
        print("Usage: orchestrator_v2.py <mode> <transcript> [--json] [--speak] [--debug-thinking] [--prompt NAME]", file=sys.stderr)
        print("  mode: 'cloud' or 'local'", file=sys.stderr)
        print("  --json: Output only JSON (for scripting)", file=sys.stderr)
        print("  --speak: Speak the final result through speakers", file=sys.stderr)
        print("  --debug-thinking: Show LLM reasoning (for debugging)", file=sys.stderr)
        print("  --feedback: Ask LLM for feedback about the experience (QA mode)", file=sys.stderr)
        print("  --prompt NAME: Load a prompt from jarvis-web/data/prompts/NAME.md", file=sys.stderr)
        print("\nExample:")
        print("  ./orchestrator_v2.py cloud 'Send a webhook to my server'")
        print("  ./orchestrator_v2.py cloud 'What time is it?' --speak")
        print("  ./orchestrator_v2.py cloud 'Should I save this?' --debug-thinking")
        print("  ./orchestrator_v2.py cloud 'Test a task' --feedback")
        print("  ./orchestrator_v2.py cloud --prompt deep_research 'Research AI chips'")
        sys.exit(1)
    
    mode = sys.argv[1]
    
    # Check for --json flag
    json_only = "--json" in sys.argv
    if json_only:
        sys.argv.remove("--json")
        # Set env var to suppress verbose MCP output
        os.environ['JARVIS_JSON_MODE'] = '1'
    
    # Check for --debug-thinking flag
    debug_thinking = "--debug-thinking" in sys.argv
    if debug_thinking:
        sys.argv.remove("--debug-thinking")
        # Set env var for thinking module
        os.environ['JARVIS_DEBUG_THINKING'] = '1'
    
    # Check for --feedback flag (LLM-as-QA mode)
    collect_feedback = "--feedback" in sys.argv
    if collect_feedback:
        sys.argv.remove("--feedback")
    
    # Check for --speak flag (speak final result through speakers)
    speak_result = "--speak" in sys.argv
    if speak_result:
        sys.argv.remove("--speak")
    
    # Check for --prompt flag (load prompt file as context)
    prompt_context = None
    prompt_name = None
    if "--prompt" in sys.argv:
        idx = sys.argv.index("--prompt")
        if idx + 1 < len(sys.argv):
            prompt_name = sys.argv[idx + 1]
            # Remove both --prompt and the name
            sys.argv.pop(idx)  # Remove --prompt
            sys.argv.pop(idx)  # Remove the name (now at same index)
            
            # Load the prompt file
            prompt_path = Path(__file__).parent.parent / "jarvis-web" / "data" / "prompts" / f"{prompt_name}.md"
            if prompt_path.exists():
                prompt_context = prompt_path.read_text()
            else:
                print(f"❌ Prompt not found: {prompt_path}", file=sys.stderr)
                print(f"   Available prompts:", file=sys.stderr)
                prompts_dir = Path(__file__).parent.parent / "jarvis-web" / "data" / "prompts"
                for p in sorted(prompts_dir.glob("*.md")):
                    print(f"     - {p.stem}", file=sys.stderr)
                sys.exit(1)
        else:
            print("❌ --prompt requires a name (e.g., --prompt deep_research)", file=sys.stderr)
            sys.exit(1)
    
    transcript = " ".join(sys.argv[2:])
    
    # Inject prompt context if provided
    if prompt_context:
        transcript = f"[CONTEXT - Use these guidelines for the request below]\n\n{prompt_context}\n\n[END CONTEXT]\n\nUser's request: {transcript}"
    
    # Load config early for random feedback check
    load_config(mode)
    
    # Random feedback during normal operation (if enabled)
    if not collect_feedback:
        import random
        from config_loader import get_config_value, get_float
        random_enabled = get_config_value('FEEDBACK_RANDOM_ENABLED', 'false').lower() == 'true'
        random_chance = get_float('FEEDBACK_RANDOM_CHANCE', 0.0)  # 0.1 = 10%
        if random_enabled and random.random() < random_chance:
            collect_feedback = True
            if not json_only:
                print("🎲 Random feedback collection triggered")
    
    if not json_only:
        from config_loader import get_config_value
        
        print(f"🎯 Processing: '{transcript}'")
        print(f"📡 Mode: {mode}")
        
        # Show provider/model being used
        if mode == "cloud":
            provider = get_config_value("LLM_PROVIDER", "anthropic")
            if provider == "openai":
                model = get_config_value("OPENAI_MODEL", get_provider_fallback_model("openai"))
            elif provider == "xai":
                model = get_config_value("XAI_MODEL", get_provider_fallback_model("xai"))
            elif provider == "ollama":
                from ollama_utils import resolve_ollama_model
                model = resolve_ollama_model(mode)
            else:
                model = get_config_value("ANTHROPIC_MODEL", get_provider_fallback_model("anthropic"))
            print(f"🤖 Provider: {provider}  Model: {model}")
        else:
            from ollama_utils import resolve_ollama_model
            model = resolve_ollama_model(mode)
            print(f"🤖 Model: {model}")
        
        print("=" * 60)

    # Optional tool exclusions for unattended harnesses like self-play.
    excluded_tools = []
    excluded_tools_env = os.environ.get("JARVIS_SELF_PLAY_EXCLUDED_TOOLS") or os.environ.get("JARVIS_EXCLUDED_TOOLS", "")
    if excluded_tools_env:
        excluded_tools = [tool.strip() for tool in excluded_tools_env.split(",") if tool.strip()]
    
    orch = Orchestrator(mode)
    result = orch.process(transcript, excluded_tools=excluded_tools)
    
    # Collect feedback if requested
    if collect_feedback:
        from feedback import FeedbackCollector
        from config_loader import get_config_value
        
        if not json_only:
            print("\n" + "=" * 60)
            print("🔍 COLLECTING FEEDBACK (LLM-as-QA Mode)")
            print("=" * 60)
        
        collector = FeedbackCollector(mode)
        
        # Get tools used from result
        tools_used = result.get("tools_used", [])
        if isinstance(tools_used, str):
            tools_used = [tools_used]
        
        num_tools = len(orch.registry.list_tools())
        
        # Get the ACTUAL system prompt from router (it's a property)
        system_prompt = orch.router.system_prompt if hasattr(orch.router, 'system_prompt') else None
        
        # @TOOL_CONFIG: feedback relevant tools — keyword-to-tool mapping for explicit feedback
        tool_descriptions = {}
        relevant_tools = set(tools_used)
        query_lower = transcript.lower()
        if "time" in query_lower:
            relevant_tools.add("get_time")
        if "weather" in query_lower:
            relevant_tools.add("weather")
        if "bitcoin" in query_lower or "crypto" in query_lower or "price" in query_lower:
            relevant_tools.add("crypto_price")
        if "memory" in query_lower or "remember" in query_lower:
            relevant_tools.update(["semantic_recall", "search_memory", "remember"])
        
        for tool_name in relevant_tools:
            try:
                tool = orch.registry.get_tool(tool_name)
                if tool:
                    tool_descriptions[tool_name] = tool.description
            except:
                pass
        
        # Get intelligence insights that were used (if available)
        intelligence_insights = result.get("intelligence_context", "Intelligence insights not captured in result.")
        
        # Build config context with EXPLANATIONS for style modes
        response_style = get_config_value('JARVIS_RESPONSE_STYLE', 'auto')
        qa_word_limit = int(get_config_value('JARVIS_QA_WORD_LIMIT', str(DEFAULT_JARVIS_QA_WORD_LIMIT)))
        multi_turn_word_limit = int(get_config_value('JARVIS_MULTI_TURN_WORD_LIMIT', str(DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT)))
        
        # Explain what the style means so feedback LLM doesn't penalize correct behavior
        style_explanations = {
            'casual': f'Short voice-friendly output. Tool confirmations stay at 35 words max, Q&A is capped at {qa_word_limit}, multi-turn summaries at {multi_turn_word_limit}.',
            'auto': f'Smart mode. Search tools get condensed (no URLs), complex tools keep full details. Q&A cap is {qa_word_limit}, multi-turn cap is {multi_turn_word_limit}.',
            'detailed': 'FULL LLM response preserved. URLs ARE INCLUDED. Verbose output is EXPECTED and CORRECT.'
        }
        style_explanation = style_explanations.get(response_style, 'Unknown style')
        
        if orch.auto_context_enabled:
            interface_line = f"Interface: cli/voice (auto-context enabled, last {orch.auto_context_window} conversations within {orch.auto_context_minutes} minutes)"
        else:
            interface_line = "Interface: cli/voice (no prior conversation context)"
        
        config_context = f"""
{interface_line}
Auto-Context: {'Enabled' if orch.auto_context_enabled else 'Disabled'} (window={orch.auto_context_window}, minutes={orch.auto_context_minutes})
Response Style: {response_style}
  → Style Behavior: {style_explanation}
  → DO NOT penalize verbose output or URLs if style is 'detailed' - that's CORRECT behavior!
Tools Available: {num_tools}
Mode: {mode}
"""
        
        feedback = collector.collect(
            query=transcript,
            result=result,
            tools_used=tools_used,
            num_tools=num_tools,
            system_prompt=system_prompt,
            tool_descriptions=tool_descriptions,
            intelligence_insights=intelligence_insights,
            config_context=config_context,
            session_id=orch.session_id
        )
        
        # Add feedback to result
        result["feedback"] = feedback
        
        # ============================================
        # FEEDBACK → INTELLIGENCE BRIDGE
        # Update experience outcome based on feedback rating
        # ============================================
        rating = feedback.get('rating')
        experience_id = result.get('experience_id', -1)
        
        if rating is not None and experience_id > 0:
            from intelligence_hooks import update_experience_from_feedback
            updated = update_experience_from_feedback(
                experience_id=experience_id,
                feedback_rating=rating,
                feedback_summary=feedback.get('summary'),
                feedback_details={
                    'positive': feedback.get('positive', ''),
                    'issues': feedback.get('issues', []),
                    'suggestions': feedback.get('suggestions', []),
                    'tool_ratings': feedback.get('tool_ratings', {}),
                    'analysis': feedback.get('analysis', ''),
                }
            )
            if updated and rating <= 2 and not json_only:
                print(f"🔄 Intelligence corrected: experience {experience_id} marked as FAILURE (rating {rating})")
        
        if not json_only:
            print(f"\n📊 Feedback Rating: {feedback.get('rating', 'N/A')}/5")
            print(f"📝 Summary: {feedback.get('summary', 'No summary')}")
            
            if feedback.get('issues'):
                print("\n⚠️  Issues Found:")
                for issue in feedback['issues']:
                    print(f"   [{issue.get('category', 'other')}] {issue.get('description', 'No description')}")
                    if issue.get('suggestion'):
                        print(f"      💡 Suggestion: {issue['suggestion']}")
            
            if feedback.get('positive'):
                print(f"\n✅ What Worked: {feedback['positive']}")
            
            print(f"\n📁 Feedback logged to: logs/feedback/feedback-{datetime.now().strftime('%Y-%m-%d')}.jsonl")
    
    if json_only:
        # Output only JSON for scripting
        print(json.dumps(result))
    else:
        # Pretty output for human viewing
        print("=" * 60)
        
        # Display thinking if present and not in JSON mode
        if result.get("thinking") and debug_thinking:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
            from thinking import format_thinking_display
            print(format_thinking_display(result["thinking"]))
        
        print(f"🗣️  Speech Output: {result['speech']}")
        print(f"✓  Status: {'✅ OK' if result['ok'] else '❌ Failed'}")
        
        # Show usage info with cache metrics (cloud mode only)
        if result.get("usage") and mode == "cloud":
            usage = result["usage"]
            print(f"\n💰 Token Usage:")
            print(f"   Input: {usage.get('input_tokens', 0):,} tokens")
            print(f"   Output: {usage.get('output_tokens', 0):,} tokens")
            
            # Show cache metrics if available
            cache_read = usage.get('cache_read_tokens', 0)
            cache_write = usage.get('cache_creation_tokens', 0)
            
            if cache_read > 0:
                print(f"   💾 Cache READ: {cache_read:,} tokens (90% cheaper!)")
                print(f"   💵 Cache read cost: ${usage.get('cache_read_cost_usd', 0):.4f}")
                savings = usage.get('cache_savings_usd', 0)
                if savings > 0:
                    print(f"   ✅ Saved: ${savings:.4f}")
            if cache_write > 0:
                print(f"   💾 Cache WRITE: {cache_write:,} tokens (first request)")
                print(f"   💵 Cache write cost: ${usage.get('cache_write_cost_usd', 0):.4f}")
            
            print(f"   💵 Total Cost: ${usage.get('cost_usd', 0):.4f}")
        
        if result.get("data"):
            print(f"\n📊 Data: {json.dumps(result['data'], indent=2)}")
        
        print("\n📄 Full Response:")
        print(json.dumps(result, indent=2))
    
    # Speak the result if --speak flag was provided
    if speak_result and result.get("speech"):
        import subprocess
        project_root = Path(__file__).parent.parent
        say_script = project_root / "bin" / ("say.sh" if mode == "cloud" else "say-local.sh")
        
        if not json_only:
            print(f"\n🔊 Speaking result via {say_script.name}...")
        
        try:
            safe_speech = sanitize_for_speech(result["speech"])
            if safe_speech:
                subprocess.run([str(say_script), safe_speech], check=False)
        except Exception as e:
            print(f"⚠️ TTS failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
