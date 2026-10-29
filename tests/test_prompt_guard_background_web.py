"""Late security notices stay deterministic across background delivery retries."""

import importlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from server_package_utils import load_server_package

from lib.prompt_guard_observer import is_prompt_guard_stopped, prompt_guard_notice

ROOT = Path(__file__).resolve().parents[1]
load_server_package("prompt_guard_background_web_server", ROOT / "jarvis-web/server")
background = importlib.import_module("prompt_guard_background_web_server.services.background_tasks")


def rejected_job(tool, state="failed"):
    return {
        "id": "background-job", "mode": "local", "state": state,
        "adapter": "http_callback_v1" if tool == "browser_use" else "remote_skill_v1",
        "admission": {"tool": tool, "arguments": {"url": "https://example.test"}},
        "result": {
            "ok": False, "error_code": "prompt_injection_detected",
            "terminal_failure": True, "retry_safe": False,
            "completion": "unknown" if state == "needs_attention" else "completed",
            "speech": "UNREVIEWED_UPSTREAM_SPEECH", "error": "UNREVIEWED_UPSTREAM_ERROR",
            "data": {
                "prompt_guard": {
                    "content_withheld": True, "tool": tool,
                    "incident_id": "pg-" + "a" * 32, "evidence_saved": True,
                },
                "operation": {"tool_executed": True, "original_ok": True},
            },
        },
    }


@pytest.mark.parametrize("tool", ["browser_use", "browser_use_cloud", "mcp_apify_research"])
@pytest.mark.parametrize("state", ["failed", "needs_attention"])
def test_late_rejection_notice_skips_model_and_survives_repeated_delivery(monkeypatch, tool, state):
    import llm_provider

    def unexpected(**_kwargs):
        pytest.fail("Withheld results must not require a model call to deliver their notice")

    monkeypatch.setattr(llm_provider, "create_configured_provider", unexpected)
    service = background.WebBackgroundTasks.__new__(background.WebBackgroundTasks)
    service.handler = SimpleNamespace(_prepare_web_response_text=lambda _result, text: (text, text))
    job = rejected_job(tool, state)
    before = deepcopy(job)
    # Missing provider authorization does not delay a security notice.
    first = service._synthesize(job, {}, {"messages": []})
    restored = service._synthesize(deepcopy(job), {}, {"messages": []})
    assert first == restored
    assert first["text"].startswith(prompt_guard_notice(job["result"]))
    assert "pg-" + "a" * 32 in first["text"]
    assert "UNREVIEWED_UPSTREAM" not in first["text"]
    assert first["data"][tool] == job["result"]
    assert first["data"]["background_job_id"] == job["id"]
    assert is_prompt_guard_stopped(first)
    assert ("outcome is still unconfirmed" in first["text"]) == (state == "needs_attention")
    assert job == before


def test_foreground_task_snapshot_retains_terminal_policy_and_incident():
    job = rejected_job("browser_use_cloud")
    job.update(updated_at=1000, progress=None, archived_at=None)
    evidence = background.WebBackgroundTasks._task_evidence(job)
    result = evidence["result"]
    assert result["terminal_failure"] is True and result["retry_safe"] is False
    assert result["data"]["prompt_guard"]["incident_id"] == "pg-" + "a" * 32
    assert result["completion"] == "completed"
