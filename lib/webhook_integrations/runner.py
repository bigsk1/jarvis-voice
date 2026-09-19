"""Explicit trusted binding for local or reviewed private HTTP task services.

Bindings are supplied by trusted deployment code. This runner submits once and returns immediately;
the durable inbox, not a polling child/thread, observes completion.
"""
import json
import time

import requests

from lib.background_tasks.local_skill import argument_validators
from lib.background_tasks.models import TaskError, canonical_json
from lib.background_tasks.worker import AwaitingCallback, KnownFailure

from .contracts import endpoint


class SubmissionRejected(TaskError):
    """The configured service proved it did not accept work."""


def post_json(url, payload, *, headers=None, timeout=10):
    """Configured service only. No redirects, ambient proxies or unlimited body."""
    deadline = time.monotonic() + timeout
    with requests.Session() as session:
        session.trust_env = False
        with session.post(url, data=canonical_json(payload, 65536).encode(),
                          headers={'Content-Type': 'application/json', **(headers or {})}, timeout=(3, timeout),
                          allow_redirects=False, stream=True) as response:
            if 400 <= response.status_code < 500 and response.status_code != 408:
                raise SubmissionRejected('The configured service rejected the request')
            if response.status_code not in {200, 202}:
                raise TaskError('The configured service did not acknowledge the request')
            content = bytearray()
            # read1 returns available bytes. A slow trickle cannot reset the
            # entire response budget as it could with iter_content/read.
            while True:
                if time.monotonic() >= deadline:
                    raise TaskError('Service receipt timed out')
                chunk = response.raw.read1(4096)
                if not chunk:
                    break
                if len(content) + len(chunk) > 65536:
                    raise TaskError('Service receipt is too large')
                content.extend(chunk)
            return json.loads(content)


class LocalCallbackRunner:
    def __init__(self, service, bindings, *, prepare=None, binding_loader=None):
        # tool -> (source_id, reviewed parameter schema), supplied by trusted code.
        self.service, self.bindings = service, dict(bindings)
        # A trusted per-tool function may return (payload, headers) for a
        # loopback service, or (payload, headers, exact_remote_url) for a
        # reviewed private HTTPS service. Model arguments never choose a URL.
        self.prepare = prepare
        self.binding_loader = binding_loader

    def __call__(self, context):
        job = context.claim.job
        tool, arguments = job['admission']['tool'], job['admission']['arguments']
        try:
            bindings = self.binding_loader() if self.binding_loader else self.bindings
            source_id, parameters = bindings[tool]
            authorization = self.service.store.authorization(job['admission']['authorization_id'])
            if not authorization or authorization.get('callback_sources', {}).get(tool) != source_id:
                raise TaskError('Missing trusted callback binding')
            for validator in argument_validators(parameters, None):
                validator.validate(arguments)
            # Optional trusted deployment policy may stamp runtime context and
            # submission auth. Neither is accepted from model tool arguments.
            policy = self.prepare[tool] if isinstance(self.prepare, dict) else self.prepare
            prepared = policy(context) if policy else ({}, {})
            if len(prepared) == 2:
                extra, headers = prepared
                reviewed_remote_url = None
            else:
                extra, headers, reviewed_remote_url = prepared
            context.checkpoint()
            submission = self.service.prepare_submission(context.claim, source_id)
        except Exception as exc:
            raise KnownFailure({'ok': False, 'speech': 'Callback setup or authorization is unavailable; nothing was submitted.'}) from exc
        try:
            stored_url = submission.pop('submit_url')
            try:
                if reviewed_remote_url is None:
                    url = endpoint(stored_url, local_only=True)
                else:
                    url = endpoint(stored_url)
                    if url != reviewed_remote_url or not url.startswith('https://'):
                        raise SubmissionRejected('The private submit destination changed')
            except TaskError as exc:
                # URL validation happens before the POST. It proves that this
                # attempt did not start remote work, even though it was bound.
                raise SubmissionRejected('The configured submit destination is invalid') from exc
            result = post_json(url, {**extra, **submission, 'arguments': arguments}, headers=headers,
                               timeout=max(1, min(10, job['deadline'] - self.service.store.clock())))
            self.service.record_submission(context.claim, result['remote_id'])
        except SubmissionRejected as exc:
            # Binding precedes submission so a callback can win the receipt race.
            # A bad destination or definite service 4xx proves no work was accepted.
            raise KnownFailure({'ok': False, 'speech':
                'Background work could not start because the submission was rejected before acceptance.'}) from exc
        except Exception as exc:
            # A lost/malformed receipt or a local persistence failure can happen
            # after the helper committed the job. Keep the prebound attempt open,
            # do not fence it, and never submit it a second time.
            try:
                self.service.store.events.emit(
                    'callback_receipt_unknown', component='callback', level='WARNING',
                    job=job, error_type=type(exc).__name__,
                )
            except Exception:
                pass  # Event logging cannot fence an already-bound callback.
            return AwaitingCallback()
        return AwaitingCallback()
