"""Durability boundaries between the task database and Web conversation JSON."""

import copy
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from test_background_tasks import admission
from test_background_tasks import store as store
from test_web_attachment_bundle_chat import journey as journey

from lib.background_tasks import AdmissionDenied, Conflict, LostLease
from lib.background_tasks.admission import (
    BackgroundAdmissionService,
    contains_admission,
    reject_background_result,
)


@pytest.fixture
def destination(journey, store):
    journey.store.background_tasks = store
    journey.send(message="Run a background fixture.")
    cid = journey.handler.sessions["client"]["conversation_id"]
    run = journey.handler.runs.active[cid]
    job = store.admit(admission(conversation_id=cid, generation=0, request_id=run["message_id"]))
    journey.store.add_message(
        cid,
        "assistant",
        "Queued; results will follow.",
        data={
            "_web_message_id": run["message_id"],
            "_run_status": "completed",
            "pending_jobs": [{"job_id": job["id"]}],
        },
    )
    journey.tasks, journey.job, journey.run = store, job, run
    return journey


def complete_source(h):
    h.handler.runs.finish(h.job["conversation_id"], h.run["message_id"], "completed")
    evidence = h.store.task_receipt_evidence(h.job)
    assert evidence
    return h.tasks.release(h.job["id"], evidence)


def completed_job(h):
    complete_source(h)
    claim = h.tasks.claim("test-worker", {"local_fixture"})
    delivery_id = h.tasks.finish(claim, {"artifact": "fixture.txt"})
    return h.tasks.get(h.job["id"]), h.tasks.delivery(delivery_id)


def test_held_receipt_waits_for_durable_finish_and_actual_lease_release(destination, monkeypatch):
    h = destination
    assert h.store.task_receipt_evidence(h.job) is None
    assert h.tasks.claim("worker", {"local_fixture"}) is None
    update = h.store.update_run
    monkeypatch.setattr(
        h.store, "update_run", lambda *a, **kw: (_ for _ in ()).throw(OSError("injected"))
    )
    outcome = h.handler.runs.finish(h.job["conversation_id"], h.run["message_id"], "completed")
    assert outcome["persistence_error"]
    assert h.store.task_receipt_evidence(h.job) is None
    assert h.tasks.claim("worker", {"local_fixture"}) is None
    monkeypatch.setattr(h.store, "update_run", update)
    h.handler.runs.snapshot(h.job["conversation_id"])
    h.tasks.release(h.job["id"], h.store.task_receipt_evidence(h.job))
    assert h.tasks.claim("worker", {"local_fixture"})


def test_crash_gap_recovers_source_history_during_successor_turn(destination):
    h = destination
    cid = h.job["conversation_id"]
    h.handler.runs.finish(cid, h.run["message_id"], "completed")
    assert h.tasks.get(h.job["id"])["dispatch_state"] == "held"
    h.handler.runs.claim(cid, "second-request", "cloud", message="Independent question")
    evidence = h.store.task_receipt_evidence(h.job)
    assert evidence.request_id == h.run["message_id"]
    h.tasks.release(h.job["id"], evidence)
    assert h.tasks.claim("worker", {"local_fixture"})
    assert h.store.get_conversation(cid)["run"]["message_id"] == "second-request"


@pytest.mark.parametrize("outcome", ["failed", "cancelled", "interrupted"])
def test_unsuccessful_source_cannot_release_even_with_receipt(destination, outcome):
    h = destination
    h.handler.runs.finish(h.job["conversation_id"], h.run["message_id"], outcome)
    assert h.store.task_receipt_evidence(h.job) is None
    assert h.tasks.claim("worker", {"local_fixture"}) is None


