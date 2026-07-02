"""Audit Jarvis's curated OpenAI chat options against the OpenAI Models API."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


_GENERAL_TEXT_MODEL = re.compile(r"^gpt-\d+(?:\.\d+)?(?:-(?:mini|nano))?$")
_DATED_SUFFIX = re.compile(r"-\d{4}-\d{2}-\d{2}$")


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json", exclude_none=True)
    raise TypeError(f"Unsupported OpenAI Models API item: {type(value).__name__}")


def normalize_openai_model(model: Any) -> dict[str, Any]:
    raw = _as_dict(model)
    return {
        "id": str(raw["id"]),
        "created": int(raw.get("created") or 0),
        "object": raw.get("object"),
        "owned_by": raw.get("owned_by"),
    }


def _model_family(model_id: str) -> str:
    return _DATED_SUFFIX.sub("", model_id)


def _catalog_api_ids(entry: Mapping[str, Any]) -> set[str]:
    return {
        str(value)
        for value in (entry.get("id"), *(entry.get("aliases") or []))
        if value
    }


def audit_openai_models(
    api_models: Iterable[Any],
    catalog_entries: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return a JSON report without misclassifying specialized API models.

    The Models API exposes identity/availability only. A new general-purpose
    GPT family is considered actionable drift when it is newer than every
    available curated entry. Specialized models remain visible in JSON output
    but are not treated as chat-catalog candidates.
    """
    normalized_api = [normalize_openai_model(model) for model in api_models]
    catalog = [dict(entry) for entry in catalog_entries]
    api_by_id = {entry["id"]: entry for entry in normalized_api}
    api_ids = set(api_by_id)

    warnings: list[dict[str, Any]] = []
    matched_api_ids: set[str] = set()
    curated_created: list[int] = []
    for entry in catalog:
        accepted_ids = _catalog_api_ids(entry)
        available_ids = sorted(accepted_ids & api_ids)
        if not available_ids:
            warnings.append(
                {
                    "type": "catalog_model_unavailable_to_key",
                    "model_id": entry["id"],
                    "accepted_ids": sorted(accepted_ids),
                    "note": "Availability can be account-specific; review before removing it.",
                }
            )
            continue
        matched_api_ids.update(available_ids)
        curated_created.extend(api_by_id[model_id]["created"] for model_id in available_ids)

    newest_curated_created = max(curated_created, default=0)
    known_families = {
        _model_family(model_id)
        for entry in catalog
        for model_id in _catalog_api_ids(entry)
    }
    candidate_groups: dict[str, list[dict[str, Any]]] = {}
    for model in normalized_api:
        family = _model_family(model["id"])
        if model["created"] <= newest_curated_created:
            continue
        if family in known_families or not _GENERAL_TEXT_MODEL.fullmatch(family):
            continue
        candidate_groups.setdefault(family, []).append(model)

    review_candidates = [
        {
            "type": "new_general_model_family",
            "family": family,
            "models": sorted(models, key=lambda item: (item["created"], item["id"])),
        }
        for family, models in sorted(candidate_groups.items())
    ]
    uncurated_models = [
        model for model in normalized_api if model["id"] not in matched_api_ids
    ]

    return {
        "status": "drift" if review_candidates else "ok",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "api_models": len(normalized_api),
            "catalog_models": len(catalog),
            "review_candidates": len(review_candidates),
            "warnings": len(warnings),
            "uncurated_api_models": len(uncurated_models),
        },
        "review_candidates": review_candidates,
        "warnings": warnings,
        "api_models": sorted(normalized_api, key=lambda item: item["id"]),
        "uncurated_api_models": sorted(uncurated_models, key=lambda item: item["id"]),
        "api_note": (
            "OpenAI's Models API reports identity, creation time, owner, and availability only. "
            "Context limits, capabilities, modalities, and pricing remain curated separately."
        ),
    }
