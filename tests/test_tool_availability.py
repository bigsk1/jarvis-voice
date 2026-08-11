#!/usr/bin/env python3
"""Tests for credential-aware tool availability (lib/tool_availability.py).

Covers the requirement schema, blank/missing detection, multi-provider
semantics, malformed-block fail-closed behavior, config-scope isolation,
secret non-leakage, media provider preflight, and ToolRegistry integration
(including profile force-enable not bypassing missing hard requirements).
"""
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

from tool_availability import (  # noqa: E402
    MALFORMED_MARKER,
    check_availability_block,
    check_tool_availability,
    describe_missing,
    is_config_file_ready,
    is_env_configured,
    media_provider_preflight,
)


class EnvVarCleanupMixin:
    """Track os.environ mutations and restore them after each test."""

    def setUp(self):
        super().setUp()
        self._env_added: list[str] = []

    def set_env(self, key: str, value: str):
        os.environ[key] = value
        if key not in self._env_added:
            self._env_added.append(key)

    def tearDown(self):
        for key in self._env_added:
            os.environ.pop(key, None)
        super().tearDown()


class TestAvailabilityEvaluator(EnvVarCleanupMixin, unittest.TestCase):
    def test_spotify_manifest_requires_credentials_and_oauth_cache(self):
        manifest = json.loads((ROOT / "skills" / "spotify.tool.json").read_text())
        availability = manifest["availability"]
        self.assertEqual(
            availability["all_of_env"],
            ["SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"],
        )
        self.assertEqual(availability["config_files"], ["data/.spotify_cache"])

    def test_no_block_is_available(self):
        self.assertEqual(check_availability_block(None).status, "available")
        self.assertEqual(check_tool_availability({"name": "x"}).status, "available")

    def test_all_of_env_missing(self):
        result = check_availability_block(
            {"all_of_env": ["ZZTEST_MISSING_KEY"], "setup_hint": "add it"}
        )
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.missing, ["ZZTEST_MISSING_KEY"])
        self.assertEqual(result.setup_hint, "add it")
        self.assertFalse(result.available)

    def test_all_of_env_configured(self):
        self.set_env("ZZTEST_KEY_A", "value")
        result = check_availability_block({"all_of_env": ["ZZTEST_KEY_A"]})
        self.assertEqual(result.status, "available")
        self.assertTrue(result.available)

    def test_blank_and_whitespace_values_are_missing(self):
        self.set_env("ZZTEST_BLANK", "")
        self.set_env("ZZTEST_SPACES", "   ")
        self.assertFalse(is_env_configured("ZZTEST_BLANK"))
        self.assertFalse(is_env_configured("ZZTEST_SPACES"))
        result = check_availability_block({"all_of_env": ["ZZTEST_BLANK", "ZZTEST_SPACES"]})
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.missing, ["ZZTEST_BLANK", "ZZTEST_SPACES"])

    def test_any_of_env(self):
        self.set_env("ZZTEST_ALT_B", "x")
        ok = check_availability_block({"any_of_env": ["ZZTEST_ALT_A", "ZZTEST_ALT_B"]})
        self.assertEqual(ok.status, "available")
        bad = check_availability_block({"any_of_env": ["ZZTEST_ALT_A", "ZZTEST_ALT_C"]})
        self.assertEqual(bad.status, "unavailable")
        self.assertIn("any of", bad.missing[0])

    def test_config_files_require_nonempty_project_relative_files(self):
        import tool_availability

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_file = root / "data" / "oauth-cache.json"
            config_file.parent.mkdir()
            block = {"config_files": ["data/oauth-cache.json"]}
            with patch.object(tool_availability, "get_project_root", return_value=root):
                missing = check_availability_block(block)
                self.assertEqual(missing.status, "unavailable")
                self.assertEqual(missing.missing, ["file: data/oauth-cache.json"])

                config_file.write_text("")
                self.assertFalse(is_config_file_ready("data/oauth-cache.json"))
                self.assertEqual(check_availability_block(block).status, "unavailable")

                config_file.write_text('{"access_token":"test-only"}')
                self.assertTrue(is_config_file_ready("data/oauth-cache.json"))
                self.assertEqual(check_availability_block(block).status, "available")

    def test_config_files_combine_with_env_requirements(self):
        import tool_availability

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            token = root / "token.json"
            token.write_text("test-token")
            block = {
                "all_of_env": ["ZZTEST_FILE_BACKED_KEY"],
                "config_files": ["token.json"],
            }
            with patch.object(tool_availability, "get_project_root", return_value=root):
                self.assertEqual(check_availability_block(block).status, "unavailable")
                self.set_env("ZZTEST_FILE_BACKED_KEY", "configured")
                self.assertEqual(check_availability_block(block).status, "available")

    def test_webhook_registry_requires_enabled_entry_with_resolved_url(self):
        import tool_availability

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "config"
            config_dir.mkdir()
            registry = config_dir / "webhook_registry.json"
            block = {"webhook_registry": ["send_email"]}
            with patch.object(tool_availability, "get_project_root", return_value=root):
                self.assertEqual(check_availability_block(block).status, "unavailable")
                self.assertEqual(check_availability_block(block).missing, ["file: config/webhook_registry.json"])

                registry.write_text(json.dumps({"webhooks": {}}))
                result = check_availability_block(block)
                self.assertEqual(result.status, "unavailable")
                self.assertEqual(result.missing, ["webhook: send_email"])

                registry.write_text(json.dumps({
                    "webhooks": {
                        "send_email": {
                            "url": "${ZZTEST_N8N_URL}/webhook/jarvis-email",
                            "enabled": False,
                        }
                    }
                }))
                result = check_availability_block(block)
                self.assertEqual(result.missing, ["webhook: send_email (disabled)"])

                registry.write_text(json.dumps({
                    "webhooks": {
                        "send_email": {
                            "url": "${ZZTEST_N8N_URL}/webhook/jarvis-email",
                        }
                    }
                }))
                self.set_env("ZZTEST_N8N_URL", "http://localhost:5678")
                result = check_availability_block(block)
                self.assertEqual(result.status, "available")

                registry.write_text(json.dumps({
                    "webhooks": {"send_email": {"url": "${ZZTEST_MISSING_N8N}/hook"}}
                }))
                os.environ.pop("ZZTEST_MISSING_N8N", None)
                result = check_availability_block(block)
                self.assertEqual(result.missing, ["webhook: send_email (url not configured)"])

    def test_static_config_gated_tool_manifests(self):
        manifests = {
            "ssh_remote": {"config_files": ["config/ssh.json"]},
            "send_email": {"webhook_registry": ["send_email"]},
            "crawl_url": {"all_of_env": ["CRAWL4AI_URL"]},
            "screenshot_url": {"all_of_env": ["CRAWL4AI_URL"]},
            "create_social_clip": {"all_of_env": ["MONEYPRINTER_API_URL"]},
            "document_ocr": {"all_of_env": ["OVIS_OCR_URL"]},
        }
        for name, expected_keys in manifests.items():
            manifest = json.loads((ROOT / "skills" / f"{name}.tool.json").read_text())
            availability = manifest["availability"]
            for key, value in expected_keys.items():
                self.assertEqual(availability[key], value, msg=name)

    def test_provider_requirements_one_configured(self):
        self.set_env("ZZTEST_PROV1_KEY", "k")
        self.set_env("ZZTEST_PROVIDER_SETTING", "prov2")
        block = {
            "provider_setting": "ZZTEST_PROVIDER_SETTING",
            "provider_default": "prov1",
            "provider_requirements": {
                "prov1": {"all_of_env": ["ZZTEST_PROV1_KEY"]},
                "prov2": {"all_of_env": ["ZZTEST_PROV2_KEY"]},
            },
        }
        result = check_availability_block(block)
        self.assertEqual(result.status, "available")
        self.assertEqual(result.selected_provider, "prov2")
        self.assertEqual(result.configured_providers, ["prov1"])
        self.assertEqual(result.provider_availability, {"prov1": True, "prov2": False})

    def test_provider_requirements_none_configured(self):
        block = {
            "provider_requirements": {
                "p1": {"all_of_env": ["ZZTEST_NONE_A"]},
                "p2": {"all_of_env": ["ZZTEST_NONE_B"]},
            },
        }
        result = check_availability_block(block)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.configured_providers, [])
        self.assertIn("any provider of", result.missing[0])

    def test_malformed_blocks_fail_closed_without_raising(self):
        for bad in (
            {"all_of_env": "not-a-list"},
            {"all_of_env": []},
            {"all_of_env": [123]},
            {"any_of_env": {}},
            {"config_files": "token.json"},
            {"config_files": []},
            {"config_files": [123]},
            {"webhook_registry": "send_email"},
            {"webhook_registry": []},
            {"provider_requirements": []},
            {"provider_requirements": {"p": "nope"}},
            {"allof_env": ["TYPO_KEY"]},  # unknown-only keys: fail closed
            "just a string",
        ):
            result = check_availability_block(bad)
            self.assertEqual(result.status, "unavailable", msg=repr(bad))
            self.assertEqual(result.missing, [MALFORMED_MARKER], msg=repr(bad))

    def test_setup_hint_only_block_is_available(self):
        result = check_availability_block({"setup_hint": "informational"})
        self.assertEqual(result.status, "available")

    def test_no_secret_values_in_results(self):
        secret = "zz-super-secret-value-8213"
        self.set_env("ZZTEST_SECRET_KEY", secret)
        self.set_env("ZZTEST_SECRET_SETTING", "prov1")
        block = {
            "all_of_env": ["ZZTEST_SECRET_KEY", "ZZTEST_SECRET_MISSING"],
            "provider_setting": "ZZTEST_SECRET_SETTING",
            "provider_requirements": {"prov1": {"all_of_env": ["ZZTEST_SECRET_KEY"]}},
        }
        result = check_availability_block(block)
        dumped = json.dumps(result.to_dict()) + describe_missing(result)
        self.assertNotIn(secret, dumped)

    def test_config_scope_isolation(self):
        """The same key can be configured in cloud but blank in local."""
        import config_loader

        def fake_load_mode_config(mode):
            return {"ZZTEST_SCOPED_KEY": "x"} if mode == "cloud" else {}

        block = {"all_of_env": ["ZZTEST_SCOPED_KEY"]}
        with patch.object(config_loader, "_load_mode_config", side_effect=fake_load_mode_config):
            with config_loader.config_scope("cloud"):
                self.assertEqual(check_availability_block(block).status, "available")
            with config_loader.config_scope("local"):
                self.assertEqual(check_availability_block(block).status, "unavailable")


