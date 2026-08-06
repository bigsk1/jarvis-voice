#!/usr/bin/env python3
"""Jarvis Skill: multi-retailer product discovery with Google Shopping Light."""

from __future__ import annotations

import json
import math
import os
import re
import sys
from typing import Any
from urllib.parse import parse_qs, quote, urlparse, urlsplit, urlunsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from config_loader import get_config_value, load_config
from serpapi_client import (
    clamp_results_count,
    get_proxy_enabled,
    merge_extra_params,
    parse_bool,
    request_serpapi,
)


GOOGLE_SHOPPING_LIGHT_TIMEOUT = 90
DEFAULT_MAX_RESULTS = 10
LOCALE_RE = re.compile(r"^[a-z]{2}$")
DOMAIN_RE = re.compile(r"^[a-z0-9.-]+$")
SORT_BY_MAP = {
    "relevance": None,
    "price_low": "1",
    "price_low_to_high": "1",
    "price_asc": "1",
    "price_high": "2",
    "price_high_to_low": "2",
    "price_desc": "2",
}
RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "async",
    "zero_trace",
    "json_restrictor",
    "q",
    "location",
    "uule",
    "google_domain",
    "gl",
    "hl",
    "min_price",
    "max_price",
    "sort_by",
    "free_shipping",
    "on_sale",
    "small_business",
    "start",
    "device",
    "no_cache",
}
COMPARISON_NOTE = (
    "Prices are observed search listings and may differ by product variant, seller, "
    "shipping, tax, availability, or later price changes. Verify the exact offer before purchase."
)


def return_success(speech: str, data: dict[str, Any]) -> None:
    print(json.dumps({"ok": True, "speech": speech, "data": data}))


def return_error(speech: str) -> None:
    print(json.dumps({"ok": False, "speech": speech, "error": speech}))


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _compact_text(value: Any, maximum: int = 1200) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    if len(text) <= maximum:
        return text
    return text[: maximum - 3].rstrip() + "..."


def _validate_text(value: Any, label: str, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > maximum:
        raise ValueError(f"'{label}' must be {maximum} characters or fewer.")
    return text


def _bounded_int(
    value: Any,
    label: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"'{label}' must be an integer from {minimum} to {maximum}.") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"'{label}' must be from {minimum} to {maximum}.")
    return number


def _optional_price(value: Any, label: str) -> float | int | None:
    if value in (None, ""):
        return None
    try:
        price = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"'{label}' must be a non-negative number.") from exc
    if not math.isfinite(price) or price < 0:
        raise ValueError(f"'{label}' must be a non-negative number.")
    return int(price) if price.is_integer() else price


def _http_url(value: Any) -> str | None:
    url = str(value or "").strip()
    if not url:
        return None
    parsed = urlsplit(url)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
        or any(character.isspace() for character in parsed.netloc)
    ):
        return None

    def encode_component(component: str, *, safe: str) -> str:
        # Preserve valid provider escapes such as %20, but repair a literal
        # percent sign before quoting other illegal URL characters.
        protected = re.sub(r"%(?![0-9A-Fa-f]{2})", "%25", component)
        return quote(protected, safe=safe)

    path = encode_component(parsed.path, safe="/%:@!$&'()*+,;=-._~")
    query = encode_component(parsed.query, safe="=&?/:;,+%@!$'()*[]-._~")
    fragment = encode_component(parsed.fragment, safe="=&?/:;,+%@!$'()*[]-._~")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, path, query, fragment))


def normalize_locale(value: Any, label: str) -> str | None:
    locale = str(value or "").strip().lower()
    if not locale:
        return None
    if not LOCALE_RE.fullmatch(locale):
        raise ValueError(f"'{label}' must be a two-letter code such as us or en.")
    return locale


def normalize_google_domain(value: Any) -> str:
    domain = str(value or "google.com").strip().lower()
    if len(domain) > 100 or not DOMAIN_RE.fullmatch(domain) or ".." in domain:
        raise ValueError("'google_domain' must be a Google domain such as google.com or google.co.uk.")
    return domain


def normalize_device(value: Any) -> str:
    device = str(value or "desktop").strip().lower()
    if device not in {"desktop", "tablet", "mobile"}:
        raise ValueError("'device' must be desktop, tablet, or mobile.")
    return device


