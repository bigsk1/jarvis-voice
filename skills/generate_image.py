#!/usr/bin/env python3
"""
Image Generation Tool for Jarvis
Supports multiple providers: Google Gemini, OpenAI GPT Image, and xAI Grok Imagine

Features:
  - Google Gemini: Search grounding for real-time data (weather, stocks, current events)
  - OpenAI GPT Image: Superior instruction following, text rendering, real-world knowledge
  - xAI Grok Imagine: Fast and cheap image generation with aspect ratio support
  - Multiple aspect ratios and quality settings
  - Transparent background support (OpenAI)
  - Saves to stash for use with email, printer, canvas, pdf_create, etc.

Providers:
  - gemini: Google Gemini 3 Pro Image Preview (grounding support)
  - openai: OpenAI GPT Image (best text rendering, highest quality)
  - xai: xAI Grok Imagine Image (fast, cheap, good quality)

Configure via IMAGE_TOOL_PROVIDER in cloud.env (default: gemini)
"""

import sys
import json
import base64
import mimetypes
import requests
from pathlib import Path
from datetime import datetime

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
from config_loader import load_config, get_config_value

# =============================================================================
# Provider: Google Gemini
# =============================================================================
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash-preview-image-generation"

# Gemini aspect ratios (alias names + literal ratio strings from tool schema)
GEMINI_ASPECT_RATIOS = {
    "square": "1:1",
    "landscape": "16:9",
    "portrait": "9:16",
    "wide": "16:9",
    "cinematic": "16:9",
    "widescreen": "16:9",
    "tall": "9:16",
    "4:3": "4:3",
    "3:4": "3:4",
    "2:3": "2:3",
    "3:2": "3:2",
    "4:5": "4:5",
    "5:4": "5:4",
    "16:9": "16:9",
    "9:16": "9:16",
    "1:1": "1:1",
}

# =============================================================================
# Provider: OpenAI
# =============================================================================
OPENAI_API_BASE = "https://api.openai.com/v1/images/generations"
DEFAULT_OPENAI_MODEL = "gpt-image-2"  # State of the art (Apr 2026)

# OpenAI size mappings (aspect ratio -> pixel dimensions)
OPENAI_SIZES = {
    "square": "1024x1024",
    "landscape": "1536x1024",
    "portrait": "1024x1536",
    "wide": "1536x1024",      # No ultra-wide, use landscape
    "cinematic": "1536x1024",
    "widescreen": "1536x1024",
    "tall": "1024x1536",
    "4:3": "1536x1024",       # Approximate
    "3:4": "1024x1536",       # Approximate
    "16:9": "1536x1024",
    "9:16": "1024x1536",
    "1:1": "1024x1024"
}

# gpt-image-2 supports flexible sizes that satisfy API constraints. Keep the
# public 1K/2K/4K control and map it to useful dimensions per aspect ratio.
OPENAI_IMAGE_2_SIZES = {
    "1K": {
        "square": "1024x1024",
        "landscape": "1536x1024",
        "portrait": "1024x1536",
        "wide": "1536x864",
        "cinematic": "1536x864",
        "widescreen": "1536x864",
        "tall": "864x1536",
        "4:3": "1536x1152",
        "3:4": "1152x1536",
        "2:3": "1024x1536",
        "3:2": "1536x1024",
        "4:5": "1024x1280",
        "5:4": "1280x1024",
        "16:9": "1536x864",
        "9:16": "864x1536",
        "1:1": "1024x1024",
    },
    "2K": {
        "square": "2048x2048",
        "landscape": "2048x1152",
        "portrait": "1152x2048",
        "wide": "2048x1152",
        "cinematic": "2048x1152",
        "widescreen": "2048x1152",
        "tall": "1152x2048",
        "4:3": "2048x1536",
        "3:4": "1536x2048",
        "2:3": "1360x2048",
        "3:2": "2048x1360",
        "4:5": "1600x2000",
        "5:4": "2000x1600",
        "16:9": "2048x1152",
        "9:16": "1152x2048",
        "1:1": "2048x2048",
    },
    "4K": {
        "square": "2048x2048",
        "landscape": "3840x2160",
        "portrait": "2160x3840",
        "wide": "3840x2160",
        "cinematic": "3840x2160",
        "widescreen": "3840x2160",
        "tall": "2160x3840",
        "4:3": "3072x2304",
        "3:4": "2304x3072",
        "2:3": "2304x3456",
        "3:2": "3456x2304",
        "4:5": "2304x2880",
        "5:4": "2880x2304",
        "16:9": "3840x2160",
        "9:16": "2160x3840",
        "1:1": "2048x2048",
    },
}

