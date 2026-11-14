"""Validated foreground adapters for durable watch state; never delivers messages."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lib.stash_helper import get_stash_dir

from .normalization import SHARED_RADAR_KEYS

MAX_REQUEST_BYTES = 256 * 1024
MAX_LEGACY_BYTES = 8 * 1024 * 1024
MAX_RADAR_EXCLUSIONS = 500
WatchMode = Literal["cloud", "local"]


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class KeyArguments(Arguments):
    key: str = Field(min_length=1, max_length=160)


class PageArguments(Arguments):
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0, le=1_000_000_000)


class KeyPageArguments(PageArguments):
    key: str = Field(min_length=1, max_length=160)


class RegisterArguments(KeyArguments):
    definition: dict[str, Any]


class AdminRegisterArguments(RegisterArguments):
    owner: str | None = Field(default=None, min_length=1, max_length=200)


class CompareArguments(KeyArguments):
    records: list[dict[str, Any]] = Field(max_length=1000)
    complete: bool | None = None
    dry_run: bool = False
    request_id: str | None = Field(default=None, min_length=1, max_length=200)


class CommitArguments(KeyArguments):
    run_id: str = Field(min_length=1, max_length=200)


class IntentArguments(KeyArguments):
    event_id: str = Field(min_length=1, max_length=200)
    channel: str = Field(min_length=1, max_length=40)
    destination: str = Field(min_length=1, max_length=1024)


class ClaimArguments(IntentArguments):
    lease_seconds: int = Field(default=60, ge=1, le=3600)


class AckArguments(IntentArguments):
    success: bool = True
    receipt: dict[str, Any] | None = None
    error: str | None = Field(default=None, max_length=1000)
    claim_token: str | None = Field(default=None, min_length=1, max_length=200)


class PendingArguments(PageArguments):
    key: str | None = Field(default=None, min_length=1, max_length=160)
    channel: str | None = Field(default=None, min_length=1, max_length=40)
    destination: str | None = Field(default=None, min_length=1, max_length=1024)
    include_parked: bool = False


class HealthArguments(Arguments):
    key: str | None = Field(default=None, min_length=1, max_length=160)


class HandledArguments(KeyPageArguments):
    channel: str | None = Field(default=None, min_length=1, max_length=40)


class MuteArguments(KeyArguments):
    until: int | float | None = Field(default=None, ge=0)
    seconds: int | float | None = Field(default=None, gt=0, le=31_536_000)


class DeleteArguments(KeyArguments):
    delete_handled: bool = False


class CleanupArguments(KeyArguments):
    limit: int = Field(default=100, ge=1, le=1000)


class RecordErrorArguments(KeyArguments):
    error_code: str = Field(default="source_fetch_failed", pattern=r"^[a-z][a-z0-9_]{0,63}$")


class DeliveryArguments(KeyArguments):
    record: dict[str, Any]
    channel: str = Field(min_length=1, max_length=40)
    destination: str = Field(min_length=1, max_length=1024)
    receipt: dict[str, Any]


ACTION_MODELS: dict[str, type[Arguments]] = {
    "register": RegisterArguments,
    "compare": CompareArguments,
    "commit": CommitArguments,
    "discard": CommitArguments,
    "claim": ClaimArguments,
    "ack": AckArguments,
    "pending": PendingArguments,
    "history": KeyPageArguments,
    "list": PageArguments,
    "inspect": KeyArguments,
    "reset": KeyArguments,
    "mute": MuteArguments,
    "delete": DeleteArguments,
    "health": HealthArguments,
    "handled": HandledArguments,
    "record_delivery": DeliveryArguments,
    "radar_history": KeyArguments,
    "cleanup": CleanupArguments,
    "record_error": RecordErrorArguments,
    "retry": IntentArguments,
}


def validate_arguments(arguments: Any, *, admin: bool = False) -> tuple[str, dict[str, Any]]:
    """Reject unknown authority/path fields and oversized or non-finite JSON."""
    if not isinstance(arguments, dict):
        raise ValueError("Watch state input must be an object.")
    try:
        size = len(json.dumps(arguments, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError, RecursionError):
        raise ValueError("Watch state input must contain finite JSON data.") from None
    if size > MAX_REQUEST_BYTES:
        raise ValueError("Watch state input exceeds the 256 KiB limit.")
    action = arguments.get("action")
    if not isinstance(action, str) or action not in ACTION_MODELS:
        raise ValueError("Unknown watch state action.")
    model = AdminRegisterArguments if admin and action == "register" else ACTION_MODELS[action]
    try:
        parsed = model.model_validate(
            {key: value for key, value in arguments.items() if key != "action"}
        )
    except ValidationError as exc:
        fields = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
        raise ValueError("Invalid watch state arguments: " + ", ".join(fields) + ".") from None
    return action, parsed.model_dump(exclude_none=True)


def _legacy_radar_ids(key: str) -> list[str]:
    root = get_stash_dir().resolve()
    path = root / f"space_{key}" / "meta.json"
    if not path.resolve().is_relative_to(root):
        raise ValueError("Legacy radar history is outside the configured Stash.")
    if not path.exists():
        return []
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_LEGACY_BYTES + 1)
        if len(raw) > MAX_LEGACY_BYTES:
            raise ValueError("Legacy radar history exceeds the migration size limit.")
        metadata = json.loads(raw)
        if not isinstance(metadata, dict) or not isinstance(metadata.get("files"), list):
            raise ValueError("Invalid legacy radar history.")
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("Legacy radar history could not be read safely.") from None
    ids = set()
    for item in metadata["files"]:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        is_json = item.get("kind") == "json" or item.get("mime_type") == "application/json"
        if isinstance(name, str) and re.fullmatch(r"[0-9]{1,20}", name) and is_json:
            ids.add(name)
    return sorted(ids, key=lambda value: (int(value), value))


def _radar_history(store: Any, key: str, authority: Any) -> dict[str, Any]:
    from lib.watch_state import AuthorityError, NotFoundError

    if key not in SHARED_RADAR_KEYS or authority.writer != f"workflow:{key}":
        raise AuthorityError("Radar history requires its matching trusted workflow.")
    # Read and validate before creating a watch: broken legacy data must fail closed.
    ids = _legacy_radar_ids(key)
    try:
        store.inspect(key)
    except NotFoundError:
        store.register(
            key,
            {
                "id_field": "tmdb_id",
                "compare_fields": [],
                "channels": [],
                "stale_after_seconds": 0,
            },
            authority,
        )
    imported = 0
    for start in range(0, len(ids), 1000):
        batch = [{"tmdb_id": value} for value in ids[start : start + 1000]]
        store.import_handled(key, batch, authority, "email", "legacy")
        imported += len(batch)
    handled: set[str] = set()
    offset = 0
    while True:
        page = store.handled(key, "email", limit=1000, offset=offset)
        handled.update(page["ids"])
        if len(handled) > MAX_RADAR_EXCLUSIONS:
            store.record_error(key, authority, "radar_discovery_limit_exceeded")
            raise ValueError(
                "Radar discovery accepts at most 500 excluded IDs; handled history was preserved. "
                "No IDs were truncated or reset."
            )
        next_offset = page.get("next_offset")
        if next_offset is None:
            break
        if not isinstance(next_offset, int) or next_offset <= offset:
            raise ValueError("Radar handled history pagination is invalid.")
        offset = next_offset
    store.record_check_success(key, authority)
    return {"key": key, "handled_ids": sorted(handled), "legacy_ids_reviewed": imported}


def _validate_delivery_receipt(key: str, parameters: dict[str, Any]) -> None:
    receipt = parameters["receipt"]
    if receipt.get("ok") is not True:
        raise ValueError("Completed delivery requires a successful standard receipt with ok=true.")
    if key not in SHARED_RADAR_KEYS:
        return
    record = parameters["record"]
    identifier = record.get("tmdb_id")
    if isinstance(identifier, bool) or not re.fullmatch(r"[0-9]{1,20}", str(identifier or "")):
        raise ValueError("Radar delivery requires a numeric TMDB ID.")
    data = receipt.get("data")
    if receipt.get("ok") is not True or not isinstance(data, dict) or data.get("status") != "sent":
        raise ValueError("Radar delivery requires a successful sent-email receipt.")
    recipients = data.get("to")
    recipients = recipients if isinstance(recipients, list) else [recipients]
    if parameters["channel"] != "email" or parameters["destination"] not in recipients:
        raise ValueError("Radar delivery destination must match its sent-email receipt.")


def dispatch(
    arguments: Any,
    *,
    project_root: Path,
    mode: str,
    authority: Any,
) -> dict[str, Any]:
    """Dispatch validated actions with server/executor-owned authority and paths."""
    from lib.watch_state import AuthorityError, Store

    if mode not in {"cloud", "local"}:
        raise ValueError("Watch state mode must be cloud or local.")
    action, parameters = validate_arguments(arguments, admin=authority.admin)
    if action == "retry" and not authority.admin:
        raise AuthorityError("Retrying parked deliveries requires API administrator authority.")
    key = parameters.get("key")
    scope = "shared" if key in SHARED_RADAR_KEYS else mode
    store = Store(project_root, scope)
    if action == "radar_history":
        data = _radar_history(store, parameters["key"], authority)
    elif action in {
        "register",
        "compare",
        "commit",
        "discard",
        "claim",
        "ack",
        "reset",
        "mute",
        "delete",
        "record_delivery",
        "cleanup",
        "record_error",
        "retry",
    }:
        if action == "record_delivery":
            _validate_delivery_receipt(key, parameters)
        data = getattr(store, action)(**parameters, authority=authority)
    else:
        data = getattr(store, action)(**parameters)
    data = {**data, "action": action, "mode": mode, "scope": scope}
    if action == "radar_history":
        speech = f"Read {len(data['handled_ids'])} previously emailed radar IDs."
    elif action == "compare":
        speech = (
            "Watch comparison previewed."
            if parameters.get("dry_run")
            else "Watch comparison staged; baseline unchanged."
        )
    elif action == "record_delivery":
        speech = (
            "This record was already handled; its existing receipt was preserved."
            if data.get("already_handled")
            else "Recorded delivery in the per-record handled ledger; no message was sent."
        )
    elif action == "health":
        speech = f"Watch health: {data.get('stale_count', 0)} stale and {data.get('error_count', 0)} errors."
        if data.get("counts_complete") is False:
            speech += " Health counts are incomplete; inspect the remaining watches."
    elif action == "claim":
        speech = (
            "Delivery claimed; retain its token and acknowledge the actual delivery result."
            if data.get("claimed") is True
            else f"Delivery was not claimed; its status is {data.get('status', 'unknown')}. Do not send."
        )
    elif action == "ack":
        speech = (
            "Delivery acknowledged as completed."
            if data.get("status") == "delivered"
            else f"Delivery did not complete; its status is {data.get('status', 'unknown')}."
        )
    else:
        speech = f"Watch state {action.replace('_', ' ')} complete."
    return {"ok": True, "speech": speech, "data": data}
