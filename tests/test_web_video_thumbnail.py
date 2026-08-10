"""Regression coverage for generated-video posters in Jarvis Web chat."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from server_package_utils import load_server_package


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))
load_server_package("jarvis_web_test_server", PROJECT_ROOT / "jarvis-web" / "server")

from jarvis_web_test_server.app import app  # noqa: E402
from jarvis_web_test_server.routes import api  # noqa: E402


def test_chat_uses_generated_video_thumbnail_as_poster():
    chat_js = (PROJECT_ROOT / "jarvis-web/client/js/chat.js").read_text()
    assert "videoUrl.startsWith('/api/videos/')" in chat_js
    assert "`${videoUrl}/thumbnail`" in chat_js
    assert 'poster="${videoPosterUrl}"' in chat_js


def test_thumbnail_route_generates_and_serves_first_frame(tmp_path):
    video = tmp_path / "generated.mp4"
    video.write_bytes(b"fake-video")

    def fake_run(command, **_kwargs):
        assert command[0] == "ffmpeg"
        Path(command[-1]).write_bytes(b"fake-jpeg")
        return SimpleNamespace(returncode=0, stderr=b"")

    with app.test_request_context("/api/videos/generated.mp4/thumbnail"), patch.object(
        api, "VIDEOS_PATH", tmp_path
    ), patch("subprocess.run", side_effect=fake_run) as run:
        response = api.serve_video_thumbnail("generated.mp4")
        response.direct_passthrough = False
        response_data = response.get_data()

    assert response_data == b"fake-jpeg"
    assert response.mimetype == "image/jpeg"
    run.assert_called_once()


def test_thumbnail_route_reuses_fresh_canvas_cache(tmp_path):
    video = tmp_path / "generated.mp4"
    video.write_bytes(b"fake-video")
    thumbnail_dir = tmp_path / ".thumbnails"
    thumbnail_dir.mkdir()
    thumbnail = thumbnail_dir / "generated.jpg"
    thumbnail.write_bytes(b"cached-jpeg")
    newer = video.stat().st_mtime + 5
    os.utime(thumbnail, (newer, newer))

    with app.test_request_context("/api/videos/generated.mp4/thumbnail"), patch.object(
        api, "VIDEOS_PATH", tmp_path
    ), patch("subprocess.run") as run:
        response = api.serve_video_thumbnail("generated.mp4")
        response.direct_passthrough = False
        response_data = response.get_data()

    assert response_data == b"cached-jpeg"
    run.assert_not_called()
