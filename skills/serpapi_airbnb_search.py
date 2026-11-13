#!/usr/bin/env python3
"""Find Airbnb stays for an explicit destination with one bounded SerpApi call."""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from config_loader import load_config
from security_utils import redact_sensitive_text
from serpapi_airbnb import (
    AIRBNB_MAX_RESPONSE_BYTES,
    AIRBNB_TIMEOUT,
    BOOKING_CAVEAT,
    bound_result_data,
    build_search_parameters,
    normalize_listing,
    read_input,
    validate_payload,
)
from serpapi_client import clamp_results_count, request_serpapi


def _describe_search(context: dict[str, Any], budget: dict[str, Any]) -> str:
    """Describe the actual search party and filters without provider conversion details."""
    room = "entire homes" if context["room_type"] == "entire_home" else "private rooms"
    property_labels = {"house": "houses", "apartment": "apartments",
                       "guesthouse": "guesthouses", "hotel": "hotels"}
    properties = ", ".join(property_labels[value] for value in context["property_types"])
    party = [f"{context['adults']} adult{'s' if context['adults'] != 1 else ''}"]
    for key, singular, plural in (("children", "child", "children"), ("infants", "infant", "infants"),
                                  ("pets", "pet", "pets")):
        count = context[key]
        if count:
            party.append(f"{count} {singular if count == 1 else plural}")
    summary = f"Search: {room}; {properties or 'any property type'}; {', '.join(party)}. "
    if context["amenities"]:
        labels = {"wifi": "Wi-Fi", "tv": "TV", "bbq_grill": "BBQ grill", "ev_charger": "EV charger"}
        amenities = ", ".join(labels.get(value, value.replace("_", " ")) for value in context["amenities"])
        summary += f"Required amenities: {amenities}. "
    if not budget["enabled"]:
        summary += "No price filter applied. "
    else:
        def amount(value):
            return f"{int(value) if value == int(value) else value:,}"

        minimum, maximum = budget["min_price_per_night"], budget["max_price_per_night"]
        if minimum is not None and maximum is not None:
            bounds = f"{amount(minimum)} to {amount(maximum)}"
        elif minimum is not None:
            bounds = f"at least {amount(minimum)}"
        else:
            bounds = f"up to {amount(maximum)}"
        summary += f"Budget: {budget['currency']} {bounds} per night, including fees. "
    if context["dates_mode"] == "suggested":
        summary += "Dates were not supplied; each listing has Airbnb-suggested dates. "
        if budget["enabled"]:
            summary += f"The budget assumes {budget['filter_nights']} nights. "
    else:
        summary += f"Dates: {context['check_in_date']} to {context['check_out_date']}. "
    return summary + "Displayed prices are stay totals."


def search(options: dict[str, Any]) -> dict[str, Any]:
    params, context, budget, filters = build_search_parameters(options)
    limit = clamp_results_count(options.get("num_results", 5), default=5, maximum=10)
    payload = validate_payload(request_serpapi(
        params, timeout=AIRBNB_TIMEOUT, max_response_bytes=AIRBNB_MAX_RESPONSE_BYTES,
        use_proxy=False, fallback_on_proxy_fail=False,
    ))
    organic = payload.get("organic_results")
    information = payload.get("search_information", {})
    information = information if isinstance(information, dict) else {}
    if "organic_results" not in payload and type(information.get("total_results")) is int and information["total_results"] == 0:
        organic = []
    if not isinstance(organic, list):
        raise ValueError("Airbnb search did not return a listing list.")
    results = []
    for item in organic:
        if not isinstance(item, dict):
            continue
        row = normalize_listing(item, currency=context["currency"], dates_mode=context["dates_mode"], position=len(results) + 1)
        if row is not None:
            results.append(row)
        if len(results) >= limit:
            break
    if organic and not results:
        raise ValueError("Airbnb search returned no usable listing identities.")
    pagination = payload.get("serpapi_pagination", {})
    pagination = pagination if isinstance(pagination, dict) else {}
    metadata = payload.get("search_metadata", {})
    page = params["page"]
    has_next = bool(pagination.get("next")) and page < 15
    data = {
        "engine": "airbnb", "source": "SerpApi", "query": context["query"], "page": page,
        "currency": context["currency"], "dates_mode": context["dates_mode"],
        "requested_parameters": deepcopy(options), "effective_parameters": params,
        "requested_filters": filters, "search_context": context, "budget_context": budget,
        "results": results, "top_results": results[:5], "results_count": len(results),
        "provider_results_count": len(organic), "results_truncated": len(organic) > len(results),
        "result_truncated": any(row["result_truncated"] for row in results),
        "search_information": {key: value[:400] if isinstance(value, str) else value
                               for key, value in information.items() if key in {"total_results", "query_displayed"}
                               and ((key == "total_results" and type(value) is int and 0 <= value < 10**15)
                                    or (key == "query_displayed" and isinstance(value, str)))},
        "search_metadata": {key: metadata[key][:200] for key in ("id", "status", "created_at", "processed_at")
                            if isinstance(metadata.get(key), str)},
        "pagination": {"current": page, "has_next": has_next, "next_page": page + 1 if has_next else None},
        "booking_caveat": BOOKING_CAVEAT, "external_content_trust": "untrusted",
    }
    bound_result_data(data)
    speech = f"Found {data['results_count']} Airbnb stays for {context['query']}. " if results else f"No Airbnb stays found for {context['query']}. "
    speech += _describe_search(context, budget)
    return {"ok": True, "speech": speech, "data": data}


def main() -> int:
    try:
        load_config()
        result = search(read_input(sys.argv))
    except (ValueError, RuntimeError, OSError) as exc:
        message = "Airbnb search error: " + redact_sensitive_text(str(exc))[:1000]
        result = {"ok": False, "speech": message, "error": message}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
