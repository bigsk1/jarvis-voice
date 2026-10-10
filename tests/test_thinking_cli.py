#!/usr/bin/env python3
"""CLI precedence regressions for visible provider reasoning."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "orchestrator"))


def test_debug_thinking_flag_survives_mode_config_hydration(monkeypatch, capsys):
    import orchestrator_v2
    from thinking import should_enable_thinking

    observed = {}

    def fake_load_config(_mode):
        # Reproduce config/cloud.env replacing the ordinary process value.
        os.environ["JARVIS_DEBUG_THINKING"] = "false"
        return {"JARVIS_DEBUG_THINKING": "false"}

    class FakeOrchestrator:
        def __init__(self, _mode):
            observed["debug_enabled"] = should_enable_thinking()

        def process(self, _transcript, excluded_tools=None):
            return {"ok": True, "speech": "ok", "tools_used": []}

    monkeypatch.setattr(orchestrator_v2, "load_config", fake_load_config)
    monkeypatch.setattr(orchestrator_v2, "Orchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        sys,
        "argv",
        ["orchestrator_v2.py", "cloud", "hello", "--json", "--debug-thinking"],
    )

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("JARVIS_OVERRIDE_JARVIS_DEBUG_THINKING", None)
        orchestrator_v2.main()

    assert observed["debug_enabled"] is True
    assert '"speech": "ok"' in capsys.readouterr().out


@pytest.mark.parametrize('mode,inherited', [('local', 'cloud'), ('cloud', 'local')])
def test_positional_cli_mode_controls_ollama_endpoint(monkeypatch, capsys, mode, inherited):
    import orchestrator_v2
    from config_loader import get_active_config_mode
    from llm_provider import OllamaProvider

    observed = {}

    class FakeOrchestrator:
        def __init__(self, selected_mode):
            observed['selected'] = selected_mode
            observed['active'] = get_active_config_mode()
            provider = OllamaProvider(base_url='http://processor.example:11434', model='fixture:9b')
            observed['hosts'] = provider.base_urls

        def process(self, _transcript, excluded_tools=None):
            return {'ok': True, 'speech': 'ok', 'tools_used': []}

    monkeypatch.setenv('JARVIS_MODE', inherited)
    monkeypatch.setenv('OLLAMA_API_KEY', 'fixture-key')
    monkeypatch.setenv('FEEDBACK_RANDOM_ENABLED', 'false')
    monkeypatch.setattr(orchestrator_v2, 'load_config', lambda _mode: {})
    monkeypatch.setattr(orchestrator_v2, 'Orchestrator', FakeOrchestrator)
    monkeypatch.setattr(sys, 'argv', ['orchestrator_v2.py', mode, 'hello', '--json'])

    with patch.dict(os.environ, {}, clear=False):
        orchestrator_v2.main()

    assert observed['selected'] == observed['active'] == mode
    if mode == 'local':
        assert observed['hosts'][0] == 'http://processor.example:11434'
        assert 'https://ollama.com' not in observed['hosts']
    else:
        assert observed['hosts'] == ['https://ollama.com']
    assert '"ok": true' in capsys.readouterr().out
