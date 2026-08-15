#!/usr/bin/env python3
"""Small client for GPU Hot REST and WebSocket snapshots."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import socket
import ssl
import struct
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import ProxyHandler, Request, build_opener


class GPUHotError(RuntimeError):
    """Raised when GPU Hot cannot return a usable snapshot."""


def normalize_base_url(value: str) -> str:
    """Validate and normalize a GPU Hot dashboard URL."""
    raw = str(value or "").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise GPUHotError("GPU Hot URL must be an http:// or https:// URL")
    if parsed.username or parsed.password:
        raise GPUHotError("GPU Hot URL must not contain embedded credentials")
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def websocket_url(base_url: str) -> str:
    """Return the raw GPU Hot WebSocket endpoint for a dashboard URL."""
    parsed = urlparse(normalize_base_url(base_url))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    base_path = parsed.path.rstrip("/")
    return urlunparse((scheme, parsed.netloc, f"{base_path}/socket.io/", "", "", ""))


def dashboard_url(base_url: str) -> str:
    """Return a normalized dashboard URL."""
    return f"{normalize_base_url(base_url)}/"


def _number(value: Any) -> float | None:
    if value in (None, "", "N/A", "[N/A]"):
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _gpu_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        rows = list(value.values())
    elif isinstance(value, list):
        rows = value
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def normalize_gpu(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep practical GPU fields and calculate VRAM capacity usage."""
    memory_used = _number(raw.get("memory_used"))
    memory_total = _number(raw.get("memory_total"))
    memory_free = _number(raw.get("memory_free"))
    capacity_percent = None
    if memory_used is not None and memory_total and memory_total > 0:
        capacity_percent = round((memory_used / memory_total) * 100.0, 1)

    return {
        "index": str(raw.get("index", "")),
        "name": str(raw.get("name") or "Unknown GPU"),
        "uuid": raw.get("uuid"),
        "utilization_percent": _number(raw.get("utilization")),
        # GPU Hot's memory_utilization is memory-controller activity, not
        # allocated VRAM capacity. Keep both values explicitly named.
        "memory_bandwidth_utilization_percent": _number(raw.get("memory_utilization")),
        "vram_used_mib": memory_used,
        "vram_total_mib": memory_total,
        "vram_free_mib": memory_free,
        "vram_capacity_percent": capacity_percent,
        "temperature_c": _number(raw.get("temperature")),
        "power_draw_w": _number(raw.get("power_draw")),
        "power_limit_w": _number(raw.get("power_limit")),
        "performance_state": raw.get("performance_state"),
        "encoder_utilization_percent": _number(raw.get("encoder_utilization")),
        "decoder_utilization_percent": _number(raw.get("decoder_utilization")),
        "driver_version": raw.get("driver_version"),
        "timestamp": raw.get("timestamp"),
    }


def normalize_process(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "pid": _integer(raw.get("pid")),
        "name": str(raw.get("name") or "unknown"),
        "gpu_index": str(raw.get("gpu_id", "")),
        "gpu_uuid": raw.get("gpu_uuid"),
        "vram_mib": _number(raw.get("memory")),
    }


