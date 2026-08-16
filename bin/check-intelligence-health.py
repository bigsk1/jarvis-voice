#!/usr/bin/env python3
"""Validate Intelligence data plus every persisted embedding namespace."""

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
    INTELLIGENCE_CONTEXT_NAMESPACE,
    INTELLIGENCE_INSIGHT_NAMESPACE,
    INTELLIGENCE_OUTCOME_NAMESPACE,
    INTELLIGENCE_PATTERN_NAMESPACE,
    INTELLIGENCE_QUERY_NAMESPACE,
    embedding_namespace_status,
)
from embeddings import EMBEDDING_DIMENSIONS, get_embedding_runtime_status

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
BOLD = "\033[1m"
NC = "\033[0m"


def _scan_column(
    cursor,
    table: str,
    column: str,
    eligible_where: str = "1 = 1",
) -> tuple[int, int, list[dict]]:
    rows = cursor.execute(
        f"SELECT id, {column} FROM {table} "
        f"WHERE ({eligible_where}) AND {column} IS NOT NULL"
    ).fetchall()
    issues = []
    issue_count = 0
    for identifier, blob in rows:
        try:
            dimensions = len(pickle.loads(blob))
            if dimensions != EMBEDDING_DIMENSIONS:
                issue_count += 1
                if len(issues) < 100:
                    issues.append({
                        "id": identifier,
                        "field": column,
                        "expected": EMBEDDING_DIMENSIONS,
                        "actual": dimensions,
                    })
        except Exception as exc:
            issue_count += 1
            if len(issues) < 100:
                issues.append({"id": identifier, "field": column, "error": str(exc)})
    return len(rows), issue_count, issues


def check_intelligence_health(mode: str = "cloud", _scoped: bool = False) -> dict:
    if not _scoped:
        with config_scope(mode):
            return check_intelligence_health(mode, _scoped=True)

    relative_path = (
        "data/jarvis_intelligence_local.db"
        if mode == "local"
        else "data/jarvis_intelligence.db"
    )
    db_file = Path(__file__).parent.parent / relative_path
    runtime = get_embedding_runtime_status(force_refresh=True)
    result = {
        "ok": runtime["ok"],
        "mode": mode,
        "db_path": relative_path,
        "expected_dimensions": EMBEDDING_DIMENSIONS,
        "embedding_model": runtime["model"],
        "model_digest": runtime["model_digest"],
        "runtime": runtime,
        "issues": [],
        "warnings": [],
        "stats": {},
        "namespaces": [],
    }
    if not runtime["ok"]:
        result["issues"].append(runtime["error"])

    if not db_file.exists():
        result["warnings"].append(
            f"Database not found: {relative_path} (will be created on first use)"
        )
        result["stats"] = {"experiences": 0, "insights": 0, "pending_reflections": 0}
        return result

    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.cursor()
        experiences = cursor.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]
        insights = cursor.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
        pending = cursor.execute(
            "SELECT COUNT(*) FROM reflection_queue WHERE processed = 0"
        ).fetchone()[0]
        result["stats"] = {
            "experiences": experiences,
            "insights": insights,
            "pending_reflections": pending,
        }
        context_documents = cursor.execute(
            "SELECT COUNT(*) FROM experiences "
            "WHERE context_summary IS NOT NULL AND TRIM(context_summary) != ''"
        ).fetchone()[0]
        insight_documents = cursor.execute(
            "SELECT COUNT(*) FROM insights "
            "WHERE description IS NOT NULL AND TRIM(description) != ''"
        ).fetchone()[0]
        pattern_documents = cursor.execute(
            "SELECT COUNT(*) FROM insights "
            "WHERE applies_to_pattern IS NOT NULL AND TRIM(applies_to_pattern) != ''"
        ).fetchone()[0]

        specs = [
            (
                INTELLIGENCE_QUERY_NAMESPACE,
                "experiences",
                "query_embedding",
                experiences,
                "1 = 1",
            ),
            (
                INTELLIGENCE_CONTEXT_NAMESPACE,
                "experiences",
                "context_embedding",
                context_documents,
                "context_summary IS NOT NULL AND TRIM(context_summary) != ''",
            ),
            (
                INTELLIGENCE_OUTCOME_NAMESPACE,
                "experiences",
                "outcome_embedding",
                experiences,
                "1 = 1",
            ),
            (
                INTELLIGENCE_INSIGHT_NAMESPACE,
                "insights",
                "insight_embedding",
                insight_documents,
                "description IS NOT NULL AND TRIM(description) != ''",
            ),
            (
                INTELLIGENCE_PATTERN_NAMESPACE,
                "insights",
                "pattern_embedding",
                pattern_documents,
                "applies_to_pattern IS NOT NULL AND TRIM(applies_to_pattern) != ''",
            ),
        ]
        vector_issues = []
        vector_issue_count = 0
        missing_required = []
        for namespace, table, column, required_total, eligible_where in specs:
            vector_count, issue_count, issues = _scan_column(
                cursor,
                table,
                column,
                eligible_where,
            )
            status = embedding_namespace_status(
                conn,
                namespace,
                vector_count=vector_count,
            )
            result["namespaces"].append(status)
            vector_issues.extend(issues)
            vector_issue_count += issue_count
            if required_total is not None and vector_count < required_total:
                missing_required.append({
                    "namespace": namespace,
                    "missing": required_total - vector_count,
                })

        if vector_issue_count:
            result["issues"].append(
                f"{vector_issue_count} vectors are corrupt or have the wrong dimensions"
            )
        result["embedding_issues_count"] = vector_issue_count
        result["embedding_issue_samples"] = vector_issues
        incompatible = [item for item in result["namespaces"] if not item["ok"]]
        for item in incompatible:
            result["issues"].append(f"{item['namespace']}: {item['reason']}")
        for item in missing_required:
            result["warnings"].append(
                f"{item['namespace']} is missing {item['missing']} required vectors"
            )

        stale = cursor.execute(
            """
            SELECT COUNT(*) FROM reflection_queue
            WHERE processed = 0 AND queued_at < datetime('now', '-1 hour')
            """
        ).fetchone()[0]
        if stale:
            result["warnings"].append(f"{stale} reflections pending for more than one hour")

        average = cursor.execute("SELECT AVG(confidence) FROM insights").fetchone()[0] or 0
        result["stats"]["avg_confidence"] = round(average, 3)
        constraints = cursor.execute(
            "SELECT constraint_type, COUNT(*) FROM insights GROUP BY constraint_type"
        ).fetchall()
        counts = {kind or "positive": count for kind, count in constraints}
        result["stats"]["positive_constraints"] = counts.get("positive", 0)
        result["stats"]["negative_constraints"] = counts.get("negative", 0)
    except Exception as exc:
        result["issues"].append(f"Failed to inspect Intelligence DB: {exc}")
    finally:
        conn.close()

    result["enabled"] = str(
        get_config_value("JARVIS_INTELLIGENCE", "true") or ""
    ).lower() in {"true", "1", "yes", "on"}
    if not result["enabled"]:
        result["warnings"].append("Intelligence layer is disabled in configuration")
    result["ok"] = result["ok"] and not result["issues"] and not any(
        "missing" in warning and "required vectors" in warning
        for warning in result["warnings"]
    )
    return result


