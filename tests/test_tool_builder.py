#!/usr/bin/env python3
"""Tool Builder regression tests (pending_api_key lifecycle + static verify).

The LLM is never called: specs are provided directly to _create_tool and the
approval path. Covers:
  - missing-key builds survive to pending with status pending_api_key and an
    availability block in the generated manifest (live run skipped)
  - availability blocks are emitted even when the key is ALREADY configured
  - env var names failing ^[A-Z][A-Z0-9_]*$ are rejected
  - static verification resolves imports via find_spec WITHOUT executing
    generated top-level code
  - approval is refused while the required key is absent (files stay pending)
    and succeeds with full verification once configured
  - approval uses the report card's original build mode
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

import tool_builder as tb  # noqa: E402


PASSING_TOOL_CODE = '''#!/usr/bin/env python3
import json
import sys

def main():
    print(json.dumps({"ok": True, "speech": "test ok", "data": {}}))

if __name__ == "__main__":
    main()
'''


def make_spec(**overrides):
    spec = {
        "action": "BUILD",
        "tool_name": "zztest_generated_tool",
        "description": "Test generated tool",
        "purpose": "testing",
        "capabilities": ["test"],
        "python_code": PASSING_TOOL_CODE,
        "parameters": {"type": "object", "properties": {}},
        "permissions": {
            "dangerous": False, "bash": False, "network": False,
            "filesystem": False, "auto_approve": True,
        },
        "test_input": {},
        "expected_output_contains": [],
        "packages_needed": [],
        "requires_new_api_key": False,
        "suggested_env_var": None,
        "required_env_vars": [],
    }
    spec.update(overrides)
    return spec


class BuilderDirsMixin(unittest.TestCase):
    """Redirect the builder's module-level directories into a temp tree."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        base = Path(self._tmp.name)
        self._patches = [
            patch.object(tb, "SKILLS_DIR", base),
            patch.object(tb, "AUTO_TOOLS_DIR", base / "auto-tools"),
            patch.object(tb, "PENDING_DIR", base / "pending"),
            patch.object(tb, "LOGS_DIR", base / "logs"),
        ]
        for p in self._patches:
            p.start()
        tb.AUTO_TOOLS_DIR.mkdir()
        tb.PENDING_DIR.mkdir()
        tb.LOGS_DIR.mkdir()
        self._env_added: list[str] = []

    def set_env(self, key, value):
        os.environ[key] = value
        if key not in self._env_added:
            self._env_added.append(key)

    def tearDown(self):
        for key in self._env_added:
            os.environ.pop(key, None)
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def make_builder(self):
        builder = tb.ToolBuilder.__new__(tb.ToolBuilder)
        builder.mode = "cloud"
        builder.provider_type = "test"
        builder.model = "test-model"
        return builder

    def create(self, spec):
        builder = self.make_builder()
        return builder._create_tool(
            spec=spec, gap_description="test gap", feedback_ids=[],
            existing_tools=[], retries=0,
        )


