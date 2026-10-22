"""Bounded, channel-neutral notification requests."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NotificationCreate(BaseModel):
    """Save a notification; network delivery is handled asynchronously."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=2000)
    source: str = Field(default="manual", min_length=1, max_length=80)
    channels: list[Literal["ntfy"]] | None = Field(default=None, max_length=10)
    dedupe_key: str | None = Field(default=None, min_length=1, max_length=200)
    max_age_seconds: int = Field(default=3600, ge=60, le=86400)
    mode: Literal["cloud", "local"] | None = None
