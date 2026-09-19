"""A personal manifest needs a separate operator-owned callback binding."""

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'lib'), str(ROOT / 'orchestrator')]

from lib.background_tasks import Admission, ReceiptEvidence  # noqa: E402
from lib.background_tasks.models import AdmissionDenied  # noqa: E402
from lib.background_tasks.production import bindings, worker_adapters  # noqa: E402
from lib.background_tasks.worker import AwaitingCallback, KnownFailure  # noqa: E402
from lib.webhook_integrations import private_bindings as private  # noqa: E402
from lib.webhook_integrations import runner as callback_runner  # noqa: E402
from lib.webhook_integrations.service import IntegrationService  # noqa: E402
from test_task_callbacks import configured  # noqa: E402


@pytest.fixture
def private_tool(tmp_path, monkeypatch):
    skills = tmp_path / 'skills/personal'
    skills.mkdir(parents=True)
    manifest_path = skills / 'callback_probe.tool.json'
    script_path = skills / 'callback_probe.py'
    manifest_path.write_text(json.dumps({
        'enabled': True, 'name': 'callback_probe', 'description': 'Private callback probe',
        'script': 'callback_probe.py',
        'parameters': {'type': 'object', 'additionalProperties': False,
                       'properties': {'message': {'type': 'string'}}, 'required': ['message']},
        'execution': {'background': {'supported': True, 'required': True,
                                     'adapter': 'http_callback_v1', 'timeout_seconds': 7200}},
    }))
    script_path.write_text('raise SystemExit("foreground execution refused")\n')
    config = tmp_path / 'data/secrets/private-callback-bindings.json'
    config.parent.mkdir(parents=True)
    monkeypatch.setattr(private, 'ROOT', tmp_path)
    monkeypatch.setattr(private, 'CONFIG_PATH', config)
    monkeypatch.setattr('tool_profiles.load_active_profile_overrides', lambda: {})
    row = {
        'tool': 'callback_probe', 'source_id': 'a' * 32,
        'submit_url': 'https://bridge.example.ts.net/submit',
        'callback_base': 'https://jarvis.example.ts.net',
        'health_url': 'https://bridge.example.ts.net/health',
        'submit_token': 'private-submit-token-' + 's' * 32,
        'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        'script_sha256': hashlib.sha256(script_path.read_bytes()).hexdigest(),
    }

    def write(source_id=None):
        if source_id:
            row['source_id'] = source_id
        config.write_text(json.dumps({'version': 1, 'bindings': [row]}))
        config.chmod(0o600)

    return SimpleNamespace(root=tmp_path, config=config, manifest=manifest_path,
                           script=script_path, row=row, write=write)


def test_personal_manifest_alone_cannot_register_callback(private_tool):
    assert 'callback_probe' not in bindings()
    private_tool.write()
    assert bindings()['callback_probe'] == 'http_callback_v1'
    manifest, evidence = private.policy('callback_probe')
    assert evidence['timeout_seconds'] == 7200
    assert evidence['manifest_sha256'] == private_tool.row['manifest_sha256']
    assert private_tool.row['submit_token'] not in json.dumps(evidence)
    assert manifest['name'] == 'callback_probe'
    private_tool.manifest.write_text(private_tool.manifest.read_text() + '\n')
    with pytest.raises(AdmissionDenied, match='reviewed policy'):
        private.policy('callback_probe')


def test_private_settings_status_does_not_claim_changed_files_are_ready(private_tool, tmp_path):
    private_tool.write()
    service, _, _, _ = configured(tmp_path)
    assert private.status(service.store, 'callback_probe', mode='cloud')['policy_ready'] is True
    private_tool.script.write_text('raise SystemExit("changed")\n')
    status = private.status(service.store, 'callback_probe', mode='cloud')
    assert status['policy_ready'] is False
    assert status['service_ready'] is False


