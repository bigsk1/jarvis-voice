#!/usr/bin/env python3
"""Regression tests for the Jarvis Web inline Canvas preview."""

import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHAT_JS = PROJECT_ROOT / "jarvis-web" / "client" / "js" / "chat.js"
SOCKET_JS = PROJECT_ROOT / "jarvis-web" / "client" / "js" / "socket.js"
MAIN_CSS = PROJECT_ROOT / "jarvis-web" / "client" / "css" / "main.css"


def test_structured_canvas_result_builds_clickable_preview():
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(CHAT_JS))}, 'utf8');
const start = source.indexOf('  _extractCanvasPreview(');
const end = source.indexOf('  _normalizeDisplayText(', start);
const classSource = `class PreviewHarness {{\n${{source.slice(start, end)}}\n}}; PreviewHarness;`;
const escapeHtml = value => String(value)
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;');
const sandbox = {{
  URL,
  window: {{ location: {{ hostname: 'web.test' }} }},
  Utils: {{
    escapeHtml,
    safeHttpUrlForAttr: value => {{
      const parsed = new URL(value);
      return ['http:', 'https:'].includes(parsed.protocol) ? escapeHtml(parsed.href) : '';
    }}
  }},
  console,
  fetch: async () => ({{ ok: false }}),
  CSS: {{ escape: value => String(value) }}
}};
vm.createContext(sandbox);
const PreviewHarness = vm.runInContext(classSource, sandbox);
const harness = new PreviewHarness();
const preview = harness._extractCanvasPreview({{
  canvas: {{
    page_id: 'page_20260627_062044',
    title: 'Jarvis Avatar Preference: Cyberpunk AI Aesthetic',
    url: 'http://192.168.70.228:8890/page_20260627_062044',
    base_url: 'http://192.168.70.228:8890'
  }}
}});
if (!preview) process.exit(2);
if (preview.apiUrl !== 'http://192.168.70.228:8890/api/pages/page_20260627_062044') process.exit(3);
const html = harness._renderCanvasPreviewHtml(preview);
if (!html.includes('canvas-preview-thumbnail')) process.exit(4);
if (!html.includes('Jarvis Avatar Preference')) process.exit(5);
if (!html.includes('Open in Canvas')) process.exit(6);
const imageUrl = harness._canvasPreviewImageUrl(
  '![Preferred avatar](stash://space_avatar/f_image)',
  preview
);
if (imageUrl !== 'http://192.168.70.228:8890/api/stash/space_avatar/f_image') process.exit(7);
const excerpt = harness._canvasPreviewExcerpt('# Heading\\n\\n![Image](stash://space/file)\\nUseful **page** details.');
if (excerpt !== 'Heading Useful page details.') process.exit(8);
"""

    subprocess.run(["node", "-e", script], cwd=PROJECT_ROOT, check=True)


def test_live_workflow_result_builds_canvas_preview_from_nested_steps():
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(CHAT_JS))}, 'utf8');
const start = source.indexOf('  _flattenWorkflowToolResults(');
const end = source.indexOf('  _renderCanvasPreviewHtml(', start);
const classSource = `class WorkflowPreviewHarness {{\n${{source.slice(start, end)}}\n}}; WorkflowPreviewHarness;`;
const sandbox = {{
  URL,
  window: {{ location: {{ hostname: 'web.test' }} }}
}};
vm.createContext(sandbox);
const WorkflowPreviewHarness = vm.runInContext(classSource, sandbox);
const harness = new WorkflowPreviewHarness();
const flattened = harness._flattenWorkflowToolResults({{
  workflow_id: 'deep_research',
  results: [
    {{ step: 1, tool: 'stash', data: {{ space_id: 'space_1' }} }},
    {{
      step: 6,
      tool: 'canvas',
      data: {{
        page_id: 'page_20260704_153800',
        title: 'Workflows/Research/Hazelnuts',
        url: 'http://web.test:8890/page_20260704_153800'
      }}
    }},
    {{
      step: 7,
      tool: 'canvas',
      skipped: true,
      reason: 'Condition evaluated to false'
    }}
  ]
}});
if (Array.isArray(flattened.canvas)) process.exit(2);
const preview = harness._extractCanvasPreview(flattened, {{}});
if (!preview) process.exit(3);
if (preview.pageId !== 'page_20260704_153800') process.exit(4);
if (preview.title !== 'Workflows/Research/Hazelnuts') process.exit(5);
"""

    subprocess.run(["node", "-e", script], cwd=PROJECT_ROOT, check=True)


