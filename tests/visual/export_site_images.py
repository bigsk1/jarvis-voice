#!/usr/bin/env python3
"""Export the approved UI captures as optimized GitHub Pages screenshots."""

import argparse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    'jarvis-web-ui.png': 'jarvis-web.webp',
    'jarvis-canvas-ui.png': 'jarvis-canvas.webp',
    'jarvis-memory-ui.png': 'memory-browser.webp',
    'jarvis-intelligence-ui.png': 'jarvis-intelligence.webp',
    'jarvis-logs-viewer.png': 'jarvis-logs.webp',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'site/images')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for source, name in SOURCES.items():
        with Image.open(ROOT / 'docs/images' / source) as image:
            image = image.convert('RGB')
            image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            image.save(args.output / name, format='WEBP', quality=84, method=6)
        print(args.output / name)


if __name__ == '__main__':
    main()
