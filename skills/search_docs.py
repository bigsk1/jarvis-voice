#!/usr/bin/env python3
"""
Search Docs Tool - Query Jarvis internal documentation using QMD semantic search.

Uses QMD (Query Markup Documents) to semantically search the indexed jarvis-docs
collection. Returns relevant documentation excerpts for Q&A about Jarvis capabilities.

Designed for questions like:
- "What video sizes can I generate?"
- "How long can music be?"
- "What are the image styles?"
- "How does memory work?"
"""

import sys
import json
import subprocess
import re
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# Topic to path mappings for focused searches
TOPIC_PATHS = {
    "video": ["video", "api/generated-videos"],
    "image": ["api/generated-images", "CANVAS_SYSTEM"],
    "music": ["api/generated-music", "11labs"],
    "memory": ["MEMORY_SYSTEM", "MEMORY_INTELLIGENCE"],
    "api": ["api"],
    "tools": ["TOOL_CALLING_SYSTEM", "TOOL_MANAGEMENT"],
    "workflows": ["WORKFLOW_ORCHESTRATION", "n8n"],
    "canvas": ["CANVAS_SYSTEM", "api/canvas"],
    "stash": ["api/stash"],
}


def run_qmd_vsearch(query: str, limit: int = 5, min_score: float = 0.4) -> list[dict]:
    """
    Run QMD vsearch (semantic vector search) and parse results.
    
    Args:
        query: Natural language search query
        limit: Maximum results to return
        min_score: Minimum similarity score (0-1)
        
    Returns:
        List of result dicts with title, path, score, content
    """
    results = []
    
    # Build QMD command
    cmd = [
        'qmd', 'vsearch', query,
        '-n', str(limit + 3),  # Get extra to filter
        '--min-score', str(min_score),
        '-c', 'jarvis-docs',  # Collection
        '--json'
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,  # vsearch is faster than query
            cwd=str(PROJECT_ROOT)
        )
        
        if result.returncode != 0:
            # Check if QMD not found or index missing
            if 'command not found' in result.stderr.lower():
                return []
            if 'no index' in result.stderr.lower():
                return []
        
        # Parse JSON output
        # QMD --json outputs an array of results
        output = result.stdout.strip()
        if not output:
            return []
            
        # Skip any warning lines (like Vulkan fallback messages)
        lines = output.split('\n')
        json_start = None
        for i, line in enumerate(lines):
            if line.strip().startswith('[') or line.strip().startswith('{'):
                json_start = i
                break
        
        if json_start is not None:
            json_text = '\n'.join(lines[json_start:])
            try:
                data = json.loads(json_text)
                
                # Handle both array and object responses
                if isinstance(data, list):
                    for item in data[:limit]:
                        results.append(parse_qmd_result(item))
                elif isinstance(data, dict):
                    if 'results' in data:
                        for item in data['results'][:limit]:
                            results.append(parse_qmd_result(item))
                    else:
                        results.append(parse_qmd_result(data))
            except json.JSONDecodeError:
                # Fall back to line-by-line parsing
                pass
                
    except subprocess.TimeoutExpired:
        pass
    except FileNotFoundError:
        # QMD not installed
        pass
    except Exception:
        pass
    
    return results


def parse_qmd_result(item: dict) -> dict:
    """Parse a single QMD result into a clean dict."""
    # Get file path - prefer 'file' field, clean up qmd:// prefix
    file_path = item.get('file', item.get('path', item.get('docid', '')))
    file_path = file_path.replace('qmd://jarvis-docs/', 'docs/')
    
    return {
        'title': item.get('title', ''),
        'path': file_path,
        'score': item.get('score', 0),
        'content': item.get('snippet', item.get('content', ''))[:1000],
        'context': item.get('context', ''),
        'line': item.get('line', 0)
    }


