#!/usr/bin/env python3
"""
Music Generation Tool for Jarvis
Uses ElevenLabs Music or Google Gemini Lyria to compose AI-generated music.

Features:
  - Simple prompt-based generation
  - ElevenLabs composition plans with sections and lyrics
  - Multiple genres, moods, and styles
  - Instrumental or vocal options
  - Provider-specific MP3 and Opus output
  - Saves to stash for playback in web UI and other tools

API Reference: https://elevenlabs.io/docs/api-reference/music/compose
Gemini Reference: https://ai.google.dev/gemini-api/docs/music-generation

Configure with MUSIC_TOOL_PROVIDER and the selected provider's API key.
"""

import sys
import json
import base64
import os
import requests
from pathlib import Path
from datetime import datetime

# Add lib to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'lib'))
from audio_catalog import upsert_audio_catalog_entry
from config_loader import load_config, get_config_value
from model_catalog import (
    get_media_catalog_providers,
    get_media_model_env_key,
    get_media_model_metadata,
    resolve_media_model,
)

GENERATED_MUSIC_DIR = PROJECT_ROOT / 'data' / 'generated_music'
AUDIO_CATALOG_FILE = GENERATED_MUSIC_DIR / 'audio_catalog.json'

# =============================================================================
# Music Provider Configuration
# =============================================================================
ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1/music"
DEFAULT_MUSIC_PROVIDER = "elevenlabs"
SUPPORTED_MUSIC_PROVIDERS = tuple(get_media_catalog_providers("music"))

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


def resolve_music_provider(provider: str | None = None) -> str:
    """Resolve and validate the configured or per-request music provider."""
    web_override = os.environ.get("JARVIS_OVERRIDE_MUSIC_TOOL_PROVIDER")
    selected = (
        web_override
        or provider
        or get_config_value("MUSIC_TOOL_PROVIDER", DEFAULT_MUSIC_PROVIDER)
        or DEFAULT_MUSIC_PROVIDER
    )
    selected = str(selected).strip().lower()
    if selected not in SUPPORTED_MUSIC_PROVIDERS:
        supported = ", ".join(SUPPORTED_MUSIC_PROVIDERS)
        raise ValueError(
            f"Unsupported music provider '{selected}'. "
            f"Currently supported: {supported}"
        )
    return selected


def resolve_music_model(provider: str) -> str:
    """Resolve the configured model pin or catalog default for a provider."""
    env_key = get_media_model_env_key("music", provider)
    configured = get_config_value(env_key, "") if env_key else ""
    model = resolve_media_model("music", provider, configured)
    if not model:
        raise ValueError(f"No music model is configured for provider '{provider}'")
    return model


def _enhance_music_prompt(
    prompt: str,
    genre: str | None,
    mood: str | None,
    tempo: str | None,
    instrumental: bool,
) -> str:
    """Build the common provider-neutral prompt from structured hints."""
    full_prompt = prompt
    if genre:
        genre_lower = genre.lower()
        if genre_lower in GENRE_HINTS:
            full_prompt = f"{GENRE_HINTS[genre_lower]}: {prompt}"
        else:
            full_prompt = f"{genre} style: {prompt}"
    if mood:
        full_prompt = f"{mood} mood, {full_prompt}"
    if tempo:
        full_prompt = f"{full_prompt}, {tempo} tempo"
    if instrumental:
        full_prompt = f"{full_prompt}. Instrumental only, no vocals."
    return full_prompt


def generate_music_elevenlabs(
    prompt: str,
    duration_seconds: int = 60,
    genre: str = None,
    mood: str = None,
    instrumental: bool = False,
    tempo: str = None,
    output_format: str = "mp3_medium",
    use_detailed_api: bool = False,
) -> dict:
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
    model = resolve_music_model("elevenlabs")
    
    # Convert duration to milliseconds
    duration_ms = duration_seconds * 1000
    duration_ms = max(MIN_DURATION_MS, min(MAX_DURATION_MS, duration_ms))
    
    full_prompt = _enhance_music_prompt(
        prompt,
        genre,
        mood,
        tempo,
        instrumental=False,
    )
    
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
        "model_id": model,
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
        "size_bytes": len(audio_bytes),
        "provider": "ElevenLabs",
        "model": model,
    }


