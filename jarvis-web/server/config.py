"""
Configuration loader for Jarvis Web UI
Loads web-specific config and integrates with main Jarvis config
"""
import sys
import json
from pathlib import Path

# Add parent lib to path for shared utilities
JARVIS_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(JARVIS_ROOT / 'lib'))

# Web app paths
WEB_ROOT = Path(__file__).parent.parent
CONFIG_PATH = WEB_ROOT / 'config' / 'web_config.json'
SKILLS_PATH = JARVIS_ROOT / 'skills'

# Default configuration
DEFAULT_CONFIG = {
    "server": {
        "host": "0.0.0.0",
        "port": 5001,
        "debug": False
    },
    # NOTE: Auth is controlled by WEBUI_PASSWORD env var, not this config.
    # Use is_auth_enabled() from lib/webui_auth.py to check auth state.
    "ui": {
        "theme": "dark",
        "show_tool_details": True,
        "auto_scroll": True,
        "sound_effects": True,
        "progress_events": True
    },
    "audio": {
        "tts_enabled": False,
        "tts_autoplay": True,
        "stt_enabled": False
    },
    "defaults": {
        "mode": "cloud"
    }
}

_web_config = None


def reload_web_config():
    """Force reload of web configuration (call after settings change)"""
    global _web_config
    _web_config = None
    return load_web_config()


def load_web_config() -> dict:
    """Load web configuration from JSON file"""
    global _web_config
    
    if _web_config is not None:
        return _web_config
    
    config = DEFAULT_CONFIG.copy()
    
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r') as f:
                file_config = json.load(f)
                # Deep merge
                for key, value in file_config.items():
                    if isinstance(value, dict) and key in config:
                        config[key].update(value)
                    else:
                        config[key] = value
        except Exception as e:
            print(f"Warning: Could not load web config: {e}")
    
    _web_config = config
    return config


def save_web_config(config: dict) -> bool:
    """Save web configuration to JSON file"""
    global _web_config
    
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)
        _web_config = config
        return True
    except Exception as e:
        print(f"Error saving web config: {e}")
        return False


def get_web_setting(path: str, default=None):
    """
    Get a web config setting by dot-notation path
    Example: get_web_setting('server.port', 5001)
    """
    config = load_web_config()
    keys = path.split('.')
    value = config
    
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    
    return value


def load_jarvis_config(mode: str = 'cloud'):
    """
    Load the main Jarvis configuration
    This allows web app to use the same settings as terminal mode
    """
    try:
        from config_loader import load_config
        load_config(mode)
        return True
    except Exception as e:
        print(f"Warning: Could not load Jarvis config: {e}")
        return False


def get_jarvis_setting(key: str, default=None):
    """Get a setting from the main Jarvis config"""
    try:
        from config_loader import get_config_value
        return get_config_value(key, default)
    except Exception:
        return default

