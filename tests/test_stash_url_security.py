"""Offline regression tests for the shared Stash URL/IP boundary."""

import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import security_utils  # noqa: E402
import stash_helper  # noqa: E402


def _answers(*addresses):
    return [
        (socket.AF_INET6 if ":" in address else socket.AF_INET,
         socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 0))
        for address in addresses
    ]


@pytest.fixture(autouse=True)
def offline_network(monkeypatch):
    numeric_resolver = socket.getaddrinfo
    records = {
        "public.example.test": _answers("93.184.215.14"),
        "cdn.example.test": _answers("93.184.215.14"),
        "tailnet.example.test": _answers("100.64.0.1"),
        "mixed.example.test": _answers("93.184.215.14", "::ffff:100.64.0.1"),
        "empty.example.test": [],
    }

    def resolve(host, *_args, **_kwargs):
        if host in records:
            return records[host]
        # Exercise libc's numeric IPv4 forms without permitting a DNS query.
        return numeric_resolver(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM,
                                flags=socket.AI_NUMERICHOST)

    def reject_http(*_args, **_kwargs):
        raise AssertionError("Unexpected HTTP request")

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(stash_helper, "http_request", reject_http)


@pytest.mark.parametrize("address", [
    "100.64.0.0", "100.64.0.1", "100.127.255.255",
    "::ffff:100.64.0.1", "::ffff:6440:1", "::ffff:100.127.255.255",
    "fd7a:115c:a1e0::1", "::", "::1", "127.0.0.1", "10.0.0.1",
    "172.16.0.1", "192.168.0.1", "169.254.1.1", "::ffff:127.0.0.1",
    "::ffff:10.0.0.1", "::ffff:192.168.0.1", "not-an-address",
])
def test_internal_addresses_are_blocked(address):
    assert stash_helper.is_blocked_ip(address)


@pytest.mark.parametrize("address", [
    "100.63.255.255", "100.128.0.0", "93.184.215.14",
    "::ffff:93.184.215.14", "2001:4860:4860::8888",
])
def test_public_controls_and_cgnat_boundaries_remain_allowed(address):
    assert not stash_helper.is_blocked_ip(address)


@pytest.mark.parametrize("host", [
    "100.64.0.1", "100.127.255.255", "[::ffff:100.64.0.1]",
    "[::ffff:6440:1]", "[fd7a:115c:a1e0::1]", "[::]",
    "1681915905", "0x64400001", "0144.0100.0.1", "100.64.1",
    "tailnet.example.test", "mixed.example.test", "empty.example.test",
])
def test_download_rejects_internal_or_unresolved_target_before_http(host):
    with pytest.raises(stash_helper.SecurityError):
        stash_helper.safe_download(f"https://{host}/image.png")


@pytest.mark.parametrize("url", [
    "http://100.64.0.1\\@public.example.test/image.png",
    "https://[::ffff:100.64.0.1]\\@public.example.test/image.png",
    "http://[malformed",
])
def test_ambiguous_authority_is_rejected_before_dns(monkeypatch, url):
    def reject_dns(*_args, **_kwargs):
        raise AssertionError("Ambiguous URL must not reach DNS")

    monkeypatch.setattr(socket, "getaddrinfo", reject_dns)
    with pytest.raises(stash_helper.SecurityError):
        stash_helper.safe_download(url)


def test_percent_encoded_backslash_keeps_public_authority():
    url = "https://public.example.test/path%5Csegment.png"
    assert stash_helper.validate_url(url) == url


class _Response:
    def __init__(self, location=None):
        self.is_redirect = location is not None
        self.headers = {"Location": location} if location else {"Content-Type": "text/plain"}

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield b"public test content"


@pytest.mark.parametrize("target", [
    "http://100.64.0.1/image.png",
    "https://[::ffff:6440:1]/image.png",
    "https://tailnet.example.test/image.png",
    "https://mixed.example.test/image.png",
    "http://100.64.0.1\\@public.example.test/image.png",
])
def test_redirect_to_internal_target_never_reaches_second_request(monkeypatch, target):
    calls = []

    def request(method, url, **kwargs):
        calls.append(url)
        assert kwargs["allow_redirects"] is False
        return _Response(target)

    monkeypatch.setattr(stash_helper, "http_request", request)
    with pytest.raises(stash_helper.SecurityError):
        stash_helper.safe_download("https://public.example.test/image.png")
    assert calls == ["https://public.example.test/image.png"]


@pytest.mark.parametrize("target", ["/final.txt", "https://cdn.example.test/final.txt"])
def test_public_download_and_redirects_still_work(monkeypatch, target):
    calls = []

    def request(method, url, **kwargs):
        calls.append(url)
        assert kwargs["allow_redirects"] is False
        return _Response(target if len(calls) == 1 else None)

    monkeypatch.setattr(stash_helper, "http_request", request)
    data, mime, final_url = stash_helper.safe_download("https://public.example.test/start.txt")
    assert data == b"public test content"
    assert mime == "text/plain"
    assert final_url == calls[-1]
    assert len(calls) == 2


@pytest.mark.parametrize("method", ["save_from_url", "save_image_from_url"])
def test_stash_url_save_rejects_before_artifact_write(tmp_path, method):
    space = stash_helper.StashSpace("space_test", tmp_path)
    space.create()
    original = space.meta_path.read_bytes()
    with pytest.raises(stash_helper.SecurityError):
        getattr(stash_helper.StashFile(space), method)("https://tailnet.example.test/image.png")
    assert space.meta_path.read_bytes() == original
    assert list(space.space_path.iterdir()) == [space.meta_path]


def test_local_stash_content_is_not_an_outbound_url(tmp_path):
    space = stash_helper.StashSpace("space_test", tmp_path)
    space.create()
    content = "My configured service uses http://100.64.0.1:5001"
    metadata = stash_helper.StashFile(space).save_text(content, "notes.txt")
    saved = stash_helper.StashFile(space, file_id=metadata["file_id"])
    assert saved.path.read_text() == content


@pytest.mark.parametrize("url,expected", [
    ("https://100.64.0.1/image.png", False),
    ("https://[::ffff:6440:1]/image.png", False),
    ("https://tailnet.example.test/image.png", False),
    ("https://mixed.example.test/image.png", False),
    ("https://empty.example.test/image.png", False),
    ("https://unresolved.example.test/image.png", False),
    ("file:///tmp/image.png", False),
    ("http://[invalid", False),
    ("https://public.example.test/docs?example=192.168.1.1", True),
])
def test_boolean_url_helper_uses_the_shared_dns_policy(url, expected):
    assert security_utils.is_safe_url(url) is expected
