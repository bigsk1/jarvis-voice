"""Boot the shipped classic-script dependencies in their HTML order."""

import json
import subprocess
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "jarvis-web" / "client"


class ApplicationScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script" and attributes.get("src", "").startswith("/js/"):
            self.scripts.append(attributes)


def test_chat_dependencies_boot_from_the_shipped_script_order():
    parser = ApplicationScripts()
    parser.feed((CLIENT / "index.html").read_text())
    scripts = parser.scripts
    paths = [script["src"] for script in scripts]
    assert len(paths) == len(set(paths)), "Application scripts must initialize once"
    for script in scripts:
        assert "async" not in script and "defer" not in script
        assert script.get("type", "text/javascript") == "text/javascript"
        assert (CLIENT / script["src"].lstrip("/")).is_file()

    # Load every production dependency preceding ChatUI, including the real
    # utilities, socket singleton, adapter factories and command singleton.
    # This catches a missing/misordered HTML tag even if isolated unit loaders pass.
    dependencies = paths[:paths.index("/js/chat.js")]
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const requested = [];
const storage = {
  getItem: () => null, setItem() {}, removeItem() {}
};
const sandbox = {
  URL,
  console: {log() {}, warn() {}},
  localStorage: storage,
  window: {sessionStorage: storage, addEventListener() {}},
  document: {
    addEventListener() {}, querySelectorAll: () => [],
    createElement: () => ({
      textContent: '',
      get innerHTML() {
        return String(this.textContent).replaceAll('&', '&amp;')
          .replaceAll('<', '&lt;').replaceAll('>', '&gt;');
      }
    })
  },
  setTimeout: () => 0,
  fetch: async url => {
    requested.push(url);
    return {ok: true, json: async () => url.startsWith('/api/tools')
      ? {tools: [{name: 'search_web', enabled: true}]}
      : url.startsWith('/api/prompts')
        ? {prompts: {brief: {content: 'Be brief', tool_hints: ['search_web']}}}
        : {workflows: {research: {triggers: ['/research']}}}};
  }
};
vm.createContext(sandbox);
for (const source of SOURCES) {
  vm.runInContext(fs.readFileSync(CLIENT + source, 'utf8'), sandbox, {filename: source});
}
(async () => {
  // Complete the singleton's asynchronous registry loading without network I/O.
  await new Promise(resolve => setImmediate(resolve));
  const commands = sandbox.window.commandSystem;
  assert.ok(commands?.loaded, 'Command registry must be ready before use');
  assert.equal(requested.length, 3, 'Only one command singleton should fetch registries');
  assert.ok(requested.every(url => url.includes('mode=cloud')));
  assert.equal(commands.parseInput('/research coffee').workflow, 'research');
  const parsed = commands.parseInput('@brief Compare coffee #search_web #chat_only');
  assert.equal(parsed.message, 'Compare coffee');
  assert.equal(parsed.instruction, 'Be brief');
  assert.equal(parsed.toolPolicy, 'none');
  assert.deepEqual(Array.from(parsed.toolHints), ['search_web']);

  const renderer = sandbox.window.structuredResultsRenderer;
  assert.ok(renderer, 'Renderer singleton must load before ChatUI');
  assert.ok(renderer.registeredTools().includes('serpapi_amazon_search'));
  const html = renderer.render({serpapi_amazon_search: {
    engine: 'amazon', query: 'coffee',
    results: [{title: 'Coffee <grinder>', url: 'https://example.test/item'}]
  }});
  assert.ok(html.includes('Coffee &lt;grinder&gt;'));
  assert.ok(!html.includes('Coffee <grinder>'));
  const localHtml = renderer.render({serpapi_google_local: {
    query: 'coffee',
    results: [{title: 'Cafe <corner>', website: 'https://example.test/cafe'}]
  }});
  assert.ok(localHtml.includes('Cafe &lt;corner&gt;'));
  assert.ok(localHtml.includes('Open website'));

  const messageRenderer = sandbox.window.assistantMessageRenderer;
  assert.ok(messageRenderer, 'Assistant message renderer must load before ChatUI');
  const converted = messageRenderer.renderConvertedFile({
    stash_ref: 'stash://space_test/f_preview', filename: 'Preview <file>.pdf', target_format: 'pdf'
  });
  assert.ok(converted.includes('/api/stash/space_test/f_preview'));
  assert.ok(converted.includes('Preview &lt;file&gt;.pdf'));
})().catch(error => {console.error(error); process.exit(1);});
"""
    prelude = f"const CLIENT = {json.dumps(str(CLIENT))};\n"
    prelude += f"const SOURCES = {json.dumps(dependencies)};\n"
    subprocess.run(["node", "-e", prelude + script], cwd=ROOT, check=True, timeout=15)
