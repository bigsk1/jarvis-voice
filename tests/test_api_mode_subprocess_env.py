"""Regression coverage for request-mode subprocess environments."""

from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.routes import generated_images, generated_music, generated_videos, voice

config_loader = sys.modules["config_loader"]


@pytest.mark.parametrize(
    ("request_type", "kwargs"),
    (
        (
            generated_images.GenerateRequest,
            {"prompt": "test image", "mode": "hybrid"},
        ),
        (
            generated_music.GenerateRequest,
            {"prompt": "test music", "mode": "hybrid"},
        ),
        (
            generated_videos.GenerateRequest,
            {"prompt": "test video", "mode": "hybrid"},
        ),
        (
            voice.SpeakRequest,
            {"message": "test voice", "mode": "hybrid"},
        ),
    ),
    ids=("image", "music", "video", "voice"),
)
def test_request_models_reject_unknown_modes(request_type, kwargs):
    with pytest.raises(ValidationError):
        request_type(**kwargs)


@pytest.fixture
def isolated_mode_configs(monkeypatch):
    configs = {
        "cloud": {
            "CLOUD_ONLY_SENTINEL": "cloud-value",
            "TTS_PROVIDER": "elevenlabs",
        },
        "local": {
            "LOCAL_ONLY_SENTINEL": "local-value",
            "TTS_PROVIDER": "kokoro",
        },
    }
    monkeypatch.setattr(
        config_loader,
        "_load_mode_config",
        lambda mode: dict(configs[mode]),
    )
    monkeypatch.setenv("CLOUD_ONLY_SENTINEL", "stale-cloud-value")
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")


def _successful_tool_result():
    return SimpleNamespace(
        returncode=0,
        stdout=json.dumps({"ok": True, "data": {}}),
        stderr="",
    )


def _child_environment_summary(env):
    return {
        "mode": env.get("JARVIS_MODE"),
        "local_value": env.get("LOCAL_ONLY_SENTINEL"),
        "cloud_value_present": "CLOUD_ONLY_SENTINEL" in env,
    }


def _assert_local_child_environment(env):
    assert _child_environment_summary(env) == {
        "mode": "local",
        "local_value": "local-value",
        "cloud_value_present": False,
    }


def test_generated_media_routes_export_isolated_request_mode_environment(
    monkeypatch,
    isolated_mode_configs,
):
    child_environments = []

    def capture_run(command, **kwargs):
        child_environments.append(dict(kwargs["env"]))
        return _successful_tool_result()

    monkeypatch.setattr(generated_images.subprocess, "run", capture_run)

    requests = (
        (
            generated_images.generate_image,
            generated_images.GenerateRequest(prompt="test image", mode="local"),
        ),
        (
            generated_music.generate_music,
            generated_music.GenerateRequest(prompt="test music", mode="local"),
        ),
        (
            generated_videos.generate_video,
            generated_videos.GenerateRequest(prompt="test video", mode="local"),
        ),
    )

    for generate, request in requests:
        response = asyncio.run(generate(request))
        assert response.ok is True

    assert len(child_environments) == 3
    for env in child_environments:
        _assert_local_child_environment(env)


def test_voice_route_exports_request_mode_environment_before_overrides(
    monkeypatch,
    isolated_mode_configs,
):
    child_environment = {}

    def capture_run(command, **kwargs):
        child_environment.update(kwargs["env"])
        return _successful_tool_result()

    monkeypatch.setattr(voice.subprocess, "run", capture_run)

    response = asyncio.run(
        voice.speak(voice.SpeakRequest(message="test voice", mode="local"))
    )

    assert response["ok"] is True
    assert response["provider"] == "kokoro"
    _assert_local_child_environment(child_environment)
