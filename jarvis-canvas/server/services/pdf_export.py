"""Build safe, portable PDF snapshots from Canvas page JSON."""

from __future__ import annotations

import html
import http.client
import ipaddress
import re
import socket
import ssl
import time
import unicodedata
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import fitz
from fpdf import FPDF
from fpdf.fonts import FontFace, TextStyle
from markdown_it import MarkdownIt
from PIL import Image, ImageOps, UnidentifiedImageError

from security_utils import redact_sensitive_text


PROJECT_ROOT = Path(__file__).resolve().parents[3]
FONT_DIR = PROJECT_ROOT / "jarvis-web" / "client" / "fonts"
MAX_PDF_BYTES = 8 * 1024 * 1024
MAX_EMBEDDED_MEDIA_ITEMS = 12
MAX_YOUTUBE_THUMBNAIL_CARDS = 4
MAX_EMBEDDED_MEDIA_TOTAL_BYTES = 5 * 1024 * 1024
MAX_REMOTE_IMAGE_BYTES = 6 * 1024 * 1024
MAX_REMOTE_IMAGE_PIXELS = 20_000_000
MAX_REMOTE_IMAGE_DIMENSION = 1600
REMOTE_MEDIA_RENDER_BUDGET_SECONDS = 15.0
REMOTE_IMAGE_TIMEOUT_SECONDS = 4.0
REMOTE_IMAGE_MAX_REDIRECTS = 3
_MEDIA_TOKEN_PREFIX = "JARVIS_CANVAS_MEDIA_"
_MEDIA_HTML_RE = re.compile(
    rf"<p(?:\s[^>]*)?>\s*@@{_MEDIA_TOKEN_PREFIX}(\d+)@@\s*</p>",
    re.IGNORECASE,
)

_STASH_IMAGE_RE = re.compile(
    r"!\[([^\]]*)\]\(\s*(?:stash://|/(?:api/stash|stash/view)/)[^)]+\)",
    re.IGNORECASE,
)
_STASH_REF_RE = re.compile(
    r"(?:stash://[^\s)`\"']+|/(?:api/stash|stash/view)/[^\s)`\"']+)",
    re.IGNORECASE,
)
_PUBLIC_IMAGE_RE = re.compile(
    r"!\[([^\]]*)\]\(\s*(https://[^\s)]+)(?:\s+[\"'][^)]*[\"'])?\s*\)",
    re.IGNORECASE,
)
_STANDALONE_PUBLIC_IMAGE_RE = re.compile(
    r"^[ \t]*!\[([^\]\n]*)\]\(\s*(https://[^\s)]+)(?:\s+[\"'][^)]*[\"'])?\s*\)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
_OTHER_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(\s*[^)]+\)", re.IGNORECASE)
_REFERENCE_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\s*\[[^\]]*\]", re.IGNORECASE)
_STANDALONE_MARKDOWN_LINK_RE = re.compile(
    r"^[ \t]*\[([^\]\n]+)\]\(\s*(https://[^\s)]+)(?:\s+[\"'][^)]*[\"'])?\s*\)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
_MARKDOWN_LINK_RE = re.compile(
    r"(?<!!)\[([^\]]+)\]\(\s*([^\s)]+)(?:\s+[\"'][^)]*[\"'])?\s*\)",
    re.IGNORECASE,
)
_STANDALONE_HTTPS_URL_RE = re.compile(
    r"^[ \t]*(https://[^\s<>)\]`\"']+)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
_URL_RE = re.compile(r"https?://[^\s<>)\]`\"']+", re.IGNORECASE)
_LOCAL_PATH_RE = re.compile(
    r"(?<![\w:/])(?:/(?:home|Users)/[^\s)`\"']+|[A-Za-z]:\\(?:Users|Documents)\\[^\s)`\"']+)",
)
_CRYPTO_CHART_RE = re.compile(r"```crypto-chart\s*\n.*?```", re.IGNORECASE | re.DOTALL)
_OUTER_MARKDOWN_FENCE_RE = re.compile(
    r"^```(?:markdown|md)\s*\n(?P<body>.*)\n```\s*$",
    re.IGNORECASE | re.DOTALL,
)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PRIVATE_KEY_MARKER_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE)
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0000FE0F"
    "\U0000200D"
    "]+"
)


class CanvasPDF(FPDF):
    """Small branded PDF shell used by Canvas exports."""

    def __init__(self, title: str):
        super().__init__(format="A4")
        self.canvas_title = title
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(18, 20, 18)

    def header(self):
        self.set_font("Inter", "B", 8)
        self.set_text_color(90, 98, 108)
        self.cell(0, 6, self.canvas_title[:100], align="L")
        self.ln(10)

    def footer(self):
        self.set_y(-13)
        self.set_font("Inter", "", 7)
        self.set_text_color(120, 128, 138)
        self.cell(0, 6, f"Shared from Jarvis Canvas  |  Page {self.page_no()}", align="C")


def _finding(severity: str, code: str, message: str, *, line: int | None = None) -> dict:
    result = {"severity": severity, "code": code, "message": message}
    if line is not None:
        result["line"] = line
    return result


def _append_once(findings: list[dict], finding: dict) -> None:
    key = (finding["severity"], finding["code"], finding.get("line"))
    if any((item["severity"], item["code"], item.get("line")) == key for item in findings):
        return
    findings.append(finding)


def _is_private_or_local_url(raw_url: str) -> bool:
    try:
        parsed = urlparse(raw_url)
        host = (parsed.hostname or "").strip().lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            return True
        address = ipaddress.ip_address(host)
        return bool(
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
        )
    except ValueError:
        return False


