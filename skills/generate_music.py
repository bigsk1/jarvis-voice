#!/usr/bin/env python3
"""
Music Generation Tool for Jarvis
Uses ElevenLabs Music API to compose AI-generated music.

Features:
  - Simple prompt-based generation
  - Detailed composition plans with sections and lyrics
  - Multiple genres, moods, and styles
  - Instrumental or vocal options
  - Multiple output formats (mp3, opus, pcm)
  - Saves to stash for playback in web UI and other tools

API Reference: https://elevenlabs.io/docs/api-reference/music/compose
Best Practices: https://elevenlabs.io/docs/overview/capabilities/music/best-practices

Configure via ELEVENLABS_API_KEY in cloud.env
"""

import sys
import json
import requests
from pathlib import Path
from datetime import datetime

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
from config_loader import load_config, get_config_value

# =============================================================================
# ElevenLabs Music API Configuration
# =============================================================================
ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1/music"

# Output format options
OUTPUT_FORMATS = {
    "mp3_low": "mp3_22050_32",
    "mp3_medium": "mp3_44100_128",
    "mp3_high": "mp3_44100_192",
    "opus_low": "opus_48000_32",
    "opus_medium": "opus_48000_128",
    "opus_high": "opus_48000_192",
    "pcm_16k": "pcm_16000",
    "pcm_44k": "pcm_44100",
    "pcm_48k": "pcm_48000",
}

# Duration limits
MIN_DURATION_MS = 3000      # 3 seconds
MAX_DURATION_MS = 600000    # 10 minutes
DEFAULT_DURATION_MS = 60000 # 1 minute

# Music styles/genres for prompt enhancement
GENRE_HINTS = {
    "pop": "catchy pop song with memorable melody and modern production",
    "rock": "energetic rock track with electric guitars and driving drums",
    "jazz": "smooth jazz piece with sophisticated harmonies and improvisation",
    "classical": "orchestral classical composition with rich instrumentation",
    "electronic": "electronic dance music with synthesizers and beats",
    "ambient": "atmospheric ambient soundscape for relaxation",
    "hip-hop": "hip-hop beat with strong rhythm and bass",
    "country": "country song with acoustic guitars and heartfelt feel",
    "r&b": "smooth R&B track with soulful melodies",
    "folk": "folk acoustic song with warm organic sound",
    "metal": "heavy metal track with distorted guitars and powerful drums",
    "lo-fi": "lo-fi chill beats with vinyl crackle aesthetic",
    "cinematic": "epic cinematic score for film or video",
    "jingle": "short catchy commercial jingle",
}


def generate_music(prompt: str, duration_seconds: int = 60, 
                   genre: str = None, mood: str = None,
                   instrumental: bool = False, 
                   tempo: str = None, 
                   output_format: str = "mp3_medium",
                   use_detailed_api: bool = False) -> dict:
    """
    Generate music using ElevenLabs Music API.
    
    Args:
        prompt: Description of the music to generate
        duration_seconds: Length in seconds (3-600)
        genre: Optional genre hint (pop, rock, jazz, etc.)
        mood: Optional mood (happy, sad, energetic, calm, etc.)
        instrumental: If True, force no vocals
        tempo: Optional tempo hint (slow, medium, fast, or BPM like "120 BPM")
        output_format: Audio format (mp3_low/medium/high, opus_*, pcm_*)
        use_detailed_api: Use /detailed endpoint for more metadata
    """
    
    api_key = get_config_value('ELEVENLABS_API_KEY')
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY not configured. Add it to config/cloud.env")
    
    # Convert duration to milliseconds
    duration_ms = duration_seconds * 1000
    duration_ms = max(MIN_DURATION_MS, min(MAX_DURATION_MS, duration_ms))
    
    # Build enhanced prompt
    full_prompt = prompt
    
    # Add genre context
    if genre:
        genre_lower = genre.lower()
        if genre_lower in GENRE_HINTS:
            full_prompt = f"{GENRE_HINTS[genre_lower]}: {prompt}"
        else:
            full_prompt = f"{genre} style: {prompt}"
    
    # Add mood
    if mood:
        full_prompt = f"{mood} mood, {full_prompt}"
    
    # Add tempo
    if tempo:
        full_prompt = f"{full_prompt}, {tempo} tempo"
    
    # Get output format
    format_code = OUTPUT_FORMATS.get(output_format, OUTPUT_FORMATS["mp3_medium"])
    
    # Build API URL
    endpoint = f"{ELEVENLABS_API_BASE}/detailed" if use_detailed_api else ELEVENLABS_API_BASE
    url = f"{endpoint}?output_format={format_code}"
    
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json"
    }
    
    payload = {
        "prompt": full_prompt,
        "music_length_ms": duration_ms,
        "model_id": "music_v1",
        "force_instrumental": instrumental,
        "respect_sections_durations": True,
        "store_for_inpainting": False,
        "sign_with_c2pa": False
    }
    
    # Make request - music generation can take a while
    timeout = max(300, duration_seconds * 3)  # At least 5 minutes, or 3x duration
    
    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=timeout
    )
    
    if response.status_code != 200:
        error_msg = response.text
        try:
            error_data = response.json()
            error_msg = error_data.get('detail', {}).get('message', response.text)
        except:
            pass
        raise Exception(f"ElevenLabs Music API error ({response.status_code}): {error_msg}")
    
    # Get song ID from headers if available
    song_id = response.headers.get('x-song-id')
    
    # For detailed API, response is JSON with audio data
    if use_detailed_api:
        try:
            result = response.json()
            audio_data = result.get('audio')
            if audio_data:
                import base64
                audio_bytes = base64.b64decode(audio_data)
            else:
                audio_bytes = response.content
        except:
            audio_bytes = response.content
    else:
        # Simple API returns raw audio
        audio_bytes = response.content
    
    if not audio_bytes or len(audio_bytes) < 1000:
        raise Exception("No audio data received from ElevenLabs")
    
    # Determine file extension
    if "mp3" in format_code:
        ext = "mp3"
        mime_type = "audio/mpeg"
    elif "opus" in format_code:
        ext = "opus"
        mime_type = "audio/opus"
    elif "pcm" in format_code:
        ext = "wav"
        mime_type = "audio/wav"
    else:
        ext = "mp3"
        mime_type = "audio/mpeg"
    
    return {
        "audio_bytes": audio_bytes,
        "mime_type": mime_type,
        "extension": ext,
        "prompt": prompt,
        "full_prompt": full_prompt,
        "duration_ms": duration_ms,
        "instrumental": instrumental,
        "genre": genre,
        "mood": mood,
        "tempo": tempo,
        "output_format": format_code,
        "song_id": song_id,
        "size_bytes": len(audio_bytes)
    }


