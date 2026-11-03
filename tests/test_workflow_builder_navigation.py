"""Optional workflow navigation reflects configuration or identified service health."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from flask import Flask

from lib import ui_navigation

ROOT = Path(__file__).resolve().parents[1]


def test_workflows_public_origin_uses_existing_host_scope(tmp_path):
    path = tmp_path / "ui_urls.json"
    path.write_text(json.dumps({"hosts": {
        "jarvis.example.test": {"workflows": "https://jarvis.example.test:8447"},
        "other.example.test": {"workflows": "https://other.example.test:8447"},
    }}))
    app = Flask(__name__)
    ui_navigation.register_ui_navigation(app, path)
    client = app.test_client()
    matched = client.get("/ui-navigation.js", base_url="https://jarvis.example.test")
    assert '"workflows":"https://jarvis.example.test:8447"' in matched.text
    assert "other.example.test" not in matched.text
    unmatched = client.get("/ui-navigation.js", base_url="http://192.0.2.5:5001")
    assert '"urls":{}' in unmatched.text


def test_optional_builder_link_is_only_revealed_for_configuration_or_real_health():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(SOURCE, 'utf8');
async function boot({configured, protocol = 'http:', hostname = 'jarvis.example.test',
                     status = {ok: true, service: 'jarvis-workflows'}, reachable = true,
                     existingLink = true, loading = false, port = '5001', mobile = false} = {}) {
  const requests = [], children = [], callbacks = [];
  let timeouts = 0, cleared = 0;
  const media = {matches: mobile, callback: null, addEventListener(event, callback) {
    assert.equal(event, 'change'); this.callback = callback;
  }};
  const link = {hidden: true, href: 'http://jarvis.example.test:5001/#', style: {removeProperty(name) {assert.equal(name, 'display');},
    setProperty(name, value, priority) {assert.equal(name, 'display'); assert.equal(value, 'none'); assert.equal(priority, 'important');}},
    setAttribute(name, value) {this[name] = value;}};
  const container = {
    classList: {contains: name => name === 'header-links'},
    querySelector: () => null,
    appendChild: node => children.push(node),
  };
  const document = {
    readyState: loading ? 'loading' : 'complete',
    querySelectorAll: () => existingLink ? [link] : [],
    querySelector: selector => selector === '.header-links' ? container : null,
    createElement: tag => {assert.equal(tag, 'a'); return link;},
    addEventListener(event, callback, options) {
      assert.equal(event, 'DOMContentLoaded'); assert.equal(options.once, true);
      callbacks.push(callback);
    },
  };
  const window = {document, location: new URL(`${protocol}//${hostname}:${port}`), AbortController,
    matchMedia(query) {assert.equal(query, '(max-width: 768px)'); return media;},
    setTimeout() {timeouts++; return 1;}, clearTimeout() {cleared++;},
    async fetch(url, options) {
      requests.push({url, options});
      if (!reachable) throw new Error('unavailable');
      return {ok: true, async json() {return status;}};
    },
    __jarvisUINavigationConfig: {hostname: 'jarvis.example.test', urls: configured ? {
      workflows: 'https://jarvis.example.test:8447',
    } : {}},
  };
  vm.runInNewContext(source, {window, URL});
  if (loading) {
    assert.equal(link.hidden, true);
    assert.equal(requests.length, 0);
    assert.equal(callbacks.length, 1);
    callbacks[0]();
  }
  await new Promise(setImmediate);
  return {link, requests, children, timeouts, cleared, media};
}
(async () => {
  let result = await boot({configured: true, protocol: 'https:', loading: true});
  assert.equal(result.link.href, 'https://jarvis.example.test:8447');
  assert.equal(result.link.hidden, false);
  assert.equal(result.requests.length, 0);

  result = await boot();
  assert.equal(result.link.href, 'http://jarvis.example.test:5005');
  assert.equal(result.link.hidden, false);
  assert.equal(result.requests[0].url, 'http://jarvis.example.test:5005/api/status');
  assert.equal(result.requests[0].options.credentials, 'omit');
  assert.equal(result.cleared, result.timeouts);

  result = await boot({hostname: '[::1]'});
  assert.equal(result.link.href, 'http://[::1]:5005');
  result = await boot({configured: true, hostname: 'lan.example.test'});
  assert.equal(result.link.href, 'http://lan.example.test:5005');

  for (const options of [{reachable: false}, {status: {ok: true}},
      {status: {ok: true, service: 'other-app'}}, {status: {ok: false, service: 'jarvis-workflows'}}]) {
    result = await boot(options);
    assert.equal(result.link.hidden, true);
    assert.equal(result.cleared, result.timeouts);
  }
  result = await boot({protocol: 'https:'});
  assert.equal(result.requests.length, 0, 'no mixed-content health probe');
  assert.equal(result.link.hidden, true);
  result = await boot({port: '5005'});
  assert.equal(result.requests.length, 0, 'no self navigation');
  result = await boot({existingLink: false});
  assert.equal(result.children.length, 1);
  assert.equal(result.link.className, 'header-link');
  assert.equal(result.link.target, '_blank');
  assert.equal(result.link.rel, 'noopener');

  result = await boot({configured: true, mobile: true});
  assert.equal(result.link.hidden, true, 'mobile navigation has no extra workflow icon');
  result.media.matches = false; result.media.callback();
  assert.equal(result.link.hidden, false, 'desktop navigation reveals the configured workflow icon');
  result.media.matches = true; result.media.callback();
  assert.equal(result.link.hidden, true, 'desktop to mobile resize hides the icon again');
  result = await boot({mobile: true, existingLink: false});
  assert.equal(result.children.length, 1);
  assert.equal(result.link.hidden, true, 'dynamically inserted header link consumes no mobile space');
  result = await boot({mobile: true, reachable: false});
  result.media.matches = false; result.media.callback();
  assert.equal(result.link.hidden, true, 'resizing never reveals an unavailable builder placeholder');
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    result = subprocess.run(
        ["node", "-e", f"const SOURCE = {json.dumps(str(ui_navigation.SCRIPT_PATH))};\n" + script],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
