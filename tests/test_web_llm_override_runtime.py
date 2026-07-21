"""Regression coverage for Web LLM provider/model override dispatch."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from router_v2 import LLMRouter


def test_explicit_web_provider_and_model_reach_provider_factory_unchanged():
    router = LLMRouter.__new__(LLMRouter)
    router.mode = "cloud"
    router._provider_override = "openai"
    router._model_override = "gpt-5.6-terra"
    created_provider = MagicMock()

    with patch(
        "router_v2.create_configured_provider",
        return_value=("openai", "gpt-5.6-terra", created_provider),
    ) as create_provider:
        result = router._create_provider()

    assert result is created_provider
    create_provider.assert_called_once_with(
        provider_override="openai",
        model_override="gpt-5.6-terra",
        default_provider="openai",
        mode="cloud",
    )
    assert router.provider_type == "openai"
    assert router.model_name == "gpt-5.6-terra"
