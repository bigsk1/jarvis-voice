"""Bounded, publisher-filtered Actor discovery through the native Store API.

The public MCP search schema stays unchanged. Exact operator-trusted community
Actors form a relevant, deterministic prefix before the official Store page.
Only eligible cards are retained; discovery never authorizes an Actor run.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import copy_context
from threading import Event
from typing import Any

from lib.apify import ApifyClient, ApifyError, actor_is_allowed, native_id
from lib.external_results import make_external_result_data

_WORK_SECONDS = 30.0  # Leave room inside the MCP call's 35-second hard deadline.
_READERS = 4
_STORE_LIMIT = 1000
_MAX_OFFSET = (1 << 53) - 1
_CANONICAL = re.compile(r"[A-Za-z0-9_-]{1,80}/[A-Za-z0-9_-]{1,100}\Z")


def _check_active(deadline: float, cancel_event: Event | None) -> None:
    if (cancel_event is not None and cancel_event.is_set()) or time.monotonic() >= deadline:
        raise ApifyError("Apify catalog search cancelled or exceeded its deadline")


def _arguments(arguments: dict) -> tuple[str, int, int]:
    if not isinstance(arguments, dict) or set(arguments) - {"keywords", "limit", "offset"}:
        raise ApifyError("Actor search accepts keywords, limit and offset only")
    keywords, limit, offset = (arguments.get("keywords", ""), arguments.get("limit", 5),
                               arguments.get("offset", 0))
    if not isinstance(keywords, str):
        raise ApifyError("Actor search keywords must be a string")
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ApifyError("Actor search limit must be between 1 and 10")
    if type(offset) is not int or not 0 <= offset <= _MAX_OFFSET:
        raise ApifyError("Actor search offset must be a nonnegative safe integer")
    return keywords, limit, offset


def _canonical(details: dict) -> str | None:
    username, name = details.get("username"), details.get("name")
    value = f"{username}/{name}" if isinstance(username, str) and isinstance(name, str) else ""
    return value if _CANONICAL.fullmatch(value) else None


def _relevant(details: dict, keywords: str) -> bool:
    terms = re.findall(r"\w+", keywords.casefold())
    text = " ".join(value for key in ("title", "name", "description", "username")
                    if isinstance(value := details.get(key), str)).casefold()
    return all(term in text for term in terms) if terms else keywords.strip().casefold() in text


def _card(details: dict, *, official: bool) -> dict:
    actor_id = native_id(details.get("id"), "Actor ID")
    canonical = _canonical(details)
    title, description = details.get("title"), details.get("description")
    card: dict[str, Any] = {
        "actor_id": actor_id, "actor": canonical or actor_id,
        "publisher": details.get("username") if canonical else None,
        "title": title[:160] if isinstance(title, str) else canonical or actor_id,
        "description": description[:400] if isinstance(description, str) else "",
        "eligibility": "official_apify" if official else "trusted_exception",
    }
    if canonical:
        card["url"] = "https://apify.com/" + canonical
    if ((isinstance(title, str) and len(title) > 160)
            or (isinstance(description, str) and len(description) > 400)):
        card["preview_truncated"] = True
    stats = details.get("stats") if isinstance(details.get("stats"), dict) else {}
    quality = {}
    for key, upstream in (("rating", "actorReviewRating"), ("reviews", "actorReviewCount"),
                          ("users", "totalUsers"), ("monthly_users", "totalUsers30Days")):
        value = details.get(upstream, stats.get(upstream))
        if type(value) in (int, float):
            quality[key] = value
    card["quality"] = quality
    pricing = details.get("currentPricingInfo")
    if isinstance(pricing, dict):
        card["pricing"] = {key: pricing[key] for key in (
            "pricingModel", "pricePerUnitUsd", "unitName", "minimalMaxTotalChargeUsd",
        ) if isinstance(pricing.get(key), (str, int, float)) and not isinstance(pricing[key], bool)}
    return card


def _exception(client: ApifyClient, reference: str, keywords: str) -> dict | None:
    details = client.get_actor(reference)
    # A successful lookup still needs exact native identity; display badges or
    # an upstream redirect must not turn a configured name into another Actor.
    if reference not in (details.get("id"), _canonical(details)):
        raise ApifyError("Apify returned mismatched Actor identity")
    if not actor_is_allowed(details, client.settings.allowed_actors):
        raise ApifyError("Apify returned an ineligible Actor")
    if details.get("username") == "apify" or not _relevant(details, keywords):
        return None
    return _card(details, official=False)


def _official(client: ApifyClient, params: dict) -> tuple[list[dict], int | None, bool]:
    data = client._object("GET", "/store", params=params)
    items, total = data.get("items"), data.get("total")
    if (not isinstance(items, list) or len(items) > params["limit"]
            or type(total) is not int or total < 0
            or data.get("offset") != params["offset"]):
        raise ApifyError("Apify returned invalid Store pagination")
    cards, seen, valid = [], set(), True
    for details in items:
        # Check the native publisher again before any card reaches a prompt or
        # retained file. An unexpected source page cannot establish offsets.
        if (not isinstance(details, dict) or details.get("username") != "apify"
                or not actor_is_allowed(details, client.settings.allowed_actors)):
            valid = False
            continue
        try:
            card = _card(details, official=True)
        except ApifyError:
            valid = False
            continue
        if card["actor_id"] in seen:
            valid = False
            continue
        seen.add(card["actor_id"])
        cards.append(card)
    expected = min(params["limit"], max(0, total - params["offset"]))
    valid = valid and len(items) == expected
    return cards, total if valid else None, valid


def _scan(client: ApifyClient, references: list[str], params: dict, keywords: str,
          deadline: float, cancel_event: Event | None) -> tuple[dict, set[str], set[str]]:
    """Use four copied-context reads and one observation deadline, without a cache."""
    jobs = iter([(None, lambda: _official(client, params)), *(
        (reference, lambda ref=reference: _exception(client, ref, keywords))
        for reference in references
    )])
    results, checked, failed = {}, set(), set()
    work_deadline = min(deadline, time.monotonic() + _WORK_SECONDS)
    executor = ThreadPoolExecutor(max_workers=_READERS, thread_name_prefix="apify-catalog")
    pending = {}

    def submit_next() -> bool:
        if time.monotonic() >= work_deadline or (cancel_event and cancel_event.is_set()):
            return False
        job = next(jobs, None)
        if job is None:
            return False
        reference, read = job
        context = copy_context()

        def guarded_read():
            _check_active(deadline, cancel_event)
            return read()

        pending[executor.submit(context.run, guarded_read)] = reference
        return True

    try:
        for _ in range(_READERS):
            submit_next()
        while pending:
            _check_active(deadline, cancel_event)
            remaining = work_deadline - time.monotonic()
            if remaining <= 0:
                break
            done, _ = wait(pending, timeout=min(remaining, 0.1), return_when=FIRST_COMPLETED)
            for future in done:
                reference = pending.pop(future)
                if reference is not None:
                    checked.add(reference)
                try:
                    results[reference] = future.result()
                except ApifyError:
                    if reference is None:
                        raise
                    failed.add(reference)
                submit_next()
    finally:
        for future in pending:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
    _check_active(deadline, cancel_event)
    return results, checked, failed


def search_actors(arguments: dict, *, client: ApifyClient | None = None,
                  deadline: float | None = None, cancel_event: Event | None = None) -> dict:
    """Return a generic result for the unchanged hosted MCP search tool inputs.

    Completed searches page a deterministic trusted-exception prefix followed
    by Store relevance order. An incomplete exception scan cannot establish a
    combined offset; only offset zero may show provisional candidates.
    """
    keywords, limit, offset = _arguments(arguments)
    client = client or ApifyClient()
    deadline = deadline if deadline is not None else time.monotonic() + 35
    _check_active(deadline, cancel_event)
    references = sorted(client.settings.allowed_actors)
    # Cover the possible official slice while resolving exceptions in parallel.
    # Very large configurations remain eligible, but an uncovered slice is
    # explicitly unavailable rather than silently shifted or widened.
    params = {"username": "apify", "search": keywords, "responseFormat": "full",
              "sortBy": "relevance" if keywords.strip() else "popularity",
              "offset": max(0, offset - len(references)),
              "limit": min(_STORE_LIMIT, limit + min(offset, len(references)))}
    found, checked, failed = _scan(client, references, params, keywords, deadline, cancel_event)
    exceptions = {card["actor_id"]: card for reference in references
                  if isinstance(card := found.get(reference), dict)}
    trusted = sorted(exceptions.values(), key=lambda card: (card["actor"], card["actor_id"]))
    scan_complete = len(checked) == len(references) and not failed
    official, official_total, official_complete = found.get(None, ([], None, False))
    official_offset = max(0, offset - len(trusted))
    local_offset = official_offset - params["offset"]
    slots = max(0, limit - len(trusted[offset:offset + limit]))
    needed = min(slots, max(0, official_total - official_offset)) if official_total is not None else slots
    covered = local_offset >= 0 and (
        official_total is not None and official_offset >= official_total
        or local_offset + needed <= len(official)
    )
    stable = scan_complete and official_complete and covered
    if stable:
        cards = trusted[offset:offset + limit]
        cards += official[local_offset:local_offset + limit - len(cards)]
    elif offset == 0:
        cards = (trusted + official)[:limit]
    else:
        cards = []
    total = official_total + len(trusted) if stable and official_total is not None else None
    next_offset = offset + len(cards) if stable and total is not None and offset + len(cards) < total else None
    scan = {"configured": len(references), "checked": len(checked), "matched": len(trusted),
            "complete": scan_complete}
    if pending := sorted(set(references) - checked):
        scan["pending_references"] = pending
    if failed:
        scan["unavailable_references"] = sorted(failed)
    result = {
        "kind": "catalog", "sample_items": cards, "sample_count": len(cards),
        "returned_count": len(cards), "total_items": total, "offset": offset, "limit": limit,
        "complete": stable and offset == 0 and total == len(cards),
        "pagination": {"has_more": next_offset is not None if stable else None,
                       "next_offset": next_offset, "available": stable,
                       "order": "relevant_trusted_exceptions_then_official_store"},
        "policy": {"official_publisher": "apify", "trusted_exceptions": references,
                   "quality_metrics": "advisory_only", "exception_scan": scan,
                   "details_tool": "mcp_apify_fetch-actor-details"},
    }
    if not stable:
        result["pagination_unavailable"] = True
    # Retain the filtered catalog page, never the unfiltered HTTP response.
    _check_active(deadline, cancel_event)
    data = make_external_result_data(provider="apify", tool="search-actors",
        execution={"status": "SUCCEEDED" if stable else "PARTIAL"}, result=result,
        raw_payload={"scope": "eligible_catalog_page", "keywords": keywords, **result},
        limits={"truncated": not stable, "catalog_partial": not stable})
    _check_active(deadline, cancel_event)
    speech = f"Found {len(cards)} eligible Apify Actor candidates."
    if not stable:
        speech += (" Catalog search is partial; pagination is unavailable."
                   " Configured trusted Actors can still be looked up directly.")
    elif not cards:
        speech = "No eligible Apify Actors matched this catalog page."
    return {"ok": True, "speech": speech, "data": data}