def print_health_report(health: dict) -> None:
    print(f"{BOLD}Intelligence Health - {health['mode'].upper()}{NC}")
    print(f"{GREEN if health['ok'] else RED}{'✅ Healthy' if health['ok'] else '❌ Unhealthy'}{NC}")
    print(f"{BLUE}Database:{NC} {health['db_path']}")
    print(
        f"{BLUE}Embedding contract:{NC} {health.get('embedding_model')} / "
        f"{health['expected_dimensions']}D / {health.get('model_digest')}"
    )
    stats = health.get("stats", {})
    print(
        f"Experiences: {stats.get('experiences', 0)} | "
        f"Insights: {stats.get('insights', 0)} | "
        f"Pending: {stats.get('pending_reflections', 0)}"
    )
    for namespace in health.get("namespaces", []):
        color = GREEN if namespace["ok"] else RED
        print(
            f"{color}{namespace['namespace']}: {namespace['status']} "
            f"({namespace['vector_count']} vectors){NC}"
        )
    for issue in health.get("issues", []):
        print(f"{RED}✗ {issue}{NC}")
    for warning in health.get("warnings", []):
        print(f"{YELLOW}⚠ {warning}{NC}")
    if not health["ok"]:
        print("Semantic Intelligence retrieval is disabled for incompatible namespaces.")
        print("Run ./bin/rebuild-embeddings or delete the incompatible DB.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Intelligence embedding health")
    parser.add_argument("mode", nargs="?", default="cloud", choices=["cloud", "local"])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--both", action="store_true")
    args = parser.parse_args()
    modes = ["cloud", "local"] if args.both else [args.mode]
    reports = {mode: check_intelligence_health(mode) for mode in modes}
    if args.json:
        print(json.dumps(reports if args.both else reports[args.mode], indent=2))
    else:
        for index, mode in enumerate(modes):
            if index:
                print()
            print_health_report(reports[mode])
    if not all(report["ok"] for report in reports.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