def generate_with_composition_plan(title: str, sections: list, 
                                   global_styles: list = None,
                                   output_format: str = "mp3_medium") -> dict:
    """
    Generate music with a detailed composition plan (sections with lyrics).
    
    Args:
        title: Song title
        sections: List of section dicts with:
            - section_name: "intro", "verse", "chorus", "bridge", "outro"
            - duration_seconds: Length of section (3-120 seconds)
            - styles: List of style descriptors for this section
            - lyrics: List of lyric lines (optional)
        global_styles: Overall style directions for the whole song
        output_format: Audio format
    """
    
    api_key = get_config_value('ELEVENLABS_API_KEY')
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY not configured")
    
    # Build composition plan
    plan_sections = []
    for section in sections:
        plan_section = {
            "section_name": section.get("section_name", "section"),
            "positive_local_styles": section.get("styles", []),
            "negative_local_styles": section.get("avoid_styles", []),
            "duration_ms": section.get("duration_seconds", 30) * 1000,
            "lines": section.get("lyrics", [])
        }
        plan_sections.append(plan_section)
    
    composition_plan = {
        "positive_global_styles": global_styles or ["professional production", "high quality"],
        "negative_global_styles": ["amateur", "low quality", "distorted"],
        "sections": plan_sections
    }
    
    format_code = OUTPUT_FORMATS.get(output_format, OUTPUT_FORMATS["mp3_medium"])
    url = f"{ELEVENLABS_API_BASE}?output_format={format_code}"
    
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json"
    }
    
    payload = {
        "composition_plan": composition_plan,
        "model_id": "music_v1",
        "respect_sections_durations": True
    }
    
    # Calculate total duration for timeout
    total_duration_ms = sum(s.get("duration_seconds", 30) * 1000 for s in sections)
    timeout = max(300, (total_duration_ms / 1000) * 3)
    
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    
    if response.status_code != 200:
        error_msg = response.text
        try:
            error_data = response.json()
            error_msg = error_data.get('detail', {}).get('message', response.text)
        except:
            pass
        raise Exception(f"ElevenLabs API error ({response.status_code}): {error_msg}")
    
    audio_bytes = response.content
    song_id = response.headers.get('x-song-id')
    
    # Determine extension
    ext = "mp3" if "mp3" in format_code else "opus" if "opus" in format_code else "wav"
    mime_type = "audio/mpeg" if ext == "mp3" else "audio/opus" if ext == "opus" else "audio/wav"
    
    return {
        "audio_bytes": audio_bytes,
        "mime_type": mime_type,
        "extension": ext,
        "title": title,
        "sections": sections,
        "global_styles": global_styles,
        "duration_ms": total_duration_ms,
        "output_format": format_code,
        "song_id": song_id,
        "size_bytes": len(audio_bytes),
        "has_composition_plan": True
    }


