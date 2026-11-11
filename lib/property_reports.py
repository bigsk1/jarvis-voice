"""Self-contained Canvas property snapshots from complete retained pages.

No model, remote Actor call, or new scrape. Native records are normalized by
reviewed adapters; already canonical pages can come from another provider.
"""

from __future__ import annotations

import json
import re
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_ROWS = 2000
MAX_BLOCK_BYTES = 4 * 1024 * 1024
_REF = re.compile(r"stash://(space_[A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)\Z")


def _read_archive(source: dict) -> dict:
    try:
        from config_loader import config_scope
        from stash_helper import get_space, resolve_file_path
    except ModuleNotFoundError:
        from lib.config_loader import config_scope
        from lib.stash_helper import get_space, resolve_file_path
    ref, mode = source.get("ref"), source.get("mode")
    match = _REF.fullmatch(ref) if isinstance(ref, str) else None
    if not match or mode not in {"cloud", "local"}:
        raise ValueError("Each property source requires a canonical Stash ref and its saved cloud/local mode")
    with ExitStack() as scopes:
        scopes.enter_context(config_scope(mode))
        # Package and production top-level imports can coexist in Web tools.
        try:
            from lib.config_loader import config_scope as package_scope
        except ModuleNotFoundError as exc:
            if exc.name != "lib":
                raise
        else:
            scopes.enter_context(package_scope(mode))
        path = Path(resolve_file_path(stash_ref=ref)).resolve()
        space_root = get_space(match[1]).space_path.resolve()
        if not path.is_relative_to(space_root) or path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Property source is outside its Stash space or exceeds 8 MiB")
        value = json.loads(path.read_bytes(), parse_constant=lambda _value: _invalid_json())
    if not isinstance(value, dict):
        raise ValueError("Property source must be a retained JSON page")
    return value


def _invalid_json():
    raise ValueError("Property source must contain finite JSON")