def test_stale_delivery_cannot_save_or_project_after_new_owner(destination):
    h = destination
    job, delivery = completed_job(h)
    now = h.tasks.clock()
    h.tasks.clock = lambda: now
    first = h.tasks.claim_delivery(delivery["id"], "first")
    h.tasks.save_delivery_output(first, {"text": "Saved summary"})
    now += 31
    second = h.tasks.claim_delivery(delivery["id"], "second")
    assert second["output_json"]
    with pytest.raises(LostLease):
        h.tasks.save_delivery_output(first, {"text": "Stale overwrite"})
    with pytest.raises(LostLease):
        h.store.project_continuation(job, first)
    h.store.project_continuation(job, second)
    assert (
        h.store.get_conversation(job["conversation_id"])["messages"][-1]["content"]
        == "Saved summary"
    )


def test_json_saved_but_sqlite_commit_failed_projects_exactly_once(destination):
    h = destination
    job, delivery = completed_job(h)
    claim = h.tasks.claim_delivery(delivery["id"], "first")
    h.tasks.save_delivery_output(claim, {"text": "Saved summary"})
    with sqlite3.connect(h.tasks.path) as conn:
        conn.execute("""CREATE TRIGGER fail_delivery BEFORE UPDATE ON outbox
            WHEN NEW.state='delivered' BEGIN SELECT RAISE(ABORT,'injected commit failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        h.store.project_continuation(job, claim)
    assert len(h.store.get_conversation(job["conversation_id"])["messages"]) == 3
    assert h.tasks.delivery(delivery["id"])["state"] == "ready"
    with sqlite3.connect(h.tasks.path) as conn:
        conn.execute("DROP TRIGGER fail_delivery")
    h.store.project_continuation(job, claim)
    assert len(h.store.get_conversation(job["conversation_id"])["messages"]) == 3
    assert h.tasks.delivery(delivery["id"])["state"] == "delivered"


@pytest.mark.parametrize("action", ["clear", "delete"])
def test_fence_commits_before_json_failure_and_recovery_finishes_disposition(
    destination, monkeypatch, action
):
    h = destination
    job, delivery = completed_job(h)
    claim = h.tasks.claim_delivery(delivery["id"], "delivery")
    h.tasks.save_delivery_output(claim, {"text": "Must never reappear"})
    cid = job["conversation_id"]
    if action == "clear":
        original = h.store._write_conversation
        monkeypatch.setattr(
            h.store, "_write_conversation", lambda *a: (_ for _ in ()).throw(OSError("injected"))
        )
    else:
        original = h.store._save_index
        monkeypatch.setattr(
            h.store, "_save_index", lambda *a: (_ for _ in ()).throw(OSError("injected"))
        )
    with pytest.raises(OSError):
        h.store.dispose_background(cid, action, 0)
    assert h.tasks.conversation_fence(cid)["generation"] == 1
    assert h.tasks.delivery(delivery["id"])["state"] == "suppressed"
    monkeypatch.setattr(
        h.store, "_write_conversation" if action == "clear" else "_save_index", original
    )
    recovered = h.store.get_conversation(cid)
    assert recovered is None if action == "delete" else recovered["messages"] == []
    with pytest.raises((LostLease, ValueError)):
        h.store.project_continuation(job, claim)
    with pytest.raises(AdmissionDenied):
        h.tasks.admit(replace(admission(), conversation_id=cid, generation=0))
    if action == "clear":
        assert not h.tasks.outstanding(cid)
        assert h.tasks.admit(admission(conversation_id=cid, generation=1, invocation_id="new"))


def test_fence_failure_leaves_conversation_untouched(destination, monkeypatch):
    h = destination
    complete_source(h)
    before = h.store._conversation_path(h.job["conversation_id"]).read_bytes()
    monkeypatch.setattr(
        h.tasks,
        "fence_conversation",
        lambda *a, **kw: (_ for _ in ()).throw(sqlite3.OperationalError("injected")),
    )
    with pytest.raises(sqlite3.OperationalError):
        h.store.dispose_background(h.job["conversation_id"], "clear", 0)
    assert h.store._conversation_path(h.job["conversation_id"]).read_bytes() == before


def test_retention_dry_run_preserves_pending_jobs_and_writes_nothing(destination, monkeypatch):
    h = destination
    complete_source(h)
    cid = h.job["conversation_id"]
    value = h.store.get_conversation(cid)
    value["updated_at"] = (datetime.now() - timedelta(days=120)).isoformat()
    h.store._write_conversation(value)
    before = {p.name: p.read_bytes() for p in h.store.conversations_dir.glob("*.json")}
    result = h.store.cleanup_old_unpinned(dry_run=True)
    assert result["deleted_conversations"] == 0
    assert before == {p.name: p.read_bytes() for p in h.store.conversations_dir.glob("*.json")}
    monkeypatch.setattr(
        h.tasks,
        "outstanding",
        lambda *a: (_ for _ in ()).throw(sqlite3.OperationalError("injected")),
    )
    assert h.store.cleanup_old_unpinned()["deleted_conversations"] == 0
    assert h.store._conversation_path(cid).exists()


def test_completion_guard_and_feedback_defensively_read_saved_pending_jobs(
    destination, monkeypatch
):
    h = destination
    complete_source(h)
    record = {
        "conversation_id": h.job["conversation_id"],
        "message_id": h.run["message_id"],
        "mode": "cloud",
        "feedback_requested": True,
        "completion_guard": {"enabled": True},
    }
    monkeypatch.setattr(
        h.handler, "_start_blocking_task", lambda *a, **kw: pytest.fail("No review of pending work")
    )
    monkeypatch.setattr(
        h.handler,
        "_evaluate_completion_guard_auto",
        lambda *a: pytest.fail("No audit of pending work"),
    )
    h.handler._run_completion_guard_auto_eval("client", copy.deepcopy(record))
    h.handler._run_completion_guard_repair("client", copy.deepcopy(record))
    h.handler._start_feedback_async(
        "client", h.run["message_id"], h.run["message_id"], record, {}, [], "complete"
    )
    assert h.handler._background_review_blocked({"kind": "continuation"})
    assert not h.handler._background_review_blocked({"data": {}})


def test_import_cannot_overwrite_pending_destination(destination):
    h = destination
    complete_source(h)
    imported = h.store.get_conversation(h.job["conversation_id"])
    imported["messages"] = []
    with pytest.raises(AdmissionDenied):
        h.store.save_import(imported)


@pytest.mark.parametrize(
    "value",
    [
        {"ok": True, "status": "accepted", "job_id": "external"},
        {"ok": True, "data": {"results": [{"result_kind": "background_admission"}]}},
        {"ok": True, "pending_jobs": [{"job_id": "external"}]},
    ],
)
def test_non_web_boundaries_reject_nested_receipts(value):
    assert contains_admission(value)
    assert reject_background_result(value)["ok"] is False
    assert reject_background_result({"ok": True, "data": {"time": "12:00"}})["ok"] is True


def test_missing_worker_affects_capability_readiness_not_foreground_schema(store):
    from types import SimpleNamespace

    from tool_schema import ToolSchema

    schema = ToolSchema(
        "fixture",
        "Fixture",
        {"type": "object"},
        "fixture.py",
        execution={"background": {"supported": True, "adapter": "local_fixture"}},
    )
    registry = SimpleNamespace(list_tools=lambda: ["fixture"], get_tool=lambda name: schema)
    service = BackgroundAdmissionService(
        store,
        adapters={"fixture": "local_fixture"},
        ready=lambda: True,
        validate_source=lambda payload: True,
    )
    assert service.supported(registry) == ["fixture"]
    with pytest.raises(AdmissionDenied, match="healthy worker"):
        service.authorize(
            {"source": "web", "selected": ["fixture"], "tool_policy": "auto"}, registry
        )
    assert registry.get_tool("fixture") is schema
    assert "execution_mode" not in schema.parameters


def test_admission_identity_is_the_invocation_not_the_tool_arguments(store):
    from types import SimpleNamespace

    schema = SimpleNamespace(background_adapter="local_fixture")
    registry = SimpleNamespace(list_tools=lambda: ["fixture"], get_tool=lambda name: schema)
    store.touch_worker("worker", {"local_fixture"})
    service = BackgroundAdmissionService(
        store,
        adapters={"fixture": "local_fixture"},
        ready=lambda: True,
        validate_source=lambda payload: True,
    )
    context = service.authorize(
        {
            "source": "web",
            "selected": ["fixture"],
            "tool_policy": "auto",
            "conversation_id": "chat",
            "generation": 0,
            "request_id": "request",
            "mode": "cloud",
        },
        registry,
    )
    first = context.admit("fixture", {"value": 1}, "call-1", schema)
    assert context.admit("fixture", {"value": 1}, "call-1", schema)["job_id"] == first["job_id"]
    with pytest.raises(Conflict):
        context.admit("fixture", {"value": 2}, "call-1", schema)
    assert context.admit("fixture", {"value": 1}, "call-2", schema)["job_id"] != first["job_id"]
    assert context.admit("fixture", {"value": 2}, "call-3", schema)["job_id"] != first["job_id"]
    assert len(context.receipts) == 3


@pytest.mark.parametrize("caller", ["api", "scheduled", "workflow", "loop", "executor"])
def test_real_non_web_callers_fail_closed_on_injected_receipt(journey, monkeypatch, caller):
    import asyncio
    from types import SimpleNamespace

    import orchestrator_v2

    receipt = {"ok": True, "status": "accepted", "job_id": "untrusted-provider-job"}
    monkeypatch.setattr(
        orchestrator_v2,
        "Orchestrator",
        lambda *a, **kw: SimpleNamespace(process=lambda *a, **kw: receipt),
    )
    if caller == "api":
        from api.models.query import QueryRequest
        from api.routes.query import _query_jarvis_scoped

        result = asyncio.run(_query_jarvis_scoped(QueryRequest(query="fixture"))).model_dump()
    elif caller == "scheduled":
        from services.scheduled_task_runner import _run_query_task

        result = _run_query_task("cloud", "fixture")
    elif caller == "executor":
        from executor import ToolExecutor

        executor = ToolExecutor.__new__(ToolExecutor)
        executor._execute_foreground = lambda *a, **kw: receipt
        result = executor.execute("fixture", {})
        assert not executor.execute("fixture", {}, background_context={"source": "web"})["ok"]
    else:
        from orchestrator.pipeline_executor import PipelineExecutor

        pipeline = PipelineExecutor(
            "cloud",
            executor=SimpleNamespace(execute=lambda *a, **kw: receipt),
            provider=SimpleNamespace(),
        )
        step = {"tool": "fixture", "params": {}}
        if caller == "workflow":
            result = pipeline._execute_single(step, "fixture", None, {}, {}, {})
        else:
            result = pipeline._execute_for_each(
                {**step, "for_each": "${items}", "process_all": True},
                "fixture",
                None,
                {},
                {"items": [{"value": 1}]},
                {},
                0,
                10,
            )
            assert result["items_succeeded"] == 0
            return
    assert result["ok"] is False
    assert "Background admission" in result["error"]


def test_direct_orchestrator_import_is_independent_of_working_directory(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    script = (
        f"import sys; sys.path.insert(0,{str(root / 'orchestrator')!r}); import orchestrator_v2"
    )
    subprocess.run([sys.executable, "-c", script], cwd=tmp_path, check=True, timeout=15)


def test_parallel_redelivery_of_one_invocation_reuses_one_job(store):
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace
    schema = SimpleNamespace(background_adapter='local_fixture')
    registry = SimpleNamespace(list_tools=lambda:['fixture'], get_tool=lambda name:schema)
    store.touch_worker('worker', {'local_fixture'})
    service = BackgroundAdmissionService(store, adapters={'fixture':'local_fixture'},
                                         ready=lambda:True, validate_source=lambda payload:True)
    context = service.authorize({'source':'web','selected':['fixture'],'tool_policy':'auto',
                                 'conversation_id':'chat','generation':0,'request_id':'request','mode':'cloud'}, registry)
    def call(index):
        return context.admit('fixture', {'same':True}, 'same-call', schema)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(call, range(4)))
    assert len({result['job_id'] for result in results}) == 1
    assert len(context.receipts) == 1
    assert len(store.conversation_jobs()) == 1
