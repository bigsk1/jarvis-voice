"""Slow FastAPI tools must let unrelated API requests run while callers wait."""

import asyncio
import importlib.util
import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from config_loader import config_scope, get_active_config_mode, get_config_value
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def slow_api(tmp_path, monkeypatch):
    """Load one real router with temporary storage, without the production app."""
    monkeypatch.syspath_prepend(str(ROOT / "skills"))
    routes = tmp_path / "api" / "routes"
    routes.mkdir(parents=True)
    scripts = tmp_path / "bin"
    scripts.mkdir()
    for name in ("say.sh", "say-local.sh"):
        (scripts / name).write_text("# Not executed by these tests.\n")

    def load(name):
        path = routes / f"{name}.py"
        shutil.copyfile(ROOT / "api" / "routes" / path.name, path)
        if name == "generated_videos":
            # The video launcher enforces its real reviewed child-env policy.
            skills = tmp_path / "skills"
            skills.mkdir()
            shutil.copyfile(ROOT / "skills" / "generate_video.tool.json", skills / "generate_video.tool.json")
        alias = f"_slow_api_concurrency_{name}"
        spec = importlib.util.spec_from_file_location(alias, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, alias, module)
        with config_scope("cloud", overrides={"STASH_DIR": str(tmp_path / "stash")}):
            spec.loader.exec_module(module)
        app = FastAPI()
        app.include_router(module.router)

        @app.get("/api/alert-probe")
        async def alert_probe():
            return {"responsive": True}

        return module, app

    return load


