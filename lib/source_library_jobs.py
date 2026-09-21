"""Library-owned, durable semantic indexing independent of browser and chat runs."""

from __future__ import annotations

import logging
import threading
from contextlib import ExitStack

from config_loader import config_scope
from filelock import Timeout
from source_library import LibraryError, SourceLibrary

logger = logging.getLogger(__name__)


class LibraryIndexWorker:
    """Drain mode-scoped index jobs one committed batch at a time.

    A process lock per library ensures that Web and standalone workers do not
    work on the same source concurrently. Pending jobs live in the source
    database and are picked up again when the worker restarts.
    """

    def __init__(self):
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run_forever, name="library-index", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)

    def run_forever(self, *, external=False):
        """Drain durable work until stopped, with per-mode external leases."""
        with ExitStack() as leases:
            modes = []
            for mode in ("local", "cloud"):
                if not external:
                    modes.append(mode)
                    continue
                lease = ExitStack()
                try:
                    with config_scope(mode):
                        library = SourceLibrary(mode)
                        library.ensure_inbox()
                        lease.enter_context(library.worker_lease())
                except Exception as exc:
                    lease.close()
                    logger.error("Library worker lease failed mode=%s error_type=%s", mode, type(exc).__name__)
                    continue
                leases.enter_context(lease)
                modes.append(mode)
            if external and not modes:
                raise RuntimeError("No Source Library mode is available to the standalone worker.")
            self._run_modes(modes)

    def _run_modes(self, modes):
        while not self.stop_event.is_set():
            did_work = False
            for mode in modes:
                if self.stop_event.is_set():
                    break
                try:
                    did_work = self.poll_once(mode) or did_work
                except Exception as exc:
                    logger.warning("Library indexing failed mode=%s error_type=%s", mode, type(exc).__name__)
            self.stop_event.wait(0.1 if did_work else 2.0)

    def poll_once(self, mode):
        """Process at most one batch, useful for deterministic isolated tests."""
        with config_scope(mode):
            library = SourceLibrary(mode)
            library.ensure_inbox()
            if not library.store_exists():
                return False
            try:
                with library.locked_index():
                    import_job = library.next_import_job()
                    if import_job is not None:
                        result = library.import_queued_file(import_job)
                        if result["error"]:
                            logger.warning("Library inbox import failed mode=%s; inspect import jobs in the authenticated library UI", mode)
                        return True
                    source_id = library.next_index_job()
                    if source_id is None:
                        return False
                    try:
                        before = library.read(source_id, limit=1)["source"]
                        result = library.index(
                            source_id,
                            cancel_check=self.stop_event.is_set,
                        )
                        current = library.read(source_id, limit=1)["source"]
                        if current["title"] != before["title"]:
                            return True  # Rename already queued fresh title embeddings.
                        library.record_index_progress(
                            source_id,
                            remaining=result["remaining"],
                            error=result.get("index_error"),
                            expected_title=before["title"],
                        )
                    except LibraryError as exc:
                        if self.stop_event.is_set():
                            return False
                        try:
                            current = library.read(source_id, limit=1)["source"]
                        except LibraryError:
                            return True  # Source was removed during the batch.
                        if "before" in locals() and current["title"] != before["title"]:
                            return True
                        library.record_index_progress(
                            source_id,
                            remaining=current["passage_count"] - current["indexed_passages"],
                            error=str(exc),
                            expected_title=before["title"] if "before" in locals() else None,
                        )
                    return True
            except Timeout:
                return False
