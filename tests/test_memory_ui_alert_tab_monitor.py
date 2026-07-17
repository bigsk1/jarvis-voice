#!/usr/bin/env python3
"""Regression tests for the Memory UI browser-tab alert monitor."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MONITOR_JS = PROJECT_ROOT / "jarvis-memory" / "client" / "js" / "alert-tab-monitor.js"
APP_JS = PROJECT_ROOT / "jarvis-memory" / "client" / "js" / "app.js"
INDEX_HTML = PROJECT_ROOT / "jarvis-memory" / "client" / "index.html"


class MemoryUiAlertTabMonitorTests(unittest.TestCase):
    def test_monitor_baseline_new_alert_attention_and_sound_toggle(self) -> None:
        script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const source = fs.readFileSync(process.argv[1], 'utf8');
const sandbox = { window: {}, console, encodeURIComponent, Set, Promise };
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
const AlertTabMonitor = sandbox.window.AlertTabMonitor;

const listeners = {};
const favicon = { href: 'brain-favicon' };
const documentRef = {
  title: 'Jarvis Memory',
  hidden: true,
  hasFocus: () => false,
  querySelector: selector => selector === '#memoryFavicon' ? favicon : null,
  addEventListener: (name, handler) => { listeners[`document:${name}`] = handler; },
  removeEventListener: () => {}
};

const buttonListeners = {};
const button = {
  style: {},
  classList: { toggle: () => {} },
  addEventListener: (name, handler) => { buttonListeners[name] = handler; },
  removeEventListener: () => {},
  setAttribute: (name, value) => { button[name] = value; }
};

const storageValues = {};
const storage = {
  getItem: key => storageValues[key] || null,
  setItem: (key, value) => { storageValues[key] = value; }
};

let intervalId = 0;
const intervals = new Map();
let oscillatorStarts = 0;
class FakeAudioContext {
  constructor() {
    this.state = 'running';
    this.currentTime = 1;
    this.destination = {};
  }
  createOscillator() {
    return {
      frequency: { setValueAtTime() {}, exponentialRampToValueAtTime() {} },
      connect() {},
      start() { oscillatorStarts += 1; },
      stop() {}
    };
  }
  createGain() {
    return {
      gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} },
      connect() {}
    };
  }
  async resume() { this.state = 'running'; }
}

const windowRef = {
  localStorage: storage,
  AudioContext: FakeAudioContext,
  addEventListener: (name, handler) => { listeners[`window:${name}`] = handler; },
  removeEventListener: () => {},
  setInterval: handler => { const id = ++intervalId; intervals.set(id, handler); return id; },
  clearInterval: id => intervals.delete(id)
};

const responses = [
  [{ id: 10, title: 'Existing' }],
  [{ id: 11, title: 'New' }, { id: 10, title: 'Existing' }],
  [],
  [{ id: 12, title: 'Audible' }],
  []
];
const requests = [];
const changes = [];
const api = {
  async listAlerts(options) {
    requests.push(options);
    return { alerts: responses.shift() || [] };
  }
};

(async () => {
  const monitor = new AlertTabMonitor({
    api,
    documentRef,
    windowRef,
    storage,
    soundButton: button,
    onPendingChange: change => changes.push(change)
  });

  await monitor.init();
  assert.strictEqual(monitor.soundEnabled, true, 'alert sound defaults to enabled');
  assert.strictEqual(button.textContent, '🔔');
  assert.strictEqual(button['aria-pressed'], 'true');
  assert.strictEqual(monitor.pendingCount, 1);
  assert.strictEqual(monitor.attentionActive, false, 'existing alerts must be a silent baseline');
  assert.strictEqual(documentRef.title, '1 · Jarvis Memory');
  assert.strictEqual(changes.length, 0);
  assert.strictEqual(requests[0].status, 'pending');
  assert.strictEqual(requests[0].limit, 300);

  await monitor.check();
  assert.strictEqual(monitor.pendingCount, 2);
  assert.strictEqual(monitor.attentionActive, true);
  assert.strictEqual(documentRef.title, '2 NEW ALERTS');
  assert.strictEqual(changes.length, 1);
  assert.strictEqual(changes[0].newAlerts[0].id, 11);
  assert.strictEqual(oscillatorStarts, 1, 'a new alert batch should play one ding when sound is on');

  await monitor.check();
  assert.strictEqual(monitor.pendingCount, 0);
  assert.strictEqual(monitor.attentionActive, false, 'clearing all pending alerts must stop flashing');
  assert.strictEqual(documentRef.title, 'Jarvis Memory');
  assert.strictEqual(favicon.href, 'brain-favicon');

  await monitor.toggleSound();
  assert.strictEqual(monitor.soundEnabled, false);
  assert.strictEqual(storageValues['jarvis-memory-alert-sound'], 'false');
  assert.strictEqual(button.textContent, '🔕');
  assert.strictEqual(button['aria-pressed'], 'false');
  assert.strictEqual(oscillatorStarts, 1, 'disabling sound should not play a ding');

  await monitor.toggleSound();
  assert.strictEqual(monitor.soundEnabled, true);
  assert.strictEqual(storageValues['jarvis-memory-alert-sound'], 'true');
  assert.strictEqual(button.textContent, '🔔');
  assert.strictEqual(button['aria-pressed'], 'true');
  assert.strictEqual(oscillatorStarts, 2, 'enabling sound should play one test ding');

  monitor.setControlVisible(true);
  assert.strictEqual(button.style.display, 'inline-flex');

  await monitor.check();
  assert.strictEqual(monitor.pendingCount, 1);
  assert.strictEqual(monitor.attentionActive, true);
  assert.strictEqual(oscillatorStarts, 3, 'a new alert batch should play one ding');

  monitor.acknowledgeAttention();
  assert.strictEqual(documentRef.title, '1 · Jarvis Memory');

  await monitor.reset();
  assert.strictEqual(monitor.attentionActive, false, 'a mode reset must not create attention');
  monitor.destroy();
})().catch(error => {
  console.error(error);
  process.exit(1);
});
"""
        subprocess.run(
            ["node", "-e", script, str(MONITOR_JS)],
            cwd=PROJECT_ROOT,
            check=True,
        )

    def test_alert_sound_control_is_alerts_only_and_monitor_loads_before_app(self) -> None:
        html = INDEX_HTML.read_text(encoding="utf-8")
        sound_position = html.index('id="alertSoundToggleBtn"')
        refresh_position = html.index('id="refreshBtn"')
        monitor_position = html.index('/js/alert-tab-monitor.js')
        app_position = html.index('/js/app.js')

        self.assertLess(sound_position, refresh_position)
        self.assertIn('style="display: none;"', html[sound_position : sound_position + 250])
        self.assertLess(monitor_position, app_position)
        self.assertIn("<title>Jarvis Memory</title>", html)

    def test_alert_list_uses_server_filters_and_appends_older_pages(self) -> None:
        script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('async function loadAlerts');
