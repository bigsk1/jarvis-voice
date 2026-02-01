"""
Jarvis Canvas - Image Gallery routes
"""
import json
import mimetypes
from datetime import datetime
from flask import Blueprint, jsonify, request, send_file, abort, render_template

from config import GENERATED_IMAGES_DIR

gallery_bp = Blueprint('gallery', __name__)


@gallery_bp.route('/gallery')
def gallery():
    """Serve the image gallery UI."""
    return render_template('gallery.html')


@gallery_bp.route('/api/gallery/images')
def list_gallery_images():
    """List all images in the generated_images directory."""
    images = []
    total_size = 0
    
    if GENERATED_IMAGES_DIR.exists():
        for f in GENERATED_IMAGES_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
                stat = f.stat()
                images.append({
                    'name': f.name,
                    'size': stat.st_size,
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
                total_size += stat.st_size
    
    # Sort by modified date descending by default
    images.sort(key=lambda x: x['modified'], reverse=True)
    
    return jsonify({
        'images': images,
        'count': len(images),
        'total_size': total_size
    })


@gallery_bp.route('/api/gallery/images/<filename>')
def serve_gallery_image(filename):
    """Serve an image from the gallery."""
    # Security: prevent path traversal
    if '..' in filename or '/' in filename:
        abort(400, "Invalid filename")
    
    filepath = GENERATED_IMAGES_DIR / filename
    if not filepath.exists():
        abort(404, "Image not found")
    
    return send_file(filepath)


@gallery_bp.route('/api/gallery/images/<filename>', methods=['DELETE'])
def delete_gallery_image(filename):
    """Delete an image from the gallery."""
    # Security: prevent path traversal
    if '..' in filename or '/' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    
    filepath = GENERATED_IMAGES_DIR / filename
    if not filepath.exists():
        return jsonify({'error': 'Image not found'}), 404
    
    try:
        filepath.unlink()
        # Also remove from CDN catalog if present
        cdn_catalog = GENERATED_IMAGES_DIR / "cdn_catalog.json"
        if cdn_catalog.exists():
            try:
                catalog = json.loads(cdn_catalog.read_text())
                if filename in catalog:
                    del catalog[filename]
                    cdn_catalog.write_text(json.dumps(catalog, indent=2))
            except:
                pass
        print(f"🗑️  Deleted gallery image: {filename}")
        return jsonify({'ok': True, 'deleted': filename})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@gallery_bp.route('/api/gallery/images/<filename>/cdn-url')
def get_cdn_url(filename):
    """Get or create CDN URL for an image (uploads if needed)."""
    import requests
    
    # Security: prevent path traversal
    if '..' in filename or '/' in filename:
        return jsonify({'ok': False, 'error': 'Invalid filename'}), 400
    
    filepath = GENERATED_IMAGES_DIR / filename
    if not filepath.exists():
        return jsonify({'ok': False, 'error': 'Image not found'}), 404
    
    # Check local CDN catalog first
    cdn_catalog = GENERATED_IMAGES_DIR / "cdn_catalog.json"
    if cdn_catalog.exists():
        try:
            catalog = json.loads(cdn_catalog.read_text())
            if filename in catalog:
                entry = catalog[filename]
                return jsonify({
                    'ok': True,
                    'name': filename,
                    'url': entry.get('url'),
                    'cached': True,
                    'image_id': entry.get('image_id')
                })
        except:
            pass
    
    # Not in catalog - call Jarvis API to upload
    try:
        api_url = f"http://localhost:8880/api/generated-images/{filename}/cdn-url"
        response = requests.get(api_url, timeout=60)
        data = response.json()
        return jsonify(data)
    except requests.exceptions.RequestException as e:
        return jsonify({'ok': False, 'error': f'API error: {str(e)}'}), 500


@gallery_bp.route('/api/gallery/images/<filename>/to-video', methods=['POST'])
def convert_image_to_video(filename):
    """Convert an image to video using generate_video tool."""
    import requests as req
    
    # Security: prevent path traversal
    if '..' in filename or '/' in filename:
        return jsonify({'ok': False, 'error': 'Invalid filename'}), 400
    
    filepath = GENERATED_IMAGES_DIR / filename
    if not filepath.exists():
        return jsonify({'ok': False, 'error': 'Image not found'}), 404
    
    # Get request data
    data = request.get_json() or {}
    prompt = data.get('prompt', 'Animate this image with gentle movement')
    provider = data.get('provider', 'xai')
    duration = data.get('duration', 5)
    aspect_ratio = data.get('aspect_ratio', '16:9')
    resolution = data.get('resolution', '720p')
    
    try:
        # Check if already in CDN catalog
        cdn_url = None
        cdn_catalog = GENERATED_IMAGES_DIR / "cdn_catalog.json"
        if cdn_catalog.exists():
            try:
                catalog = json.loads(cdn_catalog.read_text())
                if filename in catalog:
                    cdn_url = catalog[filename].get('url')
            except:
                pass
        
        # If not in CDN, upload it first
        if not cdn_url:
            api_url = f"http://localhost:8880/api/generated-images/{filename}/cdn-url"
            response = req.get(api_url, timeout=60)
            result = response.json()
            if result.get('ok'):
                cdn_url = result.get('url')
        
        if not cdn_url:
            return jsonify({'ok': False, 'error': 'Could not get image URL for video generation'}), 400
        
        # Build args for generate_video tool
        tool_args = {
            "prompt": prompt,
            "image_url": cdn_url,
            "provider": provider,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "save": True
        }
        
        # Call generate_video tool via API (it has proper timeout handling)
        api_url = "http://localhost:8880/api/generated-videos/generate"
        response = req.post(
            api_url,
            json=tool_args,
            timeout=660  # 11 minutes (slightly more than the 10 min internal timeout)
        )
        
        result = response.json()
        
        if result.get('ok'):
            return jsonify({
                'ok': True,
                'speech': result.get('speech'),
                'video_path': result.get('data', {}).get('file_path'),
                'video_url': result.get('data', {}).get('video_url'),
                'duration': result.get('data', {}).get('duration'),
                'provider': provider
            })
        else:
            return jsonify({
                'ok': False,
                'error': result.get('error') or result.get('speech') or 'Video generation failed'
            })
            
    except req.exceptions.Timeout:
        return jsonify({'ok': False, 'error': 'Video generation timed out (10+ minutes)'}), 504
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