# OpenAI quality mappings
OPENAI_QUALITY_MAP = {
    "1K": "low",
    "2K": "medium", 
    "4K": "high",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "auto": "auto"
}


def _is_gpt_image_2(model_name: str) -> bool:
    return str(model_name or "").startswith("gpt-image-2")


def _resolve_openai_size(model_name: str, aspect_ratio: str, quality: str) -> str:
    aspect_key = str(aspect_ratio or "square").strip().lower()
    if _is_gpt_image_2(model_name):
        requested = str(quality or "2K").strip()
        size_key = {
            "low": "1K",
            "medium": "2K",
            "high": "4K",
        }.get(requested.lower(), requested.upper())
        if size_key not in OPENAI_IMAGE_2_SIZES:
            size_key = "2K"
        return OPENAI_IMAGE_2_SIZES[size_key].get(aspect_key, OPENAI_IMAGE_2_SIZES[size_key]["square"])
    return OPENAI_SIZES.get(aspect_key, "1024x1024")

# =============================================================================
# Provider: xAI Grok Imagine
# =============================================================================
XAI_API_BASE = "https://api.x.ai/v1/images/generations"
XAI_EDIT_API = "https://api.x.ai/v1/images/edits"
DEFAULT_XAI_IMAGE_MODEL = "grok-imagine-image"

# xAI aspect ratios (supports common ratios)
XAI_ASPECT_RATIOS = {
    "square": "1:1",
    "landscape": "16:9",
    "portrait": "9:16",
    # xAI currently rejects 21:9. Treat "wide/cinematic" as standard widescreen.
    "wide": "16:9",
    "cinematic": "16:9",
    "widescreen": "16:9",
    "tall": "9:16",
    "4:3": "4:3",
    "3:4": "3:4",
    "2:3": "2:3",
    "3:2": "3:2",
    "4:5": "3:4",
    "5:4": "4:3",
    "16:9": "16:9",
    "9:16": "9:16",
    "1:1": "1:1",
    "21:9": "16:9",
    "9:21": "9:16",
    "19.5:9": "19.5:9",
    "9:19.5": "9:19.5"
}

# Shared image sizes
IMAGE_SIZES = ["1K", "2K", "4K"]

# OpenAI edit endpoint (separate from generations)
OPENAI_EDIT_API = "https://api.openai.com/v1/images/edits"


