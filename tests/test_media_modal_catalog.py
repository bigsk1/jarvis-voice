"""Regression checks for catalog-driven media attachment options."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
CHAT_JS = (PROJECT_ROOT / "jarvis-web/client/js/chat.js").read_text()
CHAT_SOCKET = (PROJECT_ROOT / "jarvis-web/server/sockets/chat.py").read_text()
APP_JS = (PROJECT_ROOT / "jarvis-web/client/js/app.js").read_text()
INDEX_HTML = (PROJECT_ROOT / "jarvis-web/client/index.html").read_text()


def test_video_provider_change_refreshes_catalog_resolutions():
    assert "videoProviderSelect.addEventListener('change', () => this._updateVideoProviderOptions(true))" in CHAT_JS
    assert "Array.isArray(modelMetadata?.resolutions)" in CHAT_JS
    assert "this._updateVideoProviderOptions(true);" in CHAT_JS


def test_modal_model_change_clamps_catalog_dependent_controls():
    assert "document.getElementById('imgActionVideoResolution')?.addEventListener" in CHAT_JS
    assert "Array.isArray(modelMetadata?.aspect_ratios)" in CHAT_JS
    assert "const durationRules = modelMetadata?.duration_seconds" in CHAT_JS
    assert "durationRules.by_resolution?.[select?.value]" in CHAT_JS
    assert "Math.max(minimum, Math.min(maximum, requested))" in CHAT_JS
    assert "Array.isArray(modelMetadata?.resolutions)" in CHAT_JS
    assert "const imageSizes = catalogImageSizes.length" in CHAT_JS
    assert 'id="imgActionVideoDurationDesc"' in INDEX_HTML

    updater_start = CHAT_JS.index('_updateVideoProviderOptions(resetModel = false)')
    updater_end = CHAT_JS.index('_getEffectiveImageProvider()', updater_start)
    updater = CHAT_JS[updater_start:updater_end]
    assert updater.index('select.value = resolutions.includes(previous)') < updater.index(
        'const resolutionDurationValues'
    )


def test_video_reset_reclamps_duration_after_forcing_720p():
    reset_start = CHAT_JS.index('  _resetImageActionOptions() {')
    reset_end = CHAT_JS.index('_collectImageActionSettings()', reset_start)
    reset_code = CHAT_JS[reset_start:reset_end]
    force_resolution = reset_code.index("videoResolution.value = '720p'")
    restore_duration = reset_code.index("videoDuration.value = '5'", force_resolution)
    reclamp = reset_code.index('this._updateVideoProviderOptions();', restore_duration)
    assert force_resolution < restore_duration < reclamp


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
    assert "selectedCapabilities.includes('transparent_background')" in CHAT_JS
    assert "providerMetadata?.model || ''" in CHAT_JS
    assert "const isGptImage2 = /^gpt-image-2(?:$|-)/" in CHAT_JS
    assert "Selected model:" in CHAT_JS
    assert 'id="imgActionImageModelDesc"' in INDEX_HTML
    assert "this._settingsData = data.settings" in APP_JS


def test_image_and_video_models_are_selectable_in_settings_and_modal():
    for element_id in (
        'setting-image-model',
        'setting-video-model',
        'imgActionImageModel',
        'imgActionVideoModel',
    ):
        assert f'id="{element_id}"' in INDEX_HTML
    assert "_populateMediaModelDropdown('image')" in APP_JS
    assert "_populateMediaModelDropdown('video')" in APP_JS
    assert "image_model: document.getElementById('setting-image-model')" in APP_JS
    assert "video_model: document.getElementById('setting-video-model')" in APP_JS
    assert "settings.model = document.getElementById('imgActionImageModel')" in CHAT_JS
    assert "settings.model = document.getElementById('imgActionVideoModel')" in CHAT_JS


def test_modal_model_is_request_scoped_and_does_not_write_ai_config():
    assert "modal_model = modal_settings.get('model')" in CHAT_SOCKET
    assert "get_media_model_env_key('image', modal_provider)" in CHAT_SOCKET
    assert "get_media_model_env_key('video', modal_provider)" in CHAT_SOCKET
    collect_start = CHAT_JS.index('_collectImageActionSettings()')
    collect_end = CHAT_JS.index('_confirmImageAction() {', collect_start)
    request_only_code = CHAT_JS[collect_start:collect_end]
    assert "settings.model" in request_only_code
    assert "/api/settings" not in request_only_code
    assert "_saveSettings" not in request_only_code


def test_modal_model_is_explicitly_forced_into_both_media_tools():
    assert "tool_overrides['generate_video']['model'] = video_model" in CHAT_SOCKET
    assert "image_model = image_settings.get('model')" in CHAT_SOCKET
    assert "img_overrides['model'] = image_model" in CHAT_SOCKET


def test_image_action_choices_follow_analysis_image_video_progression():
    analyze = INDEX_HTML.index('name="imageAction" value="analyze"')
    image = INDEX_HTML.index('name="imageAction" value="image"')
    video = INDEX_HTML.index('name="imageAction" value="video"')

    assert analyze < image < video
