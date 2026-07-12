#!/usr/bin/env python3
"""
Cost estimation for LLM API calls.
Provides token usage tracking and cost estimates for cloud providers.
"""

from model_catalog import (
    ANTHROPIC_CACHE_WRITE_1H_MULTIPLIER,
    ANTHROPIC_CACHE_WRITE_5M_MULTIPLIER,
    get_model_pricing,
)

# Pricing fallback table for non-catalog or specialized models.
#
# Source of truth:
# - Curated cloud chat model pricing now lives in lib/model_catalog.py
# - This file keeps the calculator logic plus fallback pricing for older,
#   specialized, or non-curated models
#
# Pricing as of November 2025 (USD per million tokens)
# Note: User is Tier 3 with Anthropic
PRICING = {
    "openai": {
        # GPT-5 series (Aug 2025) - Official pricing from openai.com/api/pricing
        "gpt-5": {"input": 1.25, "output": 10.00, "cached": 0.125},
        "gpt-5-2025-08-07": {"input": 1.25, "output": 10.00, "cached": 0.125},
        "gpt-5-chat-latest": {"input": 1.25, "output": 10.00, "cached": 0.125},
        "gpt-5-mini-2025-08-07": {"input": 0.25, "output": 2.00, "cached": 0.025},
        "gpt-5-pro": {"input": 15.00, "output": 120.00},
        "gpt-5-pro-2025-10-06": {"input": 15.00, "output": 120.00},
        
        # GPT-4.1 series (Apr 2025) - Based on fine-tuning pricing
        "gpt-4.1-mini": {"input": 0.15, "output": 2.00, "cached": 0.025},
        "gpt-4.1-mini-2025-04-14": {"input": 0.15, "output": 2.00, "cached": 0.025},
        "gpt-4.1-nano": {"input": 0.05, "output": 0.40, "cached": 0.005},
        "gpt-4.1-nano-2025-04-14": {"input": 0.05, "output": 0.40, "cached": 0.005},
        
        # GPT-4o series (specialized / legacy compatibility)
        "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cached": 0.025},
        "chatgpt-4o-latest": {"input": 3.00, "output": 12.00, "cached": 0.75},
        
        # Specialized models (estimated pricing based on model tier)
        "gpt-4o-audio-preview": {"input": 3.00, "output": 12.00},
        "gpt-4o-mini-audio-preview": {"input": 0.25, "output": 2.00},
        "gpt-audio": {"input": 3.00, "output": 12.00},
        "gpt-audio-mini": {"input": 0.25, "output": 2.00},
        "gpt-4o-realtime-preview": {"input": 3.00, "output": 12.00},
        "gpt-4o-mini-realtime-preview": {"input": 0.25, "output": 2.00},
        "gpt-realtime": {"input": 3.00, "output": 12.00},
        "gpt-realtime-mini": {"input": 0.25, "output": 2.00},
        "gpt-4o-transcribe": {"input": 0.25, "output": 2.00},
        "gpt-4o-mini-transcribe": {"input": 0.05, "output": 0.40},
        "gpt-4o-mini-tts": {"input": 0.05, "output": 0.40},
        # GPT-4 Turbo (still available, estimated pricing)
        "gpt-4": {"input": 30.00, "output": 60.00},
        "gpt-4-turbo": {"input": 10.00, "output": 30.00},
        "gpt-4-turbo-2024-04-09": {"input": 10.00, "output": 30.00},
    },
    "anthropic": {
        # Claude 4 / 3 fallback families not yet curated in the catalog
        "opus-4.1": {"input": 15.00, "output": 75.00},
        "haiku-4.5": {"input": 1.00, "output": 5.00},
        "sonnet-3.7": {"input": 3.00, "output": 15.00},
        "haiku-3.5": {"input": 0.80, "output": 4.00},
        "opus-3": {"input": 15.00, "output": 75.00},
        "haiku-3": {"input": 0.25, "output": 1.25},
    },
    "xai": {
        # Current curated xAI chat model pricing lives in lib/model_catalog.py.
    }
}


