#!/usr/bin/env python3
"""
Intelligence Integration Hooks

Integrates the intelligence layer with the orchestrator:
1. Record experiences after interactions
2. Get learned insights before routing
3. Process reflections asynchronously

Usage:
    from intelligence_hooks import (
        record_interaction,
        get_routing_insights,
        trigger_reflection
    )
"""

import asyncio
import concurrent.futures
import contextvars
import json
import logging
import os
import re
import sqlite3
import sys
from contextlib import nullcontext
from datetime import datetime
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
from security_utils import redact_sensitive_data, redact_sensitive_text

logger = logging.getLogger(__name__)
_INTELLIGENCE_EXCLUDED_TOOLS = {"tool_search"}


def normalize_server_side_tools_for_reflection(server_side_tools: dict[str, Any] | None) -> list[str]:
    """
    Convert provider-native tool usage into stable metadata labels for reflection.

    These are NOT first-class Jarvis tool choices. They exist only so reflection
    can understand that evidence may have come from provider-native search/code
    paths even when tools_used is empty.
    """
    if not isinstance(server_side_tools, dict):
        return []

    normalized = []
    for name, count in server_side_tools.items():
        if not name:
            continue
        label = str(name).replace('SERVER_SIDE_TOOL_', '').lower()
        try:
            repeat = max(1, int(count))
        except Exception:
            repeat = 1
        normalized.extend([f"native:{label}"] * repeat)
    return normalized


def _run_async(coro):
    """
    Run an async coroutine from sync context.
    
    Handles both standalone execution and when called from within
    an existing event loop (e.g., FastAPI).
    """
    try:
        # Check if there's already a running event loop (e.g., FastAPI)
        asyncio.get_running_loop()
        # Already in async context - run in thread to avoid blocking
        context = contextvars.copy_context()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(context.run, asyncio.run, coro)
            return future.result(timeout=30)
    except RuntimeError:
        # No running loop - safe to use asyncio.run()
        return asyncio.run(coro)

# Backward-compatible injection hook used by isolated tests. Runtime ownership
# lives in intelligence.get_intelligence_layer(), whose cache is keyed and locked
# per data mode; duplicating that cache here reintroduced cross-mode races.
_intelligence_layer = None
_intelligence_checked = False

def _is_intelligence_enabled(mode: str | None = None) -> bool:
    """Check if intelligence is enabled via config.
    
    Set JARVIS_INTELLIGENCE=false in config/cloud.env or config/local.env to disable.
    """
    from config_loader import config_scope, get_active_config_mode, get_config_value
    if mode is not None:
        resolved_mode = get_active_config_mode(mode)
        with config_scope(resolved_mode):
            enabled = get_config_value('JARVIS_INTELLIGENCE', 'true').lower()
    else:
        enabled = get_config_value('JARVIS_INTELLIGENCE', 'true').lower()
    return enabled in ('true', '1', 'yes', 'on')

def _get_intel(mode: str | None = None):
    """Resolve the Intelligence layer for the active request/data mode."""
    from config_loader import get_active_config_mode
    explicit_mode = mode
    mode = get_active_config_mode(explicit_mode)
    
    # Check if disabled
    if not _is_intelligence_enabled(explicit_mode):
        return None
    
    # Preserve the existing test-injection contract without using this mutable
    # module global as a runtime cache.
    if _intelligence_checked:
        return _intelligence_layer if _intelligence_layer else None

    try:
        from intelligence import get_intelligence_layer
        return get_intelligence_layer(mode)
    except Exception as e:
        logger.warning(f"Intelligence layer unavailable for {mode} mode: {e}")
        return None


# ============================================
# EXPERIENCE RECORDING (After interaction)
# ============================================

def record_interaction(
    query: str,
    tools_used: list[str],
    result: dict[str, Any],
    conversation_context: list[dict] | None = None
) -> int:
    """
    Record an interaction as an experience for learning.
    
    Call this after each completed interaction in the orchestrator.
    
    Args:
        query: Original user query
        tools_used: List of tools invoked
        result: The final result dict from orchestrator (contains speech, data, ok, etc.)
        conversation_context: Optional list of conversation turns
    
    Returns:
        Experience ID if recorded successfully, -1 otherwise
    """
    intel = _get_intel()
    if not intel:
        return -1
    
    try:
        tools_used = [tool for tool in (tools_used or []) if tool not in _INTELLIGENCE_EXCLUDED_TOOLS]

        # Extract outcome signals
        outcome = {
            'success': result.get('ok', True),
            'turns': len(tools_used),
            'error': result.get('error'),
            'max_turns_reached': result.get('max_turns_reached', False),
            'duplicate_prevented': result.get('duplicate_prevented', False)
        }
        
        # Infer user signals from context
        user_signals = _infer_user_signals(query, result, conversation_context)
        
        # ============================================
        # CRITICAL: Capture LLM response and tool data
        # This enables reflection to evaluate CONTENT quality
        # ============================================
        
        # Keep both the raw answer and the shorter spoken/display form.
        raw_llm_response = redact_sensitive_text(result.get('raw_llm_response', '') or result.get('speech', ''))
        final_speech = redact_sensitive_text(result.get('speech', ''))

        # Actual tool results (data returned by tools)
        tool_results = redact_sensitive_data(result.get('data', {}))
        server_side_tools = redact_sensitive_data(result.get('server_side_tools') or {})
        native_tool_labels = normalize_server_side_tools_for_reflection(server_side_tools)
        
        # Tools that were AVAILABLE to the LLM (from Tool RAG + ghost tools)
        # This is critical for reflection - shows what LLM COULD have chosen
        available_tools = result.get('available_tools', [])
        routing_provenance = result.get('routing_provenance') or {}
        if not isinstance(routing_provenance, dict):
            routing_provenance = {}
        tool_policy = routing_provenance.get('tool_policy')
        if tool_policy not in {'auto', 'none'}:
            tool_policy = None
        tool_rag_skipped = routing_provenance.get('tool_rag_skipped')
        if not isinstance(tool_rag_skipped, bool):
            tool_rag_skipped = None
        
        # Truncate to prevent DB bloat but keep enough for evaluation
        if len(raw_llm_response) > 2500:
            raw_llm_response = raw_llm_response[:2500] + "... [truncated]"
        if len(final_speech) > 1200:
            final_speech = final_speech[:1200] + "... [truncated]"
        
        # Serialize tool results, truncate if too large
        tool_results_str = json.dumps(tool_results, default=str)
        if len(tool_results_str) > 5000:
            tool_results_str = tool_results_str[:5000] + "... [truncated]"

        tool_trace = redact_sensitive_data(result.get('tool_trace') or [])
        tool_trace_str = json.dumps(tool_trace, default=str)
        if len(tool_trace_str) > 5000:
            tool_trace_str = tool_trace_str[:5000] + "... [truncated]"

        from workflow_learning import extract_workflow_learning_context

        workflow_execution = redact_sensitive_data(
            extract_workflow_learning_context(result, tools_used)
        )
        
        # Context summary with full data
        context = {
            'tools_available': len(tools_used) > 0,
            'multi_turn': len(tools_used) > 1,
            'timestamp': datetime.now().isoformat(),
            'response_style': result.get('response_style'),
            'qa_word_limit': result.get('qa_word_limit'),
            'multi_turn_word_limit': result.get('multi_turn_word_limit'),
            # Include both the raw answer and the final spoken/display form.
            'llm_response': raw_llm_response,  # backward-compatible key used by reflection prompt
            'raw_llm_response': raw_llm_response,
            'final_speech': final_speech,
            'tool_results': tool_results_str,
            'tool_trace': tool_trace_str,
            'workflow_execution': workflow_execution,
            'server_side_tools': server_side_tools,
            'provider_native_tools_used': native_tool_labels,
            # CRITICAL: What tools the LLM could have chosen from
            'available_tools': available_tools,
            # Preserve the request policy so reflection can distinguish an
            # intentional no-tools turn from missing tool telemetry.
            'tool_policy': tool_policy,
            'tool_rag_skipped': tool_rag_skipped,
            'experience_id': result.get('experience_id'),
            'web_conversation_id': result.get('web_conversation_id'),
            'jarvis_session_id': result.get('jarvis_session_id'),
        }
        
        # Run async in sync context (handles FastAPI and standalone)
        exp_id = _run_async(
            intel.record_experience(
                query=query,
                tools_used=tools_used,
                outcome=outcome,
                context=context,
                user_signals=user_signals
            )
        )
        
        logger.debug(f"Recorded experience {exp_id} for query: {query[:50]}...")
        return exp_id  # Return the experience ID for feedback linking
        
    except Exception as e:
        logger.warning(f"Failed to record experience: {e}")
        return -1