const end = source.indexOf('async function loadStats', start);
assert(start >= 0 && end > start, 'loadAlerts source not found');

const requests = [];
const firstPage = Array.from({ length: 100 }, (_, index) => ({ id: index + 1 }));
const responses = [
  { alerts: firstPage, has_more: true, next_offset: 100 },
  { alerts: [{ id: 101 }], has_more: false, next_offset: 101 }
];
const sandbox = {
  console,
  Set,
  api: {
    async listAlerts(options) {
      requests.push(options);
      return responses.shift();
    }
  }
};
vm.createContext(sandbox);
vm.runInContext(`
  const ALERT_PAGE_SIZE = 100;
  let alertStatusFilter = 'pending';
  let alertSeverityFilter = 'high';
  let searchQuery = 'camera';
  let alertOffset = 0;
  let alertsHasMore = true;
  let alertsLoading = false;
  let alertLoadGeneration = 0;
  let alerts = [];
  let renderCount = 0;
  function renderAlerts() { renderCount += 1; }
  ${source.slice(start, end)}
`, sandbox);

(async () => {
  await vm.runInContext('loadAlerts()', sandbox);
  await vm.runInContext('loadAlerts({ append: true })', sandbox);
  const state = vm.runInContext('({ length: alerts.length, alertOffset, alertsHasMore, renderCount })', sandbox);

  assert.strictEqual(requests[0].status, 'pending');
  assert.strictEqual(requests[0].severity, 'high');
  assert.strictEqual(requests[0].search, 'camera');
  assert.strictEqual(requests[0].offset, 0);
  assert.strictEqual(requests[1].offset, 100);
  assert.strictEqual(state.length, 101);
  assert.strictEqual(state.alertOffset, 101);
  assert.strictEqual(state.alertsHasMore, false);
  assert.strictEqual(state.renderCount, 2);
})().catch(error => {
  console.error(error);
  process.exit(1);
});
"""
        subprocess.run(
            ["node", "-e", script, str(APP_JS)],
            cwd=PROJECT_ROOT,
            check=True,
        )

    def test_alert_route_reports_next_page_without_hiding_filtered_records(self) -> None:
        memory_root = str(PROJECT_ROOT / "jarvis-memory")
        if memory_root not in sys.path:
            sys.path.insert(0, memory_root)

        from flask import Flask
        from server.routes import alerts as alerts_route

        captured: dict[str, object] = {}

        class FakeAlertManager:
            def list_alerts(self, **kwargs):
                captured.update(kwargs)
                return [{"id": index} for index in range(kwargs["limit"])]

        original_get_manager = alerts_route.get_manager
        alerts_route.get_manager = lambda: FakeAlertManager()
        app = Flask(__name__)
        try:
            with app.test_request_context(
                "/api/alerts?status=pending&severity=high&search=camera&limit=2&offset=7"
            ):
                response = alerts_route.list_alerts()
                payload = response.get_json()
        finally:
            alerts_route.get_manager = original_get_manager

        self.assertEqual(captured["status"], "pending")
        self.assertEqual(captured["severity"], "high")
        self.assertEqual(captured["search"], "camera")
        self.assertEqual(captured["limit"], 3)
        self.assertEqual(captured["offset"], 7)
        self.assertEqual(len(payload["alerts"]), 2)
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["next_offset"], 9)


if __name__ == "__main__":
    unittest.main()
