"""Compare Jarvis's curated Anthropic catalog with the live Models API."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json", exclude_none=True)
    raise TypeError(f"Unsupported Models API item: {type(value).__name__}")


def normalize_api_model(model: Any) -> dict[str, Any]:
    """Convert an Anthropic SDK ModelInfo (or test mapping) to stable JSON data."""
    raw = _as_dict(model)
    capabilities = raw.get("capabilities")
    if capabilities is not None:
        capabilities = _as_dict(capabilities)
    created_at = raw.get("created_at")
    if isinstance(created_at, (date, datetime)):
        created_at = created_at.isoformat().replace("+00:00", "Z")
    return {
        "id": str(raw["id"]),
        "display_name": raw.get("display_name"),
        "created_at": created_at,
        "max_input_tokens": raw.get("max_input_tokens"),
        "max_tokens": raw.get("max_tokens"),
        "capabilities": capabilities,
    }


def _pricing_warnings(
    entry: Mapping[str, Any],
    *,
    today: date,
    max_age_days: int,
) -> list[dict[str, Any]]:
    model_id = str(entry["id"])
    if not entry.get("pricing"):
        return [{"type": "missing_pricing", "model_id": model_id}]

    warnings: list[dict[str, Any]] = []
    verified_raw = entry.get("pricing_verified")
    source = entry.get("pricing_source")
    if not verified_raw:
        warnings.append({"type": "pricing_not_verified", "model_id": model_id})
    else:
        try:
            verified = date.fromisoformat(str(verified_raw))
            age_days = (today - verified).days
            if age_days > max_age_days:
                warnings.append(
                    {
                        "type": "pricing_verification_stale",
                        "model_id": model_id,
                        "verified": verified.isoformat(),
                        "age_days": age_days,
                        "max_age_days": max_age_days,
                    }
                )
        except ValueError:
            warnings.append(
                {
                    "type": "invalid_pricing_verified_date",
                    "model_id": model_id,
                    "value": verified_raw,
                }
            )
    if not source:
        warnings.append({"type": "missing_pricing_source", "model_id": model_id})

    valid_until_raw = entry.get("pricing_valid_until")
    if valid_until_raw:
        try:
            valid_until = date.fromisoformat(str(valid_until_raw))
            if today > valid_until:
                warnings.append(
                    {
                        "type": "pricing_expired",
                        "model_id": model_id,
                        "valid_until": valid_until.isoformat(),
                    }
                )
        except ValueError:
            warnings.append(
                {
                    "type": "invalid_pricing_valid_until_date",
                    "model_id": model_id,
                    "value": valid_until_raw,
                }
            )
    return warnings


def audit_anthropic_models(
    api_models: Iterable[Any],
    catalog_entries: Iterable[Mapping[str, Any]],
    *,
    ignored_api_models: Mapping[str, str] | None = None,
    today: date | None = None,
    pricing_max_age_days: int = 90,
) -> dict[str, Any]:
    """Return a deterministic, JSON-serializable drift report.

    Models absent from the current API key are warnings because availability can
    be account-specific. Models returned by the API but absent from Jarvis, or
    token/capability mismatches for shared IDs, are actionable drift.
    """
    if pricing_max_age_days < 0:
        raise ValueError("pricing_max_age_days must be zero or greater")

    checked_on = today or datetime.now(timezone.utc).date()
    normalized_api = [normalize_api_model(model) for model in api_models]
    catalog = [dict(entry) for entry in catalog_entries]
    api_by_id = {entry["id"]: entry for entry in normalized_api}
    catalog_by_id = {str(entry["id"]): entry for entry in catalog}
    ignored = dict(ignored_api_models or {})

    drift: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    ignored_models: list[dict[str, str]] = []

    for model_id in sorted(set(api_by_id) - set(catalog_by_id)):
        if model_id in ignored:
            ignored_models.append({"model_id": model_id, "reason": ignored[model_id]})
            continue
        drift.append(
            {
                "type": "api_model_missing_from_catalog",
                "model_id": model_id,
                "api": api_by_id[model_id],
            }
        )

    for model_id in sorted(set(catalog_by_id) - set(api_by_id)):
        warnings.append(
            {
                "type": "catalog_model_unavailable_to_key",
                "model_id": model_id,
                "note": "Availability may be account-specific; review before removing it.",
            }
        )

    for model_id in sorted(set(api_by_id) & set(catalog_by_id)):
        api_entry = api_by_id[model_id]
        catalog_entry = catalog_by_id[model_id]
        comparisons = (
            ("context_tokens", "max_input_tokens"),
            ("max_output_tokens", "max_tokens"),
            ("capabilities", "capabilities"),
        )
        for catalog_field, api_field in comparisons:
            expected = catalog_entry.get(catalog_field)
            actual = api_entry.get(api_field)
            if expected != actual:
                drift.append(
                    {
                        "type": "model_metadata_mismatch",
                        "model_id": model_id,
                        "field": catalog_field,
                        "catalog": expected,
                        "api": actual,
                    }
                )

    for entry in catalog:
        warnings.extend(
            _pricing_warnings(
                entry,
                today=checked_on,
                max_age_days=pricing_max_age_days,
            )
        )

    return {
        "status": "drift" if drift else "ok",
        "checked_on": checked_on.isoformat(),
        "summary": {
            "api_models": len(normalized_api),
            "catalog_models": len(catalog),
            "drift_items": len(drift),
            "warnings": len(warnings),
        },
        "drift": drift,
        "warnings": warnings,
        "ignored_api_models": ignored_models,
        "api_models": normalized_api,
        "pricing_note": "The Anthropic Models API does not provide pricing; pricing remains curated.",
    }
