#!/usr/bin/env python3
"""
Tool Name: Convert File
Description: Convert media files between formats using local tools (ImageMagick, FFmpeg, Potrace)
Input: { "source": "stash://... or file path", "target_format": "png/jpg/svg/mp4/...", "options": {} }
Output: { "ok": bool, "speech": str, "data": { "stash_ref": "...", "output_path": "..." } }

Supported conversions:
- Image formats: jpg, png, webp, gif, tiff, bmp (via ImageMagick)
- Raster to vector: jpg/png → svg (via Potrace - best for high-contrast images)
- Video formats: mp4, webm, mov, avi, mkv (via FFmpeg)
- Audio formats: mp3, wav, flac, ogg, aac, m4a (via FFmpeg)
- Video/Audio extraction: video → audio (via FFmpeg)
"""

import sys
import os
import json
import subprocess
import shutil
import tempfile
from pathlib import Path

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config
from stash_helper import open_space, StashFile, parse_stash_ref, get_space

# Format categories
IMAGE_FORMATS = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'tiff', 'tif', 'bmp', 'ico'}
VECTOR_FORMATS = {'svg', 'pdf', 'eps'}
VIDEO_FORMATS = {'mp4', 'webm', 'mov', 'avi', 'mkv', 'flv', 'wmv', 'm4v'}
AUDIO_FORMATS = {'mp3', 'wav', 'flac', 'ogg', 'aac', 'm4a', 'wma', 'opus'}

# Tool availability cache
_tool_cache = {}


def check_tool(tool_name: str) -> bool:
    """Check if a command-line tool is available."""
    if tool_name not in _tool_cache:
        _tool_cache[tool_name] = shutil.which(tool_name) is not None
    return _tool_cache[tool_name]


def get_format(filename: str) -> str:
    """Extract format from filename."""
    ext = Path(filename).suffix.lower().lstrip('.')
    # Normalize jpeg to jpg
    if ext == 'jpeg':
        return 'jpg'
    return ext


def resolve_source(source: str) -> tuple[str, dict]:
    """
    Resolve source to a local file path.
    
    Returns:
        (file_path, metadata) - metadata includes original info if from stash
    """
    # Handle stash:// references
    if source.startswith('stash://'):
        try:
            # Parse the stash reference
            space_id, file_id = parse_stash_ref(source)
            space = get_space(space_id)
            
            # Find the file in the space
            stash_file = StashFile(space, file_id=file_id)
            if not stash_file.exists:
                # Try by name
                stash_file = StashFile(space, name=file_id)
            
            if not stash_file.exists or not stash_file.path:
                raise ValueError(f"File not found in stash: {source}")
            
            file_path = str(stash_file.path)
            original_name = stash_file.meta.get('name', file_id) if stash_file.meta else file_id
            
            return file_path, {'source_type': 'stash', 'stash_ref': source, 'original_name': original_name}
        except Exception as e:
            raise ValueError(f"Could not resolve stash reference: {source} - {e}")
    
    # Handle local file paths
    path = Path(source).expanduser()
    if path.exists():
        return str(path), {'source_type': 'file', 'original_name': path.name}
    
    raise ValueError(f"Source not found: {source}")


def convert_image_to_image(input_path: str, output_path: str, options: dict = None) -> dict:
    """Convert between image formats using ImageMagick."""
    if not check_tool('convert'):
        raise RuntimeError("ImageMagick not installed. Run: sudo apt install imagemagick")
    
    options = options or {}
    cmd = ['convert', input_path]
    
    # Quality setting (for lossy formats)
    if 'quality' in options:
        cmd.extend(['-quality', str(options['quality'])])
    
    # Resize if specified
    if 'resize' in options:
        cmd.extend(['-resize', options['resize']])
    
    # Strip metadata if requested
    if options.get('strip_metadata', False):
        cmd.append('-strip')
    
    cmd.append(output_path)
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"ImageMagick failed: {result.stderr}")
    
    return {'tool': 'imagemagick', 'command': ' '.join(cmd)}


