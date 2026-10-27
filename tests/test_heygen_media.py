"""Bounded HeyGen media downloads and idempotent collection, with no provider I/O."""

import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import heygen_client as hc
import heygen_media as hm
import pytest
import requests
import stash_helper
from config_loader import config_scope
from PIL import Image
from remote_completion import completion_for_error

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\0" * 32
PUBLIC_URL = "https://media.example.test/result.mp4?signature=opaque"
MAX_VIDEO_BYTES = 128 * 1024 * 1024


class MediaResponse:
    def __init__(self, *, status=200, headers=None, chunks=None, payload=None):
        self.status_code = status
        self.headers = {"Content-Type": "video/mp4", **(headers or {})}
        self.chunks = [MP4] if chunks is None else chunks
        self.payload = payload
        self.close = Mock()
        self.iterated = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        self.iterated = True
        yield from self.chunks

    def json(self):
        return self.payload


@pytest.fixture
def no_network(monkeypatch):
    def resolve(hostname, *args, **kwargs):
        address = {"private.example.test": "10.0.0.1", "localhost": "127.0.0.1"}.get(hostname, "93.184.216.34")
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 0))]

    # Exercise the real URL validator while preventing live DNS or HTTP.
    monkeypatch.setattr(stash_helper.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(hm, "http_request", Mock(side_effect=AssertionError("Unexpected media HTTP")))
    monkeypatch.setattr(hc, "http_request", Mock(side_effect=AssertionError("Unexpected provider HTTP")))


@pytest.fixture
def configured(tmp_path, monkeypatch, no_network):
    monkeypatch.setattr(hm, "get_project_root", lambda: tmp_path)
    with config_scope("cloud", {"HEYGEN_API_KEY": "PRIVATE_API_SENTINEL", "STASH_DIR": str(tmp_path / "custom-stash")}):
        yield tmp_path


@pytest.mark.parametrize("mime", ["video/mp4", "application/mp4", "application/octet-stream", "binary/octet-stream", "VIDEO/MP4; charset=binary"])
def test_download_allows_mp4_mime_without_forwarding_api_credentials(configured, monkeypatch, mime):
    response = MediaResponse(headers={"Content-Type": mime, "Content-Length": str(len(MP4))})
    request = Mock(return_value=response)
    monkeypatch.setattr(hm, "http_request", request)
    assert hm._download_video(PUBLIC_URL) == MP4
    request.assert_called_once_with("GET", PUBLIC_URL, stream=True, timeout=(10, 120),
                                    proxy_policy="off", allow_redirects=False)
    assert "PRIVATE_API_SENTINEL" not in repr(request.call_args)
    assert "headers" not in request.call_args.kwargs and "auth" not in request.call_args.kwargs
    response.close.assert_called_once()


@pytest.mark.parametrize("url", ["http://media.example.test/file.mp4", "ftp://media.example.test/file.mp4",
                                 "https://user:secret@media.example.test/file.mp4", "https://user@media.example.test/file.mp4"])
def test_download_rejects_insecure_or_credential_urls_before_http(no_network, url):
    with pytest.raises(ValueError, match="public HTTPS URL without credentials"):
        hm._download_video(url)
    hm.http_request.assert_not_called()


def test_download_rejects_private_initial_destination_before_http(no_network):
    with pytest.raises(stash_helper.SecurityError, match="blocked IP"):
        hm._download_video("https://private.example.test/result.mp4")
    hm.http_request.assert_not_called()


def test_download_follows_relative_redirect_only_after_revalidation(no_network, monkeypatch):
    redirected = MediaResponse(status=302, headers={"Location": "/new/result.mp4"})
    result = MediaResponse()
    request = Mock(side_effect=[redirected, result])
    monkeypatch.setattr(hm, "http_request", request)
    validate = Mock(wraps=stash_helper.validate_url)
    monkeypatch.setattr(hm, "validate_url", validate)
    assert hm._download_video(PUBLIC_URL) == MP4
    assert [call.args[1] for call in request.call_args_list] == [PUBLIC_URL, "https://media.example.test/new/result.mp4"]
    assert [call.args[0] for call in validate.call_args_list] == [PUBLIC_URL, "https://media.example.test/new/result.mp4"]
    assert all(call.kwargs["allow_redirects"] is False for call in request.call_args_list)
    redirected.close.assert_called_once()
    result.close.assert_called_once()


@pytest.mark.parametrize("destination,error", [
    ("https://private.example.test/internal", stash_helper.SecurityError),
    ("http://media.example.test/insecure", ValueError),
    ("https://user:secret@media.example.test/private", ValueError),
])
def test_download_validates_redirect_target_before_second_request(no_network, monkeypatch, destination, error):
    redirect = MediaResponse(status=307, headers={"Location": destination})
    request = Mock(return_value=redirect)
    monkeypatch.setattr(hm, "http_request", request)
    with pytest.raises(error):
        hm._download_video(PUBLIC_URL)
    request.assert_called_once()
    assert redirect.iterated is False
    redirect.close.assert_called_once()


def test_missing_redirect_destination_is_closed_and_not_replayed(no_network, monkeypatch):
    response = MediaResponse(status=302)
    request = Mock(return_value=response)
    monkeypatch.setattr(hm, "http_request", request)
    with pytest.raises(ValueError, match="no destination"):
        hm._download_video(PUBLIC_URL)
    request.assert_called_once()
    response.close.assert_called_once()


def test_download_redirect_loop_is_bounded_and_closes_every_response(no_network, monkeypatch):
    responses = [MediaResponse(status=302, headers={"Location": "/again.mp4"}) for _ in range(5)]
    request = Mock(side_effect=responses)
    monkeypatch.setattr(hm, "http_request", request)
    with pytest.raises(ValueError, match="redirect limit"):
        hm._download_video(PUBLIC_URL)
    assert request.call_count == 5
    for response in responses:
        response.close.assert_called_once()


@pytest.mark.parametrize("headers,error", [
    ({"Content-Type": "text/html"}, "not an MP4"),
    ({"Content-Type": "image/png"}, "not an MP4"),
    ({"Content-Length": str(MAX_VIDEO_BYTES + 1)}, "128 MB"),
])
def test_mime_and_declared_size_rejected_before_body_read(no_network, monkeypatch, headers, error):
    response = MediaResponse(headers=headers)
    monkeypatch.setattr(hm, "http_request", Mock(return_value=response))
    with pytest.raises(ValueError, match=error):
        hm._download_video(PUBLIC_URL)
    assert response.iterated is False
    response.close.assert_called_once()


def test_stream_size_limit_enforced_even_when_content_length_lies(no_network, monkeypatch):
    chunk = b"x" * (2 * 1024 * 1024)
    response = MediaResponse(headers={"Content-Length": "1"}, chunks=(chunk for _ in range(65)))
    monkeypatch.setattr(hm, "http_request", Mock(return_value=response))
    with pytest.raises(ValueError, match="128 MB"):
        hm._download_video(PUBLIC_URL)
    response.close.assert_called_once()


@pytest.mark.parametrize("failure", [requests.Timeout, requests.ConnectionError])
def test_interrupted_body_closes_response_and_never_replays(no_network, monkeypatch, failure):
    def chunks():
        yield MP4
        raise failure("interrupted response")

    response = MediaResponse(chunks=chunks())
    request = Mock(return_value=response)
    monkeypatch.setattr(hm, "http_request", request)
    with pytest.raises(failure):
        hm._download_video(PUBLIC_URL)
    request.assert_called_once()
    response.close.assert_called_once()


def test_http_failure_closes_response_without_reading_body_or_retry(no_network, monkeypatch):
    response = MediaResponse(status=403)
    request = Mock(return_value=response)
    monkeypatch.setattr(hm, "http_request", request)
    with pytest.raises(requests.HTTPError):
        hm._download_video(PUBLIC_URL)
    assert response.iterated is False
    request.assert_called_once()
    response.close.assert_called_once()


def test_concurrent_collect_same_native_job_saves_one_artifact(configured, monkeypatch):
    barrier = threading.Barrier(2)
    both_locks_requested = threading.Event()
    lock_calls = []
    real_lock = hm.catalog_lock

    def observed_lock(path):
        lock_calls.append(path)
        if len(lock_calls) == 2:
            both_locks_requested.set()
        return real_lock(path)

    def download(_):
        assert both_locks_requested.wait(5), "Second collector did not overlap"
        return MP4

    download_mock = Mock(side_effect=download)
    monkeypatch.setattr(hm, "catalog_lock", observed_lock)
    monkeypatch.setattr(hm, "_download_video", download_mock)
    result = {"provider": "heygen", "kind": "avatar", "provider_video_id": "same_native_job",
              "model": "avatar_iv", "status": "completed", "video_url": PUBLIC_URL,
              "receipt_stash_ref": "stash://receipts/existing_job", "aspect_ratio": "16:9"}

    def collect():
        # Request config is a ContextVar and must be established in each worker.
        with config_scope("cloud", {"HEYGEN_API_KEY": "PRIVATE_API_SENTINEL", "STASH_DIR": str(configured / "custom-stash")}):
            barrier.wait(timeout=5)
            return hm.save_result(result, prompt="Exact presenter script")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(collect) for _ in range(2)]
        collected = [future.result(timeout=10) for future in futures]
    assert all(item["ok"] for item in collected)
    assert collected[0]["data"]["stash_ref"] == collected[1]["data"]["stash_ref"]
    download_mock.assert_called_once_with(PUBLIC_URL)
    media_dir = configured / "data/generated_videos"
    assert len(list(media_dir.glob("*.mp4"))) == 1
    assert not list(media_dir.glob("*.part"))
    catalog = json.loads((media_dir / "video_catalog.json").read_text())
    assert len(catalog) == 1
    entry = next(iter(catalog.values()))
    assert entry["provider_video_id"] == "same_native_job"
    assert entry["model"] == "avatar_iv"
    spaces = list((configured / "custom-stash").rglob("meta.json"))
    files = [item for meta in spaces for item in json.loads(meta.read_text())["files"]]
    assert len(files) == 1
    assert files[0]["provider_video_id"] == "same_native_job"
    resolved = stash_helper.safe_resolve_file(stash_ref=collected[0]["data"]["stash_ref"])
    assert resolved["found"] is True
    assert Path(resolved["path"]).read_bytes() == MP4
    assert Path(resolved["path"]).is_relative_to(configured / "custom-stash")