def normalize_sort_by(value: Any) -> tuple[str, str | None]:
    normalized = str(value or "relevance").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in SORT_BY_MAP:
        raise ValueError(
            "'sort_by' must be relevance, price_low_to_high, or price_high_to_low."
        )
    friendly = {
        "price_low": "price_low_to_high",
        "price_asc": "price_low_to_high",
        "price_high": "price_high_to_low",
        "price_desc": "price_high_to_low",
    }.get(normalized, normalized)
    return friendly, SORT_BY_MAP[normalized]


def resolve_location(explicit_location: Any, uule: Any) -> tuple[str | None, str | None, str]:
    """Use an explicit or mode-scoped origin while allowing provider defaults."""
    location = _validate_text(explicit_location, "location", 200)
    encoded_location = str(uule or "").strip()
    if len(encoded_location) > 500:
        raise ValueError("'uule' must be 500 characters or fewer.")
    if location and encoded_location:
        raise ValueError("'location' and 'uule' cannot be used together.")
    if location:
        return location, None, "explicit"
    if encoded_location:
        return None, encoded_location, "explicit_uule"

    default_location = _validate_text(
        get_config_value("JARVIS_DEFAULT_LOCATION", ""),
        "JARVIS_DEFAULT_LOCATION",
        200,
    )
    if default_location:
        return default_location, None, "jarvis_default_location"

    default_postal_code = _validate_text(
        get_config_value("JARVIS_DEFAULT_POSTAL_CODE", ""),
        "JARVIS_DEFAULT_POSTAL_CODE",
        40,
    )
    if default_postal_code:
        return default_postal_code, None, "jarvis_default_postal_code"
    return None, None, "provider_default"


def _compact_extensions(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        compact
        for item in value[:12]
        if (compact := _compact_text(item, 200))
    ]


