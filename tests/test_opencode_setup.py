"""Temporary-home coverage for OpenCode V2 installation and workspace controls."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def setup_module(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("opencode_setup_under_test", ROOT / "bin/opencode-setup.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checkout = tmp_path / "checkout"
    home = tmp_path / "user"
    for directory in ("config", "systemd", "docs/opencode/plugin"):
        (checkout / directory).mkdir(parents=True, exist_ok=True)
    for relative in ("config/opencode.config.json.template", "systemd/opencode-jarvis.service", "config/opencode.instructions.md.template",
                     "docs/opencode/plugin/00-workspace-protection.js"):
        shutil.copy2(ROOT / relative, checkout / relative)
    monkeypatch.setattr(module, "ROOT", checkout)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    for key in ("OPENCODE_ENV_FILE", "JARVIS_MODE", "JARVIS_SERVICE_HOME", "JARVIS_SERVICE_USER", "JARVIS_SERVICE_GROUP"):
        monkeypatch.delenv(key, raising=False)
    return module, checkout, home


def test_env_preserves_optional_keys_and_literal_secrets_without_execution(setup_module):
    module, checkout, home = setup_module
    source = checkout / "config/cloud.env"
    source.write_text('OPENAI_API_KEY=\'new$literal"key\\value\'\nOPENCODE_SERVER_PASSWORD=\'$(touch /tmp/never-opencode)\'\n')
    target = home / ".config/opencode/jarvis-env.env"
    module.atomic_write(target, 'OPTIONAL_LOCAL_SETTING="keep"\nXAI_API_KEY="old-xai"\n')
    module.prepare_env(source)
    values = module.read_env(target, systemd=True)
    assert values["OPENAI_API_KEY"] == 'new$literal"key\\value'
    assert values["XAI_API_KEY"] == "old-xai"
    assert values["OPTIONAL_LOCAL_SETTING"] == "keep"
    assert values["OPENCODE_SERVER_PASSWORD"] == "$(touch /tmp/never-opencode)"
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.with_suffix(".env.v1-backup").stat().st_mode & 0o777 == 0o600
    module.prepare_env(source)
    assert module.read_env(target, systemd=True) == values


def test_selected_env_uses_local_mode_without_cloud_file(setup_module, monkeypatch):
    module, checkout, _ = setup_module
    local = checkout / "config/local.env"
    local.write_text("OPENCODE_PROVIDER=ollama\nOPENCODE_MODEL=local-coder\nOLLAMA_MODEL=local-coder\nOLLAMA_BASE_URL=http://127.0.0.2:11434,http://localhost:11434\n")
    monkeypatch.setenv("JARVIS_MODE", "local")
    assert module.selected_env(None) == local
    module.prepare_config(local)
    config = json.loads((module.config_dir() / "opencode.json").read_text())
    assert config["model"] == "ollama/local-coder"
    assert config["providers"]["ollama"]["settings"]["baseURL"] == "http://127.0.0.2:11434/v1"
    assert config["agents"]["title"]["model"] == "ollama/local-coder"


def test_existing_model_configuration_remains_byte_identical(setup_module):
    module, checkout, _ = setup_module
    source = checkout / "config/local.env"
    source.write_text("OPENCODE_MODEL=different\n")
    target = module.config_dir() / "opencode.json"
    original = '{ "model": "xai/selected", "provider": {"custom": {"models": {"user-model": {}}}}}\n'
    module.atomic_write(target, original)
    module.prepare_config(source)
    assert target.read_text() == original


def legacy_jarvis_profile(module, effect="ask"):
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": "xai/operator-selected",
        "small_model": "ollama/operator-title-model",
        "provider": {
            "ollama": {"npm": "@ai-sdk/openai-compatible", "name": "Ollama (local)",
                       "options": {"baseURL": "http://localhost:11434/v1"},
                       "models": {"operator-local": {"name": "Operator local model"}}},
            "openai": {"npm": "@ai-sdk/openai", "name": "OpenAI",
                       "options": {"apiKey": "{env:OPENAI_API_KEY}"},
                       "models": {"operator-openai": {"name": "Operator OpenAI model"}}},
            "anthropic": {"npm": "@ai-sdk/anthropic", "name": "Anthropic",
                          "options": {"apiKey": "{env:ANTHROPIC_API_KEY}"},
                          "models": {"operator-anthropic": {"name": "Operator Anthropic model"}}},
        },
        "disabled_providers": module.LEGACY_DISABLED_PROVIDERS,
        "autoupdate": True,
        "permission": {"edit": effect, "bash": effect},
    }


@pytest.mark.parametrize("include_schema", [True, False], ids=["emitted-schema", "schema-omitted"])
def test_actual_legacy_installer_output_migrates_through_prepare(setup_module, monkeypatch, include_schema):
    module, checkout, _ = setup_module
    # Literal output of bin/setup-opencode-config.sh at commit 2bb9da3480f4f3e3a8351de166156a3f5eb12111,
    # run with an isolated destination and no local.env. Do not rebuild this
    # fixture from generated_legacy_profile or the richer operator profile above.
    original = (ROOT / "tests/fixtures/opencode/legacy-installer.json").read_text()
    config = json.loads(original)
    assert set(config) == {"$schema", "provider", "disabled_providers", "autoupdate", "permission"}
    if not include_schema:
        del config["$schema"]
        original = json.dumps(config, indent=2) + "\n"
    target = module.config_dir() / "opencode.json"
    module.atomic_write(target, original)
    source = checkout / "config/cloud.env"
    source.write_text("OPENCODE_PROVIDER=xai\nOPENCODE_MODEL=must-not-add\nOPENCODE_SERVER_PASSWORD=fixture-password\n")
    monkeypatch.setattr(module.sys, "argv", ["opencode-setup.py", "prepare", str(source)])
    module.main()
    migrated = target.read_text()
    updated = json.loads(migrated)
    expected = {key: value for key, value in config.items() if key not in {"permission", "autoupdate"}}
    expected.update({
        "update": "notify",
        "permissions": [{"action": action, "resource": "*", "effect": "allow"}
                        for action in ("edit", "shell", "external_directory")],
    })
    assert updated == expected
    backup = target.with_suffix(".json.v1-backup")
    assert backup.read_text() == original
    assert backup.stat().st_mode & 0o777 == 0o600
    assert (module.config_dir() / "jarvis-env.env").is_file()
    assert (module.config_dir() / "plugins/00-workspace-protection.js").is_file()
    module.main()
    assert target.read_text() == migrated
    assert backup.read_text() == original
    assert list(target.parent.glob("opencode.json.v1-backup*")) == [backup]


@pytest.mark.parametrize("schema", [None, "https://example.invalid/custom-opencode-schema.json"])
def test_explicit_unrecognized_schema_remains_custom_policy(setup_module, monkeypatch, schema):
    module, checkout, _ = setup_module
    config = json.loads((ROOT / "tests/fixtures/opencode/legacy-installer.json").read_text())
    config["$schema"] = schema
    target = module.config_dir() / "opencode.json"
    original = json.dumps(config)
    module.atomic_write(target, original)
    source = checkout / "config/cloud.env"
    source.write_text("OPENCODE_SERVER_PASSWORD=fixture-password\n")
    monkeypatch.setattr(module.sys, "argv", ["opencode-setup.py", "prepare", str(source)])
    with pytest.raises(ValueError, match="Customized edit/shell approval rules"):
        module.main()
    assert target.read_text() == original
    assert not target.with_suffix(".json.v1-backup").exists()
    assert not (module.config_dir() / "jarvis-env.env").exists()
    assert not (module.config_dir() / "plugins").exists()


@pytest.mark.parametrize("effect", ["ask", "allow"])
def test_generated_legacy_profile_migrates_permissions_updates_preserving_models(setup_module, effect, capsys):
    module, checkout, _ = setup_module
    config = legacy_jarvis_profile(module, effect)
    target = module.config_dir() / "opencode.json"
    original = json.dumps(config, indent=4) + "\n"
    module.atomic_write(target, original)
    module.prepare_config(checkout / "unused.env")
    updated = json.loads(target.read_text())
    for key in ("model", "small_model", "provider", "disabled_providers"):
        assert updated[key] == config[key]
    assert "permission" not in updated and "autoupdate" not in updated
    assert updated["update"] == "notify"
    assert updated["permissions"] == [
        {"action": action, "resource": "*", "effect": "allow"}
        for action in ("edit", "shell", "external_directory")
    ]
    assert target.with_suffix(".json.v1-backup").read_text() == original
    assert "native unattended build permissions" in capsys.readouterr().out
    first = target.read_text()
    module.prepare_config(checkout / "unused.env")
    assert target.read_text() == first
    assert target.with_suffix(".json.v1-backup").read_text() == original


def test_custom_narrow_rules_are_preserved_without_weakening(setup_module):
    module, checkout, _ = setup_module
    config = {
        "model": "xai/custom", "update": "notify",
        "permissions": [
            {"action": "edit", "resource": "*", "effect": "allow"},
            {"action": "shell", "resource": "*", "effect": "allow"},
            {"action": "shell", "resource": "git push *", "effect": "ask"},
            {"action": "edit", "resource": "important.txt", "effect": "deny"},
            {"action": "external_directory", "resource": "*", "effect": "deny"},
        ],
    }
    target = module.config_dir() / "opencode.json"
    original = json.dumps(config, indent=4)
    module.atomic_write(target, original)
    module.prepare_config(checkout / "unused.env")
    assert target.read_text() == original


@pytest.mark.parametrize("custom", [
    {"permission": {"edit": "ask", "bash": "ask"}},
    {"permissions": [{"action": "shell", "resource": "*", "effect": "deny"}]},
    {"autoupdate": True},
    {"update": "auto"},
    {"policies": [{"action": "tool.use", "resource": "shell:*", "effect": "deny"}]},
    {"agents": {"build": {"permissions": [{"action": "edit", "resource": "*", "effect": "ask"}]}}},
    {"default_agent": "reviewer", "agents": {"build": {"permissions": [{"action": "shell", "resource": "*", "effect": "ask"}]}}},
])
def test_custom_broad_policy_requires_review_before_any_prepare_mutations(setup_module, monkeypatch, custom):
    module, checkout, _ = setup_module
    target = module.config_dir() / "opencode.json"
    original = json.dumps(custom)
    module.atomic_write(target, original)
    source = checkout / "config/cloud.env"
    source.write_text("OPENCODE_SERVER_PASSWORD=fixture-password\n")
    monkeypatch.setattr(module.sys, "argv", ["opencode-setup.py", "prepare", str(source)])
    with pytest.raises(ValueError, match="review"):
        module.main()
    assert target.read_text() == original
    assert not target.with_suffix(".json.v1-backup").exists()
    assert not (module.config_dir() / "jarvis-env.env").exists()
    assert not (module.config_dir() / "plugins").exists()


def test_both_config_files_are_preflighted_before_known_profile_changes(setup_module, monkeypatch):
    module, checkout, _ = setup_module
    target = module.config_dir() / "opencode.json"
    original = json.dumps(legacy_jarvis_profile(module))
    module.atomic_write(target, original)
    jsonc = module.config_dir() / "opencode.jsonc"
    commented = '{\n  // User notes must not disappear.\n  "model": "xai/custom"\n}\n'
    module.atomic_write(jsonc, commented)
    source = checkout / "config/cloud.env"
    source.write_text("OPENCODE_SERVER_PASSWORD=fixture-password\n")
    monkeypatch.setattr(module.sys, "argv", ["opencode-setup.py", "prepare", str(source)])
    with pytest.raises(ValueError, match="OpenCode V2 supports JSONC"):
        module.main()
    assert target.read_text() == original
    assert jsonc.read_text() == commented
    assert not (module.config_dir() / "jarvis-env.env").exists()


def test_plain_json_in_jsonc_filename_is_migrated(setup_module):
    module, checkout, _ = setup_module
    target = module.config_dir() / "opencode.jsonc"
    module.atomic_write(target, json.dumps(legacy_jarvis_profile(module)))
    module.prepare_config(checkout / "unused.env")
    assert json.loads(target.read_text())["update"] == "notify"
    assert not target.with_suffix(".json").exists()


def test_migration_backups_capture_current_bytes_without_replacing_older_backup(setup_module):
    module, checkout, _ = setup_module
    target = module.config_dir() / "opencode.json"
    old_backup = target.with_suffix(".json.v1-backup")
    module.atomic_write(old_backup, "previous backup")
    current = json.dumps(legacy_jarvis_profile(module), indent=4)
    module.atomic_write(target, current)
    module.prepare_config(checkout / "unused.env")
    assert old_backup.read_text() == "previous backup"
    backups = list(target.parent.glob("opencode.json.v1-backup.*"))
    assert len(backups) == 1 and backups[0].read_text() == current
    assert backups[0].stat().st_mode & 0o777 == 0o600


def test_managed_cache_overrides_removed_but_optional_env_retained(setup_module, capsys):
    module, checkout, _ = setup_module
    target = module.config_dir() / "jarvis-env.env"
    module.atomic_write(target, "OPTIONAL_SETTING=keep\n" + "".join(
        f"{key}=stale-sensitive-value\n" for key in module.UNIT_MANAGED_ENV
    ))
    source = checkout / "config/cloud.env"
    source.write_text("OPENCODE_SERVER_PASSWORD=fixture-password\nXDG_CACHE_HOME=ignored-source-override\n")
    module.prepare_env(source)
    values = module.read_env(target, systemd=True)
    assert not values.keys() & module.UNIT_MANAGED_ENV
    assert values["OPTIONAL_SETTING"] == "keep"
    output = capsys.readouterr().out
    assert "XDG_CACHE_HOME" in output and "stale-sensitive-value" not in output


def test_explicit_legacy_plugin_reference_is_removed_preserving_other_settings(setup_module):
    module, _, _ = setup_module
    target = module.config_dir() / "opencode.json"
    config = {"model": "xai/operator-model", "plugin": ["./plugin/00-workspace-protection.js", "other-plugin"]}
    module.atomic_write(target, json.dumps(config))
    module.prepare_plugin()
    updated = json.loads(target.read_text())
    assert updated["model"] == "xai/operator-model"
    assert updated["plugin"] == ["other-plugin"]
    assert json.loads(target.with_suffix(".json.v1-backup").read_text()) == config


@pytest.mark.parametrize("setting", ["OPENCODE_SERVER_USERNAME=custom\nOPENCODE_SERVER_PASSWORD=fixture\n", ""])
def test_prepare_refuses_incompatible_auth_without_replacing_env(setup_module, setting):
    module, checkout, _ = setup_module
    source = checkout / "config/cloud.env"
    source.write_text(setting)
    with pytest.raises(ValueError, match="OPENCODE_SERVER_"):
        module.prepare_env(source)
    assert not (module.config_dir() / "jarvis-env.env").exists()


def test_prepare_plugin_keeps_backup_and_removes_only_legacy_guard(setup_module):
    module, _, _ = setup_module
    legacy = module.config_dir() / "plugin/00-workspace-protection.js"
    module.atomic_write(legacy, "old V1 guard")
    other = legacy.with_name("other-plugin.js")
    module.atomic_write(other, "unrelated plugin")
    module.prepare_plugin()
    assert not legacy.exists()
    assert legacy.with_suffix(".js.v1-backup").read_text() == "old V1 guard"
    assert other.read_text() == "unrelated plugin"
    assert (module.config_dir() / "plugins" / legacy.name).is_file()
    module.prepare_plugin()
    assert legacy.with_suffix(".js.v1-backup").read_text() == "old V1 guard"


def test_prepare_instructions_only_seeds_missing_file(setup_module):
    module, _, _ = setup_module
    target = module.config_dir() / "AGENTS.md"
    module.prepare_instructions()
    assert target.is_file()
    target.write_text("Operator-specific instructions\n")
    module.prepare_instructions()
    assert target.read_text() == "Operator-specific instructions\n"


def test_fresh_prepare_uses_only_copied_public_assets(setup_module, monkeypatch):
    module, checkout, _ = setup_module
    source = checkout / "config/cloud.env"
    source.write_text("OPENCODE_PROVIDER=xai\nOPENCODE_MODEL=selected-model\nOPENCODE_SERVER_PASSWORD=fixture-password\n")
    # The temporary checkout deliberately has no ignored AGENTS.md files.
    monkeypatch.setattr(module.sys, "argv", ["opencode-setup.py", "prepare", str(source)])
    module.main()
    assert (module.config_dir() / "AGENTS.md").read_text() == (checkout / "config/opencode.instructions.md.template").read_text()
    assert (module.config_dir() / "plugins/00-workspace-protection.js").is_file()
    assert (module.workspace() / "projects").is_dir()
    config = json.loads((module.config_dir() / "opencode.json").read_text())
    assert config["model"] == "xai/selected-model"


def test_render_unit_hardens_shell_and_code_mode_and_honors_workspace(setup_module):
    module, checkout, home = setup_module
    source = checkout / "config/cloud.env"
    custom = home / "custom work area"
    source.write_text(f"JARVIS_WORKSPACE_ROOT='{custom}'\nOPENCODE_SERVER_PASSWORD=fixture-password\n")
    module.prepare_env(source)
    module.prepare_directories()
    output = checkout / "opencode.service"
    module.render_unit(output)
    content = output.read_text()
    assert f'WorkingDirectory={custom}' in content
    assert f'ReadWritePaths="{custom}"' in content
    assert f'ReadOnlyPaths="{checkout}"' in content
    assert "ProtectSystem=strict" in content
    assert "ProtectHome=read-only" in content
    assert "PrivateTmp=true" in content
    assert "NoNewPrivileges=true" in content
    assert "__JARVIS_" not in content
    assert (custom / "temp").is_dir()
    assert (custom / ".cache").is_dir()
    assert (custom / ".toolchains/cargo").is_dir()
    assert (custom / ".toolchains/go").is_dir()


def test_reject_workspace_overlapping_protected_checkout(setup_module):
    module, checkout, _ = setup_module
    module.atomic_write(module.config_dir() / "jarvis-env.env", f'JARVIS_WORKSPACE_ROOT="{checkout}"\n')
    with pytest.raises(ValueError, match="separate"):
        module.render_unit(checkout / "never-created.service")


def test_service_update_rejects_v1_before_any_mutation(tmp_path):
    fake = tmp_path / "opencode-v1"
    fake.write_text("#!/bin/sh\nprintf '1.19.3\\n'\n")
    fake.chmod(0o755)
    env = os.environ.copy()
    env["OPENCODE_BINARY"] = str(fake)
    result = subprocess.run([str(ROOT / "bin/update-opencode-service.sh"), str(tmp_path / "missing.env")],
                            env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "OpenCode 2 is required" in result.stderr
    assert "Source env file not found" not in result.stderr


@pytest.mark.parametrize("output", ["opencode v2.1.0\n", "2.1.0\n", "opencode 2.1.0\n"])
def test_binary_version_accepts_actual_v2_banner(setup_module, monkeypatch, output):
    module, _, _ = setup_module
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 0, stdout=output, stderr=""))
    assert module.check_binary() == "2.1.0"


@pytest.mark.parametrize("running_version,plugin_status,success", [("2.1.0", "active", True),
                                                                  ("2.0.0", "active", False),
                                                                  ("2.1.0", "failed", False)])
def test_health_checks_authenticated_running_version_and_guard(setup_module, monkeypatch,
                                                              running_version, plugin_status, success):
    module, _, _ = setup_module
    module.atomic_write(module.config_dir() / "jarvis-env.env", 'OPENCODE_SERVER_PASSWORD="private-fixture"\n')
    monkeypatch.setattr(module, "check_binary", lambda: "2.1.0")
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    def response(request, timeout):
        assert request.get_header("Authorization") == "Basic b3BlbmNvZGU6cHJpdmF0ZS1maXh0dXJl"
        assert timeout == 3
        if request.full_url.endswith("/api/info"):
            return io.StringIO(json.dumps({"version": running_version}))
        query = module.urllib.parse.parse_qs(module.urllib.parse.urlparse(request.full_url).query)
        assert query == {"location[directory]": [str(module.workspace())]}
        return io.StringIO(json.dumps({"data": [{"id": "jarvis.workspace-protection",
                                                 "state": {"status": plugin_status}}]}))

    monkeypatch.setattr(module.urllib.request, "urlopen", response)
    if success:
        module.verify_health()
    else:
        with pytest.raises(ValueError, match="verification failed"):
            module.verify_health()


def test_workspace_plugin_rejects_escapes_and_allows_source_reads(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node is unavailable")
    # .mjs avoids relying on the enclosing repository's Node module mode.
    plugin = tmp_path / "workspace.mjs"
    shutil.copy2(ROOT / "docs/opencode/plugin/00-workspace-protection.js", plugin)
    test_script = ROOT / "tests/node/opencode_workspace_guard.mjs"
    result = subprocess.run(["node", str(test_script), str(plugin), str(tmp_path)],
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr + result.stdout
