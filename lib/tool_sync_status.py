"""Durable, mode-specific Tool RAG synchronization status."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


STATUS_VERSION = 1


def _project_root(project_root: Path | str | None = None) -> Path:
    return Path(project_root).resolve() if project_root else Path(__file__).parent.parent.resolve()


def _validate_mode(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized not in {"cloud", "local"}:
        raise ValueError(f"Unsupported Tool RAG sync mode: {mode}")
    return normalized


def tool_sync_status_path(mode: str, *, project_root: Path | str | None = None) -> Path:
    normalized = _validate_mode(mode)
    return _project_root(project_root) / "data" / f".tool_sync_status_{normalized}.json"


def _write_status(mode: str, payload: dict, *, project_root: Path | str | None = None) -> dict:
    path = tool_sync_status_path(mode, project_root=project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, sort_keys=True, indent=2) + "\n"

    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temp_name).replace(path)
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)

    return payload


def _base_status(mode: str, status: str, usable_tool_count: int) -> dict:
    normalized = _validate_mode(mode)
    count = max(0, int(usable_tool_count or 0))
    return {
        "version": STATUS_VERSION,
        "event_id": uuid4().hex,
        "mode": normalized,
        "status": status,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "usable_tool_count": count,
        "has_usable_index": count > 0,
    }


def record_tool_sync_failure(
    mode: str,
    *,
    exit_code: int,
    reason: str,
    usable_tool_count: int,
    project_root: Path | str | None = None,
) -> dict:
    normalized_exit_code = int(exit_code)
    if normalized_exit_code <= 0:
        raise ValueError("Tool RAG failure exit code must be positive")
    payload = _base_status(mode, "failed", usable_tool_count)
    payload.update({
        "exit_code": normalized_exit_code,
        "reason": str(reason or "Tool RAG synchronization failed")[:1000],
    })
    return _write_status(mode, payload, project_root=project_root)


def record_tool_sync_success(
    mode: str,
    *,
    usable_tool_count: int,
    project_root: Path | str | None = None,
) -> dict:
    payload = _base_status(mode, "ok", usable_tool_count)
    return _write_status(mode, payload, project_root=project_root)


def read_tool_sync_status(
    mode: str,
    *,
    project_root: Path | str | None = None,
) -> dict | None:
    path = tool_sync_status_path(mode, project_root=project_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    normalized_mode = _validate_mode(mode)
    if not isinstance(payload, dict):
        return None
    if payload.get("version") != STATUS_VERSION or payload.get("mode") != normalized_mode:
        return None
    if payload.get("status") not in {"ok", "failed"}:
        return None
    if not isinstance(payload.get("event_id"), str) or not payload["event_id"]:
        return None
    if not isinstance(payload.get("recorded_at"), str) or not payload["recorded_at"]:
        return None
    usable_count = payload.get("usable_tool_count")
    if isinstance(usable_count, bool) or not isinstance(usable_count, int) or usable_count < 0:
        return None
    if not isinstance(payload.get("has_usable_index"), bool):
        return None
    if payload["has_usable_index"] != (usable_count > 0):
        return None
    if payload["status"] == "failed":
        exit_code = payload.get("exit_code")
        if isinstance(exit_code, bool) or not isinstance(exit_code, int) or exit_code <= 0:
            return None
        if not isinstance(payload.get("reason"), str) or not payload["reason"]:
            return None
    if payload["status"] == "ok" and ("exit_code" in payload or "reason" in payload):
        return None
    return payload


def count_usable_tool_embeddings(
    mode: str,
    *,
    project_root: Path | str | None = None,
) -> int:
    normalized = _validate_mode(mode)
    db_name = "jarvis_memory_local.db" if normalized == "local" else "jarvis_memory.db"
    db_path = _project_root(project_root) / "data" / db_name
    if not db_path.exists():
        return 0
    try:
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM tool_definitions WHERE enabled = 1 AND embedding IS NOT NULL"
            ).fetchone()
            return int(row[0] or 0) if row else 0
    except (sqlite3.Error, OSError):
        return 0
