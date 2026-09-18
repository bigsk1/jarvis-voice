"""Task control-plane contracts using disposable real SQLite stores."""

import json
import os
import sqlite3
import stat
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from lib import config_loader
from lib.background_tasks import (
    Admission,
    AdmissionDenied,
    Conflict,
    LostLease,
    ReceiptEvidence,
    TaskError,
    TaskStore,
)
from lib.background_tasks import store as store_module
from lib.background_tasks.worker import KnownFailure, TaskWorker


def admission(**changes):
    return replace(
        Admission(
            conversation_id="conversation-1",
            generation=1,
            request_id="request-1",
            invocation_id="invocation-1",
            tool="fixture",
            adapter="local_fixture",
            mode="local",
            arguments={"operation": "fixture"},
            authorization_id="authorization-1",
            source="web",
        ),
        **changes,
    )


def receipt(job, **changes):
    source = job["admission"]
    return replace(
        ReceiptEvidence(
            conversation_id=source["conversation_id"],
            generation=source["generation"],
            request_id=source["request_id"],
            receipt_message_id="receipt-1",
            run_status="completed",
            lease_released=True,
        ),
        **changes,
    )


@pytest.fixture
def store(tmp_path):
    instance = TaskStore(tmp_path / "control" / "tasks.db")
    instance.initialize()
    instance.configure(background_enabled=True, background_tools=['fixture'])
    return instance


def ready(store, **changes):
    job = store.admit(admission(**changes))
    return store.release(job["id"], receipt(job))


def test_disabled_reads_and_imports_do_not_create_storage(tmp_path):
    store = TaskStore(tmp_path / "uncreated" / "tasks.db")
    assert store.settings()["background_enabled"] is False
    assert store.settings()["webhooks_enabled"] is False
    assert store.get("absent") is None
    assert store.pending_deliveries() == []
    assert store.healthy_workers() == []
    assert not store.path.parent.exists()


def test_background_preferences_persist_without_changing_existing_work(store):
    job = ready(store)
    store.configure(background_tools=['convert_file'])
    reopened = TaskStore(store.path)
    assert reopened.settings()['background_tools'] == ['convert_file']
    reopened.configure(background_enabled=False)
    assert reopened.settings()['background_tools'] == ['convert_file']
    assert reopened.claim('worker', {'local_fixture'}).job_id == job['id']


def test_background_preferences_migration_preserves_accepted_jobs_without_auto_enabling_tools(tmp_path, monkeypatch):
    legacy = TaskStore(tmp_path / 'previous.db')
    with monkeypatch.context() as patch:
        patch.setattr(store_module, 'MIGRATIONS', store_module.MIGRATIONS[:4])
        legacy.initialize()
        legacy.configure(background_enabled=True)
        # Emulate the pre-preferences binary admitting this job. The current
        # persistence primitive now requires membership in saved preferences.
        settings = legacy._settings
        patch.setattr(legacy, '_settings', lambda conn: {**settings(conn), 'background_tools': ['fixture']})
        job = ready(legacy)
        before = legacy.get(job['id'])
    legacy.initialize()
    assert legacy.settings()['background_tools'] == []
    assert legacy.get(job['id']) == before
    assert legacy.claim('worker', {'local_fixture'}).job_id == job['id']


@pytest.mark.parametrize('tools', ['convert_file', [None], ['convert_file', 'convert_file'], ['../script']])
def test_background_preferences_reject_invalid_names_without_partial_save(store, tools):
    before = store.settings()
    with pytest.raises(TaskError):
        store.configure(background_enabled=False, background_tools=tools)
    assert store.settings() == before


