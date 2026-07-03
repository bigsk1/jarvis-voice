"""Interim Werkzeug WebSocket teardown shim for Jarvis Web.

Why this exists
---------------
Jarvis Web serves Flask-SocketIO in ``threading`` mode through Werkzeug.
On a WebSocket request, Engine.IO's threading driver
(``engineio.async_drivers._websocket_wsgi.SimpleWebSocketWSGI``) hijacks the
raw socket from ``environ['werkzeug.socket']`` and runs the whole Socket.IO
session on it, so ``start_response`` is never called. When the browser closes
the socket (tab switch, navigation between Jarvis UIs), the WSGI call
returns, Werkzeug tries to flush a normal HTTP response, and logs a false
HTTP 500:

    AssertionError: write() before start_response

The driver special-cases only Gunicorn (it raises ``StopIteration`` so the
worker skips the response flush) and has no equivalent branch for Werkzeug.
Werkzeug's request loop, however, treats ``ConnectionError`` as "client
dropped the connection" (``connection_dropped_errors`` in
``werkzeug/serving.py``) and discards it silently. Raising it after a
completed WebSocket session therefore suppresses only this teardown path.
For comparison, Flask-Sock avoids the same assertion differently: it returns
a custom response object that drives Werkzeug's normal ``start_response``
path. Both approaches are valid; ``ConnectionError`` is the smaller change
for code we do not own.

Private-dependency warning
--------------------------
This shim patches a private Engine.IO module. A future python-engineio
upgrade may move or fix it; ``tests/test_werkzeug_websocket_teardown.py``
contains a canary test that fails when upstream no longer reproduces the
traceback, which is the signal to delete this module.
Issue: https://github.com/miguelgrinberg/python-engineio/issues/457

Removal conditions (either is sufficient)
-----------------------------------------
1. Jarvis Web normal launches move off Werkzeug (see
   ``docs/personal/Gunicorn_Upgrade.md``); Werkzeug then only serves the
   explicit ``--debug`` path and the noise is a non-issue.
2. python-engineio handles the ``werkzeug`` mode teardown itself (upstream
   report drafted in
   ``docs/personal/upstream-engineio-werkzeug-teardown.md``).
"""

_SENTINEL = '_jarvis_werkzeug_teardown_shim'


def apply_werkzeug_ws_teardown_shim() -> bool:
    """Patch Engine.IO's threading WebSocket driver for clean Werkzeug teardown.

    Idempotent: repeated calls (module reloads, tests) patch at most once.
    Returns True if the patch was applied by this call, False if it was
    already in place.
    """
    from engineio.async_drivers import _websocket_wsgi as eio_ws

    cls = eio_ws.SimpleWebSocketWSGI
    if getattr(cls, _SENTINEL, False):
        return False

    orig_call = cls.__call__

    def _call_with_werkzeug_teardown(self, environ, start_response):
        ret = orig_call(self, environ, start_response)
        ws = getattr(self, 'ws', None)
        if ws is not None and ws.mode == 'werkzeug':
            # Werkzeug catches ConnectionError as a dropped client and skips
            # the write()-before-start_response flush for the hijacked socket.
            raise ConnectionError(
                'WebSocket session ended (Jarvis Werkzeug teardown shim)')
        return ret

    _call_with_werkzeug_teardown.__wrapped__ = orig_call
    cls.__call__ = _call_with_werkzeug_teardown
    setattr(cls, _SENTINEL, True)
    return True
