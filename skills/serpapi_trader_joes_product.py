#!/usr/bin/env python3
"""Read a Trader Joe's product, including ingredients and nutrition panels."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from config_loader import load_config
from serpapi_client import request_serpapi
from serpapi_trader_joes import (
    TRADER_JOES_MAX_RESPONSE_BYTES,
    TRADER_JOES_TIMEOUT,
    normalize_product,
    normalize_product_reference,
    read_input,
    resolve_location,
    result_data,
    validate_options,
    validate_payload,
)


def product(options: dict[str, Any]) -> dict[str, Any]:
    validate_options(options, search=False)
    product_id = normalize_product_reference(options.get("product_id"))
    location = resolve_location(options)
    params = {"engine": "trader_joes_product", "product_id": product_id,
              "no_cache": "true" if options.get("no_cache", False) else "false"}
    if location["store_id"]:
        params["store_id"] = location["store_id"]
    payload = validate_payload(request_serpapi(
        params, timeout=TRADER_JOES_TIMEOUT, max_response_bytes=TRADER_JOES_MAX_RESPONSE_BYTES,
        use_proxy=False, fallback_on_proxy_fail=False,
    ), "trader_joes_product")
    item = payload.get("product_results")
    if not isinstance(item, dict) or not item:
        raise ValueError("No product_results returned for this Trader Joe's SKU.")
    row = normalize_product(item, detail=True)
    if not row["product_id"]:
        raise ValueError("Trader Joe's product response did not include a usable SKU.")
    row["position"] = 1
    data = result_data(payload, [row], location, "trader_joes_product")
    data.update(query=None, product_id=product_id, product_summary=row, requested_filters={})
    speech = f"Loaded Trader Joe's product: {row.get('title') or product_id}. {location['note']}"
    return {"ok": True, "speech": speech, "data": data}


def main() -> int:
    try:
        load_config()
        result = product(read_input(sys.argv))
    except (ValueError, RuntimeError, OSError) as exc:
        message = f"Trader Joe's product error: {exc}"
        result = {"ok": False, "speech": message, "error": message}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
