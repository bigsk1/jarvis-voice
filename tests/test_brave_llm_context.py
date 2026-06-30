import importlib.util
import sys
import unittest
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "skills" / "brave_llm_context.py"
    spec = importlib.util.spec_from_file_location("brave_llm_context", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["brave_llm_context"] = module
    spec.loader.exec_module(module)
    return module


class BraveLlmContextHelpersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module()

    def test_compact_source_metadata_drops_thumbnails(self):
        compact = self.mod.compact_source_metadata({
            "https://example.com/a": {
                "title": "Example A",
                "site_name": "Example",
                "hostname": "example.com",
                "age": ["2 days ago"],
                "favicon": "https://example.com/favicon.ico",
                "thumbnail": {"src": "https://cdn.example/thumb.jpg", "original": "https://example.com/t.jpg"},
            }
        })

        self.assertEqual(compact["https://example.com/a"]["site_name"], "Example")
        self.assertEqual(compact["https://example.com/a"]["favicon"], "https://example.com/favicon.ico")
        self.assertNotIn("thumbnail", compact["https://example.com/a"])

    def test_enrich_items_with_sources_adds_site_name_and_age(self):
        items = [{"title": "Story", "url": "https://news.example/story", "snippets": ["Body"]}]
        sources = {
            "https://news.example/story": {
                "site_name": "Example News",
                "age": ["1 hour ago", "2026-06-30"],
            }
        }

        enriched = self.mod.enrich_items_with_sources(items, sources)

        self.assertEqual(enriched[0]["site_name"], "Example News")
        self.assertEqual(enriched[0]["age"], "1 hour ago")


if __name__ == "__main__":
    unittest.main()
