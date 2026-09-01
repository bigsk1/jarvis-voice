"""Phase 3 tests for Jarvis Head publishing and socket ownership."""

from __future__ import annotations

import json
import os
import socket
import stat
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HEAD_ROOT = PROJECT_ROOT / "jarvis-head"
sys.path.insert(0, str(HEAD_ROOT))

from head_protocol import EventType  # noqa: E402
from head_socket import HeadEventSocket, HeadSocketError  # noqa: E402

from lib import head_events  # noqa: E402


def _enable_publisher(monkeypatch, socket_path: Path, *, debug: bool = False) -> None:
    monkeypatch.setenv("JARVIS_HEAD_ENABLED", "true")
    monkeypatch.setenv("JARVIS_HEAD_SOCKET", os.fspath(socket_path))
    monkeypatch.setenv("JARVIS_HEAD_DEBUG", "true" if debug else "false")
    for key in (
        "JARVIS_OVERRIDE_JARVIS_HEAD_ENABLED",
        "JARVIS_OVERRIDE_JARVIS_HEAD_SOCKET",
        "JARVIS_OVERRIDE_JARVIS_HEAD_DEBUG",
    ):
        monkeypatch.delenv(key, raising=False)


def test_socket_path_default_is_stable_across_login_runtime(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1234")
    assert head_events.get_socket_path(uid=1234) == Path(
        "/tmp/jarvis-head-1234/head.sock"
    )
    assert head_events.get_socket_path("/private/head.sock", uid=1234) == Path(
        "/private/head.sock"
    )


def test_relative_socket_override_is_rejected_and_emit_stays_fail_open(
    monkeypatch, capsys
):
    with pytest.raises(ValueError, match="absolute path"):
        head_events.get_socket_path("relative/head.sock")

    monkeypatch.setenv("JARVIS_HEAD_ENABLED", "true")
    monkeypatch.setenv("JARVIS_HEAD_SOCKET", "relative/head.sock")
    for key in (
        "JARVIS_OVERRIDE_JARVIS_HEAD_ENABLED",
        "JARVIS_OVERRIDE_JARVIS_HEAD_SOCKET",
    ):
        monkeypatch.delenv(key, raising=False)

    assert head_events.emit("listen") is False
    assert capsys.readouterr().err == ""


def test_emit_is_disabled_by_default_and_missing_receiver_is_silent(
    tmp_path, monkeypatch, capsys
):
    socket_path = tmp_path / "head.sock"
    monkeypatch.delenv("JARVIS_HEAD_ENABLED", raising=False)
    monkeypatch.delenv("JARVIS_OVERRIDE_JARVIS_HEAD_ENABLED", raising=False)
    assert head_events.emit("listen") is False

    _enable_publisher(monkeypatch, socket_path)
    started = time.monotonic()
    assert head_events.emit("listen") is False
    assert time.monotonic() - started < 0.5
    assert capsys.readouterr().err == ""


def test_emit_fails_open_if_configuration_itself_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        head_events,
        "_config_bool",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("broken config")),
    )
    assert head_events.emit("listen") is False


def test_emit_sets_nonblocking_before_a_full_queue_failure(tmp_path, monkeypatch, capsys):
    _enable_publisher(monkeypatch, tmp_path / "head.sock")
    blocking_values: list[bool] = []

    class FullQueueSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def setblocking(self, value: bool) -> None:
            blocking_values.append(value)

        def sendto(self, _payload: bytes, _destination: str) -> int:
            raise BlockingIOError("queue full")

    monkeypatch.setattr(head_events.socket, "socket", lambda *_args: FullQueueSocket())
    assert head_events.emit("speak", playback_id="attempt", wav="x.wav", t0=1.0) is False
    assert blocking_values == [False]
    assert capsys.readouterr().err == ""


def test_emit_debug_is_bounded_and_never_raises(tmp_path, monkeypatch, capsys):
    _enable_publisher(monkeypatch, tmp_path / "missing" / "head.sock", debug=True)
    assert head_events.emit("listen") is False
    diagnostic = capsys.readouterr().err
    assert diagnostic.startswith("jarvis-head emit 'listen' failed:")
    assert len(diagnostic) < 300


