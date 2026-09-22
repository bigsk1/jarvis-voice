"""Operator-owned, opt-in bindings for private HTTP callback tools.

A personal manifest cannot grant itself a callback adapter. A separate 0600
deployment file pins its bytes, source, and exact service endpoints. This file
is absent from public clones and is never sent to Tool RAG or the model.
"""

import hashlib
import json
import logging
import os
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit

from lib.background_tasks.models import AdmissionDenied, TaskError
from lib.tool_manifest_files import iter_tool_manifests

from .contracts import ADAPTER, endpoint

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / 'data/secrets/private-callback-bindings.json'
_NAME = re.compile(r'[a-z][a-z0-9_]{0,63}\Z')
_HEX = re.compile(r'[0-9a-f]{64}\Z')
_ID = re.compile(r'[0-9a-f]{32}\Z')
logger = logging.getLogger(__name__)


class PrivateToolReviewRequired(AdmissionDenied):
    """A personal tool changed since its owner-only binding was reviewed."""


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate private callback setting')
        value[key] = item
    return value


def _entries():
    """Read trusted host settings without following links or accepting group access."""
    try:
        fd = os.open(CONFIG_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise TaskError('Private callback configuration is unavailable') from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise TaskError('Private callback configuration must be an owner-only regular file')
        with os.fdopen(fd, 'rb', closefd=False) as handle:
            raw = handle.read(65537)
        if len(raw) > 65536:
            raise TaskError('Private callback configuration is too large')
        value = json.loads(raw, object_pairs_hook=_unique)
        if (not isinstance(value, dict) or set(value) != {'version', 'bindings'}
                or type(value['version']) is not int or value['version'] != 1):
            raise ValueError('Invalid private callback configuration')
        rows = value['bindings']
        if not isinstance(rows, list) or len(rows) > 16:
            raise ValueError('Invalid private callback binding list')
        result = {}
        for row in rows:
            expected = {'tool', 'source_id', 'submit_url', 'callback_base', 'health_url',
                        'submit_token', 'manifest_sha256', 'script_sha256'}
            if not isinstance(row, dict) or set(row) - (expected | {'requires_tool'}) or not expected <= set(row):
                raise ValueError('Invalid private callback binding')
            name = row['tool']
            if not isinstance(name, str) or not _NAME.fullmatch(name) or name in result:
                raise ValueError('Invalid or repeated private callback tool')
            owner, _ = _manifest(name)
            if owner.parent != ROOT / 'skills/personal':
                raise ValueError('Private callback tool must be owned by skills/personal')
            if (not isinstance(row['source_id'], str) or not _ID.fullmatch(row['source_id'])
                    or any(not isinstance(row[key], str) or not _HEX.fullmatch(row[key])
                           for key in ('manifest_sha256', 'script_sha256'))):
                raise ValueError('Invalid private callback identity or fingerprint')
            for key in ('submit_url', 'callback_base', 'health_url'):
                if not isinstance(row[key], str) or endpoint(row[key]) != row[key] or not row[key].startswith('https://'):
                    raise ValueError('Private callback endpoints must be exact HTTPS URLs')
            submit, health, callback = (urlsplit(row[key]) for key in ('submit_url', 'health_url', 'callback_base'))
            if ((submit.hostname, submit.port) != (health.hostname, health.port)
                    or not submit.path or not health.path or callback.path not in {'', '/'}):
                raise ValueError('Private callback endpoint paths or service host do not match')
            token = row['submit_token']
            if not isinstance(token, str) or not 32 <= len(token) <= 512 or any(ord(char) < 33 for char in token):
                raise ValueError('Invalid private callback submit credential')
            dependency = row.get('requires_tool')
            if dependency is not None and (not isinstance(dependency, str) or not _NAME.fullmatch(dependency)):
                raise ValueError('Invalid private callback dependency')
            result[name] = row
        return result
    except (UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise TaskError('Invalid private callback configuration') from exc
    finally:
        os.close(fd)


def _available_entries():
    try:
        return _entries()
    except TaskError as exc:
        logger.warning('Private callback bindings disabled: %s', exc)
        return {}


def bindings():
    return dict.fromkeys(_available_entries(), ADAPTER)


def callback_sources(store):
    return {name: row['source_id'] for name, row in _available_entries().items()}


def _manifest(name):
    for path, manifest in iter_tool_manifests(ROOT / 'skills'):
        if manifest.get('name') == name:
            return path, manifest
    raise AdmissionDenied('Private callback tool manifest is unavailable')


def _blocked(name, dependency):
    from config_loader import get_config_value
    from tool_profiles import effective_enabled, load_active_profile_overrides

    blocked = {part.strip() for part in str(get_config_value('BLOCKED_TOOLS', '')).split(',')}
    web_config = ROOT / 'jarvis-web/config/web_config.json'
    if web_config.exists():
        blocked.update(json.loads(web_config.read_text()).get('tools', {}).get('blocked', []))
    if name in blocked or dependency in blocked:
        return True
    if dependency:
        _, manifest = _manifest(dependency)
        if not effective_enabled(dependency, manifest.get('enabled', True), load_active_profile_overrides()):
            return True
    return False


def _reviewed_manifest(name, row):
    path, manifest = _manifest(name)
    script = path.with_name(f'{name}.py')
    if path.parent != ROOT / 'skills/personal':
        raise AdmissionDenied('Private callback tool must live in skills/personal')
    try:
        manifest_bytes, script_bytes = path.read_bytes(), script.read_bytes()
    except OSError as exc:
        raise AdmissionDenied('Private callback tool files are unavailable') from exc
    background = manifest.get('execution', {}).get('background', {})
    timeout = background.get('timeout_seconds')
    if (hashlib.sha256(manifest_bytes).hexdigest() != row['manifest_sha256']
            or hashlib.sha256(script_bytes).hexdigest() != row['script_sha256']):
        raise PrivateToolReviewRequired('Private callback tool no longer matches its reviewed policy')
    if (manifest.get('script') != script.name
            or background.get('supported') is not True or background.get('required') is not True
            or background.get('adapter') != ADAPTER or type(timeout) is not int
            or not 1 <= timeout <= 86400):
        raise AdmissionDenied('Private callback tool no longer matches its reviewed policy')
    return manifest, timeout


def policy(name):
    """Review evidence is pinned outside the manifest and rechecked at claim."""
    row = _entries().get(name)
    if not row:
        raise AdmissionDenied('Private callback binding is not installed')
    manifest, timeout = _reviewed_manifest(name, row)
    from tool_profiles import effective_enabled, load_active_profile_overrides
    if (not effective_enabled(name, manifest.get('enabled', True), load_active_profile_overrides())
            or _blocked(name, row.get('requires_tool'))):
        raise AdmissionDenied('Private callback tool or its required tool is disabled')
    evidence = {'manifest_sha256': row['manifest_sha256'], 'script_sha256': row['script_sha256'],
                'adapter': ADAPTER, 'timeout_seconds': timeout}
    return manifest, evidence


def review_required(name):
    """Safe failure detail for a private callback job rejected before submission."""
    try:
        policy(name)
    except PrivateToolReviewRequired:
        return True
    except Exception:
        pass
    return False


def service_ready(name, *, timeout=.35):
    try:
        import requests

        row = _entries()[name]
        with requests.Session() as session:
            session.trust_env = False
            with session.get(row['health_url'], headers={'Authorization': 'Bearer ' + row['submit_token']},
                             timeout=(timeout, timeout), allow_redirects=False, stream=True) as response:
                return response.status_code == 200
    except Exception:
        return False


def callback_readiness(store):
    return {name: (lambda name=name: service_ready(name)) for name in _available_entries()}


def status(store, name, *, mode='cloud'):
    """Safe Settings projection; no endpoints, ids, or credentials leave Web."""
    from config_loader import config_scope

    from .service import IntegrationService

    row = _available_entries().get(name)
    if not row:
        return {'policy_ready': False, 'policy_issue': 'unavailable',
                'source_ready': False, 'service_ready': False}
    policy_issue = None
    try:
        with config_scope(mode):
            policy(name)
        policy_ready = True
    except PrivateToolReviewRequired:
        policy_ready = False
        policy_issue = 'review_required'
    except Exception:
        policy_ready = False
        policy_issue = 'unavailable'
    try:
        IntegrationService(store).check_source_ready(row['source_id'])
        source_ready = True
    except Exception:
        source_ready = False
    return {'policy_ready': policy_ready, 'policy_issue': policy_issue,
            'source_ready': source_ready,
            'service_ready': service_ready(name) if policy_ready and source_ready else False}


def parameters(store):
    result = {}
    for name, row in _available_entries().items():
        try:
            result[name] = _reviewed_manifest(name, row)[0]['parameters']
        except (TaskError, OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning('Private callback worker binding unavailable tool=%s error_type=%s',
                           name, type(exc).__name__)
    return result


def prepare(context):
    from config_loader import config_scope

    job, store = context.claim.job, context.store
    name = job['admission']['tool']
    row = _entries().get(name)
    if not row:
        raise AdmissionDenied('Private callback binding is unavailable')
    with config_scope(job['mode']):
        _, evidence = policy(name)
    auth = store.authorization(job['admission']['authorization_id'])
    if (not auth or auth.get('tool_policies', {}).get(name) != evidence
            or auth.get('callback_sources', {}).get(name) != row['source_id']
            or auth.get('mode') != job['mode'] or auth.get('tool_policy') == 'none'):
        raise AdmissionDenied('Private callback authorization changed after admission')
    with store._connection() as conn:
        source = conn.execute('SELECT submit_url,callback_base FROM task_integrations WHERE id=?',
                              (row['source_id'],)).fetchone()
    if (not source or source['submit_url'] != row['submit_url']
            or source['callback_base'] != row['callback_base']):
        raise AdmissionDenied('Private callback endpoints changed after setup')
    if not service_ready(name, timeout=2):
        raise AdmissionDenied('Private callback service is unavailable')
    return {'deadline': job['deadline']}, {'Authorization': 'Bearer ' + row['submit_token']}, row['submit_url']
