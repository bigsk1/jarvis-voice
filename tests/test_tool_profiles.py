"""Unit tests for skills/profiles overlay merge logic."""
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

# lib/ on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))


class TestToolProfiles(unittest.TestCase):
    def test_profiles_gate_external_network_intel_by_online_lookup_scope(self):
        examples_dir = ROOT / "skills" / "profiles" / "examples"
        disabled_examples = {
            "creative_media_lab.json",
            "docs_kb_curator.json",
            "home_routines.json",
            "local_home_voice.json",
            "memory_and_artifacts.json",
            "offline.json",
            "offline_lan_first.json",
        }
        retained_examples = {
            "docker.json",
            "local_daily_driver.json",
            "local_minimal_assistant.json",
            "local_research_lite.json",
            "local_terminal_ops.json",
            "research_pipeline.json",
            "workstation_ops.json",
        }

        for profile_name in sorted(disabled_examples):
            overrides = json.loads(
                (examples_dir / profile_name).read_text(encoding="utf-8")
            )["overrides"]
            self.assertIs(overrides.get("external_network_intel"), False)

        for profile_name in sorted(retained_examples):
            overrides = json.loads(
                (examples_dir / profile_name).read_text(encoding="utf-8")
            )["overrides"]
            self.assertIsNot(overrides.get("external_network_intel"), False)

        profiles_dir = ROOT / "skills" / "profiles"
        for profile_name in ("offline.json",):
            overrides = json.loads(
                (profiles_dir / profile_name).read_text(encoding="utf-8")
            )["overrides"]
            self.assertIs(overrides.get("external_network_intel"), False)

        for profile_name in (
            "default.json", "docker.json", "docker-mcp.json",
            "local_minimal_assistant.json", "openai_only.json"
        ):
            overrides = json.loads(
                (profiles_dir / profile_name).read_text(encoding="utf-8")
            )["overrides"]
            self.assertIsNot(overrides.get("external_network_intel"), False)

    def test_narrow_profiles_gate_document_ocr_when_document_work_is_out_of_scope(self):
        examples_dir = ROOT / "skills" / "profiles" / "examples"
        disabled_profiles = {
            "creative_media_lab.json",
            "home_routines.json",
            "local_home_voice.json",
            "local_minimal_assistant.json",
            "local_terminal_ops.json",
            "workstation_ops.json",
        }
        retained_profiles = {
            "docker.json",
            "docs_kb_curator.json",
            "local_daily_driver.json",
            "local_research_lite.json",
            "memory_and_artifacts.json",
            "offline.json",
            "offline_lan_first.json",
            "research_pipeline.json",
        }

        for profile_name in sorted(disabled_profiles):
            overrides = json.loads(
                (examples_dir / profile_name).read_text(encoding="utf-8")
            )["overrides"]
            self.assertIs(
                overrides.get("document_ocr"),
                False,
                f"{profile_name} should keep document_ocr out of its narrow tool pool",
            )

        for profile_name in sorted(retained_profiles):
            overrides = json.loads(
                (examples_dir / profile_name).read_text(encoding="utf-8")
            )["overrides"]
            self.assertIsNot(
                overrides.get("document_ocr"),
                False,
                f"{profile_name} is intended to retain optional document/LAN OCR",
            )

    def test_narrow_example_profiles_explicitly_gate_optional_media_tools(self):
        media_tools = {
            "trakt_account",
            "trakt_movies",
            "trakt_tv_shows",
            "tmdb_movies",
            "tmdb_tv_shows",
        }
        examples_dir = ROOT / "skills" / "profiles" / "examples"
        for profile_path in sorted(examples_dir.glob("*.json")):
            if profile_path.name == "docker.json":
                continue
            overrides = json.loads(profile_path.read_text(encoding="utf-8"))["overrides"]
            for tool_name in media_tools:
                self.assertIs(
                    overrides.get(tool_name),
                    False,
                    f"{profile_path.name} must explicitly disable {tool_name}",
                )

    def test_example_profiles_explicitly_gate_serpapi_tools(self):
        """Keep new SerpApi verticals out of intentionally narrow profiles."""
        serpapi_tools = set()
        skills_dir = ROOT / "skills"
        for manifest_path in skills_dir.glob("*.tool.json"):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            script_name = manifest.get("script")
            if not script_name:
                continue
            script_path = skills_dir / script_name
            if (
                script_path.is_file()
                and "request_serpapi(" in script_path.read_text(encoding="utf-8")
            ):
                serpapi_tools.add(manifest["name"])

        self.assertIn("serpapi_tripadvisor", serpapi_tools)
        self.assertIn("serpapi_travel_explore", serpapi_tools)
        self.assertIn("serpapi_search_index", serpapi_tools)

        # Most examples remove the whole SerpApi family. The research pipeline
        # retains only Search Index source discovery; Amazon remains shopping-only.
        allowed_by_profile = {
            "creative_media_lab.json": set(),
            "docs_kb_curator.json": set(),
            "home_routines.json": set(),
            "local_daily_driver.json": set(),
            "local_home_voice.json": set(),
            "local_minimal_assistant.json": set(),
            "local_research_lite.json": set(),
            "local_terminal_ops.json": set(),
            "memory_and_artifacts.json": set(),
            "offline.json": set(),
            "offline_lan_first.json": set(),
            "research_pipeline.json": {
                "serpapi_search_index",
            },
            "workstation_ops.json": set(),
        }
        examples_dir = skills_dir / "profiles" / "examples"

        for profile_name, allowed in allowed_by_profile.items():
            profile = json.loads(
                (examples_dir / profile_name).read_text(encoding="utf-8")
            )
            overrides = profile["overrides"]
            for tool_name in serpapi_tools - allowed:
                self.assertIs(
                    overrides.get(tool_name),
                    False,
                    f"{profile_name} must explicitly disable {tool_name}",
                )
            for tool_name in allowed:
                self.assertIsNot(
                    overrides.get(tool_name),
                    False,
                    f"{profile_name} is intended to retain {tool_name}",
                )

    def test_effective_enabled_missing_uses_base(self):
        from tool_profiles import effective_enabled

        self.assertTrue(effective_enabled("weather", True, {}))
        self.assertFalse(effective_enabled("weather", False, {}))
        self.assertTrue(effective_enabled("weather", True, None))

    def test_effective_enabled_override_false(self):
        from tool_profiles import effective_enabled

        ov = {"weather": False}
        self.assertFalse(effective_enabled("weather", True, ov))
        self.assertFalse(effective_enabled("weather", True, ov))

    def test_effective_enabled_override_true(self):
        from tool_profiles import effective_enabled

        ov = {"weather": True}
        self.assertTrue(effective_enabled("weather", False, ov))

    def test_load_profile_overrides_from_file(self):
        from tool_profiles import load_profile_overrides

        with TemporaryDirectory() as tmp:
            os.environ["JARVIS_TOOL_PROFILE"] = "testprof"
            profiles = Path(tmp)
            # Patch get_profiles_dir — use monkeypatch via module
            import tool_profiles as tp

            orig = tp.get_profiles_dir
            try:
                tp.get_profiles_dir = lambda: profiles
                data = {"description": "t", "overrides": {"a": False, "b": True}}
                (profiles / "testprof.json").write_text(json.dumps(data), encoding="utf-8")
                self.assertEqual(load_profile_overrides("testprof"), {"a": False, "b": True})
            finally:
                tp.get_profiles_dir = orig
                del os.environ["JARVIS_TOOL_PROFILE"]

    def test_profile_can_remove_workflow_meta_tool_from_effective_registry(self):
        from tool_schema import ToolRegistry

        with TemporaryDirectory() as tmp:
            skills_dir = Path(tmp)
            (skills_dir / "workflow.tool.json").write_text(
                json.dumps(
                    {
                        "enabled": True,
                        "name": "workflow",
                        "description": "Workflow discovery",
                        "script": "workflow.py",
                        "parameters": {"type": "object", "properties": {}},
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch("tool_profiles.get_active_profile_name", return_value="minimal"),
                patch(
                    "tool_profiles.load_active_profile_overrides",
                    return_value={"workflow": False},
                ),
                patch("tool_profiles.warn_missing_profile_file"),
            ):
                registry = ToolRegistry(str(skills_dir))

        self.assertNotIn("workflow", registry.list_tools())

    def test_openai_only_profile_covers_non_openai_requirements(self):
        profile_path = ROOT / "skills" / "profiles" / "openai_only.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        overrides = profile["overrides"]

        self.assertTrue(overrides)
        self.assertTrue(all(value is False for value in overrides.values()))

        # These tools remain useful with one OpenAI key or no tool-specific key.
        for tool_name in (
            "analyze_image",
            "canvas",
            "generate_image",
            "generate_video",
            "pdf_create",
            "pdf_read",
            "stash",
            "tool_search",
            "weather",
            "workflow",
        ):
            self.assertNotIn(tool_name, overrides)

        # These legacy/personal integrations are not fully described by
        # credential availability metadata, so the starter profile gates them.
        for tool_name in (
            "check_opencode_sessions",
            "opencode",
            "phone_call",
            "printer",
            "supa_crawl_knowledge",
        ):
            self.assertIs(overrides.get(tool_name), False)

        one_key_environment = {"OPENAI_API_KEY"}

        def available_with_one_openai_key(availability):
            if not availability:
                return True
            if not set(availability.get("all_of_env", ())) <= one_key_environment:
                return False
            any_of_env = set(availability.get("any_of_env", ()))
            if any_of_env and not any_of_env & one_key_environment:
                return False
            if availability.get("config_files") or availability.get("webhook_registry"):
                return False

            providers = availability.get("provider_requirements") or {}
            if providers:
                requirements = providers.get("openai")
                if not isinstance(requirements, dict):
                    return False
                if not set(requirements.get("all_of_env", ())) <= one_key_environment:
                    return False
                any_provider_env = set(requirements.get("any_of_env", ()))
                if any_provider_env and not any_provider_env & one_key_environment:
                    return False
            return True

        for manifest_path in sorted((ROOT / "skills").glob("*.tool.json")):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not manifest.get("enabled", True):
                continue
            if available_with_one_openai_key(manifest.get("availability")):
                continue
            tool_name = manifest.get("name", manifest_path.stem)
            self.assertIs(
                overrides.get(tool_name),
                False,
                f"{tool_name} needs non-OpenAI setup but is not disabled",
            )


if __name__ == "__main__":
    unittest.main()
