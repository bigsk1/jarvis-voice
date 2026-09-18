"""Regression coverage for Web UI stash routes honoring configured storage."""

from __future__ import annotations

import io
import sys
from pathlib import Path

from flask import Flask
import pytest

from server_package_utils import load_server_package


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))
load_server_package("jarvis_web_stash_config_test", PROJECT_ROOT / "jarvis-web" / "server")

from jarvis_web_stash_config_test.routes import api  # noqa: E402
from lib.stash_helper import StashFile, open_space  # noqa: E402


def _client():
    app = Flask(__name__)
    app.register_blueprint(api.api_bp)
    return app.test_client()


def test_web_stash_file_route_reads_configured_stash_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_OVERRIDE_STASH_DIR", raising=False)
    monkeypatch.setenv("STASH_DIR", str(tmp_path))

    space, _is_new = open_space(labels=["web-configured-path"])
    saved = StashFile(space).save_text("hello from configured stash", "configured.txt")

    response = _client().get(f"/api/stash/{space.space_id}/{saved['file_id']}")

    assert response.status_code == 200
    assert response.data == b"hello from configured stash"


def test_web_stash_upload_writes_configured_stash_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_OVERRIDE_STASH_DIR", raising=False)
    monkeypatch.setenv("STASH_DIR", str(tmp_path))

    response = _client().post(
        "/api/stash/upload",
        data={"file": (io.BytesIO(b"uploaded"), "uploaded.txt"), "labels": "test-upload"},
        content_type="multipart/form-data",
    )

    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert (tmp_path / payload["space_id"] / "uploaded.txt").read_bytes() == b"uploaded"


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_background_media_stash_url_keeps_original_mode_and_supports_seeking(tmp_path, monkeypatch, mode):
    import config_loader
    from lib import config_loader as package_config

    monkeypatch.delenv('JARVIS_OVERRIDE_STASH_DIR', raising=False)
    roots = {name: tmp_path / name for name in ('cloud', 'local')}
    for name, root in roots.items():
        space = root / 'space_media'
        space.mkdir(parents=True)
        (space / 'clip.mp4').write_bytes((name * 8).encode())
    for module in (config_loader, package_config):
        monkeypatch.setattr(module, '_load_mode_config', lambda selected: {'STASH_DIR': str(roots[selected])})
    with config_loader.config_scope('local' if mode == 'cloud' else 'cloud'):
        response = _client().get('/api/stash/space_media/clip.mp4?mode=' + mode,
                                 headers={'Range': 'bytes=0-3'})
    assert response.status_code == 206
    assert response.data == (mode * 8).encode()[:4]
    assert response.mimetype == 'video/mp4'
    assert response.headers['Content-Range'].startswith('bytes 0-3/')
