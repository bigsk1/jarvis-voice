#!/usr/bin/env python3
"""Configuration loader for Jarvis Voice Assistant."""
import os
import sys
from pathlib import Path


def _expand_env_value(value: str) -> str:
    """Expand ~ and $HOME / ${HOME} so seeded env files work on any Unix user.

    Does not use full ``os.path.expandvars`` — only home-related tokens so values
    containing other ``$`` characters (rare in secrets) are left unchanged.
    """
    if not value or not isinstance(value, str):
        return value
    home = os.environ.get("HOME")
    if home:
        value = value.replace("${HOME}", home).replace("$HOME", home)
    if value.startswith("~"):
        value = os.path.expanduser(value)
    return value


def load_env_file(env_file):
    """Load environment variables from a file."""
    env_vars = {}
    if not os.path.exists(env_file):
        print(f"❌ Config file not found: {env_file}", file=sys.stderr)
        return env_vars
    
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            
            # Parse KEY=VALUE
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                # Remove quotes if present
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                
                env_vars[key] = value
    
    return env_vars


def get_project_root():
    """Get the project root directory."""
    # Assume this file is in lib/ under project root
    return Path(__file__).parent.parent.resolve()


def load_config(mode=None):
    """
    Load configuration for specified mode.
    
    Args:
        mode: 'cloud' or 'local', or None to auto-detect from LLM_PROVIDER
    
    Returns:
        dict: Configuration values
    """
    # Auto-detect mode from existing LLM_PROVIDER if not specified
    if mode is None:
        llm_provider = os.environ.get('LLM_PROVIDER', '').lower()
        if llm_provider == 'ollama':
            mode = 'local'
        else:
            mode = 'cloud'  # Default to cloud if not set or unknown
    
    project_root = get_project_root()
    config_file = project_root / 'config' / f'{mode}.env'
    
    env_vars = load_env_file(config_file)
    expanded_vars = {k: _expand_env_value(v) for k, v in env_vars.items()}

    # Web UI overrides are prefixed with JARVIS_OVERRIDE_ and take precedence
    # over env file values. This prevents load_config() from overwriting
    # runtime overrides set by the web UI settings panel.
    override_prefix = 'JARVIS_OVERRIDE_'

    # Set environment variables
    for key, value in expanded_vars.items():
        # Don't overwrite if a web UI override exists for this key
        if f'{override_prefix}{key}' in os.environ:
            continue
        os.environ[key] = value

    return expanded_vars


def get_config_value(key, default=None):
    """Get a configuration value from environment.
    
    Checks for JARVIS_OVERRIDE_{key} first (set by web UI settings),
    then falls back to the regular env var.
    """
    override = os.environ.get(f'JARVIS_OVERRIDE_{key}')
    if override is not None:
        return override
    return os.environ.get(key, default)


def get_int(key, default=0):
    """Get integer config value."""
    try:
        return int(get_config_value(key, default))
    except (ValueError, TypeError):
        return default


def get_float(key, default=0.0):
    """Get float config value."""
    try:
        return float(get_config_value(key, default))
    except (ValueError, TypeError):
        return default


def get_bool(key, default=False):
    """Get boolean config value."""
    value = get_config_value(key, str(default)).lower()
    return value in ('true', '1', 'yes', 'on')

