#!/usr/bin/env python3
"""
Analyze Image Tool - Vision analysis for images from various sources.

Accepts:
- URL: Direct image URL from the web
- Local file path: Path to image on disk  
- Stash reference: stash://space_id/file_id format

Returns vision model analysis of the image content.
"""

import sys
import json
import base64
import io
from pathlib import Path
from datetime import datetime

# Add lib to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
from config_loader import load_config, get_config_value
from paths import get_local_file_tool_allowed_dirs

MAX_VISION_IMAGE_DIMENSION = 1568
MAX_VISION_IMAGE_BYTES = 4 * 1024 * 1024
JPEG_QUALITY_START = 88
JPEG_QUALITY_MIN = 60


def _debug(msg: str):
    """Print debug message to stderr (not stdout, to avoid breaking JSON output)."""
    print(msg, file=sys.stderr)


def analyze_image(
    image: str = None,
    question: str = "Describe this image in detail.",
    stash_after: bool = False,
    images: list = None,
) -> dict:
    """
    Analyze an image using vision model.
    
    Args:
        image: Image source - can be:
            - URL (https://...)
            - Local file path (/path/to/image.jpg or ~/images/photo.png)
            - Stash reference (stash://space_id/file_id)
        question: What to ask about the image (default: general description)
        stash_after: If True and image is from URL, save to stash for future access
        images: Optional list of image sources for multi-image analysis
        
    Returns:
        dict with analysis results, image info, and optional stash reference
    """
    # Load config (already loaded by orchestrator, but ensure it's there)
    load_config()
    
    # Determine mode from environment
    mode = get_config_value('JARVIS_MODE', 'cloud')
    
    from vision_multimodal import max_vision_images

    try:
        sources = []
        if images:
            if isinstance(images, str):
                sources = [images]
            else:
                sources = [src for src in images if src]
        elif image:
            sources = [image]

        if not sources:
            return {
                "ok": False,
                "speech": "No image source provided.",
                "data": {"error": "Missing image source"}
            }
        
        image_limit = max_vision_images(mode)
        if len(sources) > image_limit:
            return {
                "ok": False,
                "speech": f"Maximum {image_limit} images allowed in {mode} mode.",
                "data": {"error": "Too many images", "limit": image_limit, "provided": len(sources)}
            }

        resolved_images = []
        for source in sources:
            resolved = _resolve_image(source)
            if not resolved:
                return {
                    "ok": False,
                    "speech": f"Could not load image from: {source[:50]}...",
                    "data": {"error": "Failed to load image", "source": source}
                }
            resolved_images.append(resolved)

        images_base64 = [item['base64'] for item in resolved_images if item.get('base64')]
        analysis = _analyze_with_vision(images_base64, question, mode)
        
        if not analysis:
            return {
                "ok": False,
                "speech": "Vision analysis failed.",
                "data": {"error": "Vision model returned no result"}
            }
        
        # Optionally stash URL-sourced images
        stash_results = []
        if stash_after:
            for resolved in resolved_images:
                if resolved.get('source_type') == 'url':
                    stashed = _stash_image(resolved, analysis, mode)
                    if stashed:
                        stash_results.append(stashed)
        
        # Build response
        # Create short speech version
        short_analysis = analysis[:150] + "..." if len(analysis) > 150 else analysis
        
        response_data = {
            "analysis": analysis,
            "source_count": len(resolved_images),
            "sources": [item.get('original_path') for item in resolved_images],
        }

        if len(resolved_images) == 1:
            primary = resolved_images[0]
            response_data["source"] = primary.get('source_type')
            response_data["original_path"] = primary.get('original_path')
            for field in (
                'filename',
                'mime_type',
                'size_bytes',
                'processed_size_bytes',
                'original_width',
                'original_height',
                'processed_width',
                'processed_height',
                'resized_for_vision',
                'recompressed_for_vision',
            ):
                if field in primary:
                    response_data[field] = primary[field]

        if stash_results:
            response_data["stash"] = stash_results[0]
            response_data["stash_ref"] = stash_results[0].get('stash_ref')
            if len(stash_results) > 1:
                response_data["stash_refs"] = [item.get('stash_ref') for item in stash_results if item.get('stash_ref')]
        
        return {
            "ok": True,
            "speech": short_analysis,
            "data": response_data
        }
        
    except Exception as e:
        return {
            "ok": False,
            "speech": f"Error analyzing image: {str(e)[:100]}",
            "data": {"error": str(e), "source": image or images}
        }


