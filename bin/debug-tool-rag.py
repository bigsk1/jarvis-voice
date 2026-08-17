#!/usr/bin/env python3
"""
Tool RAG Debugger
Shows what tools are retrieved and their similarity scores for a given query string.

Runtime Tool RAG can use either a short "stripped" user line or a long full prompt
(see docs/personal/tool-rag-routing-notes.md). This script does not call the orchestrator;
it only runs MemoryDB.search_tools so you can tune thresholds offline.

Typo RAG: In production, expand_tool_rag_query_for_typo_hints gets hint_source=raw user
text (token scan is user-only). Regime 1 below now uses the same user query as the
hint source, so the plain-query debug view is much closer to live routing behavior.

Script-only options:
  --stripped-threshold / --full-threshold — two cutoffs for two embedding regimes
  --synthetic-full — also embed a built-in synthetic "full transcript" wrapping your query
  --full-transcript-file — embed file contents as the "full" regime (real captured prompt)

Activate the project venv first so the repository dependencies and verified
Jarvis Embedding client are available. Embedding failures are explicit; the
debugger does not generate synthetic fallback vectors:

  source .venv/bin/activate

Usage:
  ./bin/debug-tool-rag.py cloud "What is the price of Bitcoin?"
  ./bin/debug-tool-rag.py cloud "What is the price of Bitcoin?" --synthetic-full --stripped-threshold 0.24 --full-threshold 0.20
  ./bin/debug-tool-rag.py local "Remember my wifi" --full-transcript-file /tmp/captured.txt --stripped-threshold 0.24 --full-threshold 0.18
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))
from config_loader import get_config_value, get_float, load_config
from hybrid_retrieval import adaptive_rank_cutoff, query_segments
from memory_db import get_memory_db
from router_v2 import (
    _cap_tool_names_for_schema,
    _resolve_tool_rag_limit,
    _tool_rag_similarity_threshold,
    build_tool_retrieval_signals,
    merge_tool_signal_names,
)
from tool_rag_typo_hints import expand_tool_rag_query_for_typo_hints
from tool_schema import (
    _ADAPTIVE_DYNAMIC_TOOL_MAX,
    _MANDATORY_GHOST_TOOLS,
    ToolRegistry,
    _merge_compound_segment_rankings,
    _merged_ghost_tool_names,
)


def _build_live_registry() -> ToolRegistry:
    """Build the active registry so debug output matches profile/runtime visibility."""
    project_root = Path(__file__).resolve().parents[1]
    skills_dir = str(project_root / "skills")
    mcp_config_path = str(project_root / "config" / "mcp-servers.json")

    previous_json_mode = os.environ.get("JARVIS_JSON_MODE")
    os.environ["JARVIS_JSON_MODE"] = "1"
    try:
        return ToolRegistry(skills_dir=skills_dir, mcp_config_path=mcp_config_path)
    finally:
        if previous_json_mode is None:
            os.environ.pop("JARVIS_JSON_MODE", None)
        else:
            os.environ["JARVIS_JSON_MODE"] = previous_json_mode


def _enabled_tool_names_from_registry(registry: ToolRegistry) -> list[str]:
    return list(registry.tools.keys())


def _active_ghost_tools(enabled_tool_names: list[str]) -> list[str]:
    ghost_tools_str = get_config_value(
        "GHOST_TOOLS",
        "search_memory,semantic_recall,remember,check_tool_logs,get_recent_conversations,get_time",
    )
    return _merged_ghost_tool_names(ghost_tools_str, set(enabled_tool_names))


def build_synthetic_full_transcript(user_query: str) -> str:
    """
    Approximate a long prompt like web/CLI when strip does NOT run: insights block,
    auto-memory style block, conversation context tail, then current request.

    Scores will not match production exactly; use --full-transcript-file with a real
    capture when you need faithful numbers.
    """
    uq = (user_query or "").strip()
    lines = [
        "=== LEARNED STRATEGIES (WHAT TO DO) ===",
        "(Based on 1 successful patterns)",
        "",
        "✅ Prefer live tools for price and status checks when freshness matters.",
        "   → Applies to: market data and server health",
        "",
        "=== KNOWN FAILURES - AVOID THESE ===",
        "⚠️  These approaches have FAILED in the past:",
        "",
        "❌ Do not rely only on stale memory for live prices.",
        "   → DO NOT use: search_memory",
        "",
        "=== RELEVANT STORED KNOWLEDGE (use this without calling search_memory tools) ===",
        "Lines tagged pinned_pref are address/tone preferences—honor those over your defaults when they apply.",
        "Other lines are semantic matches; use when relevant and ignore if off-topic.",
        "Freshness note: For live market/weather questions, newer live tool calls outrank older stored memory.",
        "",
        "- example_pref: example value (category: general, relevance: 72%, saved_at: 2026-01-01 12:00:00, age: 60m)",
        "===",
        "",
        "=== RECENT CONVERSATION CONTEXT ===",
        "User: Earlier unrelated question about settings.",
        "Jarvis [tools: search_memory]: Here is what I found in memory.",
        "  └─ search_memory data: ok=true",
        "",
        "=== END CONTEXT ===",
        "",
        f"Current request: {uq}",
        "",
    ]
    return "\n".join(lines)


def _run_search(
    db,
    query: str,
    limit_top: int,
) -> list[dict]:
    return db.search_tools(query, limit=limit_top, threshold=0.0)


def _production_initial_names(
    retrieved_tools: list[dict],
    ghost_tools: list[str],
    enabled_tool_names: list[str],
) -> list[str]:
    enabled = set(enabled_tool_names)
    names: list[str] = []
    for ghost in ghost_tools:
        if ghost in enabled and ghost not in names:
            names.append(ghost)
    for tool in retrieved_tools:
        name = tool["name"]
        if name not in names:
            names.append(name)
    return names


def _adaptive_tools(
    ranked_tools: list[dict],
    retrieval_limit: int,
    ghost_tools: list[str],
) -> tuple[list[dict], dict]:
    mandatory_count = sum(name in ghost_tools for name in _MANDATORY_GHOST_TOOLS)
    dynamic_budget = max(
        1,
        min(_ADAPTIVE_DYNAMIC_TOOL_MAX, retrieval_limit - mandatory_count),
    )
    return adaptive_rank_cutoff(ranked_tools, budget=dynamic_budget)


def _print_production_block(
    title: str,
    transcript: str,
    hint_source: str,
    db,
    retrieval_limit: int,
    ghost_tools: list[str],
    enabled_tool_names: list[str],
    threshold_override: float | None = None,
) -> None:
    signals = build_tool_retrieval_signals(transcript, enabled_tool_names)
    threshold = (
        threshold_override
        if threshold_override is not None
        else _tool_rag_similarity_threshold(transcript, signals.query, signals.source)
    )
    rag_query, typo_hints = expand_tool_rag_query_for_typo_hints(
        signals.query,
        enabled_tool_names,
        hint_source=hint_source,
    )
    all_tools = _run_search(db, rag_query, 100)
    ranked_candidates = db.search_tools(
        rag_query,
        limit=max(retrieval_limit * 2, 16),
        threshold=threshold,
    )
    primary_meta = getattr(db, "last_tool_search_meta", {})
    compound_segments = query_segments(signals.query)
    segment_rankings: list[tuple[str, list[dict]]] = []
    if not (
        isinstance(primary_meta, dict)
        and primary_meta.get("semantic_disabled_reason")
    ):
        mandatory_count = sum(name in ghost_tools for name in _MANDATORY_GHOST_TOOLS)
        dynamic_budget = max(
            1,
            min(_ADAPTIVE_DYNAMIC_TOOL_MAX, retrieval_limit - mandatory_count),
        )
        for segment in compound_segments:
            rows = db.search_tools(
                segment,
                limit=max(dynamic_budget * 2, 8),
                threshold=threshold,
            )
            segment_meta = getattr(db, "last_tool_search_meta", {})
            if not (
                isinstance(segment_meta, dict)
                and segment_meta.get("semantic_disabled_reason")
            ):
                segment_rankings.append((segment, rows))
    ranked_candidates, compound_meta = _merge_compound_segment_rankings(
        ranked_candidates,
        segment_rankings,
    )
    retrieved_tools, adaptive_meta = _adaptive_tools(
        ranked_candidates,
        retrieval_limit,
        ghost_tools,
    )
    initial_names = _production_initial_names(retrieved_tools, ghost_tools, enabled_tool_names)
    final_names, signal_meta = merge_tool_signal_names(
        initial_names,
        signals,
        enabled_tool_names,
        ghost_tools=ghost_tools,
    )
    uncapped_final_names = list(final_names)
    final_names = _cap_tool_names_for_schema(
        final_names,
        retrieval_limit,
        positive_tools=signals.positive_tools,
        ghost_tools=ghost_tools,
    )
    score_by_name = {tool["name"]: tool.get("similarity", 0.0) for tool in all_tools}
    score_by_name.update(
        {tool["name"]: tool.get("similarity", 0.0) for tool in ranked_candidates}
    )

    print(title)
    print(f"   Signal source: {signals.source}")
    print(f"   Embedding input length: {len(rag_query)} chars")
    print(f"   Threshold: {threshold}")
    print(f"   Compact query: {signals.query[:500]}")
    if typo_hints:
        print(f"   Typo RAG hints: {typo_hints}")
    if signal_meta.get("positive") or signal_meta.get("negative") or signal_meta.get("conflicted"):
        print(f"   Signal meta: {signal_meta}")
    if signals.notes:
        print(f"   Signal notes: {signals.notes}")
    if compound_segments:
        print(f"   Compound segments: {compound_segments}")
        print(f"   Segment selections: {compound_meta}")
    print(f"   Adaptive selection: {adaptive_meta}")
    print()
    print(f"🔎 Hybrid Search Results (Top 20) — dense threshold ≥ {threshold}:")
    print(f"   {'Rank':<6} {'Hybrid':<8} {'Dense':<8} {'Tool Name':<40} {'Channels':<16}")
    print(f"   {'-'*6} {'-'*8} {'-'*8} {'-'*40} {'-'*16}")
    for i, tool in enumerate(all_tools[:20], 1):
        name = tool["name"]
        hybrid = float(tool.get("hybrid_score") or 0.0)
        dense = tool.get("similarity")
        dense_text = f"{float(dense):.4f}" if dense is not None else "-"
        channels = "+".join(tool.get("retrieval_channels", []))
        ghost_marker = "👻" if name in ghost_tools else "  "
        print(f"   {i:<6} {hybrid:<8.4f} {dense_text:<8} {ghost_marker} {name:<38} {channels:<16}")
    print()
    print("📚 Production-style tool list (merged, then final schema cap):")
    print(f"   Final schema limit: {retrieval_limit}")
    print(f"   Total tool list size: {len(final_names)}")
    print(f"   Uncapped merged size: {len(uncapped_final_names)}")
    print(f"   Retrieved before signal merge: {len(initial_names)}")
    dropped = [name for name in uncapped_final_names if name not in final_names]
    if dropped:
        print(f"   Dropped by final cap: {', '.join(dropped)}")
    for i, name in enumerate(final_names, 1):
        tags: list[str] = []
        if name in ghost_tools:
            tags.append("ghost")
        if name in signal_meta.get("appended", []):
            tags.append("appended")
        elif name in [tool["name"] for tool in retrieved_tools]:
            tags.append("retrieved")
        score = score_by_name.get(name)
        score_text = f"dense={score:.4f}" if score is not None else "dense=n/a"
        tag_text = f" ({', '.join(tags)})" if tags else ""
        print(f"   {i:>2}. {name}{tag_text} {score_text}")
    print()


def _print_block(
    title: str,
    query: str,
    threshold: float,
    retrieval_limit: int,
    ghost_tools: list[str],
    all_tools: list[dict],
    retrieved_tools: list[dict],
) -> None:
    print(title)
    print(f"   Embedding input length: {len(query)} chars")
    print(f"   Threshold (this regime): {threshold}")
    print()
    print(f"🔎 Hybrid Search Results (Top 20) — dense threshold ≥ {threshold}:")
    print(f"   {'Rank':<6} {'Hybrid':<8} {'Dense':<8} {'Tool Name':<40} {'Channels':<16}")
    print(f"   {'-'*6} {'-'*8} {'-'*8} {'-'*40} {'-'*16}")
    for i, tool in enumerate(all_tools[:20], 1):
        name = tool["name"]
        hybrid = float(tool.get("hybrid_score") or 0.0)
        dense = tool.get("similarity")
        dense_text = f"{float(dense):.4f}" if dense is not None else "-"
        channels = "+".join(tool.get("retrieval_channels", []))
        ghost_marker = "👻" if name in ghost_tools else "  "
        print(f"   {i:<6} {hybrid:<8.4f} {dense_text:<8} {ghost_marker} {name:<38} {channels:<16}")
    print()
    retrieved_names = [t["name"] for t in retrieved_tools]
    final_names: list[str] = []
    for ghost in ghost_tools:
        if ghost not in final_names:
            final_names.append(ghost)
    for name in retrieved_names:
        if name not in final_names:
            final_names.append(name)
    print("📚 Hybrid candidate list approximation (ghost first, then retrieved):")
    print(f"   Total tool list size: {len(final_names)}")
    print(f"   Retrieved (above threshold): {len(retrieved_names)}")
    print("   Retrieved Tools:")
    for name in retrieved_names:
        row = next((t for t in retrieved_tools if t["name"] == name), {})
        print(
            f"      • {name} (hybrid: {float(row.get('hybrid_score') or 0.0):.4f}, "
            f"dense: {float(row.get('similarity') or 0.0):.4f})"
        )
    print()


def debug_tool_rag(
    mode: str,
    query: str,
    stripped_threshold: float | None,
    full_threshold: float | None,
    synthetic_full: bool,
    full_transcript_file: str | None,
) -> None:
    print("🔍 Tool RAG Debugger")
    print("=" * 80)
    print(f"Mode: {mode}")
    print(f"Plain user query: {query}")
    print("=" * 80)
    print()

    load_config(mode)
    env_threshold = get_float("TOOL_SIMILARITY_THRESHOLD", 0.0)
    full_env_raw = get_config_value("TOOL_SIMILARITY_THRESHOLD_FULL", None)
    try:
        env_full_threshold = (
            env_threshold
            if full_env_raw is None or str(full_env_raw).strip() == ""
            else float(full_env_raw)
        )
    except (TypeError, ValueError):
        env_full_threshold = env_threshold

    st = stripped_threshold if stripped_threshold is not None else env_threshold
    ft = full_threshold if full_threshold is not None else env_full_threshold

    retrieval_limit = _resolve_tool_rag_limit(mode)
    # This standalone debugger has no request config_scope; select the data
    # mode explicitly instead of falling back to the process JARVIS_MODE.
    db = get_memory_db(mode=mode)

    try:
        registry = _build_live_registry()
        tool_names = _enabled_tool_names_from_registry(registry)
        ghost_tools = _active_ghost_tools(tool_names)

        # Regime 1: single-line `query` — use the same text as hint_source so typo matching
        # mirrors the live path where ToolRegistry.find_tools gets typo_hint_source=user text.
        plain_query_embed, typo_hints = expand_tool_rag_query_for_typo_hints(
            query,
            tool_names,
            hint_source=query,
        )
        if typo_hints:
            print(f"🔤 Typo RAG hints (embedding only): {typo_hints}")
            print()

        # --- Regime 1: plain query (similar to stripped / debug-style single line) ---
        plain_all = _run_search(db, plain_query_embed, 100)
        plain_retrieved = db.search_tools(plain_query_embed, limit=retrieval_limit, threshold=st)

        print("📋 Configuration:")
        print(f"   Ghost Tools: {', '.join(ghost_tools)}")
        print(f"   TOOL_SIMILARITY_THRESHOLD (env): {env_threshold}")
        print(f"   TOOL_SIMILARITY_THRESHOLD_FULL (env/effective): {env_full_threshold}")
        print(f"   --stripped-threshold (regime 1): {st}")
        if synthetic_full or full_transcript_file:
            print(f"   --full-threshold (regime 2): {ft}")
        print(f"   Retrieval limit: {retrieval_limit}")
        print()

        _print_block(
            "=== Regime 1: plain query (stripped-like / default debug) ===",
            plain_query_embed,
            st,
            retrieval_limit,
            ghost_tools,
            plain_all,
            plain_retrieved,
        )

        _print_production_block(
            "=== Production-style retrieval: plain query ===",
            query,
            query,
            db,
            retrieval_limit,
            ghost_tools,
            tool_names,
            threshold_override=st,
        )

        full_query: str | None = None
        if full_transcript_file:
            with open(full_transcript_file, encoding="utf-8", errors="replace") as f:
                full_query = f.read()
            full_query_embed, full_typo_hints = expand_tool_rag_query_for_typo_hints(
                full_query,
                tool_names,
                hint_source=query,
            )
            if full_typo_hints:
                print(f"🔤 Typo RAG hints for regime 2 (embedding only): {full_typo_hints}")
                print()
            _print_block(
                f"=== Regime 2: full transcript from file ({full_transcript_file}) ===",
                full_query_embed,
                ft,
                retrieval_limit,
                ghost_tools,
                _run_search(db, full_query_embed, 100),
                db.search_tools(full_query_embed, limit=retrieval_limit, threshold=ft),
            )
            _print_production_block(
                f"=== Production-style retrieval: full transcript from file ({full_transcript_file}) ===",
                full_query,
                query,
                db,
                retrieval_limit,
                ghost_tools,
                tool_names,
                threshold_override=None,
            )
        elif synthetic_full:
            full_query = build_synthetic_full_transcript(query)
            full_query_embed, full_typo_hints = expand_tool_rag_query_for_typo_hints(
                full_query,
                tool_names,
                hint_source=query,
            )
            if full_typo_hints:
                print(f"🔤 Typo RAG hints for regime 2 (embedding only): {full_typo_hints}")
                print()
            _print_block(
                "=== Regime 2: synthetic full transcript (dilution experiment) ===",
                full_query_embed,
                ft,
                retrieval_limit,
                ghost_tools,
                _run_search(db, full_query_embed, 100),
                db.search_tools(full_query_embed, limit=retrieval_limit, threshold=ft),
            )
            _print_production_block(
                "=== Production-style retrieval: synthetic full transcript ===",
                full_query,
                query,
                db,
                retrieval_limit,
                ghost_tools,
                tool_names,
                threshold_override=None,
            )

        if synthetic_full or full_transcript_file:
            print("💡 Notes:")
            print("   - Regime 1 scores match a plain user string (like default debug).")
            print("   - Regime 2 scores use a long string; distribution often differs — tune --full-threshold separately.")
            print("   - Production-style blocks use router_v2's compact query + structured signal merge.")
            if synthetic_full and not full_transcript_file:
                print("   - Synthetic template is approximate; paste a real prompt with --full-transcript-file for fidelity.")
            print()
            print("   Current behavior: compact/current-request retrieval uses TOOL_SIMILARITY_THRESHOLD;")
            print("   only true full-fallback retrieval uses TOOL_SIMILARITY_THRESHOLD_FULL.")
        else:
            print("💡 Tip: add --synthetic-full [--stripped-threshold A --full-threshold B] to compare two regimes,")
            print("   or --full-transcript-file PATH to embed a captured orchestrator prompt.")

    finally:
        db.close()


def main() -> None:
    p = argparse.ArgumentParser(
        description="Debug Tool RAG retrieval and tune thresholds (script-only dual regime).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s cloud "What is the price of Bitcoin?"
  %(prog)s cloud "What is the price of Bitcoin?" --synthetic-full --stripped-threshold 0.24 --full-threshold 0.20
  %(prog)s local "Hi" --full-transcript-file /tmp/prompt.txt --stripped-threshold 0.24 --full-threshold 0.18

If --stripped-threshold is omitted, regime 1 uses TOOL_SIMILARITY_THRESHOLD.
If --full-threshold is omitted, regime 2 uses TOOL_SIMILARITY_THRESHOLD_FULL when set,
otherwise TOOL_SIMILARITY_THRESHOLD.
""",
    )
    p.add_argument("mode", choices=["cloud", "local"], help="Config profile to load")
    p.add_argument("query", nargs="+", help="User query (quote if it contains spaces)")
    p.add_argument(
        "--stripped-threshold",
        "--st",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Min cosine similarity for regime 1 (plain query). Default: TOOL_SIMILARITY_THRESHOLD from env.",
    )
    p.add_argument(
        "--full-threshold",
        "--ft",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Min cosine similarity for regime 2. Default: TOOL_SIMILARITY_THRESHOLD_FULL if set, else base threshold.",
    )
    p.add_argument(
        "--synthetic-full",
        action="store_true",
        help="Also run retrieval on a built-in long prompt wrapping the query (dilution experiment).",
    )
    p.add_argument(
        "--full-transcript-file",
        type=str,
        default=None,
        metavar="PATH",
        help="Use file contents as regime 2 embedding input (real captured prompt). Implies a second run; "
        "use --full-threshold for its cutoff. If set, --synthetic-full is ignored.",
    )

    args = p.parse_args()
    q = " ".join(args.query)

    if args.full_transcript_file and not os.path.isfile(args.full_transcript_file):
        print(f"Error: --full-transcript-file not found: {args.full_transcript_file}", file=sys.stderr)
        sys.exit(1)

    if args.synthetic_full and args.full_transcript_file:
        print("Note: --full-transcript-file takes precedence; --synthetic-full ignored.", file=sys.stderr)

    use_full = bool(args.synthetic_full or args.full_transcript_file)
    if not use_full and args.full_threshold is not None:
        print(
            "Warning: --full-threshold ignored without --synthetic-full or --full-transcript-file.",
            file=sys.stderr,
        )

    debug_tool_rag(
        mode=args.mode,
        query=q,
        stripped_threshold=args.stripped_threshold,
        full_threshold=args.full_threshold,
        synthetic_full=args.synthetic_full and not args.full_transcript_file,
        full_transcript_file=args.full_transcript_file,
    )


if __name__ == "__main__":
    main()
