"""Optional Craft Gateway transport. All tools share mode-aware configuration."""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import requests
from config_loader import get_config_value
from remote_completion import RemoteCompletionError, submission_error

ID = re.compile(r'^[a-f0-9]{32}$')

class CraftError(RuntimeError):
    def __init__(self, message, *, job=None, request_id=None, completion='unknown'):
        super().__init__(message)
        self.job = job
        self.request_id = request_id
        self.completion = completion

class CraftClient:
    def __init__(self):
        self.base = str(get_config_value('CRAFT_API_URL', '') or '').strip().rstrip('/')
        key = str(get_config_value('CRAFT_API_KEY', '') or '').strip()
        if not self.base or not key:
            raise ValueError('Configure CRAFT_API_URL and CRAFT_API_KEY in the selected mode ENV. See jarvis-craft-tools/README.md.')
        parsed = urlsplit(self.base)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or not parsed.path.endswith('/craft-api/v1')):
            raise ValueError('CRAFT_API_URL must be an HTTP(S) gateway URL ending in /craft-api/v1 without credentials, query or fragment')
        if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Remote Craft connections require HTTPS. Use loopback HTTP only for a same-host native client.')
        bundle = str(get_config_value('CRAFT_CA_BUNDLE', '') or '').strip()
        if bundle and not Path(bundle).is_file():
            raise ValueError('CRAFT_CA_BUNDLE is not a readable client-side certificate file')
        self.session = requests.Session()
        self.session.trust_env = False  # Do not route LAN credentials through inherited proxies.
        self.session.headers.update(Authorization='Bearer ' + key)
        self.session.verify = bundle or True
        self.capability = None

    def close(self):
        self.session.close()

    def request(self, method, path, *, submission=False, **kwargs):
        response = self.session.request(method, self.base + path, timeout=(5, 30), allow_redirects=False, **kwargs)
        if not 200 <= response.status_code < 300:
            response.close()
            message = f'Craft Gateway returned HTTP {response.status_code}; check API key, TLS route, app capabilities and project/job IDs.'
            if submission and response.status_code == 409:
                # This gateway's 409 is a pre-execution refusal, unlike a
                # generic provider conflict. Never recover it as another job.
                raise RemoteCompletionError('Craft Gateway rejected the submission (HTTP 409: project busy, revision conflict, queue full, or reused request ID).', 'rejected')
            if submission:
                raise submission_error(response.status_code, message)
            raise CraftError(message)
        return response

    def json(self, method, path, **kwargs):
        with self.request(method, path, stream=True, **kwargs) as response:
            # A bounded body also prevents an unexpected HTML/proxy response
            # from filling tool output or becoming model instructions.
            content = bytearray()
            for block in response.iter_content(65536):
                content.extend(block)
                if len(content) > 2 * 1024**2:
                    raise CraftError('Gateway JSON response exceeds limit')
            return json.loads(content)

    def capabilities(self):
        result = self.json('GET', '/capabilities')
        if result.get('protocol_version') != 1:
            raise ValueError('Unsupported Craft Gateway protocol version')
        self.capability = result
        return result

    @staticmethod
    def identifier(value):
        if not isinstance(value, str) or not ID.fullmatch(value):
            raise ValueError('Craft identifiers must be 32 lowercase hexadecimal characters')
        return value

    def project(self, project_id):
        return self.json('GET', '/projects/' + self.identifier(project_id))

    def upload(self, project_id, path):
        path = Path(path)
        limit = min((self.capability or self.capabilities())['limits']['upload_bytes'],
                    int(get_config_value('JARVIS_BACKGROUND_MAX_INPUT_BYTES', '') or 50 * 1024**2))
        if not path.is_file() or path.stat().st_size > limit:
            raise ValueError('Input is missing or exceeds the Craft upload limit')
        name = uuid.uuid4().hex + path.suffix.lower()
        with path.open('rb') as stream:
            return self.json('POST', '/projects/' + self.identifier(project_id) + '/inputs',
                             params={'filename': name}, data=stream, headers={'Content-Type': 'application/octet-stream'})

    def submit(self, project, operation, request_id=None):
        request_id = self.identifier(request_id) if request_id else uuid.uuid4().hex
        body = {'request_id': request_id, 'project_id': project['id'], 'revision': project['revision'], 'operation': operation}
        try:
            return self.json('POST', '/jobs', json=body, submission=True)
        except (requests.RequestException, CraftError, RuntimeError, ValueError) as exc:
            if isinstance(exc, RemoteCompletionError):
                raise
            # A timeout/5xx/invalid response does not prove rejection. Query the
            # persisted acceptance by request ID; never repeat the POST.
            try:
                recovered = self.json('GET', '/jobs/by-request/' + request_id)
                if (recovered.get('request_id') != request_id or recovered.get('project_id') != project['id']
                        or recovered.get('revision') != project['revision']
                        or recovered.get('operation') != operation):
                    raise CraftError('Recovered job does not match this submission')
                return recovered
            except Exception:
                raise CraftError('Submission outcome is unknown. Inspect this request ID before retrying.',
                                 request_id=request_id) from exc

    def job(self, job_id=None, request_id=None):
        path = '/jobs/' + self.identifier(job_id) if job_id else '/jobs/by-request/' + self.identifier(request_id)
        return self.json('GET', path)

    def wait(self, job, seconds):
        deadline = time.monotonic() + seconds
        while job['state'] in ('queued', 'running') and time.monotonic() < deadline:
            time.sleep(min(.5, max(0, deadline - time.monotonic())))
            try:
                job = self.job(job['id'])
            except Exception as exc:
                raise CraftError('Lost observation of the Craft job; it may still be running. Inspect the job ID.', job=job) from exc
        return job

    def download(self, output):
        limit = min((self.capability or self.capabilities())['limits']['output_bytes'], 50 * 1024**2)
        if output['size_bytes'] > limit:
            raise CraftError('Artifact exceeds the Jarvis download limit')
        result = io.BytesIO()
        digest = hashlib.sha256()
        with self.request('GET', '/artifacts/' + self.identifier(output['id']), stream=True) as response:
            for block in response.iter_content(65536):
                if result.tell() + len(block) > limit:
                    raise CraftError('Artifact download exceeds limit')
                digest.update(block)
                result.write(block)
        if result.tell() != output['size_bytes'] or digest.hexdigest() != output['sha256']:
            raise CraftError('Artifact size/checksum verification failed')
        return result.getvalue()
