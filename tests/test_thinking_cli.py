#!/usr/bin/env python3
"""CLI precedence regressions for visible provider reasoning."""

import os
import sys
from pathlib import Path
from unittest.mock import patch


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
