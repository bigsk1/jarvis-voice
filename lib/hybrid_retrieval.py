"""Small, deterministic helpers shared by hybrid memory and tool retrieval."""

from __future__ import annotations

import re
from typing import Any, Iterable

# These are grammatical filler words, not intent-to-tool rules. Keeping them out
# of FTS queries lets BM25 focus on the request's distinguishing terms.
_QUERY_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "for",
        "from",
        "get",
        "give",
        "going",
        "had",
        "has",
        "have",
        "hey",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "me",
        "my",
        "now",
        "of",
        "on",
        "or",
        "please",
        "right",
        "show",
        "tell",
        "than",
        "that",
        "the",
        "then",
        "this",
        "to",
        "up",
        "was",
        "were",
        "what",
        "whats",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)

_SEGMENT_URL_RE = re.compile(
    r"(?<![\w./@-])(?:[a-z][a-z0-9+.-]*://|www\.|"
    r"(?:[a-z0-9-]+\.)+[a-z]{2,}(?::\d+)?/)[^\s<>\"`]+",
    re.IGNORECASE,
)
_INITIALISM_RE = re.compile(r"\b(?:[A-Za-z]\.){2,}")
_ACKNOWLEDGEMENT_RE = re.compile(
    r"(?:(?:hi|hello|hey)(?: there| jarvis)?|(?:thanks|thank you)"
    r"(?: again| a lot| (?:very|so) much)?|ok(?:ay)?|sure|cool|wow|great|nice|awesome)",
    re.IGNORECASE,
)
# Recognize compact URL references: one leading word plus reference words.
# This shape check does not classify verbs, use FTS query terms, or enumerate
# tool/action names. Polite request wrappers do not change the form.
_URL_REFERENCE_CLAUSE_RE = re.compile(
    r"(?:(?:can|could|would|will) you\s+)?(?:please\s+)?"
    r"[\w'-]+(?:\s+(?:this|that|these|those|it|them|one|ones|the|following|for|me|us))*"
    r"(?:\s+please)?",
    re.IGNORECASE,
)


def _normalize_query_links(text: str) -> str:
    """Flatten Markdown links to their label and URL without losing either."""
    if "](" not in text and "<" not in text:
        return text

    from markdown_it import MarkdownIt

    parts: list[str] = []
    label: list[str] = []
    href: str | None = None
    for token in MarkdownIt("commonmark").parseInline(text)[0].children or []:
        if token.type == "link_open":
            href = token.attrGet("href")
            label = []
        elif token.type == "link_close":
            label_text = "".join(label)
            parts.append(label_text if label_text == href else f"{label_text} {href or ''}")
            href = None
        else:
            content = "\n" if token.type in {"softbreak", "hardbreak"} else token.content
            (label if href is not None else parts).append(content)
    return "".join(parts)


def _is_conversational_fragment(text: str) -> bool:
    """Exclude standalone courtesy phrases and short reaction questions."""
    words = re.findall(r"[A-Za-z]+", text.lower())
    if _ACKNOWLEDGEMENT_RE.fullmatch(" ".join(words)):
        return True
    return (
        1 <= len(words) <= 4
        and words[-1] in {"right", "huh", "eh"}
        and text.rstrip().endswith("?")
    )


def query_terms(text: str) -> list[str]:
    """Return stable, de-duplicated lexical terms for FTS and diagnostics."""
    terms: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[A-Za-z0-9]+", str(text or "").lower()):
        if token in _QUERY_STOP_WORDS or token in seen:
            continue
        terms.append(token)
        seen.add(token)
    return terms