def test_non_mp4_content_is_not_enrolled_as_completed_artifact(configured, monkeypatch):
    monkeypatch.setattr(hm, "_download_video", lambda _: b"<html>upstream error</html>")
    with pytest.raises(Exception) as error:
        hm.save_result({"provider_video_id": "bad_payload", "kind": "model", "status": "completed", "video_url": PUBLIC_URL})
    assert completion_for_error(error.value) == "completed"
    assert hc.heygen_error_result(error.value)["data"]["provider_video_id"] == "bad_payload"
    assert not list(configured.rglob("*.mp4"))
    assert not list((configured / "custom-stash").rglob("meta.json"))


@pytest.mark.parametrize("failure", [requests.Timeout("PRIVATE_API_SENTINEL"), OSError("private input details"), ValueError("invalid image")])
def test_input_preparation_failure_is_rejected_before_paid_submission(configured, monkeypatch, failure):
    monkeypatch.setattr(hc, "media_input", Mock(side_effect=failure))
    client = hc.HeyGenClient()
    with pytest.raises(Exception) as error:
        client.generate_clip("Animate existing input", image_source="stash://images/source")
    output = hc.heygen_error_result(error.value)
    assert output["completion"] == "rejected"
    assert "PRIVATE_API_SENTINEL" not in json.dumps(output)
    hc.http_request.assert_not_called()


