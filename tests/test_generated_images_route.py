"""Contract tests for the generated-images FastAPI route."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

from api.routes import generated_images


def test_generate_route_passes_shared_gemini_options_to_tool():
    request = generated_images.GenerateRequest(
        prompt="Change the sky to sunset",
        reference_image="stash://space/file",
        aspect_ratio="4:5",
        image_size="4K",
        style="photorealistic",
        negative_prompt="watermark",
        use_grounding=True,
        provider="gemini",
        mode="local",
    )
    completed = SimpleNamespace(
        returncode=0,
        stdout=json.dumps({"ok": True, "speech": "done", "data": {"provider": "gemini"}}),
        stderr="",
    )

    with patch.object(generated_images.subprocess, "run", return_value=completed) as run:
        response = asyncio.run(generated_images.generate_image(request))

    command = run.call_args.args[0]
    payload = json.loads(command[2])
    assert command[0] == "python3"
    assert payload == {
        "prompt": "Change the sky to sunset",
        "aspect_ratio": "4:5",
        "image_size": "4K",
        "save": True,
        "use_grounding": True,
        "reference_image": "stash://space/file",
        "style": "photorealistic",
        "negative_prompt": "watermark",
        "provider": "gemini",
    }
    assert run.call_args.kwargs["env"]["JARVIS_MODE"] == "local"
    assert response.ok is True
    assert response.data == {"provider": "gemini"}


def test_delete_generated_image_preserves_cdn_catalog_entry(tmp_path, monkeypatch):
    image = tmp_path / "generated_example.png"
    image.write_bytes(b"local-image")
    catalog_file = tmp_path / "cdn_catalog.json"
    catalog_file.write_text(json.dumps({
        image.name: {
            "url": "https://imagedelivery.net/account/example/public",
            "image_id": "example",
            "uploaded_at": "2026-07-13T20:00:00",
        }
    }))
    before = catalog_file.read_bytes()
    monkeypatch.setattr(generated_images, "GENERATED_IMAGES_DIR", tmp_path)
    monkeypatch.setattr(generated_images, "CDN_CATALOG_FILE", catalog_file)

    response = asyncio.run(generated_images.delete_generated_image(image.name))

    assert response.ok is True
    assert response.deleted == image.name
    assert not image.exists()
    assert catalog_file.read_bytes() == before


def test_delete_cdn_catalog_image_deletes_remote_and_catalog_but_keeps_local(tmp_path, monkeypatch):
    image = tmp_path / "generated_example.png"
    image.write_bytes(b"local-image")
    catalog_file = tmp_path / "cdn_catalog.json"
    catalog_file.write_text(json.dumps({
        image.name: {
            "url": "https://imagedelivery.net/account/example/public",
            "image_id": "gallery/2026-07-13/generated/example",
            "uploaded_at": "2026-07-13T20:00:00",
        }
    }))
    monkeypatch.setattr(generated_images, "GENERATED_IMAGES_DIR", tmp_path)
    monkeypatch.setattr(generated_images, "CDN_CATALOG_FILE", catalog_file)

    with patch("upload_cloudflare.delete_from_cloudflare", return_value={"ok": True}) as delete:
        response = asyncio.run(generated_images.delete_cdn_catalog_image(image.name))

    delete.assert_called_once_with("gallery/2026-07-13/generated/example")
    assert response.ok is True
    assert response.removed_from_catalog is True
    assert image.exists()
    assert json.loads(catalog_file.read_text()) == {}


def test_delete_cdn_catalog_image_preserves_catalog_when_cloudflare_fails(tmp_path, monkeypatch):
    catalog_file = tmp_path / "cdn_catalog.json"
    entry = {
        "url": "https://imagedelivery.net/account/example/public",
        "image_id": "example",
        "uploaded_at": "2026-07-13T20:00:00",
    }
    catalog_file.write_text(json.dumps({"generated_example.png": entry}))
    before = catalog_file.read_bytes()
    monkeypatch.setattr(generated_images, "CDN_CATALOG_FILE", catalog_file)

    with patch(
        "upload_cloudflare.delete_from_cloudflare",
        return_value={"ok": False, "error": "permission denied"},
    ):
        try:
            asyncio.run(generated_images.delete_cdn_catalog_image("generated_example.png"))
        except generated_images.HTTPException as error:
            assert error.status_code == 502
            assert error.detail == "permission denied"
        else:
            raise AssertionError("Expected Cloudflare deletion failure")

    assert catalog_file.read_bytes() == before


def test_delete_cdn_catalog_image_returns_orphan_detail_on_cloudflare_404(tmp_path, monkeypatch):
    catalog_file = tmp_path / "cdn_catalog.json"
    entry = {
        "url": "https://imagedelivery.net/account/missing/public",
        "image_id": "missing",
        "uploaded_at": "2026-07-13T20:00:00",
    }
    catalog_file.write_text(json.dumps({"orphan.png": entry}))
    before = catalog_file.read_bytes()
    monkeypatch.setattr(generated_images, "CDN_CATALOG_FILE", catalog_file)

    with patch(
        "upload_cloudflare.delete_from_cloudflare",
        return_value={
            "ok": False,
            "error": "Image not found",
            "status_code": 404,
        },
    ):
        try:
            asyncio.run(generated_images.delete_cdn_catalog_image("orphan.png"))
        except generated_images.HTTPException as error:
            assert error.status_code == 404
            assert error.detail == {
                "code": "cloudflare_image_not_found",
                "message": "Image not found",
                "image_id": "missing",
                "catalog_entry_preserved": True,
            }
        else:
            raise AssertionError("Expected Cloudflare not-found response")

    assert catalog_file.read_bytes() == before


def test_remove_stale_cdn_catalog_entry_requires_matching_image_id(tmp_path, monkeypatch):
    local_image = tmp_path / "orphan.png"
    local_image.write_bytes(b"local-image")
    catalog_file = tmp_path / "cdn_catalog.json"
    entry = {
        "url": "https://imagedelivery.net/account/missing/public",
        "image_id": "missing",
        "uploaded_at": "2026-07-13T20:00:00",
    }
    catalog_file.write_text(json.dumps({local_image.name: entry}))
    monkeypatch.setattr(generated_images, "CDN_CATALOG_FILE", catalog_file)

    response = asyncio.run(generated_images.remove_cdn_catalog_entry(
        local_image.name,
        generated_images.CdnCatalogEntryRemovalRequest(expected_image_id="missing"),
    ))

    assert response.ok is True
    assert response.deleted_from_cloudflare is False
    assert response.removed_from_catalog is True
    assert local_image.exists()
    assert json.loads(catalog_file.read_text()) == {}


def test_remove_stale_cdn_catalog_entry_rejects_changed_entry(tmp_path, monkeypatch):
    catalog_file = tmp_path / "cdn_catalog.json"
    catalog_file.write_text(json.dumps({
        "orphan.png": {
            "url": "https://imagedelivery.net/account/new/public",
            "image_id": "new-image",
            "uploaded_at": "2026-07-13T21:00:00",
        }
    }))
    before = catalog_file.read_bytes()
    monkeypatch.setattr(generated_images, "CDN_CATALOG_FILE", catalog_file)

    try:
        asyncio.run(generated_images.remove_cdn_catalog_entry(
            "orphan.png",
            generated_images.CdnCatalogEntryRemovalRequest(expected_image_id="old-image"),
        ))
    except generated_images.HTTPException as error:
        assert error.status_code == 409
    else:
        raise AssertionError("Expected changed-entry conflict")

    assert catalog_file.read_bytes() == before
