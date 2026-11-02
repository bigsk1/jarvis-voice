"""Stash API endpoints - Access to stash artifacts with upload support"""

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Annotated, Literal, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from api.models.stash import StashFile, StashResponse, StashSpace, StashStats

# Add lib to path for stash_helper
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib"))
from config_loader import config_scope, get_active_config_mode
from stash_helper import StashFile as StashFileHelper
from stash_helper import StashSpace as StashSpaceHelper
from stash_helper import get_stash_dir, open_space, parse_stash_ref, resolve_file_path

router = APIRouter(prefix="/api/stash", tags=["stash"])

TEXT_READ_MAX_BYTES = 10 * 1024 * 1024
TEXT_READ_MAX_CHARS = 40_000


def _resolve_stash_reference(ref: str) -> tuple[Path, dict]:
    """Resolve a registered Stash file while confining reads to its own space."""
    try:
        space_id, selector = parse_stash_ref(ref)
    except ValueError:
        raise HTTPException(status_code=400, detail="Expected stash://space_id/file_id or filename")
    if (
        ref != ref.strip()
        or not re.fullmatch(r"space_[A-Za-z0-9_-]+", space_id)
        or not selector
        or selector in {".", ".."}
        or any(char in selector for char in "/\\")
        or any(ord(char) < 32 or ord(char) == 127 for char in selector)
    ):
        raise HTTPException(status_code=400, detail="Invalid Stash reference")

    try:
        root = get_stash_dir().resolve()
        space_path = (root / space_id).resolve()
        meta_path = space_path / "meta.json"
        if not space_path.is_relative_to(root) or space_path == root:
            raise HTTPException(status_code=403, detail="Stash reference escapes its storage root")
        if not meta_path.resolve().is_relative_to(space_path):
            raise HTTPException(status_code=403, detail="Stash metadata escapes its space")
        if not meta_path.is_file():
            raise HTTPException(status_code=404, detail="Stash space not found")

        space = StashSpaceHelper(space_id, stash_dir=root)
        stash_file = StashFileHelper(space, file_id=selector)
        if not stash_file.exists:
            stash_file = StashFileHelper(space, name=selector)
        metadata = stash_file.meta
        if not metadata:
            raise HTTPException(status_code=404, detail="Stash file not found")
        stored_name = metadata.get("stored_name")
        if (
            not isinstance(stored_name, str)
            or not stored_name
            or stored_name in {".", ".."}
            or any(char in stored_name for char in "/\\")
        ):
            raise HTTPException(status_code=403, detail="Invalid Stash file location")
        # Canonical resolution retains the shared restricted-read-path policy.
        path = Path(resolve_file_path(stash_ref=ref))
        if not path.is_relative_to(space_path) or path == space_path:
            raise HTTPException(status_code=403, detail="Stash file escapes its space")
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Stash file data not found")
        return path, {
            "stash_ref": f"stash://{space_id}/{metadata['file_id']}",
            "space_id": space_id,
            "file_id": metadata["file_id"],
            "filename": metadata["name"],
            "mime_type": metadata.get("mime_type") or "application/octet-stream",
            "size_bytes": path.stat().st_size,
            "hash_sha256": metadata.get("hash_sha256"),
        }
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Stash file data not found")
    except (PermissionError, ValueError, RuntimeError):
        raise HTTPException(status_code=403, detail="Stash reference is not accessible")
    except (OSError, KeyError, TypeError):
        raise HTTPException(status_code=500, detail="Unable to read Stash metadata")


def _is_text_mime(mime_type: str) -> bool:
    mime = mime_type.partition(";")[0].strip().lower()
    return (
        mime.startswith("text/")
        or mime in {"application/json", "application/xml"}
        or mime.endswith(("+json", "+xml"))
    )


def _reference_details(metadata: dict, mode: str) -> dict:
    query = urlencode({"ref": metadata["stash_ref"], "mode": mode})
    text_readable = _is_text_mime(metadata["mime_type"])
    return {
        "ok": True,
        "mode": mode,
        **metadata,
        "text_readable": text_readable,
        "read_url": f"/api/stash/read?{query}" if text_readable else None,
        "download_url": f"/api/stash/download?{query}",
    }


@router.get("/resolve")
def resolve_reference(
    ref: Annotated[str, Query(min_length=1, max_length=2048)],
    mode: Literal["cloud", "local"] | None = None,
):
    """Resolve a file ID or filename reference to metadata and relative retrieval URLs."""
    with config_scope(get_active_config_mode(mode)):
        _path, metadata = _resolve_stash_reference(ref)
        return _reference_details(metadata, get_active_config_mode())


