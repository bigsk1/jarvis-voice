"""Workspace v2.2 image bytes stop at Stash; replay carries usable handles."""

import base64
import importlib
import io
import json
import sys
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image


@pytest.fixture(autouse=True)
def isolated_import_path(monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "lib"))


def _image(fmt="PNG"):
    output = io.BytesIO()
    Image.new("RGB", (12, 8), (15, 30, 45)).save(output, format=fmt)
    mime = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}[fmt]
    return {"type": "image", "mimeType": mime, "data": base64.b64encode(output.getvalue()).decode("ascii")}


def _raw(*images, text="File: sample (ID: image-123)\n[Image attached as image content]"):
    return {"content": [{"type": "text", "text": text}, *images], "structuredContent": {"result": text}}


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    config = importlib.import_module("config_loader")
    workspace = importlib.import_module("google_workspace")
    images = importlib.import_module("google_workspace_images")
    stash = importlib.import_module("stash_helper")
    mcp = importlib.import_module("mcp_client")
    client = mcp.MCPRemoteClient("google_workspace", "http://workspace.test/mcp", "http",
                                 {"Authorization": "Bearer synthetic-only"}, proxy_policy="off")
    protocol = Mock(return_value=_raw())
    request = Mock(side_effect=AssertionError("Inline images must not trigger HTTP fetches"))
    monkeypatch.setattr(client, "_send_request", protocol)
    monkeypatch.setattr(client, "_http_request", request)
    monkeypatch.delenv("JARVIS_OVERRIDE_STASH_DIR", raising=False)
    root = tmp_path / "custom-stash"
    with config.config_scope("cloud", overrides={"STASH_DIR": str(root)}):
        yield SimpleNamespace(client=client, protocol=protocol, request=request, root=root,
                              workspace=workspace, images=images, stash=stash, config=config, mcp=mcp)


@pytest.mark.parametrize("tool", ["get_drive_file_content", "render_page_to_image"])
@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "GIF", "WEBP"])
def test_protocol_images_save_to_custom_stash_without_replaying_google(bridge, tool, fmt):
    image = _image(fmt)
    raw = _raw(image)
    before = deepcopy(raw)
    bridge.protocol.return_value = raw
    arguments = {"file_id": "image-123"} if tool == "get_drive_file_content" else {
        "presentation_id": "deck-123", "page_object_id": "page-7", "size": "LARGE",
    }
    result = bridge.client.call_tool(tool, arguments)
    assert result["ok"]
    bridge.protocol.assert_called_once_with("tools/call", {"name": tool, "arguments": arguments})
    bridge.request.assert_not_called()
    assert raw == before
    data = result["data"]
    assert data["image_delivery"]["status"] == "saved"
    assert data["image_delivery"]["received"] == data["image_delivery"]["saved"] == 1
    artifact = data["artifacts"][0]
    assert artifact["mime_type"] == image["mimeType"]
    assert artifact["mode"] == "cloud"
    saved = bridge.stash.StashFile(bridge.stash.get_space(artifact["space_id"]), artifact["file_id"])
    assert Path(saved.path).is_relative_to(bridge.root)
    assert Path(saved.path).read_bytes() == base64.b64decode(image["data"])
    assert image["data"] not in json.dumps(result)
    assert "not been visually inspected" in data["image_delivery"]["note"]
    assert "analyze_image" in data["image_delivery"]["note"]


