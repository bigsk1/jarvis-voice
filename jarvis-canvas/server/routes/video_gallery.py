"""
Jarvis Canvas - Video Gallery routes
"""
import json
import subprocess
from datetime import datetime
from pathlib import Path
from flask import Blueprint, jsonify, request, send_file, abort, render_template

from config import GENERATED_VIDEOS_DIR, STASH_DIR

video_gallery_bp = Blueprint('video_gallery', __name__)

# Central catalog file for video metadata
VIDEO_CATALOG_FILE = GENERATED_VIDEOS_DIR / "video_catalog.json"


def get_video_duration(filepath):
    """Get video duration using ffprobe if available."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(filepath)],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except:
        pass
    return None


def load_video_catalog():
    """Load the video catalog from disk."""
    if VIDEO_CATALOG_FILE.exists():
        try:
            with open(VIDEO_CATALOG_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_video_catalog(catalog):
    """Save the video catalog to disk."""
    try:
        with open(VIDEO_CATALOG_FILE, 'w') as f:
            json.dump(catalog, f, indent=2)
    except Exception as e:
        print(f"⚠️  Failed to save video catalog: {e}")


def sync_video_catalog():
    """
    Sync the video catalog with actual files and stash metadata.
    
    - Adds new videos found in directory (with stash metadata if available)
    - Removes entries for deleted videos
    - Returns the synced catalog
    """
    catalog = load_video_catalog()
    changed = False
    
    # Get actual video files
    actual_files = set()
    if GENERATED_VIDEOS_DIR.exists():
        for f in GENERATED_VIDEOS_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in ('.mp4', '.webm', '.mov', '.avi', '.mkv'):
                actual_files.add(f.name)
    
    # Remove entries for deleted videos
    deleted = [name for name in catalog if name not in actual_files]
    for name in deleted:
        del catalog[name]
        changed = True
        print(f"🗑️  Removed from catalog: {name}")
    
    # Add new videos (lookup stash metadata)
    for filename in actual_files:
        if filename not in catalog:
            # New video - try to get metadata from stash
            meta = lookup_stash_metadata(filename)
            catalog[filename] = meta or {}
            changed = True
            if meta and meta.get('provider'):
                print(f"📝 Added to catalog: {filename} ({meta.get('provider')})")
            else:
                print(f"📝 Added to catalog: {filename}")
    
    if changed:
        save_video_catalog(catalog)
    
    return catalog


def lookup_stash_metadata(filename):
    """
    Look up metadata for a video file from stash.
    Returns dict with provider, aspect, tags if found.
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
            
            # Only process video stash spaces
            if 'generated_videos' not in meta.get('labels', []):
                continue
            
            for file_info in meta.get('files', []):
                stored_name = file_info.get('stored_name') or file_info.get('name')
                if stored_name != filename:
                    continue
                
                tags = file_info.get('tags', [])
                
                # Detect provider from tags
                provider = None
                if 'gemini' in tags:
                    provider = 'Gemini'
                elif 'xai' in tags:
                    provider = 'xAI'
                elif 'runway' in tags:
                    provider = 'Runway'
                elif 'pika' in tags:
                    provider = 'Pika'
                elif 'kling' in tags:
                    provider = 'Kling'
                
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


@video_gallery_bp.route('/video-gallery')
def video_gallery():
    """Serve the video gallery UI."""
    return render_template('video-gallery.html')


@video_gallery_bp.route('/api/gallery/videos')
def list_gallery_videos():
    """List all videos in the generated_videos directory."""
    videos = []
    total_size = 0
    
    # Sync catalog with actual files (handles additions and deletions)
    catalog = sync_video_catalog()
    
    if GENERATED_VIDEOS_DIR.exists():
        for f in GENERATED_VIDEOS_DIR.iterdir():
            # Skip non-video files
            if not f.is_file() or f.suffix.lower() not in ('.mp4', '.webm', '.mov', '.avi', '.mkv'):
                continue
                
            stat = f.stat()
            video_info = {
                'name': f.name,
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
            }
            
            # Try to get duration
            duration = get_video_duration(f)
            if duration:
                video_info['duration'] = duration
            
            # Get metadata from catalog
            meta = catalog.get(f.name, {})
            if meta.get('provider'):
                video_info['provider'] = meta['provider']
            if meta.get('aspect'):
                video_info['aspect'] = meta['aspect']
            if meta.get('tags'):
                video_info['tags'] = meta['tags']
            
            videos.append(video_info)
            total_size += stat.st_size
    
    # Sort by modified date descending by default
    videos.sort(key=lambda x: x['modified'], reverse=True)
    
    return jsonify({
        'videos': videos,
        'count': len(videos),
        'total_size': total_size
    })


@video_gallery_bp.route('/api/gallery/videos/<filename>')
def serve_gallery_video(filename):
    """Serve a video from the gallery."""
    # Security: prevent path traversal
    if '..' in filename or '/' in filename:
        abort(400, "Invalid filename")
    
    filepath = GENERATED_VIDEOS_DIR / filename
    if not filepath.exists():
        abort(404, "Video not found")
    
    return send_file(filepath)


@video_gallery_bp.route('/api/gallery/videos/<filename>', methods=['DELETE'])
def delete_gallery_video(filename):
    """Delete a video from the gallery."""
    # Security: prevent path traversal
    if '..' in filename or '/' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    
    filepath = GENERATED_VIDEOS_DIR / filename
    if not filepath.exists():
        return jsonify({'error': 'Video not found'}), 404
    
    try:
        # Delete the video file
        filepath.unlink()
        print(f"🗑️  Deleted gallery video: {filename}")
        
        # Remove from catalog
        catalog = load_video_catalog()
        if filename in catalog:
            del catalog[filename]
            save_video_catalog(catalog)
        
        return jsonify({'ok': True, 'deleted': filename})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
