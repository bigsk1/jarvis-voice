#!/usr/bin/env python3
"""
Video Generation Tool for Jarvis
Supports multiple providers: xAI Grok Video (default), Google Gemini, OpenAI Sora

Features:
  - xAI Grok: Text-to-video, image-to-video, video editing (1-15 seconds)
  - Gemini Veo: Text/image-to-video with native audio (4-8 seconds, up to 4K)
  - Gemini Omni Flash: Text/image-to-video with native audio (3-10 seconds, 720p)
  - OpenAI Sora: Text-to-video, image-to-video with audio (4-12 seconds, remix support)
  - Multiple aspect ratios and resolutions
  - Saves to stash for use with other tools

Providers:
  - xai: xAI Grok Imagine Video (default) - More duration options, cheapest
  - gemini: Google Veo 3.1 (default) or Omni Flash (opt-in model pin)
  - openai: OpenAI Sora 2 - Native audio, remix support, visible in OpenAI Playground

Configure via VIDEO_TOOL_PROVIDER in cloud.env (default: xai)
"""

import sys
import json
import time
import base64
import requests
from pathlib import Path
from datetime import datetime

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
from config_loader import load_config, get_config_value
from model_catalog import get_media_model_env_key, get_media_model_metadata, resolve_media_model

# =============================================================================
# Provider: xAI Grok Video
# =============================================================================
# xAI supported aspect ratios
XAI_ASPECT_RATIOS = ["16:9", "4:3", "1:1", "9:16", "3:4", "3:2", "2:3"]

# xAI supported resolutions
XAI_RESOLUTIONS = ["720p", "480p"]

# xAI duration limits
XAI_MIN_DURATION = 1
XAI_MAX_DURATION = 15

# =============================================================================
# Provider: Google Gemini Veo
# =============================================================================
# Gemini supported aspect ratios (only 2 options)
GEMINI_ASPECT_RATIOS = ["16:9", "9:16"]

# Gemini supported resolutions
GEMINI_RESOLUTIONS = ["720p", "1080p", "4k"]

# Gemini duration options (discrete values, not a range)
GEMINI_DURATIONS = [4, 6, 8]  # seconds

# Gemini Omni Flash duration range (Interactions API)
GEMINI_OMNI_MIN_DURATION = 3
GEMINI_OMNI_MAX_DURATION = 10

# =============================================================================
# Provider: OpenAI Sora
# =============================================================================
# Sora supported sizes (width x height format)
# Maps to aspect ratios: 720x1280 = 9:16, 1280x720 = 16:9, etc.
OPENAI_SIZES = {
    "9:16": "720x1280",    # Portrait
    "16:9": "1280x720",    # Landscape
    "9:16_hd": "1024x1792",  # Portrait HD (sora-2-pro only)
    "16:9_hd": "1792x1024",  # Landscape HD (sora-2-pro only)
}

# Sora duration options (discrete values)
OPENAI_DURATIONS = [4, 8, 12]  # seconds

# =============================================================================
# Duration limits (for compatibility)
# =============================================================================
MIN_DURATION = 1
MAX_DURATION = 15


def _resolve_configured_video_model(provider: str) -> str:
    env_key = get_media_model_env_key("video", provider)
    configured = get_config_value(env_key, "") if env_key else ""
    return resolve_media_model("video", provider, configured)


