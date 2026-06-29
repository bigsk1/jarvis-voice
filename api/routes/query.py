"""Query/Chat API endpoints - Send queries to Jarvis programmatically"""

from fastapi import APIRouter, Request
import sys
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'lib'))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'orchestrator'))

from api.models.query import QueryRequest, QueryResponse, QuickQueryRequest

router = APIRouter(prefix="/api/query", tags=["query"])

# Rate limiting: lib.rate_limiter.APIRateLimitMiddleware (query bucket / QUERY_RATE_LIMIT_PER_MINUTE)


@router.post("", response_model=QueryResponse)
@router.post("/", response_model=QueryResponse, include_in_schema=False)
async def query_jarvis(request: Request, body: QueryRequest):
    """
    Send a query to Jarvis and get a response.
    
    This is the core API for programmatic interaction with Jarvis.
    Perfect for:
    - n8n workflows that need Jarvis intelligence
    - Scripts that need natural language processing
    - External integrations (HomeAssistant, IFTTT, etc.)
    - Custom applications
    
    **Mode options**:
    - `cloud`: Uses cloud LLMs (xAI, Anthropic, OpenAI) - faster, smarter
    - `local`: Uses Ollama - private, offline capable
    
    **Example n8n workflow**:
    ```json
    {
      "query": "What's the status of my server monitoring?",
      "mode": "cloud",
      "session_id": "n8n-daily-check"
    }
    ```
    
    **Note**: Long-running queries may take 10-60+ seconds depending on tools used.
    """
    from config_loader import config_scope
    with config_scope(body.mode):
        return await _query_jarvis_scoped(body)


async def _query_jarvis_scoped(body: QueryRequest):
    """Execute one API query inside its immutable mode/config scope."""
    try:
        # Import orchestrator after config is loaded
        from orchestrator_v2 import Orchestrator
        
        # Create orchestrator and process query
        orch = Orchestrator(body.mode)
        
        # Build conversation history if session context provided
        conversation_history = None
        if body.context and 'messages' in body.context:
            conversation_history = body.context['messages']
        
        result = orch.process(
            transcript=body.query,
            conversation_history=conversation_history
        )
        
        return QueryResponse(
            ok=result.get('ok', True),
            speech=result.get('speech'),
            response=result.get('raw_llm_response') or result.get('speech'),  # Raw response or speech
            tools_used=result.get('tools_used', []),
            session_id=body.session_id,
            error=result.get('error'),
            # Extended fields
            data=result.get('data'),
            usage=result.get('usage'),
            server_side_tools=result.get('server_side_tools'),
            thinking=result.get('thinking'),
            raw_llm_response=result.get('raw_llm_response'),
            experience_id=result.get('experience_id'),
            available_tools=result.get('available_tools'),
            feedback=result.get('feedback'),
            cancelled=result.get('cancelled'),
            max_turns_reached=result.get('max_turns_reached'),
            workflow_executed=result.get('workflow_executed')
        )
        
    except Exception as e:
        return QueryResponse(
            ok=False,
            error=str(e)
        )


@router.post("/quick", response_model=QueryResponse)
async def quick_query(http_request: Request, body: QuickQueryRequest):
    """
    Quick query endpoint with minimal parameters (JSON body).
    
    Simpler than POST /query for basic use cases:
    ```bash
    curl -X POST http://localhost:8880/api/query/quick \\
      -H "Content-Type: application/json" \\
      -d '{"query": "What time is it?"}'
    ```
    """
    full_request = QueryRequest(query=body.query, mode=body.mode)
    return await query_jarvis(http_request, full_request)


@router.get("/quick")
async def quick_query_get(
    http_request: Request,
    q: str,
    mode: Literal["cloud", "local"] = "cloud"
):
    """
    Quick query via GET (for easy browser/webhook testing).
    
    ```
    http://localhost:8880/api/query/quick?q=What's the weather?
    ```
    
    **Warning**: GET requests may be logged in server logs.
    Use POST for sensitive queries.
    """
    body = QueryRequest(query=q, mode=mode)
    return await query_jarvis(http_request, body)
