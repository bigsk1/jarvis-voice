"""Video understanding: real bounded FFmpeg media, provider requests intercepted."""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import video_analysis as video  # noqa: E402

TOOL_SPEC = importlib.util.spec_from_file_location("jarvis_analyze_video_tool", ROOT / "skills/analyze_video.py")
assert TOOL_SPEC and TOOL_SPEC.loader
tool = importlib.util.module_from_spec(TOOL_SPEC)
TOOL_SPEC.loader.exec_module(tool)


@pytest.fixture(autouse=True)
def no_provider_side_effects(monkeypatch):
    monkeypatch.setattr(video, "get_config_value", lambda key, default=None: default)
    monkeypatch.setattr(video, "get_active_config_mode", lambda: "cloud")
    monkeypatch.setattr(video, "analyze_images", lambda *args, **kwargs: pytest.fail("Unintercepted vision request"))
    monkeypatch.setattr(video, "transcribe_audio_file", lambda *args, **kwargs: pytest.fail("Unintercepted STT request"))
    # Only settings are synthetic; actual interval extraction and audio validation run.
    from audio_transcription import AudioTranscriptionSettings
    settings = AudioTranscriptionSettings(
        provider="openai-compatible", model="test", fallback_provider="", fallback_model="",
        max_file_bytes=250 * 1024 * 1024, max_duration_seconds=7200, provider_max_bytes=25 * 1024 * 1024,
        chunk_seconds=300, timeout_seconds=900, request_timeout_seconds=300)
    monkeypatch.setattr(video, "load_audio_transcription_settings", lambda: settings)


@pytest.fixture
def media(tmp_path):
    assert shutil.which("ffmpeg") and shutil.which("ffprobe"), "Video analysis requires FFmpeg/ffprobe"

    def make(name="clip.mp4", *, video_stream=True, audio_stream=False, offset=0):
        path = tmp_path / name
        command = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error"]
        if video_stream:
            command += ["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=4:duration=3"]
        if audio_stream:
            command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=3"]
        if video_stream:
            command += ["-c:v", "mpeg4", "-threads", "1"]
        if audio_stream:
            command += ["-c:a", "aac"]
        if offset:
            command += ["-output_ts_offset", str(offset)]
        command += [str(path)]
        subprocess.run(command, check=True, capture_output=True, timeout=30)
        return path

    return make


def test_real_silent_clip_frames_and_timestamps_reach_vision_in_order(media, monkeypatch):
    path = media()
    calls = []

    def vision(images, prompt, **kwargs):
        calls.append((images, prompt, kwargs))
        for payload in images:
            with Image.open(io.BytesIO(base64.b64decode(payload))) as image:
                assert image.format == "JPEG"
                assert max(image.size) <= 1568
        return "The test pattern is visible across the sampled frames."

    monkeypatch.setattr(video, "analyze_images", vision)
    result = tool.execute({"source": str(path)})
    data = result["data"]
    assert result["ok"] is True
    assert data["audio_status"] == "no_audio"
    assert data["visual_status"] == "complete"
    assert data["frame_count"] == 6
    assert data["frame_timestamps"] == sorted(set(data["frame_timestamps"]))
    assert all(0 <= timestamp < 3 for timestamp in data["frame_timestamps"])
    assert data["analyzed_frame_timestamps"] == data["frame_timestamps"]
    assert "Image 1: video time" in calls[0][1]
    assert "events between frames" in calls[0][1]
    assert data["source_ref"] == str(path)
    assert data["partial"] is False
    assert "between frames may be missed" in data["warnings"][0]


def test_audio_only_container_is_typed_for_upload_fallback(media):
    with pytest.raises(video.NoVideoStreamError):
        video.inspect_video_file(media(video_stream=False, audio_stream=True))