def _resolve_video_source(video_source: str) -> str | None:
    """
    Resolve a video source to a public URL for xAI video editing.
    
    xAI video editing requires a publicly accessible URL (no base64).
    This function checks if a stash reference has a stored source_url
    from when the video was originally generated.
    
    Args:
        video_source: stash:// reference or URL
        
    Returns:
        Public URL if found, None otherwise
    """
    # Skip if already a URL
    if video_source.startswith(('http://', 'https://')):
        return None  # Let caller use directly
    
    # Handle stash:// references
    if video_source.startswith('stash://'):
        try:
            from stash_helper import get_stash_dir
            import json
            
            # Parse stash://space_id/file_id
            parts = video_source.replace('stash://', '').split('/')
            if len(parts) != 2:
                print(f"[VIDEO] Invalid stash ref format (expected space_id/file_id): {video_source}", file=sys.stderr)
                return None
            
            space_id, file_id = parts
            stash_root = get_stash_dir()
            meta_path = stash_root / space_id / 'meta.json'
            
            if not meta_path.exists():
                print(f"[VIDEO] Stash meta not found: {meta_path}", file=sys.stderr)
                return None
            
            with open(meta_path) as f:
                meta = json.load(f)
            
            # Find file and check for source_url
            # Provider URL expiration limits (conservative estimates):
            #   xAI: ~8h+ observed, using 4h safe cutoff
            #   OpenAI: 60min (but uses video_id for remix, not URLs)
            #   Gemini: unknown, using 4h
            VIDEO_URL_MAX_AGE_HOURS = 4
            
            for f in meta.get('files', []):
                if f.get('file_id') == file_id:
                    source_url = f.get('source_url')
                    if source_url and source_url.startswith('http'):
                        # Enforce expiration cutoff
                        created = f.get('source_url_created', '')
                        if created:
                            from datetime import datetime, timedelta
                            try:
                                created_dt = datetime.fromisoformat(created)
                                age = datetime.now() - created_dt
                                age_hours = age.total_seconds() / 3600
                                if age_hours > VIDEO_URL_MAX_AGE_HOURS:
                                    print(f"[VIDEO] source_url expired: {age_hours:.1f}h old (limit {VIDEO_URL_MAX_AGE_HOURS}h, created {created})", file=sys.stderr)
                                    return None
                            except Exception as e:
                                print(f"[VIDEO] Could not parse source_url_created: {created} ({e})", file=sys.stderr)
                        return source_url
                    else:
                        print(f"[VIDEO] File found in stash but no valid source_url (got: {source_url})", file=sys.stderr)
                    break
            else:
                print(f"[VIDEO] File {file_id} not found in stash space {space_id}", file=sys.stderr)
        except Exception as e:
            import traceback
            print(f"[VIDEO] Error resolving stash video: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
    
    return None


def _resolve_image_source(image_source: str) -> str | None:
    """
    Resolve an image source to a local file path.
    
    Handles:
    - stash:// references (e.g., stash://space_xxx/file_id)
    - Local file paths (absolute or relative)
    - Relative web paths (e.g., /api/uploads/filename)
    
    Returns:
        Local file path if resolved, None if should try as URL
    """
    from stash_helper import safe_resolve_file
    
    # Skip URLs and base64 - let caller handle those
    if image_source.startswith(('http://', 'https://', 'data:')):
        return None
    
    # Handle stash:// references
    if image_source.startswith('stash://'):
        result = safe_resolve_file(stash_ref=image_source)
        if result['found']:
            return result['path']
        else:
            raise ValueError(f"Stash file not found: {result.get('error', image_source)}")
    
    # Handle relative web paths (from WebUI uploads)
    if image_source.startswith('/api/uploads/'):
        filename = image_source.split('/')[-1]
        uploads_path = Path(__file__).parent.parent / 'jarvis-web' / 'data' / 'uploads' / filename
        if uploads_path.exists():
            return str(uploads_path)
    
    # Handle generated images path
    if image_source.startswith('/api/images/'):
        filename = image_source.split('/')[-1]
        images_path = Path(__file__).parent.parent / 'data' / 'generated_images' / filename
        if images_path.exists():
            return str(images_path)
    
    # Handle direct local paths
    if Path(image_source).is_file():
        return image_source
    
    # Check common image directories
    project_root = Path(__file__).parent.parent
    common_paths = [
        project_root / 'data' / 'generated_images',
        project_root / 'jarvis-web' / 'data' / 'uploads',
        project_root / 'data' / 'stash',
    ]
    
    # Try to find by filename in common directories
    filename = Path(image_source).name
    for base_path in common_paths:
        candidate = base_path / filename
        if candidate.exists():
            return str(candidate)
    
    # Not found locally
    return None


def generate_video_xai(prompt: str, duration: int = 5, aspect_ratio: str = "16:9",
                       resolution: str = "720p", image_url: str = None,
                       video_url: str = None) -> dict:
    """
    Generate a video using xAI Grok Imagine Video.
    
    Args:
        prompt: What to generate or describe the edit
        duration: Video duration in seconds (1-15)
        aspect_ratio: 16:9, 4:3, 1:1, 9:16, 3:4, 3:2, 2:3
        resolution: 720p or 480p
        image_url: Optional image URL or local file path to generate video from
        video_url: Optional video URL to edit (max 8.7s source)
    
    Returns:
        dict with video_url, duration, model info
    """
    
    api_key = get_config_value('XAI_API_KEY')
    if not api_key:
        raise ValueError("XAI_API_KEY not configured. Add it to config/cloud.env")
    
    # Get model from env or use default
    model_name = _resolve_configured_video_model("xai")
    
    # Validate duration
    duration = max(MIN_DURATION, min(MAX_DURATION, duration))
    
    # Validate aspect ratio
    if aspect_ratio not in XAI_ASPECT_RATIOS:
        aspect_ratio = "16:9"
    
    # Validate resolution
    if resolution not in XAI_RESOLUTIONS:
        resolution = "720p"
    
    try:
        from xai_sdk import Client
        
        # Create client with API key
        client = Client(api_key=api_key)
        
        # Build kwargs for video generation
        kwargs = {
            "prompt": prompt,
            "model": model_name,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution
        }
        
        # Add image_url for image-to-video
        # xAI requires either a URL (http/https) or base64-encoded image
        if image_url:
            resolved_path = _resolve_image_source(image_url)
            if resolved_path:
                # Convert local file to base64
                import mimetypes
                
                mime_type, _ = mimetypes.guess_type(resolved_path)
                if not mime_type:
                    mime_type = 'image/png'  # Default to PNG
                
                with open(resolved_path, 'rb') as f:
                    image_data = f.read()
                
                b64_data = base64.b64encode(image_data).decode('utf-8')
                kwargs["image_url"] = f"data:{mime_type};base64,{b64_data}"
            elif image_url.startswith(('http://', 'https://')):
                # Already a valid URL - use as-is
                kwargs["image_url"] = image_url
            elif image_url.startswith('data:'):
                # Already base64 data URI - use as-is
                kwargs["image_url"] = image_url
            else:
                raise ValueError(f"Could not resolve image source: {image_url[:100]}")
        
        # Add video_url for video editing
        # xAI requires a publicly accessible URL (no base64 for videos)
        # Provider URLs expire: xAI ~4h, OpenAI 60min
        if video_url:
            resolved_url = _resolve_video_source(video_url)
            if resolved_url:
                kwargs["video_url"] = resolved_url
            elif video_url.startswith(('http://', 'https://')):
                kwargs["video_url"] = video_url
            elif video_url.startswith('stash://'):
                raise ValueError(f"The video URL for editing has expired or is unavailable. Provider URLs are only valid for ~4 hours. To make changes, regenerate the video from the source image using image_url instead.")
            else:
                raise ValueError(f"Video editing requires a public http(s) URL. Got: {video_url[:80]}. Stash refs are not directly usable — provide the original provider URL or regenerate from the source image.")
        
        # Generate video with automatic polling (SDK handles waiting)
        # This can take 30-120+ seconds
        response = client.video.generate(**kwargs)
        
        return {
            "video_url": response.url,
            "duration": getattr(response, 'duration', duration),
            "prompt": prompt,
            "model": model_name,
            "provider": "xai",
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "from_image": image_url is not None,
            "is_edit": video_url is not None
        }
        
    except ImportError:
        raise ValueError("xai_sdk not installed. Run: pip install xai-sdk")
    except Exception as e:
        raise Exception(f"xAI Video generation failed: {str(e)}")


def _load_gemini_image_bytes(image_url: str) -> tuple[bytes, str] | None:
    """Resolve a local/stash/remote image into bytes for Gemini video APIs."""
    import mimetypes

    resolved_path = _resolve_image_source(image_url)
    if resolved_path and Path(resolved_path).exists():
        image_bytes = Path(resolved_path).read_bytes()
        mime_type, _ = mimetypes.guess_type(resolved_path)
        print(f"[GEMINI VIDEO] Using local image: {resolved_path}", file=sys.stderr)
        return image_bytes, mime_type or "image/png"

    if image_url.startswith(("http://", "https://")):
        response = requests.get(image_url, timeout=30)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "image/png").split(";", 1)[0]
        return response.content, content_type

    return None


