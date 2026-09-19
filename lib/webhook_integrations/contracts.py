"""Small explicit protocol for self-hosted task services, not provider signatures."""
import hashlib
import hmac
import ipaddress
import json
import re
from urllib.parse import urlsplit

from lib.background_tasks.models import TaskError, canonical_json, identifier

ADAPTER = 'http_callback_v1'
EVENTS = frozenset({'task.progress', 'task.completed', 'task.failed', 'task.cancelled'})
MAX_BODY = 1024 * 1024
_STASH_REF = re.compile(r'stash://[^/\r\n]{1,256}/[^/\r\n]{1,256}\Z')


def _browser_presentation(value):
    if (not isinstance(value, dict)
            or set(value) != {'kind', 'stash_ref', 'sources', 'provider', 'model'}
            or value.get('kind') != 'browser_research'
            or not isinstance(value.get('stash_ref'), str)
            or not _STASH_REF.fullmatch(value['stash_ref'])
            or not isinstance(value.get('provider'), str) or not 1 <= len(value['provider']) <= 64
            or not isinstance(value.get('model'), str) or not 1 <= len(value['model']) <= 256
            or not isinstance(value.get('sources'), list) or len(value['sources']) > 60):
        return False
    for url in value['sources']:
        try:
            if not isinstance(url, str):
                return False
            parts = urlsplit(url)
            if (len(url) > 2048 or parts.scheme not in {'http', 'https'}
                    or not parts.hostname or parts.username or parts.password
                    or any(ord(char) < 32 for char in url)):
                return False
        except (TypeError, ValueError):
            return False
    return True


class CallbackError(TaskError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def secret_hash(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def signature(secret, source, timestamp, raw):
    return hmac.new(secret.encode(), timestamp.encode() + b'.' + source.encode() + b'.' + raw,
                    hashlib.sha256).hexdigest()


def endpoint(value, *, local_only=False):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 for c in value):
        raise TaskError('Expected a callback/service URL')
    try:
        parts = urlsplit(value)
        port = parts.port
        try:
            loopback = ipaddress.ip_address(parts.hostname).is_loopback
        except ValueError:
            loopback = False
        if (parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username
                or parts.password or parts.query or parts.fragment or port == 0
                or (parts.scheme == 'http' and not loopback) or (local_only and not loopback)):
            raise ValueError()
    except (TypeError, ValueError) as exc:
        raise TaskError('Use HTTPS, or an explicit loopback IP for local HTTP; no credentials/query/fragment') from exc
    return value.rstrip('/')


def event_body(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Repeated key')
            result[key] = value
        return result
    try:
        body = json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
        if not isinstance(body, dict) or type(body.get('schema_version')) is not int or body['schema_version'] != 1:
            raise ValueError()
        identifier(body.get('event_id'), 'event ID')
        if body.get('type') == 'integration.test':
            if set(body) != {'schema_version', 'event_id', 'type'}:
                raise ValueError()
            return body
        if body.get('type') not in EVENTS:
            raise ValueError()
        field = 'progress' if body['type'] == 'task.progress' else 'result'
        if set(body) != {'schema_version', 'event_id', 'job_id', 'attempt_id', 'type', field}:
            raise ValueError()
        identifier(body['job_id'], 'job ID')
        identifier(body['attempt_id'], 'attempt ID')
        value = body[field]
        if field == 'progress':
            if (not isinstance(value, dict) or set(value) - {'phase', 'percent'}
                    or not isinstance(value.get('phase'), str) or len(value['phase']) > 256
                    or ('percent' in value and (type(value['percent']) not in {int, float}
                                              or not 0 <= value['percent'] <= 100))):
                raise ValueError()
        elif (not isinstance(value, dict) or set(value) - {'summary', 'artifacts', 'presentation'}
              or not isinstance(value.get('summary'), str) or len(value['summary']) > 32000
              or value.get('artifacts', []) != []):
            # Phase 3a never fetches URLs or accepts caller-selected stash/files.
            raise ValueError()
        elif 'presentation' in value and not _browser_presentation(value['presentation']):
            # Presentation is optional decoration. A malformed card must not
            # reject an otherwise valid terminal summary and trigger retries.
            body = dict(body)
            body['result'] = dict(value)
            body['result'].pop('presentation', None)
        canonical_json(body, MAX_BODY)
        return body
    except (ValueError, TypeError, KeyError, RecursionError, TaskError) as exc:
        raise CallbackError('Invalid task event; callbacks accept bounded text and reviewed presentation metadata') from exc
