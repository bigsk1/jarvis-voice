#!/usr/bin/env python3
"""
Cost estimation for LLM API calls.
Provides token usage tracking and cost estimates for cloud providers.
"""

# Pricing as of November 2025 (USD per million tokens)
# Note: User is Tier 2 with Anthropic
PRICING = {
    "openai": {
        # GPT-5 series
        "gpt-5.1": {"input": 1.25, "output": 10.00},
        "gpt-5-mini": {"input": 0.25, "output": 2.00},
        "gpt-5-nano": {"input": 0.05, "output": 0.40},
        "gpt-5-pro": {"input": 15.00, "output": 120.00},
        # GPT-4.1 series
        "gpt-4.1": {"input": 3.00, "output": 12.00},
        "gpt-4.1-mini": {"input": 0.80, "output": 3.20},
        "gpt-4.1-nano": {"input": 0.20, "output": 0.80},
        # Reasoning models
        "o4-mini": {"input": 4.00, "output": 16.00},
        # Realtime models
        "gpt-realtime": {"input": 4.00, "output": 16.00},
        "gpt-realtime-mini": {"input": 0.60, "output": 2.40},
        # Legacy (backward compatibility)
        "gpt-4o": {"input": 3.00, "output": 12.00},  # Maps to GPT-4.1
        "gpt-4o-mini": {"input": 0.80, "output": 3.20},  # Maps to GPT-4.1 mini
    },
    "anthropic": {
        # Claude 4 series (most recent)
        "opus-4.1": {"input": 15.00, "output": 75.00},
        "sonnet-4.5": {"input": 3.00, "output": 15.00},  # Base tier (≤200K tokens)
        "haiku-4.5": {"input": 1.00, "output": 5.00},
        "sonnet-4": {"input": 3.00, "output": 15.00},
        "opus-4": {"input": 15.00, "output": 75.00},
        # Claude 3 series
        "sonnet-3.7": {"input": 3.00, "output": 15.00},
        "haiku-3.5": {"input": 0.80, "output": 4.00},
        "opus-3": {"input": 15.00, "output": 75.00},
        "haiku-3": {"input": 0.25, "output": 1.25},
        # Legacy dated versions (backward compatibility)
        "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
        "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
        "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
        "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    }
}


# Cache Pricing as of November 2025 (USD per million tokens)
# Anthropic Prompt Caching for Tier 2
CACHE_PRICING = {
    "anthropic": {
        # All models use same cache pricing regardless of tier
        "cache_write_base": 3.00,      # Regular input cost
        "cache_write_additional": 0.75, # Additional cost for cache write (+25%)
        "cache_read": 0.30,             # Cache read cost (90% discount)
    },
    "openai": {
        # OpenAI has automatic caching, different pricing
        "cache_read": 1.50,  # 50% discount on cached tokens
    }
}


def estimate_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> dict:
    """
    Estimate cost for an LLM API call.
    
    Args:
        provider: "openai" or "anthropic"
        model: Model name
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
    
    Returns:
        Dict with token counts and cost estimates
    
    Notes:
        - Pricing as of November 2025
        - Sonnet 4.5 uses base tier pricing (≤200K tokens)
        - For prompts >200K tokens, actual costs may be higher
    """
    if provider not in PRICING:
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost_usd": None,
            "note": f"Unknown provider: {provider}"
        }
    
    # Normalize model name for matching
    model_normalized = model.lower().replace("_", "-")
    model_pricing = PRICING[provider].get(model_normalized)
    
    if not model_pricing:
        # Try partial match (e.g., "gpt-4.1-mini-2025" matches "gpt-4.1-mini")
        for known_model, prices in PRICING[provider].items():
            if known_model in model_normalized or model_normalized in known_model:
                model_pricing = prices
                break
    
    cost = None
    note = None
    
    if model_pricing:
        input_cost = (input_tokens / 1_000_000) * model_pricing["input"]
        output_cost = (output_tokens / 1_000_000) * model_pricing["output"]
        cost = round(input_cost + output_cost, 6)
        
        # Note if using Sonnet 4.5 with large context
        if "sonnet-4.5" in model_normalized or "sonnet-4-5" in model_normalized:
            if input_tokens > 200_000:
                note = "Using base tier pricing; actual cost may be higher for >200K token prompts"
    else:
        note = f"Unknown model: {model}"
    
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cost_usd": cost,
        "note": note
    }