def _url_kind(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if host in {
        "youtu.be",
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }:
        return "youtube"
    if path.endswith((".mp4", ".webm", ".mov", ".m4v")):
        return "video"
    if path.endswith((".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus")):
        return "audio"
    return "link"


class _UnsafeRemoteMedia(ValueError):
    """Raised when a media URL is not safe for server-side retrieval."""


@dataclass(frozen=True)
class _EmbeddedImage:
    payload: bytes
    width: int
    height: int


def _youtube_video_id(raw_url: str) -> str | None:
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    path_parts = [part for part in parsed.path.split("/") if part]
    candidate = None
    if host == "youtu.be" and path_parts:
        candidate = path_parts[0]
    elif host in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }:
        candidate = (parse_qs(parsed.query).get("v") or [None])[0]
        if not candidate and len(path_parts) >= 2 and path_parts[0].lower() in {
            "embed",
            "live",
            "shorts",
        }:
            candidate = path_parts[1]
    if candidate and re.fullmatch(r"[A-Za-z0-9_-]{6,32}", candidate):
        return candidate
    return None


def _public_https_target(raw_url: str) -> tuple[str, str, list[tuple]]:
    """Validate an HTTPS URL and return a DNS-pinned connection target."""
    if len(raw_url) > 2048 or any(ord(char) < 32 for char in raw_url):
        raise _UnsafeRemoteMedia("Invalid media URL")
    parsed = urlparse(raw_url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise _UnsafeRemoteMedia("Remote media must use HTTPS")
    if parsed.username or parsed.password:
        raise _UnsafeRemoteMedia("Credential-bearing media URLs are not allowed")
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise _UnsafeRemoteMedia("Invalid media port") from exc
    if port != 443:
        raise _UnsafeRemoteMedia("Remote media must use the standard HTTPS port")

    host = parsed.hostname.rstrip(".").lower()
    if not host or host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise _UnsafeRemoteMedia("Local media hosts are not allowed")
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise _UnsafeRemoteMedia("Invalid media host") from exc

    try:
        addresses = socket.getaddrinfo(
            ascii_host,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except OSError as exc:
        raise OSError("Remote media host could not be resolved") from exc
    if not addresses:
        raise OSError("Remote media host could not be resolved")

    unique_addresses = []
    seen = set()
    for family, socktype, proto, canonname, sockaddr in addresses:
        address = ipaddress.ip_address(sockaddr[0])
        if not address.is_global:
            raise _UnsafeRemoteMedia("Remote media resolved to a non-public address")
        key = (family, sockaddr)
        if key not in seen:
            seen.add(key)
            unique_addresses.append((family, socktype, proto, canonname, sockaddr))

    target = parsed.path or "/"
    if parsed.query:
        target += f"?{parsed.query}"
    try:
        target.encode("ascii")
    except UnicodeEncodeError as exc:
        raise _UnsafeRemoteMedia("Media URL paths must be percent encoded") from exc
    return ascii_host, target, unique_addresses


def _download_public_https(
    raw_url: str,
    *,
    timeout: float,
    max_bytes: int = MAX_REMOTE_IMAGE_BYTES,
) -> tuple[bytes, str]:
    """Download an image without allowing redirects or DNS to reach private networks."""
    current_url = raw_url
    deadline = time.monotonic() + timeout
    ssl_context = ssl.create_default_context()
    for redirect_count in range(REMOTE_IMAGE_MAX_REDIRECTS + 1):
        host, target, addresses = _public_https_target(current_url)
        response = None
        tls_socket = None
        last_error = None
        for family, socktype, proto, _canonname, sockaddr in addresses:
            raw_socket = socket.socket(family, socktype, proto)
            candidate_tls_socket = None
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Remote media download timed out")
                raw_socket.settimeout(remaining)
                raw_socket.connect(sockaddr)
                candidate_tls_socket = ssl_context.wrap_socket(raw_socket, server_hostname=host)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Remote media download timed out")
                candidate_tls_socket.settimeout(remaining)
                request_bytes = (
                    f"GET {target} HTTP/1.1\r\n"
                    f"Host: {'[' + host + ']' if ':' in host else host}\r\n"
                    "User-Agent: Jarvis-Canvas-PDF/1.0\r\n"
                    "Accept: image/png,image/jpeg,image/webp,image/gif\r\n"
                    "Accept-Encoding: identity\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("ascii")
                candidate_tls_socket.sendall(request_bytes)
                response = http.client.HTTPResponse(candidate_tls_socket, method="GET")
                response.begin()
                tls_socket = candidate_tls_socket
                break
            except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
                last_error = exc
                if candidate_tls_socket is not None:
                    candidate_tls_socket.close()
                else:
                    raw_socket.close()
        if response is None or tls_socket is None:
            raise OSError("Remote media could not be downloaded") from last_error

        try:
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location or redirect_count >= REMOTE_IMAGE_MAX_REDIRECTS:
                    raise OSError("Remote media redirected too many times")
                current_url = urljoin(current_url, location)
                continue
            if response.status != 200:
                raise OSError("Remote media returned an unsuccessful response")

            content_type = (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
            if content_type not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
                raise ValueError("Remote media did not return a supported image type")
            content_length = response.getheader("Content-Length")
            if content_length:
                try:
                    declared_length = int(content_length)
                except ValueError:
                    declared_length = None
                if declared_length is not None and declared_length > max_bytes:
                    raise ValueError("Remote image exceeds the download limit")

            chunks = []
            total = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Remote media download timed out")
                tls_socket.settimeout(remaining)
                chunk = response.read(min(64 * 1024, max_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("Remote image exceeds the download limit")
                chunks.append(chunk)
            return b"".join(chunks), content_type
        finally:
            response.close()
            tls_socket.close()
    raise OSError("Remote media redirected too many times")


def _normalize_embedded_image(payload: bytes) -> _EmbeddedImage:
    """Decode untrusted image bytes, cap their pixels, and strip metadata."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(payload)) as probe:
                width, height = probe.size
                if width < 1 or height < 1 or width * height > MAX_REMOTE_IMAGE_PIXELS:
                    raise ValueError("Remote image dimensions exceed the limit")
                probe.verify()
            with Image.open(BytesIO(payload)) as source:
                source.seek(0)
                source.load()
                normalized = ImageOps.exif_transpose(source)
                normalized.thumbnail(
                    (MAX_REMOTE_IMAGE_DIMENSION, MAX_REMOTE_IMAGE_DIMENSION),
                    Image.Resampling.LANCZOS,
                )
                has_alpha = normalized.mode in {"RGBA", "LA"} or "transparency" in normalized.info
                output = BytesIO()
                if has_alpha:
                    normalized.convert("RGBA").save(output, format="PNG", optimize=True)
                else:
                    normalized.convert("RGB").save(
                        output,
                        format="JPEG",
                        quality=84,
                        optimize=True,
                        progressive=False,
                    )
                return _EmbeddedImage(output.getvalue(), normalized.width, normalized.height)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError, OSError) as exc:
        raise ValueError("Remote image could not be safely decoded") from exc


def _fetch_public_image_asset(raw_url: str, *, timeout: float) -> _EmbeddedImage:
    payload, _content_type = _download_public_https(raw_url, timeout=timeout)
    return _normalize_embedded_image(payload)


def _strip_emoji(text: str, findings: list[dict]) -> str:
    stripped, count = _EMOJI_RE.subn("", text)
    if count:
        _append_once(
            findings,
            _finding(
                "info",
                "emoji_omitted",
                "Emoji were omitted because the portable PDF font does not cover every emoji glyph.",
            ),
        )
    return stripped


def _normalize_plain_metadata(value, findings: list[dict], *, max_chars: int) -> str:
    """Keep titles/tags one-line and remove local destinations before rendering."""
    text = " ".join(str(value or "").replace("\x00", "").split())
    text = _strip_emoji(text, findings)

    def replace_url(match: re.Match) -> str:
        url = match.group(0)
        if urlparse(url).scheme.lower() != "https" or _is_private_or_local_url(url):
            _append_once(
                findings,
                _finding(
                    "warn",
                    "metadata_link_omitted",
                    "A non-public link was omitted from Canvas title or tag metadata.",
                ),
            )
            return "[link omitted]"
        return url

    text = _URL_RE.sub(replace_url, text)
    text, path_count = _LOCAL_PATH_RE.subn("[local path omitted]", text)
    if path_count:
        _append_once(
            findings,
            _finding(
                "warn",
                "local_path_omitted",
                "A local filesystem path was omitted from the PDF.",
            ),
        )
    return text[:max_chars].strip()


def _normalize_timestamp(value, findings: list[dict], field_name: str) -> str | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError):
        _append_once(
            findings,
            _finding(
                "warn",
                "invalid_timestamp_omitted",
                f"Invalid Canvas {field_name} metadata was omitted from the PDF.",
            ),
        )
        return None


def _escape_markdown_inline(text: str) -> str:
    return re.sub(r"([\\`*_\[\]<>#|])", r"\\\1", text)


def _media_token(index: int) -> str:
    return f"\n\n@@{_MEDIA_TOKEN_PREFIX}{index}@@\n\n"


def _queue_public_media(
    media: list[dict],
    findings: list[dict],
    *,
    kind: str,
    url: str,
    label: str,
) -> str | None:
    if any(item.get("kind") == kind and item.get("url") == url for item in media):
        return None
    if kind == "youtube" and sum(item.get("kind") == "youtube" for item in media) >= MAX_YOUTUBE_THUMBNAIL_CARDS:
        _append_once(
            findings,
            _finding(
                "warn",
                "youtube_thumbnail_limit_reached",
                f"Only the first {MAX_YOUTUBE_THUMBNAIL_CARDS} YouTube references receive thumbnail cards.",
            ),
        )
        return None
    if len(media) >= MAX_EMBEDDED_MEDIA_ITEMS:
        _append_once(
            findings,
            _finding(
                "warn",
                "public_media_limit_reached",
                f"Only the first {MAX_EMBEDDED_MEDIA_ITEMS} public media items receive embedded previews.",
            ),
        )
        return None
    cleaned_label = " ".join(str(label or "").replace("\x00", "").split())[:180]
    cleaned_label = _strip_emoji(cleaned_label, findings) or (
        "YouTube video" if kind == "youtube" else "Public image"
    )
    item = {"kind": kind, "url": url, "label": cleaned_label}
    if kind == "youtube":
        video_id = _youtube_video_id(url)
        if not video_id:
            return None
        item["thumbnail_url"] = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    media.append(item)
    return _media_token(len(media) - 1)


def _promote_youtube_source_lines(
    content: str,
    media: list[dict],
    findings: list[dict],
) -> str:
    """Turn common standalone/source-list YouTube references into media cards."""
    output = []
    inside_fence = False
    for line in content.split("\n"):
        stripped = line.strip()
        if re.match(r"^(?:```|~~~)", stripped):
            inside_fence = not inside_fence
            output.append(line)
            continue
        if inside_fence or (stripped.startswith("|") and stripped.endswith("|")):
            output.append(line)
            continue

        youtube_urls = [
            match.group(0)
            for match in _URL_RE.finditer(line)
            if _url_kind(match.group(0)) == "youtube"
        ]
        if len(youtube_urls) != 1:
            output.append(line)
            continue

        url = youtube_urls[0]
        list_body = re.sub(r"^[-*+]\s+", "", stripped)
        markdown_link = next(
            (
                match
                for match in _MARKDOWN_LINK_RE.finditer(line)
                if match.group(2) == url
            ),
            None,
        )
        source_labels = {
            "",
            "source",
            "source video",
            "video",
            "youtube",
            "youtube video",
            "featured video",
            "watch",
        }
        labeled_markdown_link = False
        if markdown_link is not None:
            prefix = re.sub(r"[*_`>#]", "", line[: markdown_link.start()]).strip()
            prefix = re.sub(r"^[-+]\s+", "", prefix).strip().rstrip(":").lower()
            suffix = line[markdown_link.end() :].strip()
            labeled_markdown_link = not suffix and prefix in source_labels
        bare_prefix = list_body.replace(url, "", 1).strip().rstrip(":").lower()
        eligible = (
            stripped == url
            or list_body == url
            or labeled_markdown_link
            or (bool(re.match(r"^[-*+]\s+", stripped)) and bare_prefix in source_labels)
        )
        if not eligible:
            output.append(line)
            continue

        label = markdown_link.group(1) if markdown_link is not None else "YouTube video"
        token = _queue_public_media(
            media,
            findings,
            kind="youtube",
            url=url,
            label=label,
        )
        if token is None:
            output.append(line)
            continue
        _append_once(
            findings,
            _finding(
                "info",
                "public_youtube_linked",
                "YouTube playback remains a clickable link; a thumbnail is embedded when available.",
            ),
        )
        output.append(token)
    return "\n".join(output)


def _normalize_markdown(content: str, findings: list[dict], media: list[dict]) -> str:
    content = str(content or "").replace("\r\n", "\n")
    outer = _OUTER_MARKDOWN_FENCE_RE.match(content.strip())
    if outer:
        content = outer.group("body").strip()

    content, chart_count = _CRYPTO_CHART_RE.subn(
        "\n\n> Interactive chart omitted from this PDF snapshot.\n\n",
        content,
    )
    if chart_count:
        _append_once(
            findings,
            _finding(
                "info",
                "interactive_chart_omitted",
                f"{chart_count} interactive chart block(s) were replaced with a PDF placeholder.",
            ),
        )

    content, stash_image_count = _STASH_IMAGE_RE.subn(
        "\n\n> Local Canvas image omitted from this PDF snapshot.\n\n",
        content,
    )
    content, stash_ref_count = _STASH_REF_RE.subn("[local Canvas media omitted]", content)
    if stash_image_count or stash_ref_count:
        _append_once(
            findings,
            _finding(
                "info",
                "local_media_omitted",
                "Local stash media was replaced with a placeholder; no stash identifier or file was published.",
            ),
        )

    public_image_count = 0

    def queue_public_image(match: re.Match) -> str:
        nonlocal public_image_count
        alt = (match.group(1) or "Public image").strip() or "Public image"
        url = match.group(2)
        if _is_private_or_local_url(url):
            _append_once(
                findings,
                _finding(
                    "warn",
                    "local_image_omitted",
                    "A local or private-network image was omitted from the PDF.",
                ),
            )
            return f"\n\n> {alt}: local image omitted from this PDF snapshot.\n\n"
        public_image_count += 1
        token = _queue_public_media(
            media,
            findings,
            kind="image",
            url=url,
            label=alt,
        )
        if token is None:
            return (
                f"\n\n**Public image:** [{alt}]({url})  \n"
                "_The image is linked because the embedded-media limit was reached._\n\n"
            )
        _append_once(
            findings,
            _finding(
                "warn",
                "remote_image_content_unscanned",
                "Public image pixels are embedded in the PDF but are not checked by the text credential scanner.",
            ),
        )
        return token

    content = _STANDALONE_PUBLIC_IMAGE_RE.sub(
        queue_public_image,
        content,
    )

    def link_public_image(match: re.Match) -> str:
        nonlocal public_image_count
        alt = (match.group(1) or "Public image").strip() or "Public image"
        url = match.group(2)
        if _is_private_or_local_url(url):
            _append_once(
                findings,
                _finding(
                    "warn",
                    "local_image_omitted",
                    "A local or private-network image was omitted from the PDF.",
                ),
            )
            return f"\n\n> {alt}: local image omitted from this PDF snapshot.\n\n"
        public_image_count += 1
        return (
            f"\n\n**Public image:** [{alt}]({url})  \n"
            "_Inline images are linked rather than embedded in this PDF._\n\n"
        )

    content = _PUBLIC_IMAGE_RE.sub(link_public_image, content)
    if public_image_count:
        _append_once(
            findings,
            _finding(
                "info",
                "public_image_linked",
                "Public images remain clickable whether their previews are embedded or represented by fallback links.",
            ),
        )

    def replace_other_image(match: re.Match) -> str:
        alt = (match.group(1) or "Image").strip() or "Image"
        return f"\n\n> {alt}: image omitted from this PDF snapshot.\n\n"

    content, other_image_count = _OTHER_IMAGE_RE.subn(replace_other_image, content)
    content, reference_image_count = _REFERENCE_IMAGE_RE.subn(replace_other_image, content)
    if other_image_count or reference_image_count:
        _append_once(
            findings,
            _finding(
                "warn",
                "unsupported_image_omitted",
                "A non-public or unsupported Markdown image was omitted from the PDF.",
            ),
        )

    content = _promote_youtube_source_lines(content, media, findings)

    def queue_standalone_youtube_link(match: re.Match) -> str:
        label, url = match.group(1), match.group(2)
        if _url_kind(url) != "youtube" or _is_private_or_local_url(url):
            return match.group(0)
        token = _queue_public_media(
            media,
            findings,
            kind="youtube",
            url=url,
            label=label,
        )
        if token is None:
            return match.group(0)
        _append_once(
            findings,
            _finding(
                "info",
                "public_youtube_linked",
                "YouTube playback remains a clickable link; a thumbnail is embedded when available.",
            ),
        )
        return token

    content = _STANDALONE_MARKDOWN_LINK_RE.sub(queue_standalone_youtube_link, content)

    def replace_markdown_link(match: re.Match) -> str:
        label, url = match.group(1), match.group(2)
        parsed = urlparse(url)
        if parsed.scheme.lower() != "https":
            _append_once(
                findings,
                _finding("warn", "non_https_link_omitted", "A non-HTTPS link was omitted from the PDF."),
            )
            return f"{label} [non-HTTPS link omitted]"
        if _is_private_or_local_url(url):
            _append_once(
                findings,
                _finding("warn", "local_link_omitted", "A local or private-network link was omitted from the PDF."),
            )
            return f"{label} [local link omitted]"
        return match.group(0)

    content = _MARKDOWN_LINK_RE.sub(replace_markdown_link, content)

    def queue_standalone_youtube_url(match: re.Match) -> str:
        url = match.group(1)
        if _url_kind(url) != "youtube" or _is_private_or_local_url(url):
            return match.group(0)
        token = _queue_public_media(
            media,
            findings,
            kind="youtube",
            url=url,
            label="YouTube video",
        )
        if token is None:
            return match.group(0)
        _append_once(
            findings,
            _finding(
                "info",
                "public_youtube_linked",
                "YouTube playback remains a clickable link; a thumbnail is embedded when available.",
            ),
        )
        return token

    content = _STANDALONE_HTTPS_URL_RE.sub(queue_standalone_youtube_url, content)

    def replace_bare_url(match: re.Match) -> str:
        url = match.group(0)
        parsed = urlparse(url)
        if parsed.scheme.lower() != "https":
            _append_once(
                findings,
                _finding("warn", "non_https_link_omitted", "A non-HTTPS link was omitted from the PDF."),
            )
            return "[non-HTTPS link omitted]"
        if _is_private_or_local_url(url):
            _append_once(
                findings,
                _finding("warn", "local_link_omitted", "A local or private-network link was omitted from the PDF."),
            )
            return "[local link omitted]"
        kind = _url_kind(url)
        if kind in {"youtube", "video", "audio"}:
            _append_once(
                findings,
                _finding(
                    "info",
                    f"public_{kind}_linked",
                    f"Public {kind} content is kept as a clickable link; playback is not embedded in the PDF.",
                ),
            )
        return url

    content = _URL_RE.sub(replace_bare_url, content)

    content, local_path_count = _LOCAL_PATH_RE.subn("[local path omitted]", content)
    if local_path_count:
        _append_once(
            findings,
            _finding("warn", "local_path_omitted", "A local filesystem path was omitted from the PDF."),
        )

    return _strip_emoji(content, findings).strip()


def _scan_sensitive_text(text: str, findings: list[dict]) -> None:
    full_redacted = redact_sensitive_text(text)
    if full_redacted == text and not _PRIVATE_KEY_MARKER_RE.search(text):
        return

    found_line = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        if redact_sensitive_text(line) != line or _PRIVATE_KEY_MARKER_RE.search(line):
            _append_once(
                findings,
                _finding(
                    "block",
                    "secret_like_content",
                    "Secret-like credential material was detected. Remove it before publishing.",
                    line=line_number,
                ),
            )
            found_line = True
    if not found_line:
        _append_once(
            findings,
            _finding(
                "block",
                "secret_like_content",
                "Secret-like credential material was detected. Remove it before publishing.",
            ),
        )


def build_canvas_pdf_projection(page: dict) -> dict:
    """Return the normalized PDF projection and publish-safety findings."""
    findings: list[dict] = []
    public_media: list[dict] = []
    title = _normalize_plain_metadata(
        page.get("title") or "Untitled Canvas Page",
        findings,
        max_chars=200,
    )
    content = _normalize_markdown(
        str(page.get("content") or ""),
        findings,
        public_media,
    )
    raw_tags = page.get("tags", [])
    tags = (
        [
            normalized
            for tag in raw_tags[:20]
            if (normalized := _normalize_plain_metadata(tag, findings, max_chars=80))
        ]
        if isinstance(raw_tags, list)
        else []
    )
    created = _normalize_timestamp(page.get("created"), findings, "created")
    updated = _normalize_timestamp(page.get("updated"), findings, "updated")

    if page.get("source_query"):
        _append_once(
            findings,
            _finding("info", "source_query_omitted", "The original source query is not included in PDF exports."),
        )

    media_text = [
        value
        for item in public_media
        for value in (str(item.get("label") or ""), str(item.get("url") or ""))
    ]
    scanned_text = "\n".join([title, content, *tags, *media_text])
    _scan_sensitive_text(scanned_text, findings)
    if _EMAIL_RE.search(scanned_text):
        _append_once(
            findings,
            _finding("warn", "email_address_present", "An email address is present in the PDF content."),
        )

    severity_order = {"block": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda item: (severity_order[item["severity"]], item.get("line", 0), item["code"]))
    return {
        "schema_version": 2,
        "title": title or "Untitled Canvas Page",
        "content_markdown": content,
        "public_media": public_media,
        "tags": tags,
        "created": created,
        "updated": updated,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "findings": findings,
    }


def _register_fonts(pdf: FPDF) -> None:
    regular = FONT_DIR / "InterVariable.woff2"
    italic = FONT_DIR / "Inter-Italic.woff2"
    mono_files = {
        "": FONT_DIR / "JetBrainsMono-Regular.woff2",
        "B": FONT_DIR / "JetBrainsMono-Bold.woff2",
        "I": FONT_DIR / "JetBrainsMono-Italic.woff2",
        "BI": FONT_DIR / "JetBrainsMono-BoldItalic.woff2",
    }
    for path in [regular, italic, *mono_files.values()]:
        if not path.exists():
            raise RuntimeError(f"Required Canvas PDF font is missing: {path.name}")

    pdf.add_font(
        "Inter",
        "",
        str(regular),
        variations={"wght": 400, "opsz": 14},
    )
    pdf.add_font(
        "Inter",
        "B",
        str(regular),
        variations={"wght": 680, "opsz": 22},
    )
    pdf.add_font("Inter", "I", str(italic))
    pdf.add_font("Inter", "BI", str(italic))
    for style, path in mono_files.items():
        pdf.add_font("JetBrainsMono", style, str(path))


def _markdown_to_html(markdown: str) -> str:
    renderer = MarkdownIt(
        "commonmark",
        {"html": False, "linkify": True, "typographer": False},
    )
    renderer.enable(["linkify", "strikethrough", "table"])
    return renderer.render(markdown)


class _PDFTableCellFlattener(HTMLParser):
    """Flatten rich table cells and collect their links for a PDF-safe appendix."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.cell_depth = 0
        self.active_link: dict | None = None
        self.links: list[tuple[str, str]] = []
        self.flattened = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"td", "th"}:
            start_tag = self.get_starttag_text()
            if tag == "td" and not any(name.lower() == "align" for name, _value in attrs):
                start_tag = start_tag[:-1] + ' align="LEFT">'
            self.output.append(start_tag)
            self.cell_depth += 1
            return
        if not self.cell_depth:
            self.output.append(self.get_starttag_text())
            return

        self.flattened = True
        if tag == "a":
            href = next((value for name, value in attrs if name.lower() == "href"), None)
            self.active_link = {"href": href or "", "label": []}
        elif tag == "br":
            self.output.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"}:
            if self.active_link is not None:
                self._finish_link()
            self.cell_depth = max(0, self.cell_depth - 1)
            self.output.append(f"</{tag}>")
            return
        if self.cell_depth:
            if tag == "a" and self.active_link is not None:
                self._finish_link()
            return
        self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.output.append(html.escape(data))
        if self.active_link is not None:
            self.active_link["label"].append(data)

    def handle_entityref(self, name: str) -> None:
        self.handle_data(html.unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self.handle_data(html.unescape(f"&#{name};"))

    def _finish_link(self) -> None:
        href = str(self.active_link.get("href") or "").strip()
        label = " ".join("".join(self.active_link.get("label") or []).split())
        if (
            href
            and urlparse(href).scheme.lower() == "https"
            and not _is_private_or_local_url(href)
        ):
            self.links.append((label or href, href))
        self.active_link = None


def _flatten_pdf_table_cells(html_text: str) -> tuple[str, list[tuple[str, str]], bool]:
    parser = _PDFTableCellFlattener()
    parser.feed(html_text)
    parser.close()
    unique_links = list(dict.fromkeys(parser.links))
    return "".join(parser.output), unique_links, parser.flattened


def _apply_pdf_typography(html_text: str) -> str:
    """Apply line-height where fpdf2 accepts it through inline HTML styles."""

    def add_line_height(match: re.Match) -> str:
        tag = match.group("tag")
        attrs = match.group("attrs") or ""
        line_height = "1.38" if tag in {"ul", "ol"} else "1.34"
        if re.search(r"\bstyle\s*=", attrs, re.IGNORECASE):
            return match.group(0)
        return f'<{tag}{attrs} style="line-height: {line_height}">'

    return re.sub(
        r"<(?P<tag>p|ul|ol)(?P<attrs>[^>]*)>",
        add_line_height,
        html_text,
        flags=re.IGNORECASE,
    )


def _write_pdf_html(pdf: FPDF, html_text: str, tag_styles: dict) -> None:
    if not html_text.strip():
        return
    pdf.write_html(
        html_text,
        font_family="Inter",
        li_prefix_color="#64748b",
        table_line_separators=True,
        tag_styles=tag_styles,
    )


def _fit_pdf_text(pdf: FPDF, text: str, max_width: float) -> str:
    cleaned = " ".join(str(text or "").split())
    if pdf.get_string_width(cleaned) <= max_width:
        return cleaned
    suffix = "..."
    while cleaned and pdf.get_string_width(cleaned + suffix) > max_width:
        cleaned = cleaned[:-1]
    return (cleaned.rstrip() + suffix) if cleaned else suffix


def _render_embedded_media_card(pdf: FPDF, item: dict, asset: _EmbeddedImage) -> None:
    content_width = pdf.w - pdf.l_margin - pdf.r_margin
    image_max_width = min(content_width - 10, 150 if item["kind"] == "image" else 138)
    image_max_height = 92
    scale = min(
        image_max_width / asset.width,
        image_max_height / asset.height,
        25.4 / 96,
    )
    image_width = max(1, asset.width * scale)
    image_height = max(1, asset.height * scale)
    card_height = image_height + 21
    if pdf.get_y() + card_height + 4 > pdf.h - pdf.b_margin:
        pdf.add_page()

    card_x = pdf.l_margin
    card_y = pdf.get_y() + 2
    image_x = card_x + (content_width - image_width) / 2
    image_y = card_y + 4
    pdf.set_draw_color(209, 213, 219)
    pdf.set_fill_color(248, 250, 252)
    pdf.rect(
        card_x,
        card_y,
        content_width,
        card_height,
        style="DF",
        round_corners=True,
        corner_radius=2,
    )
    pdf.image(
        BytesIO(asset.payload),
        x=image_x,
        y=image_y,
        w=image_width,
        h=image_height,
        alt_text=item["label"],
    )

    caption_y = image_y + image_height + 3
    pdf.set_xy(card_x + 5, caption_y)
    pdf.set_font("Inter", "B", 9.5)
    pdf.set_text_color(31, 41, 55)
    caption = _fit_pdf_text(pdf, item["label"], content_width - 10)
    pdf.cell(content_width - 10, 4.5, caption)
    pdf.set_xy(card_x + 5, caption_y + 5)
    pdf.set_font("Inter", "", 8.5)
    pdf.set_text_color(29, 78, 216)
    action = "Watch on YouTube" if item["kind"] == "youtube" else "Open original image"
    pdf.cell(content_width - 10, 4, action)
    pdf.link(
        card_x,
        card_y,
        content_width,
        card_height,
        item["url"],
        alt_text=action,
    )
    pdf.set_y(card_y + card_height + 4)
    pdf.set_x(pdf.l_margin)


def _render_media_fallback(pdf: FPDF, item: dict, tag_styles: dict) -> None:
    label = html.escape(item["label"])
    url = html.escape(item["url"], quote=True)
    if item["kind"] == "youtube":
        lead = "YouTube video"
        note = "Thumbnail unavailable; open the video link."
    else:
        lead = "Public image"
        note = "Image preview unavailable; open the original link."
    _write_pdf_html(
        pdf,
        (
            f"<p><b>{lead}:</b> <a href=\"{url}\">{label}</a><br>"
            f"<i>{note}</i></p>"
        ),
        tag_styles,
    )


def _write_html_with_public_media(
    pdf: FPDF,
    rendered_html: str,
    projection: dict,
    tag_styles: dict,
) -> None:
    media = projection.get("public_media") or []
    cursor = 0
    deadline = time.monotonic() + REMOTE_MEDIA_RENDER_BUDGET_SECONDS
    asset_cache: dict[str, _EmbeddedImage | None] = {}
    embedded_asset_urls: set[str] = set()
    embedded_asset_bytes = 0
    fetch_enabled = not any(
        finding.get("severity") == "block"
        for finding in projection.get("findings", [])
    )
    for match in _MEDIA_HTML_RE.finditer(rendered_html):
        _write_pdf_html(pdf, rendered_html[cursor : match.start()], tag_styles)
        cursor = match.end()
        index = int(match.group(1))
        if index >= len(media):
            continue
        item = media[index]
        asset_url = item.get("thumbnail_url") if item.get("kind") == "youtube" else item.get("url")
        asset = asset_cache.get(asset_url)
        fetch_failed = not fetch_enabled or (asset_url in asset_cache and asset is None)
        if not fetch_enabled:
            _append_once(
                projection["findings"],
                _finding(
                    "info",
                    "public_media_fetch_skipped",
                    "Public media previews were not fetched because the PDF safety scan is blocking publication.",
                ),
            )
        if not fetch_failed and asset is None:
            remaining = deadline - time.monotonic()
            try:
                if remaining <= 0:
                    raise TimeoutError("Remote media render budget exhausted")
                asset = _fetch_public_image_asset(
                    asset_url,
                    timeout=max(0.25, min(REMOTE_IMAGE_TIMEOUT_SECONDS, remaining)),
                )
                asset_cache[asset_url] = asset
            except (OSError, ValueError, ssl.SSLError, http.client.HTTPException):
                asset_cache[asset_url] = None
                fetch_failed = True

        if (
            asset is not None
            and asset_url not in embedded_asset_urls
            and embedded_asset_bytes + len(asset.payload) > MAX_EMBEDDED_MEDIA_TOTAL_BYTES
        ):
            asset = None
            _append_once(
                projection["findings"],
                _finding(
                    "warn",
                    "public_media_pdf_budget_reached",
                    "An embedded media preview was replaced by its link to keep the PDF within its size limit.",
                ),
            )

        if asset is not None:
            if asset_url not in embedded_asset_urls:
                embedded_asset_urls.add(asset_url)
                embedded_asset_bytes += len(asset.payload)
            _render_embedded_media_card(pdf, item, asset)
            code = "youtube_thumbnail_embedded" if item["kind"] == "youtube" else "public_image_embedded"
            message = (
                "YouTube thumbnail previews were embedded as clickable cards; video playback remains external."
                if item["kind"] == "youtube"
                else "Public image previews were downloaded and embedded as clickable PDF snapshots."
            )
            _append_once(projection["findings"], _finding("info", code, message))
        else:
            _render_media_fallback(pdf, item, tag_styles)
            code = (
                "youtube_thumbnail_unavailable"
                if item["kind"] == "youtube"
                else "public_image_preview_unavailable"
            )
            message = (
                "A YouTube thumbnail could not be retrieved; the clickable video link was preserved."
                if item["kind"] == "youtube"
                else "A public image could not be safely retrieved; its clickable link was preserved."
            )
            _append_once(projection["findings"], _finding("warn", code, message))
    _write_pdf_html(pdf, rendered_html[cursor:], tag_styles)


def render_canvas_pdf(projection: dict) -> bytes:
    """Render a normalized Canvas projection to validated PDF bytes."""
    pdf = CanvasPDF(projection["title"])
    _register_fonts(pdf)
    pdf.set_title(projection["title"])
    pdf.set_author("Jarvis Canvas")
    pdf.set_creator("Jarvis Canvas")
    pdf.set_subject("Portable Canvas PDF snapshot")
    source_timestamp = projection.get("updated") or projection.get("created")
    creation_date = (
        datetime.fromisoformat(source_timestamp.replace("Z", "+00:00"))
        if source_timestamp
        else datetime(2000, 1, 1, tzinfo=timezone.utc)
    )
    pdf.set_creation_date(creation_date)
    pdf.set_compression(True)
    pdf.add_page()
    pdf.set_font("Inter", "", 10.5)
    pdf.set_text_color(31, 41, 55)

    tags = projection.get("tags") or []
    metadata_bits = []
    if projection.get("updated"):
        metadata_bits.append(f"Updated {projection['updated']}")
    elif projection.get("created"):
        metadata_bits.append(f"Created {projection['created']}")
    if tags:
        metadata_bits.append("Tags: " + ", ".join(_escape_markdown_inline(tag) for tag in tags))

    document_markdown = f"# {_escape_markdown_inline(projection['title'])}\n\n"
    if metadata_bits:
        document_markdown += " | ".join(metadata_bits) + "\n\n---\n\n"
    document_markdown += projection.get("content_markdown") or "_This Canvas page is empty._"
    rendered_html = _markdown_to_html(document_markdown)
    rendered_html, table_links, table_cells_flattened = _flatten_pdf_table_cells(rendered_html)
    if table_links:
        rendered_html += '<h2 style="break-before: page">Table links</h2><ul>'
        for label, url in table_links:
            rendered_html += (
                f'<li>{html.escape(label)}: '
                f'<a href="{html.escape(url, quote=True)}">{html.escape(url)}</a></li>'
            )
        rendered_html += "</ul>"
    rendered_html = _apply_pdf_typography(rendered_html)
    if table_cells_flattened:
        _append_once(
            projection["findings"],
            _finding(
                "info",
                "table_cells_flattened",
                "Rich formatting in table cells was flattened for PDF compatibility; table links are listed after the document.",
            ),
        )
    tag_styles = {
        "a": FontFace(color="#1d4ed8", emphasis="UNDERLINE"),
        "code": TextStyle(font_family="JetBrainsMono", font_size_pt=8.5),
        "pre": TextStyle(
            font_family="JetBrainsMono",
            font_size_pt=8.5,
            t_margin=4,
            b_margin=4,
        ),
        "p": TextStyle(
            font_family="Inter",
            font_size_pt=10.5,
            color="#1f2937",
            t_margin=1.5,
            b_margin=2.8,
        ),
        "li": TextStyle(
            font_family="Inter",
            font_size_pt=10.5,
            color="#1f2937",
            l_margin=5.5,
            t_margin=1.8,
            b_margin=1.8,
        ),
        "ul": TextStyle(t_margin=2.5, b_margin=3),
        "ol": TextStyle(t_margin=2.5, b_margin=3),
        "h1": TextStyle(
            font_family="Inter",
            font_style="B",
            font_size_pt=22,
            color="#111827",
            t_margin=7,
            b_margin=0.7,
        ),
        "h2": TextStyle(
            font_family="Inter",
            font_style="B",
            font_size_pt=17.5,
            color="#1f2937",
            t_margin=6,
            b_margin=0.65,
        ),
        "h3": TextStyle(
            font_family="Inter",
            font_style="B",
            font_size_pt=14,
            color="#374151",
            t_margin=5,
            b_margin=0.55,
        ),
        "blockquote": TextStyle(
            font_family="Inter",
            font_style="I",
            color="#4b5563",
            t_margin=3,
            b_margin=3,
        ),
    }
    _write_html_with_public_media(pdf, rendered_html, projection, tag_styles)
    payload = bytes(pdf.output())
    validate_canvas_pdf(payload)
    return payload


def validate_canvas_pdf(payload: bytes, *, max_bytes: int = MAX_PDF_BYTES) -> dict:
    """Validate generated PDF structure and return safe inspection details."""
    if not payload.startswith(b"%PDF-"):
        raise ValueError("Generated output is not a PDF")
    if not payload or len(payload) > max_bytes:
        raise ValueError(f"Generated PDF exceeds the {max_bytes}-byte limit")

    with fitz.open(stream=payload, filetype="pdf") as document:
        if document.is_encrypted:
            raise ValueError("Generated PDF must not be encrypted")
        if document.page_count < 1:
            raise ValueError("Generated PDF has no pages")
        page_count = document.page_count
        text = "\n".join(page.get_text("text") for page in document)
        links = sum(len(page.get_links()) for page in document)
        metadata = {key: value for key, value in (document.metadata or {}).items() if value}

    return {
        "bytes": len(payload),
        "pages": page_count,
        "links": links,
        "text": text,
        "metadata": metadata,
    }


def prepare_canvas_pdf(page: dict) -> tuple[dict, bytes]:
    """Build a projection, render it, and apply a final extracted-text scan."""
    projection = build_canvas_pdf_projection(page)
    payload = render_canvas_pdf(projection)
    inspection = validate_canvas_pdf(payload)
    if redact_sensitive_text(inspection["text"]) != inspection["text"]:
        _append_once(
            projection["findings"],
            _finding(
                "block",
                "secret_like_pdf_text",
                "Secret-like material remained in the rendered PDF. Remove it before publishing.",
            ),
        )
    projection["pdf"] = {
        "bytes": inspection["bytes"],
        "pages": inspection["pages"],
        "links": inspection["links"],
    }
    severity_order = {"block": 0, "warn": 1, "info": 2}
    projection["findings"].sort(
        key=lambda item: (
            severity_order.get(item.get("severity"), 3),
            item.get("line", 0),
            item.get("code", ""),
        )
    )
    return projection, payload


def has_blocking_findings(projection: dict) -> bool:
    """Return whether the projection is unsafe to publish."""
    return any(item.get("severity") == "block" for item in projection.get("findings", []))
