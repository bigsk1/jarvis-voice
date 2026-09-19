"""Phase 1b: real Web turns, SQLite, leases and local child processes; no live providers."""

import subprocess
import sys
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import flask_socketio
import pytest
import test_orchestrator_tool_turn_budget as orchestrator_fixture
from flask import Flask
from test_web_attachment_bundle_chat import chat, web_config
from test_web_attachment_bundle_chat import journey as journey

from lib.background_tasks import AdmissionDenied, TaskError, TaskStore


def eventually(predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("Expected condition did not become true")


@pytest.fixture
def web_tasks(journey, monkeypatch):
    import executor
    import orchestrator_v2
    import webui_auth
    from jarvis_bundle_chat_test import socket_auth
    from jarvis_bundle_chat_test.routes.background_tasks import background_bp
    from jarvis_bundle_chat_test.services import tool_discovery
    from jarvis_bundle_chat_test.services.background_tasks import WebBackgroundTasks
    from tool_schema import ToolSchema

    tasks = TaskStore(journey.tmp / "tasks.db")
    tasks.initialize()
    tasks.configure(background_enabled=True, background_tools=['fixture'])
    journey.store.background_tasks = tasks
    root = journey.tmp / "worker"
    root.mkdir()
    config = journey.tmp / "config-root" / "config"
    config.mkdir(parents=True)
    for mode in ("cloud", "local"):
        (config / f"{mode}.env").write_text("")
    script = root / "foreground.py"
    script.write_text("""import json, pathlib, sys, time
root = pathlib.Path(__file__).parent
(root / "foreground_started").touch()
while not (root / "foreground_finish").exists():
    time.sleep(.01)
print(json.dumps({"ok": True, "speech": "The foreground clock returned.", "data": {"time": "12:00"}}))
""")
    schemas = {
        "fixture": ToolSchema(
            "fixture",
            "Inert fixture",
            {"type": "object"},
            str(root / "never-execute.py"),
            execution={"background": {"supported": True, "adapter": "local_fixture"}},
        ),
        "get_time": ToolSchema(
            "get_time", "Inert foreground clock", {"type": "object"}, str(script)
        ),
    }
    registry = SimpleNamespace(
        list_tools=lambda: list(schemas), get_tool=schemas.get, is_mcp_tool=lambda name: False
    )
    monkeypatch.setattr(
        executor, "export_config_environment", lambda mode: {"PATH": "/usr/bin:/bin"}
    )
    monkeypatch.setattr(
        executor, "get_logger", lambda mode: SimpleNamespace(log_tool_call=lambda **kw: None)
    )
    monkeypatch.setattr(
        web_config,
        "get_web_setting",
        lambda key, default=None: (
            True
            if key == "ui.progress_events"
            else False
            if key == "audio.tts_enabled"
            else default
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "jarvis_bundle_chat_test.app",
        SimpleNamespace(get_startup_mode=lambda: "cloud"),
    )
    monkeypatch.setattr(
        tool_discovery, "get_tool_service", lambda mode: SimpleNamespace(get_tool_count=lambda: 0)
    )
    monkeypatch.setattr(chat, "emit", flask_socketio.emit)
    for module in (webui_auth, socket_auth):
        monkeypatch.setattr(module, "is_auth_enabled", lambda: True)
        monkeypatch.setattr(
            module,
            "verify_token",
            lambda token: {"exp": time.time() + 3600} if token == "operator-test" else None,
        )
    app = Flask(__name__)
    socket = socket_auth.AuthenticatedSocketIO(app, async_mode="threading")
    handler = chat.ChatHandler(socket)
    for name in (
        "_get_completion_guard_config",
        "_compute_effective_evidence",
        "_is_user_reaction_eligible",
    ):
        monkeypatch.setattr(handler, name, getattr(journey.handler, name))
    summaries, instances, threads = [], [], []

    def synthesize(job, authorization, conversation):
        summaries.append((job, authorization, conversation))
        return {"text": "The background fixture completed.", "data": {"fixture": job["result"]}}

    background = WebBackgroundTasks(
        handler, adapters={"fixture": "local_fixture"}, registry=registry, synthesize=synthesize
    )
    handler.background_tasks = background
    app.extensions["jarvis_background_tasks"] = background
    app.register_blueprint(background_bp)
    original_launch = handler._start_blocking_task

    def launch(*args, **kwargs):
        thread = original_launch(*args, **kwargs)
        threads.append(thread)
        return thread

    monkeypatch.setattr(handler, "_start_blocking_task", launch)

    def factory(mode, **kwargs):
        instance = orchestrator_fixture.ToolTurnBudgetTests()._build_orchestrator(
            fail_on_calls=set()
        )
        instance.registry = registry
        instance.executor = executor.ToolExecutor(mode=mode, registry=registry)
        instance.executor.skills_dir = root
        instance.status_updater.set_speech_callback = lambda fn: None
        instance._format_multi_turn_summary = lambda transcript, tools, data, text: text
        instance._format_single_turn_casual = lambda transcript, text: text
        instance._format_auto_mode = lambda transcript, tools, data, text, turn: text
        # Keep the real routing loop/executor. Only the LLM's decision is deterministic.
        decisions = []

        def route(*args, **kwargs):
            if not decisions:
                from router_v2 import extract_current_user_request
                query = extract_current_user_request(args[0])
                tool = 'get_time' if 'What time is it?' in query else 'fixture'
                decisions.append(tool)
                return {
                    "intent": "tool",
                    "tool_name": tool,
                    "arguments": {},
                    "tool_call_id": "call-1",
                }
            return {
                "intent": "qa",
                "text_response": "Queued; results will follow."
                if decisions[0] == "fixture"
                else "The foreground clock returned.",
            }

        instance.router.route = route
        instances.append(instance)
        return instance

    monkeypatch.setattr(orchestrator_v2, "Orchestrator", factory)
    worker = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).parent / "fixtures/background_task_worker.py"),
            "--db",
            str(tasks.path),
            "--root",
            str(root),
            "--config-root",
            str(config.parent),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    eventually(lambda: tasks.healthy_workers())
    background.start()
    clients = []

    def connect(origin="http://localhost", token="operator-test"):
        client = socket.test_client(app, auth={"token": token}, headers={"Origin": origin})
        clients.append(client)
        return client

    client = connect()
    client.get_received()

    def send_background(mode="cloud"):
        client.emit(
            "chat:send",
            {
                "message": "Run the inert fixture in the background.",
                "mode": mode,
            },
        )
        job = eventually(lambda: next(iter(tasks.conversation_jobs()), None))
        eventually(lambda: tasks.get(job["id"])["state"] == "running")
        return tasks.get(job["id"])

    harness = SimpleNamespace(
        **vars(journey),
        tasks=tasks,
        background=background,
        root=root,
        app=app,
        client=client,
        connect=connect,
        summaries=summaries,
        worker=worker,
        send_background=send_background,
    )
    harness.handler, harness.socket, harness.instances = handler, socket, instances
    try:
        yield harness
    finally:
        (root / "finish").touch()
        (root / "foreground_finish").touch()
        for thread in threads:
            thread.join(5)
        background.close()
        for client in clients:
            if client.is_connected():
                client.disconnect()
        worker.terminate()
        worker.communicate(timeout=6)
        for lease in list(handler.runs.leases.values()):
            lease.release()


