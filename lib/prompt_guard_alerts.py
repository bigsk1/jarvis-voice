"""Best-effort, metadata-only alerts for confirmed high-scoring content blocks.

The classifier score is an estimate, not proof that an attack succeeded. This
adapter runs only after content was withheld. Alert failures never change that
decision, and no source text, URL, filename, or provider error is published.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sqlite3
from contextlib import closing, nullcontext
from datetime import datetime, timedelta
from typing import Any

from filelock import FileLock

try:
    from config_loader import (
        config_scope,
        get_active_config_mode,
        get_config_value,
        get_scoped_config,
    )
except ModuleNotFoundError as exc:
    if exc.name != "config_loader":
        raise
    from lib.config_loader import (
        config_scope,
        get_active_config_mode,
        get_config_value,
        get_scoped_config,
    )

from lib.prompt_guard import PromptGuardResult, is_enabled

logger = logging.getLogger("prompt_guard.alerts")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,100}\Z")
_INCIDENT_ID = re.compile(r"pg-[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
DEFAULT_ALERT_THRESHOLD = 0.95
DEFAULT_COOLDOWN_SECONDS = 3600
_ALERT_TITLE = "Prompt Guard blocked suspicious content"


def _log_unavailable(channel: str) -> None:
    try:
        logger.warning("[PROMPT_GUARD] %s=unavailable action=keep_withheld", channel)
    except Exception:
        pass


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and 0 <= number <= 1 else None


def _create_alert_manager(mode: str):
    # Import the manager rather than the API route, whose module creates a
    # process-global manager. An active config scope makes load_config a no-op.
    from api.managers.alert_manager import AlertManager

    return AlertManager(mode=mode)


def _recent_alert(manager, dedupe_key: str, cooldown: int) -> int | None:
    """Keep acknowledged blocks quiet during cooldown without a second store."""
    if cooldown <= 0:
        return None
    cutoff = (datetime.now() - timedelta(seconds=cooldown)).isoformat()
    with closing(sqlite3.connect(manager.db.db_path, timeout=0.25)) as connection:
        rows = connection.execute(
            "SELECT id, metadata FROM alerts WHERE source=? AND created_at>=? "
            "AND metadata LIKE ? ORDER BY id DESC",
            ("prompt_guard", cutoff, f'%"dedupe_key": "{dedupe_key}"%'),
        )
        for alert_id, raw_metadata in rows:
            try:
                metadata = json.loads(raw_metadata)
            except (TypeError, ValueError):
                continue
            if isinstance(metadata, dict) and metadata.get("dedupe_key") == dedupe_key:
                return int(alert_id)
    return None


def notify_prompt_guard_block(
    source_name: str, observation: PromptGuardResult, withheld: dict[str, Any],
    *, text_digest: str | None = None,
) -> dict[str, Any] | None:
    """Create an ordinary Jarvis alert after a fully attested content rejection.

    ``text_digest`` is SHA256 of the exact scanned representation, never text.
    It makes repeat suppression stable across incidents and process restarts.
    Pending alerts keep the manager's normal dedupe; recently handled alerts
    also suppress repeats for PROMPT_GUARD_ALERT_COOLDOWN_SECONDS. A receipt is
    optional and must never be treated as permission to restore withheld data.
    """
    manager = None
    try:
        if not isinstance(source_name, str) or not _IDENTIFIER.fullmatch(source_name):
            return None
        if (not isinstance(observation, PromptGuardResult)
                or observation.status != "scanned" or observation.flagged is not True
                or observation.coverage_complete is not True
                or type(observation.windows_scanned) is not int or observation.windows_scanned < 1):
            return None
        score = _number(observation.injection_score)
        block_threshold = _number(observation.threshold)
        if score is None or block_threshold is None or score < block_threshold:
            return None
        if (not isinstance(withheld, dict) or withheld.get("ok") is not False
                or withheld.get("error_code") != "prompt_injection_detected"
                or withheld.get("terminal_failure") is not True or withheld.get("retry_safe") is not False):
            return None
        data = withheld.get("data")
        receipt = data.get("prompt_guard") if isinstance(data, dict) else None
        if not isinstance(receipt, dict) or receipt.get("content_withheld") is not True:
            return None
        source_type = receipt.get("source_type", "tool_result")
        if source_type not in {"tool_result", "attachment"}:
            return None

        mode = get_active_config_mode()
        scope = nullcontext() if get_scoped_config() is not None else config_scope(mode)
        with scope:
            if not is_enabled() or str(get_config_value("PROMPT_GUARD_ALERTS_ENABLED", "false")).lower().strip() not in {
                "true", "1", "yes", "on",
            }:
                return None
            alert_threshold = float(str(get_config_value("PROMPT_GUARD_ALERT_THRESHOLD", DEFAULT_ALERT_THRESHOLD)))
            if not math.isfinite(alert_threshold) or not 0 <= alert_threshold <= 1 or score < alert_threshold:
                return None
            cooldown = int(str(get_config_value("PROMPT_GUARD_ALERT_COOLDOWN_SECONDS", DEFAULT_COOLDOWN_SECONDS)))
            if not 0 <= cooldown <= 604800:
                return None

            metadata: dict[str, Any] = {
                "mode": mode, "source_name": source_name, "source_type": source_type,
                "score": score, "block_threshold": block_threshold, "alert_threshold": alert_threshold,
            }
            incident = receipt.get("incident_id")
            if isinstance(incident, str) and _INCIDENT_ID.fullmatch(incident):
                metadata["incident_id"] = incident
            policy = receipt.get("policy_id")
            if isinstance(policy, str) and _IDENTIFIER.fullmatch(policy):
                metadata["policy_id"] = policy
            if text_digest is not None and (not isinstance(text_digest, str) or not _DIGEST.fullmatch(text_digest)):
                return None
            # The central observer always supplies the digest. Other consumers
            # without one can group only the reviewed metadata, never stringify
            # arbitrary content from a source result.
            fingerprint = text_digest or hashlib.sha256(
                json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            dedupe_digest = hashlib.sha256(
                f"{mode}:{source_type}:{source_name}:{fingerprint}".encode("utf-8")
            ).hexdigest()
            dedupe_key = "prompt_guard:" + dedupe_digest
            metadata["dedupe_key"] = dedupe_key
            manager = _create_alert_manager(mode)
            # Serialize repeats of this block across Jarvis processes. Distinct
            # blocks must still create alerts during normal inline speech.
            lock_path = f"{manager.db.db_path}.prompt-guard-alert.{dedupe_digest}.lock"
            with FileLock(lock_path, timeout=0, mode=0o600):
                existing = _recent_alert(manager, dedupe_key, cooldown)
                if existing is not None:
                    return {"alert_id": existing, "duplicate_suppressed": True}
                description = (
                    f"Prompt Guard withheld content from {source_name} in {mode} mode. "
                    f"Classifier score {score:.3f}; block threshold {block_threshold:.3f}. "
                    "This is a classifier detection, not evidence of a successful attack."
                )
                if "incident_id" in metadata:
                    description += f" Private incident: {metadata['incident_id']}."
                alert_id = manager.create_alert(
                    title=_ALERT_TITLE,
                    description=description, source="prompt_guard", severity="high",
                    metadata=metadata, speak_immediately=True,
                )
                if type(alert_id) is not int or alert_id == 0:
                    return None
            return {"alert_id": abs(alert_id), "duplicate_suppressed": alert_id < 0}
    except Exception:
        # Do not log provider exceptions, source text, URLs, or arbitrary fields.
        _log_unavailable("alert")
        return None
    finally:
        if manager is not None:
            try:
                manager.db.close()
            except Exception:
                pass