def test_emit_to_stale_socket_and_oversized_payload_fail_open(tmp_path, monkeypatch, capsys):
    socket_path = tmp_path / "head.sock"
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    stale.bind(os.fspath(socket_path))
    stale.close()
    _enable_publisher(monkeypatch, socket_path)

    started = time.monotonic()
    assert head_events.emit("listen") is False
    assert head_events.emit("speak", wav="x" * 5000, playback_id="id", t0=1.0) is False
    assert time.monotonic() - started < 0.5
    assert capsys.readouterr().err == ""


def test_publisher_round_trip_with_bound_display_socket(tmp_path, monkeypatch):
    socket_path = tmp_path / "head.sock"
    _enable_publisher(monkeypatch, socket_path)

    with HeadEventSocket(socket_path) as receiver:
        assert head_events.emit("listen", type="sleep") is True
        events = receiver.poll()

    assert [event.type for event in events] == [EventType.LISTEN]


def test_listener_drops_malformed_and_oversized_datagrams(tmp_path):
    socket_path = tmp_path / "head.sock"
    with HeadEventSocket(socket_path) as receiver:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender:
            destination = os.fspath(socket_path)
            sender.sendto(b"{not-json", destination)
            sender.sendto(b"x" * (head_events.MAX_DATAGRAM_BYTES + 1), destination)
            sender.sendto(json.dumps({"type": "think"}).encode(), destination)
        events = receiver.poll()

    assert [event.type for event in events] == [EventType.THINK]


def test_second_display_cannot_steal_active_socket(tmp_path):
    socket_path = tmp_path / "head.sock"
    first = HeadEventSocket(socket_path).open()
    active_inode = socket_path.lstat().st_ino
    try:
        with pytest.raises(HeadSocketError, match="already running"):
            HeadEventSocket(socket_path).open()
        assert socket_path.lstat().st_ino == active_inode
    finally:
        first.close()


def test_owned_stale_socket_is_recovered_after_lock_is_free(tmp_path):
    socket_path = tmp_path / "head.sock"
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    stale.bind(os.fspath(socket_path))
    stale.close()

    receiver = HeadEventSocket(socket_path).open()
    try:
        assert socket_path.exists()
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender:
            sender.sendto(b'{"type":"listen"}', os.fspath(socket_path))
        assert [event.type for event in receiver.poll()] == [EventType.LISTEN]
    finally:
        receiver.close()
    assert not socket_path.exists()


@pytest.mark.parametrize("unsafe_kind", ["file", "symlink"])
def test_regular_files_and_symlinks_are_never_unlinked(tmp_path, unsafe_kind):
    socket_path = tmp_path / "head.sock"
    if unsafe_kind == "file":
        socket_path.write_text("keep me", encoding="utf-8")
    else:
        target = tmp_path / "target"
        target.write_text("keep me", encoding="utf-8")
        socket_path.symlink_to(target)

    with pytest.raises(HeadSocketError, match="non-socket"):
        HeadEventSocket(socket_path).open()
    assert socket_path.is_symlink() if unsafe_kind == "symlink" else socket_path.is_file()


def test_default_runtime_leaf_and_socket_get_private_modes(tmp_path):
    runtime_dir = tmp_path / "jarvis"
    socket_path = runtime_dir / "head.sock"
    with HeadEventSocket(socket_path, default_path=True):
        assert stat.S_IMODE(runtime_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(socket_path.lstat().st_mode) == 0o600
    assert not socket_path.exists()


def test_custom_existing_parent_is_not_chmodded(tmp_path):
    runtime_dir = tmp_path / "shared"
    runtime_dir.mkdir(mode=0o755)
    socket_path = runtime_dir / "head.sock"

    with pytest.raises(HeadSocketError, match="must be private"):
        HeadEventSocket(socket_path).open()
    assert stat.S_IMODE(runtime_dir.stat().st_mode) == 0o755