def test_web_duplicate_admission_still_allows_independent_foreground_work(web_tasks, monkeypatch):
    import orchestrator_v2

    h = web_tasks
    original_factory = orchestrator_v2.Orchestrator
    decisions = iter([
        {"intent": "tool", "tool_name": "fixture", "arguments": {}, "tool_call_id": "first"},
        {"intent": "tool", "tool_name": "fixture", "arguments": {}, "tool_call_id": "repeat"},
        {"intent": "tool", "tool_name": "get_time", "arguments": {}, "tool_call_id": "clock"},
        {"intent": "qa", "text_response": "The clock returned; the fixture is pending."},
    ])

    def factory(*args, **kwargs):
        instance = original_factory(*args, **kwargs)
        instance.router.route = lambda *a, **kw: next(decisions)
        return instance

    monkeypatch.setattr(orchestrator_v2, "Orchestrator", factory)
    (h.root / "foreground_finish").touch()
    h.client.emit("chat:send", {
        "message": "Run the fixture and check the time", "mode": "cloud",
        "background_tools": ["fixture"], "allow_repeated_background": True,
    })
    job = eventually(lambda: next(iter(h.tasks.conversation_jobs()), None))
    eventually(lambda: h.tasks.get(job["id"])["state"] == "running")
    conversation = h.store.get_conversation(job["conversation_id"])
    assert conversation["run"]["status"] == "completed"
    assert len(h.tasks.conversation_jobs()) == 1
    assert (h.root / "foreground_started").exists()
    answer = conversation["messages"][-1]
    assert answer["tools_used"] == ["get_time"]
    assert [item["job_id"] for item in answer["data"]["pending_jobs"]] == [job["id"]]
    assert "allow_repeated_background" not in conversation["messages"][0]["data"]
    authorization = h.tasks.authorization(job["admission"]["authorization_id"])
    assert "allow_repeated_background" not in authorization


def test_saved_background_policy_is_authenticated_persistent_and_not_a_client_override(web_tasks):
    h = web_tasks
    http = h.app.test_client()
    headers = {'Authorization': 'Bearer operator-test', 'Origin': 'http://localhost'}
    for bad_headers, code in [({}, 401), ({**headers, 'Origin': 'http://evil.test'}, 403)]:
        assert http.patch('/api/background-tasks', json={'background_tools': []}, headers=bad_headers).status_code == code
    assert http.patch('/api/background-tasks', json={'background_tools': ['get_time']}, headers=headers).status_code == 409
    h.worker.terminate()
    h.worker.communicate(timeout=6)
    response = http.patch('/api/background-tasks', json={'background_enabled': True, 'background_tools': ['fixture']}, headers=headers)
    assert response.status_code == 200, response.get_json()
    assert TaskStore(h.tasks.path).settings()['background_tools'] == ['fixture']
    status = http.get('/api/background-tasks', headers=headers).get_json()
    assert status['settings']['background_enabled']
    assert not status['worker_ready']
    # Unrelated chat works with saved preferences even when the worker is offline.
    (h.root / 'foreground_finish').touch()
    h.client.emit('chat:send', {'message': 'What time is it?', 'mode': 'cloud', 'background_tools': ['get_time']})
    eventually(lambda: (h.root / 'foreground_started').exists())
    eventually(lambda: not h.handler.runs.active)
    assert not h.tasks.conversation_jobs()
    assert any(e['name'] == 'chat:response' for e in h.client.get_received())
    # A call to the enabled tool reports unavailability; it never runs foreground.
    h.client.emit('chat:send', {'message': 'Run the fixture', 'mode': 'cloud'})
    eventually(lambda: len(h.instances) == 2)
    eventually(lambda: not h.handler.runs.active)
    assert h.instances[-1].background_context.selected == ('fixture',)
    assert not h.tasks.conversation_jobs()
    assert not h.instances[-1].background_context.receipts


