#!/usr/bin/env python3
"""
Context assembly helpers for the main orchestrator.

This module owns the heavy string-building and result-preview logic used to:
- format recent conversation history from the web UI
- auto-inject short-term conversation context from the DB
- build later-turn tool context for the router/LLM
- shape large tool results into bounded previews for later turns
"""

from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


def _json_safe_followup_value(value):
    """Normalize legacy values so router follow-up blocks are always strict JSON."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return (
            f"{value} "
            "[non-finite number normalized for follow-up context]"
        )
    if isinstance(value, dict):
        return {
            str(key): _json_safe_followup_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe_followup_value(item) for item in value]
    return str(value)


def _followup_json(value) -> str:
    return json.dumps(
        _json_safe_followup_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


class ContextAssembler:
    """Build prompt/context strings while keeping the main orchestrator slimmer."""

    _CANVAS_ARTIFACT_QUERY_TERMS = (
        "send to canvas",
        "save to canvas",
        "create a canvas page",
        "create a new canvas page",
        "put it on canvas",
        "from the selected jarvis response",
        "selected jarvis response",
    )

    _PREVIEW_LONG_STRING_KEYS = frozenset(
        {
            "content",
            "markdown",
            "html",
            "raw_html",
            "raw_text",
            "body",
            "transcript",
            "content_preview",
            "summary",
            "snippet",
        }
    )
    _PREVIEW_URLISH_STRING_KEYS = frozenset(
        {
            "url",
            "href",
            "canonical_url",
            "permalink",
            "short_url",
            "image_url",
            "thumbnail_url",
            "video_url",
            "source_url",
            "link_url",
            "audio_url",
            "embed_url",
        }
    )

    def __init__(
        self,
        *,
        timezone_obj,
        auto_context_window: int,
        auto_context_minutes: int,
        safe_iso_to_local_datetime: Callable[[str], Any],
        format_age_seconds: Callable[[float | int | None], str],
        format_gap_for_prompt: Callable[[float | int | None], str],
        conversation_has_text_summary_for_ref: Callable[[list, str], bool],
        stash_ref_from_result: Callable[[dict, dict], str],
        get_memory_db_fn: Callable[[], Any],
        now_utc_fn: Callable[[], datetime],
        parse_utc_timestamp_fn: Callable[[str], datetime],
    ):
        self.timezone = timezone_obj
        self.auto_context_window = auto_context_window
        self.auto_context_minutes = auto_context_minutes
        self._safe_iso_to_local_datetime = safe_iso_to_local_datetime
        self._format_age_seconds = format_age_seconds
        self._format_gap_for_prompt = format_gap_for_prompt
        self._conversation_has_text_summary_for_ref = conversation_has_text_summary_for_ref
        self._stash_ref_from_result = stash_ref_from_result
        self._get_memory_db = get_memory_db_fn
        self._now_utc = now_utc_fn
        self._parse_utc_timestamp = parse_utc_timestamp_fn

    @classmethod
    def _query_wants_canvas_artifact(cls, text: str) -> bool:
        lowered = (text or "").lower()
        return any(term in lowered for term in cls._CANVAS_ARTIFACT_QUERY_TERMS)

    def excerpt_for_synthesis(self, text: str, max_chars: int = 8000) -> str:
        """Keep enough of long text artifacts for fallback synthesis without flooding the prompt."""
        if not isinstance(text, str):
            return ""
        if len(text) <= max_chars:
            return text
        half = max_chars // 2
        return (
            text[:half].rstrip()
            + "\n\n... [middle omitted for fallback synthesis] ...\n\n"
            + text[-half:].lstrip()
        )

    def extract_useful_data(
        self,
        accumulated_data: dict,
        *,
        has_text_summarizer_summary_for_ref: Callable[[dict, str], bool],
    ) -> str:
        """
        Extract the most useful/relevant data from accumulated tool results.
        Handles arrays (repeated tool calls) and extracts titles, descriptions, key info.
        """
        extracted_parts = []

        def _extract_dict_fields(record: dict, depth: int = 0) -> list[str]:
            if not isinstance(record, dict) or depth > 2:
                return []

            info = []
            useful_fields = [
                "title", "description", "url", "name", "price",
                "coin", "price_usd", "speech", "summary", "result", "content",
                "count", "status", "status_filter", "source", "severity",
                "created_at", "id",
            ]
            for field in useful_fields:
                if field in record and record[field] not in (None, "", [], {}):
                    info.append(f"{field}: {str(record[field])[:500]}")

            for list_key in ["alerts", "reminders", "items", "results", "tasks", "events"]:
                nested_list = record.get(list_key)
                if isinstance(nested_list, list) and nested_list:
                    info.append(f"{list_key}_count: {len(nested_list)}")
                    for nested in nested_list[:3]:
                        if isinstance(nested, dict):
                            title = nested.get("title") or nested.get("name") or nested.get("description")
                            if title:
                                info.append(f"{list_key}_item: {str(title)[:200]}")
                            for nested_field in ["status", "severity", "source", "created_at", "id"]:
                                if nested_field in nested and nested[nested_field] not in (None, ""):
                                    info.append(f"{list_key}_{nested_field}: {str(nested[nested_field])[:200]}")
                        else:
                            info.append(f"{list_key}_item: {str(nested)[:200]}")

            for nested_key in ["data", "report", "payload"]:
                nested_dict = record.get(nested_key)
                if isinstance(nested_dict, dict):
                    info.extend(_extract_dict_fields(nested_dict, depth + 1)[:15])

            return info

        for tool_name, data in accumulated_data.items():
            items = data if isinstance(data, list) else [data]

            tool_info = []
            for item in items:
                if isinstance(item, dict):
                    if tool_name == "text_summarizer" and isinstance(item.get("summary"), str):
                        source = item.get("source") if isinstance(item.get("source"), dict) else {}
                        source_label = source.get("stash_ref") or source.get("path") or "provided text"
                        tool_info.append(f"source: {source_label}")
                        tool_info.append(f"summary: {item.get('summary')}")
                        summary_meta = item.get("summary_meta")
                        if isinstance(summary_meta, dict):
                            method = summary_meta.get("summary_method")
                            llm_used = summary_meta.get("llm_used")
                            if method:
                                tool_info.append(f"summary_method: {method}, llm_used: {llm_used}")

                    if tool_name == "stash" and isinstance(item.get("content"), str):
                        name = item.get("name") or item.get("file_id") or "stash artifact"
                        ref = self._stash_ref_from_result(item, {})
                        content = item.get("content") or ""
                        tool_info.append(f"name: {name}")
                        if ref:
                            tool_info.append(f"ref: {ref}")
                        if ref and has_text_summarizer_summary_for_ref(accumulated_data, ref):
                            tool_info.append("content_summary_available: see text_summarizer summary for this stash ref")
                        else:
                            tool_info.append(
                                "content_excerpt: " + self.excerpt_for_synthesis(content, max_chars=8000)
                            )

                    if "raw" in item or "full_text" in item:
                        text = item.get("full_text", "")
                        if text:
                            tool_info.append(text[:2000])

                    tool_info.extend(_extract_dict_fields(item))
                else:
                    tool_info.append(str(item)[:1000])

            if tool_info:
                extracted_parts.append(f"\n=== {tool_name} ===")
                extracted_parts.extend(tool_info[:5])

        result = "\n".join(extracted_parts)
        return result[:10000]

    def format_conversation_context(self, current_query: str, history: list) -> str:
        """Format provided conversation history as context for the LLM."""
        if not history:
            return current_query

        recent = history
        context_lines = ["=== RECENT CONVERSATION CONTEXT ==="]
        context_lines.append(
            "Follow-up grounding rule: when a prior assistant turn includes structured tool_results, "
            "treat those tool_results as the source of truth for follow-up actions, charts, edits, "
            "canvas pages, and comparisons. Use the assistant's markdown/text only as a presentation summary."
        )
        context_lines.append(
            "Do NOT reconstruct detailed artifacts from prior assistant prose when structured tool_results are available."
        )
        last_msg = recent[-1]
        last_role = last_msg.get("role", "user")
        last_msg_dt = None
        if last_role != "user":
            last_msg_dt = self._safe_iso_to_local_datetime(last_msg.get("timestamp"))

        now_local = datetime.now(self.timezone)
        if last_msg_dt:
            gap_seconds = int(max(0, (now_local - last_msg_dt).total_seconds()))
            abs_local = last_msg_dt.strftime("%b %d, %Y %H:%M")
            rel = self._format_gap_for_prompt(gap_seconds)
            context_lines.append(
                f"Context timing: latest prior message in this conversation was {abs_local} (local), about {rel} ago."
            )
            if gap_seconds >= 86400:
                context_lines.append(
                    "Resumed thread: treat earlier messages as historical context. If the new request clearly continues this thread and is not urgent or transactional, a brief welcome-back or picking-this-back-up acknowledgment is OK."
                )
            context_lines.append("")

        default_content_cap = 2000
        latest_assistant_content_cap = 4000
        last_assistant_idx = -1
        for i, message in enumerate(recent):
            if message.get("role") == "assistant":
                last_assistant_idx = i

        for idx, message in enumerate(recent):
            role = message.get("role", "user")
            content = message.get("content", "")
            tools_used = message.get("tools_used", [])
            tool_results = message.get("tool_results", {})

            cap = latest_assistant_content_cap if idx == last_assistant_idx else default_content_cap
            if role == "assistant" and tool_results and not self._query_wants_canvas_artifact(current_query):
                # Keep the display prose as a compact reminder only.
                cap = min(cap, 1200)
            if len(content) > cap:
                suffix = "... [assistant summary truncated for follow-up context]"
                content = content[: max(0, cap - len(suffix))].rstrip() + suffix

            prefix = "User" if role == "user" else "Jarvis"
            if role == "assistant" and tools_used:
                unique_tools = list(dict.fromkeys(tools_used))
                tools_str = ", ".join(unique_tools)
                if tool_results:
                    context_lines.append(f"{prefix} [tools: {tools_str}]")
                    context_lines.append("  Structured follow-up data (source of truth):")

                    for tool_name, result_data in tool_results.items():
                        if isinstance(result_data, dict):
                            fields = {
                                key: value
                                for key, value in result_data.items()
                                if value not in (None, "", [], {})
                            }
                            if fields:
                                context_lines.append(
                                    f"  └─ {tool_name} data: {_followup_json(fields)}"
                                )
                    if content:
                        context_lines.append(f"  Display summary: {content}")
                else:
                    context_lines.append(f"{prefix} [tools: {tools_str}]: {content}")
            else:
                context_lines.append(f"{prefix}: {content}")

        for message in recent:
            tool_results = message.get("tool_results", {}) or {}
            uploaded_images = tool_results.get("uploaded_images", []) if isinstance(tool_results, dict) else []
            if isinstance(uploaded_images, list):
                image_refs = []
                for index, image_info in enumerate(uploaded_images):
                    if not isinstance(image_info, dict):
                        continue
                    stash_ref = image_info.get("stash_ref")
                    if stash_ref and str(stash_ref).startswith("stash://"):
                        ordinal = image_info.get("ordinal") or index + 1
                        batch_label = image_info.get("batch_label")
                        image_refs.append((ordinal, str(stash_ref), str(batch_label or "")))
                if image_refs:
                    context_lines.append("")
                    context_lines.append(
                        "IMAGE RE-ANALYSIS: If the user asks to look again, correct, compare, or re-identify uploaded images: use analyze_image with the exact stash ref for the referenced image."
                    )
                    for ordinal, stash_ref, batch_label in image_refs:
                        label_note = f" ({batch_label})" if batch_label else ""
                        context_lines.append(f"  Uploaded image {ordinal}{label_note}: analyze_image with image=\"{stash_ref}\".")
                    context_lines.append(
                        "  If the user says first/second/third image or photo, map that ordinal to the matching uploaded image stash ref above."
                    )
                    break

            uploaded_image = tool_results.get("uploaded_image", {}) if isinstance(tool_results, dict) else {}
            stash_ref = uploaded_image.get("stash_ref") if isinstance(uploaded_image, dict) else None
            if stash_ref and str(stash_ref).startswith("stash://"):
                context_lines.append("")
                context_lines.append(
                    "IMAGE RE-ANALYSIS: If the user asks to look again, correct, or re-identify the image: use analyze_image with image=\""
                    + str(stash_ref)
                    + "\"."
                )
                break

        context_lines.append("=== END CONTEXT ===")
        context_lines.append("")
        context_lines.append(f"Current request: {current_query}")
        return "\n".join(context_lines)

    def build_conversation_context(self, current_query: str) -> str:
        """Auto-inject recent conversation history for context awareness."""
        try:
            db = self._get_memory_db()
            recent = db.get_recent_conversations(limit=self.auto_context_window)
            if not recent:
                return current_query

            cutoff = self._now_utc() - timedelta(minutes=self.auto_context_minutes)
            relevant = []
            for conv in recent:
                ts_value = conv.get("timestamp", "")
                if isinstance(ts_value, str):
                    try:
                        ts = self._parse_utc_timestamp(ts_value)
                    except Exception:
                        continue
                elif hasattr(ts_value, "timestamp"):
                    ts = ts_value
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    else:
                        ts = ts.astimezone(timezone.utc)
                else:
                    continue

                if ts > cutoff:
                    relevant.append(conv)

            if not relevant:
                return current_query

            context_parts = ["=== RECENT CONVERSATION HISTORY ==="]
            context_parts.append(f"Last {len(relevant)} conversation(s) in past {self.auto_context_minutes} minutes")
            context_parts.append("")

            for i, conv in enumerate(reversed(relevant), 1):
                context_parts.append(f"[Previous Exchange {i}]")
                context_parts.append(f"User: {conv['user_query']}")
                context_parts.append(f"Assistant: {conv['jarvis_response']}")

                tools_json = conv.get("tools_used")
                if tools_json:
                    try:
                        tools_list = json.loads(tools_json) if isinstance(tools_json, str) else tools_json
                        if tools_list:
                            context_parts.append(f"Tools used: {', '.join(tools_list)}")
                    except Exception:
                        pass

                success = conv.get("success", True)
                if not success:
                    context_parts.append("Status: FAILED - Task did not complete successfully")
                    context_parts.append("Consider using check_tool_logs to understand why")
                else:
                    context_parts.append("Status: Success")

                metadata_json = conv.get("metadata")
                if metadata_json:
                    try:
                        metadata = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
                        if metadata:
                            model = metadata.get("model", "unknown")
                            tool_count = metadata.get("tool_count", 0)
                            context_parts.append(f"Model: {model}, Tools called: {tool_count}")
                    except Exception:
                        pass

                context_parts.append("")

            context_parts.append("=== CURRENT USER QUERY ===")
            context_parts.append(current_query)
            context_parts.append("")
            context_parts.append("Instructions:")
            context_parts.append("- Use the conversation history to provide context-aware responses")
            context_parts.append("- Reference previous topics naturally when relevant")
            context_parts.append("- Continue multi-step workflows seamlessly")
            return "\n".join(context_parts)

        except Exception as exc:
            if os.environ.get("JARVIS_DEBUG"):
                print(f"DEBUG: Context loading failed: {exc}", file=sys.stderr)
            return current_query

    def build_turn_context(self, original_query: str, conversation_context: list) -> str:
        """Build context string for subsequent turns in a multi-turn conversation."""
        context_parts = [f"Original user request: {original_query}\n"]
        context_parts.append("Tools executed so far:")
        context_parts.append("Context note: some large tool payloads are intentionally truncated for context efficiency.")
        context_parts.append("Argument truncation is display-only: the complete arguments were sent to the tool. If a mutation result says ok=true, treat that completed mutation as authoritative and do not recreate it because omitted argument content is not visible.")
        context_parts.append("If ok=true, the tool completed successfully even when only a preview is shown.")
        context_parts.append("Do not repeat the same tool just to recover omitted tail content; answer from the available result or choose a different tool if genuinely needed.")
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

            if not result.get("ok", True):
                summary_parts = ["Status: FAILED"]
                if "error" in result:
                    summary_parts.append(f"Error: {result['error']}")
                if "data" in result and isinstance(result["data"], dict):
                    if "error" in result["data"]:
                        summary_parts.append(f"Details: {result['data']['error']}")
                    if "status_code" in result["data"]:
                        summary_parts.append(f"Status Code: {result['data']['status_code']}")
                result_summary = self.truncate_preview_text("\n   ".join(summary_parts), 1200)
                result_chars_total = len(result_summary)
                result_chars_shown = result_chars_total
                result_truncated = False
            else:
                result_summary, result_chars_total, result_chars_shown, result_truncated = (
                    self.build_llm_result_context_preview(tool_name, result)
                )

            context_parts.append(f"\n{i}. Tool result #{i}: {tool_name}")
            arguments = ctx.get("arguments", {}) if isinstance(ctx, dict) else {}
            if arguments:
                args_preview, args_chars_total, args_chars_shown, args_truncated = (
                    self.build_arguments_context_preview(arguments, max_chars=1200)
                )
                context_parts.append(f"   Arguments: {args_preview}")
                context_parts.append(
                    "   Arguments Meta: "
                    f"arguments_truncated={str(args_truncated).lower()}, "
                    f"arguments_chars_shown={args_chars_shown}, "
                    f"arguments_chars_total={args_chars_total}. "
                    "The complete arguments were sent to the tool; this preview does not indicate partial execution."
                )
            provider_ids = []
            if meta.get("xai_response_id"):
                provider_ids.append(f"xai_response_id={meta['xai_response_id']}")
            if meta.get("xai_tool_call_id"):
                provider_ids.append(f"xai_tool_call_id={meta['xai_tool_call_id']}")
            if provider_ids:
                context_parts.append(f"   Provider ids: {', '.join(provider_ids)}")
            context_parts.append(
                "   Freshness: "
                f"executed_at={executed_at_local or executed_at_iso or 'unknown'}, "
                f"age={self._format_age_seconds(age_seconds)}, "
                f"ttl={str(ttl_seconds) + 's' if ttl_seconds is not None else 'none'}, "
                f"expires_in={self._format_age_seconds(expires_in) if expires_in is not None else 'n/a'}, "
                f"source={source}, "
                f"authoritative_live={authoritative}"
            )
            context_parts.append(
                "   Result Meta: "
                f"ok={result.get('ok', True)}, "
                f"result_truncated={result_truncated}, "
                f"result_chars_shown={result_chars_shown}, "
                f"result_chars_total={result_chars_total}"
            )
            result_label = "Result Preview" if result_truncated else "Result"
            context_parts.append(f"   {result_label}: {result_summary}")
            if tool_name == "tool_search":
                discovery_data = result.get("data", {}) if isinstance(result, dict) else {}
                selected_hints = discovery_data.get("selected_tool_hints", [])
                if isinstance(selected_hints, list):
                    exact_names = [str(name).strip() for name in selected_hints if str(name).strip()]
                    if exact_names:
                        context_parts.append(f"   Selected tool hints: {', '.join(exact_names)}.")
                        context_parts.append(
                            "   Discovery Hint: The exact tool names above are now eligible for direct calls on the next turn."
                        )
            if tool_name == "workflow":
                workflow_data = result.get("data", {}) if isinstance(result, dict) else {}
                action = workflow_data.get("action") if isinstance(workflow_data, dict) else None
                selected_hints = (
                    workflow_data.get("selected_workflow_hints", [])
                    if isinstance(workflow_data, dict)
                    else []
                )
                exact_ids = [str(item).strip() for item in selected_hints if str(item).strip()]
                if exact_ids:
                    context_parts.append(f"   Selected workflow hints: {', '.join(exact_ids)}.")
                    context_parts.append(
                        "   Workflow Discovery Hint: Use an exact workflow_id above for workflow describe or run."
                    )
                if action == "run" and result.get("ok") and not result.get("cancelled"):
                    component_tools = workflow_data.get("component_tools_used", [])
                    context_parts.append(
                        "   Workflow Completion Hint: The deterministic recipe already completed. "
                        "Answer from this result; do not rerun the workflow or its component tools "
                        "unless the user explicitly asks to repeat/refresh it or the result says it is incomplete."
                    )
                    if component_tools:
                        context_parts.append(
                            "   Component tools already executed: "
                            + ", ".join(str(name) for name in component_tools)
                            + "."
                        )
            if result_truncated and tool_name == "stash":
                data = result.get("data", {}) if isinstance(result, dict) else {}
                content = data.get("content") if isinstance(data, dict) else None
                args = ctx.get("arguments", {}) if isinstance(ctx, dict) else {}
                stash_ref = ""
                if isinstance(data, dict):
                    stash_ref = data.get("ref") or data.get("stash_ref") or ""
                if not stash_ref and args.get("space_id") and args.get("file_id"):
                    stash_ref = f"stash://{args.get('space_id')}/{args.get('file_id')}"
                has_summary = self._conversation_has_text_summary_for_ref(conversation_context, stash_ref)
                if isinstance(content, str) and len(content) > 2000 and stash_ref and not has_summary:
                    context_parts.append(
                        "   Long Text Hint: This stash.read already succeeded and the full text is stored in tool results. "
                        "Do NOT call stash.read again for this same file. If you need a smaller working copy for analysis, "
                        f"call text_summarizer with operation='summarize', num_sentences=12, stash_ref='{stash_ref}', then answer from that summary."
                    )

        news_requested = False
        for ctx in conversation_context:
            result = ctx.get("result", {})
            data = result.get("data", {})
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

    def build_provider_tool_result_message(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        tool_call_id: str | None = None,
        duration_ms: int | None = None,
        max_chars: int = 6000,
    ) -> tuple[str, dict[str, Any]]:
        """Build a bounded provider-facing tool result without mutating canonical state."""
        max_chars = max(800, int(max_chars or 6000))
        result_summary, result_chars_total, result_chars_shown, result_truncated = (
            self.build_llm_result_context_preview(tool_name, result)
        )
        args_preview, args_chars_total, args_chars_shown, args_truncated = (
            self.build_arguments_context_preview(
                arguments or {},
                max_chars=max(120, min(1200, max_chars // 4)),
            )
        )
        metadata = {
            "ok": bool(result.get("ok", True)) if isinstance(result, dict) else False,
            "arguments_truncated": args_truncated,
            "arguments_chars_shown": args_chars_shown,
            "arguments_chars_total": args_chars_total,
            "result_truncated": result_truncated,
            "result_chars_shown": result_chars_shown,
            "result_chars_total": result_chars_total,
        }
        if duration_ms is not None:
            metadata["duration_ms"] = duration_ms

        header = [
            "Jarvis tool result",
            f"Tool: {tool_name}" + (f" (call_id: {tool_call_id})" if tool_call_id else ""),
            f"Arguments: {args_preview}",
            (
                "Arguments Meta: "
                f"arguments_truncated={str(metadata['arguments_truncated']).lower()}, "
                f"arguments_chars_shown={metadata['arguments_chars_shown']}, "
                f"arguments_chars_total={metadata['arguments_chars_total']}. "
                "The complete arguments were sent to the tool; this preview does not indicate partial execution."
            ),
            f"Status: {'ok' if metadata['ok'] else 'error'}",
        ]
        if duration_ms is not None:
            header.append(f"Duration: {duration_ms} ms")
        header.append(
            "Result Meta: "
            f"result_truncated={metadata['result_truncated']}, "
            f"result_chars_shown={metadata['result_chars_shown']}, "
            f"result_chars_total={metadata['result_chars_total']}"
        )
        header.append("Result:")
        prefix = "\n".join(header) + "\n"
        available = max_chars - len(prefix)
        if available <= 160:
            payload = {
                "preview_notice": "Result omitted because metadata consumed the provider result budget.",
                "result_truncated": True,
            }
            rendered = json.dumps(payload, default=str, separators=(",", ":"))
            metadata["result_truncated"] = True
            metadata["result_chars_shown"] = len(rendered)
            return prefix + rendered, metadata

        try:
            parsed_summary = json.loads(result_summary)
            rendered = json.dumps(
                {
                    "result": parsed_summary,
                    "result_truncated": metadata["result_truncated"],
                },
                indent=2,
                default=str,
            )
            if len(rendered) <= available:
                metadata["result_chars_shown"] = len(rendered)
                return prefix + rendered, metadata
        except Exception:
            pass

        # Keep the Result block valid JSON even when the preview has to shrink.
        # The previous text context can still carry richer previews; this string
        # is only for provider-native tool_result(...) continuation.
        preview_budget = max(80, available - 180)
        while preview_budget >= 40:
            payload = {
                "result_preview_text": self.truncate_preview_text(result_summary, preview_budget),
                "result_truncated": True,
                "preview_notice": (
                    "Provider-facing result preview shortened to fit budget; "
                    "Jarvis retains the full canonical tool result locally."
                ),
            }
            rendered = json.dumps(payload, default=str, separators=(",", ":"))
            if len(rendered) <= available:
                metadata["result_truncated"] = True
                metadata["result_chars_shown"] = len(rendered)
                return prefix + rendered, metadata
            preview_budget = preview_budget // 2

        rendered = json.dumps(
            {
                "result_preview_text": "",
                "result_truncated": True,
                "preview_notice": "Provider-facing result preview omitted to fit budget.",
            },
            default=str,
            separators=(",", ":"),
        )
        metadata["result_truncated"] = True
        metadata["result_chars_shown"] = len(rendered)
        return prefix + rendered, metadata

    def build_arguments_context_preview(
        self,
        arguments: dict[str, Any],
        *,
        max_chars: int,
    ) -> tuple[str, int, int, bool]:
        """Build an argument preview with explicit, machine-readable truncation state."""
        full_value = json.loads(json.dumps(arguments or {}, default=str))
        preview_value = self.build_preview_value(full_value, parent_key="arguments")
        full_text = json.dumps(full_value, default=str, separators=(",", ":"))
        preview_text = json.dumps(preview_value, default=str, separators=(",", ":"))
        bounded_preview = self.truncate_preview_text(preview_text, max_chars)
        truncated = preview_value != full_value or bounded_preview != preview_text
        return bounded_preview, len(full_text), len(bounded_preview), truncated

    def tool_context_max_chars(self, tool_name: str) -> int:
        lowered = (tool_name or "").lower()
        if lowered == "workflow":
            # Workflow runs return several component results at once. Give the
            # compact workflow projection enough room to retain every current
            # recipe step without exposing the much larger variables payload.
            return 8000
        if "bookmark" in lowered:
            return 5000
        if "search" in lowered or "fetch" in lowered:
            return 6000
        if lowered.startswith("serpapi_"):
            return 6000
        if tool_name == "semantic_recall" or tool_name == "crawl_url":
            return 4000
        if tool_name == "status_recap":
            return 4000
        if tool_name == "supa_crawl_knowledge" or "supa_crawl" in lowered:
            return 6500
        if tool_name == "brave_llm_context":
            return 4000
        return 2500

    def truncate_preview_text(self, value: Any, max_chars: int) -> str:
        text = str(value)
        if len(text) <= max_chars:
            return text
        suffix = "... [truncated]"
        if max_chars <= len(suffix):
            return suffix[:max_chars]
        return text[: max_chars - len(suffix)] + suffix

    def preview_key_rank(self, key: str, value: Any) -> tuple[int, int, str]:
        critical_exact = {
            "space_id", "file_id", "ref", "stash_ref", "md_stash_ref", "srt_stash_ref",
            "memory_id", "conversation_id", "page_id", "video_id", "image_id", "asin",
            "url", "top_url", "video_title", "title", "name", "engine", "query",
            "query_effective", "results_count", "count", "status", "id",
        }
        bulky_keys = {
            "content", "markdown", "html", "raw_html", "raw_text", "body",
            "transcript", "results", "top_results", "items", "matches", "documents",
            "pages", "outputs",
        }
        is_handle = key in critical_exact or key.endswith(("_id", "_ref", "_url"))
        is_scalar = value is None or isinstance(value, (str, int, float, bool))
        is_bulky = key in bulky_keys

        if is_handle:
            rank = 0
        elif is_scalar and not is_bulky:
            rank = 1
        elif not is_bulky:
            rank = 2
        else:
            rank = 3
        return (rank, len(key), key)

    def preview_string_limit(self, parent_key: str) -> int:
        pk = parent_key or ""
        if pk in self._PREVIEW_LONG_STRING_KEYS:
            return 600
        if pk in self._PREVIEW_URLISH_STRING_KEYS or pk.endswith("_url"):
            return 2048
        return 240

    def build_source_candidates_preview(
        self,
        data: Any,
        *,
        max_items: int = 5,
        tool_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Lift exact result handles out of bulky search/item arrays.

        Generic preview ranking intentionally pushes large arrays down, but
        follow-up tool calls often need the exact URLs/IDs from those arrays.
        Keep a small provider-facing candidate list so models do not have to
        reconstruct links from prose summaries.
        """
        if not isinstance(data, dict):
            return []

        candidate_keys = (
            "candidates",
            "top_results",
            "results",
            "video_results",
            "organic_results",
            "shopping_results",
            "items",
        )
        source_key = ""
        raw_items: Any = None
        for key in candidate_keys:
            value = data.get(key)
            if isinstance(value, list) and value:
                source_key = key
                raw_items = value
                break

        if not isinstance(raw_items, list):
            return []

        exact_fields = (
            "title",
            "name",
            "url",
            "link",
            "youtube_url",
            "video_id",
            "asin",
            "product_id",
            "channel",
            "source",
            "published_date",
            "date",
            "duration",
            "price",
            "rating",
            "thumbnail",
            "image",
            "image_url",
        )
        url_aliases = ("url", "link", "youtube_url", "watch_url", "product_link")
        is_hotel_search = str(data.get("engine") or "").strip().lower() == "google_hotels"
        is_yelp_search = str(data.get("engine") or "").strip().lower() == "yelp"
        is_search_index = str(tool_name or "").strip().lower() == "serpapi_search_index"
        is_google_local = (
            str(tool_name or "").strip().lower() == "serpapi_google_local"
        )
        is_google_local_services = (
            str(tool_name or "").strip().lower() == "serpapi_google_local_services"
        )
        is_google_news_light = (
            str(tool_name or "").strip().lower() == "serpapi_google_news_light"
        )
        is_google_trends = str(tool_name or "").strip().lower() == "serpapi_google_trends"
        is_google_trending_now = (
            str(tool_name or "").strip().lower() == "serpapi_google_trending_now"
        )
        is_tripadvisor = str(tool_name or "").strip().lower() == "serpapi_tripadvisor"
        is_flight_search = str(tool_name or "").strip().lower() == "flight_search"

        candidates: list[dict[str, Any]] = []
        for index, item in enumerate(raw_items[:max_items], 1):
            if not isinstance(item, dict):
                continue

            candidate: dict[str, Any] = {
                "rank": index,
                "source_list": source_key,
            }
            for key in exact_fields:
                value = item.get(key)
                if value in (None, ""):
                    continue
                candidate[key] = self.build_preview_value(
                    value,
                    parent_key=key,
                    depth=0,
                    max_depth=1,
                )

            if is_hotel_search:
                for key in ("price_total", "price_per_night"):
                    value = item.get(key)
                    if value not in (None, ""):
                        candidate[key] = self.build_preview_value(
                            value,
                            parent_key=key,
                            depth=0,
                            max_depth=1,
                        )

                amenities = item.get("amenities")
                if isinstance(amenities, list) and amenities:
                    normalized_amenities = {
                        str(amenity).strip().lower().replace("_", "-")
                        for amenity in amenities
                    }
                    candidate["pet_friendly"] = any(
                        amenity in {"pet-friendly", "pets-allowed", "pets allowed"}
                        for amenity in normalized_amenities
                    )

            if is_yelp_search:
                for key in (
                    "place_id",
                    "reviews",
                    "categories",
                    "neighborhoods",
                    "open_state",
                    "snippet",
                ):
                    value = item.get(key)
                    if value not in (None, "", [], {}):
                        candidate[key] = self.build_preview_value(
                            value,
                            parent_key=key,
                            depth=0,
                            max_depth=1,
                        )

            if is_search_index:
                for key in (
                    "displayed_link",
                    "snippet",
                    "language",
                    "sitelinks",
                ):
                    value = item.get(key)
                    if value not in (None, "", [], {}):
                        candidate[key] = self.build_preview_value(
                            value,
                            parent_key=key,
                            depth=0,
                            max_depth=2,
                        )

            if is_google_local:
                for key in (
                    "place_id",
                    "website",
                    "directions_url",
                    "google_maps_url",
                    "place_id_search",
                    "reviews",
                    "reviews_original",
                    "type",
                    "address",
                    "hours",
                    "description",
                    "gps_coordinates",
                    "service_options",
                    "sponsored",
                ):
                    value = item.get(key)
                    if value not in (None, "", [], {}):
                        candidate[key] = self.build_preview_value(
                            value,
                            parent_key=key,
                            depth=0,
                            max_depth=2,
                        )

            if is_google_local_services:
                for key in (
                    "website",
                    "phone",
                    "badge",
                    "reviews",
                    "rating_stars",
                    "type",
                    "address",
                    "service_area",
                    "years_in_business",
                    "bookings_nearby",
                    "hours_current",
                    "hours_week",
                    "checks",
                    "description",
                    "services",
                    "cid",
                    "bid",
                    "pid",
                ):
                    value = item.get(key)
                    if value not in (None, "", [], {}):
                        candidate[key] = self.build_preview_value(
                            value,
                            parent_key=key,
                            depth=0,
                            max_depth=2,
                        )

            if is_google_news_light:
                snippet = item.get("snippet")
                if snippet not in (None, ""):
                    candidate["snippet"] = self.build_preview_value(
                        snippet,
                        parent_key="snippet",
                        depth=0,
                        max_depth=1,
                    )

            if is_google_trends:
                for key in (
                    "query",
                    "trend_type",
                    "topic_id",
                    "topic_type",
                    "location",
                    "geo",
                    "latest_date",
                    "latest_value",
                    "previous_value",
                    "change_from_previous",
                    "change_over_period",
                    "direction",
                    "average_value",
                    "peak_value",
                    "peak_date",
                    "value",
                    "extracted_value",
                    "top_query",
                    "top_value",
                    "values",
                ):
                    value = item.get(key)
                    if value not in (None, "", [], {}):
                        candidate[key] = self.build_preview_value(
                            value,
                            parent_key=key,
                            depth=0,
                            max_depth=2,
                        )

            if is_google_trending_now:
                for key in (
                    "position",
                    "query",
                    "start_time",
                    "end_time",
                    "active",
                    "search_volume",
                    "increase_percentage",
                    "category_names",
                    "trend_breakdown",
                    "google_trends_url",
                ):
                    value = item.get(key)
                    if value not in (None, "", [], {}):
                        candidate[key] = self.build_preview_value(
                            value,
                            parent_key=key,
                            depth=0,
                            max_depth=2,
                        )

            if is_tripadvisor:
                for key in (
                    "place_id",
                    "place_type",
                    "review_id",
                    "reviews",
                    "location",
                    "address",
                    "description",
                    "text",
                    "author_name",
                    "trip_type",
                ):
                    value = item.get(key)
                    if value not in (None, "", [], {}):
                        candidate[key] = self.build_preview_value(
                            value,
                            parent_key=key,
                            depth=0,
                            max_depth=1,
                        )

            if is_flight_search:
                for key in (
                    "airlines",
                    "flight_numbers",
                    "departure_airport",
                    "departure_time",
                    "arrival_airport",
                    "arrival_time",
                    "duration_display",
                    "stops_label",
                ):
                    value = item.get(key)
                    if value not in (None, "", [], {}):
                        candidate[key] = self.build_preview_value(
                            value,
                            parent_key=key,
                            depth=0,
                            max_depth=1,
                        )

            if "url" not in candidate:
                for alias in url_aliases:
                    value = item.get(alias)
                    if value not in (None, ""):
                        candidate["url"] = self.build_preview_value(
                            value,
                            parent_key="url",
                            depth=0,
                            max_depth=1,
                        )
                        break

            if len(candidate) > 2:
                candidates.append(candidate)

        return candidates

    def build_yelp_data_preview(self, data: Any) -> dict[str, Any]:
        """Keep Yelp request context and review excerpts without duplicating result rows."""
        if not isinstance(data, dict):
            return {}

        preview: dict[str, Any] = {}
        for key in (
            "engine",
            "find_desc",
            "find_loc",
            "attrs",
            "sort_by",
            "sort_basis",
            "results_count",
            "provider_results_count",
            "serpapi_searches_used",
            "source",
        ):
            value = data.get(key)
            if value not in (None, "", [], {}):
                preview[key] = self.build_preview_value(
                    value,
                    parent_key=key,
                    max_depth=1,
                )

        review_data = data.get("review_data")
        if isinstance(review_data, dict):
            compact_review_data = {
                key: review_data[key]
                for key in ("place_id", "business", "total_results", "results_count")
                if review_data.get(key) not in (None, "", [], {})
            }
            reviews = []
            for item in (review_data.get("reviews") or [])[:3]:
                if not isinstance(item, dict):
                    continue
                review = {
                    key: item[key]
                    for key in ("rating", "date", "user_name", "user_location")
                    if item.get(key) not in (None, "")
                }
                if item.get("text"):
                    review["text"] = self.truncate_preview_text(item["text"], 300)
                if review:
                    reviews.append(review)
            if reviews:
                compact_review_data["reviews"] = reviews
            if compact_review_data:
                preview["review_data"] = compact_review_data

        return preview

    def build_tripadvisor_data_preview(self, data: Any) -> dict[str, Any]:
        """Keep Tripadvisor action context and bounded enrichment data."""
        if not isinstance(data, dict):
            return {}

        preview: dict[str, Any] = {}
        for key in (
            "action",
            "engine",
            "query",
            "category",
            "tripadvisor_domain",
            "place_id",
            "results_count",
            "total_reviews",
            "review_sort_by",
            "review_filters",
            "serpapi_searches_used",
            "source",
            "enrichment_errors",
        ):
            value = data.get(key)
            if value not in (None, "", [], {}):
                preview[key] = self.build_preview_value(
                    value,
                    parent_key=key,
                    max_depth=2,
                )

        place = data.get("place")
        if isinstance(place, dict):
            preview["place"] = self.build_preview_value(
                place,
                parent_key="place",
                max_depth=2,
            )

        interesting = data.get("interesting_places")
        if isinstance(interesting, list) and interesting:
            preview["interesting_places"] = self.build_preview_value(
                interesting[:5],
                parent_key="interesting_places",
                max_depth=2,
            )

        detail_data = data.get("detail_data")
        if isinstance(detail_data, dict):
            compact_detail = {}
            if isinstance(detail_data.get("place"), dict):
                compact_detail["place"] = self.build_preview_value(
                    detail_data["place"],
                    parent_key="place",
                    max_depth=2,
                )
            if isinstance(detail_data.get("interesting_places"), list):
                compact_detail["interesting_places"] = self.build_preview_value(
                    detail_data["interesting_places"][:5],
                    parent_key="interesting_places",
                    max_depth=2,
                )
            if compact_detail:
                preview["detail_data"] = compact_detail

        review_data = data.get("review_data")
        review_source = review_data if isinstance(review_data, dict) else data
        reviews = review_source.get("reviews") if isinstance(review_source, dict) else None
        if isinstance(reviews, list) and reviews:
            compact_reviews = []
            for item in reviews[:3]:
                if not isinstance(item, dict):
                    continue
                review = {
                    key: item[key]
                    for key in (
                        "title",
                        "rating",
                        "date",
                        "trip_type",
                        "author_name",
                        "url",
                    )
                    if item.get(key) not in (None, "")
                }
                if item.get("text"):
                    review["text"] = self.truncate_preview_text(item["text"], 300)
                if review:
                    compact_reviews.append(review)
            if compact_reviews:
                preview["reviews"] = compact_reviews

        return preview

    def build_search_index_data_preview(self, data: Any) -> dict[str, Any]:
        """Keep Search Index request, pagination, and related-query context."""
        if not isinstance(data, dict):
            return {}

        preview: dict[str, Any] = {}
        for key in (
            "engine",
            "query",
            "mode",
            "safe",
            "start",
            "num_results",
            "results_count",
            "provider_results_count",
            "total_results",
            "top_url",
            "search_id",
            "has_more",
            "next_start",
            "serpapi_searches_used",
            "source",
        ):
            value = data.get(key)
            if value not in (None, "", [], {}):
                preview[key] = self.build_preview_value(
                    value,
                    parent_key=key,
                    max_depth=1,
                )

        related_searches = data.get("related_searches")
        if isinstance(related_searches, list) and related_searches:
            preview["related_searches"] = self.build_preview_value(
                related_searches[:8],
                parent_key="related_searches",
                max_depth=1,
            )

        pagination = data.get("pagination")
        if isinstance(pagination, dict):
            preview["pagination"] = self.build_preview_value(
                pagination,
                parent_key="pagination",
                max_depth=1,
            )
        return preview

    def build_google_trends_data_preview(self, data: Any) -> dict[str, Any]:
        """Keep trend request context plus bounded averages and recent timeline data."""
        if not isinstance(data, dict):
            return {}

        preview: dict[str, Any] = {}
        for key in (
            "engine",
            "query",
            "queries",
            "data_type",
            "provider_data_type",
            "date",
            "geo",
            "region",
            "language",
            "timezone_offset",
            "category",
            "property",
            "results_count",
            "provider_results_count",
            "latest_period",
            "timeline_points_returned",
            "timeline_points_original",
            "search_id",
            "trends_url",
            "serpapi_searches_used",
            "source",
        ):
            value = data.get(key)
            if value not in (None, "", [], {}):
                preview[key] = self.build_preview_value(
                    value,
                    parent_key=key,
                    max_depth=2,
                )

        averages = data.get("averages")
        if isinstance(averages, list) and averages:
            preview["averages"] = self.build_preview_value(
                averages[:5],
                parent_key="averages",
                max_depth=2,
            )

        timeline = data.get("timeline_data")
        if isinstance(timeline, list) and timeline:
            selected = timeline if len(timeline) <= 4 else [timeline[0], *timeline[-3:]]
            preview["timeline_sample"] = self.build_preview_value(
                selected,
                parent_key="timeline_sample",
                max_depth=3,
            )
        return preview

    def build_google_news_light_data_preview(self, data: Any) -> dict[str, Any]:
        """Keep Google News request context and bounded grouped Top Stories."""
        if not isinstance(data, dict):
            return {}

        preview: dict[str, Any] = {}
        for key in (
            "engine",
            "query",
            "query_displayed",
            "news_results_state",
            "location",
            "country",
            "language",
            "language_restrict",
            "google_domain",
            "safe",
            "exclude_autocorrected",
            "filter_similar",
            "device",
            "start",
            "max_results",
            "results_count",
            "provider_results_count",
            "top_stories_count",
            "provider_top_story_groups_count",
            "top_story_articles_count",
            "provider_top_story_articles_count",
            "top_url",
            "search_id",
            "google_news_light_url",
            "has_more",
            "next_start",
            "serpapi_searches_used",
            "source",
        ):
            value = data.get(key)
            if value not in (None, "", [], {}):
                preview[key] = self.build_preview_value(
                    value,
                    parent_key=key,
                    max_depth=1,
                )

        pagination = data.get("pagination")
        if isinstance(pagination, dict):
            preview["pagination"] = {
                key: pagination[key]
                for key in (
                    "current",
                    "start",
                    "has_more",
                    "next_start",
                    "previous_start",
                )
                if pagination.get(key) not in (None, "") or key == "has_more"
            }

        groups = []
        for group in (data.get("top_stories") or [])[:3]:
            if not isinstance(group, dict):
                continue
            compact_group = {
                key: group[key]
                for key in (
                    "position",
                    "title",
                    "stories_count",
                    "provider_stories_count",
                )
                if group.get(key) not in (None, "")
            }
            stories = []
            for story in (group.get("stories") or [])[:3]:
                if not isinstance(story, dict):
                    continue
                compact_story = {
                    key: story[key]
                    for key in ("position", "title", "url", "source", "date")
                    if story.get(key) not in (None, "")
                }
                if compact_story:
                    stories.append(compact_story)
            if stories:
                compact_group["stories"] = stories
            if compact_group:
                groups.append(compact_group)
        if groups:
            preview["top_stories"] = groups
        return preview

    def build_google_local_data_preview(self, data: Any) -> dict[str, Any]:
        """Keep Google Local provenance, pagination, ads, and related searches compact."""
        if not isinstance(data, dict):
            return {}

        preview: dict[str, Any] = {}
        for key in (
            "engine",
            "query",
            "location",
            "location_source",
            "uule_used",
            "provider_location_requested",
            "provider_location_used",
            "country",
            "language",
            "google_domain",
            "device",
            "start",
            "place_id",
            "tbs",
            "max_results",
            "results_count",
            "provider_results_count",
            "ads_count",
            "provider_ads_count",
            "discover_more_count",
            "provider_discover_more_count",
            "local_map_image",
            "top_url",
            "search_id",
            "google_local_url",
            "has_more",
            "next_start",
            "serpapi_searches_used",
            "source",
        ):
            value = data.get(key)
            if value not in (None, "", [], {}):
                preview[key] = self.build_preview_value(
                    value,
                    parent_key=key,
                    max_depth=2,
                )

        pagination = data.get("pagination")
        if isinstance(pagination, dict):
            preview["pagination"] = {
                key: pagination[key]
                for key in (
                    "current",
                    "start",
                    "has_more",
                    "next_start",
                    "previous_start",
                )
                if pagination.get(key) not in (None, "") or key == "has_more"
            }

        ads = data.get("ads")
        if isinstance(ads, list) and ads:
            preview["ads"] = self.build_preview_value(
                ads[:3],
                parent_key="ads",
                max_depth=2,
            )

        discover_more = data.get("discover_more_places")
        if isinstance(discover_more, list) and discover_more:
            preview["discover_more_places"] = self.build_preview_value(
                discover_more[:5],
                parent_key="discover_more_places",
                max_depth=2,
            )
        return preview

    def build_google_local_services_data_preview(self, data: Any) -> dict[str, Any]:
        """Keep Local Services location cost, provider IDs, and details compact."""
        if not isinstance(data, dict):
            return {}

        preview: dict[str, Any] = {}
        for key in (
            "engine",
            "mode",
            "query",
            "provider_query",
            "location",
            "location_source",
            "resolved_location",
            "data_cid",
            "data_cid_source",
            "language",
            "job_type",
            "cid",
            "bid",
            "pid",
            "max_results",
            "results_count",
            "provider_results_count",
            "top_url",
            "google_local_services_url",
            "search_id",
            "serpapi_searches_used",
            "us_only",
            "source",
        ):
            value = data.get(key)
            if value not in (None, "", [], {}):
                preview[key] = self.build_preview_value(
                    value,
                    parent_key=key,
                    max_depth=2,
                )

        detail = data.get("detail")
        if isinstance(detail, dict) and detail:
            preview["detail"] = self.build_preview_value(
                detail,
                parent_key="detail",
                max_depth=2,
            )
        return preview

    def build_google_trending_now_data_preview(self, data: Any) -> dict[str, Any]:
        """Keep current-trend filters and news-drill-down provenance compact."""
        if not isinstance(data, dict):
            return {}

        preview: dict[str, Any] = {}
        for key in (
            "action",
            "engine",
            "requested_topic",
            "scope_notice",
            "trend_query",
            "geo",
            "language",
            "hours",
            "category_id",
            "only_active",
            "results_count",
            "provider_results_count",
            "active_results_count",
            "top_query",
            "top_url",
            "search_id",
            "trending_now_url",
            "trends_news_url",
            "serpapi_searches_used",
            "source",
        ):
            value = data.get(key)
            if value not in (None, "", [], {}):
                preview[key] = self.build_preview_value(
                    value,
                    parent_key=key,
                    max_depth=2,
                )
        return preview

    def build_flight_data_preview(self, data: Any) -> dict[str, Any]:
        """Keep compact flight-search request, route, and pricing context."""
        if not isinstance(data, dict):
            return {}

        preview: dict[str, Any] = {}
        for key in (
            "provider",
            "trip_type",
            "departure_id",
            "arrival_id",
            "outbound_date",
            "return_date",
            "travel_class",
            "stops_filter",
            "sort_by",
            "currency",
            "results_count",
            "cheapest_price",
            "price_basis",
            "booking_url",
            "price_insights",
            "source",
        ):
            value = data.get(key)
            if value not in (None, "", [], {}):
                preview[key] = self.build_preview_value(
                    value,
                    parent_key=key,
                    max_depth=2,
                )
        return preview

    def build_preview_value(
        self,
        value: Any,
        parent_key: str = "",
        depth: int = 0,
        max_depth: int = 3,
    ) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value

        if isinstance(value, str):
            return self.truncate_preview_text(value, self.preview_string_limit(parent_key))

        if depth >= max_depth:
            compact = json.dumps(value, default=str, separators=(",", ":"))
            return self.truncate_preview_text(compact, 240)

        if isinstance(value, list):
            if not value:
                return []
            item_limit = 5 if parent_key in {"results", "top_results", "items", "matches", "documents", "pages", "outputs"} else 4
            preview_items = [
                self.build_preview_value(item, parent_key=parent_key, depth=depth + 1, max_depth=max_depth)
                for item in value[:item_limit]
            ]
            if len(value) <= item_limit:
                return preview_items
            return {"total_items": len(value), "items_preview": preview_items}

        if isinstance(value, dict):
            preview = {}
            keys = sorted(value.keys(), key=lambda key: self.preview_key_rank(key, value.get(key)))
            max_keys = 12
            shown_keys = 0
            for key in keys:
                if shown_keys >= max_keys:
                    break
                preview[key] = self.build_preview_value(
                    value.get(key),
                    parent_key=key,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
                shown_keys += 1
            omitted = len(keys) - shown_keys
            if omitted > 0:
                preview["_omitted_keys"] = omitted
            return preview

        return self.truncate_preview_text(value, 240)

    def build_workflow_result_preview(
        self,
        result: dict[str, Any],
        *,
        max_chars: int,
    ) -> dict[str, Any]:
        """
        Build a step-aware workflow projection for the next orchestration turn.

        The generic preview intentionally keeps only a few items from bulky
        arrays. A workflow's ``results`` array is different: later steps often
        contain the final Canvas page, Stash ref, or summary needed to finish
        the user's request. Keep every normal recipe step, but omit the
        duplicated workflow ``variables`` graph and bound each component.
        """
        data = result.get("data") if isinstance(result, dict) else {}
        data = data if isinstance(data, dict) else {}
        raw_steps = data.get("results")
        raw_steps = raw_steps if isinstance(raw_steps, list) else []

        # Current built-in/personal recipes are small (the shipped maximum is
        # 13). Keep a defensive head+tail selection for unexpectedly large
        # personal workflows so final artifact-producing steps are never lost.
        if len(raw_steps) > 20:
            selected_steps = raw_steps[:10] + raw_steps[-10:]
            omitted_steps = len(raw_steps) - len(selected_steps)
        else:
            selected_steps = raw_steps
            omitted_steps = 0

        # Reserve room for top-level workflow metadata plus per-step status
        # fields. The remainder is shared fairly between component payloads.
        reserved_chars = 3000
        per_step_chars = max(
            260,
            min(650, (max_chars - reserved_chars) // max(1, len(selected_steps))),
        )
        step_previews: list[dict[str, Any]] = []
        for raw_step in selected_steps:
            if not isinstance(raw_step, dict):
                step_previews.append(
                    {"result_preview": self.truncate_preview_text(raw_step, per_step_chars)}
                )
                continue

            step_preview: dict[str, Any] = {}
            for key in (
                "step",
                "tool",
                "ok",
                "skipped",
                "cancelled",
                "reason",
                "items_processed",
                "items_succeeded",
                "duration_ms",
            ):
                if key in raw_step and raw_step[key] is not None:
                    step_preview[key] = self.build_preview_value(
                        raw_step[key],
                        parent_key=key,
                        max_depth=1,
                    )

            if raw_step.get("error"):
                step_preview["error"] = self.truncate_preview_text(raw_step["error"], 240)
            if raw_step.get("speech"):
                step_preview["speech"] = self.truncate_preview_text(raw_step["speech"], 300)

            component_payload = (
                raw_step.get("data")
                if raw_step.get("data") not in (None, {}, [])
                else raw_step.get("outputs")
            )
            if component_payload not in (None, {}, []):
                component_preview = self.build_preview_value(
                    component_payload,
                    parent_key="data",
                    max_depth=3,
                )
                component_context: dict[str, Any] = {}
                source_candidates = self.build_source_candidates_preview(
                    component_payload,
                    tool_name=raw_step.get("tool"),
                )
                if source_candidates:
                    component_context["source_candidates"] = source_candidates
                component_context["data_preview"] = component_preview
                component_text = json.dumps(
                    component_context,
                    default=str,
                    separators=(",", ":"),
                )
                step_preview["result_preview"] = self.truncate_preview_text(
                    component_text,
                    per_step_chars,
                )

            step_previews.append(step_preview)

        workflow_preview: dict[str, Any] = {
            "ok": result.get("ok", True),
            "speech": self.truncate_preview_text(result.get("speech", ""), 400),
            "llm_context_preview": {
                "tool": "workflow",
                "action": data.get("action"),
                "workflow_id": data.get("workflow_id"),
                "workflow_name": data.get("workflow_name"),
                "execution": data.get("execution"),
                "workflow_started": data.get("workflow_started"),
                "workflow_completed": data.get("workflow_completed"),
                "steps_completed": data.get("steps_completed"),
                "component_tools_used": data.get("component_tools_used", []),
                "step_results": step_previews,
            },
        }
        if omitted_steps:
            workflow_preview["llm_context_preview"]["omitted_middle_steps"] = omitted_steps
        if result.get("cancelled") is not None:
            workflow_preview["cancelled"] = bool(result.get("cancelled"))
        if result.get("error"):
            workflow_preview["error"] = self.truncate_preview_text(result["error"], 300)
        return workflow_preview

    def build_llm_result_context_preview(self, tool_name: str, result: dict[str, Any]) -> tuple[str, int, int, bool]:
        full_serialized = json.dumps(result, indent=2, default=str)
        result_chars_total = len(full_serialized)
        max_chars = self.tool_context_max_chars(tool_name)

        force_compact_projection = (tool_name or "").lower() == "flight_search"
        if result_chars_total <= max_chars and not force_compact_projection:
            return full_serialized, result_chars_total, result_chars_total, False

        data = result.get("data")
        if (tool_name or "").lower() == "workflow":
            preview_payload = self.build_workflow_result_preview(
                result,
                max_chars=max_chars,
            )
        else:
            normalized_tool_name = (tool_name or "").lower()
            if normalized_tool_name == "serpapi_yelp_search":
                data_preview = self.build_yelp_data_preview(data)
            elif normalized_tool_name == "serpapi_search_index":
                data_preview = self.build_search_index_data_preview(data)
            elif normalized_tool_name == "serpapi_google_local":
                data_preview = self.build_google_local_data_preview(data)
            elif normalized_tool_name == "serpapi_google_local_services":
                data_preview = self.build_google_local_services_data_preview(data)
            elif normalized_tool_name == "serpapi_google_news_light":
                data_preview = self.build_google_news_light_data_preview(data)
            elif normalized_tool_name == "serpapi_google_trends":
                data_preview = self.build_google_trends_data_preview(data)
            elif normalized_tool_name == "serpapi_google_trending_now":
                data_preview = self.build_google_trending_now_data_preview(data)
            elif normalized_tool_name == "serpapi_tripadvisor":
                data_preview = self.build_tripadvisor_data_preview(data)
            elif normalized_tool_name == "flight_search":
                data_preview = self.build_flight_data_preview(data)
            else:
                data_preview = self.build_preview_value(data, parent_key="data")
            preview_payload = {
                "ok": result.get("ok", True),
                "speech": self.truncate_preview_text(result.get("speech", ""), 400),
                "llm_context_preview": {
                    "tool": tool_name,
                    "data_preview": data_preview,
                },
            }
        source_candidates = self.build_source_candidates_preview(
            data,
            tool_name=tool_name,
        )
        if source_candidates and (tool_name or "").lower() != "workflow":
            preview_payload["llm_context_preview"]["source_candidates"] = source_candidates
        if result.get("error"):
            preview_payload["error"] = self.truncate_preview_text(result["error"], 300)

        if force_compact_projection:
            preview_serialized = json.dumps(
                preview_payload,
                separators=(",", ":"),
                default=str,
            )
        else:
            preview_serialized = json.dumps(preview_payload, indent=2, default=str)
        if len(preview_serialized) <= max_chars:
            return preview_serialized, result_chars_total, len(preview_serialized), True

        preview_compact = json.dumps(preview_payload, separators=(",", ":"), default=str)
        if len(preview_compact) <= max_chars:
            return preview_compact, result_chars_total, len(preview_compact), True

        if (tool_name or "").lower() == "workflow":
            # Rebuild with a tighter shared component budget before falling
            # through to the generic single-tool fallback, which would retain
            # only the first few workflow steps.
            preview_payload = self.build_workflow_result_preview(
                result,
                max_chars=max(2000, max_chars - 2500),
            )
            preview_compact = json.dumps(preview_payload, separators=(",", ":"), default=str)
            if len(preview_compact) <= max_chars:
                return preview_compact, result_chars_total, len(preview_compact), True

        fallback_payload = {
            "ok": result.get("ok", True),
            "speech": self.truncate_preview_text(result.get("speech", ""), 240),
            "preview_notice": (
                "Structured result preview trimmed to fit LLM context. "
                "Use speech and lifted identifiers first; do not re-call the same tool just to recover omitted tail content."
            ),
            "llm_context_preview": {
                "tool": tool_name,
                "data_preview_text": "",
            },
        }
        if result.get("error"):
            fallback_payload["error"] = self.truncate_preview_text(result["error"], 200)

        data_preview_text = json.dumps(
            self.build_preview_value(data, parent_key="data"),
            default=str,
            separators=(",", ":"),
        )
        suffix = "... [truncated]"

        base_serialized = json.dumps(fallback_payload, default=str, separators=(",", ":"))
        if len(base_serialized) >= max_chars:
            minimal_payload = {
                "ok": result.get("ok", True),
                "speech": self.truncate_preview_text(result.get("speech", ""), 120),
                "preview_notice": "Result preview omitted to fit LLM context. Do not re-call the same tool just to recover omitted tail content.",
            }
            minimal_serialized = json.dumps(minimal_payload, default=str, separators=(",", ":"))
            return minimal_serialized, result_chars_total, len(minimal_serialized), True

        empty_preview_serialized = json.dumps(fallback_payload, default=str, separators=(",", ":"))
        remaining = max_chars - len(empty_preview_serialized)
        if remaining > len(suffix):
            fallback_payload["llm_context_preview"]["data_preview_text"] = (
                self.truncate_preview_text(data_preview_text, remaining)
            )

        fallback_serialized = json.dumps(fallback_payload, default=str, separators=(",", ":"))
        if len(fallback_serialized) > max_chars:
            allowed = max_chars - len(empty_preview_serialized)
            if allowed > len(suffix):
                fallback_payload["llm_context_preview"]["data_preview_text"] = data_preview_text[: allowed - len(suffix)] + suffix
            else:
                fallback_payload["llm_context_preview"]["data_preview_text"] = ""
            fallback_serialized = json.dumps(fallback_payload, default=str, separators=(",", ":"))

        return fallback_serialized, result_chars_total, len(fallback_serialized), True
