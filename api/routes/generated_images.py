"""
Generated Images API routes - Manage locally generated images.

Unlike /api/images (Cloudflare uploads), these routes manage the local
data/generated_images/ folder where AI-generated images are stored.

Supports text-to-image generation AND image-to-image editing via the
`reference_image` parameter. All 3 providers (Gemini, OpenAI, xAI)
support both modes.

Endpoints:
- GET  /api/generated-images              - List all images
- GET  /api/generated-images/{name}       - Get image file
- GET  /api/generated-images/{name}/base64 - Get image as base64
- GET  /api/generated-images/{name}/cdn-url - Get/create CDN URL
- DELETE /api/generated-images/{name}     - Delete image
- POST /api/generated-images/generate     - Generate or edit image
- GET  /api/generated-images/cdn-catalog  - List all CDN URLs
"""
import sys
import base64
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

from config_loader import load_config, get_config_value
from model_catalog import get_media_model_env_key, resolve_media_model

# Load config
load_config()

router = APIRouter(prefix="/api/generated-images", tags=["generated-images"])

# Directory where generated images are stored
GENERATED_IMAGES_DIR = PROJECT_ROOT / "data" / "generated_images"
GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# Supported image extensions
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}

# CDN catalog file - maps filenames to Cloudflare URLs
CDN_CATALOG_FILE = GENERATED_IMAGES_DIR / "cdn_catalog.json"


