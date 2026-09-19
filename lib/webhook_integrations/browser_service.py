"""Optional loopback host for the Web-only browser_use callback job.

Submission commits before acknowledgement. Started jobs are never replayed;
completion/progress events are retained and retried independently of execution.
"""
import hashlib
import hmac
import json
import logging
import math
import os
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import requests

from lib.background_tasks.models import TaskError, canonical_json, identifier

from .browser import ROOT
from .browser_audit import BrowserAudit

logger = logging.getLogger(__name__)


def stop_browser_container(name):
    """Prove the invocation's Chrome is gone even if its Python child was killed."""
    try:
        removed = subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, timeout=10)
        if removed.returncode == 0:
            return True
        inspected = subprocess.run(['docker', 'inspect', '--format', '{{.State.Running}}', name],
                                   capture_output=True, timeout=5)
        return inspected.returncode == 1 and b'No such' in inspected.stderr
    except (OSError, subprocess.TimeoutExpired):
        return False


def child_environment(runtime, deployment_overrides=None):
    from config_loader import config_scope

    from lib.background_tasks.worker import _child_environment

    mode, provider, model = runtime['mode'], runtime['provider'], runtime['model']
    model_keys = {'openai': 'OPENAI_MODEL', 'anthropic': 'ANTHROPIC_MODEL', 'xai': 'XAI_MODEL',
                  'helper': 'JARVIS_HELPER_LLM_MODEL',
                  'ollama': 'OLLAMA_MODEL' if mode == 'local' else 'OLLAMA_CLOUD_MODEL'}
    allowed = {'STASH_DIR', 'JARVIS_TOOL_PROFILE', 'BROWSER_USE_ALLOWED_HOSTS'}
    overrides = {key: value for key, value in (deployment_overrides or {}).items() if key in allowed}
    overrides.update({'LLM_PROVIDER': provider, model_keys[provider]: model,
                 'JARVIS_BACKGROUND_DEADLINE': str(runtime['deadline']),
                 'JARVIS_TOOL_PROXY_POLICY': runtime['proxy_policy']})
    # Reuse the worker's clean per-mode environment, without promoting secrets.
    with config_scope(mode, overrides=overrides) as snapshot:
        return _child_environment(mode, snapshot)


