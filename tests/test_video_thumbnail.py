"""Atomic video-poster publication through the Web and Canvas routes."""

import importlib
import io
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest
from flask import Flask
from PIL import Image
from server_package_utils import load_canvas_server_package, load_server_package


@pytest.fixture
def jpeg_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (16, 12), "navy").save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture(params=["web", "canvas"])
def thumbnail_route(request, monkeypatch, tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    if request.param == "web":
        alias = "thumbnail_atomic_web_test_server"
        load_server_package(alias, project_root / "jarvis-web" / "server")
        module = importlib.import_module(f"{alias}.routes.api")
        monkeypatch.setattr(module, "VIDEOS_PATH", tmp_path)
        blueprint = module.api_bp
        url = "/api/videos/generated.mp4/thumbnail"
    else:
        alias = "thumbnail_atomic_canvas_test_server"
        load_canvas_server_package(alias)
        module = importlib.import_module(f"{alias}.routes.video_gallery")
        monkeypatch.setattr(module, "GENERATED_VIDEOS_DIR", tmp_path)
        monkeypatch.setattr(module, "THUMBNAIL_CACHE_DIR", tmp_path / ".thumbnails")
        blueprint = module.video_gallery_bp
        url = "/api/gallery/videos/generated.mp4/thumbnail"

    video = tmp_path / "generated.mp4"
    video.write_bytes(b"test-owned-video")
    app = Flask(f"thumbnail-{request.param}")
    app.register_blueprint(blueprint)
    return SimpleNamespace(
        client=app.test_client(),
        url=url,
        video=video,
        cache=tmp_path / ".thumbnails",
        thumbnail=tmp_path / ".thumbnails" / "generated.jpg",
    )


def test_timeout_does_not_publish_partial_image_and_next_request_retries(
    thumbnail_route, monkeypatch, jpeg_bytes
):
    route = thumbnail_route
    attempts = []

    def run(command, **kwargs):
        output = Path(command[-1])
        attempts.append(output)
        if len(attempts) == 1:
            output.write_bytes(b"\xff\xd8partial-jpeg")
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        output.write_bytes(jpeg_bytes)
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(subprocess, "run", run)
    assert route.client.get(route.url).status_code == 500
    assert not route.thumbnail.exists()
    assert list(route.cache.iterdir()) == []

    response = route.client.get(route.url)
    assert response.status_code == 200
    assert response.mimetype == "image/jpeg"
    assert response.data == jpeg_bytes
    assert len(attempts) == 2
    assert route.thumbnail.read_bytes() == jpeg_bytes
    assert route.video.read_bytes() == b"test-owned-video"


@pytest.mark.parametrize("outcome", ["nonzero", "empty", "truncated", "invalid-scan"])
def test_failed_encoder_output_is_not_cached(thumbnail_route, monkeypatch, jpeg_bytes, outcome):
    route = thumbnail_route

    def run(command, **_kwargs):
        output = Path(command[-1])
        # A JPEG header and end marker do not establish that it can be decoded.
        if outcome == "truncated":
            data = jpeg_bytes[:100] + b"\xff\xd9"
        elif outcome == "invalid-scan":
            scan_start = jpeg_bytes.index(b"\xff\xda")
            damaged = bytearray(jpeg_bytes)
            damaged[scan_start + 6] = 255  # Reference nonexistent Huffman tables.
            data = bytes(damaged)
        else:
            data = b""
        output.write_bytes(data)
        return SimpleNamespace(returncode=1 if outcome == "nonzero" else 0, stderr=b"error")

    monkeypatch.setattr(subprocess, "run", run)
    assert route.client.get(route.url).status_code == 500
    assert not route.thumbnail.exists()
    assert list(route.cache.iterdir()) == []


@pytest.mark.parametrize(
    "failure",
    ["encoder", "filesystem", "timeout", "timeout-text", "timeout-empty", "timeout-invalid-utf8"],
)
def test_public_canvas_thumbnail_errors_hide_server_details(monkeypatch, tmp_path, capsys, failure):
    alias = "thumbnail_error_canvas_test_server"
    load_canvas_server_package(alias)
    app_module = importlib.import_module(f"{alias}.app")
    routes = importlib.import_module(f"{alias}.routes.video_gallery")
    helper = importlib.import_module("video_thumbnail")
    monkeypatch.setattr(app_module, "load_config", lambda _mode: None)
    monkeypatch.setattr(app_module, "setup_error_logging", lambda *_args: None)
    monkeypatch.setattr(app_module, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(app_module, "get_token_from_request", lambda _request: None)
    monkeypatch.setattr(app_module, "verify_token", lambda _token: False)
    monkeypatch.setattr(routes, "GENERATED_VIDEOS_DIR", tmp_path)
    monkeypatch.setattr(routes, "THUMBNAIL_CACHE_DIR", tmp_path / ".thumbnails")
    video = tmp_path / "generated.mp4"
    video.write_bytes(b"invalid-video")
    diagnostic = f"{video}: Invalid data found when processing input"
    is_timeout = failure.startswith("timeout")

    if failure == "filesystem":
        def fail_thumbnail(*_args):
            raise OSError(diagnostic)
        monkeypatch.setattr(helper, "get_video_thumbnail", fail_thumbnail)
    else:
        def fail_encoder(command, **kwargs):
            if is_timeout:
                stderr = diagnostic.encode()
                if failure == "timeout-text":
                    stderr = diagnostic
                elif failure == "timeout-empty":
                    stderr = None
                elif failure == "timeout-invalid-utf8":
                    stderr = b"\xff" + stderr
                raise subprocess.TimeoutExpired(command, kwargs["timeout"], stderr=stderr)
            return SimpleNamespace(returncode=1, stderr=diagnostic.encode())
        monkeypatch.setattr(subprocess, "run", fail_encoder)

    client = app_module.create_app().test_client()
    # Auth is enabled, but the gallery thumbnail is deliberately public.
    assert client.get("/video-gallery").status_code == 302
    response = client.get("/api/gallery/videos/generated.mp4/thumbnail")
    body = response.get_data(as_text=True)
    assert response.status_code == 500
    expected = "Thumbnail generation timed out" if is_timeout else "Failed to generate video thumbnail"
    assert expected in body
    assert str(video) not in body
    assert "Invalid data found when processing input" not in body
    output = capsys.readouterr()
    logged = output.out + output.err
    if failure != "timeout-empty":
        assert diagnostic in logged
    if is_timeout:
        assert "generated.mp4" in logged
        assert "timed out" in logged
        assert "10" in logged


@pytest.mark.parametrize("corruption", ["truncated", "invalid-scan"])
def test_preexisting_corrupt_cache_is_regenerated(
    thumbnail_route, monkeypatch, jpeg_bytes, corruption
):
    route = thumbnail_route
    route.cache.mkdir()
    if corruption == "invalid-scan":
        scan_start = jpeg_bytes.index(b"\xff\xda")
        damaged = bytearray(jpeg_bytes)
        damaged[scan_start + 6] = 255
        corrupt_bytes = bytes(damaged)
    else:
        corrupt_bytes = b"\xff\xd8partial-jpeg"
    route.thumbnail.write_bytes(corrupt_bytes)
    fresh = route.video.stat().st_mtime + 5
    os.utime(route.thumbnail, (fresh, fresh))
    attempts = []

    def run(command, **_kwargs):
        attempts.append(command)
        Path(command[-1]).write_bytes(jpeg_bytes)
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(subprocess, "run", run)
    response = route.client.get(route.url)
    assert response.status_code == 200
    assert response.data == jpeg_bytes
    assert len(attempts) == 1


def test_failed_refresh_preserves_previous_valid_thumbnail(thumbnail_route, monkeypatch, jpeg_bytes):
    route = thumbnail_route
    route.cache.mkdir()
    route.thumbnail.write_bytes(jpeg_bytes)
    older = route.video.stat().st_mtime - 5
    os.utime(route.thumbnail, (older, older))

    def run(command, **kwargs):
        Path(command[-1]).write_bytes(b"\xff\xd8partial-jpeg")
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", run)
    assert route.client.get(route.url).status_code == 500
    assert route.thumbnail.read_bytes() == jpeg_bytes
    assert list(route.cache.iterdir()) == [route.thumbnail]


def test_failed_writer_does_not_delete_successful_sibling(thumbnail_route, monkeypatch, jpeg_bytes):
    route = thumbnail_route

    def run(command, **kwargs):
        Path(command[-1]).write_bytes(b"\xff\xd8partial-jpeg")
        # Another request publishes a valid result while this encoder is running.
        route.thumbnail.write_bytes(jpeg_bytes)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", run)
    assert route.client.get(route.url).status_code == 500
    assert route.thumbnail.read_bytes() == jpeg_bytes
    assert list(route.cache.iterdir()) == [route.thumbnail]


def test_fresh_valid_cache_does_not_run_encoder(thumbnail_route, monkeypatch, jpeg_bytes):
    route = thumbnail_route
    route.cache.mkdir()
    route.thumbnail.write_bytes(jpeg_bytes)
    fresh = route.video.stat().st_mtime + 5
    os.utime(route.thumbnail, (fresh, fresh))

    def unexpected_run(*_args, **_kwargs):
        pytest.fail("A fresh, valid thumbnail should be reused")

    monkeypatch.setattr(subprocess, "run", unexpected_run)
    response = route.client.get(route.url)
    assert response.status_code == 200
    assert response.data == jpeg_bytes


def test_concurrent_writers_use_unique_files_and_publish_complete_images(
    tmp_path, monkeypatch, jpeg_bytes
):
    helper = importlib.import_module("video_thumbnail")
    video = tmp_path / "generated.mp4"
    video.write_bytes(b"test-owned-video")
    thumbnail = tmp_path / ".thumbnails" / "generated.jpg"
    barrier = Barrier(2)
    lock = Lock()
    output_paths = []

    def run(command, **_kwargs):
        output = Path(command[-1])
        output.write_bytes(b"\xff\xd8partial-jpeg")
        with lock:
            output_paths.append(output)
        assert not thumbnail.exists()
        barrier.wait(timeout=5)
        output.write_bytes(jpeg_bytes)
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(subprocess, "run", run)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(helper.get_video_thumbnail, video, thumbnail) for _ in range(2)]
        assert [future.result(timeout=10) for future in futures] == [thumbnail, thumbnail]
    assert len(set(output_paths)) == 2
    assert thumbnail not in output_paths
    assert thumbnail.read_bytes() == jpeg_bytes
    assert list(thumbnail.parent.iterdir()) == [thumbnail]


def test_actual_child_timeout_cleans_its_partial_output(tmp_path, monkeypatch):
    helper = importlib.import_module("video_thumbnail")
    video = tmp_path / "generated.mp4"
    video.write_bytes(b"test-owned-video")
    thumbnail = tmp_path / ".thumbnails" / "generated.jpg"
    real_run = subprocess.run
    timeouts = []

    def run(command, **kwargs):
        script = (
            "import pathlib,sys,time; "
            "pathlib.Path(sys.argv[1]).write_bytes(b'\\xff\\xd8partial-jpeg'); "
            "print('partial-written', flush=True); time.sleep(60)"
        )
        try:
            return real_run(
                [sys.executable, "-c", script, command[-1]], **kwargs
            )
        except subprocess.TimeoutExpired as error:
            timeouts.append(error)
            raise

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(subprocess.TimeoutExpired):
        helper.get_video_thumbnail(video, thumbnail, timeout=0.5)
    assert timeouts[0].stdout == b"partial-written\n"
    assert not thumbnail.exists()
    assert list(thumbnail.parent.iterdir()) == []
