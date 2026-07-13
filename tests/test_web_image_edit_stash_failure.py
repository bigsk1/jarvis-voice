"""Regression coverage for image-edit preparation failures in Web chat."""

from pathlib import Path
from unittest.mock import patch
import sys


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))

from server_package_utils import load_server_package


load_server_package("jarvis_web_image_edit_test", PROJECT_ROOT / "jarvis-web" / "server")

from jarvis_web_image_edit_test import config as web_config
from jarvis_web_image_edit_test.sockets.chat import ChatHandler


class _Socket:
    def __init__(self):
        self.events = []

    def emit(self, event, payload, **kwargs):
        self.events.append((event, payload, kwargs))


def test_image_edit_stash_failure_aborts_before_orchestration():
    handler = ChatHandler.__new__(ChatHandler)
    handler.socketio = _Socket()
    handler._delivery_room = lambda session_id, conversation_id: conversation_id
    handler._get_completion_guard_config = lambda mode: {"enabled": False}
    handler._auto_stash_image = lambda image, analysis, mode: None

    image_data = {
        "action": "image",
        "settings": {"provider": "openai"},
        "images": [{"filename": "upload_test.jpg", "url": "/api/uploads/upload_test.jpg"}],
    }

    with patch.object(web_config, "load_web_config", return_value={"cloud": {}}), patch(
        "orchestrator_v2.Orchestrator"
    ) as orchestrator:
        handler._process_message(
            "session-1",
            "Change the shirt to blue",
            "cloud",
            "message-1",
            "conversation-1",
            image_data=image_data,
        )

    orchestrator.assert_not_called()
    error_events = [payload for event, payload, _ in handler.socketio.events if event == "chat:error"]
    assert error_events == [
        {
            "message_id": "message-1",
            "conversation_id": "conversation-1",
            "error": "Could not prepare the uploaded image for editing. No image generation was attempted. Please retry the edit.",
            "error_code": "image_edit_stash_failed",
            "retryable": True,
            "timestamp": error_events[0]["timestamp"],
        }
    ]


def test_image_video_stash_failure_aborts_before_orchestration():
    handler = ChatHandler.__new__(ChatHandler)
    handler.socketio = _Socket()
    handler._delivery_room = lambda session_id, conversation_id: conversation_id
    handler._get_completion_guard_config = lambda mode: {"enabled": False}
    handler._auto_stash_image = lambda image, analysis, mode: None

    image_data = {
        "action": "video",
        "settings": {"provider": "gemini"},
        "images": [{"filename": "upload_test.jpg", "url": "/api/uploads/upload_test.jpg"}],
    }

    with patch.object(web_config, "load_web_config", return_value={"cloud": {}}), patch(
        "orchestrator_v2.Orchestrator"
    ) as orchestrator:
        handler._process_message(
            "session-1",
            "Animate this image",
            "cloud",
            "message-1",
            "conversation-1",
            image_data=image_data,
        )

    orchestrator.assert_not_called()
    error_events = [payload for event, payload, _ in handler.socketio.events if event == "chat:error"]
    assert error_events == [
        {
            "message_id": "message-1",
            "conversation_id": "conversation-1",
            "error": "Could not prepare the uploaded image for video generation. No video generation was attempted. Please retry.",
            "error_code": "image_video_stash_failed",
            "retryable": True,
            "timestamp": error_events[0]["timestamp"],
        }
    ]
