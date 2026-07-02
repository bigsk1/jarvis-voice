"""Regression checks for catalog-driven media attachment options."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
CHAT_JS = (PROJECT_ROOT / "jarvis-web/client/js/chat.js").read_text()
CHAT_SOCKET = (PROJECT_ROOT / "jarvis-web/server/sockets/chat.py").read_text()


def test_video_provider_change_refreshes_catalog_resolutions():
    assert "videoProviderSelect.addEventListener('change', () => this._updateVideoProviderOptions())" in CHAT_JS
    assert "._settingsData?.video_providers?.[provider]?.resolutions" in CHAT_JS
    assert "this._updateVideoProviderOptions();" in CHAT_JS


def test_video_resolution_labels_include_gemini_high_res_options():
    assert "1080p (Full HD)" in CHAT_JS
    assert "4K (Ultra HD)" in CHAT_JS


def test_image_to_video_preserves_exact_user_prompt_without_vision_guessing():
    assert "user_video_prompt = message.strip()" in CHAT_SOCKET
    assert "'prompt': user_video_prompt" in CHAT_SOCKET
    assert "Do not expand it or invent subjects, identities, counts, or scene details." in CHAT_SOCKET


def test_enhance_sends_pending_image_and_active_mode_for_multimodal_context():
    assert "image_action: imagePayload?.action || null" in CHAT_JS
    assert "image: imagePayload?.images?.[0] || null" in CHAT_JS
    assert "mode: activeMode" in CHAT_JS
