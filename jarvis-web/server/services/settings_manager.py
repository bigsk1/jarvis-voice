"""
Settings Manager Service
Handles safe reading/writing of Jarvis settings with web overrides
"""
import os
from typing import Dict, List, Optional, Any
from ..config import (
    get_web_setting, save_web_config, load_web_config,
    get_jarvis_setting, load_jarvis_config
)


# Model options per provider
PROVIDER_MODELS = {
    'xai': [
        {'id': 'grok-4-1-fast-non-reasoning-latest', 'name': 'Grok 4.1 Fast (Default)', 'context': '2M'},
        {'id': 'grok-4-fast', 'name': 'Grok 4 Fast', 'context': '256K'},
        {'id': 'grok-4-1-reasoning-latest', 'name': 'Grok 4.1 Reasoning', 'context': '2M'},
        {'id': 'grok-3-fast', 'name': 'Grok 3 Fast (Legacy)', 'context': '131K'},
    ],
    'anthropic': [
        {'id': 'claude-sonnet-4-5-20250929', 'name': 'Claude Sonnet 4.5 (Default)', 'context': '200K'},
        {'id': 'claude-sonnet-4-20250514', 'name': 'Claude Sonnet 4', 'context': '200K'},
        {'id': 'claude-3-5-sonnet-20241022', 'name': 'Claude 3.5 Sonnet', 'context': '200K'},
        {'id': 'claude-3-opus-20240229', 'name': 'Claude 3 Opus', 'context': '200K'},
    ],
    'openai': [
        {'id': 'gpt-4o', 'name': 'GPT-4o (Default)', 'context': '128K'},
        {'id': 'gpt-4o-mini', 'name': 'GPT-4o Mini', 'context': '128K'},
        {'id': 'gpt-4-turbo', 'name': 'GPT-4 Turbo', 'context': '128K'},
        {'id': 'o1', 'name': 'o1 (Reasoning)', 'context': '200K'},
    ],
    'ollama': [
        {'id': 'llama3.1:70b', 'name': 'Llama 3.1 70B', 'context': '128K'},
        {'id': 'llama3.1:8b', 'name': 'Llama 3.1 8B', 'context': '128K'},
        {'id': 'mistral', 'name': 'Mistral 7B', 'context': '32K'},
        {'id': 'codellama', 'name': 'Code Llama', 'context': '16K'},
    ]
}

