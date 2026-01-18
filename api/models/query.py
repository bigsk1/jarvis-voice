"""Query/Chat API models"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class QueryRequest(BaseModel):
    """Request to query Jarvis"""
    query: str = Field(..., description="The question or command for Jarvis")
    mode: str = Field("cloud", description="LLM mode: 'cloud' or 'local'")
    session_id: Optional[str] = Field(None, description="Optional session ID for conversation continuity")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context to include")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "What's the weather like today?",
                "mode": "cloud",
                "session_id": "n8n-workflow-123"
            }
        }


class ToolUsed(BaseModel):
    """Information about a tool that was used"""
    name: str
    arguments: Optional[Dict[str, Any]] = None
    result_ok: bool = True


class QueryResponse(BaseModel):
    """Response from Jarvis query"""
    ok: bool
    speech: Optional[str] = Field(None, description="Spoken response (for TTS)")
    response: Optional[str] = Field(None, description="Full text response")
    tools_used: Optional[List[str]] = Field(None, description="List of tools that were called")
    session_id: Optional[str] = Field(None, description="Session ID for follow-up queries")
    error: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "ok": True,
                "speech": "The weather in Hillsboro is 45°F with partly cloudy skies.",
                "response": "The current weather in Hillsboro, OR is 45°F with partly cloudy skies and 65% humidity.",
                "tools_used": ["weather"],
                "session_id": "n8n-workflow-123"
            }
        }
