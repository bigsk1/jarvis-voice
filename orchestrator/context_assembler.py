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
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

class ContextAssembler:
    """Build prompt/context strings while keeping the main orchestrator slimmer."""

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
            if role == "assistant" and tool_results:
                # Keep the display prose as a compact reminder only.
                cap = min(cap, 1200)
            if len(content) > cap:
                content = content[:cap] + "... [truncated]"

            prefix = "User" if role == "user" else "Jarvis"
            if role == "assistant" and tools_used:
                unique_tools = list(dict.fromkeys(tools_used))
                tools_str = ", ".join(unique_tools)
                if tool_results:
                    context_lines.append(f"{prefix} [tools: {tools_str}]")
                    context_lines.append("  Structured follow-up data (source of truth):")

                    for tool_name, result_data in tool_results.items():
                        if isinstance(result_data, dict):
                            fields = []
                            for key, value in result_data.items():
                                if value:
                                    fields.append(f"{key}={value}")
                            if fields:
                                context_lines.append(f"  └─ {tool_name} data: {', '.join(fields)}")
                    if content:
                        context_lines.append(f"  Display summary: {content}")
                else:
                    context_lines.append(f"{prefix} [tools: {tools_str}]: {content}")
            else:
                context_lines.append(f"{prefix}: {content}")

        for message in recent:
            tool_results = message.get("tool_results", {}) or {}
            uploaded_image = tool_results.get("uploaded_image", {}) if isinstance(tool_results, dict) else {}
            stash_ref = uploaded_image.get("stash_ref") if isinstance(uploaded_image, dict) else None
            if stash_ref and str(stash_ref).startswith("stash://"):
                context_lines.append("")
                context_lines.append(
                    "IMAGE RE-ANALYSIS: If the user asks to look again, correct, or re-identify the image: use analyze_image with image=\""
                    + str(stash_ref)
                    + "\". Do NOT use '1', 'image ID 1', or attachment indices."
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

    def tool_context_max_chars(self, tool_name: str) -> int:
        lowered = (tool_name or "").lower()
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

    def build_llm_result_context_preview(self, tool_name: str, result: dict[str, Any]) -> tuple[str, int, int, bool]:
        full_serialized = json.dumps(result, indent=2, default=str)
        result_chars_total = len(full_serialized)
        max_chars = self.tool_context_max_chars(tool_name)

        if result_chars_total <= max_chars:
            return full_serialized, result_chars_total, result_chars_total, False

        data = result.get("data")
        preview_payload: dict[str, Any] = {
            "ok": result.get("ok", True),
            "speech": self.truncate_preview_text(result.get("speech", ""), 400),
            "llm_context_preview": {
                "tool": tool_name,
                "data_preview": self.build_preview_value(data, parent_key="data"),
            },
        }
        if result.get("error"):
            preview_payload["error"] = self.truncate_preview_text(result["error"], 300)

        preview_serialized = json.dumps(preview_payload, indent=2, default=str)
        if len(preview_serialized) <= max_chars:
            return preview_serialized, result_chars_total, len(preview_serialized), True

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
