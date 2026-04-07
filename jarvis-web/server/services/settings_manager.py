"""
Settings Manager Service
Handles safe reading/writing of Jarvis settings with web overrides
"""
from typing import Any
from ..config import (
    get_web_setting, save_web_config, load_web_config,
    get_jarvis_setting, load_jarvis_config
)
from model_catalog import (
    get_catalog_providers,
    get_default_model_id,
    get_model_context_label,
    get_provider_model_options,
)


def fetch_ollama_models(base_url: str = None, mode: str = None) -> list:
    """Fetch available models from Ollama server, filtered by mode when useful."""
    import requests
    
    if not base_url:
        base_url = get_jarvis_setting('OLLAMA_BASE_URL', 'http://localhost:11434')
    
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            models = []
            for model in data.get('models', []):
                name = model.get('name', '')
                is_cloud_model = ':cloud' in name.lower()
                # Get size info if available
                size_gb = model.get('size', 0) / (1024**3)
                size_str = f"{size_gb:.1f}GB" if size_gb > 0 else ''
                models.append({
                    'id': name,
                    'name': name,
                    'context': ('cloud' if is_cloud_model else (size_str or 'local')),
                    '_is_cloud': is_cloud_model,
                })

            if mode == 'cloud':
                models = [m for m in models if m.get('_is_cloud')]
            elif mode == 'local':
                models = [m for m in models if not m.get('_is_cloud')]

            for model in models:
                model.pop('_is_cloud', None)
            return models
    except Exception as e:
        print(f"[Settings] Failed to fetch Ollama models: {e}")
    
    # Fallback to default from config
    default_model = get_jarvis_setting('OLLAMA_MODEL', 'qwen3')
    fallback_context = 'cloud' if mode == 'cloud' and ':cloud' in default_model.lower() else 'local'
    return [{'id': default_model, 'name': f'{default_model} (default)', 'context': fallback_context}]

IMAGE_PROVIDERS = {
    'xai': {'name': 'xAI Grok', 'model': 'grok-imagine-image'},
    'gemini': {'name': 'Google Gemini', 'model': 'gemini-3.1-flash-image-preview'},
    'openai': {'name': 'OpenAI DALL-E', 'model': 'gpt-image-1.5'}
}

VIDEO_PROVIDERS = {
    'xai': {'name': 'xAI Grok', 'model': 'grok-imagine-video'},
    'gemini': {'name': 'Google Gemini Veo', 'model': 'veo-3.1'}
}

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


