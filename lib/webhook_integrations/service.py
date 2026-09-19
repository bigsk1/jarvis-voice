"""Shared local control service. Web administers; API accepts; worker drains."""
import json
import os
import secrets
import uuid

from lib.background_tasks import TaskStore
from lib.background_tasks.models import (
    AdmissionDenied,
    Conflict,
    TaskError,
    canonical_json,
    identifier,
)

from .contracts import ADAPTER, EVENTS, CallbackError, endpoint, secret_hash
from .credentials import CredentialStore
from .crypto import KeyStore
from .inbox import CallbackInbox


class IntegrationService(CredentialStore, CallbackInbox):
    def __init__(self, store=None, *, key_path=None):
        self.store = store if store is not None else TaskStore()
        # Deployment setting shared by Web/API/worker, never a per-chat mode override.
        self.keys = KeyStore(key_path or os.environ.get('JARVIS_TASK_INTEGRATIONS_KEY')
                             or self.store.path.parent / 'secrets/task-integrations.key')

    @staticmethod
    def _source(conn, source_id):
        try:
            identifier(source_id, 'source ID')
        except TaskError:
            raise CallbackError('Task integration not found', 404) from None
        row = conn.execute('SELECT * FROM task_integrations WHERE id=?', (source_id,)).fetchone()
        if not row:
            raise CallbackError('Task integration not found', 404)
        return row

    def _source_info(self, conn, row):
        item = dict(row)
        item['events'] = json.loads(item.pop('events_json'))
        item['enabled'], item['revoked'] = bool(item['enabled']), bool(item['revoked'])
        item['endpoint'] = row['callback_base'] + f"/api/task-callbacks/{row['id']}/events"
        item['validated'] = row['validated_revision'] == row['revision']
        item['outstanding'] = conn.execute('''SELECT COUNT(*) FROM jobs j
            LEFT JOIN task_callback_bindings b ON b.job_id=j.id
            LEFT JOIN authorizations a ON a.id=json_extract(j.admission_json,'$.authorization_id')
            WHERE j.adapter=? AND j.state IN ('queued','starting','running','needs_attention')
            AND j.expired=0 AND j.cancelled=0 AND (b.source_id=? OR EXISTS (
                SELECT 1 FROM json_each(a.payload,'$.callback_sources') binding
                WHERE binding.key=json_extract(j.admission_json,'$.tool') AND binding.value=?))''',
                                           (ADAPTER, row['id'], row['id'])).fetchone()[0]
        item['credentials'] = [dict(cred) for cred in conn.execute('''SELECT id,version,scheme,created_at,expires_at,
            revoked_at,last_used_at,probe FROM task_credentials WHERE source_id=? AND probe=0
            ORDER BY version DESC LIMIT 100''', (row['id'],))]
        return item

    def status(self):
        try:
            self.keys.read()
            key_ready = True
        except TaskError:
            key_ready = False
        if not self.store.path.exists():
            return {'enabled': False, 'key_ready': key_ready, 'sources': []}
        with self.store._connection() as conn:
            sources = [self._source_info(conn, row) for row in conn.execute('SELECT * FROM task_integrations ORDER BY created_at')]
            return {'enabled': self.store._settings(conn)['webhooks_enabled'], 'key_ready': key_ready, 'sources': sources}

    def create_source(self, *, name, callback_base, submit_url, events=None, rate_limit=60):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise TaskError('Use a source name of 1–100 characters')
        callback_base, submit_url = endpoint(callback_base), endpoint(submit_url, local_only=True)
        events = sorted(EVENTS if events is None else self._events(events))
        if type(rate_limit) is not int or not 1 <= rate_limit <= 600:
            raise TaskError('Source rate limit must be between 1 and 600 requests per minute')
        with self.store._connection(write=True) as conn:
            if conn.execute('SELECT COUNT(*) FROM task_integrations').fetchone()[0] >= 128:
                raise TaskError('Task integration limit reached')
            source_id = uuid.uuid4().hex
            conn.execute('''INSERT INTO task_integrations(id,name,adapter,events_json,callback_base,submit_url,created_at,rate_limit)
                VALUES(?,?,?,?,?,?,?,?)''', (source_id, name.strip(), ADAPTER, json.dumps(events), callback_base,
                                            submit_url, self.store._time(), rate_limit))
            return self._source_info(conn, self._source(conn, source_id))

    @staticmethod
    def _events(events):
        if (not isinstance(events, list) or not events or any(not isinstance(item, str) for item in events)
                or len(events) != len(set(events)) or set(events) - EVENTS):
            raise TaskError('Select supported task events')
        return events

    def update_source(self, source_id, revision, **changes):
        if not changes or set(changes) - {'name', 'enabled', 'events', 'callback_base', 'submit_url', 'rate_limit', 'revoke'}:
            raise TaskError('Unsupported task integration setting')
        with self.store._connection(write=True) as conn:
            row = self._source(conn, source_id)
            if type(revision) is not int or row['revision'] != revision:
                raise Conflict('Integration changed; refresh before editing')
            if row['revoked']:
                raise TaskError('Revoked integrations cannot be enabled again')
            values = dict(row)
            for name, value in changes.items():
                if name in {'enabled', 'revoke'}:
                    if type(value) is not bool:
                        raise TaskError('Expected a boolean switch')
                    values['revoked' if name == 'revoke' else name] = int(value)
                elif name == 'name':
                    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 100:
                        raise TaskError('Invalid source name')
                    values[name] = value.strip()
                elif name == 'events':
                    values['events_json'] = json.dumps(sorted(self._events(value)))
                elif name in {'callback_base', 'submit_url'}:
                    values[name] = endpoint(value, local_only=name == 'submit_url')
                elif name == 'rate_limit':
                    if type(value) is not int or not 1 <= value <= 600:
                        raise TaskError('Invalid source rate limit')
                    values[name] = value
            if values['revoked']:
                values['enabled'] = 0
                conn.execute('UPDATE task_credentials SET revoked_at=? WHERE source_id=? AND revoked_at IS NULL',
                             (self.store._time(), source_id))
            connection_changed = any(values[key] != row[key] for key in ('callback_base', 'submit_url', 'events_json'))
            values['revision'] += 1
            if connection_changed:
                values['validated_revision'] = None
            elif row['validated_revision'] == row['revision']:
                values['validated_revision'] = values['revision']
            conn.execute('''UPDATE task_integrations SET name=:name,enabled=:enabled,revoked=:revoked,
                events_json=:events_json,callback_base=:callback_base,submit_url=:submit_url,
                rate_limit=:rate_limit,revision=:revision,validated_revision=:validated_revision WHERE id=:id''', values)
            if not values['enabled']:
                conn.execute("UPDATE task_callback_inbox SET state='held',reason='source_disabled' WHERE source_id=? AND state='pending'",
                             (source_id,))
            return self._source_info(conn, self._source(conn, source_id))

    def configure(self, enabled):
        if type(enabled) is not bool:
            raise TaskError('Expected a callback receiver switch')
        self.store.configure(webhooks_enabled=enabled)
        return self.status()

    def test_source(self, source_id):
        from .contracts import signature
        from .runner import post_json
        with self.store._connection() as conn:
            source = dict(self._ready_source(conn, source_id, require_validation=False))
            credential = conn.execute('''SELECT scheme FROM task_credentials WHERE source_id=? AND probe=0
                AND revoked_at IS NULL AND expires_at>? ORDER BY version DESC LIMIT 1''',
                                     (source_id, self.store._time())).fetchone()
            if not credential:
                raise TaskError('Create a source credential before testing the receiver')
        probe = self.create_credential(source_id, scheme=credential['scheme'], expires_in=60, probe=True)
        try:
            payload = {'schema_version': 1, 'event_id': uuid.uuid4().hex, 'type': 'integration.test'}
            timestamp = str(int(self.store._time()))
            headers = {'X-Jarvis-Timestamp': timestamp}
            if probe['scheme'] == 'bearer':
                headers['Authorization'] = probe['authorization']
            else:
                headers.update({'X-Jarvis-Key-Id': probe['id'], 'X-Jarvis-Signature': signature(
                    probe['secret'], source_id, timestamp, canonical_json(payload, 65536).encode())})
            result = post_json(source['callback_base'] + f'/api/task-callbacks/{source_id}/events',
                               payload, headers=headers, timeout=5)
            if result.get('accepted') is not True or result.get('event_id') != payload['event_id']:
                raise TaskError('Receiver returned an invalid test acknowledgement')
            with self.store._connection() as conn:
                current = self._source(conn, source_id)
                verified = conn.execute("SELECT 1 FROM task_callback_inbox WHERE source_id=? AND event_id=? AND state='tested'",
                                        (source_id, payload['event_id'])).fetchone()
                if not verified or current['validated_revision'] != current['revision']:
                    raise TaskError('Receiver did not persist the test in this installation')
            return {'ok': True, 'message': 'Authenticated callback reached this installation and was saved. No tool ran.'}
        except Exception as exc:
            raise TaskError('Callback setup test failed; check the API service, URL, receiver/source switches and key access') from exc
        finally:
            self.revoke_credential(source_id, probe['id'])

    def _ready_source(self, conn, source_id, *, require_validation=True):
        source = self._source(conn, source_id)
        if not self.store._settings(conn)['webhooks_enabled']:
            raise CallbackError('Task callback receiver is disabled', 503)
        if not source['enabled'] or source['revoked']:
            raise CallbackError('Task callback source is disabled', 403)
        if require_validation and source['validated_revision'] != source['revision']:
            raise AdmissionDenied('Task callback route must pass its setup test before submission')
        self.keys.read()
        if require_validation and not conn.execute('''SELECT 1 FROM task_credentials WHERE source_id=?
            AND probe=0 AND revoked_at IS NULL AND expires_at>?''', (source_id, self.store._time())).fetchone():
            raise AdmissionDenied('A usable source credential is required before submission')
        return source

    def check_source_ready(self, source_id):
        """Read-only callback requirements for discovery/admission, without a POST."""
        with self.store._connection() as conn:
            source = self._ready_source(conn, source_id)
            if source['adapter'] != ADAPTER:
                raise AdmissionDenied('Task callback source adapter does not match')
            if not {'task.completed', 'task.failed'} <= set(json.loads(source['events_json'])):
                raise AdmissionDenied('Task callback source must accept success and failure events')

    def prepare_submission(self, claim, source_id):
        """Trusted adapter only. Bind before the first byte of submission leaves."""
        with self.store._connection(write=True) as conn:
            row = self.store._active(conn, claim)
            source = self._ready_source(conn, source_id)
            if row['adapter'] != source['adapter'] or not self.store._generation_allowed(conn, row['conversation_id'], row['generation']):
                raise AdmissionDenied('Callback adapter/destination is not authorized')
            if conn.execute('SELECT 1 FROM task_callback_bindings WHERE job_id=?', (claim.job_id,)).fetchone():
                raise Conflict('Callback execution was already prepared; never submit again')
            capability = secrets.token_urlsafe(32)
            conn.execute('''INSERT INTO task_callback_bindings(job_id,source_id,attempt_id,fence,capability_hash,created_at)
                VALUES(?,?,?,?,?,?)''', (claim.job_id, source_id, claim.attempt_id, claim.fence,
                                        secret_hash(capability), self.store._time()))
            # A callback can beat the submit receipt or survive worker death.
            # The prebound attempt, not a worker heartbeat, owns its outcome now.
            conn.execute('UPDATE jobs SET callback_waiting=1 WHERE id=?', (claim.job_id,))
            return {'job_id': claim.job_id, 'attempt_id': claim.attempt_id,
                    'idempotency_key': claim.attempt_id,
                    'callback_url': source['callback_base'] + f'/api/task-callbacks/{source_id}/events',
                    'callback_capability': capability, 'submit_url': source['submit_url']}

    def record_submission(self, claim, remote_id):
        identifier(remote_id, 'remote task ID')
        with self.store._connection(write=True) as conn:
            binding = conn.execute('SELECT * FROM task_callback_bindings WHERE job_id=? AND attempt_id=?',
                                   (claim.job_id, claim.attempt_id)).fetchone()
            if not binding or binding['fence'] != claim.fence:
                raise Conflict('Submission identity changed')
            if binding['remote_id'] not in {None, remote_id}:
                raise Conflict('Provider returned conflicting task identities')
            conn.execute('UPDATE task_callback_bindings SET remote_id=? WHERE job_id=?', (remote_id, claim.job_id))

    def deliveries(self, source_id, *, offset=0, limit=25):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise TaskError('Invalid delivery page')
        with self.store._connection() as conn:
            self._source(conn, source_id)
            rows = [dict(row) for row in conn.execute('''SELECT id,event_id,job_id,attempt_id,event_type,
                credential_id,payload_digest,verified_at,state,reason,processed_at,attempts FROM task_callback_inbox
                WHERE source_id=? ORDER BY id DESC LIMIT ? OFFSET ?''', (source_id, limit, offset))]
            return {'deliveries': rows, 'offset': offset, 'total': conn.execute(
                'SELECT COUNT(*) FROM task_callback_inbox WHERE source_id=?', (source_id,)).fetchone()[0]}

    def dispose_event(self, source_id, event_id, action):
        if action != 'discard':
            raise TaskError('Held revoked evidence can only be discarded; re-sign a new delivery with a valid credential')
        with self.store._connection(write=True) as conn:
            if not conn.execute("UPDATE task_callback_inbox SET state='discarded',reason='operator_discarded',processed_at=? WHERE source_id=? AND event_id=? AND state='held'",
                                (self.store._time(), source_id, event_id)).rowcount:
                raise Conflict('Only held deliveries can be discarded')