class TestExistingToolNames(BuilderDirsMixin):
    def write_manifest(self, directory, name, *, enabled=True, filename=None):
        directory.mkdir(exist_ok=True)
        path = directory / (filename or f"{name}.tool.json")
        path.write_text(json.dumps({
            "name": name,
            "description": "Private description fixture" if directory.name == "personal" else "Shared description",
            "enabled": enabled,
        }))
        return path

    def test_prompt_reserves_enabled_and_disabled_personal_names(self):
        self.write_manifest(tb.SKILLS_DIR, "zztest_shared")
        self.write_manifest(tb.AUTO_TOOLS_DIR, "zztest_automatic")
        self.write_manifest(tb.SKILLS_DIR / "personal", "zztest_personal")
        self.write_manifest(tb.SKILLS_DIR / "personal", "zztest_disabled", enabled=False)

        entries = self.make_builder().get_existing_tools()
        self.assertEqual(len(entries), 4)
        for name in ("zztest_shared", "zztest_automatic", "zztest_personal", "zztest_disabled"):
            self.assertTrue(any(entry.startswith(f"- {name}:") for entry in entries))
        self.assertIn("disabled; name reserved", "\n".join(entries))
        self.assertNotIn("Private description fixture", "\n".join(entries))

    def test_malformed_manifest_does_not_hide_later_personal_names(self):
        (tb.SKILLS_DIR / "aaa-invalid.tool.json").write_text("{broken")
        self.write_manifest(tb.SKILLS_DIR / "personal", "zztest_private")
        self.assertEqual(
            self.make_builder().get_existing_tools(),
            ["- zztest_private: Personal tool; name reserved"],
        )

    def test_create_rejects_existing_names_before_writes_or_verification(self):
        builder = self.make_builder()
        for directory in (tb.SKILLS_DIR, tb.AUTO_TOOLS_DIR, tb.SKILLS_DIR / "personal"):
            for enabled in (True, False):
                with self.subTest(directory=directory.name, enabled=enabled):
                    path = self.write_manifest(
                        directory, "zztest_generated_tool", enabled=enabled,
                        filename="different-filename.tool.json",
                    )
                    original = path.read_bytes()
                    with patch.object(builder, "_verify_tool") as verify:
                        with self.assertRaisesRegex(ValueError, "Tool name already exists"):
                            builder._create_tool(make_spec(), "test", [], [], 0)
                        verify.assert_not_called()
                    self.assertEqual(path.read_bytes(), original)
                    self.assertFalse((tb.AUTO_TOOLS_DIR / "zztest_generated_tool.py").exists())
                    self.assertEqual(list(tb.PENDING_DIR.iterdir()), [])
                    path.unlink()

    def test_create_does_not_overwrite_orphaned_generated_files(self):
        path = tb.AUTO_TOOLS_DIR / "zztest_generated_tool.py"
        path.write_text("# existing work\n")
        with self.assertRaisesRegex(ValueError, "Tool files already exist"):
            self.create(make_spec())
        self.assertEqual(path.read_text(), "# existing work\n")

    def test_private_reservations_are_not_written_to_generated_report(self):
        self.write_manifest(tb.SKILLS_DIR, "zztest_public")
        self.write_manifest(tb.SKILLS_DIR / "personal", "zztest_private")
        builder = self.make_builder()
        result = builder._create_tool(
            make_spec(), "test", [], builder.get_existing_tools(), 0,
        )
        self.assertTrue(result.success)
        report_path = tb.AUTO_TOOLS_DIR / "zztest_generated_tool.report.json"
        report_text = report_path.read_text()
        self.assertNotIn("zztest_private", report_text)
        self.assertNotIn("Private description fixture", report_text)
        self.assertIn("zztest_public", report_text)
        self.assertEqual(Path(result.tool_path).parent, tb.AUTO_TOOLS_DIR)

    def test_report_keeps_deleted_personal_reservation_private(self):
        manifest_path = self.write_manifest(
            tb.SKILLS_DIR / "personal", "zztest_deleted_private", enabled=False,
        )
        builder = self.make_builder()
        prompt_entries = builder.get_existing_tools()
        self.assertTrue(any("zztest_deleted_private" in entry for entry in prompt_entries))
        manifest_path.unlink()

        result = builder._create_tool(make_spec(), "test", [], prompt_entries, 0)

        self.assertTrue(result.success)
        report_path = tb.AUTO_TOOLS_DIR / "zztest_generated_tool.report.json"
        self.assertNotIn("zztest_deleted_private", report_path.read_text())
        self.assertEqual(result.report_card["mcp_alternatives_checked"], [])


