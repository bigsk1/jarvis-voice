"""Pure, loss-aware projections of retained Google search responses.

The native response stays in Stash. These projections describe what is present
and which exact JSON Pointer can recover evidence omitted from a preview.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

DEFAULT_CONTEXT_CHARS = 20000
MAX_CONTEXT_CHARS = 60000
_PRIORITY = {
    "available_on": 5, "flight_result": 5, "answer_box": 4,
    "knowledge_graph": 4, "organic_results": 5, "ai_overview": 3,
    "local_results": 3, "top_stories": 2,
}
_IDENTITY_KEYS = (
    "title", "name", "type", "kgmid", "flight_designator", "airline", "date",
    "price", "link", "url", "snippet", "description", "status", "metadata",
    "departure_airport", "arrival_airport", "dates", "available_dates",
)


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def is_google_result(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    data = value.get("data") if isinstance(value.get("data"), dict) else value
    source = data.get("source")
    result = data.get("result")
    return (
        data.get("contract") == "external_result_v1"
        and isinstance(source, dict) and source.get("provider") == "serpapi"
        and source.get("tool") == "serpapi_google_search"
        and isinstance(result, dict) and result.get("kind") == "google_search"
    )


def google_context_budget(value: Any, default: int = DEFAULT_CONTEXT_CHARS) -> int:
    data = value.get("data", value) if isinstance(value, dict) else {}
    limits = data.get("limits", {}) if isinstance(data, dict) else {}
    budget = limits.get("context_max_chars", default) if isinstance(limits, dict) else default
    if isinstance(budget, bool) or not isinstance(budget, int):
        budget = default
    return max(2000, min(MAX_CONTEXT_CHARS, budget))


def pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def preview_value(value: Any, budget: int, *, item_limit: int = 10,
                  preserve_order: bool = False) -> tuple[Any, bool]:
    """Fit complete JSON values; URLs and dictionary keys are never sliced."""
    if budget < 4:
        return None, True
    if len(json_text(value)) <= budget and not (
        isinstance(value, list) and len(value) > item_limit
    ):
        return deepcopy(value), False
    if isinstance(value, str):
        if value.startswith(("https://", "http://", "stash://")):
            return None, True
        low, high = 0, len(value)
        while low < high:
            middle = (low + high + 1) // 2
            if len(json_text(value[:middle])) <= budget:
                low = middle
            else:
                high = middle - 1
        return value[:low], low < len(value)
    if isinstance(value, list):
        rows: list[Any] = []
        truncated = len(value) > item_limit
        candidates = value[:item_limit]
        for index, child in enumerate(candidates):
            remaining = budget - len(json_text(rows)) - (1 if rows else 0)
            share = max(4, remaining // max(1, len(candidates) - index))
            preview, shortened = preview_value(child, share, item_limit=item_limit,
                                               preserve_order=preserve_order)
            if len(json_text([*rows, preview])) > budget:
                truncated = True
                break
            if preview is None and child is not None and shortened:
                truncated = True
                break
            rows.append(preview)
            truncated |= shortened
        return rows, truncated or len(rows) != len(value)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        truncated = False
        keys = list(value) if preserve_order else sorted(value, key=lambda key: (
            _IDENTITY_KEYS.index(key) if key in _IDENTITY_KEYS else len(_IDENTITY_KEYS)
        ))
        for key in keys:
            remaining = budget - len(json_text(result)) - len(json_text(key)) - 2
            if remaining < 4:
                truncated = True
                if preserve_order:
                    break
                continue
            preview, shortened = preview_value(value[key], remaining, item_limit=item_limit,
                                               preserve_order=preserve_order)
            if preview is None and value[key] is not None and shortened:
                truncated = True
                if preserve_order:
                    break
                continue
            candidate = {**result, key: preview}
            if len(json_text(candidate)) > budget:
                truncated = True
                if preserve_order:
                    break
                continue
            result[key] = preview
            truncated |= shortened
        return result, truncated or len(result) != len(value)
    return None, True


def panel_inventory(payload: dict, *, limit: int = 10) -> list[dict]:
    """Include every native top-level section, including unfamiliar sections."""
    panels = []
    for key, value in payload.items():
        kind = "array" if isinstance(value, list) else "object" if isinstance(value, dict) else "scalar"
        preview, truncated = preview_value(value, 24000, item_limit=limit)
        panel = {
            "key": key, "path": "/" + pointer_token(key), "type": kind,
            "count": len(value) if isinstance(value, (dict, list)) else 1,
            "preview_count": len(preview) if isinstance(preview, (dict, list)) else 1,
            "truncated": truncated,
        }
        if preview is None and value is not None and truncated:
            panel["preview_count"] = 0
        else:
            panel["preview"] = preview
        panels.append(panel)
    return panels


def _read_cursor(data: dict) -> dict:
    result = data["result"]
    if "selected_path" not in result:
        return data
    pointer = result["selected_path"]
    panels = result.get("panels", [])
    if pointer == "":
        returned = len(panels)
        total = result.get("panels_count", returned)
    else:
        panel = next((item for item in panels if item.get("path") == pointer), {})
        preview = panel.get("preview")
        returned = len(preview) if isinstance(preview, (dict, list, str)) else int("preview" in panel)
        total = panel.get("count", returned)
    offset = result.get("offset", 0)
    more = offset + returned < total
    result.update({"returned_count": returned, "has_more": more,
                   "next_offset": offset + returned if more and returned else None})
    if more and not returned:
        data["limits"]["page_blocked_by_budget"] = True
    return data


def project_google_result(value: dict, *, max_chars: int = DEFAULT_CONTEXT_CHARS,
                          sample_limit: int | None = None) -> dict:
    """Keep section inventory and recovery identity before distributing previews.