# =============================================================================
# Image resolution helper
# =============================================================================
def _resolve_image_to_base64(image_source: str) -> tuple[str, str]:
    """
    Resolve an image source to (base64_data, mime_type).
    
    Handles:
    - stash:// refs -> resolve to local path -> read + encode
    - Local file paths -> read + encode
    - http/https URLs -> download + encode
    - data: URIs -> extract base64 + mime
    - /api/uploads/ and /api/images/ web paths
    
    Returns:
        Tuple of (base64_encoded_data, mime_type)
    """
    from stash_helper import safe_resolve_file
    
    # Already a data URI - extract parts
    if image_source.startswith('data:'):
        # Format: data:image/jpeg;base64,/9j/4AAQ...
        header, data = image_source.split(',', 1)
        mime = header.split(':')[1].split(';')[0]
        return data, mime
    
    # HTTP/HTTPS URL - download it
    if image_source.startswith(('http://', 'https://')):
        resp = requests.get(image_source, timeout=60)
        resp.raise_for_status()
        content_type = resp.headers.get('Content-Type', 'image/jpeg').split(';')[0]
        return base64.b64encode(resp.content).decode('utf-8'), content_type
    
    # Stash reference
    local_path = None
    if image_source.startswith('stash://'):
        result = safe_resolve_file(stash_ref=image_source)
        if result['found']:
            local_path = result['path']
        else:
            raise ValueError(f"Stash file not found: {result.get('error', image_source)}")
    
    # Relative web paths from WebUI
    if not local_path and image_source.startswith('/api/uploads/'):
        filename = image_source.split('/')[-1]
        candidate = Path(__file__).parent.parent / 'jarvis-web' / 'data' / 'uploads' / filename
        if candidate.exists():
            local_path = str(candidate)
    
    if not local_path and image_source.startswith('/api/images/'):
        filename = image_source.split('/')[-1]
        candidate = Path(__file__).parent.parent / 'data' / 'generated_images' / filename
        if candidate.exists():
            local_path = str(candidate)
    
    # Direct local file path
    if not local_path and Path(image_source).is_file():
        local_path = image_source
    
    if not local_path:
        raise ValueError(f"Could not resolve image source: {image_source[:200]}")
    
    # Read file and encode
    mime_type = mimetypes.guess_type(local_path)[0] or 'image/jpeg'
    with open(local_path, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode('utf-8'), mime_type


def generate_image_xai(prompt: str, aspect_ratio: str = "square", style: str = None,
                       negative_prompt: str = None, n: int = 1,
                       reference_image: str = None) -> dict:
    """
    Generate or edit an image using xAI Grok Imagine API.
    
    Args:
        prompt: What to generate or edit instructions
        aspect_ratio: square, landscape, portrait, wide, tall, 4:3, 3:4, etc.
        style: Optional art style to prepend
        negative_prompt: Things to avoid (appended to prompt)
        n: Number of images to generate (1-10)
        reference_image: Source image for editing (stash ref, path, URL, or data URI)
    """
    
    api_key = get_config_value('XAI_API_KEY')
    if not api_key:
        raise ValueError("XAI_API_KEY not configured. Add it to config/cloud.env")
    
    # Get model from env or use default
    model_name = get_config_value('XAI_IMAGE_MODEL', DEFAULT_XAI_IMAGE_MODEL)
    
    # Build the prompt
    full_prompt = prompt
    if style:
        full_prompt = f"{style} style: {prompt}"
    if negative_prompt:
        full_prompt += f". Do not include: {negative_prompt}"
    
    # Map aspect ratio
    aspect_key = str(aspect_ratio or "square").strip().lower()
    ar = XAI_ASPECT_RATIOS.get(aspect_key, "1:1")
    
    # Validate n (1-10), force n=1 when editing
    if reference_image:
        n = 1
    else:
        n = max(1, min(10, n))
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model_name,
        "prompt": full_prompt,
        "n": n
    }
    
    # Use URL format for batch (n > 1), base64 for single
    # xAI batch generation works better with URL format
    if n > 1:
        # URLs for batch - we'll download them
        pass  # Default is URL
    else:
        payload["response_format"] = "b64_json"
    
    # Add aspect ratio if not default
    if ar != "1:1":
        payload["aspect_ratio"] = ar
    
    # Add reference image for editing (image-to-image)
    # xAI /v1/images/edits requires: "image": { "url": "data:<mime>;base64,<data>" }
    is_edit = False
    if reference_image:
        is_edit = True
        img_b64, img_mime = _resolve_image_to_base64(reference_image)
        payload["image"] = {"url": f"data:{img_mime};base64,{img_b64}"}
        print(f"[generate_image] xAI image editing mode - using /v1/images/edits endpoint", file=sys.stderr)
    
    # Use /v1/images/edits for editing, /v1/images/generations for new images
    api_url = XAI_EDIT_API if is_edit else XAI_API_BASE
    
    # Make request (longer timeout for batch)
    timeout = 120 + (n - 1) * 30  # Extra time per image
    response = requests.post(
        api_url,
        headers=headers,
        json=payload,
        timeout=timeout
    )
    
    if response.status_code != 200:
        error_msg = response.text
        try:
            error_data = response.json()
            error_msg = error_data.get('error', {}).get('message', response.text)
        except:
            pass
        raise Exception(f"xAI API error ({response.status_code}): {error_msg}")
    
    result = response.json()
    
    # Extract images from response
    data = result.get('data', [])
    if not data:
        raise Exception("No image generated - empty response from xAI")
    
    # Handle both URL and base64 responses
    images = []
    for item in data:
        # Try base64 first
        image_b64 = item.get('b64_json')
        if image_b64:
            images.append(image_b64)
        # Try URL and download
        elif item.get('url'):
            try:
                img_response = requests.get(item['url'], timeout=60)
                if img_response.status_code == 200:
                    images.append(base64.b64encode(img_response.content).decode('utf-8'))
            except Exception as e:
                print(f"Warning: Failed to download image from URL: {e}", file=sys.stderr)
    
    if not images:
        raise Exception("No image data in response")
    
    return {
        "image_base64": images[0],  # Primary image
        "all_images": images if len(images) > 1 else None,  # All images if multiple returned
        "image_count": len(images),
        "requested_count": n,
        "mime_type": "image/png",  # xAI returns PNG
        "prompt": prompt,
        "full_prompt": full_prompt,
        "model": model_name,
        "provider": "xai",
        "aspect_ratio": ar,
        "is_edit": reference_image is not None,
        "used_grounding": False
    }


