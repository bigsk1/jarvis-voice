"""Registry body races and failed refreshes must not revive disabled commands."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync('jarvis-web/client/js/command-system.js', 'utf8')
  .split('// Global command system instance')[0];
global.window = {jarvisSocket: {mode: 'cloud'}};
global.Utils = {storage: {get: () => 'cloud'}};
global.document = new EventTarget();
eval(source + '\nglobal.CommandSystem = CommandSystem;');
const commands = Object.create(CommandSystem.prototype);
Object.assign(commands, {
  tools: {}, workflows: {}, prompts: {}, loaded: false, _registryRequestId: 0
});
const events = [];
const snapshot = () => ({
  tools: Object.keys(commands.tools),
  workflows: Object.keys(commands.workflows),
  prompts: Object.keys(commands.prompts),
  loaded: commands.loaded
});
document.addEventListener('jarvis:commands-updated', () => events.push(snapshot()));
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
};
const payload = url => {
  const mode = new URL(url, 'https://example.test').searchParams.get('mode');
  if (url.includes('/tools')) return {
    tools: mode === 'cloud' ? [{name: 'bookmark_search', enabled: true}] : []
  };
  if (url.includes('/prompts')) return {prompts: {[mode]: {content: mode}}};
  return {workflows: mode === 'cloud'
    ? {bookmark_search: {triggers: ['*'], name: 'Bookmark Search'}} : {}};
};
const response = url => ({ok: true, json: async () => payload(url)});
const assertLocal = () => {
  assert.deepEqual(snapshot(), {tools: [], workflows: [], prompts: ['local'], loaded: true});
  assert.equal(commands.getSuggestions('*').length, 0);
};
const assertCloud = () => {
  assert.deepEqual(snapshot(), {
    tools: ['bookmark_search'], workflows: ['bookmark_search'], prompts: ['cloud'], loaded: true
  });
  assert.equal(commands.getSuggestions('*').length, 1);
};
"""


def _run(script, **parameters):
    prelude = "".join(f"const {name} = {json.dumps(value)};\n" for name, value in parameters.items())
    subprocess.run(
        ["node", "-e", prelude + HARNESS + "\n(async () => {\n" + script + "\n})().catch(error => {console.error(error); process.exit(1);});"],
        cwd=ROOT,
        check=True,
        timeout=15,
    )


@pytest.mark.parametrize("method", ["_loadRegistry", "refreshTools"])
def test_newer_mode_wins_even_when_old_json_body_finishes_last(method):
    _run(r"""
const bodyStarted = deferred();
const oldBody = deferred();
global.fetch = async url => url.includes('mode=cloud') && url.includes('/workflows')
  ? {ok: true, json: () => {bodyStarted.resolve(); return oldBody.promise;}}
  : response(url);
const oldLoad = commands[method]('cloud');
await bodyStarted.promise;
assert.equal(events.length, 0, 'Partial registries must never be published');
assert.deepEqual(snapshot(), {tools: [], workflows: [], prompts: [], loaded: false});
await commands.refreshTools('local');
assertLocal();
assert.equal(events.length, 1);
oldBody.resolve(payload('/api/workflows?mode=cloud'));
await oldLoad;
assertLocal();
assert.equal(events.length, 1, 'Stale bodies must not publish another event');
""", method=method)


@pytest.mark.parametrize("method", ["_loadRegistry", "refreshTools"])
@pytest.mark.parametrize("failure", ["http", "json", "network"])
def test_latest_failed_snapshot_hides_bookmarks_and_can_recover(method, failure):
    _run(r"""
global.fetch = async url => response(url);
await commands._loadRegistry('cloud');
assertCloud();
global.fetch = async url => {
  if (!url.includes('/workflows')) return response(url);
  if (failure === 'network') throw new Error('Disconnected');
  return {
    ok: failure !== 'http',
    json: async () => {throw new SyntaxError('Invalid JSON');}
  };
};
await commands[method]('local');
assert.deepEqual(snapshot(), {tools: [], workflows: [], prompts: [], loaded: false});
assert.equal(commands.getSuggestions('*').length, 0);
assert.equal(events.length, 2);
assert.deepEqual(events[1], snapshot(), 'Failure must publish the cleared snapshot');
global.fetch = async url => response(url);
await commands.refreshTools('cloud');
assertCloud();
assert.equal(events.length, 3);
assert.deepEqual(events[2], snapshot());
""", method=method, failure=failure)


@pytest.mark.parametrize("failure", ["http", "json", "network"])
def test_older_failure_does_not_clear_newer_success(failure):
    _run(r"""
const oldStarted = deferred();
const oldResponse = deferred();
global.fetch = async url => {
  if (!url.includes('mode=cloud') || !url.includes('/workflows')) return response(url);
  if (failure === 'json') return {
    ok: true, json: () => {oldStarted.resolve(); return oldResponse.promise;}
  };
  oldStarted.resolve();
  return oldResponse.promise;
};
const oldLoad = commands._loadRegistry('cloud');
await oldStarted.promise;
await commands.refreshTools('local');
assertLocal();
if (failure === 'http') oldResponse.resolve({ok: false});
else oldResponse.reject(new Error('Old request failed'));
await oldLoad;
assertLocal();
assert.equal(events.length, 1, 'Old failure must not clear or republish newer state');
""", failure=failure)
