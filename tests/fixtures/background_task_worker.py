"""Inert file-producing fixture. No manifest, remote service, or production registration.

Run this file only against disposable storage, never through Jarvis tool discovery.
The output root comes from the harness, not stored task arguments.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib import config_loader
from lib.background_tasks import TaskStore
from lib.background_tasks.worker import TaskWorker


def fixture_adapter(output_root: Path):
    def execute(context):
        job_id = context.claim.job_id
        # Exclusive create is also the fixture's evidence against a second dispatch.
        started = output_root / f"{job_id}.started"
        with started.open("x") as stream:
            json.dump({"mode": config_loader.get_active_config_mode()}, stream)
        context.progress({"phase": "waiting", "value": 0})
        while not (output_root / "finish").exists():
            context.checkpoint()
            time.sleep(0.02)
        context.progress({"phase": "finished", "value": 100})
        artifact = output_root / f"{job_id}.txt"
        artifact.write_text("fixture completed\n")
        return {"summary": "Fixture completed", "artifact": str(artifact)}

    return execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config-root", type=Path, required=True)
    parser.add_argument("--lease", type=float, default=30)
    parser.add_argument("--heartbeat", type=float, default=5)
    args = parser.parse_args()
    # Explicit empty/disposable mode files keep the harness off live credentials.
    config_loader.get_project_root = lambda: args.config_root.resolve()
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    TaskWorker(
        TaskStore(args.db),
        {"local_fixture": fixture_adapter(args.root)},
        lease_seconds=args.lease,
        heartbeat_seconds=args.heartbeat,
        poll_seconds=0.05,
    ).run_forever(stop)


if __name__ == "__main__":
    main()
