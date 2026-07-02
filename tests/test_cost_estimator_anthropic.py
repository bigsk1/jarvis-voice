"""Anthropic model-aware cache-pricing regression tests."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from cost_estimator import estimate_cache_cost


def test_fable_first_request_prices_five_minute_cache_creation_without_savings():
    result = estimate_cache_cost(
        "anthropic",
        "claude-fable-5",
        cache_creation_tokens=24_473,
        cache_creation_5m_tokens=24_473,
    )

    assert result["cache_write_cost_usd"] == 0.305913
    assert result["cache_read_cost_usd"] == 0.0
    assert result["cache_savings_usd"] == 0.0
    assert result["cache_hit"] is False
    assert result["cache_rates_usd_per_million"]["write_5m"] == 12.5


def test_fable_followup_prices_cache_read_and_reports_real_savings():
    result = estimate_cache_cost(
        "anthropic",
        "claude-fable-5",
        cache_read_tokens=24_473,
    )

    assert result["cache_read_cost_usd"] == 0.024473
    assert result["cache_savings_usd"] == 0.220257
    assert result["cache_hit"] is True


def test_cache_rates_follow_selected_model_instead_of_anthropic_default():
    fable = estimate_cache_cost("anthropic", "claude-fable-5", cache_creation_tokens=1_000)
    sonnet = estimate_cache_cost("anthropic", "claude-sonnet-5", cache_creation_tokens=1_000)

    assert fable["cache_write_cost_usd"] == 0.0125
    assert sonnet["cache_write_cost_usd"] == 0.0025


def test_one_hour_cache_creation_uses_two_times_input_rate():
    result = estimate_cache_cost(
        "anthropic",
        "claude-fable-5",
        cache_creation_tokens=1_000,
        cache_creation_1h_tokens=1_000,
    )

    assert result["cache_creation_5m_tokens"] == 0
    assert result["cache_creation_1h_tokens"] == 1_000
    assert result["cache_write_cost_usd"] == 0.02