class TestMediaProviderPreflight(EnvVarCleanupMixin, unittest.TestCase):
    KEYS = {
        "gemini": ["ZZTEST_MEDIA_GEMINI"],
        "openai": ["ZZTEST_MEDIA_OPENAI"],
        "xai": ["ZZTEST_MEDIA_XAI"],
    }

    def test_configured_provider_passes(self):
        self.set_env("ZZTEST_MEDIA_GEMINI", "k")
        self.assertIsNone(media_provider_preflight("gemini", self.KEYS))

    def test_unconfigured_provider_lists_alternatives(self):
        self.set_env("ZZTEST_MEDIA_OPENAI", "k")
        err = media_provider_preflight("gemini", self.KEYS)
        self.assertIsNotNone(err)
        self.assertIn("gemini", err)
        self.assertIn("ZZTEST_MEDIA_GEMINI", err)
        self.assertIn("openai", err)
        self.assertIn("not switch providers automatically", err)

    def test_no_alternatives_configured(self):
        err = media_provider_preflight("xai", self.KEYS)
        self.assertIn("No alternative providers", err)

    def test_unknown_provider_is_left_to_tool_dispatch(self):
        self.assertIsNone(media_provider_preflight("mystery", self.KEYS))


class TestGenerateImagePreflight(EnvVarCleanupMixin, unittest.TestCase):
    """The media tool errors on an unconfigured selected provider without
    calling any provider function (and without auto-switching)."""

    def test_selected_provider_missing_key_raises_before_any_api_call(self):
        sys.path.insert(0, str(ROOT / "skills"))
        try:
            import generate_image
        finally:
            sys.path.remove(str(ROOT / "skills"))

        # JARVIS_OVERRIDE_* has top precedence in get_config_value, so the
        # test never reads or depends on the real env files.
        self.set_env("JARVIS_OVERRIDE_IMAGE_TOOL_PROVIDER", "gemini")
        self.set_env("JARVIS_OVERRIDE_GEMINI_API_KEY", "")

        with patch.object(generate_image, "generate_image_gemini") as gem, \
             patch.object(generate_image, "generate_image_openai") as oai, \
             patch.object(generate_image, "generate_image_xai") as xai:
            with self.assertRaises(ValueError) as ctx:
                generate_image.generate_image("a test prompt")
        message = str(ctx.exception)
        self.assertIn("gemini", message)
        self.assertIn("GEMINI_API_KEY", message)
        gem.assert_not_called()
        oai.assert_not_called()
        xai.assert_not_called()