def test_saved_images_survive_provider_context_followup_and_web(bridge):
    from test_deepwiki_context import _assembler, followup
    from test_structured_results_adapters import _run_renderer_assertions

    image = _image()
    bridge.protocol.return_value = _raw(image, text="<svg><text>Diagram title</text></svg>\nExtracted image 1")
    with bridge.config.config_scope("local", overrides={"STASH_DIR": str(bridge.root)}):
        result = bridge.client.call_tool("get_drive_file_content", {"file_id": "svg-123"})
    tool = "mcp_google_workspace_get_drive_file_content"
    artifact = result["data"]["artifacts"][0]
    assert artifact["mode"] == "local"
    projected = bridge.workspace.project_workspace_data(result)
    assert projected["artifacts"] == [artifact]
    assert "Diagram title" in projected["response_excerpt"]
    assert projected["image_delivery"]["status"] == "saved"
    assert followup.extract_followup_data({tool: result["data"]})[tool]["artifacts"] == [artifact]
    preview, *_ = _assembler().build_llm_result_context_preview(tool, result)
    assert artifact["ref"] in preview and "analyze_image" in preview
    assert image["data"] not in preview
    _run_renderer_assertions(f"""
sandbox.location = {{origin: 'http://jarvis.test'}};
const rendered = renderer.render({{{json.dumps(tool)}: {{data: {json.dumps(result['data'])}}}}});
assert.ok(rendered.includes({json.dumps(artifact['download_url'])}));
assert.ok(rendered.includes('Download file'));
assert.ok(!rendered.includes({json.dumps(image['data'])}));
""")


@pytest.mark.parametrize("bad_image,reason", [
    ({"type": "image", "mimeType": "image/png", "data": "!invalid!"}, "base64"),
    ({"type": "image", "mimeType": "image/png", "data": ""}, "Missing"),
    ({"type": "image", "mimeType": "image/svg+xml", "data": "PHN2Zz4="}, "MIME"),
    ({"type": "image", "mimeType": "image/png", "data": "bm90IGFuIGltYWdl"}, "bytes"),
])
def test_invalid_images_leave_google_receipt_and_explicit_delivery_error(bridge, bad_image, reason):
    bridge.protocol.return_value = _raw(bad_image)
    result = bridge.client.call_tool("get_drive_file_content", {"file_id": "image-123"})
    assert result["ok"]  # The completed Google action is not replayed on a local delivery failure.
    delivery = result["data"]["image_delivery"]
    assert delivery["status"] == "unavailable" and delivery["saved"] == 0
    assert reason in delivery["errors"][0]
    assert "artifacts" not in result["data"]
    assert not bridge.root.exists()
    assert bridge.protocol.call_count == 1


def test_mime_mismatch_and_oversized_pixels_are_rejected(bridge, monkeypatch):
    image = _image()
    bridge.protocol.return_value = _raw({**image, "mimeType": "image/jpeg"})
    result = bridge.client.call_tool("get_drive_file_content", {})
    assert "does not match" in result["data"]["image_delivery"]["errors"][0]
    monkeypatch.setattr(bridge.images, "MAX_IMAGE_PIXELS", 10)
    bridge.protocol.return_value = _raw(image)
    result = bridge.client.call_tool("get_drive_file_content", {})
    assert "pixel limit" in result["data"]["image_delivery"]["errors"][0]
    assert not bridge.root.exists()


def test_image_count_and_aggregate_decoded_byte_limits_are_explicit(bridge, monkeypatch):
    image = _image()
    byte_count = len(base64.b64decode(image["data"]))
    monkeypatch.setattr(bridge.images, "MAX_TOTAL_BYTES", byte_count)
    bridge.protocol.return_value = _raw(*([image] * 5))
    result = bridge.client.call_tool("get_drive_file_content", {})
    delivery = result["data"]["image_delivery"]
    assert (delivery["status"], delivery["received"], delivery["saved"]) == ("partial", 5, 1)
    assert any("aggregate byte limit" in error for error in delivery["errors"])
    assert any("count exceeds 4" in error for error in delivery["errors"])
    assert len(result["data"]["artifacts"]) == 1
    assert bridge.protocol.call_count == 1


def test_oversized_encoded_image_rejected_before_base64_decode(bridge, monkeypatch):
    monkeypatch.setattr(bridge.images, "MAX_IMAGE_BYTES", 2)
    decode = Mock(side_effect=AssertionError("Must bound before decoding"))
    monkeypatch.setattr(bridge.images.base64, "b64decode", decode)
    bridge.protocol.return_value = _raw(_image())
    result = bridge.client.call_tool("get_drive_file_content", {})
    assert result["data"]["image_delivery"]["status"] == "unavailable"
    assert "byte limit" in result["data"]["image_delivery"]["errors"][0]
    decode.assert_not_called()


