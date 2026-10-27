"""HeyGen's paid boundary submits once and keeps recoverable native handles."""

import json
import wave
from pathlib import Path

import heygen_client as hc
import heygen_media as hm
import pytest
import requests
from config_loader import config_scope
from PIL import Image
from remote_completion import completion_for_error
from stash_helper import safe_resolve_file


class Response:
    def __init__(self, data, status=200):
        self.data = data
        self.status_code = status
        self.closed = False

    def json(self):
        return {"data": self.data}

    def close(self):
        self.closed = True


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setattr(hm, "get_project_root", lambda: tmp_path)
    with config_scope("cloud", {"HEYGEN_API_KEY": "test-heygen-key", "HEYGEN_WAIT_SECONDS": "0",
                                "STASH_DIR": str(tmp_path / "stash")}):
        yield tmp_path


def test_missing_key_refuses_before_http_or_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "http_request", lambda *a, **k: pytest.fail("HTTP before opt-in"))
    monkeypatch.setattr(hc, "open_space", lambda *a, **k: pytest.fail("Storage before opt-in"))
    with config_scope("local", {"HEYGEN_API_KEY": "  "}):
        assert not hc.is_heygen_configured()
        with pytest.raises(ValueError, match="not configured"):
            hc.HeyGenClient()


def test_clip_submits_once_with_idempotency_and_persists_handle(configured, monkeypatch):
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return Response({"video_id": "model-job", "status": "pending"} if method == "POST" else {
            "status": "completed", "video_url": "https://example.com/output.mp4", "duration": 5,
        })

    monkeypatch.setattr(hc, "http_request", request)
    result = hc.HeyGenClient().generate_clip("A useful scene", resolution="720p")
    assert [call[0] for call in calls] == ["POST", "GET"]
    assert calls[0][2]["json"]["resolution"] == "768p"
    assert calls[0][2]["headers"]["Idempotency-Key"] == result["request_id"]
    assert calls[0][2]["proxy_policy"] == "off"
    assert calls[0][2]["allow_redirects"] is False
    assert result["estimated_cost_usd"] == 0.09
    resolved = safe_resolve_file(stash_ref=result["receipt_stash_ref"])
    receipt = json.loads(Path(resolved["path"]).read_text())
    assert receipt["provider_video_id"] == "model-job"
    assert receipt["mode"] == "cloud"
    assert "test-heygen-key" not in Path(resolved["path"]).read_text()


@pytest.mark.parametrize("status,completion", [(401, "rejected"), (429, "rejected"), (503, "unknown")])
def test_submission_http_failure_never_retries(configured, monkeypatch, status, completion):
    calls = []

    def request(*args, **kwargs):
        calls.append(args)
        return Response({}, status)

    monkeypatch.setattr(hc, "http_request", request)
    with pytest.raises(Exception) as failure:
        hc.HeyGenClient().generate_clip("A scene")
    result = hc.heygen_error_result(failure.value)
    assert len(calls) == 1
    assert result["completion"] == completion
    assert result["data"]["request_id"].startswith("jarvis-heygen-")
    assert result["data"]["receipt_stash_ref"].startswith("stash://")


def test_lost_submit_response_keeps_request_receipt_without_replaying(configured, monkeypatch):
    calls = []

    def request(*args, **kwargs):
        calls.append(args)
        raise requests.Timeout("private HTTP request detail test-heygen-key")

    monkeypatch.setattr(hc, "http_request", request)
    with pytest.raises(hc.HeyGenError) as failure:
        hc.HeyGenClient().generate_clip("A scene")
    output = hc.heygen_error_result(failure.value)
    assert output["completion"] == "unknown"
    assert len(calls) == 1
    assert "test-heygen-key" not in json.dumps(output)
    assert output["data"]["receipt_stash_ref"]


