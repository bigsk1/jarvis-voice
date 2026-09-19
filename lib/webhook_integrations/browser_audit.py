"""Privacy-bounded, best-effort JSONL audit trail for Browser Use."""

import json
import logging
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from filelock import FileLock

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
_TOKEN = re.compile(r'[A-Za-z0-9_.:-]{1,256}\Z')


def safe_destination(value):
    """Return an audit-safe HTTP destination without credentials/query/fragment."""
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {'http', 'https'} or not parts.hostname:
            return None
        host = parts.hostname.lower()
        if ':' in host:
            host = f'[{host}]'
        if parts.port:
            host += f':{parts.port}'
        path = parts.path[:512]
        if any(ord(char) < 32 or ord(char) == 127 for char in path):
            return None
        return urlunsplit((parts.scheme.lower(), host, path or '/', '', ''))
    except (TypeError, ValueError):
        return None


class BrowserAudit:
    """Write allowlisted browser lifecycle and destination metadata only."""

    def __init__(self, database_path=None, *, directory=None, clock=time.time):
        if directory is None:
            database = Path(database_path).absolute()
            base = ROOT / 'logs' if database == ROOT / 'data/browser-use.db' else database.parent / 'logs'
            directory = base / 'browser-use'
        self.directory = Path(directory)
        self.clock = clock
        self._lock = threading.Lock()
        self._write_failed = False

    def emit(self, event, *, level='INFO', url=None, **fields):
        try:
            if not _TOKEN.fullmatch(event) or level not in {'INFO', 'WARNING', 'ERROR'}:
                return
            safe = {}
            for key in ('job_id', 'attempt_id', 'mode', 'provider', 'model', 'method',
                        'resource_type', 'state', 'error_type', 'proxy_policy'):
                value = fields.get(key)
                if isinstance(value, str) and _TOKEN.fullmatch(value):
                    safe[key] = value
            for key in ('status_code', 'bytes', 'request_count', 'step', 'step_count',
                        'error_count', 'callback_status'):
                value = fields.get(key)
                if type(value) in {int, float} and math.isfinite(value):
                    safe[key] = value
            for key in ('ok', 'accepted'):
                if type(fields.get(key)) is bool:
                    safe[key] = fields[key]
            destination = safe_destination(url)
            if destination:
                safe['destination'] = destination
            now = datetime.fromtimestamp(self.clock(), timezone.utc)
            entry = {'timestamp': now.isoformat(), 'service': 'browser-use', 'level': level,
                     'event': event, 'pid': os.getpid(), **safe}
            with self._lock:
                self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                path = self.directory / f'browser-use-{now:%Y-%m-%d}.jsonl'
                with FileLock(str(self.directory / '.write.lock'), timeout=.1):
                    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
                    try:
                        raw = (json.dumps(entry, ensure_ascii=True) + '\n').encode()
                        while raw:
                            written = os.write(fd, raw)
                            if written <= 0:
                                raise OSError('No audit bytes written')
                            raw = raw[written:]
                    finally:
                        os.close(fd)
            self._write_failed = False
        except Exception as exc:
            if not self._write_failed:
                logger.warning('Browser audit log unavailable error_type=%s', type(exc).__name__)
                self._write_failed = True


class NullBrowserAudit:
    def emit(self, *_args, **_kwargs):
        pass
