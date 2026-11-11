"""Pure Google-result context budgeting shared by orchestration and Web.

The search archive owns the evidence. Replaying a read keeps its exact archive
and JSON pointer, rather than starting another billed search or slicing JSON.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

try:
    from external_results import project_external_result
    from serpapi_google_result import google_context_budget, is_google_result
except ModuleNotFoundError as exc:
    if exc.name not in {"external_results", "serpapi_google_result"}:
        raise
    from lib.external_results import project_external_result
    from lib.serpapi_google_result import google_context_budget, is_google_result


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def google_runs(value: Any) -> list[dict]:
    """Recognize only canonical envelopes or the saved repeated-run wrapper."""
    if is_google_result(value):
        return [value]
    rows = value if isinstance(value, list) else value.get("results", []) if isinstance(value, dict) else []
    if not isinstance(rows, list):
        return []
    runs = []
    for row in rows:
        if is_google_result(row):
            runs.append(row)
        elif isinstance(row, dict) and isinstance(row.get("results"), list):
            runs.extend(child for child in row["results"] if is_google_result(child))
    return runs


def google_runs_budget(value: Any) -> int:
    return max((google_context_budget(row) for row in google_runs(value)), default=0)


def project_google_runs(value: Any, *, max_chars: int | None = None) -> dict:
    """Keep one latest preview per archive and a bounded exact read manifest.

    Reads of the same archive already include its search identity and panel
    inventory, so repeating older copies of that inventory wastes evidence room.
    Different JSON-pointer pages remain recoverable through their receipts.
    """
    runs = google_runs(value)
    if not runs:
        return {}
    budget = max_chars if max_chars is not None else google_runs_budget(runs)
    unique = {}
    reads = {}
    wrappers = value if isinstance(value, list) else [value]
    for wrapper in wrappers:
        if not isinstance(wrapper, dict):
            continue
        for receipt in wrapper.get("retained_reads", []):
            if not isinstance(receipt, dict) or not isinstance(receipt.get("raw_ref"), str):
                continue
            detached = {key: receipt[key] for key in (
                "mode", "raw_ref", "selected_path", "offset", "returned_count", "has_more", "next_offset",
            ) if key in receipt}
            identity = ((receipt.get("mode"), receipt["raw_ref"]), "selected_path" in receipt,
                        receipt.get("selected_path"), receipt.get("offset"))
            reads[identity] = detached
    for index, run in enumerate(runs):
        data = run.get("data", run)
        result = data["result"]
        archive = (data.get("source", {}).get("mode"), data.get("raw_ref") or index)
        unique[archive] = (index, run)
        receipt = {"raw_ref": data.get("raw_ref"), "mode": data.get("source", {}).get("mode"), **{
            key: result[key] for key in (
                "selected_path", "offset", "returned_count", "has_more", "next_offset",
            ) if key in result
        }}
        identity = (archive, "selected_path" in result, result.get("selected_path"), result.get("offset"))
        reads[identity] = receipt
    selected = [run for _, run in sorted(unique.values(), key=lambda row: row[0])[-3:]]
    if len(selected) == 1 and len(reads) == 1:
        return project_external_result(selected[0], max_chars=budget)
    manifest = list(reads.values())[-20:]
    wrapper = {"runs_count": len(runs), "results": [],
               "results_truncated": len(unique) > len(selected),
               "retained_reads": manifest, "retained_reads_count": len(reads),
               "retained_reads_truncated": len(reads) > len(manifest)}
    while manifest and len(_json(wrapper)) > budget // 4:
        manifest.pop(0)
        wrapper["retained_reads_truncated"] = True
    # Older archives keep a structural receipt; the latest evidence gets the
    # remaining room. Nothing shares the unrelated generic 6K follow-up cap.
    remaining = budget - len(_json(wrapper)) - 128 * len(selected)
    projected = []
    for index, run in enumerate(selected):
        allowance = remaining if index == len(selected) - 1 else min(1200, remaining // 4)
        try:
            projection = project_external_result(run, max_chars=max(256, allowance))
        except ValueError:
            # A previous archive's long query or JSON pointer must not erase
            # the latest useful result. Omit that metadata whole, retaining the
            # exact archive handle for a subsequent read.
            data = run.get("data", run)
            projection = {
                "contract": "external_result_v1", "source": deepcopy(data["source"]),
                "execution": {}, "result": {"kind": "google_search"}, "artifacts": [],
                "raw_ref": data.get("raw_ref"),
                "limits": {"truncated": True, "metadata_omitted": True},
            }
            if len(_json(projection)) > allowance:
                raise
        projected.append(projection)
        remaining -= len(_json(projection))
        result = projection["result"]
        if "selected_path" in result:
            for receipt in manifest:
                if (receipt.get("raw_ref") == projection.get("raw_ref")
                        and receipt.get("mode") == projection["source"].get("mode")
                        and receipt.get("selected_path") == result["selected_path"]
                        and receipt.get("offset") == result.get("offset")):
                    for key in ("returned_count", "has_more", "next_offset"):
                        if key in result:
                            receipt[key] = result[key]
    wrapper["results"] = projected
    return wrapper


def google_workflow_receipt(value: Any, *, max_chars: int) -> dict:
    """Keep usable read handles within a workflow's deliberately small step cap."""
    runs = google_runs(value)
    if not runs:
        return {}
    data = runs[-1].get("data", runs[-1])
    result = data["result"]
    panels = result.get("section_inventory")
    if not isinstance(panels, list):
        panels = result.get("panels", [])
    receipt = {
        "raw_ref": data.get("raw_ref"), "read_tool": "serpapi_google_search",
        "read_action": "read_result", "context_truncated": True,
        "panel_count": result.get("panels_count", len(panels)),
        "panel_keys": [panel["key"] for panel in panels
                       if isinstance(panel, dict) and isinstance(panel.get("key"), str)],
        **{key: result[key] for key in ("selected_path", "offset", "next_offset") if key in result},
    }
    while receipt["panel_keys"] and len(_json(receipt)) > max_chars:
        receipt["panel_keys"].pop()
        receipt["panel_keys_truncated"] = True
    if len(_json(receipt)) > max_chars:
        for key in ("selected_path", "offset", "next_offset"):
            receipt.pop(key, None)
        receipt["read_selection_omitted"] = True
    return receipt