def test_live_response_can_recover_canvas_preview_from_tool_trace():
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(CHAT_JS))}, 'utf8');
const start = source.indexOf('  _extractCanvasPreview(');
const end = source.indexOf('  _normalizeDisplayText(', start);
const classSource = `class PreviewHarness {{\n${{source.slice(start, end)}}\n}}; PreviewHarness;`;
const sandbox = {{ URL, window: {{ location: {{ hostname: 'web.test' }} }} }};
vm.createContext(sandbox);
const PreviewHarness = vm.runInContext(classSource, sandbox);
const harness = new PreviewHarness();
const preview = harness._extractCanvasPreview({{}}, {{
  _tool_trace: [
    {{
      tool: 'canvas',
      ok: true,
      arguments: {{
        action: 'append',
        page_id: 'page_20260704_223806',
        title: 'Workflows/Research/Hazelnuts'
      }}
    }}
  ]
}});
if (!preview) process.exit(2);
if (preview.pageId !== 'page_20260704_223806') process.exit(3);
if (preview.title !== 'Workflows/Research/Hazelnuts') process.exit(4);
"""

    subprocess.run(["node", "-e", script], cwd=PROJECT_ROOT, check=True)


def test_live_tool_state_is_scoped_by_message_id():
    chat_js = CHAT_JS.read_text()

    assert "this.pendingToolsByMessage = new Map()" in chat_js
    assert "this._activatePendingToolsForMessage(data.message_id" in chat_js
    assert "this._reconcilePendingToolsWithFinalList(toolsUsed, toolTraceEntries)" in chat_js
    assert "this._clearPendingToolsForMessage(liveMessageId)" in chat_js


def test_final_tool_list_repairs_missed_live_progress_events_without_cross_message_leakage():
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(CHAT_JS))}, 'utf8');
const start = source.indexOf('  _activatePendingToolsForMessage(');
const end = source.indexOf('  sendResponseToCanvas(', start);
const classSource = `class ToolStateHarness {{\n${{source.slice(start, end)}}\n}}; ToolStateHarness;`;
const sandbox = {{ console }};
vm.createContext(sandbox);
const ToolStateHarness = vm.runInContext(classSource, sandbox);
const harness = new ToolStateHarness();
harness.pendingTools = {{}};
harness.pendingToolsByMessage = new Map();
harness.pendingToolMessageId = null;

harness._activatePendingToolsForMessage('message-a', true);
harness.pendingTools.search = {{ toolName: 'serpapi_youtube_search', status: 'success' }};
harness.pendingTools.canvas = {{ toolName: 'canvas', status: 'success' }};
harness._reconcilePendingToolsWithFinalList([
  'serpapi_youtube_search', 'canvas', 'canvas', 'canvas', 'manage_intel'
]);
const names = Object.values(harness.pendingTools).map(item => item.toolName);
if (names.length !== 5) process.exit(2);
if (names.filter(name => name === 'canvas').length !== 3) process.exit(3);

harness._activatePendingToolsForMessage('message-b', true);
if (Object.keys(harness.pendingTools).length !== 0) process.exit(4);
harness.pendingTools.stash = {{ toolName: 'stash', status: 'pending' }};
harness._activatePendingToolsForMessage('message-a');
if (Object.keys(harness.pendingTools).length !== 5) process.exit(5);
harness._clearPendingToolsForMessage('message-a');
harness._activatePendingToolsForMessage('message-b');
if (!harness.pendingTools.stash) process.exit(6);
"""

    subprocess.run(["node", "-e", script], cwd=PROJECT_ROOT, check=True)


