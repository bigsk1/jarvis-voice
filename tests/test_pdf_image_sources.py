"""Markdown report pictures resolve safely and become self-contained PDF rasters."""

import base64
import builtins
import importlib
import io
import ipaddress
from pathlib import Path
from urllib.parse import quote_from_bytes

import fitz
import pytest
import requests
from PIL import Image

from lib import paths, pdf_rendering, stash_helper


def _raster(format="PNG", *, size=(48, 24), color=(25, 100, 175)):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format)
    return output.getvalue()


def _data_url(data, mime="image/png"):
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _render(tmp_path, markdown, *, source_path=None, name="image-sources.pdf"):
    output = tmp_path / name
    metadata = pdf_rendering.render_markdown_pdf(
        markdown, str(output), "Image source report", source_path=source_path,
    )
    with fitz.open(output) as document:
        text = " ".join(" ".join(page.get_text() for page in document).split())
        images = [
            document.extract_image(xref)
            for xref in {row[0] for page in document for row in page.get_images(full=True)}
        ]
    return output, metadata, text, images


def _omitted(tmp_path, target, *, source_path=None):
    result = _render(
        tmp_path,
        f"BEFORE PICTURE\n\n![Report picture]({target})\n\nCOMPLETE FINAL TEXT",
        source_path=source_path,
    )
    _, metadata, text, images = result
    assert images == []
    assert "Report picture" in text
    assert "BEFORE PICTURE" in text and "COMPLETE FINAL TEXT" in text
    assert metadata["warnings"], "Omitted Markdown images must be reported to the caller"
    return result


def _forbid_reads(monkeypatch, blocked):
    blocked = Path(blocked).resolve()

    def guarded(opener):
        def checked(file, *args, **kwargs):
            if isinstance(file, (str, Path)) and Path(file).resolve() == blocked:
                pytest.fail("Rejected image references must not read the target bytes")
            return opener(file, *args, **kwargs)
        return checked

    monkeypatch.setattr(builtins, "open", guarded(builtins.open))
    monkeypatch.setattr(io, "open", guarded(io.open))


@pytest.mark.parametrize("format,mime", [
    ("PNG", "image/png"),
    ("JPEG", "image/jpeg"),
    ("WEBP", "image/webp"),
    ("GIF", "image/gif"),
])
def test_inline_data_rasters_are_embedded_without_source_files(tmp_path, format, mime):
    _, metadata, text, images = _render(
        tmp_path, f"A report paragraph.\n\n![Inline chart]({_data_url(_raster(format), mime)})\n\nReport tail.",
    )
    assert len(images) == 1
    assert (images[0]["width"], images[0]["height"]) == (48, 24)
    assert "A report paragraph." in text and "Report tail." in text
    assert "[Image:" not in text
    assert metadata["warnings"] == []


