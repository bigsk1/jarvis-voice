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
import math
from pathlib import Path

# IMPORTANT: This tool lives in skills/auto-tools/, so go up 2 levels to reach lib/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lib'))
from config_loader import load_config, get_config_value
from http_client import build_proxy_url_attempts, PROXY_POLICY_ENV, STANDARD_PROXY_ENV_KEYS
from stash_helper import open_space, StashFile
from memory_db import MemoryDB
from security_utils import redact_sensitive_text
from tool_profiles import effective_enabled, load_active_profile_overrides
from ytdlp_runtime import resolve_yt_dlp_command, runtime_args, subprocess_environment

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serpapi_youtube import extract_video_id, fetch_transcript, build_transcript_markdown


def serpapi_youtube_fallback_enabled() -> bool:
    """Require opt-in, credentials, and effective tool/profile enablement."""
    enabled = get_config_value("SERPAPI_YOUTUBE_FALLBACK", "false").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return False
    if not str(get_config_value('SERP_API_KEY', '') or '').strip():
        return False

    tool_path = Path(__file__).resolve().parent.parent / "serpapi_youtube.tool.json"
    try:
        if not tool_path.is_file():
            return False
        with open(tool_path, "r", encoding="utf-8") as fh:
            tool_config = json.load(fh)
        return effective_enabled('serpapi_youtube', bool(tool_config.get('enabled', True)), load_active_profile_overrides())
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

def download_transcript(url, proxy=None):
    """Download transcript using yt-dlp."""
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Download subtitles
        output_template = os.path.join(temp_dir, 'transcript')
        
        cmd = resolve_yt_dlp_command() + runtime_args(proxy)
        cmd.extend([
            '--no-playlist', '--write-info-json',
            '--socket-timeout', '8', '--retries', '1', '--extractor-retries', '1',
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
            timeout=35,
            env=subprocess_environment(),
        )
        
        if result.returncode != 0:
            errors = [line for line in result.stderr.splitlines() if line.startswith('ERROR:')]
            detail = '\n'.join(errors) or result.stderr
            return None, None, 'yt-dlp error: ' + redact_sensitive_text(detail).strip()[:1000]
        
        # Find the .srt file
        srt_files = list(Path(temp_dir).glob('*.srt'))
        
        if not srt_files:
            return None, None, "No transcript available for this video"
        
        srt_file = srt_files[0]
        
        with open(srt_file, 'r', encoding='utf-8') as f:
            srt_content = f.read()
        if not srt_content.strip():
            return None, None, 'Downloaded transcript was empty'
        try:
            info = json.loads(Path(temp_dir, 'transcript.info.json').read_text())
        except (OSError, ValueError):
            info = {}
        if not isinstance(info, dict):
            info = {}
        video_title = re.sub(r'[<>:"/\\|?*]', '', str(info.get('title') or 'youtube_video'))[:100]
        
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


def fetch_serpapi_fallback(url):
    """Fetch once through the enabled tool's transport policy; save no artifacts here."""
    tool_path = Path(__file__).resolve().parents[1] / 'serpapi_youtube.tool.json'
    policy = json.loads(tool_path.read_text()).get('proxy_policy', 'off')
    keys = (*STANDARD_PROXY_ENV_KEYS, PROXY_POLICY_ENV)
    previous = {key: os.environ.get(key) for key in keys}
    try:
        os.environ[PROXY_POLICY_ENV] = policy
        if policy == 'off':
            for key in STANDARD_PROXY_ENV_KEYS:
                os.environ.pop(key, None)
        video_id = extract_video_id(url)
        if not video_id:
            raise ValueError('Invalid YouTube URL')
        return fetch_transcript(video_id, 'en', '', '', False)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def transcript_segments_to_srt(segments):
    """Keep supplied starts; infer cue endings when the API supplies no duration."""
    cues = []
    for item in segments:
        if not isinstance(item, dict) or not str(item.get('snippet') or '').strip():
            continue
        start = float(item['start_ms'])
        if not math.isfinite(start) or start < 0:
            raise ValueError('SerpApi transcript has an invalid timestamp')
        cues.append((int(start), str(item['snippet']).strip()))
    cues.sort(key=lambda cue: cue[0])
    if not cues:
        raise ValueError('SerpApi returned no transcript segments')

    def clock(milliseconds):
        seconds, ms = divmod(milliseconds, 1000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f'{hours:02}:{minutes:02}:{seconds:02},{ms:03}'

    lines = []
    for index, (start, text) in enumerate(cues):
        end = max(start + 1, cues[index+1][0]) if index+1 < len(cues) else start + 3000
        lines.append(f'{index+1}\n{clock(start)} --> {clock(end)}\n{text}\n')
    return '\n'.join(lines)

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
        video_id = extract_video_id(url)
        if not video_id:
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

        source = 'yt-dlp'
        fallback_markdown = None
        fallback_attempted = False
        if error and serpapi_youtube_fallback_enabled():
            fallback_attempted = True
            try:
                transcript = fetch_serpapi_fallback(url)
                srt_content = transcript_segments_to_srt(transcript.get('transcript') or [])
                video_title = 'YouTube video ' + video_id
                fallback_markdown = build_transcript_markdown({'title': video_title, 'url': url}, transcript)
                source, error = 'SerpApi', None
            except Exception as exc:
                error += ' SerpApi fallback failed: ' + redact_sensitive_text(str(exc))[:500]

        if error:
            error_message = error if fallback_attempted else maybe_append_serpapi_hint(error, url)
            speech = f"Failed to download transcript: {error_message}"
            print(json.dumps({
                "ok": False,
                "error": error_message,
                "speech": speech
            }))
            sys.exit(1)
        
        # Convert to markdown
        markdown_content = fallback_markdown or convert_srt_to_markdown(srt_content, video_title)
        
        # Create safe filenames
        safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', video_title)
        srt_filename = f"{safe_title}_transcript.srt"
        md_filename = f"{safe_title}_transcript.md"
        
        # Save both files to stash (reuse same space)
        srt_saved, space, srt_ref = save_to_stash(srt_filename, srt_content)
        md_saved, md_space, md_ref = save_to_stash(md_filename, markdown_content, space)
        if md_space is not None:
            space = md_space
        
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
            if source == 'SerpApi':
                speech += ' Used the enabled SerpApi fallback.'
        elif srt_saved or md_saved:
            speech = f"Partially saved transcript for {video_title}. Check stash for available files."
        else:
            speech = f"Downloaded transcript for {video_title}, but failed to save to stash."

        # Workflows read the markdown artifact; an SRT alone cannot satisfy them.
        markdown_available = bool(md_saved and md_ref and space)
        error_details = {}
        if not markdown_available:
            error_details["error"] = "Failed to save markdown transcript to stash"
        
        print(json.dumps({
            "ok": markdown_available,
            "speech": speech,
            **error_details,
            "data": {
                "source": source,
                "fallback_used": source == 'SerpApi',
                "video_id": video_id,
                "url": url,
                "video_title": video_title,
                "srt_filename": srt_filename,
                "md_filename": md_filename,
                "srt_saved": srt_saved,
                "md_saved": md_saved,
                "srt_stash_ref": srt_ref,
                "md_stash_ref": md_ref,
                "transcript_stash_ref": md_ref,
                "srt_timing": 'cue end times inferred from the next segment; final cue ends 3 seconds later' if source == 'SerpApi' else 'source subtitle timings',
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
