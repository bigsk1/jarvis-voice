#!/usr/bin/env python3
"""Temp-file cleanup coverage for Cloudflare image upload helpers."""

from __future__ import annotations

import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import upload_cloudflare


class _DroppingImageResponse:
    headers = {"content-type": "image/png"}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=8192):
        yield b"partial image bytes"
        raise RuntimeError("simulated dropped stream")


class _FailingWriteFile:
    def __init__(self, fd: int):
        self.fd = fd

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        os.close(self.fd)
        return False

    def write(self, data):
        raise OSError("simulated write failure")


class UploadCloudflareTempCleanupTests(unittest.TestCase):
    def _mkstemp_in(self, directory: Path):
        original_mkstemp = tempfile.mkstemp

        def mkstemp(*args, **kwargs):
            kwargs["dir"] = str(directory)
            return original_mkstemp(*args, **kwargs)

        return mkstemp

    def test_download_from_url_removes_partial_temp_file_on_stream_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir = Path(tmpdir)

            with patch.object(upload_cloudflare.tempfile, "mkstemp", side_effect=self._mkstemp_in(temp_dir)):
                with patch.object(upload_cloudflare.requests, "get", return_value=_DroppingImageResponse()):
                    result = upload_cloudflare.download_from_url("https://example.test/image.png")

            self.assertIsNone(result)
            self.assertEqual([], list(temp_dir.iterdir()))

    def test_decode_base64_removes_temp_file_on_write_failure(self):
        encoded = base64.b64encode(b"fake image bytes").decode("ascii")

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir = Path(tmpdir)

            with patch.object(upload_cloudflare.tempfile, "mkstemp", side_effect=self._mkstemp_in(temp_dir)):
                with patch.object(upload_cloudflare.os, "fdopen", side_effect=lambda fd, mode: _FailingWriteFile(fd)):
                    result = upload_cloudflare.decode_base64_to_file(encoded)

            self.assertIsNone(result)
            self.assertEqual([], list(temp_dir.iterdir()))


if __name__ == "__main__":
    unittest.main()