def run_qmd_search_fallback(query: str, limit: int = 5) -> list[dict]:
    """
    Fallback to BM25 keyword search if vsearch fails.
    """
    results = []
    
    cmd = [
        'qmd', 'search', query,
        '-n', str(limit),
        '-c', 'jarvis-docs',
        '--json'
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(PROJECT_ROOT)
        )
        
        output = result.stdout.strip()
        if not output:
            return []
        
        # Skip warning lines
        lines = output.split('\n')
        for i, line in enumerate(lines):
            if line.strip().startswith('[') or line.strip().startswith('{'):
                json_text = '\n'.join(lines[i:])
                try:
                    data = json.loads(json_text)
                    if isinstance(data, list):
                        for item in data[:limit]:
                            results.append(parse_qmd_result(item))
                except:
                    pass
                break
                
    except Exception:
        pass
    
    return results


def filter_by_topic(results: list[dict], topic: str) -> list[dict]:
    """Filter results to match a specific topic's paths."""
    if topic == "all" or topic not in TOPIC_PATHS:
        return results
    
    topic_patterns = TOPIC_PATHS[topic]
    filtered = []
    
    for r in results:
        path = r.get('path', '').lower()
        title = r.get('title', '').lower()
        
        for pattern in topic_patterns:
            if pattern.lower() in path or pattern.lower() in title:
                filtered.append(r)
                break
    
    return filtered if filtered else results  # Return all if filter yields nothing


def format_results_for_speech(results: list[dict], query: str) -> str:
    """Generate a brief speech summary of results."""
    if not results:
        return f"I couldn't find documentation about '{query}'. Try rephrasing or ask me directly."
    
    # Extract key info from top result
    top = results[0]
    title = top.get('title', 'the documentation')
    
    if len(results) == 1:
        return f"Found relevant info in {title}."
    else:
        return f"Found {len(results)} relevant docs, starting with {title}."


def format_content_for_llm(results: list[dict]) -> str:
    """Format results as readable content for the LLM to use in response."""
    if not results:
        return "No documentation found."
    
    formatted = []
    for i, r in enumerate(results, 1):
        title = r.get('title', 'Untitled')
        path = r.get('path', '')
        score = r.get('score', 0)
        content = r.get('content', '').strip()
        
        # Clean up content - remove @@ diff markers for readability
        content = re.sub(r'@@ -\d+,\d+ @@.*?\n', '', content)
        content = re.sub(r'\(\d+ before, \d+ after\)\s*\n?', '', content)
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = content[:800] if len(content) > 800 else content
        
        formatted.append(f"""
### {i}. {title}
**Source:** {path} (relevance: {score:.0%})

{content}
""".strip())
    
    return "\n\n---\n\n".join(formatted)


def main():
    """Main entry point."""
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        # Extract parameters
        query = args.get('query')
        if not query:
            raise ValueError("query parameter is required")
        
        topic = args.get('topic', 'all')
        limit = args.get('limit', 5)
        
        # Run semantic search
        results = run_qmd_vsearch(query, limit=limit + 2, min_score=0.35)
        
        # Fallback to keyword search if semantic fails
        if not results:
            results = run_qmd_search_fallback(query, limit=limit)
        
        # Filter by topic if specified
        if topic != "all":
            results = filter_by_topic(results, topic)
        
        # Limit results
        results = results[:limit]
        
        # Format output
        speech = format_results_for_speech(results, query)
        formatted_content = format_content_for_llm(results)
        
        output = {
            "ok": True,
            "speech": speech,
            "data": {
                "query": query,
                "topic": topic,
                "result_count": len(results),
                "documentation": formatted_content,
                "results": results,
                "usage_hint": "Use the 'documentation' field to answer the user's question about Jarvis capabilities."
            }
        }
        
        print(json.dumps(output))
        
    except Exception as e:
        error_result = {
            "ok": False,
            "error": str(e),
            "speech": f"Documentation search failed: {e}"
        }
        print(json.dumps(error_result))
        sys.exit(1)


if __name__ == "__main__":
    main()
