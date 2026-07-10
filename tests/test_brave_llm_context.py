import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch


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

    def _run_main_and_capture_request(self, args):
        captured = {}

        def fake_http_request(method, endpoint, **kwargs):
            captured["method"] = method
            captured["endpoint"] = endpoint
            captured["json"] = kwargs.get("json")
            return SimpleNamespace(
                status_code=200,
                json=lambda: {"grounding": {"generic": []}, "sources": {}},
                text="{}",
            )

        with patch.object(self.mod, "load_config"), \
             patch.object(self.mod, "get_config_value", return_value="brave-key"), \
             patch.object(self.mod, "http_request", side_effect=fake_http_request), \
             patch.object(sys, "argv", ["brave_llm_context.py", json.dumps(args)]), \
             redirect_stdout(io.StringIO()):
            exit_code = self.mod.main()

        self.assertEqual(exit_code, 0)
        return captured["json"]

    def test_enable_source_metadata_defaults_false(self):
        body = self._run_main_and_capture_request({"query": "latest AI news"})

        self.assertIs(body["enable_source_metadata"], False)

    def test_enable_source_metadata_can_be_enabled_explicitly(self):
        body = self._run_main_and_capture_request({
            "query": "latest AI news",
            "enable_source_metadata": True,
        })

        self.assertIs(body["enable_source_metadata"], True)


if __name__ == "__main__":
    unittest.main()
