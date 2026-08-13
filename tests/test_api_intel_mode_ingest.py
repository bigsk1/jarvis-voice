#!/usr/bin/env python3
"""Mode-aware FastAPI Intel ingestion regression coverage."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api.models.intel import IntelCreate
from api.routes import intel as intel_routes


def test_create_passes_explicit_mode_to_shared_background_ingest(tmp_path, monkeypatch):
    intel_dir = tmp_path / "jarvis-intel"
    intel_dir.mkdir()
    monkeypatch.setattr(intel_routes, "INTEL_DIR", intel_dir)

    plan = {"ok": True, "modes": ["local", "cloud"], "skipped_modes": []}
    started = {"started": True, **plan}
    with (
        patch.object(intel_routes, "get_auto_ingest_plan", return_value=plan) as plan_mock,
        patch.object(intel_routes, "start_auto_ingest", return_value=started) as start_mock,
    ):
        response = asyncio.run(
            intel_routes.create_intel_file(
                IntelCreate(
                    filename="user-profile.md",
                    content="# User Profile\n\n## Profile Card\n\n- Tester\n",
                    auto_ingest=True,
                ),
                mode="local",
            )
        )

    assert response.ingestion_started is True
    assert response.ingest_modes == ["local", "cloud"]
    plan_mock.assert_called_once_with(intel_routes.PROJECT_ROOT, "local")
    start_mock.assert_called_once_with(intel_routes.PROJECT_ROOT, "local")


def test_missing_selected_mode_config_rejects_before_file_write(tmp_path, monkeypatch):
    intel_dir = tmp_path / "jarvis-intel"
    intel_dir.mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(intel_routes, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(intel_routes, "INTEL_DIR", intel_dir)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            intel_routes.create_intel_file(
                IntelCreate(
                    filename="user-profile.md",
                    content="# User Profile\n\n## Profile Card\n\n- Tester\n",
                    auto_ingest=True,
                ),
                mode="local",
            )
        )

    assert exc_info.value.status_code == 400
    assert "config/local.env not found" in exc_info.value.detail
    assert not (intel_dir / "user-profile.md").exists()


def test_sibling_config_warning_is_returned_without_blocking_primary_save(tmp_path, monkeypatch):
    intel_dir = tmp_path / "jarvis-intel"
    intel_dir.mkdir()
    monkeypatch.setattr(intel_routes, "INTEL_DIR", intel_dir)
    warning = "local DB exists but config/local.env is missing; skipped local ingest"
    plan = {
        "ok": True,
        "modes": ["cloud"],
        "skipped_modes": ["local"],
        "warning": warning,
    }
    started = {"started": True, **plan}

    with (
        patch.object(intel_routes, "get_auto_ingest_plan", return_value=plan),
        patch.object(intel_routes, "start_auto_ingest", return_value=started),
    ):
        response = asyncio.run(
            intel_routes.create_intel_file(
                IntelCreate(
                    filename="user-profile.md",
                    content="# User Profile\n\n## Profile Card\n\n- Tester\n",
                    auto_ingest=True,
                ),
                mode="cloud",
            )
        )

    assert response.ingestion_started is True
    assert response.ingest_modes == ["cloud"]
    assert response.ingest_warning == warning
    assert (intel_dir / "user-profile.md").exists()


def test_get_missing_mode_db_reports_pending_without_initializing_db(tmp_path, monkeypatch):
    intel_dir = tmp_path / "jarvis-intel"
    intel_dir.mkdir()
    (intel_dir / "user-profile.md").write_text("# User Profile\n", encoding="utf-8")
    monkeypatch.setattr(intel_routes, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(intel_routes, "INTEL_DIR", intel_dir)

    with patch.object(intel_routes, "get_db") as get_db_mock:
        response = asyncio.run(
            intel_routes.get_intel_file("user-profile.md", mode="local")
        )

    assert response.file is not None
    assert response.file.ingested is False
    assert response.file.fact_count is None
    get_db_mock.assert_not_called()
