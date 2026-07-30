"""Canonical filename helpers for Jarvis Intel documents."""

from __future__ import annotations

import re
import unicodedata


CANONICAL_INTEL_FILENAME_RE = re.compile(
    r"^[a-z0-9]+(?:-[a-z0-9]+)*(?:\.(?:md|txt))?$"
)


def validate_create_filename(path: str) -> None:
    """Require new Intel files to use the canonical lowercase kebab-case form."""
    if not CANONICAL_INTEL_FILENAME_RE.fullmatch(path):
        raise ValueError(
            "New Intel filenames must use lowercase kebab-case "
            "(for example, 'network-config.md')"
        )


def slugify_intel_title(title: str, max_length: int = 80) -> str:
    """Convert a human-readable title into a bounded ASCII filename slug."""
    normalized = unicodedata.normalize("NFKD", title or "")
    ascii_title = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    slug = slug[:max_length].rstrip("-")
    return slug or "document"


def filename_from_markdown_title(content: str, prefix: str = "intel") -> str:
    """Build a semantic filename from the first level-one Markdown heading."""
    heading = re.search(r"(?m)^\s*#\s+(.+?)\s*$", content or "")
    if not heading:
        raise ValueError(
            "Cannot derive an Intel filename because the content has no level-one heading"
        )
    prefix_slug = slugify_intel_title(prefix, max_length=40)
    title_slug = slugify_intel_title(heading.group(1))
    return f"{prefix_slug}-{title_slug}.md"
