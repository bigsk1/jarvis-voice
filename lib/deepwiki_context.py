"""Pure, bounded DeepWiki evidence for orchestration and saved Web follow-ups."""

from __future__ import annotations

import json
import re
from typing import Any

try:
    from deepwiki import (
        DEEPWIKI_ANSWER_CHARS,
        DEEPWIKI_CITATION_REVISION_NOTE,
        DEEPWIKI_TOOL_NAMES,
        normalize_deepwiki_markdown,
        normalize_repo_names,
        safe_source_url,
    )
except ModuleNotFoundError as exc:
    if exc.name != "deepwiki":
        raise
    from lib.deepwiki import (
        DEEPWIKI_ANSWER_CHARS,
        DEEPWIKI_CITATION_REVISION_NOTE,
        DEEPWIKI_TOOL_NAMES,
        normalize_deepwiki_markdown,
        normalize_repo_names,
        safe_source_url,
    )

__all__ = ["DEEPWIKI_TOOL_NAMES", "project_deepwiki_data"]

_EXCERPT_MARKER = "\n[Answer excerpt truncated for context.]"
_STASH_REF_RE = re.compile(r"stash://[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


def _json_size(value: Any) -> int:
    # Match provider-facing JSON escaping as well as the stored data structure.
    return len(json.dumps(value, separators=(",", ":")))


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return value if len(value) <= limit else value[: max(0, limit - 15)] + "... [truncated]"


def _answer_excerpt(answer: str, limit: int) -> str:
    if len(answer) <= limit:
        return answer
    head = answer[: max(0, limit - len(_EXCERPT_MARKER))]
    # Sources are retained separately. Do not manufacture a URL by cutting one
    # in the answer, where a later model might mistake its prefix for a link.
    head = re.sub(r"https?://\S*$", "", head)
    open_link = head.rfind("[")
    if open_link >= 0 and ")" not in head[open_link:]:
        head = head[:open_link]
    return head.rstrip() + _EXCERPT_MARKER


def _legacy_text(payload: dict) -> str:
    for field in ("full_text", "text"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value
    parts = payload.get("raw", payload.get("content"))
    if isinstance(parts, list):
        return "\n".join(
            part["text"] for part in parts
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def project_deepwiki_data(
    result: Any,
    *,
    arguments: dict[str, Any] | None = None,
    max_chars: int = 7500,
    answer_max_chars: int = DEEPWIKI_ANSWER_CHARS,
    max_sources: int = 12,
) -> dict[str, Any]:
    """Keep research identity and complete handles without I/O or raw copies.

    Accept both canonical Jarvis envelopes and legacy MCP data. Parsing old
    Markdown here is deliberately pure: replaying history must never create a
    new artifact or contact DeepWiki.
    """
    max_chars = max(256, int(max_chars))
    envelope = result if isinstance(result, dict) else {}
    payload = envelope.get("data")
    payload = payload if isinstance(payload, dict) else envelope
    arguments = arguments if isinstance(arguments, dict) else {}
    repos = normalize_repo_names({"repoName": payload.get("repo_names")})
    if not repos:
        repos = normalize_repo_names(arguments)
    valid_repos = [repo for repo in repos if len(repo) <= 180]
    projected: dict[str, Any] = {
        "source": "deepwiki",
        "repo_names": valid_repos,
        "external_content_trust": "untrusted",
    }
    if len(valid_repos) < len(repos):
        projected["repo_names_truncated"] = True
    question = payload.get("question", arguments.get("question"))
    if isinstance(question, str) and question:
        projected["question"] = _text(question, 800)
        if projected["question"] != question:
            projected["question_truncated"] = True

    failed = (envelope.get("ok") is False or envelope.get("isError") is True
              or payload.get("ok") is False or payload.get("isError") is True)
    if failed:
        projected["ok"] = False
        error = envelope.get("error") or payload.get("error") or _legacy_text(payload)
        projected["error"] = _text(error, 600) or "DeepWiki request failed."
        if isinstance(error, str) and projected["error"] != error:
            projected["error_truncated"] = True
    else:
        answer = payload.get("answer")
        sources = payload.get("sources")
        if not isinstance(answer, str):
            answer, sources = normalize_deepwiki_markdown(_legacy_text(payload), repos)
        revision_note = payload.get("citation_revision_note")
        if revision_note or answer.startswith(DEEPWIKI_CITATION_REVISION_NOTE):
            projected["citation_revision_note"] = DEEPWIKI_CITATION_REVISION_NOTE
        sources = sources if isinstance(sources, list) else []
        answer_chars = payload.get("answer_chars")
        projected["answer_chars"] = (
            max(len(answer), answer_chars)
            if type(answer_chars) is int and 0 <= answer_chars < 10**12 else len(answer)
        )
        projected["answer_truncated"] = (
            payload.get("answer_truncated") is True or projected["answer_chars"] > len(answer)
        )
        projected["answer"] = _answer_excerpt(answer, max(80, answer_max_chars))
        projected["answer_truncated"] |= projected["answer"] != answer

        kept_sources = []
        seen = set()
        source_budget = min(2400, max_chars // 3)
        for source in sources:
            if not isinstance(source, dict) or not isinstance(source.get("url"), str):
                continue
            url = safe_source_url(source["url"])
            if not url or url in seen or len(url) > 2048:
                continue
            seen.add(url)
            row = {"title": _text(source.get("title"), 160), "url": url}
            if len(kept_sources) < max(0, min(max_sources, 12)) and _json_size([*kept_sources, row]) <= source_budget:
                kept_sources.append(row)
        projected["sources"] = kept_sources
        sources_count = payload.get("sources_count")
        projected["sources_count"] = (
            max(len(sources), sources_count)
            if type(sources_count) is int and 0 <= sources_count < 10**12 else len(sources)
        )
        projected["sources_truncated"] = (
            payload.get("sources_truncated") is True
            or len(kept_sources) < projected["sources_count"]
        )

        stash_ref = payload.get("stash_ref")
        if isinstance(stash_ref, str) and len(stash_ref) <= 256 and _STASH_REF_RE.fullmatch(stash_ref):
            projected["stash_ref"] = stash_ref
            for field in ("space_id", "filename", "mime_type"):
                value = payload.get(field)
                if isinstance(value, str) and 0 < len(value) <= 160:
                    projected[field] = value
        warning = payload.get("artifact_warning")
        if isinstance(warning, str) and warning:
            projected["artifact_warning"] = _text(warning, 240)

    # Reserve identities and artifact handles before shortening prose. Even
    # escaped Unicode, long questions, or a small provider budget stay valid
    # structured JSON; source URLs are dropped whole, never cut into fake refs.
    if _json_size(projected) > max_chars:
        if "question" in projected:
            shortened = _text(projected["question"], 160)
            if shortened != projected["question"]:
                projected["question_truncated"] = True
            projected["question"] = shortened
    if _json_size(projected) > max_chars:
        field = "error" if failed else "answer"
        original = projected[field]
        low, high = 0, len(original)
        while low < high:
            middle = (low + high + 1) // 2
            projected[field] = _text(original, middle) if failed else _answer_excerpt(original, middle)
            if _json_size(projected) <= max_chars:
                low = middle
            else:
                high = middle - 1
        projected[field] = _text(original, low) if failed else _answer_excerpt(original, low)
        if not failed:
            projected["answer_truncated"] = True
        elif projected[field] != original:
            projected["error_truncated"] = True
    while _json_size(projected) > max_chars and projected.get("sources"):
        projected["sources"].pop()
        projected["sources_truncated"] = True
    if _json_size(projected) > max_chars:
        if projected.pop("question", None):
            projected["question_truncated"] = True
    while _json_size(projected) > max_chars and projected["repo_names"]:
        projected["repo_names"].pop()
        projected["repo_names_truncated"] = True
    for field in ("space_id", "filename", "mime_type", "artifact_warning"):
        if _json_size(projected) > max_chars:
            projected.pop(field, None)
    if _json_size(projected) > max_chars:
        # Tiny defensive budgets cannot always hold a long Stash ref and all
        # counters. Keep that usable handle ahead of optional display metadata.
        for field in ("answer", "sources", "sources_count", "repo_names", "repo_names_truncated"):
            projected.pop(field, None)
            if _json_size(projected) <= max_chars:
                break
    if _json_size(projected) > max_chars:
        projected.pop("stash_ref", None)
    if _json_size(projected) > max_chars and not projected.get("sources"):
        projected.pop("citation_revision_note", None)
    return projected
