"""Private, reload-on-use feed profiles; no arbitrary tool-supplied file paths."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from . import RSSFeedError

ROOT = Path(__file__).resolve().parents[2]
PROFILE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")


def profile_id(value: object) -> str:
    if not isinstance(value, str) or not PROFILE_ID.fullmatch(value):
        raise RSSFeedError("Choose a configured RSS profile name, such as daily_tech.")
    return value


def _integer(value: object, default: int, maximum: int, label: str) -> int:
    value = default if value is None else value
    if type(value) is not int or not 1 <= value <= maximum:
        raise RSSFeedError(f"RSS {label} must be between 1 and {maximum}.")
    return value


def _strings(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 30 or any(
        not isinstance(item, str) or not item.strip() or len(item) > 300 for item in value
    ):
        raise RSSFeedError(f"RSS {label} must be a short list of descriptions.")
    return [item.strip() for item in value]


def load_profiles(path: Path | None = None) -> dict[str, dict]:
    path = path or ROOT / "config/rss_feeds.yaml"
    try:
        if path.stat().st_size > 128_000:
            raise RSSFeedError("The RSS configuration is too large.")
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RSSFeedError("Configure RSS profiles in config/rss_feeds.yaml using the example file.") from exc
    except (yaml.YAMLError, UnicodeError) as exc:
        raise RSSFeedError("The RSS profile configuration is not valid YAML.") from exc
    if (not isinstance(document, dict) or type(document.get("v", 1)) is not int
            or document.get("v", 1) != 1):
        raise RSSFeedError("RSS configuration must be a version 1 object.")
    raw_profiles = document.get("profiles")
    if not isinstance(raw_profiles, dict) or not 1 <= len(raw_profiles) <= 30:
        raise RSSFeedError("Configure between 1 and 30 RSS profiles.")
    profiles = {}
    for name, raw in raw_profiles.items():
        name = profile_id(name)
        if not isinstance(raw, dict):
            raise RSSFeedError("Each RSS profile must be an object.")
        if type(raw.get("track_updates", False)) is not bool:
            raise RSSFeedError("RSS track_updates must be true or false.")
        title = raw.get("canvas_title", f"Digests/{name}")
        if not isinstance(title, str) or not title.strip() or len(title) > 150:
            raise RSSFeedError("Each RSS profile needs a short Canvas title.")
        raw_feeds = raw.get("feeds")
        if not isinstance(raw_feeds, list) or not 1 <= len(raw_feeds) <= 16:
            raise RSSFeedError("Each RSS profile needs between 1 and 16 feeds.")
        feeds = []
        for feed in raw_feeds:
            if not isinstance(feed, dict):
                raise RSSFeedError("Each RSS feed must have a name and URL.")
            if type(feed.get("enabled", True)) is not bool:
                raise RSSFeedError("RSS feed enabled must be true or false.")
            if feed.get("enabled", True) is False:
                continue
            url, feed_name = feed.get("url"), feed.get("name")
            if not isinstance(url, str) or len(url) > 2048 or not isinstance(feed_name, str) or not feed_name.strip() or len(feed_name) > 120:
                raise RSSFeedError("Each RSS feed needs a short name and public HTTP(S) URL.")
            priority = feed.get("priority", "normal")
            if not isinstance(priority, str) or priority not in {"high", "normal", "low"}:
                raise RSSFeedError("RSS feed priority must be high, normal, or low.")
            feeds.append({"name": feed_name.strip(), "url": url.strip(), "priority": priority})
        if not feeds:
            raise RSSFeedError("Enable at least one feed in the RSS profile.")
        profiles[name] = {
            "profile": name,
            "title": title.strip(),
            "interests": _strings(raw.get("interests"), "interests"),
            "exclude": _strings(raw.get("exclude"), "exclusions"),
            "max_stories": _integer(raw.get("max_stories"), 8, 8, "max_stories"),
            "max_candidates": _integer(raw.get("max_candidates"), 40, 40, "max_candidates"),
            "max_age_hours": _integer(raw.get("max_age_hours"), 48, 720, "max_age_hours"),
            "feeds": feeds,
            # Preserve existing config hashes and pending batches when this
            # optional policy is absent or explicitly disabled.
            **({"track_updates": True} if raw.get("track_updates", False) else {}),
        }
    return profiles
