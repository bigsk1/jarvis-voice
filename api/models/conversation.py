"""Conversation API models"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime


class Conversation(BaseModel):
    """A single conversation record"""
    id: int
    timestamp: str
    session_id: Optional[str] = None
    user_query: str
    jarvis_response: Optional[str] = None
    tools_used: Optional[List[str]] = None
    success: bool = True
    metadata: Optional[dict] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": 858,
                "timestamp": "2026-01-18 02:00:16",
                "session_id": "20260117_180010",
                "user_query": "What time is it?",
                "jarvis_response": "It's 6:00 PM on Saturday, January 17, 2026.",
                "tools_used": ["get_time"],
                "success": True,
                "metadata": None
            }
        }


class ConversationResponse(BaseModel):
    """Response wrapper for conversation endpoints"""
    ok: bool = True
    message: Optional[str] = None
    conversation: Optional[Conversation] = None
    conversations: Optional[List[Conversation]] = None
    count: Optional[int] = None
    total: Optional[int] = None
    page: Optional[int] = None
    pages: Optional[int] = None


class ConversationStats(BaseModel):
    """Conversation statistics"""
    total_conversations: int
    total_today: int
    total_this_week: int
    success_rate: float
    top_tools: dict
    database: str
