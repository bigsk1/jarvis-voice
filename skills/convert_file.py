#!/usr/bin/env python3
"""
Tool Name: Convert File
Description: Convert media files between formats using local tools (ImageMagick, FFmpeg, Potrace)
Input: { "source": "stash://... or file path", "target_format": "png/jpg/svg/mp4/...", "options": {} }
Output: { "ok": bool, "speech": str, "data": { "stash_ref": "...", "output_path": "..." } }

Supported conversions:
- Image formats: jpg, png, webp, gif, tiff, bmp (via ImageMagick)
- Solid edge-connected background removal to transparent PNG/WebP
- Raster to vector: jpg/png → svg (via Potrace - best for high-contrast images)
- Video formats: mp4, webm, mov, avi, mkv (via FFmpeg)
- Audio formats: mp3, wav, flac, ogg, aac, m4a (via FFmpeg)
- Video/Audio extraction: video → audio (via FFmpeg)
"""

import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config
from paths import assert_not_restricted_read_path
from stash_helper import StashFile, get_space, open_space, parse_stash_ref
from tool_child_environment import RESTRICTED_ENV_MARKER

# Format categories
IMAGE_FORMATS = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'tiff', 'tif', 'bmp', 'ico'}
VIDEO_FORMATS = {'mp4', 'webm', 'mov', 'avi', 'mkv', 'flv', 'wmv', 'm4v'}
AUDIO_FORMATS = {'mp3', 'wav', 'flac', 'ogg', 'aac', 'm4a', 'wma', 'opus'}

# Tool availability cache
_tool_cache = {}
MAX_BACKGROUND_PIXELS = 32_000_000


def background_removal_options(options: object, target_format: str) -> dict | None:
    """Validate removal settings before launching a converter or creating Stash."""
    if not isinstance(options, dict):
        raise ValueError('options must be an object')
    enabled = options.get('remove_background', False)
    if not isinstance(enabled, bool):
        raise ValueError('remove_background must be true or false')
    if not enabled:
        if any(key in options for key in ('background_color', 'background_tolerance')):
            raise ValueError('background_color/tolerance require remove_background=true')
        return None
    if target_format not in {'png', 'webp'}:
        raise ValueError('Background removal requires target_format png or webp; JPEG cannot store transparency')
    color = options.get('background_color', 'auto')
    if not isinstance(color, str) or (color.lower() != 'auto' and not re.fullmatch(r'#[0-9a-fA-F]{6}', color)):
        raise ValueError('background_color must be auto or a #RRGGBB color')
    tolerance = options.get('background_tolerance', 5)
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or not 0 <= tolerance <= 25:
        raise ValueError('background_tolerance must be a finite percentage from 0 to 25')
    return {'color': color.lower(), 'tolerance': float(tolerance)}


def solid_background_color(input_path: str, settings: dict, resize=None) -> str:
    """Bound the decoded image and infer a consistent color from corner patches."""
    from PIL import Image

    with Image.open(input_path) as img:
        if img.width * img.height > MAX_BACKGROUND_PIXELS:
            raise ValueError('Background removal is limited to 32 megapixels; resize the source first')
        if getattr(img, 'n_frames', 1) != 1:
            raise ValueError('Background removal supports single-frame images only')
        if resize:
            # Keep the removal path bounded before ImageMagick allocates an
            # enlarged image. Ordinary conversions retain their existing syntax.
            geometry = re.fullmatch(r'(\d+)x(\d+)([!<>^]?)|(\d+(?:\.\d+)?)%', str(resize))
            if not geometry:
                raise ValueError('Background removal resize must be WIDTHxHEIGHT or PERCENT%')
            if geometry.group(4):
                scale = float(geometry.group(4)) / 100
                width, height = img.width * scale, img.height * scale
            else:
                requested_width, requested_height = int(geometry.group(1)), int(geometry.group(2))
                if geometry.group(3) == '!':
                    width, height = requested_width, requested_height
                else:
                    factor = (max if geometry.group(3) == '^' else min)(requested_width / img.width, requested_height / img.height)
                    if geometry.group(3) == '>':
                        factor = min(1, factor)
                    if geometry.group(3) == '<':
                        factor = max(1, factor)
                    width, height = img.width * factor, img.height * factor
            if not math.isfinite(width * height) or min(width, height) < 1 or width * height > MAX_BACKGROUND_PIXELS:
                raise ValueError('Background removal resized output must be within 1–32 million pixels')
        if settings['color'] != 'auto':
            return settings['color']
        size = min(5, img.width, img.height)
        colors = []
        for x, y in ((0, 0), (img.width - size, 0), (0, img.height - size), (img.width - size, img.height - size)):
            patch = img.crop((x, y, x + size, y + size)).convert('RGBA')
            pixels = [patch.getpixel((col, row)) for row in range(size) for col in range(size)]
            pixels = [pixel for pixel in pixels if pixel[3] == 255]
            if pixels:
                colors.append(tuple(round(statistics.median(p[c] for p in pixels)) for c in range(3)))
        if not colors:
            raise ValueError('Corners are already transparent; use ordinary conversion to retain transparency or specify background_color')
        color = tuple(round(statistics.median(p[c] for p in colors)) for c in range(3))
        agreement = max(3, settings['tolerance'] * 2.55)
        if any(max(abs(pixel[c] - color[c]) for c in range(3)) > agreement for pixel in colors):
            raise ValueError('Corner colors differ: automatic removal needs a solid background. Specify background_color for an edge-connected color, or use a subject-mask editor')
        return '#{:02x}{:02x}{:02x}'.format(*color)


