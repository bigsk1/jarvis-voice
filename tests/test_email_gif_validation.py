"""GIF validation preserves authenticated attachment bytes before email actions."""

# ruff: noqa: E402 - reuse the production lib bootstrap from the inbox fixtures.

import hashlib
import io
import json
from pathlib import Path

import pytest
import stash_helper
from PIL import Image
from test_email_inbox import SEND
from test_email_inbox import channel as channel
from test_email_inbox_attachments import AttachmentTools

from lib.email_inbox import ATTACHMENT, InboxStore


def _gif_bytes(frame_count=3):
    frames = [Image.new("RGB", (2, 2), (number % 256, number // 256, 0))
              for number in range(frame_count)]
    output = io.BytesIO()
    frames[0].save(
        output, "GIF", save_all=True, append_images=frames[1:],
        duration=[80 + number * 10 for number in range(frame_count)],
        loop=0, disposal=2, optimize=False,
    )
    return output.getvalue()


def _png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(output, "PNG")
    return output.getvalue()


@pytest.fixture(scope="module")
def animation():
    return _gif_bytes()


def _configure_inbox(channel, monkeypatch, tmp_path, files):
    inbox, _contacts = channel
    inbox.executor = AttachmentTools(
        files, monkeypatch, tmp_path, question="Please save the attached file to Stash.",
    )
    return inbox


def _finish_preparation(inbox):
    # Keep existing bounded attachment transport retry behavior. A validation
    # rejection may be reported immediately or after the ordinary retry budget.
    for _attempt in range(4):
        assert inbox.poll()["ok"]
        if inbox.store.rows()[0]["state"] == "completed":
            break


def _read_artifact(ref):
    resolved = stash_helper.safe_resolve_file(stash_ref=ref)
    assert resolved["found"]
    return Path(resolved["path"]).read_bytes()


def _artifact_metadata(ref):
    space_id, file_id = stash_helper.parse_stash_ref(ref)
    space = stash_helper.get_space(space_id)
    return next(item for item in space.meta["files"] if item["file_id"] == file_id)


def _download_attachment(inbox, ref):
    space_id, _file_id = stash_helper.parse_stash_ref(ref)
    return inbox.executor.execute(ATTACHMENT, {
        "message_id": "abc1", "attachment_id": "att_0", "attachment_index": 0,
        "return_base64": False, "stash": True, "stash_space_id": space_id,
    })


def _legacy_attachment(
    inbox, envelope, body, *, name="animation.gif", mime="image/gif", stored_name=None,
):
    """Model a pre-validation artifact without running today's save gate."""
    space_id = "space_email_" + hashlib.sha256(
        f"{inbox.account}:{envelope['message_id']}".encode(),
    ).hexdigest()[:24]
    space, _created = stash_helper.open_space(space_id=space_id)
    file_id = "f_abcdef123456"
    stored_name = name if stored_name is None else stored_name
    (space.space_path / stored_name).write_bytes(body)
    space.meta["files"].append({
        "file_id": file_id, "name": name, "stored_name": stored_name,
        "mime_type": mime, "size_bytes": len(body),
        "hash_sha256": hashlib.sha256(body).hexdigest(),
        "tags": ["google_workspace"], "tool_origin": "legacy_email_import",
        "created_at": "2026-11-01T00:00:00Z",
    })
    space._save_meta()
    ref = f"stash://{space_id}/{file_id}"
    envelope["attachments"] = [{
        "name": name, "mime_type": mime, "size_bytes": len(body),
        "inline": False, "stash_ref": ref,
    }]
    inbox.store.save_pending_envelope(envelope["message_id"], envelope)
    return ref


def test_authenticated_animated_gif_reaches_actions_without_altering_original(
    channel, monkeypatch, tmp_path, animation,
):
    inbox = _configure_inbox(
        channel, monkeypatch, tmp_path, [("animation.gif", "image/gif", animation)],
    )
    _finish_preparation(inbox)

    inbox.runner.assert_called_once()
    envelope = inbox.runner.call_args.args[1]
    attachment = envelope["attachments"][0]
    original_spec = envelope["attachment_specs"][0]
    saved = _read_artifact(attachment["stash_ref"])
    metadata = _artifact_metadata(attachment["stash_ref"])
    assert saved == animation
    assert metadata["gif_validation"]["policy_version"] == 1
    assert metadata["frame_count"] == 3
    assert metadata["mime_type"] == "image/gif"
    assert original_spec["sha256"] == hashlib.sha256(saved).hexdigest()
    assert original_spec["size_bytes"] == len(animation)
    with Image.open(io.BytesIO(saved)) as image:
        assert image.n_frames == 3
        assert image.info["loop"] == 0
        durations = []
        for index in range(image.n_frames):
            image.seek(index)
            durations.append(image.info["duration"])
        assert durations == [80, 90, 100]


@pytest.mark.parametrize(
    "body", [b"not a gif", _png_bytes(), b"GIF89a", _gif_bytes()[:40], _gif_bytes(257)],
    ids=["spoofed", "png-spoofed-as-gif", "header-only", "truncated", "too-many-frames"],
)
def test_authenticated_invalid_or_over_frame_limit_gif_runs_no_business_action(
    channel, monkeypatch, tmp_path, body,
):
    inbox = _configure_inbox(
        channel, monkeypatch, tmp_path, [("animation.gif", "image/gif", body)],
    )
    _finish_preparation(inbox)

    inbox.runner.assert_not_called()
    assert inbox.store.rows()[0]["request_ok"] == 0
    replies = [args for name, args in inbox.executor.calls if name == SEND]
    assert len(replies) == 1
    assert "No requested actions were run" in replies[0]["body"]
    assert not list(inbox.executor.stash.rglob("*.gif"))


def test_different_valid_gif_bytes_still_fail_authenticated_original_hash(
    channel, monkeypatch, tmp_path, animation,
):
    inbox = _configure_inbox(
        channel, monkeypatch, tmp_path, [("animation.gif", "image/gif", animation)],
    )
    replacement = bytearray(animation)
    replacement[13] ^= 1  # Change only a palette color; size and valid GIF structure remain.
    inbox.executor.wrong_bytes[0] = bytes(replacement)
    _finish_preparation(inbox)

    inbox.runner.assert_not_called()
    assert inbox.store.rows()[0]["request_ok"] == 0
    reply = next(args for name, args in inbox.executor.calls if name == SEND)
    assert "bytes do not match the authenticated email" in reply["body"]


@pytest.mark.parametrize(
    "body", [b"GIF89a", _gif_bytes(257)], ids=["header-only", "too-many-frames"],
)
def test_resumed_legacy_gif_is_checked_even_when_original_hash_matches(
    channel, monkeypatch, tmp_path, body,
):
    inbox = _configure_inbox(
        channel, monkeypatch, tmp_path, [("animation.gif", "image/gif", body)],
    )
    envelope = inbox.discover()[0]
    ref = _legacy_attachment(inbox, envelope, body)
    assert _read_artifact(ref) == body
    inbox.store = InboxStore(inbox.store.path)

    _finish_preparation(inbox)

    inbox.runner.assert_not_called()
    assert inbox.store.rows()[0]["request_ok"] == 0
    assert not any(
        name.endswith("get_gmail_attachment_content") for name, _args in inbox.executor.calls
    )


def test_resumed_legacy_attachment_still_rejects_original_hash_mismatch(
    channel, monkeypatch, tmp_path, animation,
):
    inbox = _configure_inbox(
        channel, monkeypatch, tmp_path, [("animation.gif", "image/gif", animation)],
    )
    envelope = inbox.discover()[0]
    modified = bytearray(animation)
    modified[13] ^= 1
    _legacy_attachment(inbox, envelope, bytes(modified))
    inbox.store = InboxStore(inbox.store.path)

    _finish_preparation(inbox)

    inbox.runner.assert_not_called()
    row = inbox.store.rows()[0]
    assert row["request_ok"] == 0
    reply = next(args for name, args in inbox.executor.calls if name == SEND)
    assert "bytes do not match the authenticated email" in reply["body"]


def test_failure_to_validate_a_legacy_gif_does_not_erase_its_authenticated_spec(
    channel, monkeypatch, tmp_path,
):
    body = b"GIF89a"
    inbox = _configure_inbox(
        channel, monkeypatch, tmp_path, [("animation.gif", "image/gif", body)],
    )
    envelope = inbox.discover()[0]
    _legacy_attachment(inbox, envelope, body)
    _finish_preparation(inbox)

    saved = json.loads(inbox.store.rows()[0]["envelope"])
    assert saved["attachment_specs"] == envelope["attachment_specs"]
    assert saved["attachment_specs"][0]["sha256"] == hashlib.sha256(body).hexdigest()
    inbox.runner.assert_not_called()


def test_resume_revalidates_and_upgrades_valid_legacy_gif_without_downloading_again(
    channel, monkeypatch, tmp_path, animation,
):
    inbox = _configure_inbox(
        channel, monkeypatch, tmp_path, [("animation.gif", "image/gif", animation)],
    )
    envelope = inbox.discover()[0]
    ref = _legacy_attachment(inbox, envelope, animation)
    assert "gif_validation" not in _artifact_metadata(ref)
    inbox.store = InboxStore(inbox.store.path)
    _finish_preparation(inbox)

    inbox.runner.assert_called_once()
    assert inbox.runner.call_args.args[1]["attachments"][0]["stash_ref"] == ref
    assert _read_artifact(ref) == animation
    metadata = _artifact_metadata(ref)
    assert metadata["gif_validation"]["policy_version"] == 1
    assert metadata["frame_count"] == 3
    assert metadata["hash_sha256"] == envelope["attachment_specs"][0]["sha256"]
    assert not any(name == ATTACHMENT for name, _args in inbox.executor.calls)


@pytest.mark.parametrize(
    "legacy_name,legacy_mime,incoming_name,incoming_mime",
    [
        ("animation.gif", "image/gif", "animation.gif", "image/gif"),
        ("attachment.bin", "application/octet-stream", "attachment.bin", "application/octet-stream"),
        ("attachment.bin", "application/octet-stream", "animation.gif", "image/gif"),
    ],
)
def test_workspace_duplicate_reuse_revalidates_and_persists_legacy_gif_metadata(
    channel, monkeypatch, tmp_path, animation, legacy_name, legacy_mime, incoming_name, incoming_mime,
):
    inbox = _configure_inbox(
        channel, monkeypatch, tmp_path, [(incoming_name, incoming_mime, animation)],
    )
    envelope = inbox.discover()[0]
    ref = _legacy_attachment(inbox, envelope, animation, name=legacy_name, mime=legacy_mime)
    assert "gif_validation" not in _artifact_metadata(ref)

    result = _download_attachment(inbox, ref)

    assert result["ok"]
    artifact = result["data"]["artifacts"][0]
    assert artifact["ref"] == ref
    assert artifact["gif_validation"]["policy_version"] == 1
    assert artifact["gif_validation"]["declared_mime_type"] == incoming_mime
    assert artifact["frame_count"] == 3
    metadata = _artifact_metadata(ref)
    assert metadata["gif_validation"]["policy_version"] == 1
    assert metadata["gif_validation"]["declared_mime_type"] == incoming_mime
    assert metadata["mime_type"] == "image/gif"
    assert _read_artifact(ref) == animation


@pytest.mark.parametrize("later_compatible_copy", [False, True], ids=["save-new", "reuse-later"])
@pytest.mark.parametrize(
    "legacy_name,legacy_mime,legacy_stored_name",
    [
        ("notes.png", "image/png", "notes.png"),
        ("notes.gif", "image/png", "notes.gif"),
        ("notes.png", "image/gif", "notes.gif"),
        ("notes.gif", "image/gif", "notes.png"),
    ],
    ids=["mime-and-name", "mime-only", "original-name-only", "stored-name-only"],
)
def test_workspace_same_hash_with_incompatible_legacy_declaration_does_not_block_valid_save(
    channel, monkeypatch, tmp_path, animation,
    legacy_name, legacy_mime, legacy_stored_name, later_compatible_copy,
):
    inbox = _configure_inbox(
        channel, monkeypatch, tmp_path, [("animation.gif", "image/gif", animation)],
    )
    envelope = inbox.discover()[0]
    legacy_ref = _legacy_attachment(
        inbox, envelope, animation,
        name=legacy_name, mime=legacy_mime, stored_name=legacy_stored_name,
    )
    original_metadata = _artifact_metadata(legacy_ref)
    space_id, _file_id = stash_helper.parse_stash_ref(legacy_ref)
    space = stash_helper.get_space(space_id)
    compatible = None
    if later_compatible_copy:
        compatible = stash_helper.StashFile(space).save_binary(
            animation, name="animation.gif", mime_type="image/gif",
        )

    result = _download_attachment(inbox, legacy_ref)

    assert result["ok"], result.get("error")
    artifact = result["data"]["artifacts"][0]
    assert artifact["ref"] != legacy_ref
    if compatible is not None:
        assert artifact["ref"] == compatible["ref"]
    assert artifact["name"] == "animation.gif"
    assert artifact["mime_type"] == "image/gif"
    assert artifact["gif_validation"]["policy_version"] == 1
    assert artifact["frame_count"] == 3
    assert _read_artifact(artifact["ref"]) == animation
    assert _artifact_metadata(artifact["ref"])["hash_sha256"] == hashlib.sha256(animation).hexdigest()
    assert len(stash_helper.get_space(space_id).meta["files"]) == 2
    assert _artifact_metadata(legacy_ref) == original_metadata
    assert _read_artifact(legacy_ref) == animation


@pytest.mark.parametrize("corruption", ["malformed", "different-valid-gif"])
def test_workspace_duplicate_reuse_checks_actual_bytes_despite_matching_saved_hash(
    channel, monkeypatch, tmp_path, animation, corruption,
):
    inbox = _configure_inbox(
        channel, monkeypatch, tmp_path, [("animation.gif", "image/gif", animation)],
    )
    envelope = inbox.discover()[0]
    ref = _legacy_attachment(inbox, envelope, animation)
    resolved = stash_helper.safe_resolve_file(stash_ref=ref)
    corrupt = bytearray(animation)
    if corruption == "malformed":
        corrupt = b"GIF89a"
    else:
        corrupt[13] ^= 1
    Path(resolved["path"]).write_bytes(corrupt)
    assert _artifact_metadata(ref)["hash_sha256"] == hashlib.sha256(animation).hexdigest()

    result = _download_attachment(inbox, ref)

    assert result["ok"] is False
    assert result["data"]["download_ok"] is True
    assert not result["data"].get("artifacts")
    assert "Stash save failed" in result["error"]
    space_id, _file_id = stash_helper.parse_stash_ref(ref)
    assert len(stash_helper.get_space(space_id).meta["files"]) == 1
    assert _read_artifact(ref) == bytes(corrupt)


@pytest.mark.parametrize(
    "name,mime", [("animation.gif", "image/jpeg"), ("animation.png", "image/gif")],
)
def test_authenticated_gif_with_conflicting_extension_or_mime_runs_no_business_action(
    channel, monkeypatch, tmp_path, animation, name, mime,
):
    inbox = _configure_inbox(channel, monkeypatch, tmp_path, [(name, mime, animation)])
    _finish_preparation(inbox)

    inbox.runner.assert_not_called()
    assert inbox.store.rows()[0]["request_ok"] == 0
    reply = next(args for tool_name, args in inbox.executor.calls if tool_name == SEND)
    assert "No requested actions were run" in reply["body"]
    assert not list(inbox.executor.stash.rglob(name))


def test_neutral_email_mime_does_not_hide_actual_gif_or_change_authenticated_spec(
    channel, monkeypatch, tmp_path, animation,
):
    inbox = _configure_inbox(
        channel, monkeypatch, tmp_path, [("attachment.bin", "application/octet-stream", animation)],
    )
    _finish_preparation(inbox)

    inbox.runner.assert_called_once()
    envelope = inbox.runner.call_args.args[1]
    ref = envelope["attachments"][0]["stash_ref"]
    assert envelope["attachment_specs"][0]["mime_type"] == "application/octet-stream"
    assert envelope["attachment_specs"][0]["sha256"] == hashlib.sha256(animation).hexdigest()
    metadata = _artifact_metadata(ref)
    assert metadata["mime_type"] == "image/gif"
    assert metadata["gif_validation"]["policy_version"] == 1
    assert metadata["gif_validation"]["declared_mime_type"] == "application/octet-stream"
    assert metadata["frame_count"] == 3
    assert _read_artifact(ref) == animation


def test_workspace_fresh_neutral_download_retains_original_mime_declaration(
    channel, monkeypatch, tmp_path, animation,
):
    inbox = _configure_inbox(
        channel, monkeypatch, tmp_path, [("attachment.bin", "application/octet-stream", animation)],
    )
    space, _created = stash_helper.open_space()

    result = _download_attachment(inbox, f"stash://{space.space_id}/f_unused")

    assert result["ok"]
    artifact = result["data"]["artifacts"][0]
    assert artifact["mime_type"] == "image/gif"
    assert artifact["gif_validation"]["declared_mime_type"] == "application/octet-stream"
    metadata = _artifact_metadata(artifact["ref"])
    assert metadata["mime_type"] == "image/gif"
    assert metadata["gif_validation"]["declared_mime_type"] == "application/octet-stream"
    assert metadata["gif_validation"]["declared_filename"] == "attachment.bin"
    assert _read_artifact(artifact["ref"]) == animation