def generate_image_gemini(prompt: str, aspect_ratio: str = "square", image_size: str = "2K",
                          use_grounding: bool = False, style: str = None, 
                          negative_prompt: str = None, context_data: str = None,
                          reference_image: str = None) -> dict:
    """
    Generate or edit an image using Google Gemini API.
    
    Args:
        prompt: What to generate or edit instructions
        aspect_ratio: square, landscape, portrait, wide, tall, 4:3, 3:4
        image_size: 1K, 2K, or 4K resolution
        use_grounding: Enable Google Search for real-time data (weather, stocks, etc.)
        style: Optional art style
        negative_prompt: Things to avoid
        context_data: Additional data from other Jarvis tools to incorporate
        reference_image: Source image for editing (stash ref, path, URL, or data URI)
    """
    
    api_key = get_config_value('GEMINI_API_KEY')
    if not api_key:
        raise ValueError("GEMINI_API_KEY not configured. Add it to config/cloud.env")
    
    # Get model from env or use default
    model_name = get_config_value('GEMINI_IMAGE_MODEL', DEFAULT_GEMINI_MODEL)
    
    # Build the prompt
    full_prompt = prompt
    if style:
        full_prompt = f"{style} style: {prompt}"
    if negative_prompt:
        full_prompt += f". Avoid: {negative_prompt}"
    if context_data:
        full_prompt += f"\n\nUse this real-time data for accuracy:\n{context_data}"
    
    # Get aspect ratio
    aspect_key = str(aspect_ratio or "square").strip().lower()
    ar = GEMINI_ASPECT_RATIOS.get(aspect_key, "1:1")
    
    # Validate image size
    size = image_size.upper() if image_size.upper() in IMAGE_SIZES else "2K"
    
    # Build request URL
    url = f"{GEMINI_API_BASE}/{model_name}:generateContent?key={api_key}"
    
    headers = {
        "Content-Type": "application/json"
    }
    
    # Build content parts
    parts = []
    
    # Add reference image for editing (image-to-image)
    # Gemini accepts inline_data in the parts array alongside the text prompt
    if reference_image:
        img_b64, img_mime = _resolve_image_to_base64(reference_image)
        parts.append({
            "inline_data": {
                "mime_type": img_mime,
                "data": img_b64
            }
        })
        parts.append({"text": f"Edit this image: {full_prompt}"})
        print(f"[generate_image] Gemini image editing mode - reference image resolved", file=sys.stderr)
    else:
        parts.append({"text": f"Generate an image: {full_prompt}"})
    
    # Build payload with Gemini format
    payload = {
        "contents": [
            {
                "parts": parts
            }
        ],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"]
        }
    }
    
    # Add Google Search grounding if requested (for real-time data)
    if use_grounding:
        payload["tools"] = [{"googleSearch": {}}]
    
    # Add image config for aspect ratio and size
    # Note: imageConfig may not be supported on all models
    if model_name.startswith("gemini-3"):
        payload["generationConfig"]["imageConfig"] = {
            "aspectRatio": ar,
            "imageSize": size
        }
    
    # Make request (Gemini 3 with grounding can take 3-5 minutes)
    timeout = 300 if use_grounding else 180
    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=timeout
    )
    
    if response.status_code != 200:
        error_msg = response.text
        try:
            error_data = response.json()
            error_msg = error_data.get('error', {}).get('message', response.text)
        except:
            pass
        raise Exception(f"Gemini API error ({response.status_code}): {error_msg}")
    
    result = response.json()
    
    # Extract image from response
    candidates = result.get('candidates', [])
    if not candidates:
        raise Exception("No image generated - empty response from Gemini")
    
    parts = candidates[0].get('content', {}).get('parts', [])
    
    image_data = None
    text_response = None
    grounding_metadata = None
    
    for part in parts:
        if 'inlineData' in part:
            image_data = part['inlineData']
        elif 'text' in part:
            text_response = part['text']
    
    # Check for grounding metadata
    grounding_meta = candidates[0].get('groundingMetadata')
    if grounding_meta:
        grounding_metadata = {
            "search_queries": grounding_meta.get('webSearchQueries', []),
            "sources": [
                {"title": s.get('web', {}).get('title'), "uri": s.get('web', {}).get('uri')}
                for s in grounding_meta.get('groundingChunks', [])
            ]
        }
    
    if not image_data:
        if text_response:
            raise Exception(f"No image generated. Gemini says: {text_response}")
        raise Exception("No image data in response")
    
    return {
        "image_base64": image_data.get('data'),
        "mime_type": image_data.get('mimeType', 'image/png'),
        "prompt": prompt,
        "full_prompt": full_prompt,
        "model": model_name,
        "provider": "gemini",
        "aspect_ratio": ar,
        "image_size": size,
        "is_edit": reference_image is not None,
        "text_response": text_response,
        "grounding": grounding_metadata,
        "used_grounding": use_grounding
    }


