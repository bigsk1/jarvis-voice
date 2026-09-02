"""Linux framebuffer, console graphics mode, and raw keyboard for the kiosk.

The framebuffer renderer draws straight into ``/dev/fb0`` while fbcon is told to
stop painting the VT (``KD_GRAPHICS``). Everything here restores what it changed:
console mode, terminal attributes, and a black framebuffer on exit.
"""

from __future__ import annotations

import fcntl
import mmap
import os
import re
import select
import struct
import sys
import syslog
import termios
import tty
from dataclasses import dataclass

import numpy as np
from display_errors import DisplaySetupError

FBIOGET_VSCREENINFO = 0x4600
FBIOGET_FSCREENINFO = 0x4602
KDGETMODE = 0x4B3B
KDSETMODE = 0x4B3A
KD_TEXT = 0
KD_GRAPHICS = 1
VAR_SCREENINFO_SIZE = 160
FIX_SCREENINFO_SIZE = 128
_VAR_PREFIX = struct.Struct("20I")
_FIX_PREFIX = struct.Struct("@16sLIIIIHHHxxI")
_VT_NAME = re.compile(r"^/dev/tty[0-9]+$")
QUIT_KEYS = (b"q", b"Q", b"\x1b")


class FramebufferError(DisplaySetupError):
    """The framebuffer cannot be used; the message is operator-facing."""


@dataclass(frozen=True, slots=True)
class ChannelLayout:
    """One ``fb_bitfield``: where a color channel lives inside a pixel."""

    offset: int
    length: int
    msb_right: int


@dataclass(frozen=True, slots=True)
class FramebufferInfo:
    width: int
    height: int
    virtual_width: int
    virtual_height: int
    x_offset: int
    y_offset: int
    stride: int
    bits_per_pixel: int
    red: ChannelLayout
    green: ChannelLayout
    blue: ChannelLayout
    memory_length: int

    @property
    def red_offset(self) -> int:
        return self.red.offset

    @property
    def green_offset(self) -> int:
        return self.green.offset

    @property
    def blue_offset(self) -> int:
        return self.blue.offset

    @property
    def mapped_length(self) -> int:
        """Bytes the renderer maps: the visible page from byte zero."""

        return self.stride * self.height

    def validate(self) -> None:
        """Fail closed on any layout the compositor does not literally handle.

        The compositor packs 8-bit channels at fixed bit offsets and writes the
        visible page from byte zero, so anything else (16 bpp, 10-bit channels,
        reversed bit order, a panned or double-buffered visible page, a mapping
        larger than the device memory) would draw wrong colors or the wrong page.
        """

        if self.width < 1 or self.height < 1:
            raise FramebufferError("framebuffer reports an empty resolution")
        if self.bits_per_pixel != 32:
            raise FramebufferError(
                f"only 32 bits per pixel is supported (device reports {self.bits_per_pixel})"
            )
        if self.stride % 4 or self.stride < self.width * 4:
            raise FramebufferError(f"unexpected framebuffer stride {self.stride}")
        channels = (self.red, self.green, self.blue)
        offsets = [channel.offset for channel in channels]
        if (
            any(channel.length != 8 for channel in channels)
            or any(channel.msb_right != 0 for channel in channels)
            or set(offsets) - {0, 8, 16}
            or len(set(offsets)) != 3
        ):
            raise FramebufferError(
                "framebuffer channels must be three distinct 8-bit fields at "
                "bit offsets 0/8/16 (device reports "
                f"r{self.red.offset}/{self.red.length} g{self.green.offset}/{self.green.length} "
                f"b{self.blue.offset}/{self.blue.length})"
            )
        if self.x_offset or self.y_offset:
            raise FramebufferError(
                f"framebuffer visible page is panned to ({self.x_offset}, {self.y_offset}); "
                "only an unpanned page is supported"
            )
        if self.virtual_width < self.width or self.virtual_height < self.height:
            raise FramebufferError("framebuffer virtual size is smaller than its resolution")
        if self.mapped_length > self.memory_length:
            raise FramebufferError(
                f"framebuffer memory ({self.memory_length} bytes) is smaller than the "
                f"visible page ({self.mapped_length} bytes)"
            )


def parse_var_screeninfo(buffer: bytes) -> dict[str, object]:
    """Return the ``fb_var_screeninfo`` fields the renderer validates against."""

    if len(buffer) < _VAR_PREFIX.size:
        raise FramebufferError("short fb_var_screeninfo")
    fields = _VAR_PREFIX.unpack_from(buffer)
    xres, yres, xres_virtual, yres_virtual, x_offset, y_offset, bpp, _gray = fields[:8]
    return {
        "width": xres,
        "height": yres,
        "virtual_width": xres_virtual,
        "virtual_height": yres_virtual,
        "x_offset": x_offset,
        "y_offset": y_offset,
        "bits_per_pixel": bpp,
        "red": ChannelLayout(*fields[8:11]),
        "green": ChannelLayout(*fields[11:14]),
        "blue": ChannelLayout(*fields[14:17]),
    }


def parse_fix_screeninfo(buffer: bytes) -> tuple[int, int]:
    """Return ``(line_length, smem_len)`` from ``fb_fix_screeninfo``."""

    if len(buffer) < _FIX_PREFIX.size:
        raise FramebufferError("short fb_fix_screeninfo")
    fields = _FIX_PREFIX.unpack_from(buffer)
    return fields[-1], fields[2]