def test_private_binding_rejects_open_file_symlink_and_unreviewed_host(private_tool, tmp_path):
    private_tool.write()
    private_tool.config.chmod(0o644)
    assert private.bindings() == {}
    private_tool.config.chmod(0o600)
    link = tmp_path / 'linked.json'
    link.symlink_to(private_tool.config)
    private.CONFIG_PATH = link
    assert private.bindings() == {}
    private.CONFIG_PATH = private_tool.config
    private_tool.row['health_url'] = 'https://other.example.ts.net/health'
    private_tool.write()
    assert private.bindings() == {}


def test_blocking_companion_tool_hides_private_long_task(private_tool):
    from config_loader import config_scope

    shared = private_tool.root / 'skills/openclaw.tool.json'
    shared.write_text(json.dumps({'name': 'openclaw', 'enabled': True, 'script': 'openclaw.py'}))
    private_tool.row['requires_tool'] = 'openclaw'
    private_tool.write()
    with config_scope('cloud', {'BLOCKED_TOOLS': ''}):
        assert private.policy('callback_probe')[1]['timeout_seconds'] == 7200
    with config_scope('cloud', {'BLOCKED_TOOLS': 'openclaw'}):
        with pytest.raises(AdmissionDenied, match='disabled'):
            private.policy('callback_probe')


def test_private_callback_submits_once_to_exact_reviewed_url(private_tool, tmp_path, monkeypatch):
    service, source, _, _ = configured(tmp_path)
    row = private_tool.row
    source = service.update_source(source['id'], source['revision'],
        callback_base=row['callback_base'], submit_url=row['submit_url'],
        _reviewed_submit_url=row['submit_url'])
    with service.store._connection(write=True) as conn:
        conn.execute('UPDATE task_integrations SET validated_revision=revision WHERE id=?', (source['id'],))
    private_tool.write(source['id'])
    monkeypatch.setattr(private, 'service_ready', lambda *args, **kwargs: True)
    service.store.configure(max_running=3)
    sent = []
    monkeypatch.setattr(callback_runner, 'post_json', lambda url, body, **kwargs:
                        (sent.append((url, body, kwargs)) or {'remote_id': 'remote-1'}))

    def claim(identity):
        authorization = {
            'source': 'web', 'conversation_id': 'conversation', 'generation': 0,
            'request_id': identity, 'mode': 'cloud', 'selected': ['callback_probe'],
            'tool_policy': 'auto', 'callback_sources': {'callback_probe': source['id']},
            'tool_policies': {'callback_probe': private.policy('callback_probe')[1]},
        }
        job = service.store.admit(Admission('conversation', 0, identity, identity,
            'callback_probe', 'http_callback_v1', 'cloud', {'message': 'Research briefly.'},
            'auth-' + identity, 'web', timeout_seconds=7200), authorization=authorization)
        service.store.release(job['id'], ReceiptEvidence('conversation', 0, identity,
            'receipt-' + identity, 'completed', True))
        claimed = service.store.claim('test-worker', {'http_callback_v1'})
        service.store.running(claimed)
        return SimpleNamespace(claim=claimed, store=service.store, checkpoint=lambda: None)

    adapter = worker_adapters(service.store)['http_callback_v1']
    assert isinstance(adapter(claim('first')), AwaitingCallback)
    assert len(sent) == 1 and sent[0][0] == row['submit_url']
    assert sent[0][1]['deadline'] == service.store.get(sent[0][1]['job_id'])['deadline']
    assert sent[0][2]['headers']['Authorization'] == 'Bearer ' + row['submit_token']
    assert row['submit_token'] not in json.dumps(sent[0][1])

    with service.store._connection(write=True) as conn:
        conn.execute('UPDATE task_integrations SET submit_url=? WHERE id=?',
                     ('https://other.example.ts.net/submit', source['id']))
    with pytest.raises(KnownFailure):
        adapter(claim('second'))
    assert len(sent) == 1
