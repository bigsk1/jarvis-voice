"""Read-only projections and shared database-file coordination for reflection review."""

import json
import os
import threading
from pathlib import Path

from filelock import FileLock, Timeout
from security_utils import redact_sensitive_data, redact_sensitive_text

QUEUE_ORDER = 'priority DESC, queued_at ASC, id ASC'
_LOCKS: dict[tuple[int, str], '_ProcessingLock'] = {}
_LOCKS_GUARD = threading.Lock()
_SOURCES = {'web': 'Web', 'voice': 'Voice', 'cli': 'CLI', 'api': 'API',
            'scheduled': 'Scheduled task', 'unknown': 'Unknown'}
_BACKGROUND_PREFIX = (
    'A background acceptance receipt confirms admission, not completion. Its job_id identifies '
    'the Jarvis queue entry, not a provider task. Do not pass it to a remote tool for job, status '
    'or collect. Provider task IDs and output references arrive separately. Continue independent '
    'work; acknowledge queued work when its result is needed. Do not repeat the accepted call '
    'or rely on its result until it arrives separately.'
)


class ReflectionBusy(RuntimeError):
    """Another processor or queue mutation owns this database's reflection lock."""


class _ProcessingLock:
    """Non-reentrant thread exclusion plus the existing portable OS file lock.

    The sidecar stays beside the database so native services and containers
    sharing that database also share the lock. FileLock releases on process exit;
    an empty leftover sidecar is not a running job. Never unlink it on release.
    """

    def __init__(self, db_path: str):
        self._thread_lock = threading.Lock()
        self._file_lock = FileLock(db_path + '.reflection.lock', thread_local=False, mode=0o600)

    def acquire(self, blocking: bool = True) -> bool:
        if not self._thread_lock.acquire(blocking=blocking):
            return False
        try:
            self._file_lock.acquire(blocking=blocking)
        except Timeout:
            self._thread_lock.release()
            return False
        except BaseException:
            self._thread_lock.release()
            raise
        return True

    def release(self) -> None:
        try:
            self._file_lock.release()
        finally:
            self._thread_lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_exc):
        self.release()


def processing_lock(db_path: str | Path) -> _ProcessingLock:
    key = str(Path(db_path).resolve())
    with _LOCKS_GUARD:
        # Forked children must not reuse an inherited, already-held thread lock.
        process_key = (os.getpid(), key)
        if process_key not in _LOCKS:
            _LOCKS[process_key] = _ProcessingLock(key)
        return _LOCKS[process_key]


def json_object(value) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def review_request(stored_query, raw_data=None) -> tuple[str, str]:
    """Get clean original text for display/search without modifying stored evidence."""
    context = json_object(json_object(raw_data).get('context'))
    interaction = json_object(context.get('interaction'))
    if interaction.get('version') == 1 and interaction.get('user_query'):
        return redact_sensitive_text(str(interaction['user_query'])), 'captured'
    query = str(stored_query or '')
    prefix = _BACKGROUND_PREFIX + "\n\nUser's request: "
    if query.startswith(prefix):
        return redact_sensitive_text(query[len(prefix):]), 'legacy_background_wrapper'
    return redact_sensitive_text(query), 'stored'


def project_review(item: dict, raw_data=None, *, full_request: bool = False) -> dict:
    """Project the saved request/source and, on demand, one recorded answer."""
    context = json_object(json_object(raw_data).get('context'))
    interaction = json_object(context.get('interaction'))
    interaction = interaction if interaction.get('version') == 1 else {}
    user_query, origin = review_request(item.get('query'), raw_data)
    saved_request_truncated = origin == 'captured' and bool(interaction.get('user_query_truncated'))
    source = interaction.get('source')
    source = source if isinstance(source, str) and source in _SOURCES else 'unknown'
    conversation_id = context.get('web_conversation_id')
    if not interaction and isinstance(conversation_id, str) and conversation_id:
        source = 'web'
    review = {
        'user_query': user_query if full_request else user_query[:600],
        'user_query_truncated': saved_request_truncated or (not full_request and len(user_query) > 600),
        'query_origin': origin, 'source': source, 'source_label': _SOURCES[source],
    }
    if full_request:
        response = redact_sensitive_text(str(context.get('raw_llm_response')
                                            or context.get('llm_response')
                                            or context.get('final_speech') or ''))
        review['response'] = response[:6000]
        review['response_truncated'] = len(response) > 6000 or '[truncated]' in response
    return redact_sensitive_data(review)
