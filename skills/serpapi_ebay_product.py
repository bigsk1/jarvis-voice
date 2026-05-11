#!/usr/bin/env python3
"""
Jarvis Skill: SerpApi eBay product page (engine=ebay_product).

SerpApi docs: https://serpapi.com/ebay-product-api

Returns a compact summary by default; set include_raw for the full SerpApi JSON.
"""
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config
from serpapi_client import (
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
    "product_id",
    "ebay_domain",
    "locale",
    "lang",
    "shipping_country",
}

RELATED_LIMIT = 12


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


def _first_product_images(media: Any, limit: int = 8) -> list[str]:
    """Collect one URL per image block, preferring the largest rendition (last in SerpApi size list)."""
    urls: list[str] = []
    if not isinstance(media, list):
        return urls
    for block in media:
        if not isinstance(block, dict) or block.get("type") != "image":
            continue
        imgs = block.get("image")
        link: str | None = None
        if isinstance(imgs, list) and imgs:
            last = imgs[-1]
            if isinstance(last, dict):
                raw = last.get("link")
                link = raw if isinstance(raw, str) and raw else None
        elif isinstance(imgs, dict):
            raw = imgs.get("link")
            link = raw if isinstance(raw, str) and raw else None
        if link:
            urls.append(link)
        if len(urls) >= limit:
            break
    return urls[:limit]


def _compact_buy(buy: Any) -> dict[str, Any] | None:
    if not isinstance(buy, dict) or not buy:
        return None
    out: dict[str, Any] = {"options": buy.get("options")}
    if isinstance(buy.get("buy_it_now"), dict):
        out["buy_it_now"] = buy["buy_it_now"]
    if isinstance(buy.get("bid"), dict):
        bid = buy["bid"]
        out["bid"] = {
            "price": bid.get("price"),
            "bid_count": bid.get("bid_count"),
            "auction_end_datetime": bid.get("auction_end_datetime"),
            "reserve_price_not_met": bid.get("reserve_price_not_met"),
        }
    return out


def _compact_seller(sr: Any) -> dict[str, Any] | None:
    if not isinstance(sr, dict) or not sr:
        return None
    return {
        "type": sr.get("type"),
        "name": sr.get("name"),
        "username": sr.get("username"),
        "sold_count": sr.get("sold_count"),
        "rating": sr.get("rating"),
        "positive_feedback": sr.get("positive_feedback"),
        "profile_link": sr.get("profile_link"),
    }


def extract_ebay_product_summary(payload: dict[str, Any]) -> dict[str, Any] | None:
    pr = payload.get("product_results")
    if not isinstance(pr, dict) or not pr:
        return None

    shipping = pr.get("shipping") if isinstance(pr.get("shipping"), dict) else {}
    var_block = pr.get("variations")
    var_hint: dict[str, int] = {}
    if isinstance(var_block, dict):
        menus = var_block.get("menus") or []
        combos = var_block.get("combinations") or []
        if isinstance(menus, list):
            var_hint["variation_menus"] = len(menus)
        if isinstance(combos, list):
            var_hint["variation_combinations"] = len(combos)

    summary: dict[str, Any] = {
        "product_id": pr.get("product_id"),
        "title": pr.get("title"),
        "url": pr.get("product_link"),
        "subtitle": pr.get("subtitle"),
        "short_description": pr.get("short_description"),
        "condition": pr.get("condition"),
        "rating": pr.get("rating"),
        "review_count": pr.get("review_count"),
        "watch_count": pr.get("watch_count"),
        "banner_status": pr.get("banner_status"),
        "buy": _compact_buy(pr.get("buy")),
        "coupon": pr.get("coupon"),
        "shipping": {
            "status": shipping.get("status"),
            "from": shipping.get("from"),
            "to": shipping.get("to"),
        },
        "quantity": pr.get("quantity"),
        "image_urls": _first_product_images(pr.get("media")),
        "categories": pr.get("categories"),
        "variation_counts": var_hint or None,
        "vehicle_report": pr.get("vehicle_report"),
        "source": "product_results",
    }
    if not summary["title"] and not summary["url"] and not summary["product_id"]:
        return None
    return summary


