#!/usr/bin/env python3
"""
Jarvis Status Phrases - Dynamic phrase selection for status updates.

Provides natural, randomized status messages with optional humor,
tool-specific overrides, and style-aware selection.
"""

import json
import random
import os
from pathlib import Path
from typing import Any


class StatusPhrases:
    """Dynamic phrase selection for status updates."""
    
    # Category to tool-specific key mapping
    CATEGORY_KEY_MAP = {
        'task_start': 'start',
        'progress': 'progress',
        'building': 'progress',
        'searching': 'start',
        'fetching': 'start',
        'analyzing': 'progress',
        'error_retry': 'error',
        'server_error': 'error',
        'near_complete': 'progress',
        'long_wait': 'progress',
        'multi_turn': 'progress'
    }
    
    def __init__(self, config_path: str | None = None, mode: str | None = None):
        """
        Initialize phrase selector.
        
        Args:
            config_path: Path to status_phrases.json. If None, uses default location.
            mode: Phrase mode override. If None, reads from STATUS_PHRASE_MODE env var.
                  Options: 'normal' (default), 'unhinged' (chaotic/funny)
        """
        # Determine phrase mode
        if mode is None:
            # Import here to avoid circular imports
            try:
                from config_loader import get_config_value
                mode = get_config_value('STATUS_PHRASE_MODE', 'normal')
            except (ImportError, Exception):
                mode = os.environ.get('STATUS_PHRASE_MODE', 'normal')
        
        # Select config file based on mode
        config_dir = Path(__file__).parent.parent / 'config'
        
        if config_path is None:
            if mode == 'unhinged':
                config_path = config_dir / 'status_phrases_unhinged.json'
                # Fall back to normal if unhinged doesn't exist
                if not config_path.exists():
                    config_path = config_dir / 'status_phrases.json'
            else:
                config_path = config_dir / 'status_phrases.json'
        else:
            config_path = Path(config_path)
        
        self.mode = mode
        self.config = self._load_config(config_path)
        self.settings = self.config.get('settings', {})
        self.categories = self.config.get('categories', {})
        self.tool_specific = self.config.get('tool_specific', {})
        aliases = self.config.get('tool_aliases', {})
        self.tool_aliases = aliases if isinstance(aliases, dict) else {}
        
        # Track recently used phrases to avoid repetition
        self._recent_phrases: list[str] = []
        self._max_recent = 5
    
    def get_phrase(
        self, 
        category: str, 
        tool_name: str | None = None, 
        style: str = 'casual',
        context: dict[str, Any] | None = None
    ) -> str:
        """
        Get a random phrase for the given category.
        
        Args:
            category: 'task_start', 'progress', 'searching', 'building', etc.
            tool_name: Optional tool name for tool-specific overrides
            style: 'casual' or 'detailed'
            context: Optional context dict (turn_number, error_type, etc.)
        
        Returns:
            Random phrase from appropriate pool
        """
        phrase = None
        
        # 1. Check tool-specific first
        resolved_tool_name = tool_name
        if tool_name and tool_name not in self.tool_specific:
            alias = self.tool_aliases.get(tool_name)
            if isinstance(alias, str) and alias:
                resolved_tool_name = alias

        if resolved_tool_name and resolved_tool_name in self.tool_specific:
            tool_phrases = self.tool_specific[resolved_tool_name]
            key = self.CATEGORY_KEY_MAP.get(category, 'progress')
            if isinstance(tool_phrases, dict) and key in tool_phrases:
                phrases = tool_phrases[key]
                phrase = self._select_random(phrases)
        
        # 2. Fall back to category
        if phrase is None:
            phrase = self._get_category_phrase(category, style)
        
        # 3. Ultimate fallback
        if phrase is None:
            phrase = "Working on it boss"
        
        # Track to avoid repetition
        self._track_phrase(phrase)
        
        return phrase
    
    def _get_category_phrase(self, category: str, style: str) -> str | None:
        """Get phrase from category pools based on style and settings."""
        if category not in self.categories:
            return None
        
        cat = self.categories[category]
        
        # Build pool based on settings and style
        pool: list[str] = []
        
        # Base pool
        if style == 'detailed' and 'detailed' in cat:
            pool = list(cat['detailed'])
        else:
            pool = list(cat.get('standard', []))
        
        # Add humor if enabled
        if self.settings.get('humor_enabled', False) and 'humor' in cat:
            # Add humor phrases (weighted less - 1 humor per 2 standard)
            humor_phrases = cat['humor']
            pool.extend(humor_phrases)
        
        # Add encouragement if enabled
        if self.settings.get('encouragement', False) and 'encouragement' in cat:
            pool.extend(cat['encouragement'])
        
        return self._select_random(pool) if pool else None
    
    def _select_random(self, phrases: list[str]) -> str | None:
        """Select random phrase, avoiding recent repetition."""
        if not phrases:
            return None
        
        # Filter out recently used if we have options
        available = [p for p in phrases if p not in self._recent_phrases]
        
        # If all filtered out, just use full list
        if not available:
            available = phrases
        
        return random.choice(available)
    
    def _track_phrase(self, phrase: str):
        """Track phrase to avoid immediate repetition."""
        self._recent_phrases.append(phrase)
        if len(self._recent_phrases) > self._max_recent:
            self._recent_phrases.pop(0)
    
    def reset_recent(self):
        """Reset recent phrase tracking (e.g., new task)."""
        self._recent_phrases.clear()
    
    def _load_config(self, path: Path) -> dict[str, Any]:
        """Load config, return defaults if missing."""
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"[StatusPhrases] Config not found at {path}, using defaults")
            return self._default_config()
        except json.JSONDecodeError as e:
            print(f"[StatusPhrases] Invalid JSON in {path}: {e}, using defaults")
            return self._default_config()
    
    def _default_config(self) -> dict[str, Any]:
        """Minimal default if config file missing."""
        return {
            'settings': {
                'humor_enabled': False,
                'encouragement': False
            },
            'categories': {
                'task_start': {
                    'standard': ['On it boss', 'Working on that', 'Got it boss']
                },
                'progress': {
                    'standard': ['Working on it boss', 'Making progress', 'Still working']
                },
                'searching': {
                    'standard': ['Searching', 'Looking that up']
                },
                'building': {
                    'standard': ['Building', 'Setting up']
                },
                'error_retry': {
                    'standard': ['Trying again', 'Working around it']
                },
                'near_complete': {
                    'standard': ['Almost there', 'Wrapping up']
                },
                'long_wait': {
                    'standard': ['Still working', 'Taking a bit longer']
                }
            },
            'tool_specific': {},
            'tool_aliases': {}
        }
    
    def get_settings(self) -> dict[str, Any]:
        """Get current settings."""
        return self.settings.copy()
    
    def update_settings(self, **kwargs):
        """Update settings at runtime."""
        self.settings.update(kwargs)
    
    def list_categories(self) -> list[str]:
        """List available categories."""
        return list(self.categories.keys())
    
    def list_tool_overrides(self) -> list[str]:
        """List tools with specific overrides."""
        direct = {k for k in self.tool_specific.keys() if not k.startswith('_')}
        aliases = {k for k in self.tool_aliases.keys() if not k.startswith('_')}
        return sorted(direct | aliases)


