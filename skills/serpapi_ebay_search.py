#!/usr/bin/env python3
"""
Jarvis Skill: SerpApi eBay search (engine=ebay).

SerpApi docs: https://serpapi.com/ebay-search-api
"""
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config
from serpapi_client import (
    clamp_results_count,
    get_proxy_enabled,
    merge_extra_params,
    parse_bool,
    request_serpapi,
)

RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "no_cache",
    "_nkw",
    "ebay_domain",
    "category_id",
    "_pgn",
    "_ipg",
    "_salic",
    "_blrs",
    "show_only",
    "buying_format",
    "_udlo",
    "_udhi",
    "_sop",
    "_dmd",
    "_stpos",
    "LH_ItemCondition",
    "LH_PrefLoc",
}

_ALLOWED_IPG = frozenset({25, 50, 100, 200})


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


def normalize_ipg(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n in _ALLOWED_IPG else None


def _clean_str(input_data: dict[str, Any], key: str) -> str:
    v = input_data.get(key)
    if v is None:
        return ""
    return str(v).strip()


def extract_ebay_search_results(payload: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    organic = payload.get("organic_results")
    if not isinstance(organic, list):
        return out

    for item in organic:
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {
            "title": item.get("title"),
            "url": item.get("link"),
            "product_id": item.get("product_id"),
            "serpapi_link": item.get("serpapi_link"),
            "condition": item.get("condition"),
            "price": item.get("price"),
            "shipping": item.get("shipping"),
            "returns": item.get("returns"),
            "thumbnail": item.get("thumbnail"),
            "sponsored": item.get("sponsored"),
            "promotion": item.get("promotion"),
            "subtitle": item.get("subtitle"),
            "seller": item.get("seller"),
            "top_rated": item.get("top_rated"),
            "rating": item.get("rating"),
            "reviews": item.get("reviews"),
            "quantity_sold": item.get("quantity_sold"),
            "extracted_quantity_sold": item.get("extracted_quantity_sold"),
            "watchers": item.get("watchers"),
            "extracted_watchers": item.get("extracted_watchers"),
            "source": "organic_results",
        }
        if not row["title"] and not row["url"] and not row["product_id"]:
            continue
        out.append(row)
        if len(out) >= limit:
            break

    return out


def build_speech(query_display: str, results: list[dict[str, Any]]) -> str:
    if not results:
        return f"No eBay listings found for '{query_display}'."

    top = results[0]
    title = (top.get("title") or "top listing").strip()
    extras: list[str] = []

    price = top.get("price")
    if isinstance(price, dict):
        if "raw" in price:
            extras.append(str(price["raw"]))
        elif "from" in price and isinstance(price["from"], dict) and price["from"].get("raw"):
            lo = price["from"].get("raw")
            hi = None
            if isinstance(price.get("to"), dict):
                hi = price["to"].get("raw")
            extras.append(f"{lo} – {hi}" if hi else str(lo))
    if top.get("condition"):
        extras.append(str(top["condition"]))

    if extras:
        return f"Found {len(results)} eBay result(s) for '{query_display}'. Top: {title}, {', '.join(extras)}."
    return f"Found {len(results)} eBay result(s) for '{query_display}'. Top: {title}."


def main() -> int:
    try:
        load_config()
        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        query = str(input_data.get("query") or input_data.get("_nkw") or "").strip()
        category_id = input_data.get("category_id")
        category_str = str(category_id).strip() if category_id not in (None, "") else ""

        ebay_domain = str(input_data.get("ebay_domain") or "ebay.com").strip() or "ebay.com"
        no_cache = parse_bool(input_data.get("no_cache", False))
        num_results = clamp_results_count(
            input_data.get("num_results", 3),
            default=3,
            maximum=5,
        )
        include_raw = parse_bool(input_data.get("include_raw", False))
        extra_params = input_data.get("extra_params", {}) or {}

        if not query and not category_str:
            return_error("Provide 'query' (eBay keywords) and/or 'category_id'.")
            return 1

        params: dict[str, Any] = {
            "engine": "ebay",
            "ebay_domain": ebay_domain,
            "no_cache": "true" if no_cache else "false",
        }
        if query:
            params["_nkw"] = query
        if category_str:
            params["category_id"] = category_str

        if _clean_str(input_data, "_salic"):
            params["_salic"] = _clean_str(input_data, "_salic")

        if input_data.get("_pgn") is not None:
            try:
                pgn = int(input_data["_pgn"])
                if pgn >= 1:
                    params["_pgn"] = pgn
            except (TypeError, ValueError):
                pass

        ipg_norm = normalize_ipg(input_data.get("_ipg"))
        if ipg_norm is not None:
            params["_ipg"] = ipg_norm

        if _clean_str(input_data, "_blrs"):
            params["_blrs"] = _clean_str(input_data, "_blrs")
        if _clean_str(input_data, "show_only"):
            params["show_only"] = _clean_str(input_data, "show_only")
        if _clean_str(input_data, "buying_format"):
            params["buying_format"] = _clean_str(input_data, "buying_format")

        for fk in ("_udlo", "_udhi"):
            if input_data.get(fk) is not None and str(input_data[fk]).strip() != "":
                params[fk] = input_data[fk]

        if _clean_str(input_data, "_sop"):
            params["_sop"] = _clean_str(input_data, "_sop")
        if _clean_str(input_data, "_dmd"):
            params["_dmd"] = _clean_str(input_data, "_dmd")
        if _clean_str(input_data, "_stpos"):
            params["_stpos"] = _clean_str(input_data, "_stpos")
        if _clean_str(input_data, "LH_ItemCondition"):
            params["LH_ItemCondition"] = _clean_str(input_data, "LH_ItemCondition")
        if _clean_str(input_data, "LH_PrefLoc"):
            params["LH_PrefLoc"] = _clean_str(input_data, "LH_PrefLoc")

        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)
        payload = request_serpapi(params)
        results = extract_ebay_search_results(payload, limit=num_results)

        q_label = query or (f"category {category_str}" if category_str else "eBay")

        data: dict[str, Any] = {
            "engine": "ebay",
            "query": query or None,
            "category_id": category_str or None,
            "ebay_domain": ebay_domain,
            "results_count": len(results),
            "results": results,
            "top_results": results[:5],
            "top_url": results[0].get("url") if results else None,
            "top_product_id": results[0].get("product_id") if results else None,
            "categories": payload.get("categories", []),
            "search_information": payload.get("search_information", {}),
            "pagination": payload.get("pagination", {}),
            "serpapi_pagination": payload.get("serpapi_pagination", {}),
            "related_searches": payload.get("related_searches", []),
            "search_metadata": payload.get("search_metadata", {}),
            "proxy_enabled": get_proxy_enabled(),
            "source": "SerpApi",
        }
        if include_raw:
            data["raw"] = payload

        return_success(build_speech(q_label, results), data=data)
        return 0

    except Exception as e:
        msg = str(e)
        if "timeout" in msg.lower():
            return_error("SerpApi eBay search timed out.")
            return 1
        return_error(f"SerpApi eBay search error: {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
