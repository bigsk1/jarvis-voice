#!/usr/bin/env python3
"""Optional Craft Gateway tool; shared transport and delivery live in lib."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from craft_tools import main

if __name__ == "__main__":
    raise SystemExit(main('craft_video'))
