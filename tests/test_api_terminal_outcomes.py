"""HTTP callers retain terminal/retry facts instead of guessing from speech."""

import asyncio
import sys
from copy import deepcopy
from types import SimpleNamespace

import config_loader
import httpx
import pytest
from config_loader import get_active_config_mode
from fastapi import FastAPI

from api.routes.query import router as query_router
from api.routes.workflows import router as workflow_router

OUTCOME_FIELDS = ("error_code", "terminal_failure", "retry_safe", "completion")
ENDPOINTS = ("query", "quick_post", "quick_get", "workflow")


@pytest.fixture
def api_outcomes(tmp_path, monkeypatch):
    directory = tmp_path / "config"
    directory.mkdir()
    for mode in ("cloud", "local"):
        (directory / f"{mode}.env").write_text("LLM_PROVIDER=ollama\n")
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    state = {"result": {}, "calls": []}

    class Orchestrator:
        def __init__(self, mode):
            self.mode = mode

        def process(self, **kwargs):
            state["calls"].append(("query", self.mode, get_active_config_mode(), kwargs["transcript"]))
            return deepcopy(state["result"])

    recipe = {
        "id": "guard_digest", "triggers": {"explicit": ["/guard_digest"]},
        "steps": [{"step": 1, "tool": "crawl_url"}],
    }

    class Loader:
        def __init__(self, **_kwargs):
            self.workflows = {recipe["id"]: recipe}

        def get_workflow(self, identifier):
            return self.workflows.get(identifier)

    class Pipeline:
        def __init__(self, mode, _executor):
            self.mode = mode

        def execute(self, _workflow, transcript):
            state["calls"].append(("workflow", self.mode, get_active_config_mode(), transcript))
            return deepcopy(state["result"])

    modules = {
        "orchestrator_v2": SimpleNamespace(Orchestrator=Orchestrator),
        "workflow_loader": SimpleNamespace(WorkflowLoader=Loader),
        "executor": SimpleNamespace(ToolExecutor=lambda **_kwargs: object()),
        "pipeline_executor": SimpleNamespace(PipelineExecutor=Pipeline),
        "tool_schema": SimpleNamespace(get_tool_registry=lambda **_kwargs: SimpleNamespace(list_tools=lambda: ["crawl_url"])),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    app = FastAPI()
    app.include_router(query_router)
    app.include_router(workflow_router)
    return app, state


def request(app, endpoint, mode):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            if endpoint == "query":
                return await client.post("/api/query", json={"query": "Read this article", "mode": mode})
            if endpoint == "quick_post":
                return await client.post("/api/query/quick", json={"query": "Read this article", "mode": mode})
            if endpoint == "quick_get":
                return await client.get("/api/query/quick", params={"q": "Read this article", "mode": mode})
            return await client.post("/api/workflows/guard_digest/execute", json={"query": "articles", "mode": mode})

    return asyncio.run(send())


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("completion", ["unknown", "completed", "rejected"])
def test_http_response_preserves_content_rejection_and_operation_outcome(api_outcomes, endpoint, mode, completion):
    app, state = api_outcomes
    incident = {"content_withheld": True, "incident_id": "pg-" + "a" * 32, "tool": "crawl_url"}
    original = {
        "ok": False, "speech": "Prompt Guard withheld the returned content.",
        "error": "Returned content withheld by Prompt Guard.",
        "error_code": "prompt_injection_detected", "terminal_failure": True,
        "retry_safe": False, "completion": completion,
        "tools_used": ["crawl_url"], "data": {"prompt_guard": incident},
    }
    state["result"] = deepcopy(original)

    response = request(app, endpoint, mode)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert {key: body[key] for key in OUTCOME_FIELDS} == {key: original[key] for key in OUTCOME_FIELDS}
    assert body["speech"] == original["speech"]
    assert body["data"]["prompt_guard"] == incident
    assert len(state["calls"]) == 1
    assert state["calls"][0][1:3] == (mode, mode)
    assert state["result"] == original


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_legacy_success_does_not_invent_retry_or_completion_claims(api_outcomes, endpoint):
    app, state = api_outcomes
    state["result"] = {"ok": True, "speech": "Done.", "data": {"title": "An article"}}
    response = request(app, endpoint, "cloud")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["speech"] == "Done."
    assert body["data"] == {"title": "An article"}
    assert all(body[key] is None for key in OUTCOME_FIELDS)


@pytest.mark.parametrize("endpoint", ["query", "workflow"])
def test_explicit_false_and_true_retry_facts_are_preserved(api_outcomes, endpoint):
    app, state = api_outcomes
    state["result"] = {
        "ok": False, "speech": "The provider rejected this request.",
        "error_code": "provider_rejected", "terminal_failure": False,
        "retry_safe": True, "completion": "rejected",
    }
    response = request(app, endpoint, "cloud")
    assert response.status_code == 200
    body = response.json()
    assert body["terminal_failure"] is False
    assert body["retry_safe"] is True
    assert body["completion"] == "rejected"
    assert body["error_code"] == "provider_rejected"
