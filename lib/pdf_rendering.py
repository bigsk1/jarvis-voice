"""Private PDF rendering using the fonts shipped with Jarvis.

Raster images can come from Stash, public URLs, data URLs, or source-relative files.
Ordinary links and private text are preserved; public-sharing filters are separate.
"""

import base64
import binascii
import io
import re
import time
import warnings
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import unquote, unquote_to_bytes, urljoin, urlsplit

from fpdf import FPDF
from markdown_it import MarkdownIt
from markdown_it.token import Token

MAX_SOURCE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_STILL_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_TOTAL_IMAGE_BYTES = 60 * 1024 * 1024
MAX_TOTAL_IMAGE_PIXELS = 80_000_000
MAX_EMBEDDED_IMAGES = 32
MAX_IMAGE_DIMENSION = 2048
MAX_STASH_METADATA_BYTES = 8 * 1024 * 1024
IMAGE_DOWNLOAD_TIMEOUT = 8.0
TOTAL_IMAGE_DOWNLOAD_SECONDS = 20.0
RASTER_MIME_FORMATS = {
    "image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP", "image/gif": "GIF",
}
FONT_DIR = Path(__file__).resolve().parents[1] / "jarvis-web" / "client" / "fonts"


@dataclass(frozen=True)
class _MarkdownImage:
    data: bytes
    width: int
    height: int


class _ImageSourceError(ValueError):
    """An image rejected after reading bytes still consumes its document budget."""

    def __init__(self, reason: str, bytes_read: int):
        super().__init__(reason)
        self.bytes_read = bytes_read


def _stash_helpers():
    # Support both library imports and the bare module used by tool children.
    if __package__:
        from . import stash_helper
    else:
        import stash_helper
    return stash_helper


def _stash_image_path(target: str) -> Path:
    """Confine metadata lookup and the returned file to one existing Stash space."""
    stash = _stash_helpers()
    parsed = urlsplit(target)
    space_id = stash.normalize_space_id(parsed.netloc)
    file_id = unquote(parsed.path.removeprefix("/"))
    if (parsed.scheme != "stash" or parsed.query or parsed.fragment
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", space_id) or space_id in {".", ".."}
        or not file_id or file_id in {".", ".."} or len(target) > 2048
        or any(char in file_id for char in "/\\\x00")
        or any(ord(char) < 32 for char in file_id)):
        raise ValueError("invalid Stash image reference")
    root = stash.get_stash_dir().resolve()
    space = (root / space_id).resolve()
    if space.parent != root:
        raise ValueError("Stash image space is outside the storage root")
    metadata = (space / "meta.json").resolve()
    if not metadata.is_relative_to(space):
        raise ValueError("Stash image metadata is outside its space")
    try:
        stash.assert_not_restricted_read_path(metadata, label="PDF image metadata")
    except ValueError as exc:
        raise ValueError("restricted Stash image metadata") from exc
    if not metadata.is_file():
        raise ValueError("Stash image is missing or expired")
    if metadata.stat().st_size > MAX_STASH_METADATA_BYTES:
        raise ValueError("Stash image metadata exceeds its size limit")
    try:
        resolved = stash.safe_resolve_file(stash_ref=f"stash://{space_id}/{file_id}")
    except (AttributeError, TypeError) as exc:
        raise ValueError("invalid Stash image metadata") from exc
    if not resolved.get("found") or not resolved.get("path"):
        raise ValueError("Stash image is missing, expired, or restricted")
    path = Path(resolved["path"]).resolve()
    if not path.is_relative_to(space):
        raise ValueError("Stash image file is outside its space")
    try:
        stash.assert_not_restricted_read_path(path, label="PDF image")
    except ValueError as exc:
        raise ValueError("restricted Stash image file") from exc
    if not path.is_file():
        raise ValueError("Stash image is not a regular file")
    return path


def _read_image_file(path: Path, max_bytes: int) -> bytes:
    """Apply the shared file policy before reading a bounded regular file."""
    stash = _stash_helpers()
    try:
        stash.assert_not_restricted_read_path(path, label="PDF image")
    except ValueError as exc:
        raise ValueError("restricted image file") from exc
    if not path.is_file():
        raise ValueError("image file is missing or is not a regular file")
    if path.stat().st_size > max_bytes:
        raise ValueError("image exceeds the per-image or total byte limit")
    with path.open("rb") as source_file:
        data = source_file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("image exceeds the per-image or total byte limit")
    return data


