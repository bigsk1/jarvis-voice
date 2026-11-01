"""Screen model-bound evidence and quarantine confirmed prompt injections.

Only returned data, speech and error text are submitted. Stash references and
URLs are never resolved here. Observation covers the returned representation;
it cannot establish coverage of an upstream page or an already saved artifact.
"""

from __future__ import annotations

import hashlib
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
from lib.prompt_guard_alerts import notify_prompt_guard_block
from lib.prompt_guard_incidents import save_incident

logger = logging.getLogger("prompt_guard.observer")

DEFAULT_TOOLS = "crawl_url,brave_llm_context,rss_feed,browser_use,browser_use_cloud,stash,source_library"
_TOOL_NAME = re.compile(r"[A-Za-z0-9_]{1,100}\Z")
_POLICY_ID = re.compile(r"[A-Za-z0-9_.:-]{1,100}\Z")
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
    if metadata.get("source_type") == "attachment":
        return (
            "Prompt Guard withheld attachment text because it detected a possible prompt injection."
            f"{reference} The attachment text was not sent to the model and will not be retried automatically."
        )
    return (
        f"Prompt Guard withheld content from {tool_label} because it detected a possible prompt injection."
        f"{reference} The tool already ran and will not be retried automatically."
    )


def _withheld_result(
    tool_name: str, original: dict[str, Any], observation: PromptGuardResult,
    *, source_type: str,
) -> dict[str, Any]:
    completion = original.get("completion")
    if not isinstance(completion, str) or completion not in {"completed", "rejected", "unknown"}:
        completion = "unknown"
    original_ok = original.get("ok")
    if source_type == "attachment":
        completion = "rejected"
    withheld = {
        "ok": False,
        "error_code": "prompt_injection_detected",
        "terminal_failure": True,
        "retry_safe": False,
        "completion": completion,
        "error": "Returned content withheld by Prompt Guard.",
        "data": {
            "prompt_guard": {
                "content_withheld": True, "tool": tool_name, "source_type": source_type,
                "incident_id": None, "evidence_saved": False,
                "score": observation.injection_score, "threshold": observation.threshold,
            },
            "operation": {
                "tool_executed": source_type == "tool_result",
                "original_ok": original_ok if type(original_ok) is bool else None,
            },
        },
    }
    policy_id = getattr(observation, "policy_id", None)
    if isinstance(policy_id, str) and _POLICY_ID.fullmatch(policy_id):
        withheld["data"]["prompt_guard"]["policy_id"] = policy_id
    return withheld


class _SkippedContent(ValueError):
    """A result cannot be fully represented inside the observation budget."""


