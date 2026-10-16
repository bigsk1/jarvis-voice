#!/usr/bin/env python3
"""Regression test for Jarvis Web proactive Socket.IO event forwarding."""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOCKET_JS = PROJECT_ROOT / "jarvis-web" / "client" / "js" / "socket.js"
PROACTIVE_JS = PROJECT_ROOT / "jarvis-web" / "client" / "js" / "proactive.js"
APP_JS = PROJECT_ROOT / "jarvis-web" / "client" / "js" / "app.js"
CHAT_SOCKET_PY = PROJECT_ROOT / "jarvis-web" / "server" / "sockets" / "chat.py"


class WebProactiveSocketTests(unittest.TestCase):
    def test_reminder_panel_displays_stored_utc_in_browser_local_time(self) -> None:
        script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const lists = {
  '.alerts-list': { items: [], replaceChildren() { this.items = []; },
    appendChild(item) { this.items.push(item); } },
  '.reminders-list': { items: [], replaceChildren() { this.items = []; },
    appendChild(item) { this.items.push(item); } }
};
const sandbox = {
  window: {}, console,
  document: { createElement: () => ({ dataset: {},
    querySelector: () => ({ addEventListener() {} }) }) },
  Utils: { escapeHtml: value => String(value) }
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), sandbox);
const manager = Object.create(sandbox.window.ProactiveManager.prototype);
manager.panel = { querySelector: selector => lists[selector] };
manager.alerts = [];
manager.reminders = [];
manager.counts = { alerts: 0, reminders: 0 };
manager._updateBadge = () => {};
manager._showBrowserNotification = () => {};
manager._shouldPlayBrowserTTS = () => false;
manager._flashBadge = () => {};
const cases = [
  ['2026-10-16T19:00:00', '2026-10-16T19:00:00Z'],
  ['2026-10-16 19:00:00', '2026-10-16T19:00:00Z'],
  ['2026-10-16T19:00:00.123456', '2026-10-16T19:00:00.123Z'],
  ['2026-10-16T19:00:00Z', '2026-10-16T19:00:00Z'],
  ['2026-10-16T19:00:00+00:00', '2026-10-16T19:00:00Z'],
  ['2026-10-16T19:00:00+0000', '2026-10-16T19:00:00Z'],
  ['2026-10-16T12:00:00-07:00', '2026-10-16T19:00:00Z'],
  ['2026-01-16T20:00:00', '2026-01-16T20:00:00Z'],
  ['', null], [null, null], ['not-a-timestamp', null]
];
for (const [index, [trigger_time, expectedUtc]] of cases.entries()) {
  const reminder = { id: index + 1, title: 'Review checklist',
    description: 'The planning session starts at 2pm.', trigger_time,
    triggered_at: '2026-10-16T19:00:31+00:00',
    created_at: '2026-10-15T19:00:00+00:00' };
  for (const route of ['new event', 'saved snapshot']) {
    manager.alerts = [];
    manager.reminders = [];
    lists['.reminders-list'].replaceChildren();
    if (route === 'new event') manager._handleNewReminder(reminder);
    else manager._applySnapshot({ alerts: [], reminders: [reminder] });
    assert.strictEqual(lists['.reminders-list'].items.length, 1);
    const html = lists['.reminders-list'].items.at(-1).innerHTML;
    const time = html.match(/<span class="time"[^>]*>([^<]*)<\/span>/)?.[1];
    const expected = expectedUtc ? new Date(expectedUtc).toLocaleString() : undefined;
    assert.strictEqual(time, expected, `${route}: ${trigger_time}`);
    assert(html.includes(reminder.title));
    assert(html.includes(reminder.description));
    assert(!html.includes('Invalid Date'));
  }
}
const localNoon = new Date('2026-10-16T19:00:00Z');
assert.strictEqual(localNoon.getHours(), process.argv[2] === 'America/Los_Angeles' ? 12 : 15);
"""
        for timezone in ("America/Los_Angeles", "America/New_York"):
            with self.subTest(timezone=timezone):
                result = subprocess.run(
                    ["node", "-e", script, str(PROACTIVE_JS), timezone],
                    cwd=PROJECT_ROOT,
                    env={"PATH": os.environ.get("PATH", os.defpath), "TZ": timezone},
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

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
  'proactive:snapshot',
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

    def test_pending_snapshot_restores_panel_without_repeating_new_alert_actions(self) -> None:
        script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const sandbox = { window: {}, console };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), sandbox);
const manager = Object.create(sandbox.window.ProactiveManager.prototype);
const lists = {
  '.alerts-list': { items: [], replaceChildren() { this.items = []; } },
  '.reminders-list': { items: [], replaceChildren() { this.items = []; } }
};
const notifications = [];
manager.panel = { querySelector: selector => lists[selector] };
manager.alerts = [];
manager.reminders = [];
manager.counts = { alerts: 0, reminders: 0 };
manager._addToPanel = (type, item) => {
  lists[type === 'alert' ? '.alerts-list' : '.reminders-list'].items.push(item);
};
manager._updateBadge = () => {};
manager._showBrowserNotification = (...args) => notifications.push(args);
manager._shouldPlayBrowserTTS = () => false;
manager._flashBadge = () => {};
const alert = { id: 41, title: 'Weather watch' };
const reminder = { id: 73, title: 'Review backup' };

manager._applySnapshot({
  alerts: [alert], reminders: [reminder], counts: { alerts: 1, reminders: 1 }
});
assert.strictEqual(lists['.alerts-list'].items.length, 1);
assert.strictEqual(lists['.reminders-list'].items.length, 1);
assert.strictEqual(manager.counts.alerts, 1);
assert.strictEqual(notifications.length, 0, 'restored items must not fire OS notifications');

manager._handleNewAlert(alert);
assert.strictEqual(lists['.alerts-list'].items.length, 1);
assert.strictEqual(notifications.length, 0, 'a repeated event must not notify twice');

manager._handleNewAlert({ id: 42, title: 'New alert' });
assert.strictEqual(lists['.alerts-list'].items.length, 2);
assert.strictEqual(manager.counts.alerts, 2);
assert.strictEqual(notifications.length, 1);

manager._applySnapshot({
  alerts: [alert], reminders: [], counts: { alerts: 1, reminders: 0 }
});
assert.strictEqual(lists['.alerts-list'].items.length, 1, 'refresh must reconcile removed items');
assert.strictEqual(lists['.reminders-list'].items.length, 0);

let rendered;
sandbox.document = { createElement: () => ({
  dataset: {}, querySelector: () => ({ addEventListener() {} })
}) };
sandbox.Utils = { escapeHtml: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;') };
const safePanel = { querySelector: () => ({ appendChild: item => { rendered = item.innerHTML; } }) };
sandbox.window.ProactiveManager.prototype._addToPanel.call(
  { panel: safePanel, _acknowledge() {} }, 'alert',
  { id: 44, title: 'Weather', source: '<img src=x>', severity: '<script>' }
);
assert(rendered.includes('&lt;img src=x>'), 'stored alert source must be escaped');
assert(!rendered.includes('severity-<script>'), 'invalid severity must not enter a CSS class');
"""
        subprocess.run(
            ["node", "-e", script, str(PROACTIVE_JS)],
            cwd=PROJECT_ROOT,
            check=True,
        )

    def test_browser_notification_permission_waits_for_explicit_click(self) -> None:
        script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const nodes = {};
