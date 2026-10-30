"""Offline phone-artifact collection against real disposable Stash storage."""

import io
import json
import socket
import wave
from unittest.mock import Mock

import phone_call_artifacts as artifacts
import pytest
import requests
import stash_helper
from config_loader import config_scope

PRIVATE_KEY = "PRIVATE_API_SENTINEL"
SIGNED_URL = "https://cdn.example.test/recording.wav?signature=SIGNED_URL_SENTINEL"
CALL_ID = "call-A"
RECORDING_ENDPOINT = f"https://api.vapi.ai/call/{CALL_ID}/mono-recording"


def _wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\0\0" * 8)
    return output.getvalue()


WAV = _wav_bytes()


class Response:
    def __init__(self, status=200, headers=None, chunks=None):
        self.status_code = status
        self.headers = requests.structures.CaseInsensitiveDict(headers or {})
        self.chunks = [WAV] if chunks is None else chunks
        self.close = Mock()
        self.iterated = False

    @property
    def is_redirect(self):
        return self.status_code in {301, 302, 303, 307, 308}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        self.iterated = True
        yield from self.chunks


@pytest.fixture(autouse=True)
def offline_transport(monkeypatch):
    def resolve(hostname, *args, **kwargs):
        address = "127.0.0.1" if hostname == "private.example.test" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    guards = []
    for module, attribute in ((artifacts.requests, "get"), (stash_helper, "http_request")):
        guard = Mock(side_effect=AssertionError("Unexpected artifact HTTP request"))
        monkeypatch.setattr(module, attribute, guard)
        guards.append(guard)
    yield
    for guard in guards:
        guard.assert_not_called()


@pytest.fixture
def configured(tmp_path):
    root = tmp_path / "custom-stash"
    with config_scope("cloud", {"STASH_DIR": str(root), "VAPI_API_KEY": PRIVATE_KEY}):
        yield root


def _result(**overrides):
    return {
        "status": "ended",
        "transcript": "AI: Hello\nUser: Dinner tomorrow works.",
        "summary": "Dinner confirmed",
        "recording_url": RECORDING_ENDPOINT,
        **overrides,
    }


def _stored_file(root, reference):
    space_id, file_id = stash_helper.parse_stash_ref(reference)
    stored = stash_helper.StashFile(stash_helper.StashSpace(space_id, root), file_id=file_id)
    assert stored.path is not None
    assert stored.path.resolve().is_relative_to(root.resolve())
    return stored.path


def _assert_no_download_secrets(root, result):
    persisted = b"\n".join(path.read_bytes() for path in root.rglob("*") if path.is_file())
    for sensitive in (PRIVATE_KEY, "SIGNED_URL_SENTINEL"):
        assert sensitive not in json.dumps(result)
        assert sensitive.encode() not in persisted


def test_transcript_and_recording_are_saved_without_signed_url_provenance(configured, monkeypatch):
    response = Response(302, {"Location": SIGNED_URL})
    request = Mock(return_value=response)
    download = Mock(return_value=(WAV, "audio/wav", SIGNED_URL))
    monkeypatch.setattr(artifacts.requests, "get", request)
    monkeypatch.setattr(artifacts, "safe_download", download)

    result = artifacts.save_call_artifacts(CALL_ID, _result())

    assert result["transcript_saved"] is True
    assert result["audio_saved"] is True
    assert result["transcript_status"] == "saved"
    assert result["audio_status"] == "saved"
    transcript = _stored_file(configured, result["transcript_stash_ref"]).read_text()
    assert "Dinner tomorrow works." in transcript
    assert _stored_file(configured, result["audio_stash_ref"]).read_bytes() == WAV
    assert result["stash_ref"] == result["audio_stash_ref"]
    assert result["mime_type"] == "audio/wav"
    request.assert_called_once()
    assert request.call_args.args == (RECORDING_ENDPOINT,)
    assert request.call_args.kwargs["headers"]["Authorization"] == f"Bearer {PRIVATE_KEY}"
    assert request.call_args.kwargs["allow_redirects"] is False
    assert request.call_args.kwargs["stream"] is True
    assert download.call_args.args == (SIGNED_URL,)
    assert PRIVATE_KEY not in repr(download.call_args)
    assert "Authorization" not in repr(download.call_args)
    response.close.assert_called_once()
    _assert_no_download_secrets(configured, result)


