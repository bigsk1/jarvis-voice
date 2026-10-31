"""Build credential-free retrieval manifests for explicitly selected artifacts."""

import re
from copy import deepcopy
from typing import Any
from urllib.parse import urlencode

MAX_HANDOFF_ARTIFACTS = 12


def _stash_reference(value: Any) -> str:
    """Validate a handle without opening files or claiming that it exists."""
    if isinstance(value, dict):
        ref, stash_ref = value.get("ref"), value.get("stash_ref")
        if ref is not None and stash_ref is not None and ref != stash_ref:
            raise ValueError("Selected artifact has conflicting ref and stash_ref values")
        value = ref if ref is not None else stash_ref
    if not isinstance(value, str) or len(value) > 1024 or not value.startswith("stash://"):
        raise ValueError("context.stash_refs must contain stash:// references")
    parts = value[8:].split("/")
    if (len(parts) != 2 or not re.fullmatch(r"space_[A-Za-z0-9_-]{1,180}", parts[0])
            or not 1 <= len(parts[1]) <= 512 or parts[1] in {".", ".."}
            or any(ord(char) < 32 or ord(char) == 127 or char == "\\" for char in parts[1])):
        raise ValueError("Invalid Stash reference in context.stash_refs")
    return value


def _canvas_page_id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
        raise ValueError("context.canvas_page_ids must contain actual Canvas page IDs")
    return value


def prepare_artifact_handoff(
    config: dict[str, Any], payload: dict[str, Any], *, mode: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Enrich opted-in sends; preserve ordinary payloads and never fetch artifacts.

    The receiver resolves these references through its own configured API base
    and credentials. A retrieval path is not evidence of availability or access.
    """
    policy = config.get("artifact_handoff")
    if policy is None or policy is False:
        return payload, {}
    if policy != "jarvis_v1":
        raise ValueError("Unsupported artifact_handoff in webhook registry")

    receipt: dict[str, Any] = {}
    handoff_id = payload.get("id")
    if isinstance(handoff_id, str) and 1 <= len(handoff_id) <= 200:
        receipt["handoff_id"] = handoff_id
    context = payload.get("context", {})
    if not isinstance(context, dict):
        raise ValueError("Artifact handoff requires context to be a JSON object")
    selected: dict[str, list[Any]] = {}
    for key in ("stash_refs", "canvas_page_ids"):
        values = context.get(key, [])
        if not isinstance(values, list):
            raise ValueError(f"context.{key} must be an array")
        selected[key] = values
    count = sum(len(values) for values in selected.values())
    if count > MAX_HANDOFF_ARTIFACTS:
        raise ValueError(f"Select at most {MAX_HANDOFF_ARTIFACTS} artifacts per handoff")
    if not count:
        return payload, receipt
    if "artifact_manifest" in context:
        raise ValueError("context.artifact_manifest is generated; supply stash_refs or canvas_page_ids")
    selected_mode = context.get("mode", mode)
    if not isinstance(selected_mode, str) or selected_mode not in {"cloud", "local"}:
        raise ValueError("Artifact handoff mode must be cloud or local")

    artifacts = []
    handles = []
    seen = set()
    for value in selected["stash_refs"]:
        ref = _stash_reference(value)
        if ("stash", ref) in seen:
            continue
        seen.add(("stash", ref))
        query = urlencode({"ref": ref, "mode": selected_mode})
        artifacts.append({
            "kind": "stash", "ref": ref, "mode": selected_mode,
            "resolve_url": f"/api/stash/resolve?{query}",
            "read_url": f"/api/stash/read?{query}",
            "download_url": f"/api/stash/download?{query}",
        })
        handles.append({"kind": "stash", "ref": ref, "mode": selected_mode})
    for value in selected["canvas_page_ids"]:
        page_id = _canvas_page_id(value)
        if ("canvas", page_id) in seen:
            continue
        seen.add(("canvas", page_id))
        artifacts.append({
            "kind": "canvas", "page_id": page_id,
            "read_url": f"/api/canvas/{page_id}?include_content=true",
        })
        handles.append({"kind": "canvas", "page_id": page_id})

    outgoing = deepcopy(payload)
    # Core helpers return ref; media wrappers often call the same URI stash_ref.
    # Never forward an entire selected result object with its internal path.
    if selected["stash_refs"]:
        outgoing["context"]["stash_refs"] = [item["ref"] for item in handles if item["kind"] == "stash"]
    if selected["canvas_page_ids"]:
        outgoing["context"]["canvas_page_ids"] = [item["page_id"] for item in handles if item["kind"] == "canvas"]
    outgoing["context"]["artifact_manifest"] = {
        "v": 1, "mode": selected_mode, "availability": "not_checked", "artifacts": artifacts,
    }
    receipt.update(handoff_artifacts_count=len(handles), handoff_artifacts=handles)
    return outgoing, receipt