for (const selector of ['.notification-permission', '.notification-permission-btn',
  '.notification-permission-status', '.close-panel-btn', '.refresh-btn', '.ack-all-btn']) {
  nodes[selector] = {hidden: false, listeners: {}, addEventListener(event, action) {
    this.listeners[event] = action;
  }};
}
const panel = {style: {}, querySelector: selector => nodes[selector]};
const settingsButton = {};
const header = {
  inserted: null,
  querySelector: selector => selector === '#settingsBtn' ? settingsButton : null,
  insertBefore(node, before) { this.inserted = {node, before}; }
};
const bellButton = {listeners: {}, addEventListener(event, action) {
  this.listeners[event] = action;
}};
const badgeContainer = {querySelector: selector => selector === '.notification-badge-btn'
  ? bellButton : {style: {}}};
let created = 0;
const document = {
  body: {appendChild() {}},
  createElement: () => ++created === 1 ? badgeContainer : panel,
  querySelector: selector => selector === '.header-right' ? header : null,
  addEventListener() {}
};
let requests = 0;
let inClick = false;
const Notification = {
  permission: 'default',
  requestPermission() {
    requests++;
    assert(inClick, 'permission must be requested synchronously in the click handler');
    this.permission = 'granted';
    return Promise.resolve('granted');
  }
};
const sandbox = {
  window: {Notification, isSecureContext: true}, Notification, document, console,
  setInterval: () => 1, clearInterval() {}
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), sandbox);
const manager = new sandbox.window.ProactiveManager({on() {}, emit() {}}, {});
assert.strictEqual(requests, 0, 'startup must not ask the browser for permission');
assert.strictEqual(header.inserted?.node, badgeContainer, 'the bell must mount in the visible header');
assert.strictEqual(header.inserted?.before, settingsButton, 'the bell should sit before Settings');
assert.match(badgeContainer.innerHTML, /class="icon-btn notification-badge-btn"/);
bellButton.listeners.click();
assert.strictEqual(panel.style.display, 'flex', 'the bell must open the notification panel');
assert.strictEqual(nodes['.notification-permission-btn'].hidden, false);

(async () => {
  inClick = true;
  nodes['.notification-permission-btn'].listeners.click();
  inClick = false;
  await new Promise(resolve => setImmediate(resolve));
  assert.strictEqual(requests, 1);
  assert.strictEqual(manager.notificationPermission, 'granted');
  assert.strictEqual(nodes['.notification-permission'].hidden, true);

  Notification.permission = 'denied';
  manager._syncNotificationPermission();
  assert.strictEqual(nodes['.notification-permission-btn'].hidden, true);
  assert.match(nodes['.notification-permission-status'].textContent, /blocked/);

  Notification.permission = 'default';
  sandbox.window.isSecureContext = false;
  manager._syncNotificationPermission();
  assert.strictEqual(nodes['.notification-permission-btn'].hidden, true);
  assert.match(nodes['.notification-permission-status'].textContent, /secure connection/);
})().catch(error => { console.error(error); process.exit(1); });
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
