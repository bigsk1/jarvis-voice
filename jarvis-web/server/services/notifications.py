"""Private notification settings and read-only, mode-scoped delivery history."""

import json
import os
import sqlite3
import tempfile
from pathlib import Path

from filelock import FileLock, Timeout

from lib.ntfy_notifications import load_config, validate_config

ROOT = Path(__file__).resolve().parents[3]
CATEGORIES = ("alerts", "reminders", "background_tasks", "notifications")


class NotificationSettingsError(Exception):
    """A safe error that contains no private configuration values."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _configuration() -> tuple[dict, dict]:
    path = ROOT / "config" / "ntfy.json"
    if not path.is_file():
        raise NotificationSettingsError("Configure ntfy before changing its settings.", 409)
    try:
        config = load_config(path)
        raw = json.loads(path.read_text())
        # Even a disabled channel needs valid existing credentials before the
        # UI can offer an enable switch. Validation never contacts the server.
        validate_config({**config, "enabled": True})
        return raw, config
    except (OSError, ValueError, TypeError):
        raise NotificationSettingsError(
            "Check the private ntfy configuration and its file permissions.", 409
        ) from None


def get_channels() -> dict:
    """Return switches only, without server addresses, topics, or credentials."""
    path = ROOT / "config" / "ntfy.json"
    try:
        _, config = _configuration()
    except NotificationSettingsError:
        return {"ok": True, "configured": False, "editable": False, "enabled": False,
                "configuration": "invalid" if path.exists() else "missing",
                "categories": {}, "channels": [{"id": "ntfy", "enabled": False}]}
    read_only = not os.access(path, os.W_OK) or not os.access(path.parent, os.W_OK)
    return {"ok": True, "configured": True, "editable": not read_only,
            "read_only": read_only, "enabled": config["enabled"],
            "configuration": "enabled" if config["enabled"] else "disabled",
            "categories": {name: config[name]["enabled"] for name in CATEGORIES},
            "channels": [{"id": "ntfy", "enabled": config["enabled"]}]}


def update_channels(changes: dict) -> dict:
    """Atomically change explicitly supplied switches in an existing config."""
    if not isinstance(changes, dict) or not changes or set(changes) - {"enabled", "categories"}:
        raise NotificationSettingsError("Only enabled and category switches can be changed.")
    if "enabled" in changes and type(changes["enabled"]) is not bool:
        raise NotificationSettingsError("Enabled must be a boolean.")
    categories = changes.get("categories", {})
    if (not isinstance(categories, dict) or set(categories) - set(CATEGORIES)
            or any(type(value) is not bool for value in categories.values())
            or ("categories" in changes and not categories)):
        raise NotificationSettingsError("Use boolean switches for known notification categories.")
    path = ROOT / "config" / "ntfy.json"
    if not path.is_file():
        raise NotificationSettingsError("Configure ntfy before changing its settings.", 409)
    if not os.access(path, os.W_OK) or not os.access(path.parent, os.W_OK):
        raise NotificationSettingsError(
            "Notification settings are read-only. Edit the private configuration on the host.", 503
        )
    temporary = None
    try:
        with FileLock(str(path) + ".lock", mode=0o600).acquire(timeout=1):
            raw, _ = _configuration()
            if "enabled" in changes:
                raw["enabled"] = changes["enabled"]
            for name, enabled in categories.items():
                raw[name] = {**raw.get(name, {}), "enabled": enabled}
            validate_config(raw)
            descriptor, temporary = tempfile.mkstemp(prefix=".ntfy-", dir=path.parent)
            with os.fdopen(descriptor, "w") as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(raw, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
            return get_channels()
    except Timeout:
        raise NotificationSettingsError("Notification settings are busy. Try again.", 409) from None
    except (OSError, ValueError, TypeError):
        raise NotificationSettingsError(
            "Notification settings could not be saved. For read-only deployments, edit the config on the host.",
            503,
        ) from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def get_history(mode: str, *, source_type: str | None = None, source: str | None = None,
                channel: str | None = None,
                state: str | None = None, limit: int = 25, offset: int = 0) -> dict:
    """Read receipts without running a worker, publishing, or opening MemoryDB."""
    from lib.notifications import NotificationStore

    if mode not in {"cloud", "local"}:
        raise NotificationSettingsError("Mode must be cloud or local.")
    if source_type is not None and source_type not in CATEGORIES:
        raise NotificationSettingsError("Unknown notification source category.")
    if (type(limit) is not int or not 1 <= limit <= 100
            or type(offset) is not int or not 0 <= offset <= 1_000_000):
        raise NotificationSettingsError("Use a limit from 1 to 100 and an offset from 0 to 1000000.")
    for value in (source, channel, state):
        if value is not None and (not isinstance(value, str) or len(value) > 80
                                  or any(ord(character) < 32 for character in value)):
            raise NotificationSettingsError("Invalid notification history filter.")
    if channel not in {None, "ntfy"} or state not in {
        None, "pending", "delivered", "failed", "suppressed", "unavailable", "saved"
    }:
        raise NotificationSettingsError("Invalid notification channel or delivery state.")
    try:
        return {"ok": True, **NotificationStore(ROOT, mode).list_history(
            source_type=source_type, source=source, channel=channel, state=state,
            limit=limit, offset=offset
        )}
    except ValueError:
        raise NotificationSettingsError("Invalid notification history parameters.") from None
    except (OSError, sqlite3.Error):
        raise NotificationSettingsError("Notification history is unavailable.", 503) from None
