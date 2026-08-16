#!/usr/bin/env python3
"""Validate Memory and Tool RAG embedding fingerprints and vector integrity."""

from __future__ import annotations

import argparse
import json
import pickle
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from config_loader import config_scope, get_config_value
from embedding_metadata import (
    MEMORY_KNOWLEDGE_NAMESPACE,
    MEMORY_TOOLS_NAMESPACE,
    embedding_namespace_status,
)
from embeddings import (
    EMBEDDING_DIMENSIONS,
    get_embedding_runtime_status,
    get_persistable_embedding,
)

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
BOLD = "\033[1m"
NC = "\033[0m"


def _deserialize(blob):
    try:
        return json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return pickle.loads(blob)


def _scan_vectors(
    cursor,
    table: str,
    id_column: str,
) -> tuple[int, int, int, list[dict]]:
    total = cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    rows = cursor.execute(
        f"SELECT {id_column}, embedding FROM {table} WHERE embedding IS NOT NULL"
    ).fetchall()
    issues = []
    issue_count = 0
    for identifier, blob in rows:
        try:
            dimensions = len(_deserialize(blob))
            if dimensions != EMBEDDING_DIMENSIONS:
                issue_count += 1
                if len(issues) < 100:
                    issues.append({
                        "id": identifier,
                        "expected": EMBEDDING_DIMENSIONS,
                        "actual": dimensions,
                    })
        except Exception as exc:
            issue_count += 1
            if len(issues) < 100:
                issues.append({"id": identifier, "error": str(exc)})
    return total, len(rows), issue_count, issues


def check_embedding_runtime(mode: str = "cloud", _scoped: bool = False) -> dict:
    """Verify configured Ollama hosts/model without opening or creating a DB."""
    if not _scoped:
        with config_scope(mode):
            return check_embedding_runtime(mode, _scoped=True)

    runtime = get_embedding_runtime_status(force_refresh=True)
    return {
        "ok": runtime["ok"],
        "runtime_only": True,
        "mode": mode,
        "expected_dimensions": EMBEDDING_DIMENSIONS,
        "embedding_provider": "ollama",
        "embedding_model": runtime["model"],
        "model_digest": runtime["model_digest"],
        "runtime": runtime,
        "provider_error": runtime["error"],
        "namespaces": [],
    }


def check_embedding_dimensions(mode: str = "cloud", _scoped: bool = False) -> dict:
    """Check the selected Memory database without changing its vector state."""
    if not _scoped:
        with config_scope(mode):
            return check_embedding_dimensions(mode, _scoped=True)

    relative_path = (
        "data/jarvis_memory_local.db" if mode == "local" else "data/jarvis_memory.db"
    )
    db_file = Path(__file__).parent.parent / relative_path
    runtime = get_embedding_runtime_status(force_refresh=True)

    if not db_file.exists():
        return {
            "ok": runtime["ok"],
            "warning": f"Database not found: {relative_path} (will be created on first use)",
            "mode": mode,
            "db_path": relative_path,
            "expected_dimensions": EMBEDDING_DIMENSIONS,
            "embedding_provider": "ollama",
            "embedding_model": runtime["model"],
            "model_digest": runtime["model_digest"],
            "runtime": runtime,
            "namespaces": [],
            "provider_error": runtime["error"],
        }

    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.cursor()
        memory_total, memory_vectors, memory_issue_count, memory_issues = _scan_vectors(
            cursor, "knowledge_base", "id"
        )
        tool_total, tool_vectors, tool_issue_count, tool_issues = _scan_vectors(
            cursor, "tool_definitions", "name"
        )
        namespaces = [
            embedding_namespace_status(
                conn,
                MEMORY_KNOWLEDGE_NAMESPACE,
                vector_count=memory_vectors,
            ),
            embedding_namespace_status(
                conn,
                MEMORY_TOOLS_NAMESPACE,
                vector_count=tool_vectors,
            ),
        ]
    finally:
        conn.close()

    provider_error = runtime["error"]
    current_dimensions = None
    if runtime["ok"]:
        try:
            current_dimensions = len(
                get_persistable_embedding(
                    "Jarvis embedding health probe",
                    role="query",
                )
            )
        except Exception as exc:
            provider_error = str(exc)

    missing_memory_vectors = memory_total - memory_vectors
    missing_tool_vectors = tool_total - tool_vectors
    namespace_issues = [item for item in namespaces if not item["ok"]]
    ok = (
        provider_error is None
        and current_dimensions == EMBEDDING_DIMENSIONS
        and not namespace_issues
        and memory_issue_count == 0
        and tool_issue_count == 0
        and missing_memory_vectors == 0
        and missing_tool_vectors == 0
    )
    return {
        "ok": ok,
        "mode": mode,
        "db_path": relative_path,
        "expected_dimensions": EMBEDDING_DIMENSIONS,
        "current_embedding_dimensions": current_dimensions,
        "embedding_provider": "ollama",
        "llm_provider": get_config_value("LLM_PROVIDER", "openai"),
        "embedding_model": runtime["model"],
        "model_digest": runtime["model_digest"],
        "runtime": runtime,
        "provider_error": provider_error,
        "namespaces": namespaces,
        "memories_total": memory_total,
        "memories_checked": memory_vectors,
        "missing_memory_vectors": missing_memory_vectors,
        "memory_issues": memory_issues,
        "memory_issues_count": memory_issue_count,
        "tools_total": tool_total,
        "tools_checked": tool_vectors,
        "missing_tool_vectors": missing_tool_vectors,
        "tool_issues": tool_issues,
        "tool_issues_count": tool_issue_count,
    }


