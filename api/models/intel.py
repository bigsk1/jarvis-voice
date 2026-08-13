"""Intel API models - CRUD operations for jarvis-intel/ files"""

from pydantic import BaseModel, ConfigDict, Field


class IntelFile(BaseModel):
    """An intel file in jarvis-intel/"""
    filename: str
    size_bytes: int
    modified_at: str
    ingested: bool = False
    fact_count: int | None = None
    
    model_config = ConfigDict(json_schema_extra={
            "example": {
                "filename": "network-config.md",
                "size_bytes": 1234,
                "modified_at": "2026-01-25T10:30:00",
                "ingested": True,
                "fact_count": 15
            }
        })


class IntelCreate(BaseModel):
    """Create a new intel file"""
    filename: str = Field(..., description="Lowercase kebab-case filename (e.g., 'my-notes.md'). Must end in .md or .txt")
    content: str = Field(..., description="File content (markdown or plain text)")
    auto_ingest: bool = Field(False, description="If true, trigger ingestion after creating")
    
    model_config = ConfigDict(json_schema_extra={
            "example": {
                "filename": "xai-collections.md",
                "content": "# xAI Collections API\n\n## Key Concepts\n- Collection: Group of files with embeddings\n- File: Single uploaded document\n\n## Important Facts\n- Max file size: 100MB\n- Max files: 100,000",
                "auto_ingest": True
            }
        })


class IntelUpdate(BaseModel):
    """Update an existing intel file"""
    content: str = Field(..., description="New file content")
    auto_ingest: bool = Field(False, description="If true, re-ingest after updating")


class IntelResponse(BaseModel):
    """Response wrapper for intel endpoints"""
    ok: bool = True
    message: str | None = None
    file: IntelFile | None = None
    files: list[IntelFile] | None = None
    content: str | None = None
    count: int | None = None
    ingestion_started: bool = False
    ingest_modes: list[str] | None = None
    ingest_warning: str | None = None


class IntelStats(BaseModel):
    """Intel folder statistics"""
    total_files: int
    total_size_bytes: int
    total_size_human: str
    total_facts_ingested: int
    files_pending_ingest: int
    newest_file: str | None = None
    oldest_file: str | None = None


class IngestResult(BaseModel):
    """Result of ingestion operation"""
    ok: bool = True
    new_files: int = 0
    skipped_files: int = 0
    total_facts: int = 0
    processed_files: list[str] = Field(default_factory=list)
    async_started: bool = False
    modes: list[str] = Field(default_factory=list)
    skipped_modes: list[str] = Field(default_factory=list)
    partial: bool = False
    warning: str | None = None
