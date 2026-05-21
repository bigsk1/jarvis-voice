#!/usr/bin/env python3
"""
Check cloud/local memory sync health without enforcing hard failures by default.

Reports:
- DB availability (cloud/local present, missing, or unreadable)
- Intel hash drift (on-disk file hash vs cloud/local intel_hash_* rows)
- Logical memory drift (rows only in one DB, plus conflicting values for same key/source)
- Structured user_model drift (traits only in one DB, plus conflicting values)

Examples:
    ./bin/check-memory-sync-health.py
    ./bin/check-memory-sync-health.py --limit 20
    ./bin/check-memory-sync-health.py --json
    ./bin/check-memory-sync-health.py --include-system
    ./bin/check-memory-sync-health.py --strict
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
BOLD = "\033[1m"
NC = "\033[0m"


def _md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect_db(path: Path) -> tuple[sqlite3.Connection | None, str | None]:
    if not path.exists():
        return None, "missing"
    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        return conn, None
    except Exception as exc:
        return None, str(exc)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _load_intel_hashes(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        """
        SELECT key, value
        FROM knowledge_base
        WHERE category = 'system' AND key LIKE 'intel_hash_%'
        """
    ).fetchall()
    hashes: dict[str, str] = {}
    for row in rows:
        filename = row["key"].replace("intel_hash_", "", 1)
        hashes[filename] = row["value"]
    return hashes


def _load_user_model_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "user_model"):
        return []
    columns = _table_columns(conn, "user_model")
    select_columns = [
        "key",
        "value",
        "value_type" if "value_type" in columns else "'scalar' AS value_type",
        "confidence" if "confidence" in columns else "0.5 AS confidence",
        "evidence" if "evidence" in columns else "NULL AS evidence",
        "source" if "source" in columns else "NULL AS source",
        "metadata" if "metadata" in columns else "NULL AS metadata",
        "last_reconciled_at" if "last_reconciled_at" in columns else "NULL AS last_reconciled_at",
    ]
    rows = conn.execute(
        f"""
        SELECT {', '.join(select_columns)}
        FROM user_model
        """
    ).fetchall()
    return [
        {
            "key": row["key"] or "",
            "value": row["value"] or "",
            "value_type": row["value_type"] or "",
            "confidence": float(row["confidence"] or 0),
            "evidence": row["evidence"] or "",
            "source": row["source"] or "",
            "metadata": row["metadata"] or "",
            "last_reconciled_at": row["last_reconciled_at"] or "",
        }
        for row in rows
    ]


def _load_memory_rows(conn: sqlite3.Connection, include_system: bool = False) -> list[dict[str, Any]]:
    query = """
        SELECT category, key, value, importance, source, long_form
        FROM knowledge_base
    """
    if not include_system:
        query += " WHERE category != 'system'"
    rows = conn.execute(query).fetchall()
    return [
        {
            "category": row["category"] or "",
            "key": row["key"] or "",
            "value": row["value"] or "",
            "importance": int(row["importance"] or 0),
            "source": row["source"] or "",
            "long_form": row["long_form"] or "",
        }
        for row in rows
    ]


def _row_signature(row: dict[str, Any]) -> tuple[str, str, str, str, str, int]:
    return (
        row["category"],
        row["key"],
        row["value"],
        row["source"],
        row["long_form"],
        row["importance"],
    )


def _row_brief(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": row["category"],
        "key": row["key"],
        "value": row["value"][:120],
        "source": row["source"],
        "importance": row["importance"],
    }


def _logical_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (row["category"], row["key"], row["source"])


def _compare_intel_hashes(
    intel_dir: Path,
    cloud_hashes: dict[str, str] | None,
    local_hashes: dict[str, str] | None,
) -> dict[str, Any]:
    disk_hashes: dict[str, str] = {}
    if intel_dir.exists():
        for path in sorted(intel_dir.glob("*")):
            if not path.is_file():
                continue
            if path.name == "README.md":
                continue
            if path.suffix.lower() not in {".md", ".txt"}:
                continue
            disk_hashes[path.name] = _md5_file(path)

    filenames = sorted(set(disk_hashes) | set(cloud_hashes or {}) | set(local_hashes or {}))
    mismatches = []
    for filename in filenames:
        disk_hash = disk_hashes.get(filename)
        cloud_hash = (cloud_hashes or {}).get(filename)
        local_hash = (local_hashes or {}).get(filename)
        mismatch = {
            "filename": filename,
            "disk_hash": disk_hash,
            "cloud_hash": cloud_hash,
            "local_hash": local_hash,
        }
        if len({value for value in [disk_hash, cloud_hash, local_hash] if value is not None}) > 1:
            mismatches.append(mismatch)

    return {
        "intel_files_on_disk": len(disk_hashes),
        "cloud_hash_rows": len(cloud_hashes or {}),
        "local_hash_rows": len(local_hashes or {}),
        "mismatches": mismatches,
    }


def _compare_memory_rows(
    cloud_rows: list[dict[str, Any]] | None,
    local_rows: list[dict[str, Any]] | None,
    limit: int,
) -> dict[str, Any]:
    if cloud_rows is None or local_rows is None:
        return {
            "comparable": False,
            "only_in_cloud_count": 0,
            "only_in_local_count": 0,
            "value_conflict_count": 0,
            "samples": {
                "only_in_cloud": [],
                "only_in_local": [],
                "value_conflicts": [],
            },
        }

    cloud_map = {_row_signature(row): row for row in cloud_rows}
    local_map = {_row_signature(row): row for row in local_rows}

    only_in_cloud_sigs = sorted(set(cloud_map) - set(local_map))
    only_in_local_sigs = sorted(set(local_map) - set(cloud_map))

    cloud_groups: dict[tuple[str, str, str], set[tuple[str, str, int]]] = defaultdict(set)
    local_groups: dict[tuple[str, str, str], set[tuple[str, str, int]]] = defaultdict(set)

    for row in cloud_rows:
        cloud_groups[_logical_key(row)].add((row["value"], row["long_form"], row["importance"]))
    for row in local_rows:
        local_groups[_logical_key(row)].add((row["value"], row["long_form"], row["importance"]))

    value_conflicts = []
    for logical_key in sorted(set(cloud_groups) & set(local_groups)):
        if cloud_groups[logical_key] == local_groups[logical_key]:
            continue
        category, key, source = logical_key
        value_conflicts.append(
            {
                "category": category,
                "key": key,
                "source": source,
                "cloud_entries": len(cloud_groups[logical_key]),
                "local_entries": len(local_groups[logical_key]),
                "cloud_values": [entry[0][:120] for entry in sorted(cloud_groups[logical_key])[:3]],
                "local_values": [entry[0][:120] for entry in sorted(local_groups[logical_key])[:3]],
            }
        )

    return {
        "comparable": True,
        "cloud_memory_count": len(cloud_rows),
        "local_memory_count": len(local_rows),
        "only_in_cloud_count": len(only_in_cloud_sigs),
        "only_in_local_count": len(only_in_local_sigs),
        "value_conflict_count": len(value_conflicts),
        "samples": {
            "only_in_cloud": [_row_brief(cloud_map[sig]) for sig in only_in_cloud_sigs[:limit]],
            "only_in_local": [_row_brief(local_map[sig]) for sig in only_in_local_sigs[:limit]],
            "value_conflicts": value_conflicts[:limit],
        },
    }


def _user_model_signature(row: dict[str, Any]) -> tuple[str, str, str, float, str, str, str, str]:
    return (
        row["key"],
        row["value"],
        row["value_type"],
        row["confidence"],
        row["evidence"],
        row["source"],
        row["metadata"],
        row["last_reconciled_at"],
    )


def _compare_user_model_rows(
    cloud_rows: list[dict[str, Any]] | None,
    local_rows: list[dict[str, Any]] | None,
    limit: int,
) -> dict[str, Any]:
    if cloud_rows is None or local_rows is None:
        return {
            "comparable": False,
            "cloud_count": 0,
            "local_count": 0,
            "only_in_cloud_count": 0,
            "only_in_local_count": 0,
            "value_conflict_count": 0,
            "samples": {"only_in_cloud": [], "only_in_local": [], "value_conflicts": []},
        }

    cloud_by_sig = {_user_model_signature(row): row for row in cloud_rows}
    local_by_sig = {_user_model_signature(row): row for row in local_rows}
    only_cloud = sorted(set(cloud_by_sig) - set(local_by_sig))
    only_local = sorted(set(local_by_sig) - set(cloud_by_sig))

    cloud_by_key = {row["key"]: row for row in cloud_rows}
    local_by_key = {row["key"]: row for row in local_rows}
    conflicts = []
    for key in sorted(set(cloud_by_key) & set(local_by_key)):
        if _user_model_signature(cloud_by_key[key]) == _user_model_signature(local_by_key[key]):
            continue
        conflicts.append({
            "key": key,
            "cloud_value": cloud_by_key[key]["value"],
            "local_value": local_by_key[key]["value"],
            "cloud_confidence": cloud_by_key[key]["confidence"],
            "local_confidence": local_by_key[key]["confidence"],
        })

    return {
        "comparable": True,
        "cloud_count": len(cloud_rows),
        "local_count": len(local_rows),
        "only_in_cloud_count": len(only_cloud),
        "only_in_local_count": len(only_local),
        "value_conflict_count": len(conflicts),
        "samples": {
            "only_in_cloud": [
                {"key": cloud_by_sig[sig]["key"], "value": cloud_by_sig[sig]["value"]}
                for sig in only_cloud[:limit]
            ],
            "only_in_local": [
                {"key": local_by_sig[sig]["key"], "value": local_by_sig[sig]["value"]}
                for sig in only_local[:limit]
            ],
            "value_conflicts": conflicts[:limit],
        },
    }


def build_sync_health_report(
    project_root: Path,
    *,
    cloud_db_path: Path | None = None,
    local_db_path: Path | None = None,
    intel_dir: Path | None = None,
    limit: int = 10,
    include_system: bool = False,
) -> dict[str, Any]:
    data_dir = project_root / "data"
    cloud_db_path = cloud_db_path or (data_dir / "jarvis_memory.db")
    local_db_path = local_db_path or (data_dir / "jarvis_memory_local.db")
    intel_dir = intel_dir or (project_root / "jarvis-intel")

    cloud_conn, cloud_error = _connect_db(cloud_db_path)
    local_conn, local_error = _connect_db(local_db_path)

    try:
        cloud_hashes = _load_intel_hashes(cloud_conn) if cloud_conn else None
        local_hashes = _load_intel_hashes(local_conn) if local_conn else None
        cloud_rows = _load_memory_rows(cloud_conn, include_system=include_system) if cloud_conn else None
        local_rows = _load_memory_rows(local_conn, include_system=include_system) if local_conn else None
        cloud_user_model = _load_user_model_rows(cloud_conn) if cloud_conn else None
        local_user_model = _load_user_model_rows(local_conn) if local_conn else None
    finally:
        if cloud_conn:
            cloud_conn.close()
        if local_conn:
            local_conn.close()

    intel_report = _compare_intel_hashes(intel_dir, cloud_hashes, local_hashes)
    memory_report = _compare_memory_rows(cloud_rows, local_rows, limit)
    user_model_report = _compare_user_model_rows(cloud_user_model, local_user_model, limit)

    db_status = {
        "cloud": {
            "path": str(cloud_db_path),
            "available": cloud_error is None,
            "error": cloud_error,
        },
        "local": {
            "path": str(local_db_path),
            "available": local_error is None,
            "error": local_error,
        },
    }

    mismatch_count = (
        len(intel_report["mismatches"])
        + memory_report["only_in_cloud_count"]
        + memory_report["only_in_local_count"]
        + memory_report["value_conflict_count"]
        + user_model_report["only_in_cloud_count"]
        + user_model_report["only_in_local_count"]
        + user_model_report["value_conflict_count"]
    )

    warnings = []
    if not db_status["cloud"]["available"]:
        warnings.append(f"cloud DB unavailable: {db_status['cloud']['error']}")
    if not db_status["local"]["available"]:
        warnings.append(f"local DB unavailable: {db_status['local']['error']}")
    if len(intel_report["mismatches"]) > 0:
        warnings.append(f"{len(intel_report['mismatches'])} intel hash mismatch(es)")
    if memory_report["only_in_cloud_count"] > 0 or memory_report["only_in_local_count"] > 0:
        warnings.append(
            f"logical memory drift: cloud-only={memory_report['only_in_cloud_count']}, "
            f"local-only={memory_report['only_in_local_count']}"
        )
    if memory_report["value_conflict_count"] > 0:
        warnings.append(f"{memory_report['value_conflict_count']} memory value conflict(s)")
    if (
        user_model_report["only_in_cloud_count"] > 0
        or user_model_report["only_in_local_count"] > 0
        or user_model_report["value_conflict_count"] > 0
    ):
        warnings.append(
            f"user_model drift: cloud-only={user_model_report['only_in_cloud_count']}, "
            f"local-only={user_model_report['only_in_local_count']}, "
            f"conflicts={user_model_report['value_conflict_count']}"
        )

    return {
        "ok": mismatch_count == 0 and all(status["available"] for status in db_status.values()),
        "project_root": str(project_root),
        "warnings": warnings,
        "db_status": db_status,
        "intel": intel_report,
        "memories": memory_report,
        "user_model": user_model_report,
    }


def _print_status(report: dict[str, Any], limit: int) -> None:
    print(f"{BOLD}╔════════════════════════════════════════════════════════════╗{NC}")
    print(f"{BOLD}║           Memory Sync Health Check                        ║{NC}")
    print(f"{BOLD}╚════════════════════════════════════════════════════════════╝{NC}")
    print()

    if report["ok"]:
        print(f"{GREEN}✅ Cloud/local memory state looks aligned{NC}")
    else:
        print(f"{YELLOW}⚠️  Drift or partial availability detected{NC}")
    print()

    print(f"{BOLD}DB Availability:{NC}")
    for name in ("cloud", "local"):
        status = report["db_status"][name]
        if status["available"]:
            print(f"  {GREEN}✓{NC} {name}: {status['path']}")
        else:
            print(f"  {YELLOW}!{NC} {name}: {status['error']} ({status['path']})")
    print()

    intel = report["intel"]
    print(f"{BOLD}Intel Hashes:{NC}")
    print(f"  Disk files: {intel['intel_files_on_disk']}")
    print(f"  Cloud hash rows: {intel['cloud_hash_rows']}")
    print(f"  Local hash rows: {intel['local_hash_rows']}")
    print(f"  Mismatches: {len(intel['mismatches'])}")
    for item in intel["mismatches"][:limit]:
        print(f"  {YELLOW}!{NC} {item['filename']}")
        print(f"     disk:  {item['disk_hash']}")
        print(f"     cloud: {item['cloud_hash']}")
        print(f"     local: {item['local_hash']}")
    print()

    memories = report["memories"]
    print(f"{BOLD}Logical Memories:{NC}")
    if not memories["comparable"]:
        print(f"  {YELLOW}!{NC} Skipped cloud/local comparison because one DB is unavailable")
        return

    print(f"  Cloud rows checked: {memories['cloud_memory_count']}")
    print(f"  Local rows checked: {memories['local_memory_count']}")
    print(f"  Cloud-only rows: {memories['only_in_cloud_count']}")
    print(f"  Local-only rows: {memories['only_in_local_count']}")
    print(f"  Value conflicts: {memories['value_conflict_count']}")

    for label in ("only_in_cloud", "only_in_local"):
        samples = memories["samples"][label]
        if not samples:
            continue
        print()
        heading = "Cloud-only samples" if label == "only_in_cloud" else "Local-only samples"
        print(f"  {BOLD}{heading}:{NC}")
        for row in samples[:limit]:
            print(
                f"    - [{row['category']}] {row['key']} = {row['value']}"
                + (f" (source: {row['source']})" if row["source"] else "")
            )

    conflicts = memories["samples"]["value_conflicts"]
    if conflicts:
        print()
        print(f"  {BOLD}Value conflict samples:{NC}")
        for conflict in conflicts[:limit]:
            print(
                f"    - [{conflict['category']}] {conflict['key']}"
                + (f" (source: {conflict['source']})" if conflict["source"] else "")
            )
            print(f"      cloud: {conflict['cloud_values']}")
            print(f"      local: {conflict['local_values']}")

    user_model = report["user_model"]
    print()
    print(f"{BOLD}User Model:{NC}")
    if not user_model["comparable"]:
        print(f"  {YELLOW}!{NC} Skipped cloud/local comparison because one DB is unavailable")
        return
    print(f"  Cloud traits: {user_model['cloud_count']}")
    print(f"  Local traits: {user_model['local_count']}")
    print(f"  Cloud-only traits: {user_model['only_in_cloud_count']}")
    print(f"  Local-only traits: {user_model['only_in_local_count']}")
    print(f"  Trait conflicts: {user_model['value_conflict_count']}")

    for label in ("only_in_cloud", "only_in_local"):
        samples = user_model["samples"][label]
        if not samples:
            continue
        heading = "Cloud-only traits" if label == "only_in_cloud" else "Local-only traits"
        print(f"  {BOLD}{heading}:{NC}")
        for row in samples[:limit]:
            print(f"    - {row['key']} = {row['value']}")

    if user_model["samples"]["value_conflicts"]:
        print(f"  {BOLD}Trait conflict samples:{NC}")
        for conflict in user_model["samples"]["value_conflicts"][:limit]:
            print(f"    - {conflict['key']}: cloud={conflict['cloud_value']} local={conflict['local_value']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check cloud/local memory sync health")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of formatted text")
    parser.add_argument("--limit", type=int, default=10, help="Max mismatch samples per section")
    parser.add_argument(
        "--include-system",
        action="store_true",
        help="Include system-category memories in logical row comparison",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when DBs are unavailable or mismatches are found",
    )
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--cloud-db", type=Path, default=None, help="Override cloud DB path")
    parser.add_argument("--local-db", type=Path, default=None, help="Override local DB path")
    parser.add_argument("--intel-dir", type=Path, default=None, help="Override jarvis-intel path")
    args = parser.parse_args()

    report = build_sync_health_report(
        args.project_root.resolve(),
        cloud_db_path=args.cloud_db.resolve() if args.cloud_db else None,
        local_db_path=args.local_db.resolve() if args.local_db else None,
        intel_dir=args.intel_dir.resolve() if args.intel_dir else None,
        limit=max(1, args.limit),
        include_system=args.include_system,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_status(report, max(1, args.limit))

    if args.strict and not report["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
