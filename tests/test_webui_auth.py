import os
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

import webui_auth


LOGIN_TEMPLATES = (
    PROJECT_ROOT / "jarvis-web" / "client" / "login.html",
    PROJECT_ROOT / "jarvis-canvas" / "client" / "templates" / "login.html",
    PROJECT_ROOT / "jarvis-memory" / "client" / "login.html",
    PROJECT_ROOT / "jarvis-intelligence" / "client" / "login.html",
    PROJECT_ROOT / "jarvis-docs" / "client" / "login.html",
)


class WebUISecretTests(unittest.TestCase):
    def test_concurrent_first_start_uses_one_secret(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            secret_file = Path(tmpdir) / ".webui_secret"
            workers = 8
            barrier = threading.Barrier(workers)

            def generate_secret(_length):
                barrier.wait(timeout=5)
                return f"{threading.get_ident():064x}"

            with (
                mock.patch.object(webui_auth, "SECRET_FILE", secret_file),
                mock.patch.object(webui_auth.secrets, "token_hex", side_effect=generate_secret),
                mock.patch.dict(os.environ, {}, clear=True),
                ThreadPoolExecutor(max_workers=workers) as executor,
            ):
                results = list(executor.map(lambda _index: webui_auth._get_secret(), range(workers)))

            self.assertEqual(len(set(results)), 1)
            self.assertEqual(secret_file.read_text(), results[0])
            self.assertEqual(len(results[0]), 64)

    def test_environment_secret_takes_precedence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            secret_file = Path(tmpdir) / ".webui_secret"
            with (
                mock.patch.object(webui_auth, "SECRET_FILE", secret_file),
                mock.patch.dict(os.environ, {"WEBUI_SECRET": "configured-secret"}, clear=True),
            ):
                self.assertEqual(webui_auth._get_secret(), "configured-secret")
            self.assertFalse(secret_file.exists())


class LoginTemplateTests(unittest.TestCase):
    def test_all_login_pages_restore_and_clear_shared_cookie(self):
        for template in LOGIN_TEMPLATES:
            with self.subTest(template=template):
                content = template.read_text(encoding="utf-8")
                self.assertIn("jarvis_auth=${existingToken}", content)
                self.assertIn("max-age=${remainingSeconds}", content)
                self.assertIn("jarvis_auth=; path=/; max-age=0; SameSite=Lax", content)


if __name__ == "__main__":
    unittest.main()