def test_tool_trace_reconciles_failed_card_in_original_order():
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(CHAT_JS))}, 'utf8');
const start = source.indexOf('  _reconcilePendingToolsWithFinalList(');
const end = source.indexOf('  /**\\n   * Show feedback card', start);
const classSource = `class ToolTraceHarness {{\n${{source.slice(start, end)}}\n}}; ToolTraceHarness;`;
const sandbox = {{ console }};
vm.createContext(sandbox);
const ToolTraceHarness = vm.runInContext(classSource, sandbox);
const harness = new ToolTraceHarness();
harness.pendingToolMessageId = 'message-a';
harness.pendingToolsByMessage = new Map();
harness.pendingTools = {{
  tool_search: {{ toolName: 'tool_search', status: 'success', result: {{ matches: [] }} }},
  serpapi_yelp_search: {{ toolName: 'serpapi_yelp_search', status: 'error', result: {{ error: 'No results' }} }},
  serpapi_maps_search: {{ toolName: 'serpapi_maps_search', status: 'success', result: {{ places: [] }} }}
}};

harness._reconcilePendingToolsWithFinalList(
  ['tool_search', 'serpapi_maps_search'],
  [
    {{ tool: 'tool_search', ok: true, duration_ms: 10 }},
    {{ tool: 'serpapi_yelp_search', ok: false, error: 'No results', duration_ms: 20 }},
    {{ tool: 'serpapi_maps_search', ok: true, duration_ms: 30 }}
  ]
);

const entries = Object.values(harness.pendingTools);
if (entries.map(entry => entry.toolName).join(',') !== 'tool_search,serpapi_yelp_search,serpapi_maps_search') process.exit(2);
if (entries[1].status !== 'error') process.exit(3);
if (entries[1].result.error !== 'No results') process.exit(4);
"""

    subprocess.run(["node", "-e", script], cwd=PROJECT_ROOT, check=True)


def test_workflow_results_reconcile_cards_in_step_order_with_duplicates_and_skips():
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(CHAT_JS))}, 'utf8');
const start = source.indexOf('  _reconcilePendingToolsWithFinalList(');
const end = source.indexOf('  /**\\n   * Show feedback card', start);
const classSource = `class WorkflowOrderHarness {{\\n${{source.slice(start, end)}}\\n}}; WorkflowOrderHarness;`;
const sandbox = {{ console }};
vm.createContext(sandbox);
const WorkflowOrderHarness = vm.runInContext(classSource, sandbox);
const harness = new WorkflowOrderHarness();
harness.pendingToolMessageId = 'message-a';
harness.pendingToolsByMessage = new Map();
harness.pendingTools = {{
  get_time_step1: {{ toolName: 'get_time', status: 'success', result: {{}} }},
  serpapi_google_local_step3: {{ toolName: 'serpapi_google_local', status: 'success', result: {{}} }},
  serpapi_yelp_search_step5: {{ toolName: 'serpapi_yelp_search', status: 'success', result: {{}} }},
  serpapi_tripadvisor_step6: {{ toolName: 'serpapi_tripadvisor', status: 'success', result: {{}} }},
  canvas_step7: {{ toolName: 'canvas', status: 'success', result: {{}} }},
  weather_step2: {{ toolName: 'weather', status: 'success', result: {{}} }},
  serpapi_google_local_step4: {{ toolName: 'serpapi_google_local', status: 'success', result: {{}} }}
}};

const workflowData = {{
  workflow_id: 'night_out',
  results: [
    {{ step: 1, tool: 'get_time', ok: true, duration_ms: 10 }},
    {{ step: 2, tool: 'weather', skipped: true, reason: 'Condition evaluated to false' }},
    {{ step: 3, tool: 'serpapi_google_local', ok: true, duration_ms: 20 }},
    {{ step: 4, tool: 'serpapi_google_local', ok: true, duration_ms: 30 }},
    {{ step: 5, tool: 'serpapi_yelp_search', ok: true, duration_ms: 40 }},
    {{ step: 6, tool: 'serpapi_tripadvisor', ok: true, duration_ms: 50 }},
    {{ step: 7, tool: 'canvas', ok: true, duration_ms: 60 }}
  ]
}};
const trace = harness._getToolTraceEntries(workflowData);
harness._reconcilePendingToolsWithFinalList(
  ['get_time', 'serpapi_google_local', 'serpapi_yelp_search', 'serpapi_tripadvisor', 'canvas'],
  trace
);

const names = Object.values(harness.pendingTools).map(entry => entry.toolName);
const expected = [
  'get_time',
  'weather',
  'serpapi_google_local',
  'serpapi_google_local',
  'serpapi_yelp_search',
  'serpapi_tripadvisor',
  'canvas'
];
if (names.join(',') !== expected.join(',')) process.exit(2);
if (trace.length !== 7) process.exit(3);
if (trace[1].speech !== 'Condition evaluated to false') process.exit(4);
if (trace[1].skipped !== true) process.exit(5);
const cards = Object.values(harness.pendingTools);
if (cards[1].status !== 'skipped') process.exit(6);
if (cards[1].result !== 'Condition evaluated to false') process.exit(7);

const ordinaryTrace = harness._getToolTraceEntries({{
  _tool_trace: [{{ tool: 'weather', ok: true, duration_ms: 70 }}]
}});
if (ordinaryTrace.length !== 1 || ordinaryTrace[0].tool !== 'weather') process.exit(8);
"""

    subprocess.run(["node", "-e", script], cwd=PROJECT_ROOT, check=True)