@pytest.mark.parametrize("target", [
    "data:image/png;base64,definitely!not!base64",
    _data_url(b"This is plain text."),
    _data_url(b"\x89PNG\r\n\x1a\ntruncated"),
    _data_url(_raster(), "image/jpeg"),
    _data_url(_raster("JPEG"), "image/png"),
    _data_url(b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="4" height="4"/></svg>'),
], ids=["invalid-base64", "text", "truncated", "png-as-jpeg", "jpeg-as-png", "svg-as-png"])
def test_invalid_or_spoofed_inline_images_leave_visible_reference(tmp_path, target):
    _omitted(tmp_path, target)


def test_inline_data_is_bounded_before_decoding(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_rendering, "MAX_IMAGE_BYTES", 32)
    def forbidden(*args, **kwargs):
        pytest.fail("Oversized base64 payloads must be rejected before decoding")
    monkeypatch.setattr(base64, "b64decode", forbidden)
    _, metadata, _, _ = _omitted(tmp_path, _data_url(_raster()))
    assert any(any(word in warning.lower() for word in ("limit", "large", "budget")) for warning in metadata["warnings"])


def test_percent_encoded_inline_raster_is_supported(tmp_path):
    target = f"data:image/png,{quote_from_bytes(_raster(), safe='')}"
    _, metadata, _, images = _render(tmp_path, f"![Percent encoded chart]({target})")
    assert len(images) == 1 and metadata["warnings"] == []


def test_inline_animated_gif_is_fully_checked_and_prints_first_frame(tmp_path):
    first = Image.new("RGB", (12, 8), (30, 120, 240))
    second = Image.new("RGB", (12, 8), (240, 80, 30))
    source = io.BytesIO()
    first.save(source, "GIF", save_all=True, append_images=[second], duration=[80, 120], loop=0)
    animation = source.getvalue()

    _, metadata, _, images = _render(tmp_path, f"![Motion chart]({_data_url(animation, 'image/gif')})")
    assert len(images) == 1
    with Image.open(io.BytesIO(images[0]["image"])) as embedded:
        assert embedded.convert("RGB").getpixel((0, 0)) == (30, 120, 240)
    assert any("first frame" in warning.lower() for warning in metadata["warnings"])

    # This still decodes frame zero in Pillow; the complete animation must be valid.
    with Image.open(io.BytesIO(animation[:-1])) as incomplete:
        incomplete.load()
    _omitted(tmp_path, _data_url(animation[:-1], "image/gif"))


def test_relative_image_uses_original_markdown_directory_and_keeps_source_bytes(tmp_path, monkeypatch):
    source_dir = tmp_path / "report-source"
    (source_dir / "images").mkdir(parents=True)
    source_path = source_dir / "report.md"
    markdown = "Before chart.\n\n![Quarterly chart](./images/chart.png)\n\nAfter chart."
    source_path.write_text(markdown)
    picture = source_dir / "images" / "chart.png"
    data = _raster()
    picture.write_bytes(data)
    unrelated_cwd = tmp_path / "unrelated-working-directory"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    _, metadata, text, images = _render(tmp_path, markdown, source_path=source_path)
    assert len(images) == 1
    assert "Before chart." in text and "After chart." in text and "[Image:" not in text
    assert metadata["warnings"] == []
    assert picture.read_bytes() == data
    assert source_path.read_text() == markdown


def test_relative_image_decodes_url_encoded_filename(tmp_path):
    source_path = tmp_path / "report.md"
    source_path.write_text("A source document.")
    (tmp_path / "revenue chart.png").write_bytes(_raster())
    _, metadata, _, images = _render(
        tmp_path, "![Revenue chart](./revenue%20chart.png)", source_path=source_path,
    )
    assert len(images) == 1 and metadata["warnings"] == []


def test_relative_image_without_source_path_never_uses_current_directory(tmp_path, monkeypatch):
    picture = tmp_path / "chart.png"
    picture.write_bytes(_raster())
    monkeypatch.chdir(tmp_path)
    _forbid_reads(monkeypatch, picture)
    _omitted(tmp_path, "./chart.png")


@pytest.mark.parametrize("target", ["../outside.png", "%2e%2e/outside.png", "./../outside.png"])
def test_relative_traversal_never_reads_outside_source_directory(tmp_path, monkeypatch, target):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_path = source_dir / "report.md"
    source_path.write_text("Source.")
    outside = tmp_path / "outside.png"
    outside.write_bytes(_raster())
    _forbid_reads(monkeypatch, outside)
    _omitted(tmp_path, target, source_path=source_path)


def test_relative_symlink_cannot_escape_source_directory(tmp_path, monkeypatch):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_path = source_dir / "report.md"
    source_path.write_text("Source.")
    outside = tmp_path / "private.png"
    outside.write_bytes(_raster())
    (source_dir / "chart.png").symlink_to(outside)
    _forbid_reads(monkeypatch, outside)
    _omitted(tmp_path, "./chart.png", source_path=source_path)


def test_absolute_image_reference_is_not_authorized_by_source_path(tmp_path, monkeypatch):
    picture = tmp_path / "chart.png"
    picture.write_bytes(_raster())
    source_path = tmp_path / "report.md"
    source_path.write_text("Source.")
    _forbid_reads(monkeypatch, picture)
    _omitted(tmp_path, str(picture), source_path=source_path)


def test_file_url_is_literal_markdown_and_never_loads_the_local_file(tmp_path, monkeypatch):
    picture = tmp_path / "chart.png"
    picture.write_bytes(_raster())
    _forbid_reads(monkeypatch, picture)
    _, _, text, images = _render(tmp_path, f"![File picture]({picture.as_uri()})\n\nComplete tail.")
    assert images == []
    assert "![File picture](file:///" in text and "Complete tail." in text


def test_relative_image_obeys_shared_restricted_read_policy(tmp_path, monkeypatch):
    source_path = tmp_path / "report.md"
    source_path.write_text("Source.")
    picture = tmp_path / "chart.png"
    picture.write_bytes(_raster())
    policy_modules = {paths, importlib.import_module(stash_helper.assert_not_restricted_read_path.__module__)}
    for policy in policy_modules:
        monkeypatch.setattr(policy, "get_restricted_read_paths", lambda: [str(picture)])
    _forbid_reads(monkeypatch, picture)
    _, metadata, _, _ = _omitted(tmp_path, "./chart.png", source_path=source_path)
    assert any("restricted" in warning.lower() for warning in metadata["warnings"])


def test_public_image_download_is_embedded_once_and_keeps_no_external_picture_dependency(tmp_path, monkeypatch):
    downloaded = []
    data = _raster()

    def download(target, max_bytes, **kwargs):
        downloaded.append((target, max_bytes))
        return data

    monkeypatch.setattr(pdf_rendering, "_download_public_image", download)
    target = "https://images.example.invalid/chart.png"
    output, metadata, text, images = _render(
        tmp_path, f"![First chart]({target})\n\nText between charts.\n\n![Second chart]({target})\n\nComplete tail.",
    )
    assert len(downloaded) == 1 and downloaded[0][0] == target
    assert len(images) == 1
    assert "Text between charts." in text and "Complete tail." in text and "[Image:" not in text
    assert metadata["warnings"] == []
    with fitz.open(output) as document:
        assert all(not page.get_links() for page in document)
        assert document.embfile_count() == 0


@pytest.mark.parametrize("payload", [b"<html>Not an image</html>", b"\x89PNG\r\n\x1a\ntruncated"])
def test_public_download_still_requires_valid_raster_content(tmp_path, monkeypatch, payload):
    monkeypatch.setattr(pdf_rendering, "_download_public_image", lambda target, max_bytes, **kwargs: payload)
    _omitted(tmp_path, "https://images.example.invalid/chart.png")


def test_failed_public_download_consumes_shared_time_budget(tmp_path, monkeypatch):
    clock = {"now": 0.0}
    attempts = []

    def download(target, max_bytes, **kwargs):
        attempts.append(target)
        clock["now"] += pdf_rendering.TOTAL_IMAGE_DOWNLOAD_SECONDS
        raise ValueError("Remote image timed out")

    monkeypatch.setattr(pdf_rendering.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(pdf_rendering, "_download_public_image", download)
    _, metadata, text, images = _render(
        tmp_path,
        "![First](https://images.example.invalid/first.png)\n\n"
        "![Second](https://images.example.invalid/second.png)\n\nComplete final text.",
    )
    assert attempts == ["https://images.example.invalid/first.png"]
    assert images == [] and "Complete final text." in text
    assert any("time limit" in warning.lower() for warning in metadata["warnings"])


@pytest.mark.parametrize("source", ["data", "public"])
def test_wrong_mime_bytes_consume_document_budget_before_later_valid_image(
    tmp_path, monkeypatch, source,
):
    data = _raster()
    monkeypatch.setattr(pdf_rendering, "MAX_TOTAL_IMAGE_BYTES", len(data))
    if source == "data":
        target = _data_url(data, "image/jpeg")
    else:
        target = "https://images.example.invalid/wrong-mime.png"
        _mock_download_transport(monkeypatch, [_DownloadResponse(data, mime="image/jpeg")])
    _, metadata, text, images = _render(
        tmp_path,
        f"![Spoofed picture]({target})\n\n![Valid later picture]({_data_url(data)})\n\nComplete final text.",
    )
    assert images == []
    assert "[Image: Spoofed picture" in text and "[Image: Valid later picture" in text
    assert "Complete final text." in text
    assert any("byte limit" in warning.lower() for warning in metadata["warnings"])


def test_partial_failed_download_consumes_bytes_before_later_valid_image(tmp_path, monkeypatch):
    data = _raster()

    class InterruptedResponse(_DownloadResponse):
        def iter_content(self, chunk_size):
            yield self.data
            raise requests.exceptions.ConnectionError("Connection lost after partial image body")

    response = InterruptedResponse(data)
    _mock_download_transport(monkeypatch, [response])
    monkeypatch.setattr(pdf_rendering, "MAX_TOTAL_IMAGE_BYTES", len(data))
    _, metadata, text, images = _render(
        tmp_path,
        "![Interrupted picture](https://images.example.invalid/interrupted.png)\n\n"
        f"![Valid later picture]({_data_url(data)})\n\nComplete final text.",
    )
    assert images == [] and response.closed
    assert "[Image: Valid later picture" in text and "Complete final text." in text
    assert any("byte limit" in warning.lower() for warning in metadata["warnings"])


@pytest.mark.parametrize("limit", ["MAX_EMBEDDED_IMAGES", "MAX_TOTAL_IMAGE_BYTES", "MAX_TOTAL_IMAGE_PIXELS"])
def test_data_relative_and_public_images_share_document_budgets(tmp_path, monkeypatch, limit):
    source_path = tmp_path / "report.md"
    source_path.write_text("Source.")
    inline_data = _raster(size=(10, 10), color=(20, 40, 60))
    relative_data = _raster(size=(20, 10), color=(30, 60, 90))
    remote_data = _raster(size=(30, 10), color=(40, 80, 120))
    (tmp_path / "relative.png").write_bytes(relative_data)
    monkeypatch.setattr(pdf_rendering, "_download_public_image", lambda target, max_bytes, **kwargs: remote_data)
    budgets = {
        "MAX_EMBEDDED_IMAGES": 2,
        "MAX_TOTAL_IMAGE_BYTES": len(inline_data) + len(relative_data),
        "MAX_TOTAL_IMAGE_PIXELS": 10 * 10 + 20 * 10,
    }
    monkeypatch.setattr(pdf_rendering, limit, budgets[limit])

    _, metadata, text, images = _render(
        tmp_path,
        f"![Inline]({_data_url(inline_data)})\n\n![Relative](./relative.png)\n\n"
        "![Public](https://images.example.invalid/public.png)\n\nComplete final text.",
        source_path=source_path,
    )
    assert sorted(image["width"] for image in images) == [10, 20]
    assert "[Image: Public" in text and "Complete final text." in text
    assert any(any(word in warning.lower() for word in ("limit", "exceed", "budget")) for warning in metadata["warnings"])


def test_shared_pdf_resolves_same_relative_name_per_source_document(tmp_path):
    pdf = pdf_rendering.DocumentPDF("Combined report")
    pdf.add_page()
    for name, color, width in (("first", (150, 20, 20), 15), ("second", (20, 20, 150), 30)):
        directory = tmp_path / name
        directory.mkdir()
        source_path = directory / "report.md"
        source_path.write_text("Source.")
        (directory / "chart.png").write_bytes(_raster(size=(width, 10), color=color))
        pdf_rendering.write_markdown(pdf, f"{name} report\n\n![Chart](./chart.png)", source_path=source_path)
    output = tmp_path / "combined.pdf"
    pdf.output(output)
    with fitz.open(output) as document:
        images = [
            document.extract_image(xref)
            for xref in {row[0] for page in document for row in page.get_images(full=True)}
        ]
    assert sorted(image["width"] for image in images) == [15, 30]
    assert pdf.warnings() == []


class _DownloadResponse:
    def __init__(self, data=b"", *, mime="image/png", redirect=None):
        self.data = data
        self.closed = False
        self.status_code = 302 if redirect is not None else 200
        self.is_redirect = redirect is not None
        self.headers = {"Content-Type": mime}
        if redirect is not None:
            self.headers["Location"] = redirect

    def raise_for_status(self):
        pass

    def close(self):
        self.closed = True

    def iter_content(self, chunk_size):
        for position in range(0, len(self.data), chunk_size):
            yield self.data[position:position + chunk_size]


def _mock_download_transport(monkeypatch, responses, *, addresses=("93.184.216.34",)):
    """Exercise the real Stash HTTP policy without DNS or socket side effects."""
    stash = pdf_rendering._stash_helpers()
    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        assert responses, "Unexpected extra download request"
        return responses.pop(0)

    def resolve(host, *args, **kwargs):
        try:
            ipaddress.ip_address(host)
        except ValueError:
            resolved = addresses
        else:
            resolved = (host,)
        return [(2, 1, 6, "", (address, 443)) for address in resolved]

    monkeypatch.setattr(stash, "http_request", request)
    monkeypatch.setattr(stash, "HAS_MAGIC", False)
    monkeypatch.setattr(stash.socket, "getaddrinfo", resolve)
    return requests


def test_public_downloader_reuses_redirect_validation_and_bounded_streaming(monkeypatch):
    data = _raster()
    responses = [
        _DownloadResponse(redirect="/final.png"), _DownloadResponse(data),
    ]
    requests = _mock_download_transport(monkeypatch, responses.copy())
    assert pdf_rendering._download_public_image("https://images.example.invalid/chart.png", len(data)) == data
    assert [request[1] for request in requests] == [
        "https://images.example.invalid/chart.png", "https://images.example.invalid/final.png",
    ]
    assert all(request[2]["allow_redirects"] is False for request in requests)
    assert all(request[2]["stream"] is True for request in requests)
    assert all(response.closed for response in responses)


@pytest.mark.parametrize("target", [
    "http://127.0.0.1/chart.png",
    "http://192.168.1.10/chart.png",
    "http://169.254.169.254/chart.png",
    "http://[::1]/chart.png",
    "https://user:password@images.example.invalid/chart.png",
])
def test_public_downloader_rejects_private_or_credential_urls_before_request(monkeypatch, target):
    requests = _mock_download_transport(monkeypatch, [])
    with pytest.raises((ValueError, stash_helper.SecurityError)):
        pdf_rendering._download_public_image(target, 1024)
    assert requests == []


def test_public_downloader_rejects_hostname_with_any_private_dns_answer(monkeypatch):
    requests = _mock_download_transport(monkeypatch, [], addresses=("93.184.216.34", "192.168.1.10"))
    with pytest.raises(stash_helper.SecurityError):
        pdf_rendering._download_public_image("https://images.example.invalid/chart.png", 1024)
    assert requests == []


def test_public_downloader_never_requests_private_redirect_target(monkeypatch):
    requests = _mock_download_transport(monkeypatch, [
        _DownloadResponse(redirect="http://169.254.169.254/latest/meta-data/"),
    ])
    with pytest.raises(stash_helper.SecurityError):
        pdf_rendering._download_public_image("https://images.example.invalid/chart.png", 1024)
    assert len(requests) == 1


@pytest.mark.parametrize("mime", ["image/png", "application/octet-stream"])
def test_public_downloader_accepts_supported_raster_or_unspecified_mime(monkeypatch, mime):
    data = _raster()
    _mock_download_transport(monkeypatch, [_DownloadResponse(data, mime=mime)])
    assert pdf_rendering._download_public_image("https://images.example.invalid/chart.png", 1024) == data


@pytest.mark.parametrize("mime", ["image/jpeg", "text/plain", "image/svg+xml"])
def test_public_downloader_rejects_spoofed_or_unsupported_mime(monkeypatch, mime):
    _mock_download_transport(monkeypatch, [_DownloadResponse(_raster(), mime=mime)])
    with pytest.raises((ValueError, stash_helper.SecurityError)):
        pdf_rendering._download_public_image("https://images.example.invalid/chart.png", 1024)


def test_public_downloader_stops_when_stream_exceeds_byte_budget(monkeypatch):
    response = _DownloadResponse(_raster())
    _mock_download_transport(monkeypatch, [response])
    with pytest.raises(ValueError, match="(?i)(size|large|limit)"):
        pdf_rendering._download_public_image("https://images.example.invalid/chart.png", 32)
    assert response.closed


def test_public_downloader_closes_response_when_stream_exhausts_time_budget(monkeypatch):
    clock = {"now": 0.0}

    class SlowResponse(_DownloadResponse):
        def iter_content(self, chunk_size):
            clock["now"] = 9.0
            yield self.data

    response = SlowResponse(_raster())
    _mock_download_transport(monkeypatch, [response])
    monkeypatch.setattr(pdf_rendering.time, "monotonic", lambda: clock["now"])
    with pytest.raises(ValueError, match="(?i)time limit"):
        pdf_rendering._download_public_image("https://images.example.invalid/chart.png", 1024, timeout=8.0)
    assert response.closed


def test_public_downloader_bounds_redirects_and_closes_every_response(monkeypatch):
    responses = [_DownloadResponse(redirect="/loop.png") for _ in range(stash_helper.MAX_REDIRECTS + 1)]
    requests = _mock_download_transport(monkeypatch, responses.copy())
    with pytest.raises(ValueError, match="(?i)redirect"):
        pdf_rendering._download_public_image("https://images.example.invalid/chart.png", 1024)
    assert len(requests) == stash_helper.MAX_REDIRECTS + 1
    assert all(response.closed for response in responses)


def test_public_downloader_proxy_attempts_share_one_deadline(monkeypatch):
    """Real proxy fallback must stop once the image's total allowance is spent."""
    stash = pdf_rendering._stash_helpers()
    http_client = importlib.import_module(stash.http_request.__module__)
    clock = {"now": 0.0}
    attempts = []
    settings = {
        "JARVIS_TOOL_PROXY_POLICY": "prefer",
        "LOCAL_PROXY": "http://first-proxy.example.invalid:8080",
        "LOCAL_PROXY2": "http://second-proxy.example.invalid:8080",
    }

    def failed_request(method, url, **kwargs):
        attempts.append((kwargs.get("proxies"), kwargs["timeout"]))
        clock["now"] += 5.0 if len(attempts) == 1 else 3.0
        raise requests.exceptions.ProxyError("Synthetic proxy failure")

    monkeypatch.setattr(http_client, "get_config_value", lambda key, default=None: settings.get(key, default))
    monkeypatch.setattr(http_client.requests, "request", failed_request)
    monkeypatch.setattr(stash.socket, "getaddrinfo", lambda *args, **kwargs: [
        (2, 1, 6, "", ("93.184.216.34", 443)),
    ])
    monkeypatch.setattr(pdf_rendering.time, "monotonic", lambda: clock["now"])

    with pytest.raises(requests.exceptions.Timeout):
        pdf_rendering._download_public_image("https://images.example.invalid/chart.png", 1024, timeout=8.0)

    assert len(attempts) == 2, "The spent deadline must prevent a third, direct attempt"
    assert attempts[0][1] == (8.0, 8.0)
    assert attempts[1][1] == (3.0, 3.0)
    assert attempts[0][0]["https"] == settings["LOCAL_PROXY"]
    assert attempts[1][0]["https"] == settings["LOCAL_PROXY2"]