def test_recording_request_always_uses_fixed_vapi_endpoint(configured, monkeypatch):
    request = Mock(return_value=Response(404))
    monkeypatch.setattr(artifacts.requests, "get", request)

    artifacts.save_call_artifacts(
        CALL_ID, _result(recording_url="https://untrusted.example.test/steal-api-key")
    )

    assert request.call_args.args == (RECORDING_ENDPOINT,)


def test_later_status_preserves_original_name_and_task_while_refreshing_summary(configured):
    first = artifacts.save_call_artifacts(
        CALL_ID, _result(recording_url="", recipient="Alice", task="Ask about dinner")
    )
    later = artifacts.save_call_artifacts(
        CALL_ID,
        _result(recording_url="", recipient="+12125550199", task="Phone call", summary="Dinner at six"),
    )

    assert later["transcript_stash_ref"] == first["transcript_stash_ref"]
    content = _stored_file(configured, later["transcript_stash_ref"]).read_text()
    assert "Recipient: Alice" in content
    assert "Task: Ask about dinner" in content
    assert "Dinner at six" in content
    assert "+12125550199" not in content


def test_repeated_status_reuses_saved_audio_in_the_same_space(configured, monkeypatch):
    request = Mock(return_value=Response(302, {"Location": SIGNED_URL}))
    download = Mock(return_value=(WAV, "audio/wav", SIGNED_URL))
    monkeypatch.setattr(artifacts.requests, "get", request)
    monkeypatch.setattr(artifacts, "safe_download", download)

    first = artifacts.save_call_artifacts(CALL_ID, _result())
    later = artifacts.save_call_artifacts(
        CALL_ID, _result(transcript="AI: Hello\nUser: Dinner tomorrow works.\nAI: See you there.")
    )

    assert first["stash_space_id"] == later["stash_space_id"]
    assert first["transcript_stash_ref"] == later["transcript_stash_ref"]
    assert first["audio_stash_ref"] == later["audio_stash_ref"]
    request.assert_called_once()
    download.assert_called_once()
    assert "See you there." in _stored_file(configured, later["transcript_stash_ref"]).read_text()
    metadata = json.loads(next(configured.glob("*/meta.json")).read_text())
    assert len(metadata["files"]) == 2
    _assert_no_download_secrets(configured, later)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "failed"),
        (403, "failed"),
        (404, "pending"),
        (409, "pending"),
        (429, "pending"),
        (503, "pending"),
    ],
)
def test_recording_http_failure_preserves_written_transcript(
    configured, monkeypatch, status, expected
):
    response = Response(status)
    monkeypatch.setattr(artifacts.requests, "get", Mock(return_value=response))

    result = artifacts.save_call_artifacts(CALL_ID, _result())

    assert result["audio_saved"] is False
    assert result["audio_status"] == expected
    assert result["transcript_saved"] is True
    assert _stored_file(configured, result["transcript_stash_ref"]).is_file()
    response.close.assert_called_once()
    _assert_no_download_secrets(configured, result)


def test_missing_recording_evidence_skips_audio_http(configured):
    result = artifacts.save_call_artifacts(CALL_ID, _result(recording_url=""))

    assert result["transcript_saved"] is True
    assert result["audio_saved"] is False
    assert result["audio_status"] == "unavailable"


def test_signed_download_failure_does_not_leak_url_or_credentials(configured, monkeypatch):
    monkeypatch.setattr(
        artifacts.requests, "get", Mock(return_value=Response(302, {"Location": SIGNED_URL}))
    )
    monkeypatch.setattr(
        artifacts,
        "safe_download",
        Mock(side_effect=requests.RequestException(f"Failed {SIGNED_URL} with {PRIVATE_KEY}")),
    )

    result = artifacts.save_call_artifacts(CALL_ID, _result())

    assert result["audio_saved"] is False
    assert result["audio_status"] == "failed"
    assert result["transcript_saved"] is True
    _assert_no_download_secrets(configured, result)


