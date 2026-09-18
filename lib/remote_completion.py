"""Explicit outcome evidence from trusted skill/provider boundaries.

No message matching, polling-error inference, or automatic resubmission. A
submission rejection and a terminal provider response prove work is finished;
transport failures and lost observation do not.
"""


class RemoteCompletionError(RuntimeError):
    def __init__(self, message, completion):
        if completion not in {'rejected', 'completed'}:
            raise ValueError('Expected confirmed remote completion')
        super().__init__(message)
        self.completion = completion


def submission_error(status, message):
    """Only use at the initial submission, never polling or artifact download."""
    if status in {400, 401, 403, 404, 413, 422, 429}:
        return RemoteCompletionError(message, 'rejected')
    return RuntimeError(message)


def submit(call, *args, **kwargs):
    """Preserve SDK rejection evidence at an explicit submission boundary."""
    try:
        return call(*args, **kwargs)
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if callable(code):  # gRPC submission errors (xAI).
            code = code()
            if getattr(code, 'name', None) in {
                'INVALID_ARGUMENT', 'UNAUTHENTICATED', 'PERMISSION_DENIED',
                'NOT_FOUND', 'RESOURCE_EXHAUSTED',
            }:
                raise RemoteCompletionError(str(exc), 'rejected') from exc
        elif type(code) is int:  # Gemini's structured APIError.code.
            failure = submission_error(code, str(exc))
            if isinstance(failure, RemoteCompletionError):
                raise failure from exc
        raise


def completion_for_error(error, *, provider_completed=False):
    if provider_completed:
        return 'completed'
    if isinstance(error, RemoteCompletionError):
        return error.completion
    return 'unknown'


def gemini_interactions_options():
    """Public HTTP hooks enforce one background Interactions submission.

    The SDK's Interactions bridge currently interprets ``attempts=1`` as one
    retry, unlike its models API. Stop HTTP errors before that retry layer and
    refuse another POST after a lost response. Polling GETs remain independent.
    Use a fresh options object for each client/job.
    """
    submitted = False

    def is_submission(request):
        return request.method == 'POST' and request.url.path.rstrip('/').endswith('/interactions')

    def before_request(request):
        nonlocal submitted
        if is_submission(request):
            if submitted:
                raise RuntimeError('Gemini submission outcome is unknown; refusing to resubmit')
            submitted = True

    def after_response(response):
        if is_submission(response.request) and response.status_code >= 400:
            response.read()
            raise submission_error(response.status_code,
                f'Gemini submission failed (HTTP {response.status_code}): {response.text[:8192]}')

    return {'retry_options': {'attempts': 1}, 'client_args': {
        'event_hooks': {'request': [before_request], 'response': [after_response]}}}