def _resolve_image(image: str) -> dict | None:
    """
    Resolve image source to base64 data.
    
    Returns dict with:
        - base64: Image data
        - source_type: 'url', 'file', or 'stash'
        - original_path: Original input
        - filename: Extracted or generated filename
    """
    image = image.strip()
    
    # Check if stash reference
    if image.startswith('stash://'):
        return _load_from_stash(image)
    
    # Check if URL
    if image.startswith('http://') or image.startswith('https://'):
        return _load_from_url(image)
    
    # Assume local file path
    return _load_from_file(image)


def _load_from_url(url: str) -> dict | None:
    """Download image from URL safely with SSRF protection."""
    try:
        # Use stash_helper's safe_download which includes:
        # - URL validation (scheme, hostname)
        # - SSRF protection (blocks private IPs)
        # - Safe redirect handling
        # - Size limits
        from stash_helper import safe_download, sanitize_filename, SecurityError
        
        try:
            image_bytes, content_type, final_url = safe_download(url, max_size=20*1024*1024)  # 20MB limit
        except SecurityError as sec_err:
            _debug(f"[ANALYZE_IMAGE] Security error downloading URL: {sec_err}")
            return None
        
        # Check content type
        if not content_type.startswith('image/'):
            _debug(f"[ANALYZE_IMAGE] URL content-type is not image: {content_type}")
            # Try anyway - some servers don't set correct content-type
        
        image_data, image_info = _prepare_image_for_vision(image_bytes, content_type)
        
        # Extract and sanitize filename from URL
        from urllib.parse import urlparse
        parsed = urlparse(final_url)
        raw_filename = Path(parsed.path).name or f"image_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        filename = sanitize_filename(raw_filename)
        
        return {
            'base64': image_data,
            'source_type': 'url',
            'original_path': url,
            'filename': filename,
            'size_bytes': len(image_bytes),
            **image_info
        }
    except Exception as e:
        _debug(f"[ANALYZE_IMAGE] Failed to load URL {url}: {e}")
        return None


def _load_from_file(path: str) -> dict | None:
    """Load image from local file path."""
    try:
        # Expand user home directory
        file_path = Path(path).expanduser().resolve()
        
        # SECURITY: Restrict file access to allowed directories
        ALLOWED_DIRS = get_local_file_tool_allowed_dirs(include_pictures=True)
        
        # Check if file is in an allowed directory
        file_allowed = False
        for allowed in ALLOWED_DIRS:
            try:
                file_path.relative_to(allowed)
                file_allowed = True
                break
            except ValueError:
                continue
        
        if not file_allowed:
            _debug(f"[ANALYZE_IMAGE] Path not in allowed directories: {file_path}")
            return None
        
        if not file_path.exists():
            _debug(f"[ANALYZE_IMAGE] File not found: {file_path}")
            return None
        
        if not file_path.is_file():
            _debug(f"[ANALYZE_IMAGE] Not a file: {file_path}")
            return None
        
        # Check file size (limit to 20MB)
        size = file_path.stat().st_size
        if size > 20 * 1024 * 1024:
            _debug(f"[ANALYZE_IMAGE] File too large: {size} bytes")
            return None
        
        with open(file_path, 'rb') as f:
            image_bytes = f.read()
        mime_type = _guess_mime_type(file_path)
        image_data, image_info = _prepare_image_for_vision(image_bytes, mime_type)
        
        return {
            'base64': image_data,
            'source_type': 'file',
            'original_path': str(file_path),
            'filename': file_path.name,
            'size_bytes': size,
            **image_info
        }
    except Exception as e:
        _debug(f"[ANALYZE_IMAGE] Failed to load file {path}: {e}")
        return None


def _load_from_stash(stash_ref: str) -> dict | None:
    """Load image from stash reference."""
    try:
        # Parse stash://space_id/file_id
        parts = stash_ref.replace('stash://', '').split('/')
        if len(parts) != 2:
            _debug(f"[ANALYZE_IMAGE] Invalid stash ref format: {stash_ref}")
            return None
        
        space_id, file_id = parts
        
        # Find stash space using stash_helper's path resolution
        from stash_helper import get_stash_dir
        stash_root = get_stash_dir()
        space_path = stash_root / space_id
        _debug(f"[ANALYZE_IMAGE] Looking for stash at: {space_path}")
        
        if not space_path.exists():
            _debug(f"[ANALYZE_IMAGE] Stash space not found: {space_id}")
            return None
        
        # Load space metadata to find file
        meta_path = space_path / 'meta.json'
        if not meta_path.exists():
            _debug(f"[ANALYZE_IMAGE] Stash meta not found: {meta_path}")
            return None
        
        import json
        with open(meta_path) as f:
            meta = json.load(f)
        
        # Find file in space
        file_meta = None
        for f in meta.get('files', []):
            if f.get('file_id') == file_id:
                file_meta = f
                break
        
        if not file_meta:
            _debug(f"[ANALYZE_IMAGE] File not found in stash: {file_id}")
            return None
        
        # Load the actual file
        stored_name = file_meta.get('stored_name', file_meta.get('name'))
        file_path = space_path / stored_name
        
        if not file_path.exists():
            _debug(f"[ANALYZE_IMAGE] Stash file missing: {file_path}")
            return None
        
        with open(file_path, 'rb') as f:
            image_bytes = f.read()
        mime_type = file_meta.get('mime_type') or _guess_mime_type(file_path)
        image_data, image_info = _prepare_image_for_vision(image_bytes, mime_type)
        
        return {
            'base64': image_data,
            'source_type': 'stash',
            'original_path': stash_ref,
            'filename': stored_name,
            'size_bytes': file_path.stat().st_size,
            'stash_meta': file_meta,
            **image_info
        }
    except Exception as e:
        _debug(f"[ANALYZE_IMAGE] Failed to load from stash {stash_ref}: {e}")
        return None


