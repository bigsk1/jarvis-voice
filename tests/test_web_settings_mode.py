#!/usr/bin/env python3
"""Regression coverage for Web settings mode/session consistency."""

import json
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

    def test_api_key_status_is_mode_scoped_grouped_and_secret_free(self):
        import config_loader
        from server.services.settings_manager import SettingsManager

        secrets = {
            "cloud-serp-secret",
            "cloud-brave-secret",
            "cloud-tmdb-secret",
            "cloud-cf-token-secret",
            "cloud-cf-account-secret",
            "local-brave-alias-secret",
            "local-openai-secret",
            "local-spotify-id-secret",
            "local-spotify-client-secret",
        }
        configs = {
            "cloud": {
                "SERP_API_KEY": "cloud-serp-secret",
                "BRAVE_API_KEY": "cloud-brave-secret",
                "TMDB_API_KEY": "cloud-tmdb-secret",
                "CLOUDFLARE_API_TOKEN": "cloud-cf-token-secret",
                "CLOUDFLARE_ACCOUNT_ID": "cloud-cf-account-secret",
            },
            "local": {
                "BRAVE_SEARCH_API_KEY": "local-brave-alias-secret",
                "OPENAI_API_KEY": "local-openai-secret",
                "SPOTIFY_CLIENT_ID": "local-spotify-id-secret",
                "SPOTIFY_CLIENT_SECRET": "local-spotify-client-secret",
            },
        }

        def fake_load_mode_config(mode):
            return dict(configs[mode])

        def item_by_id(sections, item_id):
            return next(
                item
                for section in sections
                for item in section["items"]
                if item["id"] == item_id
            )

        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(config_loader, "_load_mode_config", side_effect=fake_load_mode_config),
        ):
            with config_loader.config_scope("cloud"):
                cloud_manager = SettingsManager("cloud")
                cloud_status = cloud_manager._get_api_key_status()
                cloud_legacy = cloud_manager.get_settings_with_status()
            with config_loader.config_scope("local"):
                local_manager = SettingsManager("local")
                local_status = local_manager._get_api_key_status()
                local_legacy = local_manager.get_settings_with_status()

        self.assertEqual(item_by_id(cloud_status, "serpapi")["status"], "configured")
        self.assertEqual(item_by_id(local_status, "serpapi")["status"], "not_set")
        self.assertEqual(item_by_id(local_status, "brave")["status"], "configured")
        self.assertEqual(item_by_id(cloud_status, "tmdb")["status"], "configured")
        self.assertEqual(item_by_id(cloud_status, "cloudflare")["status"], "configured")
        self.assertEqual(item_by_id(local_status, "spotify")["status"], "configured")
        self.assertEqual(item_by_id(local_status, "ollama")["status"], "not_required")
        self.assertEqual(item_by_id(local_status, "openai")["status"], "configured")
        tool_section = next(section for section in cloud_status if section["id"] == "tools")
        self.assertEqual(
            [item["id"] for item in tool_section["items"]],
            [
                "serpapi",
                "brave",
                "coingecko",
                "openweather",
                "tmdb",
                "trakt",
                "github",
                "cloudflare",
                "spotify",
                "vapi",
            ],
        )
        for status in (cloud_status, local_status):
            for section in status:
                for item in section["items"]:
                    self.assertNotIn("value", item)
        self.assertEqual(cloud_legacy["SERP_API_KEY"]["value"], "***configured***")
        self.assertEqual(local_legacy["SERP_API_KEY"]["value"], "")

        serialized = json.dumps({
            "cloud": cloud_status,
            "local": local_status,
            "cloud_legacy": cloud_legacy,
            "local_legacy": local_legacy,
        })
        for secret in secrets:
            self.assertNotIn(secret, serialized)

    def test_api_key_ui_renders_grouped_presence_only(self):
        index_html = (ROOT / "jarvis-web" / "client" / "index.html").read_text()
        app_js = (ROOT / "jarvis-web" / "client" / "js" / "app.js").read_text()

        self.assertIn("Only configuration status is sent to the browser", index_html)
        self.assertIn("Array.isArray(apiKeys)", app_js)
        self.assertIn("Utils.escapeHtml(item.name", app_js)
        self.assertIn("Not required locally", app_js)
        api_start = app_js.index("// Populate API Keys status")
        api_end = app_js.index("// Populate Profile section", api_start)
        self.assertNotIn("item.value", app_js[api_start:api_end])

    def test_model_endpoint_returns_selected_provider_env_default(self):
        settings = MagicMock()
        settings._get_model_options_with_current.return_value = [
            {"id": "gpt-provider-default", "name": "Configured OpenAI model"}
        ]
        settings._get_env_provider_model.return_value = "gpt-provider-default"

        with (
            self.app.test_request_context("/api/settings/models/openai?mode=cloud"),
            patch.object(self.api, "get_settings_manager", return_value=settings),
            patch("server.config.load_jarvis_config"),
            patch("server.config.get_jarvis_setting", return_value="gpt-provider-default"),
        ):
            response = self.api.get_provider_models.__wrapped__("openai")

        body = response.get_json()
        self.assertEqual(body["default_model"], "gpt-provider-default")
        settings._get_env_provider_model.assert_called_once_with("openai")

    def test_tts_provider_metadata_matches_runtime_models_and_voices(self):
        from server.services import settings_manager as settings_module
        from server.services.settings_manager import SettingsManager

        configured = {
            "TTS_MODEL": "gpt-4o-mini-tts-custom",
            "VOICE": "cedar",
            "ELEVENLABS_TTS_MODEL": "eleven_v3",
            "ELEVENLABS_TTS_VOICE": "eleven-voice-id",
            "XAI_TTS_VOICE": "rex",
            "QWEN3_TTS_VOICE": "Jarvis Clone",
            "KOKORO_TTS_VOICE": "af_sky",
        }

        with patch.object(
            settings_module,
            "get_jarvis_setting",
            side_effect=lambda key, default="": configured.get(key, default),
        ):
            providers = SettingsManager._get_tts_providers_for_ui()

        self.assertEqual(providers["openai"]["model_name"], "gpt-4o-mini-tts-custom")
        self.assertEqual(providers["openai"]["voice_name"], "cedar")
        self.assertEqual(providers["elevenlabs"]["model_name"], "eleven_v3")
        self.assertEqual(providers["elevenlabs"]["voice_name"], "eleven-voice-id")
        self.assertEqual(providers["xai"]["voice_name"], "rex")
        self.assertNotIn("model_name", providers["xai"])
        self.assertEqual(providers["qwen3-tts"]["model_name"], "tts-1")
        self.assertEqual(providers["qwen3-tts"]["voice_name"], "Jarvis Clone")
        self.assertEqual(providers["kokoro"]["model_name"], "kokoro")
        self.assertEqual(providers["kokoro"]["voice_name"], "af_sky")

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

    def test_save_routes_router_prompt_version_through_structured_overrides(self):
        settings = MagicMock()
        settings.set_mode.return_value = True
        settings.save_web_overrides.return_value = True

        with (
            self.app.test_request_context(
                "/api/settings/web",
                method="PUT",
                json={"mode": "cloud", "router_prompt_version": "v1"},
            ),
            patch.object(self.api, "get_settings_manager", return_value=settings),
            patch.object(self.api, "reload_web_config"),
        ):
            response = self.api.update_web_settings()

        self.assertEqual(response.status_code, 200)
        settings.validate_web_overrides.assert_called_once_with({"router_prompt_version": "v1"})
        settings.save_web_overrides.assert_called_once_with({"router_prompt_version": "v1"})

    def test_save_routes_thinking_effort_through_structured_overrides(self):
        settings = MagicMock()
        settings.set_mode.return_value = True
        settings.save_web_overrides.return_value = True

        with (
            self.app.test_request_context(
                "/api/settings/web",
                method="PUT",
                json={"mode": "cloud", "thinking_effort": "low"},
            ),
            patch.object(self.api, "get_settings_manager", return_value=settings),
            patch.object(self.api, "reload_web_config"),
        ):
            response = self.api.update_web_settings()

        self.assertEqual(response.status_code, 200)
        settings.validate_web_overrides.assert_called_once_with({"thinking_effort": "low"})
        settings.save_web_overrides.assert_called_once_with({"thinking_effort": "low"})

    def test_save_routes_status_update_settings_through_structured_overrides(self):
        settings = MagicMock()
        settings.set_mode.return_value = True
        settings.save_web_overrides.return_value = True

        payload = {
            "status_llm_enabled": False,
            "status_phrase_mode": "unhinged",
        }
        with (
            self.app.test_request_context(
                "/api/settings/web",
                method="PUT",
                json={"mode": "cloud", **payload},
            ),
            patch.object(self.api, "get_settings_manager", return_value=settings),
            patch.object(self.api, "reload_web_config"),
        ):
            response = self.api.update_web_settings()

        self.assertEqual(response.status_code, 200)
        settings.validate_web_overrides.assert_called_once_with(payload)
        settings.save_web_overrides.assert_called_once_with(payload)

    def test_save_routes_music_provider_through_structured_overrides(self):
        settings = MagicMock()
        settings.set_mode.return_value = True
        settings.save_web_overrides.return_value = True

        with (
            self.app.test_request_context(
                "/api/settings/web",
                method="PUT",
                json={"mode": "cloud", "music_provider": "gemini"},
            ),
            patch.object(self.api, "get_settings_manager", return_value=settings),
            patch.object(self.api, "reload_web_config"),
        ):
            response = self.api.update_web_settings()

        self.assertEqual(response.status_code, 200)
        settings.validate_web_overrides.assert_called_once_with(
            {"music_provider": "gemini"}
        )
        settings.save_web_overrides.assert_called_once_with(
            {"music_provider": "gemini"}
        )

    def test_settings_reject_invalid_mode(self):
        with self.app.test_request_context("/api/settings?mode=hybrid"):
            response, status = self.api.get_settings()

        self.assertEqual(status, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_reset_uses_explicit_preview_mode(self):
        settings = MagicMock()
        settings.reset_to_defaults.return_value = True

        with (
            self.app.test_request_context(
                "/api/settings/reset",
                method="POST",
                json={"mode": "local"},
            ),
            patch.object(self.api, "get_settings_manager", return_value=settings),
            patch.object(self.api, "get_web_setting") as get_default,
        ):
            response = self.api.reset_settings()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        settings.reset_to_defaults.assert_called_once_with()
        get_default.assert_not_called()

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

    def test_web_config_example_mode_keys_match_reset_defaults(self):
        from server.services import settings_manager as settings_module
        from server.services.settings_manager import SettingsManager

        example_path = ROOT / "jarvis-web" / "config" / "web_config.json.example"
        example = json.loads(example_path.read_text())
        reset_config = {"cloud": {"stale": "value"}, "local": {}}
        settings = SettingsManager("cloud")

        with (
            patch.object(settings_module, "load_web_config", return_value=reset_config),
            patch.object(settings_module, "save_web_config", return_value=True),
        ):
            self.assertTrue(settings.reset_to_defaults())

        reset_keys = set(reset_config["cloud"])
        self.assertEqual(set(example["cloud"]), reset_keys)
        self.assertEqual(set(example["local"]), reset_keys)
        self.assertTrue(all(value is None for value in example["cloud"].values()))
        self.assertTrue(all(value is None for value in example["local"].values()))

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

    def test_direct_ollama_discovery_keeps_canonical_cloud_ids(self):
        from server.services import settings_manager as settings_module

        response = MagicMock(status_code=200)
        response.json.return_value = {
            "models": [
                {"name": "qwen3.5:397b", "size": 0},
                {"name": "minimax-m3", "size": 0},
            ]
        }
        env = {
            "OLLAMA_API_KEY": "configured",
            "OLLAMA_CLOUD_MODEL": "minimax-m3",
        }
        with (
            patch.object(settings_module, "get_jarvis_setting", side_effect=lambda key, default="": env.get(key, default)),
            patch.object(settings_module, "request_ollama", return_value=(response, "https://ollama.com")) as request_ollama,
        ):
            models = settings_module.fetch_ollama_models(
                "http://daemon:11434",
                mode="cloud",
            )

        self.assertEqual([model["id"] for model in models], ["minimax-m3", "qwen3.5:397b"])
        self.assertIn("env default", models[0]["name"])
        self.assertTrue(all(model["context"] == "cloud" for model in models))
        self.assertIsNone(request_ollama.call_args.kwargs["base_url"])
        self.assertTrue(request_ollama.call_args.kwargs["cloud_access"])

    def test_ollama_show_metadata_distinguishes_vision_and_context(self):
        from server.services import settings_manager as settings_module

        glm = settings_module._parse_ollama_show_metadata({
            "capabilities": ["thinking", "completion", "tools"],
            "model_info": {"glm5.2.context_length": 1_000_000},
            "details": {"parameter_size": "756162687872"},
        })
        minimax = settings_module._parse_ollama_show_metadata({
            "capabilities": ["completion", "tools", "thinking", "vision"],
            "model_info": {"minimax.context_length": 524_288},
        })

        self.assertEqual(glm["context"], "1M")
        self.assertEqual(glm["parameter_size"], "756B")
        self.assertFalse(glm["vision"])
        self.assertEqual(glm["capabilities"], ["thinking", "tools"])
        self.assertTrue(minimax["vision"])
        self.assertIn("vision", minimax["capabilities"])

    def test_direct_ollama_discovery_pins_saved_alias_without_stale_selected_label(self):
        from server.services import settings_manager as settings_module

        response = MagicMock(status_code=200)
        response.json.return_value = {
            "models": [
                {"name": "minimax-m3", "modified_at": "2026-06-01T00:00:00Z", "size": 0},
                {"name": "glm-5.2", "modified_at": "2026-06-16T00:00:00Z", "size": 0},
            ]
        }
        env = {
            "OLLAMA_API_KEY": "configured",
            "OLLAMA_CLOUD_MODEL": "minimax-m3:cloud",
        }
        with (
            patch.object(settings_module, "get_jarvis_setting", side_effect=lambda key, default="": env.get(key, default)),
            patch.object(settings_module, "request_ollama", return_value=(response, "https://ollama.com")),
        ):
            models = settings_module.fetch_ollama_models(
                mode="cloud",
                selected_models=["glm-5.2:cloud"],
            )

        self.assertEqual(
            [model["id"] for model in models],
            ["glm-5.2:cloud", "minimax-m3:cloud", "glm-5.2", "minimax-m3"],
        )
        self.assertEqual(models[0]["name"], "glm-5.2:cloud")
        self.assertIn("env default", models[1]["name"])

    def test_local_ollama_discovery_cloud_cards_require_opt_in(self):
        from server.services import settings_manager as settings_module

        response = MagicMock(status_code=200)
        response.json.return_value = {
            "models": [
                {"name": "gemma4", "size": 1024**3},
                {"name": "minimax-m3:cloud", "size": 0},
            ]
        }

        def discover(flag):
            env = {"ALLOW_OLLAMA_CLOUD": flag, "OLLAMA_MODEL": "gemma4"}
            with (
                patch.object(settings_module, "get_jarvis_setting", side_effect=lambda key, default="": env.get(key, default)),
                patch.object(settings_module, "request_ollama", return_value=(response, "http://daemon:11434")),
            ):
                return settings_module.fetch_ollama_models("http://daemon:11434", mode="local")

        self.assertEqual([model["id"] for model in discover("false")], ["gemma4"])
        self.assertEqual(
            [model["id"] for model in discover("true")],
            ["gemma4", "minimax-m3:cloud"],
        )

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

    def test_catalog_alias_replaces_canonical_option_without_custom_duplicate(self):
        from server.services.settings_manager import SettingsManager

        settings = SettingsManager("cloud")
        with patch.object(settings, "_xai_uses_oauth", return_value=False):
            options = settings._get_model_options_with_current(
                "xai", "grok-4.20-non-reasoning-latest"
            )

        matching = [
            option
            for option in options
            if "Grok 4.20 Non-Reasoning" in option["name"]
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["id"], "grok-4.20-non-reasoning-latest")
        self.assertIn("configured alias", matching[0]["name"])

    def test_grok_build_latest_alias_uses_grok_45_dropdown_capabilities(self):
        from server.services.settings_manager import SettingsManager

        settings = SettingsManager("cloud")
        with patch.object(settings, "_xai_uses_oauth", return_value=False):
            options = settings._get_model_options_with_current("xai", "grok-build-latest")

        matching = [option for option in options if option["id"] == "grok-build-latest"]
        self.assertEqual(len(matching), 1)
        self.assertIn("Grok 4.5", matching[0]["name"])
        self.assertIn("configured alias", matching[0]["name"])
        self.assertEqual(matching[0]["context"], "500K")
        self.assertTrue(matching[0]["vision"])
        self.assertIn("vision", matching[0]["capabilities"])
        self.assertIn("thinking", matching[0]["capabilities"])

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

    def test_save_allows_local_cloud_model_when_opted_in(self):
        from server.services import settings_manager as settings_module
        from server.services.settings_manager import SettingsManager

        web_config = {"local": {}}
        env = {
            "LLM_PROVIDER": "ollama",
            "ALLOW_OLLAMA_CLOUD": "true",
            "OLLAMA_MODEL": "gemma4",
        }
        settings = SettingsManager("local")
        with (
            patch.object(settings, "_ensure_jarvis_config"),
            patch.object(settings_module, "load_web_config", return_value=web_config),
            patch.object(settings_module, "get_jarvis_setting", side_effect=lambda key, default="": env.get(key, default)),
            patch.object(settings_module, "save_web_config", return_value=True),
        ):
            success = settings.save_web_overrides({
                "llm_provider": "ollama",
                "llm_model": "minimax-m3:cloud",
            })

        self.assertTrue(success)
        self.assertEqual(web_config["local"]["llm_model"], "minimax-m3:cloud")

    def test_numeric_override_false_when_web_value_matches_env(self):
        from server.services import settings_manager as settings_module
        from server.services.settings_manager import SettingsManager

        web_config = {
            "cloud": {
                "qa_word_limit": 200,
                "multi_turn_word_limit": 250,
                "completion_guard_auto_threshold": 0.89,
                "tool_rag_limit": 15,
            },
            "audio": {},
            "ui": {},
            "conversation": {},
            "tools": {},
        }
        env = {
            "JARVIS_QA_WORD_LIMIT": "200",
            "JARVIS_MULTI_TURN_WORD_LIMIT": "250",
            "JARVIS_COMPLETION_GUARD_AUTO_THRESHOLD": "0.89",
            "CLOUD_TOOL_RAG_LIMIT": "15",
        }

        def get_setting(key, default=""):
            return env.get(key, default)

        settings = SettingsManager("cloud")
        with (
            patch.object(settings, "_ensure_jarvis_config"),
            patch.object(settings_module, "load_web_config", return_value=web_config),
            patch.object(settings_module, "get_jarvis_setting", side_effect=get_setting),
            patch.object(settings, "_get_provider_models", return_value={}),
        ):
            result = settings.get_settings_for_ui()

        self.assertFalse(result["response"]["qa_word_limit"]["is_override"])
        self.assertFalse(result["response"]["multi_turn_word_limit"]["is_override"])
        self.assertFalse(result["completion_guard"]["auto_threshold"]["is_override"])
        self.assertFalse(result["tool_rag"]["limit"]["is_override"])
        self.assertEqual(result["response"]["qa_word_limit"]["value"], 200)
        self.assertEqual(result["tool_rag"]["limit"]["value"], 15)
        self.assertEqual(result["completion_guard"]["auto_threshold"]["value"], 0.89)

    def test_save_clears_numeric_override_when_matching_env(self):
        from server.services import settings_manager as settings_module
        from server.services.settings_manager import SettingsManager

        web_config = {"cloud": {"qa_word_limit": 150}}
        env = {
            "JARVIS_QA_WORD_LIMIT": "200",
            "JARVIS_MULTI_TURN_WORD_LIMIT": "250",
            "JARVIS_COMPLETION_GUARD_AUTO_THRESHOLD": "0.89",
            "CLOUD_TOOL_RAG_LIMIT": "15",
        }

        def get_setting(key, default=""):
            return env.get(key, default)

        settings = SettingsManager("cloud")
        with (
            patch.object(settings, "_ensure_jarvis_config"),
            patch.object(settings_module, "load_web_config", return_value=web_config),
            patch.object(settings_module, "get_jarvis_setting", side_effect=get_setting),
            patch.object(settings_module, "save_web_config", return_value=True),
        ):
            success = settings.save_web_overrides({
                "qa_word_limit": 200,
                "multi_turn_word_limit": 250,
                "tool_rag_limit": 15,
                "completion_guard_auto_threshold": 0.89,
            })

        self.assertTrue(success)
        self.assertIsNone(web_config["cloud"]["qa_word_limit"])
        self.assertIsNone(web_config["cloud"]["multi_turn_word_limit"])
        self.assertIsNone(web_config["cloud"]["tool_rag_limit"])
        self.assertIsNone(web_config["cloud"]["completion_guard_auto_threshold"])

    def test_tool_rag_limit_override_is_validated_and_saved_per_mode(self):
        from server.services import settings_manager as settings_module
        from server.services.settings_manager import SettingsManager, SettingsValidationError

        web_config = {"cloud": {}}
        settings = SettingsManager("cloud")
        with (
            patch.object(settings, "_ensure_jarvis_config"),
            patch.object(settings_module, "load_web_config", return_value=web_config),
            patch.object(settings_module, "get_jarvis_setting", side_effect=lambda key, default="": default),
            patch.object(settings_module, "save_web_config", return_value=True),
        ):
            self.assertTrue(settings.save_web_overrides({"tool_rag_limit": 9}))
            self.assertEqual(web_config["cloud"]["tool_rag_limit"], 9)

            with self.assertRaises(SettingsValidationError):
                settings.save_web_overrides({"tool_rag_limit": 0})
            with self.assertRaises(SettingsValidationError):
                settings.save_web_overrides({"tool_rag_limit": 51})

        self.assertEqual(web_config["cloud"]["tool_rag_limit"], 9)

    def test_router_prompt_override_is_allowlisted_and_saved_per_mode(self):
        from server.services import settings_manager as settings_module
        from server.services.settings_manager import SettingsManager, SettingsValidationError

        web_config = {"cloud": {}}
        settings = SettingsManager("cloud")
        with (
            patch.object(settings, "_ensure_jarvis_config"),
            patch.object(settings_module, "load_web_config", return_value=web_config),
            patch.object(settings_module, "get_jarvis_setting", side_effect=lambda key, default="": default),
            patch.object(settings_module, "save_web_config", return_value=True),
        ):
            self.assertTrue(settings.save_web_overrides({"router_prompt_version": "v1"}))
            self.assertEqual(web_config["cloud"]["router_prompt_version"], "v1")
            self.assertTrue(settings.save_web_overrides({"router_prompt_version": "v2"}))
            self.assertEqual(web_config["cloud"]["router_prompt_version"], "v2")
            self.assertTrue(settings.save_web_overrides({"router_prompt_version": "v3"}))
            self.assertEqual(web_config["cloud"]["router_prompt_version"], "v3")
            self.assertTrue(settings.save_web_overrides({"router_prompt_version": "v4"}))
            self.assertEqual(web_config["cloud"]["router_prompt_version"], "v4")

            with self.assertRaises(SettingsValidationError):
                settings.save_web_overrides({"router_prompt_version": "v9"})

        self.assertEqual(web_config["cloud"]["router_prompt_version"], "v4")

    def test_status_update_overrides_are_validated_and_saved_per_mode(self):
        from server.services import settings_manager as settings_module
        from server.services.settings_manager import SettingsManager, SettingsValidationError

        web_config = {"cloud": {}}
        settings = SettingsManager("cloud")
        with (
            patch.object(settings, "_ensure_jarvis_config"),
            patch.object(settings_module, "load_web_config", return_value=web_config),
            patch.object(settings_module, "get_jarvis_setting", side_effect=lambda key, default="": default),
            patch.object(settings_module, "save_web_config", return_value=True),
        ):
            self.assertTrue(settings.save_web_overrides({
                "status_llm_enabled": False,
                "status_phrase_mode": "unhinged",
            }))
            self.assertIs(web_config["cloud"]["status_llm_enabled"], False)
            self.assertEqual(web_config["cloud"]["status_phrase_mode"], "unhinged")

            with self.assertRaises(SettingsValidationError):
                settings.save_web_overrides({"status_llm_enabled": "false"})
            with self.assertRaises(SettingsValidationError):
                settings.save_web_overrides({"status_phrase_mode": "chaotic"})

        self.assertIs(web_config["cloud"]["status_llm_enabled"], False)
        self.assertEqual(web_config["cloud"]["status_phrase_mode"], "unhinged")

    def test_settings_payload_describes_status_defaults_and_overrides(self):
        from server.services import settings_manager as settings_module
        from server.services.settings_manager import SettingsManager

        web_config = {
            "cloud": {
                "status_llm_enabled": False,
                "status_phrase_mode": "unhinged",
            },
            "audio": {},
            "ui": {},
            "conversation": {},
            "tools": {},
        }
        settings = SettingsManager("cloud")
        with (
            patch.object(settings, "_ensure_jarvis_config"),
            patch.object(settings_module, "load_web_config", return_value=web_config),
            patch.object(
                settings_module,
                "get_jarvis_setting",
                side_effect=lambda key, default="": {
                    "STATUS_LLM_ENABLED": "true",
                    "STATUS_PHRASE_MODE": "normal",
                }.get(key, default),
            ),
            patch.object(settings, "_get_provider_models", return_value={}),
            patch.object(settings, "_get_api_key_status", return_value={}),
            patch.object(settings, "get_provider_availability", return_value={}),
        ):
            payload = settings.get_settings_for_ui()

        self.assertEqual(payload["status_updates"]["llm_enabled"], {
            "value": False,
            "default": True,
            "is_override": True,
        })
        self.assertEqual(payload["status_updates"]["phrase_mode"], {
            "value": "unhinged",
            "default": "normal",
            "is_override": True,
            "options": ["normal", "unhinged"],
        })

    def test_status_update_controls_are_loaded_and_saved_by_the_web_client(self):
        index_html = (ROOT / "jarvis-web" / "client" / "index.html").read_text()
        app_js = (ROOT / "jarvis-web" / "client" / "js" / "app.js").read_text()

        self.assertIn('id="setting-status-llm-enabled"', index_html)
        self.assertIn('id="setting-status-phrase-mode"', index_html)
        self.assertIn("s.status_updates?.llm_enabled", app_js)
        self.assertIn("s.status_updates?.phrase_mode", app_js)
        self.assertIn("status_llm_enabled: parseNullableBool", app_js)
        self.assertIn("status_phrase_mode: document.getElementById", app_js)
        self.assertIn('<span class="config-label">Status personality</span>', app_js)
        self.assertNotIn("${Utils.escapeHtml(effectiveStatusPhraseMode)} static phrases", app_js)

    def test_settings_payload_describes_router_prompt_default_and_override(self):
        from server.services import settings_manager as settings_module
        from server.services.settings_manager import SettingsManager

        web_config = {
            "cloud": {"router_prompt_version": "v1"},
            "audio": {},
            "ui": {},
            "conversation": {},
            "tools": {},
        }
        settings = SettingsManager("cloud")
        with (
            patch.object(settings, "_ensure_jarvis_config"),
            patch.object(settings_module, "load_web_config", return_value=web_config),
            patch.object(
                settings_module,
                "get_jarvis_setting",
                side_effect=lambda key, default="": {
                    "JARVIS_ROUTER_PROMPT_VERSION": "v1",
                }.get(key, default),
            ),
            patch.object(settings, "_get_provider_models", return_value={}),
            patch.object(settings, "_get_api_key_status", return_value={}),
            patch.object(settings, "get_provider_availability", return_value={}),
        ):
            payload = settings.get_settings_for_ui()

        self.assertEqual(payload["router_prompt"]["version"], {
            "value": "v1",
            "default": "v1",
            "is_override": True,
            "options": [
                {"id": "v1", "label": "v1 - Full context system prompt"},
                {"id": "v2", "label": "v2 - Compact full-context prompt"},
                {"id": "v3", "label": "v3 - Caveman hybrid prompt"},
                {"id": "v4", "label": "v4 - Caveman-light hybrid prompt"},
            ],
        })

    def test_settings_payload_describes_thinking_effort_default_and_override(self):
        from server.services import settings_manager as settings_module
        from server.services.settings_manager import SettingsManager

        web_config = {
            "cloud": {"thinking_effort": "low"},
            "audio": {},
            "ui": {},
            "conversation": {},
            "tools": {},
        }
        settings = SettingsManager("cloud")
        with (
            patch.object(settings, "_ensure_jarvis_config"),
            patch.object(settings_module, "load_web_config", return_value=web_config),
            patch.object(
                settings_module,
                "get_jarvis_setting",
                side_effect=lambda key, default="": {
                    "JARVIS_THINKING_EFFORT": "auto",
                }.get(key, default),
            ),
            patch.object(settings, "_get_provider_models", return_value={}),
            patch.object(settings, "_get_api_key_status", return_value={}),
            patch.object(settings, "get_provider_availability", return_value={}),
        ):
            payload = settings.get_settings_for_ui()

        self.assertEqual(payload["llm"]["thinking_effort"]["value"], "low")
        self.assertEqual(payload["llm"]["thinking_effort"]["default"], "auto")
        self.assertTrue(payload["llm"]["thinking_effort"]["is_override"])
        self.assertIn("high", payload["llm"]["thinking_effort"]["options"])
        self.assertTrue(payload["llm"]["thinking_effort"]["profiled"])

    def test_thinking_effort_validation_rejects_unknown_value(self):
        from server.services.settings_manager import SettingsManager, SettingsValidationError

        settings = SettingsManager("cloud")
        with patch.object(settings, "_ensure_jarvis_config"):
            with self.assertRaises(SettingsValidationError) as context:
                settings.validate_web_overrides({"thinking_effort": "ultra"})

        self.assertEqual(context.exception.field, "thinking_effort")

    def test_glm_web_effort_options_come_from_model_profile(self):
        from server.services.settings_manager import _model_thinking_effort_options

        options, profiled = _model_thinking_effort_options(
            "ollama",
            "glm-5.3-flash:cloud",
            "cloud",
        )

        self.assertTrue(profiled)
        self.assertEqual(options, ["low", "high", "max"])
        self.assertNotIn("medium", options)

    def test_xai_web_effort_options_distinguish_none_from_provider_default(self):
        from server.services.settings_manager import _model_thinking_effort_options

        grok_46, profiled_46 = _model_thinking_effort_options(
            "xai", "grok-4.6", "cloud"
        )
        grok_43, profiled_43 = _model_thinking_effort_options(
            "xai", "grok-4.3", "cloud"
        )

        self.assertTrue(profiled_46)
        self.assertEqual(grok_46, ["low", "medium", "high", "xhigh"])
        self.assertNotIn("off", grok_46)
        self.assertTrue(profiled_43)
        self.assertEqual(grok_43, ["none", "low", "medium", "high"])
        self.assertNotIn("off", grok_43)

    def test_unprofiled_model_has_no_web_effort_options(self):
        from server.services.settings_manager import _model_thinking_effort_options

        options, profiled = _model_thinking_effort_options(
            "openai", "gpt-4o-mini", "cloud"
        )

        self.assertFalse(profiled)
        self.assertEqual(options, [])

    def test_openai_web_effort_options_follow_selected_model_profile(self):
        from server.services.settings_manager import _model_thinking_effort_options

        gpt_56, profiled_56 = _model_thinking_effort_options(
            "openai", "gpt-5.6-sol", "cloud"
        )
        gpt_5_mini, profiled_5_mini = _model_thinking_effort_options(
            "openai", "gpt-5-mini", "cloud"
        )

        self.assertTrue(profiled_56)
        self.assertEqual(gpt_56, ["none", "low", "medium", "high", "xhigh", "max"])
        self.assertTrue(profiled_5_mini)
        self.assertEqual(gpt_5_mini, ["minimal", "low", "medium", "high"])

    def test_openai_yaml_thinking_profile_wins_in_web_options(self):
        from model_prompt_overrides import ModelThinkingOverride
        from server.services.settings_manager import _model_thinking_effort_options

        yaml_profile = ModelThinkingOverride(
            supported=True,
            disable_supported=False,
            levels=("low", "high"),
            default_level="high",
            disabled_fallback_level="low",
        )
        with patch(
            "model_prompt_overrides.load_model_prompt_override",
            return_value=MagicMock(thinking=yaml_profile),
        ):
            options, profiled = _model_thinking_effort_options(
                "openai", "gpt-5.6-sol", "cloud"
            )

        self.assertTrue(profiled)
        self.assertEqual(options, ["low", "high"])

    def test_thinking_effort_validation_uses_effective_model_levels(self):
        from server.services.settings_manager import SettingsManager, SettingsValidationError

        settings = SettingsManager("cloud")
        with (
            patch.object(settings, "_ensure_jarvis_config"),
            patch.object(settings, "_validate_provider_overrides"),
            patch.object(
                settings,
                "_effective_llm_selection_for_overrides",
                return_value=("ollama", "glm-5.3:cloud"),
            ),
        ):
            with self.assertRaises(SettingsValidationError) as context:
                settings.validate_web_overrides({"thinking_effort": "medium"})
            settings.validate_web_overrides({"thinking_effort": "high"})

        self.assertEqual(context.exception.field, "thinking_effort")
        self.assertIn("glm-5.3:cloud", context.exception.reason)

    def test_thinking_effort_validation_rejects_unprofiled_model(self):
        from server.services.settings_manager import SettingsManager, SettingsValidationError

        settings = SettingsManager("cloud")
        with (
            patch.object(settings, "_ensure_jarvis_config"),
            patch.object(settings, "_validate_provider_overrides"),
            patch.object(
                settings,
                "_effective_llm_selection_for_overrides",
                return_value=("openai", "gpt-4o-mini"),
            ),
        ):
            with self.assertRaises(SettingsValidationError) as context:
                settings.validate_web_overrides({"thinking_effort": "high"})

        self.assertIn("unprofiled model", context.exception.reason)

    def test_provider_only_save_clears_stale_incompatible_thinking_effort(self):
        from server.services import settings_manager as settings_module
        from server.services.settings_manager import SettingsManager

        web_config = {
            "cloud": {
                "llm_provider": "ollama",
                "llm_model": "glm-5.3:cloud",
                "thinking_effort": "high",
            }
        }
        settings = SettingsManager("cloud")
        with (
            patch.object(settings, "_ensure_jarvis_config"),
            patch.object(settings, "_validate_provider_overrides"),
            patch.object(settings_module, "load_web_config", return_value=web_config),
            patch.object(
                settings_module,
                "get_jarvis_setting",
                side_effect=lambda key, default="": default,
            ),
            patch.object(settings_module, "save_web_config", return_value=True),
        ):
            self.assertTrue(
                settings.save_web_overrides(
                    {"llm_provider": "openai", "llm_model": "gpt-4o-mini"}
                )
            )

        self.assertIsNone(web_config["cloud"]["thinking_effort"])

    def test_thinking_effort_control_is_loaded_and_saved_by_web_client(self):
        index_html = (ROOT / "jarvis-web" / "client" / "index.html").read_text()
        app_js = (ROOT / "jarvis-web" / "client" / "js" / "app.js").read_text()
        chat_py = (ROOT / "jarvis-web" / "server" / "sockets" / "chat.py").read_text()

        self.assertIn('id="setting-thinking-effort"', index_html)
        self.assertIn('id="thinking-effort-group" hidden', index_html)
        self.assertIn("s.llm?.thinking_effort", app_js)
        self.assertIn("_updateThinkingEffortControl(provider)", app_js)
        self.assertIn("thinking_effort: document.getElementById", app_js)
        self.assertIn("'thinking_effort': 'JARVIS_THINKING_EFFORT'", chat_py)


if __name__ == "__main__":
    unittest.main()
