"""Optional browser-host-specific origins for links between the Jarvis UIs."""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from flask import Response, request


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "ui_urls.json"
SCRIPT_PATH = Path(__file__).resolve().parent / "static" / "ui-navigation.js"
SERVICES = frozenset({"web", "canvas", "memory", "intelligence", "docs"})
MAX_CONFIG_BYTES = 64 * 1024


def _hostname(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    value = value.removeprefix("[").removesuffix("]")
    try:
        return ipaddress.ip_address(value).compressed
    except ValueError:
        pass
    try:
        hostname = value.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    labels = hostname.split(".")
    if len(hostname) > 253 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        return None
    return hostname


def _origin(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 2048 or any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        or character in "\\?#" for character in value
    ):
        return None
    try:
        parsed = urlsplit(value)
        hostname = _hostname(parsed.hostname)
        port = parsed.port
    except ValueError:
        return None
    if (parsed.scheme not in {"http", "https"} or not hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or port == 0):
        return None
    authority = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and port != (443 if parsed.scheme == "https" else 80):
        authority += f":{port}"
    return f"{parsed.scheme}://{authority}"


def navigation_for_host(hostname: str, config_path: Path = CONFIG_PATH) -> dict[str, str]:
    """Read only this host's valid service origins; missing config keeps defaults."""
    hostname = _hostname(hostname)
    if not hostname:
        return {}
    try:
        with Path(config_path).open("rb") as source:
            raw = source.read(MAX_CONFIG_BYTES + 1)
        if len(raw) > MAX_CONFIG_BYTES:
            return {}
        config = json.loads(raw)
    except (OSError, ValueError, UnicodeError):
        return {}
    hosts = config.get("hosts") if isinstance(config, dict) else None
    if not isinstance(hosts, dict):
        return {}
    for configured_host, origins in hosts.items():
        if _hostname(configured_host) != hostname:
            continue
        if not isinstance(origins, dict):
            return {}
        result = {}
        for service in SERVICES:
            origin = _origin(origins.get(service))
            if origin:
                result[service] = origin
        return result
    return {}


def register_ui_navigation(app, config_path: Path | None = None) -> None:
    """Register a same-origin classic script; URL edits apply on the next load."""
    @app.get("/ui-navigation.js", endpoint="jarvis_ui_navigation")
    def ui_navigation_script():
        try:
            hostname = _hostname(urlsplit(f"//{request.host}").hostname) or ""
        except ValueError:
            hostname = ""
        configuration = {"hostname": hostname,
                         "urls": navigation_for_host(hostname, config_path or CONFIG_PATH)}
        encoded = json.dumps(configuration, ensure_ascii=True, separators=(",", ":"))
        # Keep the bootstrap safe if a consumer ever embeds this script inline.
        encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        body = f"window.__jarvisUINavigationConfig={encoded};\n{SCRIPT_PATH.read_text(encoding='utf-8')}"
        response = Response(body, mimetype="application/javascript")
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