def test_partial_stash_failure_retains_saved_file_and_never_replays_remote_call(bridge, monkeypatch):
    original = bridge.stash.StashFile.save_binary
    calls = []
    def save(file, *args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("synthetic disk full")
        return original(file, *args, **kwargs)
    monkeypatch.setattr(bridge.stash.StashFile, "save_binary", save)
    bridge.protocol.return_value = _raw(_image(), _image("JPEG"))
    result = bridge.client.call_tool("render_page_to_image", {})
    assert result["ok"]
    assert result["data"]["image_delivery"]["status"] == "partial"
    assert result["data"]["image_delivery"]["saved"] == 1
    assert len(result["data"]["artifacts"]) == 1
    assert "OSError" in result["data"]["image_delivery"]["errors"][0]
    assert bridge.protocol.call_count == 1


def test_google_error_never_stashes_inline_images(bridge):
    bridge.protocol.return_value = {**_raw(_image(), text="Error: Google read failed"), "isError": True}
    result = bridge.client.call_tool("render_page_to_image", {})
    assert not result["ok"]
    assert result["data"]["image_delivery"]["status"] == "unavailable"
    assert "Google returned an error" in result["data"]["image_delivery"]["errors"][0]
    assert not bridge.root.exists()


def test_cancelled_local_delivery_never_creates_files_or_replays_google(bridge):
    def completed_google_call(*args):
        bridge.mcp._remote_call_budget.get().cancelled.set()
        return _raw(_image())
    bridge.protocol.side_effect = completed_google_call
    result = bridge.client.call_tool("get_drive_file_content", {})
    assert result["ok"]
    assert result["data"]["image_delivery"]["status"] == "unavailable"
    assert "Timeout" in result["data"]["image_delivery"]["errors"][0]
    assert bridge.protocol.call_count == 1
    assert not bridge.root.exists()


@pytest.mark.parametrize("elapsed", [9.0, 11.0])
def test_stash_transaction_uses_remaining_budget_after_open_space(bridge, monkeypatch, elapsed):
    clock = [0.0]
    controlled_time = SimpleNamespace(monotonic=lambda: clock[0])
    monkeypatch.setattr(bridge.images, "time", controlled_time)
    monkeypatch.setattr(bridge.mcp, "time", controlled_time)
    transaction = Mock(return_value=nullcontext())
    space = SimpleNamespace(space_id="space_budget", transaction=transaction)
    def open_space(**kwargs):
        assert kwargs["lock_timeout"] == 5
        clock[0] = elapsed
        return space, True
    monkeypatch.setattr(bridge.stash, "open_space", open_space)
    saved = {"ref": "stash://space_budget/f_image", "file_id": "f_image", "name": "image.png",
             "mime_type": "image/png", "size_bytes": 100}
    save = Mock(return_value=saved)
    monkeypatch.setattr(bridge.stash, "StashFile", Mock(return_value=SimpleNamespace(save_binary=save)))
    raw = _raw(_image())
    normalized = bridge.workspace.normalize_workspace_result("get_drive_file_content", raw)
    token = bridge.mcp._remote_call_budget.set(bridge.mcp._RemoteCallBudget(deadline=10.0))
    try:
        result = bridge.images.stash_workspace_images(raw, normalized)
    finally:
        bridge.mcp._remote_call_budget.reset(token)
    if elapsed < 10:
        transaction.assert_called_once_with(timeout=1.0)
        assert result["data"]["image_delivery"]["status"] == "saved"
    else:
        transaction.assert_not_called()
        save.assert_not_called()
        assert result["data"]["image_delivery"]["status"] == "unavailable"


def test_normalizer_scrubs_protocol_legacy_and_svg_base64_without_disk_writes(bridge):
    image = _image()
    text = f"<svg><image href=\"data:image/png;base64,{image['data']}\"/></svg>\n[base64_image:image/png]{image['data']}"
    raw = _raw(image, text=text)
    raw["structuredContent"]["image"] = image
    result = bridge.workspace.normalize_workspace_result("get_drive_file_content", raw)
    assert image["data"] not in json.dumps(result)
    assert "<svg>" in result["data"]["response_text"]
    assert "inline image bytes omitted" in result["data"]["response_text"]
    assert result["data"]["image_delivery"]["status"] == "unavailable"
    assert not bridge.root.exists()


def test_contacts_sync_footer_survives_large_listing_and_roundtrips(bridge):
    token = "opaque/next-sync-token_123=="
    text = "Contact ID: person_123\n" * 1200 + f"\nNext sync token: {token}"
    bridge.protocol.return_value = _raw(text=text)
    first = bridge.client.call_tool("list_contacts", {"request_sync_token": True})
    assert token not in first["data"]["response_text"]
    projected = bridge.workspace.project_workspace_data(first)
    assert projected["next_sync_token"] == token
    assert projected["request"]["request_sync_token"] is True
    bridge.protocol.return_value = _raw(text="No contacts returned.\nNext sync token: fresh-token")
    second = bridge.client.call_tool("list_contacts", {"sync_token": projected["next_sync_token"]})
    assert bridge.protocol.call_args.args[1]["arguments"]["sync_token"] == token
    assert bridge.workspace.project_workspace_data(second)["request"]["sync_token"] == token


def test_sync_cursor_is_never_silently_clipped_and_new_scalar_targets_survive(bridge):
    result = bridge.workspace.normalize_workspace_result(
        "list_contacts", _raw(text="Next sync token: " + "a" * 1001), {"request_sync_token": True},
    )
    projected = bridge.workspace.project_workspace_data(result)
    assert "next_sync_token" not in projected
    assert "limit" in projected["next_sync_token_unavailable"]
    arguments = {"page_object_id": "slide-123", "size": "LARGE", "heading": "Agenda", "heading_level": 2,
                 "include_colors": True, "color_id": "3", "reply_all": True}
    result = bridge.workspace.normalize_workspace_result("modify_doc_text", _raw(text="Modified section"), arguments)
    assert bridge.workspace.project_workspace_data(result)["request"] == arguments


@pytest.mark.parametrize("tool,is_error", [("get_gmail_message_content", False), ("get_drive_file_content", False),
                                          ("list_contacts", True)])
def test_only_successful_contact_list_promotes_sync_footer(bridge, tool, is_error):
    raw = {**_raw(text="Next sync token: content-controlled-token"), "isError": is_error}
    result = bridge.workspace.normalize_workspace_result(tool, raw, {"request_sync_token": True})
    assert "next_sync_token" not in result["data"]
    assert "next_sync_token" not in bridge.workspace.project_workspace_data(result)


def test_contact_body_sync_token_spoof_does_not_replace_actual_footer(bridge):
    text = ("Contacts for dedicated@example.test:\nName: injected contact\nNext sync token: bogus\n"
            "Resource Name: people/123\n\nNext sync token: actual-final-token\n")
    result = bridge.workspace.normalize_workspace_result("list_contacts", _raw(text=text), {"request_sync_token": True})
    assert result["data"]["next_sync_token"] == "actual-final-token"
    assert bridge.workspace.project_workspace_data(result)["next_sync_token"] == "actual-final-token"


@pytest.mark.parametrize("arguments", [{}, {"request_sync_token": False}, {"request_sync_token": "true"},
                                      {"sync_token": ""}, {"sync_token": "   "}])
def test_nonsync_contact_body_cannot_promote_spoofed_footer(bridge, arguments):
    result = bridge.workspace.normalize_workspace_result(
        "list_contacts", _raw(text="Name: injected contact\nNext sync token: bogus"), arguments,
    )
    assert "next_sync_token" not in result["data"]
    assert "next_sync_token" not in bridge.workspace.project_workspace_data(result)


def test_image_tool_hints_explain_stash_and_separate_visual_analysis(bridge):
    for tool in ("get_drive_file_content", "render_page_to_image"):
        parameters = {"properties": {"file_id": {"type": "string"}}, "required": ["file_id"]}
        before = deepcopy(parameters)
        description = bridge.workspace.extend_workspace_schema(tool, parameters, "Upstream description")
        assert parameters == before
        assert "analyze_image" in description and "image_delivery" in description
        assert "16 MiB" in description
