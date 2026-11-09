"""Generate validated, atomically published posters for the shared video cache."""

import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image


class VideoThumbnailError(RuntimeError):
    """The encoder failed or did not produce a decodable JPEG."""


def _is_valid_jpeg(path: Path) -> bool:
    """Check complete markers and decode the small first-frame poster."""
    try:
        with path.open("rb") as stream:
            if stream.read(2) != b"\xff\xd8":
                return False
            stream.seek(-2, os.SEEK_END)
            if stream.read(2) != b"\xff\xd9":
                return False
            stream.seek(0)
            with Image.open(stream) as image:
                if image.format != "JPEG":
                    return False
                image.load()
        return True
    except (OSError, ValueError, Image.DecompressionBombError):
        return False


def get_video_thumbnail(
    video_path: Path, thumbnail_path: Path, *, timeout: float = 10
) -> Path:
    """Reuse a fresh JPEG or publish a complete new first frame.

    Each attempt owns a distinct file beside the final cache entry. Failed
    attempts clean up only that file, preserving older posters and concurrent
    successful writers. Both HTTP services share this publication boundary.
    """
    if (
        thumbnail_path.is_file()
        and thumbnail_path.stat().st_mtime >= video_path.stat().st_mtime
        and _is_valid_jpeg(thumbnail_path)
    ):
        return thumbnail_path

    thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{thumbnail_path.stem}.", suffix=".jpg", dir=thumbnail_path.parent
    )
    temporary_path = Path(temporary_name)
    os.close(descriptor)
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-vframes", "1",
                "-vf", "scale=480:-1",
                "-q:v", "3",
                str(temporary_path),
            ],
            capture_output=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            error = result.stderr.decode(errors="replace")[:200] if result.stderr else "unknown ffmpeg error"
            raise VideoThumbnailError(error)
        if not _is_valid_jpeg(temporary_path):
            raise VideoThumbnailError("ffmpeg did not produce a valid JPEG")
        temporary_path.replace(thumbnail_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return thumbnail_path
