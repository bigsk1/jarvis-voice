#!/usr/bin/env python3
"""
Jarvis Voice Assistant - Main Orchestrator (v2)
Enhanced with LLM-based routing and confirmation flow.
"""
import os
import sys
import json
import time
from pathlib import Path
from typing import Any
from datetime import datetime
from zoneinfo import ZoneInfo

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_int, get_float, get_config_value
from memory_db import get_memory_db
from status_updater import StatusUpdater
from security_utils import sanitize_for_speech

from router_v2 import LLMRouter
from executor import ToolExecutor
from workflow_loader import WorkflowLoader
from pipeline_executor import PipelineExecutor


def _sanitize_error_for_speech(error) -> str:
    """Convert error to speech-friendly format."""
    # Handle list input
    if isinstance(error, list):
        error = str(error[0]) if error else "Unknown error"
    error = str(error)
    """
    Sanitize technical error messages for voice output.
    Removes URLs, IPs, session IDs, and simplifies to user-friendly messages.
    """
    import re
    
    if not error:
        return "an unknown error occurred"
    
    error_lower = error.lower()
    
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


class Orchestrator:
    """Main orchestration with LLM-based routing, error recovery, and retry logic."""
    
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
        
        # Auto-sync memory database from other mode if needed
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
        self.executor = ToolExecutor(mode, registry=self.registry)
        self.max_retries = 1  # Maximum retry attempts
        
        # Workflow orchestration (explicit commands like /research, /note)
        self.workflow_loader = WorkflowLoader(explicit_only=True)
        self.pipeline_executor = PipelineExecutor(mode, self.executor)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")  # Unique session ID
        self.timezone = ZoneInfo(get_config_value("JARVIS_TIMEZONE", "America/Los_Angeles"))
        
        # Auto-context configuration
        self.auto_context_enabled = get_config_value('AUTO_CONTEXT_ENABLED', 'true').lower() == 'true'
        self.auto_context_window = get_int('AUTO_CONTEXT_WINDOW', 3)
        self.auto_context_minutes = get_int('AUTO_CONTEXT_MINUTES', 10)
        
        # Status updates for voice progress feedback
        self.status_updater = StatusUpdater(mode)
        
        # Progress callback for real-time tool execution events (WebSocket)
        self.progress_callback = None
        # Cancel check callback - returns True if processing should be cancelled
        self.cancel_check = None
        # Web conversation ID for tracking web UI chat sessions (stored in metadata)
        self.web_conversation_id = None
    
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
    
    def set_cancel_check(self, callback):
        """Set callback to check if processing should be cancelled.
        
        Callback should return True if cancellation is requested.
        Checked between turns and before tool execution.
        """
        self.cancel_check = callback
    
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
        if self.progress_callback:
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
            "crypto_price": 60,
            "stock_price": 60,
            "weather": 600,
            "get_time": 30,
        }
        return ttl_map.get(tool_name)

    def _safe_iso_to_local_datetime(self, iso_text: str):
        """Parse ISO timestamp string and normalize to local timezone."""
        if not iso_text:
            return None
        try:
            dt = datetime.fromisoformat(str(iso_text).replace("Z", "+00:00"))
            if getattr(dt, "tzinfo", None) is None:
                return dt.replace(tzinfo=self.timezone)
            return dt.astimezone(self.timezone)
        except Exception:
            return None

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

    def _extract_primary_lookup_key(self, tool_name: str, arguments: dict | None) -> str | None:
        """Extract primary lookup key from common live-data tools."""
        if not isinstance(arguments, dict):
            return None
        if tool_name == "crypto_price":
            v = arguments.get("coin")
            return str(v).strip().lower() if v is not None else None
        if tool_name == "stock_price":
            v = arguments.get("symbol")
            return str(v).strip().upper() if v is not None else None
        if tool_name == "weather":
            v = arguments.get("location")
            return str(v).strip().lower() if v is not None else None
        return None

    def _query_explicitly_requests_refresh(self, transcript: str) -> bool:
        """Detect explicit user intent to refresh/recheck live data."""
        text = (transcript or "").lower()
        refresh_terms = [
            "refresh", "recheck", "check again", "update", "updated",
            "latest again", "run again", "try again", "re-run", "rerun"
        ]
        return any(term in text for term in refresh_terms)

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
            qa_word_limit = int(get_config_value('JARVIS_QA_WORD_LIMIT', '75'))
            multi_turn_word_limit = int(get_config_value('JARVIS_MULTI_TURN_WORD_LIMIT', '50'))
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
                        feedback_summary=feedback.get('summary')
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
                tool_overrides: dict[str, dict] | None = None) -> dict[str, Any]:
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
                # Could add to a security audit log here
                pass
        except ImportError:
            # security_utils not available, continue without sanitization
            pass
        
        # Store tool overrides for this request
        self._tool_overrides = tool_overrides or {}
        
        # Reset status updater for new task
        self.status_updater.reset()
        
        # Check for explicit workflow commands (e.g., /research, /note, /health)
        # These bypass normal LLM routing and execute a predefined pipeline
        workflow_result = self._try_workflow(transcript)
        if workflow_result:
            return workflow_result
        
        # Auto-inject recent conversation context
        if conversation_history:
            # Use provided conversation history (from web app)
            enhanced_transcript = self._format_conversation_context(transcript, conversation_history)
        elif self.auto_context_enabled:
            # Fall back to memory_db auto_context (terminal/TUI mode)
            enhanced_transcript = self._build_conversation_context(transcript)
        else:
            enhanced_transcript = transcript
        
        # Debug: Show what's being sent to LLM
        if os.environ.get('JARVIS_DEBUG') and enhanced_transcript != transcript:
            print("\n" + "="*80, file=sys.stderr)
            print("DEBUG: Enhanced Transcript Being Sent to LLM:", file=sys.stderr)
            print("="*80, file=sys.stderr)
            print(enhanced_transcript, file=sys.stderr)
            print("="*80 + "\n", file=sys.stderr)
        
        # Pre-fetch available tool names for insight filtering
        # This ensures insights about blocked/unavailable tools aren't shown
        try:
            from memory_db import get_memory_db
            db = get_memory_db()
            available_tool_names = db.get_enabled_tool_names() if hasattr(db, 'get_enabled_tool_names') else []
        except Exception:
            available_tool_names = []  # Fallback: no filtering
        
        # Auto-inject relevant memories (semantic search + recency weighting)
        # Works for CLI, WebUI, wake word - all go through orchestrator.process()
        memory_context = self._get_relevant_memories(transcript)
        if memory_context:
            enhanced_transcript = f"{memory_context}\n\n{enhanced_transcript}"
        
        # Inject learned insights from self-learning intelligence
        learning_context, applied_insights = self._get_learning_insights(transcript, available_tool_names)
        if learning_context:
            enhanced_transcript = f"{learning_context}\n\n{enhanced_transcript}"
        
        # Multi-turn context tracking
        max_turns = get_int('MAX_TOOL_TURNS', 15)  # Configurable, default 15 for deep research
        conversation_context = []
        tools_used = []
        accumulated_data = {}
        last_tool_call = None  # Track last tool to detect duplicates
        tool_call_counts = {}  # Track how many times each tool has been called (for progress events)
        
        # If retrying, augment transcript with error context
        if error_context and retry_count > 0:
            enhanced_transcript = f"{enhanced_transcript}\n\n===PREVIOUS ATTEMPT FAILED WITH ERROR===: {error_context}\nPlease try again with corrected parameters or check logs if needed."
        
        # Track usage info across all turns
        total_usage = {
            "input_tokens": 0, 
            "output_tokens": 0, 
            "cost_usd": 0.0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "cache_savings_usd": 0.0,
            "server_side_tools": {}  # Track xAI native search usage
        }
        
        # Track thinking from first turn (for display)
        first_thinking = None
        
        # Track available tools from first routing (for intelligence reflection)
        available_tools = []
        
        # Multi-turn loop
        for turn_num in range(max_turns):
            # Check for cancellation at start of each turn
            if self._is_cancelled():
                self._emit_progress('routing', message='Processing cancelled')
                return {
                    "ok": True,
                    "response": f"Processing stopped after {turn_num} turn(s). Results so far:\n\n" + 
                               (conversation_context[-1].get('summary', 'No results yet.') if conversation_context else 'No results yet.'),
                    "tools_used": tools_used,
                    "data": accumulated_data,
                    "usage_info": total_usage if any(total_usage.values()) else None,
                    "thinking": first_thinking,
                    "cancelled": True
                }
            
            # Build context for this turn
            if turn_num == 0:
                # First turn: use original transcript
                turn_input = enhanced_transcript
            else:
                # Subsequent turns: provide context from previous tools
                turn_input = self._build_turn_context(enhanced_transcript, conversation_context)
            
            # Inject turn limit awareness (helps LLM prioritize finishing critical tasks)
            turns_remaining = max_turns - turn_num
            if turns_remaining <= 5:
                # Warn when getting close to limit
                turn_input = f"[TURN {turn_num + 1}/{max_turns} - {turns_remaining} turns remaining. Prioritize finishing critical tasks like canvas/remember before limit!]\n\n{turn_input}"
            elif turn_num > 0:
                # Lighter context for middle turns
                turn_input = f"[Turn {turn_num + 1}/{max_turns}]\n\n{turn_input}"
            
            # Route using LLM
            if os.environ.get('JARVIS_DEBUG'):
                print(f"DEBUG: About to route turn {turn_num}", file=sys.stderr)
            route = self.router.route(turn_input, excluded_tools=excluded_tools)
            if os.environ.get('JARVIS_DEBUG'):
                print(f"DEBUG: Routing complete, intent={route.get('intent')}", file=sys.stderr)
            
            # Accumulate usage info if available
            if route.get("usage_info"):
                usage = route["usage_info"]
                if usage.get("input_tokens"):
                    total_usage["input_tokens"] += usage["input_tokens"]
                if usage.get("output_tokens"):
                    total_usage["output_tokens"] += usage["output_tokens"]
                if usage.get("cost_usd"):
                    total_usage["cost_usd"] += usage["cost_usd"]
                # Accumulate cache metrics
                if usage.get("cache_creation_tokens"):
                    total_usage["cache_creation_tokens"] += usage["cache_creation_tokens"]
                if usage.get("cache_read_tokens"):
                    total_usage["cache_read_tokens"] += usage["cache_read_tokens"]
                if usage.get("cache_savings_usd"):
                    total_usage["cache_savings_usd"] += usage["cache_savings_usd"]
                # Accumulate xAI server-side tools usage
                if usage.get("server_side_tools"):
                    for tool_name, count in usage["server_side_tools"].items():
                        total_usage["server_side_tools"][tool_name] = total_usage["server_side_tools"].get(tool_name, 0) + count
            
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
                is_exact_duplicate = last_tool_call and last_tool_call == current_call
                is_fresh_same_target_recall = self._is_fresh_same_target_recall(
                    transcript, tool_name, arguments, conversation_context
                )
                
                # @TOOL_CONFIG: single-call cap — expensive tools limited to 1 successful call per request
                # These are slow (30-120s), costly, and the LLM tends to loop when
                # the result doesn't match expectations (e.g. duration ignored by provider)
                # NOTE: failures don't hit this — they go through recursive retry with fresh counts
                SINGLE_CALL_TOOLS = {
                    'generate_video', 'generate_image', 'generate_music',
                    'send_email',
                }
                is_over_cap = (
                    tool_name in SINGLE_CALL_TOOLS
                    and tool_call_counts.get(tool_name, 0) >= 1
                )
                
                if is_exact_duplicate or is_over_cap or is_fresh_same_target_recall:
                    if is_exact_duplicate:
                        reason = "exact duplicate"
                    elif is_over_cap:
                        reason = f"{tool_name} already called (max 1)"
                    else:
                        reason = f"{tool_name} already has fresh result for same target"
                    if sys.stdout.isatty():
                        print(f"⚠️  Duplicate/capped tool call detected: {tool_name} ({reason})")
                        print(f"   Forcing Q&A mode to synthesize results")
                    
                    # Generate intelligent summary using accumulated data (not just tool list!)
                    # This ensures the user gets actual research results, not just "I used tools"
                    final_speech = self._synthesize_duplicate_prevented_response(
                        transcript, tools_used, accumulated_data, conversation_context
                    )
                    
                    self._log_conversation(transcript, final_speech, tools_used, success=True)
                    
                    # Mark status updates complete
                    self.status_updater.mark_complete()
                    
                    return {
                        "speech": final_speech,
                        "ok": True,
                        "tools_used": tools_used,
                        "data": accumulated_data,
                        "duplicate_prevented": True
                    }
                
                last_tool_call = current_call
                
                # Only print if in interactive mode
                if sys.stdout.isatty():
                    turn_marker = f" (turn {turn_num + 1})" if turn_num > 0 else ""
                    print(f"🔧 Executing tool: {tool_name}{turn_marker}")
                    print(f"📝 Arguments: {json.dumps(arguments, indent=2)}")
                
                # Status update before tool execution
                self.status_updater.set_turn(turn_num + 1)
                
                # @TOOL_CONFIG: status update categories — route tools to UI status messages
                if tool_name == 'opencode':
                    # OpenCode is long-running - start background updates
                    self.status_updater.update(category='building', tool_name=tool_name)
                    self.status_updater.start_background_updates(tool_name=tool_name, category='building')
                elif 'search' in tool_name or 'brave' in tool_name:
                    self.status_updater.update(category='searching', tool_name=tool_name)
                elif 'fetch' in tool_name or 'playwright' in tool_name:
                    self.status_updater.update(category='fetching', tool_name=tool_name)
                elif tool_name == 'weather':
                    self.status_updater.update(category='fetching', tool_name=tool_name)
                elif 'memory' in tool_name or 'recall' in tool_name:
                    # Memory tools are fast, skip status
                    pass
                elif turn_num >= 2:
                    # Multi-turn progress
                    self.status_updater.update(category='multi_turn', tool_name=tool_name)
                else:
                    # Default: acknowledge any other tool at first turn
                    if turn_num == 0:
                        self.status_updater.update(category='task_start', tool_name=tool_name)
                
                # Check for cancellation before executing tool
                if self._is_cancelled():
                    self._emit_progress('routing', message='Processing cancelled')
                    return {
                        "ok": True,
                        "response": f"Stopped before {tool_name}. Results so far:\n\n" + 
                                   (conversation_context[-1].get('summary', 'No results yet.') if conversation_context else 'No results yet.'),
                        "tools_used": tools_used,
                        "data": accumulated_data,
                        "usage_info": total_usage if any(total_usage.values()) else None,
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
                    conversation_context.append({
                        "tool": tool_name,
                        "arguments": arguments,
                        "result": result,  # Store full result, not just data
                        "speech": result.get("speech", ""),
                        "meta": {
                            "executed_at_iso": executed_at.isoformat(),
                            "executed_at_local": executed_at.strftime("%Y-%m-%d %H:%M:%S %Z"),
                            "freshness": "live_tool_call",
                            "ttl_seconds": ttl_seconds,
                            "source": source_hint,
                            "authoritative_live": ttl_seconds is not None
                        }
                    })
                    
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
                    self.status_updater.update_error(
                        error_type='server' if is_server_error else 'retry',
                        error_message=error,
                        is_server_error=is_server_error
                    )
                    
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
                        
                        # Recursive retry with error context
                        return self.process(transcript, retry_count + 1, error_context)
                    
                    # Max retries exceeded - sanitize error for voice output
                    friendly_error = _sanitize_error_for_speech(error)
                    final_speech = f"{speech}. {friendly_error.capitalize()}. I tried {retry_count + 1} time(s) but couldn't complete the task."
                    
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
                        "retries": retry_count
                    }
            
            # Handle Q&A (task complete - LLM decided to respond directly)
            elif route["intent"] == "qa":
                # Status update: near complete (if tools were used)
                if tools_used:
                    self.status_updater.update(category='near_complete')
                
                # @TOOL_CONFIG: direct speech bypass — tools whose speech is used as-is (LLM won't reformat)
                DIRECT_SPEECH_TOOLS = {'status_recap', 'generate_music', 'phone_call'}
                last_tool = tools_used[-1] if tools_used else None
                use_direct_speech = False
                
                if last_tool in DIRECT_SPEECH_TOOLS and conversation_context:
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
                
                # Auto-log conversation with all tools used and usage info
                token_info = total_usage if total_usage["cost_usd"] > 0 else None
                self._log_conversation(transcript, speech, tools_used, success=True, token_info=token_info)
                
                # Build response
                response = {
                    "speech": speech,
                    "raw_llm_response": raw_speech,  # Original LLM response before voice formatting
                    "ok": True,
                    "tools_used": tools_used,
                    "data": accumulated_data,
                    "available_tools": available_tools  # Tools LLM could choose from
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
            "max_turns_reached": True
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
                # Heuristic for payload-like snippets
                if s.count("{") >= 2 and s.count(":") >= 3:
                    return True
                return False

            # If we already have clear tool speech, prefer it over re-synthesis.
            # This avoids hallucinated contradictions when duplicate prevention triggers.
            if conversation_context:
                last_ctx = conversation_context[-1]
                last_result = last_ctx.get("result", {}) if isinstance(last_ctx, dict) else {}
                last_speech = (
                    (last_result or {}).get("speech")
                    or last_ctx.get("speech")
                    or ""
                )
                if (
                    isinstance(last_speech, str)
                    and last_speech.strip()
                    and not _is_machine_like_speech(last_speech)
                ):
                    return last_speech.strip()

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
1. MAX 100 WORDS - but ACTUALLY ANSWER the user's question
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
                system_prompt="Synthesize research results into a helpful answer. MAX 100 words. Answer the user's actual question using the data provided."
            )
            return response.strip()
            
        except Exception as e:
            # Fallback: still try to be useful
            if sys.stdout.isatty():
                print(f"⚠️ Failed to synthesize duplicate response: {e}", file=sys.stderr)
            
            # Better fallback than just "I used X tools"
            if "canvas" in [t.lower() for t in tools_used]:
                return "Research complete and saved to Canvas. Check the Canvas page for full details on your request."
            else:
                tools_summary = ', '.join(set(tools_used))
                return f"Task completed using {tools_summary}. Please check the results above."

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
        try:
            # Extract relevant data
            data = tool_result.get("data", {})
            
            # Build context for LLM
            context = f"""User asked: "{user_query}"

Tool executed: {tool_name}
Tool result: {json.dumps(data, indent=2)}

Create a short response for voice output (spoken through speakers).

CRITICAL RULES:
1. MAX 35 WORDS for tool confirmations
2. Answer directly, no greetings or confirmations
3. No emojis, no markdown, no numbered lists
4. Don't say URLs unless critical
5. If a tool failed and you are unable to resolve, say so and the reason why it failed.

GOOD EXAMPLES:
- "Bitcoin is $101,938, down 1% today"
- "Found 3 webhook memories: URL, logger, and port"
- "Time is 11:51 PM Wednesday"
- "Server is up and running started on localhost port 5001"

ERROR EXAMPLES:
- "Webhook failed to send: 404 Not Found"
- "Network error sending webhook: Connection timed out"
- "Unable to create reminder: invalid time format"
- "Server error: -> error message summarized"

BAD EXAMPLES:
- "Great! I've successfully looked up the time for you. It's currently 11:51 PM..."
- "Perfect! The webhook has been sent and here's what happened..."

Your response:"""
            
            # Get natural response from LLM (without tools)
            text_response, _, _ = self.router.provider.chat_with_tools(
                messages=[{"role": "user", "content": context}],
                tools=[],  # No tools for response formatting
                system_prompt="You are a voice assistant. Output a concise response, MAX 35 words. No greetings, no explanations."
            )
            
            if text_response:
                return text_response
            else:
                return tool_result.get("speech", "Done")
            
        except Exception as e:
            # Fallback to tool's built-in speech
            if sys.stdout.isatty():
                print(f"⚠️ Failed to format natural response: {e}", file=sys.stderr)
            return tool_result.get("speech", "Completed")
    
    def _format_auto_mode(self, user_query: str, tools_used: list, accumulated_data: dict, raw_response: str, turn_num: int) -> str:
        """
        Smart auto mode: Adapt response formatting based on tool type and complexity.
        
        FLOW:
        - Multi-turn (turn_num > 0) → ALWAYS uses _format_multi_turn_summary() for ALL tools
        - Single-turn (turn_num == 0) → Checks tool category to decide formatting:
          - SEARCH_TOOLS → Condense (remove URLs, summarize)
          - SIMPLE_TOOLS → Keep if short (<25 words), condense if longer
          - COMPLEX_TOOLS → Keep detailed if long (>50 words), condense if short
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
        try:
            # Multi-turn: always format (could be complex)
            if turn_num > 0:
                return self._format_multi_turn_summary(user_query, tools_used, accumulated_data, raw_response)
            
            # Single-turn: decide based on tool type
            if not tools_used:
                # Pure Q&A, no tools - keep short
                return self._format_single_turn_casual(user_query, raw_response)
            
            tool_name = tools_used[0] if tools_used else ""
            
            # @TOOL_CONFIG: response formatting categories — controls how tool output is spoken
            SEARCH_TOOLS = [
                'search_memory', 'semantic_recall', 'recall', 'search_conversations',
                'mcp_brave_search',  # Matches all brave search variants (web, local, news, image, video)
                'mcp_fetch'  # Matches mcp_fetch_fetch
            ]
            SIMPLE_TOOLS = ['get_time', 'crypto_price', 'get_weather']
            COMPLEX_TOOLS = ['opencode', 'execute_bash', 'send_webhook', 'api_call']
            
            # Search tools: Format for voice (remove URLs, summarize)
            if any(search in tool_name.lower() for search in SEARCH_TOOLS):
                # Format search results - remove URLs, keep key info
                return self._format_single_turn_casual(user_query, raw_response)
            
            # Simple data tools: Already concise, keep as-is or condense slightly
            elif any(simple in tool_name.lower() for simple in SIMPLE_TOOLS):
                # If already short (<25 words), keep it
                word_count = len(raw_response.split())
                if word_count <= 25:
                    return raw_response
                # Otherwise condense
                return self._format_single_turn_casual(user_query, raw_response)
            
            # Complex/build tools: Check if response is technical or simple
            elif any(complex in tool_name.lower() for complex in COMPLEX_TOOLS):
                # If response is very long (>50 words), it's probably detailed - keep detailed
                word_count = len(raw_response.split())
                if word_count > 50:
                    # GAP: This bypasses stash/URL stripping rules in _format_single_turn_casual()
                    # If opencode/bash returns stash:// refs in long response, they'd be spoken.
                    # For now acceptable since complex tools rarely output stash refs directly.
                    # TODO: Consider post-processing to strip stash:// even for detailed mode.
                    return raw_response  # Keep detailed for complex operations
                else:
                    # Short response for complex tool - condense it
                    return self._format_single_turn_casual(user_query, raw_response)
            
            # Default: condensed formatting for voice
            else:
                return self._format_single_turn_casual(user_query, raw_response)
                
        except Exception as e:
            if sys.stdout.isatty():
                print(f"⚠️ Auto mode formatting failed: {e}", file=sys.stderr)
            # Fallback to raw response
            return raw_response
    
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
        qa_limit = int(get_config_value('JARVIS_QA_WORD_LIMIT', '75'))
        try:
            # Get configurable word limit for Q&A (default 75)
            
            # If already within limit, return as-is
            word_count = len(raw_response.split())
            if word_count <= qa_limit:
                return raw_response
            
            # Use LLM to condense verbose response
            context = f"""User asked: "{user_query}"

