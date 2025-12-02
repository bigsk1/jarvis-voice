#!/usr/bin/env python3
"""
Jarvis Self-Play System

Generates novel queries, executes them through the orchestrator,
collects feedback, and detects tool gaps for improvement.

This feeds the feedback/evolution loop to make Jarvis smarter.
"""

import os
import sys
import json
import random
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from collections import defaultdict
from dataclasses import dataclass, asdict

# Add lib to path
sys.path.insert(0, os.path.dirname(__file__))
from config_loader import load_config, get_config_value
from llm_provider import create_provider

# Query categories with examples for LLM to generate variations
QUERY_CATEGORIES = {
    "information": {
        "examples": [
            "What's the weather forecast for today?",
            "Current Bitcoin price",
            "What time is it in Tokyo?",
            "What's the population of France?",
            "How far is Mars from Earth?",
        ],
        "weight": 0.20,
        "description": "Factual questions requiring lookup or calculation",
    },
    "research": {
        "examples": [
            "Compare PostgreSQL vs MySQL for web apps",
            "What are the pros and cons of Kubernetes?",
            "Latest trends in machine learning",
            "Best practices for API design",
            "Differences between REST and GraphQL",
        ],
        "weight": 0.25,
        "description": "Research and comparison questions",
    },
    "coding": {
        "examples": [
            "How do I parse JSON in Python?",
            "Explain async/await in JavaScript",
            "Best practices for error handling",
            "How to use Docker volumes?",
            "What's a good way to handle rate limiting?",
        ],
        "weight": 0.15,
        "description": "Programming and technical questions",
    },
    "productivity": {
        "examples": [
            "What's on my calendar today?",
            "Do I have any meetings this week?",
            "What did I ask you about yesterday?",
            "What projects am I working on?",
            "Find my notes about the API project",
        ],
        "weight": 0.15,
        "description": "Personal productivity and memory queries",
    },
    "home_automation": {
        "examples": [
            "What's the temperature inside?",
            "Are any lights on?",
            "Check the status of my servers",
            "Is the garage door open?",
            "What devices are connected?",
        ],
        "weight": 0.10,
        "description": "Smart home and IoT queries",
    },
    "general": {
        "examples": [
            "Tell me something interesting",
            "What's the capital of Australia?",
            "How does a rainbow form?",
            "Who invented the telephone?",
            "What's a good book recommendation?",
        ],
        "weight": 0.10,
        "description": "General knowledge and trivia",
    },
    "media": {
        "examples": [
            "Find videos about Python tutorials",
            "What's trending in tech news?",
            "Search for Docker tutorials on YouTube",
            "Latest AI research papers",
            "Find podcasts about startups",
        ],
        "weight": 0.05,
        "description": "Media search and discovery",
    },
}

# Categories to EXCLUDE from self-play (these have real side effects)
EXCLUDED_CATEGORIES = [
    "email",       # Don't send real emails
    "reminder",    # Don't create real reminders  
    "webhook",     # Don't trigger real webhooks
    "alert",       # Don't send real alerts
]

# Categories to SKIP (user doesn't have these capabilities)
# Edit this list based on your setup
DISABLED_CATEGORIES = [
    "home_automation",  # No smart home devices
    # "productivity",   # Uncomment if no calendar integration
    # "media",          # Uncomment if no media tools
]


@dataclass
class QueryResult:
    """Result of executing a single query."""
    query: str
    category: str
    response: str
    tools_used: List[str]
    duration_ms: float
    ok: bool
    error: Optional[str] = None


@dataclass
class FeedbackResult:
    """Result of feedback grading."""
    rating: int
    summary: str
    tool_ratings: Dict[str, Dict[str, Any]]
    issues: List[Dict[str, Any]]


@dataclass 
class ToolGap:
    """Identified gap where a dedicated tool would help."""
    pattern: str
    query_count: int
    example_queries: List[str]
    suggestion: str


