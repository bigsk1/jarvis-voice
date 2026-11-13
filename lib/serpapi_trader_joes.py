"""Trader Joe's product normalization and validated, exact store selection."""
from __future__ import annotations

import json
import math
import re
from typing import Any
from urllib.parse import urlsplit

import requests
from config_loader import get_config_value
from http_client import http_request

TRADER_JOES_TIMEOUT = 60
TRADER_JOES_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
TRADER_JOES_STORES_URL = "https://serpapi.com/trader-joes-stores.json"
CHARACTERISTICS = (
    "kosher", "organic", "gluten_free", "vegan", "antibiotic_free", "dairy_free",
    "grass_fed", "vegetarian", "fair_trade",
)
CHARACTERISTIC_LABELS = {identifier: identifier.replace("_", " ").title() for identifier in CHARACTERISTICS}
TAG_LABELS = {
    "a_long_finish": "A Long Finish", "alfresco_dining": "Alfresco Dining",
    "backpack_ready": "Backpack Ready", "bibulous": "Bibulous", "brunch_all_day": "Brunch All Day",
    "chance_of_rain": "Chance of Rain", "cheese_board": "Cheese Board", "cold_front": "Cold Front",
    "crack_a_beer": "Crack a Beer", "cut_the_mustard": "Cut The Mustard", "date_night": "Date Night",
    "desk_drawer": "Desk Drawer", "dinner_hack": "Dinner Hack",
    "effortless_entertaining": "Effortless Entertaining", "fall_faves": "Fall Faves",
    "family_style": "Family Style", "feeling_adventurous": "Feeling Adventurous",
    "feeling_fancy": "Feeling Fancy", "finger_food": "Finger Food", "fire_up_the_grill": "Fire Up The Grill",
    "fry_it_up": "Fry It Up", "game_night": "Game Night", "giftable": "Giftable",
    "gild_the_lily": "Gild The Lily", "glass_half_full": "Glass Half Full", "heat_wave": "Heat Wave",
    "in_lieu_of_pizza": "In Lieu of Pizza", "lets_bake": "Let's Bake!", "make_it_meatless": "Make It Meatless",
    "merry_making": "Merry-making", "midday_snacks": "Midday Snacks", "mouth_on_fire": "Mouth On Fire",
    "pair_with_wine": "Pair With Wine", "picnic": "Picnic", "pour_it_on": "Pour It On",
    "put_an_egg_on_it": "Put An Egg On It", "rain_or_shine": "Rain or Shine", "rise_and_shine": "Rise & Shine",
    "stuff_of_dreams": "Stuff of Dreams", "the_x_factor": 'The "X" Factor', "time_pressed": "Time-pressed",
    "treat_yourself": "Treat Yourself", "unexpected": "Unexpected", "welcoming": "Welcoming", "yes": "Yes!",
}
FILTER_ALIASES = {
    name: {alias.casefold(): identifier for identifier, label in labels.items() for alias in (identifier, label)}
    for name, labels in (("characteristics", CHARACTERISTIC_LABELS), ("tags", TAG_LABELS))
}
SORT_OPTIONS = ("price_low_to_high", "price_high_to_low", "popularity")
AVAILABILITY_NOTE = (
    "Store availability means the product is sold by that store; it does not establish current stock."
)


def _storefront_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    if any(character.isspace() or ord(character) < 32 for character in value):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"}
                or parsed.hostname not in {"traderjoes.com", "www.traderjoes.com"}
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in {None, 80, 443}):
            return None
    except ValueError:
        return None
    return value


def normalize_product_reference(value: Any) -> str:
    """Keep the exact string SKU, including its leading zeroes."""
    if not isinstance(value, str):
        raise ValueError("product_id must be a string SKU or a Trader Joe's product URL.")
    reference = value.strip()
    if reference.startswith(("http://", "https://")):
        if not _storefront_url(reference):
            raise ValueError("Provide a public TraderJoes.com product URL without credentials.")
        match = re.fullmatch(r"/home/products/pdp/(?:[^/]*-)?([0-9]{1,32})/?", urlsplit(reference).path)
        if not match:
            raise ValueError("Trader Joe's product URLs must contain a /home/products/pdp/ SKU.")
        reference = match.group(1)
    if not re.fullmatch(r"[0-9]{1,32}", reference):
        raise ValueError("Provide a numeric Trader Joe's SKU string, preserving its leading zeroes.")
    return reference


def read_input(argv: list[str]) -> dict[str, Any]:
    value = json.loads(argv[1]) if len(argv) > 1 else {}
    if not isinstance(value, dict):
        raise ValueError("Tool input must be a JSON object.")
    return value


def canonical_filter_values(values: list[str], kind: str) -> list[str]:
    """Accept documented display labels while sending exact provider filter IDs."""
    selected = []
    for value in values:
        identifier = FILTER_ALIASES[kind].get(" ".join(value.split()).casefold())
        if identifier is None and kind == "tags" and re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", value):
            identifier = value
        if identifier is None or len(value) > 80:
            raise ValueError(f"Use documented Trader Joe's {kind} identifiers or display labels.")
        if identifier not in selected:
            selected.append(identifier)
    return selected