def query_segments(
    text: str,
    *,
    minimum_query_terms: int = 5,
    max_segments: int = 3,
) -> list[str]:
    """Build bounded, distinct retrieval views of a compound request.

    This deliberately uses punctuation and conjunction boundaries rather than
    phrase-to-tool or intent rules. Longer compound requests receive a small
    number of supplemental retrieval views. Linked requests can also supplement
    a short action clause whose signal would otherwise compete with the URL.
    """
    normalized = re.sub(r"[^\S\n]+", " ", _normalize_query_links(str(text or ""))).strip()
    url_matches = list(_SEGMENT_URL_RE.finditer(normalized))
    if not url_matches and len(query_terms(normalized)) < max(1, int(minimum_query_terms)):
        return []

    # URL punctuation describes the artifact, not another requested action.
    # Keep the original URL in its clause, while still allowing a sentence
    # boundary immediately after it (including a Markdown link's closing ')').
    url_spans = [
        (match.start(), match.start() + len(match.group().rstrip(".,;:!?)]}")))
        for match in url_matches
    ]
    protected_spans = url_spans + [match.span() for match in _INITIALISM_RE.finditer(normalized)]
    url_ends = {right for left, right in url_spans}
    # Dots within filenames, versions, and hostnames are not sentence breaks.
    # Initialisms also protect their final dot before whitespace (e.g. U.S.).
    boundaries = re.finditer(
        r"(?:[.!?]+(?=\s|$)|;+|[,:]+(?=\s|$)|\n+|\s*,\s*(?:and|then|also)\s+|\s+(?:and then|and|then|also)\s+)",
        normalized,
        flags=re.IGNORECASE,
    )
    raw_segments: list[tuple[str, bool]] = []
    start = 0
    follows_sequence = False
    for boundary in boundaries:
        if any(left <= boundary.start() < right for left, right in protected_spans):
            continue
        # Add comma/colon boundaries only immediately after a link; ordinary
        # lists, times, and prose keep their existing grouping.
        if set(boundary.group()) <= {",", ":"} and boundary.start() not in url_ends:
            continue
        clause_end = boundary.end() if boundary.group().startswith((".", "!", "?")) else boundary.start()
        raw_segments.append((normalized[start:clause_end], follows_sequence))
        follows_sequence = bool(re.search(r"\b(?:and|then|also)\b|[,;:]", boundary.group(), re.IGNORECASE))
        start = boundary.end()
    raw_segments.append((normalized[start:], follows_sequence))
    clauses: list[str] = []
    for raw_segment, sequenced in raw_segments:
        if _is_conversational_fragment(raw_segment):
            continue
        segment = raw_segment.strip(" \t\r\n,;:.!?")
        if not _SEGMENT_URL_RE.search(segment):
            if not query_terms(segment):
                continue
            # Isolated one-word sentences are too ambiguous for an extra
            # retrieval view. Explicit chaining still permits "and summarize".
            if not sequenced and len(re.findall(r"[A-Za-z0-9]+", segment)) < 2:
                continue
        clauses.append(segment)

    # A URL alone cannot waive this check: require a second eligible clause.
    if len(clauses) < 2:
        return []
    queries: list[str] = []
    seen: set[str] = set()
    for index, clause in enumerate(clauses):
        query = segment_retrieval_query(clause, source_clause=index == 0)
        identity = query.casefold()
        if identity in seen:
            continue
        seen.add(identity)
        queries.append(query)
        if len(queries) >= max(2, int(max_segments)):
            break
    return queries


def fts5_query(terms: Iterable[str], operator: str = "OR") -> str:
    """Build a safely quoted FTS5 query from already-tokenized terms."""
    joiner = " AND " if str(operator).upper() == "AND" else " OR "
    quoted = [f'"{str(term).replace(chr(34), chr(34) * 2)}"' for term in terms if term]
    return joiner.join(quoted)


def segment_retrieval_query(segment: str, *, source_clause: bool = False) -> str:
    """Keep direct URL references; focus descriptive and follow-up action views."""
    segment = re.sub(r"\s+", " ", _normalize_query_links(segment)).strip()
    action_text = re.sub(r"\s+", " ", _SEGMENT_URL_RE.sub(" ", segment)).strip()
    # A bare link is itself a source view. First-clause references such as
    # "Open this <url>" retain their URL; "Read the annual report <url>" can
    # retrieve from its descriptive text. Follow-up views omit URL payloads.
    if not action_text or (source_clause and _URL_REFERENCE_CLAUSE_RE.fullmatch(action_text)):
        return segment
    return action_text


