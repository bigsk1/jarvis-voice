#!/usr/bin/env python3
"""
Regression tests for the shared model catalog.

Run:
    python3 tests/test_model_catalog.py
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from lib.model_catalog import (
    get_default_media_model_id,
    get_media_model_env_key,
    get_media_model_pricing,
    get_media_model_metadata,
    get_media_provider_options,
    get_default_model_id,
    get_model_context_label,
    get_model_context_window,
    get_model_metadata,
    get_model_pricing,
    get_model_xai_reasoning_effort_values,
    get_model_supports_xai_reasoning,
    get_model_supports_xai_reasoning_effort,
    get_provider_fallback_model,
    get_provider_model_options,
    resolve_media_model,
)


class ModelCatalogTests(unittest.TestCase):
    def test_media_defaults_are_centralized(self):
        self.assertEqual(get_default_media_model_id("image", "gemini"), "gemini-3.1-flash-image")
        self.assertEqual(get_default_media_model_id("image", "openai"), "gpt-image-2")
        self.assertEqual(get_default_media_model_id("image", "xai"), "grok-imagine-image")
        self.assertEqual(get_default_media_model_id("video", "gemini"), "veo-3.1-fast-generate-preview")
        self.assertEqual(get_default_media_model_id("video", "openai"), "sora-2")
        self.assertEqual(get_default_media_model_id("video", "xai"), "grok-imagine-video")
        self.assertEqual(get_default_media_model_id("music", "elevenlabs"), "music_v1")
        self.assertEqual(get_default_media_model_id("music", "gemini"), "lyria-3-clip-preview")

    def test_media_env_keys_and_ui_provider_metadata_come_from_catalog(self):
        self.assertEqual(get_media_model_env_key("image", "gemini"), "GEMINI_IMAGE_MODEL")
        self.assertEqual(get_media_model_env_key("video", "openai"), "OPENAI_VIDEO_MODEL")
        self.assertEqual(get_media_model_env_key("music", "elevenlabs"), "ELEVENLABS_MUSIC_MODEL")
        self.assertEqual(get_media_model_env_key("music", "gemini"), "GEMINI_MUSIC_MODEL")
        self.assertEqual(get_media_provider_options("image")["gemini"]["model"], "gemini-3.1-flash-image")
        self.assertEqual(get_media_provider_options("image")["gemini"]["model_name"], "Gemini 3.1 Flash Image")
        self.assertEqual(get_media_provider_options("video")["xai"]["model"], "grok-imagine-video")
        self.assertEqual(
            get_media_provider_options("video")["gemini"]["resolutions"],
            ["720p", "1080p", "4k"],
        )
        music_options = get_media_provider_options("music")
        self.assertEqual(music_options["elevenlabs"]["model"], "music_v1")
        self.assertEqual(music_options["gemini"]["model"], "lyria-3-clip-preview")
        self.assertIn("synthid", music_options["gemini"]["capabilities"])
        lyria_pro = get_media_model_metadata(
            "music",
            "gemini",
            "lyria-3-pro-preview",
        )
        self.assertIn("full_length", lyria_pro["capabilities"])
        self.assertEqual(lyria_pro["output_formats"], ["mp3", "wav"])
        self.assertFalse(lyria_pro.get("default", False))

    def test_media_provider_options_follow_explicit_model_pin_capabilities(self):
        options = get_media_provider_options(
            "video",
            {
                "openai": "sora-2-pro",
                "xai": "grok-imagine-video-1.5",
                "gemini": "gemini-omni-flash-preview",
            },
        )
        self.assertEqual(options["openai"]["model"], "sora-2-pro")
        self.assertEqual(options["openai"]["resolutions"], ["720p", "1080p"])
        self.assertEqual(options["xai"]["resolutions"], ["1080p", "720p", "480p"])
        self.assertEqual(options["gemini"]["model"], "gemini-omni-flash-preview")
        self.assertEqual(options["gemini"]["resolutions"], ["720p"])
        self.assertEqual(
            get_media_model_metadata("video", "gemini", "gemini-omni-flash-preview")["api"],
            "interactions",
        )

        openai_image = get_media_provider_options(
            "image", {"openai": "gpt-image-1.5"}
        )["openai"]
        self.assertEqual(openai_image["model_name"], "GPT Image 1.5")
        self.assertIn("transparent_background", openai_image["capabilities"])

    def test_media_resolution_defaults_empty_values_and_preserves_unknown_pins(self):
        self.assertEqual(resolve_media_model("image", "openai"), "gpt-image-2")
        self.assertEqual(resolve_media_model("image", "openai", ""), "gpt-image-2")
        self.assertEqual(resolve_media_model("image", "openai", "future-image-model"), "future-image-model")
        self.assertEqual(resolve_media_model("music", "elevenlabs", "music_v2"), "music_v2")

    def test_retired_media_models_resolve_to_replacements(self):
        with self.assertLogs("lib.model_catalog", level="WARNING") as captured:
            model = resolve_media_model("image", "gemini", "gemini-3.1-flash-image-preview")
        self.assertEqual(model, "gemini-3.1-flash-image")
        self.assertTrue(any("Replacing retired image model" in line for line in captured.output))
        self.assertEqual(
            resolve_media_model("video", "gemini", "veo-3.0-fast-generate-001"),
            "veo-3.1-fast-generate-preview",
        )

    def test_media_pricing_preserves_provider_specific_units(self):
        gemini_image = get_media_model_pricing("image", "gemini", "gemini-3.1-flash-image")
        self.assertEqual(gemini_image["unit"], "image")
        self.assertEqual(gemini_image["usd_by_size"]["4K"], 0.151)
        xai_video = get_media_model_pricing("video", "xai", "grok-imagine-video")
        self.assertEqual(xai_video["unit"], "second")
        self.assertEqual(xai_video["usd_by_resolution"]["720p"], 0.07)
        omni_video = get_media_model_pricing("video", "gemini", "gemini-omni-flash-preview")
        self.assertEqual(omni_video["usd_by_resolution"]["720p"], 0.10)
        lyria = get_media_model_pricing("music", "gemini", "lyria-3-clip-preview")
        self.assertEqual(lyria, {"unit": "request", "usd": 0.04})
        lyria_pro = get_media_model_pricing("music", "gemini", "lyria-3-pro-preview")
        self.assertEqual(lyria_pro, {"unit": "request", "usd": 0.08})

    def test_openai_options_are_newest_first(self):
        models = [entry["id"] for entry in get_provider_model_options("openai")]
        self.assertEqual(
            models[:7],
            [
                "gpt-5.6-sol",
                "gpt-5.6-terra",
                "gpt-5.6-luna",
                "gpt-5.5",
                "gpt-5.4",
                "gpt-5.4-mini",
                "gpt-5.4-nano",
            ],
        )

    def test_provider_options_distinguish_catalog_defaults(self):
        for provider, model_id in (
            ("xai", "grok-4.5"),
            ("anthropic", "claude-sonnet-5"),
            ("openai", "gpt-5.6-luna"),
        ):
            options = {
                entry["id"]: entry
                for entry in get_provider_model_options(provider)
            }
            self.assertIn("(Catalog default)", options[model_id]["name"])

    def test_gpt_5_6_models_resolve_with_pricing(self):
        self.assertEqual(get_model_context_window("openai", "gpt-5.6-luna"), 1_050_000)
        self.assertEqual(get_model_context_window("openai", "gpt-5.6"), 1_050_000)
        self.assertEqual(get_model_context_label("openai", "gpt-5.6-luna"), "1.05M")
        self.assertEqual(get_model_metadata("openai", "gpt-5.6")["id"], "gpt-5.6-sol")

        sol_pricing = get_model_pricing("openai", "gpt-5.6-sol")
        self.assertIsNotNone(sol_pricing)
        self.assertEqual(sol_pricing["input"], 10.00)
        self.assertEqual(sol_pricing["cached"], 1.00)
        self.assertEqual(sol_pricing["output"], 60.00)

        luna_pricing = get_model_pricing("openai", "gpt-5.6-luna")
        self.assertIsNotNone(luna_pricing)
        self.assertEqual(luna_pricing["input"], 2.00)
        self.assertEqual(luna_pricing["cached"], 0.20)
        self.assertEqual(luna_pricing["output"], 12.00)

    def test_gpt_5_5_resolves_with_pricing(self):
        self.assertEqual(get_model_context_window("openai", "gpt-5.5"), 1_050_000)
        self.assertEqual(get_model_context_window("openai", "gpt-5.5-2026-04-23"), 1_050_000)
        self.assertEqual(get_model_context_label("openai", "gpt-5.5"), "1.05M")
        pricing = get_model_pricing("openai", "gpt-5.5")
        self.assertIsNotNone(pricing)
        self.assertEqual(pricing["input"], 5.00)
        self.assertEqual(pricing["cached"], 0.50)
        self.assertEqual(pricing["output"], 30.00)

    def test_xai_options_match_current_catalog(self):
        models = [entry["id"] for entry in get_provider_model_options("xai")]
        self.assertEqual(
            models[:5],
            [
                "grok-4.5",
                "grok-4.3",
                "grok-build-0.1",
                "grok-4.20-0309-reasoning",
                "grok-4.20-0309-non-reasoning",
            ],
        )
        self.assertNotIn("grok-4-fast", models)
        self.assertNotIn("grok-4-1-fast-reasoning-latest", models)
        self.assertNotIn("grok-4-1-fast-non-reasoning-latest", models)
        self.assertEqual(get_model_context_label("xai", "grok-4.20-reasoning"), "1M")
        self.assertEqual(get_model_context_window("xai", "grok-4.20-reasoning"), 1_000_000)

    def test_grok_4_5_variant_resolves_with_pricing(self):
        self.assertEqual(get_model_context_window("xai", "grok-4.5"), 500_000)
        self.assertEqual(get_model_context_window("xai", "grok-4.5-latest"), 500_000)
        self.assertEqual(get_model_context_window("xai", "grok-build-latest"), 500_000)
        self.assertEqual(get_model_context_label("xai", "grok-4.5"), "500K")
        self.assertEqual(get_model_metadata("xai", "grok-build-latest")["id"], "grok-4.5")
        pricing = get_model_pricing("xai", "grok-4.5")
        self.assertIsNotNone(pricing)
        self.assertEqual(pricing["input"], 2.00)
        self.assertEqual(pricing["cached"], 0.50)
        self.assertEqual(pricing["output"], 6.00)

    def test_retired_xai_models_are_not_curated(self):
        models = [entry["id"] for entry in get_provider_model_options("xai")]
        self.assertNotIn("grok-4-1-fast-reasoning-latest", models)
        self.assertNotIn("grok-4-1-reasoning-latest", models)

        metadata = get_model_metadata("xai", "grok-4-1-reasoning-latest")
        self.assertIsNone(metadata)

    def test_grok_4_20_variant_resolves_with_pricing(self):
        self.assertEqual(get_model_context_window("xai", "grok-4.20-reasoning"), 1_000_000)
        self.assertEqual(get_model_context_window("xai", "grok-4.20-0309-reasoning"), 1_000_000)
        self.assertEqual(get_model_context_window("xai", "grok-4.20-non-reasoning-latest"), 1_000_000)
        self.assertEqual(get_model_context_window("xai", "grok-4.20-0309-non-reasoning"), 1_000_000)
        pricing = get_model_pricing("xai", "grok-4.20-reasoning")
        self.assertIsNotNone(pricing)
        self.assertEqual(pricing["input"], 1.25)
        self.assertEqual(pricing["output"], 2.50)
        self.assertEqual(pricing["cached"], 0.20)
        self.assertEqual(pricing["long_context"]["threshold"], 200_000)

    def test_grok_4_3_variant_resolves_with_pricing(self):
        self.assertEqual(get_model_context_window("xai", "grok-4.3"), 1_000_000)
        self.assertEqual(get_model_context_window("xai", "grok-4.3-latest"), 1_000_000)
        pricing = get_model_pricing("xai", "grok-4.3")
        self.assertIsNotNone(pricing)
        self.assertEqual(pricing["input"], 1.25)
        self.assertEqual(pricing["cached"], 0.20)
        self.assertEqual(pricing["output"], 2.50)

    def test_grok_build_0_1_resolves_with_pricing(self):
        self.assertEqual(get_model_context_window("xai", "grok-build-0.1"), 256_000)
        self.assertEqual(get_model_context_window("xai", "grok-build"), 256_000)
        self.assertEqual(get_model_context_label("xai", "grok-build-0.1"), "256K")
        self.assertEqual(get_model_metadata("xai", "grok-build")["id"], "grok-build-0.1")
        pricing = get_model_pricing("xai", "grok-build-0.1")
        self.assertIsNotNone(pricing)
        self.assertEqual(pricing["input"], 1.00)
        self.assertEqual(pricing["output"], 2.00)

    def test_provider_options_expose_only_known_vision_capabilities(self):
        xai = {entry["id"]: entry for entry in get_provider_model_options("xai")}
        anthropic = {entry["id"]: entry for entry in get_provider_model_options("anthropic")}
        openai = {entry["id"]: entry for entry in get_provider_model_options("openai")}

        # API-key Grok Build accepts images; OAuth transport capabilities are
        # advertised separately from the developer API catalog.
        self.assertTrue(xai["grok-4.5"]["vision"])
        self.assertIn("vision", xai["grok-4.5"]["capabilities"])
        self.assertIn("thinking", xai["grok-4.5"]["capabilities"])
        self.assertIn("tools", xai["grok-4.5"]["capabilities"])
        self.assertTrue(xai["grok-build-0.1"]["vision"])
        self.assertIn("vision", xai["grok-build-0.1"]["capabilities"])
        self.assertIn("tools", xai["grok-build-0.1"]["capabilities"])
        self.assertTrue(anthropic["claude-sonnet-5"]["vision"])
        self.assertTrue(openai["gpt-5.6-luna"]["vision"])
        self.assertIn("vision", openai["gpt-5.6-luna"]["capabilities"])
        self.assertIn("tools", openai["gpt-5.6-luna"]["capabilities"])
        self.assertTrue(openai["gpt-5.4-nano"]["vision"])
        self.assertIn("vision", openai["gpt-5.4-nano"]["capabilities"])

    def test_xai_reasoning_effort_flag_from_catalog(self):
        self.assertTrue(get_model_supports_xai_reasoning_effort("xai", "grok-4.5"))
        self.assertTrue(get_model_supports_xai_reasoning_effort("xai", "grok-4.5-latest"))
        self.assertTrue(get_model_supports_xai_reasoning_effort("xai", "grok-build-latest"))
        self.assertTrue(get_model_supports_xai_reasoning_effort("xai", "grok-4.3"))
        self.assertTrue(get_model_supports_xai_reasoning_effort("xai", "grok-4.3-latest"))
        self.assertFalse(get_model_supports_xai_reasoning_effort("xai", "grok-build-0.1"))
        self.assertFalse(get_model_supports_xai_reasoning_effort("xai", "grok-4.20-reasoning"))

    def test_xai_reasoning_effort_values_from_catalog(self):
        self.assertEqual(
            get_model_xai_reasoning_effort_values("xai", "grok-4.5"),
            ["low", "medium", "high"],
        )
        self.assertEqual(
            get_model_xai_reasoning_effort_values("xai", "grok-build-latest"),
            ["low", "medium", "high"],
        )
        self.assertEqual(
            get_model_xai_reasoning_effort_values("xai", "grok-4.3"),
            ["none", "low", "medium", "high"],
        )
        self.assertEqual(get_model_xai_reasoning_effort_values("xai", "grok-build-0.1"), [])

    def test_xai_reasoning_flag_from_catalog(self):
        self.assertTrue(get_model_supports_xai_reasoning("xai", "grok-4.5"))
        self.assertTrue(get_model_supports_xai_reasoning("xai", "grok-4.5-latest"))
        self.assertTrue(get_model_supports_xai_reasoning("xai", "grok-build-latest"))
        self.assertTrue(get_model_supports_xai_reasoning("xai", "grok-4.3"))
        self.assertTrue(get_model_supports_xai_reasoning("xai", "grok-4.20-reasoning"))
        self.assertFalse(get_model_supports_xai_reasoning("xai", "grok-4.20-non-reasoning"))

    def test_dated_openai_variant_resolves_to_family_metadata(self):
        self.assertEqual(get_model_context_window("openai", "gpt-5.4-nano-2026-03-17"), 400_000)
        pricing = get_model_pricing("openai", "gpt-5.4-nano-2026-03-17")
        self.assertIsNotNone(pricing)
        self.assertEqual(pricing["input"], 0.20)
        self.assertEqual(pricing["output"], 1.25)

    def test_gpt_5_4_mini_resolves_with_pricing(self):
        self.assertEqual(get_model_context_window("openai", "gpt-5.4-mini"), 400_000)
        pricing = get_model_pricing("openai", "gpt-5.4-mini")
        self.assertIsNotNone(pricing)
        self.assertEqual(pricing["input"], 0.75)
        self.assertEqual(pricing["cached"], 0.075)
        self.assertEqual(pricing["output"], 4.50)

    def test_anthropic_sonnet_5_resolves_with_pricing_and_context(self):
        self.assertEqual(get_model_context_window("anthropic", "claude-sonnet-5"), 1_000_000)
        self.assertEqual(get_model_context_label("anthropic", "claude-sonnet-5"), "1M")
        metadata = get_model_metadata("anthropic", "sonnet-5")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["id"], "claude-sonnet-5")
        self.assertEqual(metadata["max_output_tokens"], 128_000)
        self.assertTrue(metadata["capabilities"]["image_input"]["supported"])
        pricing = get_model_pricing("anthropic", "claude-sonnet-5")
        self.assertEqual(pricing["input"], 2.00)
        self.assertEqual(pricing["output"], 10.00)
        self.assertEqual(pricing["cached"], 0.20)

    def test_anthropic_sonnet_4_6_resolves_with_pricing_and_context(self):
        self.assertEqual(get_model_context_window("anthropic", "claude-sonnet-4-6"), 1_000_000)
        self.assertEqual(get_model_context_label("anthropic", "claude-sonnet-4-6"), "1M")
        metadata = get_model_metadata("anthropic", "sonnet-4.6")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["id"], "claude-sonnet-4-6")
        pricing = get_model_pricing("anthropic", "claude-sonnet-4-6")
        self.assertEqual(pricing["input"], 3.00)
        self.assertEqual(pricing["output"], 15.00)
        self.assertEqual(pricing["cached"], 0.30)

    def test_anthropic_options_include_sonnet_5_first(self):
        models = [entry["id"] for entry in get_provider_model_options("anthropic")]
        self.assertEqual(models[0], "claude-sonnet-5")
        self.assertIn("claude-fable-5", models)
        self.assertIn("claude-sonnet-4-6", models)
        self.assertLess(models.index("claude-sonnet-4-6"), models.index("claude-opus-4-8"))

    def test_anthropic_fable_5_resolves_with_pricing_and_context(self):
        self.assertEqual(get_model_context_window("anthropic", "claude-fable-5"), 1_000_000)
        self.assertEqual(get_model_context_label("anthropic", "claude-fable-5"), "1M")
        metadata = get_model_metadata("anthropic", "fable-5")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["id"], "claude-fable-5")
        self.assertEqual(metadata["max_output_tokens"], 128_000)
        pricing = get_model_pricing("anthropic", "claude-fable-5")
        self.assertEqual(pricing["input"], 10.00)
        self.assertEqual(pricing["output"], 50.00)
        self.assertEqual(pricing["cached"], 1.00)

    def test_retired_anthropic_models_resolve_to_replacements(self):
        sonnet = get_model_metadata("anthropic", "claude-sonnet-4-20250514")
        self.assertIsNotNone(sonnet)
        self.assertEqual(sonnet["id"], "claude-sonnet-4-6")

        opus = get_model_metadata("anthropic", "claude-opus-4-20250514")
        self.assertIsNotNone(opus)
        self.assertEqual(opus["id"], "claude-opus-4-8")

        self.assertEqual(get_model_metadata("anthropic", "sonnet-4")["id"], "claude-sonnet-4-6")
        self.assertEqual(get_model_metadata("anthropic", "opus-4")["id"], "claude-opus-4-8")

        retired_sonnet = [entry["id"] for entry in get_provider_model_options("anthropic")]
        self.assertNotIn("claude-sonnet-4-20250514", retired_sonnet)
        self.assertNotIn("claude-4-opus", retired_sonnet)

    def test_anthropic_opus_5_resolves_with_pricing_and_context(self):
        self.assertEqual(get_model_context_window("anthropic", "claude-opus-5"), 1_000_000)
        self.assertEqual(get_model_context_label("anthropic", "claude-opus-5"), "1M")
        metadata = get_model_metadata("anthropic", "opus-5")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["id"], "claude-opus-5")
        self.assertEqual(metadata["max_output_tokens"], 128_000)
        self.assertFalse(metadata.get("default", False))
        pricing = get_model_pricing("anthropic", "claude-opus-5")
        self.assertEqual(pricing["input"], 5.00)
        self.assertEqual(pricing["output"], 25.00)
        self.assertEqual(pricing["cached"], 0.50)

    def test_anthropic_opus_4_8_resolves_with_pricing_and_context(self):
        self.assertEqual(get_model_context_window("anthropic", "claude-opus-4-8"), 1_000_000)
        self.assertEqual(get_model_context_label("anthropic", "claude-opus-4-8"), "1M")
        metadata = get_model_metadata("anthropic", "opus-4.8")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["id"], "claude-opus-4-8")
        pricing = get_model_pricing("anthropic", "claude-opus-4-8")
        self.assertEqual(pricing["input"], 5.00)
        self.assertEqual(pricing["output"], 25.00)
        self.assertEqual(pricing["cached"], 0.50)

    def test_anthropic_options_include_opus_5_first_among_opus(self):
        models = [entry["id"] for entry in get_provider_model_options("anthropic")]
        opus_index = models.index("claude-opus-5")
        self.assertLess(opus_index, models.index("claude-opus-4-8"))
        self.assertLess(opus_index, models.index("claude-opus-4-7"))
        self.assertLess(opus_index, models.index("claude-opus-4-6"))

    def test_catalog_defaults_are_explicit(self):
        self.assertEqual(get_default_model_id("openai"), "gpt-5.6-luna")
        self.assertEqual(get_default_model_id("xai"), "grok-4.5")
        self.assertEqual(get_default_model_id("anthropic"), "claude-sonnet-5")

    def test_legacy_claude_4_5_alias_resolves_to_sonnet(self):
        metadata = get_model_metadata("anthropic", "claude-4-5")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["id"], "claude-sonnet-4-5-20250929")

    def test_latest_suffix_falls_back_to_family_match(self):
        metadata = get_model_metadata("xai", "grok-4.5-latest")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["id"], "grok-4.5")
        alias = get_model_metadata("xai", "grok-build-latest")
        self.assertIsNotNone(alias)
        self.assertEqual(alias["id"], "grok-4.5")
        family = get_model_metadata("xai", "grok-4.3-2026-05-06")
        self.assertIsNotNone(family)
        self.assertEqual(family["id"], "grok-4.3")

    def test_unknown_provider_default_warns_and_returns_empty(self):
        with self.assertLogs("lib.model_catalog", level="WARNING") as captured:
            result = get_default_model_id("not-a-provider")
        self.assertEqual(result, "")
        self.assertTrue(any("Unknown provider requested" in line for line in captured.output))

    def test_unknown_provider_metadata_warns_and_returns_none(self):
        with self.assertLogs("lib.model_catalog", level="WARNING") as captured:
            result = get_model_metadata("not-a-provider", "some-model")
        self.assertIsNone(result)
        self.assertTrue(any("Unknown provider requested for model metadata" in line for line in captured.output))

    def test_ollama_fallback_default_can_be_overridden(self):
        self.assertEqual(get_provider_fallback_model("ollama"), "gemma4")
        self.assertEqual(
            get_provider_fallback_model("ollama", local_default="gemma4"),
            "gemma4",
        )


if __name__ == "__main__":
    unittest.main()
