"""Deterministic authoring, auth, admission, and persistence regressions."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'jarvis_workflow_builder_test_server'
SPEC = importlib.util.spec_from_file_location(
    PACKAGE, ROOT / 'jarvis-workflows' / 'server' / '__init__.py',
    submodule_search_locations=[str(ROOT / 'jarvis-workflows' / 'server')])
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[PACKAGE] = MODULE
SPEC.loader.exec_module(MODULE)
app_module = __import__(f'{PACKAGE}.app', fromlist=['create_app'])
recipes_module = __import__(f'{PACKAGE}.recipes', fromlist=['RecipeService'])
runs_module = __import__(f'{PACKAGE}.runs', fromlist=['RunSupervisor'])
store_module = __import__(f'{PACKAGE}.store', fromlist=['BuilderStore'])
preview_module = __import__(f'{PACKAGE}.previews', fromlist=['bounded_preview'])


def recipe(workflow_id='sample', **extra):
    return {'id': workflow_id, 'name': 'Sample', 'triggers': {'explicit': [f'/{workflow_id}']},
            'variables': {}, 'steps': [{'step': 8, 'tool': 'calculator',
                                       'params': {'expression': '2+2'}, 'output_var': 'answer'}],
            **extra}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / 'cloud.env').write_text('')
    (tmp_path / 'data' / 'workflows' / 'personal').mkdir(parents=True)
    (tmp_path / 'skills').mkdir()
    (tmp_path / 'skills' / 'calculator.tool.json').write_text(json.dumps({
        'name': 'calculator', 'enabled': True, 'parameters': {'type': 'object'},
        'permissions': {'auto_approve': True}}))
    monkeypatch.delenv('WEBUI_PASSWORD', raising=False)
    monkeypatch.setattr(runs_module, 'get_workflow_excluded_tools', lambda mode: set())
    catalog_module = __import__(f'{PACKAGE}.catalog', fromlist=['CatalogService'])
    monkeypatch.setattr(catalog_module, 'get_workflow_excluded_tools', lambda mode: set())
    runner = Mock()
    app = app_module.create_app(repo_root=tmp_path, runner=runner)
    app.config['TESTING'] = True
    return tmp_path, app, app.test_client(), runner


def write_recipe(root, filename='sample.json', workflow=None):
    path = root / 'data' / 'workflows' / filename
    path.write_text(json.dumps(workflow or recipe()))
    return path


def test_inventory_keeps_disabled_invalid_shadowed_and_duplicate_sources(setup):
    root, app, client, _ = setup
    write_recipe(root)
    write_recipe(root, 'personal/odd_filename.json')
    write_recipe(root, 'personal/z_override.json')
    write_recipe(root, 'disabled.json', recipe('disabled', enabled=False))
    (root / 'data' / 'workflows' / 'broken.json').write_text('{bad')
    rows = client.get('/api/workflows').json['workflows']
    assert len(rows) == 5
    personal = [row for row in rows if row['tier'] == 'personal']
    assert all(row['duplicate'] for row in personal)
    assert next(row for row in personal if row['effective'])['filename'] == 'personal/z_override.json'
    assert next(row for row in rows if row['filename'] == 'broken.json')['errors']
    assert not next(row for row in rows if row['id'] == 'disabled')['enabled']
    assert all(not Path(row['filename']).is_absolute() for row in rows)


def test_personal_filename_preserved_and_unknown_fields_round_trip(setup):
    root, app, client, _ = setup
    path = write_recipe(root, 'personal/non_matching.json', recipe(_comment='retained', custom={'x': [1]}))
    source = client.get('/api/workflows').json['workflows'][0]
    draft = client.post('/api/drafts', json={'source_id': source['source_id']}).json['draft']
    assert draft['workflow']['_comment'] == 'retained'
    draft['workflow']['name'] = 'Edited'
    updated = client.patch(f"/api/drafts/{draft['id']}", json={
        'revision': draft['revision'], 'workflow': draft['workflow']}).json['draft']
    response = client.post(f"/api/drafts/{draft['id']}/publish", json={'revision': updated['revision']})
    assert response.status_code == 200, response.json
    saved = json.loads(path.read_text())
    assert saved['name'] == 'Edited'
    assert saved['builder_policy_version'] == 1
    assert saved['custom'] == {'x': [1]}
    assert saved['steps'][0]['step'] == 8
    assert not (path.parent / 'sample.json').exists()


def test_drafts_are_not_runtime_files_and_shared_customization_routes_off(setup):
    root, app, client, _ = setup
    path = write_recipe(root)
    original = path.read_bytes()
    source = client.get('/api/workflows').json['workflows'][0]
    draft = client.post('/api/drafts', json={'source_id': source['source_id']}).json['draft']
    assert draft['workflow']['allow_workflow_tool'] is False
    assert list((path.parent / 'personal').glob('*.json')) == []
    response = client.post(f"/api/drafts/{draft['id']}/publish", json={'revision': 1})
    assert response.status_code == 200, response.json
    assert path.read_bytes() == original
    assert response.json['source']['tier'] == 'personal'
    assert response.json['workflow']['allow_workflow_tool'] is False


def test_first_edit_draft_preserves_supplied_definition_and_provenance(setup):
    root, _, client, _ = setup
    write_recipe(root)
    source = client.get('/api/workflows').json['workflows'][0]
    changed = recipe(name='First edit', allow_workflow_tool=False)
    result = client.post('/api/drafts', json={'source_id': source['source_id'], 'workflow': changed}).json['draft']
    assert result['workflow']['name'] == 'First edit'
    assert result['base_hash'] == source['hash']


def test_raw_editor_cannot_remove_policy_and_import_starts_routing_off(setup):
    root, _, client, _ = setup
    response = client.post('/api/drafts', json={'workflow': recipe(allow_workflow_tool=True)})
    draft = response.json['draft']
    assert draft['workflow']['allow_workflow_tool'] is False
    draft['workflow']['builder_policy_version'] = 999
    draft = client.patch(f"/api/drafts/{draft['id']}", json={'revision': 1, 'workflow': draft['workflow']}).json['draft']
    response = client.post(f"/api/drafts/{draft['id']}/publish", json={'revision': draft['revision']})
    assert response.status_code == 200, response.json
    assert response.json['workflow']['builder_policy_version'] == 1


def test_stale_draft_and_external_source_edits_fail_without_overwrite(setup):
    root, _, client, _ = setup
    path = write_recipe(root, 'personal/original.json')
    source = client.get('/api/workflows').json['workflows'][0]
    draft = client.post('/api/drafts', json={'source_id': source['source_id']}).json['draft']
    saved = client.patch(f"/api/drafts/{draft['id']}", json={'revision': 1, 'workflow': recipe()})
    assert saved.status_code == 200
    assert client.patch(f"/api/drafts/{draft['id']}", json={'revision': 1, 'workflow': recipe()}).status_code == 409
    external = recipe(name='External')
    path.write_text(json.dumps(external))
    result = client.post(f"/api/drafts/{draft['id']}/publish", json={'revision': 2})
    assert result.status_code == 409
    assert json.loads(path.read_text()) == external


def test_duplicate_ids_block_publication_and_removal_restores_shared(setup):
    root, _, client, _ = setup
    write_recipe(root)
    path = write_recipe(root, 'personal/non_matching.json')
    write_recipe(root, 'personal/z.json')
    source = next(row for row in client.get('/api/workflows').json['workflows'] if row['filename'] == 'personal/non_matching.json')
    draft = client.post('/api/drafts', json={'source_id': source['source_id']}).json['draft']
    assert client.post(f"/api/drafts/{draft['id']}/publish", json={'revision': 1}).status_code == 400
    (path.parent / 'z.json').unlink()
    assert client.post(f"/api/drafts/{draft['id']}/publish", json={'revision': 1}).status_code == 200
    source = next(row for row in client.get('/api/workflows').json['workflows'] if row['tier'] == 'personal')
    removed = client.delete(f"/api/workflows/{source['source_id']}/personal", json={'hash': source['hash']})
    assert removed.status_code == 200
    assert removed.json['restored']['tier'] == 'shared'


def test_secret_env_rejected_before_resolution_and_symlinks_refused(setup, monkeypatch):
    root, _, client, _ = setup
    monkeypatch.setenv('OPENAI_API_KEY', 'do-not-expose-this')
    secret = recipe(variables={'leak': {'from': 'env', 'key': 'OPENAI_API_KEY'}})
    result = client.post('/api/validate', json={'workflow': secret})
    assert result.json['errors']
    assert 'do-not-expose-this' not in result.get_data(as_text=True)
    outside = root / 'outside.json'
    outside.write_text(json.dumps(recipe()))
    (root / 'data' / 'workflows' / 'escape.json').symlink_to(outside)
    source = client.get('/api/workflows').json['workflows'][0]
    assert source['errors']
    assert client.get(f"/api/workflows/{source['source_id']}").status_code == 400


def test_traversal_id_and_renaming_existing_id_fail(setup):
    root, _, client, _ = setup
    draft = client.post('/api/drafts', json={'workflow': recipe('../escape')}).json['draft']
    assert client.post(f"/api/drafts/{draft['id']}/publish", json={'revision': 1}).status_code == 400
    assert not (root / 'data' / 'escape.json').exists()


def test_shared_optional_auth_and_network_posture(setup, monkeypatch):
    _, _, client, _ = setup
    assert client.get('/api/bootstrap').status_code == 200
    monkeypatch.setenv('WEBUI_PASSWORD', 'test-password')
    monkeypatch.setenv('WEBUI_SECRET', 'isolated-test-signing-secret')
    assert client.get('/api/bootstrap').status_code == 401
    assert client.get('/api/status').json['service'] == 'jarvis-workflows'
    response = client.get('/api/status', headers={'Origin': 'http://other-host:8890'})
    assert response.headers['Access-Control-Allow-Origin'] == 'http://other-host:8890'
    assert client.post('/api/auth/login', json={'password': 'wrong'}).status_code == 401
    token = client.post('/api/auth/login', json={'password': 'test-password'}).json['token']
    assert client.get('/api/bootstrap', headers={'Authorization': f'Bearer {token}'}).status_code == 200
    assert client.get('/api/bootstrap', query_string={'auth_token': token}).status_code == 200
    client.set_cookie('jarvis_auth', token)
    assert client.get('/api/bootstrap').status_code == 200
    assert client.post('/api/drafts', json={'workflow': recipe()}, headers={'Origin': 'http://other-host:8890'}).status_code == 201


def test_configured_modes_and_offline_catalog_never_construct_registry(setup, monkeypatch):
    root, app, client, _ = setup
    assert client.get('/api/bootstrap').json['modes'] == ['cloud']
    assert client.get('/api/tools?mode=local').status_code == 400
    from tool_schema import ToolRegistry
    monkeypatch.setattr(ToolRegistry, '__init__', Mock(side_effect=AssertionError('Discovery must be explicit')))
    result = client.get('/api/tools?mode=cloud')
    assert result.status_code == 200
    assert result.json['tools'][0]['name'] == 'calculator'


def test_prepare_exact_source_hash_then_transactional_idempotent_slot(setup, monkeypatch):
    root, app, client, _ = setup
    write_recipe(root)
    store = app.extensions['workflow_store']
    supervisor = runs_module.RunSupervisor(root, store, app.extensions['workflow_recipes'], app.extensions['workflow_catalog'])
    source = client.get('/api/workflows').json['workflows'][0]
    prepared = supervisor.prepare({'source_id': source['source_id'], 'hash': source['hash'], 'mode': 'cloud', 'query': 'hello', 'timeout_seconds': 900})
    run, created = store.admit(prepared['confirmation_token'], 'test-idempotency-key')
    assert created and run['status'] == 'starting'
    assert 'query' not in run and 'workflow' not in run
    repeated, created = store.admit(prepared['confirmation_token'], 'test-idempotency-key')
    assert not created and repeated['id'] == run['id']
    prepared2 = supervisor.prepare({'source_id': source['source_id'], 'hash': source['hash'], 'mode': 'cloud'})
    with pytest.raises(store_module.BuilderError, match='already active'):
        store.admit(prepared2['confirmation_token'], 'another-idempotency-key')
    assert store.get_run(run['id'], internal=True)['workflow']['steps'][0]['step'] == 8
    store.set_status(run['id'], 'completed', {'ok': True})
    supervisor.close()


def test_admission_requires_confirmed_effects_and_published_revision(setup):
    root, app, client, _ = setup
    path = write_recipe(root)
    store = app.extensions['workflow_store']
    supervisor = runs_module.RunSupervisor(root, store, app.extensions['workflow_recipes'], app.extensions['workflow_catalog'])
    source = client.get('/api/workflows').json['workflows'][0]
    prepared = supervisor.prepare({'source_id': source['source_id'], 'hash': source['hash'], 'mode': 'cloud'})
    with pytest.raises(store_module.BuilderError, match='Confirm'):
        supervisor.start({'confirmation_token': prepared['confirmation_token'], 'idempotency_key': 'test-run-12345'})
    path.write_text(json.dumps(recipe(name='Externally changed')))
    with pytest.raises(store_module.BuilderError, match='changed'):
        supervisor.start({'confirmed': True, 'confirmation_token': prepared['confirmation_token'], 'idempotency_key': 'test-run-12345'})
    supervisor.close()


def test_approval_requires_exact_call_hash_and_is_single_use(setup):
    _, app, _, _ = setup
    store = app.extensions['workflow_store']
    token = store.prepare({'workflow': recipe(), 'mode': 'cloud'})
    run, _ = store.admit(token, 'approval-test-run')
    approval_id = store.request_approval(run['id'], {'call_hash': 'exact-call-hash', 'tool': 'send_email', 'arguments': {'to': 'example@example.com'}})
    with pytest.raises(store_module.BuilderError):
        store.decide(approval_id, True, 'wrong-hash')
    store.decide(approval_id, False, 'exact-call-hash')
    assert store.approvals(run['id'])[0]['status'] == 'denied'
    with pytest.raises(store_module.BuilderError):
        store.decide(approval_id, True, 'exact-call-hash')
    store.set_status(run['id'], 'rejected')


def test_events_cursors_and_redacted_recovery_previews(setup):
    _, app, _, _ = setup
    store = app.extensions['workflow_store']
    token = store.prepare({'workflow': recipe(), 'mode': 'cloud'})
    run, _ = store.admit(token, 'progress-test-run')
    preview = preview_module.bounded_preview({'type': 'heygen_progress', 'video_id': 'native-video-id', 'request_id': 'req-123', 'api_key': 'secret', 'body': 'x' * 50000, 'variables': {'secret': 'do-not-persist'}})
    store.event(run['id'], preview)
    first = store.events(run['id'])
    assert first[0]['video_id'] == 'native-video-id'
    assert first[0]['request_id'] == 'req-123'
    assert first[0]['api_key'] == '[redacted]'
    assert 'variables' not in first[0]
    assert store.events(run['id'], first[0]['sequence']) == []
    store.set_status(run['id'], 'timed_out')
    assert store.events(run['id'])[0]['video_id'] == 'native-video-id'


def test_versioned_database_rejects_unknown_schema(tmp_path):
    path = tmp_path / 'future.db'
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=99')
    with pytest.raises(store_module.BuilderError, match='Unsupported'):
        store_module.BuilderStore(path)


def test_retention_keeps_active_run_and_removes_old_terminal_history(setup):
    _, app, _, _ = setup
    store = app.extensions['workflow_store']
    run, _ = store.admit(store.prepare({'workflow': recipe()}), 'old-completed')
    store.set_status(run['id'], 'completed')
    with store.connect() as db:
        db.execute('UPDATE runs SET created=? WHERE id=?', (time.time() - 31 * 86400, run['id']))
    active, _ = store.admit(store.prepare({'workflow': recipe()}), 'active-run')
    store.prune()
    assert [row['id'] for row in store.list_runs()] == [active['id']]
    store.set_status(active['id'], 'cancelled')


def test_personal_source_appearing_after_shared_draft_is_a_conflict(setup):
    root, _, client, _ = setup
    write_recipe(root)
    source = client.get('/api/workflows').json['workflows'][0]
    draft = client.post('/api/drafts', json={'source_id': source['source_id']}).json['draft']
    write_recipe(root, 'personal/non_matching.json')
    result = client.post(f"/api/drafts/{draft['id']}/publish", json={'revision': 1})
    assert result.status_code == 409, result.json
    assert not (root / 'data' / 'workflows' / 'personal' / 'sample.json').exists()


def test_disabled_shared_customization_cannot_silently_restore_bundled_recipe(setup):
    root, _, client, _ = setup
    write_recipe(root)
    source = client.get('/api/workflows').json['workflows'][0]
    draft = client.post('/api/drafts', json={'source_id': source['source_id'], 'workflow': recipe(enabled=False)}).json['draft']
    result = client.post(f"/api/drafts/{draft['id']}/publish", json={'revision': 1})
    assert result.status_code == 400
    assert not list((root / 'data' / 'workflows' / 'personal').glob('*.json'))


def test_idempotency_key_is_bound_to_exact_confirmation_snapshot(setup):
    _, app, _, _ = setup
    store = app.extensions['workflow_store']
    token = store.prepare({'workflow': recipe(), 'query': 'first'})
    run, _ = store.admit(token, 'one-exact-request')
    other = store.prepare({'workflow': recipe(), 'query': 'second'})
    with pytest.raises(store_module.BuilderError, match='different confirmed run'):
        store.admit(other, 'one-exact-request')
    assert store.admit(token, 'one-exact-request')[0]['id'] == run['id']
    store.set_status(run['id'], 'completed')


def test_worker_completion_keeps_slot_until_cleanup_and_parent_finalization(setup):
    _, app, _, _ = setup
    store = app.extensions['workflow_store']
    run, _ = store.admit(store.prepare({'workflow': recipe()}), 'cleanup-first-run')
    store.set_status(run['id'], 'running')
    store.finish_worker(run['id'], 'completed', {'ok': True, 'video_id': 'recovery'})
    assert store.active_run()['id'] == run['id']
    assert store.get_run(run['id'])['status'] == 'running'
    with pytest.raises(store_module.BuilderError, match='already active'):
        store.admit(store.prepare({'workflow': recipe()}), 'cleanup-second-run')
    store.finalize_worker(run['id'])
    assert store.active_run() is None
    assert store.get_run(run['id'])['result']['video_id'] == 'recovery'


def test_worker_persists_live_receipt_before_cleanup_without_live_tools(setup, monkeypatch):
    root, app, _, _ = setup
    store = app.extensions['workflow_store']
    run, _ = store.admit(store.prepare({'workflow': recipe(), 'mode': 'cloud', 'query': '', 'stop_after': 1}), 'mock-worker-run')
    worker = __import__(f'{PACKAGE}.worker', fromlist=['execute_run'])
    from orchestrator import executor as executor_module
    from orchestrator import pipeline_executor as pipeline_module

    class FakeExecutor:
        def __init__(self, mode):
            self.registry = Mock()
            self.registry.cleanup.side_effect = lambda: assertion_during_cleanup()

        def set_excluded_tools(self, excluded):
            assert 'workflow' in excluded

        def set_cancel_check(self, callback):
            self.cancel_check = callback

        def set_progress_callback(self, callback):
            self.progress = callback

    def assertion_during_cleanup():
        assert store.get_run(run['id'])['status'] == 'running'
        assert store.events(run['id'])[0]['receipt_stash_ref'] == 'stash://space_x/file_x'

    class FakePipeline:
        def __init__(self, mode, executor):
            self.executor = executor

        def execute(self, workflow, query, **kwargs):
            self.executor.progress('heygen_receipt', video_id='native-id', task_id='task-123',
                                   receipt_stash_ref='stash://space_x/file_x')
            assert kwargs['execution_context']['surface'] == 'builder'
            assert kwargs['stop_after'] == 1
            return {'ok': True, 'partial': True, 'variables': {'not_stored': 'secret'}}

    monkeypatch.setattr(executor_module, 'ToolExecutor', FakeExecutor)
    monkeypatch.setattr(pipeline_module, 'PipelineExecutor', FakePipeline)
    monkeypatch.setattr(worker.signal, 'signal', lambda *_: None)
    worker.execute_run(root, store, run['id'])
    assert store.get_run(run['id'])['status'] == 'running'
    store.finalize_worker(run['id'])
    assert 'variables' not in store.get_run(run['id'])['result']


def test_verified_process_cleanup_stops_detached_tool_children(tmp_path):
    import subprocess

    processes = __import__(f'{PACKAGE}.processes', fromlist=['process_identity'])
    marker = tmp_path / 'child-pid'
    script = (
        'import pathlib,subprocess,sys,time; '
        'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],start_new_session=True); '
        'pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)'
    )
    parent = subprocess.Popen([sys.executable, '-c', script, str(marker)], start_new_session=True)
    try:
        until = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < until:
            time.sleep(.02)
        assert marker.exists()
        child_pid = int(marker.read_text())
        identity = processes.process_identity(parent.pid)
        assert identity
        child_identity = processes.process_identity(child_pid)
        known = processes.descendants(identity)
        assert child_pid in known
        assert processes.stop_verified(identity, known)
        parent.wait(timeout=2)
        assert child_identity and not processes.same_process(child_identity)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=2)


def test_inherited_worker_lease_blocks_restart_until_worker_stops(setup):
    import subprocess

    root, app, _, _ = setup
    store = app.extensions['workflow_store']
    supervisor = runs_module.RunSupervisor(root, store, app.extensions['workflow_recipes'], app.extensions['workflow_catalog'])
    lease = supervisor._worker_lease()
    run, _ = store.admit(store.prepare({'workflow': recipe(), 'timeout_seconds': 900}), 'orphan-worker-run')
    child = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'],
                             pass_fds=(lease.fileno(),), start_new_session=True)
    lease.close()
    identity = runs_module.process_identity(child.pid)
    store.set_worker_identity(run['id'], identity)
    # Simulate losing the server without invoking its normal shutdown path.
    supervisor._closed = True
    supervisor._owner_lock.close()
    replacement = runs_module.RunSupervisor(root, store, app.extensions['workflow_recipes'], app.extensions['workflow_catalog'])
    try:
        assert store.active_run()['id'] == run['id']
        with pytest.raises(store_module.BuilderError, match='still active'):
            replacement._worker_lease()
        runs_module.stop_verified(identity)
        child.wait(timeout=2)
        until = time.monotonic() + 3
        while store.active_run() and time.monotonic() < until:
            time.sleep(.02)
        assert store.active_run() is None
        assert store.get_run(run['id'])['status'] == 'interrupted'
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)
        replacement.close()


def test_shutdown_stops_catalog_discovery_without_waiting_for_lifecycle_lock(setup, monkeypatch):
    import subprocess
    import threading

    root, app, _, _ = setup
    store = app.extensions['workflow_store']
    supervisor = runs_module.RunSupervisor(root, store, app.extensions['workflow_recipes'], app.extensions['workflow_catalog'])
    real_popen = subprocess.Popen
    children = []
    failures = []

    def harmless_discovery(*args, **kwargs):
        child = real_popen([sys.executable, '-c', 'import time;time.sleep(60)'],
                           pass_fds=kwargs['pass_fds'], start_new_session=True)
        children.append(child)
        return child

    def refresh():
        try:
            supervisor.refresh_catalog('cloud')
        except store_module.BuilderError as exc:
            failures.append(exc)

    monkeypatch.setattr(runs_module.subprocess, 'Popen', harmless_discovery)
    thread = threading.Thread(target=refresh)
    thread.start()
    until = time.monotonic() + 3
    while supervisor._discovery is None and time.monotonic() < until:
        time.sleep(.02)
    assert children
    started = time.monotonic()
    supervisor.close()
    thread.join(timeout=3)
    assert time.monotonic() - started < 3
    assert not thread.is_alive()
    assert children[0].poll() is not None
    assert failures


def test_restart_cleans_recorded_detached_descendant_after_worker_died(setup, tmp_path):
    import os
    import signal
    import subprocess

    root, app, _, _ = setup
    store = app.extensions['workflow_store']
    run, _ = store.admit(store.prepare({'workflow': recipe()}), 'dead-worker-live-child')
    marker = tmp_path / 'detached-pid'
    script = (
        'import pathlib,subprocess,sys,time; '
        'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],start_new_session=True); '
        'pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)'
    )
    child = subprocess.Popen([sys.executable, '-c', script, str(marker)], start_new_session=True)
    replacement = None
    try:
        until = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < until:
            time.sleep(.02)
        assert marker.exists()
        identity = runs_module.process_identity(child.pid)
        assert identity
        known = runs_module.descendants(identity)
        descendant = known[int(marker.read_text())]
        store.set_worker_identity(run['id'], identity)
        store.record_processes(run['id'], known)
        os.kill(child.pid, signal.SIGKILL)
        child.wait(timeout=2)
        replacement = runs_module.RunSupervisor(root, store, app.extensions['workflow_recipes'], app.extensions['workflow_catalog'])
        assert not runs_module.same_process(descendant)
        assert store.active_run() is None
    finally:
        if child.poll() is None:
            runs_module.RunSupervisor._stop(child)
        if replacement:
            replacement.close()


def test_approval_preview_retains_ordinary_long_email_and_lists():
    body = 'This is the complete email body.\n' + 'Ordinary content ' * 500
    arguments = {'to': 'reader@example.com', 'subject': 'Detailed report', 'body': body,
                 'attachment_ids': list(range(35))}
    preview, metadata = preview_module.approval_argument_preview(arguments)
    assert preview == arguments
    assert metadata['kind'] == 'bounded_redacted_preview'
    assert metadata['truncated'] is False
    assert metadata['redacted'] is False
    assert 'No content was truncated' in metadata['note']


def test_every_history_preview_reduction_is_explicit():
    preview = preview_module.bounded_preview({
        'body': 'x' * 3000, 'items': list(range(25)), 'variables': {'not_stored': 'value'},
        'deep': {'one': {'two': {'three': {'four': {'five': {'six': {'seven': 'deep'}}}}}}},
    })
    assert 'preview truncated 1000 characters' in preview['body']
    assert preview['items'][-1] == '[preview omitted 5 more items]'
    assert 'variables' not in preview
    assert preview['_preview_omitted_fields'] == 1
    metadata = preview['_preview']
    assert metadata['truncated'] is True
    assert metadata['changes']['shortened_strings'] == 1
    assert metadata['changes']['omitted_items'] == 5
    assert metadata['changes']['omitted_fields'] == 1
    assert metadata['changes']['depth_limits'] == 1


def test_large_approval_is_byte_bounded_with_explicit_truncation_and_redaction():
    arguments = {'password': 'must-be-redacted', 'body': '日' * 20000,
                 'video_id': 'native-video-id', 'receipt_stash_ref': 'stash://space/file'}
    preview, metadata = preview_module.approval_argument_preview(arguments)
    assert metadata['truncated'] is True
    assert metadata['redacted'] is True
    assert 'truncated or omitted' in metadata['note']
    assert len(json.dumps(preview, ensure_ascii=False).encode()) <= 20000
    assert preview['video_id'] == 'native-video-id'
    assert preview['receipt_stash_ref'] == 'stash://space/file'
    assert 'must-be-redacted' not in json.dumps(preview)
    assert 'preview truncated' in json.dumps(preview)


def test_history_collection_and_small_total_limits_are_marked():
    preview = preview_module.bounded_preview({f'field_{i}': i for i in range(70)})
    assert preview['_preview_omitted_fields'] == 30
    assert preview['_preview']['truncated'] is True
    tiny = preview_module.bounded_preview({'video_id': 'native', 'body': 'x' * 10000}, budget=256)
    assert len(json.dumps(tiny, ensure_ascii=False).encode()) <= 256
    assert tiny['_preview']['truncated'] is True


def test_worker_approval_exposes_preview_metadata_and_preserves_long_arguments(setup, monkeypatch):
    root, app, _, _ = setup
    store = app.extensions['workflow_store']
    run, _ = store.admit(store.prepare({'workflow': recipe(), 'mode': 'cloud', 'query': '', 'stop_after': None}), 'mock-approval-preview-run')
    worker = __import__(f'{PACKAGE}.worker', fromlist=['execute_run'])
    from orchestrator import executor as executor_module
    from orchestrator import pipeline_executor as pipeline_module

    body = 'A complete long message. ' * 300
    captured = []
    original_request = store.request_approval

    def request_approval(run_id, payload):
        captured.append(payload)
        approval_id = original_request(run_id, payload)
        store.decide(approval_id, True, payload['call_hash'])
        return approval_id

    class FakeExecutor:
        def __init__(self, mode):
            self.registry = Mock()

        def set_excluded_tools(self, excluded):
            pass

        def set_cancel_check(self, callback):
            pass

        def set_progress_callback(self, callback):
            pass

    class FakePipeline:
        def __init__(self, mode, executor):
            pass

        def execute(self, workflow, query, **kwargs):
            assert kwargs['approval_callback']({
                'tool': 'send_email', 'arguments': {'body': body, 'password': 'do-not-store'},
                'step': 8, 'index': 0, 'item_index': None, 'attempt': 1, 'mode': 'cloud',
                'recipe_hash': 'recipe-hash', 'call_hash': 'exact-call-hash', 'run_id': run['id'],
            }) is True
            return {'ok': True}

    monkeypatch.setattr(store, 'request_approval', request_approval)
    monkeypatch.setattr(executor_module, 'ToolExecutor', FakeExecutor)
    monkeypatch.setattr(pipeline_module, 'PipelineExecutor', FakePipeline)
    monkeypatch.setattr(worker.signal, 'signal', lambda *_: None)
    worker.execute_run(root, store, run['id'])
    payload = captured[0]
    assert payload['arguments']['body'] == body
    assert payload['arguments']['password'] == '[redacted]'
    assert payload['arguments_preview']['kind'] == 'bounded_redacted_preview'
    assert payload['arguments_preview']['truncated'] is False
    assert payload['arguments_preview']['redacted'] is True
    store.finalize_worker(run['id'])


@pytest.mark.parametrize('explicit', ['/invalid_string', 17, None, ['/valid', 3, {}]])
def test_invalid_trigger_inventory_commands_are_always_a_string_list(setup, explicit):
    root, _, client, _ = setup
    write_recipe(root, workflow=recipe(triggers={'explicit': explicit}))
    source = client.get('/api/workflows').json['workflows'][0]
    assert isinstance(source['commands'], list)
    assert all(isinstance(command, str) for command in source['commands'])
    assert source['errors']


def test_worker_cancellation_has_priority_over_approval_denial(setup, monkeypatch):
    root, app, _, _ = setup
    store = app.extensions['workflow_store']
    run, _ = store.admit(store.prepare({'workflow': recipe(), 'mode': 'cloud', 'query': '', 'stop_after': None}), 'approval-cancel-priority')
    worker = __import__(f'{PACKAGE}.worker', fromlist=['execute_run'])
    from orchestrator import executor as executor_module
    from orchestrator import pipeline_executor as pipeline_module

    class FakeExecutor:
        def __init__(self, mode):
            self.registry = Mock()

        def set_excluded_tools(self, excluded):
            pass

        def set_cancel_check(self, callback):
            pass

        def set_progress_callback(self, callback):
            pass

    class FakePipeline:
        def __init__(self, mode, executor):
            pass

        def execute(self, workflow, query, **kwargs):
            store.cancel(run['id'])
            return {'ok': False, 'completion': 'rejected', 'error_code': 'approval_denied'}

    monkeypatch.setattr(executor_module, 'ToolExecutor', FakeExecutor)
    monkeypatch.setattr(pipeline_module, 'PipelineExecutor', FakePipeline)
    monkeypatch.setattr(worker.signal, 'signal', lambda *_: None)
    worker.execute_run(root, store, run['id'])
    assert store.get_run(run['id'], internal=True)['result']['_pending_status'] == 'cancelled'
    store.finalize_worker(run['id'])
    assert store.get_run(run['id'])['status'] == 'cancelled'


@pytest.mark.parametrize(('stop_after', 'partial', 'expected'), [(1, True, 'partial'), (2, False, 'completed'), (None, False, 'completed')])
def test_worker_partial_status_matches_admitted_execution_range(setup, monkeypatch, stop_after, partial, expected):
    root, app, _, _ = setup
    store = app.extensions['workflow_store']
    workflow = recipe(steps=[{'step': 8, 'tool': 'calculator', 'params': {'expression': '2+2'}},
                             {'step': 12, 'tool': 'calculator', 'params': {'expression': '3+3'}}])
    run, _ = store.admit(store.prepare({'workflow': workflow, 'mode': 'cloud', 'query': '',
                                      'stop_after': stop_after, 'partial': partial}), 'range-status-test')
    worker = __import__(f'{PACKAGE}.worker', fromlist=['execute_run'])
    from orchestrator import executor as executor_module
    from orchestrator import pipeline_executor as pipeline_module

    class FakeExecutor:
        def __init__(self, mode):
            self.registry = Mock()

        def set_excluded_tools(self, excluded):
            pass

        def set_cancel_check(self, callback):
            pass

        def set_progress_callback(self, callback):
            pass

    class FakePipeline:
        def __init__(self, mode, executor):
            pass

        def execute(self, definition, query, **kwargs):
            assert kwargs['stop_after'] == stop_after
            return {'ok': True, 'partial': partial}

    monkeypatch.setattr(executor_module, 'ToolExecutor', FakeExecutor)
    monkeypatch.setattr(pipeline_module, 'PipelineExecutor', FakePipeline)
    monkeypatch.setattr(worker.signal, 'signal', lambda *_: None)
    worker.execute_run(root, store, run['id'])
    assert store.active_run()['id'] == run['id']  # cleanup still owns the slot
    store.finalize_worker(run['id'])
    assert store.get_run(run['id'])['status'] == expected
    assert store.active_run() is None
    # Both terminal states are retained and permit a subsequent admission.
    assert store.list_runs()[0]['status'] == expected
    next_run, _ = store.admit(store.prepare({'workflow': recipe()}), 'after-range-status')
    store.set_status(next_run['id'], 'cancelled')


def test_real_early_child_import_failure_is_useful_bounded_and_private(setup, monkeypatch, caplog):
    import logging
    import subprocess

    root, app, client, _ = setup
    write_recipe(root)
    store = app.extensions['workflow_store']
    supervisor = runs_module.RunSupervisor(root, store, app.extensions['workflow_recipes'], app.extensions['workflow_catalog'])
    source = client.get('/api/workflows').json['workflows'][0]
    prepared = supervisor.prepare({'source_id': source['source_id'], 'hash': source['hash'],
                                   'mode': 'cloud', 'query': 'private user query marker'})
    real_popen = subprocess.Popen
    secret = 'private-secret-value-should-never-appear'
    script = (
        'import sys; '
        f'sys.stdout.write({secret!r}+" full tool output\\n"); '
        f'sys.stderr.write({secret!r}+" private user query marker\\n"); '
        'sys.stderr.flush(); import jarvis_builder_missing_dependency_for_test'
    )

    def fail_before_startup(*args, **kwargs):
        return real_popen([sys.executable, '-c', script], **kwargs)

    monkeypatch.setattr(runs_module.subprocess, 'Popen', fail_before_startup)
    caplog.set_level(logging.ERROR, logger=runs_module.__name__)
    try:
        run = supervisor.start({'confirmed': True, 'confirmation_token': prepared['confirmation_token'],
                                'idempotency_key': 'real-early-startup-failure'})
        until = time.monotonic() + 5
        while store.get_run(run['id'])['status'] in store_module.ACTIVE_STATUSES and time.monotonic() < until:
            time.sleep(.02)
        failed = store.get_run(run['id'])
        assert failed['status'] == 'failed'
        assert failed['result']['error_code'] == 'worker_startup_failed'
        assert 'jarvis_builder_missing_dependency_for_test' in failed['result']['error']
        assert 'ModuleNotFoundError' in caplog.text
        retained = json.dumps(failed) + json.dumps(store.events(run['id'])) + caplog.text
        assert secret not in retained
        assert 'private user query marker' not in retained
        assert 'full tool output' not in retained
        assert len(failed['result']['error']) < 1000
    finally:
        supervisor.close()


def test_worker_structured_startup_diagnostic_never_includes_exception_values(setup, monkeypatch):
    root, app, _, _ = setup
    store = app.extensions['workflow_store']
    run, _ = store.admit(store.prepare({'workflow': recipe(), 'mode': 'cloud', 'query': 'private query', 'stop_after': None}), 'startup-message-redaction')
    worker = __import__(f'{PACKAGE}.worker', fromlist=['execute_run'])
    from orchestrator import executor as executor_module

    def fail_registry(mode):
        raise ValueError('private query password=top-secret-literal')

    monkeypatch.setattr(executor_module, 'ToolExecutor', fail_registry)
    monkeypatch.setattr(worker.signal, 'signal', lambda *_: None)
    worker.execute_run(root, store, run['id'])
    store.finalize_worker(run['id'])
    failed = store.get_run(run['id'])
    assert failed['status'] == 'failed'
    assert failed['result']['startup']['phase'] == 'tool_registry'
    assert failed['result']['startup']['exception_type'] == 'ValueError'
    retained = json.dumps(failed) + json.dumps(store.events(run['id']))
    assert 'private query' not in retained
    assert 'top-secret-literal' not in retained
    assert 'test_workflow_builder_server.py' in failed['result']['error']


def test_late_worker_result_cannot_replace_terminal_parent_result(setup):
    _, app, _, _ = setup
    store = app.extensions['workflow_store']
    run, _ = store.admit(store.prepare({'workflow': recipe()}), 'late-worker-result')
    store.set_status(run['id'], 'timed_out', {'error': 'parent deadline'})
    store.finish_worker(run['id'], 'completed', {'ok': True})
    assert store.get_run(run['id'])['status'] == 'timed_out'
    assert store.get_run(run['id'])['result'] == {'error': 'parent deadline'}


def test_partial_runs_use_the_existing_terminal_retention_rules(setup):
    _, app, _, _ = setup
    store = app.extensions['workflow_store']
    run, _ = store.admit(store.prepare({'workflow': recipe(), 'partial': True}), 'old-partial-run')
    store.finish_worker(run['id'], 'partial', {'ok': True, 'partial': True})
    store.finalize_worker(run['id'])
    assert store.get_run(run['id'])['status'] == 'partial'
    with store.connect() as db:
        db.execute('UPDATE runs SET created=? WHERE id=?', (time.time() - 31 * 86400, run['id']))
    store.prune()
    assert store.list_runs() == []


def test_startup_projection_discards_untrusted_messages_and_malformed_fields():
    worker = __import__(f'{PACKAGE}.worker', fromlist=['normalize_startup_diagnostic'])
    diagnostic = worker.normalize_startup_diagnostic({
        'phase': ['invalid'], 'exception_type': {'invalid': True},
        'message': 'full query and password=secret', 'frames': [{'file': '/secret/path/file.py'}],
    })
    assert diagnostic['phase'] == 'startup'
    assert diagnostic['exception_type'] == 'StartupError'
    assert 'frames' not in diagnostic
    assert 'password' not in json.dumps(diagnostic)
    assert len(json.dumps(diagnostic)) < 300


def test_live_effects_show_revision_grants_and_still_require_initial_confirmation(setup):
    from workflow_policy import workflow_approval_hash

    root, app, client, _ = setup
    workflow = recipe(builder_policy_version=1)
    workflow['builder_unattended_approval'] = {
        'version': 1, 'recipe_hash': workflow_approval_hash(workflow), 'tools': ['calculator']}
    write_recipe(root, workflow=workflow)
    (root / 'skills' / 'calculator.tool.json').write_text(json.dumps({
        'name': 'calculator', 'enabled': True, 'parameters': {'type': 'object'},
        'permissions': {'auto_approve': False, 'filesystem': True}}))
    store = app.extensions['workflow_store']
    supervisor = runs_module.RunSupervisor(root, store, app.extensions['workflow_recipes'], app.extensions['workflow_catalog'])
    try:
        source = client.get('/api/workflows').json['workflows'][0]
        prepared = supervisor.prepare({'source_id': source['source_id'], 'hash': source['hash'], 'mode': 'cloud'})
        effect = prepared['effects'][0]
        assert effect['unattended_authorized'] is True
        assert effect['requires_approval'] is False
        assert effect['permissions']['filesystem'] is True
        with pytest.raises(store_module.BuilderError, match='Confirm'):
            supervisor.start({'confirmation_token': prepared['confirmation_token'], 'idempotency_key': 'trusted-effects-still-confirm'})
    finally:
        supervisor.close()


def test_live_effects_reject_changed_recipe_trust_before_startup(setup):
    from workflow_policy import workflow_approval_hash

    root, app, client, _ = setup
    workflow = recipe(builder_policy_version=1)
    workflow['builder_unattended_approval'] = {
        'version': 1, 'recipe_hash': workflow_approval_hash(workflow), 'tools': ['calculator']}
    workflow['name'] = 'Changed after approval'
    write_recipe(root, workflow=workflow)
    store = app.extensions['workflow_store']
    supervisor = runs_module.RunSupervisor(root, store, app.extensions['workflow_recipes'], app.extensions['workflow_catalog'])
    try:
        source = client.get('/api/workflows').json['workflows'][0]
        with pytest.raises(store_module.BuilderError, match='approval must be renewed'):
            supervisor.prepare({'source_id': source['source_id'], 'hash': source['hash'], 'mode': 'cloud'})
        assert store.active_run() is None
    finally:
        supervisor.close()
