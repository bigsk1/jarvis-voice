"""Documentation Search API - Query Jarvis internal docs via QMD semantic search.

Provides API access to search Jarvis documentation for capabilities,
tool parameters, and system information.

Rate limited due to CPU-intensive semantic search (~15-20s per query).
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Literal
import subprocess
import json
import re
import time
from pathlib import Path

from lib.rate_limiter import get_docs_search_rate_limit_per_minute

router = APIRouter(prefix="/api/docs", tags=["docs"])

# Project root for running QMD
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()

# CPU-heavy /search is rate-limited by lib.rate_limiter.APIRateLimitMiddleware (docs bucket).


class DocsSearchRequest(BaseModel):
    """Request model for docs search."""
    query: str = Field(..., description="Natural language question about Jarvis capabilities")
    topic: Literal["all", "video", "image", "music", "memory", "api", "tools", "workflows", "canvas", "stash"] = Field(
        default="all",
        description="Optional topic filter to narrow results"
    )
    limit: int = Field(default=5, ge=1, le=10, description="Max results (1-10)")


class DocsSearchResult(BaseModel):
    """Individual search result."""
    title: str
    path: str
    score: float
    content: str


class DocsSearchResponse(BaseModel):
    """Response model for docs search."""
    ok: bool
    query: str
    topic: str
    result_count: int
    documentation: str
    results: list[DocsSearchResult]
    search_time_ms: int


def run_qmd_vsearch(query: str, limit: int = 5, min_score: float = 0.4) -> list[dict]:
    """Run QMD vsearch and parse JSON results."""
    results = []
    
    cmd = [
        'qmd', 'vsearch', query,
        '-n', str(limit + 2),
        '--min-score', str(min_score),
        '-c', 'jarvis-docs',
        '--json'
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=90,
            cwd=str(PROJECT_ROOT)
        )
        
        output = result.stdout.strip()
        if not output:
            return []
        
        # Skip warning lines, find JSON
        lines = output.split('\n')
        for i, line in enumerate(lines):
            if line.strip().startswith('[') or line.strip().startswith('{'):
                json_text = '\n'.join(lines[i:])
                try:
                    data = json.loads(json_text)
                    if isinstance(data, list):
                        for item in data[:limit]:
                            results.append(parse_result(item))
                except json.JSONDecodeError:
                    pass
                break
                
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    
    return results


def parse_result(item: dict) -> dict:
    """Parse QMD result into clean dict."""
    file_path = item.get('file', item.get('path', item.get('docid', '')))
    file_path = file_path.replace('qmd://jarvis-docs/', 'docs/')
    
    return {
        'title': item.get('title', ''),
        'path': file_path,
        'score': item.get('score', 0),
        'content': item.get('snippet', item.get('content', ''))[:1000]
    }


def format_documentation(results: list[dict]) -> str:
    """Format results as readable documentation."""
    if not results:
        return "No documentation found."
    
    formatted = []
    for i, r in enumerate(results, 1):
        title = r.get('title', 'Untitled')
        path = r.get('path', '')
        score = r.get('score', 0)
        content = r.get('content', '').strip()
        
        # Clean up QMD diff markers
        content = re.sub(r'@@ -\d+,\d+ @@.*?\n', '', content)
        content = re.sub(r'\(\d+ before, \d+ after\)\s*\n?', '', content)
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = content[:600] if len(content) > 600 else content
        
        formatted.append(f"### {i}. {title}\n**Source:** {path} ({score:.0%})\n\n{content}")
    
    return "\n\n---\n\n".join(formatted)


# Topic path mappings
TOPIC_PATHS = {
    "video": ["video", "api/generated-videos"],
    "image": ["api/generated-images", "CANVAS_SYSTEM"],
    "music": ["tools/generate-music-tool", "api/generated-music", "11labs"],
    "memory": ["MEMORY_SYSTEM", "MEMORY_INTELLIGENCE"],
    "api": ["api"],
    "tools": ["TOOL_CALLING_SYSTEM", "TOOL_MANAGEMENT"],
    "workflows": ["WORKFLOW_ORCHESTRATION", "n8n"],
    "canvas": ["CANVAS_SYSTEM", "api/canvas"],
    "stash": ["api/stash"],
}


def filter_by_topic(results: list[dict], topic: str) -> list[dict]:
    """Filter results by topic."""
    if topic == "all" or topic not in TOPIC_PATHS:
        return results
    
    patterns = TOPIC_PATHS[topic]
    filtered = []
    
    for r in results:
        path = r.get('path', '').lower()
        title = r.get('title', '').lower()
        
        for pattern in patterns:
            if pattern.lower() in path or pattern.lower() in title:
                filtered.append(r)
                break
    
    return filtered if filtered else results


@router.post("/search", response_model=DocsSearchResponse)
async def search_docs(request: Request, body: DocsSearchRequest):
    """
    Search Jarvis documentation using semantic search.
    
    Returns relevant documentation excerpts for questions about:
    - Tool capabilities and parameters
    - Video/image/music generation options
    - API endpoints and usage
    - System features and workflows
    
    Rate limited per IP (docs bucket; see lib.rate_limiter / DOCS_API_RATE_LIMIT_PER_MINUTE).
    """
    start_time = time.time()
    
    # Run search
    results = run_qmd_vsearch(body.query, limit=body.limit + 2, min_score=0.35)
    
    # Filter by topic
    if body.topic != "all":
        results = filter_by_topic(results, body.topic)
    
    # Limit results
    results = results[:body.limit]
    
    # Format documentation
    documentation = format_documentation(results)
    
    search_time = int((time.time() - start_time) * 1000)
    
    return DocsSearchResponse(
        ok=True,
        query=body.query,
        topic=body.topic,
        result_count=len(results),
        documentation=documentation,
        results=[DocsSearchResult(**r) for r in results],
        search_time_ms=search_time
    )


@router.get("/topics")
async def list_topics():
    """List available topic filters for docs search."""
    return {
        "topics": list(TOPIC_PATHS.keys()) + ["all"],
        "descriptions": {
            "all": "Search all documentation",
            "video": "Video generation (xAI, Gemini)",
            "image": "Image generation and canvas",
            "music": "ElevenLabs music generation",
            "memory": "Memory system and intelligence",
            "api": "REST API endpoints",
            "tools": "Tool system and management",
            "workflows": "Workflow orchestration and n8n",
            "canvas": "Canvas artifact system",
            "stash": "Stash file storage"
        }
    }


@router.get("/status")
async def docs_status():
    """Get QMD index status and health."""
    try:
        result = subprocess.run(
            ['qmd', 'status'],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(PROJECT_ROOT)
        )
        
        output = result.stdout
        
        # Parse key metrics
        files_match = re.search(r'Total:\s*(\d+)\s*files', output)
        vectors_match = re.search(r'Vectors:\s*(\d+)', output)
        updated_match = re.search(r'Updated:\s*(.+)', output)
        
        return {
            "status": "healthy" if result.returncode == 0 else "error",
            "indexed_files": int(files_match.group(1)) if files_match else 0,
            "vectors": int(vectors_match.group(1)) if vectors_match else 0,
            "last_updated": updated_match.group(1).strip() if updated_match else "unknown",
            "collection": "jarvis-docs",
            "rate_limit": f"{get_docs_search_rate_limit_per_minute()} requests per minute (POST /search only)"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
