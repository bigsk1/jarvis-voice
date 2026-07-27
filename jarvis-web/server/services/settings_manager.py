"""
Settings Manager Service
Handles safe reading/writing of Jarvis settings with web overrides
"""
from concurrent.futures import ThreadPoolExecutor, wait
import threading
import time
from typing import Any
from ..config import (
    save_web_config, load_web_config,
    get_jarvis_setting, load_jarvis_config,
    DEFAULT_JARVIS_QA_WORD_LIMIT, DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT,
)
from model_catalog import (
    get_catalog_providers,
    get_default_model_id,
    get_model_context_label,
    get_model_metadata,
    get_media_catalog_providers,
    get_media_model_env_key,
    get_media_provider_options,
    get_provider_catalog,
    get_provider_model_options,
)
from ollama_utils import request_ollama, is_ollama_cloud_model
from router_prompt_catalog import (
    DEFAULT_ROUTER_PROMPT_VERSION,
    available_router_prompt_versions,
    normalize_router_prompt_version,
    router_prompt_version_options,
)
from xai_oauth import (
    XaiOAuthError,
    discover_xai_oauth_models,
    get_xai_auth_mode,
    get_xai_oauth_model,
    get_xai_oauth_status,
    is_xai_oauth_model,
    xai_oauth_model_supports_vision,
)


_OLLAMA_MODEL_METADATA_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_OLLAMA_MODEL_METADATA_CACHE_LOCK = threading.Lock()
_OLLAMA_MODEL_METADATA_TTL_SECONDS = 600
_OLLAMA_MODEL_METADATA_FAILURE_TTL_SECONDS = 30
_OLLAMA_MODEL_METADATA_BATCH_TIMEOUT_SECONDS = 5


def _compact_count(value: Any) -> str | None:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    if count <= 0:
        return None
    if count >= 1_000_000_000:
        return f"{count / 1_000_000_000:.0f}B"
    if count >= 1_000_000:
        millions = count / 1_000_000
        return f"{millions:.2f}".rstrip("0").rstrip(".") + "M"
    if count >= 1_000:
        return f"{count // 1_000}K"
    return str(count)


def _parse_ollama_show_metadata(payload: Any) -> dict[str, Any]:
    """Extract only metadata Ollama explicitly reports for model selection."""
    if not isinstance(payload, dict):
        return {}
    result: dict[str, Any] = {}
    raw_capabilities = payload.get("capabilities")
    if isinstance(raw_capabilities, list):
        declared = list(dict.fromkeys(
            str(value).strip().lower() for value in raw_capabilities if str(value).strip()
        ))
        result["vision"] = "vision" in declared
        result["capabilities"] = [
            value for value in declared if value in {"vision", "tools", "thinking"}
        ]

    model_info = payload.get("model_info")
    if isinstance(model_info, dict):
        for key, value in model_info.items():
            if isinstance(key, str) and key.endswith("context_length"):
                label = _compact_count(value)
                if label:
                    result["context"] = label
                    break

    details = payload.get("details")
    if isinstance(details, dict):
        raw_size = details.get("parameter_size")
        if isinstance(raw_size, str) and raw_size.strip():
            parameter_size = raw_size.strip().upper()
            result["parameter_size"] = (
                _compact_count(parameter_size) if parameter_size.isdigit() else parameter_size
            )
        elif raw_size is not None:
            result["parameter_size"] = _compact_count(raw_size)
    return {key: value for key, value in result.items() if value is not None}


def _fetch_ollama_model_metadata(
    model: str,
    *,
    base_url: str | None,
    direct_cloud_api: bool,
) -> dict[str, Any]:
    cache_key = (("direct" if direct_cloud_api else (base_url or "")), model)
    now = time.monotonic()
    with _OLLAMA_MODEL_METADATA_CACHE_LOCK:
        cached = _OLLAMA_MODEL_METADATA_CACHE.get(cache_key)
    if cached:
        ttl = (
            _OLLAMA_MODEL_METADATA_TTL_SECONDS
            if cached[1]
            else _OLLAMA_MODEL_METADATA_FAILURE_TTL_SECONDS
        )
        if now - cached[0] < ttl:
            return dict(cached[1])
    try:
        response, _ = request_ollama(
            "post",
            "/api/show",
            base_url=None if direct_cloud_api else base_url,
            json={"model": model, "verbose": False},
            timeout=(3, 6),
            cloud_access=direct_cloud_api,
        )
        metadata = _parse_ollama_show_metadata(response.json()) if response.status_code == 200 else {}
    except Exception:
        metadata = {}
    with _OLLAMA_MODEL_METADATA_CACHE_LOCK:
        _OLLAMA_MODEL_METADATA_CACHE[cache_key] = (now, metadata)
    return metadata


def _enrich_ollama_models(
    models: list[dict[str, Any]],
    *,
    base_url: str | None,
    direct_cloud_api: bool,
) -> None:
    """Best-effort capability enrichment without serially blocking the modal."""
    if not models:
        return
    workers = min(12, len(models))
    pool = ThreadPoolExecutor(max_workers=workers)
    futures = {
        pool.submit(
            _fetch_ollama_model_metadata,
            model["id"],
            base_url=base_url,
            direct_cloud_api=direct_cloud_api,
        ): model
        for model in models
        if model.get("id")
    }
    done, pending = wait(
        futures,
        timeout=_OLLAMA_MODEL_METADATA_BATCH_TIMEOUT_SECONDS,
    )
    for future in done:
        metadata = future.result()
        if metadata:
            futures[future].update(metadata)
    for future in pending:
        future.cancel()
    pool.shutdown(wait=False, cancel_futures=True)

    if direct_cloud_api:
        # Direct ollama.com discovery returns canonical IDs, while an older
        # env/UI selection may still pin the equivalent ``:cloud`` alias.
        # Reuse the canonical card metadata so the selected default is useful.
        by_id = {model.get("id"): model for model in models}
        for model in models:
            model_id = str(model.get("id") or "")
            if not model_id.endswith(":cloud"):
                continue
            canonical = by_id.get(model_id[:-6])
            if not canonical:
                continue
            for key in ("context", "parameter_size", "capabilities", "vision"):
                if key in canonical:
                    model[key] = canonical[key]


