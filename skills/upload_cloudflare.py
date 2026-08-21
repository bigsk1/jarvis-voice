#!/usr/bin/env python3
"""
Upload images to Cloudflare Images CDN.

Accepts images from:
- File path (local file, stash, generated_images)
- URL (download and upload)
- Base64 encoded data
- Stash reference (stash://space_id/file_id)

Returns a permanent Cloudflare CDN URL like:
https://imagedelivery.net/{account_hash}/{image_id}/public

!! PRIVACY WARNING !!
=====================
Uploaded images are PUBLICLY ACCESSIBLE to anyone with the URL.
The API is IP-whitelisted but the resulting image URLs are not.

DO NOT UPLOAD:
- Screenshots (may contain sensitive info)
- Personal photos
- Documents or PDFs
- Anything with passwords, API keys, or private data
- Medical, financial, or legal documents

SAFE TO UPLOAD:
- AI-generated artwork and images
- Status visuals and diagrams
- Shareable infographics
- Public content meant for distribution

Environment variables required:
- CLOUDFLARE_API_TOKEN
- CLOUDFLARE_ACCOUNT_ID
"""

import sys
import os
import json
import base64
import tempfile
from pathlib import Path
from urllib.parse import quote

import requests

# Add lib to path for config_loader and stash helper
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

from config_loader import load_config, get_config_value
from paths import assert_not_restricted_read_path
from stash_helper import get_stash_dir, parse_stash_ref

# Load config from correct env file (local.env or cloud.env based on JARVIS_MODE)
load_config()