def validate_options(options: dict[str, Any], *, search: bool) -> None:
    strings = {"store_id", "postal_code"}
    booleans = {"no_cache"}
    integers: set[str] = set()
    arrays: set[str] = set()
    if search:
        strings |= {"query", "category_id", "sort_by"}
        booleans.add("new_products")
        integers |= {"page", "num_results"}
        arrays |= {"characteristics", "tags"}
    else:
        strings.add("product_id")
    if options.keys() - strings - booleans - integers - arrays:
        raise ValueError("Unknown Trader Joe's argument; use the declared tool parameters.")
    for key, value in options.items():
        if key in strings and not isinstance(value, str):
            raise ValueError(f"{key} must be a string.")
        if key in booleans and type(value) is not bool:
            raise ValueError(f"{key} must be a boolean.")
        if key in integers and type(value) is not int:
            raise ValueError(f"{key} must be an integer.")
        if key in arrays:
            maximum = len(CHARACTERISTICS) if key == "characteristics" else 20
            if (not isinstance(value, list) or len(value) > maximum
                    or any(not isinstance(item, str) for item in value)):
                raise ValueError(f"{key} must be an array of at most {maximum} strings.")
            canonical_filter_values(value, key)
    if "store_id" in options and not re.fullmatch(r"[0-9]{1,10}", options["store_id"]):
        raise ValueError("store_id must be a supported numeric Trader Joe's store ID string.")
    if "postal_code" in options and not re.fullmatch(r"[0-9]{5}(?:-[0-9]{4})?", options["postal_code"]):
        raise ValueError("postal_code must be a US ZIP code.")
    if search:
        if not options.get("query", "").strip() or len(options["query"]) > 400:
            raise ValueError("query must contain 1 to 400 characters.")
        if "category_id" in options and not re.fullmatch(r"[0-9]{1,20}", options["category_id"]):
            raise ValueError("category_id must be a numeric category ID string from Trader Joe's.")
        if "sort_by" in options and options["sort_by"] not in SORT_OPTIONS:
            raise ValueError("Unsupported Trader Joe's sort_by value.")
        if not 1 <= options.get("page", 1) <= 100:
            raise ValueError("page must be an integer from 1 to 100.")


def _load_stores() -> list[dict[str, Any]]:
    response = http_request(
        "GET", TRADER_JOES_STORES_URL, timeout=10, stream=True,
        allow_redirects=False, use_proxy=False, fallback_on_proxy_fail=False,
    )
    try:
        if response.status_code != 200:
            raise ValueError("Trader Joe's store directory unavailable.")
        body = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            if len(body) + len(chunk) > TRADER_JOES_MAX_RESPONSE_BYTES:
                raise ValueError("Trader Joe's store directory exceeded its size limit.")
            body.extend(chunk)
        payload = json.loads(body)
        if not isinstance(payload, list):
            raise ValueError("Trader Joe's store directory is invalid.")
        rows = [row for row in payload if isinstance(row, dict)
                and re.fullmatch(r"[0-9]{1,10}", str(row.get("store_id", "")))]
        if not rows:
            raise ValueError("Trader Joe's store directory contains no supported stores.")
        return rows
    finally:
        response.close()


def _selected_store(row: dict[str, Any], source: str, requested_postal: str,
                    *, matching_stores: int = 1) -> dict[str, Any]:
    store_id = str(row["store_id"])
    address = ", ".join(str(row[key]).strip() for key in ("address", "city", "state", "postal_code")
                        if row.get(key) not in (None, ""))
    name = str(row.get("name") or "").strip()
    note = f"Selected Trader Joe's store {store_id}"
    note += f" ({name})" if name else ""
    note += f" at {address}." if address else "."
    if source == "postal_code" and matching_stores > 1:
        note += f" {matching_stores} stores match ZIP {requested_postal[:5]}; selected the lowest store ID."
    return {
        "store_id": store_id, "source": source, "requested_postal_code": requested_postal or None,
        "store_name": name or None, "store_address": address or None,
        "store_postal_code": str(row.get("postal_code") or "") or None,
        "matching_stores": matching_stores, "note": note,
    }


