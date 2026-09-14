import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeServerUrl, originPermission} from '../core/connection.js';

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
