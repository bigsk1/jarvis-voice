#!/usr/bin/env python3
"""Regression tests for generic Canvas audio embedding."""

import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANVAS_ROOT = PROJECT_ROOT / "jarvis-canvas"


def test_canvas_client_prefers_matching_stash_audio_over_remote_source():
    canvas_js = CANVAS_ROOT / "client" / "static" / "js" / "canvas.js"
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(canvas_js))}, 'utf8');
const start = source.indexOf('function inferAudioMimeType');
const end = source.indexOf('function getFilteredPages', start);
if (start < 0 || end < 0) process.exit(1);
const sandbox = {{
  window: {{ location: {{ origin: 'http://canvas.test' }} }},
  URL,
  console,
  cleanStashFileIdSegment: value => String(value).replace(/(?:%2560|%60|`)+$/gi, ''),
  escapeHtml: value => String(value),
  fetch: async url => ({{
    ok: true,
    json: async () => JSON.parse({json.dumps(json.dumps({
        'name': 'music_midnight_drive.mp3',
        'mime_type': 'audio/mpeg',
        'source_url': 'https://example.test/final.mp3',
    }))})
  }})
}};
vm.createContext(sandbox);
vm.runInContext(source.slice(start, end), sandbox);
(async () => {{
  const content = '[Play](https://example.test/final.mp3)\\n`stash://space_music/f_music`';
  const candidates = sandbox.collectPageAudioCandidates(content);
  if (candidates.directUrls.length !== 1 || candidates.stashRefs.length !== 1) process.exit(2);
  const embeds = await sandbox.collectPageAudioEmbeds(content);
  if (embeds.length !== 1) process.exit(3);
  if (embeds[0].playbackUrl !== '/api/stash/space_music/f_music') process.exit(4);
  if (!embeds[0].stashed || embeds[0].mimeType !== 'audio/mpeg') process.exit(5);
  const html = sandbox.renderNativeAudioEmbeds(embeds);
  if (!html.includes('<audio') || !html.includes('controls preload="metadata"')) process.exit(6);
  if (!html.includes('Open audio') || !html.includes('music midnight drive')) process.exit(7);
}})().catch(() => process.exit(8));
"""

    subprocess.run(["node", "-e", script], check=True, cwd=PROJECT_ROOT)


def test_canvas_page_mounts_and_hydrates_native_audio_player():
    canvas_js = (CANVAS_ROOT / "client" / "static" / "js" / "canvas.js").read_text()
    canvas_css = (CANVAS_ROOT / "client" / "static" / "css" / "canvas.css").read_text()

    assert 'data-canvas-native-audio' in canvas_js
    assert "hydratePageAudioEmbeds(page, pageView)" in canvas_js
    assert 'class="canvas-audio-player" controls preload="metadata"' in canvas_js
    assert ".canvas-audio-player" in canvas_css
