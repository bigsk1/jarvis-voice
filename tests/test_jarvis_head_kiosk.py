"""Behavioral tests for the manual Linux-VT Jarvis Head kiosk wrapper."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import pwd
import subprocess
import sys
from pathlib import Path

import pytest

from lib import config_loader

ROOT = Path(__file__).resolve().parents[1]
KIOSK = ROOT / "bin" / "kiosk.sh"
HEAD = ROOT / "bin" / "jarvis-head"


def _write_command(bin_dir: Path, name: str, body: str) -> None:
    command = bin_dir / name
    command.write_text(f"#!/usr/bin/env bash\nset -euo pipefail\n{body}\n")
    command.chmod(0o755)


def _fake_environment(tmp_path: Path) -> dict[str, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "commands.log"
    dev_root = tmp_path / "dev"
    dev_root.mkdir()
    (dev_root / "tty1").symlink_to("/dev/null")
    (dev_root / "tty8").symlink_to("/dev/null")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cloud.env").write_text("JARVIS_HEAD_KIOSK_VT=8\nJARVIS_HEAD_CELL_ASPECT=0.45\n")

    _write_command(
        fake_bin,
        "sudo",
        """
echo "sudo|$*" >> "$KIOSK_TEST_LOG"
if [[ "${1:-}" == "-v" ]]; then
    exit 0
fi
exec "$@"
""",
    )
    _write_command(
        fake_bin,
        "systemctl",
        """
echo "systemctl|$*" >> "$KIOSK_TEST_LOG"
case "${1:-}" in
    show)
        if [[ " $* " == *" --value "* ]]; then
            echo "${FAKE_UNIT_STATE:-inactive}"
        else
            echo "SubState=running"
            echo "MainPID=4242"
            echo "ExecMainStatus=0"
        fi
        ;;
    is-active)
        if [[ "$*" == *"getty@tty"* ]]; then
            [[ "${FAKE_GETTY_ACTIVE:-false}" == "true" ]] && exit 0
            exit 3
        fi
        [[ "${FAKE_UNIT_STATE:-inactive}" == "active" ]] && exit 0
        exit 3
        ;;
    reset-failed|stop)
        exit 0
        ;;
esac
""",
    )
    _write_command(
        fake_bin,
        "systemd-run",
        'echo "systemd-run|$*" >> "$KIOSK_TEST_LOG"',
    )
    _write_command(fake_bin, "fgconsole", "echo 1")
    _write_command(
        fake_bin,
        "openvt",
        'echo "openvt|$*" >> "$KIOSK_TEST_LOG"',
    )
    _write_command(
        fake_bin,
        "chvt",
        """