def test_browser_setup_operator_action_owns_the_full_normal_flow(web_tasks, monkeypatch):
    import browser_agent
    from jarvis_bundle_chat_test.routes import background_tasks as routes

    from lib.webhook_integrations import browser

    h = web_tasks
    steps = []
    monkeypatch.setattr(browser_agent, 'install_runtime', lambda: steps.append('runtime'))
    monkeypatch.setattr(browser, 'activate', lambda *args: steps.append('activate'))
    monkeypatch.setattr(routes, 'ensure_task_worker', lambda tasks: steps.append('worker'))
    monkeypatch.setattr(routes, 'browser_command', lambda action, tasks: steps.append(action))
    monkeypatch.setattr(routes, 'browser_details', lambda tasks: {'ready': True, 'operational': True})
    response = h.app.test_client().post(
        '/api/background-tasks/tools/browser_use/actions', json={'action': 'setup'},
        headers={'Authorization': 'Bearer operator-test', 'Origin': 'http://localhost'},
    )
    assert response.status_code == 202
    eventually(lambda: len(steps) == 4)
    assert steps == ['runtime', 'activate', 'worker', 'start']
    eventually(lambda: routes._browser_setup_status(h.background)['state'] == 'ready')


def test_browser_setup_restarts_an_idle_worker_that_cannot_run_callbacks(web_tasks, monkeypatch):
    from jarvis_bundle_chat_test.routes import background_tasks as routes

    h = web_tasks
    actions = []
    monkeypatch.setattr(h.tasks, 'healthy_workers', lambda: [{'adapters': ['local_skill_v1']}])
    monkeypatch.setattr(h.tasks, 'counts', lambda: {'running': 0, 'reserved': 0})
    monkeypatch.setattr(routes, 'task_worker_command', lambda action, tasks: actions.append(action))
    routes.ensure_task_worker(h.background)
    assert actions == ['restart']


def test_browser_setup_will_not_restart_a_worker_with_reserved_work(web_tasks, monkeypatch):
    from jarvis_bundle_chat_test.routes import background_tasks as routes

    h = web_tasks
    monkeypatch.setattr(h.tasks, 'healthy_workers', lambda: [{'adapters': ['local_skill_v1']}])
    monkeypatch.setattr(h.tasks, 'counts', lambda: {'running': 0, 'reserved': 1})
    monkeypatch.setattr(routes, 'task_worker_command', lambda *_: pytest.fail('must not restart active worker'))
    with pytest.raises(TaskError, match='must be upgraded'):
        routes.ensure_task_worker(h.background)


def test_saved_policy_survives_multiple_messages_without_client_selection(web_tasks):
    h = web_tasks
    first = h.send_background()
    (h.root / 'finish').touch()
    eventually(lambda: h.tasks.get(first['id'])['state'] == 'succeeded')
    h.client.emit('chat:send', {'conversation_id': first['conversation_id'],
                              'message': 'Run the fixture again', 'mode': 'cloud'})
    eventually(lambda: len(h.tasks.conversation_jobs()) == 2)
    assert h.tasks.settings()['background_tools'] == ['fixture']


