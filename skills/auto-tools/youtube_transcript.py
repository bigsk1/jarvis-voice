#!/usr/bin/env python3
"""
YouTube Transcript Downloader - Downloads transcripts in .srt format and converts to markdown.
Both files are saved to stash for indexing.
"""
import sys
import os
import json
import shutil
import subprocess
import tempfile
import re
from pathlib import Path

# IMPORTANT: This tool lives in skills/auto-tools/, so go up 2 levels to reach lib/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lib'))
from config_loader import load_config, get_config_value
from http_client import build_proxy_url_attempts
from stash_helper import open_space, StashFile
from memory_db import MemoryDB


def serpapi_youtube_fallback_enabled() -> bool:
    """Only advertise SerpApi YouTube fallback when explicitly enabled and the tool is active."""
    enabled = get_config_value("SERPAPI_YOUTUBE_FALLBACK", "false").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return False

    tool_path = Path(__file__).resolve().parent.parent / "serpapi_youtube.tool.json"
    try:
        if not tool_path.is_file():
            return False
        with open(tool_path, "r", encoding="utf-8") as fh:
            tool_config = json.load(fh)
        return bool(tool_config.get("enabled", True))
    except Exception:
        return False


def maybe_append_serpapi_hint(message: str, url: str) -> str:
    """Append an opt-in hint for SerpApi YouTube fallback after yt-dlp transcript failures."""
    text = (message or "").strip()
    if not serpapi_youtube_fallback_enabled():
        return text
    hint = (
        f" SerpApi YouTube fallback is enabled. "
        f"Try serpapi_youtube with this URL for video details and transcript fallback: {url}"
    )
    return text + hint

def convert_srt_to_markdown(srt_content, video_title):
    """Convert SRT subtitle format to clean markdown."""
    lines = srt_content.strip().split('\n')
    markdown_lines = [f"# {video_title}\n\n"]
    
    current_text = []
    
    for line in lines:
        line = line.strip()
        
        # Skip sequence numbers
        if line.isdigit():
            continue
        
        # Skip timestamp lines (format: 00:00:00,000 --> 00:00:00,000)
        if '-->' in line:
            continue
        
        # Empty line indicates end of subtitle block
        if not line:
            if current_text:
                # Join and clean up the text
                text = ' '.join(current_text)
                # Remove duplicate spaces
                text = re.sub(r'\s+', ' ', text)
                markdown_lines.append(text + '\n\n')
                current_text = []
        else:
            current_text.append(line)
    
    # Handle any remaining text
    if current_text:
        text = ' '.join(current_text)
        text = re.sub(r'\s+', ' ', text)
        markdown_lines.append(text + '\n\n')
    
    return ''.join(markdown_lines)

def resolve_yt_dlp_command() -> list[str]:
    """Prefer yt-dlp binary, fallback to module invocation (matches youtube_video)."""
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]


def get_video_title(url, proxy=None):
    """Extract video title using yt-dlp."""
    try:
        cmd = resolve_yt_dlp_command()
        if proxy:
            cmd.extend(["--proxy", proxy])
        cmd.extend(["--no-warnings", "--get-title", url])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            title = result.stdout.strip()
            # Clean filename
            title = re.sub(r'[<>:"/\\|?*]', '', title)
            return title[:100]  # Limit length
        return "youtube_video"
    except Exception:
        return "youtube_video"

def download_transcript(url, proxy=None):
    """Download transcript using yt-dlp."""
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Get video title first
        video_title = get_video_title(url, proxy=proxy)
        
        # Download subtitles
        output_template = os.path.join(temp_dir, 'transcript')
        
        cmd = resolve_yt_dlp_command()
        if proxy:
            cmd.extend(["--proxy", proxy])
        cmd.extend([
            '--write-auto-sub',
            '--write-sub',
            '--sub-lang', 'en',
            '--sub-format', 'srt',
            '--skip-download',
            '--output', output_template,
            url,
        ])
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            return None, None, f"yt-dlp error: {result.stderr}"
        
        # Find the .srt file
        srt_files = list(Path(temp_dir).glob('*.srt'))
        
        if not srt_files:
            return None, None, "No transcript available for this video"
        
        srt_file = srt_files[0]
        
        with open(srt_file, 'r', encoding='utf-8') as f:
            srt_content = f.read()
        
        return srt_content, video_title, None
        
    except subprocess.TimeoutExpired:
        return None, None, "Timeout while downloading transcript"
    except Exception as e:
        return None, None, str(e)
    finally:
        try:
            shutil.rmtree(temp_dir)
        except OSError:
            pass

