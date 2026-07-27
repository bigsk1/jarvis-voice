"""Generate AI music and serve durable generated-music files.

Endpoints:
- POST /api/generated-music/generate     - Generate a new track
- GET  /api/generated-music/health       - Provider and storage status
- GET  /api/generated-music/{filename}   - Download or stream a generated track
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator


PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

from audio_catalog import AUDIO_EXTENSIONS  # noqa: E402
from config_loader import get_config_value, load_config  # noqa: E402
from generate_music import (  # noqa: E402
    DEFAULT_MUSIC_PROVIDER,
    OUTPUT_FORMATS,
    SUPPORTED_MUSIC_PROVIDERS,
    resolve_music_model,
)
from model_catalog import get_media_model_metadata  # noqa: E402


load_config()

router = APIRouter(prefix="/api/generated-music", tags=["generated-music"])

GENERATED_MUSIC_DIR = PROJECT_ROOT / "data" / "generated_music"
GENERATED_MUSIC_DIR.mkdir(parents=True, exist_ok=True)

PUBLIC_OUTPUT_FORMATS = tuple(
    name
    for name in OUTPUT_FORMATS
    if name.startswith(("mp3_", "opus_"))
)

MIME_TYPES = {
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".wav": "audio/wav",
}


class CompositionSection(BaseModel):
    """One section in an advanced composition plan."""

    section_name: str = Field(..., min_length=1, description="intro, verse, chorus, bridge, or outro")
    duration_seconds: int = Field(30, ge=3, le=120)
    styles: list[str] = Field(default_factory=list)
    avoid_styles: list[str] = Field(default_factory=list)
    lyrics: list[str] = Field(default_factory=list)


class CompositionPlan(BaseModel):
    """Structured song plan currently implemented by the ElevenLabs adapter."""

    global_styles: list[str] = Field(default_factory=list)
    sections: list[CompositionSection] = Field(..., min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_total_duration(self):
        total = sum(section.duration_seconds for section in self.sections)
        if total > 600:
            raise ValueError("composition plan duration cannot exceed 600 seconds")
        return self


class GenerateRequest(BaseModel):
    """Request to generate a new music track."""

    prompt: str = Field(
        ...,
        min_length=1,
        description="Describe original music without named artists, copyrighted songs or lyrics, or voice imitation.",
    )
    title: Optional[str] = Field(None, description="Display title and filename basis")
    duration_seconds: int = Field(
        60,
        ge=3,
        le=600,
        description="Requested track length. ElevenLabs supports 3-600 seconds; Lyria Clip is fixed at 30 seconds; Lyria Pro treats it as an approximate prompt target.",
    )
    genre: Optional[str] = Field(None, description="Genre such as ambient, pop, rock, cinematic, or lo-fi")
    mood: Optional[str] = Field(None, description="Emotional tone such as calm, energetic, dark, or hopeful")
    instrumental: bool = Field(False, description="Generate without vocals")
    tempo: Optional[str] = Field(None, description="slow, medium, fast, or a BPM value such as 120 BPM")
    output_format: str = Field(
        "mp3_medium",
        description="ElevenLabs accepts MP3 or Opus presets. The Gemini adapter returns MP3 only.",
    )
    composition_plan: Optional[CompositionPlan] = Field(
        None,
        description="Optional structured sections and lyrics; currently supported by ElevenLabs",
    )
    provider: Optional[str] = Field(
        None,
        description="Provider override: elevenlabs or gemini. Otherwise MUSIC_TOOL_PROVIDER is used.",
    )
    save: bool = Field(True, description="Save to data/generated_music and stash")
    mode: Literal["cloud", "local"] = Field("cloud", description="Configuration mode")

    @model_validator(mode="after")
    def validate_current_format(self):
        if self.output_format not in PUBLIC_OUTPUT_FORMATS:
            supported = ", ".join(PUBLIC_OUTPUT_FORMATS)
            raise ValueError(f"unsupported output_format; choose one of: {supported}")
        return self


class GenerateResponse(BaseModel):
    """Response from music generation."""

    ok: bool
    speech: Optional[str] = None
    error: Optional[str] = None
    data: Optional[dict] = None
    audio_url: Optional[str] = None


def _tool_output(stdout: str) -> dict | None:
    try:
        output = json.loads(stdout)
    except (TypeError, json.JSONDecodeError):
        return None
    return output if isinstance(output, dict) else None


def _generation_timeout(request: GenerateRequest) -> int:
    duration = request.duration_seconds
    if request.composition_plan:
        duration = sum(
            section.duration_seconds
            for section in request.composition_plan.sections
        )
    return max(600, duration * 3 + 60)


def _safe_audio_path(filename: str) -> Path:
    if (
        not isinstance(filename, str)
        or not filename
        or filename != Path(filename).name
        or ".." in filename
        or "/" in filename
        or "\\" in filename
        or Path(filename).suffix.lower() not in AUDIO_EXTENSIONS
    ):
        raise HTTPException(status_code=400, detail="Invalid audio filename")

    candidate = GENERATED_MUSIC_DIR / filename
    try:
        candidate.resolve(strict=True).relative_to(
            GENERATED_MUSIC_DIR.resolve(strict=True)
        )
    except (FileNotFoundError, OSError, ValueError):
        raise HTTPException(status_code=404, detail="Audio not found")
    if candidate.is_symlink() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Audio not found")
    return candidate


@router.get("/health")
async def generated_music_health():
    """Report generated-music storage and provider readiness."""
    configured_provider = str(
        get_config_value("MUSIC_TOOL_PROVIDER", DEFAULT_MUSIC_PROVIDER)
        or DEFAULT_MUSIC_PROVIDER
    ).strip().lower()
    audio_count = sum(
        1
        for path in GENERATED_MUSIC_DIR.iterdir()
        if (
            path.is_file()
            and not path.is_symlink()
            and path.suffix.lower() in AUDIO_EXTENSIONS
        )
    )
    credential_env = {
        "elevenlabs": "ELEVENLABS_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }.get(configured_provider)
    provider_supported = configured_provider in SUPPORTED_MUSIC_PROVIDERS
    configured_model = (
        resolve_music_model(configured_provider)
        if provider_supported
        else None
    )
    model_metadata = (
        get_media_model_metadata("music", configured_provider, configured_model)
        if configured_model
        else None
    )
    return {
        "ok": True,
        "directory": str(GENERATED_MUSIC_DIR),
        "exists": GENERATED_MUSIC_DIR.exists(),
        "audio_count": audio_count,
        "configured_provider": configured_provider,
        "configured_model": configured_model,
        "model_metadata": model_metadata,
        "provider_supported": provider_supported,
        "credential_configured": (
            bool(get_config_value(credential_env))
            if credential_env
            else False
        ),
        "supported_providers": list(SUPPORTED_MUSIC_PROVIDERS),
        "supported_output_formats": list(PUBLIC_OUTPUT_FORMATS),
    }


@router.post("/generate", response_model=GenerateResponse)
async def generate_music(request: GenerateRequest):
    """Generate music through the configured provider adapter."""
    args = {
        "prompt": request.prompt,
        "duration_seconds": request.duration_seconds,
        "instrumental": request.instrumental,
        "output_format": request.output_format,
        "save": request.save,
    }
    if request.title:
        args["title"] = request.title
    if request.genre:
        args["genre"] = request.genre
    if request.mood:
        args["mood"] = request.mood
    if request.tempo:
        args["tempo"] = request.tempo
    if request.composition_plan:
        args["composition_plan"] = request.composition_plan.model_dump()
    if request.provider:
        args["provider"] = request.provider

    env = os.environ.copy()
    env["JARVIS_MODE"] = request.mode
    tool_path = PROJECT_ROOT / "skills" / "generate_music.py"

    try:
        result = subprocess.run(
            [sys.executable, str(tool_path), json.dumps(args)],
            capture_output=True,
            text=True,
            timeout=_generation_timeout(request),
            cwd=str(PROJECT_ROOT),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return GenerateResponse(
            ok=False,
            error="Music generation timed out",
        )
    except Exception as exc:
        return GenerateResponse(ok=False, error=str(exc))

    output = _tool_output(result.stdout)
    if result.returncode != 0:
        return GenerateResponse(
            ok=False,
            speech=output.get("speech") if output else None,
            error=(
                output.get("error")
                if output
                else result.stderr.strip() or "Unknown music generation error"
            ),
            data=output.get("data") if output else None,
        )
    if output is None:
        return GenerateResponse(
            ok=False,
            error=f"Invalid tool output: {result.stdout[:200]}",
        )
    if not output.get("ok", False):
        return GenerateResponse(
            ok=False,
            speech=output.get("speech"),
            error=output.get("error"),
            data=output.get("data"),
        )

    data = output.get("data")
    filename = (
        ((data or {}).get("saved") or {}).get("filename")
        if isinstance(data, dict)
        else None
    )
    audio_url = f"/api/generated-music/{filename}" if filename else None
    return GenerateResponse(
        ok=True,
        speech=output.get("speech"),
        error=output.get("error"),
        data=data,
        audio_url=audio_url,
    )


@router.get("/{filename}")
async def get_generated_music(filename: str):
    """Stream or download one durable generated-music file."""
    filepath = _safe_audio_path(filename)
    return FileResponse(
        filepath,
        media_type=MIME_TYPES.get(filepath.suffix.lower(), "application/octet-stream"),
        filename=filename,
        content_disposition_type="inline",
    )
