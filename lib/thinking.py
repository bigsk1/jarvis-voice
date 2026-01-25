#!/usr/bin/env python3
"""
Thinking Module - Extended reasoning support for LLMs
Supports multiple providers: Anthropic, OpenAI, Ollama
"""
import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Models that support extended thinking
THINKING_MODELS = {
    "anthropic": [
        "claude-sonnet-4-5-20250929",
        "claude-sonnet-4-20250514", 
        "sonnet-4.5",
        "sonnet-4"
    ],
    "openai": [
        "o1",
        "o1-preview",
        "o1-mini",
        "o3-mini"  # Reasoning models
    ],
    "ollama": [
        "qwen2.5-coder:32b-instruct-q4_K_M",  # Some Qwen models support thinking
        "qwen3:14b",  # Qwen3 14B reasoning model
        "deepseek-r1",  # DeepSeek reasoning model
        "qwq"  # QwQ thinking model
    ]
}


def is_thinking_supported(provider: str, model: str) -> bool:
    """
    Check if a model supports extended thinking.
    
    Args:
        provider: Provider name (anthropic, openai, ollama)
        model: Model name
        
    Returns:
        True if thinking is supported, False otherwise
    """
    if provider not in THINKING_MODELS:
        return False
    
    # Check exact match
    if model in THINKING_MODELS[provider]:
        return True
    
    # Check partial match (for versioned models)
    for supported_model in THINKING_MODELS[provider]:
        if supported_model in model or model in supported_model:
            return True
    
    return False


def should_enable_thinking() -> bool:
    """
    Check if thinking mode should be enabled.
    Priority: CLI flag > env variable
    
    Returns:
        True if thinking should be enabled
    """
    # Check environment variable
    env_value = os.getenv("JARVIS_DEBUG_THINKING", "false").lower()
    return env_value in ("true", "1", "yes", "on")


def get_thinking_config(provider: str, model: str) -> dict[str, Any] | None:
    """
    Get thinking configuration for a specific provider/model.
    
    Args:
        provider: Provider name
        model: Model name
        
    Returns:
        Thinking config dict or None if not supported
    """
    if not is_thinking_supported(provider, model):
        return None
    
    if provider == "anthropic":
        return {
            "type": "enabled",
            "budget_tokens": 2000  # Tokens allocated for thinking
        }
    elif provider == "openai":
        # OpenAI o1 models think automatically, no special config needed
        return {
            "type": "automatic"
        }
    elif provider == "ollama":
        # Ollama thinking models may need special prompting
        return {
            "type": "prompted",
            "system_addition": "\n\nThink step-by-step before responding."
        }
    
    return None


def extract_thinking(response: Any, provider: str) -> str | None:
    """
    Extract thinking content from LLM response.
    
    Args:
        response: LLM response object
        provider: Provider name
        
    Returns:
        Thinking text or None if not available
    """
    try:
        if provider == "anthropic":
            # Anthropic returns thinking as a content block with type="thinking"
            if hasattr(response, 'content'):
                for block in response.content:
                    if hasattr(block, 'type') and block.type == 'thinking':
                        # Extract text from thinking block
                        if hasattr(block, 'thinking'):
                            return block.thinking
                        elif hasattr(block, 'text'):
                            return block.text
            # Fallback: Check if thinking is a direct attribute (older API format)
            if hasattr(response, 'thinking') and response.thinking:
                return response.thinking[0].text
        
        elif provider == "openai":
            # OpenAI o1 models include thinking in response ( o1 is very old now and not going to use, gpt-5 and gpt-5.1 are latest and support reasoning)
            if hasattr(response, 'choices') and len(response.choices) > 0:
                choice = response.choices[0]
                if hasattr(choice, 'reasoning_content'):
                    return choice.reasoning_content
        
        elif provider == "ollama":
            # Ollama has TWO formats for thinking:
            # 1. Structured field (qwen3:14b, modern models) - preferred
            # 2. Tags in content (deepseek-r1, raw output) - fallback
            
            # Method 1: Check for structured thinking field (Ollama API format)
            if isinstance(response, dict):
                # Response is a dict (from JSON)
                if 'thinking' in response and response['thinking']:
                    return response['thinking']
                # Sometimes thinking is nested in message
                if 'message' in response and isinstance(response['message'], dict):
                    if 'thinking' in response['message']:
                        return response['message']['thinking']
            
            # Method 2: Check for thinking in message content (tags)
            if hasattr(response, 'message') and hasattr(response.message, 'content'):
                content = response.message.content
                
                # DeepSeek R1 uses <think> tags
                if '<think>' in content and '</think>' in content:
                    start = content.find('<think>') + len('<think>')
                    end = content.find('</think>')
                    return content[start:end].strip()
                
                # Generic <thinking> tags (other models)
                if '<thinking>' in content and '</thinking>' in content:
                    start = content.find('<thinking>') + len('<thinking>')
                    end = content.find('</thinking>')
                    return content[start:end].strip()
    
    except Exception as e:
        logger.warning(f"Failed to extract thinking: {e}")
    
    return None


