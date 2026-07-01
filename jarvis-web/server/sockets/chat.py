"""
WebSocket handlers for chat functionality
Real-time message handling and tool execution streaming
"""
import os
import sys
import uuid
import time
import traceback
import json
import re
import copy
import threading
import functools
import inspect
from urllib.parse import urlparse
from datetime import datetime
from pathlib import Path
from flask_socketio import emit, join_room, leave_room
from flask import request

# Add Jarvis libs to path
JARVIS_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(JARVIS_ROOT / 'lib'))
sys.path.insert(0, str(JARVIS_ROOT / 'orchestrator'))
from config_loader import DEFAULT_JARVIS_QA_WORD_LIMIT, DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT

from model_prompt_overrides import apply_prompt_override_sections, load_model_prompt_override
from model_catalog import get_provider_fallback_model
from ..services.usage_metadata import enrich_usage_metadata
from ..services.completion_guard import CompletionGuardPolicy
from ..services.followup_extractor import (
    extract_followup_data,
    extract_text_summarizer_followup,
    compact_text_summarizer_item,
    truncate_followup_summary,
    FOLLOWUP_EVIDENCE_MAX_CANDIDATES as _FOLLOWUP_EVIDENCE_MAX_CANDIDATES,
    FOLLOWUP_SUMMARY_MAX_CHARS as _FOLLOWUP_SUMMARY_MAX_CHARS,
)

def _scoped_by_mode(method):
    """Run a thread-entry handler inside a request-scoped config overlay.

    Web chat work runs in dedicated OS threads (see ``_start_blocking_task``),
    which each start with an empty ``contextvars`` context. Installing a
    ``config_scope`` at the thread entry keeps that thread's deployment mode and
    resolved ``config/<mode>.env`` values isolated, so a concurrent local
    request can never clobber a cloud request's provider/model/db/embedding
    selection through global ``os.environ`` mutation (the old ``load_config``
    behaviour). Per-mode Web overrides are installed in the same scope and are
    exported deliberately to child tools.

    The wrapped method's ``mode`` is taken from a ``mode`` parameter when present,
    otherwise from a ``record['mode']`` argument; it defaults to ``cloud``.
    """
    sig = inspect.signature(method)

    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        mode = None
        arguments = {}
        try:
            bound = sig.bind_partial(*args, **kwargs)
            arguments = bound.arguments
            mode = arguments.get('mode')
            if not mode and isinstance(arguments.get('record'), dict):
                mode = arguments['record'].get('mode')
        except TypeError:
            mode = None

        mode = mode or 'cloud'
        from ..config import load_web_config
        from ..services.settings_manager import (
            CLOUD_TTS_PROVIDER_OPTIONS,
            LOCAL_TTS_PROVIDER_OPTIONS,
        )

        web_config = load_web_config()
        mode_overrides = web_config.get(mode, {}) if isinstance(web_config, dict) else {}
        scoped_overrides = {}
        key_map = {
            'image_provider': 'IMAGE_TOOL_PROVIDER',
            'video_provider': 'VIDEO_TOOL_PROVIDER',
            'tts_provider': 'TTS_PROVIDER',
            'response_style': 'JARVIS_RESPONSE_STYLE',
            'qa_word_limit': 'JARVIS_QA_WORD_LIMIT',
            'multi_turn_word_limit': 'JARVIS_MULTI_TURN_WORD_LIMIT',
        }
        for web_key, config_key in key_map.items():
            value = mode_overrides.get(web_key)
            if value is not None:
                scoped_overrides[config_key] = str(value)

        tts_provider = mode_overrides.get('tts_provider')
        allowed_tts = LOCAL_TTS_PROVIDER_OPTIONS if mode == 'local' else CLOUD_TTS_PROVIDER_OPTIONS
        if tts_provider not in (None, *allowed_tts):
            scoped_overrides.pop('TTS_PROVIDER', None)

        # One-shot image/video modal choices outrank saved per-mode settings.
        image_data = arguments.get('image_data')
        if isinstance(image_data, dict):
            action = image_data.get('action')
            modal_provider = (image_data.get('settings') or {}).get('provider')
            if action == 'video':
                scoped_overrides['VIDEO_TOOL_PROVIDER'] = str(modal_provider or 'xai')
            elif action == 'image' and modal_provider:
                scoped_overrides['IMAGE_TOOL_PROVIDER'] = str(modal_provider)

        from config_loader import config_scope
        with config_scope(mode, overrides=scoped_overrides):
            return method(*args, **kwargs)

    return wrapper