def _guess_mime_type(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix in ('.jpg', '.jpeg'):
        return 'image/jpeg'
    if suffix == '.png':
        return 'image/png'
    if suffix == '.webp':
        return 'image/webp'
    if suffix == '.gif':
        return 'image/gif'
    return 'image/jpeg'


def _prepare_image_for_vision(image_bytes: bytes, mime_type: str = 'image/jpeg') -> tuple[str, dict]:
    """
    Convert images into a bounded JPEG payload for vision APIs.

    Browser uploads are already resized on /api/upload-image, but follow-up
    stash refs, URLs, and local files can be much larger. Keep the visual
    content while avoiding provider payload limits.
    """
    from PIL import Image, ImageOps

    original_bytes = len(image_bytes)
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            original_width, original_height = img.size
            resized = False

            if img.mode not in ('RGB', 'L'):
                bg = Image.new('RGB', img.size, (255, 255, 255))
                if 'A' in img.getbands():
                    bg.paste(img, mask=img.getchannel('A'))
                    img = bg
                else:
                    img = img.convert('RGB')
            elif img.mode == 'L':
                img = img.convert('RGB')

            longest = max(img.size)
            if longest > MAX_VISION_IMAGE_DIMENSION:
                scale = MAX_VISION_IMAGE_DIMENSION / longest
                new_size = (
                    max(1, int(img.size[0] * scale)),
                    max(1, int(img.size[1] * scale)),
                )
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                resized = True

            quality = JPEG_QUALITY_START
            while True:
                buffer = io.BytesIO()
                img.save(buffer, format='JPEG', quality=quality, optimize=True)
                processed_bytes = buffer.getvalue()
                if len(processed_bytes) <= MAX_VISION_IMAGE_BYTES or quality <= JPEG_QUALITY_MIN:
                    break
                quality -= 8

            if resized or len(processed_bytes) != original_bytes:
                _debug(
                    "[ANALYZE_IMAGE] Prepared image for vision: "
                    f"{original_width}x{original_height}/{original_bytes} bytes -> "
                    f"{img.size[0]}x{img.size[1]}/{len(processed_bytes)} bytes, quality={quality}"
                )

            return base64.b64encode(processed_bytes).decode('utf-8'), {
                'mime_type': 'image/jpeg',
                'original_width': original_width,
                'original_height': original_height,
                'processed_width': img.size[0],
                'processed_height': img.size[1],
                'processed_size_bytes': len(processed_bytes),
                'resized_for_vision': resized,
                'recompressed_for_vision': len(processed_bytes) != original_bytes,
            }
    except Exception as e:
        _debug(f"[ANALYZE_IMAGE] PIL preprocessing failed, using original bytes: {e}")
        return base64.b64encode(image_bytes).decode('utf-8'), {
            'mime_type': mime_type or 'image/jpeg',
            'processed_size_bytes': original_bytes,
            'resized_for_vision': False,
            'recompressed_for_vision': False,
        }


def _sanitize_vision_prompt(question: str) -> str:
    """
    Sanitize vision prompt to prevent injection.
    Removes obvious injection patterns but allows legitimate questions.
    """
    if not question:
        return "Describe this image in detail."
    
    # Limit length
    if len(question) > 1000:
        question = question[:1000]
    
    # Check for obvious injection patterns (log but allow - vision models are generally safer)
    import re
    injection_patterns = [
        r'ignore\s+(all\s+)?instructions',
        r'system\s*:',
        r'<\|im_start\|>',
        r'\[INST\]',
    ]
    
    for pattern in injection_patterns:
        if re.search(pattern, question, re.IGNORECASE):
            _debug(f"[ANALYZE_IMAGE] Warning: potential injection in question: {question[:50]}...")
            # Don't block, but prepend a grounding instruction
            return f"Analyze this image. User question: {question}"
    
    return question


def _analyze_with_vision(images_base64: list[str], question: str, mode: str) -> str | None:
    """Perform vision analysis through the shared mode-aware dispatcher."""
    question = _sanitize_vision_prompt(question)
    if not images_base64:
        return None
    from vision_provider import analyze_images

    provider = 'ollama' if mode == 'local' else get_config_value('LLM_PROVIDER', 'xai')
    model = None
    if mode == 'cloud' and provider != 'ollama':
        model = get_config_value('VISION_MODEL', '') or None
    try:
        _debug(
            f"[ANALYZE_IMAGE] Shared vision dispatch: mode={mode}, "
            f"provider={provider}, count={len(images_base64)}"
        )
        return analyze_images(
            images_base64,
            question,
            mode=mode,
            provider=provider,
            model=model,
        )
    except Exception as e:
        _debug(f"[ANALYZE_IMAGE] Vision failed: {e}")
        return None


def _stash_image(image_data: dict, analysis: str, mode: str) -> dict | None:
    """Save image to stash for future access."""
    try:
        from stash_helper import open_space
        from datetime import datetime, timezone
        import hashlib
        
        # Create stash space
        space, is_new = open_space(
            labels=['analyzed_image', 'downloaded'],
            scope='session',
            ttl_days=7
        )
        
        # Decode and save image
        image_bytes = base64.b64decode(image_data['base64'])
        
        from stash_helper import sanitize_filename
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        raw_filename = image_data.get('filename', f'image_{timestamp}.jpg')
        # Use stash_helper's sanitize_filename for path traversal protection
        filename = sanitize_filename(raw_filename)
        if not filename.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
            filename += '.jpg'
        
        dest_path = space.space_path / filename
        with open(dest_path, 'wb') as f:
            f.write(image_bytes)
        
        # Add to space metadata
        file_hash = hashlib.sha256(image_bytes).hexdigest()
        file_id = f"f_{file_hash[:12]}"
        
        file_meta = {
            'file_id': file_id,
            'name': filename,
            'stored_name': filename,
            'mime_type': 'image/jpeg',
            'size_bytes': len(image_bytes),
            'hash_sha256': file_hash,
            'tags': ['analyzed', 'downloaded'],
            'tool_origin': 'analyze_image',
            'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + 'Z',
            'vision_analysis': analysis[:500],
            'original_url': image_data.get('original_path', '')
        }
        
        space.meta.setdefault('files', []).append(file_meta)
        space._save_meta()
        
        stash_ref = f"stash://{space.space_id}/{file_id}"
        
        # Add to memory_db
        try:
            from memory_db import MemoryDB
            db = MemoryDB()
            
            memory_key = f"stash_image_{space.space_id}"
            short_analysis = analysis[:200] + "..." if len(analysis) > 200 else analysis
            memory_value = f"Analyzed image: {short_analysis}. STASH: {stash_ref}. FILE: {filename}"
            
            db.remember(
                key=memory_key,
                value=memory_value,
                category="stash_artifact",
                importance=6,
                source="analyze_image",
                metadata={
                    "stash_ref": stash_ref,
                    "space_id": space.space_id,
                    "file_id": file_id,
                    "filename": filename,
                    "original_url": image_data.get('original_path', ''),
                    "tags": ["image", "analyzed", "downloaded"],
                    "type": "image"
                }
            )
        except Exception as mem_err:
            _debug(f"[ANALYZE_IMAGE] Memory save failed: {mem_err}")
        
        return {
            'space_id': space.space_id,
            'file_id': file_id,
            'stash_ref': stash_ref,
            'path': str(dest_path),
            'filename': filename
        }
        
    except Exception as e:
        _debug(f"[ANALYZE_IMAGE] Stash failed: {e}")
        return None


def main():
    """Entry point when called by orchestrator executor."""
    try:
        # Parse arguments from JSON (argv[1] or stdin)
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        # Extract parameters
        image = args.get('image')
        images = args.get('images')
        if not image and not images:
            raise ValueError("image or images parameter is required")
        
        question = args.get('question', 'Describe this image in detail.')
        stash_after = args.get('stash_after', False)
        
        # Run the tool
        result = analyze_image(
            image=image,
            question=question,
            stash_after=stash_after,
            images=images,
        )
        
        # Output result as JSON
        print(json.dumps(result))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Error analyzing image: {str(e)[:100]}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