def normalize_system(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    return {
        "cpu_percent": _number(raw.get("cpu_percent")),
        "cpu_count": _integer(raw.get("cpu_count")),
        "cpu_frequency_mhz": _number(raw.get("cpu_freq_current")),
        "load_average_1m": _number(raw.get("load_avg_1")),
        "load_average_5m": _number(raw.get("load_avg_5")),
        "load_average_15m": _number(raw.get("load_avg_15")),
        "ram_percent": _number(raw.get("memory_percent")),
        "ram_used_gb": _number(raw.get("memory_used_gb")),
        "ram_total_gb": _number(raw.get("memory_total_gb")),
        "ram_available_gb": _number(raw.get("memory_available_gb")),
        "swap_percent": _number(raw.get("swap_percent")),
        "network_bytes_sent": _integer(raw.get("net_bytes_sent")),
        "network_bytes_received": _integer(raw.get("net_bytes_recv")),
        "disk_read_bytes": _integer(raw.get("disk_read_bytes")),
        "disk_write_bytes": _integer(raw.get("disk_write_bytes")),
        "timestamp": raw.get("timestamp"),
    }


def normalize_snapshot(
    raw: dict[str, Any],
    *,
    base_url: str,
    transport: str,
    max_processes: int = 10,
) -> dict[str, Any]:
    """Normalize the two GPU Hot payload shapes into one stable contract."""
    gpus = [normalize_gpu(row) for row in _gpu_rows(raw.get("gpus", raw))]
    if not gpus:
        raise GPUHotError("GPU Hot returned no GPU metrics")

    processes_raw = raw.get("processes") if isinstance(raw, dict) else None
    processes = []
    if isinstance(processes_raw, list):
        processes = [normalize_process(row) for row in processes_raw if isinstance(row, dict)]
        processes.sort(key=lambda row: row.get("vram_mib") or 0, reverse=True)

    system = normalize_system(raw.get("system")) if isinstance(raw, dict) else None
    timestamp = next((gpu.get("timestamp") for gpu in gpus if gpu.get("timestamp")), None)
    if system and system.get("timestamp"):
        timestamp = system["timestamp"]

    return {
        "source": "gpu-hot",
        "transport": transport,
        "dashboard_url": dashboard_url(base_url),
        "mode": raw.get("mode") if isinstance(raw, dict) else None,
        "node_name": raw.get("node_name") if isinstance(raw, dict) else None,
        "timestamp": timestamp,
        "gpu_count": len(gpus),
        "gpus": gpus,
        "process_count": len(processes),
        "processes": processes[: max(0, max_processes)],
        "processes_truncated": len(processes) > max(0, max_processes),
        "system": system,
    }


def fetch_rest_snapshot(base_url: str, *, timeout: float = 8.0) -> dict[str, Any]:
    """Fetch GPU metrics from the REST snapshot endpoint."""
    normalized = normalize_base_url(base_url)
    request = Request(
        f"{normalized}/api/gpu-data",
        headers={"Accept": "application/json", "User-Agent": "Jarvis-GPU-Hot/1.0"},
    )
    try:
        # GPU Hot is normally a private-LAN service. Never send its address to
        # a configured outbound proxy.
        with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise GPUHotError(f"GPU Hot REST request failed: {exc}") from exc
    if not isinstance(payload, (dict, list)):
        raise GPUHotError("GPU Hot REST response was not an object or list")
    raw = payload if isinstance(payload, dict) else {"gpus": payload}
    return normalize_snapshot(raw, base_url=normalized, transport="rest", max_processes=0)


def fetch_websocket_snapshot(
    base_url: str,
    *,
    timeout: float = 8.0,
    max_processes: int = 10,
) -> dict[str, Any]:
    """Read one full GPU/host/process snapshot, then close the connection."""
    normalized = normalize_base_url(base_url)
    try:
        payload = json.loads(_receive_websocket_text(websocket_url(normalized), timeout=timeout))
    except Exception as exc:
        raise GPUHotError(f"GPU Hot WebSocket request failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise GPUHotError("GPU Hot WebSocket response was not an object")
    return normalize_snapshot(
        payload,
        base_url=normalized,
        transport="websocket",
        max_processes=max_processes,
    )


def _recv_exact(connection: socket.socket, size: int, buffered: bytearray) -> bytes:
    while len(buffered) < size:
        chunk = connection.recv(max(4096, size - len(buffered)))
        if not chunk:
            raise ConnectionError("WebSocket closed before a complete frame arrived")
        buffered.extend(chunk)
    result = bytes(buffered[:size])
    del buffered[:size]
    return result


def _send_masked_frame(connection: socket.socket, opcode: int, payload: bytes) -> None:
    """Send a small RFC 6455 client control frame (clients must mask)."""
    if len(payload) >= 126:
        raise ValueError("WebSocket control payload is too large")
    mask = secrets.token_bytes(4)
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    connection.sendall(bytes((0x80 | opcode, 0x80 | len(payload))) + mask + masked)


def _receive_websocket_text(url: str, *, timeout: float) -> str:
    """Receive one raw RFC 6455 text message without a third-party dependency."""
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise ValueError("WebSocket URL is missing a host")
    secure = parsed.scheme == "wss"
    port = parsed.port or (443 if secure else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    connection = socket.create_connection((host, port), timeout=timeout)
    try:
        connection.settimeout(timeout)
        if secure:
            context = ssl.create_default_context()
            connection = context.wrap_socket(connection, server_hostname=host)

        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        host_header = parsed.netloc
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "User-Agent: Jarvis-GPU-Hot/1.0\r\n\r\n"
        )
        connection.sendall(request.encode("ascii"))

        buffered = bytearray()
        while b"\r\n\r\n" not in buffered:
            chunk = connection.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket closed during the HTTP upgrade")
            buffered.extend(chunk)
            if len(buffered) > 65536:
                raise ValueError("WebSocket upgrade headers were too large")
        header_bytes, remainder = bytes(buffered).split(b"\r\n\r\n", 1)
        buffered = bytearray(remainder)
        header_lines = header_bytes.decode("iso-8859-1").split("\r\n")
        if not header_lines or " 101 " not in f" {header_lines[0]} ":
            raise ConnectionError(f"WebSocket upgrade failed: {header_lines[0] if header_lines else 'empty response'}")
        headers = {}
        for line in header_lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
        expected_accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        if headers.get("sec-websocket-accept") != expected_accept:
            raise ConnectionError("WebSocket upgrade returned an invalid accept key")

        fragments = bytearray()
        message_started = False
        while True:
            first, second = _recv_exact(connection, 2, buffered)
            final = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", _recv_exact(connection, 2, buffered))[0]
            elif length == 127:
                length = struct.unpack("!Q", _recv_exact(connection, 8, buffered))[0]
            if length > 4 * 1024 * 1024:
                raise ValueError("WebSocket snapshot exceeded 4 MiB")
            mask = _recv_exact(connection, 4, buffered) if masked else b""
            payload = _recv_exact(connection, length, buffered)
            if masked:
                payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))

            if opcode == 0x9:  # ping
                _send_masked_frame(connection, 0xA, payload)
                continue
            if opcode == 0x8:  # close
                raise ConnectionError("WebSocket closed before sending a snapshot")
            if opcode == 0x1:
                fragments = bytearray(payload)
                message_started = True
            elif opcode == 0x0 and message_started:
                fragments.extend(payload)
            else:
                continue
            if final:
                return fragments.decode("utf-8")
    finally:
        connection.close()


def fetch_snapshot(
    base_url: str,
    *,
    timeout: float = 8.0,
    max_processes: int = 10,
    prefer_websocket: bool = True,
) -> dict[str, Any]:
    """Fetch a full snapshot, with a GPU-only REST fallback."""
    warning = None
    if prefer_websocket:
        try:
            return fetch_websocket_snapshot(
                base_url,
                timeout=timeout,
                max_processes=max_processes,
            )
        except GPUHotError as exc:
            warning = str(exc)

    snapshot = fetch_rest_snapshot(base_url, timeout=timeout)
    if warning:
        snapshot["warnings"] = [
            "Full host/process snapshot was unavailable; returned GPU-only REST metrics.",
            warning,
        ]
    return snapshot