def test_live_pending_tool_cards_skip_failures_when_indexing_success_results():
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(CHAT_JS))}, 'utf8');
const start = source.indexOf('  _getToolResultForOccurrence(');
const end = source.indexOf('  /**\\n   * Show feedback card', start);
const classSource = `class PendingCardHarness {{\n${{source.slice(start, end)}}\n}}; PendingCardHarness;`;
const sandbox = {{}};
vm.createContext(sandbox);
const PendingCardHarness = vm.runInContext(classSource, sandbox);
const harness = new PendingCardHarness();

const entries = harness._getPendingToolCardEntries(
  {{
    serpapi_yelp_search: [
      {{ result_id: 'first-success' }},
      {{ result_id: 'second-success' }}
    ]
  }},
  [
    ['serpapi_yelp_search', {{
      toolName: 'serpapi_yelp_search',
      status: 'error',
      result: {{ error: 'No Yelp results' }},
      duration: 20
    }}],
    ['serpapi_yelp_search_1', {{
      toolName: 'serpapi_yelp_search',
      status: 'skipped',
      result: 'Condition evaluated to false',
      duration: null
    }}],
    ['serpapi_yelp_search_2', {{
      toolName: 'serpapi_yelp_search',
      status: 'success',
      result: null,
      duration: 30
    }}]
  ]
);

if (entries.length !== 3) process.exit(2);
if (entries[0].status !== 'error') process.exit(3);
if (entries[0].result.error !== 'No Yelp results') process.exit(4);
if (entries[1].status !== 'skipped') process.exit(5);
if (entries[1].result !== 'Condition evaluated to false') process.exit(6);
if (entries[2].status !== 'success') process.exit(7);
if (entries[2].result.result_id !== 'first-success') process.exit(8);
"""

    subprocess.run(["node", "-e", script], cwd=PROJECT_ROOT, check=True)


def test_skipped_tool_card_is_distinct_from_successful_empty_result():
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(CHAT_JS))}, 'utf8');
const start = source.indexOf('  _createToolCardHtml(');
const end = source.indexOf('  _getToolResultForOccurrence(', start);
const classSource = `class ToolCardHarness {{\n${{source.slice(start, end)}}\n}}; ToolCardHarness;`;
const sandbox = {{
  Utils: {{
    escapeHtml: value => String(value),
    escapeHtmlAndLinkify: value => String(value),
    formatJson: value => JSON.stringify(value, null, 2),
    formatDuration: value => `${{value}}ms`
  }}
}};
vm.createContext(sandbox);
const ToolCardHarness = vm.runInContext(classSource, sandbox);
const harness = new ToolCardHarness();

const skipped = harness._createToolCardHtml(
  'send_email', 'skipped', 'Condition evaluated to false'
);
if (!skipped.includes('tool-card skipped')) process.exit(2);
if (!skipped.includes('⏭ Skipped')) process.exit(3);
if (!skipped.includes('Condition evaluated to false')) process.exit(4);
if (skipped.includes('Complete')) process.exit(5);

const emptySuccess = harness._createToolCardHtml('empty_tool', 'success', {{}});
if (!emptySuccess.includes('tool-card success')) process.exit(6);
if (!emptySuccess.includes('✅ Complete')) process.exit(7);
"""

    subprocess.run(["node", "-e", script], cwd=PROJECT_ROOT, check=True)