def resolve_location(options: dict[str, Any]) -> dict[str, Any]:
    """Validate selected IDs because the provider silently ignores unknown stores."""
    explicit_store = options.get("store_id", "").strip()
    explicit_postal = options.get("postal_code", "").strip()
    default_store = str(get_config_value("JARVIS_TRADER_JOES_STORE_ID", "") or "").strip()
    postal = explicit_postal or str(get_config_value("JARVIS_DEFAULT_POSTAL_CODE", "") or "").strip()
    store = explicit_store or (default_store if not explicit_postal else "")
    source = "explicit_store" if explicit_store else "configured_store"
    base = {"store_id": None, "source": "provider_default", "requested_postal_code": postal or None}
    if not store and not postal:
        return {**base, "note": "No store selected; results cover Trader Joe's all-store catalog."}
    if store and not re.fullmatch(r"[0-9]{1,10}", store):
        raise ValueError("Configured Trader Joe's store ID must be a supported numeric store ID.")
    if not store and not re.fullmatch(r"[0-9]{5}(?:-[0-9]{4})?", postal):
        if explicit_postal:
            raise ValueError("postal_code must be a US ZIP code.")
        return {**base, "note": "Configured postal code is not a US ZIP and was not applied. "
                               "Results cover the all-store catalog; no local availability is established."}
    try:
        rows = _load_stores()
    except (requests.RequestException, ValueError, OSError):
        if store:
            raise ValueError("Trader Joe's store validation is unavailable; no store-specific request was made.") from None
        return {**base, "note": "ZIP-to-store lookup unavailable; requested ZIP was not applied. "
                               "Results cover the all-store catalog; no local availability is established."}
    if store:
        selected = next((row for row in rows if str(row["store_id"]) == store), None)
        if selected is None:
            raise ValueError("Trader Joe's store ID is not in the supported store directory; no request was made.")
        return _selected_store(selected, source, postal)
    matches = [row for row in rows if str(row.get("postal_code") or "") == postal[:5]]
    matches.sort(key=lambda row: (int(row["store_id"]), str(row["store_id"])))
    if matches:
        return _selected_store(matches[0], "postal_code", postal, matching_stores=len(matches))
    return {**base, "note": "No supported Trader Joe's store matches the requested ZIP exactly; ZIP was not applied. "
                           "Results cover the all-store catalog; no local availability is established."}


def _category(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    url = _storefront_url(value.get("link"))
    match = re.fullmatch(r"/home/products/category/[^/]*-([0-9]+)/?", urlsplit(url).path) if url else None
    return {"name": value.get("name"), "url": url, "category_id": match.group(1) if match else None}


def normalize_product(item: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
    """Preserve catalog availability and complete dietary/nutrition evidence."""
    url = _storefront_url(item.get("link"))
    try:
        product_id = normalize_product_reference(item.get("product_id"))
    except ValueError:
        product_id = normalize_product_reference(url) if url else None
    price = item.get("extracted_price")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price < 0:
        price = None
    formatted = item.get("price")
    categories = [_category(category) for category in item.get("categories", [])
                  if isinstance(category, dict)] if isinstance(item.get("categories"), list) else []
    category = categories[-1] if categories else _category({
        "name": item.get("category"), "link": item.get("category_link"),
    })
    images = item.get("images", []) if detail else [item.get("thumbnail")]
    images = [image for image in images if _storefront_url(image)] if isinstance(images, list) else []
    result: dict[str, Any] = {
        "product_id": product_id, "title": item.get("title"), "url": url,
        "image_url": images[0] if images else None, "thumbnail": images[0] if images else None,
        "price": price, "price_formatted": formatted if isinstance(formatted, str) and formatted else None,
        "currency": "USD" if price is not None else None, "size": item.get("size"),
        "category": category.get("name"), "category_url": category.get("url"),
        "category_id": category.get("category_id"),
    }
    if detail:
        result.update(images=images, categories=categories)
        for key in ("available", "characteristics", "label", "description", "fun_tags",
                    "ingredients", "allergens", "nutrition_facts"):
            if key in item:
                result[key] = item[key]
    search_filters = {}
    for name, source in (("characteristics", "characteristics"), ("tags", "fun_tags")):
        values = item.get(source)
        selected = []
        if isinstance(values, list):
            for value in values:
                identifier = FILTER_ALIASES[name].get(" ".join(value.split()).casefold()) if isinstance(value, str) else None
                if identifier and identifier not in selected:
                    selected.append(identifier)
        if selected:
            search_filters[name] = selected
    if search_filters:
        result["search_filters"] = search_filters
    return result


def validate_payload(payload: Any, engine: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Trader Joe's returned an invalid response.")
    metadata = payload.get("search_metadata", {})
    parameters = payload.get("search_parameters", {})
    if (not isinstance(metadata, dict) or metadata.get("status", "Success") != "Success"
            or payload.get("error")):
        raise ValueError("Trader Joe's did not return a completed result.")
    if not isinstance(parameters, dict) or parameters.get("engine", engine) != engine:
        raise ValueError("Trader Joe's returned a response for a different engine.")
    return payload


def result_data(payload: dict[str, Any], results: list[dict[str, Any]],
                location: dict[str, Any], engine: str) -> dict[str, Any]:
    metadata = payload.get("search_metadata", {})
    top = results[0] if results else {}
    return {
        "engine": engine, "source": "SerpApi", "country": "us", "store_id": location["store_id"],
        "location_context": location, "results": results, "top_results": results[:5],
        "results_count": len(results), "top_product_id": top.get("product_id"),
        "top_url": top.get("url"), "top_image_url": top.get("image_url"),
        "search_information": payload.get("search_information", {}),
        "search_metadata": {key: metadata[key] for key in ("id", "status", "created_at", "processed_at") if key in metadata},
        "availability_note": AVAILABILITY_NOTE, "external_content_trust": "untrusted",
    }
