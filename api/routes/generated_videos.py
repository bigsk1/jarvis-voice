"""
Generated Videos API routes - Manage locally generated videos.

Endpoints:
- GET  /api/generated-videos              - List all videos
- GET  /api/generated-videos/{name}       - Get video file
- GET  /api/generated-videos/{name}/info  - Get video metadata
- DELETE /api/generated-videos/{name}     - Delete video
- POST /api/generated-videos/generate     - Generate new video
- GET  /api/generated-videos/health       - Health check
"""
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional

# Add lib and skills to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'lib'))
sys.path.insert(0, str(PROJECT_ROOT / 'skills'))

from config_loader import load_config, get_config_value

# Load config
load_config()

router = APIRouter(prefix="/api/generated-videos", tags=["generated-videos"])

# Directory where generated videos are stored
GENERATED_VIDEOS_DIR = PROJECT_ROOT / "data" / "generated_videos"
GENERATED_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

# Catalog file for video metadata (shared with jarvis-canvas)
VIDEO_CATALOG_FILE = GENERATED_VIDEOS_DIR / "video_catalog.json"

# Stash directory for looking up metadata
STASH_DIR = PROJECT_ROOT / "data" / "stash"

# Supported video extensions
VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mov', '.avi', '.mkv'}


def load_video_catalog() -> dict:
    """Load the video catalog from disk."""
    if VIDEO_CATALOG_FILE.exists():
        try:
            with open(VIDEO_CATALOG_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_video_catalog(catalog: dict):
    """Save the video catalog to disk."""
    try:
        with open(VIDEO_CATALOG_FILE, 'w') as f:
            json.dump(catalog, f, indent=2)
    except Exception as e:
        print(f"⚠️  Failed to save video catalog: {e}")


def lookup_stash_metadata(filename: str) -> Optional[dict]:
    """Look up metadata for a video file from stash."""
    if not STASH_DIR.exists():
        return None
    
    for space_dir in STASH_DIR.iterdir():
        if not space_dir.is_dir():
            continue
        
        meta_file = space_dir / "meta.json"
        if not meta_file.exists():
            continue
        
        try:
            with open(meta_file) as f:
                meta = json.load(f)
            
            if 'generated_videos' not in meta.get('labels', []):
                continue
            
            for file_info in meta.get('files', []):
                stored_name = file_info.get('stored_name') or file_info.get('name')
                if stored_name != filename:
                    continue
                
                tags = file_info.get('tags', [])
                
                # Detect provider from tags
                provider = None
                if 'gemini' in tags:
                    provider = 'Gemini'
                elif 'xai' in tags:
                    provider = 'xAI'
                elif 'runway' in tags:
                    provider = 'Runway'
                
                # Get aspect ratio from tags
                aspect = None
                for tag in tags:
                    if ':' in tag and tag.replace(':', '').replace('.', '').isdigit():
                        aspect = tag
                        break
                
                return {
                    'provider': provider,
                    'aspect': aspect,
                    'tags': tags,
                    'tool_origin': file_info.get('tool_origin'),
                    'created_at': file_info.get('created_at')
                }
        except Exception:
            pass
    
    return None


def sync_video_catalog() -> dict:
    """Sync video catalog with actual files and stash metadata."""
    catalog = load_video_catalog()
    changed = False
    
    # Get actual video files
    actual_files = set()
    if GENERATED_VIDEOS_DIR.exists():
        for f in GENERATED_VIDEOS_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
                actual_files.add(f.name)
    
    # Remove deleted videos from catalog
    deleted = [name for name in catalog if name not in actual_files]
    for name in deleted:
        del catalog[name]
        changed = True
    
    # Add new videos (lookup stash metadata)
    for filename in actual_files:
        if filename not in catalog:
            meta = lookup_stash_metadata(filename)
            catalog[filename] = meta or {}
            changed = True
    
    if changed:
        save_video_catalog(catalog)
    
    return catalog


class VideoInfo(BaseModel):
    """Information about a generated video."""
    name: str
    size: int
    size_human: str
    modified: str
    extension: str
    provider: Optional[str] = None
    aspect: Optional[str] = None
    tags: Optional[list[str]] = None


class VideoListResponse(BaseModel):
    """Response for listing videos."""
    ok: bool = True
    count: int
    total_size: int
    total_size_human: str
    videos: list[VideoInfo]


class VideoDetailResponse(BaseModel):
    """Detailed info about a single video."""
    ok: bool = True
    name: str
    size: int
    size_human: str
    modified: str
    extension: str
    mime_type: str
    path: str
    provider: Optional[str] = None
    aspect: Optional[str] = None
    tags: Optional[list[str]] = None
    tool_origin: Optional[str] = None
    created_at: Optional[str] = None


class DeleteResponse(BaseModel):
    """Response for delete operation."""
    ok: bool
    deleted: Optional[str] = None
    error: Optional[str] = None


class GenerateRequest(BaseModel):
    """Request to generate a new video."""
    prompt: str = Field(..., description="What to generate - describe the video content")
    duration: int = Field(5, ge=1, le=15, description="Video duration in seconds (xAI: 1-15, Gemini: 4/6/8)")
    aspect_ratio: str = Field("16:9", description="xAI: 16:9, 4:3, 1:1, 9:16, 3:4, 3:2, 2:3 | Gemini: 16:9 or 9:16")
    resolution: str = Field("720p", description="xAI: 720p/480p | Gemini: 720p/1080p/4k")
    image_url: Optional[str] = Field(None, description="Image URL to generate video from (image-to-video)")
    video_url: Optional[str] = Field(None, description="Video URL to edit (xAI only, max 8.7s source)")
    negative_prompt: Optional[str] = Field(None, description="What to avoid in video (Gemini only)")
    provider: Optional[str] = Field(None, description="Override provider: 'xai' or 'gemini'")
    save: bool = Field(True, description="Save to disk and stash")
    mode: str = Field("cloud", description="'cloud' uses cloud.env, 'local' uses local.env")


class GenerateResponse(BaseModel):
    """Response from video generation."""
    ok: bool
    speech: Optional[str] = None
    error: Optional[str] = None
    data: Optional[dict] = None


def format_size(size_bytes: int) -> str:
    """Format bytes to human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def get_video_list() -> tuple[list[VideoInfo], int, dict]:
    """Get list of videos with metadata."""
    videos = []
    total_size = 0
    
    # Sync catalog with actual files
    catalog = sync_video_catalog()
    
    if GENERATED_VIDEOS_DIR.exists():
        for f in GENERATED_VIDEOS_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
                stat = f.stat()
                
                # Get metadata from catalog
                meta = catalog.get(f.name, {})
                
                videos.append(VideoInfo(
                    name=f.name,
                    size=stat.st_size,
                    size_human=format_size(stat.st_size),
                    modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    extension=f.suffix.lower(),
                    provider=meta.get('provider'),
                    aspect=meta.get('aspect'),
                    tags=meta.get('tags')
                ))
                total_size += stat.st_size
    
    # Sort by modified date descending
    videos.sort(key=lambda x: x.modified, reverse=True)
    return videos, total_size, catalog


def get_mime_type(extension: str) -> str:
    """Get MIME type for video extension."""
    mime_types = {
        '.mp4': 'video/mp4',
        '.webm': 'video/webm',
        '.mov': 'video/quicktime',
        '.avi': 'video/x-msvideo',
        '.mkv': 'video/x-matroska'
    }
    return mime_types.get(extension.lower(), 'video/mp4')


@router.get("", response_model=VideoListResponse)
@router.get("/", response_model=VideoListResponse, include_in_schema=False)
async def list_generated_videos(
    limit: int = Query(100, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Skip N results"),
    search: Optional[str] = Query(None, description="Filter by filename")
):
    """
    List all generated videos.
    
    Returns video metadata including name, size, and modification date.
    Sorted by newest first.
    
    **Example**:
    ```bash
    curl http://localhost:8880/api/generated-videos
    curl http://localhost:8880/api/generated-videos?search=robot&limit=10
    ```
    """
    videos, total_size, _ = get_video_list()
    
    # Filter by search if provided
    if search:
        search_lower = search.lower()
        videos = [vid for vid in videos if search_lower in vid.name.lower()]
    
    total = len(videos)
    
    # Apply pagination
    videos = videos[offset:offset + limit]
    
    return VideoListResponse(
        ok=True,
        count=len(videos),
        total_size=total_size,
        total_size_human=format_size(total_size),
        videos=videos
    )


@router.get("/health")
async def generated_videos_health():
    """Check generated videos directory status."""
    videos, total_size, _ = get_video_list()
    
    # Check configured provider
    provider = get_config_value("VIDEO_TOOL_PROVIDER", "xai")
    model = get_config_value("XAI_VIDEO_MODEL", "grok-imagine-video")
    
    return {
        "ok": True,
        "directory": str(GENERATED_VIDEOS_DIR),
        "exists": GENERATED_VIDEOS_DIR.exists(),
        "video_count": len(videos),
        "total_size": total_size,
        "total_size_human": format_size(total_size),
        "configured_provider": provider,
        "configured_model": model
    }


@router.post("/generate", response_model=GenerateResponse)
async def generate_video(request: GenerateRequest):
    """
    Generate a new video using the generate_video tool.
    
    Uses xAI Grok Imagine Video by default. Generation can take 30-120+ seconds.
    
    **Example**:
    ```bash
    curl -X POST http://localhost:8880/api/generated-videos/generate \\
      -H "Content-Type: application/json" \\
      -d '{
        "prompt": "A cat playing with a ball, slow motion",
        "duration": 5,
        "aspect_ratio": "16:9"
      }'
    ```
    
    **Image-to-Video**:
    ```json
    {
      "prompt": "Animate this image with gentle movement",
      "image_url": "https://example.com/image.jpg",
      "duration": 10
    }
    ```
    
    **Response**:
    ```json
    {
      "ok": true,
      "speech": "Generated 5s video with xai: A cat playing...",
      "data": {
        "prompt": "A cat playing with a ball, slow motion",
        "provider": "xai",
        "model": "grok-imagine-video",
        "duration": 5,
        "saved": {
          "path": "data/generated_videos/video_a_cat_playing_20260128_123456.mp4",
          "filename": "video_a_cat_playing_20260128_123456.mp4"
        }
      }
    }
    ```
    """
    try:
        # Build args for generate_video tool
        args = {
            "prompt": request.prompt,
            "duration": request.duration,
            "aspect_ratio": request.aspect_ratio,
            "resolution": request.resolution,
            "save": request.save
        }
        
        if request.image_url:
            args["image_url"] = request.image_url
        if request.video_url:
            args["video_url"] = request.video_url
        if request.negative_prompt:
            args["negative_prompt"] = request.negative_prompt
        if request.provider:
            args["provider"] = request.provider
        
        # Call generate_video tool
        tool_path = PROJECT_ROOT / "skills" / "generate_video.py"
        
        # Set environment for mode
        import os
        env = os.environ.copy()
        env["JARVIS_MODE"] = request.mode
        
        # Video generation can take a long time (30-120+ seconds)
        result = subprocess.run(
            ["python3", str(tool_path), json.dumps(args)],
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout for video generation
            cwd=str(PROJECT_ROOT),
            env=env
        )
        
        if result.returncode != 0:
            error = result.stderr or "Unknown error"
            return GenerateResponse(ok=False, error=error)
        
        # Parse tool output
        try:
            output = json.loads(result.stdout)
            
            if not output.get("ok", False):
                return GenerateResponse(
                    ok=False,
                    speech=output.get("speech"),
                    error=output.get("error"),
                    data=output.get("data")
                )
            
            return GenerateResponse(
                ok=True,
                speech=output.get("speech"),
                error=output.get("error"),
                data=output.get("data")
            )
        except json.JSONDecodeError:
            return GenerateResponse(ok=False, error=f"Invalid tool output: {result.stdout[:200]}")
        
    except subprocess.TimeoutExpired:
        return GenerateResponse(ok=False, error="Video generation timed out (10 min limit)")
    except Exception as e:
        return GenerateResponse(ok=False, error=str(e))


@router.get("/{filename}/info", response_model=VideoDetailResponse)
async def get_video_info(filename: str):
    """
    Get detailed information about a video including provider and tags.
    
    **Example**:
    ```bash
    curl http://localhost:8880/api/generated-videos/my_video.mp4/info
    ```
    """
    # Security: prevent path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    filepath = GENERATED_VIDEOS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    
    stat = filepath.stat()
    ext = filepath.suffix.lower()
    
    # Get metadata from catalog
    catalog = sync_video_catalog()
    meta = catalog.get(filename, {})
    
    return VideoDetailResponse(
        ok=True,
        name=filename,
        size=stat.st_size,
        size_human=format_size(stat.st_size),
        modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
        extension=ext,
        mime_type=get_mime_type(ext),
        path=str(filepath.relative_to(PROJECT_ROOT)),
        provider=meta.get('provider'),
        aspect=meta.get('aspect'),
        tags=meta.get('tags'),
        tool_origin=meta.get('tool_origin'),
        created_at=meta.get('created_at')
    )


@router.get("/{filename}")
async def get_generated_video(filename: str):
    """
    Get a generated video file.
    
    Returns the video file directly with support for range requests
    (needed for video seeking).
    
    **Example**:
    ```bash
    curl http://localhost:8880/api/generated-videos/my_video.mp4 -o my_video.mp4
    ```
    """
    # Security: prevent path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    filepath = GENERATED_VIDEOS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    
    # Get mime type
    ext = filepath.suffix.lower()
    mime_type = get_mime_type(ext)
    
    # FileResponse supports range requests for video seeking
    return FileResponse(
        filepath,
        media_type=mime_type,
        filename=filename
    )


@router.delete("/{filename}", response_model=DeleteResponse)
async def delete_generated_video(filename: str):
    """
    Delete a generated video and remove from catalog.
    
    **Example**:
    ```bash
    curl -X DELETE http://localhost:8880/api/generated-videos/my_video.mp4
    ```
    """
    # Security: prevent path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        return DeleteResponse(ok=False, error="Invalid filename")
    
    filepath = GENERATED_VIDEOS_DIR / filename
    if not filepath.exists():
        return DeleteResponse(ok=False, error="Video not found")
    
    try:
        # Delete the video file
        filepath.unlink()
        
        # Remove from catalog
        catalog = load_video_catalog()
        if filename in catalog:
            del catalog[filename]
            save_video_catalog(catalog)
        
        return DeleteResponse(ok=True, deleted=filename)
    except Exception as e:
        return DeleteResponse(ok=False, error=str(e))