def save_to_stash(filename, content, space=None):
    """Save file to stash using stash_helper library."""
    try:
        # Create/reuse a stash space for YouTube transcripts
        if space is None:
            space, _ = open_space(scope='session', labels=['youtube_transcripts'])
        
        stash_file = StashFile(space)
        result = stash_file.save_text(
            content=content,
            name=filename,
            on_conflict='overwrite',
            tags=['transcript', 'youtube'],
            tool_origin='youtube_transcript'
        )
        
        # save_text returns dict with file_id, ref, path etc on success
        success = bool(result.get('file_id'))
        return success, space, result.get('ref')
        
    except Exception as e:
        print(f"Stash error: {e}", file=sys.stderr)
        return False, space, None

def main():
    try:
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        load_config()
        
        url = args.get('url', '').strip()
        
        if not url:
            print(json.dumps({
                "ok": False,
                "error": "No URL provided",
                "speech": "Please provide a YouTube URL"
            }))
            sys.exit(1)
        
        # Validate YouTube URL
        if not ('youtube.com' in url or 'youtu.be' in url):
            print(json.dumps({
                "ok": False,
                "error": "Invalid YouTube URL",
                "speech": "Please provide a valid YouTube URL"
            }))
            sys.exit(1)
        
        proxy_attempts = build_proxy_url_attempts(direct_fallback_default=False)

        srt_content, video_title, error = None, None, None
        for proxy in proxy_attempts:
            srt_content, video_title, error = download_transcript(url, proxy=proxy)
            if not error:
                break

        if error:
            error_message = maybe_append_serpapi_hint(error, url)
            speech = maybe_append_serpapi_hint(f"Failed to download transcript: {error}", url)
            print(json.dumps({
                "ok": False,
                "error": error_message,
                "speech": speech
            }))
            sys.exit(1)
        
        # Convert to markdown
        markdown_content = convert_srt_to_markdown(srt_content, video_title)
        
        # Create safe filenames
        safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', video_title)
        srt_filename = f"{safe_title}_transcript.srt"
        md_filename = f"{safe_title}_transcript.md"
        
        # Save both files to stash (reuse same space)
        srt_saved, space, srt_ref = save_to_stash(srt_filename, srt_content)
        md_saved, _, md_ref = save_to_stash(md_filename, markdown_content, space)
        
        # Save stash artifacts to memory for follow-up queries
        if md_saved and md_ref and space:
            try:
                db = MemoryDB()
                space_id = space.space_id
                
                # Save the markdown transcript reference (primary - readable content)
                db.remember(
                    key=f"youtube_transcript_{space_id}",
                    value=f"YouTube transcript: {video_title}. STASH: {md_ref}. FILE: {md_filename}. URL: {url}",
                    category="stash_artifact",
                    importance=6,
                    source="youtube_transcript",
                    metadata={
                        "stash_ref": md_ref,
                        "srt_stash_ref": srt_ref,
                        "space_id": space_id,
                        "filename": md_filename,
                        "srt_filename": srt_filename,
                        "video_title": video_title,
                        "youtube_url": url,
                        "transcript_length": len(markdown_content),
                        "tags": ["transcript", "youtube", "video", "text"],
                        "type": "transcript"
                    }
                )
            except Exception as e:
                print(f"Memory save warning: {e}", file=sys.stderr)
        
        if srt_saved and md_saved:
            speech = f"Downloaded transcript for {video_title}. Saved SRT and markdown files to stash."
        elif srt_saved or md_saved:
            speech = f"Partially saved transcript for {video_title}. Check stash for available files."
        else:
            speech = f"Downloaded transcript for {video_title}, but failed to save to stash."
        
        print(json.dumps({
            "ok": True,
            "speech": speech,
            "data": {
                "video_title": video_title,
                "srt_filename": srt_filename,
                "md_filename": md_filename,
                "srt_saved": srt_saved,
                "md_saved": md_saved,
                "srt_stash_ref": srt_ref,
                "md_stash_ref": md_ref,
                "space_id": space.space_id if space else None,
                "transcript_length": len(srt_content)
            }
        }))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Error downloading transcript: {e}"
        }))
        sys.exit(1)

if __name__ == "__main__":
    main()
