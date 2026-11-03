"""Optional standalone workflow authoring service."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT, ROOT / 'lib'):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