@router.get("/read")
def read_reference(
    ref: Annotated[str, Query(min_length=1, max_length=2048)],
    mode: Literal["cloud", "local"] | None = None,
    offset: int = Query(0, ge=0, description="Unicode character offset, not a byte offset"),
    max_chars: int = Query(20_000, ge=1, le=TEXT_READ_MAX_CHARS),
    expected_sha256: str | None = Query(
        None, pattern=r"^[0-9a-f]{64}$", description="Prior page's hash; reject changed files"
    ),
):
    """Read bounded UTF-8 text, with exact character continuation and no format conversion."""
    with config_scope(get_active_config_mode(mode)):
        path, metadata = _resolve_stash_reference(ref)
        if not _is_text_mime(metadata["mime_type"]):
            raise HTTPException(status_code=415, detail="Not a supported text file; use download")
        if metadata["size_bytes"] > TEXT_READ_MAX_BYTES:
            raise HTTPException(status_code=413, detail="Text exceeds 10 MiB read limit; use download")
        try:
            with path.open("rb") as handle:
                raw = handle.read(TEXT_READ_MAX_BYTES + 1)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Stash file data not found")
        except OSError:
            raise HTTPException(status_code=500, detail="Unable to read Stash file")
        if len(raw) > TEXT_READ_MAX_BYTES:
            raise HTTPException(status_code=413, detail="Text exceeds 10 MiB read limit; use download")
        actual_hash = hashlib.sha256(raw).hexdigest()
        if expected_sha256 is not None and actual_hash != expected_sha256:
            raise HTTPException(status_code=409, detail="File changed; restart reading at offset 0")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=415, detail="File is not UTF-8 text; use download")
        if "\x00" in text:
            raise HTTPException(status_code=415, detail="File contains binary data; use download")
        if offset > len(text):
            raise HTTPException(status_code=416, detail="Offset exceeds the file's character length")
        content = text[offset:offset + max_chars]
        end = offset + len(content)
        has_more = end < len(text)
        next_offset = end if has_more else None
        next_url = None
        if has_more:
            query = urlencode({
                "ref": metadata["stash_ref"], "mode": get_active_config_mode(),
                "offset": next_offset, "max_chars": max_chars, "expected_sha256": actual_hash,
            })
            next_url = f"/api/stash/read?{query}"
        return {
            **_reference_details(metadata, get_active_config_mode()),
            "content": content,
            "offset": offset,
            "max_chars": max_chars,
            "returned_chars": len(content),
            "total_chars": len(text),
            "has_more": has_more,
            "next_offset": next_offset,
            "next_url": next_url,
            "content_sha256": actual_hash,
        }


@router.get("/download")
def download_reference(
    ref: Annotated[str, Query(min_length=1, max_length=2048)],
    mode: Literal["cloud", "local"] | None = None,
):
    """Download original bytes using a canonical, confined Stash reference."""
    with config_scope(get_active_config_mode(mode)):
        path, metadata = _resolve_stash_reference(ref)
        return FileResponse(path=path, filename=metadata["filename"], media_type=metadata["mime_type"])


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


def _stash_component(value: object) -> str:
    """Require one component for legacy space selectors and stored filenames."""
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or any(char in value for char in "/\\")
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError("Invalid Stash path component")
    return value


def _confined_stash_path(parent: Path, name: object) -> Path:
    """Resolve each component inside its canonical parent before reading it."""
    path = (parent / _stash_component(name)).resolve()
    if path == parent or not path.is_relative_to(parent):
        raise ValueError("Stash path escapes its parent")
    return path


def get_space_meta(space_id: str) -> dict | None:
    """Load confined metadata, treating unsafe or unreadable spaces as unavailable."""
    try:
        space_id = normalize_space_id(_stash_component(space_id))
        root = get_stash_dir().resolve()
        space_path = _confined_stash_path(root, space_id)
        meta_path = _confined_stash_path(space_path, "meta.json")
        if not meta_path.is_file():
            return None
        with meta_path.open() as f:
            meta = json.load(f)
        return meta if isinstance(meta, dict) else None
    except (OSError, ValueError, RuntimeError):
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
        meta = get_space_meta(space_id)
        if not meta:
            raise HTTPException(status_code=404, detail=f"Space {space_id} not found")
        normalized_space_id = normalize_space_id(space_id)
        
        for f in meta.get('files', []):
            if f['file_id'] == file_id:
                root = get_stash_dir().resolve()
                space_path = _confined_stash_path(root, normalized_space_id)
                file_path = _confined_stash_path(space_path, f['stored_name'])
                if not file_path.is_file():
                    raise HTTPException(status_code=404, detail="File not found on disk")
                
                return FileResponse(
                    path=str(file_path),
                    filename=f['name'],
                    media_type=f.get('mime_type', 'application/octet-stream')
                )
        
        raise HTTPException(status_code=404, detail=f"File {file_id} not found")
        
    except HTTPException:
        raise
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(status_code=403, detail="Stash file is not accessible")
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
            label_list.extend([label.strip() for label in labels.split(',') if label.strip()])
        
        # Open or create space
        if space_id:
            # Add to existing space
            from stash_helper import get_space
            space = get_space(space_id)
            if not space:
                raise HTTPException(status_code=404, detail=f"Space {space_id} not found")
        else:
            # Create new space
            space, _is_new = open_space(
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
