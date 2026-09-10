"""Conversation-owned Web runs, independent of transient Socket.IO connections.

One Web server process owns execution. Persisted unfinished runs from a previous
process are observations of interrupted work, never a queue to replay.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from weakref import WeakValueDictionary

from filelock import Timeout

from .conversation_store import ConversationBusyError

logger = logging.getLogger(__name__)


class ChatRuns:
    def __init__(self, get_store, emit):
        self.get_store = get_store
        self.emit = emit
        self.owner = str(uuid.uuid4())
        self.lock = threading.RLock()
        self._conversation_locks = WeakValueDictionary()
        self._changing_mode = False
        self.active = {}
        self.leases = {}
        self.unsaved = OrderedDict()
        self.feedback = OrderedDict()
        self.feedback_revision = 0

    @staticmethod
    def public(run):
        return {key: value for key, value in (run or {}).items() if key != 'owner'}

    def conversation_lock(self, conversation_id):
        """Order one thread's snapshot/events without blocking other threads."""
        with self.lock:
            lock = self._conversation_locks.get(conversation_id)
            if lock is None:
                lock = threading.RLock()
                self._conversation_locks[conversation_id] = lock
            return lock

    @contextmanager
    def mode_change(self, mode=None):
        """Reserve the mode transition; never hold the state mutex during I/O."""
        with self.lock:
            self.check_mode(mode)
            self._changing_mode = True
            can_reset = not self.active
        try:
            yield can_reset
        finally:
            with self.lock:
                self._changing_mode = False

    def _persist_outcome(self, conversation_id, run):
        saved = self.get_store().update_run(
            conversation_id, run['message_id'], recover_owner=self.owner,
            status=run['status'], error=run.get('error', ''),
            finished_at=run['finished_at'], status_text='',
        )
        if not saved or any(saved.get(key) != run.get(key) for key in ('message_id', 'status', 'finished_at')):
            raise ValueError('The saved task outcome did not match its execution owner')
        self.unsaved.pop(conversation_id, None)
        lease = self.leases.pop(conversation_id, None)
        if lease:
            lease.release()

    def snapshot(self, conversation_id):
        """Caller holds the conversation lock through room join and delivery."""
        with self.conversation_lock(conversation_id):
            store = self.get_store()
            conversation = store.get_conversation(conversation_id, reconcile=False)
            if not conversation:
                return None
            run = conversation.get('run')
            unsaved = self.unsaved.get(conversation_id)
            if unsaved and run and unsaved['message_id'] == run['message_id']:
                try:
                    self._persist_outcome(conversation_id, unsaved)
                    conversation = store.get_conversation(conversation_id, reconcile=False)
                    run = conversation.get('run')
                except (OSError, ValueError):
                    logger.exception('Could not persist the recovered Web task outcome')
            if run and conversation_id not in self.active and conversation_id not in self.unsaved:
                conversation = store.get_conversation(conversation_id)
                run = conversation.get('run')
            current = self.active.get(conversation_id) or self.unsaved.get(conversation_id)
            if current and run and current['message_id'] == run['message_id']:
                run = current
            if run:
                conversation['run'] = self.public(run)
            with self.lock:
                feedback = self.feedback.get(conversation_id)
            if (feedback
                    and any((item.get('data') or {}).get('_web_message_id') == feedback['data'].get('message_id')
                            for item in conversation['messages'] if item['role'] == 'assistant')):
                conversation['feedback'] = feedback
            return conversation

    def claim(self, conversation_id, message_id, mode, *, message=None, data=None,
              kind='chat', parent_message_id=None):
        with self.conversation_lock(conversation_id):
            # Reconcile BEFORE acquiring our own lease: probing a self-held OS
            # lock cannot distinguish it from another live execution owner.
            conversation = self.snapshot(conversation_id)
            if conversation and any((item.get('data') or {}).get('_request_id') == message_id
                                    for item in conversation['messages']):
                return False
            if conversation_id in self.unsaved:
                raise ConversationBusyError('The previous task outcome could not be saved. Restore storage before sending again.')
            lease = self.get_store().run_lease(conversation_id)
            try:
                lease.acquire()
            except Timeout as exc:
                raise ConversationBusyError('This conversation has a running task. Stop it and wait first.') from exc
            run = {
                'message_id': message_id, 'conversation_id': conversation_id,
                'mode': mode, 'kind': kind, 'status': 'running', 'owner': self.owner,
                'started_at': time.time(), 'status_text': 'Working…',
            }
            if parent_message_id:
                run['parent_message_id'] = parent_message_id
            reserved = False
            try:
                with self.lock:
                    self.check_mode(mode)
                    self.active[conversation_id] = run
                    reserved = True
                claimed = self.get_store().claim_run(conversation_id, run, message=message, data=data)
                if claimed:
                    self.leases[conversation_id] = lease
                return claimed
            except (OSError, ValueError):
                try:
                    self.get_store().update_run(conversation_id, message_id, status='failed',
                                                finished_at=time.time(),
                                                error='The request was saved, but its worker could not be started. It was not retried.')
                except (OSError, ValueError):
                    logger.exception('Could not persist failed Web admission')
                raise
            finally:
                if conversation_id not in self.leases:
                    if reserved:
                        with self.lock:
                            self.active.pop(conversation_id, None)
                    lease.release()

    def check_mode(self, mode):
        """The existing MCP registry is shared and is recreated on mode changes."""
        with self.lock:
            if self._changing_mode:
                raise ConversationBusyError('Settings are changing. Wait for the mode change to finish before sending.')
            if any(mode is None or run['mode'] != mode for run in self.active.values()):
                raise ConversationBusyError(
                    'A task is still running in the other mode. Wait for it or stop it '
                    'before starting a task in this mode.'
                )

    def cancel(self, conversation_id, message_id, cancellations):
        with self.lock:
            run = self.active.get(conversation_id)
            if not run or run['message_id'] != message_id or run['status'] not in ('running', 'stopping'):
                return None
            # Signal execution even if storage has become unavailable.
            cancellations[message_id] = True
            run.update(status='stopping', status_text='Stopping…')
        with self.conversation_lock(conversation_id):
            if self.active.get(conversation_id) is not run:
                return None
            try:
                self.get_store().update_run(conversation_id, message_id, status='stopping')
            except (OSError, ValueError):
                logger.exception('Could not persist a Web task stop request')
                run['persistence_error'] = 'The stop request could not be saved; stopping the active worker.'
            self.emit('chat:run', self.public(run), room=f'conversation:{conversation_id}')
            return self.public(run)

    def finish(self, conversation_id, message_id, status, error=''):
        with self.conversation_lock(conversation_id):
            run = self.active.get(conversation_id)
            if not run or run['message_id'] != message_id:
                return None
            with self.lock:
                run.update(status=status, error=error, finished_at=time.time())
            try:
                self._persist_outcome(conversation_id, run)
            except (OSError, ValueError):
                logger.exception('Could not persist a Web task outcome')
                run['persistence_error'] = 'The task outcome could not be saved. Keep this page open to preserve the visible result.'
                self.unsaved[conversation_id] = dict(run)
                # Retain the lease until this exact outcome is durable. Listing
                # and retention must not invent an interrupted result meanwhile.
            with self.lock:
                del self.active[conversation_id]
            return self.public(run)

    def event(self, event, data, **kwargs):
        """Order snapshots and terminal delivery; cache only bounded status text."""
        data = dict(data)
        room = kwargs.get('room', '')
        conversation_id = data.get('conversation_id')
        if not conversation_id and isinstance(room, str) and room.startswith('conversation:'):
            conversation_id = room.removeprefix('conversation:')
            data['conversation_id'] = conversation_id
        with self.conversation_lock(conversation_id):
            run = self.active.get(conversation_id)
            settled = None
            if conversation_id and event in ('feedback:start', 'feedback:complete'):
                with self.lock:
                    self.feedback_revision += 1
                    data['feedback_revision'] = f'{self.owner}:{self.feedback_revision}'
                    self.feedback[conversation_id] = {'event': event, 'data': data}
                    self.feedback.move_to_end(conversation_id)
                    while len(self.feedback) > 100:
                        self.feedback.popitem(last=False)
            if run and data.get('message_id') == run['message_id']:
                if event in ('chat:status', 'tool:progress') and run['status'] != 'stopping':
                    run['status_text'] = str(data.get('status') or 'Working…')[:500]
                elif event == 'tool:start' and run['status'] != 'stopping':
                    run['status_text'] = f"Running {str(data.get('tool') or 'tool')[:100]}…"
                elif event in ('chat:response', 'chat:error', 'chat:cancelled') and run.get('kind') != 'repair':
                    status = ('cancelled' if data.get('cancelled') or event == 'chat:cancelled'
                              else 'failed' if event == 'chat:error' or data.get('ok') is False
                              else 'completed')
                    if event == 'chat:response' and data.get('run_status') in ('completed', 'failed'):
                        status = data['run_status']
                    settled = self.finish(conversation_id, run['message_id'], status,
                                          str(data.get('error') or '')[:2000])
                    if settled and settled.get('persistence_error'):
                        data['persistence_error'] = settled['persistence_error']
            if settled:
                self.emit('chat:run', settled, room=f'conversation:{conversation_id}')
            self.emit(event, data, **kwargs)
