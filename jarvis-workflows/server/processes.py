"""Linux process identities for verified worker/descendant cleanup after a crash."""
from __future__ import annotations

import os
import signal
import time
from pathlib import Path

try:
    BOOT_ID = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
except OSError:
    BOOT_ID = ''


def process_identity(pid: int) -> dict | None:
    """PID plus kernel start ticks prevents signaling an unrelated reused PID."""
    try:
        fields = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(') ', 1)[1].split()
        if fields[0] == 'Z':
            return None
        return {'pid': pid, 'started': fields[19], 'parent': int(fields[1]), 'boot_id': BOOT_ID}
    except (OSError, ValueError, IndexError):
        return None


def same_process(identity: dict) -> bool:
    current = process_identity(identity['pid'])
    return (current is not None and current['started'] == identity['started']
            and current['boot_id'] == identity.get('boot_id'))


def descendants(identity: dict) -> dict[int, dict]:
    if not same_process(identity):
        return {}
    processes = {}
    for entry in Path('/proc').glob('[0-9]*'):
        current = process_identity(int(entry.name))
        if current:
            processes[current['pid']] = current
    parents = {identity['pid']}
    found = {}
    while True:
        children = {pid: item for pid, item in processes.items()
                    if item['parent'] in parents and pid not in found}
        if not children:
            return found
        found.update(children)
        parents = set(children)


def stop_verified(identity: dict, known: dict[int, dict] | None = None) -> bool:
    """Stop only recorded identities, including detached tool sessions."""
    recorded = dict(known or {})
    recorded.update(descendants(identity))
    recorded[identity['pid']] = identity
    for number, duration in ((signal.SIGTERM, 2), (signal.SIGKILL, 2)):
        recorded.update(descendants(identity))
        for item in reversed(list(recorded.values())):
            if same_process(item):
                try:
                    os.kill(item['pid'], number)
                except ProcessLookupError:
                    pass
        until = time.monotonic() + duration
        while time.monotonic() < until:
            if not any(same_process(item) for item in recorded.values()):
                return True
            time.sleep(0.05)
    return not any(same_process(item) for item in recorded.values())