@dataclass
class SessionSummary:
    """Summary of a self-play session."""
    session_id: str
    timestamp: str
    mode: str
    total_queries: int
    avg_rating: float
    low_ratings: int
    tool_gaps: List[ToolGap]
    evolution_triggered: bool
    duration_seconds: float
    results: List[Dict[str, Any]]


class SelfPlayEngine:
    """Engine for running self-play sessions."""
    
    def __init__(self, mode: str = "cloud"):
        self.mode = mode
        load_config(mode)
        self.project_root = Path(__file__).parent.parent
        self.logs_dir = self.project_root / "logs" / "self-play"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        
    def generate_queries(self, num_queries: int, categories: Optional[List[str]] = None) -> List[Dict[str, str]]:
        """
        Generate novel queries using LLM.
        
        Args:
            num_queries: Total number of queries to generate
            categories: Optional list of categories to use (default: all)
            
        Returns:
            List of {"query": str, "category": str} dicts
        """
        if categories is None:
            categories = list(QUERY_CATEGORIES.keys())
        
        # Filter to valid categories and remove disabled ones
        categories = [c for c in categories if c in QUERY_CATEGORIES]
        categories = [c for c in categories if c not in DISABLED_CATEGORIES]
        
        if not categories:
            # Fallback if all filtered out
            categories = [c for c in QUERY_CATEGORIES.keys() if c not in DISABLED_CATEGORIES]
        
        if not categories:
            raise ValueError("No valid categories available after filtering")
        
        # Calculate queries per category based on weights
        total_weight = sum(QUERY_CATEGORIES[c]["weight"] for c in categories)
        queries_per_category = {}
        
        remaining = num_queries
        for cat in categories[:-1]:
            weight = QUERY_CATEGORIES[cat]["weight"] / total_weight
            count = int(num_queries * weight)
            queries_per_category[cat] = count
            remaining -= count
        queries_per_category[categories[-1]] = remaining
        
        # Generate queries for each category
        all_queries = []
        provider = self._create_provider()
        
        for category, count in queries_per_category.items():
            if count <= 0:
                continue
                
            cat_info = QUERY_CATEGORIES[category]
            examples = cat_info["examples"]
            
            prompt = f"""Generate {count} unique, realistic voice assistant queries in the "{category}" category.

Category description: {cat_info["description"]}

Example queries (generate DIFFERENT ones, not these):
{chr(10).join(f"- {ex}" for ex in examples)}

Rules:
1. Make them sound natural, like someone talking to a voice assistant
2. Vary the phrasing and complexity
3. Don't include emails, reminders, webhooks, or alerts (these have side effects)
4. Keep them reasonable - things a real person would ask
5. Output ONLY the queries, one per line, no numbering or bullets

Generate {count} queries:"""

            try:
                response = provider.chat(
                    message=prompt,
                    max_tokens=1000,
                )
                
                # Parse response - one query per line
                lines = response.strip().split("\n")
                for line in lines:
                    line = line.strip()
                    # Skip empty lines, bullets, numbers
                    if not line:
                        continue
                    if line.startswith(("-", "*", "•")):
                        line = line[1:].strip()
                    if line and line[0].isdigit() and "." in line[:3]:
                        line = line.split(".", 1)[1].strip()
                    if line:
                        all_queries.append({
                            "query": line,
                            "category": category,
                        })
                        
            except Exception as e:
                # Fallback to examples if LLM fails
                print(f"Warning: LLM query generation failed for {category}: {e}", file=sys.stderr)
                for i in range(min(count, len(examples))):
                    all_queries.append({
                        "query": examples[i],
                        "category": category,
                    })
        
        # Shuffle to mix categories
        random.shuffle(all_queries)
        
        return all_queries[:num_queries]
    
    def execute_query(self, query: str, category: str, silent: bool = True) -> QueryResult:
        """
        Execute a single query through the orchestrator.
        
        Args:
            query: The query to execute
            category: Category for logging
            silent: If True, no TTS output
            
        Returns:
            QueryResult with response and metrics
        """
        start_time = datetime.now()
        
        orchestrator_path = self.project_root / "orchestrator" / "orchestrator_v2.py"
        
        try:
            # Run orchestrator with --json flag
            env = os.environ.copy()
            env["JARVIS_SELF_PLAY"] = "true"  # Flag for tracking
            if silent:
                env["JARVIS_TTS_DISABLED"] = "true"
            
            result = subprocess.run(
                [sys.executable, str(orchestrator_path), self.mode, query, "--json"],
                capture_output=True,
                text=True,
                timeout=180,  # 3 minute timeout
                env=env,
            )
            
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            
            # Parse JSON response
            try:
                response_data = json.loads(result.stdout)
                return QueryResult(
                    query=query,
                    category=category,
                    response=response_data.get("speech", ""),
                    tools_used=response_data.get("tools_used", []),
                    duration_ms=duration_ms,
                    ok=response_data.get("ok", False),
                    error=response_data.get("error"),
                )
            except json.JSONDecodeError:
                return QueryResult(
                    query=query,
                    category=category,
                    response=result.stdout[:500] if result.stdout else "",
                    tools_used=[],
                    duration_ms=duration_ms,
                    ok=False,
                    error=f"JSON parse error: {result.stderr[:200] if result.stderr else 'no stderr'}",
                )
                
        except subprocess.TimeoutExpired:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            return QueryResult(
                query=query,
                category=category,
                response="",
                tools_used=[],
                duration_ms=duration_ms,
                ok=False,
                error="Timeout after 180 seconds",
            )
        except Exception as e:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            return QueryResult(
                query=query,
                category=category,
                response="",
                tools_used=[],
                duration_ms=duration_ms,
                ok=False,
                error=str(e),
            )
    
    def collect_feedback(self, query_result: QueryResult) -> Optional[FeedbackResult]:
        """
        Collect feedback on a query result using the feedback system.
        
        Args:
            query_result: The result to grade
            
        Returns:
            FeedbackResult or None if feedback collection fails
        """
        try:
            from feedback import FeedbackCollector
            
            collector = FeedbackCollector(mode=self.mode)
            
            # Prepare the result dict for feedback
            result_dict = {
                "ok": query_result.ok,
                "speech": query_result.response,
                "tools_used": query_result.tools_used,
            }
            
            # Get response style for context
            response_style = get_config_value("JARVIS_RESPONSE_STYLE", "casual")
            
            # Build config context to help feedback understand the style
            config_context = f"""Response Style: {response_style}
- casual: Brief voice output (~25 words), no URLs for speech
- auto: Adapts based on query complexity
- detailed: Full output for display/reading, markdown and URLs allowed"""
            
            # Run feedback collection with proper parameters
            feedback_data = collector.collect(
                query=query_result.query,
                result=result_dict,
                tools_used=query_result.tools_used,
                config_context=config_context,
                session_id=f"self_play_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            )
            
            if feedback_data:
                return FeedbackResult(
                    rating=feedback_data.get("rating", 0),
                    summary=feedback_data.get("summary", ""),
                    tool_ratings=feedback_data.get("tool_ratings", {}),
                    issues=feedback_data.get("issues", []),
                )
            return None
            
        except Exception as e:
            print(f"Warning: Feedback collection failed: {e}", file=sys.stderr)
            return None
    
    def analyze_tool_gaps(self, results: List[Dict[str, Any]]) -> List[ToolGap]:
        """
        Analyze results to find tool gaps.
        
        A "gap" is when Brave search is used repeatedly for similar queries
        that could benefit from a dedicated tool.
        
        Args:
            results: List of query results with tools_used
            
        Returns:
            List of identified tool gaps
        """
        # Track queries that hit Brave search
        brave_queries = defaultdict(list)
        
        for result in results:
            tools = result.get("tools_used", [])
            if any("brave" in t.lower() for t in tools):
                category = result.get("category", "unknown")
                brave_queries[category].append(result.get("query", ""))
        
        # Identify gaps (3+ queries in same category hitting Brave)
        gaps = []
        for category, queries in brave_queries.items():
            if len(queries) >= 3:
                gaps.append(ToolGap(
                    pattern=category,
                    query_count=len(queries),
                    example_queries=queries[:5],
                    suggestion=f"Consider dedicated '{category}' tool instead of Brave search",
                ))
        
        return gaps
    
    def run_session(
        self,
        num_queries: int = 50,
        categories: Optional[List[str]] = None,
        silent: bool = True,
        collect_feedback: bool = True,
        progress_callback=None,
    ) -> SessionSummary:
        """
        Run a complete self-play session.
        
        Args:
            num_queries: Number of queries to run
            categories: Optional category filter
            silent: Disable TTS
            collect_feedback: Whether to run feedback on each query
            progress_callback: Optional callback(current, total, query) for progress
            
        Returns:
            SessionSummary with all results and analysis
        """
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        start_time = datetime.now()
        
        # Generate queries
        queries = self.generate_queries(num_queries, categories)
        
        results = []
        ratings = []
        
        # Execute each query
        for i, q in enumerate(queries):
            if progress_callback:
                progress_callback(i + 1, len(queries), q["query"])
            
            # Execute
            query_result = self.execute_query(q["query"], q["category"], silent=silent)
            
            result_data = {
                "query": q["query"],
                "category": q["category"],
                "response": query_result.response,
                "tools_used": query_result.tools_used,
                "duration_ms": query_result.duration_ms,
                "ok": query_result.ok,
                "error": query_result.error,
            }
            
            # Collect feedback if enabled
            if collect_feedback and query_result.ok:
                feedback = self.collect_feedback(query_result)
                if feedback:
                    result_data["feedback"] = {
                        "rating": feedback.rating,
                        "summary": feedback.summary,
                        "tool_ratings": feedback.tool_ratings,
                        "issues": feedback.issues,
                    }
                    ratings.append(feedback.rating)
            
            results.append(result_data)
            
            # Log each result
            self._log_result(session_id, result_data)
        
        # Analyze gaps
        tool_gaps = self.analyze_tool_gaps(results)
        
        # Calculate summary
        avg_rating = sum(ratings) / len(ratings) if ratings else 0.0
        low_ratings = len([r for r in ratings if r < 4])
        
        # Check if evolution was triggered
        evolution_triggered = self._check_evolution_triggered()
        
        duration_seconds = (datetime.now() - start_time).total_seconds()
        
        summary = SessionSummary(
            session_id=session_id,
            timestamp=datetime.now().isoformat(),
            mode=self.mode,
            total_queries=len(queries),
            avg_rating=round(avg_rating, 2),
            low_ratings=low_ratings,
            tool_gaps=tool_gaps,
            evolution_triggered=evolution_triggered,
            duration_seconds=round(duration_seconds, 1),
            results=results,
        )
        
        # Save session summary
        self._save_session(summary)
        
        return summary
    
    def _create_provider(self):
        """Create LLM provider for query generation."""
        provider_type = get_config_value("LLM_PROVIDER", "anthropic")
        
        if provider_type == "ollama":
            return create_provider(
                "ollama",
                model=get_config_value("OLLAMA_MODEL", "qwen3:14b"),
                base_url=get_config_value("OLLAMA_BASE_URL", "http://localhost:11434"),
            )
        elif provider_type == "xai":
            return create_provider(
                "xai",
                api_key=get_config_value("XAI_API_KEY"),
                model=get_config_value("XAI_MODEL", "grok-4-1-fast-non-reasoning-latest"),
            )
        elif provider_type == "anthropic":
            return create_provider(
                "anthropic",
                api_key=get_config_value("ANTHROPIC_API_KEY"),
                model=get_config_value("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929"),
            )
        else:
            return create_provider(
                "openai",
                api_key=get_config_value("OPENAI_API_KEY"),
                model=get_config_value("CHAT_MODEL", "gpt-4o"),
            )
    
    def _log_result(self, session_id: str, result: Dict[str, Any]):
        """Log a single result to JSONL file."""
        log_file = self.logs_dir / f"self-play-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
            "mode": self.mode,
            **result,
        }
        
        with open(log_file, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    
    def _save_session(self, summary: SessionSummary):
        """Save session summary to JSON file."""
        summary_file = self.logs_dir / f"session-{summary.session_id}.json"
        
        # Convert dataclasses to dicts
        summary_dict = {
            "session_id": summary.session_id,
            "timestamp": summary.timestamp,
            "mode": summary.mode,
            "total_queries": summary.total_queries,
            "avg_rating": summary.avg_rating,
            "low_ratings": summary.low_ratings,
            "tool_gaps": [asdict(g) for g in summary.tool_gaps],
            "evolution_triggered": summary.evolution_triggered,
            "duration_seconds": summary.duration_seconds,
            "results": summary.results,
        }
        
        with open(summary_file, "w") as f:
            json.dump(summary_dict, f, indent=2)
    
    def _check_evolution_triggered(self) -> bool:
        """Check if evolution was triggered during the session."""
        # Look for recent evolution log entries
        evolution_log = self.project_root / "logs" / "evolution" / f"evolution-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        
        if not evolution_log.exists():
            return False
        
        # Check for entries in the last minute
        try:
            with open(evolution_log) as f:
                lines = f.readlines()
                
            for line in reversed(lines[-10:]):  # Check last 10 entries
                try:
                    entry = json.loads(line)
                    entry_time = datetime.fromisoformat(entry.get("timestamp", ""))
                    if (datetime.now() - entry_time).total_seconds() < 60:
                        return True
                except:
                    continue
        except:
            pass
        
        return False
    
    def get_latest_session(self) -> Optional[Dict[str, Any]]:
        """Get the most recent session summary."""
        session_files = sorted(self.logs_dir.glob("session-*.json"), reverse=True)
        
        if session_files:
            with open(session_files[0]) as f:
                return json.load(f)
        return None
    
    def list_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List recent session summaries."""
        session_files = sorted(self.logs_dir.glob("session-*.json"), reverse=True)[:limit]
        
        sessions = []
        for f in session_files:
            try:
                with open(f) as fp:
                    data = json.load(fp)
                    # Return summary without full results
                    sessions.append({
                        "session_id": data["session_id"],
                        "timestamp": data["timestamp"],
                        "mode": data["mode"],
                        "total_queries": data["total_queries"],
                        "avg_rating": data["avg_rating"],
                        "low_ratings": data["low_ratings"],
                        "tool_gaps": len(data.get("tool_gaps", [])),
                        "evolution_triggered": data.get("evolution_triggered", False),
                    })
            except:
                continue
        
        return sessions


def main():
    """CLI entry point for testing."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Jarvis Self-Play System")
    parser.add_argument("--mode", "-m", choices=["cloud", "local"], default="cloud")
    parser.add_argument("--queries", "-n", type=int, default=10)
    parser.add_argument("--categories", "-c", nargs="+", help="Categories to use")
    parser.add_argument("--no-feedback", action="store_true", help="Skip feedback collection")
    
    args = parser.parse_args()
    
    engine = SelfPlayEngine(mode=args.mode)
    
    def progress(current, total, query):
        print(f"  [{current}/{total}] {query[:50]}...")
    
    print(f"Starting self-play session ({args.queries} queries, {args.mode} mode)")
    
    summary = engine.run_session(
        num_queries=args.queries,
        categories=args.categories,
        collect_feedback=not args.no_feedback,
        progress_callback=progress,
    )
    
    print(f"\nSession Complete:")
    print(f"  Total queries: {summary.total_queries}")
    print(f"  Avg rating: {summary.avg_rating}")
    print(f"  Low ratings: {summary.low_ratings}")
    print(f"  Tool gaps: {len(summary.tool_gaps)}")
    print(f"  Evolution triggered: {summary.evolution_triggered}")


if __name__ == "__main__":
    main()

