"""Versioned, provider-neutral results and deterministic context projections.

The retained response is authoritative. Projections preserve provider handles
before reducing samples, and never turn nested JSON into a serialized fragment.
This module does not run a model, retrieve another page, or repeat an operation.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from copy import deepcopy
from typing import Any

CONTRACT = "external_result_v1"
_MISSING = object()
_SAMPLE_KEYS = ("sample_items", "items")
_VALUE_KEYS = ("value", "text", *_SAMPLE_KEYS)
_HANDLE_KEYS = frozenset({
    "id", "ref", "url", "uri", "status", "state", "cursor", "next_cursor",
    "nextCursor", "pagination_token", "next_page_token", "continuation_token",
})
_MAX_SAFE_JAVASCRIPT_INTEGER = (1 << 53) - 1
_ENVELOPE_FIELDS = frozenset({
    "contract", "source", "execution", "result", "artifacts", "raw_ref", "limits", "schema",
})


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("External result must contain finite JSON") from exc


def _json_copy(value: Any) -> Any:
    """Validate and detach JSON, rejecting keys JSON would silently coerce."""
    def validate_keys(item: Any) -> None:
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("External result object keys must be strings")
            for child in item.values():
                validate_keys(child)
        elif isinstance(item, list):
            for child in item:
                validate_keys(child)
        elif item is not None and not isinstance(item, (str, bool, int, float)):
            raise ValueError("External result must contain JSON values")

    try:
        validate_keys(value)
        return json.loads(_json_text(value))
    except RecursionError as exc:
        raise ValueError("External result exceeds JSON nesting limits") from exc


def is_external_result(value: Any) -> bool:
    """Recognize only the explicit contract, including normal tool wrappers."""
    if not isinstance(value, dict):
        return False
    payload = value.get("data") if isinstance(value.get("data"), dict) else value
    return (
        payload.get("contract") == CONTRACT
        and isinstance(payload.get("source"), dict)
        and isinstance(payload.get("result"), dict)
    )


def _handle_key(key: str) -> bool:
    return key in _HANDLE_KEYS or key.lower().endswith((
        "_id", "_ref", "_url", "_uri", "_cursor", "_token", "id", "cursor",
    ))


def _encode_unsafe_integers(value: Any, paths: list[str], path: str = "") -> Any:
    """Make display JSON lossless across ordinary browser JSON parsers."""
    if type(value) is int and abs(value) > _MAX_SAFE_JAVASCRIPT_INTEGER:
        paths.append(path)
        return str(value)
    if isinstance(value, dict):
        return {
            key: _encode_unsafe_integers(
                child, paths, f"{path}/{key.replace('~', '~0').replace('/', '~1')}",
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_encode_unsafe_integers(child, paths, f"{path}/{index}")
                for index, child in enumerate(value)]
    return value


def _compact_value(
    value: Any,
    *,
    depth: int,
    fields: int,
    items: int,
    string_chars: int,
    path: str,
    omitted: list[str],
    key: str = "",
) -> Any:
    def mark() -> None:
        if path not in omitted:
            omitted.append(path)

    if isinstance(value, str):
        if (_handle_key(key) or value.startswith(("stash://", "https://", "http://"))
                or (len(value) > 16 and value.lstrip("-").isdigit())):
            return value
        if len(value) > string_chars:
            mark()
            return value[:string_chars] + " [preview truncated]"
        return value
    if isinstance(value, (dict, list)) and depth <= 0:
        if value:
            mark()
        return {} if isinstance(value, dict) else []
    if isinstance(value, dict):
        keys = sorted(value, key=lambda field: not _handle_key(field))
        if len(keys) > fields:
            mark()
        compact = {}
        for field in keys[:fields]:
            escaped = field.replace("~", "~0").replace("/", "~1")
            compact[field] = _compact_value(
                value[field], depth=depth - 1, fields=fields, items=items,
                string_chars=string_chars, path=f"{path}/{escaped}", omitted=omitted, key=field,
            )
        return compact
    if isinstance(value, list):
        if len(value) > items:
            mark()
        return [
            _compact_value(
                child, depth=depth - 1, fields=fields, items=items,
                string_chars=string_chars, path=f"{path}/{index}", omitted=omitted,
            )
            for index, child in enumerate(value[:items])
        ]
    return value


def _mark_limits(data: dict, paths: list[str], *, sample_truncated: bool = False) -> None:
    limits = data.setdefault("limits", {})
    if paths or sample_truncated:
        limits["truncated"] = True
    if paths:
        existing = limits.get("truncated_paths", [])
        combined = list(dict.fromkeys([*(existing if isinstance(existing, list) else []), *paths]))
        limits["truncated_paths"] = combined[:12]
        limits["truncated_paths_count"] = max(
            int(limits.get("truncated_paths_count", 0)), len(combined),
        )
    if sample_truncated:
        limits["sample_truncated"] = True


def _sample_count(data: dict) -> None:
    result = data["result"]
    for key in _SAMPLE_KEYS:
        if isinstance(result.get(key), list):
            result["sample_count"] = len(result[key])
            return
    if "sample_count" in result:
        result["sample_count"] = 0


def project_external_result(
    value: dict,
    *,
    max_chars: int = 6000,
    sample_limit: int = 5,
) -> dict:
    """Return bounded strict JSON, keeping exact metadata before sample data.

    Complete/total/returned counts describe provider evidence and are never
    inferred from a preview. sample_count describes retained preview rows.
    Exceptionally large metadata is omitted whole with an explicit marker;
    opaque IDs, URLs and cursors are never shortened into unusable values.
    """
    if not is_external_result(value):
        return {}
    if max_chars < 256:
        raise ValueError("External result context budget must be at least 256 characters")
    payload = value.get("data") if isinstance(value.get("data"), dict) else value
    integer_paths = []
    # Tool wrappers can acquire unrelated diagnostic/config fields later.
    # Replay only the versioned contract; arbitrary Actor data belongs inside
    # result, where its original structure is retained.
    validated = _json_copy(payload)
    original = _encode_unsafe_integers(
        {key: child for key, child in validated.items() if key in _ENVELOPE_FIELDS},
        integer_paths,
    )
    projected = deepcopy(original)
    projected.setdefault("limits", {}).setdefault("truncated", False)
    if integer_paths:
        projected["limits"]["integer_strings"] = True
        projected["limits"]["integer_string_paths"] = integer_paths[:8]
        projected["limits"]["integer_string_paths_count"] = len(integer_paths)
        if any(path.startswith("/schema/") for path in integer_paths):
            # Changing numeric schema constraints would produce an invalid
            # declared schema. Refer to the intact retained schema instead.
            projected.pop("schema", None)
            projected["limits"]["schema_omitted"] = True
            _mark_limits(projected, ["/schema"])
    sample_limit = max(0, int(sample_limit))
    omitted = []
    for key in _SAMPLE_KEYS:
        rows = projected["result"].get(key)
        if isinstance(rows, list) and len(rows) > sample_limit:
            projected["result"][key] = rows[:sample_limit]
            omitted.append(f"/result/{key}")
    _sample_count(projected)
    _mark_limits(projected, omitted, sample_truncated=bool(omitted))
    if len(_json_text(projected)) <= max_chars:
        return projected

    # Declared schemas remain valid whole schemas. A partial schema is not a
    # trustworthy replacement; the retained response still holds the original.
    if "schema" in projected:
        projected.pop("schema")
        _mark_limits(projected, ["/schema"])
        projected["limits"]["schema_omitted"] = True
        if len(_json_text(projected)) <= max_chars:
            return projected

    sampled = deepcopy(projected)
    for depth, fields, items, string_chars in ((8, 30, 12, 1200), (6, 18, 8, 500), (4, 10, 4, 160)):
        candidate = deepcopy(sampled)
        paths = []
        for key in _VALUE_KEYS:
            if key in candidate["result"]:
                candidate["result"][key] = _compact_value(
                    sampled["result"][key], depth=depth, fields=fields, items=items,
                    string_chars=string_chars, path=f"/result/{key}", omitted=paths, key=key,
                )
        _sample_count(candidate)
        _mark_limits(candidate, paths, sample_truncated=any(
            path.startswith(("/result/items", "/result/sample_items")) for path in paths
        ))
        projected = candidate
        if len(_json_text(projected)) <= max_chars:
            return projected

    # Drop entire rows instead of cutting identifiers or deduplicating rows.
    for key in _SAMPLE_KEYS:
        rows = projected["result"].get(key)
        if not isinstance(rows, list):
            continue
        while rows and len(_json_text(projected)) > max_chars:
            rows.pop()
            _sample_count(projected)
            _mark_limits(projected, [f"/result/{key}"], sample_truncated=True)
    for key in ("value", "text"):
        if len(_json_text(projected)) <= max_chars:
            return projected
        if key in projected["result"]:
            projected["result"].pop(key)
            _mark_limits(projected, [f"/result/{key}"])
    if len(_json_text(projected)) <= max_chars:
        return projected

    # Detailed path lists are useful but expendable; the fact/count of omitted
    # evidence remains visible when keeping paths would crowd out native IDs.
    projected["limits"].pop("truncated_paths", None)
    projected["limits"].pop("integer_string_paths", None)
    if len(_json_text(projected)) <= max_chars:
        return projected

    # Optional metadata can be arbitrary provider JSON too. Preserve direct
    # handles/status/counts first. Never serialize a cut-off JSON fragment.
    for section in ("execution", "result"):
        metadata = projected.get(section, {})
        for key in list(metadata):
            if _handle_key(key) or key in {
                "kind", "complete", "total_items", "returned_count", "sample_count",
                "offset", "limit", "pagination", "has_more", "next_offset",
            }:
                continue
            metadata.pop(key)
            _mark_limits(projected, [f"/{section}/{key}"])
            if len(_json_text(projected)) <= max_chars:
                return projected
    if projected.get("artifacts"):
        projected["artifacts"] = []
        _mark_limits(projected, ["/artifacts"])
        if len(_json_text(projected)) <= max_chars:
            return projected

    # A long continuation cursor is useful for paging, but recovery identity
    # takes precedence. Omit the complete pagination record and point back to
    # the retained response; a shortened cursor must never be reused.
    if "pagination" in projected["result"]:
        projected["result"].pop("pagination")
        _mark_limits(projected, ["/result/pagination"])
        projected["limits"]["metadata_omitted"] = True
        if len(_json_text(projected)) <= max_chars:
            return projected

    # A pathological opaque handle may itself exceed the entire budget. Keep
    # the exact archive reference and explicitly require reading that record.
    minimal = {
        "contract": CONTRACT,
        "source": {key: item for key, item in projected["source"].items()
                   if key in {"provider", "tool", "mode"}},
        "execution": {}, "result": {"kind": projected["result"].get("kind", "object")},
        "artifacts": [], "raw_ref": projected.get("raw_ref"),
        "limits": {"truncated": True, "metadata_omitted": True,
                   **({"integer_strings": True} if projected["limits"].get("integer_strings") else {})},
    }
    if len(_json_text(minimal)) > max_chars:
        raise ValueError("External result reference metadata exceeds the context budget")
    return minimal


def make_external_result_data(
    *,
    provider: str,
    tool: str,
    execution: dict | None = None,
    result: dict | None = None,
    artifacts: list[dict] | None = None,
    raw_payload: Any = _MISSING,
    raw_ref: str | None = None,
    limits: dict | None = None,
    stash_raw: bool = True,
    stash_space_id: str | None = None,
    schema: dict | None = None,
    mode: str | None = None,
) -> dict:
    """Build a tool's data envelope and retain one complete response in Stash.

    Passing raw_ref reuses an existing archive and never writes another copy.
    Projection calls are pure. A retention failure is explicit and does not
    turn a successful provider operation into a request to execute it again.
    """
    if not isinstance(provider, str) or not provider or not isinstance(tool, str) or not tool:
        raise ValueError("External results require provider and tool names")
    if execution is not None and not isinstance(execution, dict):
        raise ValueError("External execution must be an object")
    if result is not None and not isinstance(result, dict):
        raise ValueError("External result must be an object")
    if artifacts is not None and (
        not isinstance(artifacts, list) or any(not isinstance(item, dict) for item in artifacts)
    ):
        raise ValueError("External artifacts must be an array of objects")
    if limits is not None and not isinstance(limits, dict):
        raise ValueError("External limits must be an object")
    try:
        from config_loader import config_scope, get_active_config_mode
    except ModuleNotFoundError:
        from lib.config_loader import config_scope, get_active_config_mode
    selected_mode = get_active_config_mode(mode)
    data = _json_copy({
        "contract": CONTRACT,
        "source": {"provider": provider, "tool": tool, "mode": selected_mode},
        "execution": execution or {},
        "result": result if result is not None else {"kind": "object"},
        "artifacts": artifacts or [],
        "raw_ref": raw_ref,
        "limits": {"truncated": False, **(limits or {})},
        **({"schema": schema} if schema is not None else {}),
    })
    if not isinstance(data["execution"], dict) or not isinstance(data["result"], dict):
        raise ValueError("External execution and result must be objects")
    if not isinstance(data["artifacts"], list) or not isinstance(data["limits"], dict):
        raise ValueError("External artifacts and limits have invalid types")
    archive = _json_text(data if raw_payload is _MISSING else _json_copy(raw_payload)).encode("utf-8")
    if stash_raw and raw_ref is None:
        try:
            try:
                from stash_helper import StashFile, open_space
            except ModuleNotFoundError:
                from lib.stash_helper import StashFile, open_space
            scope = (nullcontext() if selected_mode == get_active_config_mode()
                     else config_scope(selected_mode))
            with scope:
                space, _created = open_space(
                    space_id=stash_space_id, labels=["external_result", provider], scope="session",
                )
                saved = StashFile(space).save_binary(
                    archive, name="external-response.json", mime_type="application/json",
                    on_conflict="version", tool_origin=f"{provider}:{tool}",
                )
            data["raw_ref"] = saved["ref"]
            data["artifacts"].append({
                key: saved[key] for key in (
                    "ref", "file_id", "name", "mime_type", "size_bytes", "hash_sha256",
                )
            } | {"space_id": space.space_id, "mode": selected_mode, "role": "raw_response"})
        except (ImportError, OSError, ValueError, TimeoutError) as exc:
            data["limits"]["raw_retention_error"] = type(exc).__name__
    return project_external_result(data, max_chars=48000, sample_limit=20)


def external_result_from_mcp(
    provider: str,
    tool: str,
    response: dict,
    *,
    output_schema: dict | None = None,
    stash_raw: bool = True,
) -> dict:
    """Represent an opted-in MCP response without interpreting Actor fields."""
    blocks = response.get("content", [])
    if "structuredContent" in response:
        value = response["structuredContent"]
    else:
        texts = [item.get("text") for item in blocks
                 if isinstance(item, dict) and item.get("type") == "text"
                 and isinstance(item.get("text"), str)]
        value = texts[0] if len(texts) == 1 and len(blocks) == 1 else blocks
        if isinstance(value, str):
            try:
                def invalid_constant(_constant: str) -> None:
                    raise ValueError("Non-finite JSON")
                value = json.loads(value, parse_constant=invalid_constant)
            except (json.JSONDecodeError, ValueError):
                pass
    if isinstance(value, list):
        result = {"kind": "array", "items": value, "returned_count": len(value),
                  "total_items": None, "complete": None}
    elif isinstance(value, dict):
        result = {"kind": "object", "value": value}
    elif isinstance(value, str):
        result = {"kind": "text", "text": value}
    else:
        result = {"kind": "scalar", "value": value}
    return make_external_result_data(
        provider=provider, tool=tool, result=result,
        execution={"mcp_is_error": response.get("isError") is True},
        raw_payload={"response": response, **({"output_schema": output_schema}
                                             if output_schema is not None else {})},
        schema=output_schema, stash_raw=stash_raw,
    )