def _download_gemini_omni_video(client, video_output) -> bytes:
    """Return Omni output bytes, polling Files API when URI delivery is used."""
    if getattr(video_output, "data", None):
        return base64.b64decode(video_output.data)

    uri = getattr(video_output, "uri", None)
    if not uri:
        raise Exception("Gemini Omni returned no video data or URI")

    if "/files/" in uri:
        file_id = uri.split("/files/", 1)[1].split(":", 1)[0].split("?", 1)[0]
    elif uri.startswith("files/"):
        file_id = uri.split("/", 1)[1].split(":", 1)[0].split("?", 1)[0]
    else:
        raise Exception(f"Gemini Omni returned an unrecognized video URI: {uri}")

    for _ in range(120):  # Up to 10 minutes at 5-second intervals.
        file_info = client.files.get(name=f"files/{file_id}")
        state = getattr(file_info, "state", "")
        state_name = getattr(state, "name", str(state)).upper()
        if state_name.endswith("ACTIVE"):
            return client.files.download(file=uri)
        if state_name.endswith("FAILED"):
            raise Exception("Gemini Omni video processing failed")
        time.sleep(5)

    raise Exception("Gemini Omni video processing timed out after 10 minutes")


def _generate_video_gemini_omni(client, model_name: str, prompt: str, duration: int,
                                 aspect_ratio: str, image_url: str | None,
                                 negative_prompt: str | None) -> dict:
    """Generate text/image-to-video with Gemini Omni through Interactions API."""
    try:
        omni_duration = round(float(duration))
    except (TypeError, ValueError):
        omni_duration = 5
    omni_duration = max(GEMINI_OMNI_MIN_DURATION, min(GEMINI_OMNI_MAX_DURATION, omni_duration))

    if aspect_ratio not in GEMINI_ASPECT_RATIOS:
        aspect_ratio = "9:16" if aspect_ratio in ["9:16", "3:4", "2:3"] else "16:9"

    effective_prompt = prompt
    if negative_prompt:
        effective_prompt = f"{prompt}\nDo not include: {negative_prompt}"

    interaction_input = effective_prompt
    task = "text_to_video"
    if image_url:
        try:
            loaded_image = _load_gemini_image_bytes(image_url)
        except Exception as exc:
            print(f"Warning: Could not load image: {exc}", file=sys.stderr)
            loaded_image = None
        if loaded_image:
            image_bytes, mime_type = loaded_image
            interaction_input = [
                {
                    "type": "image",
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                    "mime_type": mime_type,
                },
                {"type": "text", "text": effective_prompt},
            ]
            task = "image_to_video"
        else:
            print(f"Warning: Could not resolve image source: {image_url}", file=sys.stderr)

    interaction = client.interactions.create(
        model=model_name,
        input=interaction_input,
        response_format={
            "type": "video",
            "delivery": "uri",
            "aspect_ratio": aspect_ratio,
            "duration": f"{omni_duration}s",
        },
        generation_config={"video_config": {"task": task}},
    )

    if getattr(interaction, "status", "completed") == "failed":
        raise Exception("Gemini Omni interaction failed")
    video_output = getattr(interaction, "output_video", None)
    if not video_output:
        raise Exception("No video generated - empty Gemini Omni response")

    return {
        "video_url": getattr(video_output, "uri", None),
        "video_bytes": _download_gemini_omni_video(client, video_output),
        "duration": omni_duration,
        "prompt": prompt,
        "model": model_name,
        "provider": "gemini",
        "aspect_ratio": aspect_ratio,
        "resolution": "720p",
        "from_image": task == "image_to_video",
        "has_audio": True,
        "interaction_id": getattr(interaction, "id", None),
    }


