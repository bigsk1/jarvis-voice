#!/usr/bin/env python3
"""Search Trader Joe's products with one bounded SerpApi request."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from config_loader import load_config
from serpapi_client import clamp_results_count, request_serpapi
from serpapi_trader_joes import (
    TRADER_JOES_MAX_RESPONSE_BYTES,
    TRADER_JOES_TIMEOUT,
    canonical_filter_values,
    normalize_product,
    read_input,
    resolve_location,
    result_data,
    validate_options,
    validate_payload,
)


def search(options: dict[str, Any]) -> dict[str, Any]:
    validate_options(options, search=True)
    query = options["query"].strip()
    page = options.get("page", 1)
    limit = clamp_results_count(options.get("num_results", 5), default=5, maximum=10)
    params: dict[str, Any] = {
        "engine": "trader_joes", "q": query, "page": page,
        "new_products": "true" if options.get("new_products", False) else "false",
        "no_cache": "true" if options.get("no_cache", False) else "false",
    }
    requested_filters = {}
    for key in ("category_id", "sort_by"):
        if key in options:
            params[key] = requested_filters[key] = options[key]
    for key in ("characteristics", "tags"):
        if options.get(key):
            selected = canonical_filter_values(options[key], key)
            params[key] = ",".join(selected)
            requested_filters[key] = selected
    if "new_products" in options:
        requested_filters["new_products"] = options["new_products"]
    location = resolve_location(options)
    if location["store_id"]:
        params["store_id"] = location["store_id"]
    payload = validate_payload(request_serpapi(
        params, timeout=TRADER_JOES_TIMEOUT, max_response_bytes=TRADER_JOES_MAX_RESPONSE_BYTES,
        use_proxy=False, fallback_on_proxy_fail=False,
    ), "trader_joes")
    organic = payload.get("organic_results")
    if "organic_results" not in payload:
        information = payload.get("search_information")
        if isinstance(information, dict):
            total = information.get("total_results")
            state = information.get("organic_results_state")
            if (isinstance(total, int) and not isinstance(total, bool) and total == 0) or state == "Fully empty":
                organic = []
    if not isinstance(organic, list):
        raise ValueError("Trader Joe's search did not return a product list.")
    results = []
    for item in organic:
        if not isinstance(item, dict):
            continue
        row = normalize_product(item)
        if not row["product_id"]:
            continue
        row["position"] = len(results) + 1
        results.append(row)
        if len(results) >= limit:
            break
    data = result_data(payload, results, location, "trader_joes")
    pagination = payload.get("serpapi_pagination", {})
    pagination = pagination if isinstance(pagination, dict) else {}
    has_next = bool(pagination.get("next")) and page < 100
    data.update(query=query, page=page, requested_filters=requested_filters,
                provider_results_count=len(organic), results_truncated=len(organic) > len(results),
                pagination={"current": page, "has_next": has_next, "next_page": page + 1 if has_next else None})
    speech = f"Found {len(results)} Trader Joe's products for {query}." if results else f"No Trader Joe's products found for {query}."
    return {"ok": True, "speech": speech + " " + location["note"], "data": data}


def main() -> int:
    try:
        load_config()
        result = search(read_input(sys.argv))
    except (ValueError, RuntimeError, OSError) as exc:
        message = f"Trader Joe's search error: {exc}"
        result = {"ok": False, "speech": message, "error": message}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