def framebuffer_info_from_structs(var: bytes, fix: bytes) -> FramebufferInfo:
    """Build and validate the device description from the two raw ioctl structs."""

    stride, memory_length = parse_fix_screeninfo(fix)
    info = FramebufferInfo(
        stride=stride,
        memory_length=memory_length,
        **parse_var_screeninfo(var),  # type: ignore[arg-type]
    )
    info.validate()
    return info


def read_framebuffer_info(fd: int) -> FramebufferInfo:
    var = bytearray(VAR_SCREENINFO_SIZE)
    fix = bytearray(FIX_SCREENINFO_SIZE)
    try:
        fcntl.ioctl(fd, FBIOGET_VSCREENINFO, var)
        fcntl.ioctl(fd, FBIOGET_FSCREENINFO, fix)
    except OSError as exc:
        raise FramebufferError(f"framebuffer ioctl failed: {exc}") from exc
    return framebuffer_info_from_structs(bytes(var), bytes(fix))


class Framebuffer:
    """A memory-mapped 32bpp framebuffer exposed as a ``uint32`` row/column view."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = os.fspath(path)
        try:
            self.fd = os.open(self.path, os.O_RDWR)
        except PermissionError as exc:
            raise FramebufferError(
                f"cannot open {self.path}: permission denied; "
                "add the kiosk user to the 'video' group and log in again"
            ) from exc
        except FileNotFoundError as exc:
            raise FramebufferError(f"framebuffer device not found: {self.path}") from exc
        except OSError as exc:
            raise FramebufferError(f"cannot open {self.path}: {exc}") from exc
        try:
            self.info = read_framebuffer_info(self.fd)
            self._map = mmap.mmap(
                self.fd, self.info.mapped_length, mmap.MAP_SHARED, mmap.PROT_WRITE
            )
        except Exception:
            os.close(self.fd)
            raise
        self.view = np.ndarray(
            (self.info.height, self.info.stride // 4),
            dtype=np.uint32,
            buffer=self._map,
        )

    @property
    def width(self) -> int:
        return self.info.width

    @property
    def height(self) -> int:
        return self.info.height

    def present(self, frame: np.ndarray, *, x: int = 0, y: int = 0) -> None:
        """Copy a packed ``uint32`` frame into the device at ``(x, y)``."""

        rows, cols = frame.shape
        if x < 0 or y < 0 or x + cols > self.width or y + rows > self.height:
            raise ValueError("frame does not fit inside the framebuffer")
        self.view[y : y + rows, x : x + cols] = frame

    def clear(self) -> None:
        self.view[:, : self.width] = 0

    def close(self) -> None:
        try:
            self._map.close()
        finally:
            os.close(self.fd)


def controlling_console() -> str | None:
    """Return ``/dev/ttyN`` if stdin is a Linux virtual console, else ``None``."""

    try:
        name = os.ttyname(sys.stdin.fileno())
    except (OSError, ValueError, AttributeError):
        return None
    return name if _VT_NAME.match(name) else None


class ConsoleGraphicsMode:
    """Switch the VT to ``KD_GRAPHICS`` so fbcon stops drawing over us.

    The ioctl goes through an already-open VT descriptor (normally stdin). Under
    ``openvt … setpriv`` the display user inherits the VT as fds 0-2 but may not
    be allowed to reopen ``/dev/ttyN`` by path, so reopening is never attempted.
    """

    def __init__(self, fd: int, *, console_path: str = "the console") -> None:
        self.fd = fd
        self.console_path = console_path
        self._previous: int | None = None

    def __enter__(self) -> ConsoleGraphicsMode:
        try:
            mode = bytearray(4)
            fcntl.ioctl(self.fd, KDGETMODE, mode)
            previous = struct.unpack("i", mode)[0]
            fcntl.ioctl(self.fd, KDSETMODE, KD_GRAPHICS)
        except OSError as exc:
            raise FramebufferError(
                f"cannot switch {self.console_path} to graphics mode: {exc}"
            ) from exc
        self._previous = previous
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._previous is None:
            return
        try:
            fcntl.ioctl(self.fd, KDSETMODE, self._previous)
        except OSError as exc:
            # Nothing more can be done from here, but a stranded black VT must
            # not look like a clean exit: say so where an operator will look.
            # stderr is the VT itself under the kiosk, so also hit the journal.
            report_restore_failure(f"could not restore {self.console_path} text mode: {exc}")
        finally:
            self._previous = None


def report_restore_failure(message: str) -> None:
    """Log a permanent console-restore failure to stderr and the system journal."""

    print(f"jarvis-head: {message}", file=sys.stderr, flush=True)
    try:
        syslog.syslog(syslog.LOG_WARNING, f"jarvis-head: {message}")
    except OSError:  # pragma: no cover - no /dev/log on this host
        pass


class RawKeyboard:
    """Nonblocking quit-key detection on stdin with terminal attributes restored."""

    def __init__(self) -> None:
        self._fd = sys.stdin.fileno()
        self._saved: list[object] | None = None

    def __enter__(self) -> RawKeyboard:
        try:
            self._saved = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        except termios.error:
            self._saved = None
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._saved is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
            self._saved = None

    def quit_requested(self) -> bool:
        if self._saved is None:
            return False
        ready, _, _ = select.select([self._fd], [], [], 0)
        if not ready:
            return False
        try:
            data = os.read(self._fd, 64)
        except OSError:
            return False
        return any(key in data for key in QUIT_KEYS)