# Singleton instance for easy access
_instance: StatusPhrases | None = None


def get_phrases() -> StatusPhrases:
    """Get singleton StatusPhrases instance."""
    global _instance
    if _instance is None:
        _instance = StatusPhrases()
    return _instance


def get_phrase(category: str, tool_name: str | None = None, style: str = 'casual') -> str:
    """Convenience function to get a phrase."""
    return get_phrases().get_phrase(category, tool_name, style)


if __name__ == "__main__":
    # Test phrase selection
    phrases = StatusPhrases()
    
    print("=== Status Phrases Test ===\n")
    
    print("Categories:", phrases.list_categories())
    print("Tool overrides:", phrases.list_tool_overrides())
    print("Settings:", phrases.get_settings())
    print()
    
    # Test various categories
    categories = ['task_start', 'progress', 'searching', 'building', 'error_retry', 'near_complete']
    
    for cat in categories:
        print(f"{cat}:")
        for _ in range(3):
            print(f"  - {phrases.get_phrase(cat)}")
        print()
    
    # Test tool-specific
    print("Tool-specific (opencode):")
    for _ in range(3):
        print(f"  - {phrases.get_phrase('building', tool_name='opencode')}")
    print()
    
    # Test detailed style
    print("Detailed style (building):")
    for _ in range(3):
        print(f"  - {phrases.get_phrase('building', style='detailed')}")
