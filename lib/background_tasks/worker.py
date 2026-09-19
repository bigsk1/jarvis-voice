"""Supervised worker primitive; adapters are explicitly supplied by trusted code.

No tools are imported/discovered here, and no services start on import.
The separately supervised CLI registers reviewed production adapters explicitly.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from lib.config_loader import config_scope

from .models import Claim, LostLease, TaskError
from .store import TaskStore

logger = logging.getLogger(__name__)


def _child_environment(mode: str, snapshot) -> dict[str, str]:
    """Build a dual-mode-safe child env without promoting secrets to overrides.

    Mode file values stay ordinary ``KEY=value`` entries. Only reviewed
    request/deployment overrides are stamped as ``JARVIS_OVERRIDE_*``.
    Parent overrides and session/conversation identity are dropped so a
    leftover Web UI or other-mode value cannot outrank the job's mode file.
    """
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in snapshot.mode_keys
        and not key.startswith("JARVIS_OVERRIDE_")
        and key not in {"JARVIS_SESSION_ID", "JARVIS_WEB_CONVERSATION_ID"}
    }
    environment.update(snapshot.merged())
    environment["JARVIS_MODE"] = mode
    for key, value in snapshot.overrides.items():
        if value is None:
            continue
        name, text = str(key), str(value)
        environment[name] = text
        if not name.startswith("JARVIS_OVERRIDE_"):
            environment[f"JARVIS_OVERRIDE_{name}"] = text
    return environment


class Interrupted(TaskError):
    """Cooperative stop; the adapter's effects may already have happened."""


class KnownFailure(TaskError):
    """An adapter has evidence of a completed unsuccessful operation."""

    def __init__(self, result: dict):
        super().__init__("Adapter reported a known failure")
        self.result = result


class CancellationRequested(TaskError):
    """A request to stop, not evidence that any subprocess has stopped."""


class KnownCancelled(TaskError):
    """Adapter verified that its entire local execution has stopped."""


class KnownStopped(TaskError):
    """Local execution is proven stopped, including after observation expires."""


class UncertainOutcome(TaskError):
    """Trusted adapter explanation; never use raw provider exception text here."""


class AwaitingCallback:
    """A prebound durable callback owns completion; never interpret as success."""


@dataclass
class ExecutionContext:
    claim: Claim
    store: TaskStore
    stop: threading.Event
    lost: threading.Event
    environment: dict[str, str]
    config_values: dict[str, str] = field(default_factory=dict)
    local_execution: dict = field(default_factory=dict)
    local_process_started: bool = False
    local_process_stopped: bool = False

    def record_process_stop(self):
        # Called only after the supervisor verifies death of the whole group.
        self.local_process_stopped = True

    def record_process_start(self, pid, phase):
        # Set before progress/checkpoint: a racing stop cannot erase evidence
        # that a child capable of submitting remote work was launched.
        self.local_process_started = True
        self.progress({'phase': phase, 'process_id': pid, 'process_group': pid})

    def checkpoint(self):
        if self.lost.is_set() or self.store.clock() >= self.claim.job["deadline"]:
            raise LostLease("Worker ownership or observation deadline ended")
        if self.stop.is_set():
            raise Interrupted("Worker is stopping")
        # Poll the durable fence, including operator cancellation. Heartbeats
        # alone could let a child run for seconds after ownership was revoked.
        with self.store._connection() as conn:
            row = self.store._active(conn, self.claim)
            if row['cancel_requested']:
                raise CancellationRequested("Operator requested cancellation")

    def progress(self, value: dict):
        self.checkpoint()
        self.store.progress(self.claim, value)


Adapter = Callable[[ExecutionContext], dict]