def generate_video_gemini(prompt: str, duration: int = 8, aspect_ratio: str = "16:9",
                          resolution: str = "720p", image_url: str = None,
                          negative_prompt: str = None) -> dict:
    """
    Generate a video using the configured Google Gemini video model.
    
    Args:
        prompt: What to generate (supports audio cues in quotes for dialogue)
        duration: Veo maps to 4/6/8 seconds; Omni clamps to 3-10 seconds
        aspect_ratio: 16:9 (landscape) or 9:16 (portrait)
        resolution: Veo supports 720p-4k; Omni uses 720p
        image_url: Optional image URL for image-to-video
        negative_prompt: What to avoid (native on Veo, prompt guidance on Omni)
    
    Returns:
        dict with video_url, duration, model info
    """
    
    api_key = get_config_value('GEMINI_API_KEY')
    if not api_key:
        raise ValueError("GEMINI_API_KEY not configured. Add it to config/cloud.env")
    
    # Get model from env or use default
    model_name = _resolve_configured_video_model("gemini")
    
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise ValueError("google-genai not installed. Run: pip install google-genai")

    client = genai.Client(api_key=api_key)
    model_metadata = get_media_model_metadata("video", "gemini", model_name) or {}
    if model_metadata.get("api") == "interactions":
        try:
            return _generate_video_gemini_omni(
                client, model_name, prompt, duration, aspect_ratio, image_url, negative_prompt
            )
        except Exception as e:
            raise Exception(f"Gemini Video generation failed: {str(e)}")

    # Validate and map duration to nearest supported value
    if duration <= 5:
        gemini_duration = 4
    elif duration <= 7:
        gemini_duration = 6
    else:
        gemini_duration = 8
    
    # Validate aspect ratio (Gemini only supports 2)
    if aspect_ratio not in GEMINI_ASPECT_RATIOS:
        # Map to nearest supported
        if aspect_ratio in ["9:16", "3:4", "2:3"]:
            aspect_ratio = "9:16"
        else:
            aspect_ratio = "16:9"
    
    # Validate resolution
    if resolution not in GEMINI_RESOLUTIONS:
        resolution = "720p"
    
    # 1080p and 4k only support 8 second videos
    if resolution in ["1080p", "4k"] and gemini_duration != 8:
        gemini_duration = 8
    
    try:
        # Build config for video generation
        config_kwargs = {
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "duration_seconds": gemini_duration,
        }
        
        if negative_prompt:
            config_kwargs["negative_prompt"] = negative_prompt
        
        config = types.GenerateVideosConfig(**config_kwargs)
        
        # Build generation kwargs
        gen_kwargs = {
            "model": model_name,
            "prompt": prompt,
            "config": config,
        }
        
        # Add image for image-to-video if provided
        if image_url:
            import mimetypes
            try:
                img_bytes = None
                mime_type = 'image/png'
                
                # First try to resolve as stash ref or local path
                resolved_path = _resolve_image_source(image_url)
                if resolved_path and Path(resolved_path).exists():
                    # Read local file
                    with open(resolved_path, 'rb') as f:
                        img_bytes = f.read()
                    detected_mime, _ = mimetypes.guess_type(resolved_path)
                    if detected_mime:
                        mime_type = detected_mime
                    print(f"[GEMINI VIDEO] Using local image: {resolved_path}", file=sys.stderr)
                elif image_url.startswith(('http://', 'https://')):
                    # Download from URL
                    img_response = requests.get(image_url, timeout=30)
                    img_response.raise_for_status()
                    img_bytes = img_response.content
                    
                    # Determine mime type from response
                    content_type = img_response.headers.get('content-type', 'image/png')
                    if 'jpeg' in content_type or 'jpg' in content_type:
                        mime_type = 'image/jpeg'
                    elif 'png' in content_type:
                        mime_type = 'image/png'
                    elif 'webp' in content_type:
                        mime_type = 'image/webp'
                else:
                    print(f"Warning: Could not resolve image source: {image_url}", file=sys.stderr)
                
                if img_bytes:
                    # Create image object
                    gen_kwargs["image"] = types.Image(
                        image_bytes=img_bytes,
                        mime_type=mime_type
                    )
            except Exception as e:
                # Continue without image if download fails
                print(f"Warning: Could not load image: {e}", file=sys.stderr)
        
        # Start video generation (async operation)
        operation = client.models.generate_videos(**gen_kwargs)
        
        # Poll for completion (Gemini videos can take 30-120+ seconds)
        poll_count = 0
        max_polls = 60  # 10 minutes max (10s intervals)
        
        while not operation.done and poll_count < max_polls:
            time.sleep(10)
            operation = client.operations.get(operation)
            poll_count += 1
        
        if not operation.done:
            raise Exception("Video generation timed out after 10 minutes")
        
        # Get the generated video
        if not operation.response or not operation.response.generated_videos:
            raise Exception("No video generated - empty response from Gemini")
        
        generated_video = operation.response.generated_videos[0]
        
        # Download the video file
        client.files.download(file=generated_video.video)
        
        # Get the video URL or bytes
        video = generated_video.video
        video_url = getattr(video, 'uri', None) or getattr(video, 'url', None)
        
        # Return SDK bytes directly. The main save path writes the final named
        # artifact, so creating an intermediate .mp4 here only exposes partial
        # files to the Canvas gallery if later processing or a test stops early.
        video_bytes = getattr(video, 'video_bytes', None)
        
        return {
            "video_url": video_url,
            "video_bytes": video_bytes,
            "duration": gemini_duration,
            "prompt": prompt,
            "model": model_name,
            "provider": "gemini",
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "from_image": image_url is not None,
            "has_audio": True  # Veo 3+ generates native audio
        }
        
    except Exception as e:
        raise Exception(f"Gemini Video generation failed: {str(e)}")


