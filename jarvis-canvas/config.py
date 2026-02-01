"""
Jarvis Canvas Configuration
"""
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
CANVAS_DIR = PROJECT_ROOT / "data" / "canvas"
STATIC_DIR = PROJECT_ROOT / "docs" / "images"
STASH_DIR = PROJECT_ROOT / "data" / "stash"
GENERATED_IMAGES_DIR = PROJECT_ROOT / "data" / "generated_images"
GENERATED_VIDEOS_DIR = PROJECT_ROOT / "data" / "generated_videos"

# Ensure directories exist
CANVAS_DIR.mkdir(parents=True, exist_ok=True)
GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
GENERATED_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

# Server settings
DEFAULT_PORT = 8890
DEFAULT_HOST = "0.0.0.0"
