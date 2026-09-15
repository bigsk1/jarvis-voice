"""Exercise shipped cross-UI links and handoffs with optional public origins."""

import json
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
NAVIGATION = ROOT / "lib/static/ui-navigation.js"
CANVAS_TEMPLATES = ROOT / "jarvis-canvas/client/templates"


class NavigationMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.scripts.append(attrs)
        if tag == "a" and "window.open(" in attrs.get("onclick", ""):
            # A navigation click must not race the configuration script.
            assert any(script["src"] == "/ui-navigation.js" for script in self.scripts)
            self.links.append(attrs["onclick"])


def run_browser(body, **fixtures):
    prelude = "\n".join(f"const {key} = {json.dumps(value)};" for key, value in fixtures.items())
    script = prelude + r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const publicUrls = {
  web: 'https://jarvis.example.test', canvas: 'https://jarvis.example.test:8443',
  memory: 'https://jarvis.example.test:8444', intelligence: 'https://jarvis.example.test:8445',
  docs: 'https://jarvis.example.test:8446'
};
function browser(state, path = '/') {
  const hostname = state === 'unknown' ? 'lan.example.test' : 'jarvis.example.test';
  const protocol = state === 'mapped' ? 'https:' : 'http:';
  const opened = [];
  const sandbox = {URL, URLSearchParams, console, window: {
    location: new URL(`${protocol}//${hostname}:8890${path}`),
    open: (...args) => opened.push(args)
  }};
  vm.createContext(sandbox);
  if (state !== 'missing') {
    sandbox.window.__jarvisUINavigationConfig = state === 'unconfigured' ? {} : {
      hostname: 'jarvis.example.test', urls: publicUrls
    };
    vm.runInContext(fs.readFileSync(NAVIGATION, 'utf8'), sandbox);
  }
  return {sandbox, opened, hostname, protocol};
}
""" + body
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(("page", "services"), [
    ("jarvis-web/client/index.html", ["canvas", "memory", "intelligence", "logs", "docs"]),
    ("jarvis-web/client/logs.html", ["canvas", "memory", "intelligence"]),
    ("jarvis-memory/client/index.html", ["intelligence", "web"]),
    ("jarvis-intelligence/client/index.html", ["memory", "web"]),
    ("jarvis-docs/client/index.html", []),
    ("canvas.html", ["web", "memory"]),
    ("gallery.html", ["web"]),
    ("video-gallery.html", ["web"]),
    ("audio-gallery.html", ["web"]),
])
def test_shipped_navigation_keeps_defaults_and_uses_matching_host_overrides(page, services):
    if "/" in page:
        html = (ROOT / page).read_text()
    else:
        html = Environment(loader=FileSystemLoader(CANVAS_TEMPLATES)).get_template(page).render()
    markup = NavigationMarkup()
    markup.feed(html)
    navigation_scripts = [script for script in markup.scripts if script["src"] == "/ui-navigation.js"]
    assert len(navigation_scripts) == 1
    assert not {"async", "defer"}.intersection(navigation_scripts[0])
    assert len(markup.links) == len(services)
    run_browser(r"""
const ports = {web: 5001, canvas: 8890, memory: 5002, intelligence: 5003, docs: 5004};
for (const state of ['missing', 'unconfigured', 'unknown', 'mapped']) {
  const {sandbox, opened, hostname, protocol} = browser(state);
  for (const handler of HANDLERS) vm.runInContext(`(function() {${handler}})()`, sandbox);
  assert.equal(opened.length, SERVICES.length);
  SERVICES.forEach((service, index) => {
    const expected = service === 'logs' ? sandbox.window.location.origin + '/logs'
      : state === 'mapped' ? publicUrls[service]
      : `${service === 'docs' ? protocol : 'http:'}//${hostname}:${ports[service]}`;
    assert.equal(opened[index][0], expected, `${state}: ${service}`);
    assert.equal(opened[index][1], '_blank');
  });
}
""", NAVIGATION=str(NAVIGATION), HANDLERS=markup.links, SERVICES=services)


def test_canvas_handoff_and_web_deep_links_preserve_their_payloads():
    run_browser(r"""
const gallery = fs.readFileSync(ROOT + '/jarvis-canvas/client/static/js/gallery.js', 'utf8');
const handoff = gallery.slice(gallery.indexOf('function buildJarvisWebMediaHandoffUrl('),
  gallery.indexOf('function sendImageToJarvisWeb('));
const chatSource = fs.readFileSync(ROOT + '/jarvis-web/client/js/chat.js', 'utf8');
const appSource = fs.readFileSync(ROOT + '/jarvis-web/client/js/app.js', 'utf8');
for (const state of ['missing', 'unconfigured', 'unknown', 'mapped']) {
  const {sandbox, hostname} = browser(state, '/gallery?old=discard#previous');
  vm.runInContext(handoff, sandbox);
  const result = new URL(sandbox.buildJarvisWebMediaHandoffUrl('Image & one.png'));
  assert.equal(result.origin, state === 'mapped' ? publicUrls.web : `http://${hostname}:5001`);
  assert.equal(result.pathname, '/');
  assert.equal(result.hash, '');
  assert.deepEqual([...result.searchParams], [
    ['media_handoff', 'image'], ['media_filename', 'Image & one.png'], ['media_action', 'video']
  ]);

  const ChatUI = vm.runInContext(chatSource.slice(0, chatSource.lastIndexOf('// Create global instance'))
    + '\nChatUI;', sandbox);
  const chat = Object.create(ChatUI.prototype);
  const preview = chat._extractCanvasPreview({canvas: {
    page_id: 'page_test', title: 'Example',
    url: 'http://old.example.test:8890/page_test?view=one%20two#section'
  }});
  const canvasOrigin = state === 'mapped' ? publicUrls.canvas : 'http://old.example.test:8890';
  assert.equal(preview.url, canvasOrigin + '/page_test?view=one%20two#section');
  assert.equal(preview.apiUrl, canvasOrigin + '/api/pages/page_test');
  const fallbackPreview = chat._extractCanvasPreview({canvas: {page_id: 'page_test'}});
  assert.equal(fallbackPreview.url,
    (state === 'mapped' ? publicUrls.canvas : `http://${hostname}:8890`) + '/page_test');
  assert.equal(chat._extractCanvasPreview({canvas: {page_id: 'page_test', url: 'javascript:alert(1)'}}), null);

  const JarvisApp = vm.runInContext(appSource.slice(0, appSource.lastIndexOf('// Initialize app'))
    + '\nJarvisApp;', sandbox);
  const app = Object.create(JarvisApp.prototype);
  assert.equal(app._getMemoryIntelUrl(),
    (state === 'mapped' ? publicUrls.memory : `http://${hostname}:5002`) + '/#intel');
}
""", NAVIGATION=str(NAVIGATION), ROOT=str(ROOT))