@pytest.mark.parametrize('input_mode,origin', [('talk','http://localhost'), ('text','moz-extension://fixture'), ('text',None)])
def test_saved_policy_is_not_inherited_by_talk_or_companion(web_tasks, monkeypatch, input_mode, origin):
    h = web_tasks
    # Avoid real tool execution; verify the shared executor stays foreground.
    import executor
    foreground = []
    monkeypatch.setattr(executor.ToolExecutor, '_execute_foreground',
                        lambda self, name, args, *a, **kw: foreground.append(name) or {'ok': True, 'speech': 'Foreground fixture', 'data': {}})
    client = h.socket.test_client(h.app, auth={'token':'operator-test'}, headers={'Origin':origin} if origin else {})
    try:
        client.get_received()
        client.emit('chat:send', {'message': 'Run the fixture', 'mode':'cloud', 'input_mode':input_mode,
                                  'background_tools':['fixture']})
        eventually(lambda: foreground)
        eventually(lambda: not h.handler.runs.active)
        assert foreground == ['fixture']
        assert not h.tasks.conversation_jobs()
        cid = next(s['conversation_id'] for s in h.handler.sessions.values() if s.get('conversation_id'))
        client.emit('tasks:subscribe', {'conversation_id': cid})
        assert any(event['name'] == 'tasks:snapshot' for event in client.get_received())
    finally:
        client.disconnect()


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_admit_chat_with_second_tool_then_late_result(web_tasks, mode):
    h = web_tasks
    job = h.send_background(mode)
    cid = job["conversation_id"]
    h.client.emit("tasks:subscribe", {"conversation_id": cid})
    conversation = h.store.get_conversation(cid)
    assert [m["role"] for m in conversation["messages"]] == ["user", "assistant"]
    assert conversation["run"]["status"] == "completed"
    assert conversation["messages"][1]["data"]["pending_jobs"][0]["job_id"] == job["id"]
    assert not conversation["messages"][1]["tools_used"]
    assert not (h.root / "never-execute.py").exists()
    initial = h.client.get_received()
    assert not [
        e
        for e in initial
        if e["name"].startswith("tool:") and e["args"][0].get("tool") == "fixture"
    ]
    h.client.emit(
        "chat:send", {"conversation_id": cid, "message": "What time is it?", "mode": mode}
    )
    eventually(lambda: (h.root / "foreground_started").exists())
    second_id = h.store.get_conversation(cid)["run"]["message_id"]
    h.client.get_received()
    (h.root / "finish").touch()
    eventually(lambda: h.tasks.get(job["id"])["state"] == "succeeded")
    eventually(
        lambda: (
            h.store.get_conversation(cid)["messages"][1]["data"]["background_jobs"][job["id"]][
                "state"
            ]
            == "succeeded"
        )
    )
    assert h.store.get_conversation(cid)["run"]["message_id"] == second_id
    assert h.store.get_conversation(cid)["run"]["status"] == "running"
    assert not h.summaries
    events = h.client.get_received()
    assert any(e["name"] == "task:updated" for e in events)
    assert not any(
        e["name"] in ("chat:response", "chat:continuation", "tool:complete") for e in events
    )
    (h.root / "foreground_finish").touch()
    eventually(lambda: len(h.store.get_conversation(cid)["messages"]) == 5)
    eventually(lambda: h.store.get_conversation(cid)["run"]["status"] == "completed")
    saved = h.store.get_conversation(cid)
    assert [m["role"] for m in saved["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "assistant",
    ]
    assert saved["messages"][3]["tools_used"] == ["get_time"]
    assert saved["messages"][4]["data"]["_kind"] == "continuation"
    assert saved["messages"][4]["data"]["parent_message_id"] == job["admission"]["request_id"]
    assert h.summaries[0][0]["mode"] == mode
    assert h.summaries[0][2]["messages"][-1]["content"] == "The foreground clock returned."
    events = h.client.get_received()
    assert len([e for e in events if e["name"] == "chat:continuation"]) == 1
    assert len([e for e in events if e["name"] == "chat:response"]) == 1  # Foreground only.
    h.background.drain_once(inline=True)
    assert len(h.summaries) == 1
    assert len(list(h.root.glob("*.started"))) == 1
    # An offline/reconnected client receives the same saved answer and card.
    h.client.disconnect()
    second = h.connect()
    second.emit("conversation:load", {"conversation_id": cid})
    restored = next(
        e["args"][0]["conversation"]
        for e in second.get_received()
        if e["name"] == "conversation:loaded"
    )
    assert len(restored["messages"]) == 5
    assert restored["messages"][1]["data"]["background_jobs"][job["id"]]["state"] == "succeeded"


def test_receipt_save_failure_never_releases_or_executes(web_tasks, monkeypatch):
    h = web_tasks
    original = h.store.add_message

    def fail_receipt(conv_id, role, *args, **kwargs):
        if role == "assistant":
            raise OSError("injected receipt save failure")
        return original(conv_id, role, *args, **kwargs)

    monkeypatch.setattr(h.store, "add_message", fail_receipt)
    h.client.emit(
        "chat:send", {"message": "Run fixture", "mode": "cloud", "background_tools": ["fixture"]}
    )
    job = eventually(lambda: next(iter(h.tasks.conversation_jobs()), None))
    eventually(lambda: job["conversation_id"] not in h.handler.runs.active)
    h.background.recover_receipts()
    assert h.tasks.get(job["id"])["dispatch_state"] == "held"
    assert not list(h.root.glob("*.started"))


def test_coordinator_ownership_conflict_keeps_chat_and_status_available(web_tasks, monkeypatch):
    from jarvis_bundle_chat_test.services.background_tasks import WebBackgroundTasks

    h = web_tasks
    other = WebBackgroundTasks(h.handler, adapters=h.background.adapters, registry=h.background.registry)
    # Execute both production boot entry points with isolated configuration and
    # the network listener replaced, so no operator service/config is touched.
    import ast

    app_path = Path(__file__).resolve().parents[1] / 'jarvis-web/server/app.py'
    module = ast.parse(app_path.read_text())
    boot = ast.Module(body=[node for node in module.body if isinstance(node, ast.FunctionDef)
                           and node.name in {'create_app', 'run_server'}], type_ignores=[])
    listeners = []
    scope = {
        'chat_handler': SimpleNamespace(background_tasks=other),
        'load_web_config': lambda: None, 'load_jarvis_config': lambda mode: None,
        'get_web_setting': lambda key, default: default, 'is_auth_enabled': lambda: True,
        'JARVIS_ROOT': h.tmp, 'app': h.app,
        'socketio': SimpleNamespace(run=lambda *args, **kwargs: listeners.append(kwargs)),
    }
    exec(compile(boot, str(app_path), 'exec'), scope)
    assert scope['create_app']()[0] is h.app
    scope['run_server']()
    assert len(listeners) == 1
    assert other.start() is False
    assert other.thread is None and other.ownership is None
    assert h.background.ready()
    monkeypatch.setattr(h.handler, 'background_tasks', other)
    monkeypatch.setitem(h.app.extensions, 'jarvis_background_tasks', other)
    headers = {'Authorization': 'Bearer operator-test'}
    response = h.app.test_client().get('/api/background-tasks', headers=headers)
    assert response.status_code == 200
    assert response.json['coordinator_ready'] is False
    assert 'Another Web coordinator' in response.json['coordinator_unavailable_reason']
    # Explicitly enabling on the losing process still fails closed.
    h.tasks.configure(background_enabled=False)
    response = h.app.test_client().patch('/api/background-tasks', headers=headers,
                                       json={'background_enabled': True})
    assert response.status_code == 409
    assert h.tasks.settings()['background_enabled'] is False
    h.tasks.configure(background_enabled=True)
    h.client.emit('chat:send', {'message': 'Run fixture', 'mode': 'cloud', 'background_tools': ['fixture']})
    eventually(lambda: h.instances)
    eventually(lambda: not h.handler.runs.active)
    assert any(e['name'] == 'chat:response' for e in h.client.get_received())
    assert h.instances[-1].background_context.receipts == {}
    assert not h.tasks.conversation_jobs()
    (h.root / 'foreground_finish').touch()
    h.client.emit('chat:send', {'message': 'What time is it?', 'mode': 'cloud'})
    events = []
    def answered():
        events.extend(h.client.get_received())
        return any(e['name'] == 'chat:response' for e in events)
    eventually(answered)
    assert (h.root / 'foreground_started').exists()
    assert not h.tasks.conversation_jobs()
    assert other.thread is None and h.background.ready()
    # Disabling admission is still available and does not steal the drain lock.
    response = h.app.test_client().patch('/api/background-tasks', headers=headers,
                                       json={'background_enabled': False})
    assert response.status_code == 200
    h.background.close()
    try:
        assert other.start() is True
        assert other.unavailable_reason is None
    finally:
        other.close()


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({}, 401),
        ({"Cookie": "jarvis_auth=operator-test"}, 401),
        ({"Authorization": "Bearer operator-test", "Origin": "https://hostile.example"}, 403),
        ({"Authorization": "Bearer operator-test", "Origin": "http://localhost"}, 200),
        ({"Authorization": "Bearer operator-test"}, 200),
    ],
)
def test_operator_routes_require_explicit_bearer_and_origin(web_tasks, headers, expected):
    response = web_tasks.app.test_client().get(
        "/api/background-tasks?token=operator-test", headers=headers
    )
    assert response.status_code == expected


