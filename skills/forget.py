#!/usr/bin/env python3
"""
Forget Tool - Delete memories by ID or search query
"""
import sys
import json
import os

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib'))
from memory_db import get_memory_db

MAX_FORGET_IDS = 10


def _normalize_memory_ids(args: dict) -> list[int]:
    """Accept either memory_id or memory_ids and return a deduplicated list."""
    raw_ids = []

    if args.get("memory_id") is not None:
        raw_ids.append(args.get("memory_id"))

    raw_ids.extend(args.get("memory_ids") or [])

    normalized = []
    seen = set()
    for raw_id in raw_ids:
        try:
            memory_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if memory_id not in seen:
            seen.add(memory_id)
            normalized.append(memory_id)

    return normalized[:MAX_FORGET_IDS]


def main():
    """Delete a memory from database by ID or search query."""
    try:
        # Read arguments
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}

        requested_memory_ids = _normalize_memory_ids(args)
        memory_ids = requested_memory_ids
        search_query = args.get('search_query')

        db = get_memory_db()

        # If no memory IDs, try to find one by search_query
        if not memory_ids and search_query:
            # Search for matching memories
            memories = db.search_memory(query=search_query, limit=5)

            if not memories:
                result = {
                    "ok": False,
                    "speech": f"I couldn't find any memories matching '{search_query}'",
                    "error": "No matching memories found"
                }
                print(json.dumps(result))
                db.close()
                return result

            # Take the best match (first result)
            best_match = memories[0]
            if best_match.get('id') is not None:
                memory_ids = [int(best_match['id'])]

        if not memory_ids:
            result = {
                "ok": False,
                "speech": "I need either a memory ID, memory IDs, or search keywords to forget something",
                "error": "Missing memory_id, memory_ids, or search_query parameter"
            }
            print(json.dumps(result))
            db.close()
            return result

        raw_memory_ids = []
        if args.get("memory_id") is not None:
            raw_memory_ids.append(args.get("memory_id"))
        raw_memory_ids.extend(args.get("memory_ids") or [])
        requested_count = len({str(item) for item in raw_memory_ids if item is not None})
        was_capped = requested_count > MAX_FORGET_IDS and bool(raw_memory_ids)

        memory_by_id = {
            memory.get("id"): memory
            for memory in db.get_all_memories()
            if memory.get("id") is not None
        }

        deleted = []
        missing = []

        for memory_id in memory_ids:
            memory_info = memory_by_id.get(memory_id)
            success = db.forget(memory_id=memory_id)
            if success:
                deleted_entry = {"id": memory_id}
                if memory_info:
                    deleted_entry["key"] = memory_info.get("key", "that memory")
                deleted.append(deleted_entry)
            else:
                missing.append(memory_id)

        db.close()

        if deleted:
            deleted_ids = [entry["id"] for entry in deleted]
            deleted_keys = [entry["key"] for entry in deleted if entry.get("key")]

            if len(deleted) == 1 and not missing:
                result = {
                    "ok": True,
                    "speech": f"I've forgotten about {deleted[0].get('key', 'that memory')}",
                    "data": {
                        "deleted_id": deleted[0]["id"],
                        "deleted_key": deleted[0].get("key"),
                        "deleted": deleted,
                        "deleted_ids": deleted_ids,
                        "deleted_keys": deleted_keys,
                    },
                }
            elif missing:
                result = {
                    "ok": True,
                    "speech": (
                        f"I forgot {len(deleted)} memorie{'s' if len(deleted) != 1 else ''}, "
                        f"but I couldn't find ID{'s' if len(missing) != 1 else ''} "
                        f"{', '.join(str(mid) for mid in missing)}"
                    ),
                    "data": {
                        "deleted": deleted,
                        "deleted_ids": deleted_ids,
                        "deleted_keys": deleted_keys,
                        "missing_ids": missing,
                    },
                }
            else:
                result = {
                    "ok": True,
                    "speech": f"I've forgotten {len(deleted)} memories",
                    "data": {
                        "deleted": deleted,
                        "deleted_ids": deleted_ids,
                        "deleted_keys": deleted_keys,
                    },
                }
        else:
            result = {
                "ok": False,
                "speech": (
                    "I couldn't find "
                    + (
                        f"a memory with ID {missing[0]}"
                        if len(missing) == 1
                        else f"those memory IDs: {', '.join(str(mid) for mid in missing)}"
                    )
                ),
                "error": "Memory not found"
            }

        if was_capped:
            suffix = f" I only processed the first {MAX_FORGET_IDS} memory IDs for safety."
            result["speech"] = (result.get("speech") or "").rstrip() + suffix
            if isinstance(result.get("data"), dict):
                result["data"]["capped_at"] = MAX_FORGET_IDS
                result["data"]["requested_id_count"] = requested_count

        print(json.dumps(result))
        return result

    except Exception as e:
        error_result = {
            "ok": False,
            "speech": f"Failed to forget memory: {str(e)}",
            "error": str(e)
        }
        print(json.dumps(error_result))
        return error_result


if __name__ == "__main__":
    main()
