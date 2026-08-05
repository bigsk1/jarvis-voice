#!/usr/bin/env python3
"""
Jarvis Skill: SerpApi Amazon Search
Amazon listing discovery and product details through SerpApi.

Input examples:
  {"engine": "amazon", "query": "usb c hub"}
  {"engine": "amazon_product", "asin": "B08N5WRWNW"}
"""
import json
import os
import sys
from typing import Any

# Add lib to path for shared SerpApi helpers
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import get_config_value, load_config
from serpapi_client import (
    GENERIC_RESERVED_KEYS,
    build_search_speech,
    clamp_results_count,
    extract_generic_results,
    fallback_amazon_query,
    get_proxy_enabled,
    merge_extra_params,
    normalize_amazon_query,
    parse_bool,
    request_serpapi,
    should_optimize_amazon_query,
)


def return_success(speech: str, data: dict[str, Any] | None = None) -> None:
    result: dict[str, Any] = {"ok": True, "speech": speech}
    if data:
        result["data"] = data
    print(json.dumps(result))


def return_error(speech: str, data: dict[str, Any] | None = None) -> None:
    result: dict[str, Any] = {"ok": False, "speech": speech, "error": speech}
    if data:
        result["data"] = data
    print(json.dumps(result))


AMAZON_SORT_MAP = {
    "featured": "relevanceblender",
    "relevance": "relevanceblender",
    "price_low": "price-asc-rank",
    "price_low_to_high": "price-asc-rank",
    "price_asc": "price-asc-rank",
    "price-high": "price-desc-rank",
    "price_high": "price-desc-rank",
    "price_high_to_low": "price-desc-rank",
    "price_desc": "price-desc-rank",
    "rating": "review-rank",
    "reviews": "review-rank",
    "review": "review-rank",
    "review_score": "review-rank",
    "best_reviews": "review-rank",
    "best_review_rating": "review-rank",
    "newest": "date-desc-rank",
    "latest": "date-desc-rank",
    "best_sellers": "exact-aware-popularity-rank",
    "bestseller": "exact-aware-popularity-rank",
    "bestseller": "exact-aware-popularity-rank",
    "popularity": "exact-aware-popularity-rank",
}


def normalize_sort_by(engine: str, sort_by: Any) -> tuple[str | None, str | None]:
    """Map friendly sort names to engine-specific SerpApi params."""
    if sort_by is None:
        return None, None

    raw = str(sort_by).strip()
    if not raw:
        return None, None

    lowered = raw.lower().replace(" ", "_")
    if engine == "amazon":
        return "s", AMAZON_SORT_MAP.get(lowered, raw)
    return "sort_by", raw


def merge_product_detail(search_row: dict[str, Any], detail_row: dict[str, Any]) -> dict[str, Any]:
    """Merge richer product signals while preserving discovery identity/link."""
    merged = dict(search_row)
    for field, value in detail_row.items():
        if value in (None, "", [], {}):
            continue
        if field in {"title", "url", "thumbnail"} and merged.get(field):
            continue
        merged[field] = value
    merged["detail_enriched"] = True
    return merged