# Legacy cache-pricing fallbacks for models absent from the shared catalog.
# Curated Anthropic models derive cache rates from their own catalog entry.
CACHE_PRICING = {
    "anthropic": {
        # Sonnet-family fallback only; curated models do not use these values.
        "cache_write_base": 3.00,      # Regular input cost
        "cache_write_additional": 0.75, # Additional cost for cache write (+25%)
        "cache_read": 0.30,             # Cache read cost (90% discount)
    },
    "openai": {
        # OpenAI has automatic caching, different pricing
        "cache_read": 1.50,  # 50% discount on cached tokens
    },
    "xai": {
        # xAI has automatic caching (like OpenAI, no cache_control needed)
        # Default Grok 4.3 pricing is $1.25 input / $0.20 cached input per 1M.
        "cache_read": 0.20,
        "cache_write_base": 1.25,
    }
}


def estimate_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> dict:
    """
    Estimate cost for an LLM API call.
    
    Args:
        provider: "openai", "anthropic", or "xai"
        model: Model name
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
    
    Returns:
        Dict with token counts and cost estimates
    
    Notes:
        - Curated models use the shared catalog; legacy fallbacks retain older estimates.
        - Catalog-defined long-context tiers are selected from the input token count.
        - xAI chat pricing is audited against the live xAI model APIs.
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
    model_pricing = get_model_pricing(provider, model_normalized) or PRICING[provider].get(model_normalized)
    
    if not model_pricing:
        # Try partial match (e.g., "gpt-4.1-mini-2025" matches "gpt-4.1-mini")
        for known_model, prices in PRICING[provider].items():
            if known_model in model_normalized or model_normalized in known_model:
                model_pricing = prices
                break
    
    cost = None
    note = None
    
    if model_pricing:
        effective_pricing = model_pricing
        long_context = model_pricing.get("long_context")
        if long_context and input_tokens >= int(long_context["threshold"]):
            effective_pricing = long_context
            note = f"Using long-context pricing for prompts at or above {long_context['threshold']:,} tokens"
        input_cost = (input_tokens / 1_000_000) * effective_pricing["input"]
        output_cost = (output_tokens / 1_000_000) * effective_pricing["output"]
        cost = round(input_cost + output_cost, 6)
        
        # Note if using Sonnet 4.5 with large context
        if "sonnet-4.5" in model_normalized or "sonnet-4-5" in model_normalized:
            if input_tokens > 200_000:
                note = note or "Using base tier pricing; actual cost may be higher for >200K token prompts"
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


def estimate_cache_cost(
    provider: str,
    model: str,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_5m_tokens: int | None = None,
    cache_creation_1h_tokens: int | None = None,
) -> dict:
    """
    Estimate cache-related costs for prompt caching.
    
    Args:
        provider: "openai", "anthropic", or "xai"
        model: Model name (for future model-specific cache pricing)
        cache_creation_tokens: Aggregate tokens written to cache (first request)
        cache_read_tokens: Tokens read from cache (subsequent requests)
        cache_creation_5m_tokens: Anthropic 5-minute cache-write tokens, when reported
        cache_creation_1h_tokens: Anthropic 1-hour cache-write tokens, when reported
    
    Returns:
        Dict with cache metrics and savings
        {
            "cache_creation_tokens": int,
            "cache_read_tokens": int,
            "cache_write_cost_usd": float (full cache-write cost),
            "cache_read_cost_usd": float,
            "cache_cost_usd": float,
            "cache_savings_usd": float (savings from cache read),
            "cache_hit": bool,
            "note": str (if fallback used)
        }
    
    Notes:
        - Pricing as of July 2026
        - Anthropic rates are derived from the selected model's catalog pricing.
          Five-minute writes cost 1.25x input, one-hour writes 2x, and reads
          use the model's cached-input rate.
        - OpenAI: Automatic caching, 50% discount on cached tokens
        - OpenAI/xAI legacy cache estimates are retained for non-catalog paths.
        - Falls back gracefully for unknown providers
    """
    result = {
        "cache_creation_tokens": cache_creation_tokens,
        "cache_creation_5m_tokens": 0,
        "cache_creation_1h_tokens": 0,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_cost_usd": 0.0,
        "cache_read_cost_usd": 0.0,
        "cache_cost_usd": 0.0,
        "cache_savings_usd": 0.0,
        "cache_hit": False,
        "note": None
    }
    
    # Check if provider supports caching
    if provider not in CACHE_PRICING:
        result["note"] = f"Cache pricing unknown for provider: {provider}"
        return result
    
    cache_prices = CACHE_PRICING[provider]
    
    model_prices = get_model_pricing(provider, model)

    if provider == "anthropic" and model_prices:
        five_minute_tokens = max(0, int(cache_creation_5m_tokens or 0))
        one_hour_tokens = max(0, int(cache_creation_1h_tokens or 0))
        # Older SDK responses only provide the aggregate. Jarvis cache_control
        # uses Anthropic's default five-minute TTL unless an explicit TTL is set.
        unclassified_tokens = max(
            0,
            int(cache_creation_tokens or 0) - five_minute_tokens - one_hour_tokens,
        )
        five_minute_tokens += unclassified_tokens
        result["cache_creation_5m_tokens"] = five_minute_tokens
        result["cache_creation_1h_tokens"] = one_hour_tokens

        input_rate = float(model_prices["input"])
        cached_rate = float(model_prices.get("cached", input_rate))
        write_cost = (
            (five_minute_tokens / 1_000_000)
            * input_rate
            * ANTHROPIC_CACHE_WRITE_5M_MULTIPLIER
            + (one_hour_tokens / 1_000_000) * input_rate * ANTHROPIC_CACHE_WRITE_1H_MULTIPLIER
        )
        read_cost = (cache_read_tokens / 1_000_000) * cached_rate
        regular_read_cost = (cache_read_tokens / 1_000_000) * input_rate

        result["cache_write_cost_usd"] = round(write_cost, 6)
        result["cache_read_cost_usd"] = round(read_cost, 6)
        result["cache_cost_usd"] = round(write_cost + read_cost, 6)
        result["cache_savings_usd"] = round(regular_read_cost - read_cost, 6)
        result["cache_hit"] = cache_read_tokens > 0
        result["cache_rates_usd_per_million"] = {
            "write_5m": input_rate * ANTHROPIC_CACHE_WRITE_5M_MULTIPLIER,
            "write_1h": input_rate * ANTHROPIC_CACHE_WRITE_1H_MULTIPLIER,
            "read": cached_rate,
        }
        return result

    # Legacy provider fallback when model-specific metadata is unavailable.
    if cache_creation_tokens > 0:
        if provider == "anthropic":
            # Legacy Sonnet fallback: full five-minute write price is $3.75/M.
            cache_write_rate = (
                cache_prices["cache_write_base"] + cache_prices["cache_write_additional"]
            )
            cache_write_cost = (cache_creation_tokens / 1_000_000) * cache_write_rate
            result["cache_write_cost_usd"] = round(cache_write_cost, 6)
        result["cache_hit"] = False
    
    # Calculate cache read savings
    if cache_read_tokens > 0:
        if provider == "anthropic":
            # Cache read costs $0.30/1M vs $3.00/1M for regular input
            cache_read_cost = (cache_read_tokens / 1_000_000) * cache_prices["cache_read"]
            regular_cost = (cache_read_tokens / 1_000_000) * cache_prices["cache_write_base"]
            savings = regular_cost - cache_read_cost
            result["cache_read_cost_usd"] = round(cache_read_cost, 6)
            result["cache_savings_usd"] = round(savings, 6)
        elif provider == "openai":
            # OpenAI has 50% discount on cached tokens
            cache_read_cost = (cache_read_tokens / 1_000_000) * cache_prices["cache_read"]
            regular_cost = (cache_read_tokens / 1_000_000) * 3.00  # Approximate for GPT-4
            savings = regular_cost - cache_read_cost
            result["cache_read_cost_usd"] = round(cache_read_cost, 6)
            result["cache_savings_usd"] = round(savings, 6)
        elif provider == "xai":
            # xAI automatic cache pricing for the default Grok 4.3 model.
            cache_read_cost = (cache_read_tokens / 1_000_000) * cache_prices["cache_read"]
            regular_cost = (cache_read_tokens / 1_000_000) * cache_prices["cache_write_base"]
            savings = regular_cost - cache_read_cost
            result["cache_read_cost_usd"] = round(cache_read_cost, 6)
            result["cache_savings_usd"] = round(savings, 6)
        result["cache_hit"] = True

    result["cache_cost_usd"] = round(
        result["cache_write_cost_usd"] + result["cache_read_cost_usd"], 6
    )
    
    return result