# Configuration from loaded environment
CLOUDFLARE_API_TOKEN = get_config_value("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_ACCOUNT_ID = get_config_value("CLOUDFLARE_ACCOUNT_ID", "")

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
GENERATED_IMAGES_DIR = PROJECT_ROOT / "data" / "generated_images"

# Supported image formats (per Cloudflare docs)
SUPPORTED_FORMATS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.heic'}


def generate_custom_id(uploader: str, filename: str, category: str = None) -> str:
    """
    Generate a custom ID path for organizing images in Cloudflare.
    
    Format: {uploader}/{date}/{category_or_filename}
    Example: jarvis/2026-01-27/status_visual_abc123
    
    Args:
        uploader: Who uploaded (jarvis, samantha, api, etc.)
        filename: Original filename
        category: Optional category (status, generated, stash, etc.)
        
    Returns:
        Custom ID string for Cloudflare
    """
    from datetime import datetime
    import hashlib
    
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    # Clean filename - remove extension and sanitize
    name = Path(filename).stem
    # Remove common prefixes
    for prefix in ['generated_', 'image_', 'img_']:
        if name.lower().startswith(prefix):
            name = name[len(prefix):]
    
    # Truncate long names and add short hash for uniqueness
    if len(name) > 50:
        name = name[:50]
    
    # Add short hash for uniqueness
    hash_input = f"{filename}{datetime.now().isoformat()}"
    short_hash = hashlib.md5(hash_input.encode()).hexdigest()[:8]
    
    # Build path
    if category:
        custom_id = f"{uploader}/{date_str}/{category}/{name}_{short_hash}"
    else:
        custom_id = f"{uploader}/{date_str}/{name}_{short_hash}"
    
    # Ensure valid characters (replace spaces with underscores)
    custom_id = custom_id.replace(' ', '_')
    
    return custom_id


def upload_to_cloudflare(file_path: str, custom_id: str = None, uploader: str = "jarvis", category: str = None, metadata: dict = None) -> dict:
    """
    Upload a local file to Cloudflare Images.
    
    Args:
        file_path: Path to local image file
        custom_id: Optional custom ID/path for the image
        uploader: Who is uploading (jarvis, samantha, api) - used for auto-generated paths
        category: Optional category (status, generated, stash) - used for auto-generated paths
        metadata: Optional metadata dict to store with the image (not exposed to end users)
        
    Returns:
        dict with 'ok', 'url', 'image_id', etc.
    """
    if not CLOUDFLARE_API_TOKEN:
        return {
            "ok": False,
            "error": "CLOUDFLARE_API_TOKEN not configured",
            "hint": "Add CLOUDFLARE_API_TOKEN to cloud.env"
        }
    
    if not CLOUDFLARE_ACCOUNT_ID:
        return {
            "ok": False,
            "error": "CLOUDFLARE_ACCOUNT_ID not configured",
            "hint": "Add CLOUDFLARE_ACCOUNT_ID to cloud.env"
        }
    
    if not os.path.exists(file_path):
        return {
            "ok": False,
            "error": f"File not found: {file_path}"
        }
    
    # Generate custom ID if not provided
    filename = os.path.basename(file_path)
    if not custom_id:
        custom_id = generate_custom_id(uploader, filename, category)
    
    # Build metadata - Cloudflare stores this but never exposes to end users
    from datetime import datetime
    upload_metadata = {
        "uploader": uploader,
        "uploaded_at": datetime.now().isoformat(),
        "original_filename": filename,
        "category": category or "unknown"
    }
    # Merge with any provided metadata
    if metadata:
        upload_metadata.update(metadata)
    
    headers = {
        'Authorization': f'Bearer {CLOUDFLARE_API_TOKEN}',
    }
    
    url = f'https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/images/v1'
    
    try:
        with open(file_path, 'rb') as f:
            files = {'file': (filename, f)}
            # Include custom ID and metadata in the form data
            data = {
                'id': custom_id,
                'metadata': json.dumps(upload_metadata)
            }
            response = requests.post(url, headers=headers, files=files, data=data, timeout=60)
            response.raise_for_status()
            
            resp_data = response.json()
            
            if resp_data.get('success'):
                result = resp_data.get('result', {})
                variants = result.get('variants', [])
                # Get the public variant URL
                public_url = next((v for v in variants if '/public' in v), variants[0] if variants else None)
                
                return {
                    "ok": True,
                    "url": public_url,
                    "image_id": result.get('id'),
                    "custom_path": custom_id,
                    "filename": result.get('filename'),
                    "variants": variants,
                    "uploader": uploader,
                    "speech": f"Image uploaded to Cloudflare CDN"
                }
            else:
                errors = resp_data.get('errors', [])
                return {
                    "ok": False,
                    "error": errors[0].get('message') if errors else "Upload failed",
                    "details": errors
                }
                
    except requests.exceptions.Timeout:
        return {
            "ok": False,
            "error": "Upload timed out after 60 seconds"
        }
    except requests.exceptions.RequestException as e:
        return {
            "ok": False,
            "error": f"Upload failed: {str(e)}"
        }


def delete_from_cloudflare(image_id: str) -> dict:
    """Permanently delete a Cloudflare Images asset by its cataloged ID."""
    image_id = str(image_id or '').strip()
    if not image_id:
        return {"ok": False, "error": "Cloudflare image ID is required"}
    if not CLOUDFLARE_API_TOKEN:
        return {"ok": False, "error": "CLOUDFLARE_API_TOKEN not configured"}
    if not CLOUDFLARE_ACCOUNT_ID:
        return {"ok": False, "error": "CLOUDFLARE_ACCOUNT_ID not configured"}

    headers = {'Authorization': f'Bearer {CLOUDFLARE_API_TOKEN}'}
    encoded_image_id = quote(image_id, safe='')
    url = (
        f'https://api.cloudflare.com/client/v4/accounts/'
        f'{CLOUDFLARE_ACCOUNT_ID}/images/v1/{encoded_image_id}'
    )

    try:
        response = requests.delete(url, headers=headers, timeout=30)
        try:
            response_data = response.json()
        except ValueError:
            response_data = {}

        if not response.ok or not response_data.get('success', False):
            errors = response_data.get('errors') or []
            message = errors[0].get('message') if errors and isinstance(errors[0], dict) else None
            return {
                "ok": False,
                "error": message or f"Cloudflare delete failed ({response.status_code})",
                "status_code": response.status_code,
            }

        return {
            "ok": True,
            "image_id": image_id,
        }
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "Cloudflare delete timed out after 30 seconds"}
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": f"Cloudflare delete failed: {str(e)}"}