def format_cost_summary(cost_info: dict) -> str:
    """
    Format cost info for display.
    
    Args:
        cost_info: Dict from estimate_cost()
    
    Returns:
        Human-readable string
    """
    if cost_info["cost_usd"] is None:
        return f"{cost_info['total_tokens']} tokens (cost unknown)"
    
    # Format cost nicely
    cost = cost_info["cost_usd"]
    if cost < 0.01:
        cost_str = f"${cost:.4f}"  # Show 4 decimals for tiny amounts
    else:
        cost_str = f"${cost:.2f}"
    
    return f"{cost_info['total_tokens']} tokens ({cost_str})"


def estimate_cache_cost(provider: str, model: str, cache_creation_tokens: int = 0, 
                        cache_read_tokens: int = 0) -> dict:
    """
    Estimate cache-related costs for prompt caching.
    
    Args:
        provider: "openai" or "anthropic"
        model: Model name (for future model-specific cache pricing)
        cache_creation_tokens: Tokens written to cache (first request)
        cache_read_tokens: Tokens read from cache (subsequent requests)
    
    Returns:
        Dict with cache metrics and savings
        {
            "cache_creation_tokens": int,
            "cache_read_tokens": int,
            "cache_write_cost_usd": float (additional cost for cache write),
            "cache_savings_usd": float (savings from cache read),
            "cache_hit": bool,
            "note": str (if fallback used)
        }
    
    Notes:
        - Pricing as of November 2025
        - Anthropic: $3.75/1M for cache write, $0.30/1M for cache read
        - Falls back gracefully for unknown providers
    """
    result = {
        "cache_creation_tokens": cache_creation_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_cost_usd": 0.0,
        "cache_savings_usd": 0.0,
        "cache_hit": False,
        "note": None
    }
    
    # Check if provider supports caching
    if provider not in CACHE_PRICING:
        result["note"] = f"Cache pricing unknown for provider: {provider}"
        return result
    
    cache_prices = CACHE_PRICING[provider]
    
    # Calculate cache write cost (additional cost beyond regular input)
    if cache_creation_tokens > 0:
        if provider == "anthropic":
            # Anthropic charges $3.75/1M for cache write vs $3.00/1M for regular input
            # So additional cost is $0.75/1M
            cache_write_cost = (cache_creation_tokens / 1_000_000) * cache_prices["cache_write_additional"]
            result["cache_write_cost_usd"] = round(cache_write_cost, 6)
        result["cache_hit"] = False
    
    # Calculate cache read savings
    if cache_read_tokens > 0:
        if provider == "anthropic":
            # Cache read costs $0.30/1M vs $3.00/1M for regular input
            cache_read_cost = (cache_read_tokens / 1_000_000) * cache_prices["cache_read"]
            regular_cost = (cache_read_tokens / 1_000_000) * cache_prices["cache_write_base"]
            savings = regular_cost - cache_read_cost
            result["cache_savings_usd"] = round(savings, 6)
        elif provider == "openai":
            # OpenAI has 50% discount on cached tokens
            cache_read_cost = (cache_read_tokens / 1_000_000) * cache_prices["cache_read"]
            regular_cost = (cache_read_tokens / 1_000_000) * 3.00  # Approximate for GPT-4
            savings = regular_cost - cache_read_cost
            result["cache_savings_usd"] = round(savings, 6)
        result["cache_hit"] = True
    
    return result