Your previous response: {raw_response}

Condense this for voice output (MAX {qa_limit} words).

RULES:
1. Keep the core answer with key details
2. Remove: greetings, emojis, markdown, numbered lists
3. For informational queries, include enough context to be useful
4. No URLs unless critical
5. NEVER drop named entities - movie titles, restaurant names, product names, people's names MUST be preserved
6. If user asked for specific items (top 3, best restaurants, etc.), include those by name
7. NEVER speak stash:// references (e.g., stash://space_xxx/f_xxx) - just say "saved to stash" or "image saved"
8. NEVER speak long URLs (>30 chars) - summarize as "link saved" or mention domain only (e.g., "on Wikipedia")
9. Simplify file paths (/home/user/...) to just the filename
10. NEVER speak auto-generated filenames (e.g., "generated_modify_the_previous_20260209.png") - just say "saved" or "saved to stash"

EXAMPLES:
Verbose: "Great! I've looked up ntfy. It's an open-source push notification service that lets you..."
Condensed: "Ntfy is an open-source push notification service. Self-hosted setup needs TLS certs for iOS APNs. Without proper HTTPS, it falls back to battery-draining polling. Use Caddy or nginx for auto-TLS."

BAD (drops entities): "Found several restaurants nearby including one Italian and one Thai option."
GOOD (preserves entities): "Top restaurants nearby: Olive Garden for Italian, Thai Orchid for Thai, and Red Robin for burgers."