def resolve_stash_path(stash_ref: str) -> str | None:
    """
    Resolve a stash:// reference to a local file path.
    
    Args:
        stash_ref: e.g., "stash://space_20260127_095852_abc123/f_12345"
        
    Returns:
        Local file path or None if not found
    """
    try:
        space_id, file_id = parse_stash_ref(stash_ref)
        if not space_id or not file_id:
            return None

        stash_dir = get_stash_dir()
        # Load space metadata
        meta_path = stash_dir / space_id / 'meta.json'
        if not meta_path.exists():
            return None
        
        with open(meta_path) as f:
            meta = json.load(f)
        
        # Find file by ID
        for file_info in meta.get('files', []):
            if file_info.get('file_id') == file_id:
                return str(stash_dir / space_id / file_info.get('stored_name'))
        
        return None
    except Exception:
        return None


def download_from_url(url: str) -> str | None:
    """
    Download an image from URL to a temp file.
    
    Returns:
        Path to temp file or None on failure
    """
    temp_path = None
    try:
        response = requests.get(url, timeout=30, stream=True)
        response.raise_for_status()
        
        # Determine extension from content-type or URL
        content_type = response.headers.get('content-type', '')
        if 'png' in content_type:
            ext = '.png'
        elif 'gif' in content_type:
            ext = '.gif'
        elif 'webp' in content_type:
            ext = '.webp'
        else:
            ext = '.jpg'
        
        # Create temp file
        fd, temp_path = tempfile.mkstemp(suffix=ext)
        with os.fdopen(fd, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return temp_path
    except Exception:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        return None


def decode_base64_to_file(base64_data: str) -> str | None:
    """
    Decode base64 image data to a temp file.
    
    Args:
        base64_data: Base64 encoded image (with or without data:image prefix)
        
    Returns:
        Path to temp file or None on failure
    """
    temp_path = None
    try:
        # Strip data URL prefix if present
        if base64_data.startswith('data:'):
            # Format: data:image/png;base64,XXXXX
            header, base64_data = base64_data.split(',', 1)
            if 'png' in header:
                ext = '.png'
            elif 'gif' in header:
                ext = '.gif'
            elif 'webp' in header:
                ext = '.webp'
            else:
                ext = '.jpg'
        else:
            ext = '.jpg'
        
        # Decode
        image_data = base64.b64decode(base64_data)
        
        # Create temp file
        fd, temp_path = tempfile.mkstemp(suffix=ext)
        with os.fdopen(fd, 'wb') as f:
            f.write(image_data)
        
        return temp_path
    except Exception:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        return None


def get_stash_metadata(stash_ref: str) -> dict | None:
    """
    Get metadata from a stash reference.
    
    Args:
        stash_ref: e.g., "stash://space_20260127_095852_abc123/f_12345"
        
    Returns:
        Metadata dict or None if not found
    """
    try:
        space_id, file_id = parse_stash_ref(stash_ref)
        if not space_id or not file_id:
            return None

        stash_dir = get_stash_dir()
        # Load space metadata
        meta_path = stash_dir / space_id / 'meta.json'
        if not meta_path.exists():
            return None
        
        with open(meta_path) as f:
            meta = json.load(f)
        
        # Find file by ID and return its metadata
        for file_info in meta.get('files', []):
            if file_info.get('file_id') == file_id:
                return {
                    "stash_ref": stash_ref,
                    "space_id": space_id,
                    "filename": file_info.get('original_name'),
                    "prompt": file_info.get('prompt'),
                    "provider": file_info.get('provider'),
                    "tags": file_info.get('tags', []),
                    "type": file_info.get('type')
                }
        
        return None
    except Exception:
        return None


def upload_image(source: str, source_type: str = "auto", uploader: str = "jarvis", category: str = None, custom_id: str = None, metadata: dict = None) -> dict:
    """
    Upload an image to Cloudflare from various sources.
    
    Args:
        source: File path, URL, base64 data, or stash reference
        source_type: "file", "url", "base64", "stash", or "auto" (detect)
        uploader: Who is uploading - "jarvis", "samantha", "api" (for path organization)
        category: Optional category - "status", "generated", "stash", etc.
        custom_id: Optional full custom ID/path (overrides auto-generation)
        metadata: Optional metadata dict (prompt, tags, provider, etc.)
        
    Returns:
        dict with 'ok', 'url', 'image_id', 'custom_path', etc.
    """
    temp_file = None
    detected_category = category
    upload_metadata = metadata.copy() if metadata else {}
    
    try:
        # Auto-detect source type
        if source_type == "auto":
            if source.startswith('stash://'):
                source_type = "stash"
            elif source.startswith(('http://', 'https://')):
                source_type = "url"
            elif source.startswith('data:') or (len(source) > 1000 and '/' not in source):
                source_type = "base64"
            else:
                source_type = "file"
        
        # Add source info to metadata
        upload_metadata['source_type'] = source_type
        if source_type == "url":
            upload_metadata['source_url'] = source
        
        # Auto-detect category if not provided
        if not detected_category:
            if source_type == "stash":
                detected_category = "stash"
            elif source_type == "base64":
                detected_category = "generated"
            elif "generated_images" in source or source.startswith("generated_"):
                detected_category = "generated"
            elif "status" in source.lower():
                detected_category = "status"
        
        # Resolve source to local file path
        if source_type == "stash":
            file_path = resolve_stash_path(source)
            if not file_path:
                return {
                    "ok": False,
                    "error": f"Could not resolve stash reference: {source}"
                }
            # Get metadata from stash
            stash_meta = get_stash_metadata(source)
            if stash_meta:
                # Stash metadata takes precedence but can be overridden
                for key, value in stash_meta.items():
                    if key not in upload_metadata and value:
                        upload_metadata[key] = value
        
        elif source_type == "url":
            temp_file = download_from_url(source)
            if not temp_file:
                return {
                    "ok": False,
                    "error": f"Could not download image from URL: {source}"
                }
            file_path = temp_file
        
        elif source_type == "base64":
            temp_file = decode_base64_to_file(source)
            if not temp_file:
                return {
                    "ok": False,
                    "error": "Could not decode base64 image data"
                }
            file_path = temp_file
        
        else:  # file
            file_path = source
            # Check if it's a relative path in generated_images
            if not os.path.isabs(source):
                # Try generated_images first
                gen_path = GENERATED_IMAGES_DIR / source
                if gen_path.exists():
                    file_path = str(gen_path)
                    if not detected_category:
                        detected_category = "generated"
                # Try stash directories
                elif not os.path.exists(source):
                    for space_dir in get_stash_dir().iterdir():
                        if space_dir.is_dir():
                            potential = space_dir / source
                            if potential.exists():
                                file_path = str(potential)
                                if not detected_category:
                                    detected_category = "stash"
                                break
        
        # Enforce the local read boundary after every source type has resolved.
        # This also follows symlinks before checking the restricted trees.
        file_path = str(assert_not_restricted_read_path(file_path, label="Upload source"))

        # Upload to Cloudflare with custom path and metadata
        result = upload_to_cloudflare(
            file_path, 
            custom_id=custom_id, 
            uploader=uploader, 
            category=detected_category,
            metadata=upload_metadata
        )
        result['source_type'] = source_type
        
        return result
        
    finally:
        # Clean up temp file
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print(json.dumps({
            "ok": False,
            "error": "Usage: upload_cloudflare.py <source> [source_type]",
            "hint": "source can be: file path, URL, base64, or stash://reference",
            "parameters": {
                "source": "Image source (required)",
                "source_type": "auto|file|url|base64|stash",
                "uploader": "jarvis|samantha|api (default: jarvis)",
                "category": "status|generated|stash|etc (auto-detected)",
                "custom_id": "Full custom path (optional, overrides auto)"
            }
        }))
        sys.exit(1)
    
    try:
        args = json.loads(sys.argv[1])
        source = args.get('source')
        source_type = args.get('source_type', 'auto')
        uploader = args.get('uploader', 'jarvis')
        category = args.get('category')
        custom_id = args.get('custom_id')
        metadata = args.get('metadata', {})
        # Allow passing prompt/tags directly as convenience
        if args.get('prompt'):
            metadata['prompt'] = args.get('prompt')
        if args.get('tags'):
            metadata['tags'] = args.get('tags')
        if args.get('provider'):
            metadata['provider'] = args.get('provider')
    except json.JSONDecodeError:
        # Plain string argument
        source = sys.argv[1]
        source_type = sys.argv[2] if len(sys.argv) > 2 else 'auto'
        uploader = 'jarvis'
        category = None
        custom_id = None
        metadata = {}
    
    if not source:
        print(json.dumps({
            "ok": False,
            "error": "source is required"
        }))
        sys.exit(1)
    
    result = upload_image(source, source_type, uploader=uploader, category=category, custom_id=custom_id, metadata=metadata)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
