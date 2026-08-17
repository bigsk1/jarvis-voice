"""Memory API models."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MemoryCategory(str, Enum):
    """Common memory categories"""
    personal = "personal"
    technical = "technical"
    contact = "contact"
    preference = "preference"
    project = "project"
    fact = "fact"
    location = "location"
    other = "other"


class MemoryCreate(BaseModel):
    """Request to create a memory"""
    category: str = Field(..., description="Memory category (personal, technical, contact, preference, project, fact, location, other)")
    key: str = Field(..., description="What this memory is about (identifier)")
    value: str = Field(..., description="The information to remember")
    importance: int = Field(5, ge=1, le=10, description="Importance level 1-10 (higher = more important)")
    source: str | None = Field(None, description="Where this information came from")
    metadata: dict[str, Any] | None = Field(None, description="Additional metadata (tags, expiration, etc.)")
    generate_embedding: bool = Field(True, description="Generate vector embedding for semantic search")

    model_config = ConfigDict(json_schema_extra={
            "example": {
                "category": "technical",
                "key": "jarvis_api_port",
                "value": "Jarvis API runs on port 8880",
                "importance": 7,
                "source": "user",
                "metadata": {"tags": ["api", "config"]}
            }
        })


class MemoryUpdate(BaseModel):
    """Request to update a memory"""
    value: str | None = Field(None, description="New value")
    importance: int | None = Field(None, ge=1, le=10, description="New importance level")
    
    model_config = ConfigDict(json_schema_extra={
            "example": {
                "value": "Jarvis API runs on port 8880 with Swagger docs at /docs",
                "importance": 8
            }
        })


class Memory(BaseModel):
    """A memory record"""
    id: int
    category: str
    key: str
    value: str
    importance: int
    created_at: str | None = None
    updated_at: str | None = None
    source: str | None = None
    metadata: dict[str, Any] | None = None
    relevance: float | None = Field(None, description="Search relevance score (if from search)")
    similarity: float | None = Field(None, description="Semantic similarity score (if from semantic search)")
    retrieval_score: float | None = Field(
        None,
        description="Final normalized score used to rank a hybrid search result",
    )
    hybrid_score: float | None = Field(
        None,
        description="Combined dense and keyword score used by hybrid retrieval",
    )
    rrf_score: float | None = Field(
        None,
        description="Reciprocal-rank-fusion diagnostic score",
    )
    retrieval_channels: list[str] | None = Field(
        None,
        description="Evidence channels contributing to this result",
    )
    keyword_match_mode: str | None = Field(
        None,
        description="How keyword evidence was admitted: precise, dense_support, or fallback",
    )


class MemoryRetrievalMetadata(BaseModel):
    """Diagnostics for one semantic/hybrid memory search."""

    retrieval_mode: str
    semantic_disabled_reason: str | None = None
    similarity_threshold: float | None = None
    dense_candidate_count: int | None = None
    keyword_candidate_count: int | None = None
    keyword_precise_candidate_count: int | None = None
    keyword_admitted_count: int | None = None
    fused_candidate_count: int | None = None


class MemoryResponse(BaseModel):
    """Standard memory API response"""
    ok: bool
    message: str | None = None
    memory_id: int | None = None
    memory: Memory | None = None
    memories: list[Memory] | None = None
    count: int | None = None


class MemorySearchResponse(MemoryResponse):
    """Memory response with diagnostics from semantic/hybrid retrieval."""

    retrieval: MemoryRetrievalMetadata


class MemoryCategoriesResponse(BaseModel):
    """Memory category names and their record counts."""
    ok: bool
    message: str
    categories: dict[str, int]
    count: int


class MemorySearchRequest(BaseModel):
    """Request for memory search"""
    query: str = Field(..., description="Search query")
    category: str | None = Field(None, description="Filter by category")
    limit: int = Field(10, ge=1, le=100, description="Maximum results")


class SemanticSearchRequest(BaseModel):
    """Request for hybrid semantic and keyword search."""
    query: str = Field(..., description="Natural language question or concept")
    limit: int = Field(5, ge=1, le=50, description="Maximum results")
    similarity_threshold: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum dense similarity score (0-1); omit to use "
            "SEMANTIC_SIMILARITY_THRESHOLD for the active mode"
        ),
    )

    model_config = ConfigDict(json_schema_extra={
            "example": {
                "query": "Where is the Flask API project located?",
                "limit": 5,
                "similarity_threshold": 0.35
            }
        })