Your condensed response:"""
            
            response = self.router.provider.chat(context, system_prompt=f"Condense for voice output. MAX {qa_limit} words. Keep key info. No greetings/emojis.")
            return response.strip()
        except Exception as e:
            # Fallback: truncate at limit
            if sys.stdout.isatty():
                print(f"⚠️ Failed to condense response: {e}", file=sys.stderr)
            words = raw_response.split()
            if len(words) > qa_limit:
                return ' '.join(words[:qa_limit]) + '...'
            return raw_response
    
    def _format_multi_turn_summary(self, user_query: str, tools_used: list, accumulated_data: dict, llm_response: str) -> str:
        """
        Format multi-turn (multiple tools) results for voice output.
        Uses JARVIS_MULTI_TURN_WORD_LIMIT (default: 50 words).
        
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
            Concise voice-friendly summary (50 words max by default)
        """
        multi_turn_limit = int(get_config_value('JARVIS_MULTI_TURN_WORD_LIMIT', '50'))
        try:
            # Get configurable word limit for multi-turn (default 50)
            
            # Use LLM to create a concise voice summary
            # Calculate dynamic truncation - more data for repeated tools (arrays)
            has_arrays = any(isinstance(v, list) for v in accumulated_data.values())
            max_chars = 2000 if has_arrays else 800
            
            # Include BOTH: LLM's synthesized response (has extracted names) AND raw tool data (has structured info)
            # This ensures we don't lose either source of truth
            context = f"""User asked: "{user_query}"

