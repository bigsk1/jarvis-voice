"""Unit tests for skills/profiles overlay merge logic."""
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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


if __name__ == "__main__":
    unittest.main()
