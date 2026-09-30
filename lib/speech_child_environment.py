"""Reviewed environment for Web speech conversion and local transcription.

These launches bypass ToolExecutor, so apply its restricted policy explicitly.
Model caches keep their existing location, while HOME is private scratch space.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from tool_child_environment import restrict_child_environment


_MEDIA_ENV = frozenset({"LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"})
_TRANSCRIPTION_ENV = _MEDIA_ENV | frozenset({
    "STT_DEVICE", "STT_COMPUTE_TYPE", "STT_TIMEOUT_SECONDS",
    "HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "XDG_CACHE_HOME",
    "HF_HUB_OFFLINE", "HF_HUB_DISABLE_TELEMETRY",
    "CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER", "OMP_NUM_THREADS",
})


@contextmanager
def speech_child_environment(
    source: dict[str, str], *, transcription: bool = False
) -> Iterator[dict[str, str]]:
    """Exclude provider credentials and prevent reloading mode files in children."""
    source = dict(source)
    if transcription and "HF_HOME" not in source:
        original_home = source.get("HOME") or str(Path.home())
        cache = source.get("XDG_CACHE_HOME") or str(Path(original_home) / ".cache")
        source["HF_HOME"] = str(Path(cache) / "huggingface")
    with TemporaryDirectory(prefix="jarvis-speech-home-") as home:
        yield restrict_child_environment(
            source, _TRANSCRIPTION_ENV if transcription else _MEDIA_ENV,
            home=home,
        )
