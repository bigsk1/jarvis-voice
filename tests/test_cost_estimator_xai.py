"""xAI tiered-pricing regression tests."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from cost_estimator import estimate_cost


def test_xai_standard_context_uses_base_catalog_pricing():
    result = estimate_cost("xai", "grok-4.3", 100_000, 10_000)

    assert result["cost_usd"] == 0.15
    assert result["note"] is None


def test_xai_long_context_uses_higher_api_tier():
    result = estimate_cost("xai", "grok-4.3", 200_000, 10_000)

    assert result["cost_usd"] == 0.55
    assert "long-context pricing" in result["note"]
