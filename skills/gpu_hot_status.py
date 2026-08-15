#!/usr/bin/env python3
"""Return an on-demand GPU Hot GPU and host status snapshot."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from config_loader import get_config_value, load_config, load_env_file  # noqa: E402
from gpu_hot_client import GPUHotError, fetch_snapshot  # noqa: E402


def _configured_url(arguments: dict[str, Any]) -> str:
    explicit = str(arguments.get("base_url") or "").strip()
    if explicit:
        return explicit

    configured = str(get_config_value("GPU_HOT_URL", "") or "").strip()
    if configured:
        return configured

    # The autonomous monitor has an intentionally ignored config file. Reuse
    # its URL so operators only need one private-LAN configuration source.
    service_config = PROJECT_ROOT / "services" / "gpu-hot-monitor" / "config.env"
    if service_config.exists():
        configured = str(load_env_file(service_config).get("GPU_HOT_URL", "")).strip()
    return configured


def _percent(value: Any) -> str:
    return "unknown" if value is None else f"{round(float(value))} percent"


def _speech(snapshot: dict[str, Any], host_label: str) -> str:
    gpu = snapshot["gpus"][0]
    parts = [
        f"{host_label}'s {gpu.get('name') or 'GPU'} is at "
        f"{_percent(gpu.get('utilization_percent'))} utilization",
    ]
    if gpu.get("temperature_c") is not None:
        parts.append(f"{round(float(gpu['temperature_c']))} degrees Celsius")
    if gpu.get("vram_capacity_percent") is not None:
        parts.append(f"{_percent(gpu['vram_capacity_percent'])} VRAM used")

    system = snapshot.get("system") or {}
    if system.get("cpu_percent") is not None:
        parts.append(f"host CPU {_percent(system['cpu_percent'])}")
    if system.get("ram_percent") is not None:
        parts.append(f"host RAM {_percent(system['ram_percent'])}")

    speech = ", ".join(parts) + "."
    if snapshot.get("gpu_count", 0) > 1:
        speech += f" {snapshot['gpu_count']} GPUs are reporting."
    if snapshot.get("transport") == "rest":
        speech += " Host and process details were unavailable."
    return speech


def run(arguments: dict[str, Any]) -> dict[str, Any]:
    """Fetch and format one status snapshot."""
    base_url = _configured_url(arguments)
    if not base_url:
        raise GPUHotError(
            "GPU Hot is not configured. Set GPU_HOT_URL or provide base_url."
        )

    timeout = min(max(float(arguments.get("timeout_seconds", 8)), 1.0), 15.0)
    max_processes = min(max(int(arguments.get("max_processes", 10)), 0), 25)
    host_label = str(
        arguments.get("host_label")
        or get_config_value("GPU_HOT_HOST_LABEL", "Mini AI")
        or "GPU host"
    ).strip()

    snapshot = fetch_snapshot(
        base_url,
        timeout=timeout,
        max_processes=max_processes,
        prefer_websocket=bool(arguments.get("include_host", True)),
    )
    snapshot["host_label"] = host_label
    return {
        "ok": True,
        "speech": _speech(snapshot, host_label),
        "data": snapshot,
    }


def main() -> int:
    try:
        load_config()
        arguments = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        if not isinstance(arguments, dict):
            raise ValueError("Input must be a JSON object")
        print(json.dumps(run(arguments)))
        return 0
    except (GPUHotError, ValueError, TypeError, json.JSONDecodeError) as exc:
        message = f"Could not get GPU Hot status: {exc}"
        print(json.dumps({"ok": False, "speech": message, "error": str(exc)}))
        return 1
    except Exception as exc:
        message = f"Could not get GPU Hot status: {exc}"
        print(json.dumps({"ok": False, "speech": message, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
