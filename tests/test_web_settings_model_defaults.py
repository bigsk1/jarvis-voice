"""Regression coverage for provider-aware model defaults in Web settings."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_JS = (PROJECT_ROOT / "jarvis-web" / "client" / "js" / "app.js").read_text()


def test_provider_change_refreshes_static_provider_default():
    ensure_start = APP_JS.index("async _ensureProviderModelsLoaded(provider)")
    ensure_end = APP_JS.index("\n  _getCompletionGuardEvalProviderSelection", ensure_start)
    ensure_source = APP_JS[ensure_start:ensure_end]

    assert "provider !== 'ollama'" not in ensure_source
    assert "fetch(`/api/settings/models/${provider}" in ensure_source
    assert "provider_model_defaults[provider] = data.default_model" in ensure_source


def test_model_dropdown_prefers_refreshed_provider_default_with_fallback():
    populate_start = APP_JS.index("_populateProviderModelDropdown(selectId, provider)")
    populate_end = APP_JS.index("\n  _formatModelCapabilitySummary", populate_start)
    populate_source = APP_JS[populate_start:populate_end]

    assert "const defaultModel = endpointDefault || settingsDefault" in populate_source
