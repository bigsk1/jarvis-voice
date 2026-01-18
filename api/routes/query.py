"""Query/Chat API endpoints - Send queries to Jarvis programmatically"""

from fastapi import APIRouter, HTTPException
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'lib'))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'orchestrator'))

from api.models.query import QueryRequest, QueryResponse, QuickQueryRequest

router = APIRouter(prefix="/api/query", tags=["query"])


@router.post("", response_model=QueryResponse)
@router.post("/", response_model=QueryResponse, include_in_schema=False)
async def query_jarvis(request: QueryRequest):
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
    try:
        # Load config for the requested mode
        from config_loader import load_config
        load_config(request.mode)
        
        # Set mode in environment for downstream components
        if request.mode == "local":
            os.environ['LLM_PROVIDER'] = 'ollama'
        else:
            # Keep existing provider for cloud mode
            pass
        
        # Import orchestrator after config is loaded
        from orchestrator_v2 import Orchestrator
        
        # Create orchestrator and process query
        orch = Orchestrator(request.mode)
        
        # Build conversation history if session context provided
        conversation_history = None
        if request.context and 'messages' in request.context:
            conversation_history = request.context['messages']
        
        result = orch.process(
            transcript=request.query,
            conversation_history=conversation_history
        )
        
        return QueryResponse(
            ok=result.get('ok', True),
            speech=result.get('speech'),
            response=result.get('speech'),  # Full response same as speech for now
            tools_used=result.get('tools_used', []),
            session_id=request.session_id,
            error=result.get('error')
        )
        
    except Exception as e:
        return QueryResponse(
            ok=False,
            error=str(e)
        )


@router.post("/quick", response_model=QueryResponse)
async def quick_query(request: QuickQueryRequest):
    """
    Quick query endpoint with minimal parameters (JSON body).
    
    Simpler than POST /query for basic use cases:
    ```bash
    curl -X POST http://localhost:8880/api/query/quick \\
      -H "Content-Type: application/json" \\
      -d '{"query": "What time is it?"}'
    ```
    """
    full_request = QueryRequest(query=request.query, mode=request.mode)
    return await query_jarvis(full_request)


@router.get("/quick")
async def quick_query_get(
    q: str,
    mode: str = "cloud"
):
    """
    Quick query via GET (for easy browser/webhook testing).
    
    ```
    http://localhost:8880/api/query/quick?q=What's the weather?
    ```
    
    **Warning**: GET requests may be logged in server logs.
    Use POST for sensitive queries.
    """
    request = QueryRequest(query=q, mode=mode)
    return await query_jarvis(request)
