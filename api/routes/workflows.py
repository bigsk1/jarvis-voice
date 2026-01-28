"""Workflow API endpoints - Execute predefined multi-tool workflows"""

from fastapi import APIRouter, HTTPException
import sys
import os
import json
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'lib'))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'orchestrator'))

from api.models.workflows import (
    WorkflowInfo,
    WorkflowExecuteRequest,
    WorkflowExecuteResponse,
    WorkflowExecution,
    WorkflowListResponse,
    WorkflowHistoryResponse
)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


def get_workflow_logs(limit: int = 20, workflow_id: str | None = None, days: int = 7) -> list:
    """Get recent workflow execution logs from JSONL files."""
    logs_dir = Path(__file__).parent.parent.parent / "logs"
    workflow_logs = []
    
    cutoff_date = datetime.now() - timedelta(days=days)
    
    for log_file in sorted(logs_dir.glob("workflows-*.jsonl"), reverse=True):
        try:
            date_str = log_file.stem.replace("workflows-", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date < cutoff_date:
                continue
        except ValueError:
            continue
        
        try:
            with open(log_file, 'r') as f:
                for line in f:
                    if line.strip():
                        try:
                            entry = json.loads(line)
                            if workflow_id and entry.get('workflow_id') != workflow_id:
                                continue
                            workflow_logs.append(entry)
                        except json.JSONDecodeError:
                            continue
        except IOError:
            continue
    
    workflow_logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return workflow_logs[:limit]


@router.get("", response_model=WorkflowListResponse)
@router.get("/", response_model=WorkflowListResponse, include_in_schema=False)
async def list_workflows():
    """
    List all available workflows.
    
    Workflows are predefined multi-tool pipelines triggered by commands like `/crypto`, `/research`.
    They execute deterministically without LLM routing decisions.
    
    **Use cases**:
    - Discover available automation workflows
    - Get workflow IDs for execution
    - See what tools each workflow uses
    """
    try:
        from workflow_loader import WorkflowLoader
        
        WorkflowLoader(explicit_only=True)
        workflows_dir = Path(__file__).parent.parent.parent / "data" / "workflows"
        
        workflows = []
        for wf_file in workflows_dir.glob("*.json"):
            if wf_file.name.startswith("_") or wf_file.name == "AGENTS.md":
                continue
            try:
                with open(wf_file, 'r') as f:
                    wf = json.load(f)
                
                # Extract tools used from steps
                tools_used = []
                for step in wf.get("steps", []):
                    tool = step.get("tool")
                    if tool and tool not in tools_used:
                        tools_used.append(tool)
                
                # Get explicit triggers
                explicit_triggers = wf.get("triggers", {}).get("explicit", [])
                primary_trigger = explicit_triggers[0] if explicit_triggers else f"/{wf_file.stem}"
                
                # Check if workflow requires input (has main_subject extraction)
                variables = wf.get("variables", {})
                requires_input = any(
                    isinstance(v, dict) and v.get("extract") == "main_subject"
                    for v in variables.values()
                )
                
                workflows.append(WorkflowInfo(
                    id=wf.get("id", wf_file.stem),
                    name=wf.get("name", wf_file.stem),
                    description=wf.get("description"),
                    trigger=primary_trigger,
                    triggers=explicit_triggers if explicit_triggers else [f"/{wf_file.stem}"],
                    requires_input=requires_input,
                    version=wf.get("version"),
                    tools_used=tools_used
                ))
            except Exception:
                continue
        
        return WorkflowListResponse(
            workflows=workflows,
            count=len(workflows)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history", response_model=WorkflowHistoryResponse)
async def get_workflow_history(
    limit: int = 20,
    workflow_id: str | None = None,
    days: int = 7
):
    """
    Get recent workflow execution history.
    
    **Parameters**:
    - `limit`: Maximum executions to return (default: 20)
    - `workflow_id`: Filter by specific workflow (e.g., 'crypto_market_report')
    - `days`: How many days back to search (default: 7)
    
    **Use cases**:
    - Monitor workflow success/failure rates
    - Debug failed workflow executions
    - Track execution times
    """
    try:
        logs = get_workflow_logs(limit=limit, workflow_id=workflow_id, days=days)
        
        executions = []
        success_count = 0
        failure_count = 0
        
        for log in logs:
            result = log.get('result', {})
            ok = result.get('ok', False)
            
            if ok:
                success_count += 1
            else:
                failure_count += 1
            
            executions.append(WorkflowExecution(
                timestamp=log.get('timestamp', ''),
                workflow_id=log.get('workflow_id', 'unknown'),
                workflow_name=log.get('workflow_name'),
                user_query=log.get('user_query'),
                ok=ok,
                speech=result.get('speech'),
                steps_completed=result.get('steps_completed', 0),
                tools_used=result.get('tools_used', []),
                duration_ms=log.get('duration_ms', 0)
            ))
        
        return WorkflowHistoryResponse(
            executions=executions,
            count=len(executions),
            success_count=success_count,
            failure_count=failure_count
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workflow_id}", response_model=WorkflowInfo)
async def get_workflow(workflow_id: str):
    """
    Get details about a specific workflow.
    
    **Parameters**:
    - `workflow_id`: The workflow ID (e.g., 'crypto_market_report', 'web_archive')
    """
    try:
        workflows_dir = Path(__file__).parent.parent.parent / "data" / "workflows"
        wf_file = workflows_dir / f"{workflow_id}.json"
        
        if not wf_file.exists():
            raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found")
        
        with open(wf_file, 'r') as f:
            wf = json.load(f)
        
        # Extract tools used from steps
        tools_used = []
        for step in wf.get("steps", []):
            tool = step.get("tool")
            if tool and tool not in tools_used:
                tools_used.append(tool)
        
        # Get explicit triggers
        explicit_triggers = wf.get("triggers", {}).get("explicit", [])
        primary_trigger = explicit_triggers[0] if explicit_triggers else f"/{workflow_id}"
        
        # Check if workflow requires input (has main_subject extraction)
        variables = wf.get("variables", {})
        requires_input = any(
            isinstance(v, dict) and v.get("extract") == "main_subject"
            for v in variables.values()
        )
        
        return WorkflowInfo(
            id=wf.get("id", workflow_id),
            name=wf.get("name", workflow_id),
            description=wf.get("description"),
            trigger=primary_trigger,
            triggers=explicit_triggers if explicit_triggers else [f"/{workflow_id}"],
            requires_input=requires_input,
            version=wf.get("version"),
            tools_used=tools_used
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{workflow_id}/execute", response_model=WorkflowExecuteResponse)
async def execute_workflow(workflow_id: str, request: WorkflowExecuteRequest = None):
    """
    Execute a workflow by ID.
    
    **Parameters**:
    - `workflow_id`: The workflow to execute (e.g., 'crypto_market_report')
    - `query`: Optional parameters to pass (e.g., 'ethereum solana' for crypto workflow)
    - `mode`: LLM mode for any LLM-powered steps ('cloud' or 'local')
    
    **Example**:
    ```bash
    # Default crypto report (Bitcoin, Solana)
    curl -X POST http://localhost:8880/api/workflows/crypto_market_report/execute
    
    # Custom coins
    curl -X POST http://localhost:8880/api/workflows/crypto_market_report/execute \\
      -H "Content-Type: application/json" \\
      -d '{"query": "ethereum xrp"}'
    ```
    
    **Note**: Workflow execution can take 30-120+ seconds depending on the workflow.
    """
    import time
    
    if request is None:
        request = WorkflowExecuteRequest()
    
    try:
        # Load config
        from config_loader import load_config
        load_config(request.mode)
        
        if request.mode == "local":
            os.environ['LLM_PROVIDER'] = 'ollama'
        
        # Load workflow
        workflows_dir = Path(__file__).parent.parent.parent / "data" / "workflows"
        wf_file = workflows_dir / f"{workflow_id}.json"
        
        # If direct ID not found, search by trigger alias (e.g., "health" → "server_health_check")
        if not wf_file.exists():
            # Search all workflows for matching trigger
            found_workflow = None
            search_trigger = f"/{workflow_id}" if not workflow_id.startswith("/") else workflow_id
            
            for wf_path in workflows_dir.glob("*.json"):
                try:
                    with open(wf_path, 'r') as f:
                        wf = json.load(f)
                    triggers = wf.get("triggers", {}).get("explicit", [])
                    # Check if search_trigger matches any explicit trigger
                    if search_trigger in triggers or workflow_id in triggers:
                        found_workflow = wf
                        wf_file = wf_path
                        break
                    # Also check without leading slash
                    if f"/{workflow_id}" in triggers:
                        found_workflow = wf
                        wf_file = wf_path
                        break
                except (json.JSONDecodeError, IOError):
                    continue
            
            if not found_workflow:
                # List available workflows and their triggers for helpful error
                available = []
                for wf_path in workflows_dir.glob("*.json"):
                    try:
                        with open(wf_path, 'r') as f:
                            wf = json.load(f)
                        if wf.get("enabled", True):
                            triggers = wf.get("triggers", {}).get("explicit", [])
                            available.append(f"{wf.get('id')} (triggers: {', '.join(triggers) or 'none'})")
                    except:
                        continue
                raise HTTPException(
                    status_code=404, 
                    detail=f"Workflow '{workflow_id}' not found. Available: {'; '.join(available[:5])}"
                )
            workflow = found_workflow
        else:
            with open(wf_file, 'r') as f:
                workflow = json.load(f)
        
        # Build transcript (trigger + optional query)
        # Use first explicit trigger if available, otherwise fall back to /{workflow_id}
        explicit_triggers = workflow.get("triggers", {}).get("explicit", [])
        all_triggers = explicit_triggers + [f"/{workflow_id}"]
        trigger = explicit_triggers[0] if explicit_triggers else f"/{workflow_id}"
        
        # Clean up query - remove trigger prefix if user accidentally included it
        query = request.query.strip() if request.query else ""
        for t in all_triggers:
            if query.lower().startswith(t.lower()):
                query = query[len(t):].strip()
                break
        
        # Check if workflow requires a topic/query
        variables = workflow.get("variables", {})
        requires_topic = any(
            isinstance(v, dict) and v.get("extract") == "main_subject" 
            for v in variables.values()
        )
        
        if requires_topic and not query:
            # Return helpful error for workflows that need input
            raise HTTPException(
                status_code=400,
                detail={
                    "error": f"Workflow '{workflow_id}' requires a topic/query parameter",
                    "hint": f"Example: POST /api/workflows/{workflow_id}/execute with body: {{\"query\": \"your topic here\"}}",
                    "workflow_description": workflow.get("description", "")
                }
            )
        
        if query:
            transcript = f"{trigger} {query}"
        else:
            transcript = trigger
        
        # Import and execute
        from executor import ToolExecutor
        from pipeline_executor import PipelineExecutor
        
        executor = ToolExecutor(mode=request.mode)
        pipeline = PipelineExecutor(request.mode, executor)
        
        start_time = time.time()
        result = pipeline.execute(workflow, transcript)
        duration_ms = (time.time() - start_time) * 1000
        
        return WorkflowExecuteResponse(
            ok=result.get("ok", False),
            workflow_id=workflow_id,
            speech=result.get("speech"),
            tools_used=result.get("tools_used", []),
            steps_completed=result.get("steps_completed", 0),
            duration_ms=duration_ms,
            data=result.get("data"),
            usage=result.get("usage"),
            error=result.get("error")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        return WorkflowExecuteResponse(
            ok=False,
            workflow_id=workflow_id,
            error=str(e)
        )
