"""Regression coverage for Canvas stash routes honoring configured storage."""

from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANVAS_ROOT = PROJECT_ROOT / "jarvis-canvas"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(CANVAS_ROOT))

from lib.stash_helper import StashFile, open_space  # noqa: E402
from server.routes import stash as stash_routes  # noqa: E402


def test_canvas_stash_file_route_reads_configured_stash_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_OVERRIDE_STASH_DIR", raising=False)
    monkeypatch.setenv("STASH_DIR", str(tmp_path))

    space, _is_new = open_space(labels=["canvas-configured-path"])
    saved = StashFile(space).save_text("hello from canvas stash", "canvas.txt")

    app = Flask(__name__)
    app.register_blueprint(stash_routes.stash_bp)
    client = app.test_client()

    response = client.get(f"/api/stash/{space.space_id}/{saved['file_id']}")
    metadata = client.get(f"/api/stash/{space.space_id}/{saved['file_id']}/metadata")

    assert response.status_code == 200
    assert response.data == b"hello from canvas stash"
    assert metadata.status_code == 200
    assert metadata.get_json()["space_id"] == space.space_id
