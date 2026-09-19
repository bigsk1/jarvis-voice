"""Outer ASGI admission limits for task callbacks only; no framework body buffering."""
import asyncio
import ipaddress
import re
import threading
import time

from starlette.responses import JSONResponse

from .contracts import MAX_BODY


def callback_path(path):
    return re.fullmatch(r'/api/task-callbacks/[a-f0-9]{32}/events', path) is not None


def callback_namespace(path):
    return path == '/api/task-callbacks' or path.startswith('/api/task-callbacks/')


class CallbackBoundary:
    def __init__(self, app, *, max_body=MAX_BODY, clock=time.monotonic,
                 per_client=120, global_limit=600, body_timeout=10):
        self.app, self.max_body, self.clock = app, max_body, clock
        self.per_client, self.global_limit, self.body_timeout = per_client, global_limit, body_timeout
        self.buckets, self.lock = {}, threading.Lock()

    def allowed(self, client):
        window = int(self.clock() // 60)
        try:
            local = ipaddress.ip_address(client).is_loopback
        except (TypeError, ValueError):
            local = False
        # The managed Browser Use helper delivers over loopback. Remote noise
        # must not consume its pre-auth global budget before source auth runs.
        ingress = 'loopback' if local else 'remote'
        with self.lock:
            self.buckets = {key: count for key, count in self.buckets.items() if key[0] == window}
            for key, maximum in (((window, ingress, None), self.global_limit),
                                 ((window, ingress, client), self.per_client)):
                if self.buckets.get(key, 0) >= maximum:
                    return False
            for key in ((window, ingress, None), (window, ingress, client)):
                self.buckets[key] = self.buckets.get(key, 0) + 1
        return True

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not callback_namespace(scope['path']):
            return await self.app(scope, receive, send)
        # Query authentication is unsupported. Strip before any access logger
        # (including Uvicorn) sees the response; never echo query data.
        query = bool(scope.get('query_string'))
        scope['query_string'] = b''

        async def reject(status, message):
            await JSONResponse({'error': message}, status_code=status,
                               headers={'Retry-After': '60'} if status == 429 else None)(scope, receive, send)

        if not self.allowed((scope.get('client') or ('unknown',))[0]):
            return await reject(429, 'Task callback rate limit exceeded')
        if query:
            return await reject(400, 'Callback query parameters are not supported')
        if not callback_path(scope['path']):
            return await reject(404, 'Task callback endpoint not found')
        lengths = [value for key, value in scope['headers'] if key.lower() == b'content-length']
        if lengths:
            try:
                if len(lengths) != 1 or not lengths[0].isdigit():
                    raise ValueError()
                if int(lengths[0]) > self.max_body:
                    return await reject(413, 'Callback body is too large')
            except ValueError:
                return await reject(400, 'Invalid callback length')
        protected = [key.lower() for key, _ in scope['headers'] if key.lower() in {
            b'authorization', b'x-jarvis-key-id', b'x-jarvis-timestamp', b'x-jarvis-signature', b'x-jarvis-task-capability'}]
        if len(protected) != len(set(protected)):
            return await reject(400, 'Repeated callback authentication headers')
        if any(key.lower() == b'content-encoding' and value.lower() != b'identity' for key, value in scope['headers']):
            return await reject(415, 'Compressed callback bodies are not supported')
        body = bytearray()
        deadline = self.clock() + self.body_timeout
        while True:
            try:
                part = await asyncio.wait_for(receive(), timeout=max(.001, deadline - self.clock()))
            except TimeoutError:
                return await reject(408, 'Callback body timed out')
            if part['type'] == 'http.disconnect':
                return
            chunk = part.get('body', b'')
            if len(body) + len(chunk) > self.max_body:
                return await reject(413, 'Callback body is too large')
            body.extend(chunk)
            if not part.get('more_body', False):
                break
        consumed = False

        async def bounded_receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()

        await self.app(scope, bounded_receive, send)
