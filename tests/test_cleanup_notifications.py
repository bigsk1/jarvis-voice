"""Cleanup notices use isolated copied scripts and never send live notifications."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest
from test_cleanup_all_environment import (
    HELPERS,
    ROOT,
    _alerts,
    _checkout,
    _production_python,
    _run,
    _write_executable,
)


def _notification_checkout(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    checkout, env, _ = _checkout(tmp_path)
    log = tmp_path / "notifications.jsonl"
    env["TEST_CLEANUP_NOTIFICATION_LOG"] = str(log)
    _write_executable(
        checkout / "skills/create_notification.py",
        f"#!{sys.executable}\n"
        "import json, os, sys, time\n"
        "record = {'payload': json.loads(sys.argv[1]), "
        "'python': os.environ.get('TEST_CLEANUP_PYTHON'), "
        "'mode': os.environ.get('JARVIS_MODE')}\n"
        "with open(os.environ['TEST_CLEANUP_NOTIFICATION_LOG'], 'a') as stream:\n"
        "    stream.write(json.dumps(record) + '\\n')\n"
        "behavior = os.environ.get('TEST_NOTIFICATION_BEHAVIOR')\n"
        "if behavior == 'timeout':\n"
        "    time.sleep(60)\n"
        "if behavior == 'invalid_json':\n"
        "    print('private child output')\n"
        "elif behavior == 'wrong_shape':\n"
        "    print('[]')\n"
        "else:\n"
        "    print(json.dumps({'ok': behavior not in {'error', 'logical_failure'}, "
        "'speech': 'Saved.', 'data': {'delivery_status': 'queued'}}))\n"
        "print('private child diagnostic', file=sys.stderr)\n"
        "sys.exit(7 if behavior == 'error' else 0)\n",
    )
    return checkout, env, log


def _notices(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


@pytest.mark.parametrize("configured", [False, True])
def test_cleanup_success_records_quiet_notice_with_production_interpreter(tmp_path, configured):
    checkout, env, log = _notification_checkout(tmp_path)
    venv = Path(env["HOME"]) / "jarvis-venv"
    if configured:
        venv = tmp_path / "selected venv"
        env.update(JARVIS_VENV=str(venv), JARVIS_MODE="local")
    interpreter = _production_python(venv)

    result = _run(checkout, env)

    assert result.returncode == 0, result.stderr
    notices = _notices(log)
    assert len(notices) == 1
    assert notices[0]["python"] == str(interpreter)
    assert notices[0]["mode"] == env.get("JARVIS_MODE")
    payload = notices[0]["payload"]
    assert set(payload) == {
        "title", "message", "source", "channels", "dedupe_key", "max_age_seconds"
    }
    assert payload["title"] == "Jarvis cleanup completed"
    assert "successfully" in payload["message"]
    assert "logs/cleanup.log" in payload["message"]
    assert payload["source"] == "cleanup_all"
    assert payload["channels"] == ["ntfy"]
    assert payload["max_age_seconds"] == 3600
    assert payload["dedupe_key"].startswith("cleanup-all:success:")
    assert "Cleanup success notification recorded" in result.stdout
    assert "private child" not in result.stdout + result.stderr
    assert not Path(env["TEST_CLEANUP_ALERT_LOG"]).exists()


def test_separate_successful_runs_have_separate_occurrence_keys(tmp_path):
    checkout, env, log = _notification_checkout(tmp_path)
    _production_python(Path(env["HOME"]) / "jarvis-venv")

    assert _run(checkout, env).returncode == 0
    assert _run(checkout, env).returncode == 0

    keys = [notice["payload"]["dedupe_key"] for notice in _notices(log)]
    assert len(keys) == len(set(keys)) == 2


@pytest.mark.parametrize(
    "args",
    [
        ("--dry-run",), ("--no-notify",),
        ("--dry-run", "--no-notify"), ("--no-notify", "--dry-run"),
    ],
)
def test_cleanup_opt_out_and_dry_run_do_not_record_notices(tmp_path, args):
    checkout, env, log = _notification_checkout(tmp_path)
    _production_python(Path(env["HOME"]) / "jarvis-venv")

    result = _run(checkout, env, *args)

    assert result.returncode == 0, result.stderr
    assert "Cleanup complete!" in result.stdout
    assert not _notices(log)
    calls = [json.loads(line) for line in Path(env["TEST_CLEANUP_LOG"]).read_text().splitlines()]
    assert all(("--dry-run" in call["args"]) == ("--dry-run" in args) for call in calls)
    assert not Path(env["TEST_CLEANUP_ALERT_LOG"]).exists()


@pytest.mark.parametrize("args,code", [(("--help",), 0), (("-h",), 0), (("--bad",), 2)])
def test_invocation_validation_precedes_environment_preflight_and_alerts(tmp_path, args, code):
    checkout, env, log = _notification_checkout(tmp_path)

    result = _run(checkout, env, *args)

    assert result.returncode == code
    assert "Usage:" in result.stdout + result.stderr
    assert not Path(env["TEST_CLEANUP_LOG"]).exists()
    assert not _notices(log)
    assert not Path(env["TEST_CLEANUP_ALERT_LOG"]).exists()
    assert "production environment" not in result.stderr


@pytest.mark.parametrize("helper", HELPERS)
@pytest.mark.parametrize("opt_out", [False, True])
def test_cleanup_failure_only_records_existing_failure_alert(tmp_path, helper, opt_out):
    checkout, env, log = _notification_checkout(tmp_path)
    _production_python(Path(env["HOME"]) / "jarvis-venv")
    env["TEST_FAIL_HELPER"] = helper

    result = _run(checkout, env, *(["--no-notify"] if opt_out else []))

    assert result.returncode == 31
    assert len(_alerts(env)) == 1
    assert not _notices(log)
    assert "Cleanup complete!" not in result.stdout


@pytest.mark.parametrize(
    "behavior", ["error", "logical_failure", "invalid_json", "wrong_shape", "missing_tool"]
)
def test_notice_failure_does_not_change_cleanup_success_or_create_alert(tmp_path, behavior):
    checkout, env, log = _notification_checkout(tmp_path)
    _production_python(Path(env["HOME"]) / "jarvis-venv")
    env["TEST_NOTIFICATION_BEHAVIOR"] = behavior
    if behavior == "missing_tool":
        (checkout / "skills/create_notification.py").unlink()

    result = _run(checkout, env)

    assert result.returncode == 0, result.stderr
    assert "Cleanup complete!" in result.stdout
    assert "cleanup remains successful" in result.stderr
    assert "private child" not in result.stdout + result.stderr
    assert len(_notices(log)) == (0 if behavior == "missing_tool" else 1)
    assert not Path(env["TEST_CLEANUP_ALERT_LOG"]).exists()


def test_notice_deadline_does_not_turn_success_into_failure(tmp_path):
    checkout, env, log = _notification_checkout(tmp_path)
    _production_python(Path(env["HOME"]) / "jarvis-venv")
    env["TEST_NOTIFICATION_BEHAVIOR"] = "timeout"

    result = _run(checkout, env)

    assert result.returncode == 0, result.stderr
    assert "timed out after 15 seconds" in result.stderr
    assert "cleanup remains successful" in result.stderr
    assert len(_notices(log)) == 1
    assert not Path(env["TEST_CLEANUP_ALERT_LOG"]).exists()


@pytest.mark.parametrize("helper,folder", [("cleanup-logs", "logs"), ("cleanup-audio", "audio")])
@pytest.mark.parametrize("phase", ["count", "scan", "partial_scan", "du", "stat"])
def test_filesystem_failures_propagate_and_never_record_success(tmp_path, helper, folder, phase):
    checkout, env, log = _notification_checkout(tmp_path)
    _production_python(Path(env["HOME"]) / "jarvis-venv")
    shutil.copy2(ROOT / "bin" / helper, checkout / "bin" / helper)
    target = checkout / folder / ("old.log" if folder == "logs" else "old.wav")
    target.parent.mkdir(parents=True)
    target.write_text("temporary fixture")
    old = time.time() - 120 * 86400
    os.utime(target, (old, old))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    env.update(TEST_FILESYSTEM_FAILURE=phase, TMPDIR=str(scratch))
    fake_bin = Path(env["PATH"].split(":")[0])
    _write_executable(
        fake_bin / "find",
        f"#!{sys.executable}\n"
        "import os, subprocess, sys\n"
        "phase = os.environ['TEST_FILESYSTEM_FAILURE']\n"
        "scan = '-mtime' in sys.argv\n"
        "if phase == 'partial_scan' and scan:\n"
        "    subprocess.run(['/usr/bin/find', *sys.argv[1:]], check=True)\n"
        "    raise SystemExit(44)\n"
        "if (phase == 'count' and not scan) or (phase == 'scan' and scan):\n"
        "    raise SystemExit(44)\n"
        "os.execv('/usr/bin/find', ['find', *sys.argv[1:]])\n",
    )
    for command in ("du", "stat"):
        _write_executable(
            fake_bin / command,
            f"#!{sys.executable}\n"
            "import os, sys\n"
            f"if os.environ['TEST_FILESYSTEM_FAILURE'] == {command!r}:\n"
            "    raise SystemExit(44)\n"
            f"os.execv('/usr/bin/{command}', [{command!r}, *sys.argv[1:]])\n",
        )

    result = _run(checkout, env)

    assert result.returncode == 44, result.stdout + result.stderr
    assert len(_alerts(env)) == 1
    assert _alerts(env)[0]["payload"]["metadata"]["failed_stage"] == (
        "Logs" if folder == "logs" else "Runtime audio"
    )
    assert not _notices(log)
    assert target.exists()
    assert not list(scratch.iterdir())
    assert "Cleanup complete!" not in result.stdout


@pytest.mark.parametrize("partial_output", [False, True])
def test_disk_summary_failure_keeps_cleanup_successful(tmp_path, partial_output):
    checkout, env, log = _notification_checkout(tmp_path)
    _production_python(Path(env["HOME"]) / "jarvis-venv")
    (checkout / "logs").mkdir()
    (checkout / "audio").mkdir()
    fake_bin = Path(env["PATH"].split(":")[0])
    _write_executable(
        fake_bin / "du",
        "#!/bin/sh\n"
        'if [ "${2##*/}" = logs ]; then\n'
        + ('    printf "999G\\t%s\\n" "$2"\n' if partial_output else "")
        + "    exit 44\n"
        "fi\n"
        'printf "8.0K\\t%s\\n" "$2"\n',
    )

    result = _run(checkout, env)

    assert result.returncode == 0, result.stderr
    assert not Path(env["TEST_CLEANUP_ALERT_LOG"]).exists()
    assert len(_notices(log)) == 1
    assert "Cleanup complete!" in result.stdout
    assert "Could not calculate disk usage for logs; cleanup remains successful." in result.stderr
    assert any(line.split() == ["logs/", "unavailable"] for line in result.stdout.splitlines())
    assert any(line.split() == ["audio/", "8.0K"] for line in result.stdout.splitlines())
    assert "999G" not in result.stdout