class BrowserService:
    def __init__(self, path, config, *, deployment_overrides=None, audit=None, task_store=None):
        self.path, self.config = path, config
        self.task_store = task_store
        self.deployment_overrides = dict(deployment_overrides or {})
        self.audit = audit or BrowserAudit(path)
        self.stop = threading.Event()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connection() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS browser_jobs (
                    id TEXT PRIMARY KEY, digest TEXT NOT NULL, payload TEXT NOT NULL,
                    state TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS browser_events (
                    id INTEGER PRIMARY KEY, job_id TEXT NOT NULL, body TEXT NOT NULL,
                    delivered INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
                    retry_at REAL NOT NULL DEFAULT 0, last_status INTEGER);
            ''')
            # A crash may leave a Chrome child or an in-flight provider call.
            # Preserve uncertainty; never turn started work back into queued.
            conn.execute("UPDATE browser_jobs SET state='uncertain' WHERE state='running'")
        os.chmod(self.path, 0o600)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def retry_rejected(path, attempt_id):
        """Operator repair: requeue only parked callbacks, never browser work."""
        identifier(attempt_id, 'browser attempt ID')
        path = Path(path)
        if not path.is_file():
            raise TaskError('Browser callback history is unavailable')
        with sqlite3.connect(path, timeout=5) as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('''SELECT j.payload,COUNT(e.id) FROM browser_jobs j
                LEFT JOIN browser_events e ON e.job_id=j.id AND e.delivered=-1
                WHERE j.id=? GROUP BY j.id''', (attempt_id,)).fetchone()
            if not row or not row[1]:
                raise TaskError('No rejected callbacks exist for this browser attempt')
            if time.time() >= json.loads(row[0])['runtime']['deadline']:
                raise TaskError('Browser attempt deadline passed; reconcile the task instead')
            conn.execute('UPDATE browser_events SET delivered=0,retry_at=0 WHERE job_id=? AND delivered=-1',
                         (attempt_id,))
            return row[1]

    def accept(self, payload):
        from jsonschema import Draft202012Validator

        expected = {'job_id', 'attempt_id', 'idempotency_key', 'callback_url',
                    'callback_capability', 'arguments', 'runtime'}
        if not isinstance(payload, dict) or set(payload) != expected:
            raise TaskError('Invalid browser submission')
        for key in ('job_id', 'attempt_id', 'idempotency_key'):
            identifier(payload[key], key)
        if (payload['idempotency_key'] != payload['attempt_id']
                or payload['callback_url'] != self.config['callback_url']
                or not isinstance(payload['callback_capability'], str)
                or not 32 <= len(payload['callback_capability']) <= 128):
            raise TaskError('Invalid browser destination')
        runtime = payload['runtime']
        if (not isinstance(runtime, dict) or set(runtime) != {'mode', 'provider', 'model', 'deadline', 'proxy_policy'}
                or runtime['mode'] not in {'cloud', 'local'}
                or runtime['provider'] not in {'openai', 'anthropic', 'xai', 'ollama', 'helper'}
                or not isinstance(runtime['model'], str) or not 1 <= len(runtime['model']) <= 256
                or runtime['proxy_policy'] not in {'inherit', 'off', 'prefer', 'require'}
                or type(runtime['deadline']) not in {int, float} or not math.isfinite(runtime['deadline'])):
            raise TaskError('Invalid browser runtime selection')
        manifest = json.loads((ROOT / 'skills/browser_use.tool.json').read_text())
        Draft202012Validator(manifest['parameters']).validate(payload['arguments'])
        raw = canonical_json(payload, 65536)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            old = conn.execute('SELECT digest FROM browser_jobs WHERE id=?', (payload['attempt_id'],)).fetchone()
            if old:
                if old['digest'] != digest:
                    raise TaskError('Conflicting browser invocation')
                return {'remote_id': payload['attempt_id']}, 200
            if not time.time() < runtime['deadline'] <= time.time() + 905:
                raise TaskError('Browser task deadline expired or exceeds the reviewed budget')
            # Uncertain rows are durable no-replay evidence, not live work. They
            # must never poison the bounded execution queue permanently.
            if conn.execute("SELECT count(*) FROM browser_jobs WHERE state IN ('queued','running')").fetchone()[0] >= 32:
                raise TaskError('Browser service queue is full')
            conn.execute('INSERT INTO browser_jobs VALUES(?,?,?,?,?)',
                         (payload['attempt_id'], digest, raw, 'queued', time.time()))
        logger.info('Browser job accepted attempt=%s mode=%s', payload['attempt_id'], runtime['mode'])
        self.audit.emit('job_accepted', job_id=payload['job_id'], attempt_id=payload['attempt_id'],
                        mode=runtime['mode'], provider=runtime['provider'], model=runtime['model'], state='queued')
        return {'remote_id': payload['attempt_id']}, 202

    def event(self, payload, event_type, value, *, conn=None):
        field = 'progress' if event_type == 'task.progress' else 'result'
        body = canonical_json({'schema_version': 1, 'event_id': uuid.uuid4().hex,
            'job_id': payload['job_id'], 'attempt_id': payload['attempt_id'],
            'type': event_type, field: value}, 1024 * 1024)
        if conn is not None:
            conn.execute('INSERT INTO browser_events(job_id,body) VALUES(?,?)', (payload['attempt_id'], body))
        else:
            with self.connection() as conn:
                conn.execute('INSERT INTO browser_events(job_id,body) VALUES(?,?)', (payload['attempt_id'], body))

    def execute_one(self):
        from tool_process import TerminationUnverified, run_local_process, terminate_verified
        from tool_progress import parse_tool_progress

        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute("SELECT * FROM browser_jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if not row or self.stop.is_set():
                return False
            conn.execute("UPDATE browser_jobs SET state='running' WHERE id=?", (row['id'],))
        payload = json.loads(row['payload'])
        logger.info('Browser job started attempt=%s', row['id'])
        audit_context = {'job_id': payload['job_id'], 'attempt_id': payload['attempt_id'],
                         'mode': payload['runtime']['mode'], 'provider': payload['runtime']['provider'],
                         'model': payload['runtime']['model'],
                         'proxy_policy': payload['runtime']['proxy_policy']}
        self.audit.emit('job_started', state='running', **audit_context)
        container_name = 'jarvis-browser-job-' + row['id']
        archive_ref = None
        operator_cancelled = False
        destination_closed = False
        next_cancel_check = 0

        def checkpoint():
            # Keep the process-group verification in run_local_process. Stop and
            # deadline are cooperative cancellation below so the child can emit
            # its archived partial result after SIGTERM.
            return None

        def cancel_check():
            nonlocal operator_cancelled, destination_closed, next_cancel_check
            if operator_cancelled or destination_closed:
                return True
            if self.stop.is_set() or time.time() >= payload['runtime']['deadline']:
                return True
            if self.task_store is not None and time.monotonic() >= next_cancel_check:
                next_cancel_check = time.monotonic() + 1
                status = self.task_store.callback_attempt_status(payload['job_id'], row['id'])
                operator_cancelled = status == 'cancel_requested'
                destination_closed = status == 'closed'
                return operator_cancelled or destination_closed
            return False

        def progress(line):
            nonlocal archive_ref
            value = parse_tool_progress(line)
            if value:
                reference = value.get('stash_ref')
                if (isinstance(reference, str) and reference.startswith('stash://')
                        and len(reference) <= 520):
                    archive_ref = reference
                self.event(payload, 'task.progress', {'phase': str(value.get('phase', 'Browsing'))[:256]})
            return bool(value)

        def terminate(process, grace_seconds, verify=False):
            return terminate_verified(process, grace_seconds)

        try:
            checkpoint()
            # A queued helper job may be cancelled or fenced before Chrome starts.
            if self.task_store is not None:
                status = self.task_store.callback_attempt_status(payload['job_id'], row['id'])
                if status == 'closed':
                    with self.connection() as conn:
                        conn.execute("UPDATE browser_jobs SET state='finished' WHERE id=?", (row['id'],))
                    self.audit.emit('job_destination_closed', state='finished', **audit_context)
                    return True
                if status == 'cancel_requested':
                    with self.connection() as conn:
                        self.event(payload, 'task.cancelled', {'summary': 'Browser research cancelled before it started.'}, conn=conn)
                        conn.execute("UPDATE browser_jobs SET state='finished' WHERE id=?", (row['id'],))
                    self.audit.emit('job_finished', state='finished', ok=False, **audit_context)
                    return True
            environment = child_environment(payload['runtime'], self.deployment_overrides)
            environment['JARVIS_BROWSER_USE_AUDIT_DIR'] = str(self.audit.directory)
            environment['JARVIS_BROWSER_USE_CONTAINER_NAME'] = container_name
            private_request = {'arguments': payload['arguments'], 'job_id': payload['job_id'],
                               'attempt_id': payload['attempt_id']}
            stdout, _, cancelled = run_local_process(
                # Isolated startup prevents the entrypoint's http.py sibling
                # from shadowing Python's standard http package.
                [sys.executable, '-I', str(ROOT / 'lib/webhook_integrations/browser_job.py'), canonical_json(private_request, 32768)], '',
                python_script=True, cwd=str(ROOT), tool_env=environment,
                timeout=max(1, payload['runtime']['deadline'] - time.time()), tool_name='browser_use',
                consume_progress=progress, cancel_check=cancel_check, terminate=terminate, checkpoint=checkpoint,
                max_output_bytes=1024 * 1024,
            )
            if cancelled and not stop_browser_container(container_name):
                raise TerminationUnverified('Browser container stop could not be verified')
            if destination_closed:
                with self.connection() as conn:
                    conn.execute("UPDATE browser_jobs SET state='finished' WHERE id=?", (row['id'],))
                self.audit.emit('job_destination_closed', state='finished', **audit_context)
                return True
            if cancelled and not stdout.strip():
                result = {'ok': False, 'completion': 'failed',
                          'speech': 'Browser research stopped before a final report. Saved page evidence is partial.'}
            else:
                result = json.loads(stdout)
            if not isinstance(result, dict) or type(result.get('ok')) is not bool:
                raise ValueError('Invalid browser skill result')
            if result.get('completion') == 'unknown':
                if isinstance(result.get('stash_ref'), str):
                    archive_ref = result['stash_ref']
                raise RuntimeError('Browser execution did not establish a terminal outcome')
            if cancelled and operator_cancelled:
                result['ok'] = False
                result['speech'] = 'Browser research cancelled. ' + str(result.get('speech') or '')
            if not result.get('stash_ref') and archive_ref:
                result['stash_ref'] = archive_ref
                result.setdefault('provider', payload['runtime']['provider'])
                result.setdefault('model', payload['runtime']['model'])
                result['speech'] = f'Saved research: {archive_ref}\n\n' + str(result.get('speech') or '')
            summary = str(result.get('speech') or 'Browser task finished without a report.').encode()[:28000].decode('utf-8', errors='ignore')
            event_result = {'summary': summary}
            stash_ref, provider, model = result.get('stash_ref'), result.get('provider'), result.get('model')
            sources, source_bytes = [], 0
            for source in result.get('sources', []) if isinstance(result.get('sources'), list) else []:
                if not isinstance(source, str) or len(source) > 2048:
                    continue
                size = len(source.encode())
                if len(sources) >= 60 or source_bytes + size > 12000:
                    break
                sources.append(source)
                source_bytes += size
            # A terminal Browser Use run may produce a useful archived report
            # while honestly failing to satisfy the full research goal. Keep
            # the failed task state, but preserve the reviewed presentation so
            # Web can show that evidence as an explicitly partial report.
            if (isinstance(stash_ref, str) and isinstance(provider, str)
                    and isinstance(model, str)):
                event_result['presentation'] = {
                    'kind': 'browser_research', 'stash_ref': stash_ref,
                    'sources': sources, 'provider': provider, 'model': model,
                }
            with self.connection() as conn:
                event_type = ('task.cancelled' if cancelled and operator_cancelled else
                              'task.completed' if result['ok'] else 'task.failed')
                self.event(payload, event_type, event_result, conn=conn)
                conn.execute("UPDATE browser_jobs SET state='finished' WHERE id=?", (row['id'],))
            logger.info('Browser job finished attempt=%s ok=%s', row['id'], result['ok'])
            self.audit.emit('job_finished', state='finished', ok=result['ok'], **audit_context)
        except Exception as exc:
            if isinstance(exc, TerminationUnverified):
                # Still tear down Docker if possible, but the Python process
                # group lacks stop proof, so do not claim a terminal result.
                stop_browser_container(container_name)
            if not isinstance(exc, TerminationUnverified) and stop_browser_container(container_name):
                # run_local_process only raises ordinary failures after it has
                # verified the whole child process group stopped. Its archive
                # checkpoint is already durable when stash_ref was reported.
                summary = 'Browser research stopped before a final report. Any saved evidence is partial.'
                if archive_ref:
                    summary = f'Saved research: {archive_ref}\n\n' + summary
                result = {'summary': summary}
                if archive_ref:
                    result['presentation'] = {
                        'kind': 'browser_research', 'stash_ref': archive_ref, 'sources': [],
                        'provider': payload['runtime']['provider'], 'model': payload['runtime']['model'],
                    }
                with self.connection() as conn:
                    if not destination_closed:
                        self.event(payload, 'task.cancelled' if operator_cancelled else 'task.failed',
                                   result, conn=conn)
                    conn.execute("UPDATE browser_jobs SET state='finished' WHERE id=?", (row['id'],))
                logger.warning('Browser job stopped attempt=%s error_type=%s', row['id'], type(exc).__name__)
                self.audit.emit('job_finished', level='WARNING', state='finished', ok=False,
                                error_type=type(exc).__name__, **audit_context)
                return True
            # Without process-group stop proof Docker may still be running;
            # preserve uncertainty instead of inventing a terminal callback.
            with self.connection() as conn:
                conn.execute("UPDATE browser_jobs SET state='uncertain' WHERE id=?", (row['id'],))
            logger.warning('Browser job needs attention attempt=%s error_type=%s', row['id'], type(exc).__name__)
            self.audit.emit('job_uncertain', level='WARNING', state='uncertain',
                            error_type=type(exc).__name__, **audit_context)
        return True

    def deliver_one(self):
        with self.connection() as conn:
            row = conn.execute('''SELECT e.*, j.payload FROM browser_events e JOIN browser_jobs j ON j.id=e.job_id
                WHERE delivered=0 AND retry_at<=? ORDER BY e.id LIMIT 1''', (time.time(),)).fetchone()
        if not row:
            return False
        payload = json.loads(row['payload'])
        headers = {'Content-Type': 'application/json', 'Authorization': self.config['credential']['authorization'],
                   'X-Jarvis-Timestamp': str(int(time.time())),
                   'X-Jarvis-Task-Capability': payload['callback_capability']}
        status = 0
        try:
            with requests.Session() as session:
                session.trust_env = False
                with session.post(self.config['callback_url'], data=row['body'].encode(), headers=headers,
                                  timeout=(3, 5), allow_redirects=False, stream=True) as response:
                    status = response.status_code
        except requests.RequestException:
            pass
        delivered = status in {200, 202}
        permanent_rejection = 400 <= status < 500 and status not in {408, 425, 429}
        with self.connection() as conn:
            conn.execute('UPDATE browser_events SET delivered=?, attempts=attempts+1, last_status=?, retry_at=? WHERE id=?',
                         (-1 if permanent_rejection else int(delivered), status,
                          time.time() + min(60, 2 ** min(row['attempts'] + 1, 6)), row['id']))
        logger.info('Browser callback attempt=%s http_status=%s accepted=%s permanent_rejection=%s',
                    row['job_id'], status, delivered, permanent_rejection)
        self.audit.emit('callback_delivery', job_id=payload['job_id'],
                        attempt_id=payload['attempt_id'], callback_status=status,
                        accepted=delivered, state='rejected' if permanent_rejection else None)
        return True

    def run(self):
        parts = urlsplit(self.config['submit_url'])
        if parts.hostname not in {'127.0.0.1', '::1'} or parts.scheme != 'http' or parts.path != '/submit':
            raise TaskError('Browser service requires http://127.0.0.1:PORT/submit')
        service = self
        self.audit.emit('service_started', state='running')

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def authorized(self):
                return (len(self.headers.get_all('Authorization', [])) == 1
                        and hmac.compare_digest(self.headers.get('Authorization', ''), service.config['credential']['authorization'])
                        and service.config['credential']['expires_at'] > time.time())

            def do_GET(self):
                self.connection.settimeout(5)
                if self.path != '/health' or not self.authorized():
                    self.send_error(401)
                    return
                self.send_response(200)
                self.send_header('Content-Length', '0')
                self.end_headers()

            def do_POST(self):
                self.connection.settimeout(5)
                if self.path != '/submit' or not self.authorized():
                    self.send_error(401)
                    return
                try:
                    if (self.headers.get('Content-Encoding') or self.headers.get('Transfer-Encoding')
                            or len(self.headers.get_all('Content-Length', [])) != 1):
                        raise ValueError()
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 65536:
                        raise ValueError()
                    body, status = service.accept(json.loads(self.rfile.read(length)))
                except Exception:
                    self.send_error(400, 'Browser submission rejected')
                    return
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        server = ThreadingHTTPServer((parts.hostname, parts.port), Handler)
        server.timeout = .5

        def deliveries():
            while not self.stop.is_set():
                try:
                    worked = self.deliver_one()
                except Exception as exc:
                    logger.warning('Browser callback retry error_type=%s', type(exc).__name__)
                    worked = False
                if not worked:
                    self.stop.wait(.5)

        delivery_thread = threading.Thread(target=deliveries, daemon=True)
        delivery_thread.start()
        logger.info('Browser service ready on %s; runtime model follows each originating conversation', self.config['submit_url'])
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                active = set()
                while not self.stop.is_set():
                    active = {future for future in active if not future.done()}
                    while len(active) < 2:
                        active.add(pool.submit(self.execute_one))
                    server.handle_request()
        finally:
            self.stop.set()
            server.server_close()
            delivery_thread.join(6)
            self.audit.emit('service_stopped', state='stopped')
