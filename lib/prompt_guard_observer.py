"""Screen selected tool results and quarantine confirmed prompt injections.

Only returned data, speech and error text are submitted. Stash references and
URLs are never resolved here. Observation covers the returned representation;
it cannot establish coverage of an upstream page or an already saved artifact.
"""

from __future__ import annotations

import json
import logging
import math
import re
from contextlib import nullcontext
from typing import Any

try:
    from config_loader import config_scope, get_active_config_mode, get_config_value
except ModuleNotFoundError as exc:
    if exc.name != "config_loader":
        raise
    from lib.config_loader import config_scope, get_active_config_mode, get_config_value

from lib.prompt_guard import PromptGuardResult, get_max_input_bytes, is_enabled, scan_text
from lib.prompt_guard_incidents import save_incident

logger = logging.getLogger("prompt_guard.observer")

DEFAULT_TOOLS = "crawl_url,brave_llm_context,rss_feed,browser_use,browser_use_cloud"
_TOOL_NAME = re.compile(r"[A-Za-z0-9_]{1,100}\Z")
_MAX_DEPTH = 32
_MAX_NODES = 4096
_INCIDENT_ID = re.compile(r"pg-[0-9a-f]{32}\Z")


def is_prompt_guard_rejection(result: object) -> bool:
    """Recognize the canonical terminal rejection from the tool boundary."""
    return (
        isinstance(result, dict)
        and result.get("error_code") == "prompt_injection_detected"
        and result.get("terminal_failure") is True
    )


def is_prompt_guard_stopped(result: object) -> bool:
    """Recognize a rejection after projection or persistence by a frontend.

    Tool execution uses the canonical envelope above. Continuation consumers
    also receive a saved stop flag or a receipt in data, optionally grouped by
    tool name. Inspect only those known shapes, never arbitrary nested content.
    """
    if not isinstance(result, dict):
        return False
    if result.get("prompt_guard_blocked") is True or is_prompt_guard_rejection(result):
        return True
    data = result.get("data")
    if not isinstance(data, dict):
        return False
    for value in (data, *data.values()):
        metadata = value.get("prompt_guard") if isinstance(value, dict) else None
        if isinstance(metadata, dict) and metadata.get("content_withheld") is True:
            return True
    return False


def prompt_guard_notice(result: dict[str, Any]) -> str:
    """Render only reviewed identifiers, never an upstream error or content."""
    data = result.get("data")
    metadata = data.get("prompt_guard") if isinstance(data, dict) else None
    metadata = metadata if isinstance(metadata, dict) else {}
    tool = metadata.get("tool")
    tool_label = tool if isinstance(tool, str) and _TOOL_NAME.fullmatch(tool) else "a tool"
    incident = metadata.get("incident_id")
    reference = (
        f" Incident {incident}."
        if isinstance(incident, str) and _INCIDENT_ID.fullmatch(incident) and metadata.get("evidence_saved") is True
        else " The incident evidence could not be saved."
    )
    return (
        f"Prompt Guard withheld content from {tool_label} because it detected a possible prompt injection."
        f"{reference} The tool already ran and will not be retried automatically."
    )


def _withheld_result(tool_name: str, original: dict[str, Any], observation: PromptGuardResult) -> dict[str, Any]:
    completion = original.get("completion")
    if not isinstance(completion, str) or completion not in {"completed", "rejected", "unknown"}:
        completion = "unknown"
    original_ok = original.get("ok")
    return {
        "ok": False,
        "error_code": "prompt_injection_detected",
        "terminal_failure": True,
        "retry_safe": False,
        "completion": completion,
        "error": "Returned content withheld by Prompt Guard.",
        "data": {
            "prompt_guard": {
                "content_withheld": True, "tool": tool_name,
                "incident_id": None, "evidence_saved": False,
                "score": observation.injection_score, "threshold": observation.threshold,
            },
            "operation": {"tool_executed": True, "original_ok": original_ok if type(original_ok) is bool else None},
        },
    }


class _SkippedContent(ValueError):
    """A result cannot be fully represented inside the observation budget."""


def _log_skip(tool_name: str, reason: str) -> None:
    """Keep diagnostics metadata-only, even when observation itself fails."""
    try:
        logger.info(
            "[PROMPT_GUARD] mode=%s source=tool_result tool=%s reason=%s action=continue",
            get_active_config_mode(), tool_name, reason,
        )
    except Exception:
        # A broken logging handler must not turn observation into enforcement.
        pass