@pytest.mark.parametrize(
    "destination",
    [
        "https://private.example.test/internal-recording",
        "http://cdn.example.test/insecure-recording",
        "https://user:PRIVATE_API_SENTINEL@cdn.example.test/recording",
    ],
)
def test_invalid_redirect_is_rejected_before_storage_http(configured, monkeypatch, destination):
    response = Response(302, {"Location": destination})
    monkeypatch.setattr(artifacts.requests, "get", Mock(return_value=response))

    result = artifacts.save_call_artifacts(CALL_ID, _result())

    assert result["audio_saved"] is False
    assert result["audio_status"] == "failed"
    assert result["transcript_saved"] is True
    assert len(list(configured.glob("*/*.md"))) == 1
    _assert_no_download_secrets(configured, result)


@pytest.mark.parametrize(
    ("headers", "chunks"),
    [
        ({"Content-Type": "text/html"}, [b"<html>not a recording</html>"]),
        ({"Content-Type": "audio/wav"}, [b"not an audio file"]),
        ({"Content-Type": "audio/wav", "Content-Length": str(2**60)}, [WAV]),
    ],
)
def test_invalid_audio_is_not_saved_as_a_recording(configured, monkeypatch, headers, chunks):
    response = Response(headers=headers, chunks=chunks)
    monkeypatch.setattr(artifacts.requests, "get", Mock(return_value=response))

    result = artifacts.save_call_artifacts(CALL_ID, _result())

    assert result["audio_saved"] is False
    assert result["audio_status"] == "failed"
    assert result["transcript_saved"] is True
    metadata = json.loads(next(configured.glob("*/meta.json")).read_text())
    assert [entry["name"] for entry in metadata["files"]] == ["transcript.md"]
    response.close.assert_called_once()


def test_streamed_recording_without_length_is_still_bounded(configured, monkeypatch):
    monkeypatch.setattr(artifacts, "MAX_RECORDING_BYTES", 16)
    response = Response(headers={"Content-Type": "audio/wav"}, chunks=[WAV])
    monkeypatch.setattr(artifacts.requests, "get", Mock(return_value=response))

    result = artifacts.save_call_artifacts(CALL_ID, _result())

    assert result["audio_saved"] is False
    assert result["audio_status"] == "failed"
    assert result["transcript_saved"] is True
    response.close.assert_called_once()


def test_direct_authenticated_audio_response_can_be_saved(configured, monkeypatch):
    response = Response(headers={"Content-Type": "audio/wav", "Content-Length": str(len(WAV))})
    monkeypatch.setattr(artifacts.requests, "get", Mock(return_value=response))

    result = artifacts.save_call_artifacts(CALL_ID, _result())

    assert result["audio_saved"] is True
    assert _stored_file(configured, result["audio_stash_ref"]).read_bytes() == WAV
    response.close.assert_called_once()


def test_call_artifact_spaces_are_scoped_by_mode(configured):
    cloud = artifacts.save_call_artifacts(CALL_ID, _result(recording_url=""))
    with config_scope("local", {"STASH_DIR": str(configured), "VAPI_API_KEY": PRIVATE_KEY}):
        local = artifacts.save_call_artifacts(CALL_ID, _result(recording_url=""))

    assert cloud["stash_space_id"] != local["stash_space_id"]
    assert _stored_file(configured, cloud["transcript_stash_ref"]).is_file()
    assert _stored_file(configured, local["transcript_stash_ref"]).is_file()


def test_canvas_identity_persists_without_replacing_other_artifact_metadata(configured):
    result = artifacts.save_call_artifacts(CALL_ID, _result(recording_url=""))
    space_id = result["stash_space_id"]
    space = stash_helper.StashSpace(space_id, configured)
    with space.transaction():
        space.meta["owner_note"] = "Keep my annotation"
        space._save_meta()
    audio_ref = f"stash://{space_id}/recording-file"

    artifacts.remember_call_canvas(
        space_id, "page-call", "Phone Calls/Original", audio_ref, result_sha256="a" * 64
    )
    artifacts.remember_call_canvas(space_id, "page-call", "Phone Calls/Renamed")

    assert artifacts.get_call_canvas(space_id) == {
        "page_id": "page-call",
        "title": "Phone Calls/Renamed",
        "audio_stash_ref": audio_ref,
        "result_sha256": "a" * 64,
    }
    metadata = json.loads((configured / space_id / "meta.json").read_text())
    assert metadata["owner_note"] == "Keep my annotation"
    assert len(metadata["files"]) == 1
    assert _stored_file(configured, result["transcript_stash_ref"]).is_file()
