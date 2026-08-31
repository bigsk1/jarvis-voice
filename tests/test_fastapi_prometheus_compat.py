"""Regression coverage for FastAPI included-router Prometheus instrumentation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_included_routers_cors_and_metrics_work_on_current_fastapi():
    """Exercise Jarvis's real instrument-before-include_router ordering in isolation."""
    script = r'''
from fastapi.testclient import TestClient

from api.server import PROMETHEUS_AVAILABLE, app

assert PROMETHEUS_AVAILABLE

origin = "https://jarvis.test"
with TestClient(app, client=("127.0.0.1", 50000)) as client:
    route_response = client.get("/api/generated-videos/health")
    preflight_response = client.options(
        "/api/generated-videos/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    metrics_response = client.get("/metrics")

assert route_response.status_code == 200, route_response.text
assert preflight_response.status_code == 200, preflight_response.text
assert preflight_response.headers["access-control-allow-origin"] == origin
assert metrics_response.status_code == 200, metrics_response.text
assert 'handler="/api/generated-videos/health"' in metrics_response.text
assert 'method="GET"' in metrics_response.text
'''

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, (
        "FastAPI/Prometheus compatibility smoke failed\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
