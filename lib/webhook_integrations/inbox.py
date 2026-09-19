"""Durable acceptance and atomic inbox/result/outbox application, never execution."""
import hashlib
import hmac
import json
import uuid

from lib.background_tasks.models import MAX_RESULT_BYTES, canonical_json, digest

from .contracts import CallbackError, event_body, secret_hash


class CallbackInbox:
    def accept(self, source_id, raw, headers):
        headers = {key.lower(): value for key, value in headers.items()}
        if len(raw) > 1024 * 1024:
            raise CallbackError('Callback body is too large', 413)
        with self.store._connection(write=True) as conn:
            source = self._source(conn, source_id)
            credential = self._authenticate(conn, source_id, headers, raw)
            if source['revoked']:
                raise CallbackError('Invalid callback credentials or timestamp', 401)
            body = event_body(raw)
            probe = body['type'] == 'integration.test'
            if bool(credential['probe']) != probe:
                raise CallbackError('Credential is not authorized for this event', 403)
            if not probe:
                binding = conn.execute('SELECT * FROM task_callback_bindings WHERE job_id=?', (body['job_id'],)).fetchone()
                if (not binding or binding['source_id'] != source_id or binding['attempt_id'] != body['attempt_id']
                        or not hmac.compare_digest(binding['capability_hash'], secret_hash(headers.get('x-jarvis-task-capability', '')))):
                    raise CallbackError('Callback does not match a source-bound execution attempt', 403)
                presentation = body.get('result', {}).get('presentation')
                if presentation:
                    job = conn.execute('SELECT admission_json FROM jobs WHERE id=?', (body['job_id'],)).fetchone()
                    admission = json.loads(job['admission_json']) if job else {}
                    if admission.get('tool') != 'browser_use':
                        raise CallbackError('Presentation metadata is not allowed for this callback job', 403)
            payload = canonical_json(body, 1024 * 1024)
            # Identity covers the original event, even when invalid optional
            # presentation metadata was discarded for safe application.
            fingerprint = (hashlib.sha256(raw).hexdigest() if json.loads(raw) != body
                           else digest(payload))
            duplicate = conn.execute('SELECT payload_digest FROM task_callback_inbox WHERE source_id=? AND event_id=?',
                                     (source_id, body['event_id'])).fetchone()
            if duplicate:
                if duplicate['payload_digest'] != fingerprint:
                    raise CallbackError('Event identity was reused with different content', 409)
                return {'accepted': True, 'duplicate': True, 'event_id': body['event_id']}
            # Switches govern new receipt, never erase a committed acceptance.
            # Retries still require current credentials and the attempt capability.
            self._ready_source(conn, source_id, require_validation=False)
            if probe and credential['probe_revision'] != source['revision']:
                raise CallbackError('Integration changed during setup test; test the current route', 409)
            if not probe and body['type'] not in json.loads(source['events_json']):
                raise CallbackError('Event type is not allowed for this source', 403)
            now = self.store._time()
            window = int(now // 60)
            bucket = 'source:' + source_id
            current = conn.execute('SELECT * FROM task_callback_limits WHERE bucket=?', (bucket,)).fetchone()
            count = current['count'] if current and current['window'] == window else 0
            if count >= source['rate_limit']:
                raise CallbackError('Callback source rate limit exceeded; retry later', 429)
            if conn.execute("SELECT COUNT(*) FROM task_callback_inbox WHERE state IN ('pending','held')").fetchone()[0] >= 10000:
                raise CallbackError('Callback inbox is full; retry later', 503)
            conn.execute('INSERT OR REPLACE INTO task_callback_limits VALUES(?,?,?)', (bucket, window, count + 1))
            conn.execute('''INSERT INTO task_callback_inbox(source_id,credential_id,event_id,job_id,attempt_id,event_type,
                payload_json,payload_digest,verified_at,state,processed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                         (source_id, credential['id'], body['event_id'], body.get('job_id'), body.get('attempt_id'),
                          body['type'], payload, fingerprint, now, 'tested' if probe else 'pending', now if probe else None))
            conn.execute('UPDATE task_credentials SET last_used_at=? WHERE id=?', (now, credential['id']))
            if probe:
                conn.execute('UPDATE task_integrations SET validated_revision=revision,validated_at=? WHERE id=?', (now, source_id))
        self.store.events.emit('callback_accepted', component='callback', source_id=source_id,
                               event_id=body['event_id'], job_id=body.get('job_id'))
        return {'accepted': True, 'duplicate': False, 'event_id': body['event_id']}

    def drain(self, *, limit=100):
        """Short serialized transactions; multiple drainers cannot apply twice."""
        processed = 0
        for _ in range(limit):
            with self.store._connection(write=True) as conn:
                entry = conn.execute('''SELECT i.* FROM task_callback_inbox i JOIN task_integrations s ON s.id=i.source_id
                    WHERE i.state='pending' OR (i.state='held' AND i.reason='source_disabled' AND s.enabled=1 AND s.revoked=0)
                    ORDER BY i.id LIMIT 1''').fetchone()
                if not entry:
                    break
                state, reason = self._apply_event(conn, entry)
                conn.execute('''UPDATE task_callback_inbox SET state=?,reason=?,processed_at=?,attempts=attempts+1 WHERE id=?''',
                             (state, reason, self.store._time() if state != 'held' else None, entry['id']))
            processed += 1
            self.store.events.emit('callback_processed', component='callback', source_id=entry['source_id'],
                                   event_id=entry['event_id'], job_id=entry['job_id'], state=state, reason=reason)
        return processed

    def _apply_event(self, conn, entry):
        now = self.store._time()
        source = self._source(conn, entry['source_id'])
        credential = conn.execute('SELECT * FROM task_credentials WHERE id=?', (entry['credential_id'],)).fetchone()
        if not credential or credential['revoked_at'] is not None:
            return 'held', 'credential_revoked'
        if credential['expires_at'] <= now:
            return 'held', 'credential_expired'
        if not source['enabled'] or source['revoked']:
            return 'held', 'source_disabled'
        if entry['event_type'] not in json.loads(source['events_json']):
            return 'held', 'event_permission_changed'
        binding = conn.execute('SELECT * FROM task_callback_bindings WHERE job_id=?', (entry['job_id'],)).fetchone()
        row = conn.execute('SELECT * FROM jobs WHERE id=?', (entry['job_id'],)).fetchone()
        if not row or not binding:
            return 'late', 'job_removed'
        if (binding['source_id'] != entry['source_id'] or binding['attempt_id'] != entry['attempt_id']
                or row['attempt_id'] != binding['attempt_id'] or row['fence'] != binding['fence']):
            return 'late', 'execution_fenced'
        if (row['state'] not in {'starting', 'running'} or row['expired'] or row['cancelled']
                or row['deadline'] <= now or not row['callback_waiting']
                or not self.store._generation_allowed(conn, row['conversation_id'], row['generation'])):
            return 'late', 'execution_closed'
        body = json.loads(entry['payload_json'])
        if entry['event_type'] == 'task.progress':
            if binding['last_progress_at'] is not None and now - binding['last_progress_at'] < 2:
                return 'ignored', 'progress_throttled'
            conn.execute('UPDATE jobs SET progress_json=?,updated_at=? WHERE id=?',
                         (canonical_json(body['progress'], 4096), now, row['id']))
            conn.execute('UPDATE task_callback_bindings SET last_progress_at=? WHERE job_id=?', (now, row['id']))
            return 'applied', None
        cancelled = entry['event_type'] == 'task.cancelled'
        if cancelled and not row['cancel_requested']:
            return 'held', 'cancellation_not_requested'
        succeeded = entry['event_type'] == 'task.completed'
        presentation = body['result'].get('presentation')
        result = {'ok': succeeded, 'speech': body['result']['summary'],
                  'data': {'browser_research': presentation} if presentation else {}}
        if cancelled:
            result['cancelled'] = True
        payload = canonical_json(result, MAX_RESULT_BYTES)
        fingerprint = digest(payload)
        state = 'succeeded' if succeeded else 'failed'
        conn.execute('''UPDATE jobs SET state=?,cancelled=?,callback_waiting=0,result_json=?,result_digest=?,
            updated_at=?,progress_json=NULL WHERE id=?''', (state, int(cancelled), payload, fingerprint, now, row['id']))
        conn.execute('UPDATE attempts SET finished_at=?,outcome=? WHERE id=?',
                     (now, 'cancelled' if cancelled else state, row['attempt_id']))
        # Acknowledged cancellation follows local cancellation: update the card
        # without scheduling an assistant follow-up.
        conn.execute('INSERT INTO outbox(id,job_id,result_digest,created_at,state) VALUES(?,?,?,?,?)',
                     (uuid.uuid4().hex, row['id'], fingerprint, now, 'suppressed' if cancelled else 'pending'))
        return 'applied', None