def transparency_info(output_path: str) -> dict:
    """Check the actual delivered alpha, rather than assuming PNG means cutout."""
    from PIL import Image

    with Image.open(output_path) as img:
        if img.width * img.height > MAX_BACKGROUND_PIXELS:
            raise ValueError('Background removal output exceeds 32 megapixels; choose a smaller resize')
        if 'A' not in img.getbands() and 'transparency' not in img.info:
            raise RuntimeError('Background removal produced no alpha channel')
        alpha = img.convert('RGBA').getchannel('A')
        histogram = alpha.histogram()
        if not histogram[0]:
            raise RuntimeError('No matching edge-connected background was removed; check background_color/tolerance')
        if not sum(histogram[1:]):
            raise RuntimeError('Background removal erased the entire image; lower background_tolerance or choose another color')
        return {'width': img.width, 'height': img.height, 'has_alpha': True,
                'transparent_pixels': histogram[0], 'visible_pixels': sum(histogram[1:])}


def conversion_timeout(foreground_seconds: float) -> float:
    """Only the trusted background executor supplies this absolute deadline."""
    deadline = os.environ.get('JARVIS_BACKGROUND_DEADLINE')
    if not deadline:
        return foreground_seconds
    remaining = float(deadline) - time.time()
    if not math.isfinite(remaining) or remaining <= 0:
        raise TimeoutError('Background conversion deadline expired before subprocess launch')
    return remaining


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
            
            file_path = str(assert_not_restricted_read_path(
                stash_file.path,
                label="Stash source file",
            ))
            original_name = stash_file.meta.get('name', file_id) if stash_file.meta else file_id
            
            return file_path, {'source_type': 'stash', 'stash_ref': source, 'original_name': original_name}
        except Exception as e:
            raise ValueError(f"Could not resolve stash reference: {source} - {e}")
    
    # Handle local file paths
    # Restricted children have a scratch HOME. Resolve explicit ~/ inputs
    # against the operator account, without restoring HOME for subprocesses.
    if os.environ.get(RESTRICTED_ENV_MARKER) == '1' and (source == '~' or source.startswith('~/')):
        if os.name == 'posix':
            import pwd
            home = pwd.getpwuid(os.getuid()).pw_dir
        else:
            home = os.environ.get('USERPROFILE')
            if not home:
                raise ValueError('Use an absolute source path on this installation')
        source = str(Path(home) / source[2:]) if source != '~' else home
    path = Path(source).expanduser().resolve()
    assert_not_restricted_read_path(path, label="Source file")
    if path.exists():
        return str(path), {'source_type': 'file', 'original_name': path.name}
    
    raise ValueError(f"Source not found: {source}")


