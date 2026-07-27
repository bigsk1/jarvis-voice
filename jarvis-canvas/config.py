"""
Jarvis Canvas Configuration
"""
import sys
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from stash_helper import get_stash_dir

CANVAS_DIR = PROJECT_ROOT / "data" / "canvas"
STATIC_DIR = PROJECT_ROOT / "docs" / "images"
STASH_DIR = get_stash_dir()
GENERATED_IMAGES_DIR = PROJECT_ROOT / "data" / "generated_images"
GENERATED_VIDEOS_DIR = PROJECT_ROOT / "data" / "generated_videos"
GENERATED_AUDIO_DIR = PROJECT_ROOT / "data" / "generated_music"

# Ensure directories exist
CANVAS_DIR.mkdir(parents=True, exist_ok=True)
GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
GENERATED_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
GENERATED_AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# Server settings
DEFAULT_PORT = 8890
DEFAULT_HOST = "0.0.0.0"