def test_unconfigured_auth_and_cross_origin_admission_fail_closed(web_tasks, monkeypatch):
    import webui_auth

    h = web_tasks
    monkeypatch.setattr(webui_auth, "is_auth_enabled", lambda: False)
    assert (
        h.app.test_client()
        .get("/api/background-tasks", headers={"Authorization": "Bearer operator-test"})
        .status_code
        == 401
    )
    remote = h.connect("https://hostile.example")
    remote.emit(
        "chat:send", {"message": "Run fixture", "mode": "cloud", "background_tools": ["fixture"]}
    )
    eventually(lambda: h.instances)
    eventually(lambda: not h.handler.runs.active)
    assert not h.tasks.conversation_jobs()
    assert getattr(h.instances[-1], 'background_context', None) is None


@pytest.mark.parametrize("action", ["clear", "delete"])
def test_dispose_requires_explicit_generation_and_fences_execution(web_tasks, action):
    h = web_tasks
    job = h.send_background()
    cid = job["conversation_id"]
    method = h.store.clear_conversation if action == "clear" else h.store.delete_conversation
    with pytest.raises(AdmissionDenied):
        method(cid)
    headers = {"Authorization": "Bearer operator-test", "Origin": "http://localhost"}
    client = h.app.test_client()
    url = f"/api/background-tasks/conversations/{cid}/dispose"
    assert (
        client.post(url, json={"action": action, "generation": 99}, headers=headers).status_code
        == 409
    )
    assert (
        client.post(
            url, json={"action": action, "generation": job["generation"]}, headers=headers
        ).status_code
        == 200
    )
    assert h.tasks.get(job["id"])["state"] == "needs_attention"
    (h.root / "finish").touch()
    h.background.drain_once(inline=True)
    assert not h.summaries
    conversation = h.store.get_conversation(cid)
    assert conversation is None if action == "delete" else conversation["messages"] == []


def test_generated_output_is_reused_after_projection_failure(web_tasks, monkeypatch):
    h = web_tasks
    job = h.send_background()
    original = h.store.project_continuation
    failed = threading.Event()

    def fail_once(*args):
        if not failed.is_set():
            failed.set()
            raise OSError("injected projection failure")
        return original(*args)

    monkeypatch.setattr(h.store, "project_continuation", fail_once)
    (h.root / "finish").touch()
    assert failed.wait(6)
    eventually(
        lambda: len(h.store.get_conversation(job["conversation_id"])["messages"]) == 3, timeout=8
    )
    assert len(h.summaries) == 1
    assert len(list(h.root.glob("*.started"))) == 1


def test_disable_stops_new_admission_but_accepted_job_still_delivers(web_tasks):
    h = web_tasks
    job = h.send_background()
    response = h.app.test_client().patch(
        "/api/background-tasks",
        json={"background_enabled": False},
        headers={"Authorization": "Bearer operator-test"},
    )
    assert response.status_code == 200
    assert not h.tasks.settings()["background_enabled"]
    (h.root / "finish").touch()
    eventually(lambda: len(h.store.get_conversation(job["conversation_id"])["messages"]) == 3)
    assert len(h.summaries) == 1
    h.client.emit(
        "chat:send",
        {
            "conversation_id": job["conversation_id"],
            "message": "Another fixture",
            "mode": "cloud",
            "background_tools": ["fixture"],
        },
    )
    eventually(lambda: job["conversation_id"] not in h.handler.runs.active)
    assert len(h.tasks.conversation_jobs()) == 1


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_continuation_uses_original_provider_with_all_tools_disabled(web_tasks, monkeypatch, mode):
    import json

    import config_loader
    import llm_provider

    h = web_tasks
    job = h.send_background(mode)
    captured = []

    class Provider:
        def chat(self, prompt, **kwargs):
            captured.append((config_loader.get_active_config_mode(), prompt, kwargs))
            return "Fixture result summary"

    def factory(**kwargs):
        captured.append(kwargs)
        return None, None, Provider()

    monkeypatch.setattr(llm_provider, "create_configured_provider", factory)
    auth = h.tasks.authorization(job["admission"]["authorization_id"])
    assert 'query' not in auth
    output = h.background._synthesize(job, auth, h.store.get_conversation(job["conversation_id"]))
    assert captured[0] == {
        "provider_override": "test",
        "model_override": "fake-model",
        "mode": mode,
        "disable_server_side_tools": True,
    }
    assert captured[1][0] == mode
    assert json.loads(captured[1][1])['original_request'] == 'Run the inert fixture in the background.'
    assert output["text"] == "Fixture result summary"