def _serialize_content(result: dict[str, Any], max_bytes: int) -> str:
    """Serialize JSON data incrementally; skip whole instead of clipping text.

    Check strings before encoding and bound depth, nodes and accumulated UTF-8
    bytes. Reject unsupported objects rather than invoking their string methods.
    """
    if type(result) is not dict:
        raise _SkippedContent("invalid_content")
    payload: dict[str, Any] = {}
    if "data" in result:
        payload["data"] = result["data"]
    if result.get("speech") not in (None, ""):
        if not isinstance(result["speech"], str):
            raise _SkippedContent("invalid_content")
        payload["speech"] = result["speech"]
    if result.get("error") not in (None, ""):
        if not isinstance(result["error"], str):
            raise _SkippedContent("invalid_content")
        payload["error"] = result["error"]
    if not payload:
        raise _SkippedContent("empty_content")

    parts: list[str] = []
    seen: set[int] = set()
    size = 0
    nodes = 0

    def append(part: str) -> None:
        nonlocal size
        if len(part) > max_bytes:
            raise _SkippedContent("input_too_large")
        size += len(part.encode("utf-8"))
        if size > max_bytes:
            raise _SkippedContent("input_too_large")
        parts.append(part)

    def encode(value: object, depth: int = 0) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > _MAX_NODES or depth > _MAX_DEPTH:
            raise _SkippedContent("content_structure_limit")
        if value is None or type(value) in (bool, int, float, str):
            if isinstance(value, str) and len(value) > max_bytes:
                raise _SkippedContent("input_too_large")
            if isinstance(value, float) and not math.isfinite(value):
                raise _SkippedContent("invalid_content")
            append(json.dumps(value, ensure_ascii=False, allow_nan=False))
            return
        if type(value) not in (dict, list):
            raise _SkippedContent("invalid_content")
        identity = id(value)
        if identity in seen:
            raise _SkippedContent("cyclic_content")
        seen.add(identity)
        try:
            if isinstance(value, dict):
                append("{")
                for index, (key, item) in enumerate(value.items()):
                    if type(key) is not str:
                        raise _SkippedContent("invalid_content")
                    if index:
                        append(",")
                    encode(key, depth + 1)
                    append(":")
                    encode(item, depth + 1)
                append("}")
            elif isinstance(value, list):
                append("[")
                for index, item in enumerate(value):
                    if index:
                        append(",")
                    encode(item, depth + 1)
                append("]")
        finally:
            seen.remove(identity)

    try:
        encode(payload)
    except (UnicodeEncodeError, ValueError, OverflowError) as exc:
        if isinstance(exc, _SkippedContent):
            raise
        raise _SkippedContent("invalid_content") from None
    return "".join(parts)


def review_tool_result(
    tool_name: str, result: dict[str, Any], *, args: dict[str, Any] | None = None,
    mode: str | None = None, config_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Continue on scan failures; withhold confirmed detections without retry.

    Explicit tool names only: an empty PROMPT_GUARD_TOOLS disables this hook.
    Switching modes creates a scope; the current mode keeps request overrides.
    Background consumers pass config_overrides (including an empty dict) to
    explicitly create the originating job's scope in this adapter's loader.
    Evidence-saving failures cannot restore content after a confirmed detection.
    The original result is never mutated, including when it is quarantined.
    """
    if not isinstance(tool_name, str) or not _TOOL_NAME.fullmatch(tool_name):
        return result
    withheld: dict[str, Any] | None = None
    try:
        selected_mode = get_active_config_mode(mode)
        scope = (
            nullcontext()
            if config_overrides is None and (mode is None or selected_mode == get_active_config_mode())
            else config_scope(selected_mode, config_overrides)
        )
        with scope:
            raw_tools = get_config_value("PROMPT_GUARD_TOOLS", DEFAULT_TOOLS)
            if not isinstance(raw_tools, str):
                _log_skip(tool_name, "invalid_tool_selection")
                return result
            selected = {name.strip() for name in raw_tools.split(",") if name.strip()}
            if tool_name not in selected:
                return result
            if not is_enabled():
                # The shared client reports disabled before validating text.
                # Avoid inspecting large results when observation is switched off.
                scan_text("", source_type="tool_result", source_name=tool_name)
                return result
            try:
                text = _serialize_content(result, get_max_input_bytes())
            except _SkippedContent as exc:
                _log_skip(tool_name, str(exc))
                return result
            observation = scan_text(text, source_type="tool_result", source_name=tool_name)
            if not isinstance(observation, PromptGuardResult) or observation.status != "scanned" or observation.flagged is not True:
                return result
            # Establish the neutral result before attempting any optional I/O.
            withheld = _withheld_result(tool_name, result, observation)
            try:
                receipt = save_incident(
                    tool_name=tool_name, mode=selected_mode, observation=observation,
                    text=text, args=args if isinstance(args, dict) else {}, result=result,
                )
                withheld["data"]["prompt_guard"].update(
                    incident_id=receipt.incident_id, evidence_saved=receipt.evidence_saved,
                )
            except Exception:
                pass  # A failed quarantine write must still withhold the content.
            withheld["speech"] = prompt_guard_notice(withheld)
            try:
                logger.warning(
                    "[PROMPT_GUARD] mode=%s tool=%s incident_id=%s evidence_saved=%s action=withhold",
                    selected_mode, tool_name, withheld["data"]["prompt_guard"]["incident_id"],
                    withheld["data"]["prompt_guard"]["evidence_saved"],
                )
            except Exception:
                pass
            return withheld
    except Exception:
        # The optional observer must never mask an existing tool outcome or
        # turn an already completed action into a retryable execution failure.
        if withheld is not None:
            withheld["speech"] = prompt_guard_notice(withheld)
            return withheld
        _log_skip(tool_name, "observer_error")
        return result
