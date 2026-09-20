"""Reviewed browser-use binding and local service provisioning.

The private callback child owns browser behavior; the public skill refuses direct
execution. This module supplies reviewed policy and private service configuration.
"""
import hashlib
import json
import os
import stat
import uuid
from pathlib import Path

from lib.background_tasks.models import AdmissionDenied, TaskError

from .contracts import ADAPTER, endpoint

ROOT = Path(__file__).resolve().parents[2]


def managed_runtime_available():
    """The managed helper currently requires native host Docker and tmux."""
    return os.environ.get('JARVIS_DEPLOYMENT', '').strip().lower() != 'docker'


def config_path(store):
    return store.path.parent / 'secrets/browser-use.json'


def read_config(store):
    path = config_path(store)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise TaskError('Browser service configuration must be an owner-only regular file')
    value = json.loads(path.read_text())
    endpoint(value['submit_url'], local_only=True)
    endpoint(value['callback_url'], local_only=True)
    if (value['credential']['scheme'] != 'bearer'
            or len(value['credential']['secret']) < 32):
        raise TaskError('Invalid browser service credential')
    return value


def callback_sources(store):
    if not managed_runtime_available():
        return {}
    try:
        return {'browser_use': read_config(store)['source_id']}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def service_ready(store, *, timeout=.35):
    """Check the private loopback helper without exposing its bearer credential."""
    if not managed_runtime_available():
        return False
    try:
        import requests

        config = read_config(store)
        with requests.Session() as session:
            session.trust_env = False
            with session.get(config['submit_url'].removesuffix('/submit') + '/health',
                             headers={'Authorization': config['credential']['authorization']},
                             timeout=(timeout, timeout), allow_redirects=False, stream=True) as response:
                return response.status_code == 200
    except Exception:
        return False


def managed_status(store):
    """Safe operator status for the Browser Use row in Settings → Tools."""
    from .service import IntegrationService

    result = {'configured': False, 'receiver_enabled': False, 'source_enabled': False,
              'source_validated': False, 'credential_ready': False,
              'service_ready': False, 'source_id': None}
    if not managed_runtime_available():
        return result
    try:
        config = read_config(store)
        result['configured'], result['source_id'] = True, config['source_id']
        status = IntegrationService(store).status()
        result['receiver_enabled'] = bool(status['enabled'])
        source = next((item for item in status['sources'] if item['id'] == config['source_id']), None)
        if source:
            result['source_enabled'] = bool(source['enabled'] and not source['revoked'])
            result['source_validated'] = bool(source['validated'])
            credential_id = config.get('credential', {}).get('id')
            result['credential_ready'] = any(
                item['id'] == credential_id and item['revoked_at'] is None
                and item['expires_at'] > store.clock()
                for item in source['credentials']
            )
        result['service_ready'] = service_ready(store)
    except Exception:
        pass
    return result


def _replace_config(store, value):
    path = config_path(store)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def activate(store, callback_base='http://127.0.0.1:8880',
             submit_url='http://127.0.0.1:8790/submit'):
    """Idempotently provision, enable and verify the managed Browser Use source."""
    from .contracts import EVENTS
    from .service import IntegrationService

    try:
        config = read_config(store)
    except FileNotFoundError:
        provision(store, callback_base, submit_url)
        config = read_config(store)
    service = IntegrationService(store)
    service.initialize_key()
    status = service.status()
    source = next((item for item in status['sources'] if item['id'] == config['source_id']), None)
    if not source:
        raise TaskError('Browser Use source is missing; preserve the private config and restore the task database')
    if source['revoked']:
        raise TaskError('Browser Use source was permanently revoked and requires operator recovery')
    changes = {}
    if source['name'] != 'Browser use':
        changes['name'] = 'Browser use'
    if source['callback_base'] != endpoint(callback_base, local_only=True):
        changes['callback_base'] = callback_base
    if source['submit_url'] != endpoint(submit_url, local_only=True):
        changes['submit_url'] = submit_url
    if set(source['events']) != set(EVENTS):
        changes['events'] = sorted(EVENTS)
    if not source['enabled']:
        changes['enabled'] = True
    if changes:
        source = service.update_source(source['id'], source['revision'], **changes)
    service.configure(True)
    credential_id = config.get('credential', {}).get('id')
    credential = next((item for item in source['credentials'] if item['id'] == credential_id), None)
    if not credential or credential['revoked_at'] is not None or credential['expires_at'] <= store.clock():
        replacement = service.create_credential(source['id'])
        config['credential'] = replacement
    desired_config = {**config, 'source_id': source['id'], 'submit_url': source['submit_url'],
                      'callback_url': source['endpoint']}
    if desired_config != config:
        config = desired_config
    _replace_config(store, config)
    service.test_source(source['id'])
    settings = store.settings()
    store.configure(background_enabled=True,
                    background_tools=sorted(set(settings['background_tools']) | {'browser_use'}))
    return managed_status(store)


