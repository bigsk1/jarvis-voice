#!/usr/bin/env python3
"""
Jarvis Status LLM - Dynamic status summaries using small/fast LLMs.

Uses cheap models (gpt-4o-mini, grok-2, qwen2.5:1.5b) to generate
natural status updates from tool output/logs.

Falls back to static phrases if LLM unavailable or fails.
"""

import os
import sys
import requests

# Add lib to path
sys.path.insert(0, os.path.dirname(__file__))
from config_loader import get_config_value, get_int


class StatusSummarizer:
    """Generate dynamic status summaries using small LLM."""
    
    # Base system prompt for status summaries
    BASE_SYSTEM_PROMPT = """You are a voice assistant status updater. Generate VERY short (5-8 words) 
conversational status updates. Be natural and avoid technical jargon.
Only output the status phrase, nothing else."""
    
    def __init__(self):
        """Initialize summarizer with config."""
        self.enabled = get_config_value('STATUS_LLM_ENABLED', 'false').lower() == 'true'
        self.provider = get_config_value('STATUS_LLM_PROVIDER', 'openai').lower()
        self.model = get_config_value('STATUS_LLM_MODEL', 'gpt-4o-mini')
        self.max_tokens = get_int('STATUS_LLM_MAX_TOKENS', 30)
        
        # Personality settings (same as static phrases use)
        self.phrase_mode = get_config_value('STATUS_PHRASE_MODE', 'normal').lower()
        self.humor_enabled = get_config_value('STATUS_HUMOR_ENABLED', 'true').lower() == 'true'
        self.sass_level = get_int('STATUS_SASS_LEVEL', 1)  # 0=pro, 1=light, 2=sassy
        self.encouragement = get_config_value('STATUS_ENCOURAGEMENT_ENABLED', 'true').lower() == 'true'
        
        # Build dynamic system prompt based on personality
        self.system_prompt = self._build_system_prompt()
        
        # API keys/URLs based on provider
        self.api_key = None
        self.base_url = None
        
        if self.provider == 'openai':
            self.api_key = get_config_value('OPENAI_API_KEY')
            self.base_url = 'https://api.openai.com/v1'
        elif self.provider == 'xai':
            self.api_key = get_config_value('XAI_API_KEY')
            self.base_url = 'https://api.x.ai/v1'
        elif self.provider == 'anthropic':
            self.api_key = get_config_value('ANTHROPIC_API_KEY')
            self.base_url = 'https://api.anthropic.com/v1'
        elif self.provider == 'ollama':
            self.base_url = get_config_value('OLLAMA_BASE_URL', 'http://localhost:11434')
            self.model = get_config_value('STATUS_LLM_MODEL', 'qwen3')
    
    def _build_system_prompt(self) -> str:
        """Build system prompt based on personality settings."""
        parts = [self.BASE_SYSTEM_PROMPT]
        
        # Unhinged mode = chaotic, over-the-top
        if self.phrase_mode == 'unhinged':
            parts.append("""
Personality: UNHINGED MODE! Be chaotic, dramatic, over-the-top, and hilarious!
Use expressions like: "YEET!", "Let's gooo!", "Chaos mode activated!", "WHO SUMMONED ME?!"
Be unpredictable, energetic, and slightly unhinged. Have fun with it!""")
        else:
            # Normal mode with configurable personality
            personality_notes = []
            
            if self.humor_enabled:
                personality_notes.append("Include occasional humor, wit, or playful remarks.")
            
            if self.sass_level == 0:
                personality_notes.append("Be professional and straightforward.")
            elif self.sass_level == 1:
                personality_notes.append("Be friendly with a hint of sass.")
            elif self.sass_level >= 2:
                personality_notes.append("Be confidently sassy and playfully superior.")
            
            if self.encouragement:
                personality_notes.append("Add encouraging, positive vibes when appropriate.")
            
            if personality_notes:
                parts.append("\nPersonality: " + " ".join(personality_notes))
        
        return "\n".join(parts)
    
    def summarize(
        self, 
        context: str, 
        tool_name: str | None = None,
        event_type: str = 'progress'
    ) -> str | None:
        """
        Generate a 5-8 word status summary.
        
        Args:
            context: Tool output, logs, or current state
            tool_name: Optional tool name for context
            event_type: 'start', 'progress', 'error', 'complete'
        
        Returns:
            Short summary string for TTS, or None if failed (use fallback)
        """
        if not self.enabled:
            return None
        
        if not self.api_key and self.provider != 'ollama':
            return None
        
        # Build prompt
        prompt = self._build_prompt(context, tool_name, event_type)
        
        try:
            if self.provider == 'ollama':
                return self._call_ollama(prompt)
            elif self.provider == 'anthropic':
                return self._call_anthropic(prompt)
            else:
                # OpenAI-compatible (OpenAI, xAI)
                return self._call_openai_compatible(prompt)
        except Exception as e:
            # Log but don't crash - caller should use fallback
            print(f"[StatusLLM] Error: {e}", file=sys.stderr)
            return None
    
    def _build_prompt(self, context: str, tool_name: str | None, event_type: str) -> str:
        """Build the prompt for summarization."""
        # Truncate context to avoid large prompts
        context = context[:500] if context else "Working on task"
        
        tool_hint = f"Tool: {tool_name}\n" if tool_name else ""
        event_hint = {
            'start': 'Task is starting.',
            'progress': 'Task is in progress.',
            'error': 'Task hit an error but recovering.',
            'complete': 'Task is almost done.'
        }.get(event_type, 'Task is in progress.')
        
        return f"""{tool_hint}{event_hint}

Current state:
{context}

Generate a natural 5-8 word status update:"""
    
    def _call_openai_compatible(self, prompt: str) -> str | None:
        """Call OpenAI-compatible API (OpenAI, xAI)."""
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': self.system_prompt},
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': self.max_tokens,
            'temperature': 0.8  # Slightly higher for more creative/varied responses
        }
        
        response = requests.post(
            f'{self.base_url}/chat/completions',
            headers=headers,
            json=payload,
            timeout=5  # Fast timeout - status updates shouldn't wait
        )
        response.raise_for_status()
        
        result = response.json()
        content = result['choices'][0]['message']['content']
        return self._clean_response(content)
    
    def _call_anthropic(self, prompt: str) -> str | None:
        """Call Anthropic API."""
        headers = {
            'x-api-key': self.api_key,
            'Content-Type': 'application/json',
            'anthropic-version': '2023-06-01'
        }
        
        payload = {
            'model': self.model,
            'max_tokens': self.max_tokens,
            'system': self.system_prompt,
            'messages': [
                {'role': 'user', 'content': prompt}
            ]
        }
        
        response = requests.post(
            f'{self.base_url}/messages',
            headers=headers,
            json=payload,
            timeout=5
        )
        response.raise_for_status()
        
        result = response.json()
        content = result['content'][0]['text']
        return self._clean_response(content)
    
    def _call_ollama(self, prompt: str) -> str | None:
        """Call local Ollama API."""
        payload = {
            'model': self.model,
            'prompt': f"{self.system_prompt}\n\n{prompt}",
            'stream': False,
            'options': {
                'num_predict': self.max_tokens,
                'temperature': 0.8
            }
        }
        
        response = requests.post(
            f'{self.base_url}/api/generate',
            json=payload,
            timeout=10  # Ollama may need more time
        )
        response.raise_for_status()
        
        result = response.json()
        content = result.get('response', '')
        return self._clean_response(content)
    
    def _clean_response(self, content: str) -> str | None:
        """Clean up LLM response for TTS."""
        if not content:
            return None
        
        # Remove quotes, newlines, extra whitespace
        content = content.strip().strip('"').strip("'")
        content = content.replace('\n', ' ').strip()
        
        # Remove common prefixes LLMs add
        prefixes = ['Status:', 'Update:', 'Progress:', 'Summary:']
        for prefix in prefixes:
            if content.lower().startswith(prefix.lower()):
                content = content[len(prefix):].strip()
        
        # Ensure reasonable length (5-15 words)
        words = content.split()
        if len(words) > 15:
            content = ' '.join(words[:12]) + '...'
        elif len(words) < 2:
            return None  # Too short, use fallback
        
        return content
    
    def is_enabled(self) -> bool:
        """Check if LLM summarization is enabled and configured."""
        if not self.enabled:
            return False
        if self.provider != 'ollama' and not self.api_key:
            return False
        return True


