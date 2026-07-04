#!/usr/bin/env python3
"""Restricted-read coverage for tools that accept resolved local paths."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import stash_helper
import pdf_read
import screenshot_url
import upload_cloudflare

AUTO_TOOLS = PROJECT_ROOT / "skills" / "auto-tools"
sys.path.insert(0, str(AUTO_TOOLS))
import docker_control


class RestrictedFileToolTests(unittest.TestCase):
    def test_safe_resolve_rechecks_final_stash_path(self):
        restricted = PROJECT_ROOT / "config" / "cloud.env"
        with patch.object(stash_helper, "resolve_file_path", return_value=str(restricted)):
            result = stash_helper.safe_resolve_file(stash_ref="stash://space_test/file")

        self.assertFalse(result["found"])
        self.assertIn("restricted location", result["error"])

    def test_cloudflare_upload_rejects_restricted_source_before_network(self):
        restricted = PROJECT_ROOT / "config" / "cloud.env"
        with patch.object(upload_cloudflare, "upload_to_cloudflare") as upload:
            with self.assertRaisesRegex(ValueError, "restricted location"):
                upload_cloudflare.upload_image(str(restricted), source_type="file")
        upload.assert_not_called()

    def test_docker_compose_rejects_restricted_compose_file(self):
        restricted = PROJECT_ROOT / "config" / "docker-compose.yml"
        with patch.object(docker_control, "run_command") as run:
            with self.assertRaisesRegex(ValueError, "restricted location"):
                docker_control.compose_action("config", compose_file=str(restricted))
        run.assert_not_called()

    def test_pdf_merge_resolves_direct_paths_through_pdf_policy(self):
        with patch.object(pdf_read, "resolve_pdf_path", side_effect=ValueError("blocked")) as resolve:
            with self.assertRaisesRegex(ValueError, "blocked"):
                pdf_read.action_merge({"pdfs": ["first.pdf", "second.pdf"]})
        resolve.assert_called_once_with({'file_path': 'first.pdf'})

    def test_screenshot_output_path_rejects_restricted_destination(self):
        restricted = PROJECT_ROOT / "config" / "screenshot.png"
        with self.assertRaisesRegex(ValueError, "restricted location"):
            screenshot_url.resolve_screenshot_output_path(str(restricted))

    def test_screenshot_output_path_preserves_normal_temp_workflow(self):
        self.assertEqual(
            screenshot_url.resolve_screenshot_output_path("/tmp/jarvis-shot.png"),
            Path("/tmp/jarvis-shot.jpg"),
        )


if __name__ == "__main__":
    unittest.main()
