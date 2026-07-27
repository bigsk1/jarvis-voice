"""Contract tests for the generated-music FastAPI route."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.routes import generated_music
from lib import rate_limiter
from skills import generate_music as generate_music_tool


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_generate_route_passes_provider_neutral_options_to_tool():
    request = generated_music.GenerateRequest(
        prompt="A hopeful cinematic theme",
        title="New Horizon",
        duration_seconds=90,
        genre="cinematic",
        mood="hopeful",
        instrumental=True,
        tempo="110 BPM",
        output_format="opus_high",
        provider="elevenlabs",
        mode="local",
        composition_plan={
            "global_styles": ["cinematic", "orchestral"],
            "sections": [
                {
                    "section_name": "intro",
                    "duration_seconds": 30,
                    "styles": ["soft strings"],
                },
                {
                    "section_name": "theme",
                    "duration_seconds": 60,
                    "styles": ["full orchestra"],
                    "lyrics": [],
                },
            ],
        },
    )
    completed = SimpleNamespace(
        returncode=0,
        stdout=json.dumps({
            "ok": True,
            "speech": "Generated music",
            "data": {
                "provider": "ElevenLabs",
                "model": "music_v1",
                "saved": {
                    "filename": "music_new_horizon_20260726_230000.opus",
                },
            },
        }),
        stderr="",
    )

    with patch.object(
        generated_music.subprocess,
        "run",
        return_value=completed,
    ) as run:
        response = asyncio.run(generated_music.generate_music(request))

    command = run.call_args.args[0]
    payload = json.loads(command[2])
    assert command[0] == sys.executable
    assert payload == {
        "prompt": "A hopeful cinematic theme",
        "duration_seconds": 90,
        "instrumental": True,
        "output_format": "opus_high",
        "save": True,
        "title": "New Horizon",
        "genre": "cinematic",
        "mood": "hopeful",
        "tempo": "110 BPM",
        "composition_plan": {
            "global_styles": ["cinematic", "orchestral"],
            "sections": [
                {
                    "section_name": "intro",
                    "duration_seconds": 30,
                    "styles": ["soft strings"],
                    "avoid_styles": [],
                    "lyrics": [],
                },
                {
                    "section_name": "theme",
                    "duration_seconds": 60,
                    "styles": ["full orchestra"],
                    "avoid_styles": [],
                    "lyrics": [],
                },
            ],
        },
        "provider": "elevenlabs",
    }
    assert run.call_args.kwargs["env"]["JARVIS_MODE"] == "local"
    assert run.call_args.kwargs["timeout"] == 600
    assert response.ok is True
    assert response.data["provider"] == "ElevenLabs"
    assert (
        response.audio_url
        == "/api/generated-music/music_new_horizon_20260726_230000.opus"
    )


def test_generate_route_preserves_structured_tool_error():
    request = generated_music.GenerateRequest(
        prompt="Test",
        provider="future-provider",
    )
    completed = SimpleNamespace(
        returncode=1,
        stdout=json.dumps({
            "ok": False,
            "speech": "Failed to generate music",
            "error": "Unsupported music provider 'future-provider'",
        }),
        stderr="",
    )

    with patch.object(
        generated_music.subprocess,
        "run",
        return_value=completed,
    ):
        response = asyncio.run(generated_music.generate_music(request))

    assert response.ok is False
    assert response.error == "Unsupported music provider 'future-provider'"
    assert response.speech == "Failed to generate music"


def test_music_request_validates_formats_and_composition_duration():
    with pytest.raises(ValidationError, match="unsupported output_format"):
        generated_music.GenerateRequest(
            prompt="Test",
            output_format="windows_media_audio",
        )

    with pytest.raises(
        ValidationError,
        match="composition plan duration cannot exceed 600 seconds",
    ):
        generated_music.GenerateRequest(
            prompt="Test",
            composition_plan={
                "sections": [
                    {
                        "section_name": f"part-{index}",
                        "duration_seconds": 120,
                    }
                    for index in range(6)
                ],
            },
        )


def test_music_provider_resolution_is_explicit(monkeypatch):
    monkeypatch.setattr(
        generate_music_tool,
        "get_config_value",
        lambda key, default=None: (
            "elevenlabs" if key == "MUSIC_TOOL_PROVIDER" else default
        ),
    )

    assert generate_music_tool.resolve_music_provider() == "elevenlabs"
    assert (
        generate_music_tool.resolve_music_provider("ELEVENLABS")
        == "elevenlabs"
    )
    assert generate_music_tool.resolve_music_provider("GEMINI") == "gemini"
    with pytest.raises(
        ValueError,
        match="Unsupported music provider 'suno'",
    ):
        generate_music_tool.resolve_music_provider("suno")


def test_jarvis_web_music_provider_override_outranks_tool_argument(
    monkeypatch,
):
    monkeypatch.setenv(
        "JARVIS_OVERRIDE_MUSIC_TOOL_PROVIDER",
        "gemini",
    )
    monkeypatch.setattr(
        generate_music_tool,
        "get_config_value",
        lambda key, default=None: (
            "elevenlabs" if key == "MUSIC_TOOL_PROVIDER" else default
        ),
    )

    assert generate_music_tool.resolve_music_provider("elevenlabs") == "gemini"


def test_gemini_adapter_normalizes_fixed_clip_contract(monkeypatch):
    audio_bytes = b"ID3" + (b"music" * 300)
    captured = {}

    class FakeInteractions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                id="interaction-123",
                status="completed",
                output_audio=SimpleNamespace(
                    data=base64.b64encode(audio_bytes).decode(),
                    mime_type="audio/mpeg",
                ),
                output_text="Original instrumental",
            )

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.interactions = FakeInteractions()

    monkeypatch.setattr(
        generate_music_tool,
        "get_config_value",
        lambda key, default=None: {
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MUSIC_MODEL": "lyria-3-clip-preview",
        }.get(key, default),
    )
    import google

    monkeypatch.setattr(
        google,
        "genai",
        SimpleNamespace(Client=FakeClient),
        raising=False,
    )

    result = generate_music_tool.generate_music(
        prompt="A bright synthwave drive through a neon city",
        duration_seconds=75,
        genre="electronic",
        mood="hopeful",
        instrumental=True,
        tempo="120 BPM",
        output_format="mp3_high",
        provider="gemini",
    )

    assert captured["client"] == {"api_key": "test-key"}
    assert captured["model"] == "lyria-3-clip-preview"
    assert captured["timeout"] == 300
    assert "Instrumental only, no vocals." in captured["input"]
    assert result["audio_bytes"] == audio_bytes
    assert result["provider"] == "Google Gemini"
    assert result["duration_ms"] == 30000
    assert result["requested_duration_ms"] == 75000
    assert result["output_format"] == "mp3"
    assert result["requested_output_format"] == "mp3_high"
    assert result["synthid_watermarked"] is True


def test_gemini_adapter_rejects_unsupported_contract_options(monkeypatch):
    monkeypatch.setattr(
        generate_music_tool,
        "get_config_value",
        lambda key, default=None: {
            "GEMINI_API_KEY": "test-key",
        }.get(key, default),
    )

    with pytest.raises(ValueError, match="returns MP3 only"):
        generate_music_tool.generate_music(
            prompt="Original ambient music",
            output_format="opus_high",
            provider="gemini",
        )
    with pytest.raises(ValueError, match="only by the ElevenLabs"):
        generate_music_tool.generate_with_composition_plan(
            title="Structured song",
            sections=[{"section_name": "intro", "duration_seconds": 30}],
            provider="gemini",
        )


def test_gemini_pro_adapter_prompts_for_approximate_full_song_duration(
    monkeypatch,
):
    captured = {}
    audio_bytes = b"ID3" + (b"full-song" * 200)

    class FakeInteractions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                id="interaction-pro-123",
                status="completed",
                output_audio=SimpleNamespace(
                    data=base64.b64encode(audio_bytes).decode(),
                    mime_type="audio/mpeg",
                ),
                output_text="Verse, chorus, bridge",
            )

    class FakeClient:
        def __init__(self, **_kwargs):
            self.interactions = FakeInteractions()

    monkeypatch.setattr(
        generate_music_tool,
        "get_config_value",
        lambda key, default=None: {
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MUSIC_MODEL": "lyria-3-pro-preview",
        }.get(key, default),
    )
    import google

    monkeypatch.setattr(
        google,
        "genai",
        SimpleNamespace(Client=FakeClient),
        raising=False,
    )

    result = generate_music_tool.generate_music(
        prompt="An original pop song with two verses, choruses, and a bridge",
        duration_seconds=150,
        provider="gemini",
    )

    assert captured["model"] == "lyria-3-pro-preview"
    assert "approximately 150 seconds" in captured["input"]
    assert "coherent musical ending" in captured["input"]
    assert result["duration_ms"] == 150000
    assert result["duration_is_estimate"] is True
    assert result["requested_duration_ms"] == 150000


def test_elevenlabs_v2_uses_catalog_pin_and_chunk_plan(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200
        content = b"generated-audio" * 100
        headers = {"x-song-id": "song-123"}

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(
        generate_music_tool,
        "get_config_value",
        lambda key, default=None: {
            "ELEVENLABS_API_KEY": "test-key",
            "ELEVENLABS_MUSIC_MODEL": "music_v2",
        }.get(key, default),
    )
    monkeypatch.setattr(generate_music_tool.requests, "post", fake_post)

    simple = generate_music_tool.generate_music(
        prompt="Original cinematic theme",
        provider="elevenlabs",
    )
    planned = generate_music_tool.generate_with_composition_plan(
        title="New Dawn",
        sections=[{
            "section_name": "verse",
            "duration_seconds": 20,
            "styles": ["warm strings"],
            "avoid_styles": ["distorted"],
            "lyrics": ["A new day begins"],
        }],
        global_styles=["cinematic"],
        provider="elevenlabs",
    )

    assert calls[0][1]["json"]["model_id"] == "music_v2"
    plan_payload = calls[1][1]["json"]
    assert plan_payload["model_id"] == "music_v2"
    assert "respect_sections_durations" not in plan_payload
    assert plan_payload["composition_plan"] == {
        "chunks": [{
            "text": "[verse]\nA new day begins",
            "duration_ms": 20000,
            "positive_styles": ["cinematic", "warm strings"],
            "negative_styles": ["distorted"],
            "context_adherence": "high",
        }],
    }
    assert simple["model"] == "music_v2"
    assert planned["model"] == "music_v2"


def test_generated_music_health_and_file_serving(tmp_path, monkeypatch):
    track = tmp_path / "music_test_20260726_230000.mp3"
    track.write_bytes(b"fake-mp3")
    monkeypatch.setattr(generated_music, "GENERATED_MUSIC_DIR", tmp_path)
    monkeypatch.setattr(
        generated_music,
        "get_config_value",
        lambda key, default=None: {
            "MUSIC_TOOL_PROVIDER": "elevenlabs",
            "ELEVENLABS_API_KEY": "configured",
        }.get(key, default),
    )
    monkeypatch.setattr(
        generated_music,
        "resolve_music_model",
        lambda provider: "music_v1" if provider == "elevenlabs" else None,
    )

    health = asyncio.run(generated_music.generated_music_health())
    response = asyncio.run(
        generated_music.get_generated_music(track.name)
    )

    assert health["audio_count"] == 1
    assert health["configured_provider"] == "elevenlabs"
    assert health["provider_supported"] is True
    assert health["credential_configured"] is True
    assert health["configured_model"] == "music_v1"
    assert health["model_metadata"]["id"] == "music_v1"
    assert health["supported_providers"] == ["elevenlabs", "gemini"]
    assert response.path == track
    assert response.media_type == "audio/mpeg"
    assert response.headers["content-disposition"].startswith("inline;")

    outside = tmp_path.parent / "outside.mp3"
    outside.write_bytes(b"outside")
    linked = tmp_path / "linked.mp3"
    linked.symlink_to(outside)
    with pytest.raises(HTTPException) as error:
        asyncio.run(generated_music.get_generated_music(linked.name))
    assert error.value.status_code == 404


def test_generated_music_health_reports_gemini_pro_catalog_metadata(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(generated_music, "GENERATED_MUSIC_DIR", tmp_path)
    monkeypatch.setattr(
        generated_music,
        "get_config_value",
        lambda key, default=None: {
            "MUSIC_TOOL_PROVIDER": "gemini",
            "GEMINI_API_KEY": "configured",
        }.get(key, default),
    )
    monkeypatch.setattr(
        generated_music,
        "resolve_music_model",
        lambda provider: "lyria-3-pro-preview",
    )

    health = asyncio.run(generated_music.generated_music_health())

    assert health["configured_provider"] == "gemini"
    assert health["configured_model"] == "lyria-3-pro-preview"
    assert health["credential_configured"] is True
    assert health["model_metadata"]["pricing"] == {
        "unit": "request",
        "usd": 0.08,
    }
    assert "full_length" in health["model_metadata"]["capabilities"]


def test_generated_music_router_exposes_expected_routes():
    routes = {
        (route.path, tuple(sorted(route.methods or [])))
        for route in generated_music.router.routes
    }

    assert (
        "/api/generated-music/generate",
        ("POST",),
    ) in routes
    assert (
        "/api/generated-music/health",
        ("GET",),
    ) in routes
    assert (
        "/api/generated-music/{filename}",
        ("GET",),
    ) in routes


def test_generated_music_has_dedicated_rate_limit_bucket(monkeypatch):
    calls = []

    def fake_get_int(key, default):
        calls.append((key, default))
        return default

    monkeypatch.setattr("lib.config_loader.get_int", fake_get_int)

    assert (
        rate_limiter._bucket_for_path("/api/generated-music/generate")
        == "generated-music"
    )
    assert rate_limiter._rpm_for_bucket("generated-music") == 10
    assert calls == [("API_RATE_LIMIT_GENERATED_MUSIC_PER_MINUTE", -1)]


def test_generated_music_router_is_registered_and_manifest_is_provider_ready():
    server_source = (PROJECT_ROOT / "api" / "server.py").read_text()
    routes_source = (PROJECT_ROOT / "api" / "routes" / "__init__.py").read_text()
    manifest = json.loads(
        (PROJECT_ROOT / "skills" / "generate_music.tool.json").read_text()
    )

    assert "generated_music_router" in routes_source
    assert "app.include_router(generated_music_router)" in server_source
    assert manifest["parameters"]["properties"]["provider"]["enum"] == [
        "elevenlabs",
        "gemini",
    ]
    assert manifest["availability"]["provider_setting"] == "MUSIC_TOOL_PROVIDER"
    assert manifest["availability"]["provider_default"] == "elevenlabs"
    assert manifest["availability"]["provider_requirements"]["gemini"] == {
        "all_of_env": ["GEMINI_API_KEY"]
    }
