"""Stash API endpoints - Access to stash artifacts with upload support"""

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
import json
import re
import sys
from pathlib import Path
from typing import Optional

from api.models.stash import (
    StashFile, StashSpace, StashResponse, StashStats
)

# Add lib to path for stash_helper
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib"))
from stash_helper import get_stash_dir, open_space, StashFile as StashFileHelper

router = APIRouter(prefix="/api/stash", tags=["stash"])

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


def get_space_meta(space_id: str) -> dict | None:
    """Load meta.json for a space"""
    # Normalize space_id to handle LLM date reformatting
    space_id = normalize_space_id(space_id)
    meta_path = get_stash_dir() / space_id / "meta.json"
    if not meta_path.exists():
        return None
    try:
        with open(meta_path) as f:
            return json.load(f)
    except:
        return None


def meta_to_space(meta: dict, include_files: bool = False) -> StashSpace:
    """Convert meta.json to StashSpace model"""
    files = meta.get('files', [])
    total_size = sum(f.get('size_bytes', 0) for f in files)
    
    space = StashSpace(
        space_id=meta['space_id'],
        created_at=meta['created_at'],
        last_used_at=meta.get('last_used_at'),
        labels=meta.get('labels', []),
        owner=meta.get('owner', 'jarvis'),
        scope=meta.get('scope', 'session'),
        ttl_days=meta.get('ttl_days', 7),
        pinned=meta.get('pinned', False),
        file_count=len(files),
        total_size_bytes=total_size
    )
    
    if include_files:
        space.files = [StashFile(**f) for f in files]
    
    return space


