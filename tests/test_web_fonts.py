#!/usr/bin/env python3
"""Ensure fonts.css only references files that exist under jarvis-web/client/fonts."""

import importlib
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from server_package_utils import load_server_package

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FONTS_CSS = PROJECT_ROOT / "jarvis-web" / "client" / "css" / "fonts.css"
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
        load_server_package("fonts_web_test_server", PROJECT_ROOT / "jarvis-web/server")
        app = importlib.import_module("fonts_web_test_server.app").app

        with app.test_client() as client:
            r = client.get("/fonts/InterVariable.woff2")
            self.assertEqual(r.status_code, 200)
            self.assertGreater(len(r.data), 1000)
            r_css = client.get("/css/fonts.css")
            self.assertEqual(r_css.status_code, 200)
            self.assertIn(b"@font-face", r_css.data)

    def test_02_memory_browser_serves_shared_font_bytes(self):
        load_server_package("fonts_memory_test_server", PROJECT_ROOT / "jarvis-memory/server")
        app_module = importlib.import_module("fonts_memory_test_server.app")

        with (
            mock.patch.object(app_module, "is_auth_enabled", return_value=True),
            app_module.app.test_client() as client,
        ):
            r = client.get("/fonts/InterVariable.woff2")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data[:4], b"wOF2", "memory UI must return font bytes, not HTML fallback")

    def test_03_intelligence_browser_serves_shared_font_bytes(self):
        load_server_package("fonts_intelligence_test_server", PROJECT_ROOT / "jarvis-intelligence/server")
        app_module = importlib.import_module("fonts_intelligence_test_server.app")

        with (
            mock.patch.object(app_module, "is_auth_enabled", return_value=True),
            app_module.app.test_client() as client,
        ):
            r = client.get("/fonts/JetBrainsMono-Regular.woff2")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data[:4], b"wOF2", "intelligence UI must return font bytes, not HTML fallback")

    def test_04_canvas_static_fonts_and_vendor(self):
        # Canvas's launcher uses absolute server/config imports. Exercise that
        # boundary in a fresh interpreter without replacing other apps' modules.
        script = """
import importlib
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from unittest import TestCase, mock

root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'tests'))
from suite_isolation import install_default_isolation
install_default_isolation()
sys.path.insert(0, str(root / 'jarvis-canvas'))

with tempfile.TemporaryDirectory() as directory:
    config = ModuleType('config')
    for name in ('CANVAS_DIR', 'STATIC_DIR', 'STASH_DIR', 'GENERATED_IMAGES_DIR',
                 'GENERATED_VIDEOS_DIR', 'GENERATED_AUDIO_DIR'):
        setattr(config, name, Path(directory) / name)
    sys.modules['config'] = config

    from config_loader import config_scope
    with config_scope('cloud', overrides={'STASH_DIR': str(config.STASH_DIR)}):
        app_module = importlib.import_module('server.app')
        with mock.patch.object(app_module, 'is_auth_enabled', return_value=True):
            app = app_module.create_app('cloud')
            case = TestCase()
            with app.test_client() as client:
                response = client.get('/static/fonts/InterVariable.woff2')
                case.assertEqual(response.status_code, 200)
                case.assertEqual(response.data[:4], b'wOF2',
                                 'Canvas must return font bytes, not a 404 or HTML fallback')
                case.assertEqual(client.get('/static/vendor/marked.min.js').status_code, 200)
"""
        result = subprocess.run(
            [sys.executable, "-I", "-c", script, str(PROJECT_ROOT)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