def print_health_report(health: dict) -> None:
    mode = health["mode"]
    title = "Embedding Runtime Preflight" if health.get("runtime_only") else "Embedding Health"
    print(f"{BOLD}{title} - {mode.upper()}{NC}")
    print(f"{GREEN if health['ok'] else RED}{'✅ Healthy' if health['ok'] else '❌ Unhealthy'}{NC}")
    print(f"{BLUE}Contract:{NC} Ollama / {health.get('embedding_model')} / {health.get('expected_dimensions')}D")
    print(f"{BLUE}Digest:{NC} {health.get('model_digest')}")
    runtime = health.get("runtime", {})
    print(f"{BLUE}Compatible hosts:{NC} {', '.join(runtime.get('compatible_hosts', [])) or 'none'}")
    if runtime.get("unavailable_hosts"):
        print(f"{YELLOW}Unavailable hosts:{NC} {', '.join(runtime['unavailable_hosts'])}")
    if runtime.get("missing_model_hosts"):
        print(f"{YELLOW}Hosts missing model:{NC} {', '.join(runtime['missing_model_hosts'])}")
    if health.get("provider_error"):
        print(f"{RED}Embedding provider unavailable:{NC} {health['provider_error']}")

    for namespace in health.get("namespaces", []):
        color = GREEN if namespace["ok"] else RED
        print(
            f"{color}{namespace['namespace']}: {namespace['status']}"
            f" ({namespace['vector_count']} vectors){NC}"
        )
        if namespace.get("reason") and not namespace["ok"]:
            print(f"  {namespace['reason']}")

    if "memories_total" in health:
        print(
            f"Memory vectors: {health['memories_checked']}/{health['memories_total']} "
            f"({health['memory_issues_count']} corrupt or wrong-size)"
        )
        print(
            f"Tool vectors: {health['tools_checked']}/{health['tools_total']} "
            f"({health['tool_issues_count']} corrupt or wrong-size)"
        )

    if not health["ok"]:
        print()
        if health.get("runtime_only"):
            print(f"{YELLOW}Jarvis does not install Ollama or pull models automatically.{NC}")
            print("Set OLLAMA_BASE_URL to the intended daemon host(s), ensure Ollama is running,")
            print(
                "and pull bigsk1/jarvis-embedding:bf16-v1 on each host before "
                "starting Jarvis."
            )
        else:
            print(f"{YELLOW}Semantic retrieval is fail-closed for incompatible namespaces.{NC}")
            print("Back up the DB, then run ./bin/rebuild-embeddings for preserved data")
            print("or delete the incompatible DB and restart for a clean initialization.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Jarvis embedding fingerprints")
    parser.add_argument("mode", nargs="?", default="cloud", choices=["cloud", "local"])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--both", action="store_true")
    parser.add_argument(
        "--runtime-only",
        action="store_true",
        help="check configured Ollama hosts/model without reading or creating databases",
    )
    args = parser.parse_args()

    modes = ["cloud", "local"] if args.both else [args.mode]
    checker = check_embedding_runtime if args.runtime_only else check_embedding_dimensions
    reports = {mode: checker(mode) for mode in modes}
    if args.json:
        payload = reports if args.both else reports[args.mode]
        print(json.dumps(payload, indent=2))
    else:
        for index, mode in enumerate(modes):
            if index:
                print()
            print_health_report(reports[mode])
    if not all(report["ok"] for report in reports.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
