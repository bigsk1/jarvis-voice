"""GIF requests keep animation bytes and distinguish reference frames from edits."""

import base64
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tool(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "lib"))
    spec = importlib.util.spec_from_file_location("gif_generation_test", ROOT / "skills/generate_image.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "get_config_value", lambda key, default=None: {
        "OPENAI_API_KEY": "test-key",
        "IMAGE_TOOL_PROVIDER": "openai",
    }.get(key, default))
    return module


@pytest.fixture
def animation():
    output = io.BytesIO()
    Image.new("RGB", (32, 24), "red").save(
        output, format="GIF", save_all=True,
        append_images=[Image.new("RGB", (32, 24), "blue")],
        duration=[100, 300], loop=0, disposal=2,
    )
    return output.getvalue()


def response(raw):
    return SimpleNamespace(status_code=200, text="", json=lambda: {
        "data": [{"b64_json": base64.b64encode(raw).decode("ascii")}],
    })


def test_generation_sends_gif_controls_and_reports_actual_animation(tool, monkeypatch, animation):
    calls = []
    monkeypatch.setattr(tool.requests, "post", lambda url, **kwargs: calls.append((url, kwargs)) or response(animation))
    result = tool.generate_image_openai(
        "A waving cat", model="gpt-image-2.6-flare", output_format="gif",
        quality="4K", complexity="low", frame_count=2, frame_duration_ms=100,
    )
    payload = calls[0][1]["json"]
    assert payload["model"] == "gpt-image-2.6-flare"
    assert payload["output_format"] == "gif"
    assert payload["frame_count"] == 2
    assert payload["frame_duration_ms"] == 100
    assert payload["complexity"] == "low"
    assert payload["size"] == "auto"
    assert payload["quality"] == "high"
    assert result["mime_type"] == "image/gif"
    assert result["animated"] is True
    assert result["frame_count"] == 2
    assert result["duration_ms"] == 400  # Encoded timing, not requested 2 * 100.
    assert result["aspect_ratio"] == "4:3"
    assert result["requested_aspect_ratio"] == "square"
    assert base64.b64decode(result["image_base64"]) == animation


@pytest.mark.parametrize("options", [
    {"model": "gpt-image-2.5-flare", "output_format": "gif"},
    {"model": "custom-image", "output_format": "gif"},
    {"output_format": "png", "frame_count": 2},
    {"output_format": "gif", "frame_count": True},
    {"output_format": "gif", "frame_count": 17},
    {"output_format": "gif", "frame_duration_ms": 19},
    {"output_format": "gif", "frame_duration_ms": 655351},
    {"complexity": "extreme"},
    {"reference_frame": 0},
    {"output_format": "gif", "transparent": True},
])
def test_invalid_options_fail_before_provider_submission(tool, monkeypatch, options):
    def unexpected(*args, **kwargs):
        pytest.fail("invalid request submitted to provider")
    monkeypatch.setattr(tool.requests, "post", unexpected)
    with pytest.raises(ValueError):
        tool.generate_image_openai("A cat", **{"model": "gpt-image-2.6-sunburst", **options})


def test_gif_edit_sends_selected_reference_frame_as_png(tool, monkeypatch, animation, tmp_path):
    source = tmp_path / "source.gif"
    source.write_bytes(animation)
    calls = []
    monkeypatch.setattr(tool.requests, "post", lambda url, **kwargs: calls.append((url, kwargs)) or response(animation))
    result = tool.generate_image_openai(
        "Make it wave", model="gpt-image-2.6-sunburst", output_format="gif",
        reference_image=str(source), reference_frame=1, frame_count=2,
        frame_duration_ms=80, complexity="medium",
    )
    assert calls[0][0].endswith("/edits")
    fields = calls[0][1]
    assert fields["data"]["frame_count"] == "2"
    assert fields["data"]["frame_duration_ms"] == "80"
    assert fields["data"]["output_format"] == "gif"
    assert fields["data"]["complexity"] == "medium"
    _, png, mime = fields["files"]["image"]
    assert mime == "image/png"
    with Image.open(io.BytesIO(png)) as frame:
        assert frame.convert("RGB").getpixel((0, 0)) == (0, 0, 255)
    assert result["reference_frame"] == 1
    assert result["reference_frame_count"] == 2
    assert "still reference" in result["reference_note"]
    assert source.read_bytes() == animation


def test_out_of_bounds_reference_frame_is_rejected(tool, animation):
    uri = "data:image/gif;base64," + base64.b64encode(animation).decode()
    with pytest.raises(ValueError, match="less than 2"):
        tool.generate_image_openai("A cat", model="gpt-image-2.6-flare", reference_image=uri, reference_frame=2)


def test_still_response_cannot_claim_gif_success(tool, monkeypatch):
    output = io.BytesIO()
    Image.new("RGB", (16, 16)).save(output, format="PNG")
    monkeypatch.setattr(tool.requests, "post", lambda *args, **kwargs: response(output.getvalue()))
    with pytest.raises(RuntimeError, match="still image"):
        tool.generate_image_openai("A cat", model="gpt-image-2.6-flare", output_format="gif")


def test_gif_save_keeps_original_bytes_and_catalog_when_stash_fails(tool, monkeypatch, animation, tmp_path):
    import stash_helper
    monkeypatch.setattr(tool, "GENERATED_IMAGES_DIR", tmp_path)
    monkeypatch.setattr(tool, "IMAGE_CATALOG_FILE", tmp_path / "image_catalog.json")
    def unavailable(**kwargs):
        raise RuntimeError("Stash unavailable")
    monkeypatch.setattr(stash_helper, "open_space", unavailable)
    encoded = base64.b64encode(animation).decode()
    metadata = tool._inspect_generated_image(encoded)
    saved = tool.save_to_stash({
        "image_base64": encoded, "model": "gpt-image-2.6-flare", "provider": "openai", **metadata,
    }, "A waving cat")
    assert saved["filename"].endswith(".gif")
    assert Path(saved["path"]).read_bytes() == animation
    entry = json.loads((tmp_path / "image_catalog.json").read_text())[saved["filename"]]
    assert entry["model"] == "gpt-image-2.6-flare"
    assert entry["mime_type"] == "image/gif"
    assert entry["animated"] is True
    assert entry["frame_count"] == 2
    assert entry["duration_ms"] == 400


def test_gif_timeout_fits_inside_worker_budget():
    from orchestrator.executor import ToolExecutor
    executor = object.__new__(ToolExecutor)
    assert executor._get_subprocess_timeout("generate_image", {"output_format": "gif"}) == 660
    assert executor._get_subprocess_timeout("generate_image", {}) == 300
