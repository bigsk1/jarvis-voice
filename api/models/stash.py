"""Stash API models"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class StashFile(BaseModel):
    """A file within a stash space"""
    file_id: str
    name: str
    stored_name: str
    mime_type: str
    size_bytes: int
    hash_sha256: Optional[str] = None
    tags: List[str] = []
    tool_origin: Optional[str] = None
    created_at: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "file_id": "f_5d190ce797c6",
                "name": "generated_image.jpg",
                "stored_name": "generated_image.jpg",
                "mime_type": "image/jpeg",
                "size_bytes": 2314172,
                "tags": ["ai_generated", "gemini"],
                "tool_origin": "generate_image",
                "created_at": "2026-01-18T00:54:00.291003Z"
            }
        }


class StashSpace(BaseModel):
    """A stash space containing files"""
    space_id: str
    created_at: str
    last_used_at: Optional[str] = None
    labels: List[str] = []
    owner: str = "jarvis"
    scope: str = "session"
    ttl_days: int = 7
    pinned: bool = False
    file_count: int = 0
    total_size_bytes: int = 0
    files: Optional[List[StashFile]] = None


class StashResponse(BaseModel):
    """Response wrapper for stash endpoints"""
    ok: bool = True
    message: Optional[str] = None
    space: Optional[StashSpace] = None
    spaces: Optional[List[StashSpace]] = None
    file: Optional[StashFile] = None
    count: Optional[int] = None
    total_size_bytes: Optional[int] = None


class StashStats(BaseModel):
    """Stash statistics"""
    total_spaces: int
    total_files: int
    total_size_bytes: int
    total_size_human: str
    pinned_spaces: int
    by_label: dict
    by_tool: dict
    oldest_space: Optional[str] = None
    newest_space: Optional[str] = None