def convert_raster_to_svg(input_path: str, output_path: str, options: dict = None) -> dict:
    """Convert raster image to SVG using Potrace."""
    if not check_tool('potrace'):
        raise RuntimeError("Potrace not installed. Run: sudo apt install potrace")
    if not check_tool('convert'):
        raise RuntimeError("ImageMagick not installed (needed for pre-processing). Run: sudo apt install imagemagick")
    
    options = options or {}
    
    # Potrace needs PBM/PGM/PPM input, so we convert first
    with tempfile.NamedTemporaryFile(suffix='.pgm', delete=False) as tmp:
        tmp_pgm = tmp.name
    
    try:
        # Convert to grayscale PGM (potrace input)
        # Apply threshold to make it more "traceable"
        threshold = options.get('threshold', '50%')
        convert_cmd = [
            'convert', input_path,
            '-colorspace', 'Gray',
            '-threshold', threshold,
            tmp_pgm
        ]
        result = subprocess.run(convert_cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(f"Pre-processing failed: {result.stderr}")
        
        # Run potrace
        potrace_cmd = ['potrace', tmp_pgm, '-s', '-o', output_path]
        
        # Potrace options
        if 'turdsize' in options:  # Suppress speckles of this size
            potrace_cmd.extend(['-t', str(options['turdsize'])])
        if 'alphamax' in options:  # Corner threshold
            potrace_cmd.extend(['-a', str(options['alphamax'])])
        if 'opttolerance' in options:  # Curve optimization tolerance
            potrace_cmd.extend(['-O', str(options['opttolerance'])])
        
        result = subprocess.run(potrace_cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"Potrace failed: {result.stderr}")
        
        return {'tool': 'potrace', 'note': 'Best results with high-contrast images'}
    finally:
        if os.path.exists(tmp_pgm):
            os.unlink(tmp_pgm)


def convert_video(input_path: str, output_path: str, options: dict = None) -> dict:
    """Convert video formats using FFmpeg."""
    if not check_tool('ffmpeg'):
        raise RuntimeError("FFmpeg not installed. Run: sudo apt install ffmpeg")
    
    options = options or {}
    cmd = ['ffmpeg', '-y', '-i', input_path]
    
    # Video codec
    output_format = get_format(output_path)
    if output_format == 'webm':
        cmd.extend(['-c:v', 'libvpx-vp9', '-c:a', 'libopus'])
    elif output_format == 'mp4':
        cmd.extend(['-c:v', 'libx264', '-c:a', 'aac'])
    
    # Quality/CRF
    if 'crf' in options:
        cmd.extend(['-crf', str(options['crf'])])
    
    # Resolution
    if 'resolution' in options:
        cmd.extend(['-s', options['resolution']])
    
    # Framerate
    if 'fps' in options:
        cmd.extend(['-r', str(options['fps'])])
    
    # Duration limit
    if 'duration' in options:
        cmd.extend(['-t', str(options['duration'])])
    
    cmd.append(output_path)
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr}")
    
    return {'tool': 'ffmpeg', 'command': ' '.join(cmd)}


def convert_audio(input_path: str, output_path: str, options: dict = None) -> dict:
    """Convert audio formats using FFmpeg."""
    if not check_tool('ffmpeg'):
        raise RuntimeError("FFmpeg not installed. Run: sudo apt install ffmpeg")
    
    options = options or {}
    cmd = ['ffmpeg', '-y', '-i', input_path]
    
    # Audio codec based on output format
    output_format = get_format(output_path)
    if output_format == 'mp3':
        cmd.extend(['-c:a', 'libmp3lame'])
        if 'bitrate' in options:
            cmd.extend(['-b:a', options['bitrate']])
        else:
            cmd.extend(['-b:a', '192k'])
    elif output_format == 'flac':
        cmd.extend(['-c:a', 'flac'])
    elif output_format == 'ogg':
        cmd.extend(['-c:a', 'libvorbis'])
    elif output_format == 'opus':
        cmd.extend(['-c:a', 'libopus'])
    elif output_format == 'aac' or output_format == 'm4a':
        cmd.extend(['-c:a', 'aac'])
    
    # Sample rate
    if 'sample_rate' in options:
        cmd.extend(['-ar', str(options['sample_rate'])])
    
    # Channels (mono/stereo)
    if 'channels' in options:
        cmd.extend(['-ac', str(options['channels'])])
    
    cmd.append(output_path)
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr}")
    
    return {'tool': 'ffmpeg'}


def extract_audio_from_video(input_path: str, output_path: str, options: dict = None) -> dict:
    """Extract audio track from video using FFmpeg."""
    if not check_tool('ffmpeg'):
        raise RuntimeError("FFmpeg not installed. Run: sudo apt install ffmpeg")
    
    options = options or {}
    cmd = ['ffmpeg', '-y', '-i', input_path, '-vn']  # -vn = no video
    
    # Audio codec based on output format
    output_format = get_format(output_path)
    if output_format == 'mp3':
        cmd.extend(['-c:a', 'libmp3lame', '-b:a', options.get('bitrate', '192k')])
    elif output_format == 'flac':
        cmd.extend(['-c:a', 'flac'])
    elif output_format == 'wav':
        cmd.extend(['-c:a', 'pcm_s16le'])
    else:
        cmd.extend(['-c:a', 'aac'])
    
    cmd.append(output_path)
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr}")
    
    return {'tool': 'ffmpeg', 'operation': 'extract_audio'}


