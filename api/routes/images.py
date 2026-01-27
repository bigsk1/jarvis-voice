"""
Images API routes - Upload images to Cloudflare CDN.

This endpoint allows external systems (like Samantha) to upload images
and get back permanent CDN URLs, avoiding base64 size issues.

!! PRIVACY WARNING !!
=====================
Uploaded images are PUBLICLY ACCESSIBLE to anyone with the URL.
The API is IP-whitelisted but the resulting image URLs are not.

DO NOT UPLOAD: screenshots, personal photos, documents, anything with
passwords/API keys/private data, medical/financial/legal documents.

SAFE TO UPLOAD: AI-generated artwork, status visuals, diagrams,
shareable infographics, public content meant for distribution.
"""
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# Add lib and skills to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'lib'))
sys.path.insert(0, str(PROJECT_ROOT / 'skills'))

from config_loader import load_config, get_config_value

# Load config from correct env file (local.env or cloud.env based on JARVIS_MODE)
load_config()

router = APIRouter(prefix="/api/images", tags=["images"])


class ImageUploadRequest(BaseModel):
    """Request to upload an image to Cloudflare CDN."""
    source: str = Field(..., description="Image source: file path, URL, base64 data, or stash://reference")
    source_type: str = Field("auto", description="Source type: auto, file, url, base64, stash")
    uploader: str = Field("api", description="Who is uploading (jarvis, samantha, api) - for path organization")
    category: str | None = Field(None, description="Category (status, generated, stash) - auto-detected if not provided")
    prompt: str | None = Field(None, description="Prompt used to generate the image (stored as metadata)")
    tags: list[str] | None = Field(None, description="Tags for the image (stored as metadata)")
    provider: str | None = Field(None, description="Image provider (gemini, openai, etc)")


class ImageUploadResponse(BaseModel):
    """Response from image upload."""
    ok: bool = True
    url: str | None = None
    image_id: str | None = None
    custom_path: str | None = None
    filename: str | None = None
    source_type: str | None = None
    uploader: str | None = None
    error: str | None = None


@router.post("", response_model=ImageUploadResponse)
@router.post("/", response_model=ImageUploadResponse, include_in_schema=False)
async def upload_image(request: ImageUploadRequest):
    """
    Upload an image to Cloudflare Images CDN.
    
    Returns a permanent CDN URL that can be used anywhere.
    
    **⚠️ PRIVACY WARNING**: Uploaded images are PUBLICLY ACCESSIBLE to anyone 
    with the URL. Do NOT upload screenshots, personal photos, documents, or 
    anything containing private information. Use only for AI-generated artwork, 
    diagrams, and shareable content.
    
    **Sources supported**:
    - `file`: Local file path (e.g., "data/generated_images/image.jpg")
    - `url`: HTTP/HTTPS URL to download and upload
    - `base64`: Base64 encoded image data (with or without data:image prefix)
    - `stash`: Stash reference (e.g., "stash://space_20260127_123456/f_abc123")
    
    **Example**:
    ```bash
    curl -X POST http://localhost:8880/api/images \\
      -H "Content-Type: application/json" \\
      -d '{
        "source": "https://example.com/image.jpg",
        "source_type": "url"
      }'
    ```
    
    **Response**:
    ```json
    {
      "ok": true,
      "url": "https://imagedelivery.net/xxx/yyy/public",
      "image_id": "yyy",
      "source_type": "url"
    }
    ```
    
    **Base64 example** (for generated images):
    ```json
    {
      "source": "data:image/png;base64,iVBORw0KGgo...",
      "source_type": "base64"
    }
    ```
    """
    try:
        from upload_cloudflare import upload_image as cf_upload
        
        # Build metadata from request fields
        metadata = {}
        if request.prompt:
            metadata['prompt'] = request.prompt
        if request.tags:
            metadata['tags'] = request.tags
        if request.provider:
            metadata['provider'] = request.provider
        
        result = cf_upload(
            request.source, 
            request.source_type,
            uploader=request.uploader,
            category=request.category,
            metadata=metadata if metadata else None
        )
        
        return ImageUploadResponse(
            ok=result.get("ok", False),
            url=result.get("url"),
            image_id=result.get("image_id"),
            custom_path=result.get("custom_path"),
            filename=result.get("filename"),
            source_type=result.get("source_type"),
            uploader=result.get("uploader"),
            error=result.get("error")
        )
        
    except Exception as e:
        return ImageUploadResponse(
            ok=False,
            error=str(e)
        )


@router.post("/base64", response_model=ImageUploadResponse)
async def upload_base64_image(data: dict):
    """
    Convenience endpoint for base64 uploads.
    
    **Request**:
    ```json
    {
      "image": "data:image/png;base64,iVBORw0KGgo...",
      "filename": "my_image.png",  // optional
      "uploader": "samantha",      // optional, default: api
      "category": "generated",     // optional, auto-detected
      "prompt": "A cute robot",    // optional, stored as metadata
      "tags": ["ai", "robot"],     // optional, stored as metadata
      "provider": "gemini"         // optional, stored as metadata
    }
    ```
    
    This is a simpler endpoint for Samantha to upload generated images
    without needing to specify source_type.
    """
    base64_data = data.get("image") or data.get("base64") or data.get("data")
    
    if not base64_data:
        return ImageUploadResponse(
            ok=False,
            error="Missing 'image' or 'base64' field with base64 image data"
        )
    
    uploader = data.get("uploader", "api")
    category = data.get("category", "generated")
    
    # Build metadata from request
    metadata = {}
    if data.get("prompt"):
        metadata['prompt'] = data.get("prompt")
    if data.get("tags"):
        metadata['tags'] = data.get("tags")
    if data.get("provider"):
        metadata['provider'] = data.get("provider")
    if data.get("filename"):
        metadata['original_filename'] = data.get("filename")
    
    try:
        from upload_cloudflare import upload_image as cf_upload
        
        result = cf_upload(base64_data, "base64", uploader=uploader, category=category, metadata=metadata if metadata else None)
        
        return ImageUploadResponse(
            ok=result.get("ok", False),
            url=result.get("url"),
            image_id=result.get("image_id"),
            custom_path=result.get("custom_path"),
            filename=data.get("filename") or result.get("filename"),
            source_type="base64",
            uploader=result.get("uploader"),
            error=result.get("error")
        )
        
    except Exception as e:
        return ImageUploadResponse(
            ok=False,
            error=str(e)
        )


@router.get("/health")
async def images_health():
    """Check if Cloudflare credentials are configured."""
    api_token = get_config_value("CLOUDFLARE_API_TOKEN", "")
    account_id = get_config_value("CLOUDFLARE_ACCOUNT_ID", "")
    
    return {
        "ok": bool(api_token and account_id),
        "api_token_configured": bool(api_token),
        "account_id_configured": bool(account_id)
    }