def test_real_interval_audio_is_transcribed_and_temp_file_removed(media, monkeypatch):
    path = media(audio_stream=True)
    monkeypatch.setattr(video, "analyze_images", lambda *args, **kwargs: "At 1s a test pattern is visible.")
    audio_paths = []

    def transcribe(audio_path, *, settings):
        audio_paths.append(audio_path)
        from audio_transcription import inspect_audio_file
        info = inspect_audio_file(audio_path, max_file_bytes=10 * 1024 * 1024, max_duration_seconds=5)
        assert info.duration_seconds == pytest.approx(1.0, abs=0.03)
        assert settings.timeout_seconds <= 300
        return SimpleNamespace(transcript="A recorded test tone.", provider="test", model="test")

    monkeypatch.setattr(video, "transcribe_audio_file", transcribe)
    data = video.analyze_video_file(path, start_seconds=1, end_seconds=2)
    assert data["transcript"] == "A recorded test tone."
    assert data["audio_status"] == "transcribed"
    assert data["transcript_time_origin_seconds"] == 1
    assert data["partial"] is True
    assert audio_paths and not audio_paths[0].parent.exists()
    assert all(1 <= timestamp < 2 for timestamp in data["frame_timestamps"])


def test_local_vision_batches_respect_two_image_limit_and_pinned_model(media, monkeypatch):
    calls = []
    monkeypatch.setattr(video, "analyze_images", lambda images, prompt, **kwargs: calls.append((images, kwargs)) or "Visible evidence.")
    data = video.analyze_video_file(media(), mode="local", provider="openai", model="wrong-web-chat-model")
    assert len(calls) == 3
    assert all(len(images) == 2 and params == {"mode": "local", "provider": "ollama", "model": None}
               for images, params in calls)
    assert data["mode"] == "local"


def test_cloud_vision_uses_same_request_overrides_as_analyze_image(media, monkeypatch):
    values = {"ANALYZE_IMAGE_LLM_PROVIDER": "ollama", "ANALYZE_IMAGE_LLM_MODEL": "selected-cloud-vision"}
    monkeypatch.setattr(video, "get_config_value", lambda key, default=None: values.get(key, default))
    calls = []
    monkeypatch.setattr(video, "analyze_images", lambda images, prompt, **kwargs: calls.append(kwargs) or "Visible evidence.")
    video.analyze_video_file(media())
    assert calls == [{"mode": "cloud", "provider": "ollama", "model": "selected-cloud-vision"}]


@pytest.mark.parametrize("args", [
    {"start_seconds": -1}, {"start_seconds": float("nan")}, {"start_seconds": True},
    {"end_seconds": float("inf")}, {"end_seconds": 4}, {"start_seconds": 2, "end_seconds": 1},
    {"start_seconds": 3}, {"include_audio": "false"}, {"question": ""},
])
def test_invalid_input_never_calls_provider(media, args):
    with pytest.raises(video.VideoAnalysisError):
        video.analyze_video_file(media(), **args)


def test_default_window_is_explicit_and_oversized_interval_is_rejected():
    info = video.VideoInfo(Path("video.mp4"), "video.mp4", 20, 700, 320, 180, False, "video/mp4", "mov", 0, 4)
    limits = video.VideoAnalysisLimits()
    assert video._window(info, 0, None, limits) == (0, 300)
    assert video._window(info, 650, None, limits) == (650, 700)
    with pytest.raises(video.VideoAnalysisError, match="at most 300"):
        video._window(info, 0, 301, limits)


def test_audio_failure_preserves_visual_evidence_and_cleans_temporary_file(media, monkeypatch):
    path = media(audio_stream=True)
    monkeypatch.setattr(video, "analyze_images", lambda *args, **kwargs: "The screen shows a test pattern.")
    seen = []

    def unavailable(path, **kwargs):
        seen.append(path)
        raise video.STTProviderError("Test transcription outage", retryable=True)

    monkeypatch.setattr(video, "transcribe_audio_file", unavailable)
    result = tool.execute({"source": str(path)})
    assert result["ok"] is True  # Usable visual evidence remains in conversation context.
    assert result["data"]["analysis"]
    assert result["data"]["audio_status"] == "unavailable"
    assert result["data"]["error_code"] == "video_analysis_partial"
    assert result["data"]["partial"] is True
    assert seen and not seen[0].parent.exists()


