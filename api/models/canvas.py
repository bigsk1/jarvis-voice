"""
Pydantic models for Canvas API.
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class CanvasPage(BaseModel):
    """Represents a canvas page."""
    page_id: str = Field(..., description="Unique page identifier")
    title: str = Field(..., description="Page title")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")
    tags: List[str] = Field(default_factory=list, description="Page tags")
    source_tool: Optional[str] = Field(None, description="Tool that created the page")
    content_preview: Optional[str] = Field(None, description="First 500 chars of content")
    content_length: int = Field(0, description="Total content length")
    embedded_images: List[str] = Field(default_factory=list, description="Stash refs of embedded images")
    

class CanvasPageFull(CanvasPage):
    """Canvas page with full content."""
    content: str = Field("", description="Full markdown content")


class CanvasPageResponse(BaseModel):
    """Response for single page request."""
    ok: bool = True
    page: Optional[CanvasPageFull] = None
    error: Optional[str] = None


class CanvasListResponse(BaseModel):
    """Response for page list request."""
    ok: bool = True
    pages: List[CanvasPage] = Field(default_factory=list)
    count: int = 0
    total: int = 0
    error: Optional[str] = None


class CanvasStats(BaseModel):
    """Canvas statistics."""
    total_pages: int = 0
    total_size_bytes: int = 0
    total_size_human: str = "0 B"
    pages_with_images: int = 0
    by_tool: Dict[str, int] = Field(default_factory=dict)
    by_tag: Dict[str, int] = Field(default_factory=dict)
    oldest_page: Optional[str] = None
    newest_page: Optional[str] = None
