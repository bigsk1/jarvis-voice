"""
Jarvis Canvas - Image Gallery routes
"""
import json
from datetime import datetime
from urllib.parse import quote, urlsplit

from flask import Blueprint, jsonify, request, send_file, abort, render_template, make_response

from config import GENERATED_IMAGES_DIR
from config_loader import get_config_value
try:
    from stash_helper import get_stash_dir
except ImportError:
    from lib.stash_helper import get_stash_dir
from internal_api import get_internal_api_base_url, get_internal_api_headers

gallery_bp = Blueprint('gallery', __name__)

# Central catalog file for image metadata (provider, tags, etc.)
IMAGE_CATALOG_FILE = GENERATED_IMAGES_DIR / "image_catalog.json"
CDN_CATALOG_FILE = GENERATED_IMAGES_DIR / "cdn_catalog.json"
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.webp')


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


def load_cdn_catalog():
    """Load cached Cloudflare URLs for generated images."""
    if CDN_CATALOG_FILE.exists():
        try:
            with open(CDN_CATALOG_FILE) as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


def cloudflare_configured():
    """Return whether the active Canvas mode has Cloudflare Images credentials."""
    token = str(get_config_value('CLOUDFLARE_API_TOKEN', '') or '').strip()
    account_id = str(get_config_value('CLOUDFLARE_ACCOUNT_ID', '') or '').strip()
    return bool(token and account_id)


def load_cdn_export_entries():
    """Return safe, current CDN catalog entries sorted newest first."""
    entries = []
    for filename, data in load_cdn_catalog().items():
        if not isinstance(data, dict):
            continue
        url = str(data.get('url') or '').strip()
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.netloc:
            continue
        entries.append({
            'filename': str(filename),
            'url': url,
            'uploaded_at': str(data.get('uploaded_at') or ''),
        })
    entries.sort(key=lambda entry: (entry['uploaded_at'], entry['filename']), reverse=True)
    return entries


def is_safe_image_filename(filename):
    """Return true when a gallery filename cannot escape generated_images."""
    return (
        filename
        and '..' not in filename
        and '/' not in filename
        and '\\' not in filename
        and (GENERATED_IMAGES_DIR / filename).suffix.lower() in IMAGE_EXTENSIONS
    )


def update_image_favorite(filename, favorite):
    """Persist favorite state in the image metadata catalog."""
    if not is_safe_image_filename(filename):
        return None
    filepath = GENERATED_IMAGES_DIR / filename
    if not filepath.exists():
        return None

    catalog = sync_image_catalog()
    meta = dict(catalog.get(filename) or {})
    meta['favorite'] = bool(favorite)
    meta['favorited_at'] = datetime.now().isoformat() if favorite else None
    catalog[filename] = meta
    save_image_catalog(catalog)
    return meta


def lookup_image_stash_metadata(filename):
    """
    Look up metadata for an image file from stash.
    Returns dict with provider, tags, aspect if found.
    """
    stash_dir = get_stash_dir()
    if not stash_dir.exists():
        return None
    
    for space_dir in stash_dir.iterdir():
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
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
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


@gallery_bp.route('/api/gallery/cdn-catalog/export')
def export_cdn_catalog_html():
    """Render the current CDN catalog as standalone, bookmarkable HTML."""
    response = make_response(render_template(
        'cdn-catalog-export.html',
        entries=load_cdn_export_entries(),
        cloudflare_configured=cloudflare_configured(),
        generated_at=datetime.now().isoformat(timespec='seconds'),
    ))
    response.headers['Content-Disposition'] = 'inline; filename="jarvis-cdn-catalog.html"'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = (
        "default-src 'none'; img-src https: data:; style-src 'unsafe-inline'; "
        "script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'"
    )
    return response


@gallery_bp.route('/api/cdn-catalog/delete', methods=['DELETE'])
def delete_cdn_catalog_image():
    """Proxy an authenticated CDN deletion through the internal Jarvis API."""
    data = request.get_json(silent=True) or {}
    filename = str(data.get('filename') or '')
    if not is_safe_image_filename(filename):
        return jsonify({'ok': False, 'error': 'Invalid filename'}), 400

    import requests

    encoded_filename = quote(filename, safe='')
    api_url = (
        f"{get_internal_api_base_url()}/api/generated-images/"
        f"cdn-catalog/{encoded_filename}"
    )
    try:
        response = requests.delete(
            api_url,
            headers=get_internal_api_headers(),
            timeout=40,
        )
        try:
            data = response.json()
        except ValueError:
            data = {'ok': False, 'error': 'Jarvis API returned an invalid response'}
        return jsonify(data), response.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({'ok': False, 'error': f'API error: {str(e)}'}), 502


