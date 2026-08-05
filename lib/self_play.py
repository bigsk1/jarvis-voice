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
from typing import Any
from collections import defaultdict
from dataclasses import dataclass, asdict

# Add lib to path
sys.path.insert(0, os.path.dirname(__file__))
from config_loader import config_scope, export_config_environment, get_config_value
from llm_provider import create_configured_provider

# Tools that are too side-effectful or operationally powerful for unattended self-play.
DEFAULT_EXCLUDED_TOOLS = [
    "acknowledge_alerts",
    "acknowledge_reminders",
    "api_call",
    "opencode",
    "docker_control",
    "execute_bash",
    "ssh_remote",
    "phone_call",
    "send_email",
    "send_webhook",
    "create_alert",
    "create_reminder",
    "schedule_task",
    "canvas",
    "convert_file",
    "printer",
    "pdf_create",
    "pdf_read",
    "generate_image",
    "generate_video",
    "generate_music",
    "create_social_clip",
    "manage_intel",
    "ingest_intel",
    "remember",
    "update_memory",
    "forget",
    "memory_deduper",
    "price_alert",
    "spotify",
    "speaker_volume",
    "stash",
    "upload_cloudflare",
    "qr_code_generator",
    "screenshot_url",
    "status_recap",
    "youtube_transcript",
    "youtube_video",
    "git_release_notes",
    "evolution_test",
    "network_tools",
]

# Self-play is fail-closed: only reviewed read-only tools are eligible. New
# tools discovered by the registry are excluded until added here deliberately.
DEFAULT_ALLOWED_TOOLS = {
    "analyze_image",
    "bookmark_search",
    "brave_llm_context",
    "calculator",
    "check_opencode_sessions",
    "check_tool_logs",
    "crawl_url",
    "crypto_chart",
    "crypto_price",
    "deep_memory_search",
    "get_recent_conversations",
    "get_time",
    "list_alerts",
    "list_reminders",
    "query_service_logs",
    "recall",
    "search_conversations",
    "search_docs",
    "search_memory",
    "semantic_recall",
    "serpapi_ebay_product",
    "serpapi_ebay_search",
    "serpapi_home_depot",
    "serpapi_hotel_search",
    "serpapi_maps_search",
    "serpapi_amazon_search",
    "serpapi_search_index",
    "serpapi_tripadvisor",
    "serpapi_yelp_search",
    "serpapi_youtube",
    "serpapi_youtube_search",
    "stock_price",
    "supa_crawl_knowledge",
    "system_monitor",
    "tool_search",
    "weather",
}

DEFAULT_ALLOWED_TOOL_PREFIXES = (
    "mcp_brave_search_",
    "mcp_fetch_",
)

# Queries should stay read-mostly even if the app supports rich actions.
UNSAFE_QUERY_PREFIXES = (
    "play ",
    "send ",
    "email ",
    "call ",
    "text ",
    "create ",
    "make ",
    "build ",
    "write ",
    "schedule ",
    "set ",
    "save ",
    "remember ",
    "print ",
    "generate ",
    "open ",
    "launch ",
)

# Query categories with examples for LLM to generate variations
QUERY_CATEGORIES = {
    "information": {
        "examples": [
            "What's the population of France?",
            "How far is Mars from Earth?",
            "How many calories are in an avocado?",
            "What's the capital of New Zealand?",
            "How many kilometers are in 25 miles?",
        ],
        "weight": 0.15,
        "description": "Objective factual questions, definitions, and calculations",
    },
    "live_data": {
        "examples": [
            "What's the weather forecast for today?",
            "Current Bitcoin price",
            "What time is it in Tokyo?",
            "What's the current unemployment rate in the US?",
            "How is Tesla stock doing today?",
        ],
        "weight": 0.20,
        "description": "Time-sensitive public data that should use live search or live-data tools",
    },
    "research": {
        "examples": [
            "Compare PostgreSQL vs MySQL for web apps",
            "What are the pros and cons of Kubernetes?",
            "Latest trends in machine learning",
            "Best practices for API design",
            "Differences between REST and GraphQL",
        ],
        "weight": 0.20,
        "description": "Research, comparisons, and explanatory questions",
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
            "Do I have any pending reminders?",
            "Are there any active alerts right now?",
            "What did I ask you about yesterday?",
            "What do you know about my projects?",
            "Search my memories for API",
            "What recent conversations have I had about Spotify?",
        ],
        "weight": 0.15,
        "description": "Personal productivity and memory SEARCH queries (read-only)",
    },
    "general": {
        "examples": [
            "Tell me something interesting",
            "What's the capital of Australia?",
            "How does a rainbow form?",
            "Who invented the telephone?",
            "What's a good book recommendation?",
        ],
        "weight": 0.05,
        "description": "General knowledge and trivia",
    },
    "media": {
        "examples": [
            "What's new on Netflix this weekend?",
            "What's coming to Hulu this month?",
            "What sci-fi shows are trending on Apple TV Plus right now?",
            "What new documentaries are on Max this week?",
            "What are the biggest streaming releases this weekend?",
        ],
        "weight": 0.10,
        "description": "Streaming-release and entertainment lookup questions (no playback or creation actions)",
    },
    "system_status": {
        "examples": [
            "How much RAM is the machine using right now?",
            "What's the CPU usage at the moment?",
            "Any disk space issues I should know about?",
            "How long has this system been up?",
            "Show me the busiest processes right now.",
        ],
        "weight": 0.10,
        "description": "Read-only local system status and health checks",
    },
}

