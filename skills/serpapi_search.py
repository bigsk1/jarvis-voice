#!/usr/bin/env python3
"""
Jarvis Skill: SerpApi Search
Generic SerpApi search tool for Amazon and other engines.

Input examples:
  {"engine": "amazon", "query": "usb c hub"}
  {"engine": "amazon_product", "asin": "B08N5WRWNW"}
  {"engine": "google", "query": "latest ai news"}
"""
import json
import os
import sys
from typing import Any

# Add lib to path for shared SerpApi helpers
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config
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
        sort_by = input_data.get("sort_by")
        node = input_data.get("node")
        rh = input_data.get("rh")
        min_price = input_data.get("min_price")
        max_price = input_data.get("max_price")
        extra_params = input_data.get("extra_params", {}) or {}

        if not engine:
            return_error("Parameter 'engine' is required (example: amazon, amazon_product, google).")
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

        if query_effective:
            if engine == "amazon":
                params["k"] = query_effective
                params["amazon_domain"] = amazon_domain
                params["language"] = language
            else:
                params["q"] = query_effective

        if asin:
            params["asin"] = asin

        sort_param_key, sort_param_value = normalize_sort_by(engine, sort_by)
        if sort_param_key and sort_param_value is not None:
            params[sort_param_key] = sort_param_value

        if node is not None:
            params["node"] = node
        if rh is not None:
            params["rh"] = rh
        # Generic passthrough convenience for engines that support direct price filters.
        # For Amazon specifically, query/rh may still be the primary filtering path.
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
