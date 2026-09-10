"""
Conversation Storage Service
Saves and loads chat conversations
"""
import json
import logging
import os
import re
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from filelock import FileLock, Timeout

# Store conversations in data directory
CONVERSATIONS_DIR = Path(__file__).parent.parent.parent.parent / 'data' / 'web_conversations'

ACTIVE_RUN_STATES = frozenset({'running', 'stopping'})
logger = logging.getLogger(__name__)


class ConversationBusyError(ValueError):
    """A conversation still has work in flight."""


def _transaction(method):
    """Serialize JSON read/modify/write across threads and store instances."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            outermost = not self._file_lock.is_locked
            with self._file_lock:
                if outermost:
                    self._index = self._load_index()
                return method(self, *args, **kwargs)
    return wrapped


class ConversationStore:
    """Manages conversation persistence"""
    
    def __init__(self, conversations_dir: Path | None = None):
        self.conversations_dir = conversations_dir or CONVERSATIONS_DIR
        self.conversations_dir.mkdir(parents=True, exist_ok=True)
        self._index_file = self.conversations_dir / 'index.json'
        self._lock = threading.RLock()
        self._file_lock = FileLock(self.conversations_dir / '.store.lock', timeout=10)
        self._index = self._load_index()
        self._listed_documents = {}

    def _conversation_path(self, conv_id: str) -> Path:
        if not isinstance(conv_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', conv_id):
            raise ValueError('Invalid conversation ID')
        return self.conversations_dir / f'{conv_id}.json'

    def run_lease(self, conv_id: str) -> FileLock:
        """Held from admission through settlement; released by the OS on a crash.

        Admission and completion run on different threads, hence thread_local=False.
        Keep the lock file: unlinking it could let two owners lock different inodes.
        """
        self._conversation_path(conv_id)
        return FileLock(self.conversations_dir / f'.run-{conv_id}.lock', timeout=0, thread_local=False)

    def _read_conversation(self, conv_id: str) -> dict | None:
        path = self._conversation_path(conv_id)
        if path.exists():
            with path.open() as stream:
                return self._normalize_conversation_metadata(json.load(stream))
        return None

    def _reconcile_run(self, conversation: dict, *, persist: bool = True) -> dict:
        run = conversation.get('run') or {}
        if run.get('status') not in ACTIVE_RUN_STATES:
            if run and persist:
                summary = next((item for item in self._index['conversations']
                                if item['id'] == conversation['id']), {})
                if (summary.get('run_status') != run['status']
                        or summary.get('message_count') != len(conversation['messages'])):
                    self._save_run_summary(conversation)
            return conversation
        lease = self.run_lease(conversation['id'])
        try:
            lease.acquire()
        except Timeout:
            return conversation  # An actual execution owner still holds the lease.
        try:
            saved = next((item for item in conversation['messages']
                          if item['role'] == 'assistant'
                          and (item.get('data') or {}).get('_web_message_id') == run['message_id']), None)
            outcome = (saved.get('data') or {}).get('_run_status') if saved else None
            certain = outcome in ('completed', 'failed', 'cancelled')
            patch = {
                'status': outcome if certain else 'interrupted',
                'finished_at': time.time(),
                'error': '' if certain else (
                    'The task no longer has an execution owner. It was not retried. '
                    'Some actions may already have completed; check their results before sending another request.'
                ),
            }
            if persist:
                self.update_run(conversation['id'], run['message_id'], **patch)
                return self._read_conversation(conversation['id'])
            # Retention dry runs project the outcome without modifying JSON.
            conversation['run'] = {**run, **patch}
            return conversation
        finally:
            lease.release()

    @staticmethod
    def _write_json(path: Path, value: dict) -> None:
        """Replace a complete document; readers never see truncated JSON."""
        fd, name = tempfile.mkstemp(prefix=f'.{path.stem}-', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                if path.exists():
                    os.fchmod(stream.fileno(), path.stat().st_mode & 0o777)
                json.dump(value, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def _write_conversation(self, conversation: dict) -> None:
        self._write_json(self._conversation_path(conversation['id']), conversation)

    @staticmethod
    def _require_idle(conversation: dict | None) -> None:
        if (conversation or {}).get('run', {}).get('status') in ACTIVE_RUN_STATES:
            raise ConversationBusyError('This conversation has a running task. Stop it and wait for it to finish first.')

    @staticmethod
    def _default_summary(
        conv_id: str,
        title: str,
        created_at: str,
        updated_at: str,
        message_count: int = 0,
    ) -> dict:
        return {
            'id': conv_id,
            'title': title,
            'created_at': created_at,
            'updated_at': updated_at,
            'message_count': message_count,
            'pinned': False,
            'archived': False,
            'pinned_at': None,
            'archived_at': None,
        }

    @staticmethod
    def _normalize_summary(summary: dict | None) -> dict:
        summary = dict(summary or {})
        summary.setdefault('message_count', 0)
        summary['pinned'] = bool(summary.get('pinned', False))
        summary['archived'] = bool(summary.get('archived', False))
        summary['pinned_at'] = summary.get('pinned_at')
        summary['archived_at'] = summary.get('archived_at')
        return summary

    @staticmethod
    def _normalize_conversation_metadata(conversation: dict | None) -> dict:
        conversation = dict(conversation or {})
        conversation['pinned'] = bool(conversation.get('pinned', False))
        conversation['archived'] = bool(conversation.get('archived', False))
        conversation['pinned_at'] = conversation.get('pinned_at')
        conversation['archived_at'] = conversation.get('archived_at')
        return conversation
    
    def _load_index(self) -> dict:
        """Load conversation index"""
        if self._index_file.exists():
            try:
                with open(self._index_file, 'r') as f:
                    loaded = json.load(f)
                    summaries = [
                        self._normalize_summary(item)
                        for item in loaded.get('conversations', [])
                    ]
                    return {'conversations': summaries}
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                raise ValueError('The conversation index could not be read; it has not been overwritten.') from exc
        return {'conversations': []}
    
    def _save_index(self):
        """Save conversation index"""
        self._write_json(self._index_file, self._index)
    
    @_transaction
    def create_conversation(self, title: str = None, *, request_id: str | None = None) -> dict:
        """Create a new conversation"""
        # A first-send receipt has a direct document address, including when the
        # index write failed. Fresh requests never need to search the archive.
        conv_id = self.request_conversation_id(request_id) if request_id else str(uuid.uuid4())[:8]
        if request_id:
            existing = self._read_conversation(conv_id)
            if existing:
                return existing
        timestamp = datetime.now().isoformat()
        
        conversation = {
            'id': conv_id,
            'title': title or f'Chat {datetime.now().strftime("%m/%d %H:%M")}',
            'created_at': timestamp,
            'updated_at': timestamp,
            'messages': [],
            'pinned': False,
            'archived': False,
            'pinned_at': None,
            'archived_at': None,
        }
        
        # Save to file
        self._write_conversation(conversation)
        
        # Update index
        self._index['conversations'].insert(
            0,
            self._default_summary(
                conv_id,
                conversation['title'],
                timestamp,
                timestamp,
                message_count=0,
            ),
        )
        self._save_index()
        
        return conversation
    
    @_transaction
    def get_conversation(self, conv_id: str, *, reconcile: bool = True) -> dict | None:
        """Get a conversation by ID"""
        conversation = self._read_conversation(conv_id)
        if conversation and reconcile:
            conversation = self._reconcile_run(conversation)
        return conversation
    
    @_transaction
    def add_message(self, conv_id: str, role: str, content: str, 
                    data: dict = None, tools_used: list[str] = None) -> dict:
        """Add a message to a conversation"""
        conversation = self.get_conversation(conv_id)
        if not conversation:
            raise ValueError('Conversation not found')
        
        message = {
            'id': str(uuid.uuid4())[:8],
            'role': role,  # 'user' or 'assistant'
            'content': content,
            'timestamp': datetime.now().isoformat(),
            'data': data,
            'tools_used': tools_used or []
        }
        
        conversation['messages'].append(message)
        conversation['updated_at'] = message['timestamp']
        
        # Auto-generate title from first user message (full text; sidebar row ellipsizes in CSS)
        if len(conversation['messages']) == 1 and role == 'user':
            line = ' '.join(content.strip().split())
            if line:
                conversation['title'] = line[:4000]
        
        # Save conversation
        self._write_conversation(conversation)
        
        # Update index
        for idx_conv in self._index['conversations']:
            if idx_conv['id'] == conv_id:
                idx_conv['updated_at'] = message['timestamp']
                idx_conv['message_count'] = len(conversation['messages'])
                idx_conv['title'] = conversation['title']
                break
        self._save_index()
        
        return message
    
    @_transaction
    def list_conversations(self, limit: int = 50, include_archived: bool = True) -> list[dict]:
        """List recent conversations, with pinned chats sorted first."""
        # The index can lag ANY document, including a newly admitted run whose
        # summary is still idle or missing. Only parse changed/active documents
        # after the first listing, but keep probing active leases after a crash.
        seen = set()
        for path in self.conversations_dir.glob('*.json'):
            if path.name == 'index.json':
                continue
            seen.add(path.stem)
            try:
                stat = path.stat()
                signature = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
                if self._listed_documents.get(path.stem) == signature:
                    continue
                conversation = self._read_conversation(path.stem)
                if not conversation or conversation.get('id') != path.stem:
                    continue
                conversation = self._reconcile_run(conversation)
                self._save_run_summary(conversation)
                if (conversation.get('run') or {}).get('status') not in ACTIVE_RUN_STATES:
                    self._listed_documents[path.stem] = signature
            except (OSError, ValueError, KeyError, TypeError):
                logger.exception('Could not reconcile conversation %s', path.name)
        self._listed_documents = {key: value for key, value in self._listed_documents.items() if key in seen}
        convs = [self._normalize_summary(item) for item in self._index['conversations']]
        if not include_archived:
            convs = [item for item in convs if not item.get('archived')]
        convs = sorted(
            convs,
            key=lambda item: (
                1 if item.get('pinned') and not item.get('archived') else 0,
                1 if not item.get('archived') else 0,
                item.get('pinned_at') or item.get('updated_at', ''),
                item.get('updated_at', ''),
            ),
            reverse=True,
        )
        return convs[:limit]
    
    @_transaction
    def delete_conversation(self, conv_id: str) -> bool:
        """Delete a conversation"""
        self._require_idle(self.get_conversation(conv_id))
        conv_file = self._conversation_path(conv_id)
        if conv_file.exists():
            conv_file.unlink()
        
        self._index['conversations'] = [
            c for c in self._index['conversations'] if c['id'] != conv_id
        ]
        self._save_index()
        return True

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        """Parse saved conversation timestamps for retention cleanup."""
        if not value:
            return None
        try:
            timestamp = str(value)
            if timestamp.endswith('Z'):
                timestamp = f"{timestamp[:-1]}+00:00"
            parsed = datetime.fromisoformat(timestamp)
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed

    @_transaction
    def cleanup_old_unpinned(
        self,
        *,
        retention_days: int = 90,
        dry_run: bool = False,
        now: datetime | None = None,
    ) -> dict:
        """Delete unpinned conversations older than the retention window."""
        now = now or datetime.now()
        cutoff = now - timedelta(days=retention_days)
        result = {
            'deleted_conversations': 0,
            'freed_bytes': 0,
            'preserved_pinned': 0,
            'preserved_recent': 0,
            'preserved_active': 0,
            'skipped_invalid_timestamp': 0,
            'missing_files': 0,
            'candidates': [],
            'warnings': [],
            'errors': [],
        }

        for summary in list(self._index.get('conversations', [])):
            summary = self._normalize_summary(summary)
            conv_id = summary.get('id')
            if not conv_id:
                continue

            conv_file = self._conversation_path(conv_id)
            conversation = self._read_conversation(conv_id)
            if conversation is None:
                result['missing_files'] += 1
                conversation = {}

            if summary.get('pinned') or conversation.get('pinned'):
                result['preserved_pinned'] += 1
                continue

            if conversation:
                conversation = self._reconcile_run(conversation, persist=not dry_run)
                if (conversation.get('run') or {}).get('status') in ACTIVE_RUN_STATES:
                    result['preserved_active'] += 1
                    continue

            timestamp = self._parse_timestamp(
                conversation.get('updated_at')
                or summary.get('updated_at')
                or conversation.get('created_at')
                or summary.get('created_at')
            )
            if timestamp is None:
                result['skipped_invalid_timestamp'] += 1
                result['warnings'].append({
                    'conversation_id': conv_id,
                    'warning': 'Missing or invalid updated_at timestamp',
                })
                continue
            if timestamp >= cutoff:
                result['preserved_recent'] += 1
                continue

            size = conv_file.stat().st_size if conv_file.exists() else 0
            result['candidates'].append({
                'id': conv_id,
                'title': conversation.get('title') or summary.get('title') or conv_id,
                'updated_at': timestamp.isoformat(),
                'size': size,
            })
            result['freed_bytes'] += size
            if dry_run:
                continue

            try:
                self.delete_conversation(conv_id)
                result['deleted_conversations'] += 1
            except Exception as exc:
                result['errors'].append({
                    'conversation_id': conv_id,
                    'error': str(exc),
                })
        return result
    
    @_transaction
    def clear_conversation(self, conv_id: str) -> bool:
        """Clear all messages from a conversation (keeps the conversation, resets to empty)"""
        conversation = self.get_conversation(conv_id)
        if conversation:
            self._require_idle(conversation)
            conversation.pop('run', None)
            conversation['messages'] = []
            conversation['title'] = f'Chat {datetime.now().strftime("%m/%d %H:%M")}'
            conversation['updated_at'] = datetime.now().isoformat()
            self._write_conversation(conversation)
            for idx_conv in self._index['conversations']:
                if idx_conv['id'] == conv_id:
                    idx_conv['updated_at'] = conversation['updated_at']
                    idx_conv['message_count'] = 0
                    idx_conv['title'] = conversation['title']
                    idx_conv.pop('run_status', None)
                    idx_conv.pop('first_request_id', None)
                    idx_conv.pop('last_request_id', None)
                    break
            self._save_index()
            return True
        return False

    @_transaction
    def update_title(self, conv_id: str, title: str) -> bool:
        """Update conversation title"""
        conversation = self.get_conversation(conv_id)
        if conversation:
            conversation['title'] = title
            self._write_conversation(conversation)
            
            for idx_conv in self._index['conversations']:
                if idx_conv['id'] == conv_id:
                    idx_conv['title'] = title
                    break
            self._save_index()
            return True
        return False

    @_transaction
    def update_state(self, conv_id: str, *, pinned: bool | None = None, archived: bool | None = None) -> dict | None:
        """Update pinned/archive state for a conversation and return the updated summary."""
        conversation = self.get_conversation(conv_id)
        if not conversation:
            return None

        timestamp = datetime.now().isoformat()
        if archived is not None:
            conversation['archived'] = bool(archived)
            conversation['archived_at'] = timestamp if conversation['archived'] else None
            if conversation['archived']:
                conversation['pinned'] = False
                conversation['pinned_at'] = None
        if pinned is not None and not conversation.get('archived'):
            conversation['pinned'] = bool(pinned)
            conversation['pinned_at'] = timestamp if conversation['pinned'] else None

        self._write_conversation(conversation)

        updated_summary = None
        for idx_conv in self._index['conversations']:
            if idx_conv['id'] != conv_id:
                continue
            idx_conv['pinned'] = conversation.get('pinned', False)
            idx_conv['archived'] = conversation.get('archived', False)
            idx_conv['pinned_at'] = conversation.get('pinned_at')
            idx_conv['archived_at'] = conversation.get('archived_at')
            updated_summary = dict(idx_conv)
            break
        self._save_index()
        return self._normalize_summary(updated_summary)

    @_transaction
    def update_llm_metadata(
        self,
        conv_id: str,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> bool:
        """Persist the provider/model used for this conversation (for token UI restore)."""
        conversation = self.get_conversation(conv_id)
        if not conversation:
            return False

        changed = False
        if provider and conversation.get('llm_provider') != provider:
            conversation['llm_provider'] = provider
            changed = True
        if model and conversation.get('llm_model') != model:
            conversation['llm_model'] = model
            changed = True
        if not changed:
            return True

        conversation['updated_at'] = datetime.now().isoformat()
        self._write_conversation(conversation)
        return True

    @_transaction
    def update_message_data_by_web_message_id(self, conv_id: str, web_message_id: str, patch: dict) -> bool:
        """Merge message data into an assistant message identified by its live web message id."""
        conversation = self.get_conversation(conv_id)
        if not conversation:
            return False

        for message in conversation.get('messages', []):
            message_data = message.get('data') or {}
            if message_data.get('_web_message_id') != web_message_id:
                continue

            message_data.update(patch or {})
            message['data'] = message_data
            conversation['updated_at'] = datetime.now().isoformat()

            self._write_conversation(conversation)

            for idx_conv in self._index['conversations']:
                if idx_conv['id'] == conv_id:
                    idx_conv['updated_at'] = conversation['updated_at']
                    break
            self._save_index()
            return True

        return False


    @staticmethod
    def request_conversation_id(request_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f'jarvis-web-request:{uuid.UUID(request_id)}'))

    @_transaction
    def find_request_conversation(self, request_id: str, *, recover: bool = True) -> str | None:
        """Find an accepted first send even if its conversation-created event was lost."""
        direct_id = self.request_conversation_id(request_id)
        conversation = self._read_conversation(direct_id)
        if conversation and any((item.get('data') or {}).get('_request_id') == request_id
                                for item in conversation.get('messages', [])):
            return direct_id
        for summary in self._index['conversations']:
            if request_id in (summary.get('first_request_id'), summary.get('last_request_id')):
                return summary['id']
        if not recover:
            return None
        # Explicit resume also supports older receipts without a direct address.
        for path in self.conversations_dir.glob('*.json'):
            if path.name == 'index.json':
                continue
            try:
                conversation = self._read_conversation(path.stem)
                if conversation and conversation.get('id') != path.stem:
                    continue
            except (OSError, ValueError, TypeError):
                logger.exception('Skipping unreadable conversation %s during resume', path.name)
                continue
            if conversation and any((item.get('data') or {}).get('_request_id') == request_id
                                    for item in conversation.get('messages', [])):
                if conversation.get('run'):
                    self._save_run_summary(conversation)
                return conversation['id']
        return None

    @_transaction
    def claim_run(
        self, conv_id: str, run: dict, *, message: str | None = None,
        data: dict | None = None,
    ) -> bool:
        """Persist admission and its user turn together, before starting work."""
        conversation = self.get_conversation(conv_id)
        if conversation is None:
            raise ValueError('Conversation not found')
        # Transport retries refer to the same user request, even after completion.
        if any((item.get('data') or {}).get('_request_id') == run['message_id']
               for item in conversation['messages']):
            return False
        self._require_idle(conversation)
        if message is not None:
            timestamp = datetime.now().isoformat()
            user_data = dict(data or {})
            user_data['_request_id'] = run['message_id']
            user_data['_run'] = dict(run)
            conversation['messages'].append({
                'id': str(uuid.uuid4())[:8], 'role': 'user', 'content': message,
                'timestamp': timestamp, 'data': user_data, 'tools_used': [],
            })
            conversation['updated_at'] = timestamp
            if len(conversation['messages']) == 1:
                conversation['title'] = ' '.join(message.strip().split())[:4000] or conversation['title']
        conversation['run'] = dict(run)
        if run.get('kind') == 'repair':
            for item in conversation['messages']:
                if (item.get('data') or {}).get('_web_message_id') == run.get('parent_message_id'):
                    item['data']['_repair_run'] = dict(run)
                    item['data']['_completion_guard'] = {
                        **(data or {}), 'status': 'repairing',
                        'started_at': datetime.now().isoformat(),
                    }
                    break
        self._write_conversation(conversation)
        self._save_run_summary(conversation)
        return True

    @_transaction
    def update_run(self, conv_id: str, message_id: str, *, recover_owner: str | None = None, **patch) -> dict | None:
        """Update only the current request; late workers cannot overwrite its successor."""
        conversation = self._read_conversation(conv_id)
        if conversation is None:
            return None
        run = conversation.get('run')
        if not run or run.get('message_id') != message_id:
            return None
        recover_interrupted = (run['status'] == 'interrupted' and recover_owner
                               and run.get('owner') == recover_owner)
        if run['status'] not in ACTIVE_RUN_STATES and not recover_interrupted:
            self._save_run_summary(conversation)
            return dict(run)
        run.update(patch)
        for item in conversation['messages']:
            if (item.get('data') or {}).get('_request_id') == message_id:
                item['data']['_run'] = dict(run)
                break
            if (run.get('kind') == 'repair'
                    and (item.get('data') or {}).get('_web_message_id') == run.get('parent_message_id')):
                item['data']['_repair_run'] = dict(run)
                guard = item['data'].setdefault('_completion_guard', {})
                if run['status'] == 'interrupted' or (guard.get('status') == 'repairing'
                                                       and run['status'] in ('failed', 'cancelled')):
                    guard.update(status='error' if run['status'] == 'failed' else run['status'],
                                 reason=run.get('error', ''))
                break
        self._write_conversation(conversation)
        self._save_run_summary(conversation)
        return dict(run)

    def _save_run_summary(self, conversation: dict) -> None:
        """Repair index fields if an earlier document write outlived its index write."""
        previous = [dict(item) for item in self._index['conversations']]
        run = conversation.get('run') or {}
        if not any(item['id'] == conversation['id'] for item in self._index['conversations']):
            self._index['conversations'].insert(0, self._normalize_summary({
                key: value for key, value in conversation.items()
                if key in ('id', 'title', 'created_at', 'updated_at', 'pinned', 'pinned_at', 'archived', 'archived_at')
            }))
        for summary in self._index['conversations']:
            if summary['id'] == conversation['id']:
                first = next(((item.get('data') or {}).get('_request_id')
                              for item in conversation['messages']
                              if (item.get('data') or {}).get('_request_id')), run.get('message_id'))
                summary.update(title=conversation['title'], updated_at=conversation['updated_at'],
                               message_count=len(conversation['messages']))
                if run:
                    summary.update(run_status=run['status'], first_request_id=first,
                                   last_request_id=run['message_id'])
                else:
                    for key in ('run_status', 'first_request_id', 'last_request_id'):
                        summary.pop(key, None)
                break
        if self._index['conversations'] != previous:
            self._save_index()

    @_transaction
    def save_import(self, conversation: dict) -> None:
        """Save an imported chat without racing other conversations' index updates."""
        self._require_idle(self.get_conversation(conversation['id']))
        conversation.pop('run', None)  # Exported work must never become executable.
        for message in conversation.get('messages', []):
            data = message.get('data') or {}
            for key in ('_run', '_repair_run'):
                if (data.get(key) or {}).get('status') in ACTIVE_RUN_STATES:
                    data[key] = {**data[key], 'status': 'interrupted',
                                 'error': 'This task was imported without an execution owner. It was not retried.'}
            if (data.get('_completion_guard') or {}).get('status') == 'repairing':
                data['_completion_guard']['status'] = 'interrupted'
        self._write_conversation(conversation)
        for summary in self._index['conversations']:
            if summary['id'] == conversation['id']:
                summary.update({key: conversation.get(key) for key in (
                    'title', 'updated_at', 'pinned', 'archived', 'pinned_at', 'archived_at',
                )})
                summary['message_count'] = len(conversation['messages'])
                break
        self._save_index()


# Singleton instance
_store: ConversationStore | None = None


def get_conversation_store() -> ConversationStore:
    """Get or create the conversation store singleton"""
    global _store
    if _store is None:
        _store = ConversationStore()
    return _store
