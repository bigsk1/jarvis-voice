"""Conversation API models"""

from pydantic import BaseModel, ConfigDict


class Conversation(BaseModel):
    """A single conversation record"""
    id: int
    timestamp: str
    session_id: str | None = None
    user_query: str
    jarvis_response: str | None = None
    tools_used: list[str] | None = None
    success: bool = True
    metadata: dict | None = None
    
    model_config = ConfigDict(json_schema_extra={
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
        })


class ConversationResponse(BaseModel):
    """Response wrapper for conversation endpoints"""
    ok: bool = True
    message: str | None = None
    conversation: Conversation | None = None
    conversations: list[Conversation] | None = None
    count: int | None = None
    total: int | None = None
    page: int | None = None
    pages: int | None = None


class ConversationStats(BaseModel):
    """Conversation statistics"""
    total_conversations: int
    total_today: int
    total_this_week: int
    success_rate: float
    top_tools: dict
    database: str
