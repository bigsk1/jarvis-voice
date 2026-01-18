"""
Canvas API routes - Read-only access to canvas pages.
"""
import os
import json
import re
from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from ..models.canvas import (
    CanvasPage, CanvasPageFull, CanvasPageResponse,
    CanvasListResponse, CanvasStats
)

router = APIRouter(prefix="/api/canvas", tags=["Canvas"])

# Canvas data directory
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CANVAS_DIR = os.path.join(PROJECT_ROOT, "data", "canvas")


def _format_size(size_bytes: int) -> str:
    """Format bytes to human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _extract_embedded_images(content: str) -> List[str]:
    """Extract stash:// references from markdown content."""
    # Match ![title](stash://...) patterns
    pattern = r'!\[.*?\]\(stash://([^)]+)\)'
    matches = re.findall(pattern, content)
    return [f"stash://{m}" for m in matches]


def _load_page(filepath: str) -> Optional[dict]:
    """Load a canvas page from JSON file."""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception:
        return None


def _get_all_pages() -> List[tuple]:
    """Get all canvas pages as (filepath, data) tuples."""
    if not os.path.exists(CANVAS_DIR):
        return []
    
    pages = []
    for filename in os.listdir(CANVAS_DIR):
        if filename.startswith("page_") and filename.endswith(".json"):
            filepath = os.path.join(CANVAS_DIR, filename)
            data = _load_page(filepath)
            if data:
                pages.append((filepath, data))
    
    # Sort by created date, newest first
    pages.sort(key=lambda x: x[1].get('created', ''), reverse=True)
    return pages


def _page_to_model(data: dict, include_content: bool = False, for_list: bool = True) -> CanvasPage:
    """Convert raw page data to Pydantic model.
    
    Args:
        data: Raw page data dict
        include_content: Whether to include full content
        for_list: If True, return CanvasPage; if False, return CanvasPageFull
    """
    content = data.get('content', '')
    
    page_data = {
        "page_id": data.get('id', ''),
        "title": data.get('title', 'Untitled'),
        "created_at": data.get('created', ''),
        "updated_at": data.get('updated'),
        "tags": data.get('tags', []),
        "source_tool": data.get('source_tool'),
        "content_preview": content[:500] if content else None,
        "content_length": len(content),
        "embedded_images": _extract_embedded_images(content)
    }
    
    # For single page responses, always use CanvasPageFull
    if not for_list:
        page_data["content"] = content if include_content else ""
        return CanvasPageFull(**page_data)
    
    # For list responses, use CanvasPage (no content field)
    if include_content:
        page_data["content"] = content
        return CanvasPageFull(**page_data)
    
    return CanvasPage(**page_data)


# ============================================================================
# STATS ENDPOINT (MUST BE BEFORE /{page_id} TO AVOID CONFLICTS)
# ============================================================================

@router.get("/stats", response_model=CanvasStats)
async def get_canvas_stats():
    """
    Get canvas statistics.
    
    Returns total pages, size, breakdown by tool and tags.
    """
    pages = _get_all_pages()
    
    if not pages:
        return CanvasStats()
    
    total_size = 0
    pages_with_images = 0
    by_tool = {}
    by_tag = {}
    oldest = None
    newest = None
    
    for filepath, data in pages:
        # File size
        total_size += os.path.getsize(filepath)
        
        # Content analysis
        content = data.get('content', '')
        if _extract_embedded_images(content):
            pages_with_images += 1
        
        # Source tool
        tool = data.get('source_tool')
        if tool:
            by_tool[tool] = by_tool.get(tool, 0) + 1
        
        # Tags
        for tag in data.get('tags', []):
            by_tag[tag] = by_tag.get(tag, 0) + 1
        
        # Date tracking
        created = data.get('created', '')
        if created:
            if oldest is None or created < oldest:
                oldest = created
            if newest is None or created > newest:
                newest = created
    
    return CanvasStats(
        total_pages=len(pages),
        total_size_bytes=total_size,
        total_size_human=_format_size(total_size),
        pages_with_images=pages_with_images,
        by_tool=by_tool,
        by_tag=by_tag,
        oldest_page=oldest,
        newest_page=newest
    )