def update_experience_from_feedback(
    experience_id: int,
    feedback_rating: int,
    feedback_summary: str = None,
    feedback_details: dict[str, Any] | None = None
) -> bool:
    """
    Update experience outcome based on feedback rating.
    
    This is the FEEDBACK → INTELLIGENCE BRIDGE:
    - Rating 4-5: Mark user satisfaction when no hard guard failure exists
    - Rating 1-2: Mark as failure (retroactive correction)
    - Rating 3: Leave outcome as-is (ambiguous)
    - All ratings: Store compact feedback metadata in raw_data for reflection
    
    Args:
        experience_id: The experience to update
        feedback_rating: Rating from feedback system (1-5)
        feedback_summary: Optional summary from feedback
        feedback_details: Optional structured feedback payload
    
    Returns:
        True if updated, False otherwise
    """
    if experience_id < 0:
        return False
    
    intel = _get_intel()
    if not intel:
        return False

    try:
        rating = int(feedback_rating)
    except Exception:
        logger.debug(f"Experience {experience_id}: invalid feedback rating {feedback_rating!r}")
        return False

    if rating < 1 or rating > 5:
        logger.debug(f"Experience {experience_id}: feedback rating out of range: {rating}")
        return False

    def compact_value(value: Any, text_limit: int = 1200) -> Any:
        """Keep feedback metadata useful for reflection without bloating raw_data."""
        if value is None:
            return None
        if isinstance(value, str):
            return redact_sensitive_text(value)[:text_limit]
        if isinstance(value, dict):
            compacted = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= 20:
                    compacted["..."] = f"truncated {len(value) - index} more key(s)"
                    break
                key_str = str(key)[:80]
                compacted[key_str] = "[redacted]" if key_str and redact_sensitive_data({key_str: item}).get(key_str) == "[redacted]" else compact_value(item, text_limit=500)
            return compacted
        if isinstance(value, list):
            compacted = [compact_value(item, text_limit=500) for item in value[:10]]
            if len(value) > 10:
                compacted.append(f"... truncated {len(value) - 10} more item(s)")
            return compacted
        return value
    
    try:
        cursor = intel.conn.cursor()
        cursor.execute("""
            SELECT outcome_success, user_satisfied, had_to_retry, raw_data
            FROM experiences
            WHERE id = ?
        """, (experience_id,))
        row = cursor.fetchone()
        if not row:
            return False

        raw_data = {}
        if row['raw_data']:
            try:
                raw_data = json.loads(row['raw_data'])
            except Exception:
                raw_data = {}

        feedback_details = redact_sensitive_data(feedback_details or {})
        summary = redact_sensitive_text(feedback_summary or feedback_details.get('summary') or '')
        feedback_record = raw_data.get('feedback', {})
        if not isinstance(feedback_record, dict):
            feedback_record = {}

        previous_latest = feedback_record.get('latest')
        history = feedback_record.get('history', [])
        if not isinstance(history, list):
            history = []
        if isinstance(previous_latest, dict):
            history.append(previous_latest)

        latest_feedback = {
            'rating': rating,
            'summary': compact_value(summary, text_limit=1500) or '',
            'updated_at': datetime.now().isoformat(),
            'source': 'feedback',
        }
        for key in ('positive', 'issues', 'suggestions', 'tool_ratings', 'analysis', 'completion_guard_status'):
            if key in feedback_details and feedback_details.get(key) not in (None, '', [], {}):
                latest_feedback[key] = compact_value(feedback_details.get(key))

        feedback_record['latest'] = latest_feedback
        feedback_record['history'] = history[-4:]
        raw_data['feedback'] = feedback_record
        raw_data = redact_sensitive_data(raw_data)

        outcome_success = int(row['outcome_success']) if row['outcome_success'] is not None else 1
        user_satisfied = int(row['user_satisfied']) if row['user_satisfied'] is not None else 0
        had_to_retry = int(row['had_to_retry']) if row['had_to_retry'] is not None else 0

        guard_status = (
            raw_data.get('completion_guard', {}).get('status', '')
            if isinstance(raw_data.get('completion_guard'), dict)
            else ''
        )
        hard_guard_failure = guard_status in {'unresolved', 'ticket_created', 'error'}

        if rating <= 2:
            outcome_success = 0
            user_satisfied = 0
            had_to_retry = 1
        elif rating >= 4 and not hard_guard_failure:
            user_satisfied = 1

        cursor.execute("""
            UPDATE experiences
            SET outcome_success = ?,
                user_satisfied = ?,
                had_to_retry = ?,
                raw_data = ?
            WHERE id = ?
        """, (
            outcome_success,
            user_satisfied,
            had_to_retry,
            json.dumps(raw_data),
            experience_id
        ))
        intel.conn.commit()
        
        rows_updated = cursor.rowcount
        if rows_updated > 0:
            if rating <= 2:
                logger.info(f"Experience {experience_id}: corrected to FAILURE based on rating {rating}")
            else:
                logger.debug(f"Experience {experience_id}: stored feedback rating {rating}")
            
            # Increase priority in reflection queue (failures are valuable learning)
            if rating <= 2:
                cursor.execute("""
                    UPDATE reflection_queue
                    SET priority = MAX(priority, 0.8)
                    WHERE experience_id = ?
                """, (experience_id,))
                intel.conn.commit()
            
        return rows_updated > 0
        
    except Exception as e:
        logger.warning(f"Failed to update experience {experience_id}: {e}")
        return False


