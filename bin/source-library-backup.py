#!/usr/bin/env python3
"""Back up, verify, or safely restore one Source Library mode store."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from config_loader import load_config  # noqa: E402
from source_library import LibraryError, SourceLibrary  # noqa: E402
from source_library_archive import backup_database, restore_database, verify_database  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "verify", "restore"))
    parser.add_argument("--mode", choices=("cloud", "local"))
    parser.add_argument("--output", type=Path, help="New backup path for the backup action")
    parser.add_argument("--input", type=Path, help="Backup path for verify or restore")
    parser.add_argument("--apply", action="store_true", help="Actually restore after preflight")
    args = parser.parse_args()
    try:
        if args.action == "verify":
            if args.input is None:
                parser.error("verify requires --input")
            result = verify_database(args.input)
        else:
            if args.mode is None:
                parser.error(f"{args.action} requires --mode")
            load_config(args.mode)
            library = SourceLibrary(args.mode)
            if args.action == "backup":
                if args.output is None:
                    parser.error("backup requires --output")
                result = backup_database(library, args.output)
            else:
                if args.input is None:
                    parser.error("restore requires --input")
                result = restore_database(library, args.input, apply=args.apply)
        print(json.dumps(result, indent=2))
    except (LibraryError, OSError) as exc:
        parser.exit(1, f"Source Library: {exc}\n")


if __name__ == "__main__":
    main()
