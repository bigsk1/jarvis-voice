"""Generation tools retain provider/model metadata outside stash."""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIB_ROOT = PROJECT_ROOT / "lib"


def _load_module(name: str, path: Path):
    sys.path.insert(0, str(LIB_ROOT))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_generate_image_catalog_keeps_model_when_stash_fails(tmp_path, monkeypatch):
    generate_image = _load_module(
        "generate_image_model_catalog_test",
        PROJECT_ROOT / "skills" / "generate_image.py",
    )
    monkeypatch.setattr(generate_image, "GENERATED_IMAGES_DIR", tmp_path)
    monkeypatch.setattr(
        generate_image,
        "IMAGE_CATALOG_FILE",
        tmp_path / "image_catalog.json",
    )

    import stash_helper

    monkeypatch.setattr(
        stash_helper,
        "open_space",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("stash unavailable")),
    )
    result = generate_image.save_to_stash(
        {
            "image_base64": base64.b64encode(b"generated-image").decode(),
            "mime_type": "image/png",
            "provider": "openai",
            "model": "gpt-image-2",
            "aspect_ratio": "16:9",
        },
        "Model badge image",
    )

    catalog = json.loads((tmp_path / "image_catalog.json").read_text())
    entry = catalog[result["filename"]]
    assert result["stash"] is False
    assert entry["provider"] == "OpenAI"
    assert entry["model"] == "gpt-image-2"
    assert entry["aspect"] == "16:9"


def test_generate_video_catalog_keeps_model_when_stash_fails(tmp_path, monkeypatch):
    generate_video = _load_module(
        "generate_video_model_catalog_test",
        PROJECT_ROOT / "skills" / "generate_video.py",
    )
    monkeypatch.setattr(
        generate_video,
        "VIDEO_CATALOG_FILE",
        tmp_path / "video_catalog.json",
    )

    import stash_helper

    monkeypatch.setattr(
        stash_helper,
        "open_space",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("stash unavailable")),
    )
    video_path = tmp_path / "video_model_badge.mp4"
    video_path.write_bytes(b"generated-video")
    result = generate_video.save_to_stash(
        video_path,
        "Model badge video",
        {
            "provider": "gemini",
            "model": "veo-3.1-generate-preview",
            "aspect_ratio": "16:9",
        },
    )

    catalog = json.loads((tmp_path / "video_catalog.json").read_text())
    entry = catalog[video_path.name]
    assert result["stash"] is False
    assert entry["provider"] == "Gemini"
    assert entry["model"] == "veo-3.1-generate-preview"
    assert entry["aspect"] == "16:9"