def fetch_ollama_models(
    base_url: str = None,
    mode: str = None,
    selected_models: list[str] | None = None,
) -> list:
    """Fetch available models from Ollama server, filtered by mode when useful."""
    mode = (mode or 'cloud').strip().lower()
    direct_cloud_api = mode == 'cloud' and bool(
        (get_jarvis_setting('OLLAMA_API_KEY', '') or '').strip()
    )
    allow_local_cloud = mode == 'local' and str(
        get_jarvis_setting('ALLOW_OLLAMA_CLOUD', 'false') or ''
    ).strip().lower() in {'true', '1', 'yes', 'on'}
    try:
        response, used_base_url = request_ollama(
            "get",
            "/api/tags",
            # Direct cloud discovery must not be pinned back to the daemon URL.
            base_url=None if direct_cloud_api else base_url,
            timeout=5,
            cloud_access=(mode == "cloud"),
        )
        base_url = used_base_url
        if response.status_code == 200:
            data = response.json()
            raw_models = data.get('models', [])
            if direct_cloud_api:
                # ollama.com does not promise a useful response order. Its
                # modified_at values track catalog releases well enough to
                # present a stable newest-first list without maintaining one.
                raw_models = sorted(
                    raw_models,
                    key=lambda item: item.get('modified_at') or '',
                    reverse=True,
                )
            models = []
            for model in raw_models:
                name = model.get('name', '')
                is_cloud_model = direct_cloud_api or is_ollama_cloud_model(name)
                # Get size info if available
                size_gb = model.get('size', 0) / (1024**3)
                size_str = f"{size_gb:.1f}GB" if size_gb > 0 else ''
                models.append({
                    'id': name,
                    'name': name,
                    'context': ('cloud' if is_cloud_model else (size_str or 'local')),
                    '_is_cloud': is_cloud_model,
                })

            if mode == 'cloud' and not direct_cloud_api:
                models = [m for m in models if m.get('_is_cloud')]
            elif mode == 'local' and not allow_local_cloud:
                models = [m for m in models if not m.get('_is_cloud')]

            for model in models:
                model.pop('_is_cloud', None)
            configured_model = (
                (get_jarvis_setting('OLLAMA_CLOUD_MODEL', '') or '').strip()
                if mode == 'cloud'
                else (get_jarvis_setting('OLLAMA_MODEL', '') or '').strip()
            )
            selected = [str(value).strip() for value in (selected_models or []) if str(value).strip()]
            pinned_ids = list(dict.fromkeys([*selected, configured_model] if configured_model else selected))
            by_id = {model.get('id'): model for model in models}
            pinned = []
            for model_id in pinned_ids:
                model = by_id.pop(model_id, None) or {
                    'id': model_id,
                    'name': model_id,
                    'context': 'cloud' if (direct_cloud_api or is_ollama_cloud_model(model_id)) else 'local',
                }
                labels = []
                if model_id == configured_model:
                    labels.append('env default')
                display_name = f"{model_id} ({', '.join(labels)})" if labels else model_id
                model = {**model, 'name': display_name}
                pinned.append(model)
            result = [*pinned, *by_id.values()]
            _enrich_ollama_models(
                result,
                base_url=base_url,
                direct_cloud_api=direct_cloud_api,
            )
            return result
    except Exception as e:
        print(f"[Settings] Failed to fetch Ollama models: {e}")
    
    # Fallback to default from config. Cloud mode must surface the configured
    # cloud model (OLLAMA_CLOUD_MODEL) even when discovery is unavailable.
    if mode == 'cloud':
        default_model = (
            get_jarvis_setting('OLLAMA_CLOUD_MODEL', '').strip()
            or get_jarvis_setting('OLLAMA_MODEL', '').strip()
            or 'qwen3.5:cloud'
        )
    else:
        default_model = get_jarvis_setting('OLLAMA_MODEL', 'qwen3')
    fallback_context = 'cloud' if (direct_cloud_api or is_ollama_cloud_model(default_model)) else 'local'
    return [{'id': default_model, 'name': f'{default_model} (default)', 'context': fallback_context}]

TTS_PROVIDERS = {
    'kokoro': {'name': 'Kokoro', 'description': 'Fast, local Kokoro TTS server'},
    'openai': {'name': 'OpenAI', 'description': 'OpenAI TTS API ($15/1M chars)'},
    'elevenlabs': {'name': 'ElevenLabs', 'description': 'ElevenLabs TTS API (best quality, paid)'},
    'xai': {'name': 'xAI', 'description': 'xAI TTS API (uses XAI_API_KEY)'},
    'qwen3-tts': {'name': 'Qwen3-TTS', 'description': 'Local network Qwen3-TTS server (free, 28 cloned voices)'},
}

CLOUD_TTS_PROVIDER_OPTIONS = ['openai', 'elevenlabs', 'xai', 'qwen3-tts']
LOCAL_TTS_PROVIDER_OPTIONS = ['kokoro', 'qwen3-tts']

RESPONSE_STYLE_OPTIONS = {
    'casual': {'name': 'Casual', 'description': 'Short voice-friendly output'},
    'auto': {'name': 'Auto', 'description': 'Adaptive formatting based on tool/result type'},
    'detailed': {'name': 'Detailed', 'description': 'Keep full verbose responses'}
}

COMPLETION_GUARD_MODE_OPTIONS = {
    'off': {'name': 'Off', 'description': 'Disable completion prompts'},
    'manual': {'name': 'Manual', 'description': 'Ask whether the response completed correctly'},
    'auto': {'name': 'Auto', 'description': 'Evaluate the final raw answer and auto-repair when confidence is low'}
}

# Provider -> required API key env var (presence checked, value never exposed).
# Providers absent from this map are either always available (local engines)
# or handled specially (ollama: live sign-in check in cloud mode).
PROVIDER_KEY_REQUIREMENTS = {
    'openai': 'OPENAI_API_KEY',
    'anthropic': 'ANTHROPIC_API_KEY',
    'xai': 'XAI_API_KEY',
    'gemini': 'GEMINI_API_KEY',
    'elevenlabs': 'ELEVENLABS_API_KEY',
}

# Short UI labels for credential availability. Native select option text does
# not wrap consistently (especially on mobile), so keep these deliberately
# compact instead of exposing env filenames or long setup instructions there.
PROVIDER_DISPLAY_NAMES = {
    'openai': 'OpenAI',
    'anthropic': 'Anthropic',
    'xai': 'xAI',
    'gemini': 'Gemini',
    'elevenlabs': 'ElevenLabs',
}


class SettingsValidationError(ValueError):
    """A web settings save was rejected before any mutation occurred."""

    def __init__(self, field: str, provider: str, reason: str):
        super().__init__(reason)
        self.field = field
        self.provider = provider
        self.reason = reason

    def to_dict(self) -> dict[str, str]:
        return {'field': self.field, 'provider': self.provider, 'reason': self.reason}