def generate_image_openai(prompt: str, aspect_ratio: str = "square", quality: str = "medium",
                          style: str = None, negative_prompt: str = None,
                          transparent: bool = False, output_format: str = "png",
                          reference_image: str = None) -> dict:
    """
    Generate or edit an image using OpenAI GPT Image API.
    
    For text-to-image: uses POST /v1/images/generations (JSON body).
    For image editing: uses POST /v1/images/edits (multipart/form-data).
    
    Args:
        prompt: What to generate or edit instructions
        aspect_ratio: square, landscape, portrait
        quality: low, medium, high (or 1K, 2K, 4K mapped to quality)
        style: Optional art style to prepend
        negative_prompt: Things to avoid (appended to prompt)
        transparent: Enable transparent background (png/webp only)
        output_format: png, jpeg, or webp
        reference_image: Source image for editing (stash ref, path, URL, or data URI)
    """
    
    api_key = get_config_value('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("OPENAI_API_KEY not configured. Add it to config/cloud.env")
    
    # Get model from env or use default
    model_name = get_config_value('OPENAI_IMAGE_MODEL', DEFAULT_OPENAI_MODEL)
    
    # Build the prompt
    full_prompt = prompt
    if style:
        full_prompt = f"{style} style: {prompt}"
    if negative_prompt:
        full_prompt += f". Do not include: {negative_prompt}"
    
    # Map quality (handle both 1K/2K/4K and low/medium/high)
    quality_setting = OPENAI_QUALITY_MAP.get(quality.upper() if quality else "2K", 
                                              OPENAI_QUALITY_MAP.get(quality.lower() if quality else "medium", "medium"))

    # Map aspect ratio and requested size to OpenAI dimensions. gpt-image-2
    # supports larger flexible sizes, while earlier models keep the legacy set.
    size = _resolve_openai_size(model_name, aspect_ratio, quality)

    if transparent and _is_gpt_image_2(model_name):
        print("[generate_image] OpenAI gpt-image-2 does not support transparent backgrounds; using default background", file=sys.stderr)
        transparent = False

    endpoint_label = "edits" if reference_image else "generations"
    print(
        f"[generate_image] OpenAI request model={model_name}, endpoint={endpoint_label}, "
        f"size={size}, quality={quality_setting}, format={output_format}, "
        f"reference_image={'yes' if reference_image else 'no'}",
        file=sys.stderr
    )
    
    timeout = 180  # OpenAI can take up to 2 minutes for complex prompts
    
    if reference_image:
        # ---- IMAGE EDITING: POST /v1/images/edits (multipart/form-data) ----
        print(f"[generate_image] OpenAI image editing mode - reference image resolved", file=sys.stderr)
        
        img_b64, img_mime = _resolve_image_to_base64(reference_image)
        img_bytes = base64.b64decode(img_b64)
        
        # Determine file extension from mime
        ext_map = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
        ext = ext_map.get(img_mime, "png")
        
        headers = {
            "Authorization": f"Bearer {api_key}"
            # No Content-Type - requests sets multipart boundary automatically
        }
        
        files = {
            "image": (f"source.{ext}", img_bytes, img_mime)
        }
        
        form_data = {
            "model": model_name,
            "prompt": full_prompt,
            "size": size,
            "quality": quality_setting,
            "n": "1"
        }
        
        response = requests.post(
            OPENAI_EDIT_API,
            headers=headers,
            files=files,
            data=form_data,
            timeout=timeout
        )
    else:
        # ---- TEXT-TO-IMAGE: POST /v1/images/generations (JSON) ----
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model_name,
            "prompt": full_prompt,
            "size": size,
            "quality": quality_setting,
            "n": 1
        }
        
        # Handle transparent background (gpt-image-2 does not support this)
        if transparent and output_format in ("png", "webp"):
            payload["background"] = "transparent"
        
        # Set output format (default png)
        if output_format in ("jpeg", "webp"):
            payload["output_format"] = output_format
        
        response = requests.post(
            OPENAI_API_BASE,
            headers=headers,
            json=payload,
            timeout=timeout
        )
    
    if response.status_code != 200:
        error_msg = response.text
        try:
            error_data = response.json()
            error_msg = error_data.get('error', {}).get('message', response.text)
        except:
            pass
        raise Exception(f"OpenAI API error ({response.status_code}): {error_msg}")
    
    result = response.json()
    
    # Extract image from response (same format for both endpoints)
    data = result.get('data', [])
    if not data:
        raise Exception("No image generated - empty response from OpenAI")
    
    image_b64 = data[0].get('b64_json')
    if not image_b64:
        raise Exception("No image data in response")
    
    # Determine mime type
    mime_map = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
    mime_type = mime_map.get(output_format, "image/png")
    
    # Get revised prompt if available
    revised_prompt = data[0].get('revised_prompt')
    
    return {
        "image_base64": image_b64,
        "mime_type": mime_type,
        "prompt": prompt,
        "full_prompt": full_prompt,
        "revised_prompt": revised_prompt,
        "model": model_name,
        "provider": "openai",
        "aspect_ratio": aspect_ratio,
        "size": size,
        "quality": quality_setting,
        "transparent": transparent,
        "is_edit": reference_image is not None,
        "used_grounding": False  # OpenAI doesn't have grounding
    }


