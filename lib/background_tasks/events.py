"""Best-effort, daily JSONL diagnostics shared by Web and the task worker."""

import json
import logging
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
_TOKEN = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')
_TOKENS = frozenset({'job_id', 'attempt_id', 'conversation_id', 'request_id', 'tool',
                     'adapter', 'mode', 'state', 'delivery_state', 'delivery_id', 'owner',
                     'error_type', 'action'})
_NUMBERS = frozenset({'duration_ms', 'queue_ms', 'count', 'generation', 'max_running',
                      'max_outstanding', 'max_queued', 'max_per_adapter', 'result_retention_days'})


class TaskEventLog:
    def __init__(self, database_path, *, directory=None, clock=time.time):
        database_path = Path(database_path).absolute()
        if directory is None:
            # An isolated --db must never write to the installation's logs.
            base = ROOT / 'logs' if database_path == ROOT / 'data/background_tasks.db' else database_path.parent / 'logs'
            directory = base / 'background-tasks'
        self.directory = Path(directory)
        self.clock = clock
        self._lock = threading.Lock()
        self._repeated = {}
        self._write_failed = False

    def emit(self, event, *, component, level='INFO', job=None, throttle=False, **fields):
        """Allowlisted metadata only; diagnostics never change task outcomes.

        Call after state commits. Repeated drain/store failures can be throttled;
        normal polling and heartbeat renewals must not call this method.
        """
        try:
            if not _TOKEN.fullmatch(event) or component not in {'store', 'web', 'worker', 'operator'}:
                return
            if level not in {'INFO', 'WARNING', 'ERROR'}:
                return
            values = {}
            if job:
                admission = job.get('admission') or {}
                values.update({key: job.get(key) for key in
                               ('attempt_id', 'conversation_id', 'mode', 'adapter', 'state', 'delivery_state', 'generation')})
                values.update(job_id=job.get('id'), tool=admission.get('tool'), request_id=admission.get('request_id'))
            values.update(fields)
            safe = {key: value for key, value in values.items()
                    if (key in _TOKENS and isinstance(value, str) and _TOKEN.fullmatch(value))
                    or (key in _NUMBERS and type(value) in {int, float} and math.isfinite(value))}
            for key in ('background_enabled', 'webhooks_enabled'):
                if type(values.get(key)) is bool:
                    safe[key] = values[key]
            if isinstance(values.get('background_tools'), list):
                safe['background_tools'] = [name for name in values['background_tools'][:128]
                                            if isinstance(name, str) and _TOKEN.fullmatch(name)]
            now = datetime.fromtimestamp(self.clock(), timezone.utc)
            entry = {'timestamp': now.isoformat(), 'service': 'background-tasks',
                     'component': component, 'level': level, 'event': event,
                     'pid': os.getpid(), **safe}
            with self._lock:
                if throttle:
                    key = (event, component, safe.get('job_id'), safe.get('error_type'))
                    last, suppressed = self._repeated.get(key, (float('-inf'), 0))
                    if now.timestamp() - last < 60:
                        self._repeated[key] = (last, suppressed + 1)
                        return
                    if suppressed:
                        entry['suppressed_repeats'] = suppressed
                    if len(self._repeated) >= 256:
                        self._repeated.clear()
                    self._repeated[key] = (now.timestamp(), 0)
                self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                path = self.directory / f'background-tasks-{now:%Y-%m-%d}.jsonl'
                # One shared lock covers concurrent Web/worker writes, including
                # short writes. It does not share the task DB transaction/lock.
                with FileLock(str(self.directory / '.write.lock'), timeout=0.1):
                    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
                    try:
                        data = (json.dumps(entry, ensure_ascii=True) + '\n').encode('utf-8')
                        while data:
                            written = os.write(fd, data)
                            if written <= 0:
                                raise OSError('No log bytes written')
                            data = data[written:]
                    finally:
                        os.close(fd)
                self._write_failed = False
        except Exception as exc:
            if not self._write_failed:
                logger.warning('Background event log unavailable error_type=%s', type(exc).__name__)
                self._write_failed = True
