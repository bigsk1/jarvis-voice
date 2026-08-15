#!/usr/bin/env python3
"""
Jarvis Status LLM - Dynamic status summaries using small/fast LLMs.

Uses cheap models (gpt-4o-mini, grok-4.3, qwen2.5:1.5b) to generate
natural status updates from a small sanitized execution snapshot.

Falls back to static phrases if LLM unavailable or fails.
"""

import os
import re
import sys
import time
import requests
from typing import Any

# Add lib to path
sys.path.insert(0, os.path.dirname(__file__))
from config_loader import get_config_value, get_int
from ollama_utils import (
    get_ollama_execution_class,
    get_ollama_request_urls,
    request_ollama,
    OLLAMA_EXECUTION_LOCAL_DAEMON,
)

_STATUS_CONTEXT_MAX_CHARS = 500
_STATUS_CONTEXT_TRUNCATED = "... [truncated]"
_HELPER_STATUS_INSTRUCTION = (
    "Rewrite only as a 3-8 word progress phrase. Do not answer the task, "
    "invent facts, claim completion unless stated, or use labels."
)


class StatusSummarizer:
    """Generate dynamic status summaries using small LLM."""
    
    # Base system prompt for status summaries
    BASE_SYSTEM_PROMPT = """You are a voice assistant status updater. Generate VERY short (5-8 words)
conversational status updates. Be natural and avoid technical jargon.
Do not use exclamation marks.
Describe only the action currently underway. Never invent results, facts, or
claim completion unless the current state explicitly says it is complete.
Do not repeat prompt labels such as "Current state" or "Tool".
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
        self.xai_provider = None
        self.helper_provider = None
        self._last_usage_info: dict[str, Any] | None = None
        
        if self.provider == 'openai':
            self.api_key = get_config_value('OPENAI_API_KEY')
            self.base_url = 'https://api.openai.com/v1'
        elif self.provider == 'xai':
            self.api_key = get_config_value('XAI_API_KEY')
            if self.enabled:
                try:
                    from llm_provider import create_provider

                    self.xai_provider = create_provider(
                        'xai',
                        api_key=self.api_key,
                        model=self.model,
                    )
                    self.model = self.xai_provider.model
                except Exception as exc:
                    print(f"[StatusLLM] xAI auth unavailable: {exc}", file=sys.stderr)
        elif self.provider == 'anthropic':
            self.api_key = get_config_value('ANTHROPIC_API_KEY')
            self.base_url = 'https://api.anthropic.com/v1'
        elif self.provider == 'helper':
            from llm_provider import create_configured_provider

            _provider_name, self.model, self.helper_provider = create_configured_provider(
                provider_override='helper',
                disable_server_side_tools=True,
            )
            self.base_url = self.helper_provider.base_url
        elif self.provider == 'ollama':
            status_model = (get_config_value('STATUS_LLM_MODEL', '') or '').strip()
            from ollama_utils import resolve_ollama_model
            self.model = resolve_ollama_model(model_override=(status_model or None))
            execution_class = get_ollama_execution_class(self.model)
            self.base_url = get_ollama_request_urls(
                cloud_access=(execution_class != OLLAMA_EXECUTION_LOCAL_DAEMON),
            )[0]
    
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
        event_type: str = 'progress',
        call_metadata: dict[str, Any] | None = None,
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
        
        if (
            not self.api_key
            and self.provider not in {'helper', 'ollama', 'xai'}
        ):
            return None
        
        started = time.monotonic()
        prompt = (
            self._build_helper_prompt(context, tool_name, event_type)
            if self.provider == 'helper'
            else self._build_prompt(context, tool_name, event_type)
        )
        self._last_usage_info = None
        result = None
        error = None
        try:
            if self.provider == 'helper':
                result = self._call_helper(prompt, event_type=event_type)
            elif self.provider == 'ollama':
                result = self._call_ollama(prompt)
            elif self.provider == 'xai':
                if not self.xai_provider:
                    return None
                content = self.xai_provider.chat(
                    prompt,
                    system_prompt=self.system_prompt,
                    max_tokens=self.max_tokens,
                )
                if content.startswith('Error:'):
                    error = content
                else:
                    result = self._clean_response(content)
            elif self.provider == 'anthropic':
                result = self._call_anthropic(prompt)
            else:
                # OpenAI-compatible (OpenAI, xAI)
                result = self._call_openai_compatible(prompt)
        except Exception as e:
            # Log but don't crash - caller should use fallback
            error = str(e)
            print(f"[StatusLLM] Error: {e}", file=sys.stderr)
        finally:
            self._log_call(
                prompt=prompt,
                response_text=result,
                usage_info=self._last_usage_info,
                duration_ms=(time.monotonic() - started) * 1000,
                call_metadata=call_metadata,
                error=error,
            )
        return result

    def _log_call(
        self,
        *,
        prompt: str,
        response_text: str | None,
        usage_info: dict[str, Any] | None,
        duration_ms: float,
        call_metadata: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        """Record actual provider calls without adding them to chat usage totals."""
        if get_config_value('STATUS_LOGGING_ENABLED', 'true').strip().lower() != 'true':
            return
        try:
            from llm_logger import get_logger

            mode = str((call_metadata or {}).get('mode') or get_config_value('JARVIS_MODE', 'cloud'))
            get_logger(mode).log_llm_call(
                provider=self.provider,
                model=self.model,
                prompt_type='status_update',
                messages=[
                    {
                        'role': 'system',
                        'content': '' if self.provider == 'helper' else self.system_prompt,
                    },
                    {'role': 'user', 'content': prompt},
                ],
                response_text=response_text,
                tool_call=None,
                usage_info=usage_info,
                thinking=None,
                duration_ms=duration_ms,
                mode=mode,
                user_query=None,
                error=error,
                call_metadata=call_metadata,
            )
        except Exception as exc:
            if os.environ.get('JARVIS_DEBUG'):
                print(f"[StatusLLM] Failed to log call: {exc}", file=sys.stderr)
    
    @staticmethod
    def _truncate_context_for_prompt(
        context: str,
        max_chars: int = _STATUS_CONTEXT_MAX_CHARS,
    ) -> str:
        """Bound execution snapshot size with an explicit truncation marker."""
        cleaned = (context or "").strip()
        if not cleaned:
            return "Working on task"
        if len(cleaned) <= max_chars:
            return cleaned
        budget = max_chars - len(_STATUS_CONTEXT_TRUNCATED)
        if budget < 1:
            return _STATUS_CONTEXT_TRUNCATED[:max_chars]
        return cleaned[:budget].rstrip() + _STATUS_CONTEXT_TRUNCATED

    def _build_prompt(self, context: str, tool_name: str | None, event_type: str) -> str:
        """Build the prompt for summarization."""
        context = self._truncate_context_for_prompt(context)
        
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

    def _build_helper_prompt(
        self,
        context: str,
        tool_name: str | None,
        event_type: str,
    ) -> str:
        """Use a compact rewrite prompt that a 1B local model follows reliably."""
        context = self._truncate_context_for_prompt(context)
        tool_label = (tool_name or "task").replace("_", " ")
        phase = {
            'start': 'Starting',
            'progress': 'Working on',
            'error': 'Recovering while handling',
            'complete': 'Finishing',
        }.get(event_type, 'Working on')
        state = f"{phase} {tool_label}. {context}"
        return f"{_HELPER_STATUS_INSTRUCTION}\nSTATE: {state}\nPHRASE:"
    
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
        usage = result.get('usage') or {}
        if usage:
            from cost_estimator import estimate_cost

            input_tokens = int(usage.get('prompt_tokens') or 0)
            output_tokens = int(usage.get('completion_tokens') or 0)
            self._last_usage_info = estimate_cost(
                provider='openai',
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            prompt_details = usage.get('prompt_tokens_details') or {}
            cached_tokens = prompt_details.get('cached_tokens')
            if cached_tokens is not None:
                self._last_usage_info['cached_input_tokens'] = cached_tokens
                self._last_usage_info['cache_read_tokens'] = cached_tokens
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
        usage = result.get('usage') or {}
        if usage:
            from cost_estimator import estimate_cost

            input_tokens = int(usage.get('input_tokens') or 0)
            output_tokens = int(usage.get('output_tokens') or 0)
            self._last_usage_info = estimate_cost(
                provider='anthropic',
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            for source, target in (
                ('cache_creation_input_tokens', 'cache_creation_tokens'),
                ('cache_read_input_tokens', 'cache_read_tokens'),
            ):
                if usage.get(source) is not None:
                    self._last_usage_info[target] = usage[source]
        content = result['content'][0]['text']
        return self._clean_response(content)
    
    def _call_ollama(self, prompt: str) -> str | None:
        """Call the mode-appropriate Ollama daemon or direct cloud API."""
        payload = {
            'model': self.model,
            'prompt': f"{self.system_prompt}\n\n{prompt}",
            'stream': False,
            'options': {
                'num_predict': self.max_tokens,
                'temperature': 0.8
            }
        }
        
        execution_class = get_ollama_execution_class(self.model)
        response, used_base_url = request_ollama(
            'post',
            '/api/generate',
            cloud_access=(execution_class != OLLAMA_EXECUTION_LOCAL_DAEMON),
            json=payload,
            timeout=10  # Ollama may need more time
        )
        self.base_url = used_base_url
        response.raise_for_status()
        
        result = response.json()
        input_tokens = int(result.get('prompt_eval_count') or 0)
        output_tokens = int(result.get('eval_count') or 0)
        self._last_usage_info = {
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'total_tokens': input_tokens + output_tokens,
        }
        if execution_class == OLLAMA_EXECUTION_LOCAL_DAEMON:
            self._last_usage_info.update(cost_usd=0.0, billing_mode='local_compute')
        else:
            self._last_usage_info.update(
                cost_usd=None,
                cost_known=False,
                billing_mode='ollama_cloud_subscription',
            )
        content = result.get('response', '')
        return self._clean_response(content)

    def _call_helper(self, prompt: str, *, event_type: str = 'progress') -> str | None:
        """Call the dedicated host-local helper without mode-aware routing."""
        if not self.helper_provider:
            return None
        content = self.helper_provider.chat(
            prompt,
            system_prompt=None,
            max_tokens=self.max_tokens,
        )
        self.base_url = self.helper_provider.base_url
        self._last_usage_info = self.helper_provider.last_usage_info
        if content.startswith('Error:'):
            raise RuntimeError(content)
        lowered = content.lower()
        if any(label in lowered for label in ('current state:', 'tool:', 'phrase:')):
            return None
        if event_type != 'complete' and re.search(
            r'\b(?:complete|completed|done|finished)\b', lowered
        ):
            return None
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
        
        # Flash/v2 status TTS reads "!" as shouting; static JSON phrases are unchanged.
        content = content.replace('!', '.')

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
        if self.provider == 'xai':
            return self.xai_provider is not None
        if self.provider == 'helper':
            return self.helper_provider is not None
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
