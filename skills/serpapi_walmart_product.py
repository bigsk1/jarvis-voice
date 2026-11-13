#!/usr/bin/env python3
"""Read one Walmart product and its returned review evidence through SerpApi."""
from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config
from serpapi_client import parse_bool, request_serpapi
from serpapi_walmart import (
    WALMART_MAX_RESPONSE_BYTES,
    WALMART_TIMEOUT,
    normalize_product,
    normalize_product_reference,
    read_input,
    resolve_location,
    result_data,
    validate_options,
)


def main() -> int:
    try:
        load_config()
        options = read_input(sys.argv)
        validate_options(options, search=False)
        product_id = normalize_product_reference(options.get("product_id"))
        location = resolve_location(options)
        params: dict[str, Any] = {"engine": "walmart_product", "product_id": product_id,
                                  "no_cache": "true" if parse_bool(options.get("no_cache")) else "false"}
        if location.get("store_id"):
            params["store_id"] = location["store_id"]
        payload = request_serpapi(params, timeout=WALMART_TIMEOUT, max_response_bytes=WALMART_MAX_RESPONSE_BYTES)
        item = payload.get("product_result")
        if not isinstance(item, dict) or not any(item.get(k) for k in ("title", "product_id", "us_item_id", "product_page_url")):
            raise ValueError("No product_result returned for this Walmart product ID.")
        product = normalize_product(item, detail=True)
        product["position"] = 1
        data = result_data(payload, [product], location, "walmart_product")
        data.update(product_id=product_id, product_summary=product,
                    country="us", walmart_domain="walmart.com", reviews_results=payload.get("reviews_results", {}))
        speech = f"Loaded Walmart product: {product.get('title') or product_id}."
        if location.get("note"):
            speech += " " + location["note"]
        print(json.dumps({"ok": True, "speech": speech, "data": data}))
        return 0
    except Exception as exc:
        message = f"Walmart product error: {exc}"
        print(json.dumps({"ok": False, "speech": message, "error": message}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
