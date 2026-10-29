"""Supervised worker primitive; adapters are explicitly supplied by trusted code.

No tools are imported/discovered here, and no services start on import.
The separately supervised CLI registers reviewed production adapters explicitly.
"""

from __future__ import annotations

import logging
import math
import os
import random
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from lib.config_loader import config_scope
from lib.prompt_guard_observer import is_prompt_guard_rejection, review_tool_result

from .models import (
    RESUMABLE_REMOTE_ADAPTERS,
    Claim,
    LostLease,
    TaskError,
    identifier,
    recovery_details,
    remote_checkpoint,
    validate_remote_checkpoint,
)
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


class KnownRemoteCancelled(TaskError):
    """A trusted observer verified native cancellation of its saved remote run."""

    def __init__(self, run_id: str):
        super().__init__('Provider confirmed cancellation')
        self.run_id = identifier(run_id, 'cancelled remote run ID')


class RemoteObservationPaused(TaskError):
    """Observation may be reacquired without repeating the paid submission."""


class KnownStopped(TaskError):
    """Local execution is proven stopped, including after observation expires."""


class UncertainOutcome(TaskError):
    """Trusted adapter explanation; never use raw provider exception text here."""

    def __init__(self, reason: str, *, result=None):
        super().__init__(reason)
        self.result = result


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
    remote_submission_started: bool = False
    pending_tool_logs: list[tuple[Callable[..., None], dict]] = field(default_factory=list, repr=False)
    unreviewed_tool_result: dict | None = field(default=None, repr=False)

    def stage_tool_log(self, writer: Callable[..., None], entry: dict) -> None:
        """Hold this invocation's diagnostics in memory until its result is reviewed."""
        self.pending_tool_logs.append((writer, entry))

    def flush_tool_logs(self, result: dict) -> None:
        """Write reviewed diagnostics without changing the operation's outcome."""
        entries, self.pending_tool_logs = self.pending_tool_logs, []
        for writer, entry in entries:
            try:
                writer(**{**entry, 'result': result})
            except Exception:
                try:
                    logger.warning('Task tool log write failed job=%s; preserving outcome', self.claim.job_id)
                except Exception:
                    pass

    def record_process_stop(self):
        # Called only after the supervisor verifies death of the whole group.
        self.local_process_stopped = True

    def record_process_start(self, pid, phase):
        # Set before progress/checkpoint: a racing stop cannot erase evidence
        # that a child capable of submitting remote work was launched.
        self.local_process_started = True
        self.progress({'phase': phase, 'process_id': pid, 'process_group': pid})

    def checkpoint(self, *, allow_cancel=False):
        if self.lost.is_set() or self.store.clock() >= self.claim.job["deadline"]:
            raise LostLease("Worker ownership or observation deadline ended")
        if self.stop.is_set():
            raise Interrupted("Worker is stopping")
        # Poll the durable fence, including operator cancellation. Heartbeats
        # alone could let a child run for seconds after ownership was revoked.
        with self.store._connection() as conn:
            row = self.store._active(conn, self.claim)
            if row['cancel_requested'] and not allow_cancel:
                raise CancellationRequested("Operator requested cancellation")

    @property
    def remote_checkpoint(self) -> dict[str, str] | None:
        return remote_checkpoint(self.claim.job['adapter'], self.claim.job.get('progress'))

    def persist_remote_checkpoint(self, checkpoint: dict):
        """Save submission identity even if shutdown/cancellation raced its receipt."""
        checkpoint = validate_remote_checkpoint(checkpoint)
        try:
            progress = self.store.checkpoint_remote(self.claim, checkpoint)
        except LostLease:
            # A late submission receipt remains recovery evidence, never a new
            # lease or authorization to continue a fenced attempt.
            self.store.reconcile()
            self.store.retain_uncertain_result(self.claim, {'data': {'run_id': checkpoint['run_id']}})
            raise
        self.claim.job['progress'] = progress

    def wait(self, seconds: float, *, allow_cancel=False):
        """Wait between short HTTP observations while checking durable fences."""
        if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                or not math.isfinite(seconds) or not 0 <= seconds <= 300):
            raise TaskError('Observer wait must be between zero and 300 seconds')
        until = time.monotonic() + seconds
        while True:
            self.checkpoint(allow_cancel=allow_cancel)
            remaining = until - time.monotonic()
            if remaining <= 0:
                return
            self.stop.wait(min(0.25, remaining))

    def progress(self, value: dict, *, allow_cancel=False):
        try:
            self.checkpoint(allow_cancel=allow_cancel)
            self.store.progress(self.claim, value)
        except LostLease:
            # Only recovery metadata can survive expiry; normal progress still
            # loses its lease, and this never authorizes further execution.
            recovery = recovery_details(value.get('recovery'))
            if recovery:
                self.store.reconcile()
                self.store.retain_uncertain_result(self.claim, {'data': recovery})
            raise