def test_explicit_migration_and_owner_only_sqlite_sidecars(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    previous = os.umask(0o002)
    try:
        store.initialize()
        store.initialize()
        with sqlite3.connect(store.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE settings SET max_running=3")
            for path in (store.path, tmp_path / "tasks.db-wal", tmp_path / "tasks.db-shm"):
                assert stat.S_IMODE(path.stat().st_mode) == 0o600
            assert conn.execute("SELECT version FROM schema_migrations").fetchall() == [
                (version,) for version in range(1, len(store_module.MIGRATIONS) + 1)]
        assert store.settings()["background_enabled"] is False
    finally:
        os.umask(previous)


def test_failed_migration_rolls_back_schema_and_stamp(store, monkeypatch):
    monkeypatch.setattr(
        store_module,
        "MIGRATIONS",
        store_module.MIGRATIONS
        + (
            (
                "CREATE TABLE must_rollback (id INTEGER)",
                "THIS IS NOT SQL",
            ),
        ),
    )
    with pytest.raises(sqlite3.OperationalError):
        store.initialize()
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT version FROM schema_migrations").fetchall() == [
            (version,) for version in range(1, len(store_module.MIGRATIONS))]
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='must_rollback'"
        ).fetchall()


def test_future_schema_rejected_without_downgrade(store):
    with sqlite3.connect(store.path) as conn:
        conn.execute("INSERT INTO schema_migrations VALUES (?, 0)", (len(store_module.MIGRATIONS) + 1,))
    with pytest.raises(TaskError, match="Unsupported"):
        store.initialize()
    with pytest.raises(TaskError, match="migration"):
        store.settings()
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == len(store_module.MIGRATIONS) + 1


def test_symlink_and_nonregular_store_rejected(tmp_path):
    target = tmp_path / "target"
    target.write_text("unchanged")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises((TaskError, OSError)):
        TaskStore(link).initialize()
    assert target.read_text() == "unchanged"
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(TaskError, match="regular"):
        TaskStore(fifo).initialize()


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "voice"},
        {"source": "api"},
        {"source": "workflow"},
        {"source": "scheduled"},
        {"conversation_id": ""},
        {"generation": True},
        {"mode": "unknown"},
        {"authorization_id": ""},
        {"arguments": []},
        {"timeout_seconds": float("nan")},
        {"arguments": {"value": float("inf")}},
        {"arguments": {"text": "x" * 65536}},
    ],
)
def test_invalid_admission_is_rejected(store, changes):
    with pytest.raises(TaskError):
        store.admit(admission(**changes))


def test_invocation_deduplication_and_disable_draining(store):
    source = admission()
    job = store.admit(source)
    assert store.admit(source)["id"] == job["id"]
    for change in ({"arguments": {"different": True}}, {"tool": "other"}, {"mode": "cloud"}):
        with pytest.raises(Conflict):
            store.admit(replace(source, **change))
    store.configure(background_enabled=False)
    assert store.admit(source)["id"] == job["id"]
    with pytest.raises(AdmissionDenied, match="disabled"):
        store.admit(admission(request_id="new-request"))
    store.release(job["id"], receipt(job))
    claim = store.claim("worker", {"local_fixture"})
    assert claim.job_id == job["id"]
    store.finish(claim, {"summary": "drained"})
    assert store.get(job["id"])["state"] == "succeeded"
    assert store.settings()["webhooks_enabled"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"lease_released": False},
        {"run_status": "running"},
        {"receipt_message_id": ""},
        {"request_id": "successor"},
        {"conversation_id": "another"},
        {"generation": 2},
    ],
)
def test_receipt_settlement_gate(store, change):
    job = store.admit(admission())
    assert store.claim("worker", {"local_fixture"}) is None
    with pytest.raises(TaskError):
        store.release(job["id"], receipt(job, **change))
    assert store.get(job["id"])["dispatch_state"] == "held"
    assert store.claim("worker", {"local_fixture"}) is None
    store.release(job["id"], receipt(job))
    assert store.release(job["id"], receipt(job))["dispatch_state"] == "ready"
    with pytest.raises(Conflict):
        store.release(job["id"], receipt(job, receipt_message_id="different"))
    assert store.claim("worker", {"other_adapter"}) is None
    assert store.claim("worker", {"local_fixture"}) is not None


