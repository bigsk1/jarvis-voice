"""Bounded, read-only Tailscale diagnostics for the Web settings page."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time


CACHE_SECONDS = 15
COMMAND_TIMEOUT_SECONDS = 2
MAX_RESPONSE_BYTES = 256 * 1024
MAX_CONFIG_BLOCKS = 64
BACKEND_STATES = frozenset({
    "NoState", "InUseOtherUser", "NeedsLogin", "NeedsMachineAuth", "Stopped", "Starting", "Running",
})
_cache = None
_cache_expires = 0.0
_cache_lock = threading.Lock()


def _deployment():
    if (os.environ.get("JARVIS_DEPLOYMENT", "").strip().lower() == "docker"
            or Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()):
        return "docker"
    return "native"


def _hostname(value):
    if not isinstance(value, str) or not value or len(value) > 254:
        return None
    value = value.rstrip(".").lower()
    if (value.startswith("[") or value.endswith("]")) and not (value.startswith("[") and value.endswith("]")):
        return None
    try:
        return ipaddress.ip_address(value.strip("[]")).compressed
    except ValueError:
        pass
    if all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
           for label in value.split(".")):
        return value
    return None


def _host_port(value):
    if not isinstance(value, str):
        return None
    hostname, separator, raw_port = value.rpartition(":")
    if ":" in hostname and not (hostname.startswith("[") and hostname.endswith("]")):
        return None
    hostname = _hostname(hostname)
    if not separator or not hostname or not re.fullmatch(r"[0-9]{1,5}", raw_port):
        return None
    port = int(raw_port)
    return (hostname, port) if 1 <= port <= 65535 else None


def _read_json(command):
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=COMMAND_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except OSError:
        return None, "unavailable"
    if result.returncode != 0:
        return None, "unavailable"
    if not isinstance(result.stdout, bytes) or len(result.stdout) > MAX_RESPONSE_BYTES:
        return None, "invalid_response"
    try:
        value = json.loads(result.stdout)
    except (ValueError, UnicodeError, RecursionError):
        return None, "invalid_response"
    if value is not None and not isinstance(value, dict):
        return None, "invalid_response"
    return value, None


def parse_serve_status(configuration):
    """Reduce HTTPS listeners without returning proxy targets, file paths or text.

    Funnel grants apply to a hostname/port across background and foreground
    configs. Any malformed exposure metadata prevents a private classification.
    """
    if configuration is None or configuration == {}:
        return {"state": "not_configured", "listeners": [], "error_code": None}
    pending = [(configuration, 0)]
    listeners = set()
    funnel = set()
    malformed = False
    configured = False
    visited = 0
    while pending:
        block, depth = pending.pop()
        visited += 1
        if visited > MAX_CONFIG_BLOCKS or depth > 4:
            malformed = True
            break
        if not isinstance(block, dict):
            malformed = True
            continue
        if set(block) - {"TCP", "Web", "AllowFunnel", "Foreground", "Services"}:
            malformed = True
        maps = {}
        for key in ("TCP", "Web", "AllowFunnel", "Foreground", "Services"):
            value = block.get(key, {})
            if not isinstance(value, dict):
                malformed = True
                value = {}
            maps[key] = value
        configured = configured or bool(maps["TCP"] or maps["Web"] or maps["Services"])
        for endpoint, allowed in maps["AllowFunnel"].items():
            target = _host_port(endpoint)
            if not target or type(allowed) is not bool:
                malformed = True
            elif allowed:
                funnel.add(target)
        pending.extend((value, depth + 1) for value in maps["Foreground"].values())
        # Services have their own TCP/Web configuration. They do not introduce
        # a separate Funnel policy; the hostname/port grants above still govern.
        pending.extend((value, depth + 1) for value in maps["Services"].values())
        for raw_port, handler in maps["TCP"].items():
            if (not isinstance(raw_port, str) or not re.fullmatch(r"[0-9]{1,5}", raw_port)
                    or not 1 <= int(raw_port) <= 65535 or not isinstance(handler, dict)):
                malformed = True
                continue
            if (set(handler) - {"HTTPS", "HTTP", "TCPForward", "TerminateTLS", "ProxyProtocol"}
                    or any(key in handler and type(handler[key]) is not bool for key in ("HTTPS", "HTTP"))
                    or any(key in handler and not isinstance(handler[key], str) for key in ("TCPForward", "TerminateTLS"))
                    or "ProxyProtocol" in handler and type(handler["ProxyProtocol"]) is not int
                    or sum(bool(handler.get(key)) for key in ("HTTPS", "HTTP", "TCPForward")) != 1):
                malformed = True
        for endpoint, web in maps["Web"].items():
            target = _host_port(endpoint)
            handlers = web.get("Handlers") if isinstance(web, dict) else None
            if not target or not isinstance(handlers, dict) or not handlers:
                malformed = True
                continue
            for path, handler in handlers.items():
                if not isinstance(path, str) or not path.startswith("/") or not isinstance(handler, dict):
                    malformed = True
                    continue
                targets = ("Path", "Proxy", "Text", "Redirect")
                if (set(handler) - {*targets, "AcceptAppCaps"}
                        or any(key in handler and not isinstance(handler[key], str) for key in targets)
                        or sum(bool(handler.get(key)) for key in targets) != 1
                        or "AcceptAppCaps" in handler and (
                            not isinstance(handler["AcceptAppCaps"], list)
                            or any(not isinstance(capability, str) for capability in handler["AcceptAppCaps"]))):
                    malformed = True
            tcp = maps["TCP"].get(str(target[1]))
            if not isinstance(tcp, dict):
                malformed = True
                continue
            if tcp.get("HTTPS") is True:
                listeners.add(target)
            elif tcp.get("HTTP") is not True:
                malformed = True
    return {
        "state": "unavailable" if malformed else "configured" if configured else "not_configured",
        "listeners": [
            {"hostname": hostname, "port": port, "https": True,
             "funnel": True if (hostname, port) in funnel else None if malformed else False}
            for hostname, port in sorted(listeners)
        ],
        "error_code": "invalid_serve_status" if malformed else None,
    }


def _collect_status():
    deployment = _deployment()
    result = {
        "ok": True, "deployment": deployment, "state": "unavailable", "backend_state": None,
        "hostname": None, "online": None, "error_code": None,
        "serve": {"state": "unavailable", "listeners": [], "error_code": "status_unavailable"},
        "checked_at": datetime.now(timezone.utc).isoformat(), "cached": False,
    }
    executable = shutil.which("tailscale")
    if not executable:
        result["state"] = "unavailable" if deployment == "docker" else "not_installed"
        result["error_code"] = "host_status_unavailable" if deployment == "docker" else "cli_not_found"
        return result
    status, error = _read_json([executable, "status", "--json", "--peers=false"])
    if (error or not isinstance(status, dict) or not isinstance(status.get("BackendState"), str)
            or status["BackendState"] not in BACKEND_STATES):
        result["error_code"] = f"status_{error}" if error else "invalid_status_response"
        return result
    result["backend_state"] = status["BackendState"]
    result["state"] = "running" if status["BackendState"] == "Running" else "stopped"
    own = status.get("Self")
    if isinstance(own, dict):
        result["hostname"] = _hostname(own.get("DNSName"))
        result["online"] = own.get("Online") if type(own.get("Online")) is bool else None
    configuration, error = _read_json([executable, "serve", "status", "--json"])
    if error:
        result["serve"]["error_code"] = f"serve_{error}"
    else:
        result["serve"] = parse_serve_status(configuration)
    return result


def get_tailscale_status():
    """Coalesce all checks, including refresh clicks, for fifteen seconds.

    The lock covers collection so concurrent requests start only one pair of
    short-lived commands. Returned copies cannot mutate the cached observation.
    """
    global _cache, _cache_expires
    with _cache_lock:
        if _cache is not None and time.monotonic() < _cache_expires:
            return {**copy.deepcopy(_cache), "cached": True}
        result = _collect_status()
        _cache = copy.deepcopy(result)
        _cache_expires = time.monotonic() + CACHE_SECONDS
        return result