def test_browser_continuation_preserves_full_report_without_a_second_llm(web_tasks, monkeypatch):
    import llm_provider

    h = web_tasks
    monkeypatch.setattr(llm_provider, 'create_configured_provider',
                        lambda **_: pytest.fail('Browser report must not be resummarized'))
    report = 'Saved research: stash://space/report\n\n' + ('Complete evidence. ' * 400)
    job = {'admission': {'tool': 'browser_use'}, 'result': {'ok': True, 'speech': report,
           'data': {'browser_research': {'kind': 'browser_research'}}}}
    output = h.background._synthesize(job, {'provider': 'ollama', 'model': 'selected'}, {'messages': []})
    assert output['text'] == report.rstrip()
    assert output['data']['browser_use']['speech'] == report


@pytest.mark.parametrize('ok', [True, False])
def test_callback_continuation_preserves_full_report_without_a_second_llm(web_tasks, monkeypatch, ok):
    import llm_provider

    monkeypatch.setattr(llm_provider, 'create_configured_provider',
                        lambda **_: pytest.fail('Callback report must not be resummarized'))
    report = '# Full report\n\n' + ('Observed evidence. ' * 400).rstrip()
    job = {'adapter': 'http_callback_v1', 'admission': {'tool': 'private_probe'},
           'result': {'ok': ok, 'speech': report, 'data': {}}}
    output = web_tasks.background._synthesize(job, {'provider': 'ollama', 'model': 'selected'},
                                                {'messages': []})
    assert output['text'] == report
    assert output['data']['_callback_tool'] == 'private_probe'
    assert output['data']['private_probe'] == job['result']


def test_restart_drains_saved_result_without_reexecuting_tool(web_tasks):
    from jarvis_bundle_chat_test.services.background_tasks import WebBackgroundTasks

    h = web_tasks
    job = h.send_background()
    h.background.close()
    (h.root / "finish").touch()
    eventually(lambda: h.tasks.get(job["id"])["state"] == "succeeded")
    assert len(h.store.get_conversation(job["conversation_id"])["messages"]) == 2
    second = WebBackgroundTasks(h.handler, synthesize=h.background.synthesize)
    try:
        second.start()
        eventually(lambda: len(h.store.get_conversation(job["conversation_id"])["messages"]) == 3)
        assert len(h.summaries) == 1
        assert len(list(h.root.glob("*.started"))) == 1
    finally:
        second.close()


def test_continuation_defers_while_other_conversation_uses_other_mode(web_tasks):
    h = web_tasks
    job = h.send_background("cloud")
    other = h.store.create_conversation()["id"]
    h.client.emit(
        "chat:send", {"conversation_id": other, "message": "What time is it?", "mode": "local"}
    )
    eventually(lambda: (h.root / "foreground_started").exists())
    (h.root / "finish").touch()
    eventually(lambda: h.tasks.get(job["id"])["state"] == "succeeded")
    h.background.drain_once(inline=True)
    assert not h.summaries
    assert h.store.get_conversation(other)["run"]["status"] == "running"
    (h.root / "foreground_finish").touch()
    eventually(lambda: len(h.store.get_conversation(job["conversation_id"])["messages"]) == 3)
    assert h.summaries[0][0]["mode"] == "cloud"


def test_task_subscription_and_delivery_recheck_feature_credentials(web_tasks, monkeypatch):
    from jarvis_bundle_chat_test import socket_auth

    h = web_tasks
    job = h.send_background()
    h.client.emit("tasks:subscribe", {"conversation_id": job["conversation_id"]})
    assert any(e["name"] == "tasks:snapshot" for e in h.client.get_received())
    monkeypatch.setattr(socket_auth, "is_auth_enabled", lambda: False)
    h.socket.emit_background(
        "task:updated", {"job_id": job["id"]}, room=f"tasks:{job['conversation_id']}"
    )
    assert h.client.get_received() == []
    h.client.emit("tasks:subscribe", {"conversation_id": job["conversation_id"]})
    assert not any(e["name"] == "tasks:snapshot" for e in h.client.get_received())


def test_reverse_proxy_origin_requires_explicit_deployment_allowlist(web_tasks, monkeypatch):
    h = web_tasks
    headers = {
        "Authorization": "Bearer operator-test",
        "Origin": "https://jarvis.example",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "jarvis.example",
    }
    client = h.app.test_client()
    assert client.get("/api/background-tasks", headers=headers).status_code == 403
    monkeypatch.setenv("JARVIS_WEB_BACKGROUND_ALLOWED_ORIGINS", "https://jarvis.example")
    assert client.get("/api/background-tasks", headers=headers).status_code == 200
    assert (
        client.get(
            "/api/background-tasks", headers={**headers, "Origin": "https://hostile.example"}
        ).status_code
        == 403
    )


