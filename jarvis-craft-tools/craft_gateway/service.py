"""Single-instance gateway lifecycle and worker; engine failures stay outside Jarvis."""
import fcntl
import json
import os
import signal
import threading
from pathlib import Path

from .engine import Cancelled, Engine, execute
from .models import APPS, TESTED_VERSIONS, Operation
from .store import Store, process_identity


class Service:
    def __init__(self, config):
        self.config = config
        self.root = Path(config['state_dir']).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.store = Store(self.root, config.get('queue_limit', 8))
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.lock_file = None

    def capabilities(self):
        apps = {}
        actions = {'photocraft': ['invert', 'grayscale'], 'pdfcraft': ['rotate', 'extract', 'combine', 'render'],
                   'lightcraft': ['develop'], 'filmcraft': ['assemble'], 'effectcraft': ['title']}
        for app in APPS:
            binary = Path(self.config.get('binaries', {}).get(app, str(Path(self.config['apps_root']) / app / 'current/bin' / (app + '-cli')))).expanduser()
            version = None
            manifest = binary.parent.parent / 'craft-install.json'
            if manifest.is_file():
                version = json.loads(manifest.read_text()).get('release', {}).get('version')
            supported = binary.is_file() and os.access(binary, os.X_OK) and (
                version == TESTED_VERSIONS[app] or self.config.get('allow_untested_versions', False))
            apps[app] = {'installed': binary.is_file(), 'version': version,
                         'tested_version': TESTED_VERSIONS[app], 'supported': supported,
                         'actions': actions[app] if supported else [], 'binary': str(binary.resolve())}
        return {'protocol_version': 1, 'gateway_version': '0.1.0', 'apps': apps,
                'limits': {'upload_bytes': self.config.get('upload_bytes', 50 * 1024**2),
                           'output_bytes': self.config.get('output_bytes', 50 * 1024**2),
                           'disk_bytes': self.config.get('disk_bytes', 4 * 1024**3),
                           'timeout_seconds': self.config.get('timeout_seconds', 900),
                           'queue_limit': self.store.queue_limit}}

    def public_capabilities(self):
        result = self.capabilities()
        for app in result['apps'].values():
            app.pop('binary')
        result['operation_schema'] = Operation.model_json_schema()
        return result

    def start(self):
        self.lock_file = (self.root / 'gateway.lock').open('a')
        fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for job in self.store.interrupted():
            pid = job['process_pid']
            if pid and job['process_start'] and process_identity(pid) == job['process_start']:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.store.finish(job['id'], 'interrupted', 'Gateway restarted during this job. Work was not replayed; inspect inputs/outputs before submitting a new request.')
        self.thread = threading.Thread(target=self.run, name='craft-worker', daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=15)
            if self.thread.is_alive():
                raise RuntimeError('Craft worker did not stop; retaining the instance lock')
        if self.lock_file:
            self.lock_file.close()
            self.lock_file = None

    def run(self):
        while not self.stop_event.is_set():
            job = self.store.claim()
            if job is None:
                self.wake.wait(.5)
                self.wake.clear()
                continue
            engine = None
            try:
                operation = Operation.model_validate(json.loads(job['body'])['operation'])
                inputs = [self.store.artifact(item, job['project_id'])['path'] for item in operation.inputs]
                folder = self.store.workspaces / job['project_id'] / job['id']
                folder.mkdir(mode=0o700)
                engine = Engine(job['binary'], folder,
                                lambda: self.stop_event.is_set() or self.store.job(job['id'])['cancel_requested'],
                                lambda pid: self.store.process_started(job['id'], pid),
                                timeout=self.config.get('timeout_seconds', 900),
                                max_bytes=self.config.get('job_disk_bytes', 512 * 1024**2))
                exports, renderer = execute(engine, operation, inputs)
                engine.guard()
                for path, role in exports:
                    if path.stat().st_size > self.config.get('output_bytes', 50 * 1024**2):
                        raise ValueError('Output exceeds the artifact size limit')
                    self.store.add_artifact(job['project_id'], path, role, job['id'])
                self.store.finish(job['id'], 'succeeded', renderer=renderer)
            except Cancelled:
                if engine:
                    engine.stop()
                state = 'interrupted' if self.stop_event.is_set() else 'cancelled'
                self.store.finish(job['id'], state, 'Engine stopped. Inputs were preserved.')
            except Exception as exc:
                if engine:
                    engine.stop()
                self.store.finish(job['id'], 'failed', str(exc)[:1000])

    def disk_usage(self):
        size = 0
        count = 0
        for path in self.store.workspaces.rglob('*'):
            if path.is_file():
                size += path.stat().st_size
                count += 1
                if count > 100000:
                    raise ValueError('Workspace file-count limit exceeded')
        return size

    def validate_inputs(self, submission):
        image = {'.png', '.jpg', '.jpeg', '.webp'}
        allowed = {'photocraft': image | {'.pcraft'}, 'pdfcraft': {'.pdf'}, 'lightcraft': image,
                   'filmcraft': image | {'.mp4', '.mov', '.webm'}, 'effectcraft': set()}
        for artifact_id in submission.operation.inputs:
            record = self.store.artifact(artifact_id, submission.project_id)
            if record['job_id'] and self.store.job(record['job_id'])['state'] != 'succeeded':
                raise ValueError('Input belongs to an unsuccessful or unfinished job')
            if record['path'].suffix.lower() not in allowed[submission.operation.app]:
                raise ValueError('Input format is not supported by the selected adapter')
            if record['path'].suffix == '.pcraft' and record['role'] != 'project':
                raise ValueError('Only gateway-produced editable projects may be reopened')