def generate_video_openai(prompt: str, duration: int = 8, aspect_ratio: str = "16:9",
                          resolution: str = "720p", image_path: str = None,
                          remix_video_id: str = None) -> dict:
    """
    Generate a video using OpenAI Sora 2.
    
    Args:
        prompt: What to generate (supports dialogue in quotes for speech)
        duration: Video duration - must be 4, 8, or 12 seconds
        aspect_ratio: 16:9 (landscape) or 9:16 (portrait)
        resolution: 720p or 1080p (1080p requires sora-2-pro)
        image_path: Optional local image path for image-to-video
        remix_video_id: Optional video ID to remix (extend/edit)
    
    Returns:
        dict with video_url, duration, model info
    """
    import asyncio
    
    api_key = get_config_value('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("OPENAI_API_KEY not configured. Add it to config/cloud.env")
    
    # Get model from env or use default
    model_name = _resolve_configured_video_model("openai")
    
    # Validate and map duration to nearest supported value
    if duration <= 6:
        openai_duration = 4
    elif duration <= 10:
        openai_duration = 8
    else:
        openai_duration = 12
    
    # Determine size based on aspect ratio and resolution
    # sora-2-pro supports higher res (1024x1792, 1792x1024)
    is_pro = 'pro' in model_name.lower()
    
    if aspect_ratio in ["9:16", "3:4", "2:3"]:
        # Portrait
        if is_pro and resolution == "1080p":
            size = "1024x1792"
        else:
            size = "720x1280"
    else:
        # Landscape (default)
        if is_pro and resolution == "1080p":
            size = "1792x1024"
        else:
            size = "1280x720"
    
    try:
        from openai import AsyncOpenAI
        
        client = AsyncOpenAI(api_key=api_key)
        
        # Parse target dimensions from size string (e.g., "1280x720" -> (1280, 720))
        target_width, target_height = map(int, size.split('x'))
        
        def resize_image_for_sora(image_path: str, target_w: int, target_h: int) -> str:
            """
            Resize image to match Sora's required dimensions.
            OpenAI Sora requires input image to match the requested video size.
            Returns path to resized image (temp file).
            """
            try:
                from PIL import Image
                import tempfile
                
                with Image.open(image_path) as img:
                    # Convert to RGB if necessary (handles RGBA, etc.)
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # Resize to exact target dimensions (Sora requirement)
                    # Use LANCZOS for high-quality downscaling
                    resized = img.resize((target_w, target_h), Image.LANCZOS)
                    
                    # Save to temp file
                    temp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                    resized.save(temp_file.name, 'JPEG', quality=95)
                    print(f"[OPENAI VIDEO] Resized image from {img.size} to ({target_w}, {target_h})", file=sys.stderr)
                    return temp_file.name
            except ImportError:
                raise ValueError("PIL/Pillow not installed. Run: pip install Pillow")
            except Exception as e:
                raise ValueError(f"Failed to resize image: {e}")
        
        async def create_video():
            # Build kwargs for video generation
            kwargs = {
                "model": model_name,
                "prompt": prompt,
                "seconds": str(openai_duration),
                "size": size,
            }
            
            # Handle image-to-video
            if image_path:
                # OpenAI expects input_reference as a file upload
                # First, check if it's a local file
                resolved_path = _resolve_image_source(image_path)
                if resolved_path and Path(resolved_path).exists():
                    # Resize image to match target video dimensions (Sora requirement)
                    resized_path = resize_image_for_sora(resolved_path, target_width, target_height)
                    try:
                        # Upload resized file as input_reference
                        with open(resized_path, 'rb') as f:
                            kwargs["input_reference"] = f
                            # Use create_and_poll for automatic polling
                            video = await client.videos.create_and_poll(**kwargs)
                    finally:
                        # Clean up temp file
                        try:
                            Path(resized_path).unlink()
                        except:
                            pass
                else:
                    # No valid image, proceed without
                    video = await client.videos.create_and_poll(**kwargs)
            else:
                # Use create_and_poll for automatic polling
                video = await client.videos.create_and_poll(**kwargs)
            
            return video
        
        async def remix_video():
            # Remix an existing video with new prompt
            video = await client.videos.remix(
                video_id=remix_video_id,
                prompt=prompt
            )
            # Poll for completion
            while video.status in ("queued", "in_progress"):
                await asyncio.sleep(5)
                video = await client.videos.retrieve(video.id)
            return video
        
        # Run the async function
        if remix_video_id:
            video = asyncio.run(remix_video())
        else:
            video = asyncio.run(create_video())
        
        # Check for errors
        if video.status == "failed":
            error_msg = getattr(video.error, 'message', str(video.error)) if video.error else "Unknown error"
            raise Exception(f"Sora video generation failed: {error_msg}")
        
        if video.status != "completed":
            raise Exception(f"Video generation did not complete. Status: {video.status}")
        
        # Download the video content
        async def download_content():
            return await client.videos.download_content(video.id)
        
        content_response = asyncio.run(download_content())
        video_bytes = content_response.read() if hasattr(content_response, 'read') else content_response
        
        # Save to temp file
        temp_dir = Path(__file__).parent.parent / 'data' / 'generated_videos'
        temp_dir.mkdir(exist_ok=True)
        temp_file = temp_dir / f"sora_temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        
        if isinstance(video_bytes, bytes):
            temp_file.write_bytes(video_bytes)
        else:
            # It might be a streaming response
            with open(temp_file, 'wb') as f:
                for chunk in video_bytes:
                    f.write(chunk)
        
        # Map size back to aspect ratio for metadata
        result_aspect = "9:16" if size.startswith("720x1280") or size.startswith("1024x1792") else "16:9"
        
        return {
            "video_url": f"file://{temp_file}",
            "video_bytes": temp_file.read_bytes(),
            "video_id": video.id,  # OpenAI video ID for remix
            "duration": openai_duration,
            "prompt": prompt,
            "model": model_name,
            "provider": "openai",
            "aspect_ratio": result_aspect,
            "resolution": "1080p" if is_pro and "1792" in size else "720p",
            "from_image": image_path is not None,
            "has_audio": True,  # Sora 2 generates native audio
            "remix_from": remix_video_id
        }
        
    except ImportError:
        raise ValueError("openai SDK not installed. Run: pip install openai")
    except Exception as e:
        raise Exception(f"OpenAI Sora video generation failed: {str(e)}")


def generate_video(prompt: str, duration: int = 5, aspect_ratio: str = "16:9",
                   resolution: str = "720p", image_url: str = None,
                   video_url: str = None, negative_prompt: str = None,
                   provider: str = None) -> dict:
    """
    Generate a video using configured provider.
    
    Args:
        prompt: What to generate
        duration: Video duration in seconds
                  - xAI: 1-15 seconds (continuous range)
                  - Gemini: 4, 6, or 8 seconds (discrete values)
                  - OpenAI: 4, 8, or 12 seconds (discrete values)
        aspect_ratio: Video shape
                  - xAI: 16:9, 4:3, 1:1, 9:16, 3:4, 3:2, 2:3
                  - Gemini: 16:9 or 9:16 only
                  - OpenAI: 16:9 or 9:16 only
        resolution: Video quality
                  - xAI: 720p or 480p
                  - Gemini: 720p, 1080p, or 4k
                  - OpenAI: 720p or 1080p (1080p requires sora-2-pro)
        image_url: Optional image URL for image-to-video
        video_url: Optional video URL for editing (xAI only) or remix video ID (OpenAI)
        negative_prompt: What to avoid (Gemini only)
        provider: Override provider (xai, gemini, or openai)
    """
    
    # Determine provider
    # get_config_value checks JARVIS_OVERRIDE_ prefix first (web UI settings),
    # then falls back to cloud.env default. LLM-passed provider is ignored
    # when a config/override value exists.
    provider = get_config_value('VIDEO_TOOL_PROVIDER', provider or 'xai').lower()
    
    if provider == 'openai':
        # OpenAI Sora - video_url is treated as remix_video_id
        return generate_video_openai(
            prompt=prompt,
            duration=duration,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            image_path=image_url,
            remix_video_id=video_url if video_url and video_url.startswith('video_') else None
        )
    elif provider == 'gemini':
        return generate_video_gemini(
            prompt=prompt,
            duration=duration,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            image_url=image_url,
            negative_prompt=negative_prompt
        )
    else:
        # Default to xAI
        return generate_video_xai(
            prompt=prompt,
            duration=duration,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            image_url=image_url,
            video_url=video_url
        )


def download_video(video_url: str, filename: str, video_bytes: bytes = None) -> Path:
    """Download video from URL to local file, or save bytes directly."""
    
    videos_dir = Path(__file__).parent.parent / 'data' / 'generated_videos'
    videos_dir.mkdir(exist_ok=True)
    
    video_path = videos_dir / filename
    
    # If we already have bytes (Gemini/OpenAI may provide these directly), save them
    if video_bytes:
        video_path.write_bytes(video_bytes)
        # Clean up temp file if one was created (OpenAI Sora creates file:// temp files)
        if video_url and video_url.startswith('file://'):
            temp_path = Path(video_url.replace('file://', ''))
            if temp_path.exists() and temp_path != video_path:
                try:
                    temp_path.unlink()
                    print(f"[VIDEO] Cleaned up temp file: {temp_path.name}", file=sys.stderr)
                except Exception:
                    pass  # Ignore cleanup errors
        return video_path
    
    # Handle file:// URLs (local temp files from Gemini/OpenAI)
    if video_url and video_url.startswith('file://'):
        temp_path = Path(video_url.replace('file://', ''))
        if temp_path.exists():
            # Move temp file to final location
            import shutil
            shutil.move(str(temp_path), str(video_path))
            return video_path
    
    # Download from remote URL (xAI or Gemini remote)
    if video_url:
        # Add API key header if it's a Gemini URL
        headers = {}
        if 'googleapis.com' in video_url or 'google' in video_url:
            api_key = get_config_value('GEMINI_API_KEY', '')
            if api_key:
                headers['x-goog-api-key'] = api_key
        
        response = requests.get(video_url, timeout=300, stream=True, headers=headers, allow_redirects=True)
        response.raise_for_status()
        
        # Write in chunks for large files
        with open(video_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return video_path
    
    raise ValueError("No video URL or bytes provided")


def save_to_stash(video_path: Path, prompt: str, video_data: dict) -> dict:
    """Save generated video to stash for use with other tools."""
    
    filename = video_path.name
    
    # Read video bytes
    video_bytes = video_path.read_bytes()
    
    # Create stash reference for discoverability
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
        from stash_helper import open_space, StashFile
        
        space, _ = open_space(scope='session', labels=['generated_videos'])
        stash_file = StashFile(space)
        
        # Get provider tag
        provider = video_data.get('provider', 'xai')
        
        # Build tags with original URL (for video editing capability)
        tags = ['ai_generated', 'video', provider, video_data.get('aspect_ratio', '16:9')]
        
        # Store original xAI/Gemini URL for potential video editing
        # These URLs may expire but are valid for some time after generation
        source_url = video_data.get('video_url')
        
        # Save as binary to stash
        result = stash_file.save_binary(
            data=video_bytes,
            name=filename,
            mime_type='video/mp4',
            on_conflict='overwrite',
            tags=tags,
            tool_origin='generate_video'
        )
        
        # Add source_url to the file metadata for video editing
        if source_url and source_url.startswith('http'):
            file_id = result.get('file_id')
            for f in space.meta.get('files', []):
                if f.get('file_id') == file_id:
                    f['source_url'] = source_url  # xAI/Gemini public URL
                    f['source_url_created'] = datetime.now().isoformat()
                    break
            space._save_meta()
        
        return {
            "saved": True,
            "stash_ref": result.get('ref'),
            "space_id": space.space_id,
            "path": str(video_path),
            "stash_path": result.get('path'),
            "filename": filename,
            "size_bytes": len(video_bytes),
            "stash": True,
            "source_url": source_url if source_url and source_url.startswith('http') else None
        }
    except Exception as e:
        # Stash failed but file is saved
        return {
            "saved": True,
            "path": str(video_path),
            "filename": filename,
            "size_bytes": video_path.stat().st_size,
            "stash": False,
            "note": f"File saved but stash indexing failed: {e}"
        }


def main():
    try:
        load_config()
        
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        prompt = args.get('prompt', '')
        if not prompt:
            raise ValueError("prompt is required - describe what video you want to generate")
        
        # Parameters
        duration = args.get('duration', 5)
        aspect_ratio = args.get('aspect_ratio', '16:9')
        resolution = args.get('resolution', '720p')
        image_url = args.get('image_url')  # For image-to-video
        video_url = args.get('video_url')  # For video editing (xAI only)
        negative_prompt = args.get('negative_prompt')  # For Gemini
        save = args.get('save', True)
        provider = args.get('provider')  # Override provider if specified
        
        # Generate the video
        result = generate_video(
            prompt=prompt,
            duration=duration,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            image_url=image_url,
            video_url=video_url,
            negative_prompt=negative_prompt,
            provider=provider
        )
        
        # Download and save video
        save_info = None
        if save and (result.get('video_url') or result.get('video_bytes')):
            # Generate filename from prompt
            safe_prompt = "".join(c if c.isalnum() or c in ' -_' else '' for c in prompt[:40])
            safe_prompt = safe_prompt.replace(' ', '_').lower()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"video_{safe_prompt}_{timestamp}.mp4"
            
            # Download video (may have bytes directly from Gemini)
            video_path = download_video(
                result.get('video_url', ''), 
                filename,
                video_bytes=result.get('video_bytes')
            )
            
            # Save to stash
            save_info = save_to_stash(video_path, prompt, result)
            
            # Also save to memory for cross-session discovery
            try:
                from memory_db import MemoryDB
                db = MemoryDB()
                
                stash_ref = save_info.get('stash_ref', '')
                space_id = save_info.get('space_id', '')
                
                memory_key = f"stash_video_{space_id}" if space_id else f"generated_video_{timestamp}"
                memory_value = f"Generated video: {prompt[:150]}. STASH: {stash_ref}. FILE: {save_info.get('filename')}"
                
                db.remember(
                    key=memory_key,
                    value=memory_value,
                    category="stash_artifact",
                    importance=6,  # Higher importance for stash items
                    source="generate_video",
                    metadata={
                        "stash_ref": stash_ref,
                        "space_id": space_id,
                        "filename": save_info.get('filename', ''),
                        "prompt": prompt[:200],
                        "provider": result.get('provider', 'xai'),
                        "duration": result.get('duration'),
                        "tags": ["video", "generated", "ai_created"],
                        "type": "video"
                    }
                )
            except Exception:
                pass  # Don't fail the tool if memory save fails
        
        # Build response
        provider_used = result.get('provider', 'xai')
        duration_result = result.get('duration', duration)
        speech = f"Generated {duration_result}s video with {provider_used}: {prompt[:50]}{'...' if len(prompt) > 50 else ''}"
        
        response = {
            "ok": True,
            "speech": speech,
            "data": {
                "prompt": prompt,
                "provider": provider_used,
                "model": result['model'],
                "duration": duration_result,
                "aspect_ratio": result.get('aspect_ratio'),
                "resolution": result.get('resolution'),
                "video_url": result.get('video_url')  # Original URL (may expire)
            }
        }
        if result.get("interaction_id"):
            response["data"]["interaction_id"] = result["interaction_id"]
        
        # Add mode indicators and source references
        if result.get('from_image'):
            response["data"]["generated_from"] = "image"
            # Include source image ref so LLM can regenerate from same image
            if image_url:
                response["data"]["source_image"] = image_url
        if result.get('is_edit'):
            response["data"]["mode"] = "edit"
        if result.get('has_audio'):
            response["data"]["has_audio"] = True
        
        # Add save info
        if save_info:
            response["data"]["saved"] = save_info
            if save_info.get('path'):
                response["speech"] += ". Saved to stash."
                response["data"]["file_path"] = save_info['path']
        
        print(json.dumps(response))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "speech": f"Failed to generate video: {e}",
            "error": str(e)
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
