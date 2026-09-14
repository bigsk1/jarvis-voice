"""Authenticate every registered Web socket event and expire idle connections.

Flask's before_request hooks do not protect Socket.IO event handlers. Keep the
guard at registration so chat, logs, and proactive subscriptions share it.
"""
from functools import wraps
import threading
import time

from flask import request
from flask_socketio import ConnectionRefusedError, SocketIO

from webui_auth import is_auth_enabled, verify_token


class AuthenticatedSocketIO(SocketIO):
    """WebUI bearer authentication around SocketIO's public registration API."""

    def __init__(self, *args, **kwargs):
        self._credentials = {}
        self._credentials_lock = threading.RLock()
        super().__init__(*args, **kwargs)

    @staticmethod
    def _connection_token(auth):
        if isinstance(auth, dict) and 'token' in auth:
            token = auth['token']
            return token if isinstance(token, str) else None
        header = request.headers.get('Authorization', '')
        if header.startswith('Bearer '):
            return header[7:]
        # Preserve shared-cookie sign-in for existing same-origin Web clients.
        # Cross-origin clients must explicitly present a bearer credential.
        origin = request.headers.get('Origin')
        if not origin or origin.rstrip('/') == request.host_url.rstrip('/'):
            return request.cookies.get('jarvis_auth')
        return None

    def _forget_credentials(self, key):
        with self._credentials_lock:
            credentials = self._credentials.pop(key, None)
            if credentials and credentials.get('timer'):
                credentials['timer'].cancel()

    def _arm_expiry(self, key, credentials, expires_at):
        timer = threading.Timer(
            max(0.05, expires_at - time.time()), self._expire_connection,
            args=(key, credentials),
        )
        timer.daemon = True
        with self._credentials_lock:
            if self._credentials.get(key) is not credentials:
                return
            credentials['timer'] = timer
            timer.start()

    def _expire_connection(self, key, credentials):
        with self._credentials_lock:
            if self._credentials.get(key) is not credentials:
                return
        if not is_auth_enabled():
            return
        payload = verify_token(credentials['token'])
        if payload:
            # A clock adjustment or early timer wakeup must not end valid auth.
            self._arm_expiry(key, credentials, payload['exp'])
            return
        self._reject_connection(key)

    def _reject_connection(self, key):
        namespace, sid = key
        self.emit('auth:required', {
            'code': 'authentication_required',
            'message': 'Please sign in again to reconnect.',
        }, to=sid, namespace=namespace)
        # Disconnect removes room subscriptions but never cancels owned runs.
        self.server.disconnect(sid, namespace=namespace)
        self._forget_credentials(key)

    def on(self, message, namespace=None):
        register = super().on(message, namespace=namespace)

        def decorate(handler):
            @wraps(handler)
            def authenticated(*args, **kwargs):
                key = (request.namespace, request.sid)
                if message == 'disconnect':
                    self._forget_credentials(key)
                    return handler(*args, **kwargs)
                if message == 'connect':
                    token = self._connection_token(args[0] if args else None)
                    payload = verify_token(token) if is_auth_enabled() else None
                    if is_auth_enabled() and not payload:
                        raise ConnectionRefusedError('Authentication required', {
                            'code': 'authentication_required',
                        })
                    credentials = {'token': token, 'timer': None}
                    with self._credentials_lock:
                        self._credentials[key] = credentials
                    try:
                        result = handler(*args, **kwargs)
                    except Exception:
                        self._forget_credentials(key)
                        raise
                    if result is False:
                        self._forget_credentials(key)
                    elif payload:
                        self._arm_expiry(key, credentials, payload['exp'])
                    return result
                with self._credentials_lock:
                    credentials = self._credentials.get(key)
                if is_auth_enabled() and not verify_token(
                    credentials['token'] if credentials else None
                ):
                    self._reject_connection(key)
                    return {'ok': False, 'error': 'Authentication required'}
                return handler(*args, **kwargs)

            register(authenticated)
            return authenticated

        return decorate
