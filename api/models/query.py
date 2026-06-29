"""Query/Chat API models"""

from pydantic import BaseModel, Field
from typing import Any, Literal


class QueryRequest(BaseModel):
    """Request to query Jarvis"""
    query: str = Field(..., description="The question or command for Jarvis")
    mode: Literal["cloud", "local"] = Field("cloud", description="LLM mode: 'cloud' or 'local'")
    session_id: str | None = Field(None, description="Optional session ID for conversation continuity")
    context: dict[str, Any] | None = Field(None, description="Additional context to include")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "What's the weather like today?",
                "mode": "cloud",
                "session_id": "n8n-workflow-123"
            }
        }


class QuickQueryRequest(BaseModel):
    """Simple query request for /quick endpoint"""
    query: str = Field(..., description="The question or command")
    mode: Literal["cloud", "local"] = Field("cloud", description="LLM mode: 'cloud' or 'local'")
    
    class Config:
        json_schema_extra = {
            "example": {
                "query": "What time is it?",
                "mode": "cloud"
            }
        }


class ToolUsed(BaseModel):
    """Information about a tool that was used"""
    name: str
    arguments: dict[str, Any] | None = None
    result_ok: bool = True


class QueryResponse(BaseModel):
    """Response from Jarvis query"""
    ok: bool
    speech: str | None = Field(None, description="Spoken response (for TTS)")
    response: str | None = Field(None, description="Full text response")
    tools_used: list[str] | None = Field(None, description="List of tools that were called")
    session_id: str | None = Field(None, description="Session ID for follow-up queries")
    error: str | None = None
    
    # Extended fields (all optional for backwards compatibility)
    data: dict[str, Any] | None = Field(None, description="Accumulated data from tool results")
    usage: dict[str, Any] | None = Field(None, description="Token usage and cost info")
    server_side_tools: dict[str, int] | None = Field(None, description="LLM provider native tools (xAI web_search, x_search, etc.)")
    thinking: str | None = Field(None, description="LLM reasoning/thinking (if enabled)")
    raw_llm_response: str | None = Field(None, description="Original LLM response before voice formatting")
    experience_id: int | None = Field(None, description="Experience ID for feedback linking")
    available_tools: list[str] | None = Field(None, description="Tools the LLM could choose from")
    feedback: dict[str, Any] | None = Field(None, description="Self-critique feedback (if collected)")
    cancelled: bool | None = Field(None, description="True if user stopped processing")
    max_turns_reached: bool | None = Field(None, description="True if hit max turns limit")
    workflow_executed: str | None = Field(None, description="Workflow ID if a workflow was triggered")
    
    class Config:
        json_schema_extra = {
            "example": {
                "ok": True,
                "speech": "The weather in Hillsboro is 45°F with partly cloudy skies.",
                "response": "The current weather in Hillsboro, OR is 45°F with partly cloudy skies and 65% humidity.",
                "tools_used": ["weather"],
                "session_id": "n8n-workflow-123",
                "data": {"temperature": "45°F", "conditions": "partly cloudy"},
                "usage": {"input_tokens": 1500, "output_tokens": 200, "cost_usd": 0.0023},
                "server_side_tools": {"SERVER_SIDE_TOOL_WEB_SEARCH": 1}
            }
        }