Generic five-row sample limits do not apply: the tool's limit determines its
preview, and subsequent projections only reduce it when the real budget needs it.
"""
    del sample_limit
    if not is_google_result(value):
        return {}
    data = value.get("data", value)
    projected = json.loads(json_text({key: child for key, child in data.items() if key in {
        "contract", "source", "execution", "result", "artifacts", "raw_ref", "limits",
    }}))
    budget = max(256, min(MAX_CONTEXT_CHARS, int(max_chars)))
    panels = projected["result"].get("panels", [])
    if not isinstance(panels, list):
        panels = []
    projected["result"]["panels"] = panels
    projected.setdefault("limits", {}).setdefault("truncated", False)
    if any(panel.get("truncated") for panel in panels):
        projected["limits"]["truncated"] = True
    _read_cursor(projected)
    if len(json_text(projected)) <= budget:
        return projected

    originals = [deepcopy(panel) for panel in panels]
    for panel in panels:
        panel.pop("preview", None)
        panel["preview_count"] = 0
        panel["truncated"] = True
    projected["limits"]["truncated"] = True
    projected["limits"]["preview_budget_chars"] = budget
    projected["limits"]["read_tool"] = "serpapi_google_search"
    projected["limits"]["read_action"] = "read_result"
    base_size = len(json_text(projected))
    if base_size > budget:
        # Preserve compact, exact handles and a truthful inventory continuation.
        projected["artifacts"] = []
        for key in ("search_url", "request", "section_inventory"):
            if key == "section_inventory" and key in projected["result"]:
                projected["result"]["inventory_complete"] = False
            projected["result"].pop(key, None)
        if "query" in projected["result"]:
            query, shortened = preview_value(projected["result"]["query"], max(80, budget // 8))
            projected["result"]["query"] = query
            if shortened:
                projected["limits"]["query_truncated"] = True
        projected["limits"]["metadata_omitted"] = True
        page_count = len(panels)
        total = projected["result"].get("panels_count", page_count)
        inventory_offset = projected["result"].get("offset", 0) if projected["result"].get("selected_path") == "" else 0
        while panels and len(json_text(projected)) > budget:
            panels.pop()
        if len(panels) < page_count:
            projected["result"]["inventory_complete"] = False
            projected["result"]["panels_count"] = total
            projected["result"]["inventory_truncated"] = True
            projected["result"]["inventory_next_offset"] = inventory_offset + len(panels)
            while panels and len(json_text(projected)) > budget:
                panels.pop()
                projected["result"]["inventory_next_offset"] = inventory_offset + len(panels)
        _read_cursor(projected)
        if len(json_text(projected)) > budget:
            projected = {
                "contract": "external_result_v1", "source": projected["source"],
                "execution": {key: child for key, child in projected.get("execution", {}).items()
                              if key in {"action", "engine", "status", "serpapi_searches_used"}},
                "result": {"kind": "google_search", "panels": [], "panels_count": total,
                           "inventory_complete": False,
                           "inventory_truncated": True, "inventory_next_offset": 0},
                "artifacts": [], "raw_ref": projected.get("raw_ref"),
                "limits": {"truncated": True, "metadata_omitted": True,
                           "context_max_chars": google_context_budget(data)},
            }
            search_id = data.get("execution", {}).get("search_id")
            if search_id is not None and len(json_text(projected)) + len(json_text(search_id)) + 14 <= budget:
                projected["execution"]["search_id"] = search_id
            if data.get("limits", {}).get("raw_retention_error"):
                projected["limits"]["raw_retention_error"] = data["limits"]["raw_retention_error"]
        if len(json_text(projected)) > budget:
            raise ValueError("Google result recovery reference exceeds the context budget")
        return projected

    remaining = budget - base_size
    ordered = sorted(range(len(panels)), key=lambda i: -_PRIORITY.get(panels[i].get("key"), 1))
    total_weight = sum(_PRIORITY.get(panels[i].get("key"), 1) for i in ordered)
    for index in ordered:
        panel, original = panels[index], originals[index]
        weight = _PRIORITY.get(panel.get("key"), 1)
        allowance = max(0, remaining * weight // max(1, total_weight) - 20)
        before = len(json_text(panel))
        if "preview" in original and allowance >= 8:
            limit = max(1, original.get("preview_count", 10))
            preview, shortened = preview_value(
                original["preview"], allowance, item_limit=limit,
                preserve_order=panel.get("path") == projected["result"].get("selected_path"),
            )
            if not (preview is None and original["preview"] is not None and shortened):
                panel["preview"] = preview
                panel["preview_count"] = len(preview) if isinstance(preview, (dict, list)) else 1
            panel["truncated"] = bool(original.get("truncated") or shortened)
        remaining -= max(0, len(json_text(panel)) - before)
        total_weight -= weight
    # Escaping/boolean-size overhead must never produce an invalid cut JSON blob.
    _read_cursor(projected)
    while len(json_text(projected)) > budget:
        candidates = [panel for panel in reversed(panels) if "preview" in panel]
        if not candidates:
            raise ValueError("Google result recovery metadata exceeds the context budget")
        panel = candidates[0]
        panel.pop("preview")
        panel["preview_count"] = 0
        panel["truncated"] = True
        _read_cursor(projected)
    return projected