def generate_image(prompt: str, aspect_ratio: str = "square", image_size: str = "2K",
                   use_grounding: bool = False, style: str = None, 
                   negative_prompt: str = None, context_data: str = None,
                   transparent: bool = False, output_format: str = "png",
                   provider: str = None, n: int = 1,
                   reference_image: str = None) -> dict:
    """
    Generate or edit an image using configured provider (Gemini, OpenAI, or xAI).
    
    When reference_image is provided, edits that image based on the prompt.
    Otherwise generates a new image from the text prompt.
    
    Args:
        prompt: What to generate or edit instructions
        aspect_ratio: square, landscape, portrait, wide, tall, 4:3, 3:4
        image_size: 1K, 2K, or 4K (maps to quality for OpenAI)
        use_grounding: Enable Google Search for real-time data (Gemini only)
        style: Optional art style
        negative_prompt: Things to avoid
        context_data: Additional data from other Jarvis tools (Gemini only)
        transparent: Enable transparent background (OpenAI only, png/webp)
        output_format: png, jpeg, or webp (OpenAI only)
        provider: Override provider (gemini, openai, or xai)
        n: Number of images to generate (xAI only, 1-10)
        reference_image: Source image for editing (stash ref, path, URL, or data URI)
    """
    
    # Determine provider
    # get_config_value checks JARVIS_OVERRIDE_ prefix first (web UI settings),
    # then falls back to cloud.env default. LLM-passed provider is ignored
    # when a config/override value exists.
    provider = get_config_value('IMAGE_TOOL_PROVIDER', provider or 'gemini').lower()
    
    if reference_image:
        mode_label = "editing" if reference_image else "generating"
        print(f"[generate_image] {mode_label} with {provider}, reference_image={'yes' if reference_image else 'no'}", file=sys.stderr)
    
    if provider == 'openai':
        return generate_image_openai(
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            quality=image_size,  # Map 1K/2K/4K to quality
            style=style,
            negative_prompt=negative_prompt,
            transparent=transparent,
            output_format=output_format,
            reference_image=reference_image
        )
    elif provider == 'xai':
        return generate_image_xai(
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            style=style,
            negative_prompt=negative_prompt,
            n=n,
            reference_image=reference_image
        )
    else:
        # Default to Gemini
        return generate_image_gemini(
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            use_grounding=use_grounding,
            style=style,
            negative_prompt=negative_prompt,
            context_data=context_data,
            reference_image=reference_image
        )


