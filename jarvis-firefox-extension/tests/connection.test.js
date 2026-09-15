import test from 'node:test';
import assert from 'node:assert/strict';
import {assertCapabilities, normalizeServerUrl, originPermission, pageTextSupported} from '../core/connection.js';

test('server connections default to HTTPS with explicit local HTTP exception', () => {
  assert.equal(normalizeServerUrl('https://jarvis.example:5001/'), 'https://jarvis.example:5001');
  for (const url of ['http://127.0.0.1:5001', 'http://192.168.1.2:5001', 'http://[::1]:5001']) {
    assert.throws(() => normalizeServerUrl(url));
    assert.equal(normalizeServerUrl(url, {allowInsecureLocal: true}), url);
  }
  for (const url of ['http://public.example', 'http://8.8.8.8', 'file:///tmp/app', 'https://user:password@jarvis.example',
    'https://jarvis.example/?token=secret', 'https://jarvis.example/proxy', 'https://jarvis.example/#secret']) {
    assert.throws(() => normalizeServerUrl(url, {allowInsecureLocal: true}));
  }
  assert.equal(originPermission('https://jarvis.example:5001'), 'https://jarvis.example/*');
});

test('companion contract requires chat recovery and authenticated sockets; page text is optional', () => {
  const features = {chat: true, images: true, conversations: true, recovery: true, cancel: true};
  assert.equal(assertCapabilities({features: {auth: false}, extension: {api: 1, socket_auth: true, features}}).api, 1);
  assert.equal(pageTextSupported({extension: {features: {...features, text: true}}}), true);
  assert.equal(pageTextSupported({extension: {features}}), false);
  assert.throws(() => assertCapabilities({features: {auth: false}, extension: {api: 1, socket_auth: true,
    features: {...features, cancel: false}}}), /Companion API 1/);
});