# Categories to EXCLUDE from self-play (these have real side effects)
EXCLUDED_CATEGORIES = [
    "email",       # Don't send real emails
    "reminder",    # Don't create real reminders  
    "webhook",     # Don't trigger real webhooks
    "alert",       # Don't send real alerts
]

# Categories to SKIP during self-play
# Edit this list based on your setup
DISABLED_CATEGORIES = [
    "coding",           # Risk of triggering opencode builds - use --categories to re-enable
    # "productivity",   # Uncomment if no calendar integration
    # "media",          # Uncomment if no media tools  
]


@dataclass
class QueryResult:
    """Result of executing a single query."""
    query: str
    category: str
    response: str
    tools_used: list[str]
    duration_ms: float
    ok: bool
    error: str | None = None
    feedback: dict[str, Any] | None = None


@dataclass
class FeedbackResult:
    """Result of feedback grading."""
    rating: int
    summary: str
    tool_ratings: dict[str, dict[str, Any]]
    issues: list[dict[str, Any]]


@dataclass 
class ToolGap:
    """Identified gap where a dedicated tool would help."""
    pattern: str
    query_count: int
    example_queries: list[str]
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
    tool_gaps: list[ToolGap]
    evolution_triggered: bool
    duration_seconds: float
    results: list[dict[str, Any]]


class SelfPlayEngine:
    """Engine for running self-play sessions."""
    
    def __init__(self, mode: str = "cloud"):
        self.mode = mode
        self.project_root = Path(__file__).parent.parent
        self.logs_dir = self.project_root / "logs" / "self-play"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        with config_scope(mode):
            self.excluded_tools = self._get_excluded_tools()

    @classmethod
    def session_reader(cls, mode: str = "cloud") -> "SelfPlayEngine":
        """Create a log-only instance without loading provider/tool execution state."""
        engine = cls.__new__(cls)
        engine.mode = mode
        engine.project_root = Path(__file__).parent.parent
        engine.logs_dir = engine.project_root / "logs" / "self-play"
        engine.logs_dir.mkdir(parents=True, exist_ok=True)
        engine.excluded_tools = []
        return engine

    def _get_excluded_tools(self) -> list[str]:
        """Get the default self-play tool denylist plus any dangerous tools."""
        excluded = set(DEFAULT_EXCLUDED_TOOLS)

        extra_excluded = get_config_value("SELF_PLAY_EXCLUDED_TOOLS", "")
        if extra_excluded:
            excluded.update(t.strip() for t in extra_excluded.split(",") if t.strip())

        extra_allowed = {
            name.strip()
            for name in get_config_value("SELF_PLAY_ALLOWED_TOOLS", "").split(",")
            if name.strip()
        }
        allowed = DEFAULT_ALLOWED_TOOLS | extra_allowed

        try:
            from tool_schema import ToolRegistry

            mcp_config = str(self.project_root / "config" / "mcp-servers.json")
            registry = ToolRegistry(str(self.project_root / "skills"), mcp_config)
            for tool_name in registry.list_tools():
                tool = registry.get_tool(tool_name)
                explicitly_safe = tool_name in allowed or tool_name.startswith(DEFAULT_ALLOWED_TOOL_PREFIXES)
                dangerous = bool(tool and tool.permissions.get("dangerous", False))
                if dangerous or not explicitly_safe:
                    excluded.add(tool_name)
        except Exception as exc:
            raise RuntimeError(
                "Self-play safety registry failed to initialize; refusing to run fail-open"
            ) from exc

        return sorted(excluded)

    def _is_safe_query(self, query: str) -> bool:
        """Heuristic filter to keep self-play read-mostly and avoid real actions."""
        q = (query or "").strip().lower()
        if not q:
            return False

        if q.startswith(UNSAFE_QUERY_PREFIXES):
            return False

        blocked_fragments = [
            " on spotify",
            "send an email",
            "send me an email",
            "call my",
            "call ",
            "text ",
            "create a reminder",
            "set a reminder",
            "schedule a task",
            "save this",
            "remember this",
            "open canvas",
            "make a canvas",
            "print this",
            "generate an image",
            "generate a video",
            "generate music",
            "build an app",
            "write code",
        ]
        return not any(fragment in q for fragment in blocked_fragments)

    def _generate_query_text(self, provider, prompt: str) -> str:
        """Run generation inside the selected mode's immutable config scope."""
        with config_scope(self.mode):
            return provider.chat(message=prompt, max_tokens=1000)
        
    def generate_queries(self, num_queries: int, categories: list[str] | None = None) -> list[dict[str, str]]:
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
3. NEVER include queries that create real artifacts or side effects:
   - NO emails, reminders, webhooks, alerts
   - NO "build", "create", "write code", "make an app" (triggers real code generation)
   - NO canvas, pages, documents, notes creation
   - NO printing or PDF generation
   - NO saving or remembering things
