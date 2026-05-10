#!/usr/bin/env python3
"""
Jarvis Skill: SerpApi Home Depot Search
Search Home Depot products through SerpApi with normalized product output.
"""
import json
import os
import sys
from typing import Any
from urllib.parse import urlparse, urlunparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config, get_config_value
from serpapi_client import (
    clamp_results_count,
    merge_extra_params,
    parse_bool,
    request_serpapi,
)


RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "q",
    "product_id",
    "country",
    "hd_sort",
    "hd_filter_tokens",
    "delivery_zip",
    "store_id",
    "store",
    "sort",
    "filter",
    "lowerbound",
    "upperbound",
    "minmax",
    "nao",
    "page",
    "ps",
    "pagesize",
    "no_cache",
}


US_SORT_MAP = {
    "top_sellers": "top_sellers",
    "best_sellers": "top_sellers",
    "bestseller": "top_sellers",
    "price_low": "price_low_to_high",
    "price_low_to_high": "price_low_to_high",
    "price_asc": "price_low_to_high",
    "price_high": "price_high_to_low",
    "price_high_to_low": "price_high_to_low",
    "price_desc": "price_high_to_low",
    "top_rated": "top_rated",
    "rating": "top_rated",
    "best_match": "best_match",
    "relevance": "best_match",
}

CA_SORT_MAP = {
    "price_low": "price-asc",
    "price_low_to_high": "price-asc",
    "price_asc": "price-asc",
    "price_high": "price-desc",
    "price_high_to_low": "price-desc",
    "price_desc": "price-desc",
    "top_rated": "reviewAvgRating",
    "rating": "reviewAvgRating",
    "recommended": "relevance",
    "relevance": "relevance",
}

HOME_DEPOT_SERPAPI_TIMEOUT = 90

# Home Depot SerpApi is slow; avoid LOCAL_PROXY — it burns full TCP timeouts per hop.
def _home_depot_serpapi(params: dict[str, Any], timeout: int = HOME_DEPOT_SERPAPI_TIMEOUT) -> dict[str, Any]:
    return request_serpapi(params, timeout=timeout, use_proxy=False, fallback_on_proxy_fail=False)


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


