"""Shared Walmart product normalization and exact ZIP-to-store resolution."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import requests
from config_loader import get_config_value
from http_client import http_request

WALMART_TIMEOUT = 60
WALMART_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
WALMART_STORES_URL = "https://serpapi.com/walmart-stores.json"


class _DescriptionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"br", "p", "li", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"p", "li", "div"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def description_text(value: Any) -> str:
    """Convert provider HTML descriptions to inert, readable text."""
    if not isinstance(value, str):
        return ""
    parser = _DescriptionParser()
    parser.feed(value)
    return "\n".join(" ".join(line.split()) for line in "".join(parser.parts).splitlines()
                     if line.strip())


def normalize_product_reference(value: Any) -> str:
    """Accept Walmart's product ID, numeric US item ID, or a US /ip/ URL."""
    text = str(value or "").strip()
    if text.lower().startswith(("http://", "https://")):
        parsed = urlparse(text)
        if (parsed.hostname not in {"walmart.com", "www.walmart.com"}
                or parsed.username or parsed.password or parsed.port not in {None, 80, 443}):
            raise ValueError("Provide a Walmart.com /ip/ product URL or a Walmart product ID.")
        match = re.fullmatch(r"/ip/(?:[^/]+/)?([A-Za-z0-9]{1,32})/?", parsed.path)
        if not match:
            raise ValueError("Walmart product URLs must contain an /ip/ product ID.")
        text = match.group(1)
    if not re.fullmatch(r"[A-Za-z0-9]{1,32}", text):
        raise ValueError("Provide a Walmart product_id, numeric us_item_id, or Walmart.com /ip/ URL.")
    return text


def _load_stores() -> list[dict[str, Any]]:
    response = http_request("GET", WALMART_STORES_URL, timeout=10, stream=True)
    try:
        response.raise_for_status()
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(chunk_size=65536):
            size += len(chunk)
            if size > WALMART_MAX_RESPONSE_BYTES:
                raise ValueError("Walmart store directory exceeds the size limit.")
            chunks.append(chunk)
        rows = json.loads(b"".join(chunks))
        if not isinstance(rows, list):
            raise ValueError("Invalid Walmart store directory.")
        return [row for row in rows if isinstance(row, dict)]
    finally:
        response.close()


def resolve_location(options: dict[str, Any], domain: str = "walmart.com") -> dict[str, Any]:
    """Resolve US ZIP defaults without pretending an unmatched ZIP was applied."""
    explicit_store = str(options.get("store_id") or "").strip()
    default_store = get_config_value("JARVIS_WALMART_STORE_ID", "").strip() if domain == "walmart.com" else ""
    explicit_postal = str(options.get("postal_code") or "").strip()
    postal = explicit_postal or (
        get_config_value("JARVIS_DEFAULT_POSTAL_CODE", "").strip() if domain == "walmart.com" else ""
    )
    result: dict[str, Any] = {"requested_postal_code": postal or None}
    # A ZIP supplied for this call overrides a configured store in another ZIP.
    store = explicit_store or (default_store if not explicit_postal else "")
    if store:
        if not store.isdigit() or len(store) > 10:
            raise ValueError("store_id must be a numeric Walmart store ID.")
        result.update(store_id=store, source="explicit_store" if explicit_store else "configured_store")
        return result
    if not postal:
        result.update(store_id=None, source="provider_default",
                      note="No store selected; prices and availability use Walmart's returned location.")
        return result
    if domain != "walmart.com":
        raise ValueError("For Walmart Mexico, specify store_id instead of postal_code.")
    if not re.fullmatch(r"\d{5}(?:-\d{4})?", postal):
        raise ValueError("postal_code must be a US ZIP code; use store_id for other locations.")
    zip_code = postal[:5]
    try:
        rows = _load_stores()
        matches = [row for row in rows
                   if str(row.get("postal_code") or "") == zip_code
                   and str(row.get("country") or "US").upper() == "US"
                   and not str(row.get("address") or "").rstrip().upper().endswith(", MX")
                   and str(row.get("store_id") or "").isdigit()]
        matches.sort(key=lambda row: int(row["store_id"]))
    except (requests.RequestException, ValueError):
        result.update(store_id=None, source="provider_default",
                      note="ZIP-to-store lookup unavailable; requested ZIP was not applied. "
                           "Prices and availability use Walmart's returned location; specify store_id for local results.")
        return result
    if matches:
        result.update(store_id=str(matches[0]["store_id"]), source="postal_code",
                      store_address=matches[0].get("address"), matching_stores=len(matches))
        result["note"] = f"Using Walmart store {result['store_id']}"
        if result.get("store_address"):
            result["note"] += f" at {result['store_address']}"
        result["note"] += "."
        if len(matches) > 1:
            result["note"] += f" Selected one of {len(matches)} matching stores in ZIP {zip_code}; specify store_id to choose another."
    else:
        result.update(store_id=None, source="provider_default",
                      note="No supported Walmart store matches the requested ZIP exactly; ZIP was not applied. "
                           "Prices and availability use Walmart's returned location; specify store_id for local results.")
    return result