4. ONLY include READ-ONLY queries: searching, asking questions, playing media, lookups
4. ONLY include READ-ONLY queries: searching, asking questions, recommendations, comparisons, lookups
   - Do NOT ask Jarvis to actually play, call, send, schedule, print, save, generate, or create anything
5. Keep them reasonable - things a real person would ask
6. Prefer objective, verifiable questions over subjective taste-based prompts
7. For media, prefer release/date/trending lookups over "recommend something like X"
8. Output ONLY the queries, one per line, no numbering or bullets

Generate {count} queries:"""

            try:
                response = self._generate_query_text(provider, prompt)
                
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
                    if line and self._is_safe_query(line):
                        all_queries.append({
                            "query": line,
                            "category": category,
                        })
                        
            except Exception as e:
                # Fallback to examples if LLM fails
                print(f"Warning: LLM query generation failed for {category}: {e}", file=sys.stderr)
                for i in range(min(count, len(examples))):
                    if self._is_safe_query(examples[i]):
                        all_queries.append({
                            "query": examples[i],
                            "category": category,
                        })
        
        # Backfill if filtering removed unsafe queries.
        if len(all_queries) < num_queries:
            safe_examples = []
            for category, cat_info in QUERY_CATEGORIES.items():
                if category in categories:
                    safe_examples.extend(
                        {"query": ex, "category": category}
                        for ex in cat_info["examples"]
                        if self._is_safe_query(ex)
                    )
            random.shuffle(safe_examples)
            for item in safe_examples:
                if len(all_queries) >= num_queries:
                    break
                if item not in all_queries:
                    all_queries.append(item)

        # Shuffle to mix categories
        random.shuffle(all_queries)
        
        return all_queries[:num_queries]
    
    def execute_query(self, query: str, category: str, silent: bool = True, collect_feedback: bool = True) -> QueryResult:
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
            env = export_config_environment(self.mode)
            env["JARVIS_SELF_PLAY"] = "true"  # Flag for tracking
            env["JARVIS_SELF_PLAY_EXCLUDED_TOOLS"] = ",".join(self.excluded_tools)
            if silent:
                env["JARVIS_TTS_DISABLED"] = "true"
            
            cmd = [sys.executable, str(orchestrator_path), self.mode, query, "--json"]
            if collect_feedback:
                cmd.append("--feedback")

            result = subprocess.run(
                cmd,
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
                    feedback=response_data.get("feedback"),
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
                    feedback=None,
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
                feedback=None,
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
                feedback=None,
            )
    
    def analyze_tool_gaps(self, results: list[dict[str, Any]]) -> list[ToolGap]:
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
        categories: list[str] | None = None,
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
            query_result = self.execute_query(
                q["query"],
                q["category"],
                silent=silent,
                collect_feedback=collect_feedback,
            )
            
            result_data = {
                "query": q["query"],
                "category": q["category"],
                "response": query_result.response,
                "tools_used": query_result.tools_used,
                "duration_ms": query_result.duration_ms,
                "ok": query_result.ok,
                "error": query_result.error,
            }
            
            # Orchestrator-native feedback (keeps self-play aligned with current CLI behavior)
            if collect_feedback and query_result.ok and query_result.feedback:
                result_data["feedback"] = query_result.feedback
                rating = query_result.feedback.get("rating")
                if rating is not None:
                    ratings.append(rating)
            
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
        with config_scope(self.mode):
            _, _, provider = create_configured_provider(
                default_provider="ollama" if self.mode == "local" else "anthropic",
                mode=self.mode,
            )
            return provider
    
    def _log_result(self, session_id: str, result: dict[str, Any]):
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
    
    def get_latest_session(self) -> dict[str, Any] | None:
        """Get the most recent session summary."""
        session_files = sorted(self.logs_dir.glob("session-*.json"), reverse=True)
        
        if session_files:
            with open(session_files[0]) as f:
                return json.load(f)
        return None
    
    def list_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
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
