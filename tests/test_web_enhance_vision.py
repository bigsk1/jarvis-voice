"""Regression test for vision-grounded Web prompt enhancement."""

import sys
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from flask import Flask


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))

from server_package_utils import load_server_package


load_server_package("jarvis_web_enhance_test", PROJECT_ROOT / "jarvis-web" / "server")

from jarvis_web_enhance_test import config as web_config
from jarvis_web_enhance_test.routes import api as api_module


def test_enhance_prompt_prioritizes_valid_music_hint_without_exposing_schema():
    app = Flask(__name__)
    app.register_blueprint(api_module.api_bp)
    captured = {}

    def enhance(message, system_prompt=None, max_tokens=None):
        captured.update({
            "message": message,
            "system_prompt": system_prompt,
            "max_tokens": max_tokens,
        })
        return (
            "Create an atmospheric electronic piece with warm analog synths, "
            "a gradual energy build, and an original hopeful vocal theme."
        )

    provider = SimpleNamespace(chat=enhance)
    tool_service = SimpleNamespace(
        get_tools_summary=lambda: [
            {
                "name": "generate_music",
                "description": (
                    "Generate AI music. Describe musical characteristics instead "
                    "of naming artists, copyrighted songs or lyrics, or requesting "
                    "voice imitation."
                ),
                "enabled": True,
                "available": True,
                "blocked": False,
                "parameters": {
                    "duration_seconds": {"type": "integer"},
                    "output_format": {"type": "string"},
                },
            },
            {
                "name": "unavailable_music",
                "description": "SHOULD_NOT_APPEAR",
                "enabled": False,
                "available": False,
                "blocked": False,
            },
        ]
    )

    with patch.object(
        web_config,
        "load_web_config",
        return_value={"cloud": {"llm_provider": "openai", "llm_model": "gpt-test"}},
    ), patch(
        "llm_provider.create_provider", return_value=provider
    ), patch.object(api_module, "get_tool_service", return_value=tool_service):
        response = app.test_client().post(
            "/api/enhance-prompt",
            json={
                "input": "make some spacey electronic music about exploration",
                "mode": "cloud",
                "tool_hints": ["generate_music", "unavailable_music", "missing_tool"],
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["tool_hints"] == ["generate_music"]
    assert payload["enhanced"].startswith("Create an atmospheric electronic piece")
    prompt = captured["system_prompt"]
    assert "## User-Selected Tool Context" in prompt
    assert "- generate_music: Generate AI music." in prompt
    assert "SHOULD_NOT_APPEAR" not in prompt
    assert "duration_seconds" not in prompt
    assert "output_format" not in prompt
    assert "Do not invent operational parameters" in prompt
    assert "Use qualitative tempo language rather than inventing an exact BPM" in prompt
    assert "Do not introduce artist/band names" in prompt


def test_enhance_prompt_can_infer_music_without_tool_hint():
    app = Flask(__name__)
    app.register_blueprint(api_module.api_bp)
    captured = {}

    def enhance(message, system_prompt=None, max_tokens=None):
        captured["system_prompt"] = system_prompt
        return "Create a calm ambient track with airy synth textures and a gentle emotional arc."

    provider = SimpleNamespace(chat=enhance)
    tool_service = SimpleNamespace(
        get_tools_summary=lambda: [
            {
                "name": "generate_music",
                "description": "Generate AI music, songs, instrumentals, jingles, beats, and soundtracks.",
                "enabled": True,
                "available": True,
                "blocked": False,
            }
        ]
    )

    with patch.object(
        web_config,
        "load_web_config",
        return_value={"cloud": {"llm_provider": "openai", "llm_model": "gpt-test"}},
    ), patch(
        "llm_provider.create_provider", return_value=provider
    ), patch.object(api_module, "get_tool_service", return_value=tool_service):
        response = app.test_client().post(
            "/api/enhance-prompt",
            json={
                "input": "generate calm music for stargazing",
                "mode": "cloud",
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["tool_hints"] == []
    assert "- generate_music: Generate AI music" in captured["system_prompt"]
    assert "## User-Selected Tool Context" not in captured["system_prompt"]
    assert "Enhance media creatively, not mechanically" in captured["system_prompt"]


def test_enhance_client_sends_parsed_tool_hints_separately_from_clean_input():
    chat_source = (
        PROJECT_ROOT / "jarvis-web" / "client" / "js" / "chat.js"
    ).read_text()
    enhance_start = chat_source.index("async _enhancePrompt()")
    enhance_end = chat_source.index("async _startRecording()", enhance_start)
    enhance_source = chat_source[enhance_start:enhance_end]

    assert "const inputToEnhance = parsedInput.message || input;" in enhance_source
    assert "tool_hints: toolHints" in enhance_source
    assert "this.selectedToolHints = toolHints;" in enhance_source


def test_enhance_prompt_uses_attached_image_with_ollama_cloud(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "upload_test.jpg").write_bytes(b"jpeg-image-bytes")
    api_module.WEB_DATA_PATH = tmp_path

    app = Flask(__name__)
    app.register_blueprint(api_module.api_bp)

    captured = {}

    def fake_analyze(images, prompt, **kwargs):
        captured.update({"images": images, "prompt": prompt, **kwargs})
        return "The visible holographic figure slowly turns its head while computer sounds play."

    with patch.object(
        web_config,
        "load_web_config",
        return_value={"cloud": {"llm_provider": "ollama", "llm_model": "minimax-m3:cloud"}},
    ), patch("vision_provider.analyze_images", side_effect=fake_analyze):
        response = app.test_client().post(
            "/api/enhance-prompt",
            json={
                "input": "make the head look around with computer sounds",
                "mode": "cloud",
                "image_action": "video",
                "image": {"filename": "upload_test.jpg", "url": "/api/uploads/upload_test.jpg"},
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["vision_grounded"] is True
    assert payload["provider"] == "ollama"
    assert payload["enhanced"].startswith("The visible holographic figure")
    assert captured["provider"] == "ollama"
    assert captured["model"] == "minimax-m3:cloud"
    assert captured["mode"] == "cloud"
    assert captured["images"]
    assert "Do not invent subjects" in captured["prompt"]
    assert "make the head look around with computer sounds" in captured["prompt"]


def test_enhance_falls_back_to_warned_text_only_when_model_rejects_images(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "upload_test.jpg").write_bytes(b"jpeg-image-bytes")
    api_module.WEB_DATA_PATH = tmp_path

    app = Flask(__name__)
    app.register_blueprint(api_module.api_bp)
    captured = {}

    def text_only_enhance(message, system_prompt=None, max_tokens=None):
        captured.update({"message": message, "system_prompt": system_prompt})
        return "Make the existing subject look around while preserving all unspecified visual details."

    provider = SimpleNamespace(chat=text_only_enhance)
    tool_service = SimpleNamespace(get_tools_summary=lambda: [])

    with patch.object(
        web_config,
        "load_web_config",
        return_value={
            "cloud": {"llm_provider": "ollama", "llm_model": "gpt-oss:120b-cloud"}
        },
    ), patch(
        "vision_provider.analyze_images",
        side_effect=RuntimeError("model does not support image input"),
    ), patch(
        "llm_provider.create_provider", return_value=provider
    ), patch.object(api_module, "get_tool_service", return_value=tool_service):
        response = app.test_client().post(
            "/api/enhance-prompt",
            json={
                "input": "make the head look around",
                "mode": "cloud",
                "image_action": "video",
                "image": {"filename": "upload_test.jpg"},
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["vision_grounded"] is False
    assert "used text only" in payload["vision_warning"]
    assert payload["enhanced"].startswith("Make the existing subject")
    assert "You rewrite user instructions for image-to-video generation" in captured["system_prompt"]
    assert "Do not ask a question" in captured["system_prompt"]
    assert captured["message"].endswith("make the head look around")


def test_text_only_enhance_keeps_original_when_model_returns_generic_clarification(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "upload_test.jpg").write_bytes(b"jpeg-image-bytes")
    api_module.WEB_DATA_PATH = tmp_path

    app = Flask(__name__)
    app.register_blueprint(api_module.api_bp)
    provider = SimpleNamespace(
        chat=lambda message, system_prompt=None, max_tokens=None: (
            "Create a video with motion. Generate a short AI video clip that includes "
            "dynamic movement and animation. If you need a specific subject or scene, "
            "ask me what you'd like the video to show."
        )
    )
    tool_service = SimpleNamespace(get_tools_summary=lambda: [])

    with patch.object(
        web_config,
        "load_web_config",
        return_value={
            "cloud": {"llm_provider": "ollama", "llm_model": "glm-5.2:cloud"}
        },
    ), patch(
        "vision_provider.analyze_images",
        side_effect=RuntimeError("model does not support image input"),
    ), patch(
        "llm_provider.create_provider", return_value=provider
    ), patch.object(api_module, "get_tool_service", return_value=tool_service):
        response = app.test_client().post(
            "/api/enhance-prompt",
            json={
                "input": "make her head slowly look around",
                "mode": "cloud",
                "image_action": "video",
                "image": {"filename": "upload_test.jpg"},
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["vision_grounded"] is False
    assert payload["enhanced"] == "make her head slowly look around"
    assert "original text was kept" in payload["vision_warning"]