def test_pending_result_counts_toward_conversation_capacity(store):
    store.configure(max_outstanding=1)
    ready(store)
    store.finish(store.claim("worker", {"local_fixture"}), {"summary": "done"})
    with pytest.raises(AdmissionDenied, match="capacity"):
        store.admit(admission(request_id="new-request"))
    assert store.admit(admission(conversation_id="other"))["state"] == "queued"


def test_global_queue_limit_includes_held_admissions(store):
    store.configure(max_queued=1)
    store.admit(admission())
    with pytest.raises(AdmissionDenied, match="capacity"):
        store.admit(admission(conversation_id="other"))


def test_competing_connections_claim_once_and_respect_global_limit(store):
    store.configure(max_running=1)
    jobs = {ready(store, request_id=f"request-{i}")["id"] for i in range(2)}

    def claim(index):
        return TaskStore(store.path).claim(f"worker-{index}", {"local_fixture"})

    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = [result for result in pool.map(claim, range(8)) if result is not None]
    assert len(claimed) == 1
    assert claimed[0].job_id in jobs
    store.finish(claimed[0], {"summary": "done"})
    next_claim = claim(9)
    assert next_claim.job_id != claimed[0].job_id
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 2


def test_expired_attempt_fences_writes_and_is_never_replayed(store):
    now = [1000.0]
    store.clock = lambda: now[0]
    store.configure(max_running=1)
    job = ready(store)
    claim = store.claim("original", {"local_fixture"}, lease_seconds=10)
    store.running(claim)
    now[0] += 11
    for operation in (
        lambda: store.renew(claim),
        lambda: store.progress(claim, {"value": 100}),
        lambda: store.finish(claim, {"summary": "late"}),
    ):
        with pytest.raises(LostLease):
            operation()
    assert store.reconcile() == 1
    assert store.reconcile() == 0
    recovered = store.get(job["id"])
    assert recovered["state"] == "needs_attention"
    assert recovered["fence"] > claim.fence
    ready(store, request_id="new-request")
    assert store.claim("replacement", {"local_fixture"}) is None
    assert store.pending_deliveries() == []


@pytest.mark.parametrize("change", [{"owner": "wrong"}, {"attempt_id": "wrong"}, {"fence": 99}])
def test_wrong_execution_identity_cannot_write(store, change):
    ready(store)
    claim = store.claim("worker", {"local_fixture"})
    with pytest.raises(LostLease):
        store.finish(replace(claim, **change), {"summary": "forged"})
    assert store.get(claim.job_id)["state"] == "starting"


def test_unstarted_deadline_expires_without_dispatch(store):
    now = [1000.0]
    store.clock = lambda: now[0]
    job = ready(store, timeout_seconds=1)
    now[0] += 2
    assert store.claim("worker", {"local_fixture"}) is None
    assert store.get(job["id"])["state"] == "expired"
    assert store.get(job["id"])["attempt_id"] is None