def test_actual_asset_upload_timeout_is_rejected_without_paid_video_post(configured, monkeypatch):
    source = configured / "input.png"
    Image.new("RGB", (16, 16)).save(source)
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url))
        raise requests.Timeout("PRIVATE_API_SENTINEL")

    monkeypatch.setattr(hc, "http_request", request)
    with pytest.raises(Exception) as error:
        hc.HeyGenClient().generate_clip("Animate existing input", image_source=str(source))
    output = hc.heygen_error_result(error.value)
    assert output["completion"] == "rejected"
    assert calls == [("POST", "https://api.heygen.com/v3/assets")]
    assert "PRIVATE_API_SENTINEL" not in json.dumps(output)


@pytest.mark.parametrize("action,path,id_field", [("list_avatars", "/v3/avatars/looks", "id"),
                                                  ("list_voices", "/v3/voices", "voice_id")])
def test_catalog_top_level_pagination_roundtrips_exact_token(configured, monkeypatch, action, path, id_field):
    token = "opaque+/= pagination token"
    responses = [MediaResponse(payload={"data": [{id_field: "native_7", "name": "Presenter", "api_key": "PRIVATE_FIELD"}],
                                        "next_token": token, "has_more": True}),
                 MediaResponse(payload={"data": {"items": []}, "has_more": False})]
    request = Mock(side_effect=responses)
    monkeypatch.setattr(hc, "http_request", request)
    client = hc.HeyGenClient()
    first = getattr(client, action)(limit=2)
    assert first == {"items": [{id_field: "native_7", "name": "Presenter"}], "next_cursor": token, "has_more": True}
    second = getattr(client, action)(limit=2, cursor=first["next_cursor"])
    assert second == {"items": [], "next_cursor": None, "has_more": False}
    assert [call.args for call in request.call_args_list] == [("GET", "https://api.heygen.com" + path)] * 2
    assert request.call_args_list[1].kwargs["params"] == {"limit": 2, "token": token}
    for response in responses:
        response.close.assert_called_once()