@gallery_bp.route('/api/cdn-catalog/remove-entry', methods=['DELETE'])
def remove_cdn_catalog_entry():
    """Proxy confirmed removal of a stale local CDN catalog entry."""
    data = request.get_json(silent=True) or {}
    filename = str(data.get('filename') or '')
    expected_image_id = str(data.get('image_id') or '').strip()
    if not is_safe_image_filename(filename) or not expected_image_id:
        return jsonify({'ok': False, 'error': 'Invalid catalog entry'}), 400

    import requests

    encoded_filename = quote(filename, safe='')
    api_url = (
        f"{get_internal_api_base_url()}/api/generated-images/"
        f"cdn-catalog/{encoded_filename}/entry"
    )
    try:
        response = requests.delete(
            api_url,
            headers=get_internal_api_headers(),
            json={'expected_image_id': expected_image_id},
            timeout=15,
        )
        try:
            response_data = response.json()
        except ValueError:
            response_data = {'ok': False, 'error': 'Jarvis API returned an invalid response'}
        return jsonify(response_data), response.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({'ok': False, 'error': f'API error: {str(e)}'}), 502


@gallery_bp.route('/api/gallery/images')
def list_gallery_images():
    """List all images in the generated_images directory."""
    images = []
    total_size = 0
    
    # Sync catalog with actual files (handles additions and deletions)
    catalog = sync_image_catalog()
    cdn_catalog = load_cdn_catalog()
    
    if GENERATED_IMAGES_DIR.exists():
        for f in GENERATED_IMAGES_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
                stat = f.stat()
                image_info = {
                    'name': f.name,
                    'size': stat.st_size,
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    'favorite': bool(catalog.get(f.name, {}).get('favorite', False)),
                    'cdn_cached': bool((cdn_catalog.get(f.name) or {}).get('url')),
                }
                
                # Get metadata from catalog
                meta = catalog.get(f.name, {})
                if meta.get('provider'):
                    image_info['provider'] = meta['provider']
                if meta.get('aspect'):
                    image_info['aspect'] = meta['aspect']
                if meta.get('tags'):
                    image_info['tags'] = meta['tags']
                if meta.get('favorited_at'):
                    image_info['favorited_at'] = meta['favorited_at']
                
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
    """Serve an image from the gallery (inline)."""
    # Security: prevent path traversal
    if not is_safe_image_filename(filename):
        abort(400, "Invalid filename")
    
    filepath = GENERATED_IMAGES_DIR / filename
    if not filepath.exists():
        abort(404, "Image not found")
    
    return send_file(filepath)


@gallery_bp.route('/api/gallery/images/<filename>/download')
def download_gallery_image(filename):
    """
    Download an image with Content-Disposition: attachment header.
    This triggers Safari's native download prompt on iOS.
    """
    # Security: prevent path traversal
    if not is_safe_image_filename(filename):
        abort(400, "Invalid filename")
    
    filepath = GENERATED_IMAGES_DIR / filename
    if not filepath.exists():
        abort(404, "Image not found")
    
    return send_file(filepath, as_attachment=True, download_name=filename)


@gallery_bp.route('/api/gallery/images/<filename>/favorite', methods=['PATCH'])
def set_gallery_image_favorite(filename):
    """Set or clear the favorite flag for a generated image."""
    if not is_safe_image_filename(filename):
        return jsonify({'ok': False, 'error': 'Invalid filename'}), 400

    data = request.get_json(silent=True) or {}
    favorite = bool(data.get('favorite', True))
    meta = update_image_favorite(filename, favorite)
    if meta is None:
        return jsonify({'ok': False, 'error': 'Image not found'}), 404

    return jsonify({
        'ok': True,
        'name': filename,
        'favorite': bool(meta.get('favorite', False)),
        'favorited_at': meta.get('favorited_at'),
    })


@gallery_bp.route('/api/gallery/images/<filename>', methods=['DELETE'])
def delete_gallery_image(filename):
    """Delete an image from the gallery."""
    # Security: prevent path traversal
    if not is_safe_image_filename(filename):
        return jsonify({'error': 'Invalid filename'}), 400
    
    filepath = GENERATED_IMAGES_DIR / filename
    if not filepath.exists():
        return jsonify({'error': 'Image not found'}), 404
    
    try:
        filepath.unlink()
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
    if not is_safe_image_filename(filename):
        return jsonify({'ok': False, 'error': 'Invalid filename'}), 400
    
    filepath = GENERATED_IMAGES_DIR / filename
    if not filepath.exists():
        return jsonify({'ok': False, 'error': 'Image not found'}), 404
    
    # Check local CDN catalog first
    if CDN_CATALOG_FILE.exists():
        try:
            catalog = json.loads(CDN_CATALOG_FILE.read_text())
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
        api_url = f"{get_internal_api_base_url()}/api/generated-images/{filename}/cdn-url"
        response = requests.get(api_url, headers=get_internal_api_headers(), timeout=60)
        data = response.json()
        return jsonify(data)
    except requests.exceptions.RequestException as e:
        return jsonify({'ok': False, 'error': f'API error: {str(e)}'}), 500
