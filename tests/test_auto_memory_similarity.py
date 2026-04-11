#!/usr/bin/env python3
"""
Auto-memory similarity threshold tuning helper.

Shows which memories would be injected for a query using logic that mirrors
the production auto-memory injection flow in orchestrator_v2.py.

Usage:
    python3 tests/test_auto_memory_similarity.py
    python3 tests/test_auto_memory_similarity.py "call me sir"
    python3 tests/test_auto_memory_similarity.py "how do I run the flask server?" --local
    python3 tests/test_auto_memory_similarity.py "call me sir" --threshold 0.45 --all
"""

import argparse
import os
import sys
from datetime import datetime


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from config_loader import get_bool, get_float, get_int, load_config
from memory_db import MemoryDB


DEFAULT_TEST_QUERIES = [
    "call me sir",
    "how should you address me?",
    "what do you know about my flask setup?",
    "what tool should I use for memory search?",
]

NO_PREFERENCE_VALUES = frozenset(
    [
        "no specific preference",
        "no preference",
        "none",
        "nothing",
        "n/a",
        "na",
        "forget",
        "remove",
        "delete",
    ]
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect auto-memory injection similarity thresholds"
    )
    parser.add_argument("query", nargs="?", help="Single query to inspect")
    parser.add_argument(
        "--mode",
        choices=["cloud", "local"],
        default="cloud",
        help="Mode to use (default: cloud)",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Convenience flag for --mode local",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        help="Override AUTO_MEMORY_SIMILARITY_THRESHOLD",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Override AUTO_MEMORY_LIMIT",
    )
    parser.add_argument(
        "--always-include-limit",
        type=int,
        help="Override AUTO_MEMORY_ALWAYS_INCLUDE_LIMIT",
    )
    parser.add_argument(
        "--no-recency",
        action="store_true",
        help="Disable recency weighting for this run",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Show all semantic candidates instead of truncating",
    )
    parser.add_argument(
        "--sweep",
        default="0.30,0.35,0.38,0.40,0.42,0.45,0.50",
        help="Comma-separated thresholds to compare (default: %(default)s)",
    )
    return parser.parse_args()


def resolve_mode(args: argparse.Namespace) -> str:
    return "local" if args.local else args.mode


def parse_sweep_values(raw: str) -> list[float]:
    values = []
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        values.append(float(piece))
    return sorted(set(values))


def is_intel_source(source: str) -> bool:
    return bool(source and str(source).startswith("intel/"))


def is_curated_intel(source: str) -> bool:
    return source in {
        "intel/jarvis-tool-knowledge.md",
        "intel/jarvis-learned-lessons.md",
    }


def is_tooling_query(text: str) -> bool:
    tooling_terms = [
        "tool",
        "tools",
        "provider",
        "model",
        "workflow",
        "scheduler",
        "memory",
        "intel",
        "prompt",
        "cache",
        "retry",
        "error",
        "errors",
        "failed",
        "failure",
        "bug",
        "issue",
        "issues",
        "quirk",
        "limitation",
        "limitations",
        "parameter",
        "params",
        "api",
        "orchestrator",
        "routing",
    ]
    return any(term in text for term in tooling_terms)


def is_no_preference(value: str) -> bool:
    normalized = (value or "").strip().lower()
    if not normalized:
        return True
    if normalized in NO_PREFERENCE_VALUES:
        return True
    return "no specific" in normalized or "no preference" in normalized


