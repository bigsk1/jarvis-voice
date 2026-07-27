"""Contract tests for the generated-music FastAPI route."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.routes import generated_music
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
    with pytest.raises(
        ValueError,
        match="Unsupported music provider 'suno'",
    ):
        generate_music_tool.resolve_music_provider("suno")


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

    health = asyncio.run(generated_music.generated_music_health())
    response = asyncio.run(
        generated_music.get_generated_music(track.name)
    )

    assert health["audio_count"] == 1
    assert health["configured_provider"] == "elevenlabs"
    assert health["provider_supported"] is True
    assert health["credential_configured"] is True
    assert health["supported_providers"] == ["elevenlabs"]
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


def test_generated_music_router_is_registered_and_manifest_is_provider_ready():
    server_source = (PROJECT_ROOT / "api" / "server.py").read_text()
    routes_source = (PROJECT_ROOT / "api" / "routes" / "__init__.py").read_text()
    manifest = json.loads(
        (PROJECT_ROOT / "skills" / "generate_music.tool.json").read_text()
    )

    assert "generated_music_router" in routes_source
    assert "app.include_router(generated_music_router)" in server_source
    assert manifest["parameters"]["properties"]["provider"]["enum"] == [
        "elevenlabs"
    ]
    assert manifest["availability"]["provider_setting"] == "MUSIC_TOOL_PROVIDER"
    assert manifest["availability"]["provider_default"] == "elevenlabs"