def log_thinking(
    query: str,
    thinking: str,
    decision: dict[str, Any],
    provider: str,
    model: str
) -> None:
    """
    Log thinking to file for later analysis.
    
    Args:
        query: User query
        thinking: LLM thinking/reasoning
        decision: Decision made (tools called, saved, etc.)
        provider: Provider name
        model: Model name
    """
    try:
        # Create logs/thinking directory if it doesn't exist
        log_dir = Path("logs/thinking")
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # Log file: YYYY-MM-DD_decisions.jsonl
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = log_dir / f"{today}_decisions.jsonl"
        
        # Create log entry
        entry = {
            "timestamp": datetime.now().isoformat(),
            "provider": provider,
            "model": model,
            "query": query,
            "thinking": thinking,
            "decision": decision
        }
        
        # Append to log file (JSONL format)
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        
        logger.debug(f"Thinking logged to {log_file}")
    
    except Exception as e:
        logger.error(f"Failed to log thinking: {e}")


def format_thinking_display(thinking: str, compact: bool = False) -> str:
    """
    Format thinking for console display.
    
    Args:
        thinking: Thinking text
        compact: If True, show abbreviated version
        
    Returns:
        Formatted string for display
    """
    if not thinking:
        return ""
    
    # ANSI color codes
    CYAN = '\033[0;36m'
    YELLOW = '\033[1;33m'
    NC = '\033[0m'  # No Color
    
    if compact and len(thinking) > 200:
        # Show first 150 chars + "..."
        thinking = thinking[:150] + "..."
    
    # Format with box
    lines = thinking.split('\n')
    formatted = f"\n{CYAN}{'═' * 60}{NC}\n"
    formatted += f"{YELLOW}🧠 LLM Thinking:{NC}\n"
    formatted += f"{CYAN}{'─' * 60}{NC}\n"
    
    for line in lines:
        formatted += f"   {line}\n"
    
    formatted += f"{CYAN}{'═' * 60}{NC}\n"
    
    return formatted


def get_thinking_prompt_addition() -> str:
    """
    Get additional system prompt text to encourage thinking.
    
    Returns:
        Additional prompt text
    """
    return """
When making complex decisions (auto-save, tool selection, grey areas), explicitly reason through:
1. What is the user asking for?
2. What information do I need?
3. Should I save this? (check criteria)
4. What category/importance?
5. Which tool is best?

Think step-by-step before deciding.
"""


# Thinking analysis helpers

def analyze_thinking_logs(date: str = None) -> dict[str, Any]:
    """
    Analyze thinking logs to find patterns.
    
    Args:
        date: Date to analyze (YYYY-MM-DD) or None for today
        
    Returns:
        Analysis summary
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    
    log_file = Path(f"logs/thinking/{date}_decisions.jsonl")
    
    if not log_file.exists():
        return {"error": "No thinking logs found for this date"}
    
    # Parse logs
    decisions = []
    with open(log_file, "r") as f:
        for line in f:
            if line.strip():
                decisions.append(json.loads(line))
    
    # Analyze
    total = len(decisions)
    saved = sum(1 for d in decisions if d['decision'].get('saved', False))
    tools_used = {}
    
    for decision in decisions:
        for tool in decision['decision'].get('tools', []):
            tools_used[tool] = tools_used.get(tool, 0) + 1
    
    return {
        "date": date,
        "total_decisions": total,
        "saved_to_memory": saved,
        "save_rate": f"{(saved/total*100):.1f}%" if total > 0 else "0%",
        "tools_used": tools_used,
        "recent_decisions": decisions[-5:]  # Last 5
    }


if __name__ == "__main__":
    # Test thinking support detection
    print("Testing thinking support detection:")
    print(f"Anthropic Sonnet 4.5: {is_thinking_supported('anthropic', 'claude-sonnet-4-5-20250929')}")
    print(f"OpenAI o1: {is_thinking_supported('openai', 'o1')}")
    print(f"Ollama qwen3-vl: {is_thinking_supported('ollama', 'qwen3-vl')}")
    print(f"Ollama qwq: {is_thinking_supported('ollama', 'qwq')}")

