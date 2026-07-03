"""Helpers for normalizing intel file content before writing or ingesting."""

from __future__ import annotations

import json


def normalize_intel_content(content: str) -> tuple[str, bool]:
    """
    Normalize LLM-produced intel content.

    This primarily fixes single-line strings that contain literal ``\\n`` escape
    sequences instead of real newlines, which breaks intel fact extraction.
    """
    if not content:
        return content, False

    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    changed = normalized != content
    stripped = normalized.strip()

    if _looks_like_json_string_literal(stripped):
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            decoded = None

        if isinstance(decoded, str) and decoded != normalized:
            normalized = decoded.replace("\r\n", "\n").replace("\r", "\n")
            changed = True

    if _looks_like_escaped_multiline_text(normalized):
        escaped_fixed = (
            normalized
            .replace("\\r\\n", "\n")
            .replace("\\n", "\n")
            .replace("\\t", "\t")
        )
        if escaped_fixed != normalized:
            normalized = escaped_fixed
            changed = True

    return normalized, changed


def normalize_intel_document_eof(content: str) -> tuple[str, bool]:
    """Canonicalize an edited intel document to exactly one newline at EOF.

    Textareas make a trailing blank line difficult to distinguish or remove by
    sight. Preserve all internal spacing, but prevent UI saves from accumulating
    extra blank lines at the end of tracked intel files.
    """
    normalized, changed = normalize_intel_content(content)
    if not normalized:
        return normalized, changed

    canonical = normalized.rstrip(" \t\n") + "\n"
    return canonical, changed or canonical != content


def _looks_like_json_string_literal(content: str) -> bool:
    return len(content) >= 2 and content[0] == '"' and content[-1] == '"'


def _looks_like_escaped_multiline_text(content: str) -> bool:
    escaped_newlines = content.count("\\n") + content.count("\\r\\n")
    actual_newlines = content.count("\n")

    if escaped_newlines < 2 or actual_newlines > 1:
        return False

    markdown_markers = ("\\n#", "\\n- ", "\\n* ", "\\n##", "\\n###", "\\n1. ")
    return any(marker in content for marker in markdown_markers)