def normalize_product(item: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
    """Keep shopping identities, images, offers and factual fulfillment fields."""
    offer = item.get("price_map" if detail else "primary_offer")
    offer = offer if isinstance(offer, dict) else {}
    price = offer.get("price" if detail else "offer_price")
    currency = offer.get("currency")
    images = item.get("images") if detail else [item.get("thumbnail")]
    images = [image for image in images if isinstance(image, str) and image] if isinstance(images, list) else []
    row = {key: item[key] for key in (
        "product_id", "us_item_id", "upc", "title", "rating", "reviews", "seller_id",
        "seller_name", "sponsored", "in_stock", "out_of_stock", "quantity", "two_day_shipping", "free_shipping",
        "free_shipping_with_walmart_plus", "special_offer_text", "price_per_unit", "badges",
        "manufacturer", "manufacture_number", "product_type", "variants", "offers", "variant_swatches",
        "shipping_option", "pickup_option", "delivery_option", "warranty", "ingredients",
        "active_ingredients", "inactive_ingredients", "warnings",
    ) if key in item}
    row.update(url=item.get("product_page_url"), price=price, currency=currency,
               price_formatted=f"{currency} {price}" if currency and price is not None else None,
               price_was=offer.get("was_price"), thumbnail=images[0] if images else None,
               image_url=images[0] if images else None, images=images,
               source="product_result" if detail else "organic_results")
    if detail:
        row["description"] = description_text(item.get("detailed_description_html") or item.get("short_description_html"))
        row["specifications"] = item.get("specification_highlights") or []
    elif item.get("description"):
        row["description"] = description_text(item["description"])
    return row


def read_input(argv: list[str]) -> dict[str, Any]:
    """Parse the standard local-tool argument object."""
    value = json.loads(argv[1]) if len(argv) > 1 else {}
    if not isinstance(value, dict):
        raise ValueError("Tool input must be a JSON object.")
    return value


def validate_options(options: dict[str, Any], *, search: bool) -> None:
    """Reject malformed arguments before a paid provider request is made."""
    string_keys = {"store_id", "postal_code"}
    bool_keys = {"no_cache"}
    numeric_keys: set[str] = set()
    integer_keys: set[str] = set()
    if search:
        string_keys |= {"query", "cat_id", "sort_by", "facet", "walmart_domain"}
        bool_keys |= {"soft_sort", "next_day", "spelling"}
        numeric_keys |= {"min_price", "max_price"}
        integer_keys |= {"page", "num_results"}
    else:
        string_keys.add("product_id")
    unknown = options.keys() - string_keys - bool_keys - numeric_keys - integer_keys
    if unknown:
        raise ValueError("Unknown Walmart tool argument. Use the declared tool parameters.")
    for key, value in options.items():
        if key in string_keys and not isinstance(value, str):
            raise ValueError(f"{key} must be a string.")
        if key in bool_keys and type(value) is not bool:
            raise ValueError(f"{key} must be a boolean.")
        if key in integer_keys and type(value) is not int:
            raise ValueError(f"{key} must be an integer.")
        if key in numeric_keys and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError(f"{key} must be a number.")


def result_data(payload: dict[str, Any], results: list[dict[str, Any]],
                location: dict[str, Any], engine: str) -> dict[str, Any]:
    """Build the common shopping envelope without leaking provider request URLs."""
    metadata = payload.get("search_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    top = results[0] if results else {}
    return {
        "engine": engine, "source": "SerpApi", "results": results, "top_results": results[:5],
        "results_count": len(results), "top_url": top.get("url"),
        "top_product_id": top.get("product_id") or top.get("us_item_id"),
        "top_image_url": top.get("image_url"), "store_id": location.get("store_id"),
        "location_context": location, "search_information": payload.get("search_information", {}),
        "search_metadata": {key: metadata[key] for key in ("id", "status", "created_at", "processed_at") if key in metadata},
    }