class SettingsManager:
    """Manages settings for the web UI with override support"""
    
    # Settings safe to expose to the UI (no API keys)
    SAFE_JARVIS_SETTINGS = [
        'MODE',
        'OWNER_NAME',
        'LLM_PROVIDER',
        'TTS_PROVIDER',
        'IMAGE_TOOL_PROVIDER',
        'VIDEO_TOOL_PROVIDER',
        'TOOL_SIMILARITY_THRESHOLD',
        'SEMANTIC_SIMILARITY_THRESHOLD',
        'INTELLIGENCE_ENABLED',
        'INTELLIGENCE_MIN_CONFIDENCE',
    ]
    
    # Patterns that indicate sensitive values (never expose)
    SENSITIVE_PATTERNS = ['API_KEY', 'SECRET', 'TOKEN', 'PASSWORD', 'PRIVATE']
    
    def __init__(self, mode: str = 'cloud'):
        self.mode = mode
        self._jarvis_loaded = False
    
    def _ensure_jarvis_config(self):
        """Ensure Jarvis config is loaded"""
        if not self._jarvis_loaded:
            load_jarvis_config(self.mode)
            self._jarvis_loaded = True

    def _get_model_options_with_current(self, provider: str, current_model: str | None) -> list[dict[str, str]]:
        """Return curated provider options plus any active custom model."""
        options = get_provider_model_options(provider)
        if not current_model:
            return options

        if any(option.get('id') == current_model for option in options):
            return options

        context = get_model_context_label(provider, current_model) or 'custom'
        return [
            {'id': current_model, 'name': f'{current_model} (custom)', 'context': context},
            *options,
        ]
    
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
            'JARVIS_RESPONSE_STYLE': ('response', 'style'),
            'JARVIS_QA_WORD_LIMIT': ('response', 'qa_word_limit'),
            'JARVIS_MULTI_TURN_WORD_LIMIT': ('response', 'multi_turn_word_limit'),
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
        env_image_provider = get_jarvis_setting('IMAGE_TOOL_PROVIDER', 'gemini')
        env_video_provider = get_jarvis_setting('VIDEO_TOOL_PROVIDER', 'xai')
        env_response_style = get_jarvis_setting('JARVIS_RESPONSE_STYLE', 'auto')
        env_qa_word_limit = int(get_jarvis_setting('JARVIS_QA_WORD_LIMIT', '75'))
        env_multi_turn_word_limit = int(get_jarvis_setting('JARVIS_MULTI_TURN_WORD_LIMIT', '50'))
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
                get_jarvis_setting('OLLAMA_MODEL', 'qwen3.5:latest')
                if env_completion_guard_eval_provider == 'ollama'
                else get_default_model_id(env_completion_guard_eval_provider)
            )
        )
        
        # Get per-mode web overrides (null = use env default)
        mode_overrides = web_config.get(self.mode, {})
        web_provider = mode_overrides.get('llm_provider')
        web_model = mode_overrides.get('llm_model')
        web_image = mode_overrides.get('image_provider')
        web_video = mode_overrides.get('video_provider')
        web_response_style = mode_overrides.get('response_style')
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
        effective_model = web_model or self._get_env_provider_model(effective_provider)
        effective_image = web_image or env_image_provider
        effective_video = web_video or env_video_provider
        effective_response_style = web_response_style or env_response_style
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
        effective_completion_guard_eval_model = (
            web_completion_guard_eval_model
            or env_completion_guard_eval_model
            or self._get_env_provider_model(effective_completion_guard_eval_provider)
        )
        
        return {
            'mode': self.mode,
            
            # LLM Settings
            'llm': {
                'provider': {
                    'value': effective_provider,
                    'default': env_provider,
                    'is_override': web_provider is not None,
                    'options': get_catalog_providers()
                },
                'model': {
                    'value': effective_model,
                    'default': self._get_env_provider_model(env_provider),
                    'is_override': web_model is not None,
                    'options': self._get_model_options_with_current(effective_provider, effective_model)
                }
            },
            
            # Image Settings
            'image': {
                'provider': {
                    'value': effective_image,
                    'default': env_image_provider,
                    'is_override': web_image is not None,
                    'options': list(IMAGE_PROVIDERS.keys())
                }
            },
            
            # Video Settings
            'video': {
                'provider': {
                    'value': effective_video,
                    'default': env_video_provider,
                    'is_override': web_video is not None,
                    'options': list(VIDEO_PROVIDERS.keys())
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
                    'is_override': web_qa_word_limit is not None
                },
                'multi_turn_word_limit': {
                    'value': effective_multi_turn_word_limit,
                    'default': env_multi_turn_word_limit,
                    'is_override': web_multi_turn_word_limit is not None
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
                    'is_override': web_completion_guard_auto_threshold is not None
                },
                'eval_provider': {
                    'value': effective_completion_guard_eval_provider,
                    'default': env_completion_guard_eval_provider,
                    'is_override': web_completion_guard_eval_provider is not None,
                    'options': ['ollama'] if self.mode == 'local' else get_catalog_providers()
                },
                'eval_model': {
                    'value': effective_completion_guard_eval_model,
                    'default': env_completion_guard_eval_model or self._get_env_provider_model(env_completion_guard_eval_provider),
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
            
            # Other Jarvis settings
            'owner_name': get_jarvis_setting('OWNER_NAME', 'Boss'),
            'tts_provider': get_jarvis_setting('TTS_PROVIDER', 'elevenlabs'),
            
            # Available models reference (with dynamic Ollama)
            'provider_models': self._get_provider_models(),
            'image_providers': IMAGE_PROVIDERS,
            'video_providers': VIDEO_PROVIDERS,
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
        
        # Dynamically fetch Ollama models if in local mode or Ollama selected
        web_config = load_web_config()
        mode_overrides = web_config.get(self.mode, {}) if isinstance(web_config, dict) else {}
        ollama_needed = (
            self.mode == 'local'
            or mode_overrides.get('llm_provider') == 'ollama'
            or mode_overrides.get('completion_guard_eval_provider') == 'ollama'
            or get_jarvis_setting('JARVIS_COMPLETION_GUARD_EVAL_PROVIDER', 'openai') == 'ollama'
        )
        if ollama_needed:
            ollama_url = get_jarvis_setting('OLLAMA_BASE_URL', 'http://localhost:11434')
            models['ollama'] = fetch_ollama_models(ollama_url, mode=self.mode)
        else:
            # Fallback for cloud mode
            default_model = get_jarvis_setting('OLLAMA_MODEL', 'qwen3')
            models['ollama'] = [{'id': default_model, 'name': f'{default_model}', 'context': 'local'}]
        
        return models
    
    def _get_default_model(self, provider: str) -> str:
        """Get the default model for a provider"""
        if provider == 'ollama':
            # For Ollama, use the configured model from env
            return get_jarvis_setting('OLLAMA_MODEL', 'qwen3')

        return get_default_model_id(provider)

    def _get_env_provider_model(self, provider: str) -> str:
        """Get the configured model from env for a provider, or fall back to the provider default."""
        env_key_map = {
            'xai': 'XAI_MODEL',
            'anthropic': 'ANTHROPIC_MODEL',
            'openai': 'OPENAI_MODEL',
            'ollama': 'OLLAMA_MODEL',
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
        keys = ['OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'XAI_API_KEY', 
                'GEMINI_API_KEY', 'ELEVENLABS_API_KEY', 'VAPI_API_KEY',
                'COINGECKO_API_KEY', 'OPENWEATHER_API_KEY', 'CLOUDFLARE_API_TOKEN']
        return {key: bool(get_jarvis_setting(key, '')) for key in keys}
    
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
            'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'XAI_API_KEY',
            'GEMINI_API_KEY', 'ELEVENLABS_API_KEY', 'VAPI_API_KEY',
            'COINGECKO_API_KEY', 'OPENWEATHER_API_KEY', 'CLOUDFLARE_API_TOKEN',
        ]
        for key in api_keys:
            value = get_jarvis_setting(key, '')
            settings[key] = {
                'value': '***configured***' if value else '',
                'sensitive': True,
                'configured': bool(value)
            }
        
        return settings
    
    def get_web_settings(self) -> dict:
        """Return web UI specific settings"""
        return load_web_config()
    
    def save_web_overrides(self, overrides: dict[str, Any]) -> bool:
        """Save web UI overrides (per-mode for LLM/image)"""
        config = load_web_config()
        
        # Ensure mode section exists
        if self.mode not in config:
            config[self.mode] = {}
        mode_config = config[self.mode]
        
        # Handle LLM overrides (per-mode)
        if 'llm_provider' in overrides:
            mode_config['llm_provider'] = overrides['llm_provider'] or None
        
        if 'llm_model' in overrides:
            mode_config['llm_model'] = overrides['llm_model'] or None
        
        # Handle image overrides (per-mode)
        if 'image_provider' in overrides:
            mode_config['image_provider'] = overrides['image_provider'] or None
        
        # Handle video overrides (per-mode)
        if 'video_provider' in overrides:
            mode_config['video_provider'] = overrides['video_provider'] or None

        if 'response_style' in overrides:
            mode_config['response_style'] = overrides['response_style'] or None

        if 'qa_word_limit' in overrides:
            value = overrides['qa_word_limit']
            mode_config['qa_word_limit'] = int(value) if value not in (None, '') else None

        if 'multi_turn_word_limit' in overrides:
            value = overrides['multi_turn_word_limit']
            mode_config['multi_turn_word_limit'] = int(value) if value not in (None, '') else None

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
            value = overrides['completion_guard_auto_threshold']
            mode_config['completion_guard_auto_threshold'] = float(value) if value not in (None, '') else None

        if 'completion_guard_eval_provider' in overrides:
            value = overrides['completion_guard_eval_provider'] or None
            if self.mode == 'local' and value not in (None, 'ollama'):
                value = 'ollama'
            mode_config['completion_guard_eval_provider'] = value

        if 'completion_guard_eval_model' in overrides:
            value = overrides['completion_guard_eval_model']
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
            'image_provider': None,
            'video_provider': None,
            'response_style': None,
            'qa_word_limit': None,
            'multi_turn_word_limit': None,
            'completion_guard_enabled': None,
            'completion_guard_mode': None,
            'completion_guard_ticket_on_fail': None,
            'completion_guard_show_ui_prompt': None,
            'completion_guard_include_qa': None,
            'completion_guard_include_tool_tasks': None
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
        self._jarvis_loaded = False
        self._ensure_jarvis_config()
        
        # Also update web config default
        self.update_web_setting('defaults.mode', mode)
        return True


# Singleton instance
_settings_manager: SettingsManager | None = None


def get_settings_manager(mode: str = None) -> SettingsManager:
    """Get or create the settings manager singleton"""
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager(mode or 'cloud')
    elif mode and mode != _settings_manager.mode:
        _settings_manager.set_mode(mode)
    return _settings_manager
