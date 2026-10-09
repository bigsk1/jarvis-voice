"""Lazy, sanitized ntfy diagnostics and explicit test publishing for Settings."""

import json
import os
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from filelock import FileLock, Timeout

from lib.ntfy_notifications import DeliveryError, NoRedirect, load_config, publish, validate_config

ROOT = Path(__file__).resolve().parents[3]
_health_lock = threading.Lock()
_health_cache = {}
TEST_COOLDOWN_SECONDS = 30


def _configuration():
    path = ROOT / "config" / "ntfy.json"
    if not path.exists():
        return None, "missing"
    try:
        config = load_config(path)
        if not config["enabled"]:
            try:
                validate_config({**config, "enabled": True})
                return config, "disabled"
            except ValueError:
                return None, "disabled"
        return config, "enabled"
    except Exception:
        return None, "invalid"


def _worker_status():
    path = ROOT / "logs" / "ntfy_notifications.status.json"
    try:
        with path.open() as stream:
            heartbeat = json.loads(stream.read(4097))
        stamp, interval = heartbeat["updated_at"], heartbeat["poll_seconds"]
        if (type(stamp) not in {int, float} or type(interval) is not int
                or not 5 <= interval <= 300 or heartbeat["mode"] not in {"cloud", "local"}
                or heartbeat["state"] not in {"ready", "disabled", "checking", "degraded", "stopped"}):
            raise ValueError()
        if not 0 <= time.time() - stamp <= max(45, interval * 3):
            return {"state": "stale", "mode": heartbeat["mode"]}
        return {"state": heartbeat["state"], "mode": heartbeat["mode"]}
    except Exception:
        return {"state": "unknown", "mode": None}


def _health(origin):
    with _health_lock:
        cached = _health_cache.get(origin)
        if cached and time.monotonic() < cached[0]:
            return cached[1]
        try:
            with urllib.request.build_opener(NoRedirect()).open(
                origin + "/v1/health", timeout=3
            ) as response:
                value = json.loads(response.read(4097))
                online = isinstance(value, dict) and value.get("healthy") is True
        except Exception:
            online = False
        _health_cache.clear()
        _health_cache[origin] = (time.monotonic() + 15, online)
        return online


def get_ntfy_status():
    config, state = _configuration()
    result = {"ok": True, "configuration": state, "enabled": state == "enabled",
              "configured": config is not None, "server_online": None,
              "worker": _worker_status(), "test_available": False, "categories": []}
    if config and state == "enabled":
        result["categories"] = [name for name in ("alerts", "reminders", "background_tasks")
                                if config[name]["enabled"]]
        result["server_online"] = _health(config["server_url"])
        result["test_available"] = bool(result["categories"])
    return result


def send_ntfy_test():
    """One user-triggered publish; no caller-controlled server, topic or content."""
    config, state = _configuration()
    if config is None or state != "enabled":
        return {"ok": False, "error": "Enable a valid private ntfy configuration first."}, 409
    category = next((name for name in ("alerts", "reminders", "background_tasks")
                     if config[name]["enabled"]), None)
    if category is None:
        return {"ok": False, "error": "Enable a notification category first."}, 409
    folder = ROOT / "data"
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / "ntfy_notifications.db.test.json"
    lock = FileLock(folder / "ntfy_notifications.db.test.lock", mode=0o600)
    try:
        with lock.acquire(timeout=0):
            now = time.time()
            try:
                last = json.loads(marker.read_text())["attempted_at"]
                if now - last < TEST_COOLDOWN_SECONDS:
                    return {"ok": False, "error": "Wait 30 seconds before sending another test."}, 429
            except (OSError, ValueError, TypeError, KeyError):
                pass
            fd, temporary = tempfile.mkstemp(prefix="ntfy_notifications.db.test-", dir=folder)
            try:
                with os.fdopen(fd, "w") as stream:
                    json.dump({"attempted_at": now}, stream)
                os.replace(temporary, marker)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            try:
                # A test uses an enabled topic the phone already subscribes to.
                publish({**config, "request_timeout_seconds": 5}, {
                                 "topic": config[category]["topic"], "priority": 3,
                                 "title": "Jarvis notification test",
                                 "message": "Jarvis can publish to ntfy. If you see this on your phone, phone delivery is working."})
            except DeliveryError:
                return {"ok": False, "error": "ntfy did not confirm the test. Check the server and publisher credentials."}, 502
    except Timeout:
        return {"ok": False, "error": "A notification test is already in progress."}, 429
    except OSError:
        return {"ok": False, "error": "The notification test could not be recorded."}, 503
    return {"ok": True, "message": "Test accepted by ntfy. Check your phone for ‘Jarvis notification test’."}, 200