@pytest.mark.parametrize("transcript", ["A spoken test phrase.", ""])
def test_failed_vision_is_partial_success_only_when_audio_is_usable(media, monkeypatch, transcript):
    def vision(*args, **kwargs):
        raise video.VisionProviderError("Test vision outage")
    monkeypatch.setattr(video, "analyze_images", vision)
    monkeypatch.setattr(video, "transcribe_audio_file", lambda *args, **kwargs: SimpleNamespace(
        transcript=transcript, provider="test", model="test"))
    result = tool.execute({"source": str(media(audio_stream=True))})
    assert result["ok"] is bool(transcript)
    assert result["data"]["visual_status"] == "unavailable"
    assert result["data"]["analyzed_frame_timestamps"] == []
    assert result["data"]["partial"] is True


def test_later_visual_failure_preserves_earlier_timestamps(media, monkeypatch):
    calls = []
    def vision(*args, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            raise video.VisionProviderError("Test vision outage")
        return "Two sampled frames show a test pattern."
    monkeypatch.setattr(video, "get_active_config_mode", lambda: "local")
    monkeypatch.setattr(video, "analyze_images", vision)
    result = tool.execute({"source": str(media())})
    assert result["ok"] is True
    assert result["data"]["visual_status"] == "partial"
    assert len(result["data"]["analyzed_frame_timestamps"]) == 2
    assert len(result["data"]["frame_timestamps"]) == 6
    assert result["data"]["partial"] is True


def test_visual_only_request_does_not_transcribe_existing_audio(media, monkeypatch):
    monkeypatch.setattr(video, "analyze_images", lambda *args, **kwargs: "Visible test pattern.")
    data = video.analyze_video_file(media(audio_stream=True), include_audio=False)
    assert data["has_audio"] is True
    assert data["audio_status"] == "skipped"


def test_playlist_disguised_as_video_is_rejected_without_opening_media(tmp_path):
    path = tmp_path / "untrusted.mp4"
    path.write_text("#EXTM3U\n#EXTINF:1,\nhttp://127.0.0.1:1/private\n")
    with pytest.raises(video.VideoAnalysisError, match="inspection failed"):
        video.inspect_video_file(path)


def test_remote_and_restricted_sources_rejected_before_inspection():
    for source in ("https://example.com/clip.mp4", "file:///etc/passwd", "/etc/passwd"):
        with pytest.raises(ValueError):
            tool.execute({"source": source})


def test_decode_dimensions_and_cover_art_are_validated_before_frames(tmp_path, monkeypatch):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"metadata fixture")
    def probe(streams):
        return SimpleNamespace(stdout=json.dumps({"format": {"duration": "3", "format_name": "mov"}, "streams": streams}).encode())
    monkeypatch.setattr(video, "_run", lambda *args, **kwargs: probe([
        {"index": 0, "codec_type": "video", "width": 9000, "height": 10}]))
    with pytest.raises(video.VideoAnalysisError, match="dimensions exceed"):
        video.inspect_video_file(path)
    monkeypatch.setattr(video, "_run", lambda *args, **kwargs: probe([
        {"index": 0, "codec_type": "video", "disposition": {"attached_pic": 1}}, {"index": 1, "codec_type": "audio"}]))
    with pytest.raises(video.NoVideoStreamError):
        video.inspect_video_file(path)


def test_subprocess_timeout_is_typed_and_does_not_expose_command(monkeypatch):
    monkeypatch.setattr(video.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(
        subprocess.TimeoutExpired(["ffmpeg", "private-path"], 1)))
    with pytest.raises(video.VideoAnalysisError, match="frame extraction timed out") as error:
        video._run(["ffmpeg", "private-path"], timeout=1, operation="frame extraction")
    assert "private-path" not in str(error.value)

