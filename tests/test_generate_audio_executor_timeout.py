"""An audio subprocess timeout cannot prove that a paid request was rejected."""

import importlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from config_loader import config_scope
from tool_schema import ToolSchema

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("tool_name", ["generate_audio", "generate_image"])
def test_audio_timeout_retains_unknown_completion_without_changing_other_tools(monkeypatch, tool_name):
    module = importlib.import_module("orchestrator.executor")
    schema = ToolSchema.from_json_file(str(ROOT / "skills/generate_audio.tool.json"))
    registry = SimpleNamespace(
        get_tool=lambda _name: schema,
        is_mcp_tool=lambda _name: False,
    )
    logger = Mock()
    monkeypatch.setattr(module, "get_logger", lambda _mode: logger)
    monkeypatch.setattr(module, "export_config_environment", lambda _mode: {})
    run = Mock(side_effect=subprocess.TimeoutExpired("unsafe-command-private-key", 1))
    monkeypatch.setattr("tool_process.run_local_process", run)
    with config_scope("cloud", overrides={"AUDIO_TOOL_TIMEOUT_SECONDS": "180"}):
        executor = module.ToolExecutor(mode="cloud", registry=registry, load_runtime_config=False)
        result = executor.execute(tool_name, {"text": "Hello."}, skip_permission_check=True)
    assert result["ok"] is False
    assert result["error"] == "Timeout"
    assert "private-key" not in str(result)
    run.assert_called_once()
    assert logger.log_tool_call.call_args.kwargs["result"] == result
    if tool_name == "generate_audio":
        assert result["completion"] == "unknown"
        assert "may have been billed" in result["speech"]
        assert "do not retry it automatically" in result["speech"]
    else:
        assert "completion" not in result
        assert result["speech"] == "Tool generate_image timed out"
