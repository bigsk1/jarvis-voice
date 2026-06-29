#!/usr/bin/env python3
"""Regression test for Jarvis Web proactive Socket.IO event forwarding."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOCKET_JS = PROJECT_ROOT / "jarvis-web" / "client" / "js" / "socket.js"
PROACTIVE_JS = PROJECT_ROOT / "jarvis-web" / "client" / "js" / "proactive.js"
APP_JS = PROJECT_ROOT / "jarvis-web" / "client" / "js" / "app.js"
CHAT_SOCKET_PY = PROJECT_ROOT / "jarvis-web" / "server" / "sockets" / "chat.py"


class WebProactiveSocketTests(unittest.TestCase):
    def test_proactive_events_reach_wrapper_listeners(self) -> None:
        script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const source = fs.readFileSync(process.argv[1], 'utf8');
const rawHandlers = {};
const rawSocket = {
  on(event, callback) { rawHandlers[event] = callback; },
  emit() {},
  disconnect() {}
};
const storageValues = {};
const sandbox = {
  console,
  io: () => rawSocket,
  Utils: {
    storage: {
      get: (key, fallback) => storageValues[key] ?? fallback,
      set: (key, value) => { storageValues[key] = value; }
    }
  },
  window: {
    location: { protocol: 'http:', host: 'localhost:5001' }
  }
};

vm.createContext(sandbox);
vm.runInContext(source, sandbox);

const socket = sandbox.window.jarvisSocket;
const events = [
  'proactive:counts',
  'proactive:alert',
  'proactive:reminder',
  'proactive:ack_success',
  'proactive:error'
];
const received = {};
events.forEach(event => socket.on(event, data => { received[event] = data.marker; }));

socket.connect();

events.forEach(event => {
  assert.strictEqual(typeof rawHandlers[event], 'function', `${event} must be registered on Socket.IO`);
  rawHandlers[event]({ marker: event });
  assert.strictEqual(received[event], event, `${event} must reach the wrapper listener`);
});
"""
        subprocess.run(
            ["node", "-e", script, str(SOCKET_JS)],
            cwd=PROJECT_ROOT,
            check=True,
        )

    def test_proactive_tts_is_limited_to_docker_deployments(self) -> None:
        script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const source = fs.readFileSync(process.argv[1], 'utf8');
const sandbox = { window: {}, console };
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
const ProactiveManager = sandbox.window.ProactiveManager;

function createManager(deployment) {
  const spoken = [];
  const manager = Object.create(ProactiveManager.prototype);
  manager.alerts = [];
  manager.reminders = [];
  manager.counts = { alerts: 0, reminders: 0 };
  manager.app = {
    deployment,
    audioEnabled: true,
    _generateAndPlayTTS: text => spoken.push(text)
  };
  manager._addToPanel = () => {};
  manager._showBrowserNotification = () => {};
  manager._updateBadge = () => {};
  manager._flashBadge = () => {};
  return { manager, spoken };
}

const docker = createManager('docker');
docker.manager._handleNewAlert({ id: 1, title: 'Service down', description: 'API unavailable' });
docker.manager._handleNewReminder({ id: 2, title: 'Check backup', description: '' });
assert.strictEqual(docker.spoken.length, 2, 'Docker proactive events should use browser TTS');

const native = createManager('native');
native.manager._handleNewAlert({ id: 3, title: 'Service down', description: '' });
native.manager._handleNewReminder({ id: 4, title: 'Check backup', description: '' });
assert.strictEqual(native.spoken.length, 0, 'Native proactive events must keep the local speaker path only');

const mutedDocker = createManager('docker');
mutedDocker.manager.app.audioEnabled = false;
mutedDocker.manager._handleNewReminder({ id: 5, title: 'Muted', description: '' });
assert.strictEqual(mutedDocker.spoken.length, 0, 'The Jarvis Web TTS toggle must still be respected');
"""
        subprocess.run(
            ["node", "-e", script, str(PROACTIVE_JS)],
            cwd=PROJECT_ROOT,
            check=True,
        )

    def test_session_handshake_sets_deployment_before_proactive_manager(self) -> None:
        app_source = APP_JS.read_text(encoding="utf-8")
        chat_source = CHAT_SOCKET_PY.read_text(encoding="utf-8")

        assignment = "this.deployment = data.deployment === 'docker' ? 'docker' : 'native';"
        manager_creation = "this.proactive = new ProactiveManager(this.socket, this);"
        self.assertIn("'deployment': (", chat_source)
        self.assertIn("JARVIS_DEPLOYMENT", chat_source)
        self.assertLess(app_source.index(assignment), app_source.index(manager_creation))


if __name__ == "__main__":
    unittest.main()