def test_terminal_result_and_delivery_commit_together_and_dedupe(store):
    ready(store)
    claim = store.claim("worker", {"local_fixture"})
    store.running(claim)
    with sqlite3.connect(store.path) as conn:
        conn.execute("""CREATE TRIGGER fail_outbox BEFORE INSERT ON outbox
            BEGIN SELECT RAISE(ABORT, 'fixture storage failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="fixture storage failure"):
        store.finish(claim, {"summary": "done"})
    assert store.get(claim.job_id)["state"] == "running"
    assert store.get(claim.job_id)["result"] is None
    assert store.pending_deliveries() == []
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT finished_at FROM attempts").fetchone()[0] is None
        conn.execute("DROP TRIGGER fail_outbox")
    delivery = store.finish(claim, {"summary": "done"})
    assert store.finish(claim, {"summary": "done"}) == delivery
    assert len(store.pending_deliveries()) == 1
    with pytest.raises(Conflict):
        store.finish(claim, {"summary": "different"})
    with pytest.raises(LostLease):
        store.progress(claim, {"value": 20})


def test_worker_health_is_lease_based_and_drain_excludes_admission_readiness(store):
    now = [1000.0]
    store.clock = lambda: now[0]
    store.touch_worker("first", {"local_fixture"}, lease_seconds=10)
    assert store.healthy_workers()[0]["adapters"] == ["local_fixture"]
    now[0] += 11
    assert store.healthy_workers() == []
    store.touch_worker("second", {"local_fixture"}, draining=True)
    assert store.healthy_workers() == []


@pytest.fixture
def config_root(tmp_path, monkeypatch):
    root = tmp_path / "configuration"
    (root / "config").mkdir(parents=True)
    (root / "config" / "cloud.env").write_text("FIXTURE_TOKEN=cloud\nCLOUD_FIXTURE_ONLY=cloud\n")
    (root / "config" / "local.env").write_text("FIXTURE_TOKEN=local\nLOCAL_FIXTURE_ONLY=local\n")
    monkeypatch.setattr(config_loader, "get_project_root", lambda: root)
    return root


def test_worker_uses_job_mode_and_explicit_child_environment(store, config_root, monkeypatch):
    monkeypatch.setenv("FIXTURE_TOKEN", "inherited-cloud")
    monkeypatch.setenv("CLOUD_FIXTURE_ONLY", "inherited-cloud")
    monkeypatch.setenv("JARVIS_OVERRIDE_FIXTURE_TOKEN", "request-override")
    monkeypatch.setenv("JARVIS_WEB_CONVERSATION_ID", "unrelated-conversation")
    original_environment = dict(os.environ)
    seen = []

    def adapter(context):
        seen.append(config_loader.get_active_config_mode())
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os,json; print(json.dumps({k:v for k,v in os.environ.items() "
                "if 'FIXTURE' in k or k == 'JARVIS_WEB_CONVERSATION_ID'}))",
            ],
            env=context.environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return {"mode": seen[-1], "environment": json.loads(child.stdout)}

    worker = TaskWorker(store, {"local_fixture": adapter})
    with config_loader.config_scope("cloud", {"FIXTURE_TOKEN": "outer-scope"}):
        for mode in ("local", "cloud"):
            job = ready(store, request_id=f"request-{mode}", mode=mode)
            assert worker.run_once()
            result = store.get(job["id"])["result"]
            assert result == {
                "mode": mode,
                "environment": {
                    "FIXTURE_TOKEN": mode,
                    f"{mode.upper()}_FIXTURE_ONLY": mode,
                },
            }
            assert config_loader.get_active_config_mode() == "cloud"
            assert config_loader.get_scoped_config()["FIXTURE_TOKEN"] == "outer-scope"
    assert seen == ["local", "cloud"]
    assert dict(os.environ) == original_environment


def test_worker_stamps_only_deployment_overrides_not_mode_secrets(store, config_root, monkeypatch):
    (config_root / "config" / "cloud.env").write_text(
        "FIXTURE_TOKEN=cloud\nCLOUD_FIXTURE_ONLY=cloud\nGEMINI_API_KEY=mode-secret\n"
    )
    monkeypatch.setenv("JARVIS_OVERRIDE_FIXTURE_TOKEN", "hijack")
    monkeypatch.setenv("JARVIS_OVERRIDE_GEMINI_API_KEY", "stolen")
    monkeypatch.setenv("GEMINI_API_KEY", "parent-secret")
    seen = []

    def adapter(context):
        env = context.environment
        seen.append({
            "token": env.get("FIXTURE_TOKEN"),
            "override_token": env.get("JARVIS_OVERRIDE_FIXTURE_TOKEN"),
            "secret": env.get("GEMINI_API_KEY"),
            "override_secret": env.get("JARVIS_OVERRIDE_GEMINI_API_KEY"),
            "stash": env.get("STASH_DIR"),
            "override_stash": env.get("JARVIS_OVERRIDE_STASH_DIR"),
            "config_values": dict(context.config_values),
        })
        return {"ok": True}

    worker = TaskWorker(
        store, {"local_fixture": adapter},
        deployment_overrides={"STASH_DIR": "/tmp/bg-stash"},
    )
    job = ready(store, mode="cloud")
    assert worker.run_once()
    assert store.get(job["id"])["state"] == "succeeded"
    assert seen == [{
        "token": "cloud",
        "override_token": None,
        "secret": "mode-secret",
        "override_secret": None,
        "stash": "/tmp/bg-stash",
        "override_stash": "/tmp/bg-stash",
        "config_values": {"STASH_DIR": "/tmp/bg-stash"},
    }]


@pytest.mark.parametrize("kind", ["failure", "exception", "bad_result", "stop", "expired_failure"])
def test_worker_settles_only_known_outcomes(store, config_root, caplog, kind):
    now = [1000.0]
    store.clock = lambda: now[0]
    job = ready(store)
    stop = threading.Event()

    def adapter(context):
        if kind == "failure":
            raise KnownFailure({"summary": "fixture rejected the input"})
        if kind == "expired_failure":
            now[0] += 40
            raise KnownFailure({"summary": "too late"})
        if kind == "exception":
            raise RuntimeError("private-token-must-not-be-persisted")
        if kind == "bad_result":
            return ["not an outcome object"]
        stop.set()
        context.checkpoint()

    worker = TaskWorker(store, {"local_fixture": adapter})
    assert worker.run_once(stop)
    settled = store.get(job["id"])
    assert settled["state"] == ("failed" if kind == "failure" else "needs_attention")
    assert len(store.pending_deliveries()) == (1 if kind == "failure" else 0)
    assert "private-token-must-not-be-persisted" not in json.dumps(settled) + caplog.text
    assert worker.run_once() is False


def test_heartbeat_renews_a_job_longer_than_initial_lease(store, config_root):
    job = ready(store)

    def adapter(context):
        initial_expiry = context.claim.job["lease_expires_at"]
        while time.time() <= initial_expiry + 0.15:
            context.checkpoint()
            time.sleep(0.02)
        return {"summary": "finished after initial lease"}

    worker = TaskWorker(
        store, {"local_fixture": adapter}, lease_seconds=0.5, heartbeat_seconds=0.05
    )
    assert worker.run_once()
    assert store.get(job["id"])["state"] == "succeeded"
    assert store.get(job["id"])["heartbeat_at"] > job["created_at"]


def test_worker_does_not_claim_after_stop(store, config_root):
    job = ready(store)
    stop = threading.Event()
    stop.set()
    worker = TaskWorker(store, {"local_fixture": lambda context: pytest.fail("must not execute")})
    assert worker.run_once(stop) is False
    assert store.get(job["id"])["attempt_id"] is None


def test_shutdown_racing_known_result_preserves_completion(store, config_root):
    job = ready(store)
    stop = threading.Event()

    def adapter(context):
        stop.set()
        return {"summary": "operation already completed"}

    worker = TaskWorker(store, {"local_fixture": adapter})
    assert worker.run_once(stop)
    assert store.get(job["id"])["state"] == "succeeded"
    assert len(store.pending_deliveries()) == 1
    assert not worker.run_once(stop)


def wait_until(predicate, *, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.02)
    pytest.fail("Timed out waiting for isolated worker fixture")


@pytest.fixture
def worker_process(store, config_root, tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    processes = []

    def start():
        # The subprocess parses only temporary config files and writes only here.
        process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).parent / "fixtures" / "background_task_worker.py"),
                "--db",
                str(store.path),
                "--root",
                str(root),
                "--config-root",
                str(config_root),
                "--lease",
                "0.8",
                "--heartbeat",
                "0.1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        processes.append(process)
        return process

    yield start, root
    for process in processes:
        if process.poll() is None:
            process.terminate()
        try:
            _, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            _, stderr = process.communicate(timeout=5)
        assert process.returncode in (0, -9), stderr


def test_real_worker_process_hold_release_result_and_restart(store, worker_process):
    start, root = worker_process
    job = store.admit(admission())
    process = start()
    first_seen = wait_until(store.healthy_workers)[0]["heartbeat_at"]
    wait_until(lambda: store.healthy_workers()[0]["heartbeat_at"] > first_seen + 0.15)
    assert list(root.iterdir()) == []
    assert store.get(job["id"])["attempt_id"] is None
    store.release(job["id"], receipt(job))
    wait_until(lambda: (root / f"{job['id']}.started").exists())
    wait_until(lambda: store.get(job["id"])["progress"])
    # The Web receipt/second chat turn is intentionally NOT simulated here.
    # This gate proves only durable worker execution; real Web follows in phase 1b.
    assert store.get(job["id"])["state"] == "running"
    store.configure(background_enabled=False)
    (root / "finish").touch()
    wait_until(lambda: store.get(job["id"])["state"] == "succeeded")
    assert (root / f"{job['id']}.txt").read_text() == "fixture completed\n"
    delivery = store.pending_deliveries()
    assert len(delivery) == 1
    process.terminate()
    process.wait(timeout=5)
    assert store.healthy_workers() == []
    start()
    wait_until(store.healthy_workers)
    assert store.pending_deliveries() == delivery
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1


def test_killed_worker_is_fenced_by_restart_without_reexecution(store, worker_process):
    start, root = worker_process
    job = ready(store)
    process = start()
    wait_until(lambda: (root / f"{job['id']}.started").exists())
    process.kill()
    process.wait(timeout=5)
    # Restart immediately, while the killed owner's lease may still be valid.
    # Startup/periodic recovery must fence expiry without another execution.
    start()
    wait_until(lambda: store.get(job["id"])["state"] == "needs_attention")
    (root / "finish").touch()
    assert not (root / f"{job['id']}.txt").exists()
    assert store.pending_deliveries() == []
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1


@pytest.mark.parametrize('outcome', ['success', 'failure', 'exception', 'storage_failure'])
def test_worker_activity_logs_only_committed_outcomes_without_payloads(store, config_root, caplog, monkeypatch, outcome):
    caplog.set_level('INFO', logger='lib.background_tasks.worker')
    secret = 'private-worker-payload-do-not-log'
    job = ready(store, arguments={'private_input': secret})

    def adapter(context):
        if outcome == 'failure':
            raise KnownFailure({'ok': False, 'error': secret})
        if outcome == 'exception':
            raise RuntimeError(secret)
        return {'ok': True, 'private_result': secret}

    if outcome == 'storage_failure':
        def fail_finish(*args):
            raise OSError(secret)
        monkeypatch.setattr(store, 'finish', fail_finish)
    worker = TaskWorker(store, {'local_fixture': adapter})
    assert worker.run_once()
    assert f"Task started job={job['id']} tool=fixture mode=local" in caplog.text
    assert secret not in caplog.text
    if outcome == 'success':
        assert f"Task succeeded job={job['id']}" in caplog.text
        assert store.get(job['id'])['state'] == 'succeeded'
    elif outcome == 'failure':
        assert f"Task failed job={job['id']}" in caplog.text
        assert store.get(job['id'])['state'] == 'failed'
    else:
        assert f"Task needs attention job={job['id']}" in caplog.text
        assert 'Task succeeded' not in caplog.text and 'Task failed' not in caplog.text
        assert store.get(job['id'])['state'] == 'needs_attention'


def test_idle_worker_reports_preferences_once_and_again_only_when_changed(store, caplog):
    caplog.set_level('INFO', logger='lib.background_tasks.worker')
    store.configure(background_enabled=False)

    class IdleCycles(threading.Event):
        cycles = 0

        def wait(self, timeout=None):
            self.cycles += 1
            if self.cycles == 3:
                store.configure(background_enabled=True, background_tools=['fixture'])
            if self.cycles == 6:
                self.set()
            return self.is_set()

    stop = IdleCycles()
    TaskWorker(store, {'local_fixture': lambda context: pytest.fail('No job was admitted')}).run_forever(stop)
    assert caplog.text.count('Task worker ready') == 1
    assert caplog.text.count('New background tasks: disabled; saved tools=fixture') == 1
    assert caplog.text.count('New background tasks: enabled; saved tools=fixture') == 1
    assert caplog.text.count('Task worker stopped') == 1
    assert len(caplog.records) == 6  # No polling/heartbeat messages during idle cycles.
