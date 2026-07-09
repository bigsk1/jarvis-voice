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
    }}
  ]
}});
const preview = harness._extractCanvasPreview(flattened, {{}});
if (!preview) process.exit(2);
if (preview.pageId !== 'page_20260704_153800') process.exit(3);
if (preview.title !== 'Workflows/Research/Hazelnuts') process.exit(4);
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
    assert "this._reconcilePendingToolsWithFinalList(toolsUsed)" in chat_js
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


def test_canvas_preview_keeps_assistant_reply_bubble():
    chat_js = CHAT_JS.read_text()

    assert "const messageBubbleHtml = `" in chat_js
    assert "${canvasPreviewHtml}" in chat_js
    assert "${messageBubbleHtml}" in chat_js
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