class TestManageToolsModeAware(unittest.TestCase):
    """manage-tools runs inside an explicit config scope per --mode."""

    def _run(self, *args):
        import subprocess
        return subprocess.run(
            [sys.executable, str(ROOT / "bin" / "manage-tools.py"), *args],
            capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        )

    def test_list_reports_selected_mode(self):
        for mode in ("cloud", "local"):
            result = self._run("--mode", mode, "list")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"Mode: {mode}", result.stdout)
            self.assertIn("unavailable (missing config)", result.stdout)

    def test_profile_export_includes_availability(self):
        result = self._run("--mode", "cloud", "profile", "export")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(all("available" in v for v in data["tools"].values() if "error" not in v))


class TestRegistryIntegration(EnvVarCleanupMixin, unittest.TestCase):
    """ToolRegistry excludes unavailable tools and records diagnostics."""

    def _write_manifest(self, skills_dir: Path, name: str, extra: dict | None = None):
        manifest = {
            "enabled": True,
            "name": name,
            "description": f"{name} test tool",
            "script": f"{name}.py",
            "parameters": {"type": "object", "properties": {}},
        }
        manifest.update(extra or {})
        (skills_dir / f"{name}.tool.json").write_text(json.dumps(manifest))

    def _make_registry(self, skills_dir: Path):
        from tool_schema import ToolRegistry
        return ToolRegistry(str(skills_dir), None)

    def setUp(self):
        super().setUp()
        self.set_env("JARVIS_TOOL_PROFILE", "default")

    def test_unavailable_tool_excluded_with_diagnostics(self):
        with TemporaryDirectory() as tmp:
            skills = Path(tmp)
            self._write_manifest(skills, "plain_tool")
            self._write_manifest(
                skills, "needs_key_tool",
                {"availability": {"all_of_env": ["ZZTEST_REG_KEY"], "setup_hint": "add ZZTEST_REG_KEY"}},
            )
            registry = self._make_registry(skills)

            self.assertIn("plain_tool", registry.tools)
            self.assertNotIn("needs_key_tool", registry.tools)
            self.assertIn("needs_key_tool", registry.unavailable_tools)
            self.assertEqual(
                registry.unavailable_tools["needs_key_tool"].missing,
                ["ZZTEST_REG_KEY"],
            )
            # Callable tool count excludes the unavailable tool while
            # diagnostics still report it.
            self.assertEqual(len(registry.tools), 1)
            self.assertEqual(len(registry.unavailable_tools), 1)

    def test_tool_restored_after_configuration(self):
        with TemporaryDirectory() as tmp:
            skills = Path(tmp)
            self._write_manifest(
                skills, "needs_key_tool",
                {"availability": {"all_of_env": ["ZZTEST_REG_KEY2"]}},
            )
            registry = self._make_registry(skills)
            self.assertNotIn("needs_key_tool", registry.tools)

            self.set_env("ZZTEST_REG_KEY2", "now-configured")
            registry = self._make_registry(skills)
            self.assertIn("needs_key_tool", registry.tools)
            self.assertNotIn("needs_key_tool", registry.unavailable_tools)

    def test_profile_force_enable_cannot_bypass_missing_requirement(self):
        import tool_profiles

        with TemporaryDirectory() as tmp:
            skills = Path(tmp)
            self._write_manifest(
                skills, "needs_key_tool",
                {"enabled": False, "availability": {"all_of_env": ["ZZTEST_REG_KEY3"]}},
            )
            with patch.object(
                tool_profiles, "load_active_profile_overrides",
                return_value={"needs_key_tool": True},
            ):
                registry = self._make_registry(skills)
            self.assertNotIn("needs_key_tool", registry.tools)
            self.assertIn("needs_key_tool", registry.unavailable_tools)

    def test_malformed_manifest_block_does_not_crash_registry(self):
        with TemporaryDirectory() as tmp:
            skills = Path(tmp)
            self._write_manifest(skills, "plain_tool")
            self._write_manifest(skills, "broken_tool", {"availability": {"all_of_env": "oops"}})
            registry = self._make_registry(skills)
            self.assertIn("plain_tool", registry.tools)
            self.assertNotIn("broken_tool", registry.tools)
            self.assertEqual(
                registry.unavailable_tools["broken_tool"].missing,
                [MALFORMED_MARKER],
            )


if __name__ == "__main__":
    unittest.main()