def lexical_coverage(terms: Iterable[str], *texts: str) -> float:
    """Fraction of query terms present in one or more candidate text fields."""
    wanted = set(terms)
    if not wanted:
        return 0.0
    candidate_terms: set[str] = set()
    for text in texts:
        candidate_terms.update(re.findall(r"[A-Za-z0-9]+", str(text or "").lower()))
    return len(wanted & candidate_terms) / len(wanted)


def reciprocal_rank_score(*ranks: int | None, rank_constant: int = 60) -> float:
    """Return an RRF score for the supplied one-based channel ranks."""
    score = 0.0
    for rank in ranks:
        if rank is not None and rank > 0:
            score += 1.0 / (rank_constant + rank)
    return score


def adaptive_rank_cutoff(
    ranked: list[dict[str, Any]],
    *,
    budget: int,
    score_key: str = "hybrid_score",
    minimum: int = 2,
    dominance_ratio: float = 0.42,
    gap_ratio: float = 0.22,
    dense_gap_ratio: float = 0.12,
    relative_floor: float = 0.25,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Trim a ranked list at a natural confidence boundary.

    The decision depends only on the per-query score distribution. It does not
    classify intents or map phrases to tools. ``budget`` remains a hard safety
    ceiling, while a dominant winner or a pronounced score gap can use less.
    """
    budget = max(0, int(budget))
    if budget == 0 or not ranked:
        return [], {
            "candidate_count": len(ranked),
            "budget": budget,
            "selected_count": 0,
            "reason": "empty_or_zero_budget",
        }

    candidates = list(ranked[:budget])
    if len(candidates) <= 1:
        return candidates, {
            "candidate_count": len(ranked),
            "budget": budget,
            "selected_count": len(candidates),
            "reason": "single_candidate",
        }

    scores = [max(0.0, float(item.get(score_key) or 0.0)) for item in candidates]
    top = scores[0]
    if top <= 0.0:
        return candidates, {
            "candidate_count": len(ranked),
            "budget": budget,
            "selected_count": len(candidates),
            "reason": "no_positive_scores",
        }

    second_ratio = scores[1] / top
    if second_ratio < dominance_ratio:
        selected = candidates[:1]
        reason = "dominant_top_result"
        boundary = {"after_rank": 1, "ratio": round(second_ratio, 6)}
    else:
        floor_count = min(max(1, int(minimum)), len(candidates))
        cutoff = len(candidates)
        reason = "budget"
        boundary: dict[str, Any] | None = None
        top_dense = next(
            (
                float(item["similarity"])
                for item in candidates
                if item.get("similarity") is not None
            ),
            0.0,
        )
        for index in range(floor_count, len(candidates)):
            previous = scores[index - 1]
            current = scores[index]
            absolute_gap_ratio = (previous - current) / top
            previous_dense = candidates[index - 1].get("similarity")
            current_dense = candidates[index].get("similarity")
            if (
                top_dense > 0.0
                and previous_dense is not None
                and current_dense is not None
                and float(previous_dense) >= float(current_dense)
                and (float(previous_dense) - float(current_dense)) / top_dense
                >= dense_gap_ratio
            ):
                cutoff = index
                reason = "dense_score_gap"
                boundary = {
                    "after_rank": index,
                    "ratio": round(
                        (float(previous_dense) - float(current_dense)) / top_dense,
                        6,
                    ),
                }
                break
            if current / top < relative_floor:
                cutoff = index
                reason = "relative_floor"
                boundary = {
                    "after_rank": index,
                    "ratio": round(current / top, 6),
                }
                break
            if absolute_gap_ratio >= gap_ratio:
                cutoff = index
                reason = "score_gap"
                boundary = {
                    "after_rank": index,
                    "ratio": round(absolute_gap_ratio, 6),
                }
                break
        selected = candidates[:cutoff]

    return selected, {
        "candidate_count": len(ranked),
        "budget": budget,
        "selected_count": len(selected),
        "reason": reason,
        "top_score": round(top, 6),
        "boundary": boundary,
    }
