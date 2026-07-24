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


if __name__ == "__main__":
    unittest.main()
