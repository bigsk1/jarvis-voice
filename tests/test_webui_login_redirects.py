"""Exercise the shipped login scripts through both authentication success paths."""

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES = [
    "jarvis-canvas/client/templates/login.html",
    "jarvis-web/client/login.html",
    "jarvis-memory/client/login.html",
    "jarvis-intelligence/client/login.html",
    "jarvis-docs/client/login.html",
]


@pytest.mark.parametrize("page", PAGES)
@pytest.mark.parametrize("existing_token", [False, True], ids=["sign-in", "restore-cookie"])
def test_login_navigation_keeps_authentication_on_its_origin(page, existing_token):
    source = (ROOT / page).read_text()
    inline = "\n".join(re.findall(r"<script>\s*([\s\S]*?)</script>", source))
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const origin = 'https://jarvis.example.test:8443';
async function login(requested, helperAvailable = true) {
  const handlers = {};
  const values = new Map(EXISTING ? [['jarvis_auth_token', 'existing-token']] : []);
  const elements = new Map();
  const document = {
    cookie: '',
    getElementById(id) {
      if (id === 'loginHudLogo') return null;
      if (!elements.has(id)) elements.set(id, {
        value: 'fixture-password', disabled: false, textContent: '',
        classList: {add() {}, remove() {}}, focus() {},
        addEventListener(type, fn) { handlers[id + ':' + type] = fn; }
      });
      return elements.get(id);
    }
  };
  const location = {origin, hostname: 'jarvis.example.test', href: origin + '/login',
    search: requested === null ? '' : '?redirect=' + encodeURIComponent(requested)};
  const context = {window: {location}, document, URL, URLSearchParams, console,
    localStorage: {getItem: key => values.get(key) || null,
      setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key)},
    fetch: async () => ({ok: true, status: 200,
      json: async () => ({ok: true, token: 'new-token', expires_in_days: 30})})};
  vm.createContext(context);
  if (helperAvailable) vm.runInContext(fs.readFileSync(NAVIGATION, 'utf8'), context);
  vm.runInContext(INLINE, context);
  if (!EXISTING) {
    if (PAGE === 'jarvis-web/client/login.html') await vm.runInContext('doLogin()', context);
    else await handlers['loginForm:submit']({preventDefault() {}});
  }
  await new Promise(resolve => setImmediate(resolve));
  assert.match(document.cookie, /jarvis_auth=(existing-token|new-token);/);
  return new URL(location.href, origin);
}
(async () => {
  for (const requested of [null, '', '/', '/page_20261031_test', '/gallery?sort=newest#image',
      '/stash/view/space_test/f_test?mode=local',
      '/library?mode=local&source=' + 'a'.repeat(64) + '&passage=7',
      origin + '/audio-gallery#track', '/x/..//evil.test/path', '/%2e%2e//evil.test/path']) {
    const result = await login(requested);
    assert.equal(result.origin, origin, String(requested));
    assert.equal(result.href, new URL(requested || '/', origin).href, String(requested));
  }
  for (const requested of ['javascript:alert(1)', 'java\tscript:alert(1)', '\njavascript:alert(1)',
      'data:text/html,unsafe', 'vbscript:unsafe', 'blob:' + origin + '/unsafe',
      'https://evil.test/path', '//evil.test/path', '/\\evil.test/path', '\\\\evil.test/path',
      'http://jarvis.example.test:8443/', 'https://jarvis.example.test:8444/', 'https://[invalid',
      'https://user:password@jarvis.example.test:8443/']) {
    const result = await login(requested);
    assert.equal(result.href, origin + '/', String(requested));
  }
  assert.equal((await login('/gallery', false)).href, origin + '/', 'missing helper fails closed');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    constants = {
        "INLINE": inline,
        "PAGE": page,
        "EXISTING": existing_token,
        "NAVIGATION": str(ROOT / "lib/static/ui-navigation.js"),
    }
    prelude = "\n".join(f"const {key} = {json.dumps(value)};" for key, value in constants.items())
    result = subprocess.run(
        ["node", "-e", prelude + script], cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
