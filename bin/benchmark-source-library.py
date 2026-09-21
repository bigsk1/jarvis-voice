#!/usr/bin/env python3
"""Measure isolated Source Library search; never touches configured personal data."""

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import source_library  # noqa: E402
from source_library import SourceLibrary  # noqa: E402


def _p95(values):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


def _measure(library, query, semantic, repetitions):
    times = []
    for _ in range(repetitions):
        start = time.perf_counter()
        result = library.search(query, semantic=semantic)
        times.append((time.perf_counter() - start) * 1000)
        assert result["passages"]
    return {"median_ms": round(statistics.median(times), 2), "p95_ms": round(_p95(times), 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=int, default=1000)
    parser.add_argument("--chars", type=int, default=4000)
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    if not (1 <= args.sources <= 10000 and 100 <= args.chars <= 1_000_000 and 1 <= args.repetitions <= 100):
        parser.error("Use 1-10000 sources, 100-1000000 chars, and 1-100 repetitions.")

    vector = [1.0] + [0.0] * 767
    source_library.get_embeddings_batch = lambda texts, **_kwargs: [vector] * len(texts)
    source_library.get_embedding = lambda *_args, **_kwargs: vector
    with tempfile.TemporaryDirectory(prefix="jarvis-library-benchmark-") as temporary:
        os.environ["JARVIS_OVERRIDE_SOURCE_LIBRARY_DIR"] = temporary
        library = SourceLibrary("local")
        started = time.perf_counter()
        base = "archive reference field guide observations and context. "
        for number in range(args.sources):
            suffix = " cedarxylo distinctive waypoint." if number % 20 == 0 else " routine appendix."
            text = (base * (args.chars // len(base) + 1))[:args.chars] + suffix + f" Volume {number}."
            saved = library.save(text.encode(), f"volume-{number:05d}.txt")
            while True:
                batch = library.index(saved["source_id"])
                if not batch["remaining"]:
                    break
        build_seconds = round(time.perf_counter() - started, 2)
        stats = library.list(limit=1)
        with library._connect() as conn:
            passages = conn.execute("SELECT count(*) FROM passages").fetchone()[0]
        results = {
            "sources": stats["total"], "passages": passages,
            "database_mb": round(library.path.stat().st_size / 1048576, 2),
            "build_seconds": build_seconds, "isolated_temp_data": True,
            "keyword_narrow": _measure(library, "cedarxylo", False, args.repetitions),
            "keyword_broad": _measure(library, "archive", False, args.repetitions),
            "hybrid_narrow": _measure(library, "cedarxylo", True, args.repetitions),
        }
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
