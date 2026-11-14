"""Only the running recipe can supply a watch writer to a local tool."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "orchestrator"))

from tool_schema import ToolSchema  # noqa: E402

from lib.watch_state.authority import export_writer_context, watch_writer_scope  # noqa: E402
from orchestrator.executor import ToolExecutor  # noqa: E402
from orchestrator.pipeline_executor import PipelineExecutor  # noqa: E402


class Registry:
    def __init__(self, schema):
        self.schema = schema

    def get_tool(self, name):
        return self.schema if name == "watch_state" else None

    def is_mcp_tool(self, _name):
        return False


@pytest.mark.parametrize("workflow_id", [None, "price_check"])
def test_child_writer_replaces_stale_environment_after_restriction(monkeypatch, workflow_id):
    source = {"PATH": "/usr/bin", "HOME": "/tmp", "JARVIS_MODE": "cloud",
              "JARVIS_INTERNAL_WATCH_WRITER": "workflow:forged",
              "JARVIS_OVERRIDE_JARVIS_INTERNAL_WATCH_WRITER": "workflow:forged_override",
              "OPENAI_API_KEY": "unrelated-secret"}
    monkeypatch.setattr("orchestrator.executor.export_config_environment", lambda _mode: dict(source))
    schema = ToolSchema.from_json_file(str(ROOT / "skills/watch_state.tool.json"))
    executor = ToolExecutor(mode="cloud", registry=Registry(schema), load_runtime_config=False)
    captured = {}

    def run(*_args, **kwargs):
        captured.update(kwargs["tool_env"])
        return json.dumps({"ok": True, "data": {"count": 0}}), "", False

    with watch_writer_scope(workflow_id), patch("tool_process.run_local_process", side_effect=run):
        expected = export_writer_context()
        result = executor.execute("watch_state", {"action": "list"}, skip_permission_check=True)
    assert result["ok"] is True
    assert captured["JARVIS_INTERNAL_WATCH_WRITER"] == expected
    assert "JARVIS_OVERRIDE_JARVIS_INTERNAL_WATCH_WRITER" not in captured
    assert "OPENAI_API_KEY" not in captured
    assert captured["JARVIS_RESTRICTED_TOOL_ENV"] == "1"


def test_pipeline_uses_recipe_id_and_restores_context_after_failure():
    observed = []

    def execute(_tool, _args):
        observed.append(export_writer_context())
        return {"ok": False, "error": "fixture failure"}

    pipeline = PipelineExecutor(mode="cloud", executor=SimpleNamespace(execute=execute), provider=None)
    with watch_writer_scope("outer"):
        previous = export_writer_context()
        pipeline.execute({"id": "price_check", "variables": {"workflow_id": "forged"},
                          "steps": [{"step": 1, "tool": "watch_state", "required": True,
                                     "params": {"action": "list"}}]}, "/price_check")
        assert export_writer_context() == previous
    with watch_writer_scope("price_check"):
        assert observed == [export_writer_context()]
