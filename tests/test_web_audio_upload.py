"""Regression coverage for Web audio upload and attachment context."""

from __future__ import annotations

import hashlib
import io
import json
import struct
import subprocess
import sys
import uuid
import wave
from pathlib import Path

import pytest
from flask import Flask
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jarvis-web"))
load_server_package("jarvis_web_audio_test", ROOT / "jarvis-web" / "server")

from jarvis_web_audio_test import config as web_config  # noqa: E402
from jarvis_web_audio_test.routes import api  # noqa: E402
from jarvis_web_audio_test.services import audio_upload, conversation_store  # noqa: E402
from jarvis_web_audio_test.sockets.chat import ChatHandler  # noqa: E402


def _wav_bytes(seconds: float = 0.25) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        frames = int(16_000 * seconds)
        wav.writeframes(b"".join(struct.pack("<h", 0) for _ in range(frames)))
    return output.getvalue()


def _client():
    app = Flask(__name__)
    app.register_blueprint(api.api_bp)
    return app.test_client()


@pytest.fixture(autouse=True)
def _isolated_stash(tmp_path, monkeypatch):
    stash_dir = tmp_path / "stash"
    monkeypatch.delenv("JARVIS_OVERRIDE_STASH_DIR", raising=False)
    monkeypatch.setenv("STASH_DIR", str(stash_dir))
    monkeypatch.setenv("WEB_AUDIO_UPLOAD_RATE_LIMIT_PER_MINUTE", "0")
    audio_upload.reset_audio_upload_rate_limit_for_tests()
    yield stash_dir
    audio_upload.reset_audio_upload_rate_limit_for_tests()


def _post_audio(
    client,
    payload: bytes,
    upload_id: str,
    filename="recording.wav",
    mode="cloud",
):
    return client.post(
        "/api/upload-audio",
        data={
            "file": (io.BytesIO(payload), filename, "audio/wav"),
            "upload_id": upload_id,
            "mode": mode,
        },
        content_type="multipart/form-data",
    )


