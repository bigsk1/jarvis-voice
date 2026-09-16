import test from 'node:test';
import assert from 'node:assert/strict';
import {assertCapabilities, normalizeServerUrl, originPermission, pageTextSupported} from '../core/connection.js';

test('server connections default to HTTPS with an explicit loopback HTTP exception', () => {
  assert.equal(normalizeServerUrl('https://jarvis.example:5001/'), 'https://jarvis.example:5001');
  for (const url of ['http://localhost:5001', 'http://dev.localhost:5001', 'http://127.0.0.1:5001', 'http://127.2.3.4:5001', 'http://[::1]:5001']) {
    assert.throws(() => normalizeServerUrl(url));
    assert.equal(normalizeServerUrl(url, {allowInsecureLocal: true}), url);
  }
  for (const url of ['http://public.example', 'http://8.8.8.8', 'file:///tmp/app', 'https://user:password@jarvis.example',
    'https://jarvis.example/?token=secret', 'https://jarvis.example/proxy', 'https://jarvis.example/#secret']) {
    assert.throws(() => normalizeServerUrl(url, {allowInsecureLocal: true}));
  }
  assert.equal(originPermission('https://jarvis.example:5001'), 'https://jarvis.example/*');
});

test('private LAN and non-loopback addresses require HTTPS even with the saved HTTP opt-in', () => {
  for (const host of ['192.168.1.2', '10.0.0.2', '172.16.0.2', '[fd00::2]', '[fc00::2]',
    '[fe80::2]', '100.64.0.2', '0.0.0.0', '[::]', 'localhost.example.com', '127.0.0.1.example.com']) {
    assert.throws(() => normalizeServerUrl(`http://${host}:5001`, {allowInsecureLocal: true}), /HTTPS is required/, host);
    assert.equal(normalizeServerUrl(`https://${host}:5001`), `https://${host}:5001`);
  }
});

test('companion contract requires chat recovery and authenticated sockets; page text is optional', () => {
  const features = {chat: true, images: true, conversations: true, recovery: true, cancel: true};
  assert.equal(assertCapabilities({features: {auth: false}, extension: {api: 1, socket_auth: true, features}}).api, 1);
  assert.equal(pageTextSupported({extension: {features: {...features, text: true}}}), true);
  assert.equal(pageTextSupported({extension: {features}}), false);
  assert.throws(() => assertCapabilities({features: {auth: false}, extension: {api: 1, socket_auth: true,
    features: {...features, cancel: false}}}), /Companion API 1/);
});
