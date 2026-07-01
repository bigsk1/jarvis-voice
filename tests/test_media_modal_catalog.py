"""Regression checks for catalog-driven media attachment options."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
CHAT_JS = (PROJECT_ROOT / "jarvis-web/client/js/chat.js").read_text()


def test_video_provider_change_refreshes_catalog_resolutions():
    assert "videoProviderSelect.addEventListener('change', () => this._updateVideoProviderOptions())" in CHAT_JS
    assert "._settingsData?.video_providers?.[provider]?.resolutions" in CHAT_JS
    assert "this._updateVideoProviderOptions();" in CHAT_JS


def test_video_resolution_labels_include_gemini_high_res_options():
    assert "1080p (Full HD)" in CHAT_JS
    assert "4K (Ultra HD)" in CHAT_JS
