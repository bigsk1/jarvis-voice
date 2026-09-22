"""Dry-run audio cleanup must account for every file it does not preview."""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "cleanup-audio"


@pytest.mark.parametrize(
    ("wav_count", "local_log_count", "cloud_log_count", "preview_count"),
    [(3, 0, 0, 3), (60, 0, 0, 11), (0, 2, 1, 0)],
)
def test_dry_run_remainder_matches_unlisted_files(
    tmp_path, wav_count, local_log_count, cloud_log_count, preview_count
):
    script = tmp_path / "bin" / "cleanup-audio"
    script.parent.mkdir()
    shutil.copyfile(SCRIPT, script)
    old_mtime = time.time() - 45 * 86400
    files = []
    for directory, count, suffix in (
        (tmp_path / "audio/cloud/recordings", wav_count, ".wav"),
        (tmp_path / "audio/local/logs", local_log_count, ".txt"),
        (tmp_path / "audio/cloud/qa", cloud_log_count, ".txt"),
    ):
        directory.mkdir(parents=True, exist_ok=True)
        for index in range(count):
            path = directory / f"old_{index}{suffix}"
            path.write_bytes(b"x")
            os.utime(path, (old_mtime, old_mtime))
            files.append(path)

    completed = subprocess.run(
        ["bash", str(script), "--days", "30", "--dry-run"],
        capture_output=True,
        text=True,
        check=True,
    )

    previewed = completed.stdout.count("Would delete:")
    remainder = re.search(
        r"\.\.\. (?:and )?(-?\d+) (?:more files|files not shown individually)",
        completed.stdout,
    )
    unlisted = int(remainder.group(1)) if remainder else 0
    total = len(files)
    assert previewed == preview_count
    assert f"Would delete {total} files" in completed.stdout
    assert unlisted >= 0
    assert previewed + unlisted == total
    assert all(path.exists() for path in files)
