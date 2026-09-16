import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../ui/microphone.js', import.meta.url), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
function harness(active = 1) {
  const events = {}, button = {addEventListener: (event, handler) => {events[event] = handler;}}, status = {};
  const requests = [], updates = [];
  const window = {addEventListener: (event, handler) => {events[event] = handler;}};
  const context = {window, DOMException, document: {getElementById: id => id === 'allow-microphone' ? button : status},
    navigator: {mediaDevices: {getUserMedia: () => new Promise(resolve => requests.push(resolve))}},
    browser: {tabs: {getCurrent: async () => ({id: 2, windowId: 5}), query: async () => [{id: active}],
      update: async id => {updates.push(id); active = id;}}}};
  vm.runInNewContext(source, context);
  const track = {readyState: 'live', stop() {this.readyState = 'ended';}};
  const stream = {getTracks: () => [track]};
  return {window, events, button, status, requests, updates, track, stream, select: id => {active = id;}, active: () => active};
}

test('permission check releases capture and tells the user to keep the helper open', async () => {
  const h = harness(2), pending = h.events.click(); await tick();
  assert.equal(h.button.disabled, true);assert.match(h.status.textContent, /Firefox microphone prompt/);
  h.requests[0](h.stream);await pending;
  assert.equal(h.track.readyState, 'ended');assert.match(h.status.textContent, /Keep this tab open/);
  assert.deepEqual(h.updates, []);assert.equal(h.button.disabled, false);
});

test('sidebar microphone startup selects the helper then restores the prior tab', async () => {
  const h = harness(), pending = h.window.jarvisRequestMicrophone({audio: true});await tick();
  assert.equal(h.active(), 2);h.requests[0](h.stream);assert.equal(await pending, h.stream);
  assert.deepEqual(h.updates, [2, 1]);assert.equal(h.track.readyState, 'live');
  h.events.pagehide();assert.equal(h.track.readyState, 'ended');
});

test('a tab selected by the user during permission setup is left selected', async () => {
  const h = harness(), pending = h.window.jarvisRequestMicrophone({audio: true});await tick();
  h.select(3);h.requests[0](h.stream);await pending;
  assert.equal(h.active(), 3);assert.deepEqual(h.updates, [2]);h.events.pagehide();
});

test('ending Talk during permission setup restores the tab and releases a late grant', async () => {
  const h = harness(), controller = new AbortController();
  const pending = h.window.jarvisRequestMicrophone({audio: true}, {signal: controller.signal});await tick();
  controller.abort();await tick();assert.equal(h.active(), 1);
  h.requests[0](h.stream);await assert.rejects(pending, {name: 'AbortError'});
  assert.equal(h.track.readyState, 'ended');
});

test('closing the helper during a permission request cannot leak its late microphone stream', async () => {
  const h = harness(), pending = h.window.jarvisRequestMicrophone({audio: true});await tick();
  h.events.pagehide();h.requests[0](h.stream);await assert.rejects(pending, {name: 'AbortError'});
  assert.equal(h.track.readyState, 'ended');
});
