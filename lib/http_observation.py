"""Request-owned HTTP sockets that can be stopped during headers or body reads.

This module is standalone so the optional Google service can bundle the same
cleanup primitive. It uses the installed requests/urllib3 connection and adapter
interfaces; it changes no global pools, socket defaults, or source sessions.
"""

from __future__ import annotations

import copy
import math
import socket
import threading
import time
from contextvars import ContextVar

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

_owner = ContextVar('http_socket_owner', default=None)


def _track(sock):
    owner = _owner.get()
    if owner is not None:
        owner.track_socket(sock)


class _TrackedHTTPConnection(HTTPConnection):
    def _new_conn(self):
        sock = super()._new_conn()
        _track(sock)
        return sock


class _TrackedHTTPSConnection(HTTPSConnection):
    def _new_conn(self):
        sock = super()._new_conn()
        # Keep a duplicate before TLS can detach the original socket object.
        _track(sock)
        return sock


class _TrackedHTTPPool(HTTPConnectionPool):
    ConnectionCls = _TrackedHTTPConnection


class _TrackedHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _TrackedHTTPSConnection


class _TrackedAdapter(HTTPAdapter):
    @staticmethod
    def _track_pools(manager):
        # urllib3's defaults are shared; assign a private mapping on this manager.
        manager.pool_classes_by_scheme = {**manager.pool_classes_by_scheme,
            'http': _TrackedHTTPPool, 'https': _TrackedHTTPSPool}

    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self._track_pools(self.poolmanager)

    def proxy_manager_for(self, proxy, **kwargs):
        manager = super().proxy_manager_for(proxy, **kwargs)
        self._track_pools(manager)
        return manager


def _copy_session(source):
    session = requests.Session()
    if source is None:
        return session
    session.headers = source.headers.copy()
    session.cookies = copy.deepcopy(source.cookies)
    session.proxies = source.proxies.copy()
    session.params = copy.deepcopy(source.params)
    session.hooks = {name: list(callbacks) for name, callbacks in source.hooks.items()}
    for name in ('auth', 'verify', 'cert', 'stream', 'trust_env', 'max_redirects'):
        setattr(session, name, getattr(source, name))
    return session


def _duplicate_socket(sock):
    try:
        return sock.dup()
    except NotImplementedError:
        # SSLSocket rejects .dup(), but a plain duplicate owns the same TCP
        # connection and shutdown interrupts its TLS/header/body read as well.
        descriptor = socket.dup(sock.fileno())
        try:
            return socket.socket(sock.family, sock.type, sock.proto, fileno=descriptor)
        except Exception:
            socket.close(descriptor)
            raise


class SocketBudget:
    """Own connections until a finite deadline, explicit cancel, or normal close.

    ``session_factory(source_session)`` is an optional transport-injection seam.
    It must return an independently owned session supporting mount/request/close.
    A source session is otherwise cloned, preserving headers, cookies, proxy/TLS
    configuration and auth without mutating its adapters or retry policy.
    """

    def __init__(self, deadline, cancel_event=None, *, clock=time.monotonic):
        if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
            raise ValueError('An HTTP observation requires a finite monotonic deadline')
        self.deadline = deadline
        self.cancelled = cancel_event if cancel_event is not None else threading.Event()
        self.clock = clock
        self._done = threading.Event()
        self._lock = threading.Lock()
        self._sockets = {}
        self._session = None
        self._watcher = None
        self._closed = False

    def _watch(self):
        while not self._done.is_set():
            remaining = self.deadline - self.clock()
            if self.cancelled.is_set() or remaining <= 0:
                self.cancel()
                return
            self._done.wait(min(.05, remaining))

    def _start(self):
        with self._lock:
            if self._watcher is None and not self._closed:
                self._watcher = threading.Thread(target=self._watch, name='http-socket-budget', daemon=True)
                self._watcher.start()

    @staticmethod
    def _shutdown(sockets):
        # Response.close() may wait on a buffered reader's lock in another
        # thread. Socket shutdown takes no such lock and wakes that reader.
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            finally:
                try:
                    sock.close()
                except OSError:
                    pass

    def _check(self):
        if self._closed or self.cancelled.is_set() or self.clock() >= self.deadline:
            if not self._closed:
                self.cancel()
            raise requests.exceptions.Timeout('The HTTP observation deadline or ownership ended')

    def track_socket(self, sock):
        if sock is None or sock.fileno() < 0:
            return
        self._start()
        with self._lock:
            if id(sock) in self._sockets:
                return
            duplicate = _duplicate_socket(sock)
            stopped = self._closed or self.cancelled.is_set() or self.clock() >= self.deadline
            if not stopped:
                # Retain the original wrapper too, so Python cannot reuse its
                # object identity for another connection during this budget.
                self._sockets[id(sock)] = (sock, duplicate)
        if stopped:
            self._shutdown([duplicate])
            self._check()

    def request(self, method, url, *, source_session=None, session_factory=None, **kwargs):
        self._check()
        self._start()
        if self._session is None:
            session = session_factory(source_session) if session_factory else _copy_session(source_session)
            adapter = _TrackedAdapter(max_retries=0)
            session.mount('http://', adapter)
            session.mount('https://', adapter)
            self._session = session
        token = _owner.set(self)
        try:
            self._check()
            return self._session.request(method, url, **kwargs)
        finally:
            _owner.reset(token)

    def cancel(self):
        self.cancelled.set()
        self._done.set()
        with self._lock:
            sockets, self._sockets = [pair[1] for pair in self._sockets.values()], {}
        self._shutdown(sockets)

    def close(self):
        self._done.set()
        with self._lock:
            self._closed = True
            sockets, self._sockets = [pair[1] for pair in self._sockets.values()], {}
        self._shutdown(sockets)
        if self._session is not None:
            self._session.close()
        if self._watcher is not None and self._watcher is not threading.current_thread():
            self._watcher.join(timeout=.2)
        # Do not set a caller-owned cancellation event on normal completion.

    def __enter__(self):
        self._check()
        self._start()
        return self

    def __exit__(self, *_exception):
        self.close()


def bounded_request(method, url, *, deadline, cancel_event=None, source_session=None,
                    session_factory=None, clock=time.monotonic, **kwargs):
    """Read one complete response while its headers/body remain cancellable."""
    with SocketBudget(deadline, cancel_event, clock=clock) as budget:
        response = budget.request(method, url, source_session=source_session,
                                  session_factory=session_factory, **kwargs)
        try:
            _ = response.content
            return response
        finally:
            response.close()
