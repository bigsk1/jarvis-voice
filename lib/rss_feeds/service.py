"""Fresh feed collection, editorial selection and confirmed publication state."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import RSSFeedError
from .config import ROOT, load_profiles, profile_id
from .reader import FEED_TIMEOUT_SECONDS, canonical_url, read_feed
from .state import FeedState


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _text(value: object, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _limit_content(item: dict, limit: int) -> None:
    """Keep feed-excerpt provenance when either workflow budget shortens it."""
    raw_content = item.get("content")
    content = raw_content if isinstance(raw_content, str) else ""
    original_chars = item.get("content_chars")
    if type(original_chars) is not int or original_chars < len(content):
        original_chars = len(content)
    item["content_chars"] = original_chars
    item["content"] = content[:limit]
    item["content_truncated"] = (
        item.get("content_truncated") is True or original_chars > len(item["content"])
    )
    if item["content_truncated"]:
        item["needs_fetch"] = True


def _failure_reason(message: str) -> str:
    """Expose useful retrieval classifications without copying exception text."""
    if match := re.search(r"\bHTTP ([1-5][0-9]{2})\b", message):
        return f"HTTP {match[1]}"
    if "public-address" in message:
        return "blocked by public-address check"
    if "size limit" in message:
        return "feed exceeded size limit"
    if "XML" in message or "malformed" in message or "unsupported" in message:
        return "unsupported or malformed feed"
    if "HTML page" in message:
        return "URL returned a web page"
    if "time limit" in message:
        return "request time limit reached"
    return "request failed or timed out"


class RSSFeedService:
    """The tool and tests share one service; no model or scheduler lives here."""

    def __init__(self, *, config_path: Path | None = None, state_dir: Path | None = None,
                 canvas_dir: Path | None = None,
                 now: datetime | None = None, reader=None):
        self.config_path = config_path
        self.state_dir = state_dir or ROOT / "data/rss-feeds"
        self.canvas_dir = canvas_dir or ROOT / "data/canvas"
        self.now = now or datetime.now(timezone.utc)
        if self.now.tzinfo is None:
            raise RSSFeedError("RSS operations require an aware timestamp.")
        self.reader = reader or read_feed

    def execute(self, action: str = "read", *, url=None, profile=None, batch_id=None,
                text=None, page_id=None, limit=None) -> dict:
        if action == "list_profiles":
            profiles = load_profiles(self.config_path)
            if profile is not None:
                name = profile_id(profile)
                if name not in profiles:
                    raise RSSFeedError("That RSS profile is not configured; list_profiles shows available choices.")
                profiles = {name: profiles[name]}
            return {"action": action, "profiles": [
                {key: row[key] for key in ("profile", "title", "interests", "exclude", "feeds")}
                for row in profiles.values()
            ]}
        if action == "read" and url is not None:
            if profile is not None or not isinstance(url, str):
                raise RSSFeedError("Read either a public feed URL or a configured profile.")
            if limit is not None and (type(limit) is not int or not 1 <= limit <= 20):
                raise RSSFeedError("RSS limit must be between 1 and 20.")
            result = self.reader(url, now=self.now, limit=limit or 10)
            return {**result, "action": "read", "fresh_request": True}
        name = profile_id(profile)
        config = load_profiles(self.config_path).get(name)
        if config is None:
            raise RSSFeedError("That RSS profile is not configured; list_profiles shows available choices.")
        if action == "read":
            return self._collect(config)
        store = FeedState(self.state_dir, name)
        if not isinstance(batch_id, str) or not re.fullmatch(r"[a-f0-9]{32}", batch_id):
            raise RSSFeedError("Use the batch_id returned by this profile's fresh read.")
        with store.transaction(self.now.timestamp()) as state:
            batch = state["batches"].get(batch_id)
            if not batch or batch.get("config_hash") != _digest(config):
                raise RSSFeedError("This RSS batch expired or its profile changed; read the feeds again.")
            if batch.get("superseded"):
                raise RSSFeedError("This RSS batch was superseded by a published incident update; read the feeds again.")
            if batch.get("acknowledged"):
                if action == "acknowledge":
                    return {"action": action, "profile": name, "batch_id": batch_id, "already_acknowledged": True,
                            "page_id": batch["page_id"], "published_count": batch["published_count"]}
                raise RSSFeedError("This RSS batch has already been published; read current feeds again.")
            if action == "resolve_selection":
                return {**self._select(config, batch, state, text),
                        "action": action, "batch_id": batch_id}
            if action == "acknowledge":
                return {**self._acknowledge(config, batch_id, batch, state, page_id), "action": action}
        raise RSSFeedError("That RSS action is not supported.")

    def _collect(self, config: dict) -> dict:
        # Each reader enforces a per-feed bound inside this shared wall-clock budget.
        deadline = time.monotonic() + 45
        feeds = sorted(config["feeds"], key=lambda feed: {"high": 0, "normal": 1, "low": 2}[feed["priority"]])
        # Give every worker wave time to run, leaving five seconds for overhead.
        per_feed_seconds = min(FEED_TIMEOUT_SECONDS, 40 / math.ceil(len(feeds) / 4))

        def fetch(feed):
            try:
                result = self.reader(feed["url"], now=self.now,
                                     max_age_hours=config["max_age_hours"], limit=20,
                                     deadline=min(deadline, time.monotonic() + per_feed_seconds),
                                     **({"track_updates": True} if config.get("track_updates") else {}))
                return feed, result, None
            except RSSFeedError as exc:
                return feed, None, str(exc)
            except Exception:
                return feed, None, "This feed could not be checked."

        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(fetch, feeds))
        statuses, groups = [], []
        for feed, result, error in responses:
            statuses.append({"name": feed["name"], "ok": error is None,
                             **({"error": error} if error else {"proxy": result.get("proxy", {})})})
            if result is not None:
                groups.append((feed, result.get("items", [])))
        failed_feeds = [{"name": source["name"], "reason": _failure_reason(source["error"])}
                        for source in statuses if not source["ok"]]
        named_failures = "; ".join(f"{source['name']} ({source['reason']})" for source in failed_feeds[:3])
        extra = f"; and {len(failed_feeds) - 3} more" if len(failed_feeds) > 3 else ""
        coverage_note = f"Could not check: {named_failures}{extra}." if failed_feeds else ""
        if not groups:
            raise RSSFeedError(f"No RSS feeds could be checked. {coverage_note} The previous digest and publication history were kept.")
        store = FeedState(self.state_dir, config["profile"])
        checked_at = self.now.isoformat()
        with store.transaction(self.now.timestamp()) as state:
            full_items = []
            collected_urls = set()
            prompt_chars = 2
            existing = set(state["seen"])
            # Round-robin gives smaller publications a chance before the global cap.
            for offset in range(20):
                for feed, rows in groups:
                    if offset >= len(rows):
                        continue
                    item = dict(rows[offset])
                    try:
                        item["url"] = canonical_url(item["url"])
                    except (RSSFeedError, KeyError):
                        continue
                    identity = _digest(item["url"])[:24]
                    fingerprint = item.pop("content_fingerprint", None)
                    if config.get("track_updates"):
                        # Production readers fingerprint full visible evidence.
                        # Injected readers may supply plain title/summary/body.
                        if not isinstance(fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
                            fingerprint = _digest([item.get(key, "") for key in ("title", "summary", "content")])
                        identity = _digest([item["url"], fingerprint])[:24]
                    if identity in existing or item["url"] in collected_urls:
                        continue
                    existing.add(identity)
                    item.update(id=identity, source=feed["name"], priority=feed["priority"])
                    item["title"] = _text(item.get("title"), 240)
                    item["summary"] = _text(item.get("summary"), 450)
                    _limit_content(item, 3500)
                    candidate = {key: value for key, value in item.items()
                                 if key not in {"content", "needs_fetch"}}
                    cost = len(json.dumps(candidate, ensure_ascii=True, indent=2)) + 60
                    if prompt_chars + cost > 40_000:
                        continue
                    prompt_chars += cost
                    full_items.append(item)
                    collected_urls.add(item["url"])
                    if len(full_items) >= config["max_candidates"]:
                        break
                if len(full_items) >= config["max_candidates"]:
                    break
            batch_id = uuid.uuid4().hex
            state["batches"][batch_id] = {
                "created_at": self.now.timestamp(), "config_hash": _digest(config),
                "items": full_items, "checked_at": checked_at, "coverage_note": coverage_note,
                "failed_feeds": failed_feeds,
            }
        compact_items = [{key: value for key, value in item.items() if key not in {"content", "needs_fetch"}}
                         for item in full_items]
        return {**{key: config[key] for key in ("profile", "title", "interests", "exclude", "max_stories")},
                "action": "read", "batch_id": batch_id, "checked_at": checked_at,
                "items": compact_items, "candidate_count": len(full_items), "has_items": bool(full_items),
                "source_status": statuses, "coverage_note": coverage_note,
                "failed_feeds": failed_feeds, "fresh_request": True}

    def _select(self, config: dict, batch: dict, state: dict, text: object) -> dict:
        if not isinstance(text, str) or len(text) > 12_000:
            raise RSSFeedError('Return a small JSON object containing an "ids" list.')
        try:
            selection = json.loads(text)
        except (ValueError, RecursionError) as exc:
            raise RSSFeedError('RSS selection must be strict JSON: {"ids": ["candidate-id"]}.') from exc
        if not isinstance(selection, dict) or set(selection) != {"ids"} or not isinstance(selection["ids"], list):
            raise RSSFeedError('RSS selection must contain only an "ids" list.')
        identifiers = selection["ids"]
        if len(identifiers) > config["max_stories"] or any(not isinstance(item, str) for item in identifiers):
            raise RSSFeedError("RSS selection exceeds the configured story limit or contains invalid IDs.")
        if len(set(identifiers)) != len(identifiers):
            raise RSSFeedError("RSS selection contains duplicate story IDs.")
        candidates = {row["id"]: row for row in batch["items"]}
        if any(identity not in candidates for identity in identifiers):
            raise RSSFeedError("RSS selection contained a story that was not in this fetched batch.")
        selected = [candidates[identity] for identity in identifiers if identity not in state["seen"]]
        selected_ids = {row["id"] for row in selected}
        selected_urls = {row["url"] for row in selected}
        # The state lock protects this claim across separate CLI/Web/scheduled
        # runs while the existing tools perform crawling and publication.
        for other in state["batches"].values():
            if other is batch or other.get("acknowledged"):
                continue
            other_ids = set(other.get("selected_ids", []))
            overlap = selected_ids.intersection(other_ids)
            if config.get("track_updates"):
                overlap = selected_urls.intersection(
                    row["url"] for row in other["items"] if row["id"] in other_ids
                )
            if other.get("selected_at", 0) > self.now.timestamp() - 900 and overlap:
                raise RSSFeedError("Another RSS digest is preparing these stories; retry after it finishes or in 15 minutes.")
        selected = [dict(row) for row in selected]
        # Keep complete IDs/URLs and shrink prose before workflow interpolation.
        while len(json.dumps(selected, ensure_ascii=True, indent=2)) > 40_000:
            if not any(len(row.get("content", "")) > 100 for row in selected):
                raise RSSFeedError("Selected RSS metadata is too large; choose fewer stories.")
            for row in selected:
                _limit_content(row, max(100, len(row.get("content", "")) // 2))
        batch["selected_ids"] = [row["id"] for row in selected]
        batch["selected_at"] = self.now.timestamp()
        return {"profile": config["profile"], "title": config["title"], "selected_items": selected,
                "urls": [row["url"] for row in selected if row.get("needs_fetch", True)],
                "has_selection": bool(selected), "checked_at": batch["checked_at"],
                "coverage_note": batch["coverage_note"], "failed_feeds": batch.get("failed_feeds", [])}

    def _acknowledge(self, config: dict, batch_id: str, batch: dict, state: dict, page_id: object) -> dict:
        selected = set(batch.get("selected_ids", []))
        if not selected:
            raise RSSFeedError("Select stories before acknowledging this RSS batch.")
        if not isinstance(page_id, str) or not re.fullmatch(r"page_[A-Za-z0-9_-]{1,90}", page_id):
            raise RSSFeedError("Acknowledge requires the page_id of the published Canvas digest.")
        path = self.canvas_dir / f"{page_id}.json"
        try:
            if path.stat().st_size > 2_000_000 or path.stat().st_mtime + 2 < batch["created_at"]:
                raise ValueError("page predates batch")
            page = json.loads(path.read_text(encoding="utf-8"))
            if page.get("id") != page_id or page.get("title") != config["title"]:
                raise ValueError("wrong page")
            content = page.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty page")
        except (OSError, ValueError, AttributeError, UnicodeError) as exc:
            raise RSSFeedError("The saved Canvas digest could not be verified; RSS history was not advanced.") from exc
        page_urls = set()
        selected_urls = {row["url"] for row in batch["items"] if row["id"] in selected}
        for url in re.findall(r"https?://[^\s<>\"']+", content):
            # Markdown may add closing parentheses around a URL which itself
            # contains balanced parentheses. Compare complete identities before
            # removing a bounded number of surrounding Markdown/punctuation chars.
            for _ in range(16):
                try:
                    candidate = canonical_url(url)
                except RSSFeedError:
                    candidate = ""
                if candidate in selected_urls:
                    page_urls.add(candidate)
                    break
                if len(url) > 8208 or not url.endswith((")", "]", "}", ".", ",", ";")):
                    break
                url = url[:-1]
        published = [row for row in batch["items"] if row["id"] in selected and row["url"] in page_urls]
        if not published:
            raise RSSFeedError("No selected story links were found in the saved digest; RSS history was kept.")
        published_ids = {row["id"] for row in published}
        if config.get("track_updates"):
            published_versions = {row["url"]: row["id"] for row in published}
            for other in state["batches"].values():
                if other is batch or other.get("acknowledged"):
                    continue
                if any(row["url"] in published_versions and row["id"] != published_versions[row["url"]]
                       for row in other["items"]):
                    # A fresh read is required before a different staged
                    # revision can replace a newly published incident report.
                    other["superseded"] = True
        for row in published:
            state["seen"][row["id"]] = self.now.timestamp()
        state["recent"].extend({key: row[key] for key in ("id", "title", "url", "source")} for row in published)
        batch.update(acknowledged=True, page_id=page_id, published_count=len(published))
        return {"profile": config["profile"], "batch_id": batch_id, "page_id": page_id,
                "published_count": len(published), "omitted_selected": len(selected - published_ids),
                "acknowledged": True}