class ChatHandler:
    """Handles WebSocket chat events"""

    DEFAULT_COMPLETION_GUARD_EXCLUDED_TOOLS = {
        'phone_call',
        'send_email',
        'create_reminder',
        'create_alert',
        'opencode',
    }
    
    def __init__(self, socketio):
        self.socketio = socketio
        self.sessions = {}  # session_id -> {mode, conversation_id, ...}
        self.pending_cancellations = {}  # message_id -> True (to signal orchestrator to stop)
        self.completion_guard_policy = CompletionGuardPolicy(
            parse_bool_fn=self._parse_bool,
            normalize_server_side_tool_names_fn=self._normalize_server_side_tool_names,
            combine_feedback_tools_fn=self._combine_feedback_tools,
            default_excluded_tools=set(self.DEFAULT_COMPLETION_GUARD_EXCLUDED_TOOLS),
        )
        self._register_handlers()

    def _get_completion_guard_policy(self) -> CompletionGuardPolicy:
        """Lazily build the Completion Guard policy helper for tests using __new__."""
        policy = getattr(self, "completion_guard_policy", None)
        if policy is not None:
            return policy
        policy = CompletionGuardPolicy(
            parse_bool_fn=self._parse_bool,
            normalize_server_side_tool_names_fn=self._normalize_server_side_tool_names,
            combine_feedback_tools_fn=self._combine_feedback_tools,
            default_excluded_tools=set(self.DEFAULT_COMPLETION_GUARD_EXCLUDED_TOOLS),
        )
        self.completion_guard_policy = policy
        return policy

    @staticmethod
    def _parse_bool(value, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ('1', 'true', 'yes', 'on')

    @staticmethod
    def _sanitize_tool_hints(raw_hints, max_hints: int = 5) -> list[str]:
        """Validate #tool hints against enabled, non-blocked tools."""
        if not isinstance(raw_hints, list):
            return []

        try:
            from ..services.tool_discovery import get_tool_service
            service = get_tool_service()
            allowed = {
                t.get('name')
                for t in service.get_tools(include_blocked=False)
                if t.get('name') and t.get('enabled', True) and not t.get('blocked')
            }
        except Exception as exc:
            print(f"[CHAT] Failed to validate tool hints: {exc}")
            return []

        hints = []
        for item in raw_hints:
            if not isinstance(item, str):
                continue
            name = item.strip()
            if name in allowed and name not in hints:
                hints.append(name)
            if len(hints) >= max_hints:
                break
        return hints

    @staticmethod
    def _format_tool_hint_context(tool_hints: list[str], request_kind: str = '') -> str:
        names = ', '.join(tool_hints)
        if request_kind == 'canvas_export' and tool_hints == ['canvas']:
            return (
                "[CONTEXT - Tool preference for this request]\n\n"
                f"Selected tool hints: {names}.\n"
                "Use one canvas tool call with action=create. Build the full page from the prior assistant "
                "turn plus structured tool_results (especially source links/snippets). Do not call canvas "
                "again after a successful create; reply with the page link instead.\n\n"
                "[END CONTEXT]"
            )
        if tool_hints == ['canvas']:
            return (
                "[CONTEXT - Tool preference for this request]\n\n"
                f"Selected tool hints: {names}.\n"
                "Use the canvas action that matches the user's request: create, update, read, list, open, "
                "or delete. Do not default to creating a page unless the user asked to create or save content.\n\n"
                "[END CONTEXT]"
            )
        return (
            "[CONTEXT - Tool preference for this request]\n\n"
            f"Selected tool hints: {names}.\n"
            "Treat these as strong preferences for this turn. If one fits the user's request, use it before "
            "artifact/memory tools such as canvas; do not satisfy a fresh-search request by only reusing an old artifact. "
            "Ignore a hinted tool only if it clearly does not fit or fails, then use another appropriate tool or answer from gathered results.\n\n"
            "[END CONTEXT]"
        )

    def _get_completion_guard_config(self, mode: str) -> dict:
        """Get effective Completion Guard settings for the current mode."""
        return self._get_completion_guard_policy().get_config(mode)

    def _completion_guard_applies(self, config: dict, tools_used: list[str]) -> bool:
        """Check whether Completion Guard applies to this response at all."""
        return self._get_completion_guard_policy().applies(config, tools_used)

    def _should_prompt_completion_guard(self, config: dict, tools_used: list[str]) -> bool:
        """Decide whether to show the completion prompt for this response."""
        return self._get_completion_guard_policy().should_prompt(config, tools_used)

    def _should_auto_evaluate_completion_guard(self, config: dict, tools_used: list[str]) -> bool:
        """Decide whether auto mode should evaluate a response in the background."""
        return self._get_completion_guard_policy().should_auto_evaluate(config, tools_used)

    def _remember_completion_guard_record(self, session_id: str, message_id: str, record: dict):
        """Keep a small per-session record so a later 'No' can create a useful ticket."""
        session = self.sessions.setdefault(session_id, {})
        records = session.setdefault('completion_guard_records', {})
        record['timestamp'] = float(record.get('timestamp') or time.time())
        record.setdefault('status', 'pending')
        record.setdefault('repair_attempts', 0)
        ttl_seconds = int(record.get('completion_guard', {}).get('manual_prompt_ttl_seconds') or 0)
        if record.get('completion_guard_prompt') and ttl_seconds > 0:
            record.setdefault('expires_at', record['timestamp'] + ttl_seconds)
        records[message_id] = record

        # Keep recent records bounded per session.
        if len(records) > 50:
            oldest = sorted(records.items(), key=lambda item: item[1].get('timestamp', 0))[:10]
            for old_id, _ in oldest:
                records.pop(old_id, None)

    def _get_completion_guard_record(self, session_id: str, message_id: str) -> dict | None:
        """Fetch a stored Completion Guard record for this web session."""
        return self.sessions.get(session_id, {}).get('completion_guard_records', {}).get(message_id)

    @staticmethod
    def _completion_guard_record_expired(record: dict) -> bool:
        return CompletionGuardPolicy.record_expired(record)

    @staticmethod
    def _response_has_visual_sources(text: str) -> bool:
        """Detect responses where URLs/source blocks are useful in chat but bad for TTS."""
        if not text or not isinstance(text, str):
            return False
        if 'Sources:' in text or 'Source:' in text:
            return True
        if re.search(r'(?i)\b(?:Post|Tweet|Thread|Status|Message)\s+ID:\s*[A-Za-z0-9_-]{6,}', text):
            return True
        return bool(re.search(r'(?:https?://|www\.)\S+', text, flags=re.IGNORECASE))

    @staticmethod
    def _normalize_display_text(text: str) -> str:
        """Loosely normalize text so we can compare speech vs raw response shape."""
        if not text:
            return ''
        text = re.sub(r'[*_`#>]+', '', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def _should_prefer_raw_for_display(self, raw_response: str, speech_text: str) -> bool:
        """
        Prefer raw response in chat when it is the same answer with better visual structure.
        This keeps TTS concise while avoiding one-paragraph blobs in the UI.
        """
        if not raw_response:
            return False
        if not speech_text:
            return True

        raw_has_structure = ('\n' in raw_response) or bool(re.search(r'(?m)^\s*[-*]\s+', raw_response))
        speech_has_structure = ('\n' in speech_text) or bool(re.search(r'(?m)^\s*[-*]\s+', speech_text))
        if raw_has_structure and not speech_has_structure:
            return True
        if not raw_has_structure or speech_has_structure:
            return False

        normalized_raw = self._normalize_display_text(raw_response)
        normalized_speech = self._normalize_display_text(speech_text)
        if not normalized_raw or not normalized_speech:
            return False

        common_prefix = os.path.commonprefix([normalized_raw, normalized_speech])
        if len(common_prefix) >= 40:
            return True
        if normalized_speech[:120] and normalized_speech[:120] in normalized_raw:
            return True
        if normalized_raw[:120] and normalized_raw[:120] in normalized_speech:
            return True
        return False

    def _prepare_web_response_text(self, result: dict, tts_fallback: str) -> tuple[str, str]:
        """
        Split a result into:
        - display_text: what should stay visible in chat history/UI
        - speech_text: what should be safe to send to TTS
        """
        from security_utils import sanitize_for_speech
        from tts_normalizer import strip_speech_tags_for_display

        raw_response = result.get('raw_llm_response', '') or ''
        primary_speech = result.get('speech')
        display_text = primary_speech if primary_speech not in (None, '') else raw_response

        speech_source = primary_speech if primary_speech not in (None, '') else raw_response
        preserve_xai_tags = False
        try:
            from ..config import get_jarvis_setting
            preserve_xai_tags = (get_jarvis_setting('TTS_PROVIDER', '') or '').strip().lower() == 'xai'
        except Exception:
            preserve_xai_tags = False

        speech_text = sanitize_for_speech(speech_source, preserve_xai_tags=preserve_xai_tags) if speech_source else ''
        if speech_source and not speech_text:
            speech_text = tts_fallback

        # If the raw answer includes visual source links, preserve it in chat even when
        # speech is condensed/sanitized for TTS.
        if raw_response and self._response_has_visual_sources(raw_response):
            display_text = raw_response
        elif raw_response and self._should_prefer_raw_for_display(raw_response, primary_speech or ''):
            display_text = raw_response

        display_text = strip_speech_tags_for_display(display_text or '')

        return display_text or '', speech_text or ''

    @staticmethod
    def _conversation_room_name(conversation_id: str | None) -> str | None:
        """Build a stable room name for a chat conversation."""
        if not conversation_id:
            return None
        return f"conversation:{conversation_id}"

    def _delivery_room(self, session_id: str, conversation_id: str | None) -> str:
        """Prefer a stable conversation room so reconnects can still receive in-flight updates."""
        return self._conversation_room_name(conversation_id) or session_id

    def _join_conversation_room(self, session_id: str, conversation_id: str | None) -> None:
        """Attach the current socket to the active conversation room."""
        room = self._conversation_room_name(conversation_id)
        if not room:
            return

        prior_room = self.sessions.get(session_id, {}).get('conversation_room')
        if prior_room and prior_room != room:
            leave_room(prior_room)

        join_room(room)
        if session_id in self.sessions:
            self.sessions[session_id]['conversation_room'] = room

    def _start_blocking_task(self, target, *args, name: str | None = None) -> threading.Thread:
        """
        Run long blocking work in a dedicated OS thread.

        Some provider SDK paths, especially xAI's Agent Tools flow, can block long
        enough to starve Socket.IO heartbeats when they run inside Eventlet's
        cooperative scheduler. A native thread keeps the socket server responsive
        while the provider request is in flight.
        """
        thread = threading.Thread(
            target=target,
            args=args,
            daemon=True,
            name=name or getattr(target, '__name__', 'jarvis-blocking-task'),
        )
        thread.start()
        return thread

    @staticmethod
    def _build_feedback_result_from_record(record: dict) -> dict:
        """Build a result-like payload for feedback from the stored original response."""
        return {
            'ok': True,
            'speech': record.get('speech', ''),
            'raw_llm_response': record.get('raw_llm_response', ''),
            'data': record.get('data', {}),
            'usage': record.get('usage', {}),
            'server_side_tools': record.get('server_side_tools', {}),
            'experience_id': record.get('experience_id'),
            'intelligence_context': record.get('intelligence_context', '')
        }

    @staticmethod
    def _normalize_server_side_tool_names(server_side_tools: dict | None) -> list[str]:
        """Convert provider-native tool usage dict into stable pseudo-tool names."""
        if not isinstance(server_side_tools, dict):
            return []
        normalized = []
        for name, count in server_side_tools.items():
            if not name:
                continue
            label = str(name).replace('SERVER_SIDE_TOOL_', '').lower()
            repeat = 1
            try:
                repeat = max(1, int(count))
            except Exception:
                repeat = 1
            normalized.extend([f"native:{label}"] * repeat)
        return normalized

    @staticmethod
    def _combine_feedback_tools(original_tools: list[str] | None, settled_tools: list[str] | None = None) -> list[str]:
        """Preserve the full task tool path for feedback, original first then settled-phase tools."""
        combined = []
        for tool in list(original_tools or []) + list(settled_tools or []):
            if tool:
                combined.append(tool)
        return combined

    @staticmethod
    def _build_completion_guard_feedback_context(record: dict, status: str) -> dict:
        """Summarize Completion Guard state so feedback can grade the settled outcome."""
        policy = CompletionGuardPolicy(
            parse_bool_fn=ChatHandler._parse_bool,
            normalize_server_side_tool_names_fn=ChatHandler._normalize_server_side_tool_names,
            combine_feedback_tools_fn=ChatHandler._combine_feedback_tools,
            default_excluded_tools=set(ChatHandler.DEFAULT_COMPLETION_GUARD_EXCLUDED_TOOLS),
        )
        return policy.build_feedback_context(record, status)

    def _start_feedback_async(
        self,
        session_id: str,
        parent_message_id: str,
        display_message_id: str,
        record: dict,
        result_payload: dict,
        tools_used: list[str],
        completion_guard_status: str
    ) -> None:
        """Start deferred feedback once Completion Guard has reached a settled state."""
        if not record or not record.get('feedback_requested'):
            return
        if record.get('feedback_state') in ('running', 'complete'):
            return

        record['feedback_state'] = 'running'
        record['feedback_display_message_id'] = display_message_id

        self._start_blocking_task(
            self._collect_feedback_async,
            session_id,
            parent_message_id,
            record.get('query', '') or record.get('processed_query', ''),
            record.get('mode', 'cloud'),
            display_message_id,
            record.get('conversation_id', ''),
            result_payload,
            tools_used,
            record.get('provider'),
            record.get('model'),
            self._build_completion_guard_feedback_context(record, completion_guard_status),
            name=f"feedback-{parent_message_id[:8]}",
        )

    def _settle_pending_completion_guard(
        self,
        session_id: str,
        record: dict,
        status: str,
        reason: str = '',
        note: str = '',
    ) -> bool:
        """Settle an unanswered manual guard without running a repair pass."""
        if not record or record.get('status') != 'pending':
            return False

        record['status'] = status
        record['user_note'] = note or record.get('user_note', '')
        record['settled_reason'] = reason
        record['settled_at'] = datetime.now().isoformat()

        message_id = record.get('message_id')
        conversation_id = record.get('conversation_id')
        try:
            from ..services.conversation_store import get_conversation_store
            store = get_conversation_store()
            store.update_message_data_by_web_message_id(
                conversation_id,
                message_id,
                {
                    '_completion_guard': {
                        'status': status,
                        'note': record.get('user_note', ''),
                        'reason': reason,
                        'settled_at': record.get('settled_at'),
                    }
                },
            )
        except Exception as e:
            print(f"[COMPLETION_GUARD] Failed to persist {status} state: {e}")

        self.socketio.emit('completion_guard:updated', {
            'message_id': message_id,
            'conversation_id': conversation_id,
            'status': status,
            'note': record.get('user_note', ''),
            'reason': reason,
        }, room=session_id)

        self._update_completion_guard_experience(
            record,
            status,
            note=record.get('user_note', ''),
            extra={
                'reason': reason,
                'settled_at': record.get('settled_at'),
            },
        )

        self._start_feedback_async(
            session_id,
            message_id,
            message_id,
            record,
            self._build_feedback_result_from_record(record),
            record.get('tools_used', []),
            status,
        )
        return True

    def _supersede_pending_completion_guards(self, session_id: str, conversation_id: str) -> None:
        """Mark older unanswered manual guard prompts inactive when the user continues chatting."""
        records = self.sessions.get(session_id, {}).get('completion_guard_records', {})
        for record in list(records.values()):
            if record.get('conversation_id') != conversation_id:
                continue
            if not record.get('completion_guard_prompt'):
                continue
            self._settle_pending_completion_guard(
                session_id,
                record,
                'superseded',
                'conversation_continued',
            )

    def _expire_completion_guard_prompt_later(self, session_id: str, message_id: str, ttl_seconds: int) -> None:
        """Expire an unanswered manual prompt after its TTL."""
        if ttl_seconds <= 0:
            return
        self.socketio.sleep(ttl_seconds)
        record = self._get_completion_guard_record(session_id, message_id)
        if not record:
            return
        self._settle_pending_completion_guard(
            session_id,
            record,
            'expired',
            'manual_prompt_timeout',
        )

    @staticmethod
    def _extract_repair_status(text: str) -> tuple[str | None, str]:
        """Extract REPAIR_STATUS marker from an LLM response and remove it."""
        if not text:
            return None, ''

        lines = text.splitlines()
        while lines and not lines[0].strip():
            lines.pop(0)
        if not lines:
            return None, text

        first = lines[0].strip()
        if first.startswith('REPAIR_STATUS:'):
            status = first.split(':', 1)[1].strip().lower()
            remainder = '\n'.join(lines[1:]).strip()
            return status, remainder
        return None, text

    @staticmethod
    def _normalize_comparison_text(text: str) -> str:
        """Normalize text before comparing answer similarity."""
        return CompletionGuardPolicy.normalize_comparison_text(text)

    @classmethod
    def _text_similarity(cls, left: str, right: str) -> float:
        """Return a coarse similarity score between two strings."""
        return CompletionGuardPolicy.text_similarity(left, right)

    @staticmethod
    def _prepare_repair_data_for_delta(data) -> str:
        """Normalize result payloads before comparing evidence changes."""
        return CompletionGuardPolicy.prepare_repair_data_for_delta(data)

    def _analyze_completion_guard_delta(self, record: dict, result: dict) -> dict:
        """
        Determine whether a repair materially improved the task with new evidence
        or a different tool path, rather than only rewording the answer.
        """
        return self._get_completion_guard_policy().analyze_delta(record, result)

    @staticmethod
    def _completion_guard_tighten_instead_of_substantive_repair(delta: dict) -> bool:
        """
        True when a 'repair' run did not change the tool path and the answer text is
        nearly the same—treat as tighten_only (wording/hedging), not a better answer.
        """
        return CompletionGuardPolicy.tighten_instead_of_substantive_repair(delta)

    @staticmethod
    def _repair_has_explicit_source_or_verified_action(result: dict) -> bool:
        """
        Allow a no-tool repair to count as substantive only when it clearly cites a
        direct source already available in context or references a verified action.
        """
        text = ' '.join([
            str(result.get('raw_llm_response') or ''),
            str(result.get('speech') or ''),
        ]).strip()
        if not text:
            return False

        lowered = text.lower()

        source_patterns = [
            r'\baccording to\b',
            r'\bbased on\b',
            r'\bsource:\b',
            r'\bfrom\s+(?:docs?|documentation|manual|schema|api|readme)\b',
            r'\bdocs?/[a-z0-9._/\-]+\b',
            r'\buser_profile\.md\b',
            r'\bjarvis-intel/[a-z0-9._/\-]+\b',
        ]
        action_patterns = [
            r'\bverified\b',
            r'\bconfirmed\b',
            r'\bupdated\b.+\b(canvas|page|doc|document|presentation)\b',
            r'\bcreated\b.+\b(canvas|page|doc|document|presentation)\b',
            r'\bsaved\b.+\b(canvas|page|doc|document|presentation|stash)\b',
            r'\bsent\b.+\b(email|message|webhook)\b',
        ]

        return any(re.search(pattern, lowered) for pattern in source_patterns + action_patterns)

    @staticmethod
    def _is_machine_like_completion_text(text: str) -> bool:
        """Detect tool-ish or payload-ish text that should not be treated as a final answer."""
        if not text or not isinstance(text, str):
            return True

        s = text.strip()
        if not s:
            return True
        if s.startswith('{') or s.startswith('['):
            return True
        if '\\"url\\":' in s or '"url":' in s or '\\"title\\":' in s or '"title":' in s:
            return True
        if re.match(r"^(Read|Listed|Found)\s+\d+(\.\d+)?\s+\w+", s):
            return True
        if re.match(r"^Read\s+\d+\s+bytes\s+from\s+.+", s):
            return True
        if re.match(r"^Listed\s+\d+\s+(files|items|results)", s):
            return True
        if s.count("{") >= 2 and s.count(":") >= 3:
            return True
        return False

    @staticmethod
    def _truncate_for_prompt(value, max_chars: int = 6000) -> str:
        """Serialize and truncate large values before feeding them back to the model."""
        try:
            text = json.dumps(value, indent=2, ensure_ascii=False)
        except Exception:
            text = str(value)

        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n... [truncated]"

    @staticmethod
    def _get_completion_guard_location_context(mode: str) -> str:
        """Provide location fallback context so Completion Guard audits local queries fairly."""
        return CompletionGuardPolicy.get_location_context(mode)

    def _create_completion_guard_eval_provider(
        self,
        mode: str,
        completion_guard_config: dict | None = None,
        fallback_provider: str | None = None,
        fallback_model: str | None = None
    ):
        """Create the provider used for Completion Guard auto-evaluation."""
        from config_loader import load_config, get_config_value
        from llm_provider import create_provider

        load_config(mode)

        provider_name = (
            (completion_guard_config or {}).get('eval_provider')
            or get_config_value('JARVIS_COMPLETION_GUARD_EVAL_PROVIDER', 'openai')
            or get_config_value('FEEDBACK_PROVIDER', 'openai')
            or fallback_provider
            or ('ollama' if mode == 'local' else get_config_value('LLM_PROVIDER', 'anthropic'))
        ).strip().lower()

        model_name = (
            (completion_guard_config or {}).get('eval_model')
            or get_config_value('JARVIS_COMPLETION_GUARD_EVAL_MODEL', get_provider_fallback_model(provider_name))
            or get_config_value('FEEDBACK_MODEL', get_provider_fallback_model(provider_name))
            or fallback_model
            or ''
        ).strip()

        if provider_name == 'anthropic':
            return provider_name, (
                model_name or get_config_value('ANTHROPIC_MODEL', get_provider_fallback_model('anthropic'))
            ), create_provider(
                'anthropic',
                api_key=get_config_value('ANTHROPIC_API_KEY'),
                model=model_name or get_config_value('ANTHROPIC_MODEL', get_provider_fallback_model('anthropic'))
            )
        if provider_name == 'openai':
            return provider_name, (
                model_name or get_config_value('OPENAI_MODEL', get_provider_fallback_model('openai'))
            ), create_provider(
                'openai',
                api_key=get_config_value('OPENAI_API_KEY'),
                model=model_name or get_config_value('OPENAI_MODEL', get_provider_fallback_model('openai'))
            )
        if provider_name == 'xai':
            return provider_name, (
                model_name or get_config_value('XAI_MODEL', get_provider_fallback_model('xai'))
            ), create_provider(
                'xai',
                api_key=get_config_value('XAI_API_KEY'),
                model=model_name or get_config_value('XAI_MODEL', get_provider_fallback_model('xai'))
            )

        from ollama_utils import resolve_ollama_model
        ollama_model = resolve_ollama_model(mode, model_override=(model_name or None))
        return provider_name, ollama_model, create_provider(
            'ollama',
            model=ollama_model,
            base_url=get_config_value('OLLAMA_BASE_URL', 'http://localhost:11434')
        )

    @staticmethod
    def _parse_completion_guard_auto_eval(raw_text: str) -> dict:
        """Parse the auto-evaluator JSON response."""
        return CompletionGuardPolicy.parse_auto_eval(raw_text)

    @staticmethod
    def _score_completion_guard_auto_eval(evaluation: dict) -> tuple[float, list[str]]:
        """Convert structured audit output into a deterministic repair score."""
        return CompletionGuardPolicy.score_auto_eval(evaluation)

    def _evaluate_completion_guard_auto(self, record: dict) -> dict:
        """Evaluate whether the finished answer should auto-trigger a repair pass."""
        record_mode = record.get('mode', 'cloud')
        provider_name, model_name, provider = self._create_completion_guard_eval_provider(
            mode=record_mode,
            completion_guard_config=record.get('completion_guard'),
            fallback_provider=record.get('provider'),
            fallback_model=record.get('model')
        )

        prompt = f"""Audit whether this completed Jarvis answer is actually supported and complete.

Return JSON only:
{{
  "recommended_action": "accept" | "tighten_only" | "repair_required",
  "task_status": "complete" | "partial" | "unsupported" | "failed",
  "risk_level": "low" | "medium" | "high" | "critical",
  "repair_worthwhile": true,
  "failure_types": ["unsupported_claim", "premature_not_found"],
  "missing_requirements": ["did not answer what to call the user"],
  "unsupported_claims": ["claimed no memory exists without enough support"],
  "contradictions": ["tool data contained evidence the answer missed"],
  "evidence_gaps": ["available tools or returned data were not used well enough"],
  "reason": "short explanation",
  "suggested_note": "short note for a repair pass or empty string"
}}

Audit rules:
- Evaluate the RAW LLM RESPONSE, not just the shorter spoken output
- Do not penalize voice-style brevity by itself
- Focus on support, completeness, contradictions, and missing required outputs
- Use recommended_action=tighten_only when the answer mostly works and only needs softer wording, tighter scope, or minor hedging
- Prefer tighten_only over repair_required when the gap is disclaimers, qualification, or uncertainty wording—not missing retrieval or tool calls
- Use recommended_action=repair_required only when a follow-up pass should materially improve the evidence or tool path
- Do not request a repair only because the answer could be phrased more cleanly
- If the answer missed evidence already present in tool data, call that out
- If the answer made strong claims without enough support, call that out
- If the answer only partially addressed the request, call that out
- Be conservative but honest: if the answer is incomplete or weakly supported, mark it

General failure type vocabulary:
- unsupported_claim
- incomplete_task
- missing_required_output
- contradiction_with_tool_data
- premature_not_found
- weak_evidence
- wrong_output_format
- hidden_tool_error
- missed_direct_source

User request:
{record.get('query', '')}

{self._get_completion_guard_location_context(record_mode)}

Raw LLM response:
{record.get('raw_llm_response', '')}

Final spoken response:
{record.get('speech', '')}

Tools used:
{', '.join(record.get('tools_used', [])) or '(none)'}

Native provider tools used:
{', '.join(self._normalize_server_side_tool_names(record.get('server_side_tools'))) or '(none)'}

Available tools:
{', '.join(record.get('available_tools', [])) or '(not captured)'}

Effective evidence (structured grounding; may include prior turns; may be empty):
```json
{self._truncate_for_prompt((record.get('data') or {}).get('_effective_evidence') or {}, max_chars=4500)}
```

Structured result data:
```json
{self._truncate_for_prompt(record.get('data', {}), max_chars=7000)}
```

Important:
- Native provider tools listed above are REAL tool usage. Do not call this a zero-tool answer if native provider tools were used.
- If native provider search returned sources/URLs, treat that as valid external evidence unless the answer still overclaims beyond what was returned.
- If effective evidence is non-empty, treat supporting_tool_results as valid grounding for this answer even when tools_used is empty (e.g. refinements like "top 10" using prior tool results).
"""

        override = load_model_prompt_override(
            provider=provider_name,
            model=model_name,
            mode=record_mode,
        )
        system_prompt = apply_prompt_override_sections(
            (
                "You are Completion Guard, a strict but practical QA evaluator. "
                "Judge whether a follow-up repair pass is warranted. "
                "Return valid JSON only."
            ),
            override,
            prepend_sections=("completion_guard_eval_prepend",),
        )
        response = provider.chat(prompt, system_prompt=system_prompt, max_tokens=300)
        parsed = self._parse_completion_guard_auto_eval(response)
        if parsed:
            repair_score, trigger_reasons = self._score_completion_guard_auto_eval(parsed)
            parsed['provider'] = provider_name
            parsed['model'] = model_name
            parsed['raw_response'] = response
            parsed['repair_score'] = repair_score
            parsed['trigger_reasons'] = trigger_reasons
        else:
            preview = (response or '')[:1200].replace('\n', '\\n')
            print(
                "[COMPLETION_GUARD] Unparseable auto-eval raw response "
                f"(provider={provider_name}, model={model_name}): {preview}"
            )
        return parsed

    def _update_completion_guard_experience(self, record: dict, status: str, note: str = '', extra: dict | None = None) -> bool:
        """Feed Completion Guard outcomes back into the intelligence/experience record."""
        experience_id = record.get('experience_id')
        if not experience_id:
            return False

        try:
            from intelligence_hooks import update_experience_from_completion_guard
            return update_experience_from_completion_guard(
                experience_id=int(experience_id),
                status=status,
                note=note,
                metadata=extra or {}
            )
        except Exception as e:
            print(f"[COMPLETION_GUARD] Failed to update intelligence experience {experience_id}: {e}")
            return False

    def _classify_completion_guard_strategy(self, record: dict, note: str = '') -> dict:
        """Choose a repair strategy family and tool-family hints for the next pass."""
        return CompletionGuardPolicy.classify_strategy(record, note)

    @staticmethod
    def _format_completion_guard_strategy(strategy: dict) -> str:
        """Render repair strategy hints into prompt-ready text."""
        return CompletionGuardPolicy.format_strategy(strategy)

    def _extract_direct_answer_from_tool_data(self, record: dict, result: dict) -> str | None:
        """Use simple deterministic extraction when tool data obviously contains the answer."""
        query = (record.get('query') or '').lower()
        result_data = result.get('data') or {}
        tools_used = result.get('tools_used') or []

        if 'manage_intel' in tools_used:
            payloads = result_data.get('manage_intel')
            if not isinstance(payloads, list):
                payloads = [payloads] if payloads else []

            for payload in payloads:
                if not isinstance(payload, dict):
                    continue
                content = payload.get('content') or ''
                if not content:
                    continue

                name_match = re.search(r"\*\*Name\*\*:\s*([^\n]+)", content)
                if name_match and any(token in query for token in ['my name', 'call me', 'asked you to call']):
                    name = name_match.group(1).strip().strip('*').strip()
                    if 'call me' in query or 'asked you to call' in query:
                        return (
                            f"Your user profile in jarvis-intel says your name is {name}. "
                            f"I don't see a separate nickname in that file, so the clearest supported answer is {name}."
                        )
                    return f"Your user profile in jarvis-intel says your name is {name}."

        return None

    def _synthesize_from_existing_tool_result(
        self,
        orchestrator,
        record: dict,
        note: str,
        result: dict,
        strategy: dict
    ) -> str | None:
        """Build a final answer from returned tool data without calling more tools."""
        record_mode = record.get('mode', 'cloud')
        direct_answer = self._extract_direct_answer_from_tool_data(record, result)
        if direct_answer:
            return direct_answer

        result_data = result.get('data') or {}
        if not result_data:
            return None

        synthesis_prompt = f"""You are synthesizing a repaired final answer from existing tool output only.

Do not call any tools.
Do not mention byte counts, file read boilerplate, or internal tool mechanics.
If the tool output already contains the answer, answer directly from it.
If the tool output is still insufficient, reply with exactly: UNRESOLVED

Original user request:
{record.get('query', '')}

{self._get_completion_guard_location_context(record_mode)}

User completion note:
{note or '(none)'}

Repair strategy:
{self._format_completion_guard_strategy(strategy)}

Returned tool data:
```json
{self._truncate_for_prompt(result_data, max_chars=8000)}
```
"""

        try:
            response = orchestrator.router.provider.chat(
                synthesis_prompt,
                system_prompt=(
                    "You synthesize final user-facing answers from existing tool results only. "
                    "Do not invent facts. Max 120 words."
                )
            )
        except Exception as synth_err:
            print(f"[COMPLETION_GUARD] Synthesis fallback failed: {synth_err}")
            return None

        if not response or not isinstance(response, str):
            return None

        cleaned = response.strip()
        if not cleaned or cleaned.upper().startswith('UNRESOLVED'):
            return None
        if self._is_machine_like_completion_text(cleaned):
            return None
        return cleaned

    def _write_completion_guard_ticket(self, record: dict, note: str = '') -> Path:
        """Write a markdown ticket describing the completion failure."""
        tickets_dir = JARVIS_ROOT / 'logs' / 'completion-guard'
        tickets_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now()
        safe_conv = record.get('conversation_id', 'unknown')
        safe_msg = record.get('message_id', 'unknown')[:8]
        filename = f"{timestamp.strftime('%Y-%m-%d-%H%M%S')}-{safe_conv}-{safe_msg}-completion-guard.md"
        ticket_path = tickets_dir / filename

        def dump_json(value):
            try:
                return json.dumps(value, indent=2, ensure_ascii=False)
            except Exception:
                return str(value)

        content = f"""# Completion Guard Ticket

- Timestamp: {timestamp.isoformat()}
- Conversation ID: {record.get('conversation_id', 'unknown')}
- Web Message ID: {record.get('message_id', 'unknown')}
- Mode: {record.get('mode', 'unknown')}
- Provider: {record.get('provider', 'unknown')}
- Model: {record.get('model', 'unknown')}
- Ticket Reason: User marked response as not completed correctly

## User Query

{record.get('query', '').strip() or '(empty)'}

## User Note

{note.strip() or '(none)'}

## Spoken Response

{record.get('speech', '').strip() or '(empty)'}

## Raw LLM Response

{record.get('raw_llm_response', '').strip() or '(empty)'}

## Tools Used

{', '.join(record.get('tools_used', [])) or '(none)'}

## Server-Side Tools

```json
{dump_json(record.get('server_side_tools', {}))}
```

## Usage

```json
{dump_json(record.get('usage', {}))}
```

## Tool / Result Data

```json
{dump_json(record.get('data', {}))}
```

## Completion Guard Config

```json
{dump_json(record.get('completion_guard', {}))}
```
"""

        repair_strategy = record.get('repair_strategy')
        if repair_strategy:
            content += f"""

## Repair Strategy

```json
{dump_json(repair_strategy)}
```
"""

        auto_evaluation = record.get('auto_evaluation')
        if auto_evaluation:
            content += f"""

## Auto Evaluation

```json
{dump_json(auto_evaluation)}
```
"""

        repair_result = record.get('repair_result')
        if repair_result:
            content += f"""

## Repair Attempt

- Status: {repair_result.get('status', 'unknown')}
- Tools Used: {', '.join(repair_result.get('tools_used', [])) or '(none)'}

### Repair Response

{repair_result.get('speech', '').strip() or '(empty)'}

### Repair Raw Response

{repair_result.get('raw_llm_response', '').strip() or '(empty)'}
"""

        ticket_path.write_text(content, encoding='utf-8')
        return ticket_path

    @_scoped_by_mode
    def _run_completion_guard_auto_eval(self, session_id: str, record: dict):
        """Evaluate a completed response and auto-trigger repair when the audit score is high enough."""
        message_id = record.get('message_id')
        conversation_id = record.get('conversation_id')
        config = record.get('completion_guard', {})
        threshold = float(config.get('auto_threshold', 0.70) or 0.70)

        if record.get('status') not in (None, 'pending'):
            return

        try:
            evaluation = self._evaluate_completion_guard_auto(record)
            if not evaluation:
                raw_auto = (record.get('auto_evaluation') or {}).get('raw_response')
                if raw_auto:
                    preview = raw_auto[:1200].replace('\n', '\\n')
                    print(
                        "[COMPLETION_GUARD] Unparseable auto-eval raw response "
                        f"(provider={config.get('eval_provider')}, model={config.get('eval_model')}): {preview}"
                    )
                print(
                    "[COMPLETION_GUARD] Auto evaluation returned no parseable result "
                    f"(provider={config.get('eval_provider')}, model={config.get('eval_model')})"
                )
                self._start_feedback_async(
                    session_id,
                    message_id,
                    message_id,
                    record,
                    self._build_feedback_result_from_record(record),
                    record.get('tools_used', []),
                    'none'
                )
                return

            record['auto_evaluation'] = evaluation
            repair_score = float(evaluation.get('repair_score', 0.0) or 0.0)
            recommended_action = evaluation.get('recommended_action', 'accept')
            needs_repair = repair_score >= threshold
            note = evaluation.get('suggested_note') or evaluation.get('reason', '')

            from ..services.conversation_store import get_conversation_store
            store = get_conversation_store()

            # Judge "tighten_only" = minor wording/hedging issues only; no repair run.
            # Settle as auto_accepted so we do not label the turn "tighten_only" when nothing
            # was rewritten. Real tighten_only is reserved for post-repair settlement.
            if recommended_action == 'tighten_only':
                record['status'] = 'auto_accepted'
                store.update_message_data_by_web_message_id(
                    conversation_id,
                    message_id,
                    {
                        '_completion_guard': {
                            'status': 'auto_accepted',
                            'auto_evaluation': evaluation,
                            'evaluator_recommended_action': 'tighten_only',
                            'evaluated_at': datetime.now().isoformat()
                        }
                    }
                )
                self._update_completion_guard_experience(
                    record,
                    'auto_accepted',
                    note=note,
                    extra={
                        'auto_evaluation': evaluation,
                        'evaluator_recommended_action': 'tighten_only',
                        'operational_correction': False
                    }
                )
                self._start_feedback_async(
                    session_id,
                    message_id,
                    message_id,
                    record,
                    self._build_feedback_result_from_record(record),
                    record.get('tools_used', []),
                    'auto_accepted'
                )
                return

            if not needs_repair:
                record['status'] = 'auto_accepted'
                store.update_message_data_by_web_message_id(
                    conversation_id,
                    message_id,
                    {
                        '_completion_guard': {
                            'status': 'auto_accepted',
                            'auto_evaluation': evaluation,
                            'evaluated_at': datetime.now().isoformat()
                        }
                    }
                )
                self._update_completion_guard_experience(
                    record,
                    'auto_accepted',
                    note='',
                    extra={'auto_evaluation': evaluation}
                )
                self._start_feedback_async(
                    session_id,
                    message_id,
                    message_id,
                    record,
                    self._build_feedback_result_from_record(record),
                    record.get('tools_used', []),
                    'auto_accepted'
                )
                return

            attempts = int(record.get('repair_attempts', 0) or 0)
            if attempts >= 1:
                return

            record['status'] = 'repairing'
            record['user_note'] = note
            record['repair_attempts'] = attempts + 1
            store.update_message_data_by_web_message_id(
                conversation_id,
                message_id,
                {
                    '_completion_guard': {
                        'status': 'repairing',
                        'note': note,
                        'auto_triggered': True,
                        'auto_evaluation': evaluation,
                        'started_at': datetime.now().isoformat()
                    }
                }
            )

            self._run_completion_guard_repair(session_id, record, note)

        except Exception as e:
            print(f"[COMPLETION_GUARD] Auto evaluation failed: {e}")
            self._start_feedback_async(
                session_id,
                message_id,
                message_id,
                record,
                self._build_feedback_result_from_record(record),
                record.get('tools_used', []),
                'none'
            )

    @_scoped_by_mode
    def _run_completion_guard_repair(self, session_id: str, record: dict, note: str = ''):
        """Run one bounded repair attempt before falling back to ticketing."""
        conversation_id = record.get('conversation_id')
        parent_message_id = record.get('message_id')
        mode = record.get('mode', 'cloud')
        repair_message_id = str(uuid.uuid4())
        start_time = time.time()

        self.socketio.emit('completion_guard:updated', {
            'message_id': parent_message_id,
            'conversation_id': conversation_id,
            'status': 'repairing',
            'auto_triggered': bool(record.get('auto_evaluation'))
        }, room=session_id)

        self.socketio.emit('chat:thinking', {
            'message_id': repair_message_id,
            'conversation_id': conversation_id
        }, room=session_id)

        self.socketio.emit('chat:status', {
            'message_id': repair_message_id,
            'conversation_id': conversation_id,
            'status': "Let's see if we can find a better solution.",
            'timestamp': time.time()
        }, room=session_id)

        try:
            from orchestrator_v2 import Orchestrator

            provider_override = record.get('provider') or None
            model_override = record.get('model') or None
            orchestrator = Orchestrator(
                mode=mode,
                provider_override=provider_override,
                model_override=model_override
            )
            orchestrator.set_web_conversation_id(conversation_id)
            orchestrator.set_learning_enabled(False)
            orchestrator.set_cancel_check(
                lambda: self.pending_cancellations.get(repair_message_id, False)
            )

            def status_callback(status_message: str):
                self.socketio.emit('chat:status', {
                    'message_id': repair_message_id,
                    'conversation_id': conversation_id,
                    'status': status_message,
                    'timestamp': time.time()
                }, room=session_id)

            def progress_callback(event_type: str, **kwargs):
                if event_type == 'tool_start':
                    tool_name = kwargs.get('tool')
                    call_index = kwargs.get('call_index', 0)
                    self.socketio.emit('tool:start', {
                        'message_id': repair_message_id,
                        'tool': tool_name,
                        'call_index': call_index,
                        'args': kwargs.get('args', {}),
                        'turn': kwargs.get('turn'),
                        'max_turns': kwargs.get('max_turns'),
                        'timestamp': time.time()
                    }, room=session_id)
                elif event_type == 'tool_complete':
                    tool_name = kwargs.get('tool')
                    call_index = kwargs.get('call_index', 0)
                    duration_ms = kwargs.get('duration_ms')
                    success = kwargs.get('success')
                    event_name = 'tool:complete' if success else 'tool:error'
                    payload = {
                        'message_id': repair_message_id,
                        'tool': tool_name,
                        'call_index': call_index,
                        'duration_ms': duration_ms,
                        'timestamp': time.time()
                    }
                    if success:
                        payload['result'] = {}
                        payload['success'] = True
                    else:
                        payload['error'] = kwargs.get('error', 'Unknown error')
                    self.socketio.emit(event_name, payload, room=session_id)
                elif event_type == 'routing':
                    self.socketio.emit('tool:progress', {
                        'message_id': repair_message_id,
                        'status': kwargs.get('message'),
                        'timestamp': time.time()
                    }, room=session_id)

            orchestrator.set_status_callback(status_callback)
            orchestrator.set_progress_callback(progress_callback)
            repair_strategy = self._classify_completion_guard_strategy(record, note)
            record['repair_strategy'] = repair_strategy

            repair_prompt = f"""[COMPLETION GUARD REPAIR - CONTINUE THE SAME TASK, DO NOT START OVER]

You are repairing a previous Jarvis answer that the user marked as incomplete or incorrect.

Return your response in this exact format:
REPAIR_STATUS: repaired
or
REPAIR_STATUS: unresolved

Then provide the corrected user-facing answer.

Rules:
- Do not answer from scratch
- Audit the prior raw answer first
- Use the full raw answer, not the shortened speech text, as the main thing to critique
- Do not repeat unsupported claims
- If the previous answer made a strong claim like shut down, deprecated, removed, saved, created, updated, or sent, verify it before repeating it
- Prefer fixing the smallest missing step
- You may use tools if needed, but only when they clearly help verify or correct the issue
- Do not spend a repair pass on wording-only cleanup unless you find new evidence or a materially better tool path
- Do not just repeat the same failed retrieval path if it came back empty or weak
- If one memory/search tool did not find enough, consider a different tool path that can inspect the source more directly
- If the user references a specific file, folder, path, or source, treat that as a concrete lead and inspect it instead of only doing semantic recall
- For intel or profile questions, prefer direct intel/file inspection when the user points to a known intel file or path
- If a tool in this repair pass already returns the answer in its data, stop and answer from that data directly
- If a prior artifact such as a canvas page is now known to be wrong and you have enough context, update it
- If you still cannot resolve the issue after one attempt, use REPAIR_STATUS: unresolved and explain exactly what remains uncertain
- Do not write to jarvis-learned-lessons.md unless this repair uncovers a real reusable operational lesson, provider quirk, or tool limitation. Rewording alone is not lesson-worthy.

Repair strategy hints:
{self._format_completion_guard_strategy(repair_strategy)}

Original user request:
{record.get('query', '')}

User completion note:
{note or '(none)'}

Prior spoken response:
{record.get('speech', '')}

Prior raw LLM response:
{record.get('raw_llm_response', '')}

Tools used previously:
{', '.join(record.get('tools_used', [])) or '(none)'}

Previous structured data:
```json
{self._truncate_for_prompt(record.get('data', {}), max_chars=8000)}
```
"""

            result = orchestrator.process(repair_prompt)
            if repair_message_id in self.pending_cancellations:
                del self.pending_cancellations[repair_message_id]
            raw_response = result.get('raw_llm_response', '') or result.get('speech', '')
            repair_status, cleaned_raw = self._extract_repair_status(raw_response)
            _, cleaned_speech = self._extract_repair_status(result.get('speech', '') or '')

            if result.get('cancelled'):
                record['status'] = 'cancelled'
                record['user_note'] = note
                from ..services.conversation_store import get_conversation_store
                store = get_conversation_store()
                store.update_message_data_by_web_message_id(
                    conversation_id,
                    parent_message_id,
                    {
                        '_completion_guard': {
                            'status': 'cancelled',
                            'note': note,
                            'cancelled_at': datetime.now().isoformat(),
                            'auto_evaluation': record.get('auto_evaluation')
                        }
                    }
                )
                self._update_completion_guard_experience(
                    record,
                    'cancelled',
                    note=note,
                    extra={
                        'auto_evaluation': record.get('auto_evaluation'),
                        'repair_result': {
                            'status': 'cancelled',
                            'speech': result.get('speech', ''),
                            'raw_llm_response': result.get('raw_llm_response', ''),
                            'tools_used': result.get('tools_used', [])
                        }
                    }
                )
                self.socketio.emit('completion_guard:updated', {
                    'message_id': parent_message_id,
                    'conversation_id': conversation_id,
                    'status': 'cancelled',
                    'note': note
                }, room=session_id)
                self.socketio.emit('chat:cancelled', {
                    'conversation_id': conversation_id,
                    'message_id': repair_message_id
                }, room=session_id)
                self._start_feedback_async(
                    session_id,
                    parent_message_id,
                    parent_message_id,
                    record,
                    self._build_feedback_result_from_record(record),
                    record.get('tools_used', []),
                    'cancelled'
                )
                return

            if cleaned_raw:
                result['raw_llm_response'] = cleaned_raw
            if cleaned_speech:
                result['speech'] = cleaned_speech
            elif cleaned_raw and result.get('speech'):
                result['speech'] = cleaned_raw

            if result.get('data') and (
                repair_status != 'repaired'
                or self._is_machine_like_completion_text(result.get('speech', ''))
                or self._is_machine_like_completion_text(result.get('raw_llm_response', ''))
            ):
                synthesized_answer = self._synthesize_from_existing_tool_result(
                    orchestrator,
                    record,
                    note,
                    result,
                    repair_strategy
                )
                if synthesized_answer:
                    result['speech'] = synthesized_answer
                    result['raw_llm_response'] = synthesized_answer
                    repair_status = 'repaired'

            delta = self._analyze_completion_guard_delta(record, result)
            operational_correction = bool(delta.get('operational_correction'))

            original_tools = delta.get('original_tools', []) or []
            repair_tools = delta.get('repair_tools', []) or []
            if (
                not original_tools
                and not repair_tools
                and not self._repair_has_explicit_source_or_verified_action(result)
            ):
                operational_correction = False
                delta['operational_correction'] = False
                delta['no_tool_rewrite_defaulted'] = True

            if self._completion_guard_tighten_instead_of_substantive_repair(delta):
                operational_correction = False
                delta['operational_correction'] = False
                delta['tighten_only_similar_answer'] = True

            # Require an explicit repaired marker. Missing markers should not be treated as success.
            repaired = result.get('ok', True) and repair_status == 'repaired'
            tighten_only = repaired and not operational_correction
            if tighten_only:
                repaired = False

            record['status'] = 'tighten_only' if tighten_only else ('repaired' if repaired else 'unresolved')
            record['user_note'] = note
            record['repair_message_id'] = repair_message_id
            record['repair_result'] = {
                'status': 'tighten_only' if tighten_only else (repair_status or ('repaired' if repaired else 'unresolved')),
                'speech': result.get('speech', ''),
                'raw_llm_response': result.get('raw_llm_response', ''),
                'tools_used': result.get('tools_used', []),
                'strategy_family': repair_strategy.get('family'),
                'delta': delta
            }

            from ..services.conversation_store import get_conversation_store
            store = get_conversation_store()

            response_text = ''
            prepared_speech = ''
            save_data = (result.get('data') or {}).copy() if isinstance(result.get('data'), dict) else {'result': result.get('data')}
            if result.get('raw_llm_response'):
                save_data['raw_llm_response'] = result['raw_llm_response']
            repair_usage = enrich_usage_metadata(
                result.get('usage'),
                record.get('provider'),
                record.get('model'),
            )
            if repair_usage:
                save_data['usage'] = repair_usage
            save_data['_web_message_id'] = repair_message_id
            save_data['_completion_guard'] = {
                'status': 'repair_response',
                'repaired_from_message_id': parent_message_id,
                'created_at': datetime.now().isoformat()
            }

            if not tighten_only:
                response_text, prepared_speech = self._prepare_web_response_text(
                    result,
                    "I found a better answer and shared it in chat."
                )
                if prepared_speech:
                    save_data['speech'] = prepared_speech
                ev = self._compute_effective_evidence(
                    conversation_id,
                    save_data,
                    result.get('tools_used', []),
                    result.get('server_side_tools', {}),
                    repair_message_id,
                    record.get('query', '') or '',
                )
                if ev:
                    save_data['_effective_evidence'] = ev
                store.add_message(
                    conversation_id,
                    'assistant',
                    response_text,
                    data=save_data,
                    tools_used=result.get('tools_used', [])
                )

            store.update_message_data_by_web_message_id(
                conversation_id,
                parent_message_id,
                {
                    '_completion_guard': {
                        'status': 'tighten_only' if tighten_only else ('repaired' if repaired else 'unresolved'),
                        'note': note,
                        'repaired_at': datetime.now().isoformat(),
                        'repair_message_id': repair_message_id,
                        'auto_evaluation': record.get('auto_evaluation'),
                        'delta': delta
                    }
                }
            )

            self._update_completion_guard_experience(
                record,
                'tighten_only' if tighten_only else ('repaired' if repaired else 'unresolved'),
                note=note,
                extra={
                    'repair_result': record.get('repair_result', {}),
                    'repair_data': save_data,
                    'repair_strategy': repair_strategy,
                    'auto_evaluation': record.get('auto_evaluation'),
                    'operational_correction': operational_correction
                }
            )

            audio_url = None
            if not tighten_only:
                try:
                    from ..config import get_web_setting
                    if get_web_setting('audio.tts_enabled', False):
                        speech_text = prepared_speech
                        if speech_text:
                            audio_url = self._generate_tts(speech_text, mode=mode)
                            if audio_url:
                                save_data['audio_url'] = audio_url
                                store.update_message_data_by_web_message_id(
                                    conversation_id,
                                    repair_message_id,
                                    {'audio_url': audio_url}
                                )
                except Exception as tts_err:
                    print(f"[COMPLETION_GUARD] TTS generation failed: {tts_err}")

            self.socketio.emit('completion_guard:updated', {
                'message_id': parent_message_id,
                'conversation_id': conversation_id,
                'status': 'tighten_only' if tighten_only else ('repaired' if repaired else 'unresolved'),
                'note': note,
                'delta': delta
            }, room=session_id)

            if not tighten_only:
                self.socketio.emit('chat:response', {
                    'message_id': repair_message_id,
                    'conversation_id': conversation_id,
                    'text': response_text,
                    'speech': prepared_speech,
                    'data': save_data,
                    'tools_used': result.get('tools_used', []),
                    'ok': result.get('ok', True),
                    'cancelled': False,
                    'duration_ms': int((time.time() - start_time) * 1000),
                    'usage': repair_usage or {},
                    'audio_url': audio_url,
                    'server_side_tools': result.get('server_side_tools', {}),
                    'completion_guard': {
                        'enabled': False,
                        'mode': 'off',
                        'ticket_on_fail': record.get('completion_guard', {}).get('ticket_on_fail', True),
                        'prompt_user': False
                    }
                }, room=session_id)

            feedback_result_payload = {
                'ok': result.get('ok', True),
                'speech': prepared_speech,
                'raw_llm_response': result.get('raw_llm_response', ''),
                'data': save_data,
                'usage': repair_usage or {},
                'server_side_tools': result.get('server_side_tools', {}),
                'experience_id': record.get('experience_id'),
                'intelligence_context': record.get('intelligence_context', '')
            }
            feedback_tools_used = self._combine_feedback_tools(
                record.get('tools_used', []),
                result.get('tools_used', [])
            )

            if (not repaired and not tighten_only) and record.get('completion_guard', {}).get('ticket_on_fail', True):
                ticket_path = self._write_completion_guard_ticket(record, note)
                rel_path = str(ticket_path.relative_to(JARVIS_ROOT))
                record['status'] = 'ticket_created'
                record['ticket_path'] = rel_path
                store.update_message_data_by_web_message_id(
                    conversation_id,
                    parent_message_id,
                    {
                        '_completion_guard': {
                            'status': 'ticket_created',
                            'ticket_path': rel_path,
                            'note': note,
                            'created_at': datetime.now().isoformat(),
                            'repair_message_id': repair_message_id,
                            'auto_evaluation': record.get('auto_evaluation')
                        }
                    }
                )
                self._update_completion_guard_experience(
                    record,
                    'ticket_created',
                    note=note,
                    extra={
                        'ticket_path': rel_path,
                        'repair_result': record.get('repair_result', {}),
                        'repair_data': save_data,
                        'repair_strategy': repair_strategy,
                        'auto_evaluation': record.get('auto_evaluation')
                    }
                )
                self.socketio.emit('completion_guard:ticket_created', {
                    'message_id': parent_message_id,
                    'conversation_id': conversation_id,
                    'ticket_path': rel_path,
                    'note': note
                }, room=session_id)
                self._start_feedback_async(
                    session_id,
                    parent_message_id,
                    repair_message_id,
                    record,
                    feedback_result_payload,
                    feedback_tools_used,
                    'ticket_created'
                )
            else:
                self._start_feedback_async(
                    session_id,
                    parent_message_id,
                    repair_message_id if not tighten_only else parent_message_id,
                    record,
                    feedback_result_payload if not tighten_only else self._build_feedback_result_from_record(record),
                    feedback_tools_used if not tighten_only else record.get('tools_used', []),
                    'tighten_only' if tighten_only else ('repaired' if repaired else 'unresolved')
                )

        except Exception as e:
            print(f"[COMPLETION_GUARD] Repair failed: {e}")
            if repair_message_id in self.pending_cancellations:
                del self.pending_cancellations[repair_message_id]
            record['status'] = 'error'
            record['user_note'] = note
            record['repair_result'] = {
                'status': 'error',
                'speech': '',
                'raw_llm_response': str(e),
                'tools_used': []
            }
            if record.get('completion_guard', {}).get('ticket_on_fail', True):
                try:
                    ticket_path = self._write_completion_guard_ticket(record, note)
                    rel_path = str(ticket_path.relative_to(JARVIS_ROOT))
                    record['status'] = 'ticket_created'
                    record['ticket_path'] = rel_path
                    from ..services.conversation_store import get_conversation_store
                    store = get_conversation_store()
                    store.update_message_data_by_web_message_id(
                        conversation_id,
                        parent_message_id,
                        {
                            '_completion_guard': {
                                'status': 'ticket_created',
                                'ticket_path': rel_path,
                                'note': note,
                                'created_at': datetime.now().isoformat(),
                                'auto_evaluation': record.get('auto_evaluation')
                            }
                        }
                    )
                    self._update_completion_guard_experience(
                        record,
                        'ticket_created',
                        note=note,
                        extra={
                            'ticket_path': rel_path,
                            'repair_result': record.get('repair_result', {}),
                            'repair_data': {},
                            'repair_strategy': record.get('repair_strategy', {}),
                            'auto_evaluation': record.get('auto_evaluation')
                        }
                    )
                    self.socketio.emit('completion_guard:ticket_created', {
                        'message_id': parent_message_id,
                        'conversation_id': conversation_id,
                        'ticket_path': rel_path,
                        'note': note
                    }, room=session_id)
                    self._start_feedback_async(
                        session_id,
                        parent_message_id,
                        parent_message_id,
                        record,
                        self._build_feedback_result_from_record(record),
                        record.get('tools_used', []),
                        'ticket_created'
                    )
                except Exception as ticket_err:
                    self.socketio.emit('completion_guard:error', {
                        'message_id': parent_message_id,
                        'error': f'Completion Guard repair and ticketing failed: {ticket_err}'
                    }, room=session_id)
            else:
                self.socketio.emit('completion_guard:error', {
                    'message_id': parent_message_id,
                    'error': f'Completion Guard repair failed: {e}'
                }, room=session_id)
                self._start_feedback_async(
                    session_id,
                    parent_message_id,
                    parent_message_id,
                    record,
                    self._build_feedback_result_from_record(record),
                    record.get('tools_used', []),
                    'error'
                )
    
    def _register_handlers(self):
        """Register all socket event handlers"""
        
        @self.socketio.on('connect')
        def handle_connect():
            session_id = request.sid
            
            # Use startup mode as default for new sessions
            from ..app import get_startup_mode
            default_mode = get_startup_mode()
            
            self.sessions[session_id] = {
                'mode': default_mode,
                'conversation_id': None,
                'conversation_room': None,
                'connected_at': time.time(),
                'completion_guard_records': {}
            }
            
            # Join personal room
            join_room(session_id)
            
            # Send connection confirmation
            from ..services.tool_discovery import get_tool_service
            tool_service = get_tool_service()
            
            emit('connected', {
                'session_id': session_id,
                'mode': default_mode,
                'tools_count': tool_service.get_tool_count(),
                'deployment': (
                    'docker'
                    if os.environ.get('JARVIS_DEPLOYMENT', '').strip().lower() == 'docker'
                    else 'native'
                )
            })
            print(f"[WS] Client connected: {session_id} (default mode: {default_mode})")
        
        @self.socketio.on('disconnect')
        def handle_disconnect():
            session_id = request.sid
            if session_id in self.sessions:
                prior_room = self.sessions[session_id].get('conversation_room')
                if prior_room:
                    leave_room(prior_room)
                del self.sessions[session_id]
            leave_room(session_id)
            print(f"[WS] Client disconnected: {session_id}")
        
        @self.socketio.on('cancel')
        def handle_cancel(data):
            """Handle request to cancel current processing"""
            session_id = request.sid
            message_id = data.get('message_id')
            
            if message_id:
                self.pending_cancellations[message_id] = True
                print(f"[WS] Cancel requested for message {message_id}")
                
                # Acknowledge cancellation request
                emit('cancel:ack', {
                    'message_id': message_id,
                    'status': 'stopping'
                }, room=session_id)
        
        @self.socketio.on('chat:send')
        def handle_chat_send(data):
            """Handle incoming chat message (with optional image, text file, and command metadata)"""
            session_id = request.sid
            message = data.get('message', '').strip()
            mode = data.get('mode', self.sessions.get(session_id, {}).get('mode', 'cloud'))
            conversation_id = data.get('conversation_id')
            
            # Image data (with optional action routing and settings)
            image_data = data.get('image')  # {images: [...], action?, settings?} or legacy single shape
            
            # Text file context (read client-side, no server upload needed)
            file_context = data.get('file_context')  # {name, content, size}
            
            # Feedback request - either from toggle or --feedback flag in message
            request_feedback = data.get('request_feedback', False)
            if '--feedback' in message:
                request_feedback = True
                message = message.replace('--feedback', '').strip()
            
            # Prompt metadata from @prompt system (workflows are handled by orchestrator)
            prompt_meta = {
                'system_instruction': data.get('system_instruction'),
                'prompt_name': data.get('prompt_name'),
                'tool_hints': self._sanitize_tool_hints(data.get('tool_hints')),
                'request_kind': (
                    'canvas_export'
                    if data.get('request_kind') == 'canvas_export'
                    else ''
                ),
            }
            
            from vision_multimodal import max_vision_images, normalize_web_image_payload
            normalized_image = normalize_web_image_payload(image_data)

            if not message and not normalized_image and not file_context:
                emit('chat:error', {
                    'error': 'Empty message',
                    'conversation_id': conversation_id
                })
                return
            
            # Default message for image-only
            if not message and normalized_image:
                image_count = len(normalized_image.get('images', []))
                message = "What's in these images?" if image_count > 1 else "What's in this image?"
            
            # Default message for file-only
            if not message and file_context:
                message = "Summarize this file."

            image_limit = max_vision_images(mode)
            if normalized_image:
                image_action = normalized_image.get('action', 'analyze')
                image_count = len(normalized_image.get('images', []))
                if image_action in ('video', 'image') and image_count > 1:
                    normalized_image['images'] = normalized_image['images'][:1]
                    emit('chat:status', {
                        'conversation_id': conversation_id,
                        'status': 'Video/Image mode uses one reference image; extra images ignored.',
                        'timestamp': time.time()
                    })
                elif image_action == 'analyze' and image_count > image_limit:
                    emit('chat:error', {
                        'error': f'Maximum {image_limit} images allowed in {mode} mode',
                        'conversation_id': conversation_id
                    })
                    return
                if image_action == 'analyze':
                    hydrate_error = self._hydrate_uploaded_image_payload(normalized_image)
                    if hydrate_error:
                        emit('chat:error', {
                            'error': hydrate_error,
                            'conversation_id': conversation_id
                        })
                        return
                image_data = normalized_image
            
            # Create or get conversation
            from ..services.conversation_store import get_conversation_store
            store = get_conversation_store()
            
            if not conversation_id:
                # Create new conversation
                conv = store.create_conversation()
                conversation_id = conv['id']
                # Notify client of new conversation
                emit('conversation:created', {
                    'conversation_id': conversation_id,
                    'title': conv['title']
                })

            self._supersede_pending_completion_guards(session_id, conversation_id)
            
            # Save user message (include image URL(s), file info, and prompt info if present)
            user_msg_data = {}
            if image_data:
                image_urls = [img.get('url') for img in image_data.get('images', []) if img.get('url')]
                if image_urls:
                    user_msg_data['image_urls'] = image_urls
                    user_msg_data['image_url'] = image_urls[0]
                if image_data.get('action'):
                    user_msg_data['image_action'] = image_data.get('action')
            if file_context:
                user_msg_data['attached_file'] = file_context.get('name')
            if prompt_meta.get('prompt_name'):
                user_msg_data['prompt'] = prompt_meta['prompt_name']
            if prompt_meta.get('tool_hints'):
                user_msg_data['tool_hints'] = prompt_meta['tool_hints']
            if prompt_meta.get('request_kind'):
                user_msg_data['request_kind'] = prompt_meta['request_kind']
            store.add_message(conversation_id, 'user', message, data=user_msg_data if user_msg_data else None)
            
            # Update session
            if session_id in self.sessions:
                self.sessions[session_id]['mode'] = mode
                self.sessions[session_id]['conversation_id'] = conversation_id
            self._join_conversation_room(session_id, conversation_id)
            
            # Generate message ID
            message_id = str(uuid.uuid4())
            
            # Emit thinking state
            emit('chat:thinking', {
                'message_id': message_id,
                'conversation_id': conversation_id
            })
            
            # Process in a real thread so long provider/tool calls do not block
            # Eventlet heartbeats and disconnect the browser mid-response.
            self._start_blocking_task(
                self._process_message,
                session_id,
                message,
                mode,
                message_id,
                conversation_id,
                image_data,
                prompt_meta,
                request_feedback,
                file_context,
                name=f"jarvis-chat-{message_id[:8]}",
            )

        @self.socketio.on('completion_guard:submit')
        def handle_completion_guard_submit(data):
            """Handle a user marking an answer as complete or requesting repair."""
            session_id = request.sid
            message_id = data.get('message_id')
            conversation_id = data.get('conversation_id')
            accepted = data.get('accepted')
            note = (data.get('note') or '').strip()

            session = self.sessions.get(session_id, {})
            records = session.get('completion_guard_records', {})
            record = records.get(message_id)

            if not message_id:
                emit('completion_guard:error', {
                    'message_id': message_id,
                    'error': 'Completion Guard message id was missing.'
                })
                return

            if not record:
                emit('completion_guard:updated', {
                    'message_id': message_id,
                    'conversation_id': conversation_id,
                    'status': 'expired',
                    'reason': 'missing_session_context'
                })
                return

            if record.get('status') == 'pending' and self._completion_guard_record_expired(record):
                self._settle_pending_completion_guard(
                    session_id,
                    record,
                    'expired',
                    'manual_prompt_timeout',
                    note,
                )
                return

            if accepted is True:
                record['status'] = 'accepted'
                record['user_note'] = note
                try:
                    from ..services.conversation_store import get_conversation_store
                    store = get_conversation_store()
                    store.update_message_data_by_web_message_id(
                        record.get('conversation_id'),
                        message_id,
                        {
                            '_completion_guard': {
                                'status': 'accepted',
                                'note': note,
                                'accepted_at': datetime.now().isoformat()
                            }
                        }
                    )
                    self._update_completion_guard_experience(
                        record,
                        'accepted',
                        note=note
                    )
                except Exception as e:
                    print(f"[COMPLETION_GUARD] Failed to persist accepted state: {e}")

                emit('completion_guard:updated', {
                    'message_id': message_id,
                    'conversation_id': conversation_id or record.get('conversation_id'),
                    'status': 'accepted',
                    'note': note
                })
                self._start_feedback_async(
                    session_id,
                    message_id,
                    message_id,
                    record,
                    self._build_feedback_result_from_record(record),
                    record.get('tools_used', []),
                    'accepted'
                )
                return

            if accepted is not False:
                emit('completion_guard:error', {
                    'message_id': message_id,
                    'error': 'Completion Guard action was not understood.'
                })
                return

            config = record.get('completion_guard', {})
            excluded_tools = set(config.get('excluded_tools', self.DEFAULT_COMPLETION_GUARD_EXCLUDED_TOOLS))
            if record.get('is_workflow') or any(
                tool in excluded_tools for tool in record.get('tools_used', [])
            ):
                emit('completion_guard:error', {
                    'message_id': message_id,
                    'error': 'Completion Guard repair is skipped for workflows and fire-and-forget tools.'
                })
                return

            existing_status = record.get('status')
            if existing_status == 'repairing':
                emit('completion_guard:updated', {
                    'message_id': message_id,
                    'conversation_id': conversation_id or record.get('conversation_id'),
                    'status': 'repairing',
                    'note': note
                })
                return

            if existing_status in ('repaired', 'unresolved', 'ticket_created'):
                emit('completion_guard:updated', {
                    'message_id': message_id,
                    'conversation_id': conversation_id or record.get('conversation_id'),
                    'status': existing_status,
                    'note': note or record.get('user_note', ''),
                    'ticket_path': record.get('ticket_path', '')
                })
                return

            attempts = int(record.get('repair_attempts', 0) or 0)
            if attempts >= 1:
                if not config.get('ticket_on_fail', True):
                    record['status'] = 'unresolved'
                    record['user_note'] = note or record.get('user_note', '')
                    emit('completion_guard:updated', {
                        'message_id': message_id,
                        'conversation_id': conversation_id or record.get('conversation_id'),
                        'status': 'unresolved',
                        'note': record.get('user_note', '')
                    })
                    self._start_feedback_async(
                        session_id,
                        message_id,
                        message_id,
                        record,
                        self._build_feedback_result_from_record(record),
                        record.get('tools_used', []),
                        'unresolved'
                    )
                    return

                try:
                    ticket_path = self._write_completion_guard_ticket(record, note or record.get('user_note', ''))
                    rel_path = str(ticket_path.relative_to(JARVIS_ROOT))
                    record['ticket_path'] = rel_path
                    record['user_note'] = note or record.get('user_note', '')
                    record['status'] = 'ticket_created'

                    from ..services.conversation_store import get_conversation_store
                    store = get_conversation_store()
                    store.update_message_data_by_web_message_id(
                        record.get('conversation_id'),
                        message_id,
                        {
                            '_completion_guard': {
                                'status': 'ticket_created',
                                'ticket_path': rel_path,
                                'note': record.get('user_note', ''),
                                'created_at': datetime.now().isoformat(),
                                'auto_evaluation': record.get('auto_evaluation')
                            }
                        }
                    )
                    self._update_completion_guard_experience(
                        record,
                        'ticket_created',
                        note=record.get('user_note', ''),
                        extra={
                            'ticket_path': rel_path,
                            'repair_result': record.get('repair_result', {}),
                            'repair_strategy': record.get('repair_strategy', {}),
                            'auto_evaluation': record.get('auto_evaluation')
                        }
                    )

                    self.socketio.emit('completion_guard:ticket_created', {
                        'message_id': message_id,
                        'conversation_id': conversation_id or record.get('conversation_id'),
                        'ticket_path': rel_path,
                        'note': record.get('user_note', '')
                    }, room=session_id)
                    self._start_feedback_async(
                        session_id,
                        message_id,
                        message_id,
                        record,
                        self._build_feedback_result_from_record(record),
                        record.get('tools_used', []),
                        'ticket_created'
                    )
                except Exception as e:
                    print(f"[COMPLETION_GUARD] Failed to create ticket after repair: {e}")
                    emit('completion_guard:error', {
                        'message_id': message_id,
                        'error': f'Failed to create ticket: {e}'
                    })
                return

            record['status'] = 'repairing'
            record['user_note'] = note
            record['repair_attempts'] = attempts + 1

            try:
                from ..services.conversation_store import get_conversation_store
                store = get_conversation_store()
                store.update_message_data_by_web_message_id(
                    record.get('conversation_id'),
                    message_id,
                    {
                        '_completion_guard': {
                            'status': 'repairing',
                            'note': note,
                            'started_at': datetime.now().isoformat()
                        }
                    }
                )

                self._start_blocking_task(
                    self._run_completion_guard_repair,
                    session_id,
                    record,
                    note,
                    name=f"completion-guard-repair-{message_id[:8]}",
                )
            except Exception as e:
                print(f"[COMPLETION_GUARD] Failed to start repair: {e}")
                emit('completion_guard:error', {
                    'message_id': message_id,
                    'error': f'Failed to start repair: {e}'
                })
        
        @self.socketio.on('conversation:load')
        def handle_load_conversation(data):
            """Load a conversation history"""
            session_id = request.sid
            conv_id = data.get('conversation_id')
            reconnect_only = self._parse_bool(data.get('reconnect_only'))
            
            if not conv_id:
                emit('chat:error', {'error': 'No conversation_id provided'})
                return
            
            from ..services.conversation_store import get_conversation_store
            store = get_conversation_store()
            
            conversation = store.get_conversation(conv_id)
            if conversation:
                # Update session
                if session_id in self.sessions:
                    self.sessions[session_id]['conversation_id'] = conv_id
                self._join_conversation_room(session_id, conv_id)

                if reconnect_only:
                    return

                emit('conversation:loaded', {
                    'conversation': conversation
                })
            else:
                emit('chat:error', {'error': 'Conversation not found'})
        
        @self.socketio.on('chat:cancel')
        def handle_chat_cancel(data):
            """Backward-compatible cancel alias for older clients."""
            session_id = request.sid
            message_id = data.get('message_id')

            if message_id:
                self.pending_cancellations[message_id] = True
                print(f"[WS] Cancel requested via chat:cancel for message {message_id}")
                emit('cancel:ack', {
                    'message_id': message_id,
                    'status': 'stopping'
                }, room=session_id)
                return

            emit('chat:cancelled', {
                'conversation_id': data.get('conversation_id')
            }, room=session_id)
        
        @self.socketio.on('mode:set')
        def handle_mode_set(data):
            """Set the mode for this session and reload settings"""
            session_id = request.sid
            mode = data.get('mode', 'cloud')
            
            if mode in ['cloud', 'local']:
                if session_id in self.sessions:
                    self.sessions[session_id]['mode'] = mode
                
                # Update settings manager and reload config for new mode
                from ..services.settings_manager import get_settings_manager
                from ..config import reload_web_config
                
                settings = get_settings_manager()
                settings.set_mode(mode)
                reload_web_config()
                
                # Intelligence instances are resolved per request/data mode.
                # Do not close them here: another in-flight chat may still be
                # recording to the other mode's database.
                
                # Reset tool registry (cleans up MCP containers)
                try:
                    from tool_schema import reset_tool_registry
                    reset_tool_registry()
                    print(f"[MODE] Reset tool registry for {mode} mode")
                except Exception as e:
                    print(f"[MODE] Warning: Could not reset tool registry: {e}")
                
                emit('mode:changed', {'mode': mode})
        
        @self.socketio.on('tools:refresh')
        def handle_tools_refresh():
            """Refresh tools list"""
            from ..services.tool_discovery import get_tool_service
            tool_service = get_tool_service()
            tool_service.refresh()
            
            emit('tools:updated', {
                'count': tool_service.get_tool_count(),
                'tools': tool_service.get_tools_summary()
            })
        
        # =====================================================================
        # Proactive Notification Handlers
        # =====================================================================
        
        @self.socketio.on('proactive:subscribe')
        def handle_proactive_subscribe(data=None):
            """Client wants to receive proactive notifications"""
            session_id = request.sid
            print(f"[Proactive] Client {session_id[:8]} subscribed to notifications")
            
            # Get current counts immediately
            from ..services.proactive_service import get_proactive_service
            service = get_proactive_service()
            counts = service.get_pending_counts()
            
            emit('proactive:counts', counts)
        
        @self.socketio.on('proactive:check')
        def handle_proactive_check(data=None):
            """Manual check for new notifications"""
            from ..services.proactive_service import get_proactive_service
            service = get_proactive_service()
            
            # Poll and get results
            result = service.poll_and_notify()
            
            # Send counts to this client
            emit('proactive:counts', result['counts'])
            
            # Send any new items
            for alert in result['new_alerts']:
                emit('proactive:alert', {
                    'type': 'alert',
                    'alert': alert,
                    'timestamp': time.time()
                })
            
            for reminder in result['new_reminders']:
                emit('proactive:reminder', {
                    'type': 'reminder',
                    'reminder': reminder,
                    'timestamp': time.time()
                })
        
        @self.socketio.on('proactive:ack_alert')
        def handle_ack_alert(data):
            """Acknowledge an alert"""
            alert_id = data.get('alert_id')
            if not alert_id:
                emit('proactive:error', {'error': 'Missing alert_id'})
                return
            
            from ..services.proactive_service import get_proactive_service
            service = get_proactive_service()
            
            success = service.acknowledge_alert(alert_id)
            if success:
                emit('proactive:ack_success', {
                    'type': 'alert',
                    'id': alert_id
                })
                # Broadcast updated counts
                self.socketio.emit('proactive:counts', service.get_pending_counts())
            else:
                emit('proactive:error', {'error': f'Failed to acknowledge alert {alert_id}'})
        
        @self.socketio.on('proactive:ack_reminder')
        def handle_ack_reminder(data):
            """Acknowledge a reminder"""
            reminder_id = data.get('reminder_id')
            if not reminder_id:
                emit('proactive:error', {'error': 'Missing reminder_id'})
                return
            
            from ..services.proactive_service import get_proactive_service
            service = get_proactive_service()
            
            success = service.acknowledge_reminder(reminder_id)
            if success:
                emit('proactive:ack_success', {
                    'type': 'reminder',
                    'id': reminder_id
                })
                # Broadcast updated counts
                self.socketio.emit('proactive:counts', service.get_pending_counts())
            else:
                emit('proactive:error', {'error': f'Failed to acknowledge reminder {reminder_id}'})
        
        # =====================
        # Log Streaming Events
        # =====================
        
        @self.socketio.on('logs:subscribe')
        def handle_logs_subscribe(data):
            """Subscribe to log streaming"""
            session_id = request.sid
            sources = data.get('sources', ['llm', 'tool'])  # Default sources
            
            print(f"[LOGS] Client {session_id[:8]} subscribing to logs: {sources}")
            
            # Join logs room
            join_room('logs_subscribers')
            
            # Start log streamer if not running
            self._ensure_log_streamer_running()
            
            emit('logs:subscribed', {
                'sources': sources,
                'available': list(self._get_log_sources().keys())
            })
        
        @self.socketio.on('logs:unsubscribe')
        def handle_logs_unsubscribe():
            """Unsubscribe from log streaming"""
            session_id = request.sid
            leave_room('logs_subscribers')
            print(f"[LOGS] Client {session_id[:8]} unsubscribed from logs")
            emit('logs:unsubscribed', {})
        
        @self.socketio.on('logs:set_sources')
        def handle_logs_set_sources(data):
            """Enable/disable specific log sources"""
            sources = data.get('sources', {})  # {source: enabled}
            
            
            # Get or create streamer
            streamer = self._get_log_streamer()
            if streamer:
                for source, enabled in sources.items():
                    streamer.set_source_enabled(source, enabled)
                
                emit('logs:sources_updated', streamer.get_enabled_sources())
        
        @self.socketio.on('logs:get_sources')
        def handle_logs_get_sources():
            """Get available log sources and their enabled state"""
            emit('logs:sources', self._get_log_sources())
    
    def _get_log_sources(self) -> dict:
        """Get available log sources with enabled state"""
        from ..services.log_streamer import LogStreamer
        return {
            source: {
                'enabled': config['enabled'],
                'name': source.upper(),
                'description': self._get_source_description(source)
            }
            for source, config in LogStreamer.LOG_SOURCES.items()
        }
    
    def _get_source_description(self, source: str) -> str:
        """Get human-readable description for a log source"""
        descriptions = {
            'llm': 'LLM API calls (tokens, cost, latency)',
            'tool': 'Tool executions (success, timing)',
            'opencode': 'OpenCode sessions',
            'thinking': 'Reasoning decisions (if enabled)',
            'feedback': 'Feedback ratings'
        }
        return descriptions.get(source, source)
    
    def _ensure_log_streamer_running(self):
        """Ensure the log streamer is running and broadcasting"""
        if not hasattr(self, '_log_streamer') or self._log_streamer is None:
            from ..services.log_streamer import LogStreamer
            
            def broadcast_log(entry):
                """Broadcast log entry to all subscribed clients"""
                self.socketio.emit('logs:entry', entry.to_dict(), room='logs_subscribers')
            
            self._log_streamer = LogStreamer(broadcast_log)
            self._log_streamer.start()
            print("[LOGS] Log streamer started")
    
    def _get_log_streamer(self):
        """Get the log streamer instance"""
        return getattr(self, '_log_streamer', None)
    
    def _get_conversation_context(self, conversation_id: str) -> list:
        """Get recent conversation history for LLM context"""
        try:
            from ..services.conversation_store import get_conversation_store
            from ..config import get_web_setting
            store = get_conversation_store()
            
            conversation = store.get_conversation(conversation_id)
            if not conversation:
                return []
            
            messages = conversation.get('messages', [])
            # The current user message is saved before background processing starts.
            # Exclude a trailing user-only turn so "conversation history" means prior context,
            # not the in-flight request being processed right now.
            if messages and messages[-1].get('role') == 'user':
                messages = messages[:-1]
            
            # Get configurable history limit (default 20)
            history_limit = get_web_setting('conversation.history_limit', 20)
            
            # Format for orchestrator: [{role, content, timestamp?, tools_used?, tool_results?}, ...]
            history = []
            for msg in messages[-history_limit:]:
                role = msg.get('role', 'user')
                content = msg.get('content', '')
                if content:
                    entry = {'role': role, 'content': content}
                    if msg.get('timestamp'):
                        entry['timestamp'] = msg.get('timestamp')
                    # Include tools_used for assistant messages so LLM knows what tools were run
                    if role == 'assistant' and msg.get('tools_used'):
                        entry['tools_used'] = msg.get('tools_used')
                    if role == 'assistant' and isinstance(msg.get('data'), dict):
                        exp_id = msg['data'].get('experience_id')
                        if exp_id:
                            entry['experience_id'] = exp_id
                    # Include key tool result data for follow-up capability
                    if role == 'assistant' and msg.get('data'):
                        tool_data = self._extract_followup_data(msg.get('data', {}))
                        if tool_data:
                            entry['tool_results'] = tool_data
                    history.append(entry)
            
            return history
        except Exception as e:
            print(f"[CHAT] Error getting conversation context: {e}")
            return []
    
    def _extract_followup_data(self, data: dict, max_candidates: int | None = None) -> dict | None:
        """Thin delegate to services.followup_extractor.extract_followup_data.

        Implementation lives in jarvis-web/server/services/followup_extractor.py.
        Kept here as an instance method so existing tests and call sites stay stable.
        """
        return extract_followup_data(data, max_candidates=max_candidates)

    @staticmethod
    def _truncate_followup_summary(summary: str, max_chars: int = _FOLLOWUP_SUMMARY_MAX_CHARS) -> str:
        """Delegate to services.followup_extractor.truncate_followup_summary."""
        return truncate_followup_summary(summary, max_chars=max_chars)

    def _extract_text_summarizer_followup(self, value, max_candidates: int) -> dict | None:
        """Delegate to services.followup_extractor.extract_text_summarizer_followup."""
        return extract_text_summarizer_followup(value, max_candidates)

    def _compact_text_summarizer_item(self, item: dict) -> dict | None:
        """Delegate to services.followup_extractor.compact_text_summarizer_item."""
        return compact_text_summarizer_item(item)

    @staticmethod
    def _data_without_effective_evidence(data: dict) -> dict:
        return {k: v for k, v in data.items() if k != '_effective_evidence'}

    @staticmethod
    def _should_inherit_effective_evidence(user_query: str) -> bool:
        """Heuristic: short refinements and follow-ups inherit prior evidence; long new tasks do not."""
        q = (user_query or '').strip()
        if not q:
            return False
        if len(q) > 800:
            return False
        ql = q.lower()
        phrase_needles = (
            'sorry', 'meant', 'instead', 'rank', 'summarize', 'summarise',
            'expand', 'shorter', 'longer', 'clarify', 'same ', 'previous ',
            'the list', 'that list', 'earlier', 'you mentioned', 'above',
            'more detail', 'more about',
        )
        if any(n in ql for n in phrase_needles):
            return True

        refinement_patterns = (
            r'\b(top\s+\d+|top-\d+|first\s+\d+|next\s+\d+|list\s+\d+|show\s+me\s+\d+)\b',
            r'\b(first|second|third|fourth|fifth|last)\s+(one|two|three|few|result|results|item|items)\b',
            r'\b(those|these|them|that one|this one|those ones|these ones)\b',
            r'^(and|also|what about|how about)\b',
        )
        return any(re.search(pattern, ql) for pattern in refinement_patterns)

    def _find_nearest_prior_effective_evidence(self, conversation_id: str) -> dict | None:
        """Walk back assistant messages before the latest user message; return first v1 bundle."""
        from ..services.conversation_store import get_conversation_store
        store = get_conversation_store()
        conv = store.get_conversation(conversation_id)
        if not conv:
            return None
        msgs = conv.get('messages') or []
        last_user_idx = None
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i].get('role') == 'user':
                last_user_idx = i
                break
        if last_user_idx is None:
            return None
        assistant_hops = 0
        for j in range(last_user_idx - 1, -1, -1):
            if msgs[j].get('role') != 'assistant':
                continue
            assistant_hops += 1
            if assistant_hops > 8:
                break
            mdata = msgs[j].get('data') or {}
            ev = mdata.get('_effective_evidence')
            if isinstance(ev, dict) and ev.get('v') == 1:
                return ev
        return None

    # TODO: Move to serpapi_yelp_search tool to make it more robust and easier to understand.
    @staticmethod
    def _requested_ranked_result_count(user_query: str, default: int = 5, max_count: int = 10) -> int:
        """Infer how many ranked items the user wants for list-style result answers."""
        q = (user_query or "").strip().lower()
        if not q:
            return default

        match = re.search(r'\b(?:top|first|next|list|show me)\s+(\d{1,2})\b', q)
        if match:
            try:
                return max(1, min(int(match.group(1)), max_count))
            except Exception:
                return default

        if any(token in q for token in ("places", "restaurants", "options", "results", "spots", "picks")):
            return default
        return 1

    @staticmethod
    def _infer_yelp_location_label(url: str | None) -> str | None:
        """Best-effort location label from Yelp business URLs like /biz/foo-hillsboro or /biz/bar-beaverton-2."""
        if not url or not isinstance(url, str):
            return None
        try:
            slug = Path(urlparse(url).path).name.lower()
        except Exception:
            return None
        if not slug:
            return None

        parts = [part for part in slug.split('-') if part]
        if parts and parts[-1].isdigit():
            parts = parts[:-1]
        if not parts:
            return None

        if len(parts) >= 2 and parts[-2] == 'new' and parts[-1] == 'york':
            return 'New York'
        return parts[-1].replace('_', ' ').title() if parts else None

    def _build_grounded_yelp_answer(self, user_query: str, source_payload: dict, from_effective_evidence: bool = False) -> str | None:
        """Build a deterministic Yelp ranking answer from actual returned candidates/evidence."""
        if not isinstance(source_payload, dict):
            return None

        if from_effective_evidence:
            payload = ((source_payload.get('supporting_tool_results') or {}).get('serpapi_yelp_search') or {})
            if not isinstance(payload, dict):
                return None
            results = payload.get('candidates') or []
        else:
            payload = source_payload.get('serpapi_yelp_search') or {}
            if not isinstance(payload, dict):
                return None
            results = payload.get('results') or payload.get('top_results') or []

        if not isinstance(results, list) or not results:
            return None

        find_desc = payload.get('find_desc') or 'results'
        find_loc = payload.get('find_loc') or 'the selected area'
        total_results = payload.get('results_count') or len(results)
        desired = self._requested_ranked_result_count(user_query, default=5, max_count=10)
        shown = [item for item in results if isinstance(item, dict)][:desired]
        if not shown:
            return None

        title_desc = str(find_desc).strip().title()
        lines = [
            f"## Top {len(shown)} {title_desc} Places Near {find_loc}",
        ]

        if from_effective_evidence:
            lines.append(
                f"Using the previous Yelp results already in context, here are the top {len(shown)} actual matches I can support."
            )
        else:
            sort_label = payload.get('sort_by') or 'best match'
            lines.append(
                f"I used `serpapi_yelp_search` for \"{find_desc}\" in {find_loc} and found **{total_results} results**"
                + (f", sorted by {sort_label}" if sort_label else "")
                + ". Here are the top supported matches:"
            )

        nearby_labels = set()
        root_city = str(find_loc).split(',')[0].strip().lower()

        for idx, item in enumerate(shown, start=1):
            name = item.get('title') or item.get('name')
            url = item.get('url')
            if not name:
                continue

            label = self._infer_yelp_location_label(url)
            heading = f"{idx}. **{name}**"
            if label:
                heading += f" ({label})"
                if label.lower() != root_city:
                    nearby_labels.add(label)
            lines.append("")
            lines.append(heading)

            detail_bits = []
            if item.get('rating') is not None:
                detail_bits.append(f"**Rating**: {item['rating']}")
            if item.get('reviews'):
                detail_bits.append(f"{item['reviews']} reviews")
            if item.get('price'):
                detail_bits.append(f"**Price**: {item['price']}")
            if detail_bits:
                lines.append(f"   - " + " | ".join(detail_bits))

            snippet = item.get('snippet')
            if snippet and not from_effective_evidence:
                lines.append(f'   - **Snippet**: "{snippet}"')
            if url:
                lines.append(f"   - **Yelp**: [View listing]({url})")

        if nearby_labels:
            labels = ", ".join(sorted(nearby_labels))
            lines.append("")
            lines.append(f"Note: Yelp included nearby results outside {find_loc}, including {labels}.")

        if not from_effective_evidence:
            search_url = ((payload.get('search_metadata') or {}).get('yelp_url'))
            if search_url:
                lines.append("")
                lines.append(f"Original Yelp search: [{search_url}]({search_url})")

        return "\n".join(lines).strip()

    def _maybe_apply_grounded_result_override(self, user_query: str, result: dict, conversation_id: str) -> None:
        """Override freeform LLM synthesis when we can answer directly from grounded Yelp data/evidence."""
        if not isinstance(result, dict) or not result.get('ok', True):
            return

        tools_used = list(result.get('tools_used') or [])
        data = result.get('data') or {}

        # Fresh Yelp tool run: answer directly from the real returned results.
        if 'serpapi_yelp_search' in tools_used and isinstance(data, dict) and data.get('serpapi_yelp_search'):
            grounded = self._build_grounded_yelp_answer(user_query, data, from_effective_evidence=False)
            if grounded:
                result['raw_llm_response'] = grounded
                result['speech'] = grounded
            return

        # No-tool refinement turns: if previous evidence is Yelp-backed, use that deterministically too.
        if tools_used:
            return
        if not self._should_inherit_effective_evidence(user_query):
            return
        prior = self._find_nearest_prior_effective_evidence(conversation_id)
        if not prior or not isinstance(prior, dict):
            return
        if 'serpapi_yelp_search' not in (prior.get('supporting_tool_results') or {}):
            return

        grounded = self._build_grounded_yelp_answer(user_query, prior, from_effective_evidence=True)
        if grounded:
            result['raw_llm_response'] = grounded
            result['speech'] = grounded

    def _compute_effective_evidence(
        self,
        conversation_id: str,
        save_data: dict,
        tools_used: list | None,
        server_side_tools: dict | None,
        web_message_id: str,
        user_query: str,
    ) -> dict | None:
        """
        Structured grounding for Completion Guard: tool turns rebuild; no-tool turns may inherit.
        Stored on assistant message data['_effective_evidence'].
        """
        tools_used = list(tools_used or [])
        native_tools = list(dict.fromkeys(self._normalize_server_side_tool_names(server_side_tools)))
        if tools_used or native_tools:
            clean = self._data_without_effective_evidence(save_data)
            supporting = self._extract_followup_data(
                clean, max_candidates=_FOLLOWUP_EVIDENCE_MAX_CANDIDATES
            ) or {}
            if native_tools:
                supporting['native_tools'] = {
                    'server_side_tools': dict(server_side_tools or {}),
                    'normalized_tools': native_tools,
                }
            if not supporting:
                return None
            return {
                'v': 1,
                'supporting_tools_used': list(dict.fromkeys(tools_used + native_tools)),
                'supporting_tool_results': supporting,
                'source_message_ids': [web_message_id],
                'derived_from_prior': False,
            }
        prior = self._find_nearest_prior_effective_evidence(conversation_id)
        if not prior:
            return None
        if not self._should_inherit_effective_evidence(user_query):
            return None
        inherited = copy.deepcopy(prior)
        inherited['derived_from_prior'] = True
        return inherited
    
    @_scoped_by_mode
    def _process_message(self, session_id: str, message: str, mode: str,
                         message_id: str, conversation_id: str, image_data: dict = None,
                         prompt_meta: dict = None, request_feedback: bool = False,
                         file_context: dict = None):
        """Process a chat message through the orchestrator (with optional vision, text file, prompt metadata, and feedback)"""
        start_time = time.time()
        delivery_room = self._delivery_room(session_id, conversation_id)
        original_user_message = message
        prompt_meta = prompt_meta or {}
        prompt_info = f", prompt={prompt_meta.get('prompt_name')}" if prompt_meta.get('prompt_name') else ""
        hint_info = f", tool_hints={prompt_meta.get('tool_hints')}" if prompt_meta.get('tool_hints') else ""
        feedback_info = f", request_feedback={request_feedback}" if request_feedback else ""
        print(f"[CHAT] Processing message: {message[:50]}... (mode={mode}, session={session_id[:8]}, has_image={image_data is not None}{prompt_info}{hint_info}{feedback_info})")
        
        try:
            completion_guard_config = self._get_completion_guard_config(mode)

            # Debug image data
            if image_data:
                image_list = image_data.get('images', [])
                print(f"[CHAT] Image data keys: {image_data.keys() if isinstance(image_data, dict) else 'not a dict'}")
                print(f"[CHAT] Image count: {len(image_list)}")
                if image_list:
                    print(f"[CHAT] First image base64 length: {len(image_list[0].get('base64', ''))}")
            # Import and create orchestrator
            print("[CHAT] Importing orchestrator...")
            from orchestrator_v2 import (
                Orchestrator,
                WEB_UPLOAD_MULTI_IMAGE_VISION_ANALYSIS_PREFIX,
                WEB_UPLOAD_VISION_ANALYSIS_PREFIX,
            )
            
            # Get LLM overrides from web config (per-mode)
            from ..config import get_web_setting, load_web_config
            from ..services.settings_manager import CLOUD_TTS_PROVIDER_OPTIONS, LOCAL_TTS_PROVIDER_OPTIONS
            web_config = load_web_config()
            mode_overrides = web_config.get(mode, {})
            provider_override = mode_overrides.get('llm_provider')
            model_override = mode_overrides.get('llm_model')
            
            if provider_override:
                print(f"[CHAT] Using {mode} override: provider={provider_override}, model={model_override}")
            
            # These per-mode values are already in the request config scope.
            image_provider_override = mode_overrides.get('image_provider')
            video_provider_override = mode_overrides.get('video_provider')
            tts_provider_override = mode_overrides.get('tts_provider')
            allowed_tts_providers = LOCAL_TTS_PROVIDER_OPTIONS if mode == 'local' else CLOUD_TTS_PROVIDER_OPTIONS
            if tts_provider_override not in (None, *allowed_tts_providers):
                tts_provider_override = None
            response_style_override = mode_overrides.get('response_style')
            qa_word_limit_override = mode_overrides.get('qa_word_limit')
            multi_turn_word_limit_override = mode_overrides.get('multi_turn_word_limit')
            
            print(
                "[CHAT] Provider overrides - "
                f"image: {image_provider_override or '(env default)'}, "
                f"video: {video_provider_override or '(env default)'}, "
                f"tts: {tts_provider_override or '(env default)'}, "
                f"response_style: {response_style_override or '(env default)'}, "
                f"qa_limit: {qa_word_limit_override if qa_word_limit_override is not None else '(env default)'}, "
                f"multi_turn_limit: {multi_turn_word_limit_override if multi_turn_word_limit_override is not None else '(env default)'}"
            )
            
            # Modal overrides were also installed into the request scope by the
            # decorator; retain these messages for operator visibility.
            if image_data and image_data.get('action') == 'video':
                # Image-to-video - use provider from modal settings (xai, openai, or gemini)
                modal_video_provider = image_data.get('settings', {}).get('provider', 'xai')
                print(f"[CHAT] Image modal override - video provider: {modal_video_provider} (image-to-video)")
            elif image_data and image_data.get('action') == 'image':
                modal_provider = image_data.get('settings', {}).get('provider')
                if modal_provider:
                    print(f"[CHAT] Image modal override - image provider: {modal_provider}")
            
            # Handle text file context if provided - prepend to message
            if file_context and file_context.get('content'):
                fname = file_context.get('name', 'file.txt')
                content = file_context['content'][:100000]  # 100KB safety cap
                char_count = len(content)
                message = (
                    f"[Attached file: {fname} ({char_count} chars)]\n\n"
                    f"{content}\n\n"
                    f"[End of attached file]\n\n"
                    f"User's message: {message}"
                )
                print(f"[CHAT] Text file attached: {fname} ({char_count} chars)")
            
            # Handle image if provided - route based on action
            vision_result = None
            stash_info = None
            tool_overrides = {}  # Forced param overrides that bypass LLM decisions
            
            if image_data and image_data.get('images'):
                image_action = image_data.get('action', 'analyze')
                image_settings = image_data.get('settings', {})
                image_items = image_data.get('images', [])
                primary_image = image_items[0]
                primary_payload = {
                    'base64': primary_image.get('base64'),
                    'url': primary_image.get('url'),
                    'filename': primary_image.get('filename'),
                    'action': image_action,
                    'settings': image_settings,
                }
                print(f"[CHAT] Image action: {image_action}, count: {len(image_items)}, settings: {image_settings}")
                
                if image_action == 'video':
                    # IMAGE TO VIDEO: Skip vision, stash image, force params via overrides
                    print(f"[CHAT] Image-to-video mode - skipping vision analysis")
                    self.socketio.emit('chat:status', {
                        'message_id': message_id,
                        'conversation_id': conversation_id,
                        'status': 'Preparing image for video generation...',
                        'timestamp': time.time()
                    }, room=delivery_room)
                    
                    stash_info = self._auto_stash_image(primary_payload, '', mode)
                    stash_ref = stash_info.get('stash_ref', '') if stash_info else ''
                    
                    if stash_ref:
                        print(f"[CHAT] Auto-stashed image for video: {stash_ref}")
                    
                    # @TOOL_CONFIG: web UI forced overrides — params enforced from user's modal selections
                    # The LLM generates the creative prompt, but technical params are overridden.
                    aspect_ratio = image_settings.get('aspect_ratio', '16:9')
                    duration = image_settings.get('duration', 5)
                    resolution = image_settings.get('resolution', '720p')
                    video_provider = image_settings.get('provider', 'xai')
                    
                    tool_overrides['generate_video'] = {
                        'image_url': stash_ref,
                        'aspect_ratio': aspect_ratio,
                        'duration': int(duration),
                        'resolution': resolution,
                        'provider': video_provider,
                    }
                    
                    message = (
                        f"[User uploaded an image for VIDEO generation (image-to-video).\n"
                        f"Image stashed at: {stash_ref}\n"
                        f"Use generate_video tool. IMPORTANT: The user has pre-selected these video "
                        f"settings via the UI and they will be applied automatically as overrides:\n"
                        f"  aspect_ratio={aspect_ratio}, duration={duration}s, resolution={resolution}, provider={video_provider}\n"
                        f"These parameters are USER-CONTROLLED and will override whatever you pass. "
                        f"Do NOT worry if the tool result shows different values than what you sent - "
                        f"that is expected and correct. The user's chosen settings take priority.\n"
                        f"Your job: craft a detailed, creative prompt from the user's instructions below. "
                        f"Do NOT retry if the result looks successful.]\n\n"
                        f"User's video instructions: {message}"
                    )
                    print(f"[CHAT] Image-to-video - forced overrides: {aspect_ratio}, {duration}s, {resolution}, provider={video_provider}")
                    
                elif image_action == 'image':
                    # IMAGE TO IMAGE: Skip vision, stash image, force params via overrides
                    print(f"[CHAT] Image-to-image mode - skipping vision analysis")
                    self.socketio.emit('chat:status', {
                        'message_id': message_id,
                        'conversation_id': conversation_id,
                        'status': 'Preparing image for editing...',
                        'timestamp': time.time()
                    }, room=delivery_room)
                    
                    stash_info = self._auto_stash_image(primary_payload, '', mode)
                    stash_ref = stash_info.get('stash_ref', '') if stash_info else ''
                    
                    if stash_ref:
                        print(f"[CHAT] Auto-stashed image for editing: {stash_ref}")
                    
                    # Build forced overrides for generate_image
                    img_overrides = {}
                    for key, val in image_settings.items():
                        if val is not None and val != '' and val is not False:
                            img_overrides[key] = val
                    
                    # Pass the reference image so the tool actually edits it
                    if stash_ref:
                        img_overrides['reference_image'] = stash_ref
                    
                    tool_overrides['generate_image'] = img_overrides
                    
                    # Build context message for LLM (params are hints, overrides enforce)
                    param_lines = []
                    for key, val in img_overrides.items():
                        if key == 'reference_image':
                            continue  # Don't clutter the LLM message with the stash ref
                        param_lines.append(f"- {key}: \"{val}\"" if isinstance(val, str) else f"- {key}: {val}")
                    params_str = '\n'.join(param_lines) if param_lines else '(use defaults)'
                    
                    message = (
                        f"[User uploaded a reference image for IMAGE EDITING (image-to-image).\n"
                        f"Image stashed at: {stash_ref}\n"
                        f"Use generate_image tool. The reference_image parameter is set automatically "
                        f"via overrides - you do NOT need to pass it. The tool will edit the uploaded "
                        f"image based on your prompt.\n"
                        f"IMPORTANT: The user has pre-selected these image settings via the UI and "
                        f"they will be applied automatically as overrides:\n"
                        f"{params_str}\n"
                        f"These parameters are USER-CONTROLLED and will override whatever you pass. "
                        f"Do NOT worry if the tool result shows different values than what you sent - "
                        f"that is expected and correct. The user's chosen settings take priority.\n"
                        f"Your job: pass the user's edit instructions as the prompt. "
                        f"KEEP THE PROMPT SHORT AND DIRECT - image editing models work best with "
                        f"simple instructions like 'change X to Y' rather than over-detailed prompts. "
                        f"Do NOT add extra details about keeping textures, lighting, colors etc. "
                        f"The model already knows to preserve the rest of the image. "
                        f"Do NOT retry if the result looks successful. Do NOT run vision analysis.]\n\n"
                        f"User's image instructions: {message}"
                    )
                    print(f"[CHAT] Image-to-image editing - forced overrides: {img_overrides}")
                    
                else:
                    # ANALYZE (default): Vision analysis flow (supports multiple images)
                    image_count = len(image_items)
                    status_label = f'Analyzing {image_count} images...' if image_count > 1 else 'Analyzing image...'
                    print(f"[CHAT] Processing {image_count} image(s) with vision model...")
                    self.socketio.emit('chat:status', {
                        'message_id': message_id,
                        'conversation_id': conversation_id,
                        'status': status_label,
                        'timestamp': time.time()
                    }, room=delivery_room)
                    
                    images_base64 = [img['base64'] for img in image_items if img.get('base64')]
                    vision_result = self._process_vision(
                        images_base64,
                        message, 
                        mode
                    )
                    
                    if vision_result:
                        stash_refs = []
                        uploaded_images = []
                        batch_total = len(image_items)
                        batch_id = None
                        if batch_total > 1:
                            batch_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
                        for index, img in enumerate(image_items, start=1):
                            stash_payload = {
                                'base64': img.get('base64'),
                                'url': img.get('url'),
                                'filename': img.get('filename'),
                                'action': image_action,
                                'settings': image_settings,
                            }
                            if batch_id:
                                stash_payload.update({
                                    'batch_id': batch_id,
                                    'batch_index': index,
                                    'batch_total': batch_total,
                                    'vision_analysis_scope': 'batch',
                                })
                            stashed = self._auto_stash_image(
                                stash_payload,
                                vision_result,
                                mode
                            )
                            if stashed and stashed.get('stash_ref'):
                                stashed_image = dict(stashed)
                                stashed_image['ordinal'] = len(uploaded_images) + 1
                                if img.get('filename'):
                                    stashed_image['source_filename'] = img.get('filename')
                                uploaded_images.append(stashed_image)
                                stash_refs.append(stashed_image.get('stash_ref'))
                                print(f"[CHAT] Auto-stashed image: {stashed.get('stash_ref')}")
                        if uploaded_images:
                            stash_info = dict(uploaded_images[0])
                            stash_info['uploaded_images'] = uploaded_images
                            if len(stash_refs) > 1:
                                stash_info['stash_refs'] = stash_refs
                        
                        stash_note = ""
                        if stash_refs:
                            if len(stash_refs) == 1:
                                stash_note = f" Image stashed at: {stash_refs[0]}"
                            else:
                                joined = ', '.join(stash_refs)
                                stash_note = f" Images stashed at: {joined}"
                        
                        vision_prefix = WEB_UPLOAD_VISION_ANALYSIS_PREFIX
                        if image_count > 1:
                            vision_prefix = f"{WEB_UPLOAD_MULTI_IMAGE_VISION_ANALYSIS_PREFIX} ({image_count}). Vision analysis:"
                        message = f"{vision_prefix} {vision_result}]{stash_note}\n\nUser's message: {message}"
                        print(f"[CHAT] Image analyzed - passing to orchestrator with vision context")
            
            # Create orchestrator instance with overrides
            print(f"[CHAT] Creating orchestrator (mode={mode})...")
            orchestrator = Orchestrator(
                mode=mode,
                provider_override=provider_override,
                model_override=model_override
            )
            effective_provider = getattr(orchestrator.router, 'provider_type', provider_override or '')
            effective_model = getattr(orchestrator.router, 'model_name', model_override or '')
            
            # Set up status callback to emit via WebSocket instead of local TTS
            def status_callback(status_message: str):
                """Send status updates to browser via WebSocket"""
                print(f"[CHAT] Status update: {status_message}")
                self.socketio.emit('chat:status', {
                    'message_id': message_id,
                    'conversation_id': conversation_id,
                    'status': status_message,
                    'timestamp': time.time()
                }, room=delivery_room)
            
            orchestrator.set_status_callback(status_callback)
            
            # Set web conversation ID for tracking in conversation metadata
            # This allows searching/filtering conversations by web chat session
            orchestrator.set_web_conversation_id(conversation_id)
            
            # Set up progress callback for real-time tool execution events
            # Check if progress events are enabled (default: True)
            from ..config import get_web_setting
            progress_enabled = get_web_setting('ui.progress_events', True)
            
            if progress_enabled:
                def progress_callback(event_type: str, **kwargs):
                    """Send tool progress events to browser via WebSocket"""
                    if event_type == 'tool_start':
                        tool_name = kwargs.get('tool')
                        call_index = kwargs.get('call_index', 0)
                        print(f"[CHAT] Tool starting: {tool_name}[{call_index}] (turn {kwargs.get('turn')}/{kwargs.get('max_turns')})")
                        self.socketio.emit('tool:start', {
                            'message_id': message_id,
                            'tool': tool_name,
                            'call_index': call_index,  # For unique card IDs when same tool called multiple times
                            'args': kwargs.get('args', {}),
                            'turn': kwargs.get('turn'),
                            'max_turns': kwargs.get('max_turns'),
                            'timestamp': time.time()
                        }, room=delivery_room)
                    
                    elif event_type == 'tool_complete':
                        # Emit tool completion in real-time (success or failure)
                        tool_name = kwargs.get('tool')
                        call_index = kwargs.get('call_index', 0)
                        duration_ms = kwargs.get('duration_ms')
                        success = kwargs.get('success')
                        
                        if success:
                            print(f"[CHAT] Tool completed: {tool_name}[{call_index}] ({duration_ms}ms)")
                            self.socketio.emit('tool:complete', {
                                'message_id': message_id,
                                'tool': tool_name,
                                'call_index': call_index,  # For matching unique card ID
                                'result': {},  # Result will be in final response
                                'duration_ms': duration_ms,
                                'success': True,
                                'timestamp': time.time()
                            }, room=delivery_room)
                        else:
                            print(f"[CHAT] Tool failed: {tool_name}[{call_index}] - {kwargs.get('error', 'unknown')}")
                            self.socketio.emit('tool:error', {
                                'message_id': message_id,
                                'tool': tool_name,
                                'call_index': call_index,
                                'error': kwargs.get('error', 'Unknown error'),
                                'duration_ms': duration_ms,
                                'timestamp': time.time()
                            }, room=delivery_room)
                    
                    elif event_type == 'routing':
                        print(f"[CHAT] Routing: {kwargs.get('message')}")
                        self.socketio.emit('tool:progress', {
                            'message_id': message_id,
                            'status': kwargs.get('message'),
                            'timestamp': time.time()
                        }, room=delivery_room)
                
                orchestrator.set_progress_callback(progress_callback)
                
                # Set cancel check callback
                def cancel_check():
                    return self.pending_cancellations.get(message_id, False)
                
                orchestrator.set_cancel_check(cancel_check)
            
            # Get conversation history for context
            conversation_history = self._get_conversation_context(conversation_id)
            
            # Get blocked tools for web mode
            from ..config import get_web_setting
            blocked_tools = list(get_web_setting('tools.blocked', []))
            
            # Build enhanced message with @prompt instructions and #tool hints if present
            enhanced_message = message
            system_instruction = prompt_meta.get('system_instruction')
            tool_hints = prompt_meta.get('tool_hints') or []
            context_blocks = []
            
            if system_instruction:
                print(f"[CHAT] Prepending prompt instruction ({len(system_instruction)} chars)")
                context_blocks.append(
                    f"[CONTEXT - Use these guidelines for the request below]\n\n"
                    f"{system_instruction}\n\n"
                    f"[END CONTEXT]"
                )
            if tool_hints:
                print(f"[CHAT] Prepending tool hints: {tool_hints}")
                context_blocks.append(
                    self._format_tool_hint_context(
                        tool_hints,
                        request_kind=prompt_meta.get('request_kind', ''),
                    )
                )
            if context_blocks:
                enhanced_message = "\n\n".join(context_blocks) + f"\n\nUser's request: {message}"
            
            # Process the query with conversation context, excluded tools, and forced overrides
            override_info = f", tool_overrides={list(tool_overrides.keys())}" if tool_overrides else ""
            vision_pre_analyzed = bool(vision_result)
            if vision_pre_analyzed:
                print("[CHAT] Web upload vision complete - native server-side tools disabled for this request")
            print(f"[CHAT] Calling orchestrator.process() with {len(conversation_history)} history messages, {len(blocked_tools)} blocked tools{override_info}...")
            from config_loader import config_override_scope
            feedback_overrides = (
                {'FEEDBACK_RANDOM_ENABLED': 'false'}
                if completion_guard_config.get('enabled')
                else {}
            )
            with config_override_scope(feedback_overrides):
                result = orchestrator.process(
                    enhanced_message,
                    conversation_history=conversation_history,
                    excluded_tools=blocked_tools,
                    tool_overrides=tool_overrides if tool_overrides else None,
                    vision_pre_analyzed=vision_pre_analyzed,
                    request_kind=prompt_meta.get('request_kind', ''),
                )
            
            # Clean up cancellation flag
            if message_id in self.pending_cancellations:
                del self.pending_cancellations[message_id]
            
            was_cancelled = result.get('cancelled', False)
            print(f"[CHAT] Got result: ok={result.get('ok')}, tools={result.get('tools_used', [])}, cancelled={was_cancelled}")
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Extract tools used from result
            tools_used = result.get('tools_used', [])
            data = result.get('data', {})
            
            # Check if this is a workflow result (has different structure)
            is_workflow = result.get('workflow_executed') or data.get('workflow_id')
            
            if is_workflow:
                # Workflow results have step-by-step data in data.results
                step_results = data.get('results', [])
                emit_index = 0
                for step_data in step_results:
                    tool = step_data.get('tool', 'unknown')
                    step_ok = step_data.get('ok', True)
                    step_num = step_data.get('step')
                    
                    # Check for for_each outputs (multiple iterations of same tool)
                    outputs = step_data.get('outputs', [])
                    if outputs:
                        # Emit separate event for each for_each iteration
                        for idx, output in enumerate(outputs):
                            output_ok = output.get('ok', True) if isinstance(output, dict) else True
                            output_data = output.get('data', output) if isinstance(output, dict) else output
                            output_duration = output.get('duration_ms') if isinstance(output, dict) else None
                            step_duration = step_data.get('duration_ms')
                            event_duration = output_duration if output_duration is not None else (step_duration or 0)
                            self.socketio.emit('tool:complete', {
                                'tool': tool,
                                'result': output_data,
                                'duration_ms': event_duration,
                                'success': output_ok,
                                'message_id': message_id,
                                'workflow_step': f"{step_num}_{idx}"  # Unique per iteration
                            }, room=delivery_room)
                            emit_index += 1
                    else:
                        # Single execution step
                        step_result_payload = step_data.get('data', {})
                        if (not step_ok) and not step_result_payload:
                            # Preserve failure context for optional workflow steps
                            step_result_payload = {
                                'error': step_data.get('error') or step_data.get('speech') or 'Step failed'
                            }
                        step_duration = step_data.get('duration_ms') or 0
                        self.socketio.emit('tool:complete', {
                            'tool': tool,
                            'result': step_result_payload,
                            'duration_ms': step_duration,
                            'success': step_ok,
                            'message_id': message_id,
                            'workflow_step': step_num
                        }, room=delivery_room)
                        emit_index += 1
            else:
                # Normal orchestrator results - tools_used may have duplicates
                # Skip emitting tool:complete if progress_events is enabled - we handle this in real-time
                # via the progress callback (prevents duplicate tool cards)
                if not progress_enabled:
                    # Track how many times each tool has been seen to create unique IDs
                    tool_counts = {}
                    for idx, tool in enumerate(tools_used):
                        # Get result - accumulated_data may be a list for repeated tools
                        tool_result = data.get(tool, {})
                        
                        # If result is a list, get the specific iteration
                        tool_idx = tool_counts.get(tool, 0)
                        if isinstance(tool_result, list):
                            if tool_idx < len(tool_result):
                                tool_result = tool_result[tool_idx]
                            else:
                                tool_result = tool_result[-1] if tool_result else {}
                        
                        tool_counts[tool] = tool_idx + 1
                        
                        self.socketio.emit('tool:complete', {
                            'tool': tool,
                            'result': tool_result,
                            'duration_ms': duration_ms // max(len(tools_used), 1),
                            'success': True,
                            'message_id': message_id,
                            'workflow_step': idx  # Use overall index for unique ID
                        }, room=delivery_room)
            
            # Save assistant response to conversation
            response_usage = enrich_usage_metadata(
                result.get('usage'),
                effective_provider,
                effective_model,
            )
            try:
                from ..services.conversation_store import get_conversation_store
                store = get_conversation_store()
                response_text, prepared_speech = self._prepare_web_response_text(
                    result,
                    "Done. I shared the details in chat."
                )
                # Include raw_llm_response and vision_analysis in saved data for "expand details"
                save_data = data.copy() if data else {}
                # Workflow results store tool output in data.results (array); client expects
                # tool-name-keyed map when loading from history. Populate flat map for workflows.
                if is_workflow:
                    step_results = save_data.get('results', [])
                    for step_data in step_results:
                        tool = step_data.get('tool', 'unknown')
                        step_ok = step_data.get('ok', True)
                        if 'outputs' in step_data:
                            outputs = step_data.get('outputs', [])
                            step_output = outputs[0].get('data', outputs[0]) if outputs and isinstance(outputs[0], dict) else {}
                        else:
                            step_output = step_data.get('data', {})

                        if (not step_ok) and not step_output:
                            step_output = {
                                'error': step_data.get('error') or step_data.get('speech') or 'Step failed'
                            }
                        save_data[tool] = step_output  # last wins for duplicate tools
                raw_response = result.get('raw_llm_response', '')
                if raw_response:
                    save_data['raw_llm_response'] = raw_response
                if result.get('server_side_tools'):
                    save_data['server_side_tools'] = result['server_side_tools']
                if prepared_speech:
                    save_data['speech'] = prepared_speech
                # Include vision analysis if we processed an image
                if vision_result:
                    save_data['vision_analysis'] = vision_result
                if stash_info:
                    save_data['stash'] = stash_info
                save_data['_web_message_id'] = message_id
                if result.get('experience_id'):
                    save_data['experience_id'] = result['experience_id']
                # Include token usage for tracking
                if response_usage:
                    save_data['usage'] = response_usage
                if result.get('tool_trace'):
                    save_data['_tool_trace'] = result['tool_trace']
                # Include error details for failed tool calls (enables follow-up debugging)
                # Without this, errors only exist in the speech text and can't be analyzed
                if not result.get('ok') and result.get('error'):
                    error_data = {
                        'message': str(result['error'])[:2000],
                        'retries': result.get('retries', 0),
                        'tool_failed': tools_used[-1] if tools_used else result.get('tool_name', 'unknown'),
                    }
                    # Include tool arguments for debugging (truncated to avoid bloat)
                    if result.get('tool_args'):
                        # Keep only non-prompt args to save space (prompts are in the message text)
                        args_copy = {k: v for k, v in result['tool_args'].items() if k != 'prompt'}
                        error_data['tool_args'] = {k: str(v)[:300] for k, v in args_copy.items()}
                    save_data['_error'] = error_data
                ev = self._compute_effective_evidence(
                    conversation_id,
                    save_data,
                    tools_used,
                    result.get('server_side_tools', {}),
                    message_id,
                    original_user_message,
                )
                if ev:
                    save_data['_effective_evidence'] = ev
                    if isinstance(data, dict):
                        data['_effective_evidence'] = ev
                store.add_message(
                    conversation_id, 
                    'assistant', 
                    response_text,
                    data=save_data,
                    tools_used=tools_used
                )
                store.update_llm_metadata(
                    conversation_id,
                    provider=effective_provider,
                    model=effective_model,
                )
            except Exception as save_err:
                print(f"[CHAT] Failed to save response: {save_err}")
            
            # Generate TTS if enabled
            audio_url = None
            try:
                from ..config import get_web_setting
                if get_web_setting('audio.tts_enabled', False):
                    speech_text = prepared_speech
                    if speech_text:
                        audio_url = self._generate_tts(speech_text, mode=mode)
                        if audio_url:
                            try:
                                from ..services.conversation_store import get_conversation_store
                                store = get_conversation_store()
                                store.update_message_data_by_web_message_id(
                                    conversation_id,
                                    message_id,
                                    {'audio_url': audio_url}
                                )
                            except Exception as save_audio_err:
                                print(f"[CHAT] Failed to save TTS audio URL: {save_audio_err}")
            except Exception as tts_err:
                print(f"[CHAT] TTS generation failed: {tts_err}")
            
            # Emit final response
            # Include raw_llm_response and vision_analysis in data for "expand details" feature
            response_data = data.copy() if data else {}
            raw_response = result.get('raw_llm_response', '')
            if raw_response:
                response_data['raw_llm_response'] = raw_response
            if result.get('server_side_tools'):
                response_data['server_side_tools'] = result['server_side_tools']
            # Include vision analysis if we processed an image
            if vision_result:
                response_data['vision_analysis'] = vision_result
            if stash_info:
                response_data['stash'] = stash_info
            if result.get('experience_id'):
                response_data['experience_id'] = result['experience_id']
            if result.get('tool_trace'):
                response_data['_tool_trace'] = result['tool_trace']

            completion_guard_prompt = (not is_workflow) and self._should_prompt_completion_guard(completion_guard_config, tools_used)
            completion_guard_expires_in_ms = (
                int(completion_guard_config.get('manual_prompt_ttl_seconds', 0) * 1000)
                if completion_guard_prompt and completion_guard_config.get('manual_prompt_ttl_seconds', 0) > 0
                else None
            )
            completion_guard_auto_eval = (
                (not is_workflow)
                and result.get('ok', True)
                and self._should_auto_evaluate_completion_guard(completion_guard_config, tools_used)
            )
            defer_feedback_until_completion_guard = (
                request_feedback
                and result.get('ok', True)
                and (completion_guard_prompt or completion_guard_auto_eval)
            )
            self._remember_completion_guard_record(session_id, message_id, {
                'timestamp': time.time(),
                'conversation_id': conversation_id,
                'message_id': message_id,
                'mode': mode,
                'provider': effective_provider,
                'model': effective_model,
                'query': original_user_message,
                'processed_query': message,
                'speech': result.get('speech', ''),
                'raw_llm_response': raw_response,
                'tools_used': tools_used,
                'data': response_data,
                'usage': response_usage or {},
                'server_side_tools': result.get('server_side_tools', {}),
                'completion_guard': completion_guard_config,
                'is_workflow': bool(is_workflow),
                'experience_id': result.get('experience_id'),
                'available_tools': result.get('available_tools', []),
                'intelligence_context': result.get('intelligence_context', ''),
                'feedback_requested': bool(request_feedback and result.get('ok', True)),
                'feedback_state': 'pending' if defer_feedback_until_completion_guard else 'idle',
                'completion_guard_prompt': bool(completion_guard_prompt),
            })
            
            self.socketio.emit('chat:response', {
                'message_id': message_id,
                'conversation_id': conversation_id,
                'text': response_text,
                'speech': prepared_speech,
                'data': response_data,
                'tools_used': tools_used,
                'ok': result.get('ok', True),
                'cancelled': was_cancelled,  # True if user stopped processing
                'duration_ms': duration_ms,
                'usage': response_usage or {},
                'audio_url': audio_url,
                'server_side_tools': result.get('server_side_tools', {}),  # xAI/Anthropic native tools
                'completion_guard': {
                    'enabled': completion_guard_config.get('enabled', False),
                    'mode': completion_guard_config.get('mode', 'off'),
                    'ticket_on_fail': completion_guard_config.get('ticket_on_fail', True),
                    'prompt_user': completion_guard_prompt,
                    'expires_in_ms': completion_guard_expires_in_ms,
                }
            }, room=delivery_room)

            if completion_guard_prompt and completion_guard_config.get('manual_prompt_ttl_seconds', 0) > 0:
                self.socketio.start_background_task(
                    self._expire_completion_guard_prompt_later,
                    session_id,
                    message_id,
                    int(completion_guard_config.get('manual_prompt_ttl_seconds', 0)),
                )

            if completion_guard_auto_eval:
                self._start_blocking_task(
                    self._run_completion_guard_auto_eval,
                    session_id,
                    self.sessions.get(session_id, {}).get('completion_guard_records', {}).get(message_id, {}),
                    name=f"completion-guard-auto-{message_id[:8]}",
                )

            # Collect feedback if requested (runs async after main response)
            # Skip if Completion Guard has to settle first.
            # Also skip if orchestrator already collected feedback (random trigger), though
            # random feedback is disabled above while Completion Guard is enabled.
            already_has_feedback = result.get('feedback') is not None
            print(f"[CHAT] Feedback check: request_feedback={request_feedback}, ok={result.get('ok', True)}, already_has_feedback={already_has_feedback}")

            if defer_feedback_until_completion_guard:
                print(f"[CHAT] Deferring feedback until Completion Guard settles for message {message_id[:8]}...")
            elif request_feedback and result.get('ok', True) and not already_has_feedback:
                print(f"[CHAT] Starting async feedback collection for message {message_id[:8]}...")
                self._start_blocking_task(
                    self._collect_feedback_async,
                    session_id,
                    message_id,
                    message,
                    mode,
                    message_id,
                    conversation_id,
                    result,
                    tools_used,
                    effective_provider,
                    effective_model,
                    None,
                    name=f"feedback-{message_id[:8]}",
                )
            elif already_has_feedback:
                # Orchestrator already collected feedback (for example random trigger), emit that result
                print(f"[CHAT] Using orchestrator's feedback (pre-collected)")
                feedback = result.get('feedback', {})
                self.socketio.emit('feedback:start', {
                    'message_id': message_id,
                    'conversation_id': conversation_id,
                    'status': 'complete'  # Already done
                }, room=delivery_room)
                self.socketio.emit('feedback:complete', {
                    'message_id': message_id,
                    'conversation_id': conversation_id,
                    'rating': feedback.get('rating'),
                    'summary': feedback.get('summary', ''),
                    'positive': feedback.get('positive', ''),
                    'issues': feedback.get('issues', []),
                    'suggestions': feedback.get('suggestions', []),
                    'tool_ratings': feedback.get('tool_ratings', {}),
                    'analysis': feedback.get('analysis', ''),
                    'duration_ms': 0,  # Already collected
                    'success': True
                }, room=delivery_room)
            
        except Exception as e:
            error_msg = str(e)
            print(f"[CHAT] ERROR: {error_msg}")
            traceback.print_exc()
            
            self.socketio.emit('chat:error', {
                'message_id': message_id,
                'conversation_id': conversation_id,
                'error': error_msg,
                'traceback': traceback.format_exc()
            }, room=delivery_room)
    
    @_scoped_by_mode
    def _collect_feedback_async(self, session_id: str, source_message_id: str, query: str, mode: str,
                                 message_id: str, conversation_id: str,
                                 result: dict, tools_used: list,
                                 provider_override: str | None = None,
                                 model_override: str | None = None,
                                 completion_guard_context: dict | None = None):
        """Collect feedback asynchronously after main response is sent"""
        import time as time_module
        start_time = time_module.time()
        delivery_room = self._delivery_room(session_id, conversation_id)
        completion_guard_context = completion_guard_context or {'status': 'none'}
        
        try:
            # Emit feedback:start event so UI can show the card
            self.socketio.emit('feedback:start', {
                'message_id': message_id,
                'conversation_id': conversation_id,
                'status': 'analyzing'
            }, room=delivery_room, namespace='/')
        except Exception as emit_err:
            print(f"[FEEDBACK] ERROR emitting feedback:start: {emit_err}")
        
        try:
            from feedback import FeedbackCollector
            from config_loader import get_config_value, load_config
            from orchestrator_v2 import Orchestrator
            
            # Ensure config is loaded for the right mode
            load_config(mode)
            
            collector = FeedbackCollector(mode)

            orchestrator = Orchestrator(
                mode=mode,
                provider_override=provider_override,
                model_override=model_override
            )
            
            # Get tools used
            if isinstance(tools_used, str):
                tools_used = [tools_used]
            
            num_tools = len(orchestrator.registry.list_tools())
            
            # Get system prompt from router
            system_prompt = orchestrator.router.system_prompt if hasattr(orchestrator.router, 'system_prompt') else None
            
            # @TOOL_CONFIG: feedback relevant tools — keyword-to-tool mapping for web UI feedback
            tool_descriptions = {}
            relevant_tools = set(tools_used)
            query_lower = query.lower()
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
                    tool = orchestrator.registry.get_tool(tool_name)
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
            
            config_context = f"""
Interface: web (Jarvis Web UI with conversation history)
  → Conversation context with follow-up data (stash_refs, IDs, providers) from prior tool results IS available to the LLM
Auto-Context: {'Enabled' if orchestrator.auto_context_enabled else 'Disabled'}
Response Style: {response_style}
  → Style Behavior: {style_explanation}
Tools Available: {num_tools}
Mode: {mode}
"""
            
            # Collect feedback
            feedback = collector.collect(
                query=query,
                result=result,
                tools_used=tools_used,
                num_tools=num_tools,
                system_prompt=system_prompt,
                tool_descriptions=tool_descriptions,
                intelligence_insights=result.get("intelligence_context", ""),
                config_context=config_context,
                session_id=orchestrator.session_id,
                completion_guard_context=completion_guard_context
            )
            
            duration_ms = int((time_module.time() - start_time) * 1000)
            
            # Extract all feedback fields
            rating = feedback.get('rating')
            summary = feedback.get('summary', '')
            positive = feedback.get('positive', '')
            issues = feedback.get('issues', [])
            suggestions = feedback.get('suggestions', issues)  # Fallback to issues
            tool_ratings = feedback.get('tool_ratings', {})
            analysis = feedback.get('analysis', '')

            source_record = self._get_completion_guard_record(session_id, source_message_id or message_id or '')
            experience_id = result.get('experience_id') or (source_record.get('experience_id') if source_record else None)
            if rating is not None and experience_id:
                try:
                    from intelligence_hooks import update_experience_from_feedback
                    update_experience_from_feedback(
                        experience_id=int(experience_id),
                        feedback_rating=rating,
                        feedback_summary=summary,
                        feedback_details={
                            'positive': positive,
                            'issues': issues,
                            'suggestions': suggestions,
                            'tool_ratings': tool_ratings,
                            'analysis': analysis,
                            'completion_guard_status': completion_guard_context.get('status', 'none')
                        }
                    )
                except Exception as bridge_err:
                    print(f"[FEEDBACK] Failed to update intelligence from feedback: {bridge_err}")
            
            print(f"[FEEDBACK] Completed: rating={rating}/5, issues={len(issues)}, duration={duration_ms}ms")

            if source_record is not None:
                source_record['feedback_state'] = 'complete'
                source_record['feedback_result'] = {
                    'rating': rating,
                    'summary': summary,
                    'issues': issues,
                    'tool_ratings': tool_ratings,
                    'completion_guard_status': completion_guard_context.get('status', 'none')
                }
            
            # Emit feedback:complete event with all fields
            try:
                self.socketio.emit('feedback:complete', {
                    'message_id': message_id,
                    'conversation_id': conversation_id,
                    'rating': rating,
                    'summary': summary,
                    'positive': positive,
                    'issues': issues,
                    'suggestions': suggestions,
                    'tool_ratings': tool_ratings,
                    'analysis': analysis,
                    'duration_ms': duration_ms,
                    'success': True
                }, room=delivery_room, namespace='/')
            except Exception as emit_err:
                print(f"[FEEDBACK] ERROR emitting feedback:complete: {emit_err}")
            
        except Exception as e:
            duration_ms = int((time_module.time() - start_time) * 1000)
            print(f"[FEEDBACK] ERROR: {e}")
            source_record = self._get_completion_guard_record(session_id, source_message_id or message_id or '')
            if source_record is not None:
                source_record['feedback_state'] = 'error'
            
            # Emit error state
            try:
                self.socketio.emit('feedback:complete', {
                    'message_id': message_id,
                    'conversation_id': conversation_id,
                    'error': str(e),
                    'duration_ms': duration_ms,
                    'success': False
                }, room=delivery_room, namespace='/')
            except Exception as emit_err:
                print(f"[FEEDBACK] ERROR emitting feedback:complete: {emit_err}")
    
    def _generate_tts(self, text: str, mode: str = None) -> str:
        """Generate TTS audio and return URL - mode-aware"""
        try:
            from datetime import datetime
            from ..config import load_jarvis_config, get_jarvis_setting
            from ..services.settings_manager import get_settings_manager
            
            settings = get_settings_manager()
            current_mode = mode or settings.mode
            
            # Force reload config for correct mode
            load_jarvis_config(current_mode)
            
            # Get provider FIRST - this determines which TTS to use
            provider = get_jarvis_setting('TTS_PROVIDER', 'elevenlabs' if current_mode == 'cloud' else 'qwen3-tts')
            print(f"[CHAT TTS] Mode: {current_mode}, Provider: {provider}")
            
            # Create output directory
            project_root = Path(__file__).parent.parent.parent.parent
            tts_dir = project_root / 'audio' / current_mode / 'tts'
            tts_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Route based on provider (not inferred from URL alone)
            if provider == 'kokoro':
                # Local Kokoro (OpenAI-compatible HTTP)
                tts_url = get_jarvis_setting('KOKORO_TTS_URL', '')
                if not tts_url:
                    print("[CHAT TTS] Kokoro provider but KOKORO_TTS_URL not set!")
                    return None
                audio_path = self._local_tts(text, tts_dir, timestamp, tts_url)
            elif provider == 'qwen3-tts':
                # Qwen3-TTS (OpenAI-compatible API on local network)
                audio_path = self._qwen3_tts(text, tts_dir, timestamp)
            elif provider == 'elevenlabs':
                audio_path = self._elevenlabs_tts(text, tts_dir, timestamp)
            elif provider == 'xai':
                audio_path = self._xai_tts(text, tts_dir, timestamp)
            elif provider == 'openai':
                audio_path = self._openai_tts(text, tts_dir, timestamp)
            else:
                # Unknown provider - try qwen3-tts as fallback for local network
                print(f"[CHAT TTS] Unknown provider '{provider}', trying OpenAI TTS")
                audio_path = self._openai_tts(text, tts_dir, timestamp)
            
            if audio_path and audio_path.exists():
                return f'/api/audio/{audio_path.name}'
            
            return None
        except Exception as e:
            print(f"[CHAT] TTS error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _local_tts(self, text: str, output_dir: Path, timestamp: str, tts_url: str) -> Path:
        """Generate TTS using local/Kokoro API (OpenAI-compatible)"""
        import requests
        from ..config import get_jarvis_setting
        
        voice = get_jarvis_setting('KOKORO_TTS_VOICE', 'af_nicole')
        speed = float(get_jarvis_setting('KOKORO_TTS_SPEED', '1.0'))
        
        payload = {
            "model": "kokoro",
            "input": text,
            "voice": voice,
            "speed": speed,
            "response_format": "mp3"
        }
        
        try:
            response = requests.post(tts_url, json=payload, timeout=30)
            if response.status_code == 200:
                output_path = output_dir / f"tts_{timestamp}.mp3"
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                return output_path
            else:
                print(f"[CHAT] Local TTS error: {response.status_code} - {response.text[:100]}")
                return None
        except Exception as e:
            print(f"[CHAT] Local TTS failed: {e}")
            return None
    
    def _qwen3_tts(self, text: str, output_dir: Path, timestamp: str) -> Path:
        """Generate TTS using Qwen3-TTS API (OpenAI-compatible on local network)"""
        import requests
        from ..config import get_jarvis_setting
        
        tts_url = get_jarvis_setting('QWEN3_TTS_URL', '')
        if not tts_url:
            print("[CHAT TTS] Qwen3-TTS provider but QWEN3_TTS_URL not set!")
            return None
        
        voice = get_jarvis_setting('QWEN3_TTS_VOICE', 'Jarvis')
        speed = float(get_jarvis_setting('QWEN3_TTS_SPEED', '1.0'))
        audio_format = get_jarvis_setting('QWEN3_TTS_FORMAT', 'mp3')
        
        print(f"[CHAT TTS] Qwen3-TTS: url={tts_url}, voice={voice}, format={audio_format}")
        
        payload = {
            "model": "tts-1",
            "input": text,
            "voice": voice,
            "speed": speed,
            "response_format": audio_format
        }
        
        try:
            # Longer timeout for first-time voice builds (Qwen3 caches voices)
            response = requests.post(tts_url, json=payload, timeout=60)
            if response.status_code == 200:
                ext = audio_format if audio_format != 'mp3' else 'mp3'
                output_path = output_dir / f"tts_{timestamp}.{ext}"
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                return output_path
            else:
                print(f"[CHAT] Qwen3-TTS error: {response.status_code} - {response.text[:100]}")
                return None
        except Exception as e:
            print(f"[CHAT] Qwen3-TTS failed: {e}")
            return None
    
    def _elevenlabs_tts(self, text: str, output_dir: Path, timestamp: str) -> Path:
        """Generate TTS using ElevenLabs API"""
        import requests
        from ..config import get_jarvis_setting
        
        api_key = get_jarvis_setting('ELEVENLABS_API_KEY', '')
        voice_id = get_jarvis_setting('ELEVENLABS_TTS_VOICE', 'pgCnBQgKPGkIP8fJuita')
        model_id = get_jarvis_setting('ELEVENLABS_TTS_MODEL', 'eleven_multilingual_v2')
        
        if not api_key:
            print("[CHAT] ELEVENLABS_API_KEY not configured")
            return None
        
        # v3 has 5k char limit, v2 has 10k - truncate if needed
        char_limit = 5000 if model_id == 'eleven_v3' else 10000
        if len(text) > char_limit:
            print(f"[CHAT TTS] Text truncated from {len(text)} to {char_limit} chars for {model_id}")
            text = text[:char_limit]
        
        print(f"[CHAT TTS] ElevenLabs: model={model_id}, voice={voice_id[:8]}..., chars={len(text)}")
        
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json"
        }
        
        # Get voice settings from config (with sensible defaults)
        stability = float(get_jarvis_setting('ELEVENLABS_TTS_STABILITY', '0.5'))
        similarity = float(get_jarvis_setting('ELEVENLABS_TTS_SIMILARITY_BOOST', '0.75'))
        
        # v3 has different voice_settings requirements (stability must be 0.0, 0.5, or 1.0)
        if model_id == 'eleven_v3':
            # Snap stability to valid v3 values
            stability = min([0.0, 0.5, 1.0], key=lambda x: abs(x - stability))
            voice_settings = {
                "stability": stability,
                "similarity_boost": similarity
            }
        else:
            style = float(get_jarvis_setting('ELEVENLABS_TTS_STYLE', '0.5'))
            speaker_boost = get_jarvis_setting('ELEVENLABS_TTS_USE_SPEAKER_BOOST', 'true').lower() == 'true'
            voice_settings = {
                "stability": stability,
                "similarity_boost": similarity,
                "style": style,
                "use_speaker_boost": speaker_boost
            }
        
        payload = {
            "text": text,
            "model_id": model_id,
            "voice_settings": voice_settings
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        
        if response.status_code != 200:
            print(f"[CHAT] ElevenLabs error: {response.status_code} - {response.text}")
            return None
        
        output_path = output_dir / f"tts_{timestamp}.mp3"
        with open(output_path, 'wb') as f:
            f.write(response.content)
        
        return output_path

    def _xai_tts(self, text: str, output_dir: Path, timestamp: str) -> Path:
        """Generate TTS using xAI's native TTS API."""
        import requests
        from ..config import get_jarvis_setting

        api_key = get_jarvis_setting('XAI_API_KEY', '')
        voice_id = get_jarvis_setting('XAI_TTS_VOICE', 'eve')
        language = get_jarvis_setting('XAI_TTS_LANGUAGE', 'en')
        codec = get_jarvis_setting('XAI_TTS_CODEC', 'mp3').lower()
        sample_rate = int(get_jarvis_setting('XAI_TTS_SAMPLE_RATE', '24000'))
        bit_rate = int(get_jarvis_setting('XAI_TTS_BIT_RATE', '128000'))
        max_chars = int(get_jarvis_setting('XAI_TTS_MAX_CHARS', '15000'))
        timeout = int(get_jarvis_setting('XAI_TTS_TIMEOUT', '180'))

        if not api_key:
            print("[CHAT] XAI_API_KEY not configured")
            return None

        if len(text) > max_chars:
            print(f"[CHAT TTS] Text truncated from {len(text)} to {max_chars} chars for xAI TTS")
            text = text[:max_chars]

        print(f"[CHAT TTS] xAI: voice={voice_id}, language={language}, codec={codec}, chars={len(text)}")

        output_format = {
            "codec": codec,
            "sample_rate": sample_rate,
        }
        if codec == 'mp3':
            output_format["bit_rate"] = bit_rate

        payload = {
            "text": text,
            "voice_id": voice_id,
            "language": language,
            "output_format": output_format,
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        response = requests.post("https://api.x.ai/v1/tts", json=payload, headers=headers, timeout=timeout)

        if response.status_code != 200:
            print(f"[CHAT] xAI TTS error: {response.status_code} - {response.text}")
            return None

        ext = 'mp3' if codec == 'mp3' else codec
        output_path = output_dir / f"tts_{timestamp}.{ext}"
        with open(output_path, 'wb') as f:
            f.write(response.content)

        return output_path
    
    def _openai_tts(self, text: str, output_dir: Path, timestamp: str) -> Path:
        """Generate TTS using OpenAI API"""
        import requests
        from ..config import get_jarvis_setting
        
        api_key = get_jarvis_setting('OPENAI_API_KEY', '')
        model = get_jarvis_setting('TTS_MODEL', 'gpt-4o-mini-tts')
        voice = get_jarvis_setting('VOICE', 'onyx')
        
        if not api_key:
            print("[CHAT] OPENAI_API_KEY not configured")
            return None
        
        url = "https://api.openai.com/v1/audio/speech"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "voice": voice,
            "input": text
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        
        if response.status_code != 200:
            print(f"[CHAT] OpenAI TTS error: {response.status_code} - {response.text}")
            return None
        
        output_path = output_dir / f"tts_{timestamp}.mp3"
        with open(output_path, 'wb') as f:
            f.write(response.content)
        
        return output_path

    def _auto_stash_image(self, image_data: dict, vision_analysis: str = '', mode: str = 'cloud') -> dict:
        """
        Auto-stash uploaded image for future tool access.
        Also adds to memory_db as stash_artifact for cross-session recall.
        vision_analysis can be empty for non-vision flows (image-to-video, image-to-image).
        
        Returns stash info dict or None on failure.
        """
        from datetime import datetime, timezone
        from pathlib import Path
        import shutil
        
        try:
            # Get the uploaded image path
            image_filename = self._filename_from_upload_image(image_data)

            if not image_filename:
                print("[STASH] No image filename to stash")
                return None
            
            # Find the uploaded image file
            web_root = Path(__file__).parent.parent.parent
            uploads_path = web_root / 'data' / 'uploads' / image_filename
            
            if not uploads_path.exists():
                print(f"[STASH] Upload file not found: {uploads_path}")
                return None
            
            # Import stash helper
            from stash_helper import open_space
            
            # Create stash space for web uploads
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            has_vision = bool(vision_analysis)
            batch_id = str(image_data.get('batch_id') or '').strip()
            batch_index = image_data.get('batch_index')
            batch_total = image_data.get('batch_total')
            try:
                batch_index = int(batch_index) if batch_index is not None else None
                batch_total = int(batch_total) if batch_total is not None else None
            except (TypeError, ValueError):
                batch_index = None
                batch_total = None
            is_multi_image_batch = bool(batch_id and batch_index and batch_total and batch_total > 1)
            batch_tags = self._stash_image_batch_tags(batch_id, batch_index, batch_total) if is_multi_image_batch else []
            vision_scope = 'batch' if is_multi_image_batch else 'image'
            space_labels = ['web_upload', 'image']
            if has_vision:
                space_labels.append('vision_analyzed')
            space_labels.extend(batch_tags)
            space, is_new = open_space(
                labels=space_labels,
                scope='session',
                ttl_days=7
            )
            
            # Copy image to stash space
            dest_filename = f"upload_{timestamp}.jpg"
            dest_path = space.space_path / dest_filename
            shutil.copy2(uploads_path, dest_path)
            
            # Get file stats
            file_size = dest_path.stat().st_size
            
            # Add file to space metadata
            import hashlib
            with open(dest_path, 'rb') as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
            
            file_id = f"f_{file_hash[:12]}"
            file_tags = ['user_upload']
            if has_vision:
                file_tags.append('vision_analyzed')
            file_tags.extend(batch_tags)
            file_meta = {
                'file_id': file_id,
                'name': dest_filename,
                'stored_name': dest_filename,
                'mime_type': 'image/jpeg',
                'size_bytes': file_size,
                'hash_sha256': file_hash,
                'tags': file_tags,
                'tool_origin': 'web_upload',
                'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + 'Z',
                'vision_analysis': vision_analysis[:500] if has_vision else '',
                'vision_analysis_scope': vision_scope,
            }
            if is_multi_image_batch:
                file_meta.update({
                    'batch_id': batch_id,
                    'batch_index': batch_index,
                    'batch_total': batch_total,
                    'batch_label': f'image_{batch_index}_of_{batch_total}',
                })
            
            # Update space meta
            space.meta.setdefault('files', []).append(file_meta)
            space._save_meta()
            
            stash_ref = f"stash://{space.space_id}/{file_id}"
            
            # Add to memory_db for cross-session recall
            # MemoryDB() uses the already-loaded config (load_jarvis_config was called earlier)
            try:
                from memory_db import MemoryDB
                db = MemoryDB()
                
                memory_key = f"stash_image_{space.space_id}"
                # Build memory value based on whether vision was performed
                if has_vision:
                    short_analysis = vision_analysis[:200] + "..." if len(vision_analysis) > 200 else vision_analysis
                    if is_multi_image_batch:
                        memory_value = (
                            f"Uploaded image {batch_index} of {batch_total} from multi-image batch {batch_id}: "
                            f"{short_analysis}. STASH: {stash_ref}. FILE: {dest_filename}"
                        )
                    else:
                        memory_value = f"Uploaded image: {short_analysis}. STASH: {stash_ref}. FILE: {dest_filename}"
                else:
                    image_action = image_data.get('action', 'upload')
                    memory_value = f"Uploaded image for {image_action}. STASH: {stash_ref}. FILE: {dest_filename}"
                
                memory_tags = ["image", "user_upload"]
                if has_vision:
                    memory_tags.append("vision_analyzed")
                memory_tags.extend(batch_tags)
                memory_metadata = {
                    "stash_ref": stash_ref,
                    "space_id": space.space_id,
                    "file_id": file_id,
                    "filename": dest_filename,
                    "tags": memory_tags,
                    "type": "image",
                    "vision_analysis_scope": vision_scope,
                }
                if is_multi_image_batch:
                    memory_metadata.update({
                        "batch_id": batch_id,
                        "batch_index": batch_index,
                        "batch_total": batch_total,
                        "batch_label": f"image_{batch_index}_of_{batch_total}",
                    })
                
                db.remember(
                    key=memory_key,
                    value=memory_value,
                    category="stash_artifact",
                    importance=6,  # Same as generate_image
                    source="web_upload",
                    metadata=memory_metadata
                )
                print(f"[STASH] Added to memory_db: {memory_key}")
            except Exception as mem_err:
                print(f"[STASH] Memory save failed (non-fatal): {mem_err}")
            
            result = {
                'space_id': space.space_id,
                'file_id': file_id,
                'stash_ref': stash_ref,
                'path': str(dest_path),
                'filename': dest_filename,
                'mime_type': 'image/jpeg',
                'action': image_data.get('action', 'upload'),
                'tool_origin': 'web_upload',
                'has_vision_analysis': has_vision,
                'vision_analysis': vision_analysis[:500] if has_vision else '',
                'vision_analysis_scope': vision_scope,
            }
            if is_multi_image_batch:
                result.update({
                    'batch_id': batch_id,
                    'batch_index': batch_index,
                    'batch_total': batch_total,
                    'batch_label': f'image_{batch_index}_of_{batch_total}',
                })
            return result

        except Exception as e:
            print(f"[STASH] Auto-stash failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    @staticmethod
    def _stash_image_batch_tags(batch_id: str, batch_index: int, batch_total: int) -> list[str]:
        """Return searchable tags/labels for one image in a multi-image upload batch."""
        safe_batch_id = re.sub(r'[^A-Za-z0-9_]+', '_', str(batch_id or '').strip()).strip('_')
        tags = [
            'multi_image_upload',
            'batch_vision_analysis',
            f'image_{batch_index}_of_{batch_total}',
            f'image_index_{batch_index}',
            f'image_total_{batch_total}',
        ]
        if safe_batch_id:
            tags.append(f'upload_batch_{safe_batch_id}')
        ordinal_words = {
            1: 'first',
            2: 'second',
            3: 'third',
            4: 'fourth',
            5: 'fifth',
            6: 'sixth',
        }
        ordinal = ordinal_words.get(batch_index)
        if ordinal:
            tags.append(f'{ordinal}_image')
        return tags

    def _filename_from_upload_image(self, image: dict) -> str | None:
        """Extract a server-generated upload filename from socket image metadata."""
        filename = (image.get('filename') or '').strip()
        if not filename:
            image_url = (image.get('url') or '').strip()
            parsed_path = urlparse(image_url).path
            if parsed_path.startswith('/api/uploads/'):
                filename = parsed_path.rsplit('/', 1)[-1]

        if not filename or filename != Path(filename).name:
            return None
        return filename

    def _hydrate_uploaded_image_payload(self, image_data: dict) -> str | None:
        """Load base64 for uploaded web images from disk before vision analysis."""
        import base64

        uploads_root = (JARVIS_ROOT / 'jarvis-web' / 'data' / 'uploads').resolve()
        hydrated_images = []

        for index, image in enumerate(image_data.get('images', [])):
            hydrated = dict(image)
            if hydrated.get('base64'):
                hydrated_images.append(hydrated)
                continue

            filename = self._filename_from_upload_image(hydrated)
            if not filename:
                return f'Image {index + 1} is missing upload metadata'

            upload_path = (uploads_root / filename).resolve()
            if not upload_path.is_relative_to(uploads_root) or not upload_path.exists():
                return f'Uploaded image not found: {filename}'

            try:
                hydrated['filename'] = filename
                hydrated['url'] = hydrated.get('url') or f'/api/uploads/{filename}'
                hydrated['base64'] = base64.b64encode(upload_path.read_bytes()).decode('utf-8')
            except Exception as exc:
                print(f"[VISION] Failed to load uploaded image {filename}: {exc}")
                return f'Could not load uploaded image: {filename}'

            hydrated_images.append(hydrated)

        image_data['images'] = hydrated_images
        return None

    def _process_vision(self, images_base64: list[str], prompt: str, mode: str) -> str:
        """
        Process one or more images with a vision model.
        Returns the vision model's description/analysis.
        """
        from ..config import load_jarvis_config

        if not images_base64:
            return None
        
        # Load mode-specific config
        load_jarvis_config(mode)
        
        try:
            if mode == 'local':
                return self._vision_ollama(images_base64, prompt)
            else:
                return self._vision_cloud(images_base64, prompt, mode)
        except Exception as e:
            print(f"[VISION] Error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _vision_ollama(self, images_base64: list[str], prompt: str) -> str:
        """Use Ollama vision model (llava, llama3.2-vision, etc.)"""
        from ..config import get_jarvis_setting
        from ollama_utils import get_ollama_base_urls, get_primary_ollama_base_url, request_ollama
        from vision_multimodal import build_ollama_prompt
        
        try:
            base_url = get_primary_ollama_base_url()
            base_urls = get_ollama_base_urls()
            vision_model = get_jarvis_setting('OLLAMA_VISION_MODEL', 'llava:latest')
            
            print(f"[VISION] Using Ollama: {vision_model} at {base_url}")
            print(f"[VISION] Image count: {len(images_base64)}")
            
            payload = {
                "model": vision_model,
                "prompt": build_ollama_prompt(prompt, len(images_base64)),
                "images": images_base64,
                "stream": False
            }
            
            print(f"[VISION] Sending request to Ollama...")
            response, used_base_url = request_ollama(
                "post",
                "/api/generate",
                base_urls=base_urls,
                json=payload,
                timeout=120  # Vision can be slow
            )
            base_url = used_base_url
            print(f"[VISION] Got response: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                resp_text = result.get('response', '')
                print(f"[VISION] Ollama response length: {len(resp_text)}")
                return resp_text
            else:
                print(f"[VISION] Ollama error: {response.status_code} - {response.text[:200]}")
                return None
        except Exception as e:
            print(f"[VISION] Ollama exception: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _vision_cloud(self, images_base64: list[str], prompt: str, mode: str) -> str:
        """Use cloud provider's vision model (Anthropic, xAI, OpenAI)"""
        from ..config import get_jarvis_setting
        
        provider = get_jarvis_setting('LLM_PROVIDER', 'xai')
        vision_model = get_jarvis_setting('VISION_MODEL', '')  # Empty = use main model
        
        print(f"[VISION] Using cloud provider: {provider}, image count: {len(images_base64)}")
        
        if provider == 'anthropic':
            return self._vision_anthropic(images_base64, prompt, vision_model)
        elif provider == 'xai':
            return self._vision_xai(images_base64, prompt, vision_model)
        elif provider == 'openai':
            return self._vision_openai(images_base64, prompt, vision_model)
        else:
            print(f"[VISION] Unknown provider: {provider}, trying xAI format")
            return self._vision_xai(images_base64, prompt, vision_model)
    
    def _vision_anthropic(self, images_base64: list[str], prompt: str, model: str = None) -> str:
        """Use Anthropic Claude for vision. No detail parameter - Claude API does not support high/low."""
        import requests
        from ..config import get_jarvis_setting
        from vision_multimodal import build_anthropic_content
        
        api_key = get_jarvis_setting('ANTHROPIC_API_KEY', '')
        if not api_key:
            print("[VISION] ANTHROPIC_API_KEY not configured")
            return None
        
        # VISION_MODEL may be xAI-specific (grok-*); use only if it looks like Claude
        vision_model = model or get_jarvis_setting('VISION_MODEL', '')
        if vision_model and str(vision_model).lower().startswith('claude-'):
            model = vision_model
        else:
            model = get_jarvis_setting('ANTHROPIC_MODEL', get_provider_fallback_model('anthropic'))
        print(f"[VISION] Anthropic model: {model}")
        
        payload = {
            "model": model,
            "max_tokens": 1024,
            "messages": [{
                "role": "user",
                "content": build_anthropic_content(images_base64, prompt)
            }]
        }
        
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            json=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            },
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result.get('content', [])
            if content and content[0].get('type') == 'text':
                return content[0].get('text', '')
        else:
            print(f"[VISION] Anthropic error: {response.status_code} - {response.text[:200]}")
        return None
    
    def _vision_xai(self, images_base64: list[str], prompt: str, model: str = None) -> str:
        """Use xAI Grok for vision (grok-4.3 or newer)"""
        import requests
        from ..config import get_jarvis_setting
        from vision_multimodal import build_openai_style_content
        
        api_key = get_jarvis_setting('XAI_API_KEY', '')
        if not api_key:
            print("[VISION] XAI_API_KEY not configured")
            return None
        
        # Use VISION_MODEL if set, otherwise fall back to XAI_MODEL or grok-4
        model = model or get_jarvis_setting('VISION_MODEL') or get_jarvis_setting('XAI_MODEL', get_provider_fallback_model('xai'))
        print(f"[VISION] xAI model: {model}")
        
        # xAI uses OpenAI-compatible format with detail parameter (high = better accuracy)
        detail = get_jarvis_setting('VISION_DETAIL', 'high').lower()
        if detail not in ('low', 'high'):
            detail = 'high'
        payload = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": build_openai_style_content(images_base64, prompt, detail)
            }],
            "max_tokens": 2048
        }
        
        response = requests.post(
            "https://api.x.ai/v1/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            timeout=120  # Vision can be slower
        )
        
        if response.status_code == 200:
            result = response.json()
            choices = result.get('choices', [])
            if choices:
                return choices[0].get('message', {}).get('content', '')
        else:
            print(f"[VISION] xAI error: {response.status_code} - {response.text[:500]}")
        return None
    
    def _vision_openai(self, images_base64: list[str], prompt: str, model: str = None) -> str:
        """Use OpenAI multimodal models for vision."""
        import requests
        from ..config import get_jarvis_setting
        from vision_multimodal import build_openai_style_content
        
        api_key = get_jarvis_setting('OPENAI_API_KEY', '')
        if not api_key:
            print("[VISION] OPENAI_API_KEY not configured")
            return None
        
        # VISION_MODEL is global and may be configured for another provider.
        # When it is blank or provider-specific elsewhere, use the active
        # OpenAI chat model so image analysis tracks the selected LLM.
        requested_model = (model or get_jarvis_setting('VISION_MODEL', '') or '').strip()
        if requested_model and self._looks_like_openai_model(requested_model):
            model = requested_model
        else:
            if requested_model:
                print(f"[VISION] Ignoring non-OpenAI VISION_MODEL for OpenAI vision: {requested_model}")
            model = (
                get_jarvis_setting('OPENAI_MODEL', '')
                or get_provider_fallback_model('openai')
                or 'gpt-4o'
            )
        print(f"[VISION] OpenAI model: {model}")

        detail = self._openai_vision_detail(model, get_jarvis_setting('VISION_DETAIL', 'high'))
        
        payload = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": build_openai_style_content(images_base64, prompt, detail)
            }]
        }
        if self._openai_model_uses_max_completion_tokens(model):
            payload["max_completion_tokens"] = 1024
        else:
            payload["max_tokens"] = 1024
        
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            choices = result.get('choices', [])
            if choices:
                return choices[0].get('message', {}).get('content', '')
        else:
            print(f"[VISION] OpenAI error: {response.status_code} - {response.text[:200]}")
        return None

    @staticmethod
    def _looks_like_openai_model(model: str | None) -> bool:
        """Return true for OpenAI text/vision model ids, false for xAI/Claude/Gemini ids."""
        lowered = str(model or '').strip().lower()
        return lowered.startswith(('gpt-', 'o1', 'o3', 'o4'))

    @staticmethod
    def _openai_model_uses_max_completion_tokens(model: str | None) -> bool:
        """Newer OpenAI chat/reasoning models reject legacy max_tokens."""
        lowered = str(model or '').strip().lower()
        return lowered.startswith(('gpt-5', 'o1', 'o3', 'o4'))

    @staticmethod
    def _openai_model_supports_original_detail(model: str | None) -> bool:
        """OpenAI original-detail image inputs are only documented for full GPT-5.4+ models."""
        from vision_multimodal import openai_model_supports_original_detail

        return openai_model_supports_original_detail(model)

    @classmethod
    def _openai_vision_detail(cls, model: str | None, configured_detail: str | None) -> str:
        """Return an OpenAI-supported image detail value for the selected model."""
        from vision_multimodal import openai_vision_detail

        return openai_vision_detail(model, configured_detail, log_fn=lambda msg: print(f"[VISION] {msg}"))