def generate_music_gemini(
    prompt: str,
    duration_seconds: int = 60,
    genre: str = None,
    mood: str = None,
    instrumental: bool = False,
    tempo: str = None,
    output_format: str = "mp3_medium",
) -> dict:
    """Generate Lyria music through Gemini Interactions."""
    api_key = get_config_value("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not configured. Add it to the active mode env file")
    if not output_format.startswith("mp3_"):
        raise ValueError(
            "The Gemini Lyria adapter returns MP3 only; choose mp3_low, "
            "mp3_medium, or mp3_high"
        )

    try:
        from google import genai
    except ImportError:
        raise ValueError("google-genai not installed. Run: uv sync --dev")

    model = resolve_music_model("gemini")
    model_metadata = get_media_model_metadata("music", "gemini", model) or {}
    full_prompt = _enhance_music_prompt(
        prompt,
        genre,
        mood,
        tempo,
        instrumental,
    )
    duration_metadata = model_metadata.get("duration_seconds", {})
    fixed_duration_seconds = duration_metadata.get("fixed")
    if fixed_duration_seconds is None:
        full_prompt = (
            f"{full_prompt} Target a duration of approximately "
            f"{duration_seconds} seconds, with a coherent musical ending."
        )
    client = genai.Client(api_key=api_key)
    interaction = client.interactions.create(
        model=model,
        input=full_prompt,
        timeout=300,
    )

    status = getattr(interaction, "status", "completed")
    status_value = getattr(status, "value", status)
    if str(status_value).strip().lower() == "failed":
        raise Exception("Gemini Lyria interaction failed")

    audio = getattr(interaction, "output_audio", None)
    encoded_audio = getattr(audio, "data", None) if audio else None
    if not encoded_audio:
        raise Exception("No audio generated - empty Gemini Lyria response")
    try:
        audio_bytes = base64.b64decode(encoded_audio)
    except (TypeError, ValueError) as exc:
        raise Exception("Gemini Lyria returned invalid audio data") from exc
    if len(audio_bytes) < 1000:
        raise Exception("No audio data received from Gemini Lyria")

    return {
        "audio_bytes": audio_bytes,
        "mime_type": getattr(audio, "mime_type", None) or "audio/mpeg",
        "extension": "mp3",
        "prompt": prompt,
        "full_prompt": full_prompt,
        "duration_ms": (
            fixed_duration_seconds * 1000
            if fixed_duration_seconds is not None
            else duration_seconds * 1000
        ),
        "duration_is_estimate": fixed_duration_seconds is None,
        "requested_duration_ms": duration_seconds * 1000,
        "instrumental": instrumental,
        "genre": genre,
        "mood": mood,
        "tempo": tempo,
        "output_format": "mp3",
        "requested_output_format": output_format,
        "song_id": getattr(interaction, "id", None),
        "size_bytes": len(audio_bytes),
        "provider": "Google Gemini",
        "model": model,
        "generation_text": getattr(interaction, "output_text", None),
        "synthid_watermarked": True,
    }


def generate_music(prompt: str, duration_seconds: int = 60,
                   genre: str = None, mood: str = None,
                   instrumental: bool = False,
                   tempo: str = None,
                   output_format: str = "mp3_medium",
                   use_detailed_api: bool = False,
                   provider: str = None) -> dict:
    """Generate music through the selected catalog-backed provider adapter."""
    provider = resolve_music_provider(provider)
    if provider == "gemini":
        return generate_music_gemini(
            prompt=prompt,
            duration_seconds=duration_seconds,
            genre=genre,
            mood=mood,
            instrumental=instrumental,
            tempo=tempo,
            output_format=output_format,
        )
    return generate_music_elevenlabs(
        prompt=prompt,
        duration_seconds=duration_seconds,
        genre=genre,
        mood=mood,
        instrumental=instrumental,
        tempo=tempo,
        output_format=output_format,
        use_detailed_api=use_detailed_api,
    )


