"""Generic external-result previews use one safe, bounded browser contract."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "jarvis-web/client/js"


def run_renderer(assertions):
    scripts = [CLIENT / f"structured-results{suffix}.js"
               for suffix in ("-shopping", "-search", "-local-travel", "")]
    setup = r'''
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const escapeHtml = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const sandbox = {URL, console, Utils: {escapeHtml, safeHttpUrlForAttr: value => {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol)
    ? escapeHtml(url.href) : ''; } catch { return ''; }
}}};
sandbox.window = sandbox;
vm.createContext(sandbox);
for (const script of SCRIPTS) vm.runInContext(fs.readFileSync(script, 'utf8'), sandbox);
const renderer = sandbox.structuredResultsRenderer;
const envelope = (result, extra = {}) => ({contract: 'external_result_v1',
  source: {provider: 'apify', tool: 'call-actor', mode: 'local'},
  execution: {run_id: 'run_example', actor_id: 'owner/example', status: 'SUCCEEDED'},
  result, ...extra});
'''
    command = "const SCRIPTS=" + json.dumps([str(path) for path in scripts]) + ";\n"
    subprocess.run(["node", "-e", command + setup + assertions],
                   cwd=ROOT, check=True, timeout=15)


def test_external_contract_renders_unknown_tools_and_heterogeneous_json_safely():
    run_renderer(r'''
const tools = JSON.stringify(renderer.registeredTools());
const payload = envelope({kind: 'json', items: [
  {'<img src=x>': '<script>alert(1)</script>', url: 'javascript:alert(2)',
    nested: {rating: 0, valid: false, tags: ['a', null]}},
  'plain text', 0, false, null, ['nested'], {other: 'last row'},
], sample_count: 7, returned_count: 7, offset: 25, total_items: 103, complete: false,
  dataset_id: 'dataset_example', pagination: {has_more: true, next_offset: 32}}, {
  raw_ref: 'stash://space_example/f_raw', artifacts: [
    {ref: 'stash://space_example/f_raw', name: 'Duplicate raw'},
    {ref: 'stash://space_example/f_rows', name: '<rows>.json',
      download_url: 'https://evil.example/wrong'},
    {ref: 'stash://space_example/../config', name: 'Invalid'},
    {ref: 'javascript:alert(3)', name: 'Invalid scheme'},
  ], limits: {sample_truncated: true},
});
const html = renderer.render(JSON.parse(JSON.stringify({future_actor_tool: {data: payload}})));
for (const text of ['Rows 26–32 of 103', 'Page returned 7 items', 'Partial result',
  'More pages available', 'Preview shortened', 'Run: run_example', 'Dataset: dataset_example',
  'Inspect sample JSON', 'rating:', 'false', 'last row', '&lt;script&gt;', '&lt;img src=x&gt;',
  '/api/stash/space_example/f_raw?mode=local', '/api/stash/space_example/f_rows?mode=local',
  'Download &lt;rows&gt;.json']) assert.ok(html.includes(text), text);
assert.equal((html.match(/href=/g) || []).length, 2, 'Only canonical Stash artifacts become links');
for (const text of ['<script>', '<img', 'href="javascript:', 'evil.example', '../config']) {
  assert.ok(!html.includes(text), text);
}
assert.equal(JSON.stringify(renderer.registeredTools()), tools, 'No Actor adapters are registered');
''')


def test_external_previews_bound_rows_columns_text_and_nested_trees():
    run_renderer(r'''
const items = Array.from({length: 50}, (_, index) => Object.fromEntries([
  ['name', `unique-row-${String(index + 1).padStart(3, '0')}`],
  ...Array.from({length: 12}, (_, field) => [`field_${field}`, field]),
  ['deep', {a: {b: {c: {d: {e: {f: 'below-depth-limit'}}}}}}],
  ['wide', Object.fromEntries(Array.from({length: 100}, (_, n) => [`wide-${n}`, 'x'.repeat(5000)]))],
]));
const html = renderer.render({any_tool: envelope({items, offset: 0, total_items: 50, complete: true})});
assert.ok(html.includes('Rows 1–20 of 50'));
assert.ok(html.includes('Preview shortened'));
assert.ok(html.includes('fields omitted from the table. JSON details are also bounded'));
assert.ok(html.includes('unique-row-020'));
assert.ok(!html.includes('unique-row-021'));
assert.ok(!html.includes('below-depth-limit'));
assert.ok(html.includes('depth limit reached'));
assert.ok(html.includes('entries omitted from preview'));
assert.ok(html.length < 230000, 'Nested arbitrary data remains a bounded preview');

const text = renderer.render({text_tool: envelope({text: 'x'.repeat(15000), complete: null})});
assert.ok(text.includes('Text preview shortened'));
assert.ok(text.includes('Completeness unknown'));
assert.ok(text.length < 14000);
for (const value of [0, false, null]) {
  const scalar = renderer.render({scalar_tool: envelope({value, complete: true})});
  assert.ok(scalar.includes('Complete result'));
  assert.ok(scalar.includes(`<code>${String(value)}</code>`));
}
const empty = renderer.render({empty_tool: envelope({items: [], total_items: 0, complete: true})});
assert.ok(empty.includes('0 rows of 0'));
assert.ok(empty.includes('No items in this page'));
''')


def test_external_contract_preserves_call_occurrences_and_workflow_sections():
    run_renderer(r'''
const first = envelope({text: 'First external response', complete: false});
const last = envelope({text: 'Second external response', complete: true});
const results = {future_tool: [first, last], _tool_trace: [
  {tool: 'future_tool', ok: true}, {tool: 'future_tool', ok: false},
  {tool: 'future_tool', ok: true},
]};
const html = renderer.render(results);
assert.ok(html.includes('First external response'));
assert.ok(html.includes('Second external response'));
assert.ok(html.indexOf('First external response') < html.indexOf('Second external response'));
assert.ok(html.includes('data-orchestration-call="3"'));
assert.ok(html.includes('data-orchestration-occurrence="2"'));
assert.ok(html.includes('1 failed'));
const latest = renderer.render({future_tool: [first, last]});
assert.ok(latest.includes('Second external response'));
assert.ok(!latest.includes('First external response'));

const workflow = renderer.render({workflow: {workflow_id: 'research', results: [
  {step: 1, tool: 'unknown_provider_tool', ok: true, outputs: [{data: first}]},
  {step: 2, tool: 'another_provider_tool', ok: true, data: last},
]}});
assert.ok(workflow.includes('First external response'));
assert.ok(workflow.includes('Second external response'));
assert.ok(workflow.includes('data-workflow-tool="unknown_provider_tool"'));
assert.ok(workflow.includes('data-workflow-step="2"'));
assert.equal((workflow.match(/aria-label="External result"/g) || []).length, 2);
assert.ok(!renderer.registeredTools().includes('unknown_provider_tool'));
const directWorkflow = renderer.render({workflow_id: 'direct', results: [
  {step: 1, tool: 'another_provider_tool', ok: true, data: {data: last}},
]});
assert.equal((directWorkflow.match(/aria-label="External result"/g) || []).length, 1);
''')


def test_external_downloads_require_valid_ref_and_explicit_saved_mode():
    run_renderer(r'''
for (const mode of ['', 'invalid', undefined]) {
  const html = renderer.render({test_tool: envelope({value: '<b>literal</b>'}, {
    source: {provider: 'test', tool: 'read-result', mode},
    raw_ref: 'stash://space_example/f_raw',
  })});
  assert.ok(html.includes('&lt;b&gt;literal&lt;/b&gt;'));
  assert.ok(!html.includes('href='), 'Missing or invalid mode must not guess another dataset');
}
const cloud = renderer.render({test_tool: envelope({value: {}}, {
  artifacts: [{stash_ref: 'stash://space_example/f_cloud', mode: 'cloud', name: 'cloud.json'}],
})});
assert.ok(cloud.includes('/api/stash/space_example/f_cloud?mode=cloud'));
const unsaved = renderer.render({test_tool: envelope({text: 'Useful response'}, {
  limits: {raw_retention_error: 'OSError'},
})});
assert.ok(unsaved.includes('Raw download unavailable'));
assert.ok(unsaved.includes('Useful response'));
''')


def test_real_backend_projection_keeps_page_counts_distinct_from_preview():
    from lib.external_results import make_external_result_data, project_external_result

    payload = make_external_result_data(
        provider="fixture-provider", tool="dataset-read", mode="local", stash_raw=False,
        raw_ref="stash://space_fixture/f_archive",
        result={"kind": "array", "items": [{"number": index} for index in range(30)],
                "returned_count": 30, "offset": 10, "total_items": 40, "complete": False},
    )
    projected = project_external_result(payload, sample_limit=5)
    run_renderer("const projected=" + json.dumps(projected) + ";\n" + r'''
const html = renderer.render({any_dataset_tool: {data: projected}});
for (const text of ['Rows 11–15 of 40', 'Page returned 30 items', 'Partial result',
  'Preview shortened', '/api/stash/space_fixture/f_archive?mode=local']) {
  assert.ok(html.includes(text), text);
}
''')


def test_external_preview_labels_large_integer_strings_without_rounding():
    run_renderer(r'''
const exact = '9007199254740993';
const html = renderer.render({future_tool: envelope({items: [{id: exact}], complete: true}, {
  limits: {integer_strings: true}, raw_ref: 'stash://space_example/f_original',
})});
assert.ok(html.includes('Large integers shown as exact text'));
assert.ok(html.includes(exact));
assert.ok(!html.includes('9007199254740992'));
assert.ok(html.includes('/api/stash/space_example/f_original?mode=local'));
''')


def test_backend_wire_preserves_unsafe_count_metadata_and_row_arithmetic():
    from lib.external_results import make_external_result_data, project_external_result

    offset = 9007199254740993
    payload = make_external_result_data(
        provider="fixture-provider", tool="dataset-read", mode="local", stash_raw=False,
        raw_ref="stash://space_fixture/f_archive",
        result={"kind": "array", "items": [{"value": "first"}, {"value": "second"}],
                "returned_count": offset + 2, "offset": offset,
                "total_items": offset + 1000, "complete": False},
    )
    wire = json.dumps(project_external_result(payload))
    run_renderer("const wire=" + json.dumps(wire) + ";\n" + r'''
const html = renderer.render({any_dataset_tool: {data: JSON.parse(wire)}});
for (const text of ['Rows 9007199254740994–9007199254740995 of 9007199254741993',
  'Page returned 9007199254740995 items', 'Row 9007199254740994',
  '<th scope="row">9007199254740995</th>', 'Large integers shown as exact text']) {
  assert.ok(html.includes(text), text);
}
assert.ok(!html.includes('total unknown'));
assert.ok(!html.includes('Rows 1–2'));
const huge = '9'.repeat(128);
const canonical = renderer.render({tool: envelope({items: [0], offset: huge,
  total_items: huge, returned_count: '1', complete: false})});
assert.ok(canonical.includes(`Rows ${'1' + '0'.repeat(128)}–${'1' + '0'.repeat(128)} of ${huge}`));
assert.ok(canonical.includes('Page returned 1 item ·'));
''')
