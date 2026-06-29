"""Voice/TTS endpoints"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import subprocess
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'lib'))
from tts_normalizer import normalize_tts_text, validate_tts_profile

router = APIRouter(prefix="/api/voice", tags=["voice"])

project_root = Path(__file__).parent.parent.parent

class SpeakRequest(BaseModel):
    """Request to speak a message"""
    message: str
    mode: str = "cloud"  # cloud or local
    tts_provider: Optional[str] = None  # Override: openai, elevenlabs, xai, qwen3-tts, kokoro
    voice: Optional[str] = None  # Override voice for the provider
    profile: Optional[str] = None  # Optional named TTS normalization profile

@router.post("/speak")
async def speak(request: SpeakRequest):
    """
    Proactively speak a message via TTS
    
    Use this for urgent notifications or reminders.
    
    Optional overrides allow different voices/providers per request:
    - tts_provider: openai, elevenlabs, xai, qwen3-tts, kokoro
    - voice: Provider-specific voice name (e.g., "Samantha" for qwen3-tts)
    
    Example for Samantha's voice:
    ```json
    {
      "message": "Hello from Samantha!",
      "mode": "cloud",
      "tts_provider": "qwen3-tts",
      "voice": "Samantha"
    }
    ```
    """
    try:
        try:
            validated_profile = validate_tts_profile(request.profile)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        env = os.environ.copy()
        provider_used = request.tts_provider or env.get('TTS_PROVIDER', 'elevenlabs')
        preserve_xai_tags = provider_used == 'xai'
        spoken_message = normalize_tts_text(
            request.message,
            profile=validated_profile,
            preserve_xai_tags=preserve_xai_tags,
        )
        if not spoken_message:
            raise HTTPException(status_code=400, detail="Message was empty after TTS normalization")

        # Select appropriate TTS script
        if request.mode == "local":
            say_script = project_root / 'bin' / 'say-local.sh'
        else:
            say_script = project_root / 'bin' / 'say.sh'
        
        if not say_script.exists():
            raise HTTPException(
                status_code=500,
                detail=f"TTS script not found: {say_script}"
            )
        
        # Build environment with optional overrides
        # Use *_OVERRIDE env vars so they take precedence AFTER config is loaded
        voice_used = None
        
        if request.tts_provider:
            env['TTS_PROVIDER_OVERRIDE'] = request.tts_provider
            provider_used = request.tts_provider
        
        if request.voice:
            # Set the appropriate voice override env var based on provider
            provider = request.tts_provider or env.get('TTS_PROVIDER', 'elevenlabs')
            if provider == 'qwen3-tts':
                env['QWEN3_TTS_VOICE_OVERRIDE'] = request.voice
            elif provider == 'elevenlabs':
                env['ELEVENLABS_TTS_VOICE_OVERRIDE'] = request.voice
            elif provider == 'openai':
                env['OPENAI_VOICE_OVERRIDE'] = request.voice
            elif provider == 'xai':
                env['XAI_TTS_VOICE_OVERRIDE'] = request.voice
            elif provider == 'kokoro':
                env['KOKORO_TTS_VOICE_OVERRIDE'] = request.voice
            voice_used = request.voice
        
        # Execute TTS with (possibly overridden) environment
        result = subprocess.run(
            [str(say_script), spoken_message],
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )
        
        if result.returncode != 0:
            return {
                "ok": False,
                "message": "TTS execution failed",
                "error": result.stderr
            }
        
        return {
            "ok": True,
            "message": "Spoken successfully",
            "text": spoken_message,
            "provider": provider_used,
            "voice": voice_used,
            "profile": validated_profile,
        }
        
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="TTS timeout")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class AnnounceRequest(BaseModel):
    """Simple announce request"""
    message: str


@router.post("/announce")
async def announce(request: AnnounceRequest):
    """
    Simple announce endpoint
    
    This is a simpler version of /speak that:
    - Auto-detects mode from environment
    - Only requires 'message' field
    - Easier for external integrations (Home Assistant, IFTTT, n8n)
    
    Example:
    ```bash
    curl -X POST http://localhost:8880/api/voice/announce \\
      -H "Content-Type: application/json" \\
      -d '{"message": "Package delivered at front door"}'
    ```
    
    For full control (cloud/local mode), use /speak instead.
    """
    from config_loader import get_active_config_mode

    # Resolve mode from launcher-provided JARVIS_MODE, never the provider.
    mode = get_active_config_mode()
    
    # Use existing speak() function
    speak_req = SpeakRequest(message=request.message, mode=mode)
    return await speak(speak_req)
