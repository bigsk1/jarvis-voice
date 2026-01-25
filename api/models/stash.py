"""Stash API models"""

from pydantic import BaseModel


class StashFile(BaseModel):
    """A file within a stash space"""
    file_id: str
    name: str
    stored_name: str
    mime_type: str
    size_bytes: int
    hash_sha256: str | None = None
    tags: list[str] = []
    tool_origin: str | None = None
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
    last_used_at: str | None = None
    labels: list[str] = []
    owner: str = "jarvis"
    scope: str = "session"
    ttl_days: int = 7
    pinned: bool = False
    file_count: int = 0
    total_size_bytes: int = 0
    files: list[StashFile] | None = None


class StashResponse(BaseModel):
    """Response wrapper for stash endpoints"""
    ok: bool = True
    message: str | None = None
    space: StashSpace | None = None
    spaces: list[StashSpace] | None = None
    file: StashFile | None = None
    count: int | None = None
    total_size_bytes: int | None = None


class StashStats(BaseModel):
    """Stash statistics"""
    total_spaces: int
    total_files: int
    total_size_bytes: int
    total_size_human: str
    pinned_spaces: int
    by_label: dict
    by_tool: dict
    oldest_space: str | None = None
    newest_space: str | None = None
