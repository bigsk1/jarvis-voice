"""Regression coverage for retrying Web vision after a text-only model failure."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
CHAT_JS = (PROJECT_ROOT / "jarvis-web" / "client" / "js" / "chat.js").read_text()


def test_chat_restores_analyze_attachment_after_typed_vision_failure():
    assert "this.pendingVisionRetryPayload = ['analyze', 'image', 'video'].includes(imagePayload?.action)" in CHAT_JS
    assert "'vision_model_unsupported', 'vision_analysis_failed'" in CHAT_JS
    assert "this.attachedImages = retryPayload.images.map" in CHAT_JS
    assert "clearAttachedImage({ preserveVisionRetry: true })" in CHAT_JS


def test_chat_restores_image_edit_attachment_after_stash_failure():
    assert "'image_edit_stash_failed'" in CHAT_JS
    assert "this.imageAttachmentAction = retryPayload.action" in CHAT_JS
    assert "this.imageAttachmentSettings = retryPayload.settings" in CHAT_JS


def test_chat_restores_image_video_attachment_after_stash_failure():
    assert "'image_video_stash_failed'" in CHAT_JS
    assert "data.error_code === 'image_video_stash_failed'" in CHAT_JS
