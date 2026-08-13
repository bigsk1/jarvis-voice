"""Regression checks for catalog-driven media attachment options."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
CHAT_JS = (PROJECT_ROOT / "jarvis-web/client/js/chat.js").read_text()
CHAT_SOCKET = (PROJECT_ROOT / "jarvis-web/server/sockets/chat.py").read_text()
APP_JS = (PROJECT_ROOT / "jarvis-web/client/js/app.js").read_text()
INDEX_HTML = (PROJECT_ROOT / "jarvis-web/client/index.html").read_text()


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


def test_settings_media_providers_show_catalog_capabilities_and_pricing():
    assert "_populateMediaProviderDropdown('image')" in APP_JS
    assert "_populateMediaProviderDropdown('video')" in APP_JS
    assert "_populateMediaProviderDropdown('music')" in APP_JS
    assert "_formatMediaProviderPrice(metadata.pricing)" in APP_JS
    assert 'id="image-provider-capabilities"' in INDEX_HTML
    assert 'id="video-provider-capabilities"' in INDEX_HTML
    assert 'id="music-provider-capabilities"' in INDEX_HTML
    assert "music_provider: document.getElementById('setting-music-provider')" in APP_JS


def test_settings_tts_provider_shows_effective_model_and_voice():
    assert "['image', 'video', 'music', 'tts']" in APP_JS
    assert "this._updateMediaProviderDetail('tts')" in APP_JS
    assert "if (voice) parts.push(`Voice: ${voice}`)" in APP_JS
    assert 'id="tts-provider-capabilities"' in INDEX_HTML


def test_system_features_show_music_env_provider():
    assert "<span class=\"config-label\">MUSIC_TOOL_PROVIDER</span>" in APP_JS


def test_image_modal_loads_and_displays_effective_model_capabilities():
    assert "await window.jarvisApp?._ensureSettingsData?." in CHAT_JS
    assert "openaiCapabilities.includes('transparent_background')" in CHAT_JS
    assert "Effective model:" in CHAT_JS
    assert 'id="imgActionImageModelDesc"' in INDEX_HTML
    assert "this._settingsData = data.settings" in APP_JS