# Singleton instance
_instance: StatusSummarizer | None = None


def get_status_summarizer() -> StatusSummarizer:
    """Get singleton StatusSummarizer instance."""
    global _instance
    if _instance is None:
        _instance = StatusSummarizer()
    return _instance


def summarize_status(
    context: str, 
    tool_name: str | None = None,
    event_type: str = 'progress'
) -> str | None:
    """Convenience function for status summarization."""
    return get_status_summarizer().summarize(context, tool_name, event_type)


if __name__ == "__main__":
    # Test summarizer
    print("=== Status LLM Summarizer Test ===\n")
    
    summarizer = StatusSummarizer()
    print(f"Enabled: {summarizer.enabled}")
    print(f"Provider: {summarizer.provider}")
    print(f"Model: {summarizer.model}")
    print(f"Is configured: {summarizer.is_enabled()}")
    print()
    
    if summarizer.is_enabled():
        # Test with sample context
        context = """
        Creating snake_game.py...
        Adding pygame imports...
        Setting up game loop with 60 FPS...
        Initializing snake position and food spawner...
        """
        
        print("Testing with OpenCode-like context:")
        print(f"Context: {context[:100]}...")
        
        result = summarizer.summarize(context, tool_name='opencode', event_type='progress')
        print(f"Summary: {result}")
    else:
        print("Summarizer not enabled or not configured.")
        print("Set STATUS_LLM_ENABLED=true and configure provider/API key.")

