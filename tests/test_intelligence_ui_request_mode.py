"""Dashboard requests select isolated databases before performing any work."""

import importlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "_intelligence_request_mode_test"


@pytest.fixture
def dashboard(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.syspath_prepend(str(ROOT / "lib"))
    import config_loader
    import flask_error_logger
    import intelligence

    monkeypatch.setattr(intelligence, "get_intel_logger", Mock())
    monkeypatch.setattr(config_loader, "_load_mode_config", lambda _mode: {})
    monkeypatch.setattr(flask_error_logger, "setup_error_logging", Mock())
    load_server_package(PACKAGE, ROOT / "jarvis-intelligence/server")
    service = importlib.import_module(f"{PACKAGE}.services.intelligence_service")
    app_module = importlib.import_module(f"{PACKAGE}.app")
    paths = {mode: tmp_path / f"{mode}.db" for mode in ("cloud", "local")}
    monkeypatch.setattr(service, "DB_PATHS", paths)
    monkeypatch.setattr(app_module, "load_config", Mock())
    monkeypatch.setattr(app_module, "is_auth_enabled", lambda: False)
    monkeypatch.setattr(app_module.app, "run", Mock())
    for mode, path in paths.items():
        service.IntelligenceService(mode)
        with sqlite3.connect(path) as conn:
            for row_id in range(1, 2 if mode == "cloud" else 3):
                conn.execute(
                    "INSERT INTO experiences(id, timestamp, query, tools_used, outcome_success) "
                    "VALUES (?, '2026-01-15 12:00:00', ?, '[]', 1)",
                    (row_id, f"{mode} experience {row_id}"),
                )
                conn.execute(
                    "INSERT INTO insights(id, description, confidence) VALUES (?, ?, 0.8)",
                    (row_id, f"{mode} insight {row_id}"),
                )
                conn.execute(
                    "INSERT INTO reflection_queue(id, experience_id) VALUES (?, ?)",
                    (row_id, row_id),
                )
    try:
        yield SimpleNamespace(
            module=app_module,
            client=app_module.app.test_client(),
            paths=paths,
            service=service,
            intelligence=intelligence,
        )
    finally:
        for name in list(sys.modules):
            if name == PACKAGE or name.startswith(PACKAGE + "."):
                sys.modules.pop(name)


def rows(dashboard, mode, table, column):
    with sqlite3.connect(dashboard.paths[mode]) as conn:
        return [row[0] for row in conn.execute(f"SELECT {column} FROM {table} ORDER BY id")]


@pytest.mark.parametrize("startup_mode", ["cloud", "local"])
@pytest.mark.parametrize("explicit_opposite", [False, True])
def test_requests_read_update_and_delete_the_selected_database(
    dashboard, startup_mode, explicit_opposite
):
    dashboard.module.run_server(mode=startup_mode)
    selected = (
        ("local" if startup_mode == "cloud" else "cloud") if explicit_opposite else startup_mode
    )
    other = "local" if selected == "cloud" else "cloud"
    suffix = f"?mode={selected}" if explicit_opposite else ""
    client = dashboard.client
    assert client.get("/api/status").get_json()["startup_mode"] == startup_mode
    assert (
        client.get("/api/experiences/1" + suffix).get_json()["experience"]["query"]
        == f"{selected} experience 1"
    )
    assert (
        client.get("/api/insights/1" + suffix).get_json()["insight"]["description"]
        == f"{selected} insight 1"
    )
    count = 1 if selected == "cloud" else 2
    assert client.get("/api/stats" + suffix).get_json()["stats"]["experiences"]["total"] == count
    assert client.get("/api/stats/reflection-queue" + suffix).get_json()["total"] == count

    assert (
        client.put("/api/experiences/1" + suffix, json={"query": "edited experience"}).status_code
        == 200
    )
    assert (
        client.put("/api/insights/1" + suffix, json={"description": "edited insight"}).status_code
        == 200
    )
    assert rows(dashboard, selected, "experiences", "query")[0] == "edited experience"
    assert rows(dashboard, selected, "insights", "description")[0] == "edited insight"
    assert rows(dashboard, other, "experiences", "query")[0] == f"{other} experience 1"
    assert rows(dashboard, other, "insights", "description")[0] == f"{other} insight 1"

    assert client.delete("/api/stats/reflection-queue" + suffix).status_code == 200
    assert rows(dashboard, selected, "reflection_queue", "id") == []
    assert len(rows(dashboard, other, "reflection_queue", "id")) == (1 if other == "cloud" else 2)
    assert client.delete("/api/experiences/1" + suffix).status_code == 200
    assert client.delete("/api/insights/1" + suffix).status_code == 200
    assert 1 not in rows(dashboard, selected, "experiences", "id")
    assert 1 not in rows(dashboard, selected, "insights", "id")
    assert 1 in rows(dashboard, other, "experiences", "id")
    assert 1 in rows(dashboard, other, "insights", "id")


@pytest.mark.parametrize("invalid_mode", ["invalid", ""])
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/experiences"),
        ("PUT", "/api/experiences/1"),
        ("DELETE", "/api/experiences/1"),
        ("POST", "/api/experiences/1/reembed"),
        ("PUT", "/api/insights/1"),
        ("DELETE", "/api/insights/1"),
        ("POST", "/api/insights/1/reembed"),
        ("GET", "/api/stats"),
        ("DELETE", "/api/stats/reflection-queue/1"),
        ("DELETE", "/api/stats/reflection-queue"),
        ("POST", "/api/maintenance/reflect"),
        ("POST", "/api/maintenance/decay"),
        ("POST", "/api/maintenance/anomaly"),
        ("POST", "/api/maintenance/meta-cognition"),
        ("POST", "/api/maintenance/all"),
        ("GET", "/api/maintenance/health"),
    ],
)
def test_invalid_mode_rejects_before_database_provider_or_child_work(
    dashboard, monkeypatch, invalid_mode, method, path
):
    dashboard.module.run_server(mode="local")
    service_init = Mock(side_effect=AssertionError("invalid request opened a database"))
    provider = Mock(side_effect=AssertionError("invalid request initialized Intelligence"))
    subprocess_run = Mock(side_effect=AssertionError("invalid request launched a subprocess"))
    monkeypatch.setattr(dashboard.service.IntelligenceService, "__init__", service_init)
    monkeypatch.setattr(dashboard.intelligence, "get_intelligence_layer", provider)
    monkeypatch.setattr("subprocess.run", subprocess_run)
    response = dashboard.client.open(
        path + "?mode=" + invalid_mode,
        method=method,
        json={"query": "incorrect update", "description": "incorrect update"},
    )
    assert response.status_code == 400
    assert response.get_json() == {"ok": False, "error": "mode must be cloud or local"}
    service_init.assert_not_called()
    provider.assert_not_called()
    subprocess_run.assert_not_called()
    for mode in ("cloud", "local"):
        assert rows(dashboard, mode, "experiences", "query")[0] == f"{mode} experience 1"
        assert rows(dashboard, mode, "insights", "description")[0] == f"{mode} insight 1"
        assert len(rows(dashboard, mode, "reflection_queue", "id")) == (1 if mode == "cloud" else 2)