def _call_while_blocked(app, entered, release, method, path, body=None):
    """Release the fake tool in every outcome, including regression failures."""
    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            pending = asyncio.create_task(client.request(method, path, json=body))
            try:
                assert await asyncio.to_thread(entered.wait, 10), "Tool was not invoked"
                probe = await asyncio.wait_for(client.get("/api/alert-probe"), 3)
                assert probe.status_code == 200
                assert probe.json() == {"responsive": True}
                assert not pending.done(), "Slow tool blocked the unrelated request"
            finally:
                release.set()
                response = await asyncio.wait_for(pending, 10)
            assert response.status_code == 200
            return response.json()

    return asyncio.run(exercise())


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("endpoint", ["speak", "announce"])
def test_speech_does_not_block_alert_requests(slow_api, monkeypatch, mode, endpoint):
    module, app = slow_api("voice")
    entered, release = threading.Event(), threading.Event()
    calls = []
    loop_thread = threading.get_ident()

    def blocking_run(command, **kwargs):
        calls.append((command, kwargs, threading.get_ident(), get_active_config_mode(),
                      get_config_value("API_CONCURRENCY_SETTING")))
        entered.set()
        assert release.wait(10), "No concurrent request released the controlled speech"
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(module, "subprocess", SimpleNamespace(
        run=blocking_run, TimeoutExpired=subprocess.TimeoutExpired))
    body = {"message": "Camera activity recorded."}
    if endpoint == "speak":
        body.update(mode=mode, tts_provider="openai", voice="test-voice")
    with config_scope(mode, overrides={"TTS_PROVIDER": "openai",
                                       "API_CONCURRENCY_SETTING": "scoped-value"}):
        response = _call_while_blocked(
            app, entered, release, "POST", f"/api/voice/{endpoint}", body)
    assert response["ok"] is True
    assert response["text"] == body["message"]
    assert response["provider"] == "openai"
    assert response["voice"] == ("test-voice" if endpoint == "speak" else None)
    assert len(calls) == 1
    command, kwargs, thread_id, actual_mode, setting = calls[0]
    assert Path(command[0]).name == ("say-local.sh" if mode == "local" else "say.sh")
    assert command[1] == body["message"]
    assert kwargs["timeout"] == 30
    assert kwargs["capture_output"] is True and kwargs["text"] is True
    assert kwargs["env"]["JARVIS_MODE"] == mode
    if endpoint == "speak":
        assert kwargs["env"]["TTS_PROVIDER_OVERRIDE"] == "openai"
        assert kwargs["env"]["OPENAI_VOICE_OVERRIDE"] == "test-voice"
    assert thread_id != loop_thread
    assert (actual_mode, setting) == (mode, "scoped-value")


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("endpoint", ["search", "status"])
def test_qmd_wait_does_not_block_alert_requests(slow_api, monkeypatch, mode, endpoint):
    module, app = slow_api("docs")
    entered, release = threading.Event(), threading.Event()
    calls = []
    loop_thread = threading.get_ident()

    def blocking_run(command, **kwargs):
        calls.append((command, kwargs, threading.get_ident(), get_active_config_mode(),
                      get_config_value("API_CONCURRENCY_SETTING")))
        entered.set()
        assert release.wait(10), "No concurrent request released the controlled docs command"
        output = (
            "Index ready\n" + json.dumps([{
                "file": "qmd://jarvis-docs/MEMORY_SYSTEM.md", "title": "Memory",
                "score": 0.9, "snippet": "Memory documentation excerpt.",
            }])
            if endpoint == "search"
            else "Total: 17 files\nVectors: 42\nUpdated: a controlled fixture\n"
        )
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(module, "subprocess", SimpleNamespace(
        run=blocking_run, TimeoutExpired=subprocess.TimeoutExpired))
    monkeypatch.setattr(module, "get_docs_search_rate_limit_per_minute", lambda: 7)
    with config_scope(mode, overrides={"API_CONCURRENCY_SETTING": "scoped-value"}):
        response = _call_while_blocked(
            app, entered, release, "POST" if endpoint == "search" else "GET",
            f"/api/docs/{endpoint}",
            {"query": "How is memory stored?", "topic": "memory", "limit": 2}
            if endpoint == "search" else None,
        )
    assert len(calls) == 1
    command, kwargs, thread_id, actual_mode, setting = calls[0]
    assert kwargs == {
        "capture_output": True, "text": True,
        "timeout": 90 if endpoint == "search" else 10,
        "cwd": str(module.PROJECT_ROOT),
    }
    assert thread_id != loop_thread
    assert (actual_mode, setting) == (mode, "scoped-value")
    if endpoint == "search":
        assert command == [
            "qmd", "vsearch", "How is memory stored?", "-n", "6",
            "--min-score", "0.35", "-c", "jarvis-docs", "--json",
        ]
        assert response["ok"] is True
        assert response["query"] == "How is memory stored?"
        assert response["topic"] == "memory"
        assert response["result_count"] == 1
        assert response["results"] == [{
            "title": "Memory", "path": "docs/MEMORY_SYSTEM.md", "score": 0.9,
            "content": "Memory documentation excerpt.",
        }]
        assert "Memory documentation excerpt." in response["documentation"]
    else:
        assert command == ["qmd", "status"]
        assert response == {
            "status": "healthy", "indexed_files": 17, "vectors": 42,
            "last_updated": "a controlled fixture", "collection": "jarvis-docs",
            "rate_limit": "7 requests per minute (POST /search only)",
        }


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("kind", ["images", "videos", "music"])
def test_generation_wait_does_not_block_alert_requests(slow_api, monkeypatch, mode, kind):
    module, app = slow_api(f"generated_{kind}")
    entered, release = threading.Event(), threading.Event()
    calls = []
    loop_thread = threading.get_ident()
    body = {"prompt": "A controlled synthetic generation.", "mode": mode, "save": False}
    if kind == "images":
        body.update(provider="gemini", image_size="4K", aspect_ratio="4:5",
                    reference_image="stash://fixture/reference", use_grounding=True)
        script, expected_timeout = "generate_image.py", 300
    elif kind == "videos":
        body.update(provider="gemini", duration=8, resolution="1080p", aspect_ratio="9:16",
                    image_url="stash://fixture/reference")
        script, expected_timeout = "generate_video.py", 600
    else:
        body.update(provider="elevenlabs", instrumental=True, title="Controlled track",
                    composition_plan={"global_styles": ["ambient"], "sections": [
                        {"section_name": "intro", "duration_seconds": 120},
                        {"section_name": "outro", "duration_seconds": 120},
                    ]})
        script, expected_timeout = "generate_music.py", 780
    data = {"provider": body["provider"], "saved": {"filename": f"fixture.{kind}"}}

    def blocking_run(command, **kwargs):
        calls.append((command, kwargs, threading.get_ident(), get_active_config_mode(),
                      get_config_value("API_CONCURRENCY_SETTING")))
        entered.set()
        assert release.wait(10), "No concurrent request released the controlled generation"
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({
            "ok": True, "speech": "Synthetic generation complete.", "data": data,
        }), stderr="")

    monkeypatch.setattr(module, "subprocess", SimpleNamespace(
        run=blocking_run, TimeoutExpired=subprocess.TimeoutExpired))
    with config_scope(mode, overrides={"API_CONCURRENCY_SETTING": "scoped-value"}):
        response = _call_while_blocked(
            app, entered, release, "POST", f"/api/generated-{kind}/generate", body)
    assert response["ok"] is True
    assert response["speech"] == "Synthetic generation complete."
    assert response["data"] == data
    if kind == "music":
        assert response["audio_url"] == "/api/generated-music/fixture.music"
    assert len(calls) == 1
    command, kwargs, thread_id, actual_mode, setting = calls[0]
    assert command[0] == (sys.executable if kind in {"music", "videos"} else "python3")
    assert Path(command[1]) == module.PROJECT_ROOT / "skills" / script
    args = json.loads(command[2])
    assert args["prompt"] == body["prompt"]
    assert args["provider"] == body["provider"]
    assert args["save"] is False
    if kind == "images":
        assert args["reference_image"] == body["reference_image"]
        assert args["image_size"] == "4K"
        assert args["use_grounding"] is True
    elif kind == "videos":
        assert args["image_url"] == body["image_url"]
        assert args["duration"] == 8 and args["resolution"] == "1080p"
    else:
        assert args["composition_plan"]["global_styles"] == ["ambient"]
        assert sum(section["duration_seconds"]
                   for section in args["composition_plan"]["sections"]) == 240
    assert kwargs["capture_output"] is True and kwargs["text"] is True
    assert kwargs["timeout"] == expected_timeout
    assert kwargs["cwd"] == str(module.PROJECT_ROOT)
    assert kwargs["env"]["JARVIS_MODE"] == mode
    if kind == "videos":
        assert kwargs["env"]["VIDEO_TOOL_PROVIDER"] == body["provider"]
        assert kwargs["env"]["JARVIS_RESTRICTED_TOOL_ENV"] == "1"
        assert "API_CONCURRENCY_SETTING" not in kwargs["env"]
        assert not Path(kwargs["env"]["HOME"]).exists()
    assert thread_id != loop_thread
    assert (actual_mode, setting) == (mode, "scoped-value")


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_optional_image_cdn_upload_does_not_block_alert_requests(slow_api, monkeypatch, mode):
    module, app = slow_api("generated_images")
    entered, release = threading.Event(), threading.Event()
    calls, uploads = [], []
    loop_thread = threading.get_ident()
    saved = {"filename": "fixture.png", "path": "data/generated_images/fixture.png"}

    def generated(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({
            "ok": True, "speech": "Image created.", "data": {"saved": saved},
        }), stderr="")

    def blocking_upload(*args, **kwargs):
        uploads.append((args, kwargs, threading.get_ident(), get_active_config_mode(),
                        get_config_value("API_CONCURRENCY_SETTING")))
        entered.set()
        assert release.wait(10), "No concurrent request released the controlled CDN upload"
        return {"ok": True, "url": "https://cdn.example/fixture", "image_id": "fixture-id"}

    monkeypatch.setattr(module, "subprocess", SimpleNamespace(
        run=generated, TimeoutExpired=subprocess.TimeoutExpired))
    monkeypatch.setitem(sys.modules, "upload_cloudflare", SimpleNamespace(upload_image=blocking_upload))
    with config_scope(mode, overrides={"API_CONCURRENCY_SETTING": "scoped-value"}):
        response = _call_while_blocked(
            app, entered, release, "POST", "/api/generated-images/generate",
            {"prompt": "Synthetic image", "mode": mode, "upload_to_cdn": True})
    assert response["ok"] is True
    assert response["cdn_url"] == "https://cdn.example/fixture"
    assert response["data"] == {
        "saved": saved, "cdn": {"url": "https://cdn.example/fixture", "image_id": "fixture-id"},
    }
    assert len(calls) == 1 and len(uploads) == 1
    args, kwargs, thread_id, actual_mode, setting = uploads[0]
    assert args == (str(module.PROJECT_ROOT / saved["path"]), "file")
    assert kwargs == {"uploader": "api", "category": "generated"}
    assert thread_id != loop_thread
    assert (actual_mode, setting) == (mode, "scoped-value")
    assert json.loads(module.CDN_CATALOG_FILE.read_text())["fixture.png"]["image_id"] == "fixture-id"
