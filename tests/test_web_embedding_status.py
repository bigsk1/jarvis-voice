"""Runtime coverage for embedding status delivery and browser toast behavior."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "jarvis-web"))

from server_package_utils import load_server_package  # noqa: E402

load_server_package("jarvis_web_embedding_test", ROOT / "jarvis-web/server")

from embeddings import EmbeddingRuntimeError, get_embedding  # noqa: E402
from jarvis_web_embedding_test import config as web_config  # noqa: E402
from jarvis_web_embedding_test.sockets.chat import ChatHandler, _scoped_by_mode  # noqa: E402


def test_embedding_failures_emit_once_to_the_request_conversation():
    class Socket:
        def __init__(self):
            self.events = []

        def emit(self, event, payload, **kwargs):
            self.events.append((event, payload, kwargs))

    class Handler(ChatHandler):
        @_scoped_by_mode
        def request(self, session_id, mode, message_id, conversation_id):
            for _ in range(2):
                with pytest.raises(EmbeddingRuntimeError):
                    get_embedding("find a tool")

    handler = Handler.__new__(Handler)
    handler.socketio = Socket()
    with patch.object(web_config, "load_web_config", return_value={}), patch(
        "embeddings._resolve_embedding_runtime", side_effect=EmbeddingRuntimeError("hosts down")
    ):
        handler.request("session-a", "cloud", "message-a", "conversation-a")
        handler.request("session-b", "local", "message-b", "conversation-b")
        with pytest.raises(EmbeddingRuntimeError):
            get_embedding("outside a Web request")

    assert handler.socketio.events == [
        ("embedding:status", {
            "message_id": "message-a", "conversation_id": "conversation-a", "status": "unavailable",
        }, {"room": "conversation:conversation-a"}),
        ("embedding:status", {
            "message_id": "message-b", "conversation_id": "conversation-b", "status": "unavailable",
        }, {"room": "conversation:conversation-b"}),
    ]


def test_browser_forwards_status_deduplicates_and_ignores_other_conversations():
    script = r"""
const fs = require('fs');
const assert = require('assert');
let source = fs.readFileSync('jarvis-web/client/js/socket.js', 'utf8');
eval(source.slice(0, source.indexOf('// Create global instance')) + '\nglobal.JarvisSocket = JarvisSocket;');
source = fs.readFileSync('jarvis-web/client/js/chat.js', 'utf8');
eval(source.slice(source.indexOf('class ChatUI'), source.indexOf('// Create global instance')) + '\nglobal.ChatUI = ChatUI;');

const socketHandlers = {};
const chatHandlers = {};
const toasts = [];
const socket = Object.create(JarvisSocket.prototype);
socket.socket = {on: (event, handler) => {socketHandlers[event] = handler;}};
socket._emit = (event, data) => chatHandlers[event]?.(data);
socket.on = (event, handler) => {chatHandlers[event] = handler;};
socket.conversationId = 'conversation-a';
global.window = {jarvisSocket: socket};
global.Utils = {toast: (...args) => toasts.push(args)};
socket._setupEventHandlers();
const chat = Object.create(ChatUI.prototype);
chat._setupSocketListeners();
const event = {conversation_id: 'conversation-a', message_id: 'message-a', status: 'fallback'};
socketHandlers['embedding:status'](event);
socketHandlers['embedding:status'](event);
socketHandlers['embedding:status']({...event, conversation_id: 'conversation-b'});
socketHandlers['embedding:status']({...event, status: 'healthy'});
assert.strictEqual(toasts.length, 1);
assert.match(toasts[0][0], /fallback embedding host/);
assert.match(toasts[0][0], /semantic search is working/);
socketHandlers['embedding:status']({...event, status: 'unavailable'});
assert.strictEqual(toasts.length, 2);
assert.match(toasts[1][0], /semantic retrieval may be limited/);
socketHandlers['embedding:status']({...event, message_id: 'message-b'});
assert.strictEqual(toasts.length, 3);
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)
