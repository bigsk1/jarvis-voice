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
    provider = SimpleNamespace(
        chat=lambda message, system_prompt=None, max_tokens=None: (
            "Make the existing subject look around while preserving all unspecified visual details."
        )
    )
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
