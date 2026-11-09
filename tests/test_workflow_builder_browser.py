"""Real browser journeys without browser-driver packages or live Jarvis tools.

Chromium uses an existing executable (WORKFLOW_TEST_CHROMIUM or Playwright's
cached binary). Firefox runs only when WORKFLOW_TEST_FIREFOX names an existing
binary. Tests never download browsers; Node 22 supplies the protocol WebSocket.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from flask import jsonify
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]


def browser_binary(kind: str) -> Path | None:
    configured = os.environ.get(f"WORKFLOW_TEST_{kind.upper()}")
    if configured:
        path = Path(configured)
        return path if path.is_file() else None
    if kind == "firefox":
        return None
    candidates = sorted((Path.home() / ".cache/ms-playwright").glob("chromium-*/chrome-linux*/chrome"))
    for command in ("chromium", "chromium-browser", "google-chrome"):
        found = shutil.which(command)
        if found:
            candidates.append(Path(found))
    return next((path for path in reversed(candidates) if path.is_file()), None)


@pytest.fixture
def browser_app(tmp_path, monkeypatch):
    package = "jarvis_workflow_browser_test_server"
    spec = importlib.util.spec_from_file_location(
        package, ROOT / "jarvis-workflows/server/__init__.py",
        submodule_search_locations=[str(ROOT / "jarvis-workflows/server")],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, package, module)
    spec.loader.exec_module(module)
    from importlib import import_module

    app_module = import_module(package + ".app")
    catalog_module = import_module(package + ".catalog")
    config = tmp_path / "config"
    config.mkdir()
    (config / "cloud.env").write_text("")
    workflows = tmp_path / "data/workflows"
    (workflows / "personal").mkdir(parents=True)
    recipe = {
        "id": "browser_example", "name": "Browser Example", "description": "Offline browser fixture",
        "enabled": True, "triggers": {"explicit": ["/browser_example"]}, "variables": {},
        "success_speech": "Done", "x_extension": {"preserved": True},
        "retry": {"max_attempts": 99}, "partial_speech": "Legacy custom partial text",
        "steps": [
            {"step": 8, "tool": "calculator", "params": {"expression": "2+2"},
             "output_var": "answer", "llm_hints": {"note": "Legacy generation hint"}},
            {"step": 42, "tool": "send_email", "params": {
                "to": "workflow-test@example.test", "subject": "Browser fixture", "body": "Prepared exact body",
            }},
        ],
    }
    bundled = workflows / "browser_example.json"
    original = json.dumps(recipe, indent=2) + "\n"
    bundled.write_text(original)
    (workflows / "invalid_commands.json").write_text(json.dumps({
        **recipe, "id": "invalid_commands", "name": "Invalid Commands",
        "triggers": {"explicit": 123},
    }))
    (workflows / "untouched_autonomous.json").write_text(json.dumps({
        **recipe, "id": "untouched_autonomous", "name": "Untouched Autonomous",
        "allow_workflow_tool": True, "triggers": {"explicit": ["/untouched_autonomous"]},
    }))
    shutil.copytree(ROOT / "jarvis-web/client/fonts", tmp_path / "jarvis-web/client/fonts")
    monkeypatch.delenv("WEBUI_PASSWORD", raising=False)
    monkeypatch.setenv("WEBUI_SECRET", "browser-test-only-signing-secret")
    monkeypatch.setattr(
        app_module, "register_ui_navigation",
        lambda app: __import__("lib.ui_navigation", fromlist=["register_ui_navigation"])
        .register_ui_navigation(app, config / "ui_urls.json"),
    )
    tools = [
        {"name": "calculator", "description": "Fixture calculator", "available": True,
         "parameters": {"type": "object", "properties": {"expression": {"type": "string"}},
                        "required": ["expression"]}, "permissions": {"auto_approve": True}},
        {"name": "send_email", "description": "Fixture email; never sends", "available": True,
         "parameters": {"type": "object", "properties": {
             key: {"type": "string"} for key in ("to", "subject", "body")}},
         "permissions": {"auto_approve": False, "network": True}},
    ]
    for tool in tools:
        tool.update(permissions_verified=True, permissions_source="local_manifest")
    monkeypatch.setattr(catalog_module.CatalogService, "tools", lambda self, mode: {"tools": tools})

    class FakeSupervisor:
        """Exercise real persistence/API/UI while replacing every tool effect."""

        def __init__(self):
            self.store = None
            self.recipes = None
            self.starts = 0
            self.approved = []

        def prepare(self, body):
            source, definition = self.recipes.read(body["source_id"])
            assert source["hash"] == body["hash"]
            document = {"workflow": definition, "workflow_id": definition["id"],
                        "mode": body["mode"], "query": body["query"],
                        "timeout_seconds": body["timeout_seconds"],
                        "stop_after": body.get("stop_after"),
                        "source_id": source["source_id"], "hash": source["hash"]}
            return {"confirmation_token": self.store.prepare(document), "effects": [{
                "index": index, "step": step["step"], "tool": step["tool"],
                "description": "Mock boundary; no tool is executed",
                "requires_approval": step["tool"] == "send_email",
            } for index, step in enumerate(definition["steps"])]}

        def start(self, body):
            assert body["confirmed"] is True
            run, created = self.store.admit(body["confirmation_token"], body["idempotency_key"])
            assert created
            self.starts += 1
            self.store.set_status(run["id"], "running")
            self.store.event(run["id"], {"type": "step_started", "tool": "send_email",
                                       "step": 42, "index": 0, "message": "Tool call prepared"})
            self.store.request_approval(run["id"], {
                "tool": "send_email", "step": 42, "index": 0,
                "arguments": {"to": "workflow-test@example.test", "body": "Prepared exact body"},
                "call_hash": "a" * 64,
            })
            return self.store.get_run(run["id"])

    runner = FakeSupervisor()
    app = app_module.create_app(repo_root=tmp_path, runner=runner)
    runner.store = app.extensions["workflow_store"]
    runner.recipes = app.extensions["workflow_recipes"]
    original_decide = runner.store.decide

    def decide(approval_id, approved, call_hash):
        original_decide(approval_id, approved, call_hash)
        runner.approved.append({"approved": approved, "call_hash": call_hash})
        run = runner.store.active_run()
        assert run and approved
        for index in range(310):
            runner.store.event(run['id'], {'type': 'status', 'message': f'Buffered progress {index}'})
        partial = run.get("stop_after") is not None
        message = "Mock partial run stopped after one step" if partial else "Mock workflow completed"
        result = {"ok": True, "partial": partial, "speech": message,
                  "data": {"message_id": "mock-mail-id"}}
        runner.store.event(run["id"], {"type": "step_completed", "tool": "send_email",
                                       "step": 42, "index": 0, "result": result})
        runner.store.event(run["id"], {"type": "workflow_partial" if partial else "workflow_completed",
                                      "message": message})
        runner.store.set_status(run["id"], "partial" if partial else "completed", result)

    monkeypatch.setattr(runner.store, "decide", decide)

    @app.get("/api/test-state")
    def test_state():
        return jsonify(starts=runner.starts, approved=runner.approved)

    server = make_server("127.0.0.1", 0, app, threaded=True)
    origin = f"http://127.0.0.1:{server.server_port}"
    (config / "ui_urls.json").write_text(json.dumps({"hosts": {
        "127.0.0.1": {"workflows": origin, "web": origin},
    }}))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield origin, tmp_path, runner, bundled, original
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


JOURNEY = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const kind = process.env.BROWSER_KIND, binary = process.env.BROWSER_BINARY;
const origin = process.env.APP_ORIGIN, directory = process.env.TEST_DIRECTORY;
const profile = path.join(directory, kind + '-profile'); fs.mkdirSync(profile);
if (kind === 'firefox') fs.writeFileSync(path.join(profile, 'user.js'), [
  'user_pref("browser.shell.checkDefaultBrowser", false);',
  'user_pref("browser.startup.homepage", "about:blank");',
  'user_pref("browser.newtabpage.enabled", false);',
  'user_pref("datareporting.policy.dataSubmissionEnabled", false);',
  'user_pref("toolkit.telemetry.enabled", false);',
  'user_pref("app.update.auto", false);',
].join('\n'));
const args = kind === 'firefox' ? ['--headless', '--remote-debugging-port', '0', '--profile', profile, 'about:blank']
  : ['--headless=new', '--no-sandbox', '--disable-gpu', '--disable-background-networking', '--no-first-run',
     '--disable-extensions', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'];
const child = spawn(binary, args, {detached: true, stdio: ['ignore', 'ignore', 'pipe'],
  env: {...process.env, MOZ_DISABLE_CONTENT_SANDBOX: '1'}});
let diagnostics = '', websocket, nextId = 1, context;
const pending = new Map(), requests = [], failures = [], errors = [];
child.stderr.on('data', value => {diagnostics = (diagnostics + value).slice(-5000);});
async function until(callback, label, timeout = 12000) {
  const end = Date.now() + timeout;
  let lastError;
  while (Date.now() < end) {
    if (child.exitCode !== null) throw new Error('Browser exited: ' + diagnostics);
    try { const result = await callback(); if (result) return result; } catch (error) {lastError = error;}
    await sleep(50);
  }
  throw new Error('Timed out: ' + label + '\n' + (lastError?.message || '') + '\n' + diagnostics);
}
function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = nextId++, timer = setTimeout(() => {pending.delete(id); reject(new Error('Protocol timeout: ' + method));}, 10000);
    pending.set(id, {resolve, reject, timer}); websocket.send(JSON.stringify({id, method, params}));
  });
}
async function evaluate(expression) {
  const wrapped = `(async () => JSON.stringify(await (${expression})))()`;
  let response, result;
  if (kind === 'firefox') {
    response = await send('script.evaluate', {expression: wrapped, target: {context}, awaitPromise: true});
    if (response.type === 'exception') throw new Error(response.exceptionDetails?.text || JSON.stringify(response));
    result = response.result;
  } else {
    response = await send('Runtime.evaluate', {expression: wrapped, awaitPromise: true, returnByValue: true});
    if (response.exceptionDetails) throw new Error(JSON.stringify(response.exceptionDetails));
    result = response.result;
  }
  return result?.value === undefined ? undefined : JSON.parse(result.value);
}
const ready = (expression, label) => until(() => evaluate(`Boolean(${expression})`), label);
const click = selector => evaluate(`(() => {const target = document.querySelector(${JSON.stringify(selector)}); if (!target) throw new Error('Missing control'); target.click(); return true;})()`);
const closeReview = selector => evaluate(`new Promise(resolve => {
  const dialog = document.getElementById('reviewDialog'), target = document.querySelector(${JSON.stringify(selector)});
  if (!dialog?.open || !target) throw new Error('Missing open review or close control');
  // A closed property alone does not mean the queued native close event ran.
  // Finish that event before another review installs its cancellation listener.
  dialog.addEventListener('close', () => resolve(true), {once:true}); target.click();
})`);
const set = (selector, value) => evaluate(`(() => {const target = document.querySelector(${JSON.stringify(selector)}); target.value = ${JSON.stringify(value)}; target.dispatchEvent(new Event('change', {bubbles:true})); return true;})()`);
const getJSON = () => evaluate('JSON.parse(document.getElementById("recipeJSON").value)');
const testState = () => evaluate('fetch("/api/test-state").then(response => response.json())');
async function center(selector) {
  return evaluate(`(() => {
    const target = document.querySelector(${JSON.stringify(selector)});
    if (!target) throw new Error('Missing pointer target: ' + ${JSON.stringify(selector)});
    target.scrollIntoView({block:'center'});
    const bounds = target.getBoundingClientRect();
    return {x:Math.round(bounds.x + bounds.width / 2), y:Math.round(bounds.y + bounds.height / 2)};
  })()`);
}
async function hover(selector) {
  const point = await center(selector);
  if (kind === 'firefox') await send('input.performActions', {context, actions:[{
    type:'pointer', id:'mouse', parameters:{pointerType:'mouse'},
    actions:[{type:'pointerMove', origin:'viewport', duration:0, ...point}],
  }]});
  else await send('Input.dispatchMouseEvent', {type:'mouseMoved', ...point});
}
async function keypress(key) {
  const values = {Enter:['\uE007',13], Escape:['\uE00C',27]};
  if (kind === 'firefox') await send('input.performActions', {context, actions:[{
    type:'key', id:'keyboard', actions:[{type:'keyDown',value:values[key][0]}, {type:'keyUp',value:values[key][0]}],
  }]});
  else for (const type of ['keyDown','keyUp']) await send('Input.dispatchKeyEvent', {
    type, key, code:key, windowsVirtualKeyCode:values[key][1], nativeVirtualKeyCode:values[key][1],
    ...(key === 'Enter' && type === 'keyDown' ? {text:'\r',unmodifiedText:'\r'} : {}),
  });
}
async function tap(selector) {
  const point = await center(selector);
  if (kind === 'firefox') await send('input.performActions', {context, actions:[{
    type:'pointer', id:'touch', parameters:{pointerType:'touch'}, actions:[
      {type:'pointerMove', origin:'viewport', duration:0, ...point},
      {type:'pointerDown',button:0}, {type:'pointerUp',button:0},
    ],
  }]});
  else {
    await send('Input.dispatchTouchEvent', {type:'touchStart',touchPoints:[point]});
    await send('Input.dispatchTouchEvent', {type:'touchEnd',touchPoints:[]});
  }
}
async function drag(source, target) {
  // Native drag managers differ between headless CDP and BiDi. Exercise the
  // shipped HTML drag/drop handlers with the browser's real DataTransfer.
  await evaluate(`(() => {
    const source = document.querySelector(${JSON.stringify(source)}), target = document.querySelector(${JSON.stringify(target)});
    const dataTransfer = new DataTransfer();
    source.dispatchEvent(new DragEvent('dragstart', {bubbles:true, dataTransfer}));
    target.dispatchEvent(new DragEvent('dragover', {bubbles:true, cancelable:true, dataTransfer}));
    target.dispatchEvent(new DragEvent('drop', {bubbles:true, cancelable:true, dataTransfer}));
    source.dispatchEvent(new DragEvent('dragend', {bubbles:true, dataTransfer}));
  })()`);
}
async function resize(width, height) {
  if (kind === 'firefox') await send('browsingContext.setViewport', {context, viewport: {width, height}, devicePixelRatio: 1});
  else await send('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile: width < 600});
  await ready(`innerWidth === ${width}`, 'viewport size');
}
async function screenshot(name) {
  const captured = kind === 'firefox'
    ? await send('browsingContext.captureScreenshot', {context, origin:'viewport', format:{type:'image/png'}})
    : await send('Page.captureScreenshot', {format:'png', captureBeyondViewport:false});
  fs.writeFileSync(path.join(directory, `${kind}-${name}.png`), Buffer.from(captured.data, 'base64'));
}
async function reload() {
  // CDP acknowledges Page.reload before navigation replaces the old document.
  // Its already-restored draft must not satisfy the new page's readiness check.
  const previousDocument = `workflow-journey-${nextId++}`;
  await evaluate(`document.documentElement.dataset.workflowJourneyDocument = ${JSON.stringify(previousDocument)}`);
  if (kind === 'firefox') await send('browsingContext.reload', {context, wait: 'complete'});
  else await send('Page.reload');
  await ready(`document.documentElement?.dataset.workflowJourneyDocument !== ${JSON.stringify(previousDocument)}
    && document.getElementById("recipeJSON")
    && document.getElementById("recipeTitle")?.textContent === "Browser Example"
    && document.querySelector("#stepLane [data-index]")`, 'new document with restored draft');
}
(async () => {
  let endpoint;
  if (kind === 'firefox') {
    endpoint = await until(() => diagnostics.match(/WebDriver BiDi listening on (ws:\/\/[^\s]+)/)?.[1], 'Firefox BiDi endpoint');
    endpoint = endpoint.replace(/\/$/, '') + '/session';
  } else {
    const port = await until(() => fs.existsSync(path.join(profile, 'DevToolsActivePort')) && fs.readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0], 'Chromium CDP endpoint');
    const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, {method: 'PUT'})).json();
    endpoint = target.webSocketDebuggerUrl;
  }
  websocket = new WebSocket(endpoint);
  await new Promise((resolve, reject) => {websocket.addEventListener('open', resolve, {once:true}); websocket.addEventListener('error', reject, {once:true});});
  websocket.addEventListener('message', event => {
    const data = JSON.parse(event.data);
    if (data.id) {
      const request = pending.get(data.id); if (!request) return;
      pending.delete(data.id); clearTimeout(request.timer);
      if (data.error) request.reject(new Error(JSON.stringify(data))); else request.resolve(data.result);
      return;
    }
    if (data.method === 'Runtime.exceptionThrown') errors.push(data.params.exceptionDetails.text);
    if (data.method === 'log.entryAdded' && data.params.level === 'error') errors.push(data.params.text);
    if (data.method === 'Network.requestWillBeSent' || data.method === 'network.beforeRequestSent') requests.push(data.params.request.url);
    if (data.method === 'Network.responseReceived' || data.method === 'network.responseCompleted') {
      const response = data.params.response;
      if (response.url?.startsWith(origin) && response.status >= 400) failures.push(response.url + ': ' + response.status);
    }
    if (data.method === 'Fetch.requestPaused') {
      const url = data.params.request.url;
      send(url.startsWith(origin + '/') ? 'Fetch.continueRequest' : 'Fetch.failRequest',
        {requestId:data.params.requestId, ...(!url.startsWith(origin + '/') ? {errorReason:'BlockedByClient'} : {})}).catch(error => errors.push(error.message));
    }
    if (data.method === 'network.beforeRequestSent' && data.params.isBlocked) {
      send(data.params.request.url.startsWith(origin + '/') ? 'network.continueRequest' : 'network.failRequest',
        {request:data.params.request.request}).catch(error => errors.push(error.message));
    }
  });
  if (kind === 'firefox') {
    await send('session.new', {capabilities:{alwaysMatch:{acceptInsecureCerts:false}}});
    context = (await send('browsingContext.create', {type:'tab'})).context;
    await send('session.subscribe', {events:['network.beforeRequestSent', 'network.responseCompleted', 'log.entryAdded'], contexts:[context]});
    await send('network.addIntercept', {phases:['beforeRequestSent'], contexts:[context]});
  } else {
    await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
    await send('Fetch.enable', {patterns:[{urlPattern:'*'}]});
  }
  await resize(1440, 1000);
  if (kind === 'firefox') await send('browsingContext.navigate', {context, url:origin + '/', wait:'complete'});
  else await send('Page.navigate', {url:origin + '/'});
  await ready('document.querySelector("#recipeList .recipe-item")', 'workflow library');
  await ready('document.querySelector("#toolList .tool-option")', 'offline tool schemas');
  await click('#recipeList .recipe-item');
  await ready('document.querySelectorAll("#stepLane [data-index]").length === 2', 'bundled workflow');
  assert.deepEqual((await getJSON()).steps.map(step => step.step), [8,42]);
  const queryHelp = '[aria-label="Help for Variables / query extraction"]';
  const helpOpen = `document.querySelector(${JSON.stringify(queryHelp)})?.getAttribute('aria-expanded') === 'true'`;
  const helpText = `document.querySelector(${JSON.stringify(queryHelp)}).closest('.field').querySelector('.field-help-panel')`;
  const beforeHelp = await getJSON();
  assert.equal(await evaluate(helpOpen), false);
  await hover(queryHelp);
  await ready(helpOpen, 'query extraction help on hover');
  assert.equal(await evaluate(`${helpText}.hidden`), false);
  assert.match(await evaluate(`${helpText}.textContent`), /\$\{topic\}/);
  const variableExample = JSON.parse(await evaluate(`${helpText}.querySelector('pre').textContent`));
  assert.deepEqual(variableExample.subject, {from:'query',extract:'main_subject',default:'weekly news'});
  assert.deepEqual(variableExample.source_url, {from:'query',extract:'url'});
  assert.equal(variableExample.max_sources, 3);
  assert.deepEqual(await getJSON(), beforeHelp, 'Opening help never changes the recipe');
  await screenshot('query-help');
  await hover('#recipeTitle');
  await ready(`!(${helpOpen})`, 'hover help closes on pointer leave');
  await evaluate(`document.querySelector(${JSON.stringify(queryHelp)}).focus()`);
  await ready(helpOpen, 'query extraction help on keyboard focus');
  await keypress('Escape');
  await ready(`!(${helpOpen})`, 'Escape closes field help');
  await keypress('Enter');
  await ready(helpOpen, 'Enter pins field help');
  await evaluate(`document.querySelector(${JSON.stringify(queryHelp)}).blur()`);
  await hover('#recipeTitle');
  assert.equal(await evaluate(helpOpen), true, 'Pinned help remains open after pointer and focus leave');
  await evaluate(`document.querySelector(${JSON.stringify(queryHelp)}).focus()`);
  await keypress('Escape');
  await ready(`!(${helpOpen})`, 'Escape closes pinned field help');
  assert.match(await evaluate('document.querySelector("#inspectorBody .preserved-fields").textContent'), /Legacy custom partial text/);
  assert.equal(await evaluate('document.querySelectorAll("#inspectorBody .preserved-fields input, #inspectorBody .preserved-fields textarea, #inspectorBody .preserved-fields select").length'), 0);
  assert.equal(await evaluate(`document.querySelector('[aria-label="Partial speech"], [aria-label="Retry policy"]') === null`), true);
  await set('[aria-label="Variables / query extraction"]', JSON.stringify(variableExample));
  await evaluate(`(() => {
    document.querySelector('.palette-rail').open = true;
    const tool = document.querySelector('#paletteTools .palette-tool');
    const target = document.querySelector('#stepLane .connector');
    const dataTransfer = new DataTransfer();
    tool.dispatchEvent(new DragEvent('dragstart', {bubbles:true, dataTransfer}));
    target.dispatchEvent(new DragEvent('dragover', {bubbles:true, cancelable:true, dataTransfer}));
    target.dispatchEvent(new DragEvent('drop', {bubbles:true, cancelable:true, dataTransfer}));
    tool.dispatchEvent(new DragEvent('dragend', {bubbles:true, dataTransfer}));
  })()`);
  assert.deepEqual((await getJSON()).steps.map(step => step.step), [43,8,42]);
  await drag('#stepLane [data-index="0"] .node-copy', '#stepLane [data-index="2"] .node-copy');
  assert.deepEqual((await getJSON()).steps.map(step => step.step), [8,43,42], 'Dragging down inserts before the target');
  await click('#undoButton');
  assert.deepEqual((await getJSON()).steps.map(step => step.step), [43,8,42]);
  await click('#undoButton');
  assert.deepEqual((await getJSON()).steps.map(step => step.step), [8,42]);
  await click('#stepLane [data-index="0"]');
  await ready('document.querySelector("[aria-label*=expression]")', 'parameter form');
  assert.match(await evaluate('document.querySelector("#inspectorBody .preserved-fields").textContent'), /Legacy generation hint/);
  assert.equal(await evaluate(`document.querySelector('[aria-label="LLM hints"]') === null`), true);
  await set('[aria-label="expression *"]', '3+4');
  await click('#stepLane [data-index="1"] [aria-label="Move step up"]');
  await ready('document.getElementById("saveState").textContent === "Draft saved"', 'draft autosave');
  assert.deepEqual((await getJSON()).steps.map(step => step.step), [42,8]);
  assert.equal((await getJSON()).steps[1].params.expression, '3+4');
  await reload();
  assert.deepEqual((await getJSON()).steps.map(step => step.step), [42,8]);
  assert.equal((await getJSON()).steps[1].params.expression, '3+4');
  assert.equal((await getJSON()).x_extension.preserved, true);
  assert.deepEqual((await getJSON()).variables, variableExample);
  assert.deepEqual((await getJSON()).retry, {max_attempts:99});
  assert.equal((await getJSON()).partial_speech, 'Legacy custom partial text');
  assert.deepEqual((await getJSON()).steps[1].llm_hints, {note:'Legacy generation hint'});
  await click('#publishButton');
  await ready('document.getElementById("reviewDialog").open && document.getElementById("reviewTitle").textContent === "Publish personal recipe"', 'publication review');
  assert.match(await evaluate('document.querySelector("#reviewBody .publication-warning").textContent'), /Cloud execution.*commands, API calls, and schedules.*step 42.*send_email/);
  assert.equal(await evaluate('document.getElementById("trustUnattended").checked'), false, 'Recipe trust requires a new explicit choice');
  assert.equal(await evaluate('fetch("/api/workflows").then(response => response.json()).then(data => data.workflows.filter(row => row.tier === "personal").length)'), 0);
  await click('#reviewConfirm');
  await ready('document.getElementById("saveState").textContent === "Published" && !document.getElementById("runButton").disabled', 'personal publication');
  assert.equal((await getJSON()).builder_policy_version, 1);
  assert.equal((await getJSON()).builder_unattended_approval, undefined);
  await screenshot('desktop');
  // Direct HTTP on a headless LAN server need not expose secure-context APIs.
  await evaluate('(() => {Object.defineProperty(crypto, "randomUUID", {value:undefined, configurable:true}); return true;})()');
  await set('#runQuery', 'mock browser query');
  await click('#runButton');
  await ready('document.getElementById("reviewDialog").open && document.getElementById("reviewTitle").textContent === "Review live run"', 'effects confirmation');
  assert.equal((await testState()).starts, 0);
  await closeReview('#reviewCancel');
  await ready('!document.getElementById("reviewDialog").open', 'cancelled effects review');
  assert.equal((await testState()).starts, 0);
  await click('#runButton');
  await ready('document.getElementById("reviewDialog").open', 'second effects confirmation');
  await click('#reviewConfirm');
  await ready('document.querySelector(".approval-card")', 'prepared call approval');
  assert.match(await evaluate('document.querySelector(".approval-card").textContent'), /Prepared exact body/);
  assert.match(await evaluate('document.querySelector(".approval-card").textContent'), /workflow-test@example.test/);
  assert.equal((await testState()).starts, 1);
  await evaluate('Array.from(document.querySelectorAll(".approval-card button")).find(button => button.textContent === "Approve call").click()');
  await ready('document.getElementById("runStatus").textContent.includes("completed")', 'completed run');
  assert.deepEqual((await testState()).approved, [{approved:true, call_hash:'a'.repeat(64)}]);
  await ready('document.getElementById("runEvents").textContent.includes("Mock workflow completed")', 'drained terminal event pages');
  await evaluate('document.querySelectorAll("#runEvents details").forEach(details => {details.open = true;})');
  assert.match(await evaluate('document.getElementById("runEvents").textContent'), /mock-mail-id/);
  await click('#historyButton');
  await ready('document.querySelector("#reviewBody .recipe-item")', 'saved history');
  assert.match(await evaluate('document.getElementById("reviewBody").textContent'), /browser_example.*completed/);
  await closeReview('#reviewDialog [data-close]');
  await click('#stepLane [data-index="0"]');
  await evaluate('Array.from(document.querySelectorAll("#inspectorBody button")).find(button => button.textContent === "Run through this step").click()');
  await ready('document.getElementById("reviewDialog").open && document.getElementById("reviewTitle").textContent === "Review partial live run"', 'partial execution review');
  assert.match(await evaluate('document.getElementById("reviewBody").textContent'), /stops after position 1/);
  await click('#reviewConfirm');
  await ready('document.querySelector(".approval-card")', 'partial run exact call approval');
  await evaluate('Array.from(document.querySelectorAll(".approval-card button")).find(button => button.textContent === "Approve call").click()');
  await ready('document.getElementById("runStatus").textContent.includes("partial")', 'partial result status');
  await ready('document.getElementById("runEvents").textContent.includes("Mock partial run stopped after one step")', 'partial terminal events');
  assert.equal(await evaluate('document.getElementById("cancelRun").hidden'), true);
  assert.equal(await evaluate('document.getElementById("runButton").disabled'), false);
  assert.equal((await testState()).starts, 2);
  await resize(390, 844);
  const layout = await evaluate('({width:innerWidth, document:document.documentElement.scrollWidth, editor:document.querySelector(".editor").getBoundingClientRect().width, inspector:document.querySelector(".inspector").getBoundingClientRect().width})');
  assert.ok(layout.document <= layout.width + 1, JSON.stringify(layout));
  assert.ok(layout.editor <= layout.width && layout.inspector <= layout.width, JSON.stringify(layout));
  await screenshot('mobile');
  await click('#settingsButton');
  await ready(`document.querySelector(${JSON.stringify(queryHelp)})`, 'mobile query extraction help');
  const beforeTouchHelp = await getJSON();
  await tap(queryHelp);
  await ready(helpOpen, 'touch opens query extraction help');
  assert.equal(await evaluate(`${helpText}.hidden`), false);
  assert.deepEqual(await getJSON(), beforeTouchHelp);
  assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Help fits the mobile viewport');
  await ready('document.getElementById("notice").hidden', 'publication notice settles');
  await screenshot('mobile-help');
  await tap(queryHelp);
  await ready(`!(${helpOpen})`, 'second touch closes query extraction help');
  await evaluate('Array.from(document.querySelectorAll("#recipeList .recipe-item")).find(button => button.querySelector("strong").textContent === "Untouched Autonomous").click()');
  await ready('document.getElementById("recipeTitle").textContent === "Untouched Autonomous"', 'untouched bundled recipe');
  assert.equal((await getJSON()).allow_workflow_tool, true);
  await click('#publishButton');
  await ready('document.getElementById("reviewDialog").open', 'first customization review');
  assert.match(await evaluate('document.getElementById("reviewBody").textContent'), /Autonomous routing: disabled/);
  assert.equal(await evaluate('document.getElementById("trustUnattended").checked'), false);
  assert.match(await evaluate('document.getElementById("reviewBody").textContent'), /future query and model-generated arguments/);
  await click('#trustUnattended');
  await click('#reviewConfirm');
  await ready('document.getElementById("saveState").textContent === "Published"', 'first customization published');
  assert.equal((await getJSON()).allow_workflow_tool, false);
  const grant = (await getJSON()).builder_unattended_approval;
  assert.equal(grant.version, 1);
  assert.match(grant.recipe_hash, /^[a-f0-9]{64}$/);
  assert.deepEqual(grant.tools, ['send_email']);
  await click('#settingsButton');
  await set('[aria-label="Description"]', 'Trust must be reviewed again after this edit');
  await ready('document.getElementById("saveState").textContent === "Draft saved"', 'edited trusted draft saved');
  assert.equal((await getJSON()).builder_unattended_approval, undefined, 'Editing a draft strips the old definition grant');
  await click('#publishButton');
  await ready('document.getElementById("reviewDialog").open', 'trusted recipe republication review');
  assert.equal(await evaluate('document.getElementById("trustUnattended").checked'), false, 'Publishing an edit never silently preserves trust');
  await closeReview('#reviewCancel');
  await ready('!document.getElementById("reviewDialog").open', 'cancel edited publication');
  const navigation = await evaluate('fetch("/ui-navigation.js").then(response => response.text())');
  const navigationClient = navigation.slice(navigation.indexOf('\n') + 1);
  await evaluate(`(() => {
    window.__jarvisUINavigationConfig = {hostname: location.hostname, urls:{workflows:'https://workflows.example.test'}};
    (0, eval)(${JSON.stringify(navigationClient)});
  })()`);
  await ready('document.querySelector("[data-jarvis-workflows-link]")?.hidden === true', 'initial mobile navigation hidden');
  await resize(1440, 1000);
  await ready('document.querySelector("[data-jarvis-workflows-link]")?.hidden === false', 'desktop navigation visible');
  await resize(390, 844);
  await ready('document.querySelector("[data-jarvis-workflows-link]")?.hidden === true', 'resized mobile navigation hidden');
  assert.deepEqual(requests.filter(url => /^https?:/.test(url) && !url.startsWith(origin + '/')), []);
  assert.deepEqual(failures, []);
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({browser:kind, editedLabels:[42,8], autosave:true, personalPublication:true,
    exactApproval:true, completed:true, partial:true, helpHoverKeyboardTouch:true,
    mobile:layout, requests:requests.length}));
})().catch(error => {console.error(error.stack); process.exitCode = 1;}).finally(async () => {
  if (websocket) websocket.close();
  for (const request of pending.values()) clearTimeout(request.timer);
  try {process.kill(-child.pid, 'SIGTERM');} catch (_) {}
  await Promise.race([new Promise(resolve => child.once('exit', resolve)), sleep(1500)]);
  try {process.kill(-child.pid, 'SIGKILL');} catch (_) {}
});
"""