Tools executed: {', '.join(tools_used)}

LLM's detailed answer (USE NAMES FROM HERE):
{llm_response[:1200]}

Raw tool data (backup for numbers/details):
{json.dumps(accumulated_data, indent=2)[:max_chars]}

Condense into a voice-friendly summary (will be spoken aloud through speakers).

RULES:
1. MAX {multi_turn_limit} WORDS
2. PRESERVE all named entities (restaurant names, movie titles, business names, people) - copy them exactly
3. PRESERVE key numbers (prices, temperatures, percentages, ratings)
4. No emojis, no markdown, no bullet points, no explanations of what tools did
5. If user asked for "top 3" items, include all 3 by name
6. NEVER speak stash:// references (e.g., stash://space_xxx/f_xxx) - just say "saved to stash" or "image generated"
7. NEVER speak long URLs (>30 chars) - summarize as "link saved" or mention domain only
8. Simplify file paths (/home/user/project/file.py) to just the filename (file.py)
9. NEVER speak auto-generated filenames (e.g., "generated_modify_the_previous_20260209.png") - just say "saved" or "saved to stash"

GOOD: "Top 3 date night spots: Copper River, BJ's Brewhouse, Thirsty Lion. Tonight: 47°F clear."
GOOD: "Image generated and saved to stash." (NOT "Image saved to stash://space_20260201_xxx/f_abc")
BAD: "[Names from results]" or "Found 3 options" ← Never use placeholders!

