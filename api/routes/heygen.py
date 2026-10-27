"""Optional HeyGen catalogs, submit-once avatar generation and job recovery."""

from typing import Literal

from config_loader import config_scope
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from skills.generate_avatar_video import run as run_avatar
from skills.heygen import run as run_heygen

router = APIRouter(prefix="/api/heygen", tags=["heygen"])
Mode = Literal["cloud", "local"]
Kind = Literal["model", "avatar"]


class AvatarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    script: str | None = Field(None, min_length=1, max_length=1000)
    avatar_id: str | None = None
    image_source: str | None = None
    voice_id: str | None = None
    audio_source: str | None = None
    title: str = Field("", max_length=200)
    aspect_ratio: Literal["16:9", "9:16", "1:1", "auto"] = "16:9"
    resolution: Literal["720p", "1080p"] = "720p"
    mode: Mode = "cloud"


class CollectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,160}$")
    kind: Kind = "model"
    mode: Mode = "cloud"


def _run_in_mode(mode: str, arguments: dict, *, avatar: bool = False) -> dict:
    with config_scope(mode):
        return run_avatar(arguments, submit_only=True) if avatar else run_heygen(arguments)


@router.post("/avatar")
async def submit_avatar(request: AvatarRequest):
    """Submit one paid Avatar IV job; return its receipt without waiting or retrying."""
    result = await run_in_threadpool(
        _run_in_mode, request.mode, request.model_dump(exclude={"mode"}, exclude_none=True), avatar=True,
    )
    return JSONResponse(result, status_code=202 if result.get("ok") else 200)


@router.get("/account")
async def account(mode: Mode = "cloud"):
    return await run_in_threadpool(_run_in_mode, mode, {"action": "account"})


@router.get("/avatars")
async def avatars(mode: Mode = "cloud", limit: int = Query(20, ge=1, le=50), cursor: str | None = None):
    """List avatar looks; their IDs are the avatar_id used for video generation."""
    return await run_in_threadpool(_run_in_mode, mode, {"action": "list_avatars", "limit": limit, "cursor": cursor})


@router.get("/voices")
async def voices(mode: Mode = "cloud", limit: int = Query(20, ge=1, le=50), cursor: str | None = None):
    return await run_in_threadpool(_run_in_mode, mode, {"action": "list_voices", "limit": limit, "cursor": cursor})


@router.get("/status/{video_id}")
async def status(video_id: str, kind: Kind = "model", mode: Mode = "cloud"):
    return await run_in_threadpool(_run_in_mode, mode, {"action": "status", "video_id": video_id, "kind": kind})


@router.post("/collect")
async def collect(request: CollectRequest):
    """Observe and save an existing completed job; never submit replacement work."""
    return await run_in_threadpool(
        _run_in_mode, request.mode, {"action": "collect", "video_id": request.video_id, "kind": request.kind},
    )