IMAGE_PROVIDERS = {
    'gemini': {'name': 'Google Gemini', 'model': 'gemini-3-pro-image-preview'},
    'openai': {'name': 'OpenAI DALL-E', 'model': 'gpt-image-1'}
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
    
    def get_settings_for_ui(self) -> Dict[str, Any]:
        """Get all settings formatted for the UI"""
        self._ensure_jarvis_config()
        web_config = load_web_config()
        
        # Get cloud.env defaults
        cloud_provider = get_jarvis_setting('LLM_PROVIDER', 'xai')
        cloud_image_provider = get_jarvis_setting('IMAGE_TOOL_PROVIDER', 'gemini')
        cloud_tool_threshold = get_jarvis_setting('TOOL_SIMILARITY_THRESHOLD', '0.26')
        cloud_memory_threshold = get_jarvis_setting('SEMANTIC_SIMILARITY_THRESHOLD', '0.28')
        
        # Get web overrides (null = use default)
        web_llm = web_config.get('llm', {})
        web_image = web_config.get('image', {})
        web_thresholds = web_config.get('thresholds', {})
        
        # Calculate effective values
        effective_provider = web_llm.get('provider') or cloud_provider
        effective_model = web_llm.get('model') or self._get_default_model(effective_provider)
        effective_image = web_image.get('provider') or cloud_image_provider
        
        return {
            'mode': self.mode,
            
            # LLM Settings
            'llm': {
                'provider': {
                    'value': effective_provider,
                    'default': cloud_provider,
                    'is_override': web_llm.get('provider') is not None,
                    'options': list(PROVIDER_MODELS.keys())
                },
                'model': {
                    'value': effective_model,
                    'default': self._get_default_model(cloud_provider),
                    'is_override': web_llm.get('model') is not None,
                    'options': PROVIDER_MODELS.get(effective_provider, [])
                }
            },
            
            # Image Settings
            'image': {
                'provider': {
                    'value': effective_image,
                    'default': cloud_image_provider,
                    'is_override': web_image.get('provider') is not None,
                    'options': list(IMAGE_PROVIDERS.keys())
                }
            },
            
            # Thresholds
            'thresholds': {
                'tool_similarity': {
                    'value': float(web_thresholds.get('tool_similarity') or cloud_tool_threshold),
                    'default': float(cloud_tool_threshold),
                    'is_override': web_thresholds.get('tool_similarity') is not None
                },
                'memory_similarity': {
                    'value': float(web_thresholds.get('memory_similarity') or cloud_memory_threshold),
                    'default': float(cloud_memory_threshold),
                    'is_override': web_thresholds.get('memory_similarity') is not None
                }
            },
            
            # Audio (web-only)
            'audio': web_config.get('audio', {}),
            
            # API Key status
            'api_keys': self._get_api_key_status(),
            
            # Other Jarvis settings
            'owner_name': get_jarvis_setting('OWNER_NAME', 'Boss'),
            'tts_provider': get_jarvis_setting('TTS_PROVIDER', 'elevenlabs'),
            
            # Available models reference
            'provider_models': PROVIDER_MODELS,
            'image_providers': IMAGE_PROVIDERS
        }
    
    def _get_default_model(self, provider: str) -> str:
        """Get the default model for a provider"""
        models = PROVIDER_MODELS.get(provider, [])
        if models:
            return models[0]['id']
        return ''
    
    def _get_api_key_status(self) -> Dict[str, bool]:
        """Check which API keys are configured"""
        self._ensure_jarvis_config()
        keys = ['OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'XAI_API_KEY', 
                'GEMINI_API_KEY', 'ELEVENLABS_API_KEY', 'VAPI_API_KEY']
        return {key: bool(get_jarvis_setting(key, '')) for key in keys}
    
    def get_settings_with_status(self) -> Dict[str, dict]:
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
            'GEMINI_API_KEY', 'ELEVENLABS_API_KEY', 'VAPI_API_KEY'
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
    
    def save_web_overrides(self, overrides: Dict[str, Any]) -> bool:
        """Save web UI overrides"""
        config = load_web_config()
        
        # Handle LLM overrides
        if 'llm_provider' in overrides:
            if 'llm' not in config:
                config['llm'] = {}
            config['llm']['provider'] = overrides['llm_provider'] or None
        
        if 'llm_model' in overrides:
            if 'llm' not in config:
                config['llm'] = {}
            config['llm']['model'] = overrides['llm_model'] or None
        
        # Handle image overrides
        if 'image_provider' in overrides:
            if 'image' not in config:
                config['image'] = {}
            config['image']['provider'] = overrides['image_provider'] or None
        
        # Handle threshold overrides
        if 'tool_similarity' in overrides:
            if 'thresholds' not in config:
                config['thresholds'] = {}
            val = overrides['tool_similarity']
            config['thresholds']['tool_similarity'] = float(val) if val else None
        
        if 'memory_similarity' in overrides:
            if 'thresholds' not in config:
                config['thresholds'] = {}
            val = overrides['memory_similarity']
            config['thresholds']['memory_similarity'] = float(val) if val else None
        
        # Handle audio overrides
        if 'tts_enabled' in overrides:
            if 'audio' not in config:
                config['audio'] = {}
            config['audio']['tts_enabled'] = overrides['tts_enabled']
        
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
        """Reset all web overrides to use cloud.env defaults"""
        config = load_web_config()
        config['llm'] = {'provider': None, 'model': None}
        config['image'] = {'provider': None}
        config['thresholds'] = {'tool_similarity': None, 'memory_similarity': None}
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
_settings_manager: Optional[SettingsManager] = None


def get_settings_manager(mode: str = None) -> SettingsManager:
    """Get or create the settings manager singleton"""
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager(mode or 'cloud')
    elif mode and mode != _settings_manager.mode:
        _settings_manager.set_mode(mode)
    return _settings_manager