def _compact_installment(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    compact = {
        key: value[key]
        for key in ("price", "extracted_price", "period")
        if value.get(key) not in (None, "")
    }
    return compact or None


def _normalize_product(
    item: dict[str, Any],
    *,
    position: int,
    section: str,
    category: str | None = None,
) -> dict[str, Any] | None:
    title = _compact_text(item.get("title"), 500)
    product_link = _http_url(item.get("product_link"))
    merchant_url = _http_url(item.get("link") or item.get("raw_link"))
    url = merchant_url or product_link
    if not title and not url:
        return None

    result = {
        "position": position,
        "provider_position": item.get("position"),
        "section": section,
        "category": category,
        "title": title,
        "url": url,
        "merchant_url": merchant_url,
        "product_link": product_link,
        "product_id": _compact_text(item.get("product_id"), 200),
        "source": _compact_text(item.get("source"), 200),
        "source_icon": _http_url(item.get("source_icon")),
        "multiple_sources": (
            item.get("multiple_sources")
            if isinstance(item.get("multiple_sources"), bool)
            else None
        ),
        "price": _compact_text(item.get("price"), 100),
        "extracted_price": item.get("extracted_price"),
        "old_price": _compact_text(item.get("old_price"), 100),
        "extracted_old_price": item.get("extracted_old_price"),
        "installment": _compact_installment(item.get("installment")),
        "rating": item.get("rating"),
        "reviews": item.get("reviews"),
        "delivery": _compact_text(item.get("delivery"), 300),
        "thumbnail": _http_url(item.get("thumbnail")),
        "serpapi_thumbnail": _http_url(item.get("serpapi_thumbnail")),
        "tag": _compact_text(item.get("tag"), 100),
        "extensions": _compact_extensions(item.get("extensions")),
        "block_position": _compact_text(item.get("block_position"), 50),
    }
    return {
        key: field
        for key, field in result.items()
        if field not in (None, "", [], {})
    }


def extract_shopping_results(
    payload: dict[str, Any],
    *,
    max_results: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Flatten normal, inline, and categorized offers into one bounded shortlist."""
    shopping_rows = _dict_list(payload.get("shopping_results"))
    inline_rows = _dict_list(payload.get("inline_shopping_results"))
    category_groups = _dict_list(payload.get("categorized_shopping_results"))
    categorized_rows = [
        (group, row)
        for group in category_groups
        for row in _dict_list(group.get("shopping_results"))
    ]
    counts = {
        "provider_shopping_results_count": len(shopping_rows),
        "provider_inline_results_count": len(inline_rows),
        "provider_category_groups_count": len(category_groups),
        "provider_categorized_results_count": len(categorized_rows),
    }

    sources = [
        ("shopping", None, row) for row in shopping_rows
    ] + [
        ("inline", None, row) for row in inline_rows
    ] + [
        ("categorized", _compact_text(group.get("title"), 300), row)
        for group, row in categorized_rows
    ]

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for section, category, row in sources:
        product = _normalize_product(
            row,
            position=len(results) + 1,
            section=section,
            category=category,
        )
        if not product:
            continue
        identity = str(
            product.get("product_id")
            or product.get("url")
            or "|".join(
                str(product.get(key) or "").lower()
                for key in ("title", "source", "price")
            )
        )
        if identity in seen:
            continue
        seen.add(identity)
        results.append(product)
        if len(results) >= max_results:
            break
    counts["provider_results_count"] = len(sources)
    return results, counts


def _pagination_start(value: Any) -> int | None:
    if not value:
        return None
    try:
        raw_start = parse_qs(urlparse(str(value)).query).get("start", [None])[0]
        return int(raw_start) if raw_start is not None else None
    except (TypeError, ValueError):
        return None


def extract_pagination(payload: dict[str, Any], *, start: int) -> dict[str, Any]:
    pagination = payload.get("serpapi_pagination")
    pagination = pagination if isinstance(pagination, dict) else {}
    next_start = _pagination_start(pagination.get("next"))
    previous_start = _pagination_start(pagination.get("previous"))
    return {
        key: value
        for key, value in {
            "current": pagination.get("current"),
            "start": start,
            "has_more": next_start is not None,
            "next_start": next_start,
            "previous_start": previous_start,
        }.items()
        if value not in (None, "") or key == "has_more"
    }


def _search_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("search_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        key: metadata[key]
        for key in (
            "id",
            "status",
            "created_at",
            "processed_at",
            "total_time_taken",
            "cached",
            "google_shopping_light_url",
        )
        if metadata.get(key) not in (None, "")
    }


def _google_shopping_light_request(params: dict[str, Any]) -> dict[str, Any]:
    # Keep the implementation proxy-capable while proxy_policy=off makes direct
    # access the default for this tool.
    return request_serpapi(
        params,
        timeout=GOOGLE_SHOPPING_LIGHT_TIMEOUT,
        use_proxy=True,
        fallback_on_proxy_fail=True,
    )


def _lowest_returned_price(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    priced = [
        result
        for result in results
        if isinstance(result.get("extracted_price"), (int, float))
        and math.isfinite(float(result["extracted_price"]))
    ]
    if not priced:
        return None
    lowest = min(priced, key=lambda result: float(result["extracted_price"]))
    return {
        key: lowest[key]
        for key in ("position", "title", "url", "source", "price", "extracted_price")
        if lowest.get(key) not in (None, "")
    }


def build_speech(query: str, results: list[dict[str, Any]]) -> str:
    if not results:
        return f"Google Shopping Light returned no products for '{query}'."
    merchants = {str(row.get("source")) for row in results if row.get("source")}
    speech = f"Found {len(results)} Google Shopping result(s) for '{query}'"
    if merchants:
        speech += f" across {len(merchants)} merchant(s)"
    lowest = _lowest_returned_price(results)
    if lowest:
        speech += (
            f". Lowest returned price: {lowest.get('price') or lowest['extracted_price']}"
            f" from {lowest.get('source') or 'the listed seller'}"
        )
    else:
        speech += f". Top result: {results[0].get('title') or 'shopping result'}"
    return speech + "."


def main() -> int:
    try:
        load_config()
        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        query = _validate_text(input_data.get("query"), "query", 500)
        if not query:
            raise ValueError("'query' is required.")

        location, uule, location_source = resolve_location(
            input_data.get("location"), input_data.get("uule")
        )
        google_domain = normalize_google_domain(input_data.get("google_domain"))
        country = normalize_locale(input_data.get("country"), "country")
        language = normalize_locale(input_data.get("language"), "language")
        device = normalize_device(input_data.get("device"))
        sort_by, provider_sort = normalize_sort_by(input_data.get("sort_by"))
        min_price = _optional_price(input_data.get("min_price"), "min_price")
        max_price = _optional_price(input_data.get("max_price"), "max_price")
        if min_price is not None and max_price is not None and min_price > max_price:
            raise ValueError("'min_price' cannot be greater than 'max_price'.")
        free_shipping = parse_bool(input_data.get("free_shipping", False))
        on_sale = parse_bool(input_data.get("on_sale", False))
        small_business = parse_bool(input_data.get("small_business", False))
        start = _bounded_int(
            input_data.get("start"), "start", default=0, minimum=0, maximum=1000
        )
        max_results = clamp_results_count(
            input_data.get("max_results", DEFAULT_MAX_RESULTS),
            default=DEFAULT_MAX_RESULTS,
            maximum=20,
        )
        no_cache = parse_bool(input_data.get("no_cache", False))
        include_raw = parse_bool(input_data.get("include_raw", False))
        extra_params = input_data.get("extra_params", {})
        if extra_params is None:
            extra_params = {}
        if not isinstance(extra_params, dict):
            raise ValueError("'extra_params' must be an object.")

        params: dict[str, Any] = {
            "engine": "google_shopping_light",
            "q": query,
            "google_domain": google_domain,
            "start": start,
            "device": device,
            "no_cache": "true" if no_cache else "false",
        }
        for key, value in (
            ("location", location),
            ("uule", uule),
            ("gl", country),
            ("hl", language),
            ("min_price", min_price),
            ("max_price", max_price),
            ("sort_by", provider_sort),
        ):
            if value not in (None, ""):
                params[key] = value
        for key, enabled in (
            ("free_shipping", free_shipping),
            ("on_sale", on_sale),
            ("small_business", small_business),
        ):
            if enabled:
                params[key] = "true"
        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)

        payload = _google_shopping_light_request(params)
        if not isinstance(payload, dict):
            raise RuntimeError("SerpApi returned an invalid Google Shopping Light response.")
        results, provider_counts = extract_shopping_results(
            payload,
            max_results=max_results,
        )
        pagination = extract_pagination(payload, start=start)
        metadata = _search_metadata(payload)
        search_information = payload.get("search_information")
        search_information = search_information if isinstance(search_information, dict) else {}
        search_parameters = payload.get("search_parameters")
        search_parameters = search_parameters if isinstance(search_parameters, dict) else {}
        merchants = sorted({str(row["source"]) for row in results if row.get("source")})
        lowest = _lowest_returned_price(results)

        data: dict[str, Any] = {
            "engine": "google_shopping_light",
            "query": query,
            "query_displayed": search_information.get("query_displayed"),
            "shopping_results_state": search_information.get("shopping_results_state"),
            "location": location,
            "location_source": location_source,
            "uule_used": bool(uule),
            "provider_location_used": search_parameters.get("location"),
            "country": country,
            "language": language,
            "google_domain": google_domain,
            "device": device,
            "sort_by": sort_by,
            "min_price": min_price,
            "max_price": max_price,
            "free_shipping": free_shipping,
            "on_sale": on_sale,
            "small_business": small_business,
            "start": start,
            "max_results": max_results,
            "results_count": len(results),
            **provider_counts,
            "merchants_count": len(merchants),
            "merchants": merchants,
            "results": results,
            "top_results": results[:5],
            "top_url": results[0].get("url") if results else None,
            "lowest_returned_price": lowest,
            "comparison_note": COMPARISON_NOTE,
            "pagination": pagination,
            "has_more": pagination.get("has_more", False),
            "next_start": pagination.get("next_start"),
            "search_id": metadata.get("id"),
            "search_metadata": metadata,
            "google_shopping_light_url": metadata.get("google_shopping_light_url"),
            "serpapi_searches_used": 1,
            "proxy_enabled": get_proxy_enabled(),
            "source": "SerpApi Google Shopping Light",
        }
        data = {
            key: value
            for key, value in data.items()
            if value not in (None, "", [], {})
        }
        if include_raw:
            data["raw"] = payload

        return_success(build_speech(query, results), data)
        return 0
    except ValueError as exc:
        return_error(str(exc))
        return 1
    except Exception as exc:
        message = str(exc)
        if "timeout" in message.lower() or "timed out" in message.lower():
            return_error("SerpApi Google Shopping Light request timed out.")
            return 1
        return_error(f"SerpApi Google Shopping Light error: {message}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