def get_media_info(input_path: str) -> dict:
    """Get media file information using FFprobe."""
    if not check_tool('ffprobe'):
        return {}
    
    cmd = [
        'ffprobe', '-v', 'quiet',
        '-print_format', 'json',
        '-show_format', '-show_streams',
        input_path
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except:
        pass
    return {}


def main():
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        # Load config
        load_config()
        
        # Extract parameters
        source = args.get('source')
        target_format = args.get('target_format', '').lower().lstrip('.')
        options = args.get('options', {})
        
        if not source:
            raise ValueError("source is required (stash://... or file path)")
        if not target_format:
            raise ValueError("target_format is required (e.g., 'png', 'mp4', 'mp3')")
        
        # Normalize format
        if target_format == 'jpeg':
            target_format = 'jpg'
        
        # Resolve source to local file
        input_path, source_meta = resolve_source(source)
        source_format = get_format(input_path)
        
        # Determine conversion type
        source_is_image = source_format in IMAGE_FORMATS
        source_is_video = source_format in VIDEO_FORMATS
        source_is_audio = source_format in AUDIO_FORMATS
        
        target_is_image = target_format in IMAGE_FORMATS
        target_is_vector = target_format in VECTOR_FORMATS
        target_is_video = target_format in VIDEO_FORMATS
        target_is_audio = target_format in AUDIO_FORMATS
        
        # Create output filename
        original_name = source_meta.get('original_name', 'converted')
        base_name = Path(original_name).stem
        output_filename = f"{base_name}.{target_format}"
        
        # Create temp output file
        with tempfile.NamedTemporaryFile(suffix=f'.{target_format}', delete=False) as tmp:
            output_path = tmp.name
        
        try:
            # Route to appropriate converter
            conversion_info = {}
            
            if source_is_image and target_is_image:
                # Image → Image (ImageMagick)
                conversion_info = convert_image_to_image(input_path, output_path, options)
                
            elif source_is_image and target_format == 'svg':
                # Raster → SVG (Potrace)
                conversion_info = convert_raster_to_svg(input_path, output_path, options)
                
            elif source_is_video and target_is_video:
                # Video → Video (FFmpeg)
                conversion_info = convert_video(input_path, output_path, options)
                
            elif source_is_audio and target_is_audio:
                # Audio → Audio (FFmpeg)
                conversion_info = convert_audio(input_path, output_path, options)
                
            elif source_is_video and target_is_audio:
                # Video → Audio extraction (FFmpeg)
                conversion_info = extract_audio_from_video(input_path, output_path, options)
                
            elif source_is_image and target_is_video:
                raise ValueError("Image to video conversion not yet supported. Use generate_video tool for image-to-video AI generation.")
                
            else:
                raise ValueError(f"Unsupported conversion: {source_format} → {target_format}")
            
            # Verify output was created
            if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                raise RuntimeError("Conversion produced empty output")
            
            # Save to stash
            space, is_new = open_space(
                labels=['converted_files', f'from_{source_format}', f'to_{target_format}'],
                scope='project'  # Longer retention
            )
            
            # Read converted file
            with open(output_path, 'rb') as f:
                converted_data = f.read()
            
            # Save to stash
            stash_file = StashFile(space)
            file_result = stash_file.save_binary(
                data=converted_data,
                name=output_filename,
                tool_origin='convert_file',
                on_conflict='version'
            )
            
            # Get file info
            output_size = os.path.getsize(output_path)
            input_size = os.path.getsize(input_path)
            
            # Build response
            result_data = {
                'stash_ref': file_result.get('ref'),
                'space_id': space.space_id,
                'file_id': file_result.get('file_id'),
                'filename': output_filename,
                'source_format': source_format,
                'target_format': target_format,
                'input_size_bytes': input_size,
                'output_size_bytes': output_size,
                'conversion_info': conversion_info
            }
            
            # Calculate size change
            if input_size > 0:
                ratio = output_size / input_size
                if ratio < 1:
                    result_data['size_change'] = f"{(1-ratio)*100:.1f}% smaller"
                else:
                    result_data['size_change'] = f"{(ratio-1)*100:.1f}% larger"
            
            print(json.dumps({
                "ok": True,
                "speech": f"Converted {source_format.upper()} to {target_format.upper()}. Saved to stash.",
                "data": result_data
            }))
            
        finally:
            # Cleanup temp file
            if os.path.exists(output_path):
                os.unlink(output_path)
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Conversion failed: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