def generate_with_composition_plan(title: str, sections: list, 
                                   global_styles: list = None,
                                   output_format: str = "mp3_medium",
                                   provider: str = None) -> dict:
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
        provider: Music provider override (composition plans currently ElevenLabs)
    """
    provider = resolve_music_provider(provider)
    if provider != "elevenlabs":
        raise ValueError(
            "Structured composition plans are currently supported only by "
            "the ElevenLabs music provider"
        )

    api_key = get_config_value('ELEVENLABS_API_KEY')
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY not configured")
    model = resolve_music_model(provider)

    if model == "music_v2":
        chunks = []
        for section in sections:
            section_name = section.get("section_name", "section")
            lyrics = section.get("lyrics", [])
            text = f"[{section_name}]"
            if lyrics:
                text = f"{text}\n" + "\n".join(str(line) for line in lyrics)
            positive_styles = list(dict.fromkeys([
                *(global_styles or []),
                *section.get("styles", []),
            ]))
            if not positive_styles:
                positive_styles = ["professional production", "high quality"]
            chunks.append({
                "text": text,
                "duration_ms": section.get("duration_seconds", 30) * 1000,
                "positive_styles": positive_styles,
                "negative_styles": section.get("avoid_styles", []),
                "context_adherence": "high",
            })
        composition_plan = {"chunks": chunks}
    else:
        plan_sections = []
        for section in sections:
            plan_sections.append({
                "section_name": section.get("section_name", "section"),
                "positive_local_styles": section.get("styles", []),
                "negative_local_styles": section.get("avoid_styles", []),
                "duration_ms": section.get("duration_seconds", 30) * 1000,
                "lines": section.get("lyrics", []),
            })
        composition_plan = {
            "positive_global_styles": global_styles or [
                "professional production",
                "high quality",
            ],
            "negative_global_styles": ["amateur", "low quality", "distorted"],
            "sections": plan_sections,
        }
    
    format_code = OUTPUT_FORMATS.get(output_format, OUTPUT_FORMATS["mp3_medium"])
    url = f"{ELEVENLABS_API_BASE}?output_format={format_code}"
    
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json"
    }
    
    payload = {
        "composition_plan": composition_plan,
        "model_id": model,
    }
    if model == "music_v1":
        payload["respect_sections_durations"] = True
    
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
        "has_composition_plan": True,
        "provider": "ElevenLabs",
        "model": model,
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
    GENERATED_MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    music_path = GENERATED_MUSIC_DIR / filename
    music_path.write_bytes(music_data['audio_bytes'])

    save_result = {
        "saved": True,
        "path": str(music_path),
        "filename": filename,
        "stash": False,
    }
    provider_tag = str(
        music_data.get("provider", "unknown")
    ).strip().lower().replace(" ", "_")
    tags = ['ai_generated', 'music', provider_tag]
    if music_data.get('genre'):
        tags.append(music_data['genre'])
    if music_data.get('instrumental'):
        tags.append('instrumental')

    # Save to stash
    try:
        space, _ = open_space(scope='session', labels=['generated_music', 'audio'])
        stash_file = StashFile(space)

        result = stash_file.save_binary(
            data=music_data['audio_bytes'],
            name=filename,
            mime_type=music_data.get('mime_type', 'audio/mpeg'),
            on_conflict='overwrite',
            tags=tags,
            tool_origin='generate_music'
        )
        
        save_result.update({
            "saved": True,
            "stash_ref": result.get('ref'),
            "space_id": space.space_id,
            "path": str(music_path),
            "stash_path": result.get('path'),
            "filename": filename,
            "stash": True
        })
    except Exception as e:
        save_result["note"] = f"File saved but stash failed: {e}"

    catalog_metadata = {
        "title": title,
        "prompt": music_data.get("prompt"),
        "provider": music_data.get("provider", "ElevenLabs"),
        "model": music_data.get("model", "music_v1"),
        "genre": music_data.get("genre"),
        "mood": music_data.get("mood"),
        "tempo": music_data.get("tempo"),
        "instrumental": bool(music_data.get("instrumental", False)),
        "duration_seconds": music_data.get("duration_ms", 0) / 1000,
        "duration_is_estimate": music_data.get("duration_is_estimate", False),
        "format": ext,
        "output_format": music_data.get("output_format"),
        "requested_output_format": music_data.get("requested_output_format"),
        "requested_duration_seconds": (
            music_data.get("requested_duration_ms") / 1000
            if music_data.get("requested_duration_ms") is not None
            else None
        ),
        "mime_type": music_data.get("mime_type"),
        "size_bytes": len(music_data["audio_bytes"]),
        "song_id": music_data.get("song_id"),
        "generation_text": music_data.get("generation_text"),
        "synthid_watermarked": music_data.get("synthid_watermarked"),
        "tool_origin": "generate_music",
        "tags": tags,
        "created_at": datetime.now().isoformat(),
        "stash_ref": save_result.get("stash_ref"),
        "space_id": save_result.get("space_id"),
    }
    try:
        upsert_audio_catalog_entry(
            AUDIO_CATALOG_FILE,
            filename,
            catalog_metadata,
        )
    except Exception as e:
        save_result["catalog_note"] = f"Audio catalog update failed: {e}"

    return save_result


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
        provider = resolve_music_provider(args.get('provider'))
        
        # Generate music
        if composition_plan:
            # Use composition plan API
            result = generate_with_composition_plan(
                title=title,
                sections=composition_plan.get('sections', []),
                global_styles=composition_plan.get('global_styles'),
                output_format=output_format,
                provider=provider,
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
                output_format=output_format,
                provider=provider,
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
        if result.get("duration_is_estimate"):
            speech = (
                f"Generated approximately {duration_sec} seconds of "
                f"{'instrumental ' if instrumental else ''}music"
            )
        else:
            speech = (
                f"Generated {duration_sec} second "
                f"{'instrumental ' if instrumental else ''}music"
            )
        if genre:
            speech += f" in {genre} style"
        speech += f": {title[:40]}"
        
        response = {
            "ok": True,
            "speech": speech,
            "data": {
                "title": title,
                "duration_seconds": duration_sec,
                "duration_is_estimate": result.get("duration_is_estimate", False),
                "genre": genre,
                "mood": mood,
                "instrumental": instrumental,
                "tempo": tempo,
                "mime_type": result.get('mime_type'),
                "size_bytes": result.get('size_bytes'),
                "song_id": result.get('song_id'),
                "provider": result.get('provider'),
                "model": result.get('model'),
                "output_format": result.get('output_format'),
                "requested_output_format": result.get('requested_output_format'),
                "requested_duration_seconds": (
                    result.get("requested_duration_ms", 0) // 1000
                    if result.get("requested_duration_ms") is not None
                    else None
                ),
                "generation_text": result.get("generation_text"),
                "synthid_watermarked": result.get("synthid_watermarked"),
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
