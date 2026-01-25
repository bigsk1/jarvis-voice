"""Memory API models"""

from pydantic import BaseModel, Field
from typing import Any
from enum import Enum


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

    class Config:
        json_schema_extra = {
            "example": {
                "category": "technical",
                "key": "jarvis_api_port",
                "value": "Jarvis API runs on port 8880",
                "importance": 7,
                "source": "user",
                "metadata": {"tags": ["api", "config"]}
            }
        }


class MemoryUpdate(BaseModel):
    """Request to update a memory"""
    value: str | None = Field(None, description="New value")
    importance: int | None = Field(None, ge=1, le=10, description="New importance level")
    
    class Config:
        json_schema_extra = {
            "example": {
                "value": "Jarvis API runs on port 8880 with Swagger docs at /docs",
                "importance": 8
            }
        }


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


class MemoryResponse(BaseModel):
    """Standard memory API response"""
    ok: bool
    message: str | None = None
    memory_id: int | None = None
    memory: Memory | None = None
    memories: list[Memory] | None = None
    count: int | None = None


class MemorySearchRequest(BaseModel):
    """Request for memory search"""
    query: str = Field(..., description="Search query")
    category: str | None = Field(None, description="Filter by category")
    limit: int = Field(10, ge=1, le=100, description="Maximum results")


class SemanticSearchRequest(BaseModel):
    """Request for semantic (AI-powered) search"""
    query: str = Field(..., description="Natural language question or concept")
    limit: int = Field(5, ge=1, le=50, description="Maximum results")
    similarity_threshold: float = Field(0.3, ge=0.0, le=1.0, description="Minimum similarity score (0-1)")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "Where is the Flask API project located?",
                "limit": 5,
                "similarity_threshold": 0.35
            }
        }
