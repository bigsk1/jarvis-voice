#!/usr/bin/env python3
"""Shared SerpApi helpers used by Jarvis skills."""
from __future__ import annotations

import re
from typing import Any

from config_loader import get_config_value
from http_client import get_proxy_config, http_request


SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
GENERIC_RESERVED_KEYS = {
    "engine",
    "api_key",
    "q",
    "k",
    "asin",
    "output",
    "device",
    "page",
    "num",
    "no_cache",
    "amazon_domain",
    "language",
    "delivery_zip",
    "shipping_location",
}

AMAZON_QUERY_STOPWORDS = {
    "a", "an", "and", "are", "around", "best", "can", "for", "find", "from",
    "give", "help", "i", "ideas", "in", "into", "is", "it", "looking", "me",
    "my", "of", "on", "please", "recommend", "search", "show", "suggest",
    "that", "the", "to", "under", "want", "with", "you", "your",
    "amazon", "product", "products", "listing", "listings", "let", "know",
    "could", "would", "should", "for", "gift", "gifts", "idea", "ideas",
    "birthday", "present", "male", "female", "adult", "year", "years", "old",
    "he", "him", "his", "she", "her", "they", "them", "their",
    "so", "just", "really", "also", "items", "item", "get", "got",
}


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def clamp_results_count(value: Any, default: int = 5, *, maximum: int = 10) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = default

    cap = max(1, int(maximum))
    if count < 1:
        return 1
    if count > cap:
        return cap
    return count


def get_api_key() -> str:
    api_key = get_config_value("SERP_API_KEY", "").strip()
    if not api_key:
        raise ValueError("SERP_API_KEY is not configured.")
    if "YOUR_" in api_key or "REPLACE" in api_key or len(api_key) < 16:
        raise ValueError("SERP_API_KEY appears to be a placeholder or invalid.")
    return api_key


def get_proxy_enabled() -> bool:
    return get_proxy_config() is not None


