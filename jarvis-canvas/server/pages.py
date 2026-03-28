"""
Jarvis Canvas - Page storage functions
"""
import json
import sys

from config import CANVAS_DIR


def load_pages():
    """Load all pages from disk."""
    pages = []
    for file in CANVAS_DIR.glob("*.json"):
        try:
            with open(file) as f:
                page = json.load(f)
                pages.append(page)
        except Exception as e:
            print(f"Error loading {file}: {e}", file=sys.stderr)
    # Sort by updated/created time, newest first
    pages.sort(key=lambda p: p.get('updated') or p.get('created', ''), reverse=True)
    return pages


def save_page(page):
    """Save a page to disk."""
    filepath = CANVAS_DIR / f"{page['id']}.json"
    with open(filepath, 'w') as f:
        json.dump(page, f, indent=2)
    return page


def delete_page_file(page_id):
    """Delete a page file from disk."""
    filepath = CANVAS_DIR / f"{page_id}.json"
    if filepath.exists():
        filepath.unlink()
        return True
    return False


def get_page_path(page_id):
    """Get the path to a page file."""
    return CANVAS_DIR / f"{page_id}.json"
