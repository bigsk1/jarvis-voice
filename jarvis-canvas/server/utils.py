"""
Jarvis Canvas - Utility functions
"""
import re
import sys
from pathlib import Path

# Add lib to path for stash helper
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'lib'))


def normalize_space_id(space_id: str) -> str:
    """
    Normalize space_id to handle date format variations.
    
    LLMs sometimes reformat dates from 20260127 to 2026-01-27.
    This normalizes both formats to the canonical no-dash format.
    
    Examples:
        space_2026-01-27_095852_abc123 -> space_20260127_095852_abc123
        space_20260127_095852_abc123 -> space_20260127_095852_abc123 (unchanged)
    """
    # Match space_YYYY-MM-DD_ pattern and convert to space_YYYYMMDD_
    pattern = r'^(space_)(\d{4})-(\d{2})-(\d{2})(_.*)'
    match = re.match(pattern, space_id)
    if match:
        return f"{match.group(1)}{match.group(2)}{match.group(3)}{match.group(4)}{match.group(5)}"
    return space_id


def extract_stash_space_ids(content: str) -> set:
    """
    Extract unique stash space IDs from markdown content.
    
    Matches stash:// URLs in markdown images/links:
        ![img](stash://space_20260127_xxx/file.jpg)
        [link](stash://space_20260127_xxx/doc.pdf)
    
    Returns set of space_ids (e.g., {'space_20260127_xxx', 'space_20260128_yyy'})
    """
    if not content:
        return set()
    
    # Match stash://space_id/anything patterns
    pattern = r'stash://([^/\s\)"\']+)'
    matches = re.findall(pattern, content)
    
    # Normalize space IDs (handle date format variations)
    normalized = set()
    for space_id in matches:
        normalized.add(normalize_space_id(space_id))
    
    return normalized


def sync_stash_pins(content: str, pinned: bool, stash_dir: Path):
    """
    Sync stash space pins based on canvas page pin status.
    
    When a canvas page is pinned, pin all referenced stash spaces
    so their images won't be cleaned up by TTL expiration.
    
    Args:
        content: Canvas page markdown content
        pinned: Whether the page is being pinned (True) or unpinned (False)
        stash_dir: Path to stash directory
    
    Note: We only AUTO-PIN spaces (when page pinned).
          We don't auto-unpin to avoid breaking other pages that may reference the same space.
    """
    if not pinned:
        # Don't auto-unpin - other pages might reference the same spaces
        return
    
    space_ids = extract_stash_space_ids(content)
    if not space_ids:
        return
    
    try:
        from stash_helper import StashSpace
        
        for space_id in space_ids:
            try:
                space = StashSpace(space_id, stash_dir)
                if space.exists and not space.meta.get('pinned', False):
                    space.update(pinned=True)
                    print(f"📌 Auto-pinned stash space: {space_id}")
            except Exception as e:
                print(f"⚠️  Failed to pin stash space {space_id}: {e}")
    except ImportError:
        print("⚠️  stash_helper not available for pin sync")