@pytest.mark.parametrize("kind", ["chromium", "firefox"])
def test_real_browser_edit_publish_approval_and_mobile(browser_app, kind):
    binary = browser_binary(kind)
    if binary is None:
        pytest.skip(f"Existing {kind} binary required; set WORKFLOW_TEST_{kind.upper()}")
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node 22 with built-in WebSocket is required")
    origin, directory, runner, bundled, original = browser_app
    result = subprocess.run(
        [node, "-e", JOURNEY], cwd=ROOT,
        env={**os.environ, "BROWSER_KIND": kind, "BROWSER_BINARY": str(binary),
             "APP_ORIGIN": origin, "TEST_DIRECTORY": str(directory)},
        capture_output=True, text=True, timeout=75,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert runner.starts == 2 and runner.approved == [{"approved": True, "call_hash": "a" * 64}] * 2
    assert bundled.read_text() == original
    personal = json.loads((directory / "data/workflows/personal/browser_example.json").read_text())
    assert [step["step"] for step in personal["steps"]] == [42, 8]
    assert personal["steps"][1]["params"]["expression"] == "3+4"
    assert personal["x_extension"] == {"preserved": True}
    assert personal["builder_policy_version"] == 1
    assert "builder_unattended_approval" not in personal
    assert personal["retry"] == {"max_attempts": 99}
    assert personal["partial_speech"] == "Legacy custom partial text"
    assert personal["steps"][1]["llm_hints"] == {"note": "Legacy generation hint"}
    trusted = json.loads((directory / "data/workflows/personal/untouched_autonomous.json").read_text())
    assert trusted["builder_unattended_approval"]["version"] == 1
    assert trusted["builder_unattended_approval"]["tools"] == ["send_email"]
