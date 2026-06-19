"""Regression tests for generate_image aspect-ratio mapping."""
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import generate_image


class GenerateImageAspectTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
