"""
Pydantic models for Canvas API.
"""
from pydantic import BaseModel, Field


class CanvasPage(BaseModel):
    """Represents a canvas page."""
    page_id: str = Field(..., description="Unique page identifier")
    title: str = Field(..., description="Page title")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str | None = Field(None, description="Last update timestamp")
    tags: list[str] = Field(default_factory=list, description="Page tags")
    source_tool: str | None = Field(None, description="Tool that created the page")
    content_preview: str | None = Field(None, description="First 500 chars of content")
    content_length: int = Field(0, description="Total content length")
    embedded_images: list[str] = Field(default_factory=list, description="Stash refs of embedded images")
    

class CanvasPageFull(CanvasPage):
    """Canvas page with full content."""
    content: str = Field("", description="Full markdown content")


class CanvasPageResponse(BaseModel):
    """Response for single page request."""
    ok: bool = True
    page: CanvasPageFull | None = None
    error: str | None = None


class CanvasListResponse(BaseModel):
    """Response for page list request."""
    ok: bool = True
    pages: list[CanvasPage] = Field(default_factory=list)
    count: int = 0
    total: int = 0
    error: str | None = None


class CanvasStats(BaseModel):
    """Canvas statistics."""
    total_pages: int = 0
    total_size_bytes: int = 0
    total_size_human: str = "0 B"
    pages_with_images: int = 0
    by_tool: dict[str, int] = Field(default_factory=dict)
    by_tag: dict[str, int] = Field(default_factory=dict)
    oldest_page: str | None = None
    newest_page: str | None = None


class CanvasCreate(BaseModel):
    """Request to create a canvas page."""
    title: str = Field(..., description="Page title (can include folder path like 'Notes/2026-01-27/My Note')")
    content: str = Field(..., description="Markdown content")
    tags: list[str] = Field(default_factory=list, description="Optional tags")
    source_tool: str | None = Field(None, description="Tool/source that created this page")


class CanvasUpdate(BaseModel):
    """Request to update a canvas page."""
    title: str | None = Field(None, description="New title (optional)")
    content: str | None = Field(None, description="New content (optional)")
    tags: list[str] | None = Field(None, description="New tags (optional, replaces existing)")
    pinned: bool | None = Field(None, description="Pin status (optional)")
    allow_content_shrink: bool = Field(
        False,
        description="Allow an intentional replacement that removes most existing content",
    )


class CanvasAppend(BaseModel):
    """Request to append content while preserving the existing page."""
    content: str = Field(..., min_length=1, description="New Markdown section to append")