def parse_timestamp(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def recency_factor_for(memory: dict, now: datetime, enabled: bool) -> tuple[float, str]:
    if not enabled:
        return 1.0, "off"

    updated = parse_timestamp(memory.get("updated_at") or memory.get("created_at"))
    if not updated:
        return 1.0, "unknown"

    updated_naive = (
        updated.replace(tzinfo=None) if getattr(updated, "tzinfo", None) else updated
    )
    days_old = (now - updated_naive).days
    if days_old <= 7:
        return 1.0, "<=7d"
    if days_old <= 30:
        return 0.97, "8-30d"
    if days_old <= 60:
        return 0.94, "31-60d"
    if days_old <= 120:
        return 0.90, "61-120d"
    return 0.85, ">120d"


def age_text_for(memory: dict, now: datetime) -> str:
    updated = parse_timestamp(memory.get("updated_at") or memory.get("created_at"))
    if not updated:
        return "unknown"
    updated_naive = (
        updated.replace(tzinfo=None) if getattr(updated, "tzinfo", None) else updated
    )
    delta = now - updated_naive
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{max(minutes, 0)}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    days = hours // 24
    return f"{days}d"


def build_entry(
    memory: dict,
    *,
    bucket: str,
    base_similarity,
    adjusted_score: float,
    threshold: float,
    importance: int,
    recency_factor: float,
    recency_band: str,
    include: bool,
    reason: str,
    query_source: str,
    duplicate: bool = False,
) -> dict:
    return {
        "bucket": bucket,
        "key": memory.get("key", ""),
        "value": memory.get("value", ""),
        "category": memory.get("category", ""),
        "source_name": memory.get("source", ""),
        "importance": importance,
        "base_similarity": base_similarity,
        "adjusted_score": adjusted_score,
        "threshold": threshold,
        "recency_factor": recency_factor,
        "recency_band": recency_band,
        "include": include,
        "reason": reason,
        "query_source": query_source,
        "duplicate": duplicate,
        "memory": memory,
    }


def collect_auto_memory_diagnostics(
    db: MemoryDB,
    query: str,
    threshold: float,
    limit: int,
    recency_enabled: bool,
    addressing_limit: int,
) -> dict:
    now = datetime.now()
    transcript_lower = query.lower()
    seen_keys = set()
    merged = []
    semantic_candidates = []
    always_candidates = []
    intel_candidates = []

    if addressing_limit > 0:
        for memory in db.get_addressing_preferences(limit=addressing_limit):
            key = memory.get("key", "")
            value = memory.get("value", "")
            if not key or key in seen_keys or is_no_preference(value):
                continue
            seen_keys.add(key)
            entry = build_entry(
                memory,
                bucket="always",
                base_similarity=None,
                adjusted_score=1.10,
                threshold=threshold,
                importance=memory.get("importance", 5),
                recency_factor=1.0,
                recency_band="always",
                include=True,
                reason="always included addressing/style preference",
                query_source="always",
            )
            always_candidates.append(entry)
            merged.append(entry)

    if is_tooling_query(transcript_lower):
        intel_matches = [
            memory
            for memory in db.fts_search(query, limit=max(limit, 6))
            if is_intel_source(memory.get("source", ""))
        ]
        for memory in intel_matches:
            key = memory.get("key", "")
            duplicate = bool(key and key in seen_keys)
            if key and not duplicate:
                seen_keys.add(key)
            source_name = memory.get("source", "")
            adjusted_score = 1.08 if is_curated_intel(source_name) else 0.96
            entry = build_entry(
                memory,
                bucket="intel",
                base_similarity=memory.get("similarity"),
                adjusted_score=adjusted_score,
                threshold=threshold,
                importance=memory.get("importance", 5),
                recency_factor=1.0,
                recency_band="fts",
                include=not duplicate,
                reason="keyword intel boost" if not duplicate else "duplicate of prior key",
                query_source="fts_intel",
                duplicate=duplicate,
            )
            intel_candidates.append(entry)
            if not duplicate:
                merged.append(entry)

    candidate_limit = min(limit * 2, 20)
    candidate_threshold = min(threshold - 0.05, 0.30)
    semantic_results = db.semantic_search(
        query=query,
        limit=candidate_limit,
        similarity_threshold=candidate_threshold,
    )
    fallback_meta = getattr(db, "last_semantic_search_meta", {"fallback_embeddings": None})

    for memory in semantic_results:
        key = memory.get("key", "")
        base_similarity = memory.get("similarity")
        importance = memory.get("importance", 5)
        factor, band = recency_factor_for(memory, now, recency_enabled)
        adjusted = (base_similarity or 0.0) * factor
        source_name = memory.get("source", "")
        if is_intel_source(source_name):
            adjusted += 0.05
            if is_curated_intel(source_name):
                adjusted += 0.07

        duplicate = bool(key and key in seen_keys)
        if key and not duplicate:
            seen_keys.add(key)
        include = adjusted >= threshold and not duplicate

        if duplicate:
            reason = "duplicate of already-selected key"
        elif adjusted >= threshold:
            reason = "passes final threshold"
        else:
            reason = "below final threshold"

        entry = build_entry(
            memory,
            bucket="semantic",
            base_similarity=base_similarity,
            adjusted_score=adjusted,
            threshold=threshold,
            importance=importance,
            recency_factor=factor,
            recency_band=band,
            include=include,
            reason=reason,
            query_source="semantic",
            duplicate=duplicate,
        )
        semantic_candidates.append(entry)
        if include:
            merged.append(entry)

    merged.sort(
        key=lambda item: (item["adjusted_score"], item["importance"]),
        reverse=True,
    )
    semantic_candidates.sort(
        key=lambda item: (
            item["adjusted_score"],
            item["base_similarity"] if item["base_similarity"] is not None else -1,
            item["importance"],
        ),
        reverse=True,
    )
    injected = merged[:limit]

    return {
        "query": query,
        "threshold": threshold,
        "limit": limit,
        "candidate_threshold": candidate_threshold,
        "recency_enabled": recency_enabled,
        "addressing_limit": addressing_limit,
        "always_candidates": always_candidates,
        "intel_candidates": intel_candidates,
        "semantic_candidates": semantic_candidates,
        "injected": injected,
        "fallback_embeddings": fallback_meta.get("fallback_embeddings"),
        "db_path": db.db_path,
        "now": now,
    }


def format_similarity(value) -> str:
    if value is None:
        return "-"
    return f"{value:.3f}"


def format_entry_line(index: int, entry: dict, now: datetime) -> str:
    memory = entry["memory"]
    marker = "PASS" if entry["include"] else "SKIP"
    key = entry["key"] or "<no-key>"
    value = entry["value"] or ""
    category = entry["category"] or "-"
    source = entry["source_name"] or "-"
    age = age_text_for(memory, now)
    return (
        f"{index:2d}. {marker:4s} "
        f"adj={entry['adjusted_score']:.3f} "
        f"sim={format_similarity(entry['base_similarity']):>5s} "
        f"recency={entry['recency_factor']:.2f} "
        f"age={age:>7s} "
        f"bucket={entry['bucket']:8s} "
        f"cat={category:14.14s} "
        f"key={key[:32]:32s} "
        f"reason={entry['reason']} "
        f"source={source}"
        + (f"\n      value={value[:140]}" if value else "")
    )


def print_query_report(result: dict, show_all: bool, sweep_values: list[float], mode: str):
    query = result["query"]
    semantic_candidates = result["semantic_candidates"]
    injected = result["injected"]
    now = result["now"]

    print()
    print("=" * 100)
    print(f'Query: "{query}"')
    print("=" * 100)
    print(
        f"Mode={mode}  DB={result['db_path']}  threshold={result['threshold']:.2f}  "
        f"candidate_threshold={result['candidate_threshold']:.2f}  limit={result['limit']}  "
        f"recency={'on' if result['recency_enabled'] else 'off'}  "
        f"always_include_limit={result['addressing_limit']}"
    )
    if result["fallback_embeddings"]:
        print(f"Embedding fallback: {result['fallback_embeddings']}")

    print()
    print(f"Injected memories ({len(injected)}):")
    if not injected:
        print("  none")
    else:
        for i, entry in enumerate(injected, start=1):
            print(format_entry_line(i, entry, now))

    print()
    print(f"Semantic candidates ({len(semantic_candidates)}):")
    if not semantic_candidates:
        print("  none")
    else:
        display = semantic_candidates if show_all else semantic_candidates[: min(10, len(semantic_candidates))]
        for i, entry in enumerate(display, start=1):
            print(format_entry_line(i, entry, now))
        if not show_all and len(semantic_candidates) > len(display):
            print(f"  ... {len(semantic_candidates) - len(display)} more semantic candidates")

    print()
    print("Threshold sweep:")
    for sweep_threshold in sweep_values:
        sweep_result = collect_auto_memory_diagnostics(
            db=MemoryDB(result["db_path"]),
            query=query,
            threshold=sweep_threshold,
            limit=result["limit"],
            recency_enabled=result["recency_enabled"],
            addressing_limit=result["addressing_limit"],
        )
        top_keys = ", ".join(entry["key"] or "<no-key>" for entry in sweep_result["injected"][:4]) or "none"
        marker = " <==" if abs(sweep_threshold - result["threshold"]) < 0.0001 else ""
        print(
            f"  {sweep_threshold:0.2f}: injected={len(sweep_result['injected']):2d} "
            f"semantic_pass={sum(1 for item in sweep_result['semantic_candidates'] if item['include']):2d} "
            f"top={top_keys}{marker}"
        )


def main():
    args = parse_args()
    mode = resolve_mode(args)
    load_config(mode)

    threshold = (
        args.threshold
        if args.threshold is not None
        else get_float("AUTO_MEMORY_SIMILARITY_THRESHOLD", 0.42)
    )
    limit = args.limit if args.limit is not None else get_int("AUTO_MEMORY_LIMIT", 4)
    addressing_limit = (
        args.always_include_limit
        if args.always_include_limit is not None
        else get_int("AUTO_MEMORY_ALWAYS_INCLUDE_LIMIT", 2)
    )
    recency_enabled = (
        False
        if args.no_recency
        else get_bool("AUTO_MEMORY_RECENCY_ENABLED", True)
    )
    sweep_values = parse_sweep_values(args.sweep)

    queries = [args.query] if args.query else DEFAULT_TEST_QUERIES

    print("AUTO-MEMORY SIMILARITY TEST")
    print("-" * 100)
    print(
        f"mode={mode}  threshold={threshold:.2f}  limit={limit}  "
        f"always_include_limit={addressing_limit}  recency={'on' if recency_enabled else 'off'}"
    )

    db = MemoryDB()
    for query in queries:
        result = collect_auto_memory_diagnostics(
            db=db,
            query=query,
            threshold=threshold,
            limit=limit,
            recency_enabled=recency_enabled,
            addressing_limit=addressing_limit,
        )
        print_query_report(result, show_all=args.all, sweep_values=sweep_values, mode=mode)


if __name__ == "__main__":
    main()