@pytest.mark.parametrize("state,completion", [("pending", "unknown"), ("failed", "completed"), ("cancelled", "completed")])
def test_observer_preserves_job_on_timeout_or_terminal_failure(configured, monkeypatch, state, completion):
    calls = []

    def request(method, url, **kwargs):
        calls.append(method)
        return Response({"video_id": "existing-id"} if method == "POST" else {"status": state})

    monkeypatch.setattr(hc, "http_request", request)
    with pytest.raises(Exception) as failure:
        hc.HeyGenClient().generate_clip("A scene")
    output = hc.heygen_error_result(failure.value)
    assert calls == ["POST", "GET"]
    assert output["data"]["provider_video_id"] == "existing-id"
    assert output["data"]["kind"] == "model"
    assert output["completion"] == completion


@pytest.mark.parametrize("kwargs", [{"duration": 16}, {"duration": True}, {"resolution": "4k"}, {"model": "expensive-other"}])
def test_invalid_clip_refused_before_upload_or_submission(configured, monkeypatch, kwargs):
    monkeypatch.setattr(hc, "http_request", lambda *a, **k: pytest.fail("Invalid input reached API"))
    with pytest.raises(ValueError):
        hc.HeyGenClient().generate_clip("A scene", **kwargs)


def test_stash_image_uploads_then_generates_with_asset_id(configured, monkeypatch):
    image = configured / "input.png"
    Image.new("RGB", (32, 18)).save(image)
    space, _ = hc.open_space(labels=["test"])
    ref = hc.StashFile(space).save_binary(image.read_bytes(), "input.png", "image/png")["ref"]
    calls = []

    def request(method, url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/assets"):
            assert kwargs["files"]["file"][1].read() == image.read_bytes()
            return Response({"asset_id": "uploaded-image"})
        if method == "POST":
            assert kwargs["json"]["image"] == {"type": "asset_id", "asset_id": "uploaded-image"}
            assert kwargs["json"]["mode"] == "image_to_video"
            return Response({"video_id": "image-job"})
        return Response({"status": "completed", "video_url": "https://example.com/video.mp4"})

    monkeypatch.setattr(hc, "http_request", request)
    result = hc.HeyGenClient().generate_clip("Animate the image", image_source=ref)
    assert len(calls) == 3
    assert result["from_image"] is True


def test_avatar_preserves_exact_script_and_uses_iv_only(configured, monkeypatch):
    calls = []
    monkeypatch.setattr(hc, "http_request", lambda *a, **k: calls.append(k) or Response({"video_id": "avatar-job"}))
    script = "Jarvis Voice connects your tools. Your assistant, your choice."
    result = hc.HeyGenClient().submit_avatar(script=script, avatar_id="look-id", voice_id="voice-id")
    assert calls[0]["json"]["script"] == script
    assert calls[0]["json"]["engine"] == {"type": "avatar_iv"}
    assert result["kind"] == "avatar"
    assert result["status"] == "pending"


@pytest.mark.parametrize("audio_source", [None, "stash://space_test/f_audio"])
def test_photo_avatar_omits_engine_for_script_and_audio(configured, monkeypatch, audio_source):
    calls = []
    client = hc.HeyGenClient()
    monkeypatch.setattr(client, "_input", lambda source, kind: {
        "type": "asset_id", "asset_id": f"uploaded-{kind}",
    })

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        # CreateVideoFromImage has additionalProperties: false. In particular,
        # engine is valid only for CreateVideoFromAvatar, not for raw photos.
        assert set(kwargs["json"]) <= {
            "type", "image", "script", "voice_id", "audio_asset_id", "title",
            "aspect_ratio", "resolution",
        }
        return Response({"video_id": "photo-avatar-job"})

    monkeypatch.setattr(hc, "http_request", request)
    speech = {"audio_source": audio_source} if audio_source else {
        "script": "Hello from Jarvis.", "voice_id": "discovered-voice-id",
    }
    result = client.submit_avatar(
        image_source="stash://space_test/f_portrait", title="Photo avatar test",
        aspect_ratio="9:16", resolution="1080p", **speech,
    )
    assert len(calls) == 1
    assert calls[0][:2] == ("POST", "https://api.heygen.com/v3/videos")
    payload = calls[0][2]["json"]
    assert payload["type"] == "image"
    assert payload["image"] == {"type": "asset_id", "asset_id": "uploaded-image"}
    assert "engine" not in payload
    if audio_source:
        assert payload["audio_asset_id"] == "uploaded-audio"
        assert "script" not in payload
        assert "voice_id" not in payload
    else:
        assert payload["script"] == speech["script"]
        assert payload["voice_id"] == speech["voice_id"]
    assert result["provider_video_id"] == "photo-avatar-job"
    assert result["kind"] == "avatar"


def test_audio_duration_rejected_before_paid_generation(configured, monkeypatch):
    source = configured / "long.wav"
    with wave.open(str(source), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0\0" * 8000 * 31)
    monkeypatch.setattr(hc, "http_request", lambda *a, **k: pytest.fail("Overlong audio reached API"))
    with pytest.raises(ValueError, match="30 seconds"):
        hc.HeyGenClient().submit_avatar(avatar_id="look-id", audio_source=str(source))


def test_status_and_collect_never_submit_and_collect_is_idempotent(configured, monkeypatch):
    calls = []
    monkeypatch.setattr(hc, "http_request", lambda method, url, **kw: calls.append(method) or Response({
        "status": "completed", "video_url": "https://example.com/video.mp4", "duration": 5,
    }))
    monkeypatch.setattr(hm, "_download_video", lambda *a, **kw: b"\x00\x00\x00\x18ftypmp42" + b"\0" * 32)
    first = hc.HeyGenClient().collect("existing-video")
    second = hc.HeyGenClient().collect("existing-video")
    assert calls == ["GET", "GET"]
    assert first["ok"] and second["ok"]
    assert first["data"]["stash_ref"] == second["data"]["stash_ref"]
    catalog = json.loads((configured / "data/generated_videos/video_catalog.json").read_text())
    entry = next(iter(catalog.values()))
    assert entry["provider"] == "HeyGen"
    assert entry["model"] == "heygen-video-1"
    assert entry["provider_video_id"] == "existing-video"


def test_collect_download_failure_is_completed_remote_work(configured, monkeypatch):
    monkeypatch.setattr(hc, "http_request", lambda *a, **k: Response({
        "status": "completed", "video_url": "https://example.com/video.mp4",
    }))
    monkeypatch.setattr(hm, "_download_video", lambda *a, **k: (_ for _ in ()).throw(requests.Timeout()))
    with pytest.raises(Exception) as failure:
        hc.HeyGenClient().collect("existing-video")
    assert completion_for_error(failure.value) == "completed"
    assert hc.heygen_error_result(failure.value)["data"]["provider_video_id"] == "existing-video"


def test_audio_probe_inherits_no_provider_credentials(configured, monkeypatch):
    monkeypatch.setenv("UNRELATED_PROVIDER_KEY", "do-not-pass")
    monkeypatch.setattr(hm.shutil, "which", lambda command: "/usr/bin/ffprobe")

    def run(*args, **kwargs):
        assert "UNRELATED_PROVIDER_KEY" not in kwargs["env"]
        return type("ProbeResult", (), {"returncode": 0, "stdout": '{"format":{"duration":"3.5"}}'})()

    monkeypatch.setattr(hm.subprocess, "run", run)
    assert hm._audio_duration(configured / "short.mp3") == 3.5


@pytest.mark.parametrize("wait", ["invalid", "nan", "inf"])
def test_invalid_observer_setting_rejected_before_paid_work(configured, monkeypatch, wait):
    monkeypatch.setattr(hc, "http_request", lambda *a, **k: pytest.fail("Invalid wait reached API"))
    with config_scope("cloud", {"HEYGEN_API_KEY": "test-key", "HEYGEN_WAIT_SECONDS": wait}):
        client = hc.HeyGenClient()
        with pytest.raises(ValueError, match="finite number"):
            client.generate_clip("A scene")
        with pytest.raises(ValueError, match="finite number"):
            client.generate_avatar(script="Hello", avatar_id="look", voice_id="voice")
