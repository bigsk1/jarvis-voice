"""Compare Jarvis's curated xAI chat catalog with xAI's live REST model APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping


_PRICE_FIELDS = (
    "prompt_text_token_price",
    "cached_prompt_text_token_price",
    "prompt_image_token_price",
    "completion_text_token_price",
    "search_price",
    "prompt_text_token_price_long_context",
    "cached_prompt_text_token_price_long_context",
    "completion_text_token_price_long_context",
    "long_context_threshold",
)


def _usd_per_million(value: Any) -> float:
    """Convert xAI cents-per-100M units to USD per 1M units."""
    return float(Decimal(int(value or 0)) / Decimal(10_000))


def pricing_from_api(model: Mapping[str, Any]) -> dict[str, Any]:
    pricing: dict[str, Any] = {
        "input": _usd_per_million(model.get("prompt_text_token_price")),
        "output": _usd_per_million(model.get("completion_text_token_price")),
        "cached": _usd_per_million(model.get("cached_prompt_text_token_price")),
        "image_input": _usd_per_million(model.get("prompt_image_token_price")),
        "search": _usd_per_million(model.get("search_price")),
    }
    threshold = int(model.get("long_context_threshold") or 0)
    if threshold:
        pricing["long_context"] = {
            "threshold": threshold,
            "input": _usd_per_million(
                model.get("prompt_text_token_price_long_context")
                or model.get("prompt_text_token_price")
            ),
            "output": _usd_per_million(
                model.get("completion_text_token_price_long_context")
                or model.get("completion_text_token_price")
            ),
            "cached": _usd_per_million(
                model.get("cached_prompt_text_token_price_long_context")
                or model.get("cached_prompt_text_token_price")
            ),
        }
    return pricing


def normalize_xai_language_models(
    basic_models: Iterable[Mapping[str, Any]],
    language_models: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge `/models` context data with `/language-models` rich metadata."""
    basic_by_id = {str(model["id"]): dict(model) for model in basic_models}
    normalized: list[dict[str, Any]] = []
    endpoint_drift: list[dict[str, Any]] = []

    for language_raw in language_models:
        language = dict(language_raw)
        model_id = str(language["id"])
        basic = basic_by_id.get(model_id)
        if basic is None:
            endpoint_drift.append(
                {
                    "type": "language_model_missing_from_basic_endpoint",
                    "model_id": model_id,
                }
            )
            basic = {}
        else:
            inconsistent = {
                field: {"models": basic.get(field), "language_models": language.get(field)}
                for field in _PRICE_FIELDS
                if field in basic and field in language and basic.get(field) != language.get(field)
            }
            if inconsistent:
                endpoint_drift.append(
                    {
                        "type": "xai_endpoint_metadata_mismatch",
                        "model_id": model_id,
                        "fields": inconsistent,
                    }
                )

        normalized.append(
            {
                "id": model_id,
                "aliases": list(language.get("aliases") or []),
                "created": language.get("created"),
                "version": language.get("version"),
                "fingerprint": language.get("fingerprint"),
                "context_tokens": basic.get("context_length"),
                "input_modalities": list(language.get("input_modalities") or []),
                "output_modalities": list(language.get("output_modalities") or []),
                "pricing": pricing_from_api(language),
            }
        )
    return normalized, endpoint_drift


def audit_xai_models(
    basic_models: Iterable[Mapping[str, Any]],
    language_models: Iterable[Mapping[str, Any]],
    catalog_entries: Iterable[Mapping[str, Any]],
    *,
    ignored_api_models: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return a deterministic JSON report for the xAI chat catalog."""
    api_models, drift = normalize_xai_language_models(basic_models, language_models)
    catalog = [dict(entry) for entry in catalog_entries]
    api_by_id = {entry["id"]: entry for entry in api_models}
    catalog_by_id = {str(entry["id"]): entry for entry in catalog}
    ignored = dict(ignored_api_models or {})
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
        for field in ("context_tokens", "input_modalities", "output_modalities", "pricing"):
            expected = catalog_entry.get(field)
            actual = api_entry.get(field)
            if expected != actual:
                drift.append(
                    {
                        "type": "model_metadata_mismatch",
                        "model_id": model_id,
                        "field": field,
                        "catalog": expected,
                        "api": actual,
                    }
                )

        api_aliases = set(api_entry["aliases"])
        invalid_aliases = sorted(set(catalog_entry.get("aliases") or []) - api_aliases)
        if invalid_aliases:
            drift.append(
                {
                    "type": "catalog_aliases_not_reported_by_api",
                    "model_id": model_id,
                    "aliases": invalid_aliases,
                }
            )

    return {
        "status": "drift" if drift else "ok",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "api_language_models": len(api_models),
            "catalog_models": len(catalog),
            "drift_items": len(drift),
            "warnings": len(warnings),
        },
        "drift": drift,
        "warnings": warnings,
        "ignored_api_models": ignored_models,
        "api_models": api_models,
        "api_note": (
            "xAI exposes context, modalities, aliases, and pricing. Marketing-level capabilities "
            "such as configurable reasoning remain curated because these endpoints do not return them."
        ),
    }
