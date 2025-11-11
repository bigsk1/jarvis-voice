#!/usr/bin/env python3
"""Configuration loader for Jarvis Voice Assistant."""
import os
import sys
from pathlib import Path


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


def load_config(mode='cloud'):
    """
    Load configuration for specified mode.
    
    Args:
        mode: 'cloud' or 'local'
    
    Returns:
        dict: Configuration values
    """
    project_root = get_project_root()
    config_file = project_root / 'config' / f'{mode}.env'
    
    env_vars = load_env_file(config_file)
    
    # Set environment variables
    for key, value in env_vars.items():
        os.environ[key] = value
    
    return env_vars


def get_config_value(key, default=None):
    """Get a configuration value from environment."""
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