class TaskWorker:
    def __init__(
        self,
        store: TaskStore,
        adapters: Mapping[str, Adapter],
        *,
        owner: str | None = None,
        lease_seconds: float = 30,
        heartbeat_seconds: float = 5,
        poll_seconds: float = 1,
        deployment_overrides: dict | None = None,
        adapter_loader=None,
    ):
        store._ttl(lease_seconds)
        if not 0 < heartbeat_seconds < lease_seconds / 2 or not 0 < poll_seconds <= 60:
            raise TaskError("Heartbeat must be below half the lease; poll interval must be bounded")
        if any(not callable(adapter) for adapter in adapters.values()):
            raise TaskError("Adapters must be trusted callables")
        self.store = store
        self.adapters = dict(adapters)
        self.owner = owner or uuid.uuid4().hex
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.poll_seconds = poll_seconds
        self.deployment_overrides = dict(deployment_overrides or {})
        self.adapter_loader = adapter_loader
        self._adapter_lock = threading.RLock()

    def _refresh_adapters(self):
        """Add newly provisioned trusted adapters without restarting the worker."""
        if self.adapter_loader is None:
            return
        with self._adapter_lock:
            loaded = dict(self.adapter_loader())
            if any(not callable(adapter) for adapter in loaded.values()):
                raise TaskError("Adapters must be trusted callables")
            added = sorted(set(loaded) - set(self.adapters))
            if added:
                # Never remove a live adapter: an accepted job may still depend on it.
                # Revoked/disabled policy is rechecked inside the adapter before submit.
                self.adapters.update(loaded)
                logger.info('Task worker loaded newly provisioned adapters=%s', ', '.join(added))
                self.store.events.emit('worker_adapters_added', component='worker', owner=self.owner,
                                       adapters=added)

    def _presence(self, *, draining=False):
        with self._adapter_lock:
            adapters = set(self.adapters)
        self.store.touch_worker(
            self.owner, adapters, lease_seconds=self.lease_seconds, draining=draining
        )

    def _heartbeat(self, claim, done, lost, stop):
        while not done.wait(self.heartbeat_seconds):
            try:
                self.store.renew(claim, lease_seconds=self.lease_seconds)
                self._presence(draining=stop.is_set())
            except Exception as exc:
                lost.set()
                self.store.events.emit('heartbeat_failed', component='worker', level='ERROR',
                                       job=claim.job, error_type=type(exc).__name__)
                logger.warning(
                    "Task heartbeat lost job=%s error_type=%s", claim.job_id, type(exc).__name__
                )
                return

    def _attention(self, claim, reason):
        try:
            self.store.attention(claim, reason)
            logger.warning('Task needs attention job=%s reason=%s; review Manage tasks', claim.job_id, reason)
        except LostLease:
            # An expiry racing adapter failure must not write through the fence.
            self.store.reconcile()
            logger.warning('Task ownership lost job=%s; execution will not be retried', claim.job_id)

    def _recover_execution(self, claim, context):
        from .local_contract import LOCAL_ADAPTERS

        if context and context.local_process_stopped and claim.job['adapter'] in LOCAL_ADAPTERS:
            try:
                self.store.record_local_stop(claim)
                return
            except LostLease:
                pass  # Disposal/operator decisions still supersede this attempt.
        self.store.reconcile()

    def run_once(self, stop: threading.Event | None = None) -> bool:
        """Claim at most one released job. A stop never admits additional work."""
        stop = stop if stop is not None else threading.Event()
        if stop.is_set():
            return False
        self._refresh_adapters()
        self._presence()
        with self._adapter_lock:
            adapters = dict(self.adapters)
        claim = self.store.claim(self.owner, set(adapters), lease_seconds=self.lease_seconds)
        if claim is None:
            return False
        started_at = time.monotonic()
        done, lost = threading.Event(), threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat,
            args=(claim, done, lost, stop),
            name=f"task-heartbeat-{claim.job_id}",
            daemon=True,
        )
        heartbeat.start()
        adapter_started = False
        context = None
        try:
            with config_scope(claim.job["mode"], self.deployment_overrides) as snapshot:
                # Do not hydrate os.environ or carry another mode's inherited
                # keys/overrides into a child. The adapter must use this environment.
                context = ExecutionContext(
                    claim, self.store, stop, lost,
                    _child_environment(claim.job["mode"], snapshot),
                    dict(snapshot.overrides),
                )
                context.checkpoint()
                self.store.running(claim)
                self.store.events.emit('job_started', component='worker', job=claim.job, state='running',
                                       queue_ms=round(max(0, self.store.clock() - claim.job['created_at']) * 1000))
                logger.info('Task started job=%s tool=%s mode=%s',
                            claim.job_id, claim.job['admission']['tool'], claim.job['mode'])
                adapter_started = True
                result = adapters[claim.job["adapter"]](context)
                # A completed adapter result remains useful if shutdown raced its
                # return. finish() still checks the execution lease and deadline.
                if isinstance(result, AwaitingCallback):
                    logger.info('Task submitted job=%s; awaiting authenticated callback', claim.job_id)
                else:
                    self.store.finish(claim, result)
                    logger.info('Task succeeded job=%s; result saved for Web delivery', claim.job_id)
        except KnownStopped:
            try:
                self.store.record_local_stop(claim)
                logger.info('Task stopped job=%s; verified local stop released capacity', claim.job_id)
            except LostLease:
                self.store.reconcile()
        except KnownCancelled:
            try:
                self.store.acknowledge_cancel(claim, "Local child and process-group termination verified")
                logger.info('Task cancelled job=%s; local process group stopped', claim.job_id)
            except LostLease:
                try:
                    self.store.record_local_stop(claim)
                except LostLease:
                    self.store.reconcile()
        except CancellationRequested:
            if not adapter_started:
                self.store.acknowledge_cancel(claim, "Adapter was never invoked")
                logger.info('Task cancelled job=%s before execution', claim.job_id)
            else:
                self._attention(claim, "Cancellation needs adapter termination evidence")
        except KnownFailure as exc:
            try:
                self.store.finish(claim, exc.result, succeeded=False)
                logger.warning('Task failed job=%s; result saved for Web delivery', claim.job_id)
            except LostLease:
                self._recover_execution(claim, context)
            except Exception as failure:
                self._attention(
                    claim,
                    f"Failure persistence error ({type(failure).__name__}); outcome needs review",
                )
        except LostLease:
            self._recover_execution(claim, context)
            logger.warning('Task ownership lost job=%s; execution will not be retried', claim.job_id)
        except Interrupted:
            if not adapter_started:
                try:
                    self.store.finish(claim, {'ok': False, 'error': 'Worker stopped before execution'}, succeeded=False)
                except LostLease:
                    self.store.reconcile()
            else:
                self._attention(claim, "Worker stopped during execution; outcome needs review")
        except UncertainOutcome as exc:
            self._attention(claim, str(exc))
        except Exception as exc:
            # Do not copy arbitrary exception text (which may contain credentials).
            self.store.events.emit('execution_error', component='worker', level='ERROR',
                                   job=claim.job, error_type=type(exc).__name__)
            self._attention(
                claim,
                f"Adapter/result persistence error ({type(exc).__name__}); outcome needs review",
            )
        finally:
            done.set()
            heartbeat.join(timeout=6)
            try:
                outcome = self.store.get(claim.job_id)
                self.store.events.emit('job_outcome', component='worker', job=outcome,
                    level='INFO' if outcome['state'] in {'succeeded', 'cancelled'} else 'WARNING',
                    duration_ms=round((time.monotonic() - started_at) * 1000))
            except Exception as exc:
                self.store.events.emit('outcome_unavailable', component='worker', level='ERROR',
                                       job=claim.job, error_type=type(exc).__name__)
        return True

    def run_forever(self, stop: threading.Event):
        """Startup reconciliation plus polling; heartbeat ownership is not a PID file."""
        try:
            self.store.reconcile()
            self._presence()
            self.store.events.emit('worker_ready', component='worker', owner=self.owner)
            logger.info('Task worker ready; serves cloud and local jobs; adapters=%s',
                        ', '.join(sorted(self.adapters)))
            logger.info('Watching for released tasks. Settings → Tools controls new background admissions.')
            previous_preferences = None
            with ThreadPoolExecutor(max_workers=32, thread_name_prefix='background-job') as pool:
                active = set()
                try:
                    while not stop.is_set():
                        self._refresh_adapters()
                        self._presence()
                        try:
                            from lib.webhook_integrations.service import IntegrationService
                            IntegrationService(self.store).drain()
                        except Exception as exc:
                            self.store.events.emit('callback_drain_failed', component='worker', level='ERROR',
                                                   error_type=type(exc).__name__, throttle=True)
                        finished = {future for future in active if future.done()}
                        for future in finished:
                            future.result()
                        active -= finished
                        settings = self.store.settings()
                        preferences = (settings['background_enabled'], tuple(sorted(settings['background_tools'])))
                        if preferences != previous_preferences:
                            logger.info('New background tasks: %s; saved tools=%s. Accepted jobs continue draining.',
                                        'enabled' if preferences[0] else 'disabled', ', '.join(preferences[1]) or 'none')
                            previous_preferences = preferences
                        available = settings['max_running'] - len(active)
                        for _ in range(max(0, available)):
                            active.add(pool.submit(self.run_once, stop))
                        stop.wait(self.poll_seconds * random.uniform(0.9, 1.1))
                finally:
                    # A failed scheduler must stop active children before the
                    # pool joins; otherwise it can advertise health while stuck.
                    stop.set()
                    self.store.events.emit('worker_stopping', component='worker', owner=self.owner)
                    logger.info('Task worker stopping; waiting for active execution supervision to finish')
                    self._presence(draining=True)
        except Exception as exc:
            self.store.events.emit('worker_error', component='worker', level='ERROR',
                                   owner=self.owner, error_type=type(exc).__name__)
            raise
        finally:
            self._presence(draining=True)
            self.store.events.emit('worker_stopped', component='worker', owner=self.owner)
            logger.info('Task worker stopped')