def _relative_image_path(target: str, source_path: str | Path | None) -> Path:
    if source_path is None:
        raise ValueError("relative images need an original Markdown source file")
    parsed = urlsplit(target)
    name = unquote(parsed.path)
    if (parsed.scheme or parsed.netloc or not name or name.startswith(("/", "\\"))
        or "\\" in name or "\x00" in name or re.match(r"^[A-Za-z]:", name)):
        raise ValueError("use a relative image path inside the Markdown source directory")
    directory = Path(source_path).resolve().parent
    path = (directory / name).resolve()
    if not path.is_relative_to(directory):
        raise ValueError("relative image is outside the Markdown source directory")
    return path


def _check_image_mime(data: bytes, mime: str) -> None:
    from PIL import Image

    expected = RASTER_MIME_FORMATS.get(mime.lower())
    if expected is None:
        raise _ImageSourceError("unsupported image MIME type; use PNG, JPEG, WebP, or GIF", len(data))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != expected:
                    raise _ImageSourceError("image bytes do not match the declared MIME type", len(data))
    except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise _ImageSourceError("invalid or oversized raster image", len(data)) from exc


def _download_public_image(
    target: str, max_bytes: int, *, timeout: float = IMAGE_DOWNLOAD_TIMEOUT,
) -> bytes:
    """Use Stash URL checks and Jarvis HTTP/proxy handling with bounded streaming."""
    stash = _stash_helpers()
    deadline = time.monotonic() + timeout
    for _redirect in range(stash.MAX_REDIRECTS + 1):
        parsed = urlsplit(target)
        if (parsed.scheme not in {"https", "http"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or len(target) > 8192 or any(ord(char) < 32 for char in target)):
            raise ValueError("invalid public image URL")
        # This is the existing Stash DNS preflight, not connection pinning.
        stash.validate_url(target)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("public image download time limit reached")
        response = stash.http_request(
            "GET", target, stream=True, timeout=remaining, allow_redirects=False,
            deadline=deadline,
            use_proxy=True, fallback_on_proxy_fail=True,
            headers={"User-Agent": "Jarvis-PDF/1.0", "Accept-Encoding": "identity"},
        )
        data = bytearray()
        try:
            if response.is_redirect:
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("public image redirect has no destination")
                target = urljoin(target, location)
                continue
            response.raise_for_status()
            mime = response.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0].strip().lower()
            if mime not in RASTER_MIME_FORMATS and mime != "application/octet-stream":
                raise ValueError("public URL did not return a supported image MIME type")
            length = response.headers.get("Content-Length")
            if length and int(length) > max_bytes:
                raise ValueError("image exceeds the per-image or total byte limit")
            for chunk in response.iter_content(chunk_size=64 * 1024):
                data.extend(chunk)
                if time.monotonic() >= deadline:
                    raise ValueError("public image download time limit reached")
                if len(data) > max_bytes:
                    raise ValueError("image exceeds the per-image or total byte limit")
            payload = bytes(data)
            if mime != "application/octet-stream":
                _check_image_mime(payload, mime)
            return payload
        except (ValueError, OSError) as exc:
            if not data or isinstance(exc, _ImageSourceError):
                raise
            reason = str(exc) if isinstance(exc, ValueError) else "public image download failed"
            raise _ImageSourceError(reason, len(data)) from exc
        finally:
            response.close()
    raise ValueError("public image redirected too many times")