def _compact_related(items: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return out
    for it in items[:RELATED_LIMIT]:
        if not isinstance(it, dict):
            continue
        out.append(
            {
                "product_id": it.get("product_id"),
                "title": it.get("title"),
                "url": it.get("product_link"),
                "price": it.get("price"),
                "image_link": it.get("image_link"),
                "condition": it.get("condition"),
            }
        )
    return out


def build_product_speech(summary: dict[str, Any]) -> str:
    title = (summary.get("title") or "item").strip()
    pid = summary.get("product_id")
    bits: list[str] = []
    buy = summary.get("buy")
    if isinstance(buy, dict):
        if isinstance(buy.get("buy_it_now"), dict):
            p = buy["buy_it_now"].get("price")
            if isinstance(p, dict) and p.get("amount") is not None:
                cur = p.get("currency") or ""
                bits.append(f"Buy It Now {cur} {p['amount']}".strip())
        if isinstance(buy.get("bid"), dict):
            p = buy["bid"].get("price")
            if isinstance(p, dict) and p.get("amount") is not None:
                bits.append(f"current bid {p.get('currency', '')} {p['amount']}".strip())
    if summary.get("condition"):
        bits.append(str(summary["condition"]))

    base = f"Loaded eBay product {title}"
    if pid:
        base += f" (id {pid})"
    if bits:
        return f"{base}: {', '.join(bits)}."
    return f"{base}."


def main() -> int:
    try:
        load_config()
        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        product_id = str(input_data.get("product_id", "")).strip()
        if not product_id:
            return_error("Parameter 'product_id' is required (eBay item id from /itm/{id}).")
            return 1

        ebay_domain = str(input_data.get("ebay_domain") or "ebay.com").strip() or "ebay.com"
        locale = str(input_data.get("locale", "")).strip()
        lang = str(input_data.get("lang", "")).strip()
        shipping_country = str(input_data.get("shipping_country", "")).strip()
        no_cache = parse_bool(input_data.get("no_cache", False))
        include_raw = parse_bool(input_data.get("include_raw", False))
        extra_params = input_data.get("extra_params", {}) or {}

        params: dict[str, Any] = {
            "engine": "ebay_product",
            "product_id": product_id,
            "ebay_domain": ebay_domain,
            "no_cache": "true" if no_cache else "false",
        }
        if locale:
            params["locale"] = locale
        if lang:
            params["lang"] = lang
        if shipping_country:
            params["shipping_country"] = shipping_country

        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)
        payload = request_serpapi(params)
        summary = extract_ebay_product_summary(payload)
        if not summary:
            return_error(f"No product_results in SerpApi response for product_id {product_id}.")
            return 1

        seller = _compact_seller(payload.get("seller_results"))
        related = _compact_related(payload.get("related_products"))

        thumbs = summary.get("image_urls") or []
        thumb0 = thumbs[0] if thumbs else None
        compact_row = {
            "title": summary.get("title"),
            "url": summary.get("url"),
            "product_id": summary.get("product_id"),
            "thumbnail": thumb0,
        }

        data: dict[str, Any] = {
            "engine": "ebay_product",
            "product_id": product_id,
            "ebay_domain": ebay_domain,
            "product_summary": summary,
            "seller_summary": seller,
            "related_products": related,
            "results_count": 1,
            "results": [compact_row],
            "top_results": [compact_row],
            "top_url": compact_row.get("url"),
            "top_product_id": compact_row.get("product_id"),
            "top_image_url": thumb0,
            "search_metadata": payload.get("search_metadata", {}),
            "search_parameters": payload.get("search_parameters", {}),
            "proxy_enabled": get_proxy_enabled(),
            "source": "SerpApi",
        }
        if include_raw:
            data["raw"] = payload

        return_success(build_product_speech(summary), data=data)
        return 0

    except Exception as e:
        msg = str(e)
        if "timeout" in msg.lower():
            return_error("SerpApi eBay product lookup timed out.")
            return 1
        return_error(f"SerpApi eBay product error: {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
