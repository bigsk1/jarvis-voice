#!/usr/bin/env python3
"""Supervised, optional ntfy worker; all remote I/O stays outside Jarvis Web."""

import argparse
import logging
import signal
import sys
import threading
from pathlib import Path

from filelock import FileLock, Timeout

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.config_loader import get_active_config_mode  # noqa: E402
from lib.ntfy_notifications import (  # noqa: E402
    NotificationWorker,
    load_config,
    write_worker_status,
)

LOCK_RETRY_SECONDS = 15


def acquire_delivery_lock(lock: FileLock, stop: threading.Event, *, once: bool) -> bool:
    """Keep a competing daemon alive without scanning or publishing events."""
    waiting = False
    while not stop.is_set():
        try:
            lock.acquire(timeout=0)
        except Timeout:
            if once:
                raise
            if not waiting:
                logging.warning("Another ntfy worker owns the delivery lock; waiting")
                waiting = True
            # SIGTERM/SIGINT interrupts this wait, including before it begins.
            stop.wait(LOCK_RETRY_SECONDS)
        else:
            if waiting:
                logging.info("ntfy delivery lock acquired; resuming worker")
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Scan/deliver once and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    (PROJECT_ROOT / "data").mkdir(parents=True, exist_ok=True)
    # Shared across native/Docker and modes: only one process may publish at once.
    lock = FileLock(PROJECT_ROOT / "data" / "ntfy_notifications.db.lock", mode=0o600)
    try:
        if not acquire_delivery_lock(lock, stop, once=args.once):
            return 0
        worker = None
        interval = 15
        try:
            worker = NotificationWorker(PROJECT_ROOT, get_active_config_mode())
            logging.info("ntfy worker started (%s); phone delivery requires private config", worker.mode)
            previous_errors = None
            interval = 15
            while not stop.is_set():
                interval = 15
                enabled = False
                try:
                    config = load_config(PROJECT_ROOT / "config" / "ntfy.json")
                    interval = config["poll_seconds"]
                    enabled = config["enabled"]
                    try:
                        write_worker_status(PROJECT_ROOT, worker.mode, "checking", interval)
                    except OSError:
                        pass  # Diagnostics must not prevent notification delivery.
                    stats = worker.cycle(config)
                    if stats["delivered"] or stats["suppressed"]:
                        logging.info("ntfy delivered=%s suppressed=%s", stats["delivered"], stats["suppressed"])
                    errors = tuple(sorted(set(stats["errors"])))
                except Exception as exc:
                    # Never print exception messages: malformed config can contain secrets.
                    errors = (f"ntfy worker {type(exc).__name__}",)
                try:
                    write_worker_status(PROJECT_ROOT, worker.mode,
                                        "degraded" if errors else "ready" if enabled else "disabled",
                                        interval)
                except OSError:
                    errors = (*errors, "ntfy heartbeat unavailable")
                if errors != previous_errors:
                    if errors:
                        logging.warning("; ".join(errors))
                    elif previous_errors:
                        logging.info("ntfy delivery checks recovered")
                    previous_errors = errors
                if args.once:
                    return 1 if errors else 0
                stop.wait(interval)
        finally:
            try:
                if worker is not None:
                    write_worker_status(PROJECT_ROOT, worker.mode, "stopped", interval)
            except OSError:
                pass
            lock.release()
    except Timeout:
        logging.warning("Another ntfy worker owns the delivery lock")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
