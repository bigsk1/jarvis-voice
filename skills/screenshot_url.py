#!/usr/bin/env python3
"""
Jarvis Skill: Screenshot URL
Takes a screenshot of a webpage using Crawl4AI and optionally analyzes it with vision.

Use cases:
- Debug why a crawl isn't working (see what the page looks like)
- Extract info from visual-heavy sites (charts, graphs, infographics)
- Capture page state at a point in time
- Analyze page layout, UI elements, or visual content
"""
import sys
import os
import json
import requests
import tempfile
from base64 import b64encode, b64decode
from pathlib import Path
from datetime import datetime


def main():
    """Take screenshot of URL and optionally analyze."""
    try:
        input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except (json.JSONDecodeError, IndexError):
        return_error("Invalid JSON input")
        return 1
    
    # Get configuration from environment
    crawl4ai_url = os.environ.get("CRAWL4AI_URL", "").rstrip("/")
    crawl4ai_user = os.environ.get("CRAWL4AI_USER", "")
    crawl4ai_pass = os.environ.get("CRAWL4AI_PASS", "")
    crawl4ai_api_key = os.environ.get("CRAWL4AI_API_KEY", "")
    
    if not crawl4ai_url:
        return_error("CRAWL4AI_URL not configured")
        return 1
    
    # Extract parameters
    url = input_data.get("url")
    if not url:
        return_error("URL is required")
        return 1
    
    wait_seconds = input_data.get("wait", 2)  # Wait before screenshot
    analyze = input_data.get("analyze", False)  # Run vision analysis
    question = input_data.get("question", "Describe what you see on this webpage. Note any key information, text, or UI elements visible.")
    save_path = input_data.get("save_path")  # Optional: save to specific path
    
    # Build headers
    headers = {"Content-Type": "application/json"}
    
    if crawl4ai_user and crawl4ai_pass:
        auth_string = b64encode(f"{crawl4ai_user}:{crawl4ai_pass}".encode()).decode()
        headers["Authorization"] = f"Basic {auth_string}"
    
    if crawl4ai_api_key:
        headers["x-api-key"] = crawl4ai_api_key
    
    # Build request body
    body = {
        "url": url,
        "screenshot_wait_for": wait_seconds
    }
    
    try:
        # Take screenshot via crawl4ai
        response = requests.post(
            f"{crawl4ai_url}/screenshot",
            headers=headers,
            json=body,
            timeout=60
        )
        
        if response.status_code == 401:
            return_error("Authentication failed")
            return 1
        
        response.raise_for_status()
        result = response.json()
        
        # Get screenshot data (base64 PNG)
        screenshot_b64 = result.get("screenshot")
        if not screenshot_b64:
            return_error("No screenshot returned")
            return 1
        
        # Save to file
        if save_path:
            file_path = Path(save_path).expanduser()
        else:
            # Save to temp directory
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            file_path = Path(tempfile.gettempdir()) / f"screenshot_{timestamp}.png"
        
        # Decode and convert to proper PNG/JPEG
        screenshot_bytes = b64decode(screenshot_b64)
        
        # Convert to proper format and resize if needed (for vision APIs)
        try:
            from PIL import Image
            import io
            
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
            if str(file_path).endswith('.png'):
                file_path = Path(str(file_path).replace('.png', '.jpg'))
            
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
                    speech=f"Screenshot saved to {file_path}. Vision analysis failed.",
                    data=response_data
                )
        else:
            return_success(
                speech=f"Screenshot saved to {file_path}",
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


def _analyze_screenshot(image_path: str, question: str) -> str:
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

