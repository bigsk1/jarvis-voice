import test from 'node:test';
import assert from 'node:assert/strict';
import {requestMicrophone} from '../ui/microphone-client.js';

test('sidebar capture uses only the extension microphone tab and observes its closure', async () => {
  const url = 'moz-extension://test/ui/microphone.html';
  const view = {};
  const calls = [];
  let tabs = [];
  const originalNavigator = globalThis.navigator;
  globalThis.window = view;
  globalThis.browser = {runtime: {getURL: () => url}, windows: {getCurrent: async () => ({id: 4})},
    extension: {getViews: ({type, windowId}) => {if (type === 'sidebar') return [view];assert.equal(windowId, 4);return tabs;}}};
  Object.defineProperty(globalThis, 'navigator', {configurable: true, value: {mediaDevices: {getUserMedia: async c => {calls.push('direct'); return c;}}}});
  try {
    await assert.rejects(requestMicrophone({audio: true}), {name: 'NotAllowedError'});
    const controller = new AbortController();
    const close = () => {};
    const helper = {location: {href: url}, jarvisRequestMicrophone: async c => {calls.push(c); return 'stream';},
      addEventListener: (...args) => calls.push(args)};
    tabs = [{...helper, location: {href: 'https://unrelated.test'}}, helper];
    assert.equal(await requestMicrophone({audio: true}, {signal: controller.signal, onClosed: close}), 'stream');
    assert.deepEqual(calls, [['pagehide', close, {once: true, signal: controller.signal}], {audio: true}]);
    controller.abort();
    await assert.rejects(requestMicrophone({audio: true}, {signal: controller.signal}), {name: 'AbortError'});
    globalThis.window = {};
    assert.deepEqual(await requestMicrophone({audio: true}), {audio: true});
    assert.equal(calls.at(-1), 'direct', 'Full tabs and pop-outs keep native capture');
  } finally {
    delete globalThis.window; delete globalThis.browser;
    Object.defineProperty(globalThis, 'navigator', {configurable: true, value: originalNavigator});
  }
});