@pytest.mark.parametrize('original,current', [('cloud','local'), ('local','cloud')])
def test_same_conversation_mode_switch_preserves_pending_job_and_recovery(web_tasks, monkeypatch, original, current):
    import tool_schema
    from jarvis_bundle_chat_test.services import settings_manager
    h = web_tasks
    selected = []
    monkeypatch.setattr(settings_manager, 'get_settings_manager',
                        lambda: SimpleNamespace(set_mode=selected.append))
    monkeypatch.setattr(web_config, 'reload_web_config', lambda: None)
    monkeypatch.setattr(tool_schema, 'reset_tool_registry', lambda: None)
    job = h.send_background(original)
    cid = job['conversation_id']
    h.client.emit('tasks:subscribe', {'conversation_id': cid})
    h.client.get_received()
    h.client.emit('mode:set', {'mode': current})
    events = h.client.get_received()
    assert any(e['name'] == 'mode:changed' and e['args'][0]['mode'] == current for e in events)
    assert selected == [current]
    h.client.emit('chat:send', {'conversation_id': cid, 'message': 'What time is it?', 'mode': current})
    eventually(lambda: (h.root / 'foreground_started').exists())
    assert h.instances[-1].executor.mode == current
    (h.root / 'finish').touch()
    eventually(lambda: h.tasks.get(job['id'])['state'] == 'succeeded')
    h.background.drain_once(inline=True)
    assert not h.summaries
    (h.root / 'foreground_finish').touch()
    eventually(lambda: len(h.store.get_conversation(cid)['messages']) == 5)
    assert h.summaries[0][0]['mode'] == original
    assert h.summaries[0][1]['mode'] == original
    assert h.store.get_conversation(cid)['messages'][3]['tools_used'] == ['get_time']
    reconnect = h.connect()
    reconnect.emit('conversation:load', {'conversation_id': cid})
    recovered = next(e['args'][0]['conversation'] for e in reconnect.get_received() if e['name'] == 'conversation:loaded')
    assert len(recovered['messages']) == 5
    assert recovered['messages'][-1]['data']['_kind'] == 'continuation'
    assert h.tasks.get(job['id'])['mode'] == original


def test_management_requires_operator_auth_and_exposes_durable_actions(web_tasks):
    from test_background_tasks import admission
    h = web_tasks
    http = h.app.test_client()
    headers = {'Authorization': 'Bearer operator-test', 'Origin': 'http://localhost'}
    cid = h.store.create_conversation()['id']
    job = h.tasks.admit(admission(conversation_id=cid, generation=0))
    path = '/api/background-jobs/' + job['id']
    for action in ('cancel', 'reconcile', 'retry_delivery', 'suppress_delivery', 'read'):
        assert http.post(path+'/actions', json={'action':action}).status_code == 401
        assert http.post(path+'/actions', json={'action':action}, headers={**headers, 'Origin':'http://evil.test'}).status_code == 403
    page = http.get('/api/background-jobs?limit=1', headers=headers).get_json()
    assert page['total'] == 1 and page['jobs'][0]['can_cancel']
    response = http.post(path+'/actions', json={'action':'cancel','revision':job['revision']}, headers=headers)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['job']['state'] == 'cancelled'
    assert response.get_json()['job']['operator_events'][0]['action'] == 'cancelled'
    response = http.patch('/api/background-tasks', json={'background_enabled':False, 'max_running':3,
                          'max_per_adapter':1, 'max_outstanding':5, 'max_queued':20}, headers=headers)
    assert response.status_code == 200
    assert response.get_json()['settings']['max_running'] == 3
    assert http.patch('/api/background-tasks', json={'max_running':0}, headers=headers).status_code == 409
    read = http.post(path+'/actions', json={'action':'read'}, headers=headers)
    assert read.status_code == 200
    assert http.get('/api/background-jobs', headers=headers).get_json()['counts']['unread'] == 0


def test_browser_setup_returns_202_and_second_click_joins_the_same_pull(web_tasks, monkeypatch):
    import browser_agent
    from jarvis_bundle_chat_test.routes import background_tasks as routes

    from lib.webhook_integrations import browser

    h = web_tasks
    h.background.adapters['browser_use'] = 'http_callback_v1'
    headers = {'Authorization': 'Bearer operator-test', 'Origin': 'http://localhost'}
    started, release = threading.Event(), threading.Event()
    calls = []

    def install():
        calls.append('pull')
        started.set()
        assert release.wait(5)

    monkeypatch.setattr(browser_agent, 'install_runtime', install)
    monkeypatch.setattr(browser, 'activate', lambda *_args, **_kwargs: calls.append('activate'))
    monkeypatch.setattr(routes, 'ensure_task_worker', lambda _tasks: calls.append('worker'))
    monkeypatch.setattr(routes, 'browser_command', lambda _action, _tasks: calls.append('helper'))
    http = h.app.test_client()
    path = '/api/background-tasks/tools/browser_use/actions'
    try:
        first = http.post(path, json={'action': 'setup'}, headers=headers)
        assert first.status_code == 202
        assert started.wait(2)
        second = http.post(path, json={'action': 'setup'}, headers=headers)
        assert second.status_code == 202
        assert calls == ['pull']
        state = http.get('/api/background-tasks?mode=cloud', headers=headers).get_json()
        assert state['tool_details']['browser_use']['browser_use']['setup']['state'] == 'running'
    finally:
        release.set()
    eventually(lambda: routes._browser_setup_status(h.background)['state'] == 'ready')
    assert calls == ['pull', 'activate', 'worker', 'helper']
    assert oct(routes._browser_setup_paths(h.background)[0].stat().st_mode & 0o777) == '0o600'


