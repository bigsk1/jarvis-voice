#!/usr/bin/env python3
"""Save and retrieve complete personal sources, independently of Stash retention."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from filelock import Timeout

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from config_loader import load_config
from paths import resolve_local_file_tool_path
from source_library import MAX_SOURCE_BYTES, LibraryError, SourceLibrary
from stash_helper import get_stash_dir, safe_resolve_file


def execute(args):
    library = SourceLibrary()
    action = args.get("action", "search")
    source_id = args.get("source_id")
    if action == "save":
        source = args.get("source")
        if not isinstance(source, str) or not source.strip():
            raise LibraryError("Provide the source file path or exact stash:// reference.")
        if source.startswith("stash://"):
            resolved = safe_resolve_file(stash_ref=source)
            if not resolved["found"]:
                raise LibraryError("The Stash source is unavailable. Upload or save it again.")
            path = Path(resolved["path"])
            root = get_stash_dir().resolve()
            if (
                path.is_symlink()
                or path.parent.is_symlink()
                or not path.resolve().is_relative_to(root)
            ):
                raise LibraryError("The Stash source must remain inside the configured Stash.")
        else:
            path = resolve_local_file_tool_path(source, include_pictures=False)
        with path.open("rb") as stream:
            payload = stream.read(MAX_SOURCE_BYTES + 1)
        saved = library.save(
            payload,
            path.name,
            title=args.get("title"),
            origin=source if source.startswith("stash://") else "local file",
        )
        remaining = saved["passage_count"] - saved["indexed_passages"]
        data = {"source": saved, "duplicate": saved["duplicate"], "remaining": remaining}
        speech = f"{'Already saved' if saved['duplicate'] else 'Saved'} {saved['title']} in your {library.mode} source library."
        if remaining:
            speech += " Keyword search is ready; meaning indexing is queued for the Web library worker."
    elif action == "search":
        data = library.search(
            args.get("query"),
            source_id=source_id,
            limit=args.get("limit", 6),
            semantic=args.get("semantic", True),
        )
        speech = f"Found {len(data['passages'])} source passages ({data['retrieval_mode']})."
    elif action == "read":
        data = library.read(source_id, passage=args.get("passage", 1), limit=args.get("limit", 3))
        speech = f"Retrieved {len(data['passages'])} passages from {data['source']['title']}."
    elif action == "list":
        data = library.list(offset=args.get("offset", 0), limit=args.get("limit", 8))
        speech = f"Your {library.mode} source library contains {data['total']} sources."
    elif action == "index":
        library.read(source_id, limit=1)
        try:
            with library.locked_index():
                data = library.index(source_id)
        except Timeout as exc:
            raise LibraryError("This library is already indexing. Try again shortly.") from exc
        speech = (
            "Semantic indexing is complete."
            if not data["remaining"]
            else f"{data['remaining']} passages remain to index."
        )
    elif action == "remove":
        data = library.remove(source_id)
        speech = "Removed that source and its passages from this library."
    elif action == "rename":
        source = library.rename(source_id, args.get("title"))
        data = {"source": source}
        speech = f"Renamed the saved source to {source['title']}. Its original and citations are unchanged."
    else:
        raise LibraryError("Choose save, search, read, list, index, rename, or remove.")
    return {"ok": True, "speech": speech, "data": {"action": action, **data}}


def main():
    load_config()
    try:
        args = json.loads(sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read() or "{}")
        if not isinstance(args, dict):
            raise LibraryError("Tool arguments must be an object.")
        result = execute(args)
    except (ValueError, OSError, sqlite3.Error) as exc:
        result = {"ok": False, "speech": str(exc), "error": str(exc)}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