def test_canvas_preview_keeps_assistant_reply_bubble():
    chat_js = CHAT_JS.read_text()

    assert "const messageBubbleHtml = `" in chat_js
    assert "${canvasPreviewHtml}" in chat_js
    assert "${messageBubbleHtml}" in chat_js
    bubble_start = chat_js.index("const messageBubbleHtml = `")
    render_start = chat_js.index("messageEl.innerHTML = `", bubble_start)
    render_end = chat_js.index("`;", render_start)
    render_order = chat_js[render_start:render_end]
    assert render_order.index("${youtubeEmbedsHtml}") < render_order.index("${canvasPreviewHtml}")
    assert render_order.index("${canvasPreviewHtml}") < render_order.index("${messageBubbleHtml}")
    assert "hideCanvasReceipt" not in chat_js
    assert "_isCanvasReceiptOnly" not in chat_js


def test_canvas_preview_hydrates_stash_image_and_text_excerpt():
    chat_js = CHAT_JS.read_text()
    css = MAIN_CSS.read_text()

    assert "_canvasPreviewImageUrl" in chat_js
    assert "/api/stash/" in chat_js
    assert "_canvasPreviewExcerpt" in chat_js
    assert ".canvas-preview-thumbnail" in css
    assert "aspect-ratio: 3 / 4" in css


def test_send_to_canvas_marks_explicit_export_request():
    chat_js = CHAT_JS.read_text()
    socket_js = SOCKET_JS.read_text()

    assert "{ tool_hints: ['canvas'], request_kind: 'canvas_export', tool_rag_limit: 3 }" in chat_js
    assert "Treat structured prior tool results as authoritative content" in chat_js
    assert "Selected response preview:" in chat_js
    assert "The selected response begins:" not in chat_js
    assert "payload.request_kind = promptMeta.request_kind" in socket_js
    assert "payload.tool_rag_limit = promptMeta.tool_rag_limit" in socket_js


def test_send_to_canvas_excerpt_uses_canonical_truncation_marker_and_drops_partial_url():
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(CHAT_JS))}, 'utf8');
const start = source.indexOf('  _normalizeDisplayText(');
const end = source.indexOf('  _inferVideoMimeType(', start);
const classSource = `class ExcerptHarness {{\n${{source.slice(start, end)}}\n}}; ExcerptHarness;`;
const sandbox = {{}};
vm.createContext(sandbox);
const ExcerptHarness = vm.runInContext(classSource, sandbox);
const harness = new ExcerptHarness();

const prefix = 'SpaceX coverage ' + 'detail '.repeat(110);
const longResponse = prefix + 'https://example.com/a-very-long-source-url-that-must-not-be-cut';
const excerpt = harness._buildCanvasExportExcerpt(longResponse, 800);
if (!excerpt.endsWith('... [truncated]')) process.exit(2);
if (excerpt.includes('https://example.com/')) process.exit(3);

const exact = 'x'.repeat(800);
if (harness._buildCanvasExportExcerpt(exact, 800) !== exact) process.exit(4);
"""

    subprocess.run(["node", "-e", script], cwd=PROJECT_ROOT, check=True)