def _decode_data_image(target: str, max_bytes: int) -> bytes:
    header, separator, encoded = target.partition(",")
    if not separator:
        raise ValueError("invalid image data URL")
    fields = header[5:].split(";")
    mime = fields[0].lower()
    if mime not in RASTER_MIME_FORMATS:
        raise ValueError("unsupported image data MIME type")
    if any(field.lower() != "base64" and "=" not in field for field in fields[1:]):
        raise ValueError("invalid image data URL encoding")
    try:
        payload = unquote_to_bytes(encoded)
        if any(field.lower() == "base64" for field in fields[1:]):
            if len(payload) > ((max_bytes + 2) // 3) * 4:
                raise ValueError("image exceeds the per-image or total byte limit")
            data = base64.b64decode(payload, validate=True)
        else:
            data = payload
    except (binascii.Error, UnicodeError) as exc:
        raise ValueError("invalid image data URL encoding") from exc
    if len(data) > max_bytes:
        raise ValueError("image exceeds the per-image or total byte limit")
    _check_image_mime(data, mime)
    return data


def _prepare_image_data(pdf: "DocumentPDF", data: bytes) -> _MarkdownImage:
    """Decode bounded bytes and give fpdf a metadata-free raster, never a URI."""
    from PIL import Image, ImageOps
    stash = _stash_helpers()

    remaining = min(MAX_IMAGE_BYTES, MAX_TOTAL_IMAGE_BYTES - pdf._image_bytes)
    if len(data) > remaining:
        raise ValueError("image exceeds the per-image or total byte limit")
    # Charge work even if decoding later fails, so bad inputs cannot reset budgets.
    pdf._image_bytes += len(data)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP", "GIF"}:
                raise ValueError("unsupported raster format; use PNG, JPEG, WebP, or GIF")
            is_gif = source.format == "GIF"
            if not is_gif and len(data) > MAX_STILL_IMAGE_BYTES:
                raise ValueError("still image exceeds the 20 MiB byte limit")
            pixels = source.width * source.height
            if min(source.size) < 1 or pixels > MAX_IMAGE_PIXELS:
                raise ValueError("image exceeds the decoded pixel limit")
            remaining_pixels = MAX_TOTAL_IMAGE_PIXELS - pdf._image_pixels
            if is_gif:
                gif_pixels = min(MAX_IMAGE_PIXELS, remaining_pixels)
                # Failed late-frame decoding must still consume a work budget.
                pdf._image_pixels += gif_pixels
                info = stash.inspect_gif_image(
                    data, max_size=MAX_IMAGE_BYTES,
                    max_pixels=gif_pixels,
                    max_frames=stash.STRICT_GIF_MAX_FRAMES,
                )
                pixels = info["decoded_pixels"]
                pdf._image_pixels -= gif_pixels - pixels
                if info["animated"]:
                    pdf._warn("Animated GIFs use only the first frame in PDF; animation and timing are not included.")
            else:
                if getattr(source, "n_frames", 1) > 1:
                    raise ValueError("animated PNG/WebP is unsupported; use a still image or GIF")
                if pixels > remaining_pixels:
                    raise ValueError("images exceed the total decoded pixel limit")
                pdf._image_pixels += pixels
                source.verify()
        with Image.open(io.BytesIO(data)) as source:
            source.seek(0)
            source.load()
            image = ImageOps.exif_transpose(source)
            image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in source.info else "RGB")
            image.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)
            image.info.clear()
            output = io.BytesIO()
            image.save(output, format="PNG")
            result = _MarkdownImage(output.getvalue(), image.width, image.height)
            image.close()
            return result


def check_pdf_source(text: str) -> None:
    if not isinstance(text, str):
        raise ValueError("PDF source must be text")
    if len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("PDF text source exceeds the 5 MiB limit; no content was converted")


def read_pdf_text_source(path: str | Path) -> str:
    """Read the complete UTF-8 source or fail explicitly instead of truncating."""
    with open(path, "rb") as source:
        content = source.read(MAX_SOURCE_BYTES + 1)
    if len(content) > MAX_SOURCE_BYTES:
        raise ValueError("PDF text source exceeds the 5 MiB limit; no content was converted")
    return content.decode("utf-8-sig")


def register_pdf_fonts(pdf: FPDF) -> None:
    regular = FONT_DIR / "InterVariable.woff2"
    italic = FONT_DIR / "Inter-Italic.woff2"
    for style, path, variations in (
        ("", regular, {"wght": 400, "opsz": 14}),
        ("B", regular, {"wght": 680, "opsz": 22}),
        ("I", italic, None),
        ("BI", italic, None),
    ):
        # fpdf2 >=2.8.8 supports variable fonts; older bundled type stubs do not.
        pdf.add_font("Inter", style, str(path), variations=variations)  # pyrefly: ignore[unexpected-keyword]
    for style, suffix in (("", "Regular"), ("B", "Bold"), ("I", "Italic"), ("BI", "BoldItalic")):
        pdf.add_font("JetBrainsMono", style, str(FONT_DIR / f"JetBrainsMono-{suffix}.woff2"))


