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

    with (
        patch("router_v2.get_config_value", return_value="env-value") as get_config,
        patch("router_v2.create_provider", return_value=created_provider) as create_provider,
    ):
        result = router._create_provider()

    assert result is created_provider
    create_provider.assert_called_once_with(
        "openai",
        api_key="env-value",
        model="gpt-5.6-terra",
    )
    assert all(call.args[0] != "OPENAI_MODEL" for call in get_config.call_args_list)
