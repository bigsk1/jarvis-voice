from __future__ import annotations

import pytest

from lib import gpu_hot_client
from lib.gpu_hot_client import GPUHotError, normalize_base_url, normalize_snapshot, websocket_url


def test_normalize_snapshot_calculates_allocated_vram_and_sorts_processes():
    snapshot = normalize_snapshot(
        {
            "mode": "default",
            "node_name": "gpu-node",
            "gpus": {
                "0": {
                    "index": "0",
                    "name": "RTX Test",
                    "utilization": 75,
                    "memory_utilization": 42,
                    "memory_used": 12288,
                    "memory_total": 16384,
                    "memory_free": 4096,
                    "temperature": 63,
                }
            },
            "processes": [
                {"pid": "2", "name": "small", "gpu_id": "0", "memory": 512},
                {"pid": "1", "name": "large", "gpu_id": "0", "memory": 2048},
            ],
            "system": {"cpu_percent": 1.2, "memory_percent": 12.4, "memory_total_gb": 49.0},
        },
        base_url="http://gpu-host:1312",
        transport="websocket",
        max_processes=1,
    )

    gpu = snapshot["gpus"][0]
    assert gpu["vram_capacity_percent"] == 75.0
    assert gpu["memory_bandwidth_utilization_percent"] == 42.0
    assert snapshot["process_count"] == 2
    assert snapshot["processes"] == [
        {"pid": 1, "name": "large", "gpu_index": "0", "gpu_uuid": None, "vram_mib": 2048.0}
    ]
    assert snapshot["processes_truncated"] is True
    assert snapshot["system"]["ram_percent"] == 12.4


def test_url_validation_and_websocket_path():
    assert normalize_base_url("http://gpu-host:1312/") == "http://gpu-host:1312"
    assert websocket_url("https://gpu.example/monitor") == "wss://gpu.example/monitor/socket.io/"
    with pytest.raises(GPUHotError, match="http"):
        normalize_base_url("gpu-host:1312")
    with pytest.raises(GPUHotError, match="credentials"):
        normalize_base_url("http://user:secret@gpu-host:1312")


def test_snapshot_rejects_missing_gpu_metrics():
    with pytest.raises(GPUHotError, match="no GPU metrics"):
        normalize_snapshot({}, base_url="http://gpu-host:1312", transport="rest")


def test_full_snapshot_falls_back_to_rest_with_an_explicit_warning(monkeypatch):
    monkeypatch.setattr(
        gpu_hot_client,
        "fetch_websocket_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(GPUHotError("socket unavailable")),
    )
    monkeypatch.setattr(
        gpu_hot_client,
        "fetch_rest_snapshot",
        lambda *_args, **_kwargs: {"transport": "rest", "gpus": [{"index": "0"}]},
    )

    snapshot = gpu_hot_client.fetch_snapshot("http://gpu-host:1312")

    assert snapshot["transport"] == "rest"
    assert "GPU-only REST metrics" in snapshot["warnings"][0]
    assert snapshot["warnings"][1] == "socket unavailable"