class DocumentPDF(FPDF):
    """Unicode document shell shared by plain, mixed, and Markdown creation."""

    def __init__(self, title: str = "Document"):
        super().__init__()
        self.render_warnings: list[str] = []
        self._image_cache: dict[tuple[str, str], _MarkdownImage | None] = {}
        self._image_count = 0
        self._image_bytes = 0
        self._image_pixels = 0
        self._image_download_seconds = 0.0
        self._image_source_path: str | Path | None = None
        self._missing_characters: set[int] = set()
        self.doc_title = title
        self.set_margins(16, 16, 16)
        self.set_auto_page_break(auto=True, margin=16)
        register_pdf_fonts(self)
        self.set_title(title)
        self.set_creator("Jarvis")

    def _warn(self, warning: str) -> None:
        if warning not in self.render_warnings:
            self.render_warnings.append(warning)

    def markdown_image(self, target: str) -> _MarkdownImage | None:
        if self._image_count >= MAX_EMBEDDED_IMAGES:
            self._warn("PDF image count limit reached; remaining images stay text references.")
            return None
        self._image_count += 1
        scheme = urlsplit(target).scheme
        key = (str(self._image_source_path) if not scheme else "", target)
        if key not in self._image_cache:
            from PIL import Image, UnidentifiedImageError
            stash = _stash_helpers()

            try:
                remaining = min(MAX_IMAGE_BYTES, MAX_TOTAL_IMAGE_BYTES - self._image_bytes)
                if remaining <= 0:
                    raise ValueError("images exceed the total byte limit")
                if scheme == "stash":
                    data = _read_image_file(_stash_image_path(target), remaining)
                elif scheme in {"https", "http"}:
                    remaining_time = TOTAL_IMAGE_DOWNLOAD_SECONDS - self._image_download_seconds
                    if remaining_time <= 0:
                        raise ValueError("public image download time limit reached")
                    started = time.monotonic()
                    try:
                        data = _download_public_image(
                            target, remaining, timeout=min(IMAGE_DOWNLOAD_TIMEOUT, remaining_time),
                        )
                    finally:
                        self._image_download_seconds += time.monotonic() - started
                elif scheme == "data":
                    data = _decode_data_image(target, remaining)
                else:
                    data = _read_image_file(_relative_image_path(target, self._image_source_path), remaining)
                self._image_cache[key] = _prepare_image_data(self, data)
            except (ValueError, OSError, RuntimeError, SyntaxError, EOFError, stash.SecurityError, UnidentifiedImageError,
                    Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
                if isinstance(exc, _ImageSourceError):
                    self._image_bytes += exc.bytes_read
                self._image_cache[key] = None
                # Do not expose resolved host paths in warnings.
                reason = str(exc) if isinstance(exc, (ValueError, stash.SecurityError)) else "invalid or unreadable raster image"
                label = "inline data image" if scheme == "data" else target[:200]
                self._warn(f"Image was not embedded ({label}): {reason[:200]}; kept a text reference.")
        return self._image_cache[key]

    def add_raster_image(self, path: str | Path, max_width: float = 180) -> None:
        """Embed an explicitly resolved local image through the same raster limits."""
        path = Path(path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"PDF image source not found: {path}")
        if self._image_count >= MAX_EMBEDDED_IMAGES:
            raise ValueError("PDF image count limit reached")
        self._image_count += 1
        key = ("file", str(path))
        if key not in self._image_cache:
            remaining = min(MAX_IMAGE_BYTES, MAX_TOTAL_IMAGE_BYTES - self._image_bytes)
            if remaining <= 0:
                raise ValueError("images exceed the total byte limit")
            self._image_cache[key] = _prepare_image_data(self, _read_image_file(path, remaining))
        image = self._image_cache[key]
        if image is None:
            raise ValueError("invalid PDF image source")
        width = min(max_width, self.epw, image.width * 25.4 / 96)
        height = width * image.height / image.width
        if height > min(200, self.eph - 12):
            width *= min(200, self.eph - 12) / height
            height = min(200, self.eph - 12)
        if self.will_page_break(height):
            self.add_page()
        self.image(image.data, x=(self.w - width) / 2, w=width, h=height)
        self.ln(5)

    def clean_text(self, text: str, family: str = "Inter", style: str = "") -> str:
        """Replace unsupported glyphs visibly and report them, without dropping text."""
        cmap = self.fonts[family.lower() + style].cmap
        result = []
        for character in text.replace("\r\n", "\n").replace("\r", "\n"):
            code = ord(character)
            if character in "\n\t" or code in cmap:
                result.append(character)
            else:
                self._missing_characters.add(code)
                result.append(f"[U+{code:04X}]")
        return "".join(result)

    def footer(self):
        self.set_y(-12)
        self.set_font("Inter", "", 8)
        self.set_text_color(110, 110, 110)
        self.cell(0, 6, f"Page {self.page_no()}", align="C")

    def add_title(self, title: str):
        self.set_font("Inter", "B", 23)
        self.set_text_color(25, 30, 40)
        self.set_x(self.l_margin)
        self.multi_cell(0, 11, self.clean_text(title, style="B"), new_x="LMARGIN", new_y="NEXT")
        self.ln(5)

    def add_heading(self, text: str, level: int = 1):
        size = {1: 19, 2: 16, 3: 13}.get(level, 11)
        self.set_font("Inter", "B", size)
        self.set_text_color(35, 40, 50)
        self.ln(3)
        self.set_x(self.l_margin)
        self.multi_cell(0, size * 0.48, self.clean_text(text, style="B"), new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def add_text(self, text: str):
        self.set_font("Inter", "", 10.5)
        self.set_text_color(20, 25, 30)
        self.set_x(self.l_margin)
        self.multi_cell(0, 5.4, self.clean_text(text).expandtabs(4), new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

    def add_code(self, text: str):
        self.set_font("JetBrainsMono", "", 8.5)
        self.set_text_color(30, 35, 45)
        self.set_fill_color(242, 244, 247)
        self.set_x(self.l_margin)
        self.multi_cell(
            0, 4.5, self.clean_text(text, "JetBrainsMono").expandtabs(4).rstrip("\n"),
            fill=True, wrapmode="CHAR", new_x="LMARGIN", new_y="NEXT", padding=2,
        )
        self.ln(3)

    def warnings(self) -> list[str]:
        result = list(self.render_warnings)
        if self._missing_characters:
            codes = sorted(self._missing_characters)
            listed = ", ".join(f"U+{code:04X}" for code in codes[:20])
            if len(codes) > 20:
                listed += f", and {len(codes) - 20} other code points"
            result.append(f"Bundled fonts lack {listed}; visible [U+XXXX] placeholders preserve their positions.")
        return result


def _image_reference(alt: str, target: str) -> str:
    label = "inline data image" if target.lower().startswith("data:") else target
    return f"[Image: {alt or 'image'}; {label}]"


def _visible_inline(tokens: list[Token]) -> str:
    """Flatten table inline formatting without losing its link destinations."""
    parts = []
    links = []
    for token in tokens:
        if token.type == "link_open":
            links.append(token.attrGet("href") or "")
        elif token.type == "link_close" and links:
            parts.append(f" ({links.pop()})")
        elif token.type == "image":
            parts.append(_image_reference(token.content, token.attrGet("src") or ""))
        elif token.type in {"softbreak", "hardbreak"}:
            parts.append("\n")
        elif token.type in {"text", "code_inline", "html_inline"}:
            parts.append(token.content)
    return "".join(parts)


def _clickable_link(target: str) -> bool:
    try:
        return urlsplit(target).scheme.lower() in {"http", "https", "mailto"}
    except ValueError:
        return False


def _write_inline(pdf: DocumentPDF, tokens: list[Token], *, level: int = 0, indent: float = 0, bullet: str = "", quote: bool = False):
    size = {1: 19, 2: 16, 3: 13}.get(level, 11 if level else 10.5)
    bold, italic, strike = bool(level), quote, False
    links: list[str] = []
    pdf.set_x(pdf.l_margin)
    pdf.set_text_color(20, 25, 30)
    # Paragraphs capture their marker font when opened, before inline runs.
    pdf.set_font("Inter", ("B" if bold else "") + ("I" if italic else ""), size)
    pdf.strikethrough = False
    with pdf.text_columns(line_height=1.35, wrapmode="WORD") as columns:
        with ExitStack() as paragraphs:
            paragraph = None
            bullet_used = False

            def open_paragraph():
                nonlocal bullet_used
                # A leading bold/code run must not change the list marker's font.
                saved_font = pdf.font_family, pdf.font_style, pdf.font_size_pt
                pdf.set_font("Inter", ("B" if level else "") + ("I" if quote else ""), size)
                try:
                    item = paragraphs.enter_context(columns.paragraph(
                        top_margin=3 if level else 0, bottom_margin=2.5, indent=indent,
                        bullet_string="" if bullet_used else bullet,
                    ))
                finally:
                    pdf.set_font(*saved_font)
                bullet_used = True
                return item

            for token in tokens:
                if token.type in {"strong_open", "strong_close"}:
                    bold = token.type == "strong_open" or bool(level)
                    continue
                if token.type in {"em_open", "em_close"}:
                    italic = token.type == "em_open" or quote
                    continue
                if token.type in {"s_open", "s_close"}:
                    strike = token.type == "s_open"
                    continue
                if token.type == "link_open":
                    links.append(token.attrGet("href") or "")
                    continue
                if token.type == "link_close":
                    if links:
                        target = links.pop()
                        if target and not _clickable_link(target):
                            pdf.set_font("Inter", "", size)
                            pdf.set_text_color(20, 25, 30)
                            if paragraph is None:
                                paragraph = open_paragraph()
                            paragraph.write(pdf.clean_text(f" ({target})"))
                    continue
                if token.type in {"softbreak", "hardbreak"}:
                    text = " " if token.type == "softbreak" else "\n"
                elif token.type == "image":
                    target = token.attrGet("src") or ""
                    image = pdf.markdown_image(target)
                    if image is not None:
                        if bullet and not bullet_used:
                            paragraph = open_paragraph()
                            paragraph.write(pdf.clean_text(token.content or "Image"))
                        paragraphs.close()
                        paragraph = None
                        width = min(pdf.epw - indent, image.width * 25.4 / 96)
                        height = width * image.height / image.width
                        if height > pdf.eph - 12:
                            width *= (pdf.eph - 12) / height
                            height = pdf.eph - 12
                        link_target = links[-1] if links else ""
                        columns.image(
                            cast(str, image.data), align="CENTER", width=width, height=height,
                            top_margin=2, bottom_margin=3, alt_text=token.content or "Image",
                            link=link_target if _clickable_link(link_target) else None,
                        )
                        continue
                    text = _image_reference(token.content, target)
                elif token.type in {"text", "code_inline", "html_inline"}:
                    text = token.content
                else:
                    continue
                family = "JetBrainsMono" if token.type == "code_inline" else "Inter"
                style = ("B" if bold else "") + ("I" if italic else "")
                target = links[-1] if links else ""
                link = target if _clickable_link(target) else None
                pdf.set_font(family, style + ("U" if link else ""), size - (1 if family == "JetBrainsMono" else 0))
                pdf.strikethrough = strike
                pdf.set_text_color(*(25, 85, 165) if link else (20, 25, 30))
                cleaned = pdf.clean_text(text, family, style)
                if paragraph is None:
                    paragraph = open_paragraph()
                if family == "Inter" and style == "BI":
                    # The bundled italic face is static weight 400. Paragraph
                    # fragments capture this local state; later text stays fill-only.
                    saved = pdf.text_mode, pdf.line_width, pdf.draw_color
                    try:
                        pdf.text_mode = "FILL_STROKE"
                        pdf.line_width = 0.07
                        pdf.draw_color = pdf.text_color
                        paragraph.write(cleaned, link=link)
                    finally:
                        pdf.text_mode, pdf.line_width, pdf.draw_color = saved
                else:
                    paragraph.write(cleaned, link=link)
    pdf.strikethrough = False


@dataclass(frozen=True)
class _TablePart:
    text: str = ""
    image: _MarkdownImage | None = None
    width: float = 0
    height: float = 0


def _table_parts(pdf: DocumentPDF, tokens: list[Token], width: float) -> list[_TablePart]:
    """Lay out one cell in source order, using already validated raster bytes."""
    parts: list[_TablePart] = []
    pending: list[str] = []
    links: list[str] = []

    def flush_text():
        text = pdf.clean_text("".join(pending))
        pending.clear()
        if text.strip():
            height = cast(float, pdf.multi_cell(
                width, 4.8, text, dry_run=True, output="HEIGHT", wrapmode="WORD",
            ))
            parts.append(_TablePart(text=text, height=height))

    for token in tokens:
        if token.type == "link_open":
            links.append(token.attrGet("href") or "")
        elif token.type == "link_close" and links:
            pending.append(f" ({links.pop()})")
        elif token.type == "image":
            target = token.attrGet("src") or ""
            image = pdf.markdown_image(target)
            if image is None:
                pending.append(_image_reference(token.content, target))
                continue
            flush_text()
            image_width = min(width, image.width * 25.4 / 96)
            image_height = image_width * image.height / image.width
            if image_height > 60:
                image_width *= 60 / image_height
                image_height = 60
            parts.append(_TablePart(
                text=token.content, image=image, width=image_width, height=image_height,
            ))
            # An image's alternative text also makes a useful visible cell caption.
            if token.content:
                pending.append(token.content)
                flush_text()
        elif token.type in {"softbreak", "hardbreak"}:
            pending.append("\n")
        elif token.type in {"text", "code_inline", "html_inline"}:
            pending.append(token.content)
    flush_text()
    return parts


def _table_cell_height(parts: list[_TablePart]) -> float:
    return 4 + sum(part.height for part in parts) + max(0, len(parts) - 1) * 1.5


def _draw_image_table_row(
    pdf: DocumentPDF, row: list[list[_TablePart]], width: float, height: float,
    *, heading: bool = False,
):
    top = pdf.get_y()
    pdf.set_font("Inter", "B" if heading else "", 9)
    pdf.set_text_color(20, 25, 30)
    pdf.set_draw_color(180, 185, 190)
    pdf.set_fill_color(242, 244, 247)
    for column, parts in enumerate(row):
        left = pdf.l_margin + column * width
        pdf.rect(left, top, width, height, style="DF" if heading else "D")
        y = top + 2
        for part in parts:
            if part.image is not None:
                pdf.image(
                    part.image.data, x=left + (width - part.width) / 2, y=y,
                    w=part.width, h=part.height, alt_text=part.text or "Image",
                )
            else:
                pdf.set_xy(left + 2, y)
                pdf.multi_cell(
                    width - 4, 4.8, part.text, wrapmode="WORD",
                    new_x="RIGHT", new_y="TOP",
                )
            y += part.height + 1.5
    pdf.set_xy(pdf.l_margin, top + height)


def _write_image_table_fallback(pdf: DocumentPDF, rows: list[list[list[_TablePart]]]):
    pdf._warn("A wide or tall Markdown table was rendered as labeled rows to preserve all cell content.")
    headers = [
        " ".join(part.text for part in cell if part.image is None and part.text).strip() or f"Column {index + 1}"
        for index, cell in enumerate(rows[0])
    ]
    for index, row in enumerate(rows):
        if index:
            pdf.add_heading(f"Table row {index}", 3)
        for column, parts in enumerate(row):
            if index:
                pdf.add_text(headers[column])
            for part in parts:
                if part.image is None:
                    pdf.add_text(part.text)
                    continue
                image = part.image
                width = min(pdf.epw, image.width * 25.4 / 96)
                height = width * image.height / image.width
                if height > pdf.eph - 12:
                    width *= (pdf.eph - 12) / height
                    height = pdf.eph - 12
                if pdf.will_page_break(height + 3):
                    pdf.add_page()
                pdf.image(
                    image.data, x=pdf.l_margin + (pdf.epw - width) / 2,
                    y=pdf.get_y(), w=width, h=height, alt_text=part.text or "Image",
                )
                pdf.ln(height + 3)


def _write_image_table(pdf: DocumentPDF, tokens: list[Token]):
    """Keep ordinary image tables as grids; split only rows too large for a page."""
    source_rows: list[list[list[Token]]] = []
    for token in tokens:
        if token.type == "tr_open":
            source_rows.append([])
        elif token.type == "inline" and source_rows:
            source_rows[-1].append(token.children or [])
    if not source_rows or not source_rows[0]:
        return
    columns = max(map(len, source_rows))
    width = pdf.epw / columns
    wide = columns > 6 or width < 22
    rows: list[list[list[_TablePart]]] = []
    heights: list[float] = []
    for index, row in enumerate(source_rows):
        pdf.set_font("Inter", "B" if index == 0 else "", 9)
        cells = [
            _table_parts(pdf, cell, pdf.epw if wide else width - 4)
            for cell in row + [[]] * (columns - len(row))
        ]
        rows.append(cells)
        heights.append(max(8.8, max(_table_cell_height(cell) for cell in cells)))
    if wide or max(heights) > 150 or heights[0] + max(heights[1:], default=0) > pdf.eph - 6:
        _write_image_table_fallback(pdf, rows)
        return
    # A logical row stays together; the header (including any images) repeats.
    first_body_height = heights[1] if len(heights) > 1 else 0
    if pdf.will_page_break(heights[0] + first_body_height):
        pdf.add_page()
    _draw_image_table_row(pdf, rows[0], width, heights[0], heading=True)
    for row, height in zip(rows[1:], heights[1:]):
        if pdf.will_page_break(height):
            pdf.add_page()
            _draw_image_table_row(pdf, rows[0], width, heights[0], heading=True)
        _draw_image_table_row(pdf, row, width, height)
    pdf.ln(3)


def _write_table(pdf: DocumentPDF, tokens: list[Token]):
    if any(child.type == "image" for item in tokens for child in (item.children or [])):
        _write_image_table(pdf, tokens)
        return
    rows: list[list[str]] = []
    for token in tokens:
        if token.type == "tr_open":
            rows.append([])
        elif token.type == "inline" and rows:
            rows[-1].append(_visible_inline(token.children or []))
    if not rows or not rows[0]:
        return
    columns = max(map(len, rows))
    pdf.set_font("Inter", "", 9)
    pdf.set_text_color(20, 25, 30)
    cleaned = [[pdf.clean_text(cell) for cell in row] for row in rows]
    width = pdf.epw / columns
    tall = columns > 6 or width < 22
    if not tall:
        for row in cleaned:
            for cell in row:
                height = cast(float, pdf.multi_cell(width - 4, 4.8, cell, dry_run=True, output="HEIGHT"))
                if height > 150:
                    tall = True
                    break
            if tall:
                break
    if tall:
        pdf.render_warnings.append("A wide or tall Markdown table was rendered as labeled rows to preserve all cell content.")
        for index, row in enumerate(cleaned[1:], 1):
            pdf.add_heading(f"Table row {index}", 3)
            for column, cell in enumerate(row):
                label = cleaned[0][column] if column < len(cleaned[0]) else f"Column {column + 1}"
                pdf.add_text(f"{label}: {cell}")
        if len(cleaned) == 1:
            for cell in cleaned[0]:
                pdf.add_text(cell)
        return
    pdf.set_x(pdf.l_margin)
    with pdf.table(text_align="LEFT", line_height=4.8, padding=2, width=pdf.epw, wrapmode="WORD") as table:
        for row in cleaned:
            cells = table.row()
            for cell in row + [""] * (columns - len(row)):
                cells.cell(cell)
    pdf.ln(3)


def write_markdown(
    pdf: DocumentPDF, markdown: str, *, source_path: str | Path | None = None,
) -> None:
    """Append Markdown with image paths relative to its original file, when supplied."""
    previous = pdf._image_source_path
    pdf._image_source_path = source_path
    try:
        _write_markdown(pdf, markdown)
    finally:
        pdf._image_source_path = previous


def _write_markdown(pdf: DocumentPDF, markdown: str) -> None:
    check_pdf_source(markdown)
    renderer = MarkdownIt("commonmark", {"html": False, "linkify": True})
    default_validate_link = renderer.validateLink

    def validate_image_link(target: str) -> bool:
        # CommonMark's default allows base64 data images only. Also allow standard
        # percent-encoded raster data; the bounded decoder still verifies bytes.
        if target.lower().startswith("data:"):
            mime = target[5:].partition(",")[0].split(";", 1)[0].lower()
            return mime in RASTER_MIME_FORMATS
        return default_validate_link(target)

    renderer.validateLink = validate_image_link
    renderer.enable(["linkify", "strikethrough", "table"])
    tokens = renderer.parse(markdown)
    lists: list[dict] = []
    pending_bullet = ""
    quote_depth = 0
    level = 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == "heading_open":
            level = int(token.tag[1:])
        elif token.type == "heading_close":
            level = 0
        elif token.type in {"bullet_list_open", "ordered_list_open"}:
            lists.append({"ordered": token.type == "ordered_list_open", "next": int(token.attrGet("start") or 1)})
        elif token.type in {"bullet_list_close", "ordered_list_close"}:
            lists.pop()
        elif token.type == "list_item_open" and lists:
            current = lists[-1]
            pending_bullet = f"{current['next']}." if current["ordered"] else "•"
            current["next"] += 1
        elif token.type == "list_item_close":
            pending_bullet = ""
        elif token.type == "blockquote_open":
            quote_depth += 1
        elif token.type == "blockquote_close":
            quote_depth -= 1
        elif token.type == "inline":
            indent = min(45, len(lists) * 6 + quote_depth * 5)
            _write_inline(pdf, token.children or [], level=level, indent=indent, bullet=pending_bullet, quote=bool(quote_depth))
            pending_bullet = ""
        elif token.type in {"fence", "code_block"}:
            pdf.add_code(token.content)
        elif token.type == "table_open":
            end = index + 1
            while end < len(tokens) and tokens[end].type != "table_close":
                end += 1
            table_tokens = tokens[index:end]
            _write_table(pdf, table_tokens)
            index = end
        elif token.type == "hr":
            pdf.set_draw_color(180, 185, 190)
            pdf.line(pdf.l_margin, pdf.get_y() + 2, pdf.w - pdf.r_margin, pdf.get_y() + 2)
            pdf.ln(5)
        index += 1


def _render_pdf(
    text: str, output_path: str, title: str, *, markdown: bool,
    source_path: str | Path | None = None,
) -> dict:
    check_pdf_source(text)
    check_pdf_source(title)
    pdf = DocumentPDF(title)
    pdf.add_page()
    pdf.add_title(title)
    if markdown:
        write_markdown(pdf, text, source_path=source_path)
    else:
        pdf.add_text(text)
    pdf.output(output_path)
    return {"page_count": pdf.page_no(), "warnings": pdf.warnings()}


def render_markdown_pdf(
    markdown: str, output_path: str, title: str = "Document", *,
    source_path: str | Path | None = None,
) -> dict:
    return _render_pdf(markdown, output_path, title, markdown=True, source_path=source_path)


def render_text_pdf(text: str, output_path: str, title: str = "Document") -> dict:
    return _render_pdf(text, output_path, title, markdown=False)
