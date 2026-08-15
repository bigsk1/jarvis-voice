from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "services"
    / "gpu-hot-monitor"
    / "gpu_hot_monitor.py"
)
UNIT_PATH = MODULE_PATH.with_name("gpu-hot-monitor.service")
SPEC = importlib.util.spec_from_file_location("gpu_hot_monitor_service", MODULE_PATH)
gpu_hot_monitor = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = gpu_hot_monitor
SPEC.loader.exec_module(gpu_hot_monitor)


class FakeAlerts:
    def __init__(self):
        self.created = []
        self.resolved = []

    def create(self, payload):
        self.created.append(payload)
        return 77

    def resolve(self, alert_id):
        self.resolved.append(alert_id)


def _config(monkeypatch, tmp_path, **values):
    defaults = {
        "GPU_HOT_URL": "http://gpu-host:1312",
        "GPU_HOT_HOST_LABEL": "Mini AI",
        "GPU_HOT_STATE_FILE": str(tmp_path / "state.json"),
        "GPU_HOT_TEMPERATURE_C": "80",
        "GPU_HOT_TEMPERATURE_RECOVERY_C": "75",
        "GPU_HOT_TEMPERATURE_SAMPLES": "2",
        "GPU_HOT_RECOVERY_SAMPLES": "2",
        "GPU_HOT_VRAM_PERCENT": "95",
        "GPU_HOT_VRAM_RECOVERY_PERCENT": "90",
        "GPU_HOT_VRAM_SAMPLES": "2",
        "GPU_HOT_UTILIZATION_PERCENT": "0",
    }
    defaults.update(values)
    for key, value in defaults.items():
        monkeypatch.setenv(key, value)
    return gpu_hot_monitor.MonitorConfig.from_environment()


def _snapshot(*, temperature=40.0, vram=30.0):
    return {
        "transport": "websocket",
        "gpus": [
            {
                "index": "0",
                "name": "RTX Test",
                "temperature_c": temperature,
                "vram_capacity_percent": vram,
                "utilization_percent": 10.0,
            }
        ],
        "system": {"cpu_percent": 1.0, "ram_percent": 12.0},
    }


def test_temperature_requires_consecutive_samples_and_resolves_with_hysteresis(monkeypatch, tmp_path):
    monitor = gpu_hot_monitor.GPUHotMonitor(_config(monkeypatch, tmp_path))
    alerts = FakeAlerts()
    monitor.alerts = alerts

    monitor.process_snapshot(_snapshot(temperature=82))
    assert alerts.created == []
    monitor.process_snapshot(_snapshot(temperature=83))
    assert len(alerts.created) == 1
    assert alerts.created[0]["metadata"]["condition"] == "temperature"

    monitor.process_snapshot(_snapshot(temperature=77))
    monitor.process_snapshot(_snapshot(temperature=74))
    assert alerts.resolved == []
    monitor.process_snapshot(_snapshot(temperature=73))
    assert alerts.resolved == [77]


def test_vram_capacity_threshold_is_independent_from_gpu_utilization(monkeypatch, tmp_path):
    monitor = gpu_hot_monitor.GPUHotMonitor(_config(monkeypatch, tmp_path))
    alerts = FakeAlerts()
    monitor.alerts = alerts

    monitor.process_snapshot(_snapshot(vram=97))
    monitor.process_snapshot(_snapshot(vram=98))

    assert len(alerts.created) == 1
    metadata = alerts.created[0]["metadata"]
    assert metadata["condition"] == "vram_capacity"
    assert metadata["threshold"] == 95.0


def test_offline_alert_requires_failures_and_recovers(monkeypatch, tmp_path):
    config = _config(monkeypatch, tmp_path, GPU_HOT_FAILURE_SAMPLES="3")
    monitor = gpu_hot_monitor.GPUHotMonitor(config)
    alerts = FakeAlerts()
    monitor.alerts = alerts

    monitor.process_failure("timeout")
    monitor.process_failure("timeout")
    assert alerts.created == []
    monitor.process_failure("timeout")
    assert alerts.created[0]["title"] == "GPU Hot Down: Mini AI"

    monitor.process_snapshot(_snapshot())
    assert alerts.resolved == []
    monitor.process_snapshot(_snapshot())
    assert alerts.resolved == [77]


def test_monitor_rejects_invalid_recovery_and_percentage_thresholds(monkeypatch, tmp_path):
    monkeypatch.setenv("GPU_HOT_URL", "http://gpu-host:1312")
    monkeypatch.setenv("GPU_HOT_STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("GPU_HOT_VRAM_PERCENT", "95")
    monkeypatch.setenv("GPU_HOT_VRAM_RECOVERY_PERCENT", "96")
    try:
        gpu_hot_monitor.MonitorConfig.from_environment()
    except ValueError as exc:
        assert "recovery threshold" in str(exc)
    else:
        raise AssertionError("expected invalid hysteresis configuration to fail")

    monkeypatch.setenv("GPU_HOT_VRAM_RECOVERY_PERCENT", "90")
    monkeypatch.setenv("GPU_HOT_UTILIZATION_PERCENT", "101")
    try:
        gpu_hot_monitor.MonitorConfig.from_environment()
    except ValueError as exc:
        assert "cannot exceed 100" in str(exc)
    else:
        raise AssertionError("expected invalid percentage threshold to fail")


def test_systemd_template_renders_the_service_users_home_not_system_manager_home():
    unit = UNIT_PATH.read_text(encoding="utf-8")

    assert "__JARVIS_HOME__/jarvis-voice/services/gpu-hot-monitor" in unit
    assert "__JARVIS_HOME__/jarvis-venv/bin/python3" in unit
    assert "ReadWritePaths=__JARVIS_HOME__/jarvis-voice/logs" in unit
    assert "%h" not in unit
