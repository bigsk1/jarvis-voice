"""Bounded watch receipts for saved chat context; values remain untrusted data."""

from __future__ import annotations

import json
import math
from typing import Any


def _compact_row(row: dict) -> dict:
    result = {}
    for key in (
        "key", "scope", "mode", "owner", "run_id", "event_id", "claim_token",
        "record_id", "kind", "revision", "status", "state", "channel", "destination",
        "attempts", "lease_until", "delivered_at", "muted", "stale", "pending_count",
        "parked_count", "error_count", "last_success_at", "missing_count", "removed",
    ):
        val = row.get(key)
        if val is None or isinstance(val, (str, bool, int)) or (isinstance(val, float) and math.isfinite(val)):
            if key in row and (not isinstance(val, str) or len(val) <= 1024):
                result[key] = val
    for key in ("fields", "before", "after", "record", "receipt", "definition"):
        if key not in row:
            continue
        try:
            size = len(json.dumps(row[key], ensure_ascii=False, allow_nan=False))
        except (ValueError, TypeError, RecursionError):
            size = 10000
        if size <= 650:
            result[key] = row[key]
        else:
            result[key + "_omitted"] = True
            result["context_truncated"] = True
    return result


def project_watch_runs(value: Any, *, max_chars: int = 10000) -> dict:
    """Keep exact run/event handles, with bounded previews and visible truncation.

    Full records live in the watch store. Never shorten a handle into a different
    valid-looking handle, and never imply a delivery succeeded from prose.
    """
    runs = value if isinstance(value, list) else [value]
    selected = [run for run in runs[-4:] if isinstance(run, dict)]
    output: list[dict] = []
    truncated = len(selected) < len(runs)
    for run in selected:
        payload = run.get("data") if isinstance(run.get("data"), dict) else run
        compact = {}
        for key in (
            "action", "key", "mode", "scope", "owner", "run_id", "event_id", "claim_token",
            "revision", "base_revision", "schema_version", "committed", "dry_run",
            "initialized", "quiet", "complete", "muted", "status", "success",
            "channel", "destination", "state", "attempts", "count", "total",
            "has_more", "offset", "next_offset", "pending_count", "issue_count",
            "stale_count", "parked_count", "error_count", "healthy",
            "changes_count", "events_count", "records_count", "snapshot_count",
            "quiet_first", "already_committed", "already_delivered", "lease_until",
            "last_run_at", "last_success_at", "delivery_error_count",
            "claimed", "counts_complete", "items_truncated", "changes_truncated",
        ):
            val = payload.get(key)
            if val is None or not isinstance(val, (str, int, float, bool)):
                continue
            if isinstance(val, float) and not math.isfinite(val):
                truncated = True
                continue
            if isinstance(val, str) and len(val) > 1024:
                truncated = True
                continue
            compact[key] = val
        if isinstance(run.get("ok"), bool):
            compact["ok"] = run["ok"]
        if payload.get("action") == "health" and isinstance(payload.get("ok"), bool):
            compact["health_ok"] = payload["ok"]
        # Keep complete rows within the budget. Skipping an oversized value is
        # preferable to silently turning a partial record into a full snapshot.
        for key in (
            "changes", "events", "deliveries", "items", "watches", "history",
            "records", "snapshot", "handled_ids", "event_ids", "issues", "counts", "definition", "receipt",
        ):
            val = payload.get(key)
            if not isinstance(val, (list, dict)):
                continue
            bounded = val[:5] if isinstance(val, list) else val
            if isinstance(bounded, list):
                bounded = [_compact_row(row) if isinstance(row, dict) else row for row in bounded]
            try:
                encoded = json.dumps(bounded, ensure_ascii=False, allow_nan=False)
                while isinstance(bounded, list) and len(bounded) > 1 and len(encoded) > 4500:
                    bounded.pop()
                    truncated = True
                    compact[key + "_truncated"] = True
                    encoded = json.dumps(bounded, ensure_ascii=False, allow_nan=False)
            except (ValueError, TypeError, RecursionError):
                truncated = True
                continue
            if len(encoded) <= 4500:
                compact[key] = bounded
            else:
                truncated = True
            if isinstance(val, list) and len(val) > 5:
                compact[key + "_count"] = len(val)
                compact[key + "_truncated"] = True
                truncated = True
        if compact:
            output.append(compact)
    result = output[0] if len(runs) == 1 and output else {
        "runs_count": len(runs), "results": output,
    }
    if truncated:
        result["context_truncated"] = True
    # The store caps handles independently. Drop previews first if the combined
    # envelope grows; subsequent inspect/pending calls recover the full data.
    while len(json.dumps(result, ensure_ascii=False, allow_nan=False)) > max_chars:
        removable = next(((item, key) for item in output for key in (
            "records", "history", "items", "changes", "events", "watches",
            "definition", "receipt", "handled_ids", "event_ids", "snapshot", "issues", "deliveries",
        ) if key in item), None)
        if removable is None:
            if len(output) > 1:
                output.pop(0)
                result["context_truncated"] = True
                continue
            item = output[0] if output else result
            secondary = next((key for key in item if key not in {
                "action", "key", "mode", "run_id", "event_id", "claim_token",
                "channel", "destination", "state", "success", "committed", "ok",
                "context_truncated",
            }), None)
            if secondary:
                del item[secondary]
                result["context_truncated"] = True
                continue
            break
        del removable[0][removable[1]]
        result["context_truncated"] = True
    return result