def test_nonzero_container_start_still_uses_relative_video_timestamps(media, monkeypatch):
    monkeypatch.setattr(video, "analyze_images", lambda *args, **kwargs: "Visible test pattern.")
    data = video.analyze_video_file(media(offset=5))
    assert data["duration_seconds"] == pytest.approx(3)
    assert data["frame_timestamps"][0] == 0
    assert all(0 <= timestamp < 3 for timestamp in data["frame_timestamps"])


def test_transport_failure_can_preserve_spoken_evidence(media, monkeypatch):
    def vision(*args, **kwargs):
        raise video.requests.ConnectionError("Test connection failure")
    monkeypatch.setattr(video, "analyze_images", vision)
    monkeypatch.setattr(video, "transcribe_audio_file", lambda *args, **kwargs: SimpleNamespace(
        transcript="A spoken test phrase.", provider="test", model="test"))
    result = tool.execute({"source": str(media(audio_stream=True))})
    assert result["ok"] is True
    assert result["data"]["visual_status"] == "unavailable"


def test_unavailable_frame_preserves_other_visual_samples(media, monkeypatch):
    actual = video._extract_frame
    def extract(info, target, deadline):
        if target > 2:
            raise video.VideoAnalysisError("Test damaged frame")
        return actual(info, target, deadline)
    monkeypatch.setattr(video, "_extract_frame", extract)
    monkeypatch.setattr(video, "analyze_images", lambda *args, **kwargs: "Visible test pattern.")
    result = tool.execute({"source": str(media())})
    assert result["ok"] is True
    assert result["data"]["visual_status"] == "partial"
    assert len(result["data"]["analyzed_frame_timestamps"]) < len(result["data"]["requested_frame_timestamps"])
    assert any("damaged frame" in warning for warning in result["data"]["warnings"])


def test_stash_tool_resolution_does_not_touch_metadata(media, monkeypatch, tmp_path):
    path = media()
    space = tmp_path / "stash" / "space_test"
    space.mkdir(parents=True)
    stored = space / "clip.mp4"
    shutil.copyfile(path, stored)
    meta_path = space / "meta.json"
    meta_path.write_text(json.dumps({"space_id": "space_test", "last_used_at": "original",
                                    "files": [{"file_id": "f_test", "name": "clip.mp4", "stored_name": "clip.mp4"}]}))
    before = meta_path.read_bytes(), meta_path.stat().st_mtime_ns
    monkeypatch.setattr(tool, "get_stash_dir", lambda: tmp_path / "stash")
    import stash_helper
    monkeypatch.setattr(stash_helper, "get_stash_dir", lambda: tmp_path / "stash")
    monkeypatch.setattr(video, "analyze_images", lambda *args, **kwargs: "Visible test pattern.")
    result = tool.execute({"source": "stash://space_test/f_test"})
    assert result["data"]["source_stash_ref"] == "stash://space_test/f_test"
    assert result["data"]["original_path"] == "stash://space_test/f_test"
    assert (meta_path.read_bytes(), meta_path.stat().st_mtime_ns) == before


