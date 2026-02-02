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
  - openai: OpenAI gpt-image-1 (best text rendering, highest quality)
  - xai: xAI Grok Imagine (fast, cheap, good quality)

Configure via IMAGE_TOOL_PROVIDER in cloud.env (default: gemini)
"""

import sys
import json
import base64
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

# Gemini aspect ratios
GEMINI_ASPECT_RATIOS = {
    "square": "1:1",
    "landscape": "16:9",
    "portrait": "9:16",
    "wide": "21:9",
    "tall": "9:16",
    "4:3": "4:3",
    "3:4": "3:4",
    "2:3": "2:3",
    "3:2": "3:2",
    "4:5": "4:5",
    "5:4": "5:4"
}

# =============================================================================
# Provider: OpenAI
# =============================================================================
OPENAI_API_BASE = "https://api.openai.com/v1/images/generations"
DEFAULT_OPENAI_MODEL = "gpt-image-1.5"  # State of the art (Dec 2025)

# OpenAI size mappings (aspect ratio -> pixel dimensions)
OPENAI_SIZES = {
    "square": "1024x1024",
    "landscape": "1536x1024",
    "portrait": "1024x1536",
    "wide": "1536x1024",      # No ultra-wide, use landscape
    "tall": "1024x1536",
    "4:3": "1536x1024",       # Approximate
    "3:4": "1024x1536",       # Approximate
    "16:9": "1536x1024",
    "9:16": "1024x1536",
    "1:1": "1024x1024"
}

# OpenAI quality mappings
OPENAI_QUALITY_MAP = {
    "1K": "low",
    "2K": "medium", 
    "4K": "high",
    "low": "low",
    "medium": "medium",
    "high": "high"
}

# =============================================================================
# Provider: xAI Grok Imagine
# =============================================================================
XAI_API_BASE = "https://api.x.ai/v1/images/generations"
DEFAULT_XAI_IMAGE_MODEL = "grok-imagine-image"

# xAI aspect ratios (supports common ratios)
XAI_ASPECT_RATIOS = {
    "square": "1:1",
    "landscape": "16:9",
    "portrait": "9:16",
    "wide": "21:9",
    "tall": "9:21",
    "4:3": "4:3",
    "3:4": "3:4",
    "2:3": "2:3",
    "3:2": "3:2",
    "16:9": "16:9",
    "9:16": "9:16",
    "1:1": "1:1"
}

# Shared image sizes
IMAGE_SIZES = ["1K", "2K", "4K"]


def generate_image_xai(prompt: str, aspect_ratio: str = "square", style: str = None,
                       negative_prompt: str = None, n: int = 1) -> dict:
    """
    Generate an image using xAI Grok Imagine API.
    
    Args:
        prompt: What to generate
        aspect_ratio: square, landscape, portrait, wide, tall, 4:3, 3:4, etc.
        style: Optional art style to prepend
        negative_prompt: Things to avoid (appended to prompt)
        n: Number of images to generate (1-10)
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
    ar = XAI_ASPECT_RATIOS.get(aspect_ratio, XAI_ASPECT_RATIOS.get(aspect_ratio, "1:1"))
    
    # Validate n (1-10)
    n = max(1, min(10, n))
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model_name,
        "prompt": full_prompt,
        "response_format": "b64_json",  # Get base64 for consistency
        "n": n
    }
    
    # Add aspect ratio if not default
    if ar != "1:1":
        payload["aspect_ratio"] = ar
    
    # Make request
    timeout = 120  # xAI is generally fast
    response = requests.post(
        XAI_API_BASE,
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
    
    # Return first image (or all if n > 1)
    images = []
    for item in data:
        image_b64 = item.get('b64_json')
        if image_b64:
            images.append(image_b64)
    
    if not images:
        raise Exception("No image data in response")
    
    return {
        "image_base64": images[0],  # Primary image
        "all_images": images if n > 1 else None,  # All images if multiple requested
        "image_count": len(images),
        "mime_type": "image/png",  # xAI returns PNG
        "prompt": prompt,
        "full_prompt": full_prompt,
        "model": model_name,
        "provider": "xai",
        "aspect_ratio": ar,
        "used_grounding": False
    }


def generate_image_gemini(prompt: str, aspect_ratio: str = "square", image_size: str = "2K",
                          use_grounding: bool = False, style: str = None, 
                          negative_prompt: str = None, context_data: str = None) -> dict:
    """
    Generate an image using Google Gemini API.
    
    Args:
        prompt: What to generate
        aspect_ratio: square, landscape, portrait, wide, tall, 4:3, 3:4
        image_size: 1K, 2K, or 4K resolution
        use_grounding: Enable Google Search for real-time data (weather, stocks, etc.)
        style: Optional art style
        negative_prompt: Things to avoid
        context_data: Additional data from other Jarvis tools to incorporate
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
    ar = GEMINI_ASPECT_RATIOS.get(aspect_ratio, GEMINI_ASPECT_RATIOS.get(aspect_ratio, "1:1"))
    
    # Validate image size
    size = image_size.upper() if image_size.upper() in IMAGE_SIZES else "2K"
    
    # Build request URL
    url = f"{GEMINI_API_BASE}/{model_name}:generateContent?key={api_key}"
    
    headers = {
        "Content-Type": "application/json"
    }
    
    # Build payload with Gemini 3 format
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"Generate an image: {full_prompt}"}
                ]
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
        "text_response": text_response,
        "grounding": grounding_metadata,
        "used_grounding": use_grounding
    }


def generate_image_openai(prompt: str, aspect_ratio: str = "square", quality: str = "medium",
                          style: str = None, negative_prompt: str = None,
                          transparent: bool = False, output_format: str = "png") -> dict:
    """
    Generate an image using OpenAI gpt-image-1 API.
    
    Args:
        prompt: What to generate
        aspect_ratio: square, landscape, portrait
        quality: low, medium, high (or 1K, 2K, 4K mapped to quality)
        style: Optional art style to prepend
        negative_prompt: Things to avoid (appended to prompt)
        transparent: Enable transparent background (png/webp only)
        output_format: png, jpeg, or webp
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
    
    # Map aspect ratio to OpenAI size
    size = OPENAI_SIZES.get(aspect_ratio, OPENAI_SIZES.get(aspect_ratio, "1024x1024"))
    
    # Map quality (handle both 1K/2K/4K and low/medium/high)
    quality_setting = OPENAI_QUALITY_MAP.get(quality.upper() if quality else "2K", 
                                              OPENAI_QUALITY_MAP.get(quality.lower() if quality else "medium", "medium"))
    
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
    
    # Handle transparent background
    if transparent and output_format in ("png", "webp"):
        payload["background"] = "transparent"
    
    # Set output format (default png)
    if output_format in ("jpeg", "webp"):
        payload["output_format"] = output_format
    
    # Make request
    timeout = 180  # OpenAI can take up to 2 minutes for complex prompts
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
    
    # Extract image from response
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
        "used_grounding": False  # OpenAI doesn't have grounding
    }