def load_cdn_catalog() -> dict:
    """Load the CDN catalog from disk."""
    if CDN_CATALOG_FILE.exists():
        try:
            return json.loads(CDN_CATALOG_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_cdn_catalog(catalog: dict) -> None:
    """Save the CDN catalog to disk."""
    CDN_CATALOG_FILE.write_text(json.dumps(catalog, indent=2))


def get_cdn_url(filename: str) -> Optional[str]:
    """Get cached CDN URL for a filename, or None if not uploaded."""
    catalog = load_cdn_catalog()
    entry = catalog.get(filename)
    if entry:
        return entry.get("url")
    return None


def set_cdn_url(filename: str, url: str, image_id: str = None) -> None:
    """Store CDN URL for a filename."""
    catalog = load_cdn_catalog()
    catalog[filename] = {
        "url": url,
        "image_id": image_id,
        "uploaded_at": datetime.now().isoformat()
    }
    save_cdn_catalog(catalog)


def remove_cdn_url(filename: str) -> None:
    """Remove CDN URL entry when image is deleted."""
    catalog = load_cdn_catalog()
    if filename in catalog:
        del catalog[filename]
        save_cdn_catalog(catalog)


class ImageInfo(BaseModel):
    """Information about a generated image."""
    name: str
    size: int
    size_human: str
    modified: str
    extension: str


class ImageListResponse(BaseModel):
    """Response for listing images."""
    ok: bool = True
    count: int
    total_size: int
    total_size_human: str
    images: list[ImageInfo]


class ImageBase64Response(BaseModel):
    """Response with base64 image data."""
    ok: bool = True
    name: str
    base64: str
    mime_type: str
    size: int


class DeleteResponse(BaseModel):
    """Response for delete operation."""
    ok: bool
    deleted: Optional[str] = None
    error: Optional[str] = None


class CdnUrlResponse(BaseModel):
    """Response with CDN URL for an image."""
    ok: bool = True
    name: str
    url: Optional[str] = None
    cached: bool = False  # True if URL was already in catalog
    image_id: Optional[str] = None
    error: Optional[str] = None


class CdnCatalogEntry(BaseModel):
    """Entry in the CDN catalog."""
    filename: str
    url: str
    image_id: Optional[str] = None
    uploaded_at: str


class CdnCatalogResponse(BaseModel):
    """Response for CDN catalog listing."""
    ok: bool = True
    count: int
    entries: list[CdnCatalogEntry]


class GenerateRequest(BaseModel):
    """Request to generate or edit an image."""
    prompt: str = Field(..., description="What to generate, or edit instructions when reference_image is provided")
    reference_image: Optional[str] = Field(None, description="Source image to edit. Accepts: stash:// ref, local file path, public URL, or base64 data URI. When provided, edits this image based on the prompt instead of generating from scratch.")
    aspect_ratio: str = Field("square", description="square, landscape, portrait, wide, tall, 16:9, 4:3")
    image_size: str = Field("2K", description="1K, 2K, or 4K")
    style: Optional[str] = Field(None, description="Art style (e.g., 'photorealistic', 'watercolor', 'anime')")
    negative_prompt: Optional[str] = Field(None, description="Things to avoid in the image")
    use_grounding: bool = Field(False, description="Use Google Search for real-time data (Gemini only)")
    provider: Optional[str] = Field(None, description="Override provider: 'gemini', 'openai', or 'xai'")
    transparent: bool = Field(False, description="Transparent background (OpenAI only, png/webp)")
    n: Optional[int] = Field(None, ge=1, le=10, description="Number of images (xAI only, 1-10; forced to 1 when editing)")
    save: bool = Field(True, description="Save to disk and stash")
    mode: str = Field("cloud", description="'cloud' uses cloud.env, 'local' uses local.env")
    upload_to_cdn: bool = Field(False, description="Upload to Cloudflare CDN and return public URL")


class GenerateResponse(BaseModel):
    """Response from image generation."""
    ok: bool
    speech: Optional[str] = None
    error: Optional[str] = None
    data: Optional[dict] = None
    cdn_url: Optional[str] = None  # Populated if upload_to_cdn=True


def format_size(size_bytes: int) -> str:
    """Format bytes to human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def get_image_list() -> tuple[list[ImageInfo], int]:
    """Get list of images with metadata."""
    images = []
    total_size = 0
    
    if GENERATED_IMAGES_DIR.exists():
        for f in GENERATED_IMAGES_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
                stat = f.stat()
                images.append(ImageInfo(
                    name=f.name,
                    size=stat.st_size,
                    size_human=format_size(stat.st_size),
                    modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    extension=f.suffix.lower()
                ))
                total_size += stat.st_size
    
    # Sort by modified date descending
    images.sort(key=lambda x: x.modified, reverse=True)
    return images, total_size


@router.get("", response_model=ImageListResponse)
@router.get("/", response_model=ImageListResponse, include_in_schema=False)
async def list_generated_images(
    limit: int = Query(100, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Skip N results"),
    search: Optional[str] = Query(None, description="Filter by filename")
):
    """
    List all generated images.
    
    Returns image metadata including name, size, and modification date.
    Sorted by newest first.
    
    **Example**:
    ```bash
    curl http://localhost:8880/api/generated-images
    curl http://localhost:8880/api/generated-images?search=robot&limit=10
    ```
    """
    images, total_size = get_image_list()
    
    # Filter by search if provided
    if search:
        search_lower = search.lower()
        images = [img for img in images if search_lower in img.name.lower()]
    
    total = len(images)
    
    # Apply pagination
    images = images[offset:offset + limit]
    
    return ImageListResponse(
        ok=True,
        count=len(images),
        total_size=total_size,
        total_size_human=format_size(total_size),
        images=images
    )


@router.get("/health")
async def generated_images_health():
    """Check generated images directory status."""
    images, total_size = get_image_list()
    
    # Check configured provider
    provider = get_config_value("IMAGE_TOOL_PROVIDER", "gemini")
    model_key = get_media_model_env_key("image", provider)
    model = resolve_media_model(
        "image",
        provider,
        get_config_value(model_key, "") if model_key else "",
    )
    
    return {
        "ok": True,
        "directory": str(GENERATED_IMAGES_DIR),
        "exists": GENERATED_IMAGES_DIR.exists(),
        "image_count": len(images),
        "total_size": total_size,
        "total_size_human": format_size(total_size),
        "configured_provider": provider,
        "configured_model": model,
    }


@router.post("/generate", response_model=GenerateResponse)
async def generate_image(request: GenerateRequest):
    """
    Generate or edit an image using the generate_image tool.
    
    Uses the configured image provider (Gemini, OpenAI, or xAI) based on
    IMAGE_TOOL_PROVIDER in cloud.env or the `provider` override.
    
    **Text-to-Image (generate)**:
    ```bash
    curl -X POST http://localhost:8880/api/generated-images/generate \\
      -H "Content-Type: application/json" \\
      -d '{
        "prompt": "A cute robot dog playing in a park",
        "aspect_ratio": "landscape",
        "image_size": "2K"
      }'
    ```
    
    **Image-to-Image (edit)**:
    ```bash
    curl -X POST http://localhost:8880/api/generated-images/generate \\
      -H "Content-Type: application/json" \\
      -d '{
        "prompt": "Change the dog to a cat, keep everything else",
        "reference_image": "stash://space_xxx/file_id",
        "provider": "xai"
      }'
    ```
    
    `reference_image` accepts: stash:// ref, local file path, public URL,
    or base64 data URI. All 3 providers support editing. Keep edit prompts
    short and direct for best results.
    
    **With CDN upload** (get public URL in one step):
    ```json
    {
      "prompt": "A cute robot dog playing in a park",
      "upload_to_cdn": true
    }
    ```
    """
    try:
        # Build args for generate_image tool
        args = {
            "prompt": request.prompt,
            "aspect_ratio": request.aspect_ratio,
            "image_size": request.image_size,
            "save": request.save,
            "use_grounding": request.use_grounding
        }
        
        if request.reference_image:
            args["reference_image"] = request.reference_image
        if request.style:
            args["style"] = request.style
        if request.negative_prompt:
            args["negative_prompt"] = request.negative_prompt
        if request.provider:
            args["provider"] = request.provider
        if request.transparent:
            args["transparent"] = request.transparent
        if request.n and request.n > 1:
            args["n"] = request.n
        
        # Call generate_image tool
        tool_path = PROJECT_ROOT / "skills" / "generate_image.py"
        
        # Set environment for mode
        import os
        env = os.environ.copy()
        env["JARVIS_MODE"] = request.mode
        
        result = subprocess.run(
            ["python3", str(tool_path), json.dumps(args)],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout for image generation
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
            
            cdn_url = None
            
            # Upload to CDN if requested
            if request.upload_to_cdn and output.get("data", {}).get("saved"):
                saved_info = output["data"]["saved"]
                filename = saved_info.get("filename")
                filepath = saved_info.get("path")
                
                if filename and filepath:
                    try:
                        from upload_cloudflare import upload_image as cf_upload
                        
                        upload_result = cf_upload(
                            str(PROJECT_ROOT / filepath),
                            "file",
                            uploader="api",
                            category="generated"
                        )
                        
                        if upload_result.get("ok"):
                            cdn_url = upload_result.get("url")
                            image_id = upload_result.get("image_id")
                            # Save to catalog
                            set_cdn_url(filename, cdn_url, image_id)
                            # Add to output data
                            output["data"]["cdn"] = {
                                "url": cdn_url,
                                "image_id": image_id
                            }
                    except Exception as e:
                        # CDN upload failed but image was generated - still return success
                        output["data"]["cdn_error"] = str(e)
            
            return GenerateResponse(
                ok=True,
                speech=output.get("speech"),
                error=output.get("error"),
                data=output.get("data"),
                cdn_url=cdn_url
            )
        except json.JSONDecodeError:
            return GenerateResponse(ok=False, error=f"Invalid tool output: {result.stdout[:200]}")
        
    except subprocess.TimeoutExpired:
        return GenerateResponse(ok=False, error="Image generation timed out (5 min limit)")
    except Exception as e:
        return GenerateResponse(ok=False, error=str(e))


@router.get("/cdn-catalog", response_model=CdnCatalogResponse)
async def list_cdn_catalog():
    """
    List all images that have been uploaded to Cloudflare CDN.
    
    Returns the catalog of filename → CDN URL mappings.
    Use this to check if an image has already been uploaded.
    
    **Example**:
    ```bash
    curl http://localhost:8880/api/generated-images/cdn-catalog
    ```
    """
    catalog = load_cdn_catalog()
    entries = []
    
    for filename, data in catalog.items():
        entries.append(CdnCatalogEntry(
            filename=filename,
            url=data.get("url", ""),
            image_id=data.get("image_id"),
            uploaded_at=data.get("uploaded_at", "")
        ))
    
    # Sort by upload date descending
    entries.sort(key=lambda x: x.uploaded_at, reverse=True)
    
    return CdnCatalogResponse(
        ok=True,
        count=len(entries),
        entries=entries
    )


@router.get("/{filename}/cdn-url", response_model=CdnUrlResponse)
async def get_or_create_cdn_url(filename: str):
    """
    Get the Cloudflare CDN URL for an image.
    
    If the image hasn't been uploaded yet, it will be uploaded first.
    Subsequent calls return the cached URL without re-uploading.
    
    **Example**:
    ```bash
    curl http://localhost:8880/api/generated-images/my_image.jpg/cdn-url
    ```
    
    **Response (cached)**:
    ```json
    {
      "ok": true,
      "name": "my_image.jpg",
      "url": "https://imagedelivery.net/xxx/yyy/public",
      "cached": true
    }
    ```
    
    **Response (new upload)**:
    ```json
    {
      "ok": true,
      "name": "my_image.jpg", 
      "url": "https://imagedelivery.net/xxx/yyy/public",
      "cached": false,
      "image_id": "yyy"
    }
    ```
    """
    # Security: prevent path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        return CdnUrlResponse(ok=False, name=filename, error="Invalid filename")
    
    filepath = GENERATED_IMAGES_DIR / filename
    if not filepath.exists():
        return CdnUrlResponse(ok=False, name=filename, error="Image not found")
    
    # Check if already in catalog
    existing_url = get_cdn_url(filename)
    if existing_url:
        catalog = load_cdn_catalog()
        entry = catalog.get(filename, {})
        return CdnUrlResponse(
            ok=True,
            name=filename,
            url=existing_url,
            cached=True,
            image_id=entry.get("image_id")
        )
    
    # Upload to Cloudflare
    try:
        from upload_cloudflare import upload_image as cf_upload
        
        result = cf_upload(
            str(filepath),
            "file",
            uploader="gallery",
            category="generated"
        )
        
        if not result.get("ok"):
            return CdnUrlResponse(
                ok=False,
                name=filename,
                error=result.get("error", "Upload failed")
            )
        
        url = result.get("url")
        image_id = result.get("image_id")
        
        # Save to catalog
        set_cdn_url(filename, url, image_id)
        
        return CdnUrlResponse(
            ok=True,
            name=filename,
            url=url,
            cached=False,
            image_id=image_id
        )
        
    except Exception as e:
        return CdnUrlResponse(ok=False, name=filename, error=str(e))


@router.get("/{filename}")
async def get_generated_image(filename: str):
    """
    Get a generated image file.
    
    Returns the image file directly (not base64).
    
    **Example**:
    ```bash
    curl http://localhost:8880/api/generated-images/my_image.jpg -o my_image.jpg
    ```
    """
    # Security: prevent path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    filepath = GENERATED_IMAGES_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    
    return FileResponse(filepath)


@router.get("/{filename}/base64", response_model=ImageBase64Response)
async def get_generated_image_base64(filename: str):
    """
    Get a generated image as base64.
    
    Useful for APIs that need base64 encoded images.
    
    **Example**:
    ```bash
    curl http://localhost:8880/api/generated-images/my_image.jpg/base64
    ```
    
    **Response**:
    ```json
    {
      "ok": true,
      "name": "my_image.jpg",
      "base64": "data:image/jpeg;base64,/9j/4AAQ...",
      "mime_type": "image/jpeg",
      "size": 123456
    }
    ```
    """
    # Security: prevent path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    filepath = GENERATED_IMAGES_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    
    # Determine mime type
    ext = filepath.suffix.lower()
    mime_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp'
    }
    mime_type = mime_types.get(ext, 'application/octet-stream')
    
    # Read and encode
    data = filepath.read_bytes()
    b64 = base64.b64encode(data).decode('utf-8')
    
    return ImageBase64Response(
        ok=True,
        name=filename,
        base64=f"data:{mime_type};base64,{b64}",
        mime_type=mime_type,
        size=len(data)
    )


@router.delete("/{filename}", response_model=DeleteResponse)
async def delete_generated_image(filename: str):
    """
    Delete a generated image.
    
    **Example**:
    ```bash
    curl -X DELETE http://localhost:8880/api/generated-images/my_image.jpg
    ```
    """
    # Security: prevent path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        return DeleteResponse(ok=False, error="Invalid filename")
    
    filepath = GENERATED_IMAGES_DIR / filename
    if not filepath.exists():
        return DeleteResponse(ok=False, error="Image not found")
    
    try:
        filepath.unlink()
        # Also remove from CDN catalog if present
        remove_cdn_url(filename)
        return DeleteResponse(ok=True, deleted=filename)
    except Exception as e:
        return DeleteResponse(ok=False, error=str(e))
