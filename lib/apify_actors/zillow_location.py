"""Cached US location bounds for Zillow's direct search endpoint.

Uses a configurable Nominatim-compatible endpoint. One shared lock enforces
at most one request per second across foreground children/background workers.
No API credentials, addresses from scraped listings, or Actor data are sent.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from filelock import FileLock, Timeout

from lib.config_loader import get_active_config_mode, get_config_value
from lib.http_client import http_request
from lib.paths import get_project_root

DEFAULT_URL = "https://nominatim.openstreetmap.org/search"
ATTRIBUTION = "© OpenStreetMap contributors"
_NATIVE_ID = re.compile(r"[A-Za-z0-9]{1,128}\Z")


def _run_record_path(run_id: str) -> Path:
    mode = get_active_config_mode()
    if mode not in {"cloud", "local"} or not isinstance(run_id, str) or not _NATIVE_ID.fullmatch(run_id):
        raise ValueError("Invalid geography run identity")
    return get_project_root() / "data" / "cache" / "apify-geography" / "runs" / mode / (run_id + ".json")


def remember_run_geography(run_id: str, actor_id: str) -> bool:
    """Remember only a trusted compiler's source credit, never Actor-supplied data.

    Called after a confirmed submission: cache failure must not erase its native
    recovery handle or encourage another paid start.
    """
    staged = None
    try:
        if not isinstance(actor_id, str) or not _NATIVE_ID.fullmatch(actor_id):
            return False
        path = _run_record_path(run_id)
        for directory in (path.parent.parent.parent, path.parent.parent, path.parent):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, staged = tempfile.mkstemp(prefix=run_id + ".", suffix=".tmp", dir=path.parent)
        with os.fdopen(descriptor, "w") as stream:
            json.dump({"run_id": run_id, "actor_id": actor_id,
                       "geography_attribution": {"provider": "openstreetmap"}}, stream)
        os.replace(staged, path)
        return True
    except (OSError, ValueError):
        logging.getLogger(__name__).warning(
            "Could not retain geography attribution; the accepted Apify run must not be resubmitted")
        return False
    finally:
        if staged is not None:
            try:
                Path(staged).unlink(missing_ok=True)
            except OSError:
                pass


def run_geography(run_id: str, actor_id: str) -> dict[str, str] | None:
    """Recover mode/run/Actor-bound attribution across tool child processes."""
    try:
        path = _run_record_path(run_id)
        with path.open("rb") as stream:
            encoded = stream.read(4097)
        if len(encoded) > 4096:
            return None
        saved = json.loads(encoded)
        if (isinstance(saved, dict) and saved.get("run_id") == run_id
                and saved.get("actor_id") == actor_id
                and saved.get("geography_attribution") == {"provider": "openstreetmap"}):
            return {"provider": "openstreetmap"}
    except (OSError, ValueError, TypeError, RecursionError):
        pass
    return None


def _bounds(value: object) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != {"west", "east", "south", "north"}:
        raise ValueError("Location lookup returned invalid map bounds")
    if any(isinstance(item, bool) or not isinstance(item, (int, float))
           or not -180 <= item <= 180 for item in value.values()):
        raise ValueError("Location lookup returned invalid map bounds")
    if not (-180 <= value["west"] < value["east"] <= 180
            and -90 <= value["south"] < value["north"] <= 90):
        raise ValueError("Location lookup returned invalid map bounds")
    return value


def resolve_bounds(location: str) -> dict[str, float]:
    """Resolve a specific US location, rejecting missing or ambiguous results."""
    endpoint = str(get_config_value("APIFY_GEOCODER_URL", DEFAULT_URL) or "").strip()
    try:
        parsed = urlsplit(endpoint)
        valid_endpoint = (parsed.scheme == "https" and parsed.hostname
            and parsed.port != 0 and parsed.username is None and parsed.password is None
            and not parsed.query and not parsed.fragment
            and "\\" not in endpoint
            and not any(char.isspace() or ord(char) < 32 for char in endpoint))
    except ValueError:
        valid_endpoint = False
    if not valid_endpoint:
        raise ValueError("APIFY_GEOCODER_URL must be a credential-free HTTPS lookup endpoint")
    root = get_project_root() / "data" / "cache" / "apify-geography"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = hashlib.sha256((endpoint + "\n" + location.casefold()).encode()).hexdigest()
    cache = root / (key + ".json")
    try:
        with FileLock(str(root / "lookup.lock"), timeout=15):
            try:
                saved = json.loads(cache.read_text())
                if 0 <= time.time() - saved["saved_at"] < 180 * 86400:
                    return _bounds(saved["bounds"])
            except (OSError, ValueError, KeyError, TypeError):
                pass
            rate = root / "last-request"
            try:
                previous = float(rate.read_text())
                delay = min(1.0, max(0.0, previous + 1.0 - time.time()))
            except (OSError, ValueError):
                delay = 0
            if delay:
                time.sleep(delay)
            rate.write_text(str(time.time()))
            rows = _lookup(endpoint, location)
            if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
                raise ValueError("Location lookup was empty or ambiguous; specify a city and state or ZIP")
            row = rows[0]
            address = row.get("address")
            bbox = row.get("boundingbox")
            if (not isinstance(address, dict) or address.get("country_code") != "us"
                    or not isinstance(bbox, list) or len(bbox) != 4
                    or any(isinstance(item, bool) or not isinstance(item, (int, float, str))
                           for item in bbox)):
                raise ValueError("Location lookup did not establish US map bounds")
            try:
                south, north, west, east = map(float, bbox)
                bounds = _bounds({"west": west, "east": east, "south": south, "north": north})
            except (ValueError, TypeError):
                raise ValueError("Location lookup returned invalid map bounds") from None
            staged = cache.with_suffix(".tmp")
            staged.write_text(json.dumps({"bounds": bounds, "saved_at": time.time()}))
            staged.chmod(0o600)
            os.replace(staged, cache)
            return bounds
    except Timeout:
        raise ValueError("Location lookup is busy; no Apify run was submitted") from None


def _lookup(endpoint: str, location: str) -> object:
    response = None
    try:
        response = http_request("GET", endpoint, params={"q": location, "countrycodes": "us",
            "format": "jsonv2", "limit": 2, "addressdetails": 1},
            headers={"User-Agent": "JarvisVoice/1.0 (https://github.com/bigsk1/jarvis-voice)"},
            timeout=(5, 10), stream=True, allow_redirects=False, proxy_policy="off")
        if response.status_code != 200:
            raise ValueError("Location lookup is unavailable; no Apify run was submitted")
        deadline = time.monotonic() + 15
        body = bytearray()
        for chunk in response.iter_content(chunk_size=16384):
            body.extend(chunk)
            if len(body) > 65536 or time.monotonic() > deadline:
                raise ValueError("Location lookup exceeded its response limit")
        return json.loads(body)
    except (OSError, ValueError) as exc:
        if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError):
            raise
        raise ValueError("Location lookup failed; no Apify run was submitted") from None
    finally:
        if response is not None:
            response.close()