def generate_image(prompt: str, aspect_ratio: str = "square", image_size: str = "2K",
                   use_grounding: bool = False, style: str = None, 
                   negative_prompt: str = None, context_data: str = None,
                   transparent: bool = False, output_format: str = "png",
                   provider: str = None, n: int = 1) -> dict:
    """
    Generate an image using configured provider (Gemini, OpenAI, or xAI).
    
    Args:
        prompt: What to generate
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
    """
    
    # Determine provider
    if provider is None:
        provider = get_config_value('IMAGE_TOOL_PROVIDER', 'gemini').lower()
    
    if provider == 'openai':
        return generate_image_openai(
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            quality=image_size,  # Map 1K/2K/4K to quality
            style=style,
            negative_prompt=negative_prompt,
            transparent=transparent,
            output_format=output_format
        )
    elif provider == 'xai':
        return generate_image_xai(
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            style=style,
            negative_prompt=negative_prompt,
            n=n
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
            context_data=context_data
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
        
        # Save as binary to stash
        result = stash_file.save_binary(
            data=image_bytes,
            name=filename,
            mime_type=mime,
            on_conflict='overwrite',
            tags=['ai_generated', provider, image_data.get('aspect_ratio', 'square')],
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
        
        # Generate the image
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
            n=n
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
                        "tags": ["image", "generated", "ai_created"],
                        "type": "image"
                    }
                )
            except Exception:
                pass  # Don't fail the tool if memory save fails
        
        # Build response
        provider_used = result.get('provider', 'gemini')
        speech = f"Generated image with {provider_used}: {prompt[:50]}{'...' if len(prompt) > 50 else ''}"
        
        response = {
            "ok": True,
            "speech": speech,
            "data": {
                "prompt": prompt,
                "provider": provider_used,
                "model": result['model'],
                "aspect_ratio": result.get('aspect_ratio'),
                "mime_type": result['mime_type'],
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
        
        # Add save info
        if save_info:
            response["data"]["saved"] = save_info
            if save_info.get('path'):
                response["speech"] += f". Saved to: {save_info['filename']}"
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