Your response:"""
            
            response = self.router.provider.chat(context, system_prompt=f"Condense to MAX {multi_turn_limit} words. Preserve names, titles, and numbers exactly. No placeholders.")
            return response.strip()
        except Exception as e:
            # Fallback to LLM's original response
            if sys.stdout.isatty():
                print(f"⚠️ Failed to format multi-turn summary: {e}", file=sys.stderr)
            return llm_response
    
    def _format_max_turns_summary(self, user_query: str, tools_used: list, accumulated_data: dict, max_turns: int) -> str:
        """
        Create intelligent summary when max turns is reached.
        BEST EFFORT MODE: Extract and present whatever useful data was gathered.
        
        Args:
            user_query: Original user request
            tools_used: List of tool names executed
            accumulated_data: Results from all tools
            max_turns: The limit that was hit
            
        Returns:
            Voice-friendly explanation of progress and next steps
        """
        try:
            # Extract useful data from accumulated results (especially for search arrays)
            extracted_data = self._extract_useful_data(accumulated_data)
            
            # Use LLM to create an intelligent progress summary
            context = f"""User asked: "{user_query}"

Tools executed ({len(tools_used)} actions): {', '.join(set(tools_used))}

ALL GATHERED DATA (BEST EFFORT - use this to answer!):
{extracted_data}

IMPORTANT: The task hit a complexity limit after {max_turns} tool calls. 
You MUST provide a BEST EFFORT answer using the data above.

CRITICAL RULES:
1. MAX 50 WORDS - but ACTUALLY ANSWER the question!
2. If you found ANY relevant info (movie titles, prices, names, etc.) - INCLUDE IT
3. Don't apologize or say "couldn't find" - give the best answer you can
4. If data is incomplete, answer what you CAN and note what's missing briefly
5. NEVER say "hit limit" or mention tool counts

GOOD BEST-EFFORT EXAMPLES:
- "Top movies at Regal Hillsboro: Wicked, Avatar Fire and Ash, Zootopia 2. Check fandango.com for exact showtimes."
- "Bitcoin $90k, Solana $143, Ethereum $3k - all up 2-3% today"
- "Found theaters: Regal Evergreen Parkway, AMC Progress Ridge. Current showtimes require checking their websites directly."

