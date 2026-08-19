"""
Generated Videos API routes - Manage locally generated videos.

Endpoints:
- GET  /api/generated-videos              - List all videos
- GET  /api/generated-videos/{name}       - Get video file
- GET  /api/generated-videos/{name}/info  - Get video metadata
- DELETE /api/generated-videos/{name}     - Delete video
- POST /api/generated-videos/generate     - Generate new video
- POST /api/generated-videos/xai-shares/publish - Publish retained MP4
- DELETE /api/generated-videos/xai-shares/revoke - Revoke public MP4
- GET  /api/generated-videos/health       - Health check
"""
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional

# Add lib and skills to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'lib'))
sys.path.insert(0, str(PROJECT_ROOT / 'skills'))

from config_loader import export_config_environment, get_config_value, load_config
from model_catalog import get_media_model_env_key, resolve_media_model
from stash_helper import get_stash_dir
from video_catalog import (
    load_video_catalog as _load_video_catalog,
    lookup_stash_metadata as _lookup_stash_metadata,
    save_video_catalog as _save_video_catalog,
    sync_video_catalog as _sync_video_catalog,
)
from api.services.xai_video_share import (  # noqa: E402
    ALLOWED_TTL_DAYS,
    XaiVideoShareConflict,
    XaiVideoShareDisabled,
    XaiVideoShareError,
    XaiVideoShareService,
    XaiVideoShareValidationError,
    get_xai_video_share_status,
)

# Load config
load_config()

router = APIRouter(prefix="/api/generated-videos", tags=["generated-videos"])

# Directory where generated videos are stored
GENERATED_VIDEOS_DIR = PROJECT_ROOT / "data" / "generated_videos"
GENERATED_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

# Catalog file for video metadata (shared with jarvis-canvas)
VIDEO_CATALOG_FILE = GENERATED_VIDEOS_DIR / "video_catalog.json"
video_share_service = XaiVideoShareService(GENERATED_VIDEOS_DIR)

# Stash directory for looking up metadata
STASH_DIR = get_stash_dir()

# Supported video extensions
VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mov', '.avi', '.mkv'}


def load_video_catalog() -> dict:
    """Load the video catalog from disk."""
    return _load_video_catalog(VIDEO_CATALOG_FILE)


def save_video_catalog(catalog: dict):
    """Save the video catalog to disk."""
    _save_video_catalog(VIDEO_CATALOG_FILE, catalog)


def lookup_stash_metadata(filename: str) -> Optional[dict]:
    """Look up metadata for a video file from stash."""
    return _lookup_stash_metadata(filename, STASH_DIR)


def sync_video_catalog() -> dict:
    """Sync video catalog with actual files and stash metadata."""
    return _sync_video_catalog(
        GENERATED_VIDEOS_DIR,
        STASH_DIR,
        VIDEO_CATALOG_FILE,
    )


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
    stash_ref: Optional[str] = None
    edit_url_status: Optional[str] = None  # 'available', 'expired', or None


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
    stash_ref: Optional[str] = None
    space_id: Optional[str] = None
    source_url: Optional[str] = None
    source_url_created: Optional[str] = None
    edit_url_status: Optional[str] = None  # 'available', 'expired', or None


class DeleteResponse(BaseModel):
    """Response for delete operation."""
    ok: bool
    deleted: Optional[str] = None
    error: Optional[str] = None


class GenerateRequest(BaseModel):
    """Request to generate a new video."""
    prompt: str = Field(..., description="What to generate - describe the video content")
    duration: int = Field(5, ge=1, le=15, description="Video duration: xAI 1-15s, OpenAI 4/8/12s, Gemini 4/6/8s")
    aspect_ratio: str = Field("16:9", description="xAI: 16:9, 4:3, 1:1, 9:16, 3:4, 3:2, 2:3 | OpenAI/Gemini: 16:9 or 9:16")
    resolution: str = Field("720p", description="xAI: 720p/480p | OpenAI: 720p/1080p | Gemini: 720p/1080p/4k")
    image_url: Optional[str] = Field(None, description="Image for image-to-video (all providers). Accepts: URL, local path, or stash ref (stash://space_xxx/file_id)")
    video_url: Optional[str] = Field(None, description="Video to edit. xAI: MUST be a public http(s) URL (use source_url from /info endpoint, expires ~4h). Cannot change duration/aspect. OpenAI: video ID to remix (starts with 'video_').")
    negative_prompt: Optional[str] = Field(None, description="What to avoid in video (Gemini only)")
    provider: Optional[str] = Field(None, description="Override provider: 'xai', 'openai', or 'gemini'")
    save: bool = Field(True, description="Save to disk and stash")
    mode: str = Field("cloud", description="'cloud' uses cloud.env, 'local' uses local.env")


class GenerateResponse(BaseModel):
    """Response from video generation."""
    ok: bool
    speech: Optional[str] = None
    error: Optional[str] = None
    data: Optional[dict] = None


class VideoShareFilenameRequest(BaseModel):
    """Identify a retained video without putting its extension in a Canvas route."""

    filename: str


class VideoSharePublishRequest(VideoShareFilenameRequest):
    """Publish the exact retained MP4 that the user reviewed."""

    ttl_days: int = 7
    expected_video_sha256: str
    confirmed: bool = False