# ============================================================================
# LIST/FILTER ENDPOINTS
# ============================================================================

@router.get("", response_model=CanvasListResponse)
async def list_pages(
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Skip N results"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    tool: Optional[str] = Query(None, description="Filter by source_tool"),
    search: Optional[str] = Query(None, description="Search in title/content")
):
    """
    List canvas pages with optional filtering.
    
    Supports pagination, tag filtering, and text search.
    """
    pages = _get_all_pages()
    
    # Filter by tag
    if tag:
        pages = [(fp, d) for fp, d in pages if tag in d.get('tags', [])]
    
    # Filter by tool
    if tool:
        pages = [(fp, d) for fp, d in pages if d.get('source_tool') == tool]
    
    # Text search
    if search:
        search_lower = search.lower()
        def matches(data):
            if search_lower in data.get('title', '').lower():
                return True
            if search_lower in data.get('content', '').lower():
                return True
            return False
        pages = [(fp, d) for fp, d in pages if matches(d)]
    
    total = len(pages)
    
    # Apply pagination
    pages = pages[offset:offset + limit]
    
    return CanvasListResponse(
        ok=True,
        pages=[_page_to_model(d) for _, d in pages],
        count=len(pages),
        total=total
    )


@router.get("/recent", response_model=CanvasListResponse)
async def get_recent_pages(
    limit: int = Query(10, ge=1, le=50, description="Number of pages")
):
    """
    Get most recently created pages.
    """
    pages = _get_all_pages()[:limit]
    
    return CanvasListResponse(
        ok=True,
        pages=[_page_to_model(d) for _, d in pages],
        count=len(pages),
        total=len(pages)
    )


@router.get("/search", response_model=CanvasListResponse)
async def search_pages(
    q: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100, description="Max results")
):
    """
    Search canvas pages by title or content.
    """
    pages = _get_all_pages()
    search_lower = q.lower()
    
    matches = []
    for filepath, data in pages:
        if search_lower in data.get('title', '').lower():
            matches.append((filepath, data))
        elif search_lower in data.get('content', '').lower():
            matches.append((filepath, data))
    
    matches = matches[:limit]
    
    return CanvasListResponse(
        ok=True,
        pages=[_page_to_model(d) for _, d in matches],
        count=len(matches),
        total=len(matches)
    )


@router.get("/tags")
async def list_tags():
    """
    List all unique tags with counts.
    """
    pages = _get_all_pages()
    tags = {}
    
    for _, data in pages:
        for tag in data.get('tags', []):
            tags[tag] = tags.get(tag, 0) + 1
    
    return {
        "ok": True,
        "count": len(tags),
        "tags": tags
    }


@router.get("/tools")
async def list_tools():
    """
    List all source tools with counts.
    """
    pages = _get_all_pages()
    tools = {}
    
    for _, data in pages:
        tool = data.get('source_tool')
        if tool:
            tools[tool] = tools.get(tool, 0) + 1
    
    return {
        "ok": True,
        "count": len(tools),
        "tools": tools
    }


# ============================================================================
# SINGLE PAGE ENDPOINT (MUST BE LAST TO AVOID PATH CONFLICTS)
# ============================================================================

@router.get("/{page_id}", response_model=CanvasPageResponse)
async def get_page(
    page_id: str,
    include_content: bool = Query(True, description="Include full content")
):
    """
    Get a specific canvas page by ID.
    
    Set include_content=false for metadata only.
    """
    # Handle both "page_20251214_221346" and "page_20251214_221346.json"
    if not page_id.startswith("page_"):
        page_id = f"page_{page_id}"
    
    filename = f"{page_id}.json" if not page_id.endswith(".json") else page_id
    filepath = os.path.join(CANVAS_DIR, filename)
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail=f"Page not found: {page_id}")
    
    data = _load_page(filepath)
    if not data:
        raise HTTPException(status_code=500, detail="Failed to load page")
    
    return CanvasPageResponse(
        ok=True,
        page=_page_to_model(data, include_content=include_content, for_list=False)
    )