Adapter = Callable[[ExecutionContext], dict]


@dataclass(frozen=True)
class ResumableRemoteAdapter:
    """One paid start followed by repeatable observation of an immutable handle.

    Trusted ``observe`` code may read/collect or confirm cancellation of that
    handle. It must never call the provider's submission entry point. Registration
    is restricted to reviewed adapter IDs independently of manifest metadata.
    """

    start: Callable[[ExecutionContext], dict]
    observe: Callable[[ExecutionContext, dict[str, str]], dict]

    def __call__(self, context: ExecutionContext) -> dict:
        if context.claim.job['adapter'] not in RESUMABLE_REMOTE_ADAPTERS:
            raise KnownFailure({'ok': False, 'error': 'Unreviewed remote observer adapter'})
        try:
            saved = context.remote_checkpoint
            if saved is None:
                context.checkpoint()
                context.remote_submission_started = True
                saved = validate_remote_checkpoint(self.start(context))
                context.persist_remote_checkpoint(saved)
            else:
                # A replacement observer must reach its native abort/read path
                # when cancellation was requested while no worker was present.
                context.checkpoint(allow_cancel=True)
            return self.observe(context, saved)
        except Interrupted:
            if context.remote_checkpoint is None:
                raise
            context.store.pause_remote_observation(context.claim)
            raise RemoteObservationPaused() from None


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
        if any(isinstance(adapter, ResumableRemoteAdapter) and name not in RESUMABLE_REMOTE_ADAPTERS
               for name, adapter in adapters.items()):
            raise TaskError('Remote observer recovery requires a reviewed adapter ID')
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
            if any(isinstance(adapter, ResumableRemoteAdapter) and name not in RESUMABLE_REMOTE_ADAPTERS
                   for name, adapter in loaded.items()):
                raise TaskError('Remote observer recovery requires a reviewed adapter ID')
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

    def _attention(self, claim, reason, *, result=None):
        try:
            self.store.attention(claim, reason, result=result)
            logger.warning('Task needs attention job=%s reason=%s; review Manage tasks', claim.job_id, reason)
        except LostLease:
            # Recovery metadata may enrich this exact expired attempt, but cannot
            # restore its execution lease or supersede operator/disposal fences.
            self.store.reconcile()
            self.store.retain_uncertain_result(claim, result)
            logger.warning('Task ownership lost job=%s; execution will not be retried', claim.job_id)

    def _recover_execution(self, claim, context, *, result=None):
        from .local_contract import LOCAL_ADAPTERS

        # Only a neutral, already-reviewed rejection may survive this race.
        # Raw late output cannot replace fenced recovery evidence.
        withheld = result if is_prompt_guard_rejection(result) else None
        if context and context.local_process_stopped and claim.job['adapter'] in LOCAL_ADAPTERS:
            try:
                if withheld is None:
                    self.store.record_local_stop(claim)
                else:
                    self.store.record_local_stop(claim, result=withheld)
                return
            except LostLease:
                pass  # Disposal/operator decisions still supersede this attempt.
        self.store.reconcile()
        if withheld is not None:
            self.store.retain_uncertain_result(claim, withheld)

    def _review_result(self, claim, result, context, *, completed=False):
        """Screen once before persistence, preserving execution certainty separately.

        Supervised skills retain their pre-truncation result only in runtime
        context. A clean/unknown scan leaves the adapter's bounded result and
        original diagnostics unchanged. No scanner I/O holds a store transaction.
        """
        source = context.unreviewed_tool_result if context is not None else None
        source = source if isinstance(source, dict) else result
        try:
            reviewed = review_tool_result(
                claim.job['admission']['tool'], source,
                args=claim.job['admission']['arguments'], mode=claim.job['mode'],
                config_overrides=self.deployment_overrides,
            )
        except Exception:
            reviewed = source
            try:
                logger.warning('Task result screening unavailable job=%s; preserving outcome', claim.job_id)
            except Exception:
                pass
        withheld = is_prompt_guard_rejection(reviewed)
        if withheld and completed:
            # An adapter's successful return proves completion even when its
            # original result did not need an explicit completion field.
            reviewed = {**reviewed, 'completion': 'completed'}
        if context is not None:
            context.flush_tool_logs(reviewed if withheld else source)
            context.unreviewed_tool_result = None
        return reviewed if withheld else result

    @staticmethod
    def _before_remote_submission(adapter: Adapter, context: ExecutionContext | None) -> bool:
        """Only reviewed starters can attest that no provider POST was invoked."""
        return (isinstance(adapter, ResumableRemoteAdapter) and context is not None
                and context.remote_checkpoint is None and not context.remote_submission_started)

    def run_once(self, stop: threading.Event | None = None) -> bool:
        """Claim at most one released job. A stop never admits additional work."""
        stop = stop if stop is not None else threading.Event()
        if stop.is_set():
            return False
        self._refresh_adapters()
        self._presence()
        with self._adapter_lock:
            adapters = dict(self.adapters)
        resumable = {name for name, adapter in adapters.items()
                     if isinstance(adapter, ResumableRemoteAdapter)}
        claim = self.store.claim(self.owner, set(adapters), lease_seconds=self.lease_seconds,
                                 resumable_adapters=resumable)
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
        result = None
        try:
            with config_scope(claim.job["mode"], self.deployment_overrides) as snapshot:
                # Do not hydrate os.environ or carry another mode's inherited
                # keys/overrides into a child. The adapter must use this environment.
                context = ExecutionContext(
                    claim, self.store, stop, lost,
                    _child_environment(claim.job["mode"], snapshot),
                    dict(snapshot.overrides),
                )
                context.checkpoint(allow_cancel=context.remote_checkpoint is not None)
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
                    result = self._review_result(claim, result, context, completed=True)
                    withheld = is_prompt_guard_rejection(result)
                    self.store.finish(claim, result, succeeded=not withheld)
                    logger.info('Task %s job=%s; result saved for Web delivery',
                                'content withheld' if withheld else 'succeeded', claim.job_id)
        except RemoteObservationPaused:
            logger.info('Remote observer paused job=%s; saved native run will be observed after restart', claim.job_id)
        except KnownRemoteCancelled as exc:
            saved = context.remote_checkpoint if context else None
            if not saved or saved['run_id'] != exc.run_id:
                self._attention(claim, 'Remote cancellation did not match the saved native run')
            else:
                try:
                    self.store.acknowledge_cancel(claim, 'Provider confirmed cancellation of saved remote run')
                    logger.info('Remote task cancelled job=%s; provider termination confirmed', claim.job_id)
                except LostLease:
                    self.store.reconcile()
                except TaskError:
                    self._attention(claim, 'Native cancellation was not requested for this execution')
        except KnownStopped:
            try:
                self.store.record_local_stop(claim)
                logger.info('Task stopped job=%s; verified local stop released capacity', claim.job_id)
            except LostLease:
                self.store.reconcile()
        except KnownCancelled:
            if claim.job['adapter'] in resumable and context and context.remote_checkpoint:
                self._attention(claim, 'Local termination is not native remote cancellation evidence')
            else:
                try:
                    self.store.acknowledge_cancel(claim, "Local child and process-group termination verified")
                    logger.info('Task cancelled job=%s; local process group stopped', claim.job_id)
                except LostLease:
                    try:
                        self.store.record_local_stop(claim)
                    except LostLease:
                        self.store.reconcile()
        except CancellationRequested:
            before_remote_submit = self._before_remote_submission(adapters[claim.job['adapter']], context)
            if not adapter_started or before_remote_submit:
                evidence = 'Provider submission was never invoked' if before_remote_submit else 'Adapter was never invoked'
                self.store.acknowledge_cancel(claim, evidence)
                logger.info('Task cancelled job=%s before execution', claim.job_id)
            else:
                self._attention(claim, "Cancellation needs adapter termination evidence")
        except KnownFailure as exc:
            try:
                result = self._review_result(claim, exc.result, context)
                self.store.finish(claim, result, succeeded=False)
                logger.warning('Task failed job=%s; result saved for Web delivery', claim.job_id)
            except LostLease:
                self._recover_execution(claim, context, result=result)
            except Exception as failure:
                self._attention(
                    claim,
                    f"Failure persistence error ({type(failure).__name__}); outcome needs review",
                )
        except LostLease:
            self._recover_execution(claim, context, result=result)
            logger.warning('Task ownership lost job=%s; execution will not be retried', claim.job_id)
        except Interrupted:
            if context is not None and context.remote_checkpoint is not None:
                try:
                    self.store.pause_remote_observation(claim)
                    logger.info('Remote observer paused before execution job=%s; saved native run retained', claim.job_id)
                except LostLease:
                    self.store.reconcile()
            elif self._before_remote_submission(adapters[claim.job['adapter']], context):
                try:
                    self.store.finish(claim, {
                        'ok': False, 'completion': 'rejected',
                        'error': 'Worker stopped during preparation before provider submission',
                        'speech': 'The background task stopped before provider submission. No remote run was started.',
                    }, succeeded=False)
                    logger.info('Task stopped before provider submission job=%s; no native run was started', claim.job_id)
                except LostLease:
                    self.store.reconcile()
            elif not adapter_started:
                try:
                    self.store.finish(claim, {'ok': False, 'error': 'Worker stopped before execution'}, succeeded=False)
                except LostLease:
                    self.store.reconcile()
            else:
                self._attention(claim, "Worker stopped during execution; outcome needs review")
        except UncertainOutcome as exc:
            result = self._review_result(claim, exc.result, context)
            self._attention(claim, str(exc), result=result)
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
