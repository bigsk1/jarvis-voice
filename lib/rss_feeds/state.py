"""Bounded transactional publication receipts, not an HTTP response cache."""

from __future__ import annotations

import json
import math
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

from . import RSSFeedError
from .config import profile_id

BATCH_TTL = 2 * 60 * 60
SEEN_TTL = 90 * 24 * 60 * 60
MAX_STATE_BYTES = 4_000_000
MAX_PENDING_BATCHES = 20
MAX_ACKNOWLEDGED_BATCHES = 5


class FeedState:
    def __init__(self, root: Path, profile: str):
        # Feeds and Canvas pages are shared across modes. Publication receipts
        # share that identity so switching model modes cannot resend a story.
        self.directory = root
        self.path = self.directory / f"{profile_id(profile)}.json"

    @contextmanager
    def transaction(self, now: float):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with FileLock(str(self.path) + ".lock", timeout=5):
                state = self._read()
                state["seen"] = {
                    key: value for key, value in state["seen"].items()
                    if isinstance(value, (int, float)) and value > now - SEEN_TTL
                }
                state["batches"] = {
                    key: value for key, value in state["batches"].items()
                    if isinstance(value, dict) and value.get("created_at", 0) > now - BATCH_TTL
                }
                yield state
                self._write(state)
        except Timeout as exc:
            raise RSSFeedError("Another RSS operation is updating this profile; retry shortly.") from exc

    def _read(self) -> dict:
        if not self.path.exists():
            return {"v": 1, "seen": {}, "batches": {}, "recent": []}
        try:
            if self.path.stat().st_size > MAX_STATE_BYTES:
                raise ValueError("oversized")
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if (not isinstance(state, dict) or state.get("v") != 1
                    or not isinstance(state.get("seen"), dict)
                    or not isinstance(state.get("batches"), dict)
                    or not isinstance(state.get("recent"), list)):
                raise ValueError("invalid state")
            if any(type(value) not in (int, float) or not math.isfinite(value)
                   for value in state["seen"].values()):
                raise ValueError("invalid publication timestamp")
            for batch in state["batches"].values():
                if (not isinstance(batch, dict)
                        or type(batch.get("created_at")) not in (int, float)
                        or not math.isfinite(batch["created_at"])
                        or not isinstance(batch.get("items"), list)):
                    raise ValueError("invalid staged batch")
            return state
        except (OSError, ValueError, UnicodeError) as exc:
            raise RSSFeedError("RSS publication history could not be read; it was not reset.") from exc

    def _write(self, state: dict) -> None:
        batches = sorted(
            state["batches"].items(), key=lambda row: row[1]["created_at"], reverse=True,
        )
        pending = [row for row in batches if row[1].get("acknowledged") is not True]
        if len(pending) > MAX_PENDING_BATCHES:
            raise RSSFeedError(
                "Too many pending RSS batches (maximum 20). Finish a digest or wait "
                "for older batches to expire before reading again; existing history was kept."
            )
        acknowledged = [row for row in batches if row[1].get("acknowledged") is True][
            :MAX_ACKNOWLEDGED_BATCHES
        ]
        document = {
            **state,
            "seen": dict(sorted(state["seen"].items(), key=lambda row: row[1], reverse=True)[:5000]),
            "recent": state["recent"][-40:],
        }
        while True:
            document["batches"] = dict(pending + acknowledged)
            try:
                encoded = json.dumps(document, ensure_ascii=False, allow_nan=False).encode("utf-8")
            except (TypeError, ValueError, UnicodeError) as exc:
                raise RSSFeedError(
                    "RSS publication history could not be saved; existing history was kept."
                ) from exc
            if len(encoded) <= MAX_STATE_BYTES:
                break
            if not acknowledged:
                raise RSSFeedError(
                    "RSS publication history is full. Finish a digest or wait for pending "
                    "batches to expire before reading again; existing history was kept."
                )
            # Old completed receipts are disposable; pending reads and selected
            # digests must remain usable until transaction() expires their TTL.
            acknowledged.pop()
        descriptor, name = tempfile.mkstemp(dir=self.directory, prefix=".rss-")
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
