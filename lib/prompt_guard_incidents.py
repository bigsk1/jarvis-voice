"""Private investigation records for confirmed Prompt Guard detections.

These JSON files deliberately retain the exact scanned text, which can contain
sensitive or malicious material. They are owner-only quarantine evidence, never
Stash artifacts, model context, or ordinary log messages. Candidate URLs are
redacted separately and do not identify which source caused an aggregate hit.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from config_loader import get_config_value
except ModuleNotFoundError as exc:
    if exc.name != "config_loader":
        raise
    from lib.config_loader import get_config_value

from lib.paths import get_project_root
from lib.prompt_guard import MAX_INPUT_BYTES, PromptGuardResult
from lib.prompt_guard_diagnostics import validate_diagnostics

MAX_SOURCE_URLS = 32
MAX_URL_LENGTH = 4096
MAX_SOURCE_NODES = 2048
MAX_SOURCE_DEPTH = 8
_NAME = re.compile(r"[A-Za-z0-9_.:-]{1,100}\Z")
_REQUEST_ID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}/[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_REVISION = re.compile(r"[0-9a-fA-F]{40}\Z")
_URL_FIELDS = frozenset({
    "url", "urls", "link", "links", "source_url", "source_urls", "canonical_url",
    "permalink", "feed_url", "feed_urls", "original_url", "redirect_url", "final_url",
})
_COMPLETIONS = frozenset({"completed", "rejected", "failed", "unknown", "pending", "cancelled"})
_SENSITIVE_QUERY = re.compile(
    r"token|key|auth|password|passwd|secret|signature|credential|session|jwt|bearer|code",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class IncidentReceipt:
    """Safe correlation fields; no evidence, URL, path, or exception message."""

    incident_id: str | None
    evidence_saved: bool
    failure_code: str | None = None


def _redact_url(value: object) -> str | None:
    if (not isinstance(value, str) or not value or len(value) > MAX_URL_LENGTH
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        port = parsed.port
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        if port is not None:
            host += f":{port}"
        query = urlencode([
            (key, "[redacted]" if _SENSITIVE_QUERY.search(key) else item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=100)
        ])
        # Fragments can contain bearer tokens and never select the HTTP resource.
        cleaned = urlunsplit((parsed.scheme, host, parsed.path, query, ""))
        return cleaned if len(cleaned) <= MAX_URL_LENGTH else None
    except (ValueError, UnicodeError):
        return None


def _source_candidates(args: dict, result: dict) -> list[dict[str, str]]:
    """Inspect bounded structured fields only; never parse/fetch text or refs."""
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    visited = 0

    def add(value: object, location: str, field: str) -> None:
        cleaned = _redact_url(value)
        if cleaned is not None and (location, cleaned) not in seen:
            seen.add((location, cleaned))
            candidates.append({"location": location, "field": field, "url": cleaned})

    # A stack iterator avoids copying a potentially giant original tool result.
    for location, root in (("request", args), ("result", result)):
        stack = [(iter(root.items()), 0, "")]
        while stack and visited < MAX_SOURCE_NODES and len(candidates) < MAX_SOURCE_URLS:
            items, depth, parent_field = stack[-1]
            try:
                key, value = next(items)
            except StopIteration:
                stack.pop()
                continue
            visited += 1
            field = key if isinstance(key, str) and key in _URL_FIELDS else parent_field
            if field:
                add(value, location, field)
            if depth >= MAX_SOURCE_DEPTH:
                continue
            if isinstance(value, dict) and location == "result":
                stack.append((iter(value.items()), depth + 1, ""))
            elif isinstance(value, (list, tuple)) and (location == "result" or field):
                stack.append((enumerate(value), depth + 1, field))
    return candidates


def _scan_metadata(observation: PromptGuardResult, text: str) -> dict:
    score, threshold = observation.injection_score, observation.threshold
    if (observation.status != "scanned" or observation.flagged is not True
            or observation.coverage_complete is not True
            or type(observation.windows_scanned) is not int or observation.windows_scanned < 1
            or isinstance(score, bool) or not isinstance(score, (float, int))
            or isinstance(threshold, bool) or not isinstance(threshold, (float, int))
            or not math.isfinite(score) or not math.isfinite(threshold)
            or not 0 <= threshold <= score <= 1):
        raise ValueError("invalid_observation")
    metadata = {
        "injection_score": score,
        "threshold": threshold,
        "flagged": True,
        "coverage_complete": True,
        "windows_scanned": observation.windows_scanned,
    }
    for field, pattern in (("service_request_id", _REQUEST_ID), ("model_id", _MODEL_ID),
                           ("model_revision", _REVISION)):
        value = getattr(observation, field, None)
        if isinstance(value, str) and pattern.fullmatch(value):
            metadata[field] = value
    # Revalidate against the actual evidence, rather than relying on dataclass
    # annotations or copying a caller/service dictionary into private records.
    diagnostics = validate_diagnostics(
        observation.diagnostics, text=text, windows_scanned=observation.windows_scanned,
        injection_score=float(score),
    )
    if diagnostics is not None:
        windows = []
        for window in diagnostics.windows:
            item = {
                "index": window.index,
                "content_token_start": window.content_token_start,
                "content_token_end": window.content_token_end,
                "injection_score": window.injection_score,
            }
            if window.char_start is not None and window.char_end is not None:
                item.update(char_start=window.char_start, char_end=window.char_end)
            windows.append(item)
        saved_diagnostics = {
            "version": diagnostics.version,
            "aggregation": diagnostics.aggregation,
            "representation": diagnostics.representation,
            "winning_window_index": diagnostics.winning_window_index,
            "windows": windows,
        }
        if diagnostics.offset_unit is not None:
            saved_diagnostics["offset_unit"] = diagnostics.offset_unit
        if diagnostics.char_offset_reason is not None:
            saved_diagnostics["char_offset_reason"] = diagnostics.char_offset_reason
        metadata["diagnostics"] = saved_diagnostics
    return metadata


def _execution_summary(result: dict) -> dict:
    summary = {}
    if type(result.get("ok")) is bool:
        summary["ok"] = result["ok"]
    completion = result.get("completion")
    if isinstance(completion, str) and completion in _COMPLETIONS:
        summary["completion"] = completion
    return summary


def _open_directory(path: Path) -> int:
    """Walk with directory descriptors so no path component follows a symlink."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path.anchor, flags)
    try:
        for component in path.parts[1:]:
            try:
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _incident_directory(mode: str) -> tuple[Path, Path]:
    configured = str(get_config_value("PROMPT_GUARD_INCIDENT_DIR", "") or "").strip()
    base = Path(configured).expanduser() if configured else (
        get_project_root() / "logs" / "prompt-guard" / "incidents"
    )
    if not base.is_absolute():
        base = get_project_root() / base
    if ".." in base.parts:
        raise ValueError("invalid_directory")
    return base, base / mode


