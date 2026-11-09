"""Owned HTTP requests must be cancellable without changing their caller's session."""

import socket
import ssl
import time
from threading import Event

import pytest
import requests
from http_observation import SocketBudget, bounded_request
from urllib3.poolmanager import pool_classes_by_scheme


def test_owned_request_preserves_source_settings_without_sharing_mutable_state(monkeypatch):
    source = requests.Session()

    def hook(response, **kwargs):
        return response

    source.headers['X-Source'] = 'one'
    source.cookies.set('source-cookie', 'one')
    source.proxies = {'https': 'http://proxy.invalid:8080'}
    source.params = {'scope': ['original']}
    source.hooks = {'response': [hook]}
    source.auth = ('operator', 'credential')
    source.verify = '/tmp/test-ca.pem'
    source.cert = ('/tmp/test-cert.pem', '/tmp/test-key.pem')
    source.trust_env = False
    source.max_redirects = 7
    original_adapters = dict(source.adapters)
    original_pools = dict(pool_classes_by_scheme)
    observed = []

    def request(owned, method, url, **kwargs):
        assert owned is not source
        assert owned.auth == source.auth
        assert owned.verify == source.verify
        assert owned.cert == source.cert
        assert owned.trust_env is False
        assert owned.max_redirects == 7
        assert owned.hooks['response'][0] is hook
        observed.append((method, url))
        owned.headers['X-Added'] = 'two'
        owned.cookies.set('added-cookie', 'two')
        owned.cookies.set('source-cookie', 'updated')
        owned.proxies['http'] = 'http://another.invalid:8080'
        owned.params['scope'].append('added')
        owned.hooks['response'].append(lambda response, **kwargs: response)
        response = requests.Response()
        response.status_code = 200
        response._content = b'completed'
        response._content_consumed = True
        return response

    monkeypatch.setattr(requests.Session, 'request', request)
    cancelled = Event()
    try:
        response = bounded_request('GET', 'https://fixture.invalid/',
                                   deadline=time.monotonic() + 2,
                                   cancel_event=cancelled, source_session=source)
        assert response.content == b'completed'
        assert observed == [('GET', 'https://fixture.invalid/')]
        assert 'X-Added' not in source.headers
        assert source.cookies.get('added-cookie') is None
        assert source.cookies.get('source-cookie') == 'one'
        assert source.proxies == {'https': 'http://proxy.invalid:8080'}
        assert source.params == {'scope': ['original']}
        assert source.hooks == {'response': [hook]}
        assert source.adapters == original_adapters
        assert pool_classes_by_scheme == original_pools
        assert not cancelled.is_set()
    finally:
        source.close()


@pytest.mark.parametrize('track_before_tls', [True, False])
def test_cancellation_shutdown_survives_tls_socket_wrapper_detachment(track_before_tls):
    raw, peer = socket.socketpair()
    wrapped = None
    cancelled = Event()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with SocketBudget(time.monotonic() + 2, cancelled) as budget:
        try:
            if track_before_tls:
                budget.track_socket(raw)
            wrapped = context.wrap_socket(raw, server_hostname='fixture.invalid',
                                          do_handshake_on_connect=False)
            if not track_before_tls:
                budget.track_socket(wrapped)
            budget.cancel()
            peer.settimeout(.5)
            assert peer.recv(1) == b''
            assert cancelled.is_set()
        finally:
            if wrapped is not None:
                wrapped.close()
            raw.close()
            peer.close()


def test_normal_close_keeps_shared_cancel_event_usable_for_the_next_request():
    cancelled = Event()
    for _ in range(2):
        local, peer = socket.socketpair()
        try:
            with SocketBudget(time.monotonic() + 2, cancelled) as budget:
                budget.track_socket(local)
                local.sendall(b'one')
                assert peer.recv(3) == b'one'
            assert not cancelled.is_set()
            peer.settimeout(.5)
            assert peer.recv(1) == b''
        finally:
            local.close()
            peer.close()