def save_to_stash(image_data: dict, prompt: str) -> dict:
    """Save generated image to stash for use with other tools."""
    
    # Generate a filename from the prompt
    safe_prompt = "".join(c if c.isalnum() or c in ' -_' else '' for c in prompt[:40])
    safe_prompt = safe_prompt.replace(' ', '_').lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Determine extension from mime type
    mime = image_data.get('mime_type', 'image/png')
    ext = 'png' if 'png' in mime else 'jpg' if 'jpeg' in mime or 'jpg' in mime else 'webp' if 'webp' in mime else 'png'
    filename = f"generated_{safe_prompt}_{timestamp}.{ext}"
    
    # Decode image
    image_bytes = base64.b64decode(image_data['image_base64'])
    
    # Save directly to generated_images (always as primary storage)
    # This ensures we always have the file, and stash becomes an index
    images_dir = Path(__file__).parent.parent / 'data' / 'generated_images'
    images_dir.mkdir(exist_ok=True)
    image_path = images_dir / filename
    image_path.write_bytes(image_bytes)
    
    # Also create a stash reference for discoverability
    # Use stash helper directly to avoid subprocess overhead
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
        from stash_helper import open_space, StashFile
        
        space, _ = open_space(scope='session', labels=['generated_images'])
        stash_file = StashFile(space)
        
        # Get provider tag
        provider = image_data.get('provider', 'gemini')
        is_edit = image_data.get('is_edit', False)
        
        # Tag differently for edited vs generated
        base_tag = 'image_edited' if is_edit else 'ai_generated'
        
        # Save as binary to stash
        result = stash_file.save_binary(
            data=image_bytes,
            name=filename,
            mime_type=mime,
            on_conflict='overwrite',
            tags=[base_tag, provider, image_data.get('aspect_ratio', 'square')],
            tool_origin='generate_image'
        )
        
        return {
            "saved": True,
            "stash_ref": result.get('ref'),
            "space_id": space.space_id,
            "path": str(image_path),
            "stash_path": result.get('path'),
            "filename": filename,
            "stash": True
        }
    except Exception as e:
        # Stash failed but file is saved
        return {
            "saved": True,
            "path": str(image_path),
            "filename": filename,
            "stash": False,
            "note": f"File saved but stash indexing failed: {e}"
        }