def _write_record(base: Path, directory: Path, incident_id: str, record: dict) -> None:
    # Exact directory descriptors keep a rename/symlink swap from redirecting
    # writes. Only the quarantine base and mode are made private; operator-owned
    # ancestors such as the checkout and logs directory keep their permissions.
    base_fd = _open_directory(base)
    try:
        if os.fstat(base_fd).st_uid != os.getuid():
            raise PermissionError("unowned_directory")
        os.fchmod(base_fd, 0o700)
        try:
            os.mkdir(directory.name, mode=0o700, dir_fd=base_fd)
        except FileExistsError:
            pass
        directory_fd = os.open(
            directory.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base_fd
        )
    finally:
        os.close(base_fd)
    temporary_name = f".{incident_id}.{uuid.uuid4()}.tmp"
    try:
        if os.fstat(directory_fd).st_uid != os.getuid():
            raise PermissionError("unowned_directory")
        os.fchmod(directory_fd, 0o700)
        descriptor = os.open(
            temporary_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            mode=0o600, dir_fd=directory_fd,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(record, stream, ensure_ascii=False, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            # link publishes complete bytes atomically and fails if an existing
            # incident (including a symlink) occupies the UUID destination.
            os.link(
                temporary_name, f"{incident_id}.json", src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd, follow_symlinks=False,
            )
        finally:
            os.unlink(temporary_name, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)


def save_incident(
    *, tool_name: str, mode: str, observation: PromptGuardResult, text: str,
    args: dict, result: dict,
) -> IncidentReceipt:
    """Save bounded original evidence; failures never revoke a confirmed verdict.

    Callers must continue withholding detected content even when evidence cannot
    be saved. Error codes are safe for logs; exceptions and file paths are not.
    """
    incident_id = None
    try:
        incident_id = "pg-" + uuid.uuid4().hex
        if (mode not in {"cloud", "local"} or not isinstance(tool_name, str)
                or not _NAME.fullmatch(tool_name) or not isinstance(text, str)
                or not isinstance(args, dict) or not isinstance(result, dict)):
            return IncidentReceipt(incident_id, False, "invalid_input")
        if len(text) > MAX_INPUT_BYTES:
            return IncidentReceipt(incident_id, False, "invalid_input")
        encoded = text.encode("utf-8")
        if not encoded or len(encoded) > MAX_INPUT_BYTES:
            return IncidentReceipt(incident_id, False, "invalid_input")
        metadata = _scan_metadata(observation, text)
        record = {
            "v": 1,
            "incident_id": incident_id,
            "created_at": datetime.now(UTC).isoformat(),
            "mode": mode,
            "tool_name": tool_name,
            "decision": "flagged_content_withheld",
            "scan": metadata,
            "execution_summary": _execution_summary(result),
            "evidence": {
                "representation": "scanned_tool_result", "text": text,
                "sha256": hashlib.sha256(encoded).hexdigest(), "utf8_bytes": len(encoded),
            },
            "source_candidates": _source_candidates(args, result),
            "source_attribution": "candidate_sources_only_not_isolated_by_scan",
        }
        base, directory = _incident_directory(mode)
        _write_record(base, directory, incident_id, record)
        return IncidentReceipt(incident_id, True)
    except (ValueError, UnicodeError, TypeError, AttributeError):
        return IncidentReceipt(incident_id, False, "invalid_evidence")
    except OSError:
        return IncidentReceipt(incident_id, False, "write_failed")
    except Exception:
        # Quarantine is optional diagnostics, not another tool failure path.
        return IncidentReceipt(incident_id, False, "unexpected_error")