def policy():
    from tool_availability import check_tool_availability
    from tool_profiles import effective_enabled, load_active_profile_overrides

    raw = (ROOT / 'skills/browser_use.tool.json').read_bytes()
    manifest = json.loads(raw)
    background = manifest.get('execution', {}).get('background', {})
    if (manifest.get('name') != 'browser_use' or manifest.get('script') != 'browser_use.py'
            or background != {'supported': True, 'required': True, 'adapter': ADAPTER, 'timeout_seconds': 900}
            or manifest.get('permissions') != {'dangerous': False, 'bash': False, 'network': True,
                                                'filesystem': True, 'auto_approve': True}
            or not effective_enabled('browser_use', manifest.get('enabled', True), load_active_profile_overrides())
            or not check_tool_availability(manifest).available):
        raise AdmissionDenied('Browser tool is disabled or no longer matches its reviewed callback policy')
    return manifest, {'manifest_sha256': hashlib.sha256(raw).hexdigest(),
                      'script_sha256': hashlib.sha256((ROOT / 'skills/browser_use.py').read_bytes()).hexdigest(),
                      'job_script_sha256': hashlib.sha256((ROOT / 'lib/webhook_integrations/browser_job.py').read_bytes()).hexdigest(),
                      'adapter': ADAPTER, 'timeout_seconds': 900}


def prepare(context):
    job, store = context.claim.job, context.store
    from lib.background_tasks.browser_followup import prior_browser_job
    prior = prior_browser_job(store, {**job, 'tool': 'browser_use'}, job['admission']['arguments'])
    config = read_config(store)
    manifest, evidence = policy()
    auth = store.authorization(job['admission']['authorization_id'])
    if (not auth or auth.get('tool_policies', {}).get('browser_use') != evidence
            or auth.get('callback_sources', {}).get('browser_use') != config['source_id']
            or auth.get('mode') != job['mode'] or auth.get('tool_policy') == 'none'
            or job['admission']['tool'] != 'browser_use'):
        raise AdmissionDenied('Browser authorization changed after admission')
    web_config = ROOT / 'jarvis-web/config/web_config.json'
    if web_config.exists() and 'browser_use' in json.loads(web_config.read_text()).get('tools', {}).get('blocked', []):
        raise AdmissionDenied('Browser tool was blocked after admission')
    with store._connection() as conn:
        source = conn.execute('SELECT submit_url,callback_base FROM task_integrations WHERE id=?', (config['source_id'],)).fetchone()
        credential = conn.execute('SELECT revoked_at,expires_at FROM task_credentials WHERE id=? AND source_id=?',
                                  (config['credential']['id'], config['source_id'])).fetchone()
    if not credential or credential['revoked_at'] is not None or credential['expires_at'] <= store.clock():
        raise AdmissionDenied('Browser service credential is revoked or expired; update its private configuration')
    if (not source or source['submit_url'] != config['submit_url']
            or source['callback_base'] + f"/api/task-callbacks/{config['source_id']}/events" != config['callback_url']):
        raise AdmissionDenied('Browser endpoints changed; update service provisioning first')
    import requests
    with requests.Session() as session:
        session.trust_env = False
        with session.get(config['submit_url'].removesuffix('/submit') + '/health',
                         headers={'Authorization': config['credential']['authorization']},
                         timeout=(1, 2), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise AdmissionDenied('Browser callback service is unavailable; start bin/jarvis-browser-use run')
    followup = {}
    if prior is not None:
        previous_result = prior.get('result') or {}
        research = previous_result.get('data', {}).get('browser_research') or {}
        sources = research.get('sources') or []
        last_url = next((url for url in reversed(sources)
                         if isinstance(url, str) and url.startswith(('https://', 'http://'))
                         and len(url) <= 2048), None)
        followup = {'followup': {
            'url': last_url or prior['admission']['arguments']['url'],
            'summary': str(previous_result.get('speech') or '')[:6000],
        }}
    return {**followup, 'runtime': {'mode': job['mode'], 'provider': auth.get('provider'),
                        'model': auth.get('model'), 'deadline': job['deadline'],
                        'proxy_policy': manifest.get('proxy_policy', 'inherit')}}, {
        'Authorization': config['credential']['authorization'],
    }


def provision(store, callback_base, submit_url):
    from .service import IntegrationService

    path = config_path(store)
    if path.exists():
        raise TaskError('Browser service is already provisioned; preserve its credentials and accepted jobs')
    callback_base, submit_url = endpoint(callback_base, local_only=True), endpoint(submit_url, local_only=True)
    store.initialize()
    service = IntegrationService(store)
    service.initialize_key()
    source = service.create_source(name='Browser use', callback_base=callback_base, submit_url=submit_url)
    credential = service.create_credential(source['id'])
    value = {'source_id': source['id'], 'submit_url': submit_url,
             'callback_url': source['endpoint'], 'credential': credential}
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        service.revoke_credential(source['id'], credential['id'])
        raise
    return {'source_id': source['id'], 'config': str(path),
            'next': 'Enable and test this source in Settings → Integrations, then enable browser_use in Tools.'}