def convert_image_to_image(input_path: str, output_path: str, options: dict = None) -> dict:
    """Convert between image formats using ImageMagick."""
    executable = 'magick' if check_tool('magick') else 'convert'
    if not check_tool(executable):
        raise RuntimeError("ImageMagick not installed. Run: sudo apt install imagemagick")
    
    options = options or {}
    settings = background_removal_options(options, get_format(output_path))
    cmd = [executable, input_path]
    color = None
    if settings:
        color = solid_background_color(input_path, settings, options.get('resize'))
        # A one-pixel border connects ALL matching edge regions. Copy keeps
        # existing alpha; Over here would flatten transparent source pixels.
        # Only connected background is removed: enclosed white fur stays.
        cmd.extend(['-alpha', 'set', '-precision', '16', '-format', 'alpha_info:%[fx:mean.a]\n', '-write', 'info:',
                    '-compose', 'Copy', '-bordercolor', color,
                    '-border', '1x1', '-compose', 'Over', '-fuzz', f"{settings['tolerance']:g}%",
                    '-fill', 'none', '-draw', 'matte 0,0 floodfill' if executable == 'convert' else 'alpha 0,0 floodfill',
                    '-shave', '1x1', '+repage', '-format', 'alpha_info:%[fx:mean.a]\n', '-write', 'info:'])
    
    # Quality setting (for lossy formats)
    if 'quality' in options:
        cmd.extend(['-quality', str(options['quality'])])
    
    # Resize if specified
    if 'resize' in options:
        cmd.extend(['-resize', options['resize']])
    
    # Strip metadata if requested
    if options.get('strip_metadata', False):
        cmd.append('-strip')
    
    cmd.append('PNG32:' + output_path if settings and get_format(output_path) == 'png' else output_path)
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=conversion_timeout(120))
    if result.returncode != 0:
        raise RuntimeError(f"ImageMagick failed: {result.stderr}")
    
    result_data = {'tool': 'imagemagick', 'command': ' '.join(cmd)}
    if settings:
        opacity = [float(value) for value in re.findall(r'alpha_info:([0-9.eE+-]+)', result.stdout)]
        if len(opacity) != 2 or not all(math.isfinite(value) and 0 <= value <= 1 for value in opacity):
            raise RuntimeError('ImageMagick did not return valid background removal evidence')
        if opacity[1] >= opacity[0]:
            raise RuntimeError('No new edge-connected background was removed; check background_color/tolerance')
        result_data.update(background_removed=True, method='edge_connected_color',
                           background_color=color, background_tolerance=settings['tolerance'],
                           **transparency_info(output_path))
    return result_data


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
        result = subprocess.run(convert_cmd, capture_output=True, text=True, timeout=conversion_timeout(60))
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
        
        result = subprocess.run(potrace_cmd, capture_output=True, text=True, timeout=conversion_timeout(120))
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
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=conversion_timeout(600))
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
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=conversion_timeout(300))
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
    elif output_format == 'ogg':
        cmd.extend(['-c:a', 'libvorbis'])
    else:
        cmd.extend(['-c:a', 'aac'])
    
    cmd.append(output_path)
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=conversion_timeout(300))
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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=conversion_timeout(30))
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
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

        removal = background_removal_options(options, target_format)
        
        # Resolve source to local file
        input_path, source_meta = resolve_source(source)
        background_limit = os.environ.get('JARVIS_BACKGROUND_MAX_INPUT_BYTES')
        if background_limit and os.path.getsize(input_path) > int(background_limit):
            raise ValueError('Source exceeds the background conversion size limit')
        source_format = get_format(input_path)
        
        # Determine conversion type
        source_is_image = source_format in IMAGE_FORMATS
        source_is_video = source_format in VIDEO_FORMATS
        source_is_audio = source_format in AUDIO_FORMATS
        
        target_is_image = target_format in IMAGE_FORMATS
        target_is_video = target_format in VIDEO_FORMATS
        target_is_audio = target_format in AUDIO_FORMATS
        if removal and not source_is_image:
            raise ValueError('Background removal requires a raster image source')
        
        # Create output filename
        original_name = source_meta.get('original_name', 'converted')
        base_name = Path(original_name).stem
        output_filename = f"{base_name}{'_transparent' if removal else ''}.{target_format}"
        
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
            space, _ = open_space(
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
            if removal:
                result_data.update(background_removed=True, transparent=True,
                    width=conversion_info['width'], height=conversion_info['height'],
                    background_removal_method=conversion_info['method'],
                    background_removal_note='Removed an edge-connected solid color; complex backgrounds and fine hair may need a subject mask.')
            
            # Calculate size change
            if input_size > 0:
                ratio = output_size / input_size
                if ratio < 1:
                    result_data['size_change'] = f"{(1-ratio)*100:.1f}% smaller"
                else:
                    result_data['size_change'] = f"{(ratio-1)*100:.1f}% larger"
            
            print(json.dumps({
                "ok": True,
                "speech": (f"Removed the solid background and saved a transparent {target_format.upper()} to Stash."
                           if removal else f"Converted {source_format.upper()} to {target_format.upper()}. Saved to stash."),
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
