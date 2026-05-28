#!/usr/bin/env python3
"""
Tests for disabling provider-native tools when web upload vision is pre-attached.

Run:
    python3 tests/test_orchestrator_vision_native_tools.py
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from orchestrator_v2 import (
    Orchestrator,
    WEB_UPLOAD_VISION_ANALYSIS_PREFIX,
    _request_has_web_vision_analysis,
)


class OrchestratorVisionNativeToolsTests(unittest.TestCase):
    def test_request_has_web_vision_analysis_detects_marker(self):
        text = (
            f"{WEB_UPLOAD_VISION_ANALYSIS_PREFIX} It's a weed.]\n\n"
            "User's message: is this a weed?"
        )
        self.assertTrue(_request_has_web_vision_analysis(text))
        self.assertFalse(_request_has_web_vision_analysis("plain question"))

    def test_provider_server_side_tools_available_for_xai(self):
        handler = Orchestrator.__new__(Orchestrator)
        handler.router = SimpleNamespace(
            provider_type="xai",
            provider=SimpleNamespace(enable_search=True, xai_client=object()),
        )
        with patch.object(Orchestrator, "_config_bool", return_value=True):
            self.assertTrue(handler._provider_server_side_tools_available())

    def test_provider_server_side_tools_unavailable_for_ollama(self):
        handler = Orchestrator.__new__(Orchestrator)
        handler.router = SimpleNamespace(
            provider_type="ollama",
            provider=SimpleNamespace(),
        )
        self.assertFalse(handler._provider_server_side_tools_available())

    def test_vision_pre_analyzed_disables_native_tools_for_xai(self):
        handler = Orchestrator.__new__(Orchestrator)
        handler.router = SimpleNamespace(
            provider_type="xai",
            provider=SimpleNamespace(enable_search=True, xai_client=object()),
        )

        vision_active = True
        client_search_hint_active = False
        native_search_remaining = 6

        with patch.object(Orchestrator, "_config_bool", return_value=True):
            provider_available = handler._provider_server_side_tools_available()
            disable = (
                client_search_hint_active
                or (native_search_remaining is not None and native_search_remaining <= 0)
                or (vision_active and provider_available)
            )

        self.assertTrue(disable)

    def test_vision_pre_analyzed_noop_for_ollama(self):
        handler = Orchestrator.__new__(Orchestrator)
        handler.router = SimpleNamespace(
            provider_type="ollama",
            provider=SimpleNamespace(),
        )

        vision_active = True
        client_search_hint_active = False
        native_search_remaining = None

        provider_available = handler._provider_server_side_tools_available()
        disable = (
            client_search_hint_active
            or (native_search_remaining is not None and native_search_remaining <= 0)
            or (vision_active and provider_available)
        )

        self.assertFalse(disable)


if __name__ == "__main__":
    unittest.main()
