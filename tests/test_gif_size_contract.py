"""Saved GIFs have the same byte limit when imported, inspected, or edited."""

import base64
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from lib import stash_helper

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def gif_bytes():
    output = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(
        output, "GIF", save_all=True,
        append_images=[Image.new("RGB", (16, 16), "blue")], duration=[100, 200],
    )
    return output.getvalue()


@pytest.fixture(scope="module")
def gif_above_still_limit(gif_bytes):
    # Trailing padding leaves the decoded frames unchanged while exercising
    # the actual incoming-byte limit rather than allocating huge pixel arrays.
    return gif_bytes + bytes(21 * 1024 * 1024 - len(gif_bytes))


def test_gif_import_and_inspection_accept_saved_upload_size(
    monkeypatch, gif_above_still_limit,
):
    calls = []

    def download(url, **kwargs):
        calls.append(kwargs)
        return gif_above_still_limit, "image/gif", url

    monkeypatch.setattr(stash_helper, "safe_download", download)
    original, mime, _, metadata = stash_helper.safe_download_image(
        "https://example.test/animation.gif", allow_gif=True,
    )
    assert calls[0]["max_size"] == stash_helper.GIF_MAX_FILE_SIZE == 30 * 1024 * 1024
    assert original == gif_above_still_limit
    assert mime == "image/gif"
    assert metadata["frame_count"] == 2
    assert metadata["frame_durations_ms"] == [100, 200]
    assert metadata["duration_ms"] == 300
    assert stash_helper.inspect_gif_image(original)["frame_count"] == 2
    with pytest.raises(stash_helper.SecurityError, match="byte safety limit"):
        stash_helper.inspect_gif_image(original, max_size=20 * 1024 * 1024)


def test_gif_opt_in_keeps_still_image_limit(monkeypatch, gif_above_still_limit):
    # Oversized content that isn't a GIF must fail before image decoding.
    monkeypatch.setattr(stash_helper, "safe_download", lambda *_args, **_kwargs: (
        b"not-gif" + gif_above_still_limit, "image/jpeg", "https://example.test/image.jpg",
    ))
    with pytest.raises(stash_helper.SecurityError, match="20971520-byte"):
        stash_helper.safe_download_image("https://example.test/image.jpg", allow_gif=True)


def test_gif_edit_accepts_same_large_source_without_altering_it(
    tmp_path, monkeypatch, gif_bytes, gif_above_still_limit,
):
    monkeypatch.syspath_prepend(str(ROOT / "lib"))
    spec = importlib.util.spec_from_file_location("gif_size_edit_test", ROOT / "skills/generate_image.py")
    assert spec and spec.loader
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    monkeypatch.setattr(tool, "get_config_value", lambda key, default=None: (
        "test-key" if key == "OPENAI_API_KEY" else default
    ))
    source = tmp_path / "uploaded.gif"
    source.write_bytes(gif_above_still_limit)
    calls = []

    def submit(url, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=200, json=lambda: {
            "data": [{"b64_json": base64.b64encode(gif_bytes).decode()}],
        })

    monkeypatch.setattr(tool.requests, "post", submit)
    result = tool.generate_image_openai(
        "Make a new animation", model="gpt-image-2.6-flare", output_format="gif",
        reference_image=str(source), reference_frame=1,
    )
    assert result["reference_frame"] == 1
    assert result["animated"] is True
    assert calls[0]["files"]["image"][2] == "image/png"
    assert source.read_bytes() == gif_above_still_limit
