#!/usr/bin/env python3
"""Jarvis foreground tool for durable watch baselines and delivery evidence."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.config_loader import get_active_config_mode, load_config
from lib.paths import get_project_root
from lib.watch_state.service import dispatch


def main() -> int:
    from lib.watch_state import (
        AuthorityError,
        ConflictError,
        NotFoundError,
        StorageError,
        authority_from_environment,
    )

    try:
        load_config()
        arguments = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        result = dispatch(
            arguments,
            project_root=get_project_root(),
            mode=get_active_config_mode(),
            authority=authority_from_environment(),
        )
    except AuthorityError as exc:
        result = {"ok": False, "speech": str(exc), "error": "watch_owner_required"}
    except NotFoundError as exc:
        result = {"ok": False, "speech": str(exc), "error": "watch_not_found"}
    except ConflictError as exc:
        result = {"ok": False, "speech": str(exc), "error": "watch_conflict"}
    except (StorageError, OSError, sqlite3.Error):
        result = {
            "ok": False,
            "speech": "Watch state storage is unavailable.",
            "error": "storage_unavailable",
        }
    except json.JSONDecodeError:
        result = {
            "ok": False,
            "speech": "Watch state input must be valid JSON.",
            "error": "invalid_watch_request",
        }
    except ValueError as exc:
        result = {"ok": False, "speech": str(exc), "error": "invalid_watch_request"}
    except (TypeError, RecursionError):
        result = {
            "ok": False,
            "speech": "Watch state request failed validation or authorization.",
            "error": "invalid_watch_request",
        }
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
