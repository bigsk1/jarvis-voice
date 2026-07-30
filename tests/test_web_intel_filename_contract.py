#!/usr/bin/env python3
"""Regression coverage for canonical Intel filenames in Jarvis Web uploads."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_web_app():
    for key in list(sys.modules):
        if key == "server" or key.startswith("server."):
            del sys.modules[key]
    web_root = str(PROJECT_ROOT / "jarvis-web")
    if web_root in sys.path:
        sys.path.remove(web_root)
    sys.path.insert(0, web_root)
    from server.app import app

    return app


def test_new_web_upload_requires_lowercase_kebab_case(tmp_path):
    app = _load_web_app()
    with (
        patch("server.app.is_auth_enabled", return_value=False),
        patch("server.routes.api.INTEL_DIR", tmp_path),
    ):
        with app.test_client() as client:
            response = client.post(
                "/api/intel/upload",
                data={
                    "file": (
                        io.BytesIO(b"# Uploaded Intel\n"),
                        "uploaded_intel.md",
                    )
                },
                content_type="multipart/form-data",
            )

    assert response.status_code == 400
    assert "lowercase kebab-case" in response.get_json()["error"]


def test_web_upload_can_replace_existing_legacy_file(tmp_path):
    legacy = tmp_path / "legacy_intel.md"
    legacy.write_text("# Old\n", encoding="utf-8")
    app = _load_web_app()
    with (
        patch("server.app.is_auth_enabled", return_value=False),
        patch("server.routes.api.INTEL_DIR", tmp_path),
        patch("server.routes.api.SKILLS_DIR", tmp_path / "missing-skills"),
    ):
        with app.test_client() as client:
            response = client.post(
                "/api/intel/upload",
                data={
                    "file": (
                        io.BytesIO(b"# Updated\n"),
                        legacy.name,
                    )
                },
                content_type="multipart/form-data",
            )

    assert response.status_code == 200
    assert legacy.read_text(encoding="utf-8") == "# Updated\n"
