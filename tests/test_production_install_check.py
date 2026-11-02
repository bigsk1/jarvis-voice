"""Privacy and execution boundaries for the clean production install check."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "bin" / "check-production-environment.py"


@pytest.fixture
def production_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("production_install_check", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def clean_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    env = {
        "PATH": os.defpath,
        "HOME": str(tmp_path),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    subprocess.run(["git", "init", "--quiet", str(root)], env=env, check=True)
    (root / ".gitignore").write_text(
        ".env\nconfig/*.env\nconfig/*.json\nruntime/\n.venv*/\n__pycache__/\n*.pyc\nAGENTS.md\n",
        encoding="utf-8",
    )
    config = root / "config"
    config.mkdir()
    (config / "cloud.env.example").write_text("API_KEY=replace-me\n", encoding="utf-8")
    library = root / "lib"
    library.mkdir()
    (library / "module.py").write_text('"""Synthetic tracked application module."""\n', encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, env=env, check=True)
    return root


def test_clean_checkout_accepts_tracked_configuration_examples(
    production_check: ModuleType, clean_checkout: Path
) -> None:
    production_check.check_checkout(clean_checkout)


@pytest.mark.parametrize("relative", ["config/fake-private-token.json", "AGENTS.md", "config/cloud.env"])
def test_force_tracked_ignored_secret_is_rejected_without_name_or_content(
    production_check: ModuleType,
    clean_checkout: Path,
    capsys: pytest.CaptureFixture[str],
    relative: str,
) -> None:
    secret = clean_checkout / relative
    secret.write_text('{"token":"synthetic-value-must-stay-private"}', encoding="utf-8")
    subprocess.run(["git", "add", "--force", str(secret)], cwd=clean_checkout, check=True)

    with pytest.raises(RuntimeError, match="1 tracked ignored checkout path") as error:
        production_check.check_checkout(clean_checkout)

    captured = capsys.readouterr()
    output = str(error.value) + captured.out + captured.err
    assert secret.name not in output
    assert "synthetic-value-must-stay-private" not in output


def test_explicit_public_workflow_guide_exception_is_allowed(
    production_check: ModuleType, clean_checkout: Path
) -> None:
    guide = clean_checkout / "data" / "workflows" / "AGENTS.md"
    guide.parent.mkdir(parents=True)
    guide.write_text("Public workflow authoring guidance\n", encoding="utf-8")
    subprocess.run(["git", "add", "--force", str(guide)], cwd=clean_checkout, check=True)

    production_check.check_checkout(clean_checkout)


@pytest.mark.parametrize("relative", [".env", "config/oauth-private.json", "runtime/private.txt"])
def test_existing_ignored_runtime_artifacts_are_rejected_without_leaking(
    production_check: ModuleType,
    clean_checkout: Path,
    capsys: pytest.CaptureFixture[str],
    relative: str,
) -> None:
    artifact = clean_checkout / relative
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("synthetic-private-runtime-content", encoding="utf-8")

    with pytest.raises(RuntimeError, match="private/runtime checkout path") as error:
        production_check.check_checkout(clean_checkout)

    captured = capsys.readouterr()
    output = str(error.value) + captured.out + captured.err
    assert relative not in output
    assert "synthetic-private-runtime-content" not in output


def test_selected_environment_and_bytecode_are_allowed_but_other_environment_is_not(
    production_check: ModuleType, clean_checkout: Path
) -> None:
    environment = clean_checkout / ".venv-prod-ci"
    (environment / "bin").mkdir(parents=True)
    (environment / "bin" / "python").write_text("synthetic interpreter", encoding="utf-8")
    cache = clean_checkout / "lib" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "module.cpython-312.pyc").write_bytes(b"synthetic-bytecode")

    production_check.check_checkout(clean_checkout, environment=environment)

    other = clean_checkout / ".venv-private"
    other.mkdir()
    (other / "private-state.txt").write_text("synthetic-state", encoding="utf-8")
    with pytest.raises(RuntimeError, match="private/runtime checkout path"):
        production_check.check_checkout(clean_checkout, environment=environment)


def test_smoke_environment_uses_temporary_home_and_excludes_inherited_credentials(
    production_check: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        os,
        "environ",
        {
            "HOME": "/synthetic/operator/home",
            "PATH": os.defpath,
            "LANG": "C.UTF-8",
            "OPENAI_API_KEY": "fake-provider-secret",
            "ANTHROPIC_API_KEY": "fake-provider-secret",
            "GH_TOKEN": "fake-token",
            "GITHUB_TOKEN": "fake-token",
            "AWS_SECRET_ACCESS_KEY": "fake-secret",
            "JARVIS_MODE": "local",
            "JARVIS_OVERRIDE_LLM_PROVIDER": "fake-private-provider",
            "JARVIS_VENV": "/synthetic/operator/environment",
            "PYTHONPATH": "/synthetic/private/packages",
            "HTTPS_PROXY": "https://user:fake-secret@proxy.invalid",
        },
    )
    environment = production_check.smoke_environment(tmp_path)

    assert environment["HOME"] == str(tmp_path)
    assert environment["JARVIS_MODE"] == "cloud"
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["PATH"] == os.defpath
    assert environment["LANG"] == "C.UTF-8"
    assert not any("fake-" in value for value in environment.values())
    assert not any(key.endswith(("_KEY", "_TOKEN")) for key in environment)
    assert "PYTHONPATH" not in environment
    assert "HTTPS_PROXY" not in environment
    assert "JARVIS_VENV" not in environment
    assert "JARVIS_OVERRIDE_LLM_PROVIDER" not in environment


@pytest.mark.parametrize(
    "operation",
    [
        'socket.getaddrinfo("example.invalid", 443)',
        'socket.socket().connect(("192.0.2.1", 443))',
        'socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"fixture", ("192.0.2.1", 53))',
    ],
)
def test_network_audit_guard_rejects_outbound_operations_in_a_disposable_process(
    production_check: ModuleType, tmp_path: Path, operation: str
) -> None:
    # Never install an irreversible audit hook in the pytest process. Each child
    # must raise our specific guard error before resolver or socket activity.
    code = "\n".join(
        [
            "import importlib.util, socket, sys",
            "spec = importlib.util.spec_from_file_location('smoke_check', sys.argv[1])",
            "module = importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(module)",
            "sys.addaudithook(module.block_network)",
            "try:",
            f"    {operation}",
            "except RuntimeError as error:",
            "    assert str(error) == 'Network access is disabled during the production smoke check.'",
            "else:",
            "    raise AssertionError('Outbound operation was not blocked')",
        ]
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(HELPER)],
        cwd=tmp_path,
        env=production_check.smoke_environment(tmp_path),
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr


def test_workflow_runs_clean_locked_production_checks_with_minimal_github_permissions() -> None:
    path = ROOT / ".github" / "workflows" / "production-install.yml"
    # GitHub uses YAML 1.2 semantics for `on`; BaseLoader preserves it as a key.
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    events = workflow["on"]
    assert set(events) == {"push", "pull_request", "workflow_dispatch"}
    assert events["push"]["branches"] == ["main"]
    assert events["pull_request"]["branches"] == ["main"]
    assert workflow["permissions"] == {"contents": "read"}

    job = workflow["jobs"]["production-install"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["env"]["UV_PROJECT_ENVIRONMENT"] == "${{ github.workspace }}/.venv-prod-ci"
    assert job["env"]["UV_PYTHON"] == "3.12"
    assert job["env"]["UV_NO_CACHE"] == "1"
    actions = [step for step in job["steps"] if "uses" in step]
    assert len(actions) == 2
    assert all(re.fullmatch(r"[\w/-]+@[0-9a-f]{40}", step["uses"]) for step in actions)
    checkout = next(step for step in actions if step["uses"].startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] == "false"
    uv = next(step for step in actions if step["uses"].startswith("astral-sh/setup-uv@"))
    assert uv["with"]["enable-cache"] == "false"

    commands = [step["run"] for step in job["steps"] if "run" in step]
    privacy = next(i for i, command in enumerate(commands) if "--check-checkout" in command)
    sync = next(i for i, command in enumerate(commands) if command.startswith("uv sync "))
    assert privacy < sync
    assert {"--locked", "--no-dev", "--no-install-project"} <= set(commands[sync].split())
    assert any("uv pip check --python .venv-prod-ci/bin/python" in command for command in commands)
    assert any(
        ".venv-prod-ci/bin/python -I bin/check-production-environment.py" in command
        for command in commands
    )
    content = path.read_text(encoding="utf-8").lower()
    assert "secrets." not in content
    assert "pull_request_target" not in content
    assert "upload-artifact" not in content
    assert "actions/cache" not in content