echo "chvt|$*" >> "$KIOSK_TEST_LOG"
# Like the kernel refusing to leave a KD_GRAPHICS console: fail the first
# FAKE_CHVT_FAILURES calls, then succeed.
counter="${KIOSK_TEST_LOG%/*}/chvt-calls"
calls=$(( $(cat "$counter" 2>/dev/null || echo 0) + 1 ))
echo "$calls" > "$counter"
(( calls > ${FAKE_CHVT_FAILURES:-0} )) || exit 1
""",
    )
    _write_command(
        fake_bin,
        "setpriv",
        'echo "setpriv|$*" >> "$KIOSK_TEST_LOG"',
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "KIOSK_TEST_LOG": str(log),
            "JARVIS_HEAD_KIOSK_DEV_ROOT": str(dev_root),
            "JARVIS_HEAD_KIOSK_CONFIG_DIR": str(config_dir),
        }
    )
    return env


def _run(tmp_path: Path, *args: str, **overrides: str) -> subprocess.CompletedProcess[str]:
    env = _fake_environment(tmp_path)
    env.update(overrides)
    return subprocess.run(
        [str(KIOSK), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def test_start_creates_bounded_transient_unit_for_unused_vt(tmp_path: Path):
    result = _run(tmp_path, "start", "--", "--fps", "45", "--color", "green")

    assert result.returncode == 0, result.stderr
    assert "started on tty8" in result.stdout
    commands = (tmp_path / "commands.log").read_text().splitlines()
    launch = next(line for line in commands if line.startswith("systemd-run|"))
    assert "--unit=jarvis-head-kiosk.service" in launch
    assert "--property=KillMode=control-group" in launch
    assert "--property=CPUQuota=50%" in launch
    assert "--property=MemoryMax=256M" in launch
    assert "__session" in launch
    assert "0.45" in launch
    assert "--fps 45 --color green" in launch
    assert pwd.getpwuid(os.getuid()).pw_name in launch


def test_stop_uses_systemd_control_group_and_status_is_read_only(tmp_path: Path):
    resumed = _run(tmp_path / "resume", "start", FAKE_UNIT_STATE="active")
    assert resumed.returncode == 0, resumed.stderr
    assert "switched to tty8" in resumed.stdout
    resume_commands = (tmp_path / "resume" / "commands.log").read_text()
    assert "chvt|8" in resume_commands
    assert "systemd-run|" not in resume_commands

    stopped = _run(tmp_path / "stop", "stop", FAKE_UNIT_STATE="active")

    assert stopped.returncode == 0, stopped.stderr
    assert "kiosk stopped" in stopped.stdout
    stop_commands = (tmp_path / "stop" / "commands.log").read_text()
    assert "systemctl|stop jarvis-head-kiosk.service" in stop_commands

    status = _run(tmp_path / "status", "status", FAKE_UNIT_STATE="active")
    assert status.returncode == 0, status.stderr
    assert "Jarvis Head kiosk: active" in status.stdout
    assert "MainPID=4242" in status.stdout
    status_commands = (tmp_path / "status" / "commands.log").read_text()
    assert "sudo|" not in status_commands


def test_primary_console_and_occupied_target_are_refused(tmp_path: Path):
    primary = _run(tmp_path / "primary", "start", JARVIS_HEAD_KIOSK_VT="1")
    assert primary.returncode == 2
    assert "tty1 is reserved" in primary.stderr

    occupied = _run(tmp_path / "occupied", "start", FAKE_GETTY_ACTIVE="true")
    assert occupied.returncode == 2
    assert "active getty" in occupied.stderr

    relative_socket = _run(
        tmp_path / "relative-socket",
        "start",
        JARVIS_HEAD_SOCKET="relative/head.sock",
    )
    assert relative_socket.returncode == 2
    assert "absolute path" in relative_socket.stderr


def _run_session(tmp_path: Path, *head_args: str, **overrides: str):
    env = _fake_environment(tmp_path)
    env.update(overrides)
    user = pwd.getpwuid(os.getuid())
    return subprocess.run(
        [
            str(KIOSK),
            "__session",
            user.pw_name,
            str(user.pw_uid),
            str(user.pw_gid),
            user.pw_dir,
            "8",
            "1",
            "",
            "0.4",
            "120",
            "cloud",
            "--",
            *head_args,
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def test_session_returns_to_original_vt_when_head_exits(tmp_path: Path):
    result = _run_session(tmp_path, "--fps", "30")

    assert result.returncode == 0, result.stderr
    user = pwd.getpwuid(os.getuid())
    commands = (tmp_path / "commands.log").read_text().splitlines()
    openvt = next(line for line in commands if line.startswith("openvt|"))
    # setpriv execs the launcher directly; no runuser/PAM layer that would
    # forward a second SIGTERM and sleep two seconds on stop.
    assert (
        f"-c 8 -s -w -- setpriv --reuid {user.pw_uid} --regid {user.pw_gid} --init-groups -- env -i"
    ) in openvt
    assert "runuser" not in openvt
    assert str(ROOT / "bin" / "jarvis-head") in openvt
    assert "--fps 30" in openvt
    assert commands[-1] == "chvt|1"
    assert commands.count("chvt|1") == 1


def test_session_retries_the_return_switch_until_the_console_leaves_graphics_mode(
    tmp_path: Path,
):
    # Three refusals (the display is still restoring KD_TEXT), then it takes.
    result = _run_session(
        tmp_path / "eventually",
        FAKE_CHVT_FAILURES="3",
        JARVIS_HEAD_KIOSK_RETURN_VT_RETRY_SECONDS="0",
    )
    assert result.returncode == 0, result.stderr
    commands = (tmp_path / "eventually" / "commands.log").read_text().splitlines()
    assert commands.count("chvt|1") == 4
    assert commands[-4:] == ["chvt|1"] * 4

    # Bounded: it gives up inside the unit's stop timeout rather than hanging,
    # and the head's own exit status is preserved.
    result = _run_session(
        tmp_path / "bounded",
        FAKE_CHVT_FAILURES="999",
        JARVIS_HEAD_KIOSK_RETURN_VT_ATTEMPTS="5",
        JARVIS_HEAD_KIOSK_RETURN_VT_RETRY_SECONDS="0",
    )
    assert result.returncode == 0, result.stderr
    commands = (tmp_path / "bounded" / "commands.log").read_text().splitlines()
    assert commands.count("chvt|1") == 5
    # ...and says so on the unit's stderr (the journal) instead of a silent success.
    assert "WARNING: could not switch the console back to tty1 after 5 attempts" in result.stderr
    assert "Ctrl+Alt+F1" in result.stderr


def test_direct_display_hydrates_only_head_config_without_losing_explicit_env(
    monkeypatch,
):
    module_name = "test_jarvis_head_launcher_config"
    loader = importlib.machinery.SourceFileLoader(module_name, str(HEAD))
    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None and spec.loader is not None
    launcher = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, launcher)
    spec.loader.exec_module(launcher)

    loaded: list[Path] = []

    def fake_load_env_file(path):
        loaded.append(Path(path))
        return {
            "JARVIS_HEAD_CELL_ASPECT": "0.9",
            "JARVIS_HEAD_IDLE_TIMEOUT": "90",
            "JARVIS_HEAD_RENDERER": "fb",
            "JARVIS_HEAD_FONT_PX": "9",
            "JARVIS_HEAD_FACE_BRIGHTNESS": "1.2",
            "JARVIS_HEAD_SCAN_LEVELS": "-48",
            "JARVIS_HEAD_AMBIENT_SCAN": "true",
            "JARVIS_HEAD_AMBIENT_SCAN_FIRST_SECONDS": "2.5",
            "JARVIS_HEAD_AMBIENT_SCAN_MIN_SECONDS": "9",
            "JARVIS_HEAD_AMBIENT_SCAN_MAX_SECONDS": "13",
            "JARVIS_HEAD_AMBIENT_SCAN_DOUBLE_CHANCE": "0.25",
            "OPENAI_API_KEY": "must-not-enter-kiosk-env",
        }

    monkeypatch.setenv("JARVIS_HEAD_CELL_ASPECT", "0.4")
    for key in (
        "JARVIS_HEAD_IDLE_TIMEOUT",
        "JARVIS_HEAD_RENDERER",
        "JARVIS_HEAD_FONT_PX",
        "JARVIS_HEAD_FACE_BRIGHTNESS",
        "JARVIS_HEAD_SCAN_LEVELS",
        "JARVIS_HEAD_AMBIENT_SCAN",
        "JARVIS_HEAD_AMBIENT_SCAN_FIRST_SECONDS",
        "JARVIS_HEAD_AMBIENT_SCAN_MIN_SECONDS",
        "JARVIS_HEAD_AMBIENT_SCAN_MAX_SECONDS",
        "JARVIS_HEAD_AMBIENT_SCAN_DOUBLE_CHANCE",
        "OPENAI_API_KEY",
    ):
        # delenv on an absent key records nothing, so the launcher's writes
        # would leak into later tests; setenv first makes teardown remove them.
        monkeypatch.setenv(key, "placeholder")
        monkeypatch.delenv(key)
    monkeypatch.setattr(config_loader, "load_env_file", fake_load_env_file)

    with pytest.raises(SystemExit) as exc:
        launcher.main(["--help"])

    assert exc.value.code == 0
    assert loaded == [ROOT / "config" / "cloud.env"]
    assert os.environ["JARVIS_HEAD_CELL_ASPECT"] == "0.4"
    assert os.environ["JARVIS_HEAD_IDLE_TIMEOUT"] == "90"
    assert os.environ["JARVIS_HEAD_RENDERER"] == "fb"
    assert os.environ["JARVIS_HEAD_FONT_PX"] == "9"
    assert os.environ["JARVIS_HEAD_FACE_BRIGHTNESS"] == "1.2"
    assert os.environ["JARVIS_HEAD_SCAN_LEVELS"] == "-48"
    assert os.environ["JARVIS_HEAD_AMBIENT_SCAN"] == "true"
    assert os.environ["JARVIS_HEAD_AMBIENT_SCAN_FIRST_SECONDS"] == "2.5"
    assert os.environ["JARVIS_HEAD_AMBIENT_SCAN_MIN_SECONDS"] == "9"
    assert os.environ["JARVIS_HEAD_AMBIENT_SCAN_MAX_SECONDS"] == "13"
    assert os.environ["JARVIS_HEAD_AMBIENT_SCAN_DOUBLE_CHANCE"] == "0.25"
    assert "OPENAI_API_KEY" not in os.environ


def test_launcher_passes_validated_choreography_config_to_the_scene(monkeypatch):
    module_name = "test_jarvis_head_launcher_ambient"
    loader = importlib.machinery.SourceFileLoader(module_name, str(HEAD))
    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None and spec.loader is not None
    launcher = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, launcher)
    spec.loader.exec_module(launcher)

    seen = {}

    def fake_run_display(**kwargs):
        seen.update(kwargs)

    import app

    monkeypatch.setattr(app, "run_display", fake_run_display)
    monkeypatch.setattr(config_loader, "load_env_file", lambda _path: {})
    monkeypatch.setenv("JARVIS_HEAD_AMBIENT_SCAN", "true")
    monkeypatch.setenv("JARVIS_HEAD_SCAN_LEVELS", "-48")
    monkeypatch.setenv("JARVIS_HEAD_AMBIENT_SCAN_FIRST_SECONDS", "2.5")
    monkeypatch.setenv("JARVIS_HEAD_AMBIENT_SCAN_MIN_SECONDS", "9")
    monkeypatch.setenv("JARVIS_HEAD_AMBIENT_SCAN_MAX_SECONDS", "13")
    monkeypatch.setenv("JARVIS_HEAD_AMBIENT_SCAN_DOUBLE_CHANCE", "0.25")

    assert launcher.main(["--demo-face"]) == 0
    assert seen["ambient_scan"] is True
    assert seen["scan_levels"] == -48
    assert seen["ambient_scan_first_seconds"] == 2.5
    assert seen["ambient_scan_min_seconds"] == 9.0
    assert seen["ambient_scan_max_seconds"] == 13.0
    assert seen["ambient_scan_double_chance"] == 0.25


def test_start_forwards_and_preflights_face_brightness(tmp_path: Path):
    good = _run(tmp_path / "good", "start", JARVIS_HEAD_FACE_BRIGHTNESS="1.25")
    assert good.returncode == 0, good.stderr
    launch = next(
        line
        for line in (tmp_path / "good" / "commands.log").read_text().splitlines()
        if line.startswith("systemd-run|")
    )
    assert "--env JARVIS_HEAD_FACE_BRIGHTNESS=1.25" in launch

    for bad in ("2", "0.1", "bright", "1.2.3"):
        result = _run(tmp_path / f"bad-{bad}", "start", JARVIS_HEAD_FACE_BRIGHTNESS=bad)
        assert result.returncode == 2, result.stdout
        assert "JARVIS_HEAD_FACE_BRIGHTNESS" in result.stderr
        log = tmp_path / f"bad-{bad}" / "commands.log"
        assert not log.exists() or "systemd-run|" not in log.read_text()


def test_start_forwards_and_preflights_ambient_scan_settings(tmp_path: Path):
    settings = {
        "JARVIS_HEAD_AMBIENT_SCAN": "true",
        "JARVIS_HEAD_AMBIENT_SCAN_FIRST_SECONDS": "2.5",
        "JARVIS_HEAD_AMBIENT_SCAN_MIN_SECONDS": "9",
        "JARVIS_HEAD_AMBIENT_SCAN_MAX_SECONDS": "13",
        "JARVIS_HEAD_AMBIENT_SCAN_DOUBLE_CHANCE": "0.25",
        "JARVIS_HEAD_SCAN_LEVELS": "-48",
    }
    good = _run(tmp_path / "good-ambient", "start", **settings)
    assert good.returncode == 0, good.stderr
    launch = next(
        line
        for line in (tmp_path / "good-ambient" / "commands.log").read_text().splitlines()
        if line.startswith("systemd-run|")
    )
    for key, value in settings.items():
        assert f"--env {key}={value}" in launch

    invalid_settings = (
        {"JARVIS_HEAD_AMBIENT_SCAN": "sometimes"},
        {"JARVIS_HEAD_AMBIENT_SCAN_FIRST_SECONDS": "-1"},
        {"JARVIS_HEAD_AMBIENT_SCAN_MIN_SECONDS": "0"},
        {"JARVIS_HEAD_AMBIENT_SCAN_MAX_SECONDS": "601"},
        {"JARVIS_HEAD_AMBIENT_SCAN_DOUBLE_CHANCE": "1.1"},
        {
            "JARVIS_HEAD_AMBIENT_SCAN_MIN_SECONDS": "15",
            "JARVIS_HEAD_AMBIENT_SCAN_MAX_SECONDS": "10",
        },
    )
    for index, values in enumerate(invalid_settings):
        path = tmp_path / f"bad-ambient-{index}"
        result = _run(path, "start", **values)
        assert result.returncode == 2, result.stdout
        assert "AMBIENT_SCAN" in result.stderr
        log = path / "commands.log"
        assert not log.exists() or "systemd-run|" not in log.read_text()


def test_scan_levels_flag_wins_over_config_and_is_preflighted(tmp_path: Path):
    for flags in (("--scan-levels", "-48"), ("--scan-levels=-48",)):
        result = _run(
            tmp_path / ("good-" + "-".join(flags)),
            "start",
            "--",
            *flags,
            JARVIS_HEAD_SCAN_LEVELS="999",
        )
        assert result.returncode == 0, result.stderr
        launch = next(
            line
            for line in (tmp_path / ("good-" + "-".join(flags)) / "commands.log")
            .read_text()
            .splitlines()
            if line.startswith("systemd-run|")
        )
        assert " ".join(flags) in launch

    for flags in (
        ("--scan-levels", "256"),
        ("--scan-levels=-256",),
        ("--scan-levels", "1.5"),
        ("--scan-levels=",),
        ("--scan-levels",),
        ("--scan-levels", "--renderer", "curses"),
    ):
        path = tmp_path / ("bad-" + "-".join(flags).strip("-"))
        result = _run(path, "start", "--", *flags)
        assert result.returncode == 2, result.stdout
        assert "scan levels" in result.stderr
        log = path / "commands.log"
        assert not log.exists() or "systemd-run|" not in log.read_text()

    for value in ("256", "-256", "1.5", "dark"):
        path = tmp_path / f"bad-env-{value}"
        result = _run(path, "start", JARVIS_HEAD_SCAN_LEVELS=value)
        assert result.returncode == 2, result.stdout
        assert "JARVIS_HEAD_SCAN_LEVELS" in result.stderr
        log = path / "commands.log"
        assert not log.exists() or "systemd-run|" not in log.read_text()


def test_head_flags_win_over_config_in_the_face_knob_preflight(tmp_path: Path):
    # A valid CLI value rescues an invalid config value, in both spellings.
    for flags in (["--face-brightness", "1.0"], ["--face-brightness=1.0"]):
        result = _run(
            tmp_path / "-".join(flags), "start", "--", *flags, JARVIS_HEAD_FACE_BRIGHTNESS="2"
        )
        assert result.returncode == 0, result.stderr
        assert "started on tty8" in result.stdout

    # An invalid CLI value is refused here, not after "started".
    for flags in (
        ["--face-brightness", "2"],
        ["--face-brightness", "-0.5"],
        ["--face-brightness=0.1"],
        ["--face-presence", "0.2"],
        ["--face-presence=1.5"],
    ):
        result = _run(tmp_path / ("cli-" + "-".join(flags)), "start", "--", *flags)
        assert result.returncode == 2, result.stdout
        assert flags[0].split("=")[0] in result.stderr
        log = tmp_path / ("cli-" + "-".join(flags)) / "commands.log"
        assert not log.exists() or "systemd-run|" not in log.read_text()

    # A flag with an empty or missing value is refused here too; the launcher
    # would otherwise reject it after "started".
    for flags in (
        ["--face-brightness="],
        ["--face-brightness"],
        ["--face-presence="],
        ["--face-presence"],
        ["--face-presence", "--renderer", "curses"],
    ):
        name = "empty-" + "-".join(flags).strip("-")
        result = _run(tmp_path / name, "start", "--", *flags)
        assert result.returncode == 2, result.stdout
        assert flags[0].split("=")[0] in result.stderr
        log = tmp_path / name / "commands.log"
        assert not log.exists() or "systemd-run|" not in log.read_text()

    # Python float spellings the launcher accepts pass the preflight as well.
    for flags in (
        ["--face-presence=.45"],
        ["--face-brightness", "5e-1"],
        ["--face-brightness=1E0"],
    ):
        result = _run(tmp_path / ("float-" + "-".join(flags).strip("-")), "start", "--", *flags)
        assert result.returncode == 0, result.stderr

    # Presence is forwarded from the environment like the other knobs.
    good = _run(
        tmp_path / "presence",
        "start",
        "--",
        "--face-presence=0.45",
        JARVIS_HEAD_FACE_PRESENCE="0.9",
    )
    assert good.returncode == 0, good.stderr
    launch = next(
        line
        for line in (tmp_path / "presence" / "commands.log").read_text().splitlines()
        if line.startswith("systemd-run|")
    )
    assert "--env JARVIS_HEAD_FACE_PRESENCE=0.9" in launch and "--face-presence=0.45" in launch


def test_start_forwards_explicit_renderer_settings_into_the_clean_session(tmp_path: Path):
    result = _run(
        tmp_path,
        "start",
        "--",
        "--renderer",
        "fb",
        JARVIS_HEAD_RENDERER="fb",
        JARVIS_HEAD_FONT_PX="9",
        JARVIS_HEAD_FRAMEBUFFER=str(tmp_path / "not-a-device"),
    )

    assert result.returncode == 2, result.stdout
    assert "not a framebuffer device" in result.stderr

    # /dev/null is a character device, which is all the preflight checks for.
    result = _run(
        tmp_path / "ok",
        "start",
        "--",
        "--renderer",
        "fb",
        JARVIS_HEAD_RENDERER="fb",
        JARVIS_HEAD_FONT_PX="9",
        JARVIS_HEAD_FRAMEBUFFER="/dev/null",
    )
    assert result.returncode == 0, result.stderr
    launch = next(
        line
        for line in (tmp_path / "ok" / "commands.log").read_text().splitlines()
        if line.startswith("systemd-run|")
    )
    assert "--env JARVIS_HEAD_RENDERER=fb" in launch
    assert "--env JARVIS_HEAD_FRAMEBUFFER=/dev/null" in launch
    assert "--env JARVIS_HEAD_FONT_PX=9" in launch
    assert launch.endswith("-- --renderer fb")


def test_start_preflights_the_renderer_and_device_named_on_the_command_line(tmp_path: Path):
    missing = str(tmp_path / "no-such-fb")

    # CLI --renderer fb with a config/env device that is not a device: refused.
    for flags in (["--renderer", "fb"], ["--renderer=fb"]):
        result = _run(
            tmp_path / "-".join(flags), "start", "--", *flags, JARVIS_HEAD_FRAMEBUFFER=missing
        )
        assert result.returncode == 2, result.stdout
        assert "not a framebuffer device" in result.stderr
        assert (
            not (tmp_path / "-".join(flags) / "commands.log").exists()
            or "systemd-run|" not in (tmp_path / "-".join(flags) / "commands.log").read_text()
        )

    # CLI --framebuffer overrides the environment in both directions.
    bad_cli = _run(
        tmp_path / "bad-cli",
        "start",
        "--",
        "--renderer",
        "fb",
        f"--framebuffer={missing}",
        JARVIS_HEAD_FRAMEBUFFER="/dev/null",
    )
    assert bad_cli.returncode == 2
    assert missing in bad_cli.stderr

    good_cli = _run(
        tmp_path / "good-cli",
        "start",
        "--",
        "--renderer=fb",
        "--framebuffer",
        "/dev/null",
        JARVIS_HEAD_FRAMEBUFFER=missing,
    )
    assert good_cli.returncode == 0, good_cli.stderr
    assert "started on tty8" in good_cli.stdout

    # CLI --renderer curses beats a config that says fb, so no device is needed.
    curses_cli = _run(
        tmp_path / "curses-cli",
        "start",
        "--",
        "--renderer",
        "curses",
        JARVIS_HEAD_RENDERER="fb",
        JARVIS_HEAD_FRAMEBUFFER=missing,
    )
    assert curses_cli.returncode == 0, curses_cli.stderr

    bogus = _run(tmp_path / "bogus", "start", "--", "--renderer", "svg")
    assert bogus.returncode == 2
    assert "curses or fb" in bogus.stderr

    snapshot = _run(tmp_path / "snapshot", "start", "--", "--snapshot", "/tmp/x.png")
    assert snapshot.returncode == 2
    assert "--snapshot" in snapshot.stderr


def test_session_accepts_env_passthrough_before_head_args(tmp_path: Path):
    env = _fake_environment(tmp_path)
    user = pwd.getpwuid(os.getuid())
    result = subprocess.run(
        [
            str(KIOSK),
            "__session",
            user.pw_name,
            str(user.pw_uid),
            str(user.pw_gid),
            user.pw_dir,
            "8",
            "1",
            "",
            "",
            "",
            "cloud",
            "--env",
            "JARVIS_HEAD_RENDERER=fb",
            "--env",
            "JARVIS_HEAD_FONT_PX=9",
            "--",
            "--fps",
            "30",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    openvt = next(
        line
        for line in (tmp_path / "commands.log").read_text().splitlines()
        if line.startswith("openvt|")
    )
    assert "JARVIS_HEAD_RENDERER=fb JARVIS_HEAD_FONT_PX=9" in openvt
    assert "--fps 30" in openvt

    bad = subprocess.run(
        [
            str(KIOSK),
            "__session",
            user.pw_name,
            str(user.pw_uid),
            str(user.pw_gid),
            user.pw_dir,
            "8",
            "1",
            "",
            "",
            "",
            "cloud",
            "--env",
            "PATH=/tmp/evil",
            "--",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert bad.returncode == 2
    assert "passthrough" in bad.stderr


def test_display_launcher_falls_back_to_legacy_operator_environment(monkeypatch, tmp_path: Path):
    module_name = "test_jarvis_head_launcher_python"
    loader = importlib.machinery.SourceFileLoader(module_name, str(HEAD))
    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None and spec.loader is not None
    launcher = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, launcher)
    spec.loader.exec_module(launcher)

    repo_venv = tmp_path / "repo-venv"
    legacy_venv = tmp_path / "legacy-venv"
    legacy_python = legacy_venv / "bin" / "python"
    legacy_python.parent.mkdir(parents=True)
    legacy_python.touch()
    monkeypatch.setattr(launcher, "REPO_VENV", repo_venv)
    monkeypatch.setattr(launcher, "REPO_PYTHON", repo_venv / "bin" / "python")
    monkeypatch.setattr(launcher, "LEGACY_VENV", legacy_venv)
    monkeypatch.setattr(launcher, "LEGACY_PYTHON", legacy_python)

    assert launcher._display_python() == (legacy_venv, legacy_python)

    repo_python = repo_venv / "bin" / "python"
    repo_python.parent.mkdir(parents=True)
    repo_python.touch()
    assert launcher._display_python() == (repo_venv, repo_python)
