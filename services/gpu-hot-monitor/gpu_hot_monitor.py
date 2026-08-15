#!/usr/bin/env python3
"""Poll GPU Hot and maintain Jarvis alerts for sustained unhealthy metrics."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from gpu_hot_client import GPUHotError, fetch_snapshot, normalize_base_url  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("gpu-hot-monitor")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")


def _recovery_threshold(alert_threshold: float, configured: float) -> float:
    if configured > 0:
        return configured
    return max(0.0, alert_threshold - 5.0)


@dataclass
class ConditionState:
    active: bool = False
    breach_count: int = 0
    recovery_count: int = 0
    alert_id: int | None = None


class ConditionTracker:
    """Consecutive-sample and hysteresis state for alert conditions."""

    def __init__(self, values: dict[str, Any] | None = None):
        self.states: dict[str, ConditionState] = {}
        for key, value in (values or {}).items():
            if not isinstance(value, dict):
                continue
            try:
                allowed = {
                    "active": bool(value.get("active", False)),
                    "breach_count": int(value.get("breach_count", 0) or 0),
                    "recovery_count": int(value.get("recovery_count", 0) or 0),
                    "alert_id": value.get("alert_id"),
                }
                self.states[key] = ConditionState(**allowed)
            except (TypeError, ValueError):
                continue

    def get(self, key: str) -> ConditionState:
        return self.states.setdefault(key, ConditionState())

    def observe(
        self,
        key: str,
        *,
        breached: bool,
        recovered: bool,
        trigger_samples: int,
        recovery_samples: int,
    ) -> str | None:
        state = self.get(key)
        trigger_samples = max(1, trigger_samples)
        recovery_samples = max(1, recovery_samples)

        if not state.active:
            state.recovery_count = 0
            state.breach_count = state.breach_count + 1 if breached else 0
            return "alert" if state.breach_count >= trigger_samples else None

        state.breach_count = 0
        state.recovery_count = state.recovery_count + 1 if recovered else 0
        return "recover" if state.recovery_count >= recovery_samples else None

    def mark_active(self, key: str, alert_id: int) -> None:
        state = self.get(key)
        state.active = True
        state.alert_id = alert_id
        state.breach_count = 0
        state.recovery_count = 0

    def mark_recovered(self, key: str) -> None:
        self.states[key] = ConditionState()

    def to_dict(self) -> dict[str, Any]:
        return {key: asdict(value) for key, value in self.states.items()}


@dataclass(frozen=True)
class MetricRule:
    name: str
    label: str
    threshold: float
    recovery: float
    samples: int
    unit: str

    @property
    def enabled(self) -> bool:
        return self.threshold > 0


@dataclass(frozen=True)
class MonitorConfig:
    base_url: str
    host_label: str
    poll_seconds: float
    request_timeout: float
    failure_samples: int
    recovery_samples: int
    severity: str
    state_file: Path
    jarvis_alerts_url: str
    jarvis_api_key: str
    alert_timeout: float
    temperature: MetricRule
    vram: MetricRule
    utilization: MetricRule
    host_cpu: MetricRule
    host_ram: MetricRule

    @classmethod
    def from_environment(cls) -> "MonitorConfig":
        base_url = normalize_base_url(os.environ.get("GPU_HOT_URL", ""))
        severity = os.environ.get("GPU_HOT_ALERT_SEVERITY", "high").strip().lower()
        if severity not in {"low", "medium", "high", "critical"}:
            raise ValueError("GPU_HOT_ALERT_SEVERITY must be low, medium, high, or critical")

        state_raw = os.environ.get("GPU_HOT_STATE_FILE", "").strip()
        state_file = Path(state_raw).expanduser() if state_raw else PROJECT_ROOT / "logs" / "gpu-hot-monitor-state.json"

        temperature = _env_float("GPU_HOT_TEMPERATURE_C", 80)
        vram = _env_float("GPU_HOT_VRAM_PERCENT", 0)
        utilization = _env_float("GPU_HOT_UTILIZATION_PERCENT", 0)
        host_cpu = _env_float("GPU_HOT_HOST_CPU_PERCENT", 0)
        host_ram = _env_float("GPU_HOT_HOST_RAM_PERCENT", 0)
        config = cls(
            base_url=base_url,
            host_label=os.environ.get("GPU_HOT_HOST_LABEL", "GPU host").strip() or "GPU host",
            poll_seconds=max(5.0, _env_float("GPU_HOT_POLL_SECONDS", 30)),
            request_timeout=min(max(1.0, _env_float("GPU_HOT_REQUEST_TIMEOUT_SECONDS", 8)), 30.0),
            failure_samples=max(1, _env_int("GPU_HOT_FAILURE_SAMPLES", 3)),
            recovery_samples=max(1, _env_int("GPU_HOT_RECOVERY_SAMPLES", 2)),
            severity=severity,
            state_file=state_file,
            jarvis_alerts_url=os.environ.get("JARVIS_ALERTS_URL", "http://localhost:8880/api/alerts").rstrip("/"),
            jarvis_api_key=os.environ.get("JARVIS_API_KEY", "").strip(),
            alert_timeout=min(max(1.0, _env_float("JARVIS_ALERT_TIMEOUT_SECONDS", 10)), 30.0),
            temperature=MetricRule(
                "temperature", "temperature", temperature,
                _env_float("GPU_HOT_TEMPERATURE_RECOVERY_C", 75),
                max(1, _env_int("GPU_HOT_TEMPERATURE_SAMPLES", 4)), "C",
            ),
            vram=MetricRule(
                "vram_capacity", "allocated VRAM", vram,
                _recovery_threshold(vram, _env_float("GPU_HOT_VRAM_RECOVERY_PERCENT", 0)),
                max(1, _env_int("GPU_HOT_VRAM_SAMPLES", 4)), "%",
            ),
            utilization=MetricRule(
                "utilization", "GPU utilization", utilization,
                _recovery_threshold(utilization, _env_float("GPU_HOT_UTILIZATION_RECOVERY_PERCENT", 0)),
                max(1, _env_int("GPU_HOT_UTILIZATION_SAMPLES", 10)), "%",
            ),
            host_cpu=MetricRule(
                "host_cpu", "host CPU", host_cpu,
                _recovery_threshold(host_cpu, _env_float("GPU_HOT_HOST_CPU_RECOVERY_PERCENT", 0)),
                max(1, _env_int("GPU_HOT_HOST_CPU_SAMPLES", 10)), "%",
            ),
            host_ram=MetricRule(
                "host_ram", "host RAM", host_ram,
                _recovery_threshold(host_ram, _env_float("GPU_HOT_HOST_RAM_RECOVERY_PERCENT", 0)),
                max(1, _env_int("GPU_HOT_HOST_RAM_SAMPLES", 4)), "%",
            ),
        )
        for rule in (
            config.temperature,
            config.vram,
            config.utilization,
            config.host_cpu,
            config.host_ram,
        ):
            if rule.enabled and rule.recovery >= rule.threshold:
                raise ValueError(
                    f"{rule.name} recovery threshold must be lower than its alert threshold"
                )
        for rule in (config.vram, config.utilization, config.host_cpu, config.host_ram):
            if rule.threshold > 100 or rule.recovery > 100:
                raise ValueError(f"{rule.name} percentage thresholds cannot exceed 100")
        return config


class AlertClient:
    def __init__(self, config: MonitorConfig):
        self.base_url = config.jarvis_alerts_url
        self.api_key = config.jarvis_api_key
        self.timeout = config.alert_timeout
        self.opener = build_opener(ProxyHandler({}))

    def _request(self, url: str, *, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Jarvis alerts API request failed: {exc}") from exc
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise RuntimeError(f"Jarvis alerts API returned an unsuccessful response: {result}")
        return result

    def create(self, payload: dict[str, Any]) -> int:
        result = self._request(self.base_url, method="POST", payload=payload)
        alert_id = result.get("alert_id")
        if not isinstance(alert_id, int):
            raise RuntimeError("Jarvis alerts API did not return an alert_id")
        return alert_id

    def resolve(self, alert_id: int) -> None:
        self._request(f"{self.base_url}/{alert_id}/resolve", method="POST")


def load_tracker(path: Path) -> ConditionTracker:
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return ConditionTracker(payload.get("conditions"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not load state file %s: %s", path, exc)
    return ConditionTracker()


def save_tracker(path: Path, tracker: ConditionTracker) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps({"version": 1, "conditions": tracker.to_dict()}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temp_path, path)


class GPUHotMonitor:
    def __init__(self, config: MonitorConfig, *, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        self.tracker = ConditionTracker() if dry_run else load_tracker(config.state_file)
        self.alerts = AlertClient(config)

    def _dispatch(self, key: str, action: str | None, payload: dict[str, Any]) -> None:
        if not action:
            return
        if self.dry_run:
            log.info("DRY RUN %s %s: %s", action.upper(), key, payload.get("description"))
            if action == "alert":
                self.tracker.mark_active(key, -1)
            else:
                self.tracker.mark_recovered(key)
            return

        try:
            if action == "alert":
                alert_id = self.alerts.create(payload)
                self.tracker.mark_active(key, alert_id)
                log.warning("Created alert %s for %s", alert_id, key)
            elif action == "recover":
                alert_id = self.tracker.get(key).alert_id
                if alert_id is not None:
                    self.alerts.resolve(alert_id)
                    log.info("Resolved alert %s for %s", alert_id, key)
                self.tracker.mark_recovered(key)
        except Exception as exc:
            log.error("Could not %s Jarvis alert for %s: %s", action, key, exc)

    def _payload(
        self,
        *,
        key: str,
        title: str,
        description: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "title": title,
            "description": description,
            "severity": self.config.severity,
            "source": "gpu_hot_monitor",
            "metadata": {
                "dedupe_key": f"gpu-hot:{self.config.host_label}:{key}",
                "host": self.config.host_label,
                "dashboard_url": f"{self.config.base_url}/",
                **metadata,
            },
        }

    def process_failure(self, error: str) -> None:
        key = "service:unavailable"
        action = self.tracker.observe(
            key,
            breached=True,
            recovered=False,
            trigger_samples=self.config.failure_samples,
            recovery_samples=self.config.recovery_samples,
        )
        payload = self._payload(
            key=key,
            title=f"GPU Hot Down: {self.config.host_label}",
            description=(
                f"GPU Hot at {self.config.base_url} failed "
                f"{self.tracker.get(key).breach_count} consecutive checks. Last error: {error}"
            ),
            metadata={"condition": "unavailable", "error": error},
        )
        self._dispatch(key, action, payload)

    def _observe_metric(
        self,
        *,
        scope: str,
        rule: MetricRule,
        value: float | None,
        subject: str,
        metadata: dict[str, Any],
    ) -> None:
        if value is None:
            return
        key = f"{scope}:{rule.name}"
        if rule.enabled:
            breached = value >= rule.threshold
            recovered = value <= rule.recovery
        else:
            breached = False
            recovered = True
        action = self.tracker.observe(
            key,
            breached=breached,
            recovered=recovered,
            trigger_samples=rule.samples,
            recovery_samples=self.config.recovery_samples,
        )
        payload = self._payload(
            key=key,
            title=f"{self.config.host_label} {rule.label} high",
            description=(
                f"{subject} {rule.label} is {value:g}{rule.unit}; "
                f"the alert threshold is {rule.threshold:g}{rule.unit}."
            ),
            metadata={
                "condition": rule.name,
                "value": value,
                "threshold": rule.threshold,
                "recovery_threshold": rule.recovery,
                **metadata,
            },
        )
        self._dispatch(key, action, payload)

    def process_snapshot(self, snapshot: dict[str, Any]) -> None:
        offline_key = "service:unavailable"
        action = self.tracker.observe(
            offline_key,
            breached=False,
            recovered=True,
            trigger_samples=self.config.failure_samples,
            recovery_samples=self.config.recovery_samples,
        )
        self._dispatch(
            offline_key,
            action,
            self._payload(
                key=offline_key,
                title=f"GPU Hot Down: {self.config.host_label}",
                description=f"GPU Hot at {self.config.base_url} is responding again.",
                metadata={"condition": "unavailable"},
            ),
        )

        for gpu in snapshot.get("gpus", []):
            gpu_index = str(gpu.get("index", "unknown"))
            subject = f"GPU {gpu_index} ({gpu.get('name') or 'unknown GPU'})"
            common = {"gpu_index": gpu_index, "gpu_name": gpu.get("name")}
            self._observe_metric(
                scope=f"gpu:{gpu_index}", rule=self.config.temperature,
                value=gpu.get("temperature_c"), subject=subject, metadata=common,
            )
            self._observe_metric(
                scope=f"gpu:{gpu_index}", rule=self.config.vram,
                value=gpu.get("vram_capacity_percent"), subject=subject, metadata=common,
            )
            self._observe_metric(
                scope=f"gpu:{gpu_index}", rule=self.config.utilization,
                value=gpu.get("utilization_percent"), subject=subject, metadata=common,
            )

        system = snapshot.get("system")
        if isinstance(system, dict):
            self._observe_metric(
                scope="host", rule=self.config.host_cpu,
                value=system.get("cpu_percent"), subject=self.config.host_label,
                metadata={},
            )
            self._observe_metric(
                scope="host", rule=self.config.host_ram,
                value=system.get("ram_percent"), subject=self.config.host_label,
                metadata={},
            )

    def run_once(self) -> dict[str, Any] | None:
        try:
            snapshot = fetch_snapshot(
                self.config.base_url,
                timeout=self.config.request_timeout,
                max_processes=10,
                prefer_websocket=True,
            )
            self.process_snapshot(snapshot)
            gpu = snapshot["gpus"][0]
            system = snapshot.get("system") or {}
            log.info(
                "%s: GPU %s%%, VRAM %s%%, %s C; host CPU %s%%, RAM %s%% (%s)",
                self.config.host_label,
                gpu.get("utilization_percent"),
                gpu.get("vram_capacity_percent"),
                gpu.get("temperature_c"),
                system.get("cpu_percent", "n/a"),
                system.get("ram_percent", "n/a"),
                snapshot.get("transport"),
            )
            return snapshot
        except GPUHotError as exc:
            log.warning("GPU Hot check failed: %s", exc)
            self.process_failure(str(exc))
            return None
        finally:
            if not self.dry_run:
                try:
                    save_tracker(self.config.state_file, self.tracker)
                except OSError as exc:
                    log.error("Could not save monitor state: %s", exc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run one check and exit")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate without posting or resolving alerts")
    args = parser.parse_args()

    try:
        config = MonitorConfig.from_environment()
    except (GPUHotError, ValueError) as exc:
        log.error("Configuration error: %s", exc)
        return 2

    monitor = GPUHotMonitor(config, dry_run=args.dry_run)
    log.info(
        "Monitoring %s at %s every %ss (VRAM alert %s, utilization alert %s)",
        config.host_label,
        config.base_url,
        config.poll_seconds,
        config.vram.threshold or "disabled",
        config.utilization.threshold or "disabled",
    )
    while True:
        monitor.run_once()
        if args.once:
            return 0
        time.sleep(config.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
