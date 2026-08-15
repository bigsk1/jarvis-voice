from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "skills" / "gpu_hot_status.py"
SPEC = importlib.util.spec_from_file_location("gpu_hot_status_tool", MODULE_PATH)
gpu_hot_status = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(gpu_hot_status)


def test_status_tool_returns_spoken_gpu_and_host_snapshot(monkeypatch):
    def fake_fetch(base_url, **kwargs):
        assert base_url == "http://gpu-host:1312"
        assert kwargs["max_processes"] == 5
        return {
            "transport": "websocket",
            "gpu_count": 1,
            "gpus": [
                {
                    "name": "RTX Test",
                    "utilization_percent": 25.0,
                    "temperature_c": 44.0,
                    "vram_capacity_percent": 50.0,
                }
            ],
            "system": {"cpu_percent": 1.0, "ram_percent": 12.0},
        }

    monkeypatch.setattr(gpu_hot_status, "fetch_snapshot", fake_fetch)
    result = gpu_hot_status.run(
        {"base_url": "http://gpu-host:1312", "host_label": "Mini AI", "max_processes": 5}
    )

    assert result["ok"] is True
    assert result["data"]["host_label"] == "Mini AI"
    assert "25 percent utilization" in result["speech"]
    assert "host RAM 12 percent" in result["speech"]


def test_status_tool_requires_a_configured_url(monkeypatch):
    monkeypatch.setattr(gpu_hot_status, "get_config_value", lambda *_args: "")
    monkeypatch.setattr(Path, "exists", lambda _self: False)
    try:
        gpu_hot_status.run({})
    except gpu_hot_status.GPUHotError as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("expected a missing-configuration error")
