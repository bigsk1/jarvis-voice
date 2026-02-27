#!/usr/bin/env python3
"""
Memory Deduper Tool

Detect duplicate/conflicting memories, score confidence, and propose merge actions.
Can optionally apply dedupe for selected groups.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from typing import Any

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config
from memory_db import get_memory_db
from stash_helper import open_space, StashFile


STOP_WORDS = {
    "a", "an", "the", "to", "of", "in", "on", "for", "and", "or", "is", "are",
    "was", "were", "be", "my", "your", "our", "their", "that", "this", "these",
    "those", "about", "with", "from", "by", "at", "as", "it", "its",
}

SOURCE_CONFIDENCE = {
    "user_conversation": 1.00,
    "manual": 0.95,
    "system": 0.90,
    "remember": 0.90,
    "update_memory": 0.90,
    "git_release_notes": 0.80,
    "youtube_video": 0.78,
    "youtube_transcript": 0.78,
    "generate_video": 0.75,
}


@dataclass
class MemoryRecord:
    id: int
    category: str
    key: str
    value: str
    importance: int
    source: str
    created_at: str
    updated_at: str
    metadata: dict[str, Any]
    key_norm: str
    value_norm: str
    confidence: float


class UnionFind:
    def __init__(self, ids: list[int]):
        self.parent = {i: i for i in ids}
        self.rank = {i: 0 for i in ids}

    def find(self, x: int) -> int:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: int, b: int):
        ra = self.find(a)
        rb = self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            self.parent[ra] = rb
        elif self.rank[ra] > self.rank[rb]:
            self.parent[rb] = ra
        else:
            self.parent[rb] = ra
            self.rank[ra] += 1

    def groups(self) -> list[list[int]]:
        buckets: dict[int, list[int]] = {}
        for x in self.parent:
            root = self.find(x)
            buckets.setdefault(root, []).append(x)
        return [sorted(v) for v in buckets.values() if len(v) > 1]


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for candidate in (
        text,
        text.replace("Z", "+00:00"),
    ):
        try:
            return datetime.fromisoformat(candidate)
        except Exception:
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def preview(text: str, limit: int = 140) -> str:
    if text is None:
        return ""
    clean = re.sub(r"\s+", " ", str(text)).strip()
    return clean if len(clean) <= limit else clean[: limit - 3] + "..."


def normalize_key(text: str) -> str:
    t = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
    parts = [p for p in t.split() if p and p not in STOP_WORDS]
    return " ".join(parts)[:160]


def normalize_value(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"\s+", " ", t).strip()
    return t[:500]


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    seq = SequenceMatcher(None, a, b).ratio()
    sa = set(a.split())
    sb = set(b.split())
    if sa or sb:
        jacc = len(sa & sb) / max(len(sa | sb), 1)
    else:
        jacc = 0.0
    return (seq * 0.65) + (jacc * 0.35)


def source_factor(source: str) -> float:
    if not source:
        return 0.60
    if source in SOURCE_CONFIDENCE:
        return SOURCE_CONFIDENCE[source]
    for k, v in SOURCE_CONFIDENCE.items():
        if source.startswith(k):
            return v
    return 0.68


def compute_confidence(raw: dict[str, Any], metadata: dict[str, Any]) -> float:
    importance = int(raw.get("importance") or 5)
    importance = max(1, min(10, importance))
    importance_score = (importance / 10.0) * 45.0

    ts = parse_ts(raw.get("updated_at")) or parse_ts(raw.get("created_at"))
    if ts is None:
        recency_factor = 0.55
    else:
        now = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_days = max((now - ts).total_seconds() / 86400.0, 0.0)
        recency_factor = max(0.0, 1.0 - min(age_days / 365.0, 1.0))
    recency_score = recency_factor * 25.0

    src_score = source_factor(str(raw.get("source") or "")) * 20.0

    value = str(raw.get("value") or "").strip()
    val_len = len(value)
    if val_len < 4:
        quality_factor = 0.2
    elif val_len < 16:
        quality_factor = 0.5
    elif val_len <= 400:
        quality_factor = 1.0
    else:
        quality_factor = 0.75
    quality_score = quality_factor * 10.0

    penalty = 0.0
    if metadata.get("security_flag"):
        penalty += 25.0
    if (raw.get("category") or "").lower() == "stash_artifact":
        penalty += 8.0

    total = importance_score + recency_score + src_score + quality_score - penalty
    return round(max(0.0, min(total, 100.0)), 1)


def parse_metadata(meta_raw: Any) -> dict[str, Any]:
    if isinstance(meta_raw, dict):
        return meta_raw
    if isinstance(meta_raw, str) and meta_raw.strip():
        try:
            value = json.loads(meta_raw)
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}
    return {}


def group_id(prefix: str, ids: list[int]) -> str:
    key = ",".join(str(i) for i in sorted(ids))
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def memory_view(m: MemoryRecord) -> dict[str, Any]:
    return {
        "id": m.id,
        "category": m.category,
        "key": m.key,
        "value_preview": preview(m.value, 180),
        "importance": m.importance,
        "source": m.source,
        "updated_at": m.updated_at,
        "confidence": m.confidence,
    }


def load_records(
    include_categories: list[str],
    exclude_categories: list[str],
    limit: int,
) -> list[MemoryRecord]:
    db = get_memory_db()
    try:
        cursor = db.conn.cursor()
        query = """
            SELECT id, category, key, value, importance, created_at, updated_at, source, metadata
            FROM knowledge_base
            ORDER BY id DESC
            LIMIT ?
        """
        all_memories = [dict(row) for row in cursor.execute(query, (limit,)).fetchall()]
    finally:
        db.close()

    records: list[MemoryRecord] = []
    include_set = {c.strip() for c in include_categories if c and c.strip()}
    exclude_set = {c.strip() for c in exclude_categories if c and c.strip()}

    for raw in all_memories:
        category = str(raw.get("category") or "")
        if include_set and category not in include_set:
            continue
        if category in exclude_set:
            continue

        metadata = parse_metadata(raw.get("metadata"))
        rec = MemoryRecord(
            id=int(raw.get("id")),
            category=category,
            key=str(raw.get("key") or ""),
            value=str(raw.get("value") or ""),
            importance=int(raw.get("importance") or 5),
            source=str(raw.get("source") or ""),
            created_at=str(raw.get("created_at") or ""),
            updated_at=str(raw.get("updated_at") or ""),
            metadata=metadata,
            key_norm=normalize_key(str(raw.get("key") or "")),
            value_norm=normalize_value(str(raw.get("value") or "")),
            confidence=0.0,
        )
        rec.confidence = compute_confidence(raw, metadata)
        records.append(rec)

    return records[:limit]


def analyze_records(
    records: list[MemoryRecord],
    key_similarity_threshold: float,
    value_duplicate_threshold: float,
    value_conflict_threshold: float,
    max_pair_checks: int,
) -> dict[str, Any]:
    by_id = {r.id: r for r in records}

    # 1) Exact duplicates (same category + normalized key + normalized value)
    exact_buckets: dict[tuple[str, str, str], list[MemoryRecord]] = {}
    for r in records:
        k = (r.category, r.key_norm, r.value_norm)
        exact_buckets.setdefault(k, []).append(r)

    exact_groups = []
    exact_id_sets: set[tuple[int, ...]] = set()
    for vals in exact_buckets.values():
        if len(vals) < 2:
            continue
        sorted_vals = sorted(vals, key=lambda x: (-x.confidence, -x.importance, x.id))
        ids = [v.id for v in sorted_vals]
        exact_id_sets.add(tuple(sorted(ids)))
        gid = group_id("exact", ids)
        exact_groups.append({
            "group_id": gid,
            "group_type": "exact_duplicate",
            "category": sorted_vals[0].category,
            "memory_ids": ids,
            "primary_memory": memory_view(sorted_vals[0]),
            "secondary_memories": [memory_view(v) for v in sorted_vals[1:]],
            "suggested_action": "keep_primary_delete_others",
            "reason": "Same normalized key and value",
        })

    # 2) Probable duplicates + conflicts by pairwise similarity in category
    by_cat: dict[str, list[MemoryRecord]] = {}
    for r in records:
        by_cat.setdefault(r.category, []).append(r)

    uf_by_cat: dict[str, UnionFind] = {}
    pair_checks = 0
    probable_pairs: dict[tuple[int, int], dict[str, float]] = {}
    conflict_pairs: list[dict[str, Any]] = []

    for category, mems in by_cat.items():
        if len(mems) < 2:
            continue

        uf = UnionFind([m.id for m in mems])
        uf_by_cat[category] = uf

        # Compare likely-near neighbors first (sorted by key length/name)
        sorted_mems = sorted(mems, key=lambda m: (m.key_norm, len(m.value_norm)))

        for a, b in combinations(sorted_mems, 2):
            if pair_checks >= max_pair_checks:
                break
            pair_checks += 1

            if not a.key_norm or not b.key_norm:
                continue
            if abs(len(a.key_norm) - len(b.key_norm)) > 50:
                continue

            ks = similarity(a.key_norm, b.key_norm)
            if ks < key_similarity_threshold:
                continue

            vs = similarity(a.value_norm, b.value_norm)
            pair_key = tuple(sorted((a.id, b.id)))

            # Skip exact duplicates here (already handled)
            if a.value_norm == b.value_norm and a.key_norm == b.key_norm:
                continue

            if vs >= value_duplicate_threshold:
                uf.union(a.id, b.id)
                probable_pairs[pair_key] = {"key_similarity": round(ks, 3), "value_similarity": round(vs, 3)}
            elif vs <= value_conflict_threshold:
                confidence_gap = round(abs(a.confidence - b.confidence), 1)
                conflict_pairs.append({
                    "category": category,
                    "memory_a": memory_view(a),
                    "memory_b": memory_view(b),
                    "key_similarity": round(ks, 3),
                    "value_similarity": round(vs, 3),
                    "confidence_gap": confidence_gap,
                    "suggested_action": "manual_review_prefer_higher_confidence",
                })

        if pair_checks >= max_pair_checks:
            break

    probable_groups = []
    for category, uf in uf_by_cat.items():
        components = uf.groups()
        for ids in components:
            if tuple(sorted(ids)) in exact_id_sets:
                continue
            vals = sorted((by_id[i] for i in ids), key=lambda x: (-x.confidence, -x.importance, x.id))
            gid = group_id("probable", ids)

            # Mean pair similarity within this component
            sims = []
            for i, j in combinations(sorted(ids), 2):
                k = tuple(sorted((i, j)))
                if k in probable_pairs:
                    sims.append(probable_pairs[k]["value_similarity"])
            avg_sim = round(sum(sims) / len(sims), 3) if sims else None

            probable_groups.append({
                "group_id": gid,
                "group_type": "probable_duplicate",
                "category": category,
                "memory_ids": ids,
                "primary_memory": memory_view(vals[0]),
                "secondary_memories": [memory_view(v) for v in vals[1:]],
                "avg_value_similarity": avg_sim,
                "suggested_action": "review_then_merge",
                "reason": "High key and value similarity",
            })

    # Rank conflicts by risk signal
    conflict_pairs.sort(
        key=lambda x: (x["key_similarity"] - x["value_similarity"], x["confidence_gap"]),
        reverse=True,
    )

    # Rank probable groups
    probable_groups.sort(
        key=lambda g: (g.get("avg_value_similarity") or 0.0, len(g["memory_ids"])),
        reverse=True,
    )

    # Rank exact groups by size, then confidence spread
    exact_groups.sort(key=lambda g: len(g["memory_ids"]), reverse=True)

    return {
        "exact_groups": exact_groups,
        "probable_groups": probable_groups,
        "conflicts": conflict_pairs,
        "pair_checks": pair_checks,
    }


def build_markdown_report(summary: dict[str, Any], analysis: dict[str, Any], max_output_groups: int) -> str:
    def _memory_line(m: dict[str, Any]) -> str:
        mem_id = m.get("id")
        confidence = m.get("confidence")
        importance = m.get("importance")
        source = m.get("source") or "unknown"
        updated = m.get("updated_at") or "unknown"
        key_text = preview(str(m.get("key") or ""), 90).replace("`", "'")
        value_text = preview(str(m.get("value_preview") or ""), 220).replace("`", "'")
        return (
            f"#{mem_id} conf={confidence} imp={importance} src={source} updated={updated} "
            f"key=`{key_text}` value=`{value_text}`"
        )

    lines: list[str] = []
    lines.append("# Memory Deduper Report")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Scanned memories: {summary['scanned_memories']}")
    lines.append(f"- Categories scanned: {summary['categories_scanned']}")
    lines.append(f"- Exact duplicate groups: {summary['exact_duplicate_groups']}")
    lines.append(f"- Probable duplicate groups: {summary['probable_duplicate_groups']}")
    lines.append(f"- Conflict pairs: {summary['conflict_pairs']}")
    lines.append(f"- Pair checks run: {summary['pair_checks']}")
    lines.append("- Confidence score combines recency, source quality, importance, and content quality.")
    lines.append("")

    exact = analysis["exact_groups"][:max_output_groups]
    if exact:
        lines.append("## Exact Duplicates")
        lines.append("These are usually safe cleanup candidates: same normalized key and value.")
        lines.append("")
        for g in exact:
            lines.append(
                f"### `{g['group_id']}` [{g['category']}] ids={g['memory_ids']} -> keep {g['primary_memory']['id']}"
            )
            lines.append("- Why flagged: normalized key and value are identical.")
            lines.append(f"- Keep candidate: {_memory_line(g['primary_memory'])}")
            for m in g["secondary_memories"]:
                lines.append(f"- Delete candidate: {_memory_line(m)}")
            lines.append("")
        lines.append("")

    probable = analysis["probable_groups"][:max_output_groups]
    if probable:
        lines.append("## Probable Duplicates")
        lines.append("These need manual review: highly similar key/value but not exact text matches.")
        lines.append("")
        for g in probable:
            lines.append(
                f"### `{g['group_id']}` [{g['category']}] ids={g['memory_ids']} "
                f"(avg value sim={g.get('avg_value_similarity')})"
            )
            lines.append("- Why flagged: key and value similarity crossed probable-duplicate thresholds.")
            lines.append(f"- Suggested primary: {_memory_line(g['primary_memory'])}")
            for m in g["secondary_memories"]:
                lines.append(f"- Possible duplicate: {_memory_line(m)}")
            lines.append("")
        lines.append("")

    conflicts = analysis["conflicts"][:max_output_groups]
    if conflicts:
        lines.append("## Potential Conflicts")
        lines.append("These appear to describe the same thing but with conflicting values.")
        lines.append("")
        for c in conflicts:
            a = c["memory_a"]
            b = c["memory_b"]
            lines.append(
                f"### [{c['category']}] #{a['id']} vs #{b['id']} "
                f"(key sim={c['key_similarity']}, value sim={c['value_similarity']}, gap={c['confidence_gap']})"
            )
            lines.append("- Why flagged: key similarity is high while value similarity is low.")
            lines.append(f"- Entry A: {_memory_line(a)}")
            lines.append(f"- Entry B: {_memory_line(b)}")
            lines.append("- Suggested action: manual review; prefer higher confidence only if context matches.")
            lines.append("")
        lines.append("")

    lines.append("## Next Actions")
    lines.append("- Run action=`apply` with selected exact `group_ids` after review.")
    lines.append("- Keep probable/conflict groups in analyze mode unless you are confident they are true duplicates.")
    lines.append("- Re-run with include/exclude categories to focus a specific memory domain.")
    lines.append("")
    return "\n".join(lines)


def save_report_to_stash(markdown: str) -> tuple[str | None, str | None, str | None]:
    try:
        space, _ = open_space(scope="session", labels=["memory_deduper"])
        stash_file = StashFile(space)
        filename = f"memory_deduper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        out = stash_file.save_text(
            content=markdown,
            name=filename,
            on_conflict="version",
            tags=["memory", "dedupe", "report"],
            tool_origin="memory_deduper",
        )
        return out.get("ref"), space.space_id, out.get("name")
    except Exception:
        return None, None, None


def save_report_to_canvas(markdown: str, title: str) -> tuple[str | None, str | None]:
    canvas_script = Path(__file__).parent / "canvas.py"
    if not canvas_script.exists():
        return None, "canvas.py not found"

    payload = {
        "action": "create",
        "title": title,
        "content": markdown,
        "tags": ["memory", "dedupe", "maintenance"],
        "source_query": "memory_deduper analysis",
    }
    try:
        result = subprocess.run(
            ["python3", str(canvas_script), json.dumps(payload)],
            capture_output=True,
            text=True,
            timeout=45,
            cwd=str(Path(__file__).parent.parent),
        )
        if result.returncode != 0:
            return None, (result.stderr or "canvas tool failed").strip()
        parsed = json.loads(result.stdout or "{}")
        if not parsed.get("ok"):
            return None, parsed.get("error") or "canvas create failed"
        return (parsed.get("data") or {}).get("page_id"), None
    except Exception as e:
        return None, str(e)


def apply_groups(
    exact_groups: list[dict[str, Any]],
    probable_groups: list[dict[str, Any]],
    group_ids: list[str],
    apply_mode: str,
    dry_run: bool,
) -> dict[str, Any]:
    if not group_ids:
        raise ValueError("group_ids is required for action=apply")

    chosen_groups: list[dict[str, Any]] = []
    exact_map = {g["group_id"]: g for g in exact_groups}
    probable_map = {g["group_id"]: g for g in probable_groups}

    for gid in group_ids:
        if gid in exact_map:
            chosen_groups.append(exact_map[gid])
        elif apply_mode == "exact_and_probable" and gid in probable_map:
            chosen_groups.append(probable_map[gid])

    if not chosen_groups:
        raise ValueError("No valid group_ids found for selected apply_mode")

    db = get_memory_db()
    try:
        actions = []
        deleted_total = 0
        for g in chosen_groups:
            keep_id = g["primary_memory"]["id"]
            ids = g["memory_ids"]
            delete_ids = [i for i in ids if i != keep_id]

            deleted = []
            if not dry_run:
                for did in delete_ids:
                    if db.forget(did):
                        deleted.append(did)
                deleted_total += len(deleted)
            else:
                deleted = delete_ids

            actions.append({
                "group_id": g["group_id"],
                "group_type": g["group_type"],
                "kept_id": keep_id,
                "deleted_ids": deleted,
                "dry_run": dry_run,
            })
    finally:
        db.close()

    return {
        "applied_groups": len(chosen_groups),
        "deleted_count": deleted_total if not dry_run else sum(len(a["deleted_ids"]) for a in actions),
        "actions": actions,
    }


def main():
    try:
        load_config()
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}

        action = str(args.get("action", "analyze")).strip().lower()
        if action not in {"analyze", "apply"}:
            raise ValueError("action must be 'analyze' or 'apply'")

        include_categories = args.get("include_categories") or []
        exclude_categories = args.get("exclude_categories")
        if exclude_categories is None:
            exclude_categories = ["stash_artifact"]

        scan_limit = max(1, min(int(args.get("scan_limit", 1200) or 1200), 5000))
        max_pair_checks = max(100, min(int(args.get("max_pair_checks", 60000) or 60000), 500000))
        max_output_groups = max(1, min(int(args.get("max_output_groups", 20) or 20), 100))

        key_similarity_threshold = float(args.get("key_similarity_threshold", 0.82))
        value_duplicate_threshold = float(args.get("value_duplicate_threshold", 0.90))
        value_conflict_threshold = float(args.get("value_conflict_threshold", 0.45))

        apply_mode = str(args.get("apply_mode", "exact_only")).strip().lower()
        if apply_mode not in {"exact_only", "exact_and_probable"}:
            raise ValueError("apply_mode must be 'exact_only' or 'exact_and_probable'")
        group_ids = args.get("group_ids") or []
        dry_run = bool(args.get("dry_run", True))

        save_to_stash = bool(args.get("save_to_stash", action == "analyze"))
        save_to_canvas = bool(args.get("save_to_canvas", False))

        records = load_records(
            include_categories=include_categories,
            exclude_categories=exclude_categories,
            limit=scan_limit,
        )

        analysis = analyze_records(
            records=records,
            key_similarity_threshold=key_similarity_threshold,
            value_duplicate_threshold=value_duplicate_threshold,
            value_conflict_threshold=value_conflict_threshold,
            max_pair_checks=max_pair_checks,
        )

        categories_scanned = len({r.category for r in records})
        summary = {
            "scanned_memories": len(records),
            "categories_scanned": categories_scanned,
            "exact_duplicate_groups": len(analysis["exact_groups"]),
            "probable_duplicate_groups": len(analysis["probable_groups"]),
            "conflict_pairs": len(analysis["conflicts"]),
            "pair_checks": analysis["pair_checks"],
        }

        apply_result = None
        if action == "apply":
            apply_result = apply_groups(
                exact_groups=analysis["exact_groups"],
                probable_groups=analysis["probable_groups"],
                group_ids=group_ids,
                apply_mode=apply_mode,
                dry_run=dry_run,
            )

        # Build trimmed data
        exact_trimmed = analysis["exact_groups"][:max_output_groups]
        probable_trimmed = analysis["probable_groups"][:max_output_groups]
        conflicts_trimmed = analysis["conflicts"][:max_output_groups]

        markdown = build_markdown_report(summary=summary, analysis=analysis, max_output_groups=max_output_groups)
        stash_ref = None
        stash_space_id = None
        stash_filename = None
        canvas_page_id = None
        canvas_error = None

        if save_to_stash:
            stash_ref, stash_space_id, stash_filename = save_report_to_stash(markdown)
        if save_to_canvas:
            canvas_page_id, canvas_error = save_report_to_canvas(
                markdown=markdown,
                title=f"Memory Deduper Report {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            )

        if action == "analyze":
            speech = (
                f"Scanned {summary['scanned_memories']} memories. "
                f"Found {summary['exact_duplicate_groups']} exact duplicate groups, "
                f"{summary['probable_duplicate_groups']} probable duplicate groups, "
                f"and {summary['conflict_pairs']} potential conflicts."
            )
        else:
            speech = (
                f"{'Dry run: ' if dry_run else ''}"
                f"Processed {apply_result['applied_groups']} groups; "
                f"{'would delete' if dry_run else 'deleted'} {apply_result['deleted_count']} memory entries."
            )

        result = {
            "ok": True,
            "speech": speech,
            "data": {
                "action": action,
                "summary": summary,
                "exact_duplicate_groups": exact_trimmed,
                "probable_duplicate_groups": probable_trimmed,
                "conflicts": conflicts_trimmed,
                "apply_result": apply_result,
                "stash_ref": stash_ref,
                "stash_space_id": stash_space_id,
                "stash_filename": stash_filename,
                "canvas_page_id": canvas_page_id,
                "canvas_error": canvas_error,
            },
        }
        print(json.dumps(result))

    except Exception as e:
        print(json.dumps({
            "ok": False,
            "speech": f"Memory dedupe failed: {e}",
            "error": str(e),
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