def _serialize_csv(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        clean = [str(item).strip() for item in value if str(item).strip()]
        return ",".join(clean) if clean else None
    text = str(value).strip()
    return text or None


def _normalize_country(value: Any) -> str:
    country = str(value or "us").strip().lower()
    return country if country in {"us", "ca"} else "us"


def get_default_postal_code() -> str:
    return get_config_value("JARVIS_DEFAULT_POSTAL_CODE", "").strip()


def normalize_sort(country: str, sort_by: Any) -> tuple[str | None, str | None]:
    if sort_by is None:
        return None, None
    raw = str(sort_by).strip()
    if not raw:
        return None, None

    lowered = raw.lower().replace(" ", "_").replace("-", "_")
    if country == "ca":
        return "sort", CA_SORT_MAP.get(lowered, raw)
    return "hd_sort", US_SORT_MAP.get(lowered, raw)


def _image_candidates(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return []

    candidates: list[str] = []
    for item in value:
        candidates.extend(_image_candidates(item))
    return candidates


def _first_image(value: Any) -> str | None:
    candidates = _image_candidates(value)
    return candidates[0] if candidates else None


def _best_image(value: Any) -> str | None:
    candidates = _image_candidates(value)
    return candidates[-1] if candidates else None


def _format_price(price: Any, currency: Any = None) -> str | None:
    if price in (None, ""):
        return None
    if isinstance(price, str):
        return price
    if currency:
        return f"{currency} {price}"
    return f"${price}"


def _normalize_brand(brand: Any) -> str | None:
    if isinstance(brand, dict):
        name = brand.get("name")
        return str(name).strip() if name else None
    if brand:
        return str(brand).strip()
    return None


def _storefront_homedepot_url(url: Any, country: str) -> str | None:
    """SerpApi often returns apionline.homedepot.com links; those 403 in a normal browser (Akamai). Use www storefront."""
    if url is None:
        return None
    if not isinstance(url, str):
        return None
    text = url.strip()
    if not text:
        return text
    try:
        parsed = urlparse(text)
    except Exception:
        return text
    host = (parsed.netloc or "").lower()
    c = (country or "us").lower()
    if host in ("apionline.homedepot.com", "apionline.homedepot.ca"):
        new_host = "www.homedepot.ca" if c == "ca" else "www.homedepot.com"
        return urlunparse(("https", new_host, parsed.path, parsed.params, parsed.query, parsed.fragment))
    if host.endswith("homedepot.com") or host.endswith("homedepot.ca"):
        if parsed.scheme == "http":
            return urlunparse(("https", parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
    return text


def extract_home_depot_results(payload: dict[str, Any], limit: int, country: str = "us") -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    products = payload.get("products") or []
    if not isinstance(products, list):
        return results

    for item in products:
        if not isinstance(item, dict):
            continue

        product = {
            "position": item.get("position"),
            "product_id": item.get("product_id"),
            "title": item.get("title"),
            "url": _storefront_homedepot_url(item.get("link"), country),
            "serpapi_link": item.get("serpapi_link"),
            "model_number": item.get("model_number"),
            "brand": item.get("brand"),
            "price": item.get("price"),
            "price_formatted": _format_price(item.get("price"), item.get("currency")),
            "price_was": item.get("price_was"),
            "price_saving": item.get("price_saving"),
            "percentage_off": item.get("percentage_off") or item.get("percent_off"),
            "price_badge": item.get("price_badge"),
            "currency": item.get("currency"),
            "rating": item.get("rating"),
            "reviews": item.get("reviews"),
            "thumbnail": _first_image(item.get("thumbnails")),
            "image_url": _best_image(item.get("thumbnails")),
            "thumbnails": item.get("thumbnails"),
            "delivery": item.get("delivery"),
            "pickup": item.get("pickup"),
            "stock_information": item.get("stock_information"),
            "badges": item.get("badges"),
            "variants": item.get("variants"),
            "source": "products",
        }
        if not product["title"] and not product["url"] and not product["product_id"]:
            continue
        results.append(product)
        if len(results) >= limit:
            break
    return results


def extract_home_depot_product(payload: dict[str, Any], country: str = "us") -> dict[str, Any] | None:
    item = payload.get("product_results")
    if not isinstance(item, dict) or not item:
        return None

    product = {
        "product_id": item.get("product_id"),
        "title": item.get("title"),
        "description": item.get("description"),
        "url": _storefront_homedepot_url(item.get("link"), country),
        "upc": item.get("upc"),
        "model_number": item.get("model_number"),
        "store_sku_number": item.get("store_sku_number"),
        "brand": _normalize_brand(item.get("brand")),
        "price": item.get("price"),
        "price_formatted": _format_price(item.get("price"), item.get("currency")),
        "currency": item.get("currency"),
        "rating": item.get("rating"),
        "reviews": item.get("reviews"),
        "thumbnail": _first_image(item.get("images")),
        "image_url": _best_image(item.get("images")),
        "images": item.get("images"),
        "highlights": item.get("highlights"),
        "bullets": item.get("bullets"),
        "specifications": item.get("specifications"),
        "info_and_guides": item.get("info_and_guides"),
        "source": "product_results",
    }
    if not product["title"] and not product["url"] and not product["product_id"]:
        return None
    return product


def build_product_params(product_id: str, delivery_zip: str, store_id: str) -> dict[str, Any]:
    params: dict[str, Any] = {
        "engine": "home_depot_product",
        "product_id": product_id,
        "no_cache": "false",
    }
    if delivery_zip:
        params["delivery_zip"] = delivery_zip
    if store_id:
        params["store_id"] = store_id
    return params


def build_speech(query: str, results: list[dict[str, Any]]) -> str:
    if not results:
        return f"No Home Depot results found for '{query}'."

    top = results[0]
    title = (top.get("title") or "top product").strip()
    details = []
    if top.get("price_formatted"):
        details.append(str(top["price_formatted"]))
    if top.get("rating") is not None:
        details.append(f"rated {top['rating']}")

    if details:
        return f"Found {len(results)} Home Depot result(s) for '{query}'. Top result: {title}, {', '.join(details)}."
    return f"Found {len(results)} Home Depot result(s) for '{query}'. Top result: {title}."


def main() -> int:
    try:
        load_config()

        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        query = str(input_data.get("query") or input_data.get("q") or "").strip()
        product_id = str(input_data.get("product_id", "")).strip()
        country = _normalize_country(input_data.get("country", "us"))
        sort_by = input_data.get("sort_by")
        hd_filter_tokens = _serialize_csv(input_data.get("hd_filter_tokens"))
        ca_filter = str(input_data.get("filter", "")).strip()
        delivery_zip = str(input_data.get("delivery_zip", "")).strip()
        if country == "us" and not delivery_zip:
            delivery_zip = get_default_postal_code()
        store_id = str(input_data.get("store_id", "")).strip()
        store = str(input_data.get("store", "")).strip()
        lowerbound = input_data.get("lowerbound")
        upperbound = input_data.get("upperbound")
        minmax = str(input_data.get("minmax", "")).strip()
        nao = input_data.get("nao")
        page = input_data.get("page")
        ps = input_data.get("ps")
        pagesize = input_data.get("pagesize")
        num_results = clamp_results_count(input_data.get("num_results", 5), default=5)
        include_product_details = parse_bool(input_data.get("include_product_details", False), default=False)
        include_raw = parse_bool(input_data.get("include_raw", False))
        extra_params = input_data.get("extra_params", {}) or {}

        if not query and not product_id:
            return_error("Provide 'query' for search or 'product_id' for a focused Home Depot product lookup.")
            return 1

        if product_id and not query:
            product_payload = _home_depot_serpapi(build_product_params(product_id, delivery_zip, store_id))
            product = extract_home_depot_product(product_payload, country=country)
            results = [product] if product else []
            data: dict[str, Any] = {
                "engine": "home_depot_product",
                "product_id": product_id,
                "country": country,
                "results_count": len(results),
                "results": results,
                "top_results": results[:1],
                "top_url": product.get("url") if product else None,
                "top_image_url": product.get("image_url") if product else None,
                "product_details": product,
                "search_metadata": product_payload.get("search_metadata", {}),
                "search_information": product_payload.get("search_information", {}),
                "proxy_enabled": False,
                "source": "SerpApi",
            }
            if include_raw:
                data["raw"] = product_payload
            return_success(build_speech(product_id, results), data=data)
            return 0

        params: dict[str, Any] = {
            "engine": "home_depot",
            "q": query,
            "country": country,
            "no_cache": "false",
        }

        sort_key, sort_value = normalize_sort(country, sort_by)
        if sort_key and sort_value:
            params[sort_key] = sort_value

        if country == "ca":
            if store:
                params["store"] = store
            if ca_filter:
                params["filter"] = ca_filter
            if minmax:
                params["minmax"] = minmax
            if pagesize is not None:
                params["pagesize"] = pagesize
        else:
            if hd_filter_tokens:
                params["hd_filter_tokens"] = hd_filter_tokens
            if delivery_zip:
                params["delivery_zip"] = delivery_zip
            if store_id:
                params["store_id"] = store_id
            if lowerbound is not None:
                params["lowerbound"] = lowerbound
            if upperbound is not None:
                params["upperbound"] = upperbound
            if nao is not None:
                params["nao"] = nao
            if ps is not None:
                params["ps"] = ps

        if page is not None:
            params["page"] = page

        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)
        payload = _home_depot_serpapi(params)
        results = extract_home_depot_results(payload, limit=num_results, country=country)
        product_details = None
        product_details_error = None
        selected_product_id = product_id or (str(results[0].get("product_id")) if results and results[0].get("product_id") else "")

        if include_product_details and country == "us" and selected_product_id:
            try:
                product_payload = _home_depot_serpapi(
                    build_product_params(selected_product_id, delivery_zip, store_id),
                )
                product_details = extract_home_depot_product(product_payload, country=country)
                if product_details and results:
                    results[0] = {**results[0], **{k: v for k, v in product_details.items() if v not in (None, "", [], {})}}
            except Exception as e:
                product_details_error = str(e)

        data: dict[str, Any] = {
            "engine": "home_depot",
            "query": query,
            "country": country,
            "sort_by": sort_by,
            "include_product_details": include_product_details,
            "results_count": len(results),
            "results": results,
            "top_results": results[:5],
            "top_url": results[0].get("url") if results else None,
            "product_id": results[0].get("product_id") if results else None,
            "top_image_url": (results[0].get("image_url") or results[0].get("thumbnail")) if results else None,
            "product_details": product_details,
            "filters": payload.get("filters", []),
            "pagination": payload.get("pagination", {}),
            "serpapi_pagination": payload.get("serpapi_pagination", {}),
            "search_metadata": payload.get("search_metadata", {}),
            "search_information": payload.get("search_information", {}),
            "proxy_enabled": False,
            "source": "SerpApi",
        }
        if product_details_error:
            data["product_details_error"] = product_details_error
        if include_raw:
            data["raw"] = payload

        return_success(build_speech(query, results), data=data)
        return 0

    except Exception as e:
        msg = str(e)
        if "timeout" in msg.lower():
            return_error("SerpApi Home Depot search timed out.")
            return 1
        return_error(f"SerpApi Home Depot search error: {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