def google_prompt_evidence_parts(values: list[Any]) -> tuple[list[Any], dict | None]:
    """Detach shared Google evidence before budgeting separate prompt sections.

    Traverse known Jarvis containers, not arbitrary provider JSON. One combined
    projection deduplicates archives and preserves distinct local-read receipts.
    The returned copies let each other-context section retain its existing cap.
    """
    runs = []
    seen: set[int] = set()

    def collect(item: Any) -> None:
        # The saved data also contains the effective-evidence object passed as
        # the first section. Revisiting it must not supersede a current page.
        if id(item) not in seen:
            seen.add(id(item))
            runs.append(item)

    def detach(item: Any) -> Any:
        if is_google_result(item):
            collect(item)
            return {"google_evidence": "see serpapi_google_search"}
        if not isinstance(item, dict):
            return deepcopy(item)
        output = {}
        for key, child in item.items():
            if key == "serpapi_google_search" and google_runs(child):
                collect(child)
                output[key] = {"google_evidence": "see shared Google evidence"}
            elif key in {"_effective_evidence", "supporting_tool_results", "tool_results"}:
                output[key] = detach(child)
            else:
                output[key] = deepcopy(child)
        return output

    others = [detach(value) for value in values]
    return others, project_google_runs(runs) if runs else None


def google_prompt_evidence(value: Any, *, other_max_chars: int) -> str | None:
    """Protect a single Web recovery excerpt from prefix slicing Google data."""
    others, evidence = google_prompt_evidence_parts([value])
    if evidence is None:
        return None
    other = others[0]
    try:
        other_text = _json(other)
    except (TypeError, ValueError):
        other_text = str(other)
    if len(other_text) > other_max_chars:
        other_text = other_text[:other_max_chars] + "\n... [other context truncated]"
    return _json({"serpapi_google_search": evidence, "other_context_preview": other_text})
