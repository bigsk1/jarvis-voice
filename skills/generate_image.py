#!/usr/bin/env python3
"""
Image Generation Tool for Jarvis
Generates images using Google Gemini 3 Pro Image Preview (Nano Banana Pro)

Features:
  - Google Search grounding for real-time data (weather, stocks, current events)
  - 4K resolution support
  - Multiple aspect ratios
  - Saves to stash for use with email, printer, canvas, pdf_create, etc.

Models:
  - gemini-3-pro-image-preview: Best quality with grounding support (Dec 2025)

Output: Saves to stash for multi-tool workflows
"""

import sys
import os
import json
import base64
import requests
from pathlib import Path
from datetime import datetime

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
from config_loader import load_config, get_config_value

# Gemini API endpoint
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Default model (override via GEMINI_IMAGE_MODEL env var)
DEFAULT_MODEL = "gemini-2.0-flash-preview-image-generation"

# Aspect ratios supported by Gemini 3 Pro Image
# Valid: 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9
ASPECT_RATIOS = {
    "square": "1:1",
    "landscape": "16:9",
    "portrait": "9:16",
    "wide": "21:9",
    "tall": "9:16",      # Use portrait for tall (no 9:21)
    "4:3": "4:3",
    "3:4": "3:4",
    "2:3": "2:3",
    "3:2": "3:2",
    "4:5": "4:5",
    "5:4": "5:4"
}

# Image sizes
IMAGE_SIZES = ["1K", "2K", "4K"]


def generate_image(prompt: str, aspect_ratio: str = "square", image_size: str = "2K",
                   use_grounding: bool = False, style: str = None, 
                   negative_prompt: str = None, context_data: str = None) -> dict:
    """
    Generate an image using Gemini 3 API.
    
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
    model_name = get_config_value('GEMINI_IMAGE_MODEL', DEFAULT_MODEL)
    
    # Build the prompt
    full_prompt = prompt
    if style:
        full_prompt = f"{style} style: {prompt}"
    if negative_prompt:
        full_prompt += f". Avoid: {negative_prompt}"
    if context_data:
        full_prompt += f"\n\nUse this real-time data for accuracy:\n{context_data}"
    
    # Get aspect ratio
    ar = ASPECT_RATIOS.get(aspect_ratio, ASPECT_RATIOS.get(aspect_ratio, "1:1"))
    
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
        "aspect_ratio": ar,
        "image_size": size,
        "text_response": text_response,
        "grounding": grounding_metadata,
        "used_grounding": use_grounding
    }


def save_to_stash(image_data: dict, prompt: str) -> dict:
    """Save generated image to stash for use with other tools."""
    import subprocess
    
    # Generate a filename from the prompt
    safe_prompt = "".join(c if c.isalnum() or c in ' -_' else '' for c in prompt[:40])
    safe_prompt = safe_prompt.replace(' ', '_').lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Determine extension from mime type
    mime = image_data.get('mime_type', 'image/png')
    ext = 'png' if 'png' in mime else 'jpg' if 'jpeg' in mime or 'jpg' in mime else 'png'
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
        
        # Save as binary to stash
        result = stash_file.save_binary(
            data=image_bytes,
            name=filename,
            mime_type=mime,
            on_conflict='overwrite',
            tags=['ai_generated', 'gemini', image_data.get('aspect_ratio', 'square')],
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
        
        # Generate the image
        result = generate_image(
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            use_grounding=use_grounding,
            style=style,
            negative_prompt=negative_prompt,
            context_data=context_data
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
                    importance=6  # Higher importance for stash items
                )
            except Exception as mem_err:
                pass  # Don't fail the tool if memory save fails
        
        # Build response
        speech = f"Generated image: {prompt[:50]}{'...' if len(prompt) > 50 else ''}"
        
        response = {
            "ok": True,
            "speech": speech,
            "data": {
                "prompt": prompt,
                "model": result['model'],
                "aspect_ratio": result['aspect_ratio'],
                "image_size": result['image_size'],
                "mime_type": result['mime_type'],
                "used_grounding": result['used_grounding']
            }
        }
        
        # Add save info
        if save_info:
            response["data"]["saved"] = save_info
            if save_info.get('path'):
                response["speech"] += f". Saved to: {save_info['filename']}"
                response["data"]["file_path"] = save_info['path']
        
        # Add grounding sources if used
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
