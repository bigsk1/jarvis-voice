"""Jarvis Canvas video-gallery routes."""
import subprocess
from datetime import datetime
from pathlib import Path
from flask import Blueprint, jsonify, send_file, abort, render_template

from config import GENERATED_VIDEOS_DIR
try:
    from stash_helper import get_stash_dir
except ImportError:
    from lib.stash_helper import get_stash_dir
from video_catalog import (
    load_video_catalog as _load_video_catalog,
    lookup_stash_metadata as _lookup_stash_metadata,
    save_video_catalog as _save_video_catalog,
    sync_video_catalog as _sync_video_catalog,
)

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
    return _load_video_catalog(VIDEO_CATALOG_FILE)


def save_video_catalog(catalog):
    """Save the video catalog to disk."""
    _save_video_catalog(VIDEO_CATALOG_FILE, catalog)


def sync_video_catalog():
    """
    Sync the video catalog with actual files and stash metadata.
    
    - Adds new videos found in directory (with stash metadata if available)
    - Removes entries for deleted videos
    - Returns the synced catalog
    """
    return _sync_video_catalog(
        GENERATED_VIDEOS_DIR,
        get_stash_dir(),
        VIDEO_CATALOG_FILE,
    )


def lookup_stash_metadata(filename):
    """
    Look up metadata for a video file from stash.
    Returns dict with provider, aspect, tags if found.
    """
    return _lookup_stash_metadata(filename, get_stash_dir())


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
            if meta.get('model'):
                video_info['model'] = meta['model']
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
    """Serve a video from the gallery (inline/streaming)."""
    # Security: prevent path traversal
    if '..' in filename or '/' in filename:
        abort(400, "Invalid filename")
    
    filepath = GENERATED_VIDEOS_DIR / filename
    if not filepath.exists():
        abort(404, "Video not found")
    
    return send_file(filepath)


@video_gallery_bp.route('/api/gallery/videos/<filename>/download')
def download_gallery_video(filename):
    """
    Download a video with Content-Disposition: attachment header.
    This triggers Safari's native download prompt on iOS.
    """
    # Security: prevent path traversal
    if '..' in filename or '/' in filename:
        abort(400, "Invalid filename")
    
    filepath = GENERATED_VIDEOS_DIR / filename
    if not filepath.exists():
        abort(404, "Video not found")
    
    return send_file(filepath, as_attachment=True, download_name=filename)


# Thumbnail cache directory
THUMBNAIL_CACHE_DIR = GENERATED_VIDEOS_DIR / ".thumbnails"


@video_gallery_bp.route('/api/gallery/videos/<filename>/thumbnail')
def serve_video_thumbnail(filename):
    """
    Serve a thumbnail image for a video (first frame).
    Thumbnails are cached to avoid regenerating on every request.
    """
    # Security: prevent path traversal
    if '..' in filename or '/' in filename:
        abort(400, "Invalid filename")
    
    video_path = GENERATED_VIDEOS_DIR / filename
    if not video_path.exists():
        abort(404, "Video not found")
    
    # Create thumbnail cache directory if needed
    THUMBNAIL_CACHE_DIR.mkdir(exist_ok=True)
    
    # Thumbnail filename: video name + .jpg
    thumb_name = Path(filename).stem + ".jpg"
    thumb_path = THUMBNAIL_CACHE_DIR / thumb_name
    
    # Check if thumbnail exists and is newer than video
    if thumb_path.exists():
        if thumb_path.stat().st_mtime >= video_path.stat().st_mtime:
            return send_file(thumb_path, mimetype='image/jpeg')
    
    # Generate thumbnail using ffmpeg (extract first frame)
    try:
        result = subprocess.run(
            [
                'ffmpeg', '-y',           # Overwrite output
                '-i', str(video_path),    # Input video
                '-vframes', '1',          # Extract 1 frame
                '-vf', 'scale=480:-1',    # Scale to 480px width, maintain aspect
                '-q:v', '3',              # JPEG quality (2-5 is good)
                str(thumb_path)           # Output thumbnail
            ],
            capture_output=True,
            timeout=10
        )
        
        if result.returncode == 0 and thumb_path.exists():
            return send_file(thumb_path, mimetype='image/jpeg')
        else:
            # ffmpeg failed - return a placeholder or 404
            print(f"⚠️  Failed to generate thumbnail for {filename}: {result.stderr.decode()[:200]}")
            abort(500, "Failed to generate thumbnail")
            
    except subprocess.TimeoutExpired:
        abort(500, "Thumbnail generation timed out")
    except Exception as e:
        print(f"⚠️  Thumbnail error for {filename}: {e}")
        abort(500, str(e))


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
        
        # Delete cached thumbnail if exists
        thumb_name = Path(filename).stem + ".jpg"
        thumb_path = THUMBNAIL_CACHE_DIR / thumb_name
        if thumb_path.exists():
            thumb_path.unlink()
            print(f"🗑️  Deleted thumbnail: {thumb_name}")
        
        # Remove from catalog
        catalog = load_video_catalog()
        if filename in catalog:
            del catalog[filename]
            save_video_catalog(catalog)
        
        return jsonify({'ok': True, 'deleted': filename})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