def save_to_stash(music_data: dict, title: str) -> dict:
    """Save generated music to stash for playback."""
    from stash_helper import open_space, StashFile
    
    # Generate filename
    safe_title = "".join(c if c.isalnum() or c in ' -_' else '' for c in title[:40])
    safe_title = safe_title.replace(' ', '_').lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = music_data.get('extension', 'mp3')
    filename = f"music_{safe_title}_{timestamp}.{ext}"
    
    # Also save to generated_music directory
    music_dir = Path(__file__).parent.parent / 'data' / 'generated_music'
    music_dir.mkdir(exist_ok=True)
    music_path = music_dir / filename
    music_path.write_bytes(music_data['audio_bytes'])
    
    # Save to stash
    try:
        space, _ = open_space(scope='session', labels=['generated_music', 'audio'])
        stash_file = StashFile(space)
        
        tags = ['ai_generated', 'music', 'elevenlabs']
        if music_data.get('genre'):
            tags.append(music_data['genre'])
        if music_data.get('instrumental'):
            tags.append('instrumental')
        
        result = stash_file.save_binary(
            data=music_data['audio_bytes'],
            name=filename,
            mime_type=music_data.get('mime_type', 'audio/mpeg'),
            on_conflict='overwrite',
            tags=tags,
            tool_origin='generate_music'
        )
        
        return {
            "saved": True,
            "stash_ref": result.get('ref'),
            "space_id": space.space_id,
            "path": str(music_path),
            "stash_path": result.get('path'),
            "filename": filename,
            "stash": True
        }
    except Exception as e:
        return {
            "saved": True,
            "path": str(music_path),
            "filename": filename,
            "stash": False,
            "note": f"File saved but stash failed: {e}"
        }


def main():
    try:
        load_config()
        
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        prompt = args.get('prompt', '')
        composition_plan = args.get('composition_plan')
        
        if not prompt and not composition_plan:
            raise ValueError("Either 'prompt' or 'composition_plan' is required")
        
        # Parameters
        duration_seconds = args.get('duration_seconds', 60)
        genre = args.get('genre')
        mood = args.get('mood')
        instrumental = args.get('instrumental', False)
        tempo = args.get('tempo')
        output_format = args.get('output_format', 'mp3_medium')
        save = args.get('save', True)
        title = args.get('title', prompt[:50] if prompt else 'Untitled Song')
        
        # Generate music
        if composition_plan:
            # Use composition plan API
            result = generate_with_composition_plan(
                title=title,
                sections=composition_plan.get('sections', []),
                global_styles=composition_plan.get('global_styles'),
                output_format=output_format
            )
        else:
            # Use simple prompt API
            result = generate_music(
                prompt=prompt,
                duration_seconds=duration_seconds,
                genre=genre,
                mood=mood,
                instrumental=instrumental,
                tempo=tempo,
                output_format=output_format
            )
        
        # Save to stash
        save_info = None
        if save:
            save_info = save_to_stash(result, title)
            
            # Save to memory for discovery
            try:
                from memory_db import MemoryDB
                db = MemoryDB()
                
                stash_ref = save_info.get('stash_ref', '')
                space_id = save_info.get('space_id', '')
                
                memory_key = f"stash_music_{space_id}" if space_id else f"generated_music_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                memory_value = f"Generated music: {title}. Genre: {genre or 'unspecified'}. Duration: {result.get('duration_ms', 0)//1000}s. STASH: {stash_ref}"
                
                db.remember(
                    key=memory_key,
                    value=memory_value,
                    category="stash_artifact",
                    importance=6,
                    source="generate_music",
                    metadata={
                        "stash_ref": stash_ref,
                        "space_id": space_id,
                        "filename": save_info.get('filename', ''),
                        "title": title,
                        "genre": genre,
                        "duration_seconds": result.get('duration_ms', 0) // 1000,
                        "instrumental": instrumental,
                        "tags": ["music", "audio", "generated", "ai_created"],
                        "type": "audio"
                    }
                )
            except Exception:
                pass
        
        # Build response
        duration_sec = result.get('duration_ms', 0) // 1000
        speech = f"Generated {duration_sec} second {'instrumental ' if instrumental else ''}music"
        if genre:
            speech += f" in {genre} style"
        speech += f": {title[:40]}"
        
        response = {
            "ok": True,
            "speech": speech,
            "data": {
                "title": title,
                "duration_seconds": duration_sec,
                "genre": genre,
                "mood": mood,
                "instrumental": instrumental,
                "tempo": tempo,
                "mime_type": result.get('mime_type'),
                "size_bytes": result.get('size_bytes'),
                "song_id": result.get('song_id')
            }
        }
        
        if save_info:
            response["data"]["saved"] = save_info
            if save_info.get('path'):
                response["data"]["file_path"] = save_info['path']
            if save_info.get('stash_ref'):
                response["data"]["stash_ref"] = save_info['stash_ref']
                # For web UI playback
                response["audio_url"] = f"/api/stash/{save_info.get('space_id')}/{save_info.get('stash_ref', '').split('/')[-1]}"
        
        print(json.dumps(response))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "speech": f"Failed to generate music: {e}",
            "error": str(e)
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
