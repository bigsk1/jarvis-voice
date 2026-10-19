#!/usr/bin/env python3
"""
Jarvis Skill: Screenshot URL
Takes a screenshot of a webpage using Crawl4AI and optionally analyzes it with vision.

Use cases:
- Debug why a crawl isn't working (see what the page looks like)
- Extract info from visual-heavy sites (charts, graphs, infographics)
- Capture page state at a point in time
- Analyze page layout, UI elements, or visual content

Security:
- SSRF protection via stash_helper.validate_url()
- Blocks internal/private IPs
"""
import json
import os
import sys
import tempfile
from base64 import b64decode
from datetime import datetime
from pathlib import Path

import requests

# Add lib to path for security checks
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import get_config_value, load_config
from http_client import http_request
from paths import resolve_local_file_tool_output_path


def resolve_screenshot_output_path(save_path: str | None) -> Path:
    """Resolve a screenshot destination under an allowed writable directory."""
    if save_path:
        candidate = Path(save_path).expanduser()
    else:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        candidate = Path(tempfile.gettempdir()) / f"screenshot_{timestamp}.png"

    # Screenshots are normalized to JPEG after decoding.
    if candidate.suffix.lower() == '.png':
        candidate = candidate.with_suffix('.jpg')
    return resolve_local_file_tool_output_path(candidate, label="Screenshot output path")


def main():
    """Take screenshot of URL and optionally analyze."""
    load_config()
    try:
        input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except (json.JSONDecodeError, IndexError):
        return_error("Invalid JSON input")
        return 1
    if not isinstance(input_data, dict):
        return_error("Input must be a JSON object")
        return 1
    
    # Get configuration from environment
    crawl4ai_url = get_config_value("CRAWL4AI_URL", "").rstrip("/")
    crawl4ai_api_key = get_config_value("CRAWL4AI_API_KEY", "").strip()
    
    if not crawl4ai_url:
        return_error("CRAWL4AI_URL not configured")
        return 1
    if not crawl4ai_api_key:
        return_error("CRAWL4AI_API_KEY not configured")
        return 1
    
    # Extract parameters
    url = input_data.get("url")
    if not isinstance(url, str) or not url:
        return_error("URL is required")
        return 1
    
    # SECURITY: Validate URL to prevent SSRF
    try:
        from stash_helper import SecurityError, validate_url
    except ImportError:
        return_error("URL security validation unavailable; screenshot was not requested")
        return 1
    try:
        validate_url(url)
    except SecurityError as e:
        return_error(f"URL blocked for security: {e}")
        return 1
    
    wait_seconds = input_data.get("wait", 2)  # Wait before screenshot
    analyze = input_data.get("analyze", False)  # Run vision analysis
    question = input_data.get("question", "Describe what you see on this webpage. Note any key information, text, or UI elements visible.")
    save_path = input_data.get("save_path")  # Optional: save to specific path

    # Build headers
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {crawl4ai_api_key}",
    }
    
    # Build request body
    body = {
        "url": url,
        "screenshot_wait_for": wait_seconds
    }
    
    try:
        # Take screenshot via crawl4ai
        response = http_request(
            "POST",
            f"{crawl4ai_url}/screenshot",
            headers=headers,
            json=body,
            timeout=45, allow_redirects=False, proxy_policy="off"
        )
        
        if response.status_code == 401:
            return_error("Authentication failed")
            return 1
        if response.status_code == 403:
            return_error("Crawl4AI access forbidden; check token and enabled API features")
            return 1
        if 300 <= response.status_code < 400:
            return_error("Crawl4AI redirected the authenticated request; configure its final API URL")
            return 1
        
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or result.get("success") is False:
            return_error("Crawl4AI reported a failed screenshot")
            return 1
        
        # Get screenshot data (base64 PNG)
        screenshot_b64 = result.get("screenshot")
        if not screenshot_b64:
            return_error("No screenshot returned")
            return 1
        
        # Save to file
        file_path = resolve_screenshot_output_path(save_path)
        
        # Decode and convert to proper PNG/JPEG
        screenshot_bytes = b64decode(screenshot_b64)
        
        # Convert to proper format and resize if needed (for vision APIs)
        try:
            import io

            from PIL import Image
            
            # Load image
            img = Image.open(io.BytesIO(screenshot_bytes))
            
            # Resize if too large (max 2000px on longest side for vision APIs)
            max_dim = 2000
            if max(img.size) > max_dim:
                ratio = max_dim / max(img.size)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)
            
            # Convert to RGB if needed (remove alpha channel)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            # Save as JPEG (much smaller than PNG/BMP)
            img.save(file_path, 'JPEG', quality=85, optimize=True)
            screenshot_bytes = open(file_path, 'rb').read()
            
        except ImportError:
            # PIL not available, save raw
            with open(file_path, 'wb') as f:
                f.write(screenshot_bytes)
        except Exception as img_err:
            print(f"Image processing failed: {img_err}, saving raw", file=sys.stderr)
            with open(file_path, 'wb') as f:
                f.write(screenshot_bytes)
        
        response_data = {
            "url": url,
            "screenshot_path": str(file_path),
            "size_bytes": len(screenshot_bytes),
            "wait_seconds": wait_seconds
        }
        
        # Optionally analyze with vision
        if analyze:
            analysis = _analyze_screenshot(str(file_path), question)
            if analysis:
                response_data["analysis"] = analysis
                return_success(
                    speech=analysis[:200] + "..." if len(analysis) > 200 else analysis,
                    data=response_data
                )
            else:
                return_success(
                    speech="Screenshot saved. Vision analysis failed.",
                    data=response_data
                )
        else:
            return_success(
                speech="Screenshot saved.",
                data=response_data
            )
        
        return 0
        
    except requests.Timeout:
        return_error("Screenshot request timed out")
        return 1
    except requests.RequestException as e:
        return_error(f"Screenshot failed: {str(e)}")
        return 1
    except Exception as e:
        return_error(f"Unexpected error: {str(e)}")
        return 1


def _analyze_screenshot(image_path: str, question: str) -> str | None:
    """Analyze screenshot using analyze_image tool's vision capabilities."""
    try:
        # Import analyze_image function
        sys.path.insert(0, str(Path(__file__).parent))
        from analyze_image import analyze_image
        
        result = analyze_image(image_path, question, stash_after=False)
        
        if result.get("ok"):
            return result.get("data", {}).get("analysis", "")
        else:
            return None
    except Exception as e:
        print(f"Vision analysis failed: {e}", file=sys.stderr)
        return None


def return_success(speech, data=None):
    """Return success response."""
    result = {"ok": True, "speech": speech}
    if data:
        result["data"] = data
    print(json.dumps(result))


def return_error(speech, data=None):
    """Return error response."""
    result = {"ok": False, "speech": speech, "error": speech}
    if data:
        result["data"] = data
    print(json.dumps(result))


if __name__ == "__main__":
    sys.exit(main())
