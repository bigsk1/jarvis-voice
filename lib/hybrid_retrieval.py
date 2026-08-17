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
    """Split a sufficiently detailed request into structural retrieval clauses.

    This deliberately uses punctuation and conjunction boundaries rather than
    phrase-to-tool or intent rules. Short requests stay on the single-vector
    path; longer compound requests receive a small number of supplemental
    retrieval views so one dominant action cannot erase a secondary action.
    """
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(query_terms(normalized)) < max(1, int(minimum_query_terms)):
        return []

    raw_segments = re.split(
        r"(?:[.!?;]+|\s*,\s*(?:and|then|also)\s+|\s+(?:and then|and|then|also)\s+)",
        normalized,
        flags=re.IGNORECASE,
    )
    segments: list[str] = []
    seen: set[str] = set()
    for raw_segment in raw_segments:
        segment = raw_segment.strip(" \t\r\n,;:.!?")
        identity = segment.casefold()
        if not query_terms(segment) or identity in seen:
            continue
        seen.add(identity)
        segments.append(segment)
        if len(segments) >= max(2, int(max_segments)):
            break

    return segments if len(segments) >= 2 else []


def fts5_query(terms: Iterable[str], operator: str = "OR") -> str:
    """Build a safely quoted FTS5 query from already-tokenized terms."""
    joiner = " AND " if str(operator).upper() == "AND" else " OR "
    quoted = [f'"{str(term).replace(chr(34), chr(34) * 2)}"' for term in terms if term]
    return joiner.join(quoted)


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