def test_sigterm_cleans_interval_audio(media, tmp_path):
    import os
    import signal
    import time
    path = media(audio_stream=True)
    marker = tmp_path / "audio-path.txt"
    program = """
import importlib.util, json, signal, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'lib'))
import video_analysis as video
from audio_transcription import AudioTranscriptionSettings
spec = importlib.util.spec_from_file_location('cancel_video_tool', Path(sys.argv[1]) / 'skills/analyze_video.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
tool.load_config = lambda: None
video.get_active_config_mode = lambda: 'cloud'
video.get_config_value = lambda key, default=None: default
video.analyze_images = lambda *args, **kwargs: 'Visible pattern.'
video.load_audio_transcription_settings = lambda: AudioTranscriptionSettings(
    provider='openai-compatible', model='test', fallback_provider='', fallback_model='',
    max_file_bytes=250*1024*1024,max_duration_seconds=7200,provider_max_bytes=25*1024*1024,
    chunk_seconds=300,timeout_seconds=900,request_timeout_seconds=300)
marker = Path(sys.argv[3])
def transcribe(path, **kwargs):
    marker.write_text(str(path))
    time.sleep(60)
video.transcribe_audio_file = transcribe
sys.argv = ['analyze_video.py', json.dumps({'source': sys.argv[2]})]
raise SystemExit(tool.main())
"""
    process = subprocess.Popen([sys.executable, "-c", program, str(ROOT), str(path), str(marker)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        until = time.monotonic() + 10
        while not marker.exists() and process.poll() is None and time.monotonic() < until:
            time.sleep(0.05)
        assert marker.exists(), process.communicate(timeout=2)
        audio_path = Path(marker.read_text())
        assert audio_path.exists()
        os.killpg(process.pid, signal.SIGTERM)
        process.communicate(timeout=5)
        assert process.returncode == 143
        assert not audio_path.parent.exists()
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=5)

def test_hard_deadline_bypasses_provider_exception_fallback(tmp_path, monkeypatch):
    import time
    path = tmp_path / "clip.mp4"
    info = video.VideoInfo(path, "clip.mp4", 20, 3, 320, 180, False, "video/mp4", "mov", 0, 4)
    original_deadline = video._Deadline
    monkeypatch.setattr(video, "_Deadline", lambda: original_deadline(0.05))
    monkeypatch.setattr(video, "inspect_video_file", lambda *args, **kwargs: info)
    monkeypatch.setattr(video, "_extract_frame", lambda info, target, deadline: ("pixels", target))
    swallowed = []

    def provider_with_fallback(*args, **kwargs):
        # The shared Ollama capability probe has this broad fallback shape.
        try:
            time.sleep(0.2)
        except Exception:
            swallowed.append(True)
        return "This must not become evidence after the hard deadline."

    monkeypatch.setattr(video, "analyze_images", provider_with_fallback)
    data = video.analyze_video_file(path)
    assert swallowed == []
    assert data["visual_status"] == "unavailable"
    assert data["analyzed_frame_timestamps"] == []
    assert data["partial"] is True
    assert any("deadline" in warning for warning in data["warnings"])

def test_longer_audio_track_does_not_request_frames_past_video_end(tmp_path, monkeypatch):
    path = tmp_path / "audio-tail.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-nostdin", "-v", "error",
        "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=2:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=4.25",
        "-c:v", "mpeg4", "-threads", "1", "-c:a", "aac", str(path),
    ], capture_output=True, check=True, timeout=30)
    monkeypatch.setattr(video, "analyze_images", lambda *args, **kwargs: "Visible test pattern.")
    monkeypatch.setattr(video, "transcribe_audio_file", lambda *args, **kwargs: SimpleNamespace(
        transcript="A spoken test phrase.", provider="test", model="test"))
    data = video.analyze_video_file(path)
    assert data["duration_seconds"] > 4
    assert data["end_seconds"] == data["duration_seconds"]
    assert data["video_duration_seconds"] == pytest.approx(3)
    assert data["frame_timestamps"][-1] == pytest.approx(2.5)
    assert data["visual_status"] == "complete"
    assert data["audio_status"] == "transcribed"
    assert data["partial"] is False

    # A follow-up wholly inside the audio-only tail must not invent a frame.
    data = video.analyze_video_file(path, start_seconds=3.5, end_seconds=4)
    assert data["frame_timestamps"] == []
    assert data["visual_status"] == "unavailable"
    assert data["audio_status"] == "transcribed"
    assert data["partial"] is True
    assert any("no video frames" in warning for warning in data["warnings"])
