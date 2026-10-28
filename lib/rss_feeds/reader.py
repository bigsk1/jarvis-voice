"""Fresh, bounded RSS/Atom downloads and conservative plain-text entries."""

from __future__ import annotations

import calendar
import hashlib
import ipaddress
import math
import re
import socket
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import feedparser
import requests
from http_client import http_request
from stash_helper import SecurityError, is_blocked_ip, validate_url

from . import RSSFeedError

MAX_FEED_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
FEED_TIMEOUT_SECONDS = 15
_TRACKING_KEYS = {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid"}
_REDIRECTS = {301, 302, 303, 307, 308}
_XML_DECLARATIONS = re.compile(br"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
_XML_TEXT_REGIONS = re.compile(br"<!--.*?-->|<!\[CDATA\[.*?\]\]>", re.DOTALL)


def canonical_url(url: str, *, base_url: str | None = None) -> str:
    """Normalize an article URL without DNS lookups or fetching its contents."""
    if not isinstance(url, str) or not url.strip() or len(url) > 8192:
        raise RSSFeedError("Feed link is missing or too long")
    value = url.strip()
    if "\\" in value or any(ord(char) < 33 or ord(char) == 127 for char in value):
        raise RSSFeedError("Feed link has unsafe URL characters")
    if base_url:
        value = urljoin(base_url, value)
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
        if (parsed.scheme not in {"http", "https"} or not host or "%" in host
                or parsed.username is not None or parsed.password is not None
                or (port is not None and port <= 0)):
            raise ValueError
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home", ".home.arpa", ".onion")):
            raise ValueError
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            # Reject libc's alternate numeric IPv4 forms without resolving DNS.
            try:
                socket.inet_aton(host)
            except OSError:
                if "." not in host:
                    raise ValueError from None
            else:
                raise ValueError from None
        else:
            if is_blocked_ip(str(literal)):
                raise ValueError
        authority = f"[{host}]" if ":" in host else host.encode("idna").decode("ascii")
        if port is not None and port != (443 if parsed.scheme == "https" else 80):
            authority += f":{port}"
        query = urlencode([(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
                           if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_KEYS])
        return urlunsplit((parsed.scheme, authority, parsed.path or "/", query, ""))
    except (ValueError, UnicodeError):
        raise RSSFeedError("Feed link must use a public HTTP(S) URL without credentials") from None


class _PlainText(HTMLParser):
    def __init__(self, maximum: int):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden: list[str] = []
        self.maximum = maximum
        self.characters = 0
        self.stored = 0
        self.pending_space = False

    def _append(self, value: str):
        self.characters += len(value)
        remaining = self.maximum - self.stored
        if remaining > 0:
            fragment = value[:remaining]
            self.parts.append(fragment)
            self.stored += len(fragment)

    def handle_starttag(self, tag, _attrs):
        if tag in {"script", "style", "iframe", "object", "template", "noscript"}:
            self.hidden.append(tag)
        elif not self.hidden:
            self.pending_space = True

    def handle_endtag(self, tag):
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
        elif not self.hidden:
            self.pending_space = True

    def handle_data(self, data):
        if self.hidden:
            return
        end = 0
        for word in re.finditer(r"\S+", data):
            if self.characters and (self.pending_space or word.start() > end):
                self._append(" ")
            self._append(word.group())
            self.pending_space = False
            end = word.end()
        if end < len(data):
            self.pending_space = True


def _text_with_length(value, maximum: int) -> tuple[str, int]:
    """Keep a bounded clean prefix while counting the complete visible text."""
    if not isinstance(value, str):
        return "", 0
    parser = _PlainText(maximum)
    parser.feed(value)
    parser.close()
    return "".join(parser.parts).rstrip(), parser.characters


def _text(value, maximum: int) -> str:
    return _text_with_length(value, maximum)[0]


def _iso(value: datetime | None) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else ""


def _entry_date(entry, key: str) -> datetime | None:
    # feedparser otherwise aliases missing updated dates to published dates.
    # Keep provenance truthful instead of reporting an invented update time.
    if key + "_parsed" not in entry:
        return None
    value = entry.get(key + "_parsed")
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(value), timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def _proxy_metadata(route: dict) -> dict:
    """Keep only route classifications; never return proxy URLs or credentials."""
    result = {"used": route.get("used") if isinstance(route.get("used"), bool) else None}
    if route.get("policy") in {"inherit", "off", "prefer", "require"}:
        result["policy"] = route["policy"]
    if route.get("slot") in {"LOCAL_PROXY", "LOCAL_PROXY2", "proxy_0", "proxy_1"}:
        result["slot"] = route["slot"]
    if route.get("direct_reason") in {"policy_off", "fallback_after_proxy_failed", "no_proxy_config", "required_proxy_unavailable"}:
        result["direct_reason"] = route["direct_reason"]
    return result


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RSSFeedError("Feed request exceeded its time limit")
    return remaining


def _download(url: str, deadline: float) -> tuple[bytes, str, dict]:
    # Feed URLs retain functional query parameters. Tracking normalization is
    # for article identity only, not a transformation of the requested feed.
    canonical_url(url)
    current = url.strip().split("#", 1)[0]
    for redirects in range(MAX_REDIRECTS + 1):
        _remaining(deadline)
        try:
            validate_url(current)
        except (SecurityError, ValueError, OSError):
            raise RSSFeedError("Feed URL failed the public-address security check") from None
        route = {}
        try:
            response = http_request(
                "GET", current, stream=True, allow_redirects=False,
                timeout=min(FEED_TIMEOUT_SECONDS, _remaining(deadline)),
                deadline=deadline, route_metadata=route,
                headers={"Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9",
                         "Cache-Control": "no-cache, max-age=0", "Pragma": "no-cache"},
            )
            with response:
                _remaining(deadline)
                if response.status_code in _REDIRECTS:
                    location = response.headers.get("Location")
                    if redirects >= MAX_REDIRECTS or not isinstance(location, str) or not location:
                        raise RSSFeedError("Feed redirect limit exceeded or redirect target missing")
                    canonical_url(location, base_url=current)
                    current = urljoin(current, location)
                    continue
                if response.status_code != 200:
                    raise RSSFeedError(f"Feed request returned HTTP {response.status_code}")
                content_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
                if content_type in {"text/html", "application/xhtml+xml"}:
                    raise RSSFeedError("Feed URL returned an HTML page instead of RSS or Atom")
                body = bytearray()
                for chunk in response.iter_content(chunk_size=16384):
                    _remaining(deadline)
                    body.extend(chunk)
                    if len(body) > MAX_FEED_BYTES:
                        raise RSSFeedError("Feed response exceeded the 2 MiB size limit")
                _remaining(deadline)
                return bytes(body), current, _proxy_metadata(route)
        except requests.RequestException:
            raise RSSFeedError("Feed request failed or timed out") from None
    raise RSSFeedError("Feed redirect limit exceeded")


def _parse(body: bytes, url: str):
    # CDATA commonly contains complete article HTML, including its HTML
    # doctype. Comments and CDATA cannot declare XML entities. Exclude those
    # regions from this pre-parser check, preserving the original parse input.
    # Null removal also recognizes real declarations in UTF-16/32 encodings.
    declaration_input = _XML_TEXT_REGIONS.sub(b"", body.replace(b"\x00", b""))
    if _XML_DECLARATIONS.search(declaration_input):
        raise RSSFeedError("Feed XML declarations containing DTDs or entities are not supported")
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise RSSFeedError("Feed response is not well-formed XML") from None
    if root.tag == "rss":
        valid = root.find("channel") is not None
    elif root.tag in {"{http://www.w3.org/2005/Atom}feed", "{http://purl.org/atom/ns#}feed"}:
        valid = True
    elif root.tag == "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF":
        valid = root.find("{http://purl.org/rss/1.0/}channel") is not None
    else:
        valid = False
    if not valid:
        raise RSSFeedError("Feed response has no supported RSS or Atom envelope")
    try:
        # XML was validated above. Supplying a base URL without an XML MIME
        # type makes feedparser report a spurious NonXMLContentType warning.
        parsed = feedparser.parse(body, response_headers={"content-location": url,
                                                        "content-type": "application/xml"})
    except Exception:
        raise RSSFeedError("Feed response could not be parsed") from None
    if not parsed.get("version") or parsed.get("bozo"):
        raise RSSFeedError("Feed response is malformed or unsupported")
    return parsed


def _article(entry, feed_url: str) -> dict | None:
    links = [link.get("href") for link in entry.get("links", [])
             if isinstance(link, dict) and link.get("rel", "alternate") == "alternate"
             and link.get("type", "text/html") in {"text/html", "application/xhtml+xml", ""}]
    links.append(entry.get("link"))
    article_url = ""
    for link in links:
        try:
            article_url = canonical_url(link, base_url=feed_url)
        except RSSFeedError:
            continue
        break
    if not article_url:
        return None
    content_parts = entry.get("content", [])
    out_of_line = any(isinstance(part, dict) and part.get("src") for part in content_parts)
    inline = " ".join(part.get("value", "") for part in content_parts
                      if isinstance(part, dict) and isinstance(part.get("value"), str))
    raw_summary = entry.get("summary", "")
    summary_text, summary_chars = _text_with_length(raw_summary, 6000)
    inline_text, inline_chars = ((summary_text, summary_chars) if inline == raw_summary
                                else _text_with_length(inline, 6000))
    content, content_chars = ((inline_text, inline_chars) if inline_chars
                              else (summary_text, summary_chars))
    content_kind = "out_of_line" if out_of_line else "inline" if inline_chars else "summary"
    content_truncated = content_chars > len(content)
    categories = list(dict.fromkeys(_text(tag.get("term"), 80) for tag in entry.get("tags", [])
                                    if isinstance(tag, dict) and _text(tag.get("term"), 80)))[:12]
    return {
        "id": hashlib.sha256(article_url.encode()).hexdigest(),
        "url": article_url,
        "title": _text(entry.get("title", ""), 400),
        "summary": summary_text[:1200].rstrip(),
        "content": content,
        "content_chars": content_chars,
        "content_truncated": content_truncated,
        "content_kind": content_kind,
        "published_at": _iso(_entry_date(entry, "published")),
        "updated_at": _iso(_entry_date(entry, "updated")),
        "categories": categories,
        # A lengthy teaser is still a summary. Only substantive explicit
        # inline content can stand in for fetching the article itself.
        "needs_fetch": bool(content_kind != "inline" or content_truncated or len(content) < 500),
    }


def read_feed(url: str, *, now: datetime | None = None, max_age_hours: int = 48,
              limit: int = 20, deadline: float | None = None) -> dict:
    """Fetch once, then select recent dated entries; no cached/stale fallback."""
    if (isinstance(max_age_hours, bool) or not isinstance(max_age_hours, int)
            or not 1 <= max_age_hours <= 8760 or isinstance(limit, bool)
            or not isinstance(limit, int) or not 1 <= limit <= 100):
        raise RSSFeedError("Feed age must be 1–8760 hours and item limit 1–100")
    if deadline is not None and (not isinstance(deadline, (int, float)) or not math.isfinite(deadline)):
        raise RSSFeedError("Feed deadline must be a finite monotonic timestamp")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    deadline = min(deadline, time.monotonic() + FEED_TIMEOUT_SECONDS) if deadline is not None else time.monotonic() + FEED_TIMEOUT_SECONDS
    body, final_url, proxy = _download(url, deadline)
    parsed = _parse(body, final_url)
    _remaining(deadline)
    cutoff = now - timedelta(hours=max_age_hours)
    recent = []
    seen = set()
    undated = 0
    for entry in parsed.entries:
        _remaining(deadline)
        published = _entry_date(entry, "published")
        updated = _entry_date(entry, "updated")
        dated = published or updated
        if dated is None:
            undated += 1
            continue
        if dated < cutoff or dated > now + timedelta(minutes=15):
            continue
        article = _article(entry, final_url)
        if article and article["url"] not in seen:
            recent.append((dated, article))
            seen.add(article["url"])
    recent.sort(key=lambda row: row[0], reverse=True)
    _remaining(deadline)
    return {"url": final_url, "title": _text(parsed.feed.get("title", ""), 400),
            "checked_at": _iso(now), "items": [article for _, article in recent[:limit]],
            "total_items": len(parsed.entries), "undated_skipped": undated, "proxy": proxy}