class VideoShareRevokeRequest(BaseModel):
    """Identify a public share for revocation and remote deletion."""

    share_id: str


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
                    tags=meta.get('tags'),
                    stash_ref=meta.get('stash_ref'),
                    edit_url_status=meta.get('edit_url_status'),
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
    
    # Check configured provider and model
    provider = get_config_value("VIDEO_TOOL_PROVIDER", "xai")
    model_key = get_media_model_env_key("video", provider)
    model = resolve_media_model(
        "video",
        provider,
        get_config_value(model_key, "") if model_key else "",
    )
    
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
    
    Supports three providers:
    - **xAI** (default): Grok Imagine Video - $0.05/s, 1-15s, many aspect ratios
    - **OpenAI**: Sora 2 - $0.10/s, 4/8/12s, native audio, image-to-video
    - **Gemini**: Veo 3.1 - $0.15/s, 4/6/8s, native audio, up to 4K
    
    Generation can take 30-120+ seconds depending on provider and duration.
    
    **Example**:
    ```bash
    curl -X POST http://localhost:8880/api/generated-videos/generate \\
      -H "Content-Type: application/json" \\
      -d '{
        "prompt": "A cat playing with a ball, slow motion",
        "duration": 5,
        "aspect_ratio": "16:9",
        "provider": "openai"
      }'
    ```
    
    **Image-to-Video** (all providers):
    ```json
    {
      "prompt": "Animate this image with gentle movement",
      "image_url": "stash://space_xxx/file_id",
      "duration": 8,
      "provider": "gemini"
    }
    ```
    
    **Response**:
    ```json
    {
      "ok": true,
      "speech": "Generated 5s video with openai: A cat playing...",
      "data": {
        "prompt": "A cat playing with a ball, slow motion",
        "provider": "openai",
        "model": "sora-2",
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
        env = export_config_environment(request.mode)
        
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


def _raise_video_share_http_error(exc: XaiVideoShareError) -> None:
    if isinstance(exc, XaiVideoShareDisabled):
        status_code = 503
    elif isinstance(exc, XaiVideoShareConflict):
        status_code = 409
    elif isinstance(exc, XaiVideoShareValidationError):
        status_code = 422
    else:
        status_code = 502
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("/xai-shares/status")
def xai_video_share_status():
    """Return non-secret xAI video-share availability and limits."""
    return {"ok": True, **get_xai_video_share_status()}


@router.post("/xai-shares/preview")
def preview_xai_video_share(request: VideoShareFilenameRequest):
    """Validate and fingerprint the retained MP4 before user confirmation."""
    try:
        preview = video_share_service.inspect_video(request.filename)
    except XaiVideoShareError as exc:
        _raise_video_share_http_error(exc)
    return {"ok": True, "preview": preview}


@router.get("/xai-shares")
def list_xai_video_shares(filename: str = Query(...)):
    """List local lifecycle history for one retained video filename."""
    try:
        shares = video_share_service.list_for_video(filename)
    except XaiVideoShareError as exc:
        _raise_video_share_http_error(exc)
    return {"ok": True, "shares": shares}


@router.post("/xai-shares/publish", status_code=201)
def publish_xai_video_share(request: VideoSharePublishRequest):
    """Upload a reviewed retained MP4 and create an expiring public URL."""
    if request.confirmed is not True:
        raise HTTPException(
            status_code=400,
            detail="Confirm that this video will be public before publishing.",
        )
    if request.ttl_days not in ALLOWED_TTL_DAYS:
        raise HTTPException(status_code=400, detail="Expiration must be 1, 7, or 30 days.")

    catalog = sync_video_catalog()
    provider = str((catalog.get(request.filename) or {}).get("provider") or "").strip() or None
    try:
        record = video_share_service.publish(
            filename=request.filename,
            ttl_days=request.ttl_days,
            expected_video_sha256=request.expected_video_sha256.strip().lower(),
            provider=provider,
        )
    except XaiVideoShareError as exc:
        _raise_video_share_http_error(exc)
    return {"ok": True, "share": record}


@router.delete("/xai-shares/revoke")
def revoke_xai_video_share(request: VideoShareRevokeRequest):
    """Revoke a public URL and delete its underlying xAI file."""
    if not request.share_id or len(request.share_id) != 32:
        raise HTTPException(status_code=400, detail="Invalid share identifier.")
    try:
        record = video_share_service.revoke(request.share_id)
    except XaiVideoShareError as exc:
        _raise_video_share_http_error(exc)
    return {"ok": True, "share": record}


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
        created_at=meta.get('created_at'),
        stash_ref=meta.get('stash_ref'),
        space_id=meta.get('space_id'),
        source_url=meta.get('source_url'),
        source_url_created=meta.get('source_url_created'),
        edit_url_status=meta.get('edit_url_status'),
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
def delete_generated_video(
    filename: str,
    revoke_public_shares: bool = Query(
        False,
        description="Revoke and delete active xAI public copies before local deletion",
    ),
):
    """
    Delete a generated video and remove from catalog.

    **Example**:
    ```bash
    curl -X DELETE http://localhost:8880/api/generated-videos/my_video.mp4
    ```
    """
    revoke_public_shares = revoke_public_shares is True

    # Security: prevent path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        return DeleteResponse(ok=False, error="Invalid filename")

    filepath = GENERATED_VIDEOS_DIR / filename
    if not filepath.exists():
        return DeleteResponse(ok=False, error="Video not found")

    try:
        active_shares = video_share_service.active_for_video(filename)
    except XaiVideoShareError as exc:
        raise HTTPException(
            status_code=500,
            detail="The public-share catalog could not be checked; the video was not deleted.",
        ) from exc
    if active_shares and not revoke_public_shares:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "active_public_video_shares",
                "message": (
                    "This video still has active public copies. Revoke them before local deletion."
                ),
                "active_shares": [
                    {
                        "share_id": record.get("share_id"),
                        "public_url": record.get("public_url"),
                        "expires_at": record.get("expires_at"),
                    }
                    for record in active_shares
                ],
            },
        )
    if active_shares:
        try:
            video_share_service.revoke_all_for_video(filename)
        except XaiVideoShareError as exc:
            _raise_video_share_http_error(exc)

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
