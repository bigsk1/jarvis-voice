#!/usr/bin/env python3
"""Web provider availability + credential-aware tool discovery tests.

Covers:
  - provider_availability payload statuses (per domain, tri-state, no values)
  - saving a NEWLY selected unavailable provider is rejected (typed error,
    no mutation) while unrelated settings remain saveable even when the env
    default provider lacks credentials
  - env-default-unavailable vs explicit-new-override distinction
  - HTTP 400 mapping in the settings route
  - unavailable manifest tools stay in web discovery (enabled=False,
    available=False) so stale enabled Tool RAG rows cannot resurrect them
"""
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))


def _purge_server_modules() -> None:
    for key in list(sys.modules):
        if key == "server" or key.startswith("server."):
            del sys.modules[key]


class SettingsAvailabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _purge_server_modules()
        sys.path.insert(0, str(ROOT / "jarvis-web"))
        from server.services import settings_manager as settings_module
        cls.settings_module = settings_module

    def _manager(self, mode, env):
        from server.services.settings_manager import SettingsManager

        def get_setting(key, default=""):
            return env.get(key, default)

        manager = SettingsManager(mode)
        patches = [
            patch.object(manager, "_ensure_jarvis_config"),
            patch.object(self.settings_module, "get_jarvis_setting", side_effect=get_setting),
        ]
        return manager, patches

    def test_provider_availability_statuses_cloud(self):
        secret = "zz-secret-value-999"
        env = {
            "OPENAI_API_KEY": secret,
            "XAI_API_KEY": "  ",
            "XAI_AUTH_MODE": "api_key",
        }  # blank xai with API-key auth forced
        manager, patches = self._manager("cloud", env)
        with patches[0], patches[1]:
            availability = manager.get_provider_availability()

        llm = availability["llm"]
        self.assertEqual(llm["openai"]["status"], "available")
        self.assertEqual(llm["xai"]["status"], "unavailable")
        self.assertEqual(llm["xai"]["reason"], "xAI API key missing")
        self.assertEqual(llm["anthropic"]["status"], "unavailable")
        # Ollama Cloud is a live check, not an env key
        self.assertEqual(llm["ollama"]["status"], "unknown")
        # Media domains use the same key logic
        self.assertEqual(availability["image"]["openai"]["status"], "available")
        self.assertEqual(availability["image"]["gemini"]["status"], "unavailable")
        self.assertEqual(
            availability["image"]["gemini"]["reason"],
            "Gemini API key missing",
        )
        # TTS: local engines available without keys
        self.assertEqual(availability["tts"]["qwen3-tts"]["status"], "available")
        self.assertEqual(availability["tts"]["elevenlabs"]["status"], "unavailable")
        self.assertEqual(
            availability["tts"]["elevenlabs"]["reason"],
            "ElevenLabs API key missing",
        )
        # Completion guard mirrors catalog providers
        self.assertEqual(availability["completion_guard"]["openai"]["status"], "available")
        # No secret values anywhere in the payload
        self.assertNotIn(secret, json.dumps(availability))

    def test_xai_oauth_enables_text_domains_but_not_media_or_tts(self):
        env = {"XAI_API_KEY": "", "XAI_AUTH_MODE": "oauth"}
        manager, patches = self._manager("cloud", env)
        oauth_status = {
            "status": "available",
            "signed_in": True,
            "reason": None,
        }
        with (
            patches[0], patches[1],
            patch.object(self.settings_module, "get_xai_oauth_status", return_value=oauth_status),
        ):
            availability = manager.get_provider_availability()

        self.assertEqual(availability["llm"]["xai"]["status"], "available")
        self.assertEqual(availability["llm"]["xai"]["connection"], "oauth")
        self.assertEqual(availability["completion_guard"]["xai"]["status"], "available")
        self.assertEqual(availability["image"]["xai"]["status"], "unavailable")
        self.assertEqual(availability["video"]["xai"]["status"], "unavailable")
        self.assertEqual(availability["tts"]["xai"]["status"], "unavailable")

    def test_xai_oauth_uses_subscription_model_not_api_model(self):
        env = {
            "XAI_API_KEY": "",
            "XAI_AUTH_MODE": "oauth",
            "XAI_MODEL": "grok-build-0.1",
            "XAI_OAUTH_MODEL": "grok-build",
        }
        manager, patches = self._manager("cloud", env)
        with patches[0], patches[1]:
            self.assertEqual(manager._get_env_provider_model("xai"), "grok-build")
            self.assertFalse(manager._model_is_compatible_with_provider("xai", "grok-build-0.1"))
            self.assertTrue(manager._model_is_compatible_with_provider("xai", "grok-build"))

    def test_ollama_available_in_local_mode(self):
        manager, patches = self._manager("local", {})
        with patches[0], patches[1]:
            availability = manager.get_provider_availability()
        self.assertEqual(availability["llm"]["ollama"]["status"], "available")

    def test_ollama_cloud_api_key_uses_nonblank_presence_gate(self):
        for value, expected in [('', 'unknown'), ('   ', 'unknown'), ('configured', 'available')]:
            manager, patches = self._manager("cloud", {"OLLAMA_API_KEY": value})
            with patches[0], patches[1]:
                entry = manager._provider_availability_entry("ollama")
            self.assertEqual(entry["status"], expected)

    def test_settings_payload_includes_provider_availability(self):
        manager, patches = self._manager("cloud", {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "k"})
        web_config = {"cloud": {}, "audio": {}, "ui": {}, "conversation": {}, "tools": {}}
        with (
            patches[0], patches[1],
            patch.object(self.settings_module, "load_web_config", return_value=web_config),
            patch.object(manager, "_get_provider_models", return_value={}),
        ):
            result = manager.get_settings_for_ui()
        self.assertIn("provider_availability", result)
        self.assertEqual(result["provider_availability"]["llm"]["openai"]["status"], "available")

    def test_save_rejects_newly_selected_unavailable_provider(self):
        from server.services.settings_manager import SettingsValidationError

        env = {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "k"}  # anthropic key absent
        manager, patches = self._manager("cloud", env)
        web_config = {"cloud": {}}
        with (
            patches[0], patches[1],
            patch.object(self.settings_module, "load_web_config", return_value=web_config),
            patch.object(self.settings_module, "save_web_config", return_value=True) as save_cfg,
        ):
            with self.assertRaises(SettingsValidationError) as ctx:
                manager.save_web_overrides({"llm_provider": "anthropic"})
        # Validation happens BEFORE mutation: nothing written
        save_cfg.assert_not_called()
        self.assertEqual(ctx.exception.field, "llm_provider")
        self.assertEqual(ctx.exception.provider, "anthropic")
        self.assertEqual(ctx.exception.reason, "Anthropic API key missing")

    def test_unrelated_settings_saveable_when_env_default_unavailable(self):
        # Env default provider has NO key; changing response style must work.
        env = {"LLM_PROVIDER": "anthropic"}
        manager, patches = self._manager("cloud", env)
        web_config = {"cloud": {}}
        with (
            patches[0], patches[1],
            patch.object(self.settings_module, "load_web_config", return_value=web_config),
            patch.object(self.settings_module, "save_web_config", return_value=True) as save_cfg,
        ):
            success = manager.save_web_overrides({"response_style": "casual"})
        self.assertTrue(success)
        save_cfg.assert_called_once()

    def test_saving_current_effective_provider_is_not_a_new_selection(self):
        # Re-submitting the (unavailable) env default provider is allowed —
        # only a CHANGE to an unavailable provider is rejected.
        env = {"LLM_PROVIDER": "anthropic"}
        manager, patches = self._manager("cloud", env)
        web_config = {"cloud": {}}
        with (
            patches[0], patches[1],
            patch.object(self.settings_module, "load_web_config", return_value=web_config),
            patch.object(self.settings_module, "save_web_config", return_value=True),
        ):
            success = manager.save_web_overrides({"llm_provider": "anthropic"})
        self.assertTrue(success)

    def test_save_rejects_unavailable_media_and_tts_providers(self):
        from server.services.settings_manager import SettingsValidationError

        env = {"IMAGE_TOOL_PROVIDER": "openai", "OPENAI_API_KEY": "k"}
        manager, patches = self._manager("cloud", env)
        web_config = {"cloud": {}}
        with (
            patches[0], patches[1],
            patch.object(self.settings_module, "load_web_config", return_value=web_config),
            patch.object(self.settings_module, "save_web_config", return_value=True),
        ):
            with self.assertRaises(SettingsValidationError) as ctx:
                manager.save_web_overrides({"image_provider": "gemini"})
        self.assertEqual(ctx.exception.field, "image_provider")

    def test_clearing_override_is_always_allowed(self):
        env = {"LLM_PROVIDER": "anthropic"}
        manager, patches = self._manager("cloud", env)
        web_config = {"cloud": {"llm_provider": "openai"}}
        with (
            patches[0], patches[1],
            patch.object(self.settings_module, "load_web_config", return_value=web_config),
            patch.object(self.settings_module, "save_web_config", return_value=True),
        ):
            success = manager.save_web_overrides({"llm_provider": None})
        self.assertTrue(success)


class SettingsRouteValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _purge_server_modules()
        sys.path.insert(0, str(ROOT / "jarvis-web"))
        from server.app import app
        from server.routes import api
        cls.app = app
        cls.api = api

    def test_validation_error_maps_to_http_400_with_typed_body(self):
        from server.services.settings_manager import SettingsValidationError

        settings = MagicMock()
        settings.validate_web_overrides.side_effect = SettingsValidationError(
            field="llm_provider", provider="anthropic",
            reason="Anthropic API key missing",
        )
        with (
            self.app.test_request_context(
                "/api/settings/web", method="PUT",
                json={"llm_provider": "anthropic"},
            ),
            patch.object(self.api, "get_settings_manager", return_value=settings),
            patch.object(self.api, "reload_web_config") as reload_cfg,
        ):
            response, status = self.api.update_web_settings()

        self.assertEqual(status, 400)
        body = response.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["field"], "llm_provider")
        self.assertEqual(body["provider"], "anthropic")
        self.assertEqual(body["reason"], "Anthropic API key missing")
        reload_cfg.assert_not_called()
        settings.save_web_overrides.assert_not_called()

    def test_xai_oauth_status_route_is_sanitized(self):
        from server import config as web_config_module

        safe_status = {
            "connection": "oauth",
            "signed_in": True,
            "status": "available",
            "reason": None,
            "usage_available": False,
            "expires_at": "2099-01-01T00:00:00+00:00",
            "models": [{"id": "grok-build", "name": "grok-build", "context": "256K"}],
        }

        def get_setting(key, default=""):
            return {
                "XAI_API_KEY": "",
                "XAI_AUTH_MODE": "oauth",
                "XAI_SEARCH": "true",
            }.get(key, default)

        with (
            self.app.test_request_context("/api/xai/oauth-status?mode=cloud"),
            patch.object(web_config_module, "load_jarvis_config"),
            patch.object(web_config_module, "get_jarvis_setting", side_effect=get_setting),
            patch("xai_oauth.get_xai_oauth_status", return_value=safe_status),
        ):
            response = self.api.get_xai_oauth_status_route.__wrapped__()

        body = response.get_json()
        self.assertEqual(body["connection_mode"], "oauth")
        self.assertTrue(body["signed_in"])
        self.assertFalse(body["usage_available"])
        self.assertTrue(body["native_search_requested"])
        self.assertFalse(body["native_search_available"])
        self.assertIn("requires API-key auth", body["native_search_note"])
        self.assertEqual(body["models"][0]["id"], "grok-build")
        self.assertNotIn("token", json.dumps(body).lower())

    def test_xai_explicit_oauth_reports_present_api_key_is_ignored_for_chat(self):
        from server import config as web_config_module

        def get_setting(key, default=""):
            return {
                "XAI_API_KEY": "configured-secret",
                "XAI_AUTH_MODE": "oauth",
                "XAI_SEARCH": "true",
            }.get(key, default)

        with (
            self.app.test_request_context("/api/xai/oauth-status?mode=cloud"),
            patch.object(web_config_module, "load_jarvis_config"),
            patch.object(web_config_module, "get_jarvis_setting", side_effect=get_setting),
            patch("xai_oauth.get_xai_oauth_status", return_value={
                "connection": "oauth",
                "signed_in": True,
                "status": "available",
                "reason": None,
                "usage_available": False,
            }),
        ):
            response = self.api.get_xai_oauth_status_route.__wrapped__()

        body = response.get_json()
        self.assertEqual(body["connection_mode"], "oauth")
        self.assertTrue(body["api_key_present"])
        self.assertFalse(body["native_search_available"])
        self.assertNotIn("configured-secret", json.dumps(body))

    def test_rejected_save_does_not_persist_requested_mode(self):
        """Atomicity: a provider rejection must not change the stored mode."""
        from server.services.settings_manager import SettingsValidationError

        settings = MagicMock()
        settings.mode = "cloud"
        settings.validate_web_overrides.side_effect = SettingsValidationError(
            field="llm_provider", provider="anthropic",
            reason="Anthropic API key missing",
        )
        with (
            self.app.test_request_context(
                "/api/settings/web", method="PUT",
                json={"mode": "local", "llm_provider": "anthropic"},
            ),
            patch.object(self.api, "get_settings_manager", return_value=settings),
            patch.object(self.api, "reload_web_config"),
        ):
            response, status = self.api.update_web_settings()

        self.assertEqual(status, 400)
        # Validation ran against the requested mode...
        self.assertEqual(settings.mode, "local")
        # ...but nothing was persisted: neither the mode nor the overrides.
        settings.set_mode.assert_not_called()
        settings.save_web_overrides.assert_not_called()

    def test_valid_save_with_mode_persists_mode_then_overrides(self):
        settings = MagicMock()
        settings.mode = "cloud"
        settings.set_mode.return_value = True
        settings.save_web_overrides.return_value = True
        with (
            self.app.test_request_context(
                "/api/settings/web", method="PUT",
                json={"mode": "local", "response_style": "casual"},
            ),
            patch.object(self.api, "get_settings_manager", return_value=settings),
            patch.object(self.api, "reload_web_config"),
        ):
            response = self.api.update_web_settings()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        settings.set_mode.assert_called_once_with("local")
        settings.save_web_overrides.assert_called_once_with({"response_style": "casual"})


class ToolDiscoveryAvailabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _purge_server_modules()
        sys.path.insert(0, str(ROOT / "jarvis-web"))
        from server.services import tool_discovery
        cls.tool_discovery = tool_discovery

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

    def _service(self, skills_dir: Path, db_enabled_names: list[str]):
        import memory_db

        fake_db = MagicMock()
        fake_db.get_enabled_tool_names.return_value = db_enabled_names
        fake_db.get_tool_info.return_value = {"description": "from db"}

        os.environ["JARVIS_TOOL_PROFILE"] = "default"
        try:
            with (
                patch.object(self.tool_discovery, "get_web_setting", return_value=[]),
                patch.object(memory_db, "get_memory_db", return_value=fake_db),
            ):
                return self.tool_discovery.ToolDiscoveryService(skills_path=skills_dir)
        finally:
            os.environ.pop("JARVIS_TOOL_PROFILE", None)

    def test_stale_db_row_cannot_resurrect_unavailable_manifest_tool(self):
        with TemporaryDirectory() as tmp:
            skills = Path(tmp)
            self._write_manifest(
                skills, "needs_key_tool",
                {"availability": {"all_of_env": ["ZZTEST_WEB_KEY"], "setup_hint": "add it"}},
            )
            # DB still has an enabled row for the tool (sync hasn't run yet)
            service = self._service(skills, ["needs_key_tool"])

            tool = service.get_tool("needs_key_tool")
            self.assertIsNotNone(tool)
            # The manifest entry wins: NOT resurrected as a database tool
            self.assertEqual(tool["source"], "local")
            self.assertFalse(tool["enabled"])
            self.assertFalse(tool["available"])
            self.assertEqual(tool["missing"], ["ZZTEST_WEB_KEY"])
            self.assertEqual(tool["setup_hint"], "add it")

    def test_available_tool_enabled_and_summary_fields(self):
        with TemporaryDirectory() as tmp:
            skills = Path(tmp)
            self._write_manifest(skills, "plain_tool")
            service = self._service(skills, [])
            summary = service.get_tools_summary()
            entry = next(t for t in summary if t["name"] == "plain_tool")
            self.assertTrue(entry["enabled"])
            self.assertTrue(entry["available"])
            self.assertEqual(entry["missing"], [])

    def test_stats_count_unavailable(self):
        with TemporaryDirectory() as tmp:
            skills = Path(tmp)
            self._write_manifest(skills, "plain_tool")
            self._write_manifest(
                skills, "needs_key_tool",
                {"availability": {"all_of_env": ["ZZTEST_WEB_KEY2"]}},
            )
            service = self._service(skills, [])
            stats = service.get_stats()
            self.assertEqual(stats["unavailable"], 1)
            self.assertEqual(stats["enabled"], 1)

    def test_tool_count_excludes_unavailable_tools(self):
        with TemporaryDirectory() as tmp:
            skills = Path(tmp)
            self._write_manifest(skills, "plain_tool")
            self._write_manifest(
                skills, "needs_key_tool",
                {"availability": {"all_of_env": ["ZZTEST_WEB_KEY3"]}},
            )
            service = self._service(skills, [])
            # Callable count excludes the unavailable tool; the raw map
            # (include_blocked) still contains it for diagnostics.
            self.assertEqual(service.get_tool_count(), 1)
            self.assertEqual(service.get_tool_count(include_blocked=True), 2)


if __name__ == "__main__":
    unittest.main()
