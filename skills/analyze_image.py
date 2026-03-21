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
import requests
from pathlib import Path
from datetime import datetime

# Add lib to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
from config_loader import load_config, get_config_value


def _debug(msg: str):
    """Print debug message to stderr (not stdout, to avoid breaking JSON output)."""
    print(msg, file=sys.stderr)


def analyze_image(
    image: str,
    question: str = "Describe this image in detail.",
    stash_after: bool = False
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
        
    Returns:
        dict with analysis results, image info, and optional stash reference
    """
    # Load config (already loaded by orchestrator, but ensure it's there)
    load_config()
    
    # Determine mode from environment
    mode = get_config_value('JARVIS_MODE', 'cloud')
    
    try:
        # Resolve image source and get base64
        image_data = _resolve_image(image)
        
        if not image_data:
            return {
                "ok": False,
                "speech": f"Could not load image from: {image[:50]}...",
                "data": {"error": "Failed to load image", "source": image}
            }
        
        # Perform vision analysis
        analysis = _analyze_with_vision(
            image_data['base64'],
            question,
            mode
        )
        
        if not analysis:
            return {
                "ok": False,
                "speech": "Vision analysis failed.",
                "data": {"error": "Vision model returned no result"}
            }
        
        # Optionally stash the image (for URLs)
        stash_info = None
        if stash_after and image_data.get('source_type') == 'url':
            stash_info = _stash_image(image_data, analysis, mode)
        
        # Build response
        # Create short speech version
        short_analysis = analysis[:150] + "..." if len(analysis) > 150 else analysis
        
        response_data = {
            "analysis": analysis,
            "source": image_data.get('source_type'),
            "original_path": image,
        }
        
        if stash_info:
            response_data["stash"] = stash_info
            response_data["stash_ref"] = stash_info.get('stash_ref')
        
        return {
            "ok": True,
            "speech": short_analysis,
            "data": response_data
        }
        
    except Exception as e:
        return {
            "ok": False,
            "speech": f"Error analyzing image: {str(e)[:100]}",
            "data": {"error": str(e), "source": image}
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
        
        image_data = base64.b64encode(image_bytes).decode('utf-8')
        
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
            'size_bytes': len(image_bytes)
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
        ALLOWED_DIRS = [
            Path('/home/boss/jarvis-voice/data').resolve(),
            Path('/home/boss/jarvis-voice/stash').resolve(),
            Path('/home/boss/Downloads').resolve(),
            Path('/home/boss/Documents').resolve(),
            Path('/home/boss/Pictures').resolve(),
            Path('/tmp').resolve(),
        ]
        
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
            image_data = base64.b64encode(f.read()).decode('utf-8')
        
        return {
            'base64': image_data,
            'source_type': 'file',
            'original_path': str(file_path),
            'filename': file_path.name,
            'size_bytes': size
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
            image_data = base64.b64encode(f.read()).decode('utf-8')
        
        return {
            'base64': image_data,
            'source_type': 'stash',
            'original_path': stash_ref,
            'filename': stored_name,
            'size_bytes': file_path.stat().st_size,
            'stash_meta': file_meta
        }
    except Exception as e:
        _debug(f"[ANALYZE_IMAGE] Failed to load from stash {stash_ref}: {e}")
        return None


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


def _analyze_with_vision(image_base64: str, question: str, mode: str) -> str | None:
    """Perform vision analysis using configured model."""
    
    # SECURITY: Sanitize the question prompt
    question = _sanitize_vision_prompt(question)
    
    if mode == 'local':
        return _vision_ollama(image_base64, question)
    else:
        return _vision_cloud(image_base64, question)


def _vision_ollama(image_base64: str, question: str) -> str | None:
    """Use Ollama vision model (llava, etc)."""
    try:
        base_url = get_config_value('OLLAMA_BASE_URL', 'http://localhost:11434')
        model = get_config_value('OLLAMA_VISION_MODEL', 'llava:latest')
        
        _debug(f"[ANALYZE_IMAGE] Using Ollama vision: {model}")
        
        response = requests.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": question,
                "images": [image_base64],
                "stream": False
            },
            timeout=120
        )
        
        if response.status_code == 200:
            return response.json().get('response', '')
        else:
            _debug(f"[ANALYZE_IMAGE] Ollama error: {response.status_code}")
            return None
    except Exception as e:
        _debug(f"[ANALYZE_IMAGE] Ollama vision failed: {e}")
        return None


def _vision_cloud(image_base64: str, question: str) -> str | None:
    """Use cloud vision model (xAI Grok, Anthropic Claude, OpenAI GPT-4V)."""
    provider = get_config_value('LLM_PROVIDER', 'xai')
    vision_model = get_config_value('VISION_MODEL', '')
    
    _debug(f"[ANALYZE_IMAGE] Using cloud vision: {provider}")
    
    if provider == 'xai':
        return _vision_xai(image_base64, question, vision_model)
    elif provider == 'anthropic':
        return _vision_anthropic(image_base64, question, vision_model)
    elif provider == 'openai':
        return _vision_openai(image_base64, question, vision_model)
    else:
        # Default to xAI
        return _vision_xai(image_base64, question, vision_model)


def _vision_xai(image_base64: str, question: str, model: str = None) -> str | None:
    """Use xAI Grok for vision."""
    try:
        api_key = get_config_value('XAI_API_KEY', '')
        if not api_key:
            _debug("[ANALYZE_IMAGE] XAI_API_KEY not configured")
            return None
        
        model = model or get_config_value('VISION_MODEL') or get_config_value('XAI_MODEL', 'grok-4')
        
        response = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}",
                                "detail": "high"
                            }
                        },
                        {"type": "text", "text": question}
                    ]
                }],
                "max_tokens": 1000
            },
            timeout=120
        )
        
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        else:
            _debug(f"[ANALYZE_IMAGE] xAI error: {response.status_code} - {response.text[:200]}")
            return None
    except Exception as e:
        _debug(f"[ANALYZE_IMAGE] xAI vision failed: {e}")
        return None


def _vision_anthropic(image_base64: str, question: str, model: str = None) -> str | None:
    """Use Anthropic Claude for vision."""
    try:
        api_key = get_config_value('ANTHROPIC_API_KEY', '')
        if not api_key:
            _debug("[ANALYZE_IMAGE] ANTHROPIC_API_KEY not configured")
            return None
        
        model = model or get_config_value('ANTHROPIC_MODEL', 'claude-sonnet-4-20250514')
        
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "max_tokens": 1000,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_base64
                            }
                        },
                        {"type": "text", "text": question}
                    ]
                }]
            },
            timeout=120
        )
        
        if response.status_code == 200:
            return response.json()['content'][0]['text']
        else:
            _debug(f"[ANALYZE_IMAGE] Anthropic error: {response.status_code}")
            return None
    except Exception as e:
        _debug(f"[ANALYZE_IMAGE] Anthropic vision failed: {e}")
        return None


def _vision_openai(image_base64: str, question: str, model: str = None) -> str | None:
    """Use OpenAI GPT-4V for vision."""
    try:
        api_key = get_config_value('OPENAI_API_KEY', '')
        if not api_key:
            _debug("[ANALYZE_IMAGE] OPENAI_API_KEY not configured")
            return None
        
        model = model or get_config_value('OPENAI_MODEL', 'gpt-5.4-nano')
        
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}",
                                "detail": "high"
                            }
                        },
                        {"type": "text", "text": question}
                    ]
                }],
                "max_tokens": 1000
            },
            timeout=120
        )
        
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        else:
            _debug(f"[ANALYZE_IMAGE] OpenAI error: {response.status_code}")
            return None
    except Exception as e:
        _debug(f"[ANALYZE_IMAGE] OpenAI vision failed: {e}")
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
        if not image:
            raise ValueError("image parameter is required")
        
        question = args.get('question', 'Describe this image in detail.')
        stash_after = args.get('stash_after', False)
        
        # Run the tool
        result = analyze_image(image, question, stash_after)
        
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