def human_size(size_bytes: int) -> str:
    """Convert bytes to human readable"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# ============================================
# Stats & List
# ============================================

@router.get("/stats", response_model=StashStats)
async def get_stash_stats():
    """
    Get stash statistics.
    
    Returns total spaces, files, size, and breakdowns by label/tool.
    """
    try:
        total_spaces = 0
        total_files = 0
        total_size = 0
        pinned = 0
        by_label = {}
        by_tool = {}
        oldest = None
        newest = None
        
        for space_dir in get_stash_dir().iterdir():
            if not space_dir.is_dir() or not space_dir.name.startswith('space_'):
                continue
            
            meta = get_space_meta(space_dir.name)
            if not meta:
                continue
            
            total_spaces += 1
            files = meta.get('files', [])
            total_files += len(files)
            
            for f in files:
                total_size += f.get('size_bytes', 0)
                tool = f.get('tool_origin')
                if tool:
                    by_tool[tool] = by_tool.get(tool, 0) + 1
            
            if meta.get('pinned'):
                pinned += 1
            
            for label in meta.get('labels', []):
                by_label[label] = by_label.get(label, 0) + 1
            
            created = meta.get('created_at', '')
            if not oldest or created < oldest:
                oldest = created
            if not newest or created > newest:
                newest = created
        
        return StashStats(
            total_spaces=total_spaces,
            total_files=total_files,
            total_size_bytes=total_size,
            total_size_human=human_size(total_size),
            pinned_spaces=pinned,
            by_label=dict(sorted(by_label.items(), key=lambda x: x[1], reverse=True)[:10]),
            by_tool=dict(sorted(by_tool.items(), key=lambda x: x[1], reverse=True)[:10]),
            oldest_space=oldest,
            newest_space=newest
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=StashResponse)
@router.get("/", response_model=StashResponse, include_in_schema=False)
async def list_spaces(
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Skip N results"),
    label: str | None = Query(None, description="Filter by label"),
    pinned: bool | None = Query(None, description="Filter by pinned status"),
    tool: str | None = Query(None, description="Filter by tool_origin")
):
    """
    List stash spaces with pagination and filters.
    
    **Filters:**
    - `label`: Filter by label (e.g., "generated_images")
    - `pinned`: Only pinned (true) or unpinned (false)
    - `tool`: Filter by tool that created files (e.g., "generate_image")
    """
    try:
        all_spaces = []
        
        for space_dir in sorted(get_stash_dir().iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if not space_dir.is_dir() or not space_dir.name.startswith('space_'):
                continue
            
            meta = get_space_meta(space_dir.name)
            if not meta:
                continue
            
            # Apply filters
            if label and label not in meta.get('labels', []):
                continue
            
            if pinned is not None and meta.get('pinned', False) != pinned:
                continue
            
            if tool:
                has_tool = any(f.get('tool_origin') == tool for f in meta.get('files', []))
                if not has_tool:
                    continue
            
            all_spaces.append(meta_to_space(meta, include_files=False))
        
        # Paginate
        total = len(all_spaces)
        spaces = all_spaces[offset:offset + limit]
        
        return StashResponse(
            ok=True,
            count=len(spaces),
            spaces=spaces,
            message=f"Found {total} spaces"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Get Space & Files
# ============================================

@router.get("/space/{space_id}", response_model=StashResponse)
async def get_space(space_id: str, include_files: bool = True):
    """
    Get a specific stash space with its files.
    
    The `space_id` is the directory name (e.g., "space_20260118_005400_7374e32c").
    """
    try:
        meta = get_space_meta(space_id)
        if not meta:
            raise HTTPException(status_code=404, detail=f"Space {space_id} not found")
        
        return StashResponse(
            ok=True,
            space=meta_to_space(meta, include_files=include_files)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/space/{space_id}/file/{file_id}")
async def get_file_info(space_id: str, file_id: str):
    """
    Get information about a specific file in a space.
    """
    try:
        meta = get_space_meta(space_id)
        if not meta:
            raise HTTPException(status_code=404, detail=f"Space {space_id} not found")
        
        for f in meta.get('files', []):
            if f['file_id'] == file_id:
                return StashResponse(
                    ok=True,
                    file=StashFile(**f)
                )
        
        raise HTTPException(status_code=404, detail=f"File {file_id} not found in space")
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/space/{space_id}/file/{file_id}/download")
async def download_file(space_id: str, file_id: str):
    """
    Download a file from a stash space.
    
    Returns the actual file content with appropriate mime type.
    """
    try:
        # Normalize space_id to handle LLM date reformatting
        normalized_space_id = normalize_space_id(space_id)
        meta = get_space_meta(normalized_space_id)
        if not meta:
            raise HTTPException(status_code=404, detail=f"Space {space_id} not found")
        
        for f in meta.get('files', []):
            if f['file_id'] == file_id:
                file_path = get_stash_dir() / normalized_space_id / f['stored_name']
                if not file_path.exists():
                    raise HTTPException(status_code=404, detail="File not found on disk")
                
                return FileResponse(
                    path=str(file_path),
                    filename=f['name'],
                    media_type=f.get('mime_type', 'application/octet-stream')
                )
        
        raise HTTPException(status_code=404, detail=f"File {file_id} not found")
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Search & Recent
# ============================================

@router.get("/recent", response_model=StashResponse)
async def get_recent_spaces(
    limit: int = Query(10, ge=1, le=50, description="Max results")
):
    """
    Get most recently used stash spaces.
    
    Sorted by last_used_at descending.
    """
    try:
        spaces = []
        
        for space_dir in sorted(get_stash_dir().iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if not space_dir.is_dir() or not space_dir.name.startswith('space_'):
                continue
            
            meta = get_space_meta(space_dir.name)
            if meta:
                spaces.append(meta_to_space(meta, include_files=False))
            
            if len(spaces) >= limit:
                break
        
        return StashResponse(
            ok=True,
            count=len(spaces),
            spaces=spaces
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search", response_model=StashResponse)
async def search_stash(
    q: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100, description="Max results")
):
    """
    Search stash by filename or label.
    
    Searches in file names and space labels.
    """
    try:
        q_lower = q.lower()
        results = []
        
        for space_dir in get_stash_dir().iterdir():
            if not space_dir.is_dir() or not space_dir.name.startswith('space_'):
                continue
            
            meta = get_space_meta(space_dir.name)
            if not meta:
                continue
            
            # Check labels
            label_match = any(q_lower in label.lower() for label in meta.get('labels', []))
            
            # Check file names
            file_match = any(
                q_lower in f.get('name', '').lower() 
                for f in meta.get('files', [])
            )
            
            if label_match or file_match:
                results.append(meta_to_space(meta, include_files=True))
            
            if len(results) >= limit:
                break
        
        return StashResponse(
            ok=True,
            message=f"Found {len(results)} spaces matching '{q}'",
            count=len(results),
            spaces=results
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/labels")
async def list_labels():
    """
    List all unique labels with counts.
    """
    try:
        labels = {}
        
        for space_dir in get_stash_dir().iterdir():
            if not space_dir.is_dir() or not space_dir.name.startswith('space_'):
                continue
            
            meta = get_space_meta(space_dir.name)
            if meta:
                for label in meta.get('labels', []):
                    labels[label] = labels.get(label, 0) + 1
        
        return {
            "ok": True,
            "count": len(labels),
            "labels": dict(sorted(labels.items(), key=lambda x: x[1], reverse=True))
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Upload
# ============================================

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(..., description="File to upload"),
    labels: Optional[str] = Form(None, description="Comma-separated labels (e.g., 'uploaded,for_conversion')"),
    space_id: Optional[str] = Form(None, description="Existing space_id to add file to, or None to create new space")
):
    """
    Upload a file to stash.
    
    Creates a new stash space (or adds to existing) and stores the uploaded file.
    Returns the stash reference that can be used with other tools like convert_file.
    
    **Example usage:**
    ```
    curl -X POST http://localhost:8991/api/stash/upload \
      -F "file=@image.jpg" \
      -F "labels=uploaded,for_conversion"
    ```
    
    **Response:**
    ```json
    {
      "ok": true,
      "stash_ref": "stash://space_20260205_123456_abc123/f_xyz789",
      "space_id": "space_20260205_123456_abc123",
      "file_id": "f_xyz789",
      "filename": "image.jpg",
      "size_bytes": 123456,
      "mime_type": "image/jpeg"
    }
    ```
    """
    try:
        # Read file content
        content = await file.read()
        
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="Empty file uploaded")
        
        # Max file size: 100MB
        max_size = 100 * 1024 * 1024
        if len(content) > max_size:
            raise HTTPException(status_code=413, detail=f"File too large. Max size: {max_size // 1024 // 1024}MB")
        
        # Parse labels
        label_list = ['uploaded']
        if labels:
            label_list.extend([l.strip() for l in labels.split(',') if l.strip()])
        
        # Open or create space
        if space_id:
            # Add to existing space
            from stash_helper import get_space
            space = get_space(space_id)
            if not space:
                raise HTTPException(status_code=404, detail=f"Space {space_id} not found")
        else:
            # Create new space
            space = open_space(
                labels=label_list,
                scope='project'  # Longer retention for uploaded files
            )
        
        # Save file to stash
        stash_file = StashFileHelper(space)
        result = stash_file.save_binary(
            data=content,
            name=file.filename or "uploaded_file",
            tool_origin='api_upload',
            on_conflict='version'
        )
        
        return {
            "ok": True,
            "stash_ref": result.get('ref'),
            "space_id": space.space_id,
            "file_id": result.get('file_id'),
            "filename": result.get('name'),
            "size_bytes": len(content),
            "mime_type": result.get('mime_type', file.content_type),
            "message": f"File '{file.filename}' uploaded to stash"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