def save_additional_images(all_images: list, prompt: str, provider: str, space_id: str = None) -> list:
    """Save additional images when n > 1 (xAI batch generation).
    
    Args:
        all_images: List of base64-encoded images
        prompt: Original prompt
        provider: Provider name (xai)
        space_id: Stash space ID to add images to (same space as first image)
    """
    saved_files = []
    
    # Skip first image (already saved by save_to_stash)
    if len(all_images) <= 1:
        return saved_files
    
    images_dir = Path(__file__).parent.parent / 'data' / 'generated_images'
    images_dir.mkdir(exist_ok=True)
    
    safe_prompt = "".join(c if c.isalnum() or c in ' -_' else '' for c in prompt[:40])
    safe_prompt = safe_prompt.replace(' ', '_').lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Try to get stash helper for adding to same space
    stash_file = None
    if space_id:
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
            from stash_helper import StashSpace, StashFile
            space = StashSpace(space_id)
            stash_file = StashFile(space)
        except Exception as e:
            print(f"Warning: Could not open stash space {space_id}: {e}", file=sys.stderr)
    
    for i, img_b64 in enumerate(all_images[1:], start=2):
        filename = f"generated_{safe_prompt}_{timestamp}_{i}.png"
        image_bytes = base64.b64decode(img_b64)
        
        # Save to generated_images
        image_path = images_dir / filename
        image_path.write_bytes(image_bytes)
        
        file_info = {
            "filename": filename,
            "path": str(image_path)
        }
        
        # Also add to stash (same space as first image)
        if stash_file:
            try:
                result = stash_file.save_binary(
                    data=image_bytes,
                    name=filename,
                    mime_type="image/png",
                    on_conflict='overwrite',
                    tags=['ai_generated', provider, 'batch'],
                    tool_origin='generate_image'
                )
                file_info["stash_ref"] = result.get('ref')
            except Exception:
                pass
        
        saved_files.append(file_info)
    
    return saved_files


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
            raise ValueError("prompt is required - describe what image you want to generate")
        
        # Parameters
        aspect_ratio = args.get('aspect_ratio', 'square')
        image_size = args.get('image_size', '2K')
        use_grounding = args.get('use_grounding', False)
        style = args.get('style')
        negative_prompt = args.get('negative_prompt')
        context_data = args.get('context_data')  # Data from other Jarvis tools
        save = args.get('save', True)
        
        # OpenAI-specific parameters
        transparent = args.get('transparent', False)
        output_format = args.get('output_format', 'png')
        provider = args.get('provider')  # Override provider if specified
        
        # xAI-specific parameters
        n = args.get('n', 1)  # Number of images (xAI supports 1-10)
        
        # Image-to-image editing
        reference_image = args.get('reference_image')  # stash ref, path, URL, or data URI
        
        # Generate or edit the image
        result = generate_image(
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            use_grounding=use_grounding,
            style=style,
            negative_prompt=negative_prompt,
            context_data=context_data,
            transparent=transparent,
            output_format=output_format,
            provider=provider,
            n=n,
            reference_image=reference_image
        )
        
        # Save to stash if requested
        save_info = None
        if save:
            save_info = save_to_stash(result, prompt)
            
            # Also save to memory for cross-session discovery
            # Memory points to stash - stash is the source of truth
            try:
                from memory_db import MemoryDB
                db = MemoryDB()
                
                # Create a searchable memory entry that points to stash
                stash_ref = save_info.get('stash_ref', '')
                space_id = save_info.get('space_id', '')
                
                memory_key = f"stash_image_{space_id}" if space_id else f"generated_image_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                memory_value = f"Generated image: {prompt[:150]}. STASH: {stash_ref}. FILE: {save_info.get('filename')}"
                
                db.remember(
                    key=memory_key,
                    value=memory_value,
                    category="stash_artifact",
                    importance=6,  # Higher importance for stash items
                    source="generate_image",
                    metadata={
                        "stash_ref": stash_ref,
                        "space_id": space_id,
                        "filename": save_info.get('filename', ''),
                        "prompt": prompt[:200],
                        "provider": result.get('provider', 'gemini'),
                        "model": result.get('model', ''),
                        "tags": ["image", "generated", "ai_created"],
                        "type": "image"
                    }
                )
            except Exception:
                pass  # Don't fail the tool if memory save fails
        
        # Build response
        provider_used = result.get('provider', 'gemini')
        is_edit = result.get('is_edit', False)
        action_word = "Edited image" if is_edit else "Generated image"
        speech = f"{action_word} with {provider_used}: {prompt[:50]}{'...' if len(prompt) > 50 else ''}"
        
        response = {
            "ok": True,
            "speech": speech,
            "data": {
                "prompt": prompt,
                "provider": provider_used,
                "model": result['model'],
                "aspect_ratio": result.get('aspect_ratio'),
                "mime_type": result['mime_type'],
                "is_edit": is_edit,
                "used_grounding": result.get('used_grounding', False)
            }
        }
        
        # Add provider-specific fields
        if provider_used == 'gemini':
            response["data"]["image_size"] = result.get('image_size')
        elif provider_used == 'openai':
            response["data"]["size"] = result.get('size')
            response["data"]["quality"] = result.get('quality')
            if result.get('transparent'):
                response["data"]["transparent"] = True
            if result.get('revised_prompt'):
                response["data"]["revised_prompt"] = result['revised_prompt']
        elif provider_used == 'xai':
            if result.get('image_count', 1) > 1:
                response["data"]["image_count"] = result['image_count']
                response["speech"] += f" ({result['image_count']} images)"
                
                # Save additional images when n > 1 (same stash space)
                if save and result.get('all_images'):
                    space_id = save_info.get('space_id') if save_info else None
                    additional = save_additional_images(
                        result['all_images'], 
                        prompt, 
                        provider_used,
                        space_id
                    )
                    if additional:
                        response["data"]["additional_images"] = additional
        
        # Add save info
        if save_info:
            response["data"]["saved"] = save_info
            if save_info.get('path'):
                response["speech"] += ". Saved to stash."
                response["data"]["file_path"] = save_info['path']
        
        # Add grounding sources if used (Gemini only)
        if result.get('grounding'):
            response["data"]["grounding_sources"] = result['grounding']
        
        # Add Gemini's text response (often describes what it created)
        if result.get('text_response'):
            response["data"]["gemini_note"] = result['text_response']
        
        print(json.dumps(response))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "speech": f"Failed to generate image: {e}",
            "error": str(e)
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
