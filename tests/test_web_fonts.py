#!/usr/bin/env python3
"""Ensure fonts.css only references files that exist under jarvis-web/client/fonts."""

import re
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FONTS_CSS = PROJECT_ROOT / "jarvis-web" / "client" / "css" / "fonts.css"


def _purge_server_modules() -> None:
    for key in list(sys.modules.keys()):
        if key == "server" or key.startswith("server."):
            del sys.modules[key]
FONTS_DIR = PROJECT_ROOT / "jarvis-web" / "client" / "fonts"


class WebFontsTests(unittest.TestCase):
    def test_fonts_css_paths_exist(self):
        text = FONTS_CSS.read_text(encoding="utf-8")
        urls = re.findall(r"url\(['\"]?/fonts/([^'\")]+)['\"]?\)", text)
        self.assertTrue(urls, "expected at least one /fonts/ url in fonts.css")
        missing = []
        for name in urls:
            path = FONTS_DIR / name
            if not path.is_file():
                missing.append(name)
        self.assertFalse(missing, f"missing font files: {missing}")

    def test_required_woff2_present(self):
        """Minimal set referenced by fonts.css."""
        required = [
            "InterVariable.woff2",
            "Inter-Italic.woff2",
            "JetBrainsMono-Regular.woff2",
            "JetBrainsMono-Medium.woff2",
            "JetBrainsMono-SemiBold.woff2",
            "JetBrainsMono-Bold.woff2",
            "JetBrainsMono-Italic.woff2",
            "JetBrainsMono-BoldItalic.woff2",
        ]
        for name in required:
            with self.subTest(font=name):
                self.assertTrue((FONTS_DIR / name).is_file(), f"missing {name}")

    def test_01_jarvis_web_ui_serves_fonts(self):
        """Run before other server.* imports to avoid package name clashes."""
        _purge_server_modules()
        sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))
        from server.app import app

        with app.test_client() as client:
            r = client.get("/fonts/InterVariable.woff2")
            self.assertEqual(r.status_code, 200)
            self.assertGreater(len(r.data), 1000)
            r_css = client.get("/css/fonts.css")
            self.assertEqual(r_css.status_code, 200)
            self.assertIn(b"@font-face", r_css.data)

    def test_02_memory_browser_serves_shared_font_bytes(self):
        _purge_server_modules()
        web = str(PROJECT_ROOT / "jarvis-web")
        if web in sys.path:
            sys.path.remove(web)
        sys.path.insert(0, str(PROJECT_ROOT / "jarvis-memory"))
        from server.app import app as mem_app

        with (
            mock.patch.object(sys.modules["server.app"], "is_auth_enabled", return_value=True),
            mem_app.test_client() as client,
        ):
            r = client.get("/fonts/InterVariable.woff2")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data[:4], b"wOF2", "memory UI must return font bytes, not HTML fallback")

    def test_03_intelligence_browser_serves_shared_font_bytes(self):
        _purge_server_modules()
        for p in (str(PROJECT_ROOT / "jarvis-web"), str(PROJECT_ROOT / "jarvis-memory")):
            if p in sys.path:
                sys.path.remove(p)
        sys.path.insert(0, str(PROJECT_ROOT / "jarvis-intelligence"))
        from server.app import app as intelligence_app

        with (
            mock.patch.object(sys.modules["server.app"], "is_auth_enabled", return_value=True),
            intelligence_app.test_client() as client,
        ):
            r = client.get("/fonts/JetBrainsMono-Regular.woff2")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data[:4], b"wOF2", "intelligence UI must return font bytes, not HTML fallback")

    def test_04_canvas_static_fonts_and_vendor(self):
        _purge_server_modules()
        for p in (str(PROJECT_ROOT / "jarvis-web"), str(PROJECT_ROOT / "jarvis-memory")):
            if p in sys.path:
                sys.path.remove(p)
        sys.path.insert(0, str(PROJECT_ROOT / "jarvis-canvas"))
        from server.app import create_app

        app = create_app("cloud")
        with app.test_client() as client:
            r = client.get("/static/fonts/InterVariable.woff2")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data[:4], b"wOF2", "Canvas must return font bytes, not a 404 or HTML fallback")
            self.assertEqual(client.get("/static/vendor/marked.min.js").status_code, 200)


if __name__ == "__main__":
    unittest.main()
