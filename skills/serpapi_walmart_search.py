#!/usr/bin/env python3
"""Search Walmart through SerpApi; one cached request per invocation."""
from __future__ import annotations

import json
import math
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config
from serpapi_client import clamp_results_count, parse_bool, request_serpapi
from serpapi_walmart import (
    WALMART_MAX_RESPONSE_BYTES,
    WALMART_TIMEOUT,
    normalize_product,
    read_input,
    resolve_location,
    result_data,
    validate_options,
)


def main() -> int:
    try:
        load_config()
        options = read_input(sys.argv)
        validate_options(options, search=True)
        query = str(options.get("query") or "").strip()
        cat_id = str(options.get("cat_id") or "").strip()
        if not query and not cat_id:
            raise ValueError("Provide query or cat_id for a Walmart search.")
        domain = str(options.get("walmart_domain") or "walmart.com").strip()
        if domain not in {"walmart.com", "walmart.com.mx"}:
            raise ValueError("walmart_domain must be walmart.com or walmart.com.mx.")
        sort = str(options.get("sort_by") or "").strip()
        if sort and sort not in {"price_low", "price_high", "best_seller", "best_match", "rating_high", "new"}:
            raise ValueError("Unsupported Walmart sort_by value.")
        if domain == "walmart.com.mx" and (cat_id or sort in {"best_seller", "rating_high", "new"}
                or "soft_sort" in options or parse_bool(options.get("next_day"))):
            raise ValueError("This category, sort, relevance or NextDay option is only supported for Walmart US.")
        page = options.get("page", 1)
        if type(page) is not int or not 1 <= page <= 100:
            raise ValueError("page must be an integer from 1 to 100.")
        params: dict[str, Any] = {"engine": "walmart", "walmart_domain": domain, "page": page,
                                  "include_filters": "true",
                                  "no_cache": "true" if parse_bool(options.get("no_cache")) else "false"}
        if query:
            params["query"] = query
        if cat_id:
            params["cat_id"] = cat_id
        if sort:
            params["sort"] = sort
            params["soft_sort"] = "false"  # Honor the requested price/rating sort exactly.
            if domain == "walmart.com.mx":
                params.pop("soft_sort")
        for key in ("min_price", "max_price"):
            value = options.get(key)
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"{key} must be a nonnegative finite number.")
                params[key] = value
        if params.get("min_price", 0) > params.get("max_price", float("inf")):
            raise ValueError("min_price must not exceed max_price.")
        if options.get("facet"):
            params["facet"] = str(options["facet"]).strip()
        for argument, parameter in (("soft_sort", "soft_sort"), ("next_day", "nd_en"), ("spelling", "spelling")):
            if argument in options:
                params[parameter] = "true" if parse_bool(options[argument]) else "false"
        location = resolve_location(options, domain)
        if location.get("store_id"):
            params["store_id"] = location["store_id"]
        payload = request_serpapi(params, timeout=WALMART_TIMEOUT, max_response_bytes=WALMART_MAX_RESPONSE_BYTES)
        limit = clamp_results_count(options.get("num_results", 5), default=5, maximum=10)
        results = []
        organic = payload.get("organic_results")
        for item in organic if isinstance(organic, list) else []:
            if not isinstance(item, dict) or not any(item.get(k) for k in ("title", "product_id", "us_item_id", "product_page_url")):
                continue
            row = normalize_product(item)
            row["position"] = len(results) + 1
            results.append(row)
            if len(results) >= limit:
                break
        data = result_data(payload, results, location, "walmart")
        pagination = payload.get("pagination")
        pagination = pagination if isinstance(pagination, dict) else {}
        data.update(query=query or None, cat_id=cat_id or None, walmart_domain=domain,
                    country="us" if domain == "walmart.com" else "mx", sort_by=sort or None,
                    page=page, pagination={"current": page, "has_next": bool(pagination.get("next")),
                                           "next_page": page + 1 if pagination.get("next") and page < 100 else None},
                    filters=payload.get("filters", []), related_queries=payload.get("related_queries", []))
        data["requested_filters"] = {key: params[key] for key in ("facet", "cat_id", "min_price", "max_price") if key in params}
        speech = f"Found {len(results)} Walmart products for {query or cat_id}." if results else f"No Walmart products found for {query or cat_id}."
        if location.get("note"):
            speech += " " + location["note"]
        print(json.dumps({"ok": True, "speech": speech, "data": data}))
        return 0
    except Exception as exc:
        message = f"Walmart search error: {exc}"
        print(json.dumps({"ok": False, "speech": message, "error": message}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
