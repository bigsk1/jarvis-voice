"""Voice/TTS endpoints"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import subprocess
import sys
from pathlib import Path

router = APIRouter(prefix="/api/voice", tags=["voice"])

project_root = Path(__file__).parent.parent.parent

class SpeakRequest(BaseModel):
    """Request to speak a message"""
    message: str
    mode: str = "cloud"  # cloud or local

@router.post("/speak")
async def speak(request: SpeakRequest):
    """
    Proactively speak a message via TTS
    
    Use this for urgent notifications or reminders
    """
    try:
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
        
        # Execute TTS
        result = subprocess.run(
            [str(say_script), request.message],
            capture_output=True,
            text=True,
            timeout=30
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
            "text": request.message
        }
        
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="TTS timeout")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