class SettingsManager:
    """Manages settings for the web UI with override support"""

    _FLOAT_OVERRIDE_EPSILON = 1e-6
    
    # Settings safe to expose to the UI (no API keys)
    SAFE_JARVIS_SETTINGS = [
        'MODE',
        'OWNER_NAME',
        'LLM_PROVIDER',
        'XAI_AUTH_MODE',
        'XAI_OAUTH_MODEL',
        'OLLAMA_CLOUD_MODEL',
        'ALLOW_OLLAMA_CLOUD',
        'TTS_PROVIDER',
        'IMAGE_TOOL_PROVIDER',
        'VIDEO_TOOL_PROVIDER',
        'MUSIC_TOOL_PROVIDER',
        'TOOL_SIMILARITY_THRESHOLD',
        'TOOL_SIMILARITY_THRESHOLD_FULL',
        'SEMANTIC_SIMILARITY_THRESHOLD',
        'INTELLIGENCE_ENABLED',
        'INTELLIGENCE_MIN_CONFIDENCE',
    ]
    
    # Patterns that indicate sensitive values (never expose)
    SENSITIVE_PATTERNS = ['API_KEY', 'SECRET', 'TOKEN', 'PASSWORD', 'PRIVATE']
    
    def __init__(self, mode: str = 'cloud'):
        self.mode = mode

    def _ensure_jarvis_config(self):
        """Resolve Jarvis config for this operation's request/startup scope."""
        load_jarvis_config(self.mode)

    @staticmethod
    def _floats_equal(left: float, right: float) -> bool:
        return abs(float(left) - float(right)) < SettingsManager._FLOAT_OVERRIDE_EPSILON

    @classmethod
    def _is_web_int_override(cls, web_value, env_default) -> bool:
        if web_value is None:
            return False
        return int(web_value) != int(env_default)

    @classmethod
    def _is_web_float_override(cls, web_value, env_default) -> bool:
        if web_value is None:
            return False
        return not cls._floats_equal(web_value, env_default)

    @classmethod
    def _normalize_web_int_override(cls, value, env_default):
        if value in (None, ''):
            return None
        parsed = int(value)
        if parsed == int(env_default):
            return None
        return parsed

    @classmethod
    def _normalize_web_float_override(cls, value, env_default):
        if value in (None, ''):
            return None
        parsed = float(value)
        if cls._floats_equal(parsed, env_default):
            return None
        return parsed

    def _get_env_numeric_defaults(self) -> dict[str, int | float]:
        tool_rag_key = 'LOCAL_TOOL_RAG_LIMIT' if self.mode == 'local' else 'CLOUD_TOOL_RAG_LIMIT'
        tool_rag_default = '6' if self.mode == 'local' else '15'
        return {
            'tool_rag_limit': int(get_jarvis_setting(tool_rag_key, tool_rag_default)),
            'qa_word_limit': int(
                get_jarvis_setting('JARVIS_QA_WORD_LIMIT', str(DEFAULT_JARVIS_QA_WORD_LIMIT))
            ),
            'multi_turn_word_limit': int(
                get_jarvis_setting('JARVIS_MULTI_TURN_WORD_LIMIT', str(DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT))
            ),
            'completion_guard_auto_threshold': float(
                get_jarvis_setting('JARVIS_COMPLETION_GUARD_AUTO_THRESHOLD', '0.70')
            ),
        }

    def _get_model_options_with_current(self, provider: str, current_model: str | None) -> list[dict[str, Any]]:
        """Return curated provider options plus any active custom model."""
        if provider == 'xai' and self._xai_uses_oauth():
            try:
                return discover_xai_oauth_models()
            except XaiOAuthError:
                model = self._xai_oauth_model()
                vision = xai_oauth_model_supports_vision(model)
                capabilities = ['tools', 'thinking']
                if vision:
                    capabilities.append('vision')
                return [{
                    'id': model,
                    'name': model,
                    'context': get_model_context_label('xai', model) or 'OAuth subscription',
                    'auth': 'oauth',
                    'capabilities': capabilities,
                    'vision': vision,
                }]

        options = get_provider_model_options(provider)
        if not current_model:
            return options

        if any(option.get('id') == current_model for option in options):
            return options

        metadata = get_model_metadata(provider, current_model)
        if metadata:
            canonical_id = metadata['id']
            return [
                {
                    **option,
                    'id': current_model,
                    'name': f"{option['name']} (configured alias)",
                }
                if option.get('id') == canonical_id
                else option
                for option in options
            ]

        context = get_model_context_label(provider, current_model) or 'custom'
        return [
            {'id': current_model, 'name': f'{current_model} (custom)', 'context': context},
            *options,
        ]

    @staticmethod
    def _get_effective_media_providers(media_type: str) -> dict[str, dict[str, Any]]:
        """Resolve mode-loaded optional media model pins into UI capabilities."""
        configured_models = {}
        for provider in get_media_catalog_providers(media_type):
            env_key = get_media_model_env_key(media_type, provider)
            configured_models[provider] = get_jarvis_setting(env_key, '') if env_key else ''
        return get_media_provider_options(media_type, configured_models)

    def _get_llm_provider_options(self) -> list[str]:
        """Return provider choices that make sense for the current mode."""
        if self.mode == 'local':
            return ['ollama']
        options = get_catalog_providers()
        return options if 'ollama' in options else [*options, 'ollama']

    def _get_tts_provider_options(self, current_provider: str | None = None) -> list[str]:
        """Return mode-specific TTS provider choices, preserving any active custom value."""
        options = LOCAL_TTS_PROVIDER_OPTIONS if self.mode == 'local' else CLOUD_TTS_PROVIDER_OPTIONS
        if current_provider and current_provider not in options:
            return [current_provider, *options]
        return options

    def _model_is_compatible_with_provider(self, provider: str, model: str | None) -> bool:
        """Reject a model override that clearly belongs to another provider/mode."""
        if provider == 'xai' and self._xai_uses_oauth():
            return not model or is_xai_oauth_model(model)
        if not model or provider != 'ollama':
            return True

        normalized = model.strip().lower()
        for catalog_provider in get_catalog_providers():
            for entry in get_provider_catalog(catalog_provider):
                known_ids = [entry.get('id'), *(entry.get('aliases') or [])]
                if normalized in {str(value).lower() for value in known_ids if value}:
                    return False

        cloud_tagged = is_ollama_cloud_model(model)
        if self.mode == 'cloud':
            # Direct ollama.com IDs are canonical names without a required
            # :cloud suffix. Signed-in-daemon cloud cards remain tagged.
            return bool((get_jarvis_setting('OLLAMA_API_KEY', '') or '').strip()) or cloud_tagged
        allow_local_cloud = str(
            get_jarvis_setting('ALLOW_OLLAMA_CLOUD', 'false') or ''
        ).strip().lower() in {'true', '1', 'yes', 'on'}
        return not cloud_tagged or allow_local_cloud

    def _xai_uses_oauth(self) -> bool:
        """Whether primary xAI text calls resolve to the Grok CLI OAuth path."""
        try:
            return get_xai_auth_mode(
                get_jarvis_setting('XAI_API_KEY', ''),
                get_jarvis_setting('XAI_AUTH_MODE', 'auto'),
            ) == 'oauth'
        except XaiOAuthError:
            return False

    def _xai_oauth_model(self) -> str:
        """Resolve the mode-scoped Grok CLI OAuth chat model."""
        return get_xai_oauth_model(get_jarvis_setting('XAI_OAUTH_MODEL', ''))
    
    def _is_sensitive(self, key: str) -> bool:
        """Check if a setting key is sensitive"""
        return any(pattern in key.upper() for pattern in self.SENSITIVE_PATTERNS)
    
    def get_effective_value(self, setting: str, default: Any = None) -> Any:
        """Get the effective value: web override > cloud.env default"""
        web_config = load_web_config()
        
        # Map settings to web_config paths
        override_map = {
            'LLM_PROVIDER': ('llm', 'provider'),
            'LLM_MODEL': ('llm', 'model'),
            'IMAGE_TOOL_PROVIDER': ('image', 'provider'),
            'VIDEO_TOOL_PROVIDER': ('video', 'provider'),
            'MUSIC_TOOL_PROVIDER': ('music', 'provider'),
            'TTS_PROVIDER': ('tts', 'provider'),
            'JARVIS_RESPONSE_STYLE': ('response', 'style'),
            'JARVIS_QA_WORD_LIMIT': ('response', 'qa_word_limit'),
            'JARVIS_MULTI_TURN_WORD_LIMIT': ('response', 'multi_turn_word_limit'),
            'CLOUD_TOOL_RAG_LIMIT': ('tool_rag', 'limit'),
            'LOCAL_TOOL_RAG_LIMIT': ('tool_rag', 'limit'),
            'JARVIS_COMPLETION_GUARD_EVAL_PROVIDER': ('completion_guard', 'eval_provider'),
            'JARVIS_COMPLETION_GUARD_EVAL_MODEL': ('completion_guard', 'eval_model'),
            'TOOL_SIMILARITY_THRESHOLD': ('thresholds', 'tool_similarity'),
            'SEMANTIC_SIMILARITY_THRESHOLD': ('thresholds', 'memory_similarity'),
        }
        
        if setting in override_map:
            section, key = override_map[setting]
            override = web_config.get(section, {}).get(key)
            if override is not None:
                return override
        
        # Fall back to cloud.env
        self._ensure_jarvis_config()
        return get_jarvis_setting(setting, default)
    
    def get_settings_for_ui(self) -> dict[str, Any]:
        """Get all settings formatted for the UI"""
        self._ensure_jarvis_config()
        web_config = load_web_config()
        
        # Get env defaults for current mode
        env_provider = get_jarvis_setting('LLM_PROVIDER', 'xai' if self.mode == 'cloud' else 'ollama')
        env_router_prompt_version = normalize_router_prompt_version(
            get_jarvis_setting('JARVIS_ROUTER_PROMPT_VERSION', DEFAULT_ROUTER_PROMPT_VERSION)
        )
        env_image_provider = get_jarvis_setting('IMAGE_TOOL_PROVIDER', 'gemini')
        env_video_provider = get_jarvis_setting('VIDEO_TOOL_PROVIDER', 'xai')
        env_music_provider = get_jarvis_setting('MUSIC_TOOL_PROVIDER', 'elevenlabs')
        env_tts_provider = get_jarvis_setting('TTS_PROVIDER', 'qwen3-tts' if self.mode == 'local' else 'elevenlabs')
        env_response_style = get_jarvis_setting('JARVIS_RESPONSE_STYLE', 'auto')
        env_tool_rag_key = 'LOCAL_TOOL_RAG_LIMIT' if self.mode == 'local' else 'CLOUD_TOOL_RAG_LIMIT'
        env_tool_rag_default = '6' if self.mode == 'local' else '15'
        env_tool_rag_limit = int(get_jarvis_setting(env_tool_rag_key, env_tool_rag_default))
        env_qa_word_limit = int(get_jarvis_setting('JARVIS_QA_WORD_LIMIT', str(DEFAULT_JARVIS_QA_WORD_LIMIT)))
        env_multi_turn_word_limit = int(get_jarvis_setting('JARVIS_MULTI_TURN_WORD_LIMIT', str(DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT)))
        env_completion_guard_enabled = get_jarvis_setting('JARVIS_COMPLETION_GUARD_ENABLED', 'false').lower() == 'true'
        env_completion_guard_mode = get_jarvis_setting('JARVIS_COMPLETION_GUARD_MODE', 'manual')
        env_completion_guard_ticket_on_fail = get_jarvis_setting('JARVIS_COMPLETION_GUARD_TICKET_ON_FAIL', 'true').lower() == 'true'
        env_completion_guard_show_ui_prompt = get_jarvis_setting('JARVIS_COMPLETION_GUARD_SHOW_UI_PROMPT', 'true').lower() == 'true'
        env_completion_guard_include_qa = get_jarvis_setting('JARVIS_COMPLETION_GUARD_INCLUDE_QA', 'true').lower() == 'true'
        env_completion_guard_include_tool_tasks = get_jarvis_setting('JARVIS_COMPLETION_GUARD_INCLUDE_TOOL_TASKS', 'true').lower() == 'true'
        env_completion_guard_auto_threshold = float(get_jarvis_setting('JARVIS_COMPLETION_GUARD_AUTO_THRESHOLD', '0.70'))
        env_completion_guard_eval_provider = get_jarvis_setting('JARVIS_COMPLETION_GUARD_EVAL_PROVIDER', 'ollama' if self.mode == 'local' else 'openai')
        env_completion_guard_eval_model = get_jarvis_setting(
            'JARVIS_COMPLETION_GUARD_EVAL_MODEL',
            (
                self._ollama_env_default_model()
                if env_completion_guard_eval_provider == 'ollama'
                else get_default_model_id(env_completion_guard_eval_provider)
            )
        )
        
        # Get per-mode web overrides (null = use env default)
        mode_overrides = web_config.get(self.mode, {})
        llm_provider_options = self._get_llm_provider_options()
        image_providers = self._get_effective_media_providers('image')
        video_providers = self._get_effective_media_providers('video')
        music_providers = self._get_effective_media_providers('music')
        web_provider = mode_overrides.get('llm_provider')
        provider_invalid = False
        if web_provider not in (None, *llm_provider_options):
            web_provider = None
            provider_invalid = True
        web_model = mode_overrides.get('llm_model')
        if provider_invalid:
            web_model = None
        web_router_prompt_version = mode_overrides.get('router_prompt_version')
        if web_router_prompt_version not in (None, *available_router_prompt_versions()):
            web_router_prompt_version = None
        web_image = mode_overrides.get('image_provider')
        web_video = mode_overrides.get('video_provider')
        web_music = mode_overrides.get('music_provider')
        web_tts = mode_overrides.get('tts_provider')
        tts_provider_options = self._get_tts_provider_options(env_tts_provider)
        if web_tts not in (None, *tts_provider_options):
            web_tts = None
        web_response_style = mode_overrides.get('response_style')
        web_tool_rag_limit = mode_overrides.get('tool_rag_limit')
        web_qa_word_limit = mode_overrides.get('qa_word_limit')
        web_multi_turn_word_limit = mode_overrides.get('multi_turn_word_limit')
        web_completion_guard_enabled = mode_overrides.get('completion_guard_enabled')
        web_completion_guard_mode = mode_overrides.get('completion_guard_mode')
        web_completion_guard_ticket_on_fail = mode_overrides.get('completion_guard_ticket_on_fail')
        web_completion_guard_show_ui_prompt = mode_overrides.get('completion_guard_show_ui_prompt')
        web_completion_guard_include_qa = mode_overrides.get('completion_guard_include_qa')
        web_completion_guard_include_tool_tasks = mode_overrides.get('completion_guard_include_tool_tasks')
        web_completion_guard_auto_threshold = mode_overrides.get('completion_guard_auto_threshold')
        web_completion_guard_eval_provider = mode_overrides.get('completion_guard_eval_provider')
        web_completion_guard_eval_model = mode_overrides.get('completion_guard_eval_model')
        
        # Calculate effective values
        effective_provider = web_provider or env_provider
        if not self._model_is_compatible_with_provider(effective_provider, web_model):
            web_model = None
        effective_model = web_model or self._get_env_provider_model(effective_provider)
        effective_router_prompt_version = web_router_prompt_version or env_router_prompt_version
        effective_image = web_image or env_image_provider
        effective_video = web_video or env_video_provider
        effective_music = web_music or env_music_provider
        effective_tts = web_tts or env_tts_provider
        effective_response_style = web_response_style or env_response_style
        effective_tool_rag_limit = (
            web_tool_rag_limit if web_tool_rag_limit is not None else env_tool_rag_limit
        )
        effective_qa_word_limit = web_qa_word_limit if web_qa_word_limit is not None else env_qa_word_limit
        effective_multi_turn_word_limit = (
            web_multi_turn_word_limit if web_multi_turn_word_limit is not None else env_multi_turn_word_limit
        )
        effective_completion_guard_enabled = (
            web_completion_guard_enabled
            if web_completion_guard_enabled is not None
            else env_completion_guard_enabled
        )
        effective_completion_guard_mode = web_completion_guard_mode or env_completion_guard_mode
        effective_completion_guard_ticket_on_fail = (
            web_completion_guard_ticket_on_fail
            if web_completion_guard_ticket_on_fail is not None
            else env_completion_guard_ticket_on_fail
        )
        effective_completion_guard_show_ui_prompt = (
            web_completion_guard_show_ui_prompt
            if web_completion_guard_show_ui_prompt is not None
            else env_completion_guard_show_ui_prompt
        )
        effective_completion_guard_include_qa = (
            web_completion_guard_include_qa
            if web_completion_guard_include_qa is not None
            else env_completion_guard_include_qa
        )
        effective_completion_guard_include_tool_tasks = (
            web_completion_guard_include_tool_tasks
            if web_completion_guard_include_tool_tasks is not None
            else env_completion_guard_include_tool_tasks
        )
        effective_completion_guard_auto_threshold = (
            web_completion_guard_auto_threshold
            if web_completion_guard_auto_threshold is not None
            else env_completion_guard_auto_threshold
        )
        effective_completion_guard_eval_provider = web_completion_guard_eval_provider or env_completion_guard_eval_provider
        if not self._model_is_compatible_with_provider(
            effective_completion_guard_eval_provider,
            web_completion_guard_eval_model,
        ):
            web_completion_guard_eval_model = None
        effective_completion_guard_eval_default = (
            env_completion_guard_eval_model
            if effective_completion_guard_eval_provider == env_completion_guard_eval_provider
            else self._get_env_provider_model(effective_completion_guard_eval_provider)
        )
        effective_completion_guard_eval_model = (
            web_completion_guard_eval_model
            or effective_completion_guard_eval_default
        )
        
        _full_raw = get_jarvis_setting('TOOL_SIMILARITY_THRESHOLD_FULL', '').strip()
        try:
            env_tool_similarity_full = float(_full_raw) if _full_raw else None
        except ValueError:
            env_tool_similarity_full = None
        
        return {
            'mode': self.mode,
            
            # LLM Settings
            'llm': {
                'provider': {
                    'value': effective_provider,
                    'default': env_provider,
                    'is_override': web_provider is not None,
                    'options': llm_provider_options
                },
                'model': {
                    'value': effective_model,
                    'default': self._get_env_provider_model(effective_provider),
                    'is_override': web_model is not None,
                    'options': self._get_model_options_with_current(effective_provider, effective_model)
                }
            },

            'router_prompt': {
                'version': {
                    'value': effective_router_prompt_version,
                    'default': env_router_prompt_version,
                    'is_override': web_router_prompt_version is not None,
                    'options': router_prompt_version_options(),
                }
            },

            'tool_rag': {
                'limit': {
                    'value': effective_tool_rag_limit,
                    'default': env_tool_rag_limit,
                    'is_override': self._is_web_int_override(web_tool_rag_limit, env_tool_rag_limit),
                }
            },
            
            # Image Settings
            'image': {
                'provider': {
                    'value': effective_image,
                    'default': env_image_provider,
                    'is_override': web_image is not None,
                    'options': list(image_providers.keys())
                }
            },
            
            # Video Settings
            'video': {
                'provider': {
                    'value': effective_video,
                    'default': env_video_provider,
                    'is_override': web_video is not None,
                    'options': list(video_providers.keys())
                }
            },

            # Music Settings
            'music': {
                'provider': {
                    'value': effective_music,
                    'default': env_music_provider,
                    'is_override': web_music is not None,
                    'options': list(music_providers.keys())
                }
            },

            # TTS Settings
            'tts': {
                'provider': {
                    'value': effective_tts,
                    'default': env_tts_provider,
                    'is_override': web_tts is not None,
                    'options': self._get_tts_provider_options(effective_tts)
                }
            },

            # Response formatting settings
            'response': {
                'style': {
                    'value': effective_response_style,
                    'default': env_response_style,
                    'is_override': web_response_style is not None,
                    'options': list(RESPONSE_STYLE_OPTIONS.keys())
                },
                'qa_word_limit': {
                    'value': effective_qa_word_limit,
                    'default': env_qa_word_limit,
                    'is_override': self._is_web_int_override(web_qa_word_limit, env_qa_word_limit),
                },
                'multi_turn_word_limit': {
                    'value': effective_multi_turn_word_limit,
                    'default': env_multi_turn_word_limit,
                    'is_override': self._is_web_int_override(
                        web_multi_turn_word_limit,
                        env_multi_turn_word_limit,
                    ),
                }
            },

            'completion_guard': {
                'enabled': {
                    'value': effective_completion_guard_enabled,
                    'default': env_completion_guard_enabled,
                    'is_override': web_completion_guard_enabled is not None
                },
                'mode': {
                    'value': effective_completion_guard_mode,
                    'default': env_completion_guard_mode,
                    'is_override': web_completion_guard_mode is not None,
                    'options': list(COMPLETION_GUARD_MODE_OPTIONS.keys())
                },
                'ticket_on_fail': {
                    'value': effective_completion_guard_ticket_on_fail,
                    'default': env_completion_guard_ticket_on_fail,
                    'is_override': web_completion_guard_ticket_on_fail is not None
                },
                'show_ui_prompt': {
                    'value': effective_completion_guard_show_ui_prompt,
                    'default': env_completion_guard_show_ui_prompt,
                    'is_override': web_completion_guard_show_ui_prompt is not None
                },
                'include_qa': {
                    'value': effective_completion_guard_include_qa,
                    'default': env_completion_guard_include_qa,
                    'is_override': web_completion_guard_include_qa is not None
                },
                'include_tool_tasks': {
                    'value': effective_completion_guard_include_tool_tasks,
                    'default': env_completion_guard_include_tool_tasks,
                    'is_override': web_completion_guard_include_tool_tasks is not None
                },
                'auto_threshold': {
                    'value': effective_completion_guard_auto_threshold,
                    'default': env_completion_guard_auto_threshold,
                    'is_override': self._is_web_float_override(
                        web_completion_guard_auto_threshold,
                        env_completion_guard_auto_threshold,
                    ),
                },
                'eval_provider': {
                    'value': effective_completion_guard_eval_provider,
                    'default': env_completion_guard_eval_provider,
                    'is_override': web_completion_guard_eval_provider is not None,
                    'options': ['ollama'] if self.mode == 'local' else get_catalog_providers()
                },
                'eval_model': {
                    'value': effective_completion_guard_eval_model,
                    'default': effective_completion_guard_eval_default,
                    'is_override': web_completion_guard_eval_model is not None,
                    'options': self._get_model_options_with_current(
                        effective_completion_guard_eval_provider,
                        effective_completion_guard_eval_model,
                    )
                }
            },
            
            # Thresholds (read-only from env)
            'thresholds': {
                'tool_similarity': float(get_jarvis_setting('TOOL_SIMILARITY_THRESHOLD', '0.0')),
                'tool_similarity_full': env_tool_similarity_full,
                'memory_similarity': float(get_jarvis_setting('SEMANTIC_SIMILARITY_THRESHOLD', '0.30'))
            },
            
            # Audio (web-only)
            'audio': web_config.get('audio', {}),
            
            # UI settings (web-only)
            'ui': {
                'progress_events': web_config.get('ui', {}).get('progress_events', True)
            },
            
            # Conversation settings (web-only)
            'conversation': {
                'history_limit': web_config.get('conversation', {}).get('history_limit', 20)
            },
            
            # API Key status
            'api_keys': self._get_api_key_status(),

            # Per-domain provider availability (status/reason only, no values)
            'provider_availability': self.get_provider_availability(),
            
            # Other Jarvis settings
            'owner_name': get_jarvis_setting('OWNER_NAME', 'Boss'),
            'tts_provider': effective_tts,
            
            # Available models reference (with dynamic Ollama)
            'provider_models': self._get_provider_models(),
            'image_providers': image_providers,
            'video_providers': video_providers,
            'music_providers': music_providers,
            'tts_providers': TTS_PROVIDERS,
            'response_style_options': RESPONSE_STYLE_OPTIONS,
            
            # Blocked tools
            'blocked_tools': web_config.get('tools', {}).get('blocked', [])
        }
    
    def _get_provider_models(self) -> dict:
        """Get provider models with dynamic Ollama fetching"""
        models = {
            provider: get_provider_model_options(provider)
            for provider in get_catalog_providers()
        }
        if self._xai_uses_oauth():
            try:
                models['xai'] = discover_xai_oauth_models()
            except XaiOAuthError:
                model = self._xai_oauth_model()
                vision = xai_oauth_model_supports_vision(model)
                capabilities = ['tools', 'thinking']
                if vision:
                    capabilities.append('vision')
                models['xai'] = [{
                    'id': model,
                    'name': model,
                    'context': get_model_context_label('xai', model) or 'OAuth subscription',
                    'auth': 'oauth',
                    'capabilities': capabilities,
                    'vision': vision,
                }]
        
        # Dynamically fetch Ollama models if in local mode or Ollama selected
        web_config = load_web_config()
        mode_overrides = web_config.get(self.mode, {}) if isinstance(web_config, dict) else {}
        ollama_needed = (
            self.mode == 'local'
            # First boot: cloud env LLM_PROVIDER=ollama with no saved web override
            # must still discover cloud models and select OLLAMA_CLOUD_MODEL.
            or get_jarvis_setting('LLM_PROVIDER', '') == 'ollama'
            or mode_overrides.get('llm_provider') == 'ollama'
            or mode_overrides.get('completion_guard_eval_provider') == 'ollama'
            or get_jarvis_setting('JARVIS_COMPLETION_GUARD_EVAL_PROVIDER', 'openai') == 'ollama'
        )
        if ollama_needed:
            ollama_url = get_jarvis_setting('OLLAMA_BASE_URL', 'http://localhost:11434')
            selected_models = []
            effective_llm_provider = (
                mode_overrides.get('llm_provider')
                or get_jarvis_setting('LLM_PROVIDER', 'ollama' if self.mode == 'local' else 'xai')
            )
            if effective_llm_provider == 'ollama' and mode_overrides.get('llm_model'):
                selected_models.append(mode_overrides['llm_model'])
            effective_guard_provider = (
                mode_overrides.get('completion_guard_eval_provider')
                or get_jarvis_setting(
                    'JARVIS_COMPLETION_GUARD_EVAL_PROVIDER',
                    'ollama' if self.mode == 'local' else 'openai',
                )
            )
            if effective_guard_provider == 'ollama' and mode_overrides.get('completion_guard_eval_model'):
                selected_models.append(mode_overrides['completion_guard_eval_model'])
            models['ollama'] = fetch_ollama_models(
                ollama_url,
                mode=self.mode,
                selected_models=selected_models,
            )
        else:
            # Fallback when Ollama is not the active provider.
            default_model = self._ollama_env_default_model()
            direct_cloud_api = self.mode == 'cloud' and bool(
                (get_jarvis_setting('OLLAMA_API_KEY', '') or '').strip()
            )
            context = 'cloud' if (direct_cloud_api or is_ollama_cloud_model(default_model)) else 'local'
            models['ollama'] = [{'id': default_model, 'name': f'{default_model}', 'context': context}]
        
        return models

    def _ollama_env_default_model(self) -> str:
        """Resolve the env default Ollama model for this mode (cloud-aware).

        Cloud mode prefers OLLAMA_CLOUD_MODEL (or a cloud-tagged legacy
        OLLAMA_MODEL); local mode uses OLLAMA_MODEL.
        """
        if self.mode == 'cloud':
            cloud = (get_jarvis_setting('OLLAMA_CLOUD_MODEL', '') or '').strip()
            if cloud:
                return cloud
            legacy = (get_jarvis_setting('OLLAMA_MODEL', '') or '').strip()
            if legacy and is_ollama_cloud_model(legacy):
                return legacy
            return 'qwen3.5:cloud'
        return (get_jarvis_setting('OLLAMA_MODEL', '') or '').strip() or 'qwen3'
    
    def _get_default_model(self, provider: str) -> str:
        """Get the default model for a provider"""
        if provider == 'ollama':
            # Mode-aware: cloud uses OLLAMA_CLOUD_MODEL, local uses OLLAMA_MODEL.
            return self._ollama_env_default_model()
        if provider == 'xai' and self._xai_uses_oauth():
            return self._xai_oauth_model()

        return get_default_model_id(provider)

    def _get_env_provider_model(self, provider: str) -> str:
        """Get the configured model from env for a provider, or fall back to the provider default."""
        if provider == 'ollama':
            # Mode-aware Ollama default (OLLAMA_CLOUD_MODEL in cloud).
            return self._ollama_env_default_model()
        if provider == 'xai' and self._xai_uses_oauth():
            return self._xai_oauth_model()
        env_key_map = {
            'xai': 'XAI_MODEL',
            'anthropic': 'ANTHROPIC_MODEL',
            'openai': 'OPENAI_MODEL',
        }
        env_key = env_key_map.get(provider)
        if env_key:
            value = get_jarvis_setting(env_key, '').strip()
            if value:
                return value
        return self._get_default_model(provider)
    
    def _get_api_key_status(self) -> dict[str, bool]:
        """Check which API keys are configured"""
        self._ensure_jarvis_config()
        keys = ['OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'XAI_API_KEY', 'OLLAMA_API_KEY',
                'GEMINI_API_KEY', 'ELEVENLABS_API_KEY', 'VAPI_API_KEY',
                'COINGECKO_API_KEY', 'OPENWEATHER_API_KEY', 'CLOUDFLARE_API_TOKEN']
        return {
            key: bool(str(get_jarvis_setting(key, '') or '').strip())
            for key in keys
        }

    def _provider_availability_entry(
        self,
        provider: str,
        domain: str | None = None,
    ) -> dict[str, Any]:
        """Availability status for one provider (booleans/reasons only, never values)."""
        provider = (provider or '').strip().lower()
        if provider == 'ollama':
            if self.mode == 'local':
                return {'status': 'available', 'reason': None}
            if get_jarvis_setting('OLLAMA_API_KEY', '').strip():
                return {
                    'status': 'available',
                    'reason': 'OLLAMA_API_KEY configured (direct ollama.com API)',
                }
            # Daemon sign-in is checked live via /api/ollama/cloud-status.
            return {
                'status': 'unknown',
                'reason': 'Depends on Ollama daemon sign-in (checked live)',
            }
        if provider == 'xai' and domain in {'llm', 'completion_guard'}:
            api_key = get_jarvis_setting('XAI_API_KEY', '')
            try:
                auth_mode = get_xai_auth_mode(
                    api_key,
                    get_jarvis_setting('XAI_AUTH_MODE', 'auto'),
                )
            except XaiOAuthError as exc:
                return {'status': 'unavailable', 'reason': str(exc)}
            if auth_mode == 'oauth':
                status = get_xai_oauth_status()
                return {
                    'status': status['status'],
                    'reason': status.get('reason') or 'Grok CLI OAuth subscription',
                    'connection': 'oauth',
                }
            if str(api_key or '').strip():
                return {
                    'status': 'available',
                    'reason': 'XAI_API_KEY configured',
                    'connection': 'api_key',
                }
        required_key = PROVIDER_KEY_REQUIREMENTS.get(provider)
        if required_key is None:
            # Local engines (kokoro, qwen3-tts) and unrecognized providers:
            # no static credential requirement to enforce here.
            return {'status': 'available', 'reason': None}
        value = get_jarvis_setting(required_key, '')
        if value is not None and str(value).strip():
            return {'status': 'available', 'reason': None}
        display_name = PROVIDER_DISPLAY_NAMES.get(provider, provider.title())
        return {
            'status': 'unavailable',
            'reason': f'{display_name} API key missing',
        }

    def get_provider_availability(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Per-domain provider availability for the UI (no secret values)."""
        self._ensure_jarvis_config()
        llm_options = self._get_llm_provider_options()
        guard_options = ['ollama'] if self.mode == 'local' else get_catalog_providers()
        image_options = list(get_media_catalog_providers('image'))
        video_options = list(get_media_catalog_providers('video'))
        music_options = list(get_media_catalog_providers('music'))
        tts_options = self._get_tts_provider_options()
        return {
            'llm': {p: self._provider_availability_entry(p, 'llm') for p in llm_options},
            'image': {p: self._provider_availability_entry(p, 'image') for p in image_options},
            'video': {p: self._provider_availability_entry(p, 'video') for p in video_options},
            'music': {p: self._provider_availability_entry(p, 'music') for p in music_options},
            'tts': {p: self._provider_availability_entry(p, 'tts') for p in tts_options},
            'completion_guard': {
                p: self._provider_availability_entry(p, 'completion_guard')
                for p in guard_options
            },
        }

    def _validate_provider_overrides(self, overrides: dict[str, Any]) -> None:
        """Reject NEWLY selected unavailable providers before any mutation.

        A provider that is already the effective value (env default or a
        previously saved override) does not block saving unrelated settings;
        only a change TO an unavailable provider is rejected. Raises
        SettingsValidationError; performs no writes.
        """
        config = load_web_config()
        mode_config = config.get(self.mode, {})

        current_effective = {
            'llm_provider': (
                mode_config.get('llm_provider')
                or get_jarvis_setting('LLM_PROVIDER', 'xai' if self.mode == 'cloud' else 'ollama')
            ),
            'image_provider': mode_config.get('image_provider') or get_jarvis_setting('IMAGE_TOOL_PROVIDER', 'gemini'),
            'video_provider': mode_config.get('video_provider') or get_jarvis_setting('VIDEO_TOOL_PROVIDER', 'xai'),
            'music_provider': mode_config.get('music_provider') or get_jarvis_setting('MUSIC_TOOL_PROVIDER', 'elevenlabs'),
            'tts_provider': (
                mode_config.get('tts_provider')
                or get_jarvis_setting('TTS_PROVIDER', 'qwen3-tts' if self.mode == 'local' else 'elevenlabs')
            ),
            'completion_guard_eval_provider': (
                mode_config.get('completion_guard_eval_provider')
                or get_jarvis_setting(
                    'JARVIS_COMPLETION_GUARD_EVAL_PROVIDER',
                    'ollama' if self.mode == 'local' else 'openai',
                )
            ),
        }

        for field in (
            'llm_provider', 'image_provider', 'video_provider', 'music_provider',
            'tts_provider', 'completion_guard_eval_provider',
        ):
            if field not in overrides:
                continue
            requested = overrides[field]
            if not requested:
                continue  # clearing an override is always allowed
            requested = str(requested).strip().lower()
            effective = str(current_effective[field] or '').strip().lower()
            if requested == effective:
                continue  # not a new selection
            domain = {
                'llm_provider': 'llm',
                'image_provider': 'image',
                'video_provider': 'video',
                'music_provider': 'music',
                'tts_provider': 'tts',
                'completion_guard_eval_provider': 'completion_guard',
            }[field]
            entry = self._provider_availability_entry(requested, domain)
            if entry['status'] == 'unavailable':
                raise SettingsValidationError(
                    field=field,
                    provider=requested,
                    reason=entry['reason'] or f"Provider '{requested}' is not configured",
                )
    
    def get_settings_with_status(self) -> dict[str, dict]:
        """Return settings with configured status (for backward compat)"""
        self._ensure_jarvis_config()
        
        settings = {}
        
        # Safe settings with values
        for key in self.SAFE_JARVIS_SETTINGS:
            settings[key] = {
                'value': get_jarvis_setting(key, ''),
                'sensitive': False,
                'configured': True
            }
        
        # Add status for common API keys (don't show value)
        api_keys = [
            'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'XAI_API_KEY', 'OLLAMA_API_KEY',
            'GEMINI_API_KEY', 'ELEVENLABS_API_KEY', 'VAPI_API_KEY',
            'COINGECKO_API_KEY', 'OPENWEATHER_API_KEY', 'CLOUDFLARE_API_TOKEN',
        ]
        for key in api_keys:
            value = str(get_jarvis_setting(key, '') or '').strip()
            settings[key] = {
                'value': '***configured***' if value else '',
                'sensitive': True,
                'configured': bool(value)
            }
        
        return settings
    
    def get_web_settings(self) -> dict:
        """Return web UI specific settings"""
        return load_web_config()
    
    def validate_web_overrides(self, overrides: dict[str, Any]) -> None:
        """Validate a settings payload without mutating anything.

        Raises SettingsValidationError when the payload newly selects a
        provider whose credentials are not configured. Used by the route to
        validate BEFORE persisting anything (including a mode change), so a
        rejected request leaves web_config.json completely untouched.
        """
        self._ensure_jarvis_config()
        self._validate_provider_overrides(overrides)
        if 'router_prompt_version' in overrides and overrides['router_prompt_version'] not in (
            None,
            '',
            *available_router_prompt_versions(),
        ):
            requested = str(overrides['router_prompt_version'])
            raise SettingsValidationError(
                field='router_prompt_version',
                provider=requested,
                reason=(
                    f"Unknown router prompt version '{requested}'. Available versions: "
                    f"{', '.join(available_router_prompt_versions())}"
                ),
            )
        if 'tool_rag_limit' in overrides and overrides['tool_rag_limit'] not in (None, ''):
            try:
                tool_rag_limit = int(overrides['tool_rag_limit'])
            except (TypeError, ValueError):
                tool_rag_limit = 0
            if tool_rag_limit < 1 or tool_rag_limit > 50:
                raise SettingsValidationError(
                    field='tool_rag_limit',
                    provider=str(overrides['tool_rag_limit']),
                    reason='Tool RAG limit must be between 1 and 50',
                )

    def save_web_overrides(self, overrides: dict[str, Any]) -> bool:
        """Save per-mode Web UI overrides.

        Raises SettingsValidationError (mapped to HTTP 400 by the route)
        BEFORE any mutation when the request newly selects a provider whose
        credentials are not configured. Unrelated settings remain saveable
        even when an existing env-default provider lacks credentials.
        """
        self.validate_web_overrides(overrides)
        config = load_web_config()
        
        # Ensure mode section exists
        if self.mode not in config:
            config[self.mode] = {}
        mode_config = config[self.mode]
        
        # Handle LLM overrides (per-mode)
        if 'llm_provider' in overrides:
            value = overrides['llm_provider'] or None
            if self.mode == 'local' and value not in (None, 'ollama'):
                value = 'ollama'
            mode_config['llm_provider'] = value
        
        if 'llm_model' in overrides:
            value = overrides['llm_model'] or None
            effective_provider = (
                mode_config.get('llm_provider')
                or get_jarvis_setting('LLM_PROVIDER', 'xai' if self.mode == 'cloud' else 'ollama')
            )
            if not self._model_is_compatible_with_provider(effective_provider, value):
                value = None
            mode_config['llm_model'] = value

        if 'router_prompt_version' in overrides:
            value = overrides['router_prompt_version'] or None
            mode_config['router_prompt_version'] = value
        
        # Handle image overrides (per-mode)
        if 'image_provider' in overrides:
            mode_config['image_provider'] = overrides['image_provider'] or None
        
        # Handle video overrides (per-mode)
        if 'video_provider' in overrides:
            mode_config['video_provider'] = overrides['video_provider'] or None

        # Handle music overrides (per-mode)
        if 'music_provider' in overrides:
            mode_config['music_provider'] = overrides['music_provider'] or None

        # Handle TTS overrides (per-mode)
        if 'tts_provider' in overrides:
            value = overrides['tts_provider'] or None
            if value not in (None, *self._get_tts_provider_options()):
                value = None
            mode_config['tts_provider'] = value

        if 'response_style' in overrides:
            mode_config['response_style'] = overrides['response_style'] or None

        env_numeric_defaults = self._get_env_numeric_defaults()

        if 'tool_rag_limit' in overrides:
            mode_config['tool_rag_limit'] = self._normalize_web_int_override(
                overrides['tool_rag_limit'],
                env_numeric_defaults['tool_rag_limit'],
            )

        if 'qa_word_limit' in overrides:
            mode_config['qa_word_limit'] = self._normalize_web_int_override(
                overrides['qa_word_limit'],
                env_numeric_defaults['qa_word_limit'],
            )

        if 'multi_turn_word_limit' in overrides:
            mode_config['multi_turn_word_limit'] = self._normalize_web_int_override(
                overrides['multi_turn_word_limit'],
                env_numeric_defaults['multi_turn_word_limit'],
            )

        if 'completion_guard_enabled' in overrides:
            value = overrides['completion_guard_enabled']
            mode_config['completion_guard_enabled'] = bool(value) if value is not None else None

        if 'completion_guard_mode' in overrides:
            mode_config['completion_guard_mode'] = overrides['completion_guard_mode'] or None

        if 'completion_guard_ticket_on_fail' in overrides:
            value = overrides['completion_guard_ticket_on_fail']
            mode_config['completion_guard_ticket_on_fail'] = bool(value) if value is not None else None

        if 'completion_guard_show_ui_prompt' in overrides:
            value = overrides['completion_guard_show_ui_prompt']
            mode_config['completion_guard_show_ui_prompt'] = bool(value) if value is not None else None

        if 'completion_guard_include_qa' in overrides:
            value = overrides['completion_guard_include_qa']
            mode_config['completion_guard_include_qa'] = bool(value) if value is not None else None

        if 'completion_guard_include_tool_tasks' in overrides:
            value = overrides['completion_guard_include_tool_tasks']
            mode_config['completion_guard_include_tool_tasks'] = bool(value) if value is not None else None

        if 'completion_guard_auto_threshold' in overrides:
            mode_config['completion_guard_auto_threshold'] = self._normalize_web_float_override(
                overrides['completion_guard_auto_threshold'],
                env_numeric_defaults['completion_guard_auto_threshold'],
            )

        if 'completion_guard_eval_provider' in overrides:
            value = overrides['completion_guard_eval_provider'] or None
            if self.mode == 'local' and value not in (None, 'ollama'):
                value = 'ollama'
            mode_config['completion_guard_eval_provider'] = value

        if 'completion_guard_eval_model' in overrides:
            value = overrides['completion_guard_eval_model'] or None
            effective_provider = (
                mode_config.get('completion_guard_eval_provider')
                or get_jarvis_setting(
                    'JARVIS_COMPLETION_GUARD_EVAL_PROVIDER',
                    'ollama' if self.mode == 'local' else 'openai',
                )
            )
            if not self._model_is_compatible_with_provider(effective_provider, value):
                value = None
            mode_config['completion_guard_eval_model'] = value or None
        
        # Handle audio overrides (global, not per-mode)
        if 'tts_enabled' in overrides:
            if 'audio' not in config:
                config['audio'] = {}
            config['audio']['tts_enabled'] = overrides['tts_enabled']
        
        # Handle UI overrides (global)
        if 'progress_events' in overrides:
            if 'ui' not in config:
                config['ui'] = {}
            config['ui']['progress_events'] = overrides['progress_events']
        
        # Handle conversation overrides (global)
        if 'history_limit' in overrides:
            if 'conversation' not in config:
                config['conversation'] = {}
            config['conversation']['history_limit'] = int(overrides['history_limit'])

        if config.get('audio', {}).get('tts_enabled') and mode_config.get('response_style') == 'detailed':
            config['audio']['tts_enabled'] = False
        
        return save_web_config(config)
    
    def update_web_setting(self, path: str, value: Any) -> bool:
        """Update a web UI setting by path"""
        config = load_web_config()
        
        keys = path.split('.')
        target = config
        
        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]
        
        target[keys[-1]] = value
        return save_web_config(config)
    
    def reset_to_defaults(self) -> bool:
        """Reset current mode's web overrides to use env defaults"""
        config = load_web_config()
        # Reset current mode's overrides
        config[self.mode] = {
            'llm_provider': None,
            'llm_model': None,
            'router_prompt_version': None,
            'image_provider': None,
            'video_provider': None,
            'music_provider': None,
            'tts_provider': None,
            'response_style': None,
            'tool_rag_limit': None,
            'qa_word_limit': None,
            'multi_turn_word_limit': None,
            'completion_guard_enabled': None,
            'completion_guard_mode': None,
            'completion_guard_ticket_on_fail': None,
            'completion_guard_show_ui_prompt': None,
            'completion_guard_include_qa': None,
            'completion_guard_include_tool_tasks': None,
            'completion_guard_auto_threshold': None,
            'completion_guard_eval_provider': None,
            'completion_guard_eval_model': None
        }
        return save_web_config(config)
    
    def get_blocked_tools(self) -> list:
        """Get list of tools blocked for web mode"""
        config = load_web_config()
        return config.get('tools', {}).get('blocked', [])
    
    def update_blocked_tools(self, blocked: list) -> bool:
        """Update the list of blocked tools"""
        config = load_web_config()
        if 'tools' not in config:
            config['tools'] = {}
        config['tools']['blocked'] = blocked
        return save_web_config(config)
    
    def set_mode(self, mode: str) -> bool:
        """Switch between cloud and local mode"""
        if mode not in ['cloud', 'local']:
            return False
        
        self.mode = mode
        
        # Also update web config default
        return self.update_web_setting('defaults.mode', mode)


def get_settings_manager(mode: str = None) -> SettingsManager:
    """Create a request-local settings manager for one stable mode.

    Managers are lightweight. Avoiding a mutable singleton prevents a mode
    switch in one request from changing another request's model discovery or
    defaults while it is still running.
    """
    if mode is None:
        try:
            from config_loader import get_scoped_config, get_active_config_mode
            mode = (
                get_active_config_mode()
                if get_scoped_config() is not None
                else load_web_config().get('defaults', {}).get('mode', 'cloud')
            )
        except Exception:
            mode = 'cloud'
    if mode not in ('cloud', 'local'):
        mode = 'cloud'
    return SettingsManager(mode)
