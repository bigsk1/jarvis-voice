"""
Jarvis Canvas - Image Gallery routes
"""
import json
import mimetypes
from datetime import datetime
from flask import Blueprint, jsonify, request, send_file, abort, render_template

from config import GENERATED_IMAGES_DIR, STASH_DIR

gallery_bp = Blueprint('gallery', __name__)

# Central catalog file for image metadata (provider, tags, etc.)
IMAGE_CATALOG_FILE = GENERATED_IMAGES_DIR / "image_catalog.json"


def load_image_catalog():
    """Load the image catalog from disk."""
    if IMAGE_CATALOG_FILE.exists():
        try:
            with open(IMAGE_CATALOG_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_image_catalog(catalog):
    """Save the image catalog to disk."""
    try:
        with open(IMAGE_CATALOG_FILE, 'w') as f:
            json.dump(catalog, f, indent=2)
    except Exception as e:
        print(f"⚠️  Failed to save image catalog: {e}")


def lookup_image_stash_metadata(filename):
    """
    Look up metadata for an image file from stash.
    Returns dict with provider, tags, aspect if found.
    """
    if not STASH_DIR.exists():
        return None
    
    for space_dir in STASH_DIR.iterdir():
        if not space_dir.is_dir():
            continue
        
        meta_file = space_dir / "meta.json"
        if not meta_file.exists():
            continue
        
        try:
            with open(meta_file) as f:
                meta = json.load(f)
            
            # Only process image stash spaces
            if 'generated_images' not in meta.get('labels', []):
                continue
            
            for file_info in meta.get('files', []):
                stored_name = file_info.get('stored_name') or file_info.get('name')
                if stored_name != filename:
                    continue
                
                tags = file_info.get('tags', [])
                
                # Detect provider from tags
                provider = None
                if 'xai' in tags:
                    provider = 'xAI'
                elif 'gemini' in tags:
                    provider = 'Gemini'
                elif 'openai' in tags:
                    provider = 'OpenAI'
                elif 'dall-e' in tags or 'dalle' in tags:
                    provider = 'DALL-E'
                elif 'stability' in tags or 'stable-diffusion' in tags:
                    provider = 'Stability'
                
                # Get aspect ratio from tags
                aspect = None
                for tag in tags:
                    if ':' in tag and tag.replace(':', '').replace('.', '').isdigit():
                        aspect = tag
                        break
                
                return {
                    'provider': provider,
                    'aspect': aspect,
                    'tags': tags,
                    'tool_origin': file_info.get('tool_origin'),
                    'created_at': file_info.get('created_at')
                }
        except Exception:
            pass
    
    return None


def sync_image_catalog():
    """
    Sync the image catalog with actual files and stash metadata.
    
    - Adds new images found in directory (with stash metadata if available)
    - Removes entries for deleted images
    - Returns the synced catalog
    """
    catalog = load_image_catalog()
    changed = False
    
    # Get actual image files
    actual_files = set()
    if GENERATED_IMAGES_DIR.exists():
        for f in GENERATED_IMAGES_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
                actual_files.add(f.name)
    
    # Remove entries for deleted images
    deleted = [name for name in catalog if name not in actual_files]
    for name in deleted:
        del catalog[name]
        changed = True
    
    # Add new images (lookup stash metadata)
    for filename in actual_files:
        if filename not in catalog:
            meta = lookup_image_stash_metadata(filename)
            catalog[filename] = meta or {}
            changed = True
            if meta and meta.get('provider'):
                print(f"📝 Image catalog: {filename} ({meta.get('provider')})")
    
    if changed:
        save_image_catalog(catalog)
    
    return catalog


@gallery_bp.route('/gallery')
def gallery():
    """Serve the image gallery UI."""
    return render_template('gallery.html')


@gallery_bp.route('/api/gallery/images')
def list_gallery_images():
    """List all images in the generated_images directory."""
    images = []
    total_size = 0
    
    # Sync catalog with actual files (handles additions and deletions)
    catalog = sync_image_catalog()
    
    if GENERATED_IMAGES_DIR.exists():
        for f in GENERATED_IMAGES_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
                stat = f.stat()
                image_info = {
                    'name': f.name,
                    'size': stat.st_size,
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                }
                
                # Get metadata from catalog
                meta = catalog.get(f.name, {})
                if meta.get('provider'):
                    image_info['provider'] = meta['provider']
                if meta.get('aspect'):
                    image_info['aspect'] = meta['aspect']
                if meta.get('tags'):
                    image_info['tags'] = meta['tags']
                
                images.append(image_info)
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
        # Remove from CDN catalog if present
        cdn_catalog = GENERATED_IMAGES_DIR / "cdn_catalog.json"
        if cdn_catalog.exists():
            try:
                catalog = json.loads(cdn_catalog.read_text())
                if filename in catalog:
                    del catalog[filename]
                    cdn_catalog.write_text(json.dumps(catalog, indent=2))
            except:
                pass
        # Remove from image catalog
        img_catalog = load_image_catalog()
        if filename in img_catalog:
            del img_catalog[filename]
            save_image_catalog(img_catalog)
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