def main() -> int:
    try:
        load_config()

        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        engine = str(input_data.get("engine", "")).strip()
        query = str(input_data.get("query", "")).strip()
        asin = str(input_data.get("asin", "")).strip()
        amazon_domain = str(input_data.get("amazon_domain", "amazon.com")).strip()
        language = str(input_data.get("language", "en_US")).strip()
        device = str(input_data.get("device", "desktop")).strip()
        page = int(input_data.get("page", 1))
        num_results = int(input_data.get("num_results", 5))
        no_cache = parse_bool(input_data.get("no_cache", False))
        optimize_query = parse_bool(input_data.get("optimize_query", True), default=True)
        include_raw = parse_bool(input_data.get("include_raw", False))
        include_product_details = parse_bool(input_data.get("include_product_details", False))
        product_details_limit = clamp_results_count(
            input_data.get("product_details_limit", 5),
            default=5,
            maximum=5,
        )
        sort_by = input_data.get("sort_by")
        node = input_data.get("node")
        rh = input_data.get("rh")
        min_price = input_data.get("min_price")
        max_price = input_data.get("max_price")
        delivery_zip = str(input_data.get("delivery_zip", "")).strip()
        shipping_location = str(input_data.get("shipping_location", "")).strip()
        extra_params = input_data.get("extra_params", {}) or {}

        if not engine:
            return_error("Parameter 'engine' is required (amazon or amazon_product).")
            return 1

        if engine not in {"amazon", "amazon_product"}:
            return_error("Unsupported engine. serpapi_amazon_search accepts only amazon or amazon_product.")
            return 1

        num_results = clamp_results_count(num_results, default=5)

        if page < 1:
            page = 1

        query_effective = query
        query_was_optimized = False
        if engine == "amazon" and query and optimize_query:
            normalized_query = normalize_amazon_query(query)
            if should_optimize_amazon_query(query, normalized_query):
                query_effective = normalized_query
                query_was_optimized = True

        params: dict[str, Any] = {
            "engine": engine,
            "device": device,
            "page": page,
            "no_cache": "true" if no_cache else "false",
        }

        if engine in {"amazon", "amazon_product"}:
            params["amazon_domain"] = amazon_domain
            params["language"] = language

        if query_effective:
            if engine == "amazon":
                params["k"] = query_effective
            else:
                params["q"] = query_effective

        delivery_location_source = "none"
        if engine in {"amazon", "amazon_product"}:
            if delivery_zip:
                delivery_location_source = "explicit"
            else:
                delivery_zip = get_config_value("JARVIS_DEFAULT_POSTAL_CODE", "").strip()
                if delivery_zip:
                    delivery_location_source = "jarvis_default"
            if delivery_zip:
                params["delivery_zip"] = delivery_zip
            if shipping_location:
                params["shipping_location"] = shipping_location

        if asin:
            params["asin"] = asin

        sort_param_key, sort_param_value = normalize_sort_by(engine, sort_by)
        if sort_param_key and sort_param_value is not None:
            params[sort_param_key] = sort_param_value

        if node is not None:
            params["node"] = node
        if rh is not None:
            params["rh"] = rh
        # Amazon may still rely primarily on query/rh for price filtering.
        if min_price is not None:
            params["min_price"] = min_price
        if max_price is not None:
            params["max_price"] = max_price

        merge_extra_params(params, extra_params, reserved_keys=GENERIC_RESERVED_KEYS)

        if engine == "amazon_product" and not asin and not query:
            return_error("For engine 'amazon_product', provide 'asin' (preferred) or 'query'.")
            return 1

        if engine != "amazon_product" and not query and not asin:
            return_error("Provide at least one of: 'query' or 'asin'.")
            return 1

        payload = request_serpapi(params)
        results = extract_generic_results(payload, engine=engine, limit=num_results)
        retried_with_normalized_query = False
        retry_attempted_queries: list[str] = []

        # Amazon search is sensitive to conversational phrasing.
        # If first pass returns zero, retry once with normalized keywords.
        if engine == "amazon" and query and not results:
            retry_candidates = []
            normalized_query = normalize_amazon_query(query)
            if normalized_query and normalized_query != query and normalized_query != query_effective:
                retry_candidates.append(normalized_query)

            broad_query = fallback_amazon_query(query)
            if broad_query and broad_query not in retry_candidates and broad_query != query and broad_query != query_effective:
                retry_candidates.append(broad_query)

            for candidate in retry_candidates[:2]:
                retry_params = dict(params)
                retry_params["k"] = candidate
                retry_attempted_queries.append(candidate)
                try:
                    retry_payload = request_serpapi(retry_params)
                except RuntimeError:
                    continue

                retry_results = extract_generic_results(retry_payload, engine=engine, limit=num_results)
                if retry_results:
                    payload = retry_payload
                    results = retry_results
                    query_effective = candidate
                    retried_with_normalized_query = True
                    break

        product_details_requested = 0
        product_details_succeeded = 0
        product_details_failed_asins: list[str] = []
        if engine == "amazon" and include_product_details and results:
            enriched_results = list(results)
            for index, search_row in enumerate(results[:product_details_limit]):
                asin_value = str(search_row.get("asin") or "").strip()
                if not asin_value:
                    continue
                product_details_requested += 1
                detail_params: dict[str, Any] = {
                    "engine": "amazon_product",
                    "asin": asin_value,
                    "amazon_domain": amazon_domain,
                    "language": language,
                    "device": device,
                    "no_cache": "true" if no_cache else "false",
                }
                if delivery_zip:
                    detail_params["delivery_zip"] = delivery_zip
                if shipping_location:
                    detail_params["shipping_location"] = shipping_location
                try:
                    detail_payload = request_serpapi(detail_params)
                    detail_rows = extract_generic_results(
                        detail_payload,
                        engine="amazon_product",
                        limit=1,
                    )
                except (RuntimeError, ValueError):
                    product_details_failed_asins.append(asin_value)
                    continue
                if not detail_rows:
                    product_details_failed_asins.append(asin_value)
                    continue
                enriched_results[index] = merge_product_detail(search_row, detail_rows[0])
                product_details_succeeded += 1
            results = enriched_results

        speech = build_search_speech(engine=engine, query=query, results=results)

        data: dict[str, Any] = {
            "engine": engine,
            "query": query or None,
            "query_effective": query_effective or None,
            "query_was_optimized": query_was_optimized,
            "asin": asin or None,
            "sort_by": sort_by,
            "node": node,
            "rh": rh,
            "min_price": min_price,
            "max_price": max_price,
            "delivery_localized": bool(delivery_zip) if engine in {"amazon", "amazon_product"} else False,
            "delivery_location_source": delivery_location_source,
            "shipping_location": shipping_location or None,
            "include_product_details": include_product_details,
            "product_details_requested": product_details_requested,
            "product_details_succeeded": product_details_succeeded,
            "product_details_failed_asins": product_details_failed_asins,
            "results_count": len(results),
            "results": results,
            "top_results": results[:5],
            "top_url": (results[0].get("url") if results else None),
            "search_metadata": payload.get("search_metadata", {}),
            "search_information": payload.get("search_information", {}),
            "proxy_enabled": get_proxy_enabled(),
            "source": "SerpApi",
            "retried_with_normalized_query": retried_with_normalized_query,
            "retry_attempted_queries": retry_attempted_queries,
        }
        if include_raw:
            data["raw"] = payload

        return_success(speech=speech, data=data)
        return 0

    except Exception as e:
        msg = str(e)
        if "timeout" in msg.lower():
            return_error("SerpApi request timed out.")
            return 1
        if "HTTP " in msg:
            status_match = msg.rsplit("HTTP ", 1)[-1].rstrip(".")
            return_error(msg, data={"status_code": status_match})
            return 1
        return_error(f"SerpApi tool error: {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