class TestPendingApiKeyLifecycle(BuilderDirsMixin):
    def test_missing_key_build_survives_as_pending_api_key(self):
        spec = make_spec(
            requires_new_api_key=True,
            suggested_env_var="ZZTEST_NEW_SERVICE_KEY",
        )
        result = self.create(spec)

        self.assertTrue(result.success)
        self.assertEqual(result.status, "pending_api_key")
        py_path = tb.PENDING_DIR / "zztest_generated_tool.py"
        json_path = tb.PENDING_DIR / "zztest_generated_tool.tool.json"
        self.assertTrue(py_path.exists(), "generated files must survive to review")
        self.assertTrue(json_path.exists())

        manifest = json.loads(json_path.read_text())
        self.assertEqual(
            manifest["availability"]["all_of_env"], ["ZZTEST_NEW_SERVICE_KEY"]
        )
        self.assertIn("setup_hint", manifest["availability"])

    def test_availability_emitted_even_when_key_already_configured(self):
        self.set_env("ZZTEST_EXISTING_KEY", "already-set")
        spec = make_spec(required_env_vars=["ZZTEST_EXISTING_KEY"])
        result = self.create(spec)

        self.assertEqual(result.status, "created")
        manifest = json.loads(
            (tb.AUTO_TOOLS_DIR / "zztest_generated_tool.tool.json").read_text()
        )
        self.assertEqual(
            manifest["availability"]["all_of_env"], ["ZZTEST_EXISTING_KEY"]
        )

    def test_invalid_env_var_names_rejected(self):
        for bad in ("lowercase_key", "1STARTS_WITH_DIGIT", "HAS-DASH", "HAS SPACE"):
            with self.assertRaises(ValueError, msg=bad):
                self.create(make_spec(required_env_vars=[bad]))

    def test_no_requirements_no_availability_block(self):
        result = self.create(make_spec())
        self.assertEqual(result.status, "created")
        manifest = json.loads(
            (tb.AUTO_TOOLS_DIR / "zztest_generated_tool.tool.json").read_text()
        )
        self.assertNotIn("availability", manifest)


class TestStaticVerify(BuilderDirsMixin):
    def test_unresolvable_import_fails(self):
        py_path = tb.PENDING_DIR / "bad_imports.py"
        py_path.write_text("import zztest_module_that_does_not_exist_anywhere\n")
        builder = self.make_builder()
        ok, output = builder._static_verify(py_path)
        self.assertFalse(ok)
        self.assertIn("zztest_module_that_does_not_exist_anywhere", output)

    def test_resolvable_imports_pass(self):
        py_path = tb.PENDING_DIR / "good_imports.py"
        py_path.write_text("import json\nimport os\nfrom pathlib import Path\n")
        builder = self.make_builder()
        ok, output = builder._static_verify(py_path)
        self.assertTrue(ok, output)

    def test_static_verify_never_executes_generated_code(self):
        marker = tb.PENDING_DIR / "executed.marker"
        py_path = tb.PENDING_DIR / "side_effect.py"
        py_path.write_text(
            "import json\n"
            f"open({str(marker)!r}, 'w').write('ran')\n"
        )
        builder = self.make_builder()
        ok, output = builder._static_verify(py_path)
        self.assertTrue(ok, output)
        self.assertFalse(marker.exists(), "static review must not run generated code")

    def test_syntax_error_fails(self):
        py_path = tb.PENDING_DIR / "syntax_error.py"
        py_path.write_text("def broken(:\n")
        builder = self.make_builder()
        ok, output = builder._static_verify(py_path)
        self.assertFalse(ok)
        self.assertIn("Syntax error", output)