def test_interrupted_browser_setup_is_retryable_without_a_second_puller(web_tasks, monkeypatch):
    import browser_agent
    from jarvis_bundle_chat_test.routes import background_tasks as routes

    h = web_tasks
    state_path, _ = routes._browser_setup_paths(h.background)
    routes._write_browser_setup_state(h.background, 'running', 'Pulling image')
    assert routes._browser_setup_status(h.background)['state'] == 'failed'
    monkeypatch.setattr(browser_agent, 'install_runtime', lambda: (_ for _ in ()).throw(
        browser_agent.BrowserPreflightError('Docker image unavailable')))
    http = h.app.test_client()
    headers = {'Authorization': 'Bearer operator-test', 'Origin': 'http://localhost'}
    response = http.post('/api/background-tasks/tools/browser_use/actions',
                         json={'action': 'setup'}, headers=headers)
    assert response.status_code == 202
    eventually(lambda: routes._browser_setup_status(h.background)['state'] == 'failed'
               and 'Docker image unavailable' in routes._browser_setup_status(h.background)['message'])
    assert state_path.is_file()


def test_web_operator_cancel_is_available_only_for_the_bound_browser_callback(tmp_path, monkeypatch):
    import webui_auth
    from jarvis_bundle_chat_test.routes.background_tasks import background_bp
    from jarvis_bundle_chat_test.services.background_tasks import WebBackgroundTasks
    from test_browser_review_gates import cancel_bound_browser
    from test_task_callbacks import bound

    integration, source, _, claim, _, _ = cancel_bound_browser(tmp_path)
    tasks = integration.store
    tasks.configure(background_tools=['browser_use', 'callback_probe'])
    other, _ = bound(integration, source, invocation='other-callback')
    app = Flask(__name__)
    app.extensions['jarvis_background_tasks'] = SimpleNamespace(
        store=tasks, card=WebBackgroundTasks.card,
        handler=SimpleNamespace(runs=SimpleNamespace(conversation_lock=lambda _id: nullcontext())))
    app.register_blueprint(background_bp)
    monkeypatch.setattr(webui_auth, 'is_auth_enabled', lambda: True)
    monkeypatch.setattr(webui_auth, 'verify_token', lambda token: bool(token == 'operator-test'))
    http = app.test_client()
    headers = {'Authorization': 'Bearer operator-test', 'Origin': 'http://localhost'}
    page = http.get('/api/background-jobs', headers=headers).get_json()['jobs']
    cards = {item['job_id']: item for item in page}
    assert cards[claim.job_id]['can_cancel'] is True
    assert cards[other.job_id]['can_cancel'] is False
    for job_id, expected in ((claim.job_id, 200), (other.job_id, 409)):
        response = http.post(f'/api/background-jobs/{job_id}/actions', headers=headers,
            json={'action': 'cancel', 'revision': cards[job_id]['revision']})
        assert response.status_code == expected
    assert tasks.get(claim.job_id)['state'] == 'cancel_requested'
    assert tasks.get(other.job_id)['state'] == 'running'


@pytest.mark.parametrize('adapter', ['local_skill_v1', 'remote_fixture'])
@pytest.mark.parametrize('state', ['queued', 'starting', 'running'])
def test_management_cancel_card_matches_api_for_current_and_unsupported_adapters(web_tasks, adapter, state):
    from test_background_tasks import admission, receipt

    h = web_tasks
    h.tasks.configure(background_tools=['convert_file'])
    http = h.app.test_client()
    headers = {'Authorization': 'Bearer operator-test', 'Origin': 'http://localhost'}
    cid = h.store.create_conversation()['id']
    job = h.tasks.admit(admission(conversation_id=cid, generation=0,
                                  tool='convert_file', adapter=adapter))
    if state != 'queued':
        h.tasks.release(job['id'], receipt(job))
        claim = h.tasks.claim('inert-test-owner', {adapter})
        if state == 'running':
            h.tasks.running(claim)

    def card():
        page = http.get('/api/background-jobs', headers=headers).get_json()
        return next(item for item in page['jobs'] if item['job_id'] == job['id'])

    shown = card()
    assert shown['state'] == state
    allowed = state == 'queued' or adapter != 'remote_fixture'
    assert shown['can_cancel'] is allowed
    response = http.post('/api/background-jobs/' + job['id'] + '/actions',
                         json={'action': 'cancel', 'revision': shown['revision']}, headers=headers)
    assert response.status_code == (200 if allowed else 409), response.get_json()
    if not allowed:
        assert h.tasks.get(job['id'])['state'] == state
        return
    if state != 'queued':
        assert response.get_json()['job']['state'] == 'cancel_requested'
        assert h.tasks.counts()['running'] == 1
        assert not card()['can_cancel']
        h.tasks.acknowledge_cancel(claim, 'Inert test claim; no subprocess was launched')
    assert card()['state'] == 'cancelled'
    assert not card()['can_cancel']


def test_installation_watch_requires_web_origin_and_is_independent_of_live_turn(web_tasks):
    h = web_tasks
    h.client.emit('tasks:watch', {})
    assert any(e['name'] == 'tasks:overview' for e in h.client.get_received())
    companion = h.socket.test_client(h.app, auth={'token':'operator-test'}, headers={'Origin':'moz-extension://fixture'})
    try:
        companion.get_received()
        companion.emit('tasks:watch', {})
        assert not any(e['name'] == 'tasks:overview' for e in companion.get_received())
    finally:
        companion.disconnect()