def is_experience_pending_user_reaction(
    experience_id: int,
    *,
    mode: str | None = None,
) -> bool:
    """Return whether a live Web response can still accept one human reaction."""
    if experience_id < 0:
        return False

    intel = _get_intel(mode)
    if not intel:
        return False

    try:
        row = intel.conn.execute("""
            SELECT e.raw_data
            FROM experiences e
            JOIN reflection_queue rq ON rq.experience_id = e.id
            WHERE e.id = ?
              AND COALESCE(rq.processed, 0) = 0
            LIMIT 1
        """, (experience_id,)).fetchone()
        if not row:
            return False

        try:
            raw_data = json.loads(row["raw_data"] or "{}")
        except Exception:
            raw_data = {}
        user_feedback = raw_data.get("user_feedback", {})
        return not (
            isinstance(user_feedback, dict)
            and isinstance(user_feedback.get("latest"), dict)
        )
    except Exception as e:
        logger.debug(
            "Could not determine reaction eligibility for experience %s: %s",
            experience_id,
            e,
        )
        return False


def update_experience_from_user_reaction(
    experience_id: int,
    reaction: str,
    *,
    mode: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Attach one explicit human reaction to a still-pending experience.

    A reaction is satisfaction evidence, not evidence that Jarvis retried,
    clarified, or operationally failed. Both reactions promote the pending
    experience for reflection; a negative reaction receives higher priority.
    """
    result = {
        "updated": False,
        "reason": "unavailable",
        "experience_id": experience_id,
        "reaction": reaction,
    }
    if experience_id < 0:
        result["reason"] = "invalid_experience"
        return result

    reaction = (reaction or "").strip().lower()
    if reaction not in {"up", "down"}:
        result["reason"] = "invalid_reaction"
        return result

    intel = _get_intel(mode)
    if not intel:
        result["reason"] = "intelligence_unavailable"
        return result

    metadata = redact_sensitive_data(metadata or {})
    try:
        cursor = intel.conn.cursor()
        cursor.execute("""
            SELECT e.outcome_success, e.user_satisfied, e.had_to_retry,
                   e.had_to_clarify, e.raw_data
            FROM experiences e
            JOIN reflection_queue rq ON rq.experience_id = e.id
            WHERE e.id = ?
              AND COALESCE(rq.processed, 0) = 0
            LIMIT 1
        """, (experience_id,))
        row = cursor.fetchone()
        if not row:
            result["reason"] = "reflection_not_pending"
            return result

        try:
            raw_data = json.loads(row["raw_data"] or "{}")
        except Exception:
            raw_data = {}

        feedback_record = raw_data.get("user_feedback", {})
        if not isinstance(feedback_record, dict):
            feedback_record = {}
        if isinstance(feedback_record.get("latest"), dict):
            result["reason"] = "already_reacted"
            return result

        latest_feedback = {
            "reaction": reaction,
            "source": "web_message_reaction",
            "updated_at": datetime.now().isoformat(),
            "metadata": metadata,
        }
        feedback_record["latest"] = latest_feedback
        feedback_record.setdefault("history", [])
        raw_data["user_feedback"] = feedback_record

        priority = 0.8 if reaction == "up" else 0.9
        cursor.execute("""
            UPDATE experiences
            SET user_satisfied = ?,
                raw_data = ?
            WHERE id = ?
        """, (
            1 if reaction == "up" else 0,
            json.dumps(redact_sensitive_data(raw_data), default=str),
            experience_id,
        ))
        if cursor.rowcount <= 0:
            intel.conn.rollback()
            result["reason"] = "experience_not_found"
            return result

        cursor.execute("""
            UPDATE reflection_queue
            SET priority = MAX(priority, ?)
            WHERE experience_id = ?
              AND COALESCE(processed, 0) = 0
        """, (priority, experience_id))
        if cursor.rowcount <= 0:
            intel.conn.rollback()
            result["reason"] = "reflection_not_pending"
            return result

        intel.conn.commit()
        result.update({
            "updated": True,
            "reason": "recorded",
            "priority": priority,
            "user_satisfied": reaction == "up",
        })

        try:
            from intelligence import get_intel_logger
            get_intel_logger().log("user_reaction", {
                "experience_id": experience_id,
                "reaction": reaction,
                "mode": mode,
                "priority": priority,
                "metadata": metadata,
            })
        except Exception:
            pass

        logger.info(
            "Experience %s: recorded human reaction=%s with priority %.2f",
            experience_id,
            reaction,
            priority,
        )
        return result
    except Exception as e:
        try:
            intel.conn.rollback()
        except Exception:
            pass
        logger.warning(
            "Failed to update experience %s from human reaction: %s",
            experience_id,
            e,
        )
        result["reason"] = "update_failed"
        return result


def extract_user_correction_signals(query: str) -> dict[str, Any]:
    """
    Detect explicit user correction language in a new turn.

    This is intentionally conservative: it only flags phrases that strongly
    imply the user is correcting the previous assistant response or asking for
    a retry/style adjustment. Broader intent detection should stay in routing.
    """
    text = (query or "").strip().lower()
    signals: dict[str, Any] = {
        "is_correction": False,
        "had_to_clarify": False,
        "had_to_retry": False,
        "style_correction": False,
        "matched_patterns": [],
        "categories": [],
    }
    if not text:
        return signals

    pattern_groups = {
        "clarification": [
            r"\bwhat i meant\b",
            r"\bi meant\b",
            r"\bi said\b",
            r"\bno[, ]+i (mean|meant|want|wanted|asked)\b",
            r"\bnot that\b",
            r"\bthat's not what i (mean|meant|asked|wanted)\b",
            r"\byou misunderstood\b",
            r"\bwrong (one|thing|answer|place|file|person)\b",
        ],
        "retry": [
            r"\btry again\b",
            r"\bretry\b",
            r"\bdo it again\b",
            r"\bone more time\b",
            r"\brerun\b",
            r"\bredo\b",
            r"\bfix that\b",
        ],
        "style": [
            r"\btoo long\b",
            r"\btoo short\b",
            r"\bbe more concise\b",
            r"\bmore detail\b",
            r"\bless detail\b",
            r"\byou forgot\b",
            r"\bdon't (?:do|say|use) that\b",
        ],
    }

    for category, patterns in pattern_groups.items():
        for pattern in patterns:
            if re.search(pattern, text):
                signals["matched_patterns"].append(pattern)
                if category not in signals["categories"]:
                    signals["categories"].append(category)

    topic_pivot = re.search(
        r"\bi (?:meant|wanted) to ask (?:you )?(?:about|something else|another|a different)\b",
        text,
    )
    correction_cue = re.search(
        r"\b(no|not|wrong|instead|rather|misunderstood|forgot|fix|redo|retry)\b",
        text,
    ) or re.search(r"\bwhat i meant\b", text)
    if topic_pivot and not correction_cue:
        signals["matched_patterns"] = []
        signals["categories"] = []

    if signals["matched_patterns"]:
        signals["is_correction"] = True
        signals["had_to_clarify"] = "clarification" in signals["categories"]
        signals["had_to_retry"] = "retry" in signals["categories"]
        signals["style_correction"] = "style" in signals["categories"]

    return signals


def update_experience_from_user_correction(
    previous_experience_id: int,
    correction_query: str,
    signals: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """
    Retroactively update a previous experience when the next user turn clearly
    corrects it.

    This is the USER_CORRECTION -> INTELLIGENCE bridge. It mirrors the
    feedback/completion-guard bridges but is meant for cross-turn signals.
    """
    if previous_experience_id < 0:
        return False

    intel = _get_intel()
    if not intel:
        return False

    signals = signals or extract_user_correction_signals(correction_query)
    if not signals.get("is_correction"):
        return False

    correction_query = redact_sensitive_text(correction_query or "")
    metadata = redact_sensitive_data(metadata or {})
    signals = redact_sensitive_data(signals)

    try:
        cursor = intel.conn.cursor()
        cursor.execute("""
            SELECT outcome_success, user_satisfied, had_to_retry, raw_data
            FROM experiences
            WHERE id = ?
        """, (previous_experience_id,))
        row = cursor.fetchone()
        if not row:
            return False

        raw_data = {}
        if row["raw_data"]:
            try:
                raw_data = json.loads(row["raw_data"])
            except Exception:
                raw_data = {}

        correction_record = raw_data.get("user_correction", {})
        if not isinstance(correction_record, dict):
            correction_record = {}
        previous_latest = correction_record.get("latest")
        history = correction_record.get("history", [])
        if not isinstance(history, list):
            history = []
        if isinstance(previous_latest, dict):
            history.append(previous_latest)

        correction_record["latest"] = {
            "source": "next_turn_user_correction",
            "query": correction_query[:1500],
            "signals": signals,
            "metadata": metadata,
            "updated_at": datetime.now().isoformat(),
        }
        correction_record["history"] = history[-4:]
        raw_data["user_correction"] = correction_record

        raw_signals = raw_data.get("user_signals", {})
        if not isinstance(raw_signals, dict):
            raw_signals = {}
        raw_signals["cross_turn_correction"] = True
        if signals.get("had_to_clarify"):
            raw_signals["clarified"] = True
        if signals.get("had_to_retry"):
            raw_signals["retried"] = True
        if signals.get("style_correction"):
            raw_signals["style_corrected"] = True
        raw_data["user_signals"] = raw_signals

        # Older fake/test schemas may not have had_to_clarify; real intel DBs do.
        columns = {
            column["name"] if isinstance(column, sqlite3.Row) else column[1]
            for column in cursor.execute("PRAGMA table_info(experiences)").fetchall()
        }
        had_to_retry = 1 if signals.get("had_to_retry") or signals.get("is_correction") else int(row["had_to_retry"] or 0)
        raw_payload = json.dumps(redact_sensitive_data(raw_data), default=str)

        if "had_to_clarify" in columns:
            cursor.execute("""
                UPDATE experiences
                SET outcome_success = 0,
                    user_satisfied = 0,
                    had_to_retry = ?,
                    had_to_clarify = MAX(COALESCE(had_to_clarify, 0), ?),
                    raw_data = ?
                WHERE id = ?
            """, (
                had_to_retry,
                1 if signals.get("had_to_clarify") or signals.get("is_correction") else 0,
                raw_payload,
                previous_experience_id,
            ))
        else:
            cursor.execute("""
                UPDATE experiences
                SET outcome_success = 0,
                    user_satisfied = 0,
                    had_to_retry = ?,
                    raw_data = ?
                WHERE id = ?
            """, (
                had_to_retry,
                raw_payload,
                previous_experience_id,
            ))
        rows_updated = cursor.rowcount

        cursor.execute("""
            UPDATE reflection_queue
            SET priority = MAX(priority, 0.9)
            WHERE experience_id = ?
        """, (previous_experience_id,))
        intel.conn.commit()

        logger.info(
            "Experience %s: corrected to FAILURE based on next-turn user correction",
            previous_experience_id,
        )

        try:
            from user_profile import append_correction_to_learned_lessons
            lesson_result = append_correction_to_learned_lessons(
                correction_query,
                signals,
                previous_experience_id,
            )
            if lesson_result.get("appended"):
                correction_record = raw_data.get("user_correction", {})
                if isinstance(correction_record, dict):
                    latest = correction_record.get("latest")
                    if isinstance(latest, dict):
                        latest["learned_lesson"] = {
                            "file": lesson_result.get("file"),
                            "ingested": bool((lesson_result.get("ingest") or {}).get("ingested")),
                        }
                        raw_payload = json.dumps(redact_sensitive_data(raw_data), default=str)
                        cursor.execute(
                            "UPDATE experiences SET raw_data = ? WHERE id = ?",
                            (raw_payload, previous_experience_id),
                        )
                        intel.conn.commit()
        except Exception as lesson_err:
            logger.warning(
                "Failed to append correction lesson for experience %s: %s",
                previous_experience_id,
                lesson_err,
            )

        return rows_updated > 0

    except Exception as e:
        logger.warning(
            f"Failed to update experience {previous_experience_id} from user correction: {e}"
        )
        return False


def record_user_correction_shadow_candidate(
    current_experience_id: int,
    previous_experience_id: int,
    correction_query: str,
    signals: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """
    Persist cross-turn correction evidence on the current experience without
    retroactively downgrading the previous turn.

    Used when USER_CORRECTION_LEARNING_MODE=shadow so candidates can be
    reviewed from the intelligence DB and intel logs before apply mode.
    """
    if current_experience_id < 0 or previous_experience_id < 0:
        return False
    if current_experience_id == previous_experience_id:
        return False

    intel = _get_intel()
    if not intel:
        return False

    signals = signals or extract_user_correction_signals(correction_query)
    if not signals.get("is_correction"):
        return False

    correction_query = redact_sensitive_text(correction_query or "")
    metadata = redact_sensitive_data(metadata or {})
    signals = redact_sensitive_data(signals)

    try:
        cursor = intel.conn.cursor()
        cursor.execute(
            "SELECT raw_data FROM experiences WHERE id = ?",
            (current_experience_id,),
        )
        row = cursor.fetchone()
        if not row:
            return False

        raw_data = {}
        if row["raw_data"]:
            try:
                raw_data = json.loads(row["raw_data"])
            except Exception:
                raw_data = {}

        shadow_record = raw_data.get("user_correction_shadow", {})
        if not isinstance(shadow_record, dict):
            shadow_record = {}
        previous_latest = shadow_record.get("latest")
        history = shadow_record.get("history", [])
        if not isinstance(history, list):
            history = []
        if isinstance(previous_latest, dict):
            history.append(previous_latest)

        shadow_record["latest"] = {
            "source": "next_turn_user_correction_shadow",
            "previous_experience_id": previous_experience_id,
            "query": correction_query[:1500],
            "signals": signals,
            "metadata": metadata,
            "updated_at": datetime.now().isoformat(),
        }
        shadow_record["history"] = history[-4:]
        raw_data["user_correction_shadow"] = shadow_record

        user_signals = raw_data.get("user_signals", {})
        if not isinstance(user_signals, dict):
            user_signals = {}
        user_signals["cross_turn_correction_candidate"] = True
        user_signals["previous_experience_id_candidate"] = previous_experience_id
        if signals.get("categories"):
            user_signals["correction_categories"] = signals.get("categories")
        if signals.get("matched_patterns"):
            user_signals["correction_matched_patterns"] = signals.get("matched_patterns")
        raw_data["user_signals"] = user_signals

        raw_payload = json.dumps(redact_sensitive_data(raw_data), default=str)
        cursor.execute(
            "UPDATE experiences SET raw_data = ? WHERE id = ?",
            (raw_payload, current_experience_id),
        )
        rows_updated = cursor.rowcount
        intel.conn.commit()

        try:
            from intelligence import get_intel_logger
            get_intel_logger().log("user_correction_shadow_candidate", {
                "current_experience_id": current_experience_id,
                "previous_experience_id": previous_experience_id,
                "categories": signals.get("categories", []),
                "matched_patterns": (signals.get("matched_patterns") or [])[:5],
                "query_preview": correction_query[:200],
                "metadata": metadata,
            })
        except Exception:
            pass

        logger.info(
            "Experience %s: recorded shadow user-correction candidate for previous %s",
            current_experience_id,
            previous_experience_id,
        )
        return rows_updated > 0

    except Exception as e:
        logger.warning(
            "Failed to record shadow user correction on experience %s: %s",
            current_experience_id,
            e,
        )
        return False


def update_experience_from_completion_guard(
    experience_id: int,
    status: str,
    note: str = None,
    metadata: dict[str, Any] | None = None
) -> bool:
    """
    Update an experience using Completion Guard outcomes.

    This is the COMPLETION_GUARD → INTELLIGENCE bridge:
    - accepted / auto_accepted confirm the result
    - tighten_only means Completion Guard only found wording cleanup, not a true operational fix
    - repaired marks the experience as eventually successful but suboptimal
    - unresolved / ticket_created mark it as a failure worth reflecting on
    - expired / superseded are neutral manual prompt settlements
    """
    if experience_id < 0:
        return False

    intel = _get_intel()
    if not intel:
        return False

    status = (status or '').strip().lower()
    note = redact_sensitive_text(note or '')
    metadata = redact_sensitive_data(metadata or {})

    try:
        cursor = intel.conn.cursor()
        cursor.execute("""
            SELECT outcome_success, user_satisfied, had_to_retry, raw_data
            FROM experiences
            WHERE id = ?
        """, (experience_id,))
        row = cursor.fetchone()
        if not row:
            return False

        raw_data = {}
        if row['raw_data']:
            try:
                raw_data = json.loads(row['raw_data'])
            except Exception:
                raw_data = {}

        completion_guard = raw_data.get('completion_guard', {})
        completion_guard.update({
            'experience_id': experience_id,
            'status': status,
            'note': note or completion_guard.get('note', ''),
            'metadata': metadata,
            'updated_at': datetime.now().isoformat()
        })
        raw_data['completion_guard'] = completion_guard

        # Fold the corrected solution back into the ORIGINAL experience so
        # reflection can compare "what failed first" vs "what actually fixed it".
        context = raw_data.setdefault('context', {})
        if isinstance(context, dict) and context.get('experience_id') in (None, '', -1):
            context['experience_id'] = experience_id
        repair_result = metadata.get('repair_result') or {}
        repair_data = metadata.get('repair_data') or {}
        operational_correction = bool(metadata.get('operational_correction'))

        if repair_result and operational_correction:
            corrected_response = (
                repair_result.get('raw_llm_response')
                or repair_result.get('speech')
                or ''
            )
            if corrected_response:
                context['corrected_llm_response'] = redact_sensitive_text(corrected_response)[:2500]
            corrected_tools = repair_result.get('tools_used') or []
            if corrected_tools:
                context['corrected_tools_used'] = corrected_tools
            strategy_family = repair_result.get('strategy_family')
            if strategy_family:
                context['repair_strategy_family'] = strategy_family
        if repair_data and operational_correction:
            repair_data_str = json.dumps(redact_sensitive_data(repair_data), default=str)
            if len(repair_data_str) > 5000:
                repair_data_str = repair_data_str[:5000] + "... [truncated]"
            context['corrected_tool_results'] = repair_data_str

        outcome_success = int(row['outcome_success']) if row['outcome_success'] is not None else 1
        user_satisfied = int(row['user_satisfied']) if row['user_satisfied'] is not None else 0
        had_to_retry = int(row['had_to_retry']) if row['had_to_retry'] is not None else 0

        if status in ('accepted', 'auto_accepted', 'tighten_only'):
            user_satisfied = 1
        elif status == 'repaired':
            outcome_success = 1
            user_satisfied = 0
            had_to_retry = 1
        elif status == 'cancelled':
            user_satisfied = 0
            had_to_retry = 1
        elif status in ('repairing', 'unresolved', 'ticket_created', 'error'):
            user_satisfied = 0
            had_to_retry = 1
            if status in ('unresolved', 'ticket_created', 'error'):
                outcome_success = 0

        cursor.execute("""
            UPDATE experiences
            SET outcome_success = ?,
                user_satisfied = ?,
                had_to_retry = ?,
                raw_data = ?
            WHERE id = ?
        """, (
            outcome_success,
            user_satisfied,
            had_to_retry,
            json.dumps(redact_sensitive_data(raw_data)),
            experience_id
        ))

        if status == 'repaired':
            cursor.execute("""
                UPDATE reflection_queue
                SET priority = MAX(priority, 0.85)
                WHERE experience_id = ?
            """, (experience_id,))
        elif status == 'cancelled':
            cursor.execute("""
                UPDATE reflection_queue
                SET priority = MAX(priority, 0.7)
                WHERE experience_id = ?
            """, (experience_id,))
        elif status in ('unresolved', 'ticket_created', 'error'):
            cursor.execute("""
                UPDATE reflection_queue
                SET priority = MAX(priority, 0.95)
                WHERE experience_id = ?
            """, (experience_id,))

        intel.conn.commit()
        logger.info(f"Experience {experience_id}: updated from Completion Guard status={status}")

        try:
            from intelligence import get_intel_logger
            get_intel_logger().log("completion_guard_outcome", {
                "experience_id": experience_id,
                "status": status,
                "note": (note or "")[:300],
                "metadata": redact_sensitive_data(metadata)
            })
        except Exception:
            pass

        return True

    except Exception as e:
        logger.warning(f"Failed to update experience {experience_id} from Completion Guard: {e}")
        return False


def _infer_user_signals(
    query: str,
    result: dict[str, Any],
    conversation_context: list[dict] | None
) -> dict[str, bool]:
    """Infer user satisfaction signals from available data."""
    signals = {
        'thanked': False,
        'clarified': False,
        'retried': False
    }
    
    # Check for failure indicators
    if not result.get('ok', True):
        signals['retried'] = True  # Assume retry if failed
    
    # Check if max turns reached (indicates struggle)
    if result.get('max_turns_reached'):
        signals['clarified'] = True  # Task was complex
    
    # Check current query for correction/retry/style patterns. These are stored
    # on the current experience as shadow evidence even before a previous turn
    # is retroactively updated.
    correction_signals = extract_user_correction_signals(query)
    if correction_signals.get("is_correction"):
        signals["cross_turn_correction_candidate"] = True
        signals["correction_categories"] = correction_signals.get("categories", [])
        signals["correction_matched_patterns"] = correction_signals.get("matched_patterns", [])
    if correction_signals.get("had_to_clarify"):
        signals['clarified'] = True
    if correction_signals.get("had_to_retry"):
        signals['retried'] = True
    if correction_signals.get("style_correction"):
        signals["style_corrected"] = True
    
    return signals


# ============================================
# ROUTING INSIGHTS (Before routing)
# ============================================

def get_routing_insights(query: str) -> dict[str, Any]:
    """
    Get learned insights to inform routing decisions.
    
    Call this before routing to get biases based on past learning.
    
    Args:
        query: The user's query
    
    Returns:
        Dict with:
        - tool_biases: Dict of tool_name -> preference score
        - insights: List of relevant insight descriptions
        - confidence: Overall confidence in these insights
    """
    intel = _get_intel()
    if not intel:
        return {'tool_biases': {}, 'insights': [], 'confidence': 0.0}
    
    try:
        # Get tool biases and insights (handles FastAPI and standalone)
        biases = _run_async(intel.get_tool_biases(query))
        insights = _run_async(intel.get_relevant_insights(query, top_k=3))
        
        # Calculate overall confidence
        if insights:
            avg_confidence = sum(i['confidence'] for i in insights) / len(insights)
        else:
            avg_confidence = 0.0
        
        result = {
            'tool_biases': biases,
            'insights': [
                {
                    'id': i.get('id'),
                    'description': i['insight'],
                    'applies_to': i['applies_to'],
                    'relevance': round(i['relevance'], 3),
                    # PHASE 1: New fields
                    'constraint_type': i.get('constraint_type', 'positive'),
                    'avoided_tools': i.get('avoided_tools', []),
                    'reasoning': i.get('reasoning', ''),
                    'preferred_tools': i.get('preferred_tools') or {},
                    'preferred_workflow_id': i.get('preferred_workflow_id'),
                    'preferred_tool_sequence': i.get('preferred_tool_sequence') or [],
                    'supporting_tools': i.get('supporting_tools') or [],
                    'sequence_required': bool(i.get('sequence_required')),
                    'trigger_signals': i.get('trigger_signals') or [],
                    'matched_trigger_signals': i.get('matched_trigger_signals') or [],
                    'primary_intent': i.get('primary_intent') or '',
                    'source_experience_id': i.get('source_experience_id'),
                    'source_web_conversation_id': i.get('source_web_conversation_id'),
                }
                for i in insights
            ],
            'confidence': round(avg_confidence, 3)
        }
        
        # Log when insights are being applied
        if insights or biases:
            try:
                from intelligence import get_intel_logger
                get_intel_logger().log_insights_applied(query, insights, biases)
            except Exception:
                pass  # Don't let logging break the main flow
        
        return result
            
    except Exception as e:
        logger.warning(f"Failed to get routing insights: {e}")
        return {'tool_biases': {}, 'insights': [], 'confidence': 0.0}


def _tool_names_known_to_db() -> set[str]:
    """Names in tool_definitions (for matching insight text to tools)."""
    try:
        from memory_db import get_memory_db

        db = get_memory_db()
        rows = db.conn.execute("SELECT name FROM tool_definitions").fetchall()
        return {row["name"] for row in rows}
    except Exception:
        return set()


def _insight_ok_for_available_tools(insight: dict[str, Any], available_set: set[str]) -> bool:
    """
    Drop positive insights that recommend tools the user cannot call (blocked UI,
    profile overlay, or not in DB as enabled).

    Negative insights are kept (failure patterns may still be useful).
    """
    if insight.get("constraint_type", "positive") == "negative":
        return True

    pt = insight.get("preferred_tools") or {}
    if isinstance(pt, dict):
        for tool in pt:
            if tool not in available_set:
                return False

    preferred_workflow_id = str(
        insight.get("preferred_workflow_id") or ""
    ).strip()
    if isinstance(pt, dict) and "workflow" in pt and not preferred_workflow_id:
        # Never let a legacy/broad wrapper preference steer every workflow-
        # adjacent query without identifying the recipe that earned it.
        return False
    if preferred_workflow_id:
        if "workflow" not in available_set:
            return False
        try:
            from orchestrator.workflow_availability import workflow_tool_names
            from orchestrator.workflow_loader import WorkflowLoader

            loader = WorkflowLoader(explicit_only=True)
            loader.reload()
            workflow = loader.get_workflow(preferred_workflow_id)
            if not workflow:
                return False
            if any(
                tool_name not in available_set
                for tool_name in workflow_tool_names(workflow)
            ):
                return False
        except Exception:
            # A specific workflow preference is only useful when its current
            # recipe and effective dependencies can be verified.
            return False

    # Text scan: only for tool-like names (underscore or mcp_) so we do not treat the
    # English word "weather" as the weather tool when preferred_tools is empty.
    known = _tool_names_known_to_db()
    unavailable = known - available_set
    if not unavailable:
        return True

    parts = [
        str(insight.get("description") or ""),
        str(insight.get("applies_to") or ""),
        str(insight.get("reasoning") or ""),
    ]
    text = " ".join(parts)
    for name in sorted(unavailable, key=len, reverse=True):
        if "_" not in name and not name.startswith("mcp"):
            continue
        if re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
            return False
    return True


def filter_insights_for_available_tools(
    insight_items: list[dict[str, Any]],
    available_tools: list[str] | None,
) -> list[dict[str, Any]]:
    """Return only insights whose preferred tool/workflow is runnable now."""
    if not available_tools:
        return list(insight_items or [])
    available_set = set(available_tools)
    return [
        insight
        for insight in (insight_items or [])
        if _insight_ok_for_available_tools(insight, available_set)
    ]


def format_insights_for_prompt(insights: dict[str, Any], available_tools: list[str] = None) -> str:
    """
    Format insights as context for the routing prompt.
    
    PHASE 1 UPGRADES:
    - Separates positive constraints (WHAT TO DO) from negative (WHAT NOT TO DO)
    - LLMs respond better to explicitly labeled failures
    
    PHASE 2 UPGRADE:
    - Filters out insights recommending unavailable/blocked tools
    - Safe for cross-mode sync (cloud→local, local→cloud)
    
    Args:
        insights: Dict with insights, tool_biases, confidence
        available_tools: List of tool names currently available (if None, no filtering)
    
    Returns a string that can be injected into the system prompt.
    """
    if not insights.get('insights'):
        return ""
    
    # Filter insights if available_tools provided
    all_insights = insights['insights']
    all_insights = filter_insights_for_available_tools(
        all_insights,
        available_tools,
    )
    
    # Separate positive and negative constraints
    positive_insights = [i for i in all_insights if i.get('constraint_type', 'positive') == 'positive']
    negative_insights = [i for i in all_insights if i.get('constraint_type') == 'negative']
    
    lines = []
    
    # Positive constraints (what TO do)
    if positive_insights:
        lines.append("=== LEARNED STRATEGIES (WHAT TO DO) ===")
        lines.append(f"(Based on {len(positive_insights)} successful patterns)")
        lines.append("")
        for insight in positive_insights:
            lines.append(f"✅ {insight['description']}")
            if insight.get('applies_to'):
                lines.append(f"   → Applies to: {insight['applies_to']}")
            if insight.get('preferred_workflow_id'):
                lines.append(
                    "   → Candidate workflow: "
                    f"{insight['preferred_workflow_id']} "
                    "(confirm it is currently runnable with workflow discovery)"
                )
            sequence = insight.get('preferred_tool_sequence') or []
            if sequence and insight.get('sequence_required'):
                lines.append(f"   → Required sequence: {' → '.join(sequence)}")
        lines.append("")
    
    # Negative constraints (what NOT to do) - LLMs respond strongly to explicit failures
    if negative_insights:
        lines.append("=== KNOWN FAILURES - AVOID THESE ===")
        lines.append("⚠️  These approaches have FAILED in the past:")
        lines.append("")
        for insight in negative_insights:
            lines.append(f"❌ {insight['description']}")
            if insight.get('avoided_tools'):
                tools = ', '.join(insight['avoided_tools'])
                lines.append(f"   → DO NOT use: {tools}")
            if insight.get('reasoning'):
                # Show full reasoning (truncated was causing confusion - e.g., ending mid-word)
                lines.append(f"   → Why: {insight['reasoning']}")
        lines.append("")
    
    # Tool biases summary (filtered to available tools)
    if insights.get('tool_biases'):
        biases = dict(insights['tool_biases'])
        
        # Filter to available tools if list provided
        if available_tools:
            available_set = set(available_tools)
            biases = {k: v for k, v in biases.items() if k in available_set}
            workflow_preference_survived = any(
                "workflow" in (item.get("preferred_tools") or {})
                for item in all_insights
                if item.get("constraint_type", "positive") == "positive"
            )
            if not workflow_preference_survived:
                biases.pop("workflow", None)
        
        prefer_tools = {k: v for k, v in biases.items() if v > 0}
        avoid_tools = {k: v for k, v in biases.items() if v < 0}
        
        if prefer_tools or avoid_tools:
            lines.append("=== TOOL PREFERENCES ===")
            
            if prefer_tools:
                for tool, bias in sorted(prefer_tools.items(), key=lambda x: -x[1]):
                    lines.append(f"  ✅ PREFER: {tool} (+{bias:.2f})")
            
            if avoid_tools:
                for tool, bias in sorted(avoid_tools.items(), key=lambda x: x[1]):
                    lines.append(f"  ❌ AVOID: {tool} ({bias:.2f})")
            
            lines.append("")
    
    # Overall confidence
    if insights.get('confidence', 0) > 0:
        lines.append(f"(Overall confidence in these insights: {insights['confidence']:.0%})")
        lines.append("")
    
    return "\n".join(lines)


# ============================================
# INSIGHT OUTCOME TRACKING
# ============================================

def track_insight_outcomes(
    insights: list[dict[str, Any]],
    tools_used: list[str],
    result: dict[str, Any]
) -> int:
    """
    Track whether applied insights were helpful based on interaction outcome.
    
    This enables:
    - Confidence decay for bad insights
    - Confidence boost for good insights
    - Parameter tuning based on real effectiveness
    
    Args:
        insights: List of insight dicts that were shown to LLM (from get_routing_insights)
        tools_used: List of tools actually used in the interaction
        result: Final result dict with 'ok', 'speech', etc.
    
    Returns:
        Number of insights tracked
    """
    intel = _get_intel()
    if not intel or not insights:
        return 0
    
    tracked = 0
    outcome_success = result.get('ok', True)
    
    try:
        for insight in insights:
            insight_id = insight.get('id')
            if not insight_id:
                continue
            
            # Determine if this insight was helpful
            was_helpful = _evaluate_insight_helpfulness(
                insight=insight,
                tools_used=tools_used,
                outcome_success=outcome_success,
                result=result,
            )
            if was_helpful is None:
                logger.debug(
                    "Skipped neutral insight outcome for %s: no attributable evidence",
                    insight_id,
                )
                continue
            
            # Record the usage (handles FastAPI and standalone)
            _run_async(
                intel.record_insight_usage(
                    insight_id=insight_id,
                    was_helpful=was_helpful,
                    outcome='success' if outcome_success else 'failure'
                )
            )
            tracked += 1
            
            logger.debug(f"Tracked insight {insight_id}: helpful={was_helpful}")
        
        return tracked
            
    except Exception as e:
        logger.warning(f"Failed to track insight outcomes: {e}")
        return tracked


def _evaluate_insight_helpfulness(
    insight: dict[str, Any],
    tools_used: list[str],
    outcome_success: bool,
    result: dict[str, Any] | None = None,
) -> bool | None:
    """
    Evaluate whether an insight was helpful for this interaction.
    
    CORRECTED LOGIC (Nov 2025):
    
    POSITIVE insight ("prefer X"):
    - X was used + success → HELPFUL (advice followed, worked)
    - X was used + failure → NOT helpful (advice followed, didn't work)
    - X not used + success → NOT helpful (advice ignored, still worked = advice wasn't needed)
    - X not used + failure → NOT helpful (advice ignored, failed = should have followed?)
    
    NEGATIVE insight ("avoid Y"):
    - Y not used + replacement used successfully → HELPFUL
    - Y not used + no attributable replacement → NEUTRAL (do not self-reinforce)
    - Y not used + failure → NOT helpful
    - Y was used + success → NOT helpful (advice ignored, still worked = advice was WRONG)
    - Y was used + failure → UNCLEAR, count as helpful (advice was correct, should have avoided)
    
    Key insight: When advice is CONTRADICTED and the outcome is SUCCESS, 
    the advice was WRONG and should be marked NOT helpful.
    """
    constraint_type = insight.get('constraint_type', 'positive')
    avoided_tools = insight.get('avoided_tools', [])
    preferred_tools = insight.get('preferred_tools', {})
    
    # Parse avoided_tools if it's a string
    if isinstance(avoided_tools, str):
        try:
            avoided_tools = json.loads(avoided_tools) if avoided_tools else []
        except (json.JSONDecodeError, TypeError):
            avoided_tools = [avoided_tools] if avoided_tools else []
    
    if constraint_type == 'negative':
        # Negative constraint: "avoid these tools"
        tools_violated = [t for t in avoided_tools if t in tools_used]
        
        if not tools_violated:
            if not outcome_success:
                return False

            # Avoidance alone is not evidence. Otherwise an obsolete negative
            # can exclude the correct tool, receive credit when any fallback
            # eventually succeeds, and become permanently self-reinforcing.
            replacement_tools = _extract_preferred_tool_names(preferred_tools)
            replacement_used = any(
                tool in tools_used
                for tool in replacement_tools
            )
            if not replacement_used:
                return None
            if _preferred_tool_had_trace_failure(replacement_tools, result):
                return False
            return True
        else:
            # VIOLATED the advice (used the tool we were told to avoid)
            if outcome_success:
                # The tool we were told to avoid actually WORKED!
                # This means the "avoid" advice was WRONG → NOT helpful
                logger.debug(f"Negative insight contradicted: avoided_tools={avoided_tools} were used successfully")
                return False
            else:
                # Used the avoided tool and FAILED
                # The advice was correct (should have avoided) → helpful
                return True
    else:
        # Positive constraint: "prefer these tools".
        #
        # Historically this used final outcome only. That over-credited broad
        # insights in multi-tool recoveries: a preferred tool could fail, a later
        # tool could repair the answer, and the original insight still looked
        # perfectly helpful. Use the optional tool_trace when available to catch
        # that "success after detour" case without changing long-horizon decay.
        preferred_tool_names = _extract_preferred_tool_names(preferred_tools)
        if preferred_tool_names:
            if _preferred_tool_had_trace_failure(preferred_tool_names, result):
                return False
            if not any(tool in tools_used for tool in preferred_tool_names):
                return False

        preferred_workflow_id = str(
            insight.get('preferred_workflow_id') or ''
        ).strip()
        if preferred_workflow_id:
            from workflow_learning import completed_workflow_id

            if completed_workflow_id(result, tools_used) != preferred_workflow_id:
                return False
        return outcome_success


def _extract_preferred_tool_names(preferred_tools: Any) -> list[str]:
    """Normalize preferred_tools metadata into a list of tool names."""
    if not preferred_tools:
        return []

    if isinstance(preferred_tools, str):
        try:
            preferred_tools = json.loads(preferred_tools)
        except Exception:
            return [preferred_tools] if preferred_tools.strip() else []

    if isinstance(preferred_tools, dict):
        return [str(name) for name in preferred_tools.keys() if str(name).strip()]

    if isinstance(preferred_tools, list):
        return [str(name) for name in preferred_tools if str(name).strip()]

    return []


def _preferred_tool_had_trace_failure(
    preferred_tool_names: list[str],
    result: dict[str, Any] | None,
) -> bool:
    """Return True when any preferred tool had a failed attempt in tool_trace."""
    if not isinstance(result, dict):
        return False

    preferred = set(preferred_tool_names)
    tool_trace = result.get('tool_trace') or []
    if not isinstance(tool_trace, list):
        return False

    for entry in tool_trace:
        if not isinstance(entry, dict):
            continue
        if entry.get('tool') not in preferred:
            continue
        if entry.get('ok') is False:
            return True

    return False


# ============================================
# REFLECTION PROCESSING (Background)
# ============================================

def trigger_reflection(batch_size: int = 3) -> int:
    """
    Process pending reflections in the queue.
    
    Can be called periodically or after N interactions.
    
    Args:
        batch_size: Number of reflections to process
    
    Returns:
        Number of reflections processed
    """
    intel = _get_intel()
    if not intel:
        return 0
    
    try:
        processed = _run_async(intel.process_reflection_queue(batch_size))
        if processed > 0:
            logger.info(f"Processed {processed} reflections")
        return processed
            
    except Exception as e:
        logger.warning(f"Reflection processing failed: {e}")
        return 0


def get_learning_stats() -> dict[str, Any]:
    """Get current learning statistics."""
    intel = _get_intel()
    if not intel:
        return {'status': 'unavailable'}
    
    return intel.get_stats()


# ============================================
# META-COGNITION (Periodic evaluation)
# ============================================

def evaluate_learning() -> dict[str, Any]:
    """
    Evaluate the quality of the learning process.
    
    Returns analysis of learning quality with potential issues.
    """
    intel = _get_intel()
    if not intel:
        return {'status': 'unavailable'}
    
    try:
        return _run_async(intel.evaluate_learning_quality())
            
    except Exception as e:
        logger.warning(f"Learning evaluation failed: {e}")
        return {'status': 'error', 'error': str(e)}


# ============================================
# MAINTENANCE JOBS
# ============================================

def run_decay_job(
    force: bool = False,
    dry_run: bool = False,
    *,
    mode: str | None = None,
) -> dict[str, Any]:
    """
    Run selective Intelligence decay in an optional explicit data mode.

    Protects proven/recent strategies, applies bounded decay to weak guidance,
    and prunes unsafe legacy negatives after a verified backup.
    
    Args:
        force: If True, bypass minimum interval check (use with caution!)
        dry_run: If True, calculate changes without writing to the database
        mode: Explicit cloud/local data mode for operator and UI calls
    
    Returns:
        Stats about decayed/pruned insights
    """
    from config_loader import config_scope

    scope = config_scope(mode) if mode is not None else nullcontext()
    with scope:
        intel = _get_intel(mode)
        if not intel:
            return {'status': 'unavailable'}

        try:
            return _run_async(intel.run_decay_job(force=force, dry_run=dry_run))
        except Exception as e:
            logger.warning(f"Decay job failed: {e}")
            return {'status': 'error', 'error': str(e)}


def run_anomaly_detection(*, mode: str | None = None) -> dict[str, Any]:
    """
    Run anomaly detection on recent experiences.
    
    Flags experiences that deviate significantly from norms.
    Uses ANOMALY_THRESHOLD from config.
    
    Returns:
        Stats and list of detected anomalies

    Args:
        mode: Explicit cloud/local data mode when supplied
    """
    from config_loader import config_scope

    scope = config_scope(mode) if mode is not None else nullcontext()
    with scope:
        intel = _get_intel(mode)
        if not intel:
            return {'status': 'unavailable'}

        try:
            return _run_async(intel.run_anomaly_detection())
        except Exception as e:
            logger.warning(f"Anomaly detection failed: {e}")
            return {'status': 'error', 'error': str(e)}


def run_meta_cognition(*, mode: str | None = None) -> dict[str, Any]:
    """
    Run meta-cognition analysis.
    
    Higher-level reflection on the learning process:
    - Detects blind spots (repeated failures)
    - Detects over-generalization
    - Assesses learning quality
    
    Returns:
        Findings and actions taken

    Args:
        mode: Explicit cloud/local data mode when supplied
    """
    from config_loader import config_scope

    scope = config_scope(mode) if mode is not None else nullcontext()
    with scope:
        intel = _get_intel(mode)
        if not intel:
            return {'status': 'unavailable'}

        try:
            return _run_async(intel.run_meta_cognition())
        except Exception as e:
            logger.warning(f"Meta-cognition failed: {e}")
            return {'status': 'error', 'error': str(e)}


def run_all_maintenance(
    force: bool = False,
    dry_run: bool = False,
    *,
    mode: str | None = None,
) -> dict[str, Any]:
    """
    Run all maintenance jobs (decay, anomaly, meta-cognition).
    
    Args:
        force: If True, bypass minimum interval check for decay job
        dry_run: If True, calculate decay changes without writing decay updates
        mode: Explicit cloud/local data mode when supplied
    
    Returns:
        Combined results from all jobs
    """
    from config_loader import config_scope

    scope = config_scope(mode) if mode is not None else nullcontext()
    with scope:
        intel = _get_intel(mode)
        if not intel:
            return {'status': 'unavailable'}

        try:
            return _run_async(
                intel.run_all_maintenance(force=force, dry_run=dry_run)
            )
        except Exception as e:
            logger.warning(f"Maintenance failed: {e}")
            return {'status': 'error', 'error': str(e)}


# ============================================
# CLI for testing
# ============================================

if __name__ == "__main__":
    # Test the hooks
    print("Testing Intelligence Hooks\n")
    
    print("1. Recording test interaction...")
    success = record_interaction(
        query="What is the price of bitcoin?",
        tools_used=["crypto_price"],
        result={"ok": True, "speech": "Bitcoin is $90,000"}
    )
    print(f"   Recorded: {success}")
    
    print("\n2. Getting routing insights for similar query...")
    insights = get_routing_insights("What's ethereum worth?")
    print(f"   Insights: {json.dumps(insights, indent=4)}")
    
    print("\n3. Formatted for prompt:")
    formatted = format_insights_for_prompt(insights)
    print(formatted if formatted else "   (No insights yet)")
    
    print("\n4. Learning stats:")
    stats = get_learning_stats()
    print(f"   {json.dumps(stats, indent=4)}")
    
    print("\n5. Triggering reflection...")
    processed = trigger_reflection(batch_size=1)
    print(f"   Processed: {processed} reflections")
    
    print("\n6. Learning evaluation:")
    evaluation = evaluate_learning()
    print(f"   {json.dumps(evaluation, indent=4)}")