def merge_extra_params(
    params: dict[str, Any],
    extra_params: Any,
    reserved_keys: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(extra_params, dict):
        return params

    blocked = reserved_keys or set()
    for key, value in extra_params.items():
        if key in blocked:
            continue
        params[key] = value
    return params


def request_serpapi(
    params: dict[str, Any],
    timeout: int = 25,
    *,
    use_proxy: bool = True,
    fallback_on_proxy_fail: bool = True,
    allowed_error_substrings: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    final_params = dict(params)
    final_params["api_key"] = get_api_key()
    final_params.setdefault("output", "json")

    response = http_request(
        "GET",
        SERPAPI_ENDPOINT,
        params=final_params,
        timeout=timeout,
        use_proxy=use_proxy,
        fallback_on_proxy_fail=fallback_on_proxy_fail,
    )

    if response.status_code >= 400:
        raise RuntimeError(f"SerpApi request failed with HTTP {response.status_code}.")

    payload = response.json()
    if payload.get("error"):
        error_text = str(payload.get("error"))
        allowed_errors = tuple(allowed_error_substrings or ())
        if any(allowed.lower() in error_text.lower() for allowed in allowed_errors):
            return payload
        raise RuntimeError(f"SerpApi error: {payload.get('error')}")
    return payload


def extract_generic_results(payload: dict[str, Any], engine: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    def prime_eligibility(item: dict[str, Any]) -> bool | None:
        prime = item.get("prime")
        if isinstance(prime, bool):
            return prime

        delivery = item.get("delivery")
        delivery_text = " ".join(str(value) for value in delivery) if isinstance(delivery, list) else str(delivery or "")
        if "prime member" in delivery_text.lower() or "prime delivery" in delivery_text.lower():
            return True
        return None

    def normalize_item(item: dict[str, Any], source: str) -> dict[str, Any]:
        return {
            "title": item.get("title"),
            "url": item.get("link_clean") or item.get("link") or item.get("source"),
            "asin": item.get("asin"),
            "price": item.get("price"),
            "extracted_price": item.get("extracted_price"),
            "old_price": item.get("old_price"),
            "extracted_old_price": item.get("extracted_old_price"),
            "rating": item.get("rating"),
            "reviews": item.get("reviews"),
            "prime": item.get("prime"),
            "prime_eligible": prime_eligibility(item),
            "delivery": item.get("delivery"),
            "shipping": item.get("shipping"),
            "stock": item.get("stock"),
            "availability": item.get("availability"),
            "bought_last_month": item.get("bought_last_month"),
            "badges": item.get("badges"),
            "save_with_coupon": item.get("save_with_coupon"),
            "thumbnail": item.get("thumbnail"),
            "source": source,
        }

    if engine == "amazon_product":
        product = payload.get("product_results") or {}
        if product:
            results.append(normalize_item(product, "product_results"))
        return results[:limit]

    candidates = []
    for bucket in ("organic_results", "shopping_results", "news_results", "images_results"):
        values = payload.get(bucket)
        if isinstance(values, list):
            for item in values:
                if not isinstance(item, dict):
                    continue
                candidates.append(normalize_item(item, bucket))

    for item in candidates:
        if not item.get("title") and not item.get("url"):
            continue
        results.append(item)
        if len(results) >= limit:
            break

    return results


def extract_maps_results(payload: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    local_results = payload.get("local_results") or []
    if isinstance(local_results, dict):
        local_results = [local_results]

    for item in local_results:
        if not isinstance(item, dict):
            continue

        links = item.get("links") or {}
        website = item.get("website") or links.get("website")
        place_link = item.get("place_id_search")
        reviews_link = item.get("reviews_link") or links.get("reviews")
        directions_link = links.get("directions")
        results.append(
            {
                "title": item.get("title"),
                "url": website or place_link or reviews_link or directions_link,
                "website": website,
                "place_id_search": place_link,
                "reviews_link": reviews_link,
                "directions_link": directions_link,
                "rating": item.get("rating"),
                "reviews": item.get("reviews"),
                "price": item.get("price"),
                "type": item.get("type"),
                "types": item.get("types"),
                "address": item.get("address"),
                "open_state": item.get("open_state"),
                "hours": item.get("hours"),
                "phone": item.get("phone") or links.get("phone"),
                "description": item.get("description"),
                "gps_coordinates": item.get("gps_coordinates"),
                "place_id": item.get("place_id"),
                "data_id": item.get("data_id"),
                "thumbnail": item.get("thumbnail"),
                "source": "local_results",
            }
        )
        if len(results) >= limit:
            break

    if results:
        return results

    place_result = payload.get("place_results")
    if isinstance(place_result, dict):
        links = place_result.get("links") or {}
        website = place_result.get("website") or links.get("website")
        reviews_link = place_result.get("reviews_link") or links.get("reviews")
        directions_link = links.get("directions")
        return [
            {
                "title": place_result.get("title"),
                "url": website or reviews_link or directions_link,
                "website": website,
                "place_id_search": place_result.get("place_id_search"),
                "reviews_link": reviews_link,
                "directions_link": directions_link,
                "rating": place_result.get("rating"),
                "reviews": place_result.get("reviews"),
                "price": place_result.get("price"),
                "type": place_result.get("type"),
                "types": place_result.get("types"),
                "address": place_result.get("address"),
                "open_state": place_result.get("open_state"),
                "hours": place_result.get("hours"),
                "phone": place_result.get("phone") or links.get("phone"),
                "description": place_result.get("description"),
                "gps_coordinates": place_result.get("gps_coordinates"),
                "place_id": place_result.get("place_id"),
                "data_id": place_result.get("data_id"),
                "thumbnail": place_result.get("thumbnail"),
                "source": "place_results",
            }
        ]
    return results


def extract_hotel_results(payload: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in payload.get("properties") or []:
        if not isinstance(item, dict):
            continue

        rate_per_night = item.get("rate_per_night") or {}
        total_rate = item.get("total_rate") or {}
        prices = item.get("prices") or []
        first_price = prices[0] if prices and isinstance(prices[0], dict) else {}

        results.append(
            {
                "title": item.get("name"),
                "url": item.get("link"),
                "type": item.get("type"),
                "description": item.get("description"),
                "hotel_class": item.get("hotel_class"),
                "rating": item.get("overall_rating"),
                "reviews": item.get("reviews"),
                "price_per_night": rate_per_night.get("lowest"),
                "price_total": total_rate.get("lowest"),
                "extracted_price_per_night": rate_per_night.get("extracted_lowest"),
                "extracted_price_total": total_rate.get("extracted_lowest"),
                "before_taxes_fees_per_night": rate_per_night.get("before_taxes_fees"),
                "before_taxes_fees_total": total_rate.get("before_taxes_fees"),
                "check_in_time": item.get("check_in_time"),
                "check_out_time": item.get("check_out_time"),
                "amenities": item.get("amenities"),
                "free_cancellation": item.get("free_cancellation"),
                "gps_coordinates": item.get("gps_coordinates"),
                "thumbnail": item.get("thumbnail"),
                "nearby_places": item.get("nearby_places"),
                "first_price_source": first_price.get("source"),
                "source": "properties",
            }
        )
        if len(results) >= limit:
            break
    return results


def build_search_speech(engine: str, query: str, results: list[dict[str, Any]]) -> str:
    if not results:
        if query:
            return f"No results found for '{query}' on SerpApi engine '{engine}'."
        return f"No results found on SerpApi engine '{engine}'."

    top = results[0]
    top_title = (top.get("title") or "top result").strip()
    top_price = top.get("price")
    if top_price:
        return (
            f"Found {len(results)} result(s) on '{engine}'. "
            f"Top result: {top_title}, price {top_price}."
        )
    return f"Found {len(results)} result(s) on '{engine}'. Top result: {top_title}."


def normalize_amazon_query(query: str) -> str:
    """Convert conversational gift prompts into cleaner Amazon keyword queries."""
    raw = (query or "").strip()
    if not raw:
        return raw

    lowered = raw.lower()
    replacements = {
        "amazong": "amazon",
        "old scholl": "classic",
        "old school": "classic",
        "tech enthusiast": "tech",
    }
    for bad, good in replacements.items():
        lowered = lowered.replace(bad, good)

    budget_match = re.search(r"\$\s*\d+(?:\s*-\s*\$\s*\d+)?", lowered)
    budget_token = budget_match.group(0).replace(" ", "") if budget_match else ""

    cleaned = re.sub(r"[^a-zA-Z0-9$\- ]+", " ", lowered)
    tokens = [token for token in cleaned.split() if token]

    kept: list[str] = []
    has_budget = bool(budget_token)
    for token in tokens:
        if token in AMAZON_QUERY_STOPWORDS:
            continue
        if token.isdigit() and not has_budget:
            continue
        if len(token) <= 1 and not token.isdigit() and not token.startswith("$"):
            continue
        kept.append(token)

    seen = set()
    deduped: list[str] = []
    for token in kept:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)

    if len(deduped) < 3:
        deduped = ["tech", "gift", "ideas"]

    deduped = deduped[:12]
    normalized = " ".join(deduped).strip()

    if budget_token and budget_token not in normalized:
        normalized = f"{normalized} {budget_token}".strip()

    return normalized or raw


def should_optimize_amazon_query(raw_query: str, normalized_query: str) -> bool:
    if not raw_query or not normalized_query or normalized_query == raw_query:
        return False

    raw_tokens = re.findall(r"[a-zA-Z0-9$-]+", raw_query.lower())
    if len(raw_tokens) >= 8:
        return True
    if any(char in raw_query for char in (".", ",", "?", "!", ":")):
        return True
    conversational_markers = ("find", "show", "recommend", "looking for", "let me know", "what")
    lowered = raw_query.lower()
    return any(marker in lowered for marker in conversational_markers)


def fallback_amazon_query(query: str) -> str:
    raw = (query or "").lower()
    if not raw:
        return "tech gifts"

    topics = []
    if any(word in raw for word in ("tech", "gadget", "electronics", "programming", "coding")):
        topics.append("tech")
    if any(word in raw for word in ("gaming", "gamer")):
        topics.append("gaming")
    if any(word in raw for word in ("smart home", "home automation")):
        topics.append("smart home")
    if not topics:
        topics.append("gift")

    parts = topics + ["gifts"]
    budget_range = re.search(r"\$\s*(\d+)\s*-\s*\$?\s*(\d+)", raw)
    if budget_range:
        parts.extend(["under", budget_range.group(2)])
    else:
        budget_single = re.search(r"\$\s*(\d+)", raw)
        if budget_single:
            parts.extend(["under", budget_single.group(1)])

    return " ".join(parts).strip()


def parse_int_list(value: Any) -> list[int]:
    if isinstance(value, list):
        result = []
        for item in value:
            try:
                result.append(int(item))
            except (TypeError, ValueError):
                continue
        return result

    if isinstance(value, str):
        result = []
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                result.append(int(part))
            except ValueError:
                continue
        return result

    return []
