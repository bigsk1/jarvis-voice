"""Regression tests for generate_image aspect-ratio mapping."""
import base64
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from google import genai
from google.genai import types

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import generate_image


class _FakeModels:
    def __init__(self, response, captured):
        self.response = response
        self.captured = captured

    def generate_content(self, **kwargs):
        self.captured.update(kwargs)
        return self.response


class _FakeClient:
    def __init__(self, response, captured):
        self.models = _FakeModels(response, captured)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class GenerateImageAspectTests(unittest.TestCase):
    def test_commented_out_model_env_uses_catalog_default(self):
        with patch.object(generate_image, "get_config_value", side_effect=lambda _key, default=None: default):
            model = generate_image._resolve_configured_image_model("gemini")

        self.assertEqual(model, "gemini-3.1-flash-image")

    def test_gemini_literal_ratios_from_tool_schema(self):
        """LLM often passes enum values like 16:9; must not fall back to 1:1."""
        for key, expected in (
            ("16:9", "16:9"),
            ("9:16", "9:16"),
            ("1:1", "1:1"),
            ("4:3", "4:3"),
            ("landscape", "16:9"),
            ("square", "1:1"),
        ):
            with self.subTest(key=key):
                got = generate_image.GEMINI_ASPECT_RATIOS.get(key, "1:1")
                self.assertEqual(got, expected)

    @staticmethod
    def _response(*, grounding=False):
        metadata = None
        if grounding:
            metadata = types.GroundingMetadata(
                web_search_queries=["current Portland weather"],
                image_search_queries=["Portland skyline"],
                grounding_chunks=[
                    types.GroundingChunk(
                        web=types.GroundingChunkWeb(
                            title="Weather source",
                            uri="https://example.com/weather",
                        )
                    )
                ],
            )
        return types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(text="Generated with current data"),
                            types.Part(
                                inline_data=types.Blob(
                                    data=b"generated-image-bytes",
                                    mime_type="image/png",
                                )
                            ),
                        ],
                    ),
                    grounding_metadata=metadata,
                )
            ]
        )

    @staticmethod
    def _config_value(key, default=None):
        values = {
            "GEMINI_API_KEY": "test-key",
            "GEMINI_IMAGE_MODEL": "gemini-3.1-flash-image",
        }
        return values.get(key, default)

    def test_gemini_sdk_generation_preserves_size_ratio_and_grounding(self):
        captured = {}
        fake_client = _FakeClient(self._response(grounding=True), captured)

        with patch.object(generate_image, "get_config_value", side_effect=self._config_value), patch.object(
            genai, "Client", return_value=fake_client
        ):
            result = generate_image.generate_image_gemini(
                "A current weather infographic",
                aspect_ratio="4:5",
                image_size="4K",
                use_grounding=True,
            )

        config = captured["config"]
        self.assertEqual(captured["model"], "gemini-3.1-flash-image")
        self.assertEqual(config.image_config.aspect_ratio, "4:5")
        self.assertEqual(config.image_config.image_size, "4K")
        self.assertEqual(config.http_options.timeout, 300_000)
        self.assertIsNotNone(config.tools[0].google_search)
        self.assertEqual(base64.b64decode(result["image_base64"]), b"generated-image-bytes")
        self.assertEqual(result["grounding"]["search_queries"], ["current Portland weather"])
        self.assertEqual(result["grounding"]["sources"][0]["title"], "Weather source")

    def test_gemini_sdk_edit_passes_reference_image_as_bytes(self):
        captured = {}
        fake_client = _FakeClient(self._response(), captured)
        encoded_reference = base64.b64encode(b"reference-image-bytes").decode("ascii")

        with patch.object(generate_image, "get_config_value", side_effect=self._config_value), patch.object(
            generate_image,
            "_resolve_image_to_base64",
            return_value=(encoded_reference, "image/jpeg"),
        ), patch.object(genai, "Client", return_value=fake_client):
            result = generate_image.generate_image_gemini(
                "Change the sky to sunset",
                reference_image="stash://space/file",
            )

        content = captured["contents"]
        self.assertEqual(content.parts[0].inline_data.data, b"reference-image-bytes")
        self.assertEqual(content.parts[0].inline_data.mime_type, "image/jpeg")
        self.assertTrue(content.parts[1].text.startswith("Edit this image:"))
        self.assertEqual(captured["config"].http_options.timeout, 180_000)
        self.assertIsNone(captured["config"].tools)
        self.assertTrue(result["is_edit"])


if __name__ == "__main__":
    unittest.main()
