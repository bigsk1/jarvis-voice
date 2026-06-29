"""Workflow API models"""

from pydantic import BaseModel, Field
from typing import Any, Literal


class WorkflowInfo(BaseModel):
    """Basic workflow information"""
    id: str = Field(..., description="Workflow ID (e.g., 'crypto_market_report')")
    name: str = Field(..., description="Human-readable name")
    description: str | None = Field(None, description="What this workflow does")
    trigger: str = Field(..., description="Primary command trigger (e.g., '/crypto')")
    triggers: list[str] = Field(default_factory=list, description="All command triggers (e.g., ['/crypto', '/crypto-report'])")
    requires_input: bool = Field(False, description="Whether workflow requires a query/topic parameter")
    version: str | None = Field(None, description="Workflow version")
    tools_used: list[str] = Field(default_factory=list, description="Tools used by this workflow")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "crypto_market_report",
                "name": "Crypto Market Report Workflow",
                "description": "Get crypto prices, search news, analyze market, email report",
                "trigger": "/crypto",
                "triggers": ["/crypto"],
                "requires_input": False,
                "version": "1.1",
                "tools_used": ["crypto_price", "mcp_brave_search_brave_web_search", "canvas", "send_email"]
            }
        }


class WorkflowExecuteRequest(BaseModel):
    """Request to execute a workflow"""
    query: str | None = Field(None, description="Optional query/parameters (e.g., 'ethereum xrp' for /crypto)")
    mode: Literal["cloud", "local"] = Field("cloud", description="LLM mode: 'cloud' or 'local'")
    
    class Config:
        json_schema_extra = {
            "example": {
                "query": "ethereum solana",
                "mode": "cloud"
            }
        }


class WorkflowExecuteResponse(BaseModel):
    """Response from workflow execution"""
    ok: bool
    workflow_id: str
    speech: str | None = Field(None, description="Final speech response")
    tools_used: list[str] = Field(default_factory=list, description="Tools that were executed")
    steps_completed: int = Field(0, description="Number of steps completed")
    duration_ms: float | None = Field(None, description="Execution time in milliseconds")
    data: dict[str, Any] | None = Field(None, description="Accumulated data from steps")
    usage: dict[str, Any] | None = Field(None, description="LLM token usage from workflow")
    server_side_tools: dict[str, int] | None = Field(None, description="LLM provider native tools used (xAI web_search, x_search, etc.)")
    error: str | None = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "ok": True,
                "workflow_id": "crypto_market_report",
                "speech": "Crypto market report complete. Bitcoin is at 89651 dollars.",
                "tools_used": ["get_time", "crypto_price", "mcp_brave_search_brave_web_search", "canvas", "send_email"],
                "steps_completed": 9,
                "duration_ms": 45230.5,
                "data": {"coin1_price": "89651", "coin1_change": "2.05"},
                "server_side_tools": {"SERVER_SIDE_TOOL_X_SEARCH": 2, "SERVER_SIDE_TOOL_WEB_SEARCH": 1}
            }
        }


class WorkflowExecution(BaseModel):
    """Historical workflow execution record"""
    timestamp: str
    workflow_id: str
    workflow_name: str | None = None
    user_query: str | None = None
    ok: bool
    speech: str | None = None
    steps_completed: int = 0
    tools_used: list[str] = Field(default_factory=list)
    duration_ms: float = 0
    
    class Config:
        json_schema_extra = {
            "example": {
                "timestamp": "2026-01-22T10:25:42.235173",
                "workflow_id": "crypto_market_report",
                "workflow_name": "Crypto Market Report Workflow",
                "user_query": "/crypto ethereum xrp",
                "ok": True,
                "speech": "Crypto market report complete.",
                "steps_completed": 9,
                "tools_used": ["crypto_price", "canvas", "send_email"],
                "duration_ms": 56353.52
            }
        }


class WorkflowListResponse(BaseModel):
    """List of available workflows"""
    workflows: list[WorkflowInfo]
    count: int


class WorkflowHistoryResponse(BaseModel):
    """Workflow execution history"""
    executions: list[WorkflowExecution]
    count: int
    success_count: int
    failure_count: int
