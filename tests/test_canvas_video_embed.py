#!/usr/bin/env python3
"""Regression tests for generic Canvas video embedding."""

import json
import subprocess
import sys
from pathlib import Path

from flask import Flask


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANVAS_ROOT = PROJECT_ROOT / "jarvis-canvas"
sys.path.insert(0, str(CANVAS_ROOT))

from server.routes import stash as stash_routes  # noqa: E402


def test_stash_metadata_reports_video_without_tool_specific_logic(tmp_path, monkeypatch):
    stash_root = tmp_path / "stash"
    space = stash_root / "space_video"
    space.mkdir(parents=True)
    video_path = space / "social_clip.mp4"
    video_path.write_bytes(b"fake-mp4")
    (space / "meta.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "file_id": "f_video",
                        "name": "social_clip.mp4",
                        "stored_name": "social_clip.mp4",
                        "mime_type": "video/mp4",
                        "size_bytes": 8,
                        "source_url": "https://example.test/final.mp4",
                        "tool_origin": "future_video_tool",
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(stash_routes, "STASH_DIR", stash_root)

    app = Flask(__name__)
    app.register_blueprint(stash_routes.stash_bp)
    client = app.test_client()

    response = client.get("/api/stash/space_video/f_video/metadata")

    assert response.status_code == 200
    assert response.get_json() == {
        "file_id": "f_video",
        "mime_type": "video/mp4",
        "name": "social_clip.mp4",
        "size_bytes": 8,
        "source_url": "https://example.test/final.mp4",
        "space_id": "space_video",
        "tags": [],
        "tool_origin": "future_video_tool",
    }
    assert client.head("/api/stash/space_video/f_video").headers["Content-Type"].startswith("video/mp4")
    partial = client.get(
        "/api/stash/space_video/f_video",
        headers={"Range": "bytes=0-3"},
    )
    assert partial.status_code == 206
    assert partial.headers["Content-Range"] == "bytes 0-3/8"


def test_canvas_client_prefers_matching_stash_video_over_remote_source():
    canvas_js = CANVAS_ROOT / "client" / "static" / "js" / "canvas.js"
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(canvas_js))}, 'utf8');
const start = source.indexOf('function inferVideoMimeType');
const end = source.indexOf('function getFilteredPages', start);
const sandbox = {{
  window: {{ location: {{ origin: 'http://canvas.test' }} }},
  URL,
  console,
  cleanStashFileIdSegment: value => String(value).replace(/(?:%2560|%60|`)+$/gi, ''),
  escapeHtml: value => String(value),
  fetch: async url => ({{
    ok: true,
    json: async () => JSON.parse({json.dumps(json.dumps({
        'name': 'social_clip.mp4',
        'mime_type': 'video/mp4',
        'source_url': 'https://example.test/final.mp4',
    }))})
  }})
}};
vm.createContext(sandbox);
vm.runInContext(source.slice(start, end), sandbox);
(async () => {{
  const content = '[Play](https://example.test/final.mp4)\\n`stash://space_video/f_video`';
  const candidates = sandbox.collectPageVideoCandidates(content);
  if (candidates.directUrls.length !== 1 || candidates.stashRefs.length !== 1) process.exit(2);
  const embeds = await sandbox.collectPageVideoEmbeds(content);
  if (embeds.length !== 1) process.exit(3);
  if (embeds[0].playbackUrl !== '/api/stash/space_video/f_video') process.exit(4);
  if (!embeds[0].stashed || embeds[0].mimeType !== 'video/mp4') process.exit(5);
}})().catch(() => process.exit(6));
"""

    subprocess.run(["node", "-e", script], check=True, cwd=PROJECT_ROOT)


def test_web_chat_exposes_context_aware_send_to_canvas_action():
    chat_js = (PROJECT_ROOT / "jarvis-web" / "client" / "js" / "chat.js").read_text()

    assert "Send to Canvas" in chat_js
    assert "tool_hints: ['canvas']" in chat_js
    assert "Preserve useful source links" in chat_js
    assert "querySelectorAll('.send-to-canvas-actions')" in chat_js
    assert "actions.remove()" in chat_js