BAD EXAMPLES (never do this):
- "I searched 10 times but couldn't find..." (WRONG - use what you found!)
- "Hit complexity limit after 10 tools..." (WRONG - don't mention technical limits!)
- "Unable to find showtimes" (WRONG - at least mention the theaters/movies you DID find!)

Your BEST EFFORT response:"""
            
            response = self.router.provider.chat(context, system_prompt="You are a voice assistant. Provide a BEST EFFORT answer using whatever data you have. MAX 50 words. ALWAYS include any useful info you found - movie titles, theater names, prices, etc.")
            return response.strip()
        except Exception as e:
            # Fallback to simple message
            if sys.stdout.isatty():
                print(f"⚠️ Failed to format max turns summary: {e}", file=sys.stderr)
            return f"Completed {len(tools_used)} actions but reached the complexity limit. Tools used: {', '.join(tools_used)}. Please review or let me know if you'd like me to continue."
    
    def _extract_useful_data(self, accumulated_data: dict) -> str:
        """
        Extract the most useful/relevant data from accumulated tool results.
        Handles arrays (repeated tool calls) and extracts titles, descriptions, key info.
        
        Args:
            accumulated_data: Dict of tool_name -> result or [results]
            
        Returns:
            Formatted string of extracted useful data
        """
        extracted_parts = []
        
        def _extract_dict_fields(record: dict, depth: int = 0) -> list[str]:
            """
            Extract useful fields from nested tool data structures.
            Keeps output concise while preserving key entities and counts.
            """
            if not isinstance(record, dict) or depth > 2:
                return []

            info = []

            useful_fields = [
                'title', 'description', 'url', 'name', 'price',
                'coin', 'price_usd', 'speech', 'result', 'content',
                'count', 'status', 'status_filter', 'source', 'severity',
                'created_at', 'id'
            ]
            for field in useful_fields:
                if field in record and record[field] not in (None, "", [], {}):
                    info.append(f"{field}: {str(record[field])[:500]}")

            # Capture important nested lists like alerts/reminders/tasks/events.
            for list_key in ['alerts', 'reminders', 'items', 'results', 'tasks', 'events']:
                nested_list = record.get(list_key)
                if isinstance(nested_list, list) and nested_list:
                    info.append(f"{list_key}_count: {len(nested_list)}")
                    for nested in nested_list[:3]:
                        if isinstance(nested, dict):
                            title = nested.get('title') or nested.get('name') or nested.get('description')
                            if title:
                                info.append(f"{list_key}_item: {str(title)[:200]}")
                            for nested_field in ['status', 'severity', 'source', 'created_at', 'id']:
                                if nested_field in nested and nested[nested_field] not in (None, ""):
                                    info.append(f"{list_key}_{nested_field}: {str(nested[nested_field])[:200]}")
                        else:
                            info.append(f"{list_key}_item: {str(nested)[:200]}")

            # One-level nested dict extraction for common wrappers like data/report/payload.
            for nested_key in ['data', 'report', 'payload']:
                nested_dict = record.get(nested_key)
                if isinstance(nested_dict, dict):
                    info.extend(_extract_dict_fields(nested_dict, depth + 1)[:15])

            return info

        for tool_name, data in accumulated_data.items():
            # Handle arrays (multiple calls to same tool)
            if isinstance(data, list):
                items = data
            else:
                items = [data]
            
            tool_info = []
            for item in items:
                if isinstance(item, dict):
                    # Extract search results (brave search, fetch)
                    if 'raw' in item or 'full_text' in item:
                        # Parse search results - extract titles and descriptions
                        text = item.get('full_text', '')
                        if text:
                            # Extract first 2000 chars of each search result
                            tool_info.append(text[:2000])

                    # Extract specific and nested fields (alerts/reminders/etc.)
                    tool_info.extend(_extract_dict_fields(item))
                else:
                    # Plain string/value
                    tool_info.append(str(item)[:1000])
            
            if tool_info:
                extracted_parts.append(f"\n=== {tool_name} ===")
                extracted_parts.extend(tool_info[:5])  # Limit to 5 items per tool
        
        # Join and limit total size
        result = "\n".join(extracted_parts)
        return result[:10000]  # 10k chars should be enough for summary
    
    def _format_conversation_context(self, current_query: str, history: list) -> str:
        """
        Format provided conversation history as context for the LLM.
        Used by web app to pass its own conversation history.
        
        Args:
            current_query: User's current question/request
            history: List of previous messages [{role: str, content: str, tools_used: list, tool_results: dict}, ...]
            
        Returns:
            Enhanced query with conversation context
        """
        if not history:
            return current_query
        
        # Use all messages passed - the caller (chat.py) already applies history_limit setting
        # Don't truncate here to respect web UI's conversation.history_limit setting
        recent = history
        
        context_lines = ["=== RECENT CONVERSATION CONTEXT ==="]
        
        for msg in recent:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            tools_used = msg.get('tools_used', [])
            tool_results = msg.get('tool_results', {})
            
            # Truncate long messages
            if len(content) > 500:
                content = content[:500] + "..."
            
            prefix = "User" if role == 'user' else "Jarvis"
            
            # Include tools used for assistant messages (helps LLM know what was done)
            if role == 'assistant' and tools_used:
                # Dedupe tools (sometimes same tool called multiple times)
                unique_tools = list(dict.fromkeys(tools_used))
                tools_str = ", ".join(unique_tools)
                context_lines.append(f"{prefix} [tools: {tools_str}]: {content}")
                
                # Include tool result data for follow-up capability
                # This allows LLM to reference stash_refs, video_ids, providers for edits/remixes
                if tool_results:
                    for tool_name, result_data in tool_results.items():
                        if isinstance(result_data, dict):
                            # Format key fields concisely
                            fields = []
                            for k, v in result_data.items():
                                if v:  # Skip None/empty values
                                    fields.append(f"{k}={v}")
                            if fields:
                                context_lines.append(f"  └─ {tool_name} data: {', '.join(fields)}")
            else:
                context_lines.append(f"{prefix}: {content}")
        
        # If a previous message has uploaded_image with stash_ref, inject hint for follow-ups
        # (LLM was passing "image ID 1" instead of stash_ref, causing analyze_image to fail)
        for msg in recent:
            tr = msg.get('tool_results', {}) or {}
            ui = tr.get('uploaded_image', {}) if isinstance(tr, dict) else {}
            stash_ref = ui.get('stash_ref') if isinstance(ui, dict) else None
            if stash_ref and str(stash_ref).startswith('stash://'):
                context_lines.append("")
                context_lines.append("IMAGE RE-ANALYSIS: If the user asks to look again, correct, or re-identify the image: use analyze_image with image=\"" + str(stash_ref) + "\". Do NOT use '1', 'image ID 1', or attachment indices.")
                break
        
        context_lines.append("=== END CONTEXT ===")
        context_lines.append("")
        context_lines.append(f"Current request: {current_query}")
        
        return "\n".join(context_lines)
    
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
                self.status_updater.update(msg)
            
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
        from datetime import timedelta
        
        try:
            db = get_memory_db()
            
            # Get recent conversations
            recent = db.get_recent_conversations(limit=self.auto_context_window)
            
            if not recent:
                return current_query
            
            # Filter by time window (only include recent conversations)
            cutoff = datetime.now() - timedelta(minutes=self.auto_context_minutes)
            
            relevant = []
            for conv in recent:
                # Parse timestamp (handle both string and datetime)
                ts_str = conv.get('timestamp', '')
                if isinstance(ts_str, str):
                    # Try parsing ISO format
                    try:
                        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    except:
                        # Skip if can't parse
                        continue
                elif hasattr(ts_str, 'timestamp'):
                    ts = ts_str
                else:
                    continue
                
                # Only include if within time window
                if ts > cutoff:
                    relevant.append(conv)
            
            # If no recent context within time window, just return current query
            if not relevant:
                return current_query
            
            # Build context block (oldest first for chronological order)
            # Using simple plain text format (no Unicode boxes - saves tokens!)
            context_parts = ["=== RECENT CONVERSATION HISTORY ==="]
            context_parts.append(f"Last {len(relevant)} conversation(s) in past {self.auto_context_minutes} minutes")
            context_parts.append("")
            
            for i, conv in enumerate(reversed(relevant), 1):  # Oldest first
                context_parts.append(f"[Previous Exchange {i}]")
                context_parts.append(f"User: {conv['user_query']}")
                context_parts.append(f"Assistant: {conv['jarvis_response']}")
                
                # Include tools used (critical for self-learning)
                tools_json = conv.get('tools_used')
                if tools_json:
                    try:
                        tools_list = json.loads(tools_json) if isinstance(tools_json, str) else tools_json
                        if tools_list:
                            context_parts.append(f"Tools used: {', '.join(tools_list)}")
                    except:
                        pass
                
                # Flag failures (critical for learning from mistakes!)
                success = conv.get('success', True)
                if not success:
                    context_parts.append("Status: FAILED - Task did not complete successfully")
                    context_parts.append("Consider using check_tool_logs to understand why")
                else:
                    context_parts.append("Status: Success")
                
                # Include model/cost metadata if available (helps understand complexity)
                metadata_json = conv.get('metadata')
                if metadata_json:
                    try:
                        metadata = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
                        if metadata:
                            model = metadata.get('model', 'unknown')
                            tool_count = metadata.get('tool_count', 0)
                            context_parts.append(f"Model: {model}, Tools called: {tool_count}")
                    except:
                        pass
                
                context_parts.append("")  # Blank line between conversations
            
            context_parts.append("=== CURRENT USER QUERY ===")
            context_parts.append(current_query)
            context_parts.append("")
            context_parts.append("Instructions:")
            context_parts.append("- Use the conversation history to provide context-aware responses")
            context_parts.append("- Reference previous topics naturally when relevant")
            context_parts.append("- Learn from failed attempts (check_tool_logs if needed)")
            context_parts.append("- Catch contradictions and continue multi-step workflows seamlessly")
            context_parts.append("- If you need more history, call get_recent_conversations tool")
            context_parts.append("- Learn from failed attempts (check_tool_logs if needed)")
            context_parts.append("- Catch contradictions (\"You just said X, now saying Y?\")")
            context_parts.append("- Continue multi-step workflows seamlessly")
            context_parts.append("- If context window is too short, you can call get_recent_conversations tool for more history")
            
            return "\n".join(context_parts)
            
        except Exception as e:
            # If context loading fails, gracefully degrade to just current query
            if os.environ.get('JARVIS_DEBUG'):
                print(f"DEBUG: Context loading failed: {e}", file=sys.stderr)
            return current_query
    
    def _build_turn_context(self, original_query: str, conversation_context: list) -> str:
        """
        Build context string for subsequent turns in multi-turn conversation.
        
        Args:
            original_query: The user's original request
            conversation_context: List of previous tool executions and results
            
        Returns:
            Formatted context string for the LLM
        """
        context_parts = [f"Original user request: {original_query}\n"]
        context_parts.append("Tools executed so far:")
        now = datetime.now(self.timezone)
        
        for i, ctx in enumerate(conversation_context, 1):
            tool_name = ctx["tool"]
            result = ctx["result"]
            meta = ctx.get("meta", {}) if isinstance(ctx, dict) else {}
            executed_at_iso = meta.get("executed_at_iso")
            executed_at_local = meta.get("executed_at_local")
            ttl_seconds = meta.get("ttl_seconds")
            source = meta.get("source", "tool")
            authoritative = bool(meta.get("authoritative_live", False))
            age_seconds = None
            expires_in = None
            dt_local = self._safe_iso_to_local_datetime(executed_at_iso)
            if dt_local:
                age_seconds = max(0, int((now - dt_local).total_seconds()))
            if ttl_seconds is not None and age_seconds is not None:
                expires_in = ttl_seconds - age_seconds
            
            # Smart summarization: prioritize error details
            if not result.get("ok", True):
                # For failures, include full error context
                summary_parts = []
                summary_parts.append(f"Status: FAILED")
                if "error" in result:
                    summary_parts.append(f"Error: {result['error']}")
                if "data" in result and isinstance(result["data"], dict):
                    # Include error details from data
                    if "error" in result["data"]:
                        summary_parts.append(f"Details: {result['data']['error']}")
                    if "status_code" in result["data"]:
                        summary_parts.append(f"Status Code: {result['data']['status_code']}")
                result_summary = "\n   ".join(summary_parts)
            else:
                # For success: Pass full result (ok, speech, data, etc.) so LLM sees everything
                # @TOOL_CONFIG: context truncation limits — tools with large outputs get more chars
                if "search" in tool_name.lower() or "fetch" in tool_name.lower():
                    # Search/fetch tools: need MORE context (3000 chars) to capture movie titles, URLs, descriptions
                    max_chars = 3000
                elif tool_name == "status_recap":
                    # Status recap aggregates lots of data - needs full context (4000 chars)
                    max_chars = 4000
                else:
                    # Other tools: standard truncation (1500 chars)
                    max_chars = 1500
                
                result_summary = json.dumps(result, indent=2)[:max_chars]
            
            context_parts.append(f"\n{i}. {tool_name}")
            context_parts.append(
                "   Freshness: "
                f"executed_at={executed_at_local or executed_at_iso or 'unknown'}, "
                f"age={self._format_age_seconds(age_seconds)}, "
                f"ttl={str(ttl_seconds) + 's' if ttl_seconds is not None else 'none'}, "
                f"expires_in={self._format_age_seconds(expires_in) if expires_in is not None else 'n/a'}, "
                f"source={source}, "
                f"authoritative_live={authoritative}"
            )
            context_parts.append(f"   Result: {result_summary}")
        
        # Check if any tool requested news - prompt LLM to use native search
        news_requested = False
        for ctx in conversation_context:
            result = ctx.get("result", {})
            data = result.get("data", {})
            # Check both top-level and nested report data
            if data.get("news_requested") or data.get("report", {}).get("news_requested"):
                news_requested = True
                break
        
        context_parts.append("\n\nBased on the above results, determine if you need to:")
        context_parts.append("1. Call another tool to complete the user's request")
        context_parts.append("2. Respond directly to the user (task complete)")
        context_parts.append("")
        context_parts.append("FRESHNESS RULES (highest priority):")
        context_parts.append("- Prefer the most recent authoritative_live tool result for live-data queries.")
        context_parts.append("- If the latest live result is still within ttl/expires_in, DO NOT re-call the same tool unless user explicitly asked to refresh/recheck/update.")
        context_parts.append("- Treat stored memory/intel for price-like data as historical context, not live truth.")
        context_parts.append("- For crypto/stock, ignore stale memories older than 60 minutes when a newer live tool result exists.")
        
        if news_requested:
            context_parts.append("\n⚠️ NEWS REQUESTED: The user asked for news. Use your NATIVE SEARCH capability to get current news headlines. DO NOT call external search tools - use your built-in web search to find 3-5 relevant news headlines and include them in your response.")
        
        return "\n".join(context_parts)
    
    def _get_relevant_memories(self, transcript: str) -> str:
        """
        Fetch memories semantically relevant to the current query.
        Injected into context so LLM doesn't need to call search_memory/semantic_recall.
        
        Applies recency weighting: more recent memories rank slightly higher.
        Older memories (60+ days) fade in relevance; recently used/updated stay higher.
        Importance is preserved for conflict resolution (user preferences override defaults).
        
        Works for CLI, WebUI, and wake word - all entry points use orchestrator.process().
        """
        if get_config_value('AUTO_MEMORY_INJECTION_ENABLED', 'true').lower() != 'true':
            return ""
        try:
            db = get_memory_db()
            limit = get_int('AUTO_MEMORY_LIMIT', 8)
            threshold = get_float('AUTO_MEMORY_SIMILARITY_THRESHOLD', 0.38)
            recency_enabled = get_config_value('AUTO_MEMORY_RECENCY_ENABLED', 'true').lower() == 'true'
            addressing_limit = get_int('AUTO_MEMORY_ALWAYS_INCLUDE_LIMIT', 2)
            
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
                    if key and key not in seen_keys and not _is_no_preference(value):
                        seen_keys.add(key)
                        merged.append((1.1, m.get('importance', 5), m, 'always'))
            
            # Semantic search for query-relevant memories
            candidate_limit = min(limit * 2, 20)
            candidate_threshold = min(threshold - 0.05, 0.30)
            memories = db.semantic_search(
                query=transcript,
                limit=candidate_limit,
                similarity_threshold=candidate_threshold
            )
            
            # Apply recency weighting to semantic results
            now = datetime.now()
            for m in memories:
                key = m.get('key', '')
                if key and key in seen_keys:
                    continue
                if key:
                    seen_keys.add(key)
                sim = m.get('similarity', 0)
                importance = m.get('importance', 5)
                recency_factor = 1.0
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
                                recency_factor = 0.95
                            elif days_old <= 60:
                                recency_factor = 0.9
                            else:
                                recency_factor = 0.85
                        except (ValueError, TypeError, AttributeError):
                            pass
                adjusted = sim * recency_factor
                if adjusted >= threshold:
                    merged.append((adjusted, importance, m, 'semantic'))
            
            # Sort by score desc, then importance desc; take top N
            merged.sort(key=lambda x: (x[0], x[1]), reverse=True)
            top = merged[:limit]
            
            if not top:
                return ""
            
            memory_lines = []
            transcript_lower = transcript.lower()
            price_like_query = any(
                token in transcript_lower
                for token in ["price", "btc", "bitcoin", "eth", "ethereum", "crypto", "stock", "ticker", "quote", "gold", "tsla", "aapl"]
            )

            def _is_price_like_memory(key: str, value: str) -> bool:
                text = f"{key} {value}".lower()
                keywords = ["price", "btc", "bitcoin", "crypto", "stock", "ticker", "quote", "coin", "market cap", "gold", "tsla", "aapl"]
                return any(k in text for k in keywords)

            for _, _, m, source in top:
                key = m.get('key', '')
                value = m.get('value', '')
                if _is_no_preference(value):
                    continue  # User said forget/no preference - don't show
                cat = m.get('category', '')
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
                if source == 'always':
                    label = "user preference (always included)"
                else:
                    label = f"relevance: {m.get('similarity', 0) * 100:.0f}%"
                staleness_hint = ""
                if price_like_query and _is_price_like_memory(key, value):
                    if age_minutes is not None and age_minutes > 60:
                        staleness_hint = "STALE_FOR_LIVE_PRICE_QUERIES"
                    else:
                        staleness_hint = "recent_price_context"
                age_text = f"{age_minutes}m" if age_minutes is not None else "unknown"
                memory_lines.append(
                    f"- {key}: {value} "
                    f"(category: {cat}, {label}, saved_at: {saved_at_local}, age: {age_text}"
                    f"{', staleness: ' + staleness_hint if staleness_hint else ''})"
                )
            if not memory_lines:
                return ""
            lines = [
                "=== RELEVANT STORED KNOWLEDGE (use this without calling search tools) ===",
                "When these conflict with your defaults, prefer these (user explicitly told you):",
                "Freshness note: For live market/weather questions, newer live tool calls outrank older stored memory.",
                ""
            ] + memory_lines + ["==="]
            return "\n".join(lines) + "\n\n"
        except Exception as e:
            if os.environ.get('JARVIS_DEBUG'):
                print(f"⚠️ Auto-memory injection failed: {e}", file=sys.stderr)
            return ""
    
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
        try:
            from intelligence_hooks import record_interaction, track_insight_outcomes
            
            experience_id = record_interaction(
                query=transcript,
                tools_used=tools_used,
                result=result,
                conversation_context=conversation_context
            )
            
            # Track insight usage if insights were applied
            if applied_insights:
                track_insight_outcomes(
                    insights=applied_insights,
                    tools_used=tools_used,
                    result=result
                )
            
            return experience_id
        except Exception as e:
            # Don't let learning failures affect the main flow
            if os.environ.get('JARVIS_DEBUG'):
                print(f"⚠️ Learning recording failed: {e}", file=sys.stderr)
            return -1
    
    def _log_conversation(self, user_query: str, response: str, tools_used: list, success: bool = True, 
                          execution_time_ms: float = None, token_info: dict = None):
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
            
            # Add token/cost info for cloud providers only
            provider = metadata.get("provider", "")
            if token_info and provider in ["openai", "anthropic"]:
                metadata.update(token_info)
            
            # Add tool count
            metadata["tool_count"] = len(tools_used)
            
            # Add web conversation ID if this is a web UI request
            if self.web_conversation_id:
                metadata["web_conversation_id"] = self.web_conversation_id
            
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
        
        # Show model being used
        if mode == "cloud":
            provider = get_config_value("LLM_PROVIDER", "anthropic")
            if provider == "openai":
                model = get_config_value("OPENAI_MODEL", "gpt-5.4-nano")
            elif provider == "xai":
                model = get_config_value("XAI_MODEL", "grok-4-1-fast-non-reasoning-latest")
            else:
                model = get_config_value("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
        else:
            model = get_config_value("OLLAMA_MODEL", "qwen3-vl")
        print(f"🤖 Model: {model}")
        
        print("=" * 60)
    
    orch = Orchestrator(mode)
    result = orch.process(transcript)
    
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
        qa_word_limit = int(get_config_value('JARVIS_QA_WORD_LIMIT', '75'))
        multi_turn_word_limit = int(get_config_value('JARVIS_MULTI_TURN_WORD_LIMIT', '50'))
        
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
                feedback_summary=feedback.get('summary')
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
                savings = usage.get('cache_savings_usd', 0)
                if savings > 0:
                    print(f"   ✅ Saved: ${savings:.4f}")
            elif cache_write > 0:
                print(f"   💾 Cache WRITE: {cache_write:,} tokens (first request)")
            
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