def _log_skip(tool_name: str, reason: str, *, source_type: str = "tool_result") -> None:
    """Keep diagnostics metadata-only, even when observation itself fails."""
    try:
        logger.info(
            "[PROMPT_GUARD] mode=%s source=%s tool=%s reason=%s action=continue",
            get_active_config_mode(), source_type, tool_name, reason,
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


def _selected_artifact_action(tool_name: str, args: dict[str, Any] | None) -> bool:
    """Gate artifact reads by caller-owned arguments, never result metadata.

    Stash defaults to list; Source Library defaults to search. Match each tool's
    dispatcher, including Stash's case folding. Writes and administrative results
    carry no retrieved document text and do not belong to this boundary.
    """
    parameters = args if isinstance(args, dict) else {}
    if tool_name == "stash":
        action = parameters.get("action", "list")
        return isinstance(action, str) and action.lower() == "read"
    if tool_name == "source_library":
        return parameters.get("action", "search") in ("search", "read")
    return True


def _plain_content(text: str, max_bytes: int) -> str:
    """Validate the complete model-bound text; never scan a clipped prefix."""
    if not isinstance(text, str):
        raise _SkippedContent("invalid_content")
    if len(text) > max_bytes:
        raise _SkippedContent("input_too_large")
    if not text.strip():
        raise _SkippedContent("empty_content")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError:
        raise _SkippedContent("invalid_content") from None
    if size > max_bytes:
        raise _SkippedContent("input_too_large")
    return text


def _review_content(
    tool_name: str, result: dict[str, Any], *, source_type: str,
    args: dict[str, Any] | None, mode: str | None,
    config_overrides: dict[str, str] | None, text: str | None = None,
) -> dict[str, Any]:
    """Apply the shared fail-open scan and fail-closed confirmed withholding."""
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
            if source_type == "tool_result":
                raw_tools = get_config_value("PROMPT_GUARD_TOOLS", DEFAULT_TOOLS)
                if not isinstance(raw_tools, str):
                    _log_skip(tool_name, "invalid_tool_selection")
                    return result
                selected = {name.strip() for name in raw_tools.split(",") if name.strip()}
                if tool_name not in selected or not _selected_artifact_action(tool_name, args):
                    return result
            if not is_enabled():
                # The shared client reports disabled before validating text.
                # Avoid inspecting large results when observation is switched off.
                scan_text("", source_type=source_type, source_name=tool_name)
                return result
            try:
                scanned_text = (
                    _plain_content(text, get_max_input_bytes())
                    if source_type == "attachment"
                    else _serialize_content(result, get_max_input_bytes())
                )
            except _SkippedContent as exc:
                _log_skip(tool_name, str(exc), source_type=source_type)
                return result
            observation = scan_text(scanned_text, source_type=source_type, source_name=tool_name)
            if not isinstance(observation, PromptGuardResult) or observation.status != "scanned" or observation.flagged is not True:
                return result
            # Establish the neutral result before attempting any optional I/O.
            withheld = _withheld_result(tool_name, result, observation, source_type=source_type)
            try:
                source_fields = {"source_type": source_type} if source_type != "tool_result" else {}
                receipt = save_incident(
                    tool_name=tool_name, mode=selected_mode, observation=observation,
                    text=scanned_text, args=args if isinstance(args, dict) else {}, result=result,
                    **source_fields,
                )
                withheld["data"]["prompt_guard"].update(
                    incident_id=receipt.incident_id, evidence_saved=receipt.evidence_saved,
                )
            except Exception:
                pass  # A failed quarantine write must still withhold the content.
            try:
                alert = notify_prompt_guard_block(
                    tool_name, observation, withheld,
                    text_digest=hashlib.sha256(scanned_text.encode("utf-8")).hexdigest(),
                )
                if alert is not None:
                    withheld["data"]["prompt_guard"]["alert"] = alert
            except Exception:
                pass  # Optional notification cannot unblock confirmed content.
            withheld["speech"] = prompt_guard_notice(withheld)
            try:
                logger.warning(
                    "[PROMPT_GUARD] mode=%s source=%s tool=%s policy=%s incident_id=%s evidence_saved=%s action=withhold",
                    selected_mode, source_type, tool_name,
                    withheld["data"]["prompt_guard"].get("policy_id", "configured_default"),
                    withheld["data"]["prompt_guard"]["incident_id"],
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
        _log_skip(tool_name, "observer_error", source_type=source_type)
        return result


def review_tool_result(
    tool_name: str, result: dict[str, Any], *, args: dict[str, Any] | None = None,
    mode: str | None = None, config_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Screen selected returned evidence; preserve results on incomplete scans.

    An empty PROMPT_GUARD_TOOLS disables tool-result screening. Selected Stash
    reads and Source Library reads/searches are screened when they return, not
    when an artifact is saved, downloaded, indexed, or listed. No referenced
    artifact or URL is resolved here. Existing request and job scopes survive.
    The original result is never mutated, including after confirmed detection.
    """
    return _review_content(
        tool_name, result, source_type="tool_result", args=args, mode=mode,
        config_overrides=config_overrides,
    )


def review_untrusted_text(
    source_name: str, text: str, *, mode: str | None = None,
    args: dict[str, Any] | None = None, config_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Review attachment text immediately before inserting it into a model turn.

    Source names are short caller-owned constants, never filenames or content.
    This ingestion boundary follows PROMPT_GUARD_ENABLED and the normal resource
    limits; PROMPT_GUARD_TOOLS applies only to tool results. Clean or unscanned
    text returns ``{ok: True, data: {content: text}}`` unchanged. Confirmed hits
    return the same neutral terminal receipt used by tool-result consumers,
    with no claim that a tool executed or a model consumed the attachment.
    """
    result = {"ok": True, "data": {"content": text}}
    return _review_content(
        source_name, result, source_type="attachment", args=args, mode=mode,
        config_overrides=config_overrides, text=text,
    )
