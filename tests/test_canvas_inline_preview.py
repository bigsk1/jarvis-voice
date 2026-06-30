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
if (!harness._isCanvasReceiptOnly('Canvas page created successfully: "Example". View at: http://canvas.test/page')) process.exit(7);
if (harness._isCanvasReceiptOnly('The top options are A, B, and C. I saved the full comparison to Canvas.')) process.exit(8);
const imageUrl = harness._canvasPreviewImageUrl(
  '![Preferred avatar](stash://space_avatar/f_image)',
  preview
);
if (imageUrl !== 'http://192.168.70.228:8890/api/stash/space_avatar/f_image') process.exit(9);
const excerpt = harness._canvasPreviewExcerpt('# Heading\\n\\n![Image](stash://space/file)\\nUseful **page** details.');
if (excerpt !== 'Heading Useful page details.') process.exit(10);
"""

    subprocess.run(["node", "-e", script], cwd=PROJECT_ROOT, check=True)


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

    assert "{ tool_hints: ['canvas'], request_kind: 'canvas_export' }" in chat_js
    assert "payload.request_kind = promptMeta.request_kind" in socket_js


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