def test_upload_audio_commits_inspected_stash_artifact(_isolated_stash):
    payload = _wav_bytes()
    upload_id = str(uuid.uuid4())

    response = _post_audio(
        _client(), payload, upload_id, filename="AI is out of control.wav"
    )
    body = response.get_json()

    assert response.status_code == 200
    assert body["ok"] is True
    attachment = body["attachment"]
    digest = hashlib.sha256(payload).hexdigest()
    assert attachment["kind"] == "audio"
    assert attachment["space_id"] == f"space_web_audio_{uuid.UUID(upload_id).hex}"
    assert attachment["file_id"] == f"f_{digest[:12]}"
    assert attachment["stash_ref"].endswith(f"/f_{digest[:12]}")
    assert attachment["duration_seconds"] > 0
    assert attachment["size_bytes"] == len(payload)

    space_path = _isolated_stash / attachment["space_id"]
    meta = json.loads((space_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["source"] == "web_audio_upload"
    assert meta["labels"] == ["web_upload", "audio"]
    assert meta["files"][0]["tool_origin"] == "web_audio_upload"
    assert attachment["filename"] == "AI is out of control.wav"
    assert (space_path / "AI is out of control.wav").read_bytes() == payload


def test_stash_audio_route_supports_browser_range_playback():
    client = _client()
    payload = _wav_bytes()
    response = _post_audio(client, payload, str(uuid.uuid4()))
    attachment = response.get_json()["attachment"]
    raw_path = attachment["stash_ref"].replace("stash://", "/api/stash/", 1)

    playback = client.get(raw_path, headers={"Range": "bytes=0-31"})

    assert playback.status_code == 206
    assert playback.data == payload[:32]
    assert playback.headers["Content-Type"].startswith("audio/wav")
    assert playback.headers["Content-Range"].startswith("bytes 0-31/")


def test_audio_upload_uses_requested_mode_scope(monkeypatch):
    from config_loader import get_active_config_mode

    observed_modes = []
    real_loader = audio_upload.load_audio_transcription_limits

    def observed_limits():
        observed_modes.append(get_active_config_mode())
        return real_loader()

    monkeypatch.setattr(audio_upload, "load_audio_transcription_limits", observed_limits)

    response = _post_audio(
        _client(), _wav_bytes(), str(uuid.uuid4()), mode="local"
    )

    assert response.status_code == 200
    assert observed_modes and set(observed_modes) == {"local"}


def test_audio_upload_reports_invalid_shared_limit_configuration(monkeypatch):
    monkeypatch.setattr(
        audio_upload,
        "load_audio_transcription_limits",
        lambda: (_ for _ in ()).throw(ValueError("invalid limit")),
    )

    response = _post_audio(_client(), _wav_bytes(), str(uuid.uuid4()))

    assert response.status_code == 500
    assert response.get_json()["error_code"] == "audio_upload_configuration_invalid"


def test_audio_upload_idempotency_and_server_owned_validation():
    payload = _wav_bytes()
    upload_id = str(uuid.uuid4())
    client = _client()

    first = _post_audio(client, payload, upload_id).get_json()
    second = _post_audio(client, payload, upload_id).get_json()

    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    assert second["attachment"] == first["attachment"]
    tampered = {**first["attachment"], "filename": "pretend.mp3", "size_bytes": 1}
    assert audio_upload.validate_audio_attachment(tampered) == first["attachment"]


@pytest.mark.parametrize(
    ("filename", "mime_type", "payload", "error_code"),
    [
        ("recording.txt", "audio/wav", _wav_bytes(), "audio_upload_extension_invalid"),
        ("recording.wav", "text/plain", _wav_bytes(), "audio_upload_mime_invalid"),
        ("recording.wav", "audio/wav", b"not audio", "audio_upload_invalid"),
    ],
)
def test_audio_upload_rejects_untrusted_type_or_invalid_media(
    filename, mime_type, payload, error_code
):
    response = _client().post(
        "/api/upload-audio",
        data={
            "file": (io.BytesIO(payload), filename, mime_type),
            "upload_id": str(uuid.uuid4()),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code in {400, 422}
    assert response.get_json()["error_code"] == error_code


def test_audio_context_requires_transcription_before_content_claims():
    attachment = {
        "kind": "audio",
        "stash_ref": "stash://space_web_audio_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/f_bbbbbbbbbbbb",
        "space_id": "space_web_audio_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "file_id": "f_bbbbbbbbbbbb",
        "filename": "meeting.m4a",
        "size_bytes": 1234,
        "mime_type": "audio/mp4",
        "duration_seconds": 180.5,
    }
    context = ChatHandler._format_audio_attachment_context(attachment)
    assert attachment["stash_ref"] in context
    assert "metadata does not reveal the spoken content" in context
    assert "Use transcribe_audio" in context
    assert "exact Stash reference as source" in context


def test_prior_audio_reference_survives_conversation_history(monkeypatch):
    attachment = {
        "kind": "audio",
        "stash_ref": "stash://space_web_audio_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/f_bbbbbbbbbbbb",
        "filename": "meeting.m4a",
        "size_bytes": 1234,
        "mime_type": "audio/mp4",
        "duration_seconds": 180.5,
    }
    conversation = {"messages": [
        {"role": "user", "content": "Keep this.", "data": {"attachments": [attachment]}},
        {"role": "assistant", "content": "Attached.", "data": {}},
        {"role": "user", "content": "Now transcribe it.", "data": None},
    ]}

    class Store:
        def get_conversation(self, _conversation_id):
            return conversation

    monkeypatch.setattr(conversation_store, "get_conversation_store", lambda: Store())
    monkeypatch.setattr(web_config, "get_web_setting", lambda _key, default: default)

    history = ChatHandler.__new__(ChatHandler)._get_conversation_context("conversation")
    assert history[0]["content"].startswith("[ATTACHED AUDIO ARTIFACT]")
    assert attachment["stash_ref"] in history[0]["content"]
    assert "User's request: Keep this." in history[0]["content"]


def test_browser_audio_contract_uploads_on_send_and_restores_history_badge():
    index_html = (ROOT / "jarvis-web/client/index.html").read_text(encoding="utf-8")
    chat_js = (ROOT / "jarvis-web/client/js/chat.js").read_text(encoding="utf-8")
    app_js = (ROOT / "jarvis-web/client/js/app.js").read_text(encoding="utf-8")

    assert "audio/*" in index_html and ".m4a" in index_html and ".mp3" in index_html
    assert "fetch('/api/upload-audio'" in chat_js
    assert "formData.append('mode', this.socket?.mode" in chat_js
    audio_file_matcher = chat_js[
        chat_js.index("  _isAudioFile(") : chat_js.index("  _createArtifactUploadId(")
    ]
    assert "mime.startsWith('audio/')" not in audio_file_matcher
    assert "this.attachedAudio !== audioState" in chat_js
    assert "audioAttachment ? [audioAttachment]" in chat_js
    assert "item?.kind === 'audio'" in app_js
    assert "audioAttachment ? [audioAttachment] : null" in app_js
    assert "`🎵 ${audioAttachment.filename}" not in app_js
    assert "item?.kind === 'audio' && item?.filename" not in app_js


def test_browser_audio_contract_renders_pending_and_persisted_players():
    index_html = (ROOT / "jarvis-web/client/index.html").read_text(encoding="utf-8")
    chat_js = (ROOT / "jarvis-web/client/js/chat.js").read_text(encoding="utf-8")

    assert 'id="fileAudioPreview"' in index_html
    assert "window.URL.createObjectURL(file)" in chat_js
    assert "window.URL.revokeObjectURL(this.fileAudioPreviewUrl)" in chat_js
    assert "this._normalizeAudioAttachment(audioAttachment)" in chat_js
    assert "user-audio-attachment" in chat_js
    assert "controls preload=\"metadata\"" in chat_js
    assert ">Open</a>" in chat_js
    assert ">Download</a>" in chat_js
    assert "</div>\n      ${audioHtml}" in chat_js
    assert "this._findAudioFromToolResults(" in chat_js
    assert chat_js.index("${messageBubbleHtml}") < chat_js.index(
        "${genericStashAudio ? audioHtml : ''}"
    )


def test_audio_player_helpers_are_stash_safe_and_format_aware():
    chat_js = ROOT / "jarvis-web/client/js/chat.js"
    script = rf"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(chat_js))}, 'utf8');
const start = source.indexOf('  _safeMediaUrlForAttr(');
const end = source.indexOf('  _extractYouTubeVideoId(', start);
if (start < 0 || end < 0) process.exit(2);
const classSource = `class AudioHarness {{
${{source.slice(start, end)}}
}}; AudioHarness;`;
const escapeHtml = (value) => String(value)
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;');
const Utils = {{
  escapeHtml,
  safeHttpUrlForAttr(value) {{
    try {{
      const parsed = new URL(String(value));
      return ['http:', 'https:'].includes(parsed.protocol) ? escapeHtml(parsed.href) : '';
    }} catch {{
      return '';
    }}
  }},
  stashRefToApiUrl(ref) {{
    const match = String(ref || '').match(/^stash:\/\/([^/\s?#]+)\/([^/\s?#]+)/);
    return match
      ? `/api/stash/${{encodeURIComponent(match[1])}}/${{encodeURIComponent(match[2])}}`
      : null;
  }}
}};
const sandbox = {{ Utils, URL, encodeURIComponent }};
vm.createContext(sandbox);
const AudioHarness = vm.runInContext(classSource, sandbox);
const harness = new AudioHarness();

const generic = harness._findAudioFromToolResults({{
  stash: {{
    data: {{
      ref: 'stash://space_one/f_file_two',
      name: 'meeting notes.m4a',
      mime_type: 'audio/mp4',
      duration_seconds: 125
    }}
  }}
}}, ['convert_file']);
if (!generic) process.exit(3);
if (generic.audioUrl !== '/api/stash/space_one/f_file_two') process.exit(4);
if (generic.audioMimeType !== 'audio/mp4') process.exit(5);
if (harness._formatAudioDuration(125) !== '2:05') process.exit(6);

const html = harness._renderAudioPlayerHtml({{
  ...generic,
  audioTitle: '<meeting>',
  audioFilename: 'meeting\".m4a'
}});
if (!html.includes('&lt;meeting&gt;')) process.exit(7);
if (html.includes('<meeting>')) process.exit(8);
if (!html.includes('controls preload="metadata"')) process.exit(9);
if (!html.includes('>Open</a>')) process.exit(10);
if (!html.includes('>Download</a>')) process.exit(11);
const openText = html.indexOf('>Open</a>');
const openAnchor = html.slice(html.lastIndexOf('<a', openText), openText);
if (openAnchor.includes('download=')) process.exit(12);
if (!openAnchor.includes('target="_blank"')) process.exit(13);
const downloadText = html.indexOf('>Download</a>');
const downloadAnchor = html.slice(html.lastIndexOf('<a', downloadText), downloadText);
if (!downloadAnchor.includes('download="meeting&quot;.m4a"')) process.exit(14);
if (!openAnchor.includes('href="/api/stash/space_one/f_file_two"')) process.exit(15);

const remoteOnly = harness._findAudioFromToolResults({{
  fetch: {{ audio_url: 'https://example.com/audio.mp3', name: 'audio.mp3' }}
}});
if (remoteOnly !== null) process.exit(16);
if (harness._safeMediaUrlForAttr('javascript:alert(1)') !== '') process.exit(17);

const converted = harness._findAudioFromToolResults({{
  convert_file: {{
    stash_ref: 'stash://space_convert/f_audio',
    filename: 'converted.mp3',
    mime_type: 'audio/mpeg'
  }}
}}, ['convert_file']);
if (converted !== null) process.exit(18);

if (harness._normalizeAudioAttachment({{
  kind: 'pdf',
  stash_ref: 'stash://space_one/f_file_two',
  filename: 'not-audio.mp3'
}}) !== null) process.exit(19);
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)
