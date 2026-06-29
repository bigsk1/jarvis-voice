#!/usr/bin/env python3
"""Regression coverage for Web settings mode/session consistency."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parent.parent


def _purge_server_modules() -> None:
    for key in list(sys.modules):
        if key == "server" or key.startswith("server."):
            del sys.modules[key]


class WebSettingsModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _purge_server_modules()
        sys.path.insert(0, str(ROOT / "jarvis-web"))
        from server.app import app
        from server.routes import api

        cls.app = app
        cls.api = api

    def test_get_settings_uses_cloud_session_over_stale_local_default(self):
        settings = MagicMock()
        settings.get_settings_for_ui.return_value = {"mode": "cloud"}
        settings.get_settings_with_status.return_value = {}
        settings.get_web_settings.return_value = {}

        with (
            self.app.test_request_context("/api/settings?mode=cloud"),
            patch.object(self.api, "get_settings_manager", return_value=settings) as get_manager,
            patch.object(self.api, "get_web_setting", return_value="local") as get_default,
        ):
            response = self.api.get_settings()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["settings"]["mode"], "cloud")
        get_manager.assert_called_once_with("cloud")
        get_default.assert_not_called()

    def test_save_persists_explicit_mode_even_when_socket_already_matches(self):
        settings = MagicMock()
        settings.set_mode.return_value = True
        settings.save_web_overrides.return_value = True

        with (
            self.app.test_request_context(
                "/api/settings/web",
                method="PUT",
                json={"mode": "cloud", "llm_provider": None},
            ),
            patch.object(self.api, "get_settings_manager", return_value=settings),
            patch.object(self.api, "reload_web_config"),
        ):
            response = self.api.update_web_settings()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        settings.set_mode.assert_called_once_with("cloud")
        settings.save_web_overrides.assert_called_once_with({"llm_provider": None})

    def test_settings_reject_invalid_mode(self):
        with self.app.test_request_context("/api/settings?mode=hybrid"):
            response, status = self.api.get_settings()

        self.assertEqual(status, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_set_mode_reports_web_config_write_failure(self):
        from server.services.settings_manager import SettingsManager

        settings = SettingsManager("local")
        with (
            patch.object(settings, "_ensure_jarvis_config"),
            patch.object(settings, "update_web_setting", return_value=False) as update_setting,
        ):
            success = settings.set_mode("cloud")

        self.assertFalse(success)
        self.assertEqual(settings.mode, "cloud")
        update_setting.assert_called_once_with("defaults.mode", "cloud")

    def test_save_surfaces_web_config_write_failure(self):
        settings = MagicMock()
        settings.set_mode.return_value = False

        with (
            self.app.test_request_context(
                "/api/settings/web",
                method="PUT",
                json={"mode": "cloud", "llm_provider": None},
            ),
            patch.object(self.api, "get_settings_manager", return_value=settings),
        ):
            response, status = self.api.update_web_settings()

        self.assertEqual(status, 500)
        self.assertIn("web_config.json", response.get_json()["error"])
        settings.save_web_overrides.assert_not_called()

    def test_ollama_default_follows_effective_provider_not_env_provider(self):
        from server.services import settings_manager as settings_module
        from server.services.settings_manager import SettingsManager

        web_config = {
            "cloud": {
                "llm_provider": "ollama",
                "llm_model": None,
                "completion_guard_eval_provider": "ollama",
                "completion_guard_eval_model": None,
            },
            "audio": {},
            "ui": {},
            "conversation": {},
            "tools": {},
        }
        env = {
            "LLM_PROVIDER": "xai",
            "XAI_MODEL": "grok-build-0.1",
            "OLLAMA_CLOUD_MODEL": "minimax-m3:cloud",
        }

        def get_setting(key, default=""):
            return env.get(key, default)

        settings = SettingsManager("cloud")
        with (
            patch.object(settings, "_ensure_jarvis_config"),
            patch.object(settings_module, "load_web_config", return_value=web_config),
            patch.object(settings_module, "get_jarvis_setting", side_effect=get_setting),
            patch.object(
                settings,
                "_get_provider_models",
                return_value={"ollama": [{"id": "minimax-m3:cloud", "name": "minimax-m3:cloud", "context": "cloud"}]},
            ),
        ):
            result = settings.get_settings_for_ui()

        self.assertEqual(result["llm"]["model"]["value"], "minimax-m3:cloud")
        self.assertEqual(result["llm"]["model"]["default"], "minimax-m3:cloud")
        self.assertFalse(result["llm"]["model"]["is_override"])
        self.assertEqual(result["completion_guard"]["eval_model"]["value"], "minimax-m3:cloud")
        self.assertEqual(result["completion_guard"]["eval_model"]["default"], "minimax-m3:cloud")

    def test_stale_cloud_catalog_model_is_ignored_for_local_ollama(self):
        from server.services import settings_manager as settings_module
        from server.services.settings_manager import SettingsManager

        web_config = {
            "local": {"llm_provider": "ollama", "llm_model": "grok-build-0.1"},
            "audio": {},
            "ui": {},
            "conversation": {},
            "tools": {},
        }
        env = {"LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "gemma4:12b"}

        def get_setting(key, default=""):
            return env.get(key, default)

        settings = SettingsManager("local")
        with (
            patch.object(settings, "_ensure_jarvis_config"),
            patch.object(settings_module, "load_web_config", return_value=web_config),
            patch.object(settings_module, "get_jarvis_setting", side_effect=get_setting),
            patch.object(
                settings,
                "_get_provider_models",
                return_value={"ollama": [{"id": "gemma4:12b", "name": "gemma4:12b", "context": "local"}]},
            ),
        ):
            result = settings.get_settings_for_ui()

        self.assertEqual(result["llm"]["model"]["value"], "gemma4:12b")
        self.assertFalse(result["llm"]["model"]["is_override"])

    def test_save_rejects_cross_mode_ollama_model(self):
        from server.services import settings_manager as settings_module
        from server.services.settings_manager import SettingsManager

        web_config = {"local": {}}
        settings = SettingsManager("local")
        with (
            patch.object(settings, "_ensure_jarvis_config"),
            patch.object(settings_module, "load_web_config", return_value=web_config),
            patch.object(settings_module, "get_jarvis_setting", side_effect=lambda key, default="": "ollama" if key == "LLM_PROVIDER" else default),
            patch.object(settings_module, "save_web_config", return_value=True),
        ):
            success = settings.save_web_overrides({
                "llm_provider": "ollama",
                "llm_model": "minimax-m3:cloud",
            })

        self.assertTrue(success)
        self.assertIsNone(web_config["local"]["llm_model"])


if __name__ == "__main__":
    unittest.main()
