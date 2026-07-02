"""Regression tests for strict Web chat vision failure handling."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))

from server_package_utils import load_server_package


load_server_package("jarvis_web_vision_failure_test", PROJECT_ROOT / "jarvis-web" / "server")

from jarvis_web_vision_failure_test import config as web_config
from jarvis_web_vision_failure_test.sockets.chat import ChatHandler
from vision_provider import VisionCapabilityError


def test_process_vision_propagates_text_only_model_failure():
    handler = ChatHandler.__new__(ChatHandler)
    capability_error = VisionCapabilityError("Ollama", "glm-5.2:cloud")

    with patch.object(web_config, "load_jarvis_config"), patch.object(
        web_config,
        "load_web_config",
        return_value={
            "cloud": {"llm_provider": "ollama", "llm_model": "glm-5.2:cloud"}
        },
    ), patch(
        "vision_provider.analyze_images",
        side_effect=capability_error,
    ):
        with pytest.raises(VisionCapabilityError, match="does not support image input"):
            handler._process_vision(
                ["base64-image"],
                "What is in this image?",
                "cloud",
            )
