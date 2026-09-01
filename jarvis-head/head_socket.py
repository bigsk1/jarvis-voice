"""Secure singleton Unix datagram endpoint owned by the head display."""

from __future__ import annotations

import fcntl
import os
import socket
import stat
from pathlib import Path

from head_protocol import HeadEvent, parse_event

from lib.head_events import MAX_DATAGRAM_BYTES

MAX_EVENTS_PER_POLL = 32
LOCK_FILENAME = "head.lock"
SOCKET_MODE = 0o600
RUNTIME_DIR_MODE = 0o700


class HeadSocketError(RuntimeError):
    """The display cannot safely acquire its configured event endpoint."""


class HeadEventSocket:
    """Nonblocking receiver with advisory-lock and stale-inode protection."""

    def __init__(self, path: str | os.PathLike[str], *, default_path: bool = False) -> None:
        self.path = Path(path)
        self.default_path = default_path
        self._socket: socket.socket | None = None
        self._lock_fd: int | None = None
        self._bound_identity: tuple[int, int] | None = None

    def open(self) -> HeadEventSocket:
        if self._socket is not None or self._lock_fd is not None:
            raise HeadSocketError("head event socket is already open")
        self._validate_socket_path_length()
        self._prepare_runtime_dir()

        try:
            self._acquire_lock()
            self._remove_owned_stale_socket()
            receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                receiver.setblocking(False)
                receiver.bind(os.fspath(self.path))
                bound_stat = self.path.lstat()
                self._bound_identity = (bound_stat.st_dev, bound_stat.st_ino)
                os.chmod(self.path, SOCKET_MODE, follow_symlinks=False)
            except BaseException:
                receiver.close()
                raise
            self._socket = receiver
            return self
        except BaseException:
            self.close()
            raise

    def poll(self, *, limit: int = MAX_EVENTS_PER_POLL) -> list[HeadEvent]:
        """Drain at most ``limit`` packets without blocking; invalid packets disappear."""

        if self._socket is None:
            raise HeadSocketError("head event socket is not open")
        bounded_limit = min(max(limit, 0), MAX_EVENTS_PER_POLL)
        events: list[HeadEvent] = []
        for _ in range(bounded_limit):
            try:
                datagram = self._socket.recv(MAX_DATAGRAM_BYTES + 1)
            except BlockingIOError:
                break
            except InterruptedError:
                continue
            event = parse_event(datagram)
            if event is not None:
                events.append(event)
        return events

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

        if self._bound_identity is not None:
            try:
                path_stat = self.path.lstat()
            except FileNotFoundError:
                pass
            else:
                identity = (path_stat.st_dev, path_stat.st_ino)
                if (
                    identity == self._bound_identity
                    and stat.S_ISSOCK(path_stat.st_mode)
                    and path_stat.st_uid == os.getuid()
                ):
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
            self._bound_identity = None

        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(self._lock_fd)
                self._lock_fd = None

    def __enter__(self) -> HeadEventSocket:
        return self.open()

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def _validate_socket_path_length(self) -> None:
        if not self.path.name:
            raise HeadSocketError("head socket path must name a socket file")
        if len(os.fsencode(self.path)) > 107:
            raise HeadSocketError("head socket path is too long for a Unix socket")

    def _prepare_runtime_dir(self) -> None:
        runtime_dir = self.path.parent
        if runtime_dir.exists() or runtime_dir.is_symlink():
            self._require_private_directory(runtime_dir)
            if self.default_path:
                os.chmod(runtime_dir, RUNTIME_DIR_MODE, follow_symlinks=False)
            return

        try:
            runtime_dir.mkdir(mode=RUNTIME_DIR_MODE, parents=False)
        except OSError as exc:
            raise HeadSocketError(f"cannot create head runtime directory: {exc}") from exc
        self._require_private_directory(runtime_dir)

    def _require_private_directory(self, directory: Path) -> None:
        try:
            directory_stat = directory.lstat()
        except OSError as exc:
            raise HeadSocketError(f"cannot inspect head runtime directory: {exc}") from exc
        if not stat.S_ISDIR(directory_stat.st_mode) or directory.is_symlink():
            raise HeadSocketError("head runtime path is not a real directory")
        if directory_stat.st_uid != os.getuid():
            raise HeadSocketError("head runtime directory is not owned by the current user")
        if not self.default_path and stat.S_IMODE(directory_stat.st_mode) & 0o077:
            raise HeadSocketError("custom head runtime directory must be private (mode 0700)")
        if not os.access(directory, os.W_OK | os.X_OK):
            raise HeadSocketError("head runtime directory is not writable")

    def _acquire_lock(self) -> None:
        lock_path = self.path.parent / LOCK_FILENAME
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            lock_fd = os.open(lock_path, flags, SOCKET_MODE)
        except OSError as exc:
            raise HeadSocketError(f"cannot open head singleton lock: {exc}") from exc

        try:
            lock_stat = os.fstat(lock_fd)
            if (
                not stat.S_ISREG(lock_stat.st_mode)
                or lock_stat.st_uid != os.getuid()
                or lock_stat.st_nlink != 1
            ):
                raise HeadSocketError("head singleton lock is not a safe owned file")
            os.fchmod(lock_fd, SOCKET_MODE)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise HeadSocketError("another Jarvis Head display is already running") from exc
        except BaseException:
            os.close(lock_fd)
            raise
        self._lock_fd = lock_fd

    def _remove_owned_stale_socket(self) -> None:
        try:
            socket_stat = self.path.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise HeadSocketError(f"cannot inspect existing head socket path: {exc}") from exc

        if not stat.S_ISSOCK(socket_stat.st_mode):
            raise HeadSocketError("refusing to replace a non-socket head path")
        if socket_stat.st_uid != os.getuid():
            raise HeadSocketError("refusing to replace a head socket owned by another user")
        try:
            self.path.unlink()
        except OSError as exc:
            raise HeadSocketError(f"cannot remove stale head socket: {exc}") from exc
