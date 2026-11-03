"""Immutable run admission and isolated, deadline-bound worker supervision."""
from __future__ import annotations

import atexit
import fcntl
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from config_loader import config_scope, export_config_environment
from workflow_policy import (
    BUILDER_EXCLUDED_TOOLS,
    WorkflowPolicyError,
    get_workflow_excluded_tools,
    validated_workflow_approval_tools,
)

from .catalog import CatalogService, configured_modes
from .processes import descendants, process_identity, same_process, stop_verified
from .recipes import RecipeService, document_hash
from .store import ACTIVE_STATUSES, BuilderError, BuilderStore
from .worker import DIAGNOSTIC_PREFIX, normalize_startup_diagnostic, startup_diagnostic

LOGGER = logging.getLogger(__name__)


class RunSupervisor:
    """Admit one run and retain ownership until every child has stopped."""

    def __init__(self, root: Path, store: BuilderStore, recipes: RecipeService,
                 catalog: CatalogService):
        self.root = root
        self.store = store
        self.recipes = recipes
        self.catalog = catalog
        self._processes: dict[str, subprocess.Popen] = {}
        self._discovery: subprocess.Popen | None = None
        self._startup_state: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._closed = False
        self._owner_lock = open(str(store.path) + '.server.lock', 'a+')
        os.chmod(str(store.path) + '.server.lock', 0o600)
        try:
            fcntl.flock(self._owner_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._owner_lock.close()
            raise BuilderError('Another workflow builder server owns this database', 409) from exc
        # A worker inherits its own flock across exec and outlives a crashed parent.
        # Never release its database slot until that lease and all recorded processes stop.
        active = self.store.active_run()
        if active:
            try:
                lease = self._worker_lease()
            except BuilderError:
                self.store.cancel(active['id'])
                threading.Thread(target=self._recover_orphan, args=(active['id'],), daemon=True).start()
            else:
                verified = self._cleanup_saved_processes(active['id'])
                lease.close()
                if verified:
                    self.store.finalize_worker(active['id'])
                else:
                    self.store.cancel(active['id'])
                    threading.Thread(target=self._recover_orphan, args=(active['id'],), daemon=True).start()
        self.store.prune()
        atexit.register(self.close)

    def _worker_lease(self):
        lease = open(str(self.store.path) + '.worker.lock', 'a+')
        os.fchmod(lease.fileno(), 0o600)
        try:
            fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lease.close()
            raise BuilderError('A workflow or tool discovery process is still active', 409) from exc
        return lease

    def _cleanup_saved_processes(self, run_id: str) -> bool:
        run = self.store.get_run(run_id, internal=True)
        known = self.store.worker_processes(run_id)
        identity = run.get('worker_identity') or next(iter(known.values()), None)
        return stop_verified(identity, known) if identity else True

    def _recover_orphan(self, run_id: str) -> None:
        grace = time.monotonic() + 5
        while not self._closed:
            try:
                lease = self._worker_lease()
            except BuilderError:
                if time.monotonic() >= grace:
                    identity = self.store.get_run(run_id, internal=True).get('worker_identity')
                    if identity and same_process(identity):
                        stop_verified(identity, self.store.worker_processes(run_id))
                time.sleep(.1)
                continue
            verified = self._cleanup_saved_processes(run_id)
            lease.close()
            if not verified:
                time.sleep(.1)
                continue
            self.store.finalize_worker(run_id, 'interrupted')
            self.store.event(run_id, {'type': 'worker_stopped', 'status': 'interrupted',
                                      'message': 'Previous worker stopped; inspect recovery references before rerunning'})
            return

    def prepare(self, body: dict) -> dict:
        mode = body.get('mode')
        if mode not in configured_modes(self.root):
            raise BuilderError('Choose a configured mode')
        source, workflow = self.recipes.read(body.get('source_id', ''))
        if not source['effective'] or not source['enabled']:
            raise BuilderError('Only an effective enabled published workflow can run')
        if body.get('hash') != source['hash']:
            raise BuilderError('Published recipe changed; reload it before running', 409)
        try:
            with config_scope(mode):
                diagnostics = self.recipes.validate(workflow, source['source_id'])
                excluded = get_workflow_excluded_tools(mode) | set(BUILDER_EXCLUDED_TOOLS)
        except WorkflowPolicyError as exc:
            raise BuilderError('Saved workflow tool policy must be repaired before execution', 503) from exc
        if diagnostics['errors']:
            raise BuilderError('Published workflow is not eligible for builder execution',
                               errors=diagnostics['errors'], warnings=diagnostics['warnings'])
        try:
            approved_tools = validated_workflow_approval_tools(workflow)
        except WorkflowPolicyError as exc:
            raise BuilderError('Recipe approval must be renewed before execution',
                               errors=[{'path': 'builder_unattended_approval', 'message': str(exc)}]) from exc
        query = body.get('query', '')
        if not isinstance(query, str) or len(query) > 10000:
            raise BuilderError('Query must be text of at most 10,000 characters')
        deadline = body.get('timeout_seconds', body.get('deadline', 900))
        if type(deadline) is not int or not 30 <= deadline <= 3600:
            raise BuilderError('Deadline must be an integer from 30 to 3600 seconds')
        stop_after = body.get('stop_after')
        count = len(workflow['steps'])
        if stop_after is not None and (type(stop_after) is not int or not 1 <= stop_after <= count):
            raise BuilderError('Run-through position must refer to an existing step')
        tools = {tool['name']: tool for tool in self.catalog.tools(mode)['tools']}
        effects = []
        for index, step in enumerate(workflow['steps'][:stop_after]):
            name = step['tool']
            if name in BUILDER_EXCLUDED_TOOLS or (name in excluded and step.get('required', True)):
                raise BuilderError(f'Tool {name} is excluded from managed workflows')
            metadata = tools.get(name, {})
            permissions = metadata.get('permissions', {})
            if metadata.get('background_required') is True:
                raise BuilderError(f'Tool {name} is background-only and excluded from managed workflows')
            if metadata.get('available') is False and step.get('required', True):
                raise BuilderError(f"Required tool {name} is unavailable: {metadata.get('reason', '')}")
            effects.append({'step': step['step'], 'index': index, 'tool': name,
                            'action': step.get('action', step.get('params', {}).get('action')),
                            'permissions': permissions,
                            'requires_approval': name not in approved_tools and permissions.get('auto_approve') is not True,
                            'unattended_authorized': name in approved_tools,
                            'description': metadata.get('description', 'Availability and permissions will be checked at run time'),
                            'model_use': bool(step.get('llm_prompt')
                                              or 'llm_decides' in str(step.get('condition', ''))
                                              or (isinstance(step.get('validation'), dict)
                                                  and step['validation'].get('type') in {'llm', 'hybrid'})),
                            'state_effects': self._state_effects(name, step)})
        document = {'workflow': workflow, 'source_id': source['source_id'], 'hash': source['hash'],
                    'recipe_hash': document_hash(workflow), 'workflow_id': workflow['id'],
                    'name': workflow.get('name', workflow['id']), 'mode': mode, 'query': query,
                    'stop_after': stop_after, 'partial': stop_after is not None and stop_after < count,
                    'timeout_seconds': deadline, 'effects': effects, 'surface': 'builder', 'draft': False}
        return {'confirmation_token': self.store.prepare(document), 'effects': effects,
                'expires_at': time.time() + 300, 'warnings': diagnostics['warnings'],
                'model_use': bool(workflow.get('success_speech_llm_prompt'))
                             or any(isinstance(value, dict) and value.get('extract') == 'short_title'
                                    for value in workflow.get('variables', {}).values()),
                'partial': document['partial'], 'timeout_seconds': deadline}

    @staticmethod
    def _state_effects(name: str, step: dict) -> list[str]:
        """Declared effect hints are intentionally conservative and never a dry run."""
        effects = []
        lowered = name.lower()
        for needle, label in (('canvas', 'Canvas pages'), ('stash', 'Stash files'),
                              ('alert', 'Alerts'), ('email', 'Email delivery'),
                              ('phone', 'Phone calls'), ('release_watch', 'Release acknowledgments'),
                              ('rss', 'RSS state'), ('radar', 'Radar ledgers'),
                              ('file', 'Filesystem'), ('ssh', 'Remote commands')):
            if needle in lowered:
                effects.append(label)
        action = str(step.get('action', step.get('params', {}).get('action', '')))
        if any(word in action for word in ('ack', 'mark', 'send', 'delete', 'write', 'save', 'update')):
            effects.append('State may be changed')
        return effects

    def start(self, body: dict) -> dict:
        if body.get('confirmed') is not True:
            raise BuilderError('Confirm the exact side-effect summary before running')
        key = body.get('idempotency_key')
        if not isinstance(key, str) or not 8 <= len(key) <= 160:
            raise BuilderError('An idempotency key of 8–160 characters is required')
        token = body.get('confirmation_token')
        if not isinstance(token, str):
            raise BuilderError('Run confirmation is required')
        with self._lock:
            if self._closed:
                raise BuilderError('Builder is shutting down', 503)
            with self.store.connect() as db:
                row = db.execute('SELECT id FROM runs WHERE idempotency_key=?', (key,)).fetchone()
            if row:
                return self.store.admit(token, key)[0]  # also verifies exact token binding
            if self._processes or self._discovery is not None:
                raise BuilderError('A workflow or tool discovery process is still active', 409)
            prepared = self.store.preparation(token)
            source = self.recipes.source(prepared['source_id'])
            if source['hash'] != prepared['hash'] or not source['effective']:
                raise BuilderError('Published recipe changed; review its effects again', 409)
            lease = self._worker_lease()
            try:
                run, created = self.store.admit(token, key)
                if created:
                    try:
                        child_env = export_config_environment(prepared['mode'])
                        child_env['JARVIS_JSON_MODE'] = '1'
                        process = subprocess.Popen(
                            [sys.executable, str(Path(__file__).with_name('worker.py')),
                             '--db', str(self.store.path), '--root', str(self.root), '--run', run['id'],
                             '--lease-fd', str(lease.fileno())],
                            cwd=self.root, env=child_env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                            encoding='utf-8', errors='replace', bufsize=1,
                            start_new_session=True, pass_fds=(lease.fileno(),),
                        )
                        self._processes[run['id']] = process
                        self._startup_state[run['id']] = {'ready': False, 'reported': False, 'protocol': False}
                        reader = threading.Thread(target=self._read_diagnostics,
                                                  args=(run['id'], process), daemon=True)
                        reader.start()
                        identity = process_identity(process.pid)
                        if identity:
                            self.store.set_worker_identity(run['id'], identity)
                        threading.Thread(target=self._watch, args=(run['id'], process, reader), daemon=True).start()
                    except (OSError, ValueError, sqlite3.Error) as exc:
                        launched = self._processes.pop(run['id'], None)
                        if launched is not None:
                            self._stop(launched)
                        diagnostic = startup_diagnostic(exc, 'bootstrap')
                        self._record_startup_error(run['id'], diagnostic)
                        self.store.finalize_worker(run['id'], 'failed')
                        raise BuilderError('Could not launch workflow worker', 503) from exc
                return self.store.get_run(run['id'])
            finally:
                lease.close()  # child retains the same locked open-file description

    def _record_startup_error(self, run_id: str, diagnostic: dict) -> None:
        """Persist and log only the safe projection, never arbitrary child stderr."""
        state = self._startup_state.setdefault(run_id, {'ready': False, 'reported': False, 'protocol': False})
        if state['reported']:
            return
        state['reported'] = True
        diagnostic = normalize_startup_diagnostic(diagnostic)
        run = self.store.get_run(run_id, internal=True)
        pending = run.get('result')
        output = pending.get('output') if isinstance(pending, dict) else None
        if not (isinstance(output, dict) and output.get('error_code') == 'worker_startup_failed'):
            self.store.event(run_id, diagnostic)
            self.store.finish_worker(run_id, 'failed', {
                'error': diagnostic['message'], 'error_code': 'worker_startup_failed',
                'startup': diagnostic,
            })
        LOGGER.error('Workflow builder run %s: %s', run_id, diagnostic['message'])

    def _read_diagnostics(self, run_id: str, process: subprocess.Popen) -> None:
        """Drain stderr; retain only structured diagnostics or safe Python error types."""
        stream = process.stderr
        if stream is None:
            return
        state = self._startup_state[run_id]
        try:
            while True:
                # A large or unterminated line cannot become an unbounded buffer.
                line = stream.readline(8192)
                if not line:
                    break
                if state['ready']:
                    continue
                if line.startswith(DIAGNOSTIC_PREFIX):
                    try:
                        payload = json.loads(line[len(DIAGNOSTIC_PREFIX):])
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(payload, dict):
                        continue
                    if payload.get('type') == 'worker_starting':
                        state['protocol'] = True
                    elif payload.get('type') == 'worker_ready':
                        state['ready'] = True
                    elif payload.get('type') == 'worker_startup_error':
                        self._record_startup_error(run_id, payload)
                    continue
                # Covers interpreter/import failures before the worker can emit
                # its own protocol. Traceback source lines and exception values
                # are discarded; only a bounded Python module identifier survives.
                if state.get('protocol'):
                    continue
                match = re.match(r'^(ModuleNotFoundError|ImportError|SyntaxError|IndentationError|FileNotFoundError|PermissionError|ValueError|RuntimeError|TypeError):', line)
                if match:
                    diagnostic = {'phase': 'bootstrap', 'exception_type': match.group(1)}
                    missing = re.match(r"^ModuleNotFoundError: No module named ['\"]([A-Za-z_][A-Za-z0-9_.]{0,160})['\"]", line)
                    if missing:
                        diagnostic['module'] = missing.group(1)
                    self._record_startup_error(run_id, diagnostic)
        finally:
            stream.close()

    @staticmethod
    def _stop(process: subprocess.Popen, known=None) -> bool:
        identity = process_identity(process.pid)
        if identity:
            verified = stop_verified(identity, known)
        else:
            verified = all(not same_process(item) for item in (known or {}).values())
            if not verified:
                for item in (known or {}).values():
                    if same_process(item):
                        stop_verified(item)
                verified = all(not same_process(item) for item in (known or {}).values())
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            return False
        return verified

    def _watch(self, run_id: str, process: subprocess.Popen, diagnostic_reader: threading.Thread | None = None) -> None:
        run = self.store.get_run(run_id, internal=True)
        deadline = time.monotonic() + run['timeout_seconds']
        terminal = None
        known = {}
        while process.poll() is None:
            identity = process_identity(process.pid)
            if identity:
                discovered = descendants(identity)
                fresh = {pid: child for pid, child in discovered.items() if known.get(pid) != child}
                if fresh:
                    self.store.record_processes(run_id, fresh)
                known.update(discovered)
            if self._closed or self.store.get_run(run_id)['cancel_requested']:
                terminal = 'interrupted' if self._closed else 'cancelled'
                break
            if time.monotonic() >= deadline:
                terminal = 'timed_out'
                self.store.cancel(run_id)
                break
            time.sleep(.1)
        if terminal:
            # First let ToolExecutor stop its own separate-session tool children.
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        verified = self._stop(process, known)
        if not verified:
            self.store.cancel(run_id)
            self.store.event(run_id, {'type': 'cleanup_unverified',
                                      'message': 'Process cleanup is unverified; new runs remain blocked'})
            return
        if diagnostic_reader is not None:
            diagnostic_reader.join(timeout=1)
        current = self.store.get_run(run_id, internal=True)
        pending = current.get('result')
        if terminal is None and not (isinstance(pending, dict) and '_pending_status' in pending):
            state = self._startup_state.get(run_id, {})
            if not state.get('ready') and current['status'] in ACTIVE_STATUSES:
                diagnostic = normalize_startup_diagnostic({'phase': 'startup', 'exception_type': 'WorkerExit',
                                                            'exit_code': process.returncode})
                self._record_startup_error(run_id, diagnostic)
                terminal = 'failed'
        self.store.finalize_worker(run_id, terminal)
        self.store.event(run_id, {'type': 'worker_stopped', 'status': self.store.get_run(run_id)['status']})
        with self._lock:
            self._processes.pop(run_id, None)
            self._startup_state.pop(run_id, None)

    def refresh_catalog(self, mode: str) -> dict:
        if mode not in configured_modes(self.root):
            raise BuilderError('Mode is not configured')
        with self._lock:
            if self._closed or self._processes or self._discovery is not None or self.store.active_run():
                raise BuilderError('Wait for the active workflow before refreshing tools', 409)
            lease = self._worker_lease()
            try:
                child = subprocess.Popen(
                    [sys.executable, str(Path(__file__).with_name('worker.py')),
                     '--db', str(self.store.path), '--root', str(self.root), '--refresh', mode,
                     '--lease-fd', str(lease.fileno())],
                    cwd=self.root, env=export_config_environment(mode), stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                    pass_fds=(lease.fileno(),),
                )
                self._discovery = child
            finally:
                lease.close()
        # No lifecycle lock is held while discovery waits; shutdown can always stop it.
        known = {}
        until = time.monotonic() + 90
        try:
            while child.poll() is None and not self._closed and time.monotonic() < until:
                identity = process_identity(child.pid)
                if identity:
                    known.update(descendants(identity))
                time.sleep(.1)
            timed_out = child.poll() is None and not self._closed
            verified = self._stop(child, known)
            if not verified:
                raise BuilderError('Tool discovery cleanup could not be verified', 503)
            if timed_out:
                raise BuilderError('Tool discovery timed out; cached schemas remain available', 504)
            if child.returncode != 0 or self._closed:
                raise BuilderError('Live tool discovery stopped; cached schemas remain available', 503)
            return self.catalog.tools(mode)
        finally:
            with self._lock:
                self._discovery = None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            children = list(self._processes.items())
            discovery = self._discovery
        for run_id, process in children:
            self.store.cancel(run_id)
            identity = process_identity(process.pid)
            known = descendants(identity) if identity else {}
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            if self._stop(process, known):
                self.store.finalize_worker(run_id, 'interrupted')
        if discovery is not None:
            self._stop(discovery)
        self._owner_lock.close()