@pytest.mark.parametrize("startup_mode", ["cloud", "local"])
@pytest.mark.parametrize("explicit_opposite", [False, True])
def test_maintenance_and_reembed_use_the_selected_mode(
    dashboard, monkeypatch, startup_mode, explicit_opposite
):
    from config_loader import get_active_config_mode

    dashboard.module.run_server(mode=startup_mode)
    selected = (
        ("local" if startup_mode == "cloud" else "cloud") if explicit_opposite else startup_mode
    )
    suffix = f"?mode={selected}" if explicit_opposite else ""
    intel = SimpleNamespace(
        process_reflection_queue_detailed=AsyncMock(return_value={"processed": 0, "outcomes": []}),
        run_decay_job=AsyncMock(return_value={"status": "ok"}),
        run_anomaly_detection=AsyncMock(return_value={"status": "ok"}),
        run_meta_cognition=AsyncMock(return_value={"status": "ok"}),
        run_all_maintenance=AsyncMock(return_value={"status": "ok"}),
    )
    selected_modes = []

    def get_layer(mode):
        selected_modes.append((mode, get_active_config_mode()))
        return intel

    monkeypatch.setattr(dashboard.intelligence, "get_intelligence_layer", get_layer)
    for job in ("reflect", "decay", "anomaly", "meta-cognition", "all"):
        assert dashboard.client.post("/api/maintenance/" + job + suffix).status_code == 200
    assert selected_modes == [(selected, selected)] * 5
    subprocess_run = Mock(return_value=SimpleNamespace(returncode=0, stdout="{}", stderr=""))
    monkeypatch.setattr("subprocess.run", subprocess_run)
    assert dashboard.client.post("/api/experiences/1/reembed" + suffix).status_code == 200
    assert dashboard.client.post("/api/insights/1/reembed" + suffix).status_code == 200
    assert dashboard.client.get("/api/maintenance/health" + suffix).status_code == 200
    assert [call.args[0][-1] for call in subprocess_run.call_args_list[:2]] == [selected, selected]
    assert subprocess_run.call_args.args[0][-2:] == [selected, "--json"]


def test_omitted_feedback_filter_still_includes_both_modes(dashboard, monkeypatch, tmp_path):
    dashboard.module.run_server(mode="local")
    feedback = importlib.import_module(f"{PACKAGE}.routes.feedback")

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 15, 12, 0, tzinfo=tz)

    monkeypatch.setattr(feedback, "datetime", FixedDatetime)
    monkeypatch.setattr(feedback, "FEEDBACK_DIR", tmp_path)
    entries = [
        {"mode": mode, "rating": 4, "timestamp": "2026-01-15T11:00:00"}
        for mode in ("cloud", "local")
    ]
    (tmp_path / "feedback-2026-01-15.jsonl").write_text(
        "\n".join(json.dumps(entry) for entry in entries), encoding="utf-8"
    )
    assert dashboard.client.get("/api/feedback").get_json()["total"] == 2
    assert dashboard.client.get("/api/feedback/stats").get_json()["stats"]["total"] == 2
    local = dashboard.client.get("/api/feedback?mode=local").get_json()
    assert [entry["mode"] for entry in local["feedback"]] == ["local"]
