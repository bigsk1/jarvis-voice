#!/usr/bin/env python3
"""System monitor health-check regressions."""

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "skills" / "auto-tools" / "system_monitor.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("system_monitor_tool", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_analyze_health_flags_hot_core_and_runaway_process():
    module = _load_module()
    data = {
        "cpu": {
            "total_percent": 42,
            "per_core_percent": [12, 99.5, 8, 4],
        },
        "memory": {
            "ram": {"percent_used": 55},
            "swap": {"percent_used": 2},
        },
        "disks": [
            {"mountpoint": "/", "percent_used": 70, "free_gb": 200},
        ],
        "processes": [
            {
                "pid": 1234,
                "name": "aplay",
                "cmdline": "aplay /dev/null",
                "cpu_percent": 101.0,
                "memory_percent": 0.1,
                "age_minutes": 45,
            }
        ],
    }

    health = module.analyze_health(data)

    assert health["status"] == "critical"
    assert health["issue_count"] == 2
    assert health["highest_severity"] == "high"
    assert health["alert_severity"] == "high"
    assert health["hot_core_count"] == 1
    assert health["suspicious_process_count"] == 1
    assert "CPU core 2" in health["issue_summary"]
    assert "Process aplay" in health["issue_summary"]
    assert health["dedupe_key"] == "jarvis_self_check:cpu_core_hot:core_2"
    assert health["alert_dedupe_key"] == "jarvis_self_check:cpu_core_hot:core_2"


def test_analyze_health_all_clear():
    module = _load_module()
    data = {
        "cpu": {"total_percent": 8, "per_core_percent": [5, 10]},
        "memory": {"ram": {"percent_used": 30}, "swap": {"percent_used": 0}},
        "disks": [{"mountpoint": "/", "percent_used": 40, "free_gb": 500}],
        "processes": [{"pid": 1, "name": "systemd", "cmdline": "", "cpu_percent": 0}],
    }

    health = module.analyze_health(data)

    assert health["status"] == "healthy"
    assert health["issue_count"] == 0
    assert health["issue_summary"] == "No threshold issues detected."
    assert health["alert_severity"] == "high"


def test_health_check_reports_monitor_unavailable_without_failing(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "psutil", None)

    health = module.get_health_check({})

    assert health["status"] == "critical"
    assert health["issue_count"] == 1
    assert health["highest_severity"] == "critical"
    assert health["alert_severity"] == "critical"
    assert health["dedupe_key"] == "jarvis_self_check:monitor_unavailable:psutil"
    assert health["alert_dedupe_key"] == "jarvis_self_check:monitor_unavailable:psutil"
