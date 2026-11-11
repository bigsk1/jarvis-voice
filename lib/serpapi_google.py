"""General Google search and bounded local inspection of retained responses."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from config_loader import get_config_value
from external_results import make_external_result_data
from serpapi_client import parse_bool, request_serpapi
from serpapi_google_result import (
    DEFAULT_CONTEXT_CHARS,
    MAX_CONTEXT_CHARS,
    panel_inventory,
    project_google_result,
)
from stash_helper import StashFile, get_space, parse_stash_ref, resolve_file_path

GOOGLE_SEARCH_TIMEOUT = 90
_TOOL = "serpapi_google_search"
_RESERVED = frozenset({
    "engine", "api_key", "output", "async", "zero_trace", "json_restrictor",
    "q", "gl", "hl", "location", "uule", "device", "start", "safe", "no_cache",
    "tbs", "kgmid",
})


def _integer(value: Any, name: str, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"'{name}' must be an integer from {minimum} to {maximum}.")
    return value


def _text(value: Any, name: str, maximum: int, *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"'{name}' must be text.")
    value = value.strip()
    if len(value) > maximum or (required and not value):
        raise ValueError(f"'{name}' must be {'nonempty text, ' if required else ''}at most {maximum} characters.")
    return value


def build_search_params(arguments: dict) -> tuple[dict, str]:
    query = _text(arguments.get("query"), "query", 1500, required=True)
    params: dict[str, Any] = {"engine": "google", "q": query}
    for name, provider_name, default in (("country", "gl", "us"), ("language", "hl", "en")):
        text = _text(arguments.get(name, default), name, 20).lower()
        pattern = r"[a-z]{2}" if name == "country" else r"[a-z]{2,3}(?:-[a-z]{2,8})?"
        if not re.fullmatch(pattern, text):
            raise ValueError(f"Invalid '{name}' code.")
        params[provider_name] = text
    device = arguments.get("device", "desktop")
    if device not in ("desktop", "tablet", "mobile"):
        raise ValueError("'device' must be desktop, tablet, or mobile.")
    params["device"] = device
    params["start"] = _integer(arguments.get("start"), "start", 0, 0, 10000)
    safe = arguments.get("safe", "active")
    if safe not in ("active", "off"):
        raise ValueError("'safe' must be active or off.")
    params["safe"] = safe
    params["no_cache"] = "true" if parse_bool(arguments.get("no_cache", False)) else "false"
    extra = arguments.get("extra_params") or {}
    if not isinstance(extra, dict) or len(extra) > 30:
        raise ValueError("'extra_params' must be an object with at most 30 Google parameters.")
    for key, value in extra.items():
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key):
            raise ValueError("Advanced Google parameter names must be simple parameter names.")
        if key.lower() in _RESERVED:
            raise ValueError(f"'{key}' cannot be overridden through extra_params; use its named argument when available.")
        if not isinstance(value, (str, int, float, bool)) or len(str(value)) > 2000:
            raise ValueError(f"Advanced Google parameter '{key}' must be a scalar of at most 2000 characters.")
        if isinstance(value, float) and not (-float("inf") < value < float("inf")):
            raise ValueError("Advanced Google parameters must be finite.")
        params[key] = value
    if params.get("tbm") and params.get("udm"):
        raise ValueError("Google parameters tbm and udm cannot be combined.")
    location = _text(arguments.get("location"), "location", 200)
    uule = _text(arguments.get("uule"), "uule", 500)
    if location and (uule or "lat" in extra or "lon" in extra):
        raise ValueError("'location' cannot be combined with uule or coordinates.")
    if uule and ("lat" in extra or "lon" in extra):
        raise ValueError("'uule' cannot be combined with coordinates.")
    if ("lat" in extra) != ("lon" in extra):
        raise ValueError("Google coordinates require both lat and lon.")
    origin = "explicit" if location else "explicit_uule" if uule else "coordinates" if "lat" in extra else "none"
    if not location and not uule and "lat" not in extra and params["gl"] == "us":
        for name in ("JARVIS_DEFAULT_LOCATION", "JARVIS_DEFAULT_POSTAL_CODE"):
            configured = get_config_value(name, "")
            if configured:
                location = _text(configured, name, 200)
                origin = name.lower()
                break
    if location:
        params["location"] = location
    if uule:
        params["uule"] = uule
    for key in ("tbs", "kgmid"):
        text = _text(arguments.get(key), key, 1000)
        if text:
            params[key] = text
    return params, origin


def _result_metadata(payload: dict) -> dict:
    params = payload.get("search_parameters")
    params = params if isinstance(params, dict) else {}
    metadata = payload.get("search_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    pagination = payload.get("serpapi_pagination")
    pagination = pagination if isinstance(pagination, dict) else {}
    next_start = None
    next_link = pagination.get("next") or pagination.get("next_link")
    if isinstance(next_link, str):
        start = parse_qs(urlparse(next_link).query).get("start", [])
        if start and start[0].isdigit():
            next_start = int(start[0])
    return {
        "kind": "google_search", "query": params.get("q", ""),
        "search_url": metadata.get("google_url"),
        "searched_at": metadata.get("processed_at") or metadata.get("created_at"),
        "request": {key: params.get(native) for key, native in (
            ("country", "gl"), ("language", "hl"), ("location", "location_requested"), ("device", "device"),
        )},
        "pagination": {"has_more": next_start is not None, "next_start": next_start},
    }


def _read_payload(raw_ref: str) -> dict:
    # Accept canonical artifacts only, not local paths, arbitrary URLs, or traversal.
    if not re.fullmatch(r"stash://[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", raw_ref):
        raise ValueError("'raw_ref' must be the exact stash:// reference returned by a Google search.")
    space_id, file_id = parse_stash_ref(raw_ref)
    saved = StashFile(get_space(space_id), file_id=file_id)
    if not saved.meta or saved.meta.get("tool_origin") != f"serpapi:{_TOOL}":
        raise ValueError("The retained artifact is not a serpapi_google_search response.")
    path = Path(resolve_file_path(stash_ref=raw_ref))
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("The retained Google response exceeds the 50 MiB inspection limit; use Stash tools.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("The retained Google response is not a JSON object.")
    return payload


def _select_pointer(payload: Any, pointer: str) -> Any:
    if not pointer:
        return payload
    if not pointer.startswith("/") or re.search(r"~(?![01])", pointer):
        raise ValueError("'path' must be a JSON Pointer, such as /available_on or /knowledge_graph/description.")
    current = payload
    for encoded in pointer.split("/")[1:]:
        key = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and re.fullmatch(r"0|[1-9][0-9]*", key) and int(key) < len(current):
            current = current[int(key)]
        else:
            raise ValueError("The requested JSON Pointer does not exist in this retained response; inspect its panel inventory.")
    return current


def run_google_search(arguments: dict) -> dict:
    action = arguments.get("action", "search")
    if action not in ("search", "read_result"):
        raise ValueError("'action' must be search or read_result.")
    limit = _integer(arguments.get("limit"), "limit", 10, 1, 50)
    max_chars = _integer(arguments.get("max_chars"), "max_chars", DEFAULT_CONTEXT_CHARS, 2000, MAX_CONTEXT_CHARS)
    if action == "search":
        for field in ("raw_ref", "path", "offset"):
            if field in arguments:
                raise ValueError(f"'{field}' belongs to action=read_result; use start for another paid search page.")
        params, location_source = build_search_params(arguments)
        payload = request_serpapi(params, timeout=GOOGLE_SEARCH_TIMEOUT,
                                  use_proxy=False, fallback_on_proxy_fail=False)
        if not isinstance(payload, dict):
            raise ValueError("SerpApi returned a non-object response.")
        result = _result_metadata(payload)
        # SerpApi may omit an echoed parameter; retain the actual submitted request.
        result["query"] = params["q"]
        result["request"] = {key: params.get(native) for key, native in (
            ("country", "gl"), ("language", "hl"), ("location", "location"), ("device", "device"),
        )}
        result["location_source"] = location_source
        result["panels"] = panel_inventory(payload, limit=limit)
        result["panels_count"] = len(result["panels"])
        result["inventory_complete"] = True
        raw_ref = None
    else:
        if any(field in arguments for field in (
            "query", "country", "language", "location", "uule", "device", "start",
            "safe", "no_cache", "tbs", "kgmid", "extra_params",
        )):
            raise ValueError("read_result inspects saved data; pass raw_ref, path, offset, limit and max_chars only.")
        raw_ref = _text(arguments.get("raw_ref"), "raw_ref", 1000, required=True)
        pointer = arguments.get("path", "")
        if not isinstance(pointer, str) or len(pointer) > 2000:
            raise ValueError("'path' must be a JSON Pointer of at most 2000 characters.")
        offset = _integer(arguments.get("offset"), "offset", 0, 0, 100000000)
        payload = _read_payload(raw_ref)
        selected = _select_pointer(payload, pointer)
        result = _result_metadata(payload)
        all_panels = panel_inventory(payload, limit=limit)
        result["section_inventory"] = [{key: value for key, value in panel.items()
                                        if key in {"key", "path", "type", "count"}}
                                       for panel in all_panels]
        result["panels_count"] = len(all_panels)
        result["inventory_complete"] = True
        if not pointer:
            result["panels"] = all_panels[offset:offset + limit]
            total = len(all_panels)
            count = len(result["panels"])
            result["panels_count"] = total
        else:
            total = len(selected) if isinstance(selected, (list, dict, str)) else 1
            if isinstance(selected, list):
                preview = selected[offset:offset + limit]
            elif isinstance(selected, dict):
                preview = dict(list(selected.items())[offset:offset + limit])
            elif isinstance(selected, str):
                preview = selected[offset:]
            else:
                preview = selected if offset == 0 else None
            count = len(preview) if isinstance(preview, (list, dict, str)) else int(offset == 0)
            key = pointer.split("/")[-1].replace("~1", "/").replace("~0", "~")
            result["panels"] = [{
                "key": key, "path": pointer,
                "type": "array" if isinstance(selected, list) else "object" if isinstance(selected, dict) else "scalar",
                "count": total, "preview": preview,
                "preview_count": count, "truncated": offset > 0 or count < total,
            }]
            if offset > 0 and not isinstance(selected, (list, dict, str)):
                result["panels"][0].pop("preview", None)
            graph = payload.get("knowledge_graph")
            if isinstance(graph, dict) and not pointer.startswith("/knowledge_graph"):
                entity = {key: graph[key] for key in ("title", "type", "kgmid") if key in graph}
                if entity:
                    result["panels"].append({"key": "knowledge_graph", "path": "/knowledge_graph",
                                             "type": "object", "count": len(graph), "preview": entity,
                                             "preview_count": len(entity), "truncated": len(entity) < len(graph)})
        result.update({"selected_path": pointer, "offset": offset, "returned_count": count,
                       "has_more": offset + count < total,
                       "next_offset": offset + count if offset + count < total else None})
    metadata = payload.get("search_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    data = make_external_result_data(
        provider="serpapi", tool=_TOOL,
        execution={"action": action, "engine": "google", "search_id": metadata.get("id"),
                   "status": metadata.get("status"), "serpapi_searches_used": int(action == "search")},
        result=result, raw_payload=payload, raw_ref=raw_ref,
        limits={"context_max_chars": max_chars}, max_chars=max_chars,
    )
    data = project_google_result(data, max_chars=max_chars)
    names = [panel["key"] for panel in data["result"].get("panels", [])
             if panel["key"] not in {"search_metadata", "search_parameters", "search_information", "pagination", "serpapi_pagination"}]
    speech = (f"Google returned {', '.join(names) or 'no content panels'} for {data['result'].get('query', '')}."
              if action == "search" else "Read the requested section from the saved Google response; no new search was made.")
    speech += " Use read_result with raw_ref and a panel path for omitted details."
    if data.get("limits", {}).get("raw_retention_error"):
        speech += " Saving the full response failed; do not repeat the paid search automatically."
    return {"ok": True, "speech": speech, "data": data}