def _timestamp(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 48:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else None


def _page_counts(archive: dict, presentation: dict, items: list) -> tuple[int, int]:
    """Use native length for source positions, with explicit canonical-page evidence."""
    native = archive.get("items")
    declared = presentation.get("input_count", len(items))
    fetched = len(native) if isinstance(native, list) else declared
    excluded = presentation.get("unrecognized_count", fetched - len(items))
    if (type(declared) is not int or declared < len(items)
            or type(fetched) is not int or fetched < len(items)
            or type(excluded) is not int or excluded != fetched - len(items)
            or ("input_count" in presentation and declared != fetched)):
        raise ValueError("Property source has inconsistent native and recognized record counts")
    return fetched, excluded


def _coverage(pages: dict, returned: int, fetched: int, excluded: int) -> dict:
    """Compute source-record coverage from native page ranges, including errors."""
    complete = bool(pages)
    for page in pages.values():
        if page["total"] is not None and any(stop > page["total"] for _, stop in page["ranges"]):
            page["total"] = None  # A previously observed count now lags the fetched records.
        end = 0
        for start, stop in sorted(page["ranges"]):
            if start > end:
                break
            end = max(end, stop)
        complete &= page["succeeded"] and page["total"] is not None and end >= page["total"]
    known = all(page["total"] is not None for page in pages.values())
    total = sum(page["total"] for page in pages.values()) if known else None
    only_page = next(iter(pages.values())) if len(pages) == 1 else None
    offset = min(start for start, _ in only_page["ranges"]) if only_page and only_page["ranges"] else None
    return {"returned_count": returned, "fetched_count": fetched, "unrecognized_count": excluded,
            "total_items": total, "offset": offset, "complete": complete}


def build_property_report(sources: Any, *, criteria_text: str = "") -> str:
    """Embed full canonical rows, truthful page coverage and exact deduplication."""
    try:
        from apify_actors import normalize_property_page
    except ModuleNotFoundError:
        from lib.apify_actors import normalize_property_page

    if (not isinstance(sources, list) or not 1 <= len(sources) <= 20
            or any(not isinstance(source, dict) or set(source) != {"ref", "mode"} for source in sources)):
        raise ValueError("property_sources requires 1–20 objects containing ref and saved mode")
    if not isinstance(criteria_text, str) or len(criteria_text) > 2000:
        raise ValueError("property_criteria must be text of at most 2000 characters")
    rows, snapshots, pages, sources_used = [], [], {}, set()
    fetched, excluded, osm_attribution = 0, 0, False
    for source in sources:
        archive = _read_archive(source)
        if not isinstance(archive, dict):
            raise ValueError("Property source must be a retained JSON page")
        run = archive.get("run", {})
        native = archive.get("items")
        presentation = archive.get("presentation", {})
        # Rebuild native Apify pages, rather than trusting a stale display sample.
        if isinstance(run, dict) and run.get("actId") and isinstance(native, list):
            if not isinstance(run["actId"], str):
                raise ValueError("Property source has an invalid Actor identity")
            presentation = normalize_property_page(run["actId"], native)
        if not isinstance(presentation, dict) or presentation.get("kind") != "property_listings":
            raise ValueError("Property source has no supported property records; inspect the existing result")
        items = presentation.get("items")
        if not isinstance(items, list) or any(not isinstance(row, dict)
                or row.get("kind") != "property_listing" or not isinstance(row.get("source"), str)
                or row["source"] not in {"zillow", "redfin"}
                for row in items):
            raise ValueError("Invalid canonical property page")
        page_fetched, page_excluded = _page_counts(archive, presentation, items)
        fetched += page_fetched
        excluded += page_excluded
        if fetched > MAX_ROWS:
            raise ValueError("Property report exceeds the 2000-row limit; use smaller retained pages")
        rows.extend(items)
        sources_used.update(row["source"] for row in items)
        if isinstance(presentation.get("source"), str) and presentation["source"] in {"zillow", "redfin"}:
            sources_used.add(presentation["source"])
        attribution = archive.get("geography_attribution")
        osm_attribution |= isinstance(attribution, dict) and attribution.get("provider") == "openstreetmap"
        stamp = _timestamp(run.get("finishedAt")) if isinstance(run, dict) else None
        snapshots.extend([stamp] if stamp else [_timestamp(row.get("scraped_at")) for row in items])
        dataset = archive.get("dataset", {})
        offset = archive.get("offset")
        total = dataset.get("itemCount") if isinstance(dataset, dict) else None
        key = (source["mode"], run.get("id"), dataset.get("id")) if isinstance(run, dict) and isinstance(dataset, dict) else None
        if (key is not None and all(isinstance(part, str) and part for part in key)
                and type(offset) is int and offset >= 0):
            # A named Apify dataset can be reused by multiple runs. Its source
            # positions and total still describe one dataset in this mode.
            info = pages.setdefault((key[0], key[2]), {"total": None, "ranges": [], "succeeded": True})
            if type(total) is int and total >= offset + page_fetched:
                info["total"] = max(info["total"] or 0, total)
            info["ranges"].append((offset, offset + page_fetched))
            info["succeeded"] &= run.get("status") == "SUCCEEDED"
        else:
            pages[("unknown", source["ref"])] = {"total": None, "ranges": [], "succeeded": False}
    unique, seen = [], set()
    for row in rows:
        handle = row.get("listing_id") or row.get("url")
        key = (row["source"], handle) if isinstance(handle, (str, int)) else None
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        unique.append(row)
    payload = {"version": 1, "source": next(iter(sources_used)) if len(sources_used) == 1 else "mixed",
        "snapshot_at": max((stamp for stamp in snapshots if stamp), default=None),
        "criteria_text": " ".join(criteria_text.split()),
        "coverage": _coverage(pages, len(rows), fetched, excluded),
        "items": unique, "duplicates_removed": len(rows) - len(unique)}
    if osm_attribution:
        payload["geography_attribution"] = {"provider": "openstreetmap"}
    # Canvas's existing escaped-newline normalization must not alter JSON string
    # escapes. Canonical fields contain no newlines; encode literal backslashes.
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace("\\\\", "\\u005c")
    if len(encoded.encode()) > MAX_BLOCK_BYTES:
        raise ValueError("Property report exceeds the 4 MiB limit")
    return "\n\n```property-listings\n" + encoded + "\n```\n"