class TestApproval(BuilderDirsMixin):
    def _stage_pending(self, env_var: str, mode: str = "cloud"):
        name = "zztest_generated_tool"
        (tb.PENDING_DIR / f"{name}.py").write_text(PASSING_TOOL_CODE)
        (tb.PENDING_DIR / f"{name}.tool.json").write_text(json.dumps({
            "enabled": True,
            "name": name,
            "description": "t",
            "script": f"{name}.py",
            "parameters": {"type": "object", "properties": {}},
            "test_input": {},
            "availability": {"all_of_env": [env_var]},
        }))
        (tb.PENDING_DIR / f"{name}.report.json").write_text(json.dumps({
            "tool_name": name,
            "mode": mode,
            "packages_new": [],
            "requires_api_key": True,
            "suggested_env_var": env_var,
        }))
        return name

    def test_approval_refused_while_key_missing(self):
        name = self._stage_pending("ZZTEST_APPROVAL_KEY")
        ok, message = tb.approve_pending_tool(name)
        self.assertFalse(ok)
        self.assertIn("ZZTEST_APPROVAL_KEY", message)
        # Files must NOT move
        self.assertTrue((tb.PENDING_DIR / f"{name}.py").exists())
        self.assertFalse((tb.AUTO_TOOLS_DIR / f"{name}.py").exists())

    def test_approval_refuses_personal_name_added_since_build(self):
        name = self._stage_pending("ZZTEST_APPROVAL_KEY")
        personal_dir = tb.SKILLS_DIR / "personal"
        personal_dir.mkdir()
        personal_manifest = personal_dir / "different-filename.tool.json"
        personal_manifest.write_text(json.dumps({"name": name, "enabled": False}))
        original = personal_manifest.read_bytes()
        with patch.object(tb.subprocess, "run") as run:
            ok, message = tb.approve_pending_tool(name, install_packages=True)
        self.assertFalse(ok)
        self.assertIn("Tool name already exists", message)
        run.assert_not_called()
        self.assertEqual(personal_manifest.read_bytes(), original)
        self.assertTrue((tb.PENDING_DIR / f"{name}.py").exists())
        self.assertFalse((tb.AUTO_TOOLS_DIR / f"{name}.py").exists())

    def test_approval_succeeds_with_key_and_runs_full_verification(self):
        name = self._stage_pending("ZZTEST_APPROVAL_KEY2")
        # JARVIS_OVERRIDE_* takes precedence over scoped env files, so the
        # test never needs to touch config/cloud.env.
        self.set_env("JARVIS_OVERRIDE_ZZTEST_APPROVAL_KEY2", "configured")
        ok, message = tb.approve_pending_tool(name)
        self.assertTrue(ok, message)
        self.assertTrue((tb.AUTO_TOOLS_DIR / f"{name}.py").exists())
        self.assertFalse((tb.PENDING_DIR / f"{name}.py").exists())

    def test_approval_verification_failure_keeps_files_pending(self):
        name = self._stage_pending("ZZTEST_APPROVAL_KEY3")
        self.set_env("JARVIS_OVERRIDE_ZZTEST_APPROVAL_KEY3", "configured")
        # Break the tool so the live test run fails after the gate passes.
        (tb.PENDING_DIR / f"{name}.py").write_text(
            "import sys\nprint('not json')\nsys.exit(0)\n"
        )
        ok, message = tb.approve_pending_tool(name)
        self.assertFalse(ok)
        self.assertIn("Verification failed", message)
        self.assertTrue((tb.PENDING_DIR / f"{name}.py").exists())

    def test_approval_uses_report_mode(self):
        name = self._stage_pending("ZZTEST_APPROVAL_KEY4", mode="local")
        self.set_env("JARVIS_OVERRIDE_ZZTEST_APPROVAL_KEY4", "configured")
        ok, message = tb.approve_pending_tool(name)
        self.assertTrue(ok, message)
        self.assertIn("local mode", message)

    def test_approve_missing_tool(self):
        ok, message = tb.approve_pending_tool("zztest_nonexistent")
        self.assertFalse(ok)
        self.assertIn("not found", message.lower())

    def test_rejected_approval_never_installs_packages(self):
        """pip install must not run when the availability gate refuses."""
        name = self._stage_pending("ZZTEST_APPROVAL_KEY5")
        report_path = tb.PENDING_DIR / f"{name}.report.json"
        report = json.loads(report_path.read_text())
        report["packages_new"] = ["zztest-fake-package"]
        report_path.write_text(json.dumps(report))

        with patch.object(tb.subprocess, "run") as fake_run:
            ok, message = tb.approve_pending_tool(name, install_packages=True)
        self.assertFalse(ok)
        self.assertIn("ZZTEST_APPROVAL_KEY5", message)
        fake_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
