"""Cron cleanup uses production Python without touching an operator checkout."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPERS = (
    "cleanup-logs",
    "cleanup-audio",
    "cleanup-generated-images",
    "cleanup-web-conversations",
    "cleanup-retention",
)


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o755)


def _checkout(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    checkout = tmp_path / "checkout with spaces"
    (checkout / "bin").mkdir(parents=True)
    shutil.copy2(ROOT / "bin" / "cleanup-all", checkout / "bin")
    log = tmp_path / "calls.jsonl"
    for name in HELPERS:
        shebang = (
            sys.executable if name in {"cleanup-logs", "cleanup-audio"} else "/usr/bin/env python3"
        )
        _write_executable(
            checkout / "bin" / name,
            f"#!{shebang}\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "record = {'helper': Path(sys.argv[0]).name, 'args': sys.argv[1:], "
            "'python': os.environ.get('TEST_CLEANUP_PYTHON'), "
            "'mode': os.environ.get('JARVIS_MODE')}\n"
            "with open(os.environ['TEST_CLEANUP_LOG'], 'a') as stream:\n"
            "    stream.write(json.dumps(record) + '\\n')\n"
            "sys.exit(31 if record['helper'] == os.environ.get('TEST_FAIL_HELPER') else 0)\n",
        )
    fake_bin = tmp_path / "cron-bin"
    _write_executable(fake_bin / "python3", "#!/bin/sh\nexit 73\n")
    env = {
        "HOME": str(tmp_path / "home"),
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "TEST_CLEANUP_LOG": str(log),
        "TEST_CLEANUP_ALERT_LOG": str(tmp_path / "alerts.jsonl"),
    }
    _write_executable(
        checkout / "skills" / "create_alert.py",
        f"#!{sys.executable}\n"
        "import json, os, sys, time\n"
        "record = {'payload': json.loads(sys.argv[1]), "
        "'mode': os.environ.get('JARVIS_MODE'), "
        "'python': os.environ.get('TEST_CLEANUP_PYTHON')}\n"
        "with open(os.environ['TEST_CLEANUP_ALERT_LOG'], 'a') as stream:\n"
        "    stream.write(json.dumps(record) + '\\n')\n"
        "behavior = os.environ.get('TEST_ALERT_BEHAVIOR')\n"
        "if behavior == 'timeout':\n"
        "    time.sleep(60)\n"
        "if behavior == 'invalid_json':\n"
        "    print('invalid JSON')\n"
        "else:\n"
        "    print(json.dumps({'ok': behavior not in {'error', 'logical_failure'}}))\n"
        "sys.exit(1 if behavior == 'error' else 0)\n",
    )
    return checkout, env, log


def _production_python(venv: Path) -> Path:
    interpreter = venv / "bin" / "python"
    _write_executable(
        interpreter,
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "os.environ['TEST_CLEANUP_PYTHON'] = sys.argv[0]\n"
        f"os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])\n",
    )
    return interpreter


def _run(checkout: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(checkout / "bin" / "cleanup-all"), *args],
        cwd=checkout.parent,
        env=env,
        text=True,
        capture_output=True,
        timeout=25,
    )


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("deployment", ["default", "configured", "docker"])
def test_cleanup_selects_production_python_and_preserves_arguments(tmp_path, deployment, dry_run):
    checkout, env, log = _checkout(tmp_path)
    venv = Path(env["HOME"]) / "jarvis-venv"
    if deployment != "default":
        venv = tmp_path / ("opt-venv" if deployment == "docker" else "custom venv")
        env["JARVIS_VENV"] = str(venv)
        env["JARVIS_MODE"] = "cloud" if deployment == "docker" else "local"
    interpreter = _production_python(venv)
    args = ["--dry-run"] if dry_run else []

    result = _run(checkout, env, *args)

    assert result.returncode == 0, result.stdout + result.stderr
    records = [json.loads(line) for line in log.read_text().splitlines()]
    expected = [
        ("cleanup-logs", ["--days", "60"]),
        ("cleanup-audio", ["--days", "30", "--generated-days", "60"]),
        ("cleanup-generated-images", ["--days", "120"]),
        ("cleanup-web-conversations", ["--days", "90"]),
        ("cleanup-retention", ["uploads", "--days", "60"]),
        ("cleanup-retention", ["stash"]),
    ]
    assert [(record["helper"], record["args"]) for record in records] == [
        (helper, [*arguments, *args]) for helper, arguments in expected
    ]
    for record in records:
        is_python_helper = record["helper"] not in {"cleanup-logs", "cleanup-audio"}
        assert record["python"] == (str(interpreter) if is_python_helper else None)
        assert record["mode"] == env.get("JARVIS_MODE")
    assert "Cleanup complete!" in result.stdout
    assert not Path(env["TEST_CLEANUP_ALERT_LOG"]).exists()


@pytest.mark.parametrize("configured", [False, True])
def test_cleanup_missing_environment_fails_before_any_stage(tmp_path, configured):
    checkout, env, log = _checkout(tmp_path)
    if configured:
        _production_python(Path(env["HOME"]) / "jarvis-venv")
        env["JARVIS_VENV"] = str(tmp_path / "missing venv")

    result = _run(checkout, env)

    assert result.returncode == 2
    assert "production environment" in result.stderr
    assert "JARVIS_VENV" in result.stderr
    assert not log.exists()
    if configured:
        records = _alerts(env)
        assert len(records) == 1
        assert records[0]["python"] == str(Path(env["HOME"]) / "jarvis-venv/bin/python")
        assert records[0]["payload"]["metadata"]["failed_stage"] == "Python environment preflight"
        assert records[0]["payload"]["metadata"]["exit_code"] == 2
    else:
        assert not Path(env["TEST_CLEANUP_ALERT_LOG"]).exists()
        assert "alert unavailable" in result.stderr


def test_cleanup_helper_failure_still_stops_later_stages(tmp_path):
    checkout, env, log = _checkout(tmp_path)
    _production_python(Path(env["HOME"]) / "jarvis-venv")
    env["TEST_FAIL_HELPER"] = "cleanup-web-conversations"

    result = _run(checkout, env, "--dry-run")

    assert result.returncode == 31
    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert [record["helper"] for record in records] == list(HELPERS[:4])
    assert "Cleanup complete!" not in result.stdout
    assert not Path(env["TEST_CLEANUP_ALERT_LOG"]).exists()
    assert "Dry run: no failure alert was created" in result.stderr


def _alerts(env: dict[str, str]) -> list[dict]:
    return [
        json.loads(line) for line in Path(env["TEST_CLEANUP_ALERT_LOG"]).read_text().splitlines()
    ]


@pytest.mark.parametrize(
    ("helper", "stage"),
    [
        ("cleanup-logs", "Logs"),
        ("cleanup-web-conversations", "Web conversations"),
        ("cleanup-retention", "Web uploads"),
    ],
)
def test_cleanup_failure_creates_one_local_alert_and_keeps_failure(tmp_path, helper, stage):
    checkout, env, _ = _checkout(tmp_path)
    default_python = _production_python(Path(env["HOME"]) / "jarvis-venv")
    selected_python = _production_python(tmp_path / "selected venv")
    env.update(
        {
            "JARVIS_VENV": str(selected_python.parent.parent),
            "JARVIS_MODE": "local",
            "TEST_FAIL_HELPER": helper,
        }
    )

    result = _run(checkout, env)

    assert result.returncode == 31
    records = _alerts(env)
    assert len(records) == 1
    assert records[0]["python"] == str(selected_python)
    assert records[0]["python"] != str(default_python)
    assert records[0]["mode"] == "local"
    payload = records[0]["payload"]
    assert payload["source"] == "cleanup_all"
    assert payload["severity"] == "high"
    assert payload["speak_immediately"] is False
    assert payload["metadata"] == {
        "dedupe_key": f"cleanup-all:{stage}",
        "failed_stage": stage,
        "exit_code": 31,
        "log_file": "logs/cleanup.log",
    }
    assert stage in payload["description"]
    assert "31" in payload["description"]
    assert "Cleanup failure alert recorded" in result.stderr
    assert "Cleanup complete!" not in result.stdout


@pytest.mark.parametrize("behavior", ["error", "logical_failure", "invalid_json", "missing_tool"])
def test_cleanup_alert_delivery_failure_preserves_original_exit(tmp_path, behavior):
    checkout, env, _ = _checkout(tmp_path)
    _production_python(Path(env["HOME"]) / "jarvis-venv")
    env.update({"TEST_FAIL_HELPER": "cleanup-web-conversations", "TEST_ALERT_BEHAVIOR": behavior})
    if behavior == "missing_tool":
        (checkout / "skills/create_alert.py").unlink()

    result = _run(checkout, env)

    assert result.returncode == 31
    assert "Unable to deliver the cleanup failure alert" in result.stderr
    assert "keeping original exit 31" in result.stderr
    if behavior == "missing_tool":
        assert not Path(env["TEST_CLEANUP_ALERT_LOG"]).exists()
    else:
        assert len(_alerts(env)) == 1


def test_cleanup_alert_deadline_stops_delivery_and_preserves_failure(tmp_path):
    checkout, env, _ = _checkout(tmp_path)
    _production_python(Path(env["HOME"]) / "jarvis-venv")
    env.update({"TEST_FAIL_HELPER": "cleanup-web-conversations", "TEST_ALERT_BEHAVIOR": "timeout"})

    result = _run(checkout, env)

    assert result.returncode == 31
    assert "timed out after 15 seconds" in result.stderr
    assert "keeping original exit 31" in result.stderr
    assert len(_alerts(env)) == 1
