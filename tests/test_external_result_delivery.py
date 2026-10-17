"""Generic results survive real Web task delivery, reload and saved-mode downloads."""

import json

import pytest
from test_web_background_tasks import eventually
from test_web_background_tasks import journey as journey
from test_web_background_tasks import web_tasks as web_tasks

from lib.background_tasks.worker import TaskWorker
from lib.external_results import make_external_result_data


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_generic_result_survives_late_answer_reloaded_history_and_original_mode_download(
    web_tasks, monkeypatch, mode,
):
    import config_loader
    import llm_provider
    from jarvis_bundle_chat_test.routes import api
    from jarvis_bundle_chat_test.services import conversation_store
    from stash_helper import parse_stash_ref

    from lib import config_loader as package_config

    h = web_tasks
    roots = {name: h.tmp / (name + "-stash") for name in ("cloud", "local")}
    for module in (config_loader, package_config):
        monkeypatch.setattr(module, "_load_mode_config", lambda selected: {
            "STASH_DIR": str(roots[selected]),
        })
    raw = {"items": [{
        "record_id": f"row{index}", "nested": {"flags": [False, None], "count": 0},
    } for index in range(30)]}
    raw["items"][0]["nested"]["integer"] = 9007199254740993
    with config_loader.config_scope(mode):
        data = make_external_result_data(
            provider="fixture_catalog", tool="generic_read_result",
            execution={"run_id": "NativeRun123", "actor_id": "Actor123", "status": "SUCCEEDED"},
            result={"kind": "dataset", "dataset_id": "Dataset123", "sample_items": raw["items"],
                    "returned_count": 30, "total_items": 50, "offset": 0, "limit": 30,
                    "complete": False, "pagination": {"next_offset": 30}},
            raw_payload=raw,
        )
    result = {"ok": True, "speech": "Retrieved 30 records from the existing run.", "data": data}

    # Use a distinct trusted fixture adapter so the existing inert child worker
    # cannot claim this job. Admission, worker completion and delivery stay real.
    adapter = "generic_result_fixture"
    schema = h.background.registry.get_tool("fixture")
    schema.background_adapter = adapter
    schema.background_execution["adapter"] = adapter
    h.background.adapters["fixture"] = adapter
    h.tasks.touch_worker("generic-result-ready", {adapter})
    h.background.synthesize = h.background._synthesize
    captured = []
    factories = []

    class Provider:
        def chat(self, prompt, **kwargs):
            captured.append((config_loader.get_active_config_mode(), json.loads(prompt), kwargs))
            return "Collected a page of 30 records. The complete fetched page is retained."

    def provider_factory(**kwargs):
        factories.append(kwargs)
        return "test", "test-model", Provider()

    monkeypatch.setattr(llm_provider, "create_configured_provider", provider_factory)
    h.app.register_blueprint(api.api_bp)
    h.client.emit("chat:send", {"message": "Collect the generic fixture page.", "mode": mode})
    job = eventually(lambda: next(iter(h.tasks.conversation_jobs()), None))
    eventually(lambda: h.tasks.get(job["id"])["dispatch_state"] == "ready")
    cid = job["conversation_id"]
    h.client.emit("tasks:subscribe", {"conversation_id": cid})
    h.client.get_received()
    executions = []

    def execute(context):
        executions.append(context.claim.job_id)
        return result

    worker = TaskWorker(h.tasks, {adapter: execute})
    assert worker.run_once()
    eventually(lambda: h.tasks.get(job["id"])["delivery_state"] == "delivered")
    eventually(lambda: cid not in h.handler.runs.active)
    saved_job = h.tasks.get(job["id"])
    assert saved_job["state"] == "succeeded"
    assert saved_job["result"] == result
    assert executions == [job["id"]]
    assert len(h.tasks.job_detail(job["id"])["attempts"]) == 1
    assert not worker.run_once()

    # Synthesis receives a bounded shared projection. Persistence and the live
    # continuation keep the complete saved envelope, rather than that projection.
    assert len(captured) == len(factories) == 1
    selected_mode, prompt, kwargs = captured[0]
    evidence = prompt["result"]["data"]
    assert selected_mode == prompt["mode"] == mode
    assert prompt["original_request"] == "Collect the generic fixture page."
    assert "delivery_state" not in prompt
    assert factories[0]["mode"] == mode
    assert factories[0]["disable_server_side_tools"] is True
    assert "Do not execute tools" in kwargs["system_prompt"]
    assert evidence["execution"] == data["execution"]
    assert evidence["result"]["sample_count"] == 3
    assert evidence["result"]["returned_count"] == 30
    assert evidence["result"]["total_items"] == 50
    assert evidence["result"]["complete"] is False
    assert evidence["source"]["mode"] == mode
    assert evidence["raw_ref"] == data["raw_ref"]
    assert evidence["result"]["sample_items"][0]["nested"] == {
        "flags": [False, None], "count": 0, "integer": "9007199254740993",
    }
    assert len(json.dumps(evidence, separators=(",", ":"))) <= 3400

    events = h.client.get_received()
    continuation = next(event["args"][0] for event in events if event["name"] == "chat:continuation")
    message = continuation["message"]
    assert message["tools_used"] == []
    assert message["data"]["fixture"] == result
    assert message["data"]["_background_mode"] == mode
    assert message["data"]["parent_job_id"] == job["id"]
    assert message["data"]["fixture"]["data"]["result"]["sample_count"] == 20

    h.background.close()
    restored_store = conversation_store.ConversationStore(
        h.tmp / "conversations", background_tasks=h.tasks,
    )
    monkeypatch.setattr(conversation_store, "get_conversation_store", lambda: restored_store)
    persisted = restored_store.get_conversation(cid)["messages"][-1]
    assert persisted == message
    history = h.handler._get_conversation_context(cid)
    followup = history[-1]["tool_results"]["fixture"]
    assert followup["execution"] == data["execution"]
    assert followup["raw_ref"] == data["raw_ref"]
    assert followup["source"]["mode"] == mode
    assert followup["result"]["sample_count"] == 5
    assert followup["result"]["returned_count"] == 30
    assert followup["result"]["sample_items"][0]["nested"]["integer"] == "9007199254740993"

    reconnect = h.connect()
    reconnect.emit("conversation:load", {"conversation_id": cid})
    restored = next(event["args"][0]["conversation"] for event in reconnect.get_received()
                    if event["name"] == "conversation:loaded")
    assert restored["messages"][-1] == message
    assert len(h.tasks.conversation_jobs(cid)) == 1
    assert len(captured) == 1

    # A later active mode must not redirect the retained raw response to another
    # Stash root. The downloaded JSON still has every original row and integer.
    space_id, file_id = parse_stash_ref(followup["raw_ref"])
    other_mode = "local" if mode == "cloud" else "cloud"
    with config_loader.config_scope(other_mode):
        http = h.app.test_client()
        response = http.get(f"/api/stash/{space_id}/{file_id}?mode={followup['source']['mode']}")
        wrong_mode = http.get(f"/api/stash/{space_id}/{file_id}?mode={other_mode}")
    assert response.status_code == 200
    assert response.get_json() == raw
    assert type(response.get_json()["items"][0]["nested"]["integer"]) is int
    assert response.headers["X-Stash-Ref"] == data["raw_ref"]
    assert wrong_mode.status_code == 404
