"""Check actual launcher paths in fresh interpreters, without pytest's imports."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("launch_path", ["web", "orchestrator", "package"])
def test_deepwiki_helpers_import_and_project_without_ambient_paths(launch_path, tmp_path):
    probe = r'''
import importlib
import json
import runpy
import sys
from pathlib import Path

root = Path(sys.argv[1])
launch_path = sys.argv[2]
assert str(root) not in sys.path
assert str(root / "lib") not in sys.path

if launch_path == "web":
    # Execute the real launcher's path setup, but do not start a server or
    # construct ChatHandler (which owns live conversations and run recovery).
    runpy.run_path(str(root / "bin/jarvis-web"), run_name="startup_probe")
    from server.sockets.chat import ChatHandler
    from server.services.followup_extractor import extract_followup_data
elif launch_path == "orchestrator":
    sys.path[:0] = [str(root / "lib"), str(root / "orchestrator")]
else:
    # Direct package/file consumers also remain supported, without repo/lib.
    sys.path[:0] = [str(root), str(root / "jarvis-web"), str(root / "orchestrator")]
    from server.services.followup_extractor import extract_followup_data

if launch_path == "package":
    from lib.deepwiki import normalize_deepwiki_result
    from lib.deepwiki_context import project_deepwiki_data
else:
    from deepwiki import normalize_deepwiki_result
    from deepwiki_context import project_deepwiki_data
    from mcp_client import _normalize_call_tool_result
    assert str(root) not in sys.path
    assert "lib" not in sys.modules

from context_assembler import ContextAssembler
tool = "mcp_deepwiki_ask_question"
args = {"repoName": "pallets/flask", "question": "Explain request contexts"}
raw = {"content": [{"type": "text", "text": "Request contexts isolate request data."}]}
result = normalize_deepwiki_result("ask_question", raw, args)
assert result["ok"] is True
assert "stash_ref" not in result["data"]
assert project_deepwiki_data(result)["answer"] == result["data"]["answer"]
assembler = ContextAssembler.__new__(ContextAssembler)
preview = json.loads(assembler.build_llm_result_context_preview(tool, result)[0])
assert preview["data"]["answer"] == result["data"]["answer"]
if launch_path in {"web", "package"}:
    assert extract_followup_data({tool: result})[tool]["repo_names"] == ["pallets/flask"]
if launch_path != "package":
    assert _normalize_call_tool_result("ask_question", raw, server_name="deepwiki", arguments=args) == result
print("DeepWiki launcher imports and projection passed")
'''
    completed = subprocess.run(
        [sys.executable, "-I", "-c", probe, str(ROOT), launch_path],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "DeepWiki launcher imports and projection passed" in completed.stdout
