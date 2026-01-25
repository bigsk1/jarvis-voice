#!/usr/bin/env python3
"""
Jarvis Intelligence Layer

Self-learning, reflective intelligence system that learns from experience.

Key Principles:
- Everything is a vector (continuous, not discrete)
- Learning generalizes through embedding similarity
- Reflection extracts insights, not just scores
- Resilient to outliers and bad sessions
- Meta-cognition evaluates the learning process

Usage:
    from intelligence import IntelligenceLayer
    
    intel = IntelligenceLayer()
    
    # Record an experience
    await intel.record_experience(
        query="Is my server running?",
        tools_used=["search_memory", "mcp_fetch"],
        outcome={"answered": True, "turns": 2},
        user_signals={"clarified": False}
    )
    
    # Get learned insights for a new query
    insights = await intel.get_relevant_insights("Check if Ollama is up")
"""

import os
import sys
import json
import sqlite3
import pickle
import hashlib
from datetime import datetime, timedelta
from typing import Any
from pathlib import Path
import numpy as np
import logging

# Add lib to path
sys.path.insert(0, os.path.dirname(__file__))
from config_loader import load_config, get_float, get_int

logger = logging.getLogger(__name__)


class IntelligenceLogger:
    """Dedicated logger for intelligence layer operations."""
    
    def __init__(self):
        self.project_root = Path(__file__).parent.parent
        self.log_dir = self.project_root / "logs" / "intelligence"
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_log_file(self) -> Path:
        """Get today's log file."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        return self.log_dir / f"intelligence-{date_str}.jsonl"
    
    def log(self, event_type: str, data: dict[str, Any]):
        """Log an intelligence event."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event": event_type,
            **data
        }
        
        try:
            with open(self._get_log_file(), "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write intelligence log: {e}")
    
    def log_experience_recorded(self, exp_id: int, query: str, tools: list[str], success: bool):
        """Log when an experience is recorded."""
        self.log("experience_recorded", {
            "experience_id": exp_id,
            "query": query[:200],
            "tools_used": tools,
            "success": success
        })
    
    def log_reflection_started(self, exp_id: int, query: str):
        """Log when reflection starts."""
        self.log("reflection_started", {
            "experience_id": exp_id,
            "query": query[:200]
        })
    
    def log_reflection_prompt(self, exp_id: int, prompt: str):
        """Log the reflection prompt sent to LLM."""
        self.log("reflection_prompt", {
            "experience_id": exp_id,
            "prompt_preview": prompt[:500],
            "prompt_length": len(prompt)
        })
    
    def log_reflection_response(self, exp_id: int, response: dict[str, Any], provider: str, model: str):
        """Log the reflection response from LLM."""
        self.log("reflection_response", {
            "experience_id": exp_id,
            "provider": provider,
            "model": model,
            "response": response
        })
    
    def log_insight_created(self, insight_id: int, constraint_type: str, description: str, confidence: float):
        """Log when a new insight is created."""
        self.log("insight_created", {
            "insight_id": insight_id,
            "constraint_type": constraint_type,
            "description": description[:200],
            "confidence": confidence
        })
    
    def log_decay_applied(self, insight_id: int, old_confidence: float, new_confidence: float, 
                          days_since_applied: int, reason: str):
        """Log when confidence decay is applied to an insight."""
        self.log("decay_applied", {
            "insight_id": insight_id,
            "old_confidence": round(old_confidence, 4),
            "new_confidence": round(new_confidence, 4),
            "decay_amount": round(old_confidence - new_confidence, 4),
            "days_since_applied": days_since_applied,
            "reason": reason
        })
    
    def log_anomaly_detected(self, experience_id: int, anomaly_type: str, details: dict[str, Any]):
        """Log when an anomaly is detected in an experience."""
        self.log("anomaly_detected", {
            "experience_id": experience_id,
            "anomaly_type": anomaly_type,
            "details": details
        })
    
    def log_meta_cognition(self, meta_type: str, observation: str, conclusion: str, 
                           action: str, confidence: float):
        """Log meta-cognition findings."""
        self.log("meta_cognition", {
            "meta_type": meta_type,
            "observation": observation,
            "conclusion": conclusion,
            "action_taken": action,
            "confidence": confidence
        })
    
    def log_maintenance_run(self, job_type: str, stats: dict[str, Any]):
        """Log when a maintenance job runs."""
        self.log("maintenance_run", {
            "job_type": job_type,
            "stats": stats
        })
    
    def log_insight_pruned(self, insight_id: int, description: str, reason: str, 
                           final_confidence: float):
        """Log when an insight is pruned/removed."""
        self.log("insight_pruned", {
            "insight_id": insight_id,
            "description": description[:200],
            "reason": reason,
            "final_confidence": final_confidence
        })
    
    def log_insight_updated(self, insight_id: int, old_confidence: float, new_confidence: float):
        """Log when an existing insight is updated."""
        self.log("insight_updated", {
            "insight_id": insight_id,
            "old_confidence": old_confidence,
            "new_confidence": new_confidence
        })
    
    def log_insights_applied(self, query: str, insights: list[dict], biases: dict[str, float]):
        """Log when insights are applied to routing."""
        self.log("insights_applied", {
            "query": query[:200],
            "insights_count": len(insights),
            "insights": [{"id": i.get("id"), "relevance": i.get("relevance")} for i in insights[:5]],
            "tool_biases": biases
        })
    
    def log_insight_skipped(self, reason: str, details: str):
        """Log when an insight is not stored (factual, low generalizability, etc.)"""
        self.log("insight_skipped", {
            "reason": reason,
            "details": details[:200]
        })


# Global intelligence logger instance
_intel_logger = None

def get_intel_logger() -> IntelligenceLogger:
    """Get the intelligence logger instance."""
    global _intel_logger
    if _intel_logger is None:
        _intel_logger = IntelligenceLogger()
    return _intel_logger


class IntelligenceLayer:
    """
    Self-learning intelligence that operates in continuous vector space.
    
    Architecture:
    1. Experience Memory - Raw experiences with embeddings
    2. Insight Memory - Generalized learnings from reflection
    3. Meta Memory - Knowledge about the learning process itself
    """
    
    def __init__(self, db_path: str = None):
        """Initialize the intelligence layer."""
        load_config()
        
        if db_path is None:
            project_root = Path(__file__).parent.parent.resolve()
            data_dir = project_root / "data"
            data_dir.mkdir(exist_ok=True)
            
            # Use same DB selection logic as memory_db
            llm_provider = os.environ.get('LLM_PROVIDER', 'anthropic').lower()
            if llm_provider == 'ollama':
                db_path = str(data_dir / "jarvis_intelligence_local.db")
            else:
                db_path = str(data_dir / "jarvis_intelligence.db")
        
        self.db_path = db_path
        self.conn = None
        self._embedding_cache = {}
        self._init_db()
        
        # Learning parameters
        self.learning_rate = get_float('INTELLIGENCE_LEARNING_RATE', 0.1)
        self.decay_rate = get_float('INTELLIGENCE_DECAY_RATE', 0.95)
        self.anomaly_threshold = get_float('INTELLIGENCE_ANOMALY_THRESHOLD', 2.5)
        self.min_confidence = get_float('INTELLIGENCE_MIN_CONFIDENCE', 0.3)
        self.negative_weight = get_float('INTELLIGENCE_NEGATIVE_WEIGHT', 1.0)  # Multiplier for negative constraints
    
    def _init_db(self):
        """Initialize intelligence database with experience and insight tables."""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.cursor()
        
        # ============================================
        # EXPERIENCE MEMORY
        # Raw experiences from each interaction
        # ============================================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS experiences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                -- The interaction
                query TEXT NOT NULL,
                query_embedding BLOB,
                context_summary TEXT,
                context_embedding BLOB,
                
                -- What happened
                tools_used TEXT,  -- JSON list
                tool_sequence TEXT,  -- Order matters: ["tool1", "tool2"]
                turns_taken INTEGER,
                final_tool TEXT,  -- The tool that actually answered
                
                -- Outcome signals
                outcome_success BOOLEAN,
                user_satisfied BOOLEAN,  -- Inferred from signals
                had_to_retry BOOLEAN,
                had_to_clarify BOOLEAN,
                error_occurred BOOLEAN,
                
                -- Rich outcome embedding (captures the "feeling" of the outcome)
                outcome_embedding BLOB,
                
                -- Raw data for later analysis
                raw_data TEXT  -- JSON blob of everything
            )
        """)
        
        # ============================================
        # INSIGHT MEMORY
        # Generalized learnings from reflection
        # ============================================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                -- The insight itself
                insight_type TEXT,  -- 'tool_preference', 'query_pattern', 'error_pattern', 'macro_skill'
                description TEXT,  -- Natural language description
                insight_embedding BLOB,
                
                -- PHASE 1: Constraint type (positive vs negative)
                constraint_type TEXT DEFAULT 'positive',  -- 'positive' = DO USE, 'negative' = DO NOT USE
                
                -- What this insight applies to
                applies_to_pattern TEXT,  -- e.g., "status queries", "memory lookups"
                pattern_embedding BLOB,
                trigger_concept TEXT,  -- Specific concept that triggers this insight
                
                -- Learned associations
                preferred_tools TEXT,  -- JSON: {"mcp_fetch": 0.8, "search_memory": 0.3}
                avoided_tools TEXT,  -- JSON: ["search_memory"] - tools to explicitly avoid
                avoided_patterns TEXT,  -- JSON list of patterns to avoid
                
                -- PHASE 1: Quality filters
                generalizability TEXT DEFAULT 'medium',  -- 'high', 'medium', 'low' (filter out 'low')
                reasoning TEXT,  -- Why this insight was learned
                
                -- Confidence and strength
                confidence REAL DEFAULT 0.5,  -- 0.0 to 1.0
                strength REAL DEFAULT 0.5,  -- How strongly to apply this
                evidence_count INTEGER DEFAULT 1,  -- How many experiences support this
                
                -- PHASE 1: Decay tracking
                last_applied TIMESTAMP,
                last_outcome TEXT,  -- 'success', 'failure', 'unused'
                times_applied INTEGER DEFAULT 0,
                times_helpful INTEGER DEFAULT 0,  -- When applied, was it helpful?
                times_failed INTEGER DEFAULT 0,  -- When applied, did it fail?
                consecutive_failures INTEGER DEFAULT 0  -- For rapid decay on repeated failures
            )
        """)
        
        # ============================================
        # META MEMORY
        # Knowledge about the learning process
        # ============================================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS meta_knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                -- What meta-knowledge is this?
                meta_type TEXT,  -- 'learning_quality', 'blind_spot', 'over_generalization'
                description TEXT,
                
                -- Self-assessment
                observation TEXT,  -- What was observed
                conclusion TEXT,  -- What was concluded
                action_taken TEXT,  -- What adjustment was made
                
                -- Tracking
                confidence REAL DEFAULT 0.5,
                validated BOOLEAN DEFAULT 0
            )
        """)
        
        # ============================================
        # REFLECTION QUEUE
        # Experiences waiting for reflection
        # ============================================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reflection_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experience_id INTEGER,
                priority REAL DEFAULT 0.5,
                queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed BOOLEAN DEFAULT 0,
                FOREIGN KEY (experience_id) REFERENCES experiences(id)
            )
        """)
        
        # Indexes for efficient queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_exp_timestamp ON experiences(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_insight_type ON insights(insight_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_insight_confidence ON insights(confidence)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reflection_pending ON reflection_queue(processed, priority)")
        
        # PHASE 1: Schema migration for existing databases
        self._migrate_schema(cursor)
        
        self.conn.commit()
    
    def _migrate_schema(self, cursor):
        """Add new columns to existing databases (PHASE 1 upgrades)."""
        # Get existing columns in insights table
        cursor.execute("PRAGMA table_info(insights)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        
        # New columns to add
        new_columns = [
            ("constraint_type", "TEXT DEFAULT 'positive'"),
            ("trigger_concept", "TEXT"),
            ("avoided_tools", "TEXT"),
            ("generalizability", "TEXT DEFAULT 'medium'"),
            ("reasoning", "TEXT"),
            ("last_outcome", "TEXT"),
            ("times_failed", "INTEGER DEFAULT 0"),
            ("consecutive_failures", "INTEGER DEFAULT 0"),
        ]
        
        for col_name, col_def in new_columns:
            if col_name not in existing_columns:
                try:
                    cursor.execute(f"ALTER TABLE insights ADD COLUMN {col_name} {col_def}")
                    logger.info(f"Added column {col_name} to insights table")
                except sqlite3.OperationalError as e:
                    # Column might already exist or other issue
                    logger.debug(f"Could not add column {col_name}: {e}")
    
    # ============================================
    # EMBEDDING UTILITIES
    # ============================================
    
    def _get_embedding(self, text: str) -> np.ndarray | None:
        """Get embedding for text, with caching."""
        if not text or not text.strip():
            return None
        
        # Check cache
        cache_key = hashlib.md5(text.encode()).hexdigest()
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]
        
        try:
            # Import embedding function from existing infrastructure
            from embeddings import get_embedding
            embedding = get_embedding(text)
            
            if embedding is not None:
                self._embedding_cache[cache_key] = np.array(embedding)
                return self._embedding_cache[cache_key]
        except Exception as e:
            logger.warning(f"Failed to get embedding: {e}")
        
        return None
    
    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        if a is None or b is None:
            return 0.0
        
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(np.dot(a, b) / (norm_a * norm_b))
    
    def _serialize_embedding(self, embedding: np.ndarray) -> bytes:
        """Serialize numpy array for database storage."""
        if embedding is None:
            return None
        return pickle.dumps(embedding)
    
    def _deserialize_embedding(self, blob: bytes) -> np.ndarray | None:
        """Deserialize numpy array from database.
        
        Handles both JSON format (newer) and pickle format (older).
        CRITICAL: Must catch UnicodeDecodeError for pickle blobs!
        """
        if blob is None:
            return None
        
        # Try JSON first (newer format)
        try:
            return np.array(json.loads(blob.decode('utf-8')))
        except (json.JSONDecodeError, AttributeError, UnicodeDecodeError):
            # Fall back to pickle (older format)
            return pickle.loads(blob)
    
    # ============================================
    # EXPERIENCE RECORDING
    # ============================================
    
    async def record_experience(
        self,
        query: str,
        tools_used: list[str],
        outcome: dict[str, Any],
        context: dict[str, Any] | None = None,
        user_signals: dict[str, Any] | None = None
    ) -> int:
        """
        Record a complete experience for later reflection.
        
        Args:
            query: The user's original query
            tools_used: List of tools invoked (in order)
            outcome: Dict with keys like 'success', 'turns', 'error', etc.
            context: Optional context about the conversation state
            user_signals: Optional signals like 'thanked', 'clarified', 'retried'
        
        Returns:
            Experience ID
        """
        user_signals = user_signals or {}
        context = context or {}
        
        # Generate embeddings
        query_embedding = self._get_embedding(query)
        
        # Create rich outcome description for embedding
        outcome_description = self._describe_outcome(query, tools_used, outcome, user_signals)
        outcome_embedding = self._get_embedding(outcome_description)
        
        # Context embedding
        context_summary = json.dumps(context)[:750] if context else ""
        context_embedding = self._get_embedding(context_summary) if context_summary else None
        
        # Infer satisfaction
        user_satisfied = self._infer_satisfaction(outcome, user_signals)
        
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO experiences (
                query, query_embedding, context_summary, context_embedding,
                tools_used, tool_sequence, turns_taken, final_tool,
                outcome_success, user_satisfied, had_to_retry, had_to_clarify,
                error_occurred, outcome_embedding, raw_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            query,
            self._serialize_embedding(query_embedding),
            context_summary,
            self._serialize_embedding(context_embedding),
            json.dumps(tools_used),
            json.dumps(tools_used),  # sequence same as tools_used for now
            outcome.get('turns', len(tools_used)),
            tools_used[-1] if tools_used else None,
            outcome.get('success', True),
            user_satisfied,
            user_signals.get('retried', False),
            user_signals.get('clarified', False),
            outcome.get('error', False),
            self._serialize_embedding(outcome_embedding),
            json.dumps({
                'query': query,
                'tools_used': tools_used,
                'outcome': outcome,
                'context': context,
                'user_signals': user_signals,
                'timestamp': datetime.now().isoformat()
            })
        ))
        
        experience_id = cursor.lastrowid
        
        # Queue for reflection with priority based on learning value
        priority = self._calculate_learning_priority(outcome, user_signals, tools_used)
        cursor.execute("""
            INSERT INTO reflection_queue (experience_id, priority)
            VALUES (?, ?)
        """, (experience_id, priority))
        
        self.conn.commit()
        
        logger.info(f"Recorded experience {experience_id} with priority {priority:.2f}")
        
        # Log to intelligence log
        get_intel_logger().log_experience_recorded(
            exp_id=experience_id,
            query=query,
            tools=tools_used,
            success=outcome.get('success', True)
        )
        
        return experience_id
    
    def _describe_outcome(
        self,
        query: str,
        tools_used: list[str],
        outcome: dict[str, Any],
        user_signals: dict[str, Any]
    ) -> str:
        """Create a rich natural language description of what happened."""
        parts = []
        
        # Query type
        parts.append(f"User asked: {query[:100]}")
        
        # Tool journey
        if len(tools_used) == 1:
            parts.append(f"Answered in one turn using {tools_used[0]}")
        elif len(tools_used) > 1:
            parts.append(f"Took {len(tools_used)} turns: {' → '.join(tools_used)}")
        
        # Outcome
        if outcome.get('success'):
            parts.append("Task completed successfully")
        else:
            parts.append(f"Task failed: {outcome.get('error', 'unknown error')}")
        
        # User signals
        if user_signals.get('thanked'):
            parts.append("User expressed satisfaction")
        if user_signals.get('clarified'):
            parts.append("User had to clarify their request")
        if user_signals.get('retried'):
            parts.append("User had to retry")
        
        return ". ".join(parts)
    
    def _infer_satisfaction(
        self,
        outcome: dict[str, Any],
        user_signals: dict[str, Any]
    ) -> bool:
        """Infer whether the user was satisfied."""
        # Positive signals
        if user_signals.get('thanked'):
            return True
        
        # Negative signals
        if user_signals.get('retried') or user_signals.get('clarified'):
            return False
        
        # Default to success status
        return outcome.get('success', True)
    
    def _calculate_learning_priority(
        self,
        outcome: dict[str, Any],
        user_signals: dict[str, Any],
        tools_used: list[str]
    ) -> float:
        """
        Calculate how valuable this experience is for learning.
        
        High priority:
        - Failures (we learn more from mistakes)
        - Multi-turn journeys (shows what didn't work)
        - User clarifications (misunderstanding occurred)
        
        Lower priority:
        - Clean single-turn successes (not much to learn)
        """
        priority = 0.5  # Base
        
        # Failures are valuable learning opportunities
        if not outcome.get('success', True):
            priority += 0.3
        
        # Multi-turn suggests initial approach was wrong
        turns = outcome.get('turns', len(tools_used))
        if turns > 1:
            priority += min(0.2, (turns - 1) * 0.05)
        
        # User had to clarify = we misunderstood
        if user_signals.get('clarified'):
            priority += 0.2
        
        # User retried = we failed them
        if user_signals.get('retried'):
            priority += 0.25
        
        # Cap at 1.0
        return min(1.0, priority)
    
    # ============================================
    # REFLECTION ENGINE
    # ============================================
    
    async def reflect_on_experience(
        self,
        experience_id: int,
        use_sequential_thinking: bool = True
    ) -> dict[str, Any] | None:
        """
        Deeply reflect on an experience to extract insights.
        
        This is where the magic happens - we don't just score,
        we think about WHY things happened.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM experiences WHERE id = ?", (experience_id,))
        exp = cursor.fetchone()
        
        if not exp:
            return None
        
        # Build reflection prompt
        raw_data = json.loads(exp['raw_data'])
        context_data = raw_data.get('context', {})
        
        # Extract LLM response and tool results for content evaluation
        llm_response = context_data.get('llm_response', '[Not captured]')
        tool_results = context_data.get('tool_results', '[Not captured]')
        
        # CRITICAL: What tools were AVAILABLE to the LLM (from Tool RAG + ghost tools)
        available_tools = context_data.get('available_tools', [])
        
        # Determine if this was a suboptimal experience
        tools_list = json.loads(exp['tools_used'])
        (
            len(tools_list) > 1 or 
            not exp['outcome_success'] or 
            exp['had_to_retry'] or 
            exp['had_to_clarify']
        )
        
        # Format available tools list
        available_tools_str = ', '.join(available_tools) if available_tools else '[Not captured]'
        tools_used_list = json.loads(exp['tools_used']) if exp['tools_used'] else []
        
        # Identify tools that were available but NOT used (for reflection analysis)
        unused_tools = [t for t in available_tools if t not in tools_used_list] if available_tools else []
        unused_tools_str = ', '.join(unused_tools[:10]) if unused_tools else 'None'  # Limit to 10
        
        reflection_prompt = f"""
Analyze this interaction to extract a PROCEDURAL insight (not a fact).

**User Query**: {exp['query']}

**AVAILABLE TOOLS** (what the LLM could choose from):
{available_tools_str}

**Tools Actually Used (in order)**: {exp['tools_used']}
**Tools Available But NOT Used**: {unused_tools_str}
**Turns Taken**: {exp['turns_taken']}
**Final Tool**: {exp['final_tool']}
**Outcome Status**: {"SUCCESS" if exp['outcome_success'] else "FAILURE"}
**User Satisfied**: {exp['user_satisfied']}
**Had to Clarify**: {exp['had_to_clarify']}
**Had to Retry**: {exp['had_to_retry']}

**Tool Results** (what the tools returned):
{tool_results[:1500] if tool_results != '[Not captured]' else '[Not available]'}

**LLM Response** (what was said to the user):
{llm_response[:1000] if llm_response != '[Not captured]' else '[Not available]'}

CRITICAL EVALUATION:
1. Did the tool(s) return relevant data for the query? (tool_results vs query)
2. Did the LLM response accurately reflect the tool data? (llm_response vs tool_results)
3. Did the LLM response actually answer what the user asked? (llm_response vs query)
4. Was the FIRST tool the optimal choice, or should a different tool have been used initially?

TOOL CATEGORIES (for understanding what tools do):
- **MEMORY TOOLS** (check stored knowledge): search_memory, recall, semantic_recall, get_recent_conversations, search_conversations
- **ACTION TOOLS** (do something live): mcp_fetch_fetch, execute_bash, api_call, send_webhook, send_email
- **STORAGE TOOLS** (save info): remember, update_memory, forget
- **UTILITY TOOLS** (simple tasks): get_time, crypto_price, list_reminders, list_alerts
- **SEARCH TOOLS** (web search): mcp_brave_search_*, mcp_duckduckgo_*
- **BUILD TOOLS** (create projects): opencode

SYSTEM RULES THE LLM SHOULD HAVE FOLLOWED:
- **MEMORY-FIRST RULE**: For questions about user's info, servers, configs, preferences → SHOULD check memory FIRST
- If query mentions a server IP/service → memory might have stored health check commands with CORRECT details
- If query asks about "my X" or personal info → memory likely has stored preferences
- Using ACTION TOOLS before MEMORY TOOLS violates system rules for personal/stored data queries
- If memory search was skipped but query was about stored knowledge → first_tool_optimal = FALSE

CRITICAL: Look for signs the user-provided info might be WRONG:
- If a connection/fetch failed → memory might have the CORRECT endpoint stored
- If user says "my server at X" but X fails → the stored server might be at a DIFFERENT address
- A "not running" result could actually mean "wrong IP" if memory wasn't checked first
- When something FAILS and memory wasn't checked → strongly consider first_tool_optimal = FALSE

RESULT-BASED EVALUATION (most important):
- 1 tool used + good result = likely optimal first choice
- Multiple tools + had to retry = first tool probably suboptimal
- Action tool first + connection failed = should have checked memory
- Memory empty + action succeeded = action was correct fallback

IMPORTANT CLASSIFICATION:
- A FACT is data like "The server IP is 10.0.0.1" → belongs in Memory DB, NOT here
- A SKILL/PROCEDURE is "For status queries, use fetch tools" → belongs here

Your task: Extract a PROCEDURAL insight about TOOL SELECTION, not facts.

Provide your analysis as JSON:
```json
{{
    "is_procedural": true/false,  // Is this insight about tool selection strategy?
    "knowledge_type": "procedural" or "factual",  // If factual, we'll skip storing
    
    "insight_type": "routing_correction" or "tool_preference" or "query_pattern",
    "constraint_type": "positive" or "negative",  // "positive" = DO use this approach, "negative" = DO NOT use
    
    "trigger_concept": "the concept/topic that triggers this rule",
    "trigger_signals": ["specific", "words", "in query", "that signal this"],
    
    "first_tool_optimal": true/false,
    "why_or_why_not": "explanation of what went right or wrong",
    
    // CONTENT EVALUATION (new)
    "tool_returned_relevant_data": true/false,  // Did the tool return useful data for the query?
    "response_matched_tool_data": true/false,   // Did the LLM accurately use the tool's output?
    "response_answered_query": true/false,      // Did the final response actually answer the user's question?
    "content_quality_notes": "brief notes on response quality issues if any",
    
    "rule": "ALWAYS/NEVER + action + for + query type",  // e.g., "ALWAYS prefer crypto_price over search_memory for price queries"
    "preferred_tool": "tool_name" or null,  // The tool to use
    "avoided_tool": "tool_name" or null,  // The tool to avoid (for negative constraints)
    
    "applies_to": "category of queries this applies to",
    "generalizability": "high" or "medium" or "low",  // "low" insights won't be stored
    
    "confidence": 0.0-1.0,
    "insight_summary": "One actionable sentence, max 25 words"
}}
```

Example for POSITIVE constraint (what TO do):
```json
{{
    "is_procedural": true,
    "knowledge_type": "procedural",
    "insight_type": "routing_correction",
    "constraint_type": "positive",
    "trigger_concept": "server status",
    "trigger_signals": ["running", "up", "status", "alive"],
    "first_tool_optimal": false,
    "why_or_why_not": "search_memory returned stale data, mcp_fetch got live status",
    "rule": "ALWAYS use mcp_fetch_fetch for server status queries",
    "preferred_tool": "mcp_fetch_fetch",
    "avoided_tool": "search_memory",
    "applies_to": "System status and health check queries",
    "generalizability": "high",
    "confidence": 0.9,
    "insight_summary": "For server status queries, use mcp_fetch for real-time data."
}}
```

Example for NEGATIVE constraint (what NOT to do):
```json
{{
    "is_procedural": true,
    "knowledge_type": "procedural",
    "insight_type": "routing_correction",
    "constraint_type": "negative",
    "trigger_concept": "live data",
    "trigger_signals": ["current", "now", "live", "real-time"],
    "first_tool_optimal": false,
    "why_or_why_not": "search_memory returned outdated data from days ago",
    "rule": "NEVER use search_memory for queries requiring current/live data",
    "preferred_tool": null,
    "avoided_tool": "search_memory",
    "applies_to": "Any query requiring real-time information",
    "generalizability": "high",
    "confidence": 0.85,
    "insight_summary": "DO NOT use search_memory for real-time queries - data is stale."
}}
```

Example for FACTUAL (should NOT be stored here):
```json
{{
    "is_procedural": false,
    "knowledge_type": "factual",
    "insight_summary": "The Ollama server is at 192.168.70.226 - this is a fact, not a procedure"
}}
```
"""
        
        # Log reflection start
        intel_log = get_intel_logger()
        intel_log.log_reflection_started(experience_id, exp['query'])
        intel_log.log_reflection_prompt(experience_id, reflection_prompt)
        
        # Use sequential thinking MCP if available, otherwise direct LLM
        reflection = await self._think_deeply(reflection_prompt, use_sequential_thinking)
        
        if reflection:
            # Store the insight
            await self._store_insight(reflection, exp)
            
            # Mark as processed
            cursor.execute("""
                UPDATE reflection_queue 
                SET processed = 1 
                WHERE experience_id = ?
            """, (experience_id,))
            self.conn.commit()
        
        return reflection
    
    async def _think_deeply(
        self,
        prompt: str,
        use_sequential_thinking: bool = True
    ) -> dict[str, Any] | None:
        """
        Use sequential thinking MCP or direct LLM for deep reflection.
        """
        try:
            if use_sequential_thinking:
                # Try to use sequential thinking MCP
                reflection = await self._call_sequential_thinking(prompt)
                if reflection:
                    return reflection
            
            # Fallback to direct LLM call
            return await self._direct_llm_reflection(prompt)
            
        except Exception as e:
            logger.error(f"Reflection failed: {e}")
            return None
    
    async def _call_sequential_thinking(self, prompt: str) -> dict[str, Any] | None:
        """Call the sequential thinking MCP server for structured reasoning.
        
        NOTE: Sequential thinking MCP is optional - falls back to direct LLM if unavailable.
        Currently disabled until MCP client async support is fully implemented.
        """
        # TODO: Re-enable when MCP client supports async initialization properly
        # For now, return None to use direct LLM reflection (which works well)
        logger.debug("Sequential thinking MCP disabled - using direct LLM reflection")
        return None
        
        # Original implementation (disabled):
        # try:
        #     from mcp_client import MCPManager
        #     project_root = Path(__file__).parent.parent
        #     mcp_config_path = project_root / "config" / "mcp-servers.json"
        #     manager = MCPManager(str(mcp_config_path))
        #     if 'sequentialthinking' not in manager.servers:
        #         return None
        #     client = manager.servers['sequentialthinking']
        #     # MCP client doesn't have async initialize - needs refactoring
        #     ...
        # except Exception as e:
        #     logger.warning(f"Sequential thinking unavailable: {e}")
        # return None
    
    async def _direct_llm_reflection(self, prompt: str) -> dict[str, Any] | None:
        """Direct LLM call for reflection when sequential thinking unavailable."""
        try:
            from llm_provider import create_provider
            from config_loader import load_config, get_config_value
            
            # Ensure config is loaded
            load_config()
            
            # Create provider based on current mode (same logic as router_v2.py)
            provider_type = get_config_value('LLM_PROVIDER', 'anthropic')
            
            if provider_type == "openai":
                provider = create_provider(
                    "openai",
                    api_key=get_config_value("OPENAI_API_KEY"),
                    model=get_config_value("OPENAI_MODEL", "gpt-5.1")
                )
            elif provider_type == "anthropic":
                provider = create_provider(
                    "anthropic",
                    api_key=get_config_value("ANTHROPIC_API_KEY"),
                    model=get_config_value("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
                )
            elif provider_type == "xai":
                provider = create_provider(
                    "xai",
                    api_key=get_config_value("XAI_API_KEY"),
                    model=get_config_value("XAI_MODEL", "grok-4-1-fast-non-reasoning-latest")
                )
            elif provider_type == "ollama":
                provider = create_provider(
                    "ollama",
                    base_url=get_config_value("OLLAMA_BASE_URL", "http://localhost:11434"),
                    model=get_config_value("OLLAMA_MODEL", "qwen3:14b:latest")
                )
            else:
                logger.error(f"Unknown provider type: {provider_type}")
                return None
            
            # Get model name for logging
            model_name = getattr(provider, 'model', 'unknown')
            
            response = provider.chat(
                prompt,
                system_prompt="You are a self-reflective AI analyzing your own behavior to learn and improve. Output valid JSON only, no markdown formatting."
            )
            
            parsed = self._parse_reflection_output(response)
            
            # Log the reflection response
            get_intel_logger().log_reflection_response(
                exp_id=0,  # We don't have exp_id here, will be associated via timestamp
                response=parsed or {"raw": str(response)[:500]},
                provider=provider_type,
                model=model_name
            )
            
            return parsed
            
        except Exception as e:
            logger.error(f"Direct LLM reflection failed: {e}")
            get_intel_logger().log("reflection_error", {"error": str(e)})
        
        return None
    
    def _parse_reflection_output(self, output: Any) -> dict[str, Any] | None:
        """Parse reflection output, handling various formats."""
        if isinstance(output, dict):
            return output
        
        if isinstance(output, str):
            # Try to extract JSON from string
            try:
                # Look for JSON block
                import re
                json_match = re.search(r'```json\s*(.*?)\s*```', output, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group(1))
                
                # Try direct parse
                return json.loads(output)
            except json.JSONDecodeError:
                pass
        
        return None
    
    async def _store_insight(
        self,
        reflection: dict[str, Any],
        experience: sqlite3.Row
    ) -> int:
        """Store a new insight or update existing similar insight.
        
        PHASE 1 UPGRADES:
        - Filter out factual knowledge (only store procedural)
        - Filter out low generalizability insights
        - Track constraint_type (positive/negative)
        - Track avoided_tools for negative constraints
        """
        
        intel_log = get_intel_logger()
        
        # PHASE 1: Filter out factual knowledge
        if not reflection.get('is_procedural', True):
            logger.info(f"Skipping factual insight: {reflection.get('insight_summary', '')[:50]}")
            intel_log.log_insight_skipped("factual", reflection.get('insight_summary', ''))
            return 0
        
        if reflection.get('knowledge_type') == 'factual':
            logger.info(f"Skipping factual knowledge (belongs in memory_db)")
            intel_log.log_insight_skipped("factual_knowledge_type", reflection.get('insight_summary', ''))
            return 0
        
        # PHASE 1: Filter out low generalizability
        generalizability = reflection.get('generalizability', 'medium')
        if generalizability == 'low':
            logger.info(f"Skipping low-generalizability insight: {reflection.get('insight_summary', '')[:50]}")
            intel_log.log_insight_skipped("low_generalizability", reflection.get('insight_summary', ''))
            return 0
        
        insight_text = reflection.get('insight_summary', reflection.get('rule', reflection.get('pattern', '')))
        if not insight_text:
            return 0
        
        # Extract constraint type
        constraint_type = reflection.get('constraint_type', 'positive')
        
        # Generate embeddings
        insight_embedding = self._get_embedding(insight_text)
        pattern_text = reflection.get('applies_to', '')
        pattern_embedding = self._get_embedding(pattern_text) if pattern_text else None
        trigger_concept = reflection.get('trigger_concept', '')
        
        # Check for similar existing insights
        similar = await self._find_similar_insights(insight_embedding, threshold=0.85)
        
        cursor = self.conn.cursor()
        
        if similar:
            # Update existing insight (blend, don't replace)
            existing = similar[0]
            new_confidence = self._blend_confidence(
                existing['confidence'],
                reflection.get('confidence', 0.5),
                existing['evidence_count']
            )
            
            cursor.execute("""
                UPDATE insights SET
                    confidence = ?,
                    strength = ?,
                    evidence_count = evidence_count + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    reasoning = ?,
                    generalizability = ?
                WHERE id = ?
            """, (
                new_confidence,
                min(1.0, existing['strength'] + 0.1),
                reflection.get('why_or_why_not', ''),
                generalizability,
                existing['id']
            ))
            
            self.conn.commit()
            logger.info(f"Updated existing insight #{existing['id']} (confidence: {new_confidence:.2f})")
            
            # Log insight update
            get_intel_logger().log_insight_updated(
                insight_id=existing['id'],
                old_confidence=existing['confidence'],
                new_confidence=new_confidence
            )
            
            return existing['id']
        
        else:
            # Create new insight with PHASE 1 schema
            preferred_tools = {}
            avoided_tools = []
            
            # Extract preferred tool
            preferred_tool = reflection.get('preferred_tool')
            if preferred_tool:
                preferred_tools[preferred_tool] = reflection.get('confidence', 0.5)
            elif experience['final_tool']:
                # Fallback to final tool if not specified
                preferred_tools[experience['final_tool']] = reflection.get('confidence', 0.5)
            
            # Extract avoided tool (for negative constraints)
            avoided_tool = reflection.get('avoided_tool')
            if avoided_tool:
                avoided_tools.append(avoided_tool)
            
            insight_type = reflection.get('insight_type', 'tool_preference')
            reasoning = reflection.get('why_or_why_not', '')
            
            cursor.execute("""
                INSERT INTO insights (
                    insight_type, description, insight_embedding,
                    constraint_type, trigger_concept,
                    applies_to_pattern, pattern_embedding,
                    preferred_tools, avoided_tools,
                    generalizability, reasoning,
                    confidence, evidence_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                insight_type,
                insight_text,
                self._serialize_embedding(insight_embedding),
                constraint_type,
                trigger_concept,
                pattern_text,
                self._serialize_embedding(pattern_embedding),
                json.dumps(preferred_tools),
                json.dumps(avoided_tools),
                generalizability,
                reasoning,
                reflection.get('confidence', 0.5),
                1
            ))
            
            self.conn.commit()
            insight_id = cursor.lastrowid
            logger.info(f"Created new {constraint_type} insight #{insight_id}: {insight_text[:50]}...")
            
            # Log insight creation
            get_intel_logger().log_insight_created(
                insight_id=insight_id,
                constraint_type=constraint_type,
                description=insight_text,
                confidence=reflection.get('confidence', 0.5)
            )
            
            return insight_id
    
    def _blend_confidence(
        self,
        old_confidence: float,
        new_confidence: float,
        evidence_count: int
    ) -> float:
        """
        Blend old and new confidence with exponential moving average.
        More evidence = more stable (harder to shift).
        """
        # Higher evidence count = lower learning rate (more stable)
        effective_rate = self.learning_rate / (1 + 0.1 * evidence_count)
        
        return (1 - effective_rate) * old_confidence + effective_rate * new_confidence
    
    async def _find_similar_insights(
        self,
        embedding: np.ndarray,
        threshold: float = 0.8
    ) -> list[dict[str, Any]]:
        """Find insights similar to the given embedding."""
        if embedding is None:
            return []
        
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM insights WHERE insight_embedding IS NOT NULL")
        
        similar = []
        for row in cursor.fetchall():
            stored_embedding = self._deserialize_embedding(row['insight_embedding'])
            if stored_embedding is not None:
                similarity = self._cosine_similarity(embedding, stored_embedding)
                if similarity >= threshold:
                    similar.append({
                        **dict(row),
                        'similarity': similarity
                    })
        
        # Sort by similarity
        similar.sort(key=lambda x: x['similarity'], reverse=True)
        return similar
    
    # ============================================
    # QUERY INTELLIGENCE
    # ============================================
    
    async def get_relevant_insights(
        self,
        query: str,
        top_k: int = 5
    ) -> list[dict[str, Any]]:
        """
        Get insights relevant to a query.
        
        This is called BEFORE routing to bias tool selection
        based on learned patterns.
        
        PHASE 1 UPGRADES:
        - Returns constraint_type (positive/negative)
        - Returns avoided_tools for negative constraints
        - Filters out low-generalizability insights
        """
        query_embedding = self._get_embedding(query)
        if query_embedding is None:
            return []
        
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM insights 
            WHERE confidence >= ? 
            AND pattern_embedding IS NOT NULL
            AND (generalizability IS NULL OR generalizability != 'low')
        """, (self.min_confidence,))
        
        relevant = []
        for row in cursor.fetchall():
            pattern_embedding = self._deserialize_embedding(row['pattern_embedding'])
            if pattern_embedding is not None:
                similarity = self._cosine_similarity(query_embedding, pattern_embedding)
                
                # Weight by confidence and similarity
                relevance = similarity * row['confidence']
                
                if relevance > 0.2:  # Minimum relevance threshold
                    insight_data = {
                        'id': row['id'],
                        'insight': row['description'],
                        'applies_to': row['applies_to_pattern'],
                        'preferred_tools': json.loads(row['preferred_tools'] or '{}'),
                        'confidence': row['confidence'],
                        'relevance': relevance,
                        'evidence_count': row['evidence_count'],
                        # PHASE 1: New fields
                        'constraint_type': row['constraint_type'] if 'constraint_type' in row.keys() else 'positive',
                        'avoided_tools': json.loads(row['avoided_tools'] or '[]') if 'avoided_tools' in row.keys() else [],
                        'trigger_concept': row['trigger_concept'] if 'trigger_concept' in row.keys() else '',
                        'reasoning': row['reasoning'] if 'reasoning' in row.keys() else ''
                    }
                    relevant.append(insight_data)
        
        # Sort by relevance
        relevant.sort(key=lambda x: x['relevance'], reverse=True)
        return relevant[:top_k]
    
    async def get_tool_biases(self, query: str) -> dict[str, float]:
        """
        Get tool preference biases based on learned insights.
        
        Returns dict of tool_name -> bias score
        Positive bias = prefer this tool
        Negative bias = avoid this tool
        
        PHASE 1 UPGRADES:
        - Positive constraints add positive bias
        - Negative constraints add negative bias (penalize tools)
        - Avoided tools get explicit negative bias
        """
        insights = await self.get_relevant_insights(query)
        
        biases = {}
        for insight in insights:
            constraint_type = insight.get('constraint_type', 'positive')
            
            # Handle preferred tools (positive bias)
            for tool, preference in insight['preferred_tools'].items():
                # Weight by relevance
                weighted_preference = preference * insight['relevance']
                
                if constraint_type == 'positive':
                    biases[tool] = biases.get(tool, 0) + weighted_preference
                else:
                    # Negative constraint's "preferred" tool is actually what to use INSTEAD
                    biases[tool] = biases.get(tool, 0) + (weighted_preference * 0.5)  # Weaker positive
            
            # Handle avoided tools (negative bias) - PHASE 1
            for tool in insight.get('avoided_tools', []):
                # Strong negative bias weighted by relevance, confidence, and negative_weight
                # negative_weight > 1.0 makes negative constraints stronger than positive
                negative_bias = -self.negative_weight * insight['relevance'] * insight['confidence']
                biases[tool] = biases.get(tool, 0) + negative_bias
        
        return biases
    
    # ============================================
    # INSIGHT USAGE TRACKING (PHASE 1: Decay)
    # ============================================
    
    async def record_insight_usage(
        self,
        insight_id: int,
        was_helpful: bool,
        outcome: str = None
    ):
        """
        Record when an insight is used and whether it helped.
        
        This enables:
        - Confidence decay for bad insights
        - Strengthening of good insights
        - Pruning of consistently failing insights
        """
        cursor = self.conn.cursor()
        
        # Get current insight state
        cursor.execute("SELECT * FROM insights WHERE id = ?", (insight_id,))
        insight = cursor.fetchone()
        if not insight:
            return
        
        times_applied = (insight['times_applied'] or 0) + 1
        times_helpful = (insight['times_helpful'] or 0) + (1 if was_helpful else 0)
        times_failed = (insight['times_failed'] or 0) + (0 if was_helpful else 1)
        
        # Track consecutive failures for rapid decay
        if was_helpful:
            consecutive_failures = 0
        else:
            consecutive_failures = (insight['consecutive_failures'] or 0) + 1
        
        # Calculate new confidence with decay
        old_confidence = insight['confidence']
        if was_helpful:
            # Slight boost for helpful usage
            new_confidence = min(1.0, old_confidence + 0.05)
        else:
            # Decay based on consecutive failures
            decay_factor = 0.1 * consecutive_failures  # Faster decay with repeated failures
            new_confidence = max(0.1, old_confidence - decay_factor)
        
        cursor.execute("""
            UPDATE insights SET
                times_applied = ?,
                times_helpful = ?,
                times_failed = ?,
                consecutive_failures = ?,
                confidence = ?,
                last_applied = CURRENT_TIMESTAMP,
                last_outcome = ?
            WHERE id = ?
        """, (
            times_applied,
            times_helpful,
            times_failed,
            consecutive_failures,
            new_confidence,
            outcome or ('success' if was_helpful else 'failure'),
            insight_id
        ))
        
        self.conn.commit()
        
        logger.info(
            f"Insight #{insight_id} {'helped' if was_helpful else 'failed'}: "
            f"confidence {old_confidence:.2f} → {new_confidence:.2f}"
        )
    
    async def prune_low_confidence_insights(self, threshold: float = 0.2) -> int:
        """
        Remove insights that have decayed below threshold.
        
        The "Gardener" process - run periodically to clean up bad learnings.
        """
        cursor = self.conn.cursor()
        
        # Find insights to prune
        cursor.execute("""
            SELECT id, description, confidence, times_applied, times_failed
            FROM insights
            WHERE confidence < ?
        """, (threshold,))
        
        to_prune = cursor.fetchall()
        
        if not to_prune:
            return 0
        
        # Log what we're removing
        for row in to_prune:
            logger.info(
                f"Pruning insight #{row['id']}: '{row['description'][:50]}...' "
                f"(confidence: {row['confidence']:.2f}, failed: {row['times_failed']}x)"
            )
        
        # Delete low-confidence insights
        cursor.execute("DELETE FROM insights WHERE confidence < ?", (threshold,))
        self.conn.commit()
        
        return len(to_prune)
    
    # ============================================
    # META-COGNITION
    # ============================================
    
    async def evaluate_learning_quality(self) -> dict[str, Any]:
        """
        Meta-cognition: evaluate how well the learning process is working.
        """
        cursor = self.conn.cursor()
        
        # Get recent insights
        cursor.execute("""
            SELECT * FROM insights 
            ORDER BY created_at DESC 
            LIMIT 20
        """)
        recent_insights = cursor.fetchall()
        
        # Analyze patterns
        analysis = {
            'total_insights': len(recent_insights),
            'avg_confidence': 0,
            'avg_evidence': 0,
            'potential_issues': []
        }
        
        if recent_insights:
            confidences = [r['confidence'] for r in recent_insights]
            evidences = [r['evidence_count'] for r in recent_insights]
            
            analysis['avg_confidence'] = sum(confidences) / len(confidences)
            analysis['avg_evidence'] = sum(evidences) / len(evidences)
            
            # Check for potential issues
            if analysis['avg_confidence'] < 0.4:
                analysis['potential_issues'].append(
                    "Low average confidence - insights may not be reliable"
                )
            
            if analysis['avg_evidence'] < 2:
                analysis['potential_issues'].append(
                    "Low evidence counts - need more experience to validate insights"
                )
            
            # Check for over-generalization (too few patterns covering too much)
            cursor.execute("SELECT COUNT(DISTINCT applies_to_pattern) FROM insights")
            unique_patterns = cursor.fetchone()[0]
            
            if unique_patterns < 3 and len(recent_insights) > 10:
                analysis['potential_issues'].append(
                    "Possible over-generalization - few patterns covering many insights"
                )
        
        return analysis
    
    async def process_reflection_queue(self, batch_size: int = 5) -> int:
        """Process pending reflections in the queue."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT experience_id FROM reflection_queue
            WHERE processed = 0
            ORDER BY priority DESC
            LIMIT ?
        """, (batch_size,))
        
        pending = cursor.fetchall()
        processed = 0
        
        for row in pending:
            result = await self.reflect_on_experience(row['experience_id'])
            if result:
                processed += 1
        
        return processed
    
    # ============================================
    # MAINTENANCE JOBS (Decay, Anomaly, Meta-Cognition)
    # ============================================
    
    async def run_decay_job(self, force: bool = False) -> dict[str, Any]:
        """
        Apply confidence decay to stale/unused insights.
        
        Uses INTELLIGENCE_DECAY_RATE from config.
        Insights that haven't been applied recently lose confidence.
        Insights that have failed repeatedly decay faster.
        
        IMPORTANT: This job should only run once per decay period (default: 7 days).
        Running it multiple times will compound the decay incorrectly.
        
        Args:
            force: If True, bypass the minimum interval check
        
        Returns:
            Stats about the decay job run
        """
        intel_log = get_intel_logger()
        cursor = self.conn.cursor()
        
        # Check if decay was already run recently (prevent double-decay)
        min_interval_days = get_int('INTELLIGENCE_DECAY_INTERVAL_DAYS', 7)
        
        cursor.execute("""
            SELECT MAX(timestamp) as last_run 
            FROM meta_knowledge 
            WHERE meta_type = 'decay_job_run'
        """)
        row = cursor.fetchone()
        
        if row and row['last_run'] and not force:
            last_run = datetime.fromisoformat(row['last_run'].replace('Z', '+00:00').replace('+00:00', ''))
            days_since_run = (datetime.now() - last_run).days
            
            if days_since_run < min_interval_days:
                return {
                    'status': 'skipped',
                    'reason': f'Decay job already ran {days_since_run} days ago (minimum interval: {min_interval_days} days)',
                    'last_run': row['last_run'],
                    'next_eligible': (last_run + timedelta(days=min_interval_days)).isoformat()
                }
        
        # Get insights with tracking data
        cursor.execute("""
            SELECT id, description, confidence, times_applied, times_helpful, 
                   times_failed, consecutive_failures, last_applied, created_at
            FROM insights
            WHERE confidence > 0.1
        """)
        
        insights = cursor.fetchall()
        stats = {
            'total_checked': len(insights),
            'decayed': 0,
            'boosted': 0,
            'unchanged': 0,
            'pruned': 0
        }
        
        now = datetime.now()
        
        for insight in insights:
            old_confidence = insight['confidence']
            new_confidence = old_confidence
            reason = None
            
            # Calculate days since last application
            if insight['last_applied']:
                last_applied = datetime.fromisoformat(insight['last_applied'].replace('Z', '+00:00').replace('+00:00', ''))
                days_since = (now - last_applied).days
            else:
                # Never applied - use creation date
                created = datetime.fromisoformat(insight['created_at'].replace('Z', '+00:00').replace('+00:00', ''))
                days_since = (now - created).days
            
            # Apply decay based on various factors
            
            # 1. Time-based decay (unused insights fade)
            if days_since > 7:
                decay_factor = self.decay_rate ** (days_since / 7)  # Compound decay per week
                new_confidence *= decay_factor
                reason = f"time_decay_{days_since}d"
            
            # 2. Failure-based decay (failed insights decay faster)
            if insight['consecutive_failures'] and insight['consecutive_failures'] > 0:
                failure_decay = 0.9 ** insight['consecutive_failures']
                new_confidence *= failure_decay
                reason = f"failure_decay_{insight['consecutive_failures']}_consecutive"
            
            # 3. Success rate boost (proven insights get slight boost)
            if insight['times_applied'] and insight['times_applied'] > 3:
                success_rate = insight['times_helpful'] / insight['times_applied']
                if success_rate > 0.8:
                    # Slight boost for highly successful insights
                    new_confidence = min(1.0, new_confidence * 1.02)
                    reason = f"success_boost_{success_rate:.0%}"
                    stats['boosted'] += 1
            
            # Apply change if significant
            if abs(new_confidence - old_confidence) > 0.01:
                cursor.execute("""
                    UPDATE insights SET confidence = ? WHERE id = ?
                """, (new_confidence, insight['id']))
                
                intel_log.log_decay_applied(
                    insight['id'], old_confidence, new_confidence, 
                    days_since, reason or 'general_decay'
                )
                
                if new_confidence < old_confidence:
                    stats['decayed'] += 1
            else:
                stats['unchanged'] += 1
            
            # Prune very low confidence insights
            if new_confidence < 0.15:
                cursor.execute("DELETE FROM insights WHERE id = ?", (insight['id'],))
                intel_log.log_insight_pruned(
                    insight['id'], insight['description'], 
                    'below_threshold', new_confidence
                )
                stats['pruned'] += 1
        
        # Record that decay job ran (for interval tracking)
        cursor.execute("""
            INSERT INTO meta_knowledge (meta_type, description, observation, conclusion, action_taken, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            'decay_job_run',
            'Decay maintenance job executed',
            f"Checked {stats['total_checked']} insights",
            f"Decayed: {stats['decayed']}, Boosted: {stats['boosted']}, Pruned: {stats['pruned']}",
            'decay_applied',
            1.0
        ))
        
        self.conn.commit()
        
        intel_log.log_maintenance_run('decay_job', stats)
        return stats
    
    async def run_anomaly_detection(self) -> dict[str, Any]:
        """
        Detect anomalous experiences that might indicate issues.
        
        Uses INTELLIGENCE_ANOMALY_THRESHOLD from config.
        Flags experiences that deviate significantly from norms.
        
        Returns:
            Stats and list of detected anomalies
        """
        intel_log = get_intel_logger()
        cursor = self.conn.cursor()
        
        # Get baseline statistics
        cursor.execute("""
            SELECT 
                AVG(turns_taken) as avg_turns,
                AVG(CASE WHEN outcome_success THEN 1 ELSE 0 END) as success_rate
            FROM experiences
            WHERE timestamp > datetime('now', '-7 days')
        """)
        baseline = cursor.fetchone()
        
        if not baseline or baseline['avg_turns'] is None:
            return {'status': 'insufficient_data', 'anomalies': []}
        
        avg_turns = baseline['avg_turns']
        
        # Calculate standard deviation for turns
        cursor.execute("""
            SELECT AVG((turns_taken - ?) * (turns_taken - ?)) as variance
            FROM experiences
            WHERE timestamp > datetime('now', '-7 days')
        """, (avg_turns, avg_turns))
        variance = cursor.fetchone()['variance'] or 1
        std_dev = variance ** 0.5
        
        anomalies = []
        stats = {
            'baseline_avg_turns': round(avg_turns, 2),
            'baseline_std_dev': round(std_dev, 2),
            'anomalies_found': 0
        }
        
        # Find anomalous experiences (recent only)
        cursor.execute("""
            SELECT id, query, turns_taken, outcome_success, tools_used
            FROM experiences
            WHERE timestamp > datetime('now', '-1 day')
        """)
        
        for exp in cursor.fetchall():
            anomaly_reasons = []
            
            # Check for high turn count
            if std_dev > 0:
                z_score = (exp['turns_taken'] - avg_turns) / std_dev
                if abs(z_score) > self.anomaly_threshold:
                    anomaly_reasons.append({
                        'type': 'high_turns',
                        'turns': exp['turns_taken'],
                        'z_score': round(z_score, 2),
                        'threshold': self.anomaly_threshold
                    })
            
            # Check for failure with many tools
            if not exp['outcome_success'] and exp['turns_taken'] > 3:
                anomaly_reasons.append({
                    'type': 'failed_multi_turn',
                    'turns': exp['turns_taken']
                })
            
            if anomaly_reasons:
                anomaly = {
                    'experience_id': exp['id'],
                    'query': exp['query'][:100],
                    'reasons': anomaly_reasons
                }
                anomalies.append(anomaly)
                
                intel_log.log_anomaly_detected(
                    exp['id'],
                    anomaly_reasons[0]['type'],
                    {'query': exp['query'][:100], 'reasons': anomaly_reasons}
                )
        
        stats['anomalies_found'] = len(anomalies)
        stats['anomalies'] = anomalies[:10]  # Limit for stats
        
        intel_log.log_maintenance_run('anomaly_detection', stats)
        return stats
    
    async def run_meta_cognition(self) -> dict[str, Any]:
        """
        Higher-level reflection on the learning process itself.
        
        Detects:
        - Blind spots (repeated failures in certain areas)
        - Over-generalization (insights applied too broadly)
        - Learning quality issues
        
        Populates meta_knowledge table with findings.
        
        Returns:
            Findings and actions taken
        """
        intel_log = get_intel_logger()
        cursor = self.conn.cursor()
        
        findings = []
        
        # ============================================
        # 1. DETECT BLIND SPOTS
        # Areas where we consistently fail
        # ============================================
        cursor.execute("""
            SELECT 
                final_tool,
                COUNT(*) as total,
                SUM(CASE WHEN outcome_success = 0 THEN 1 ELSE 0 END) as failures,
                ROUND(100.0 * SUM(CASE WHEN outcome_success = 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as failure_rate
            FROM experiences
            WHERE timestamp > datetime('now', '-7 days')
            GROUP BY final_tool
            HAVING failures > 2 AND failure_rate > 30
        """)
        
        for row in cursor.fetchall():
            finding = {
                'meta_type': 'blind_spot',
                'observation': f"Tool '{row['final_tool']}' has {row['failure_rate']}% failure rate ({row['failures']}/{row['total']} calls)",
                'conclusion': f"Possible issue with {row['final_tool']} usage or selection",
                'action': 'flag_for_review',
                'confidence': min(0.9, row['failures'] / 10)
            }
            findings.append(finding)
            
            # Store in meta_knowledge
            cursor.execute("""
                INSERT INTO meta_knowledge (meta_type, description, observation, conclusion, action_taken, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                finding['meta_type'],
                f"Blind spot: {row['final_tool']}",
                finding['observation'],
                finding['conclusion'],
                finding['action'],
                finding['confidence']
            ))
            
            intel_log.log_meta_cognition(
                finding['meta_type'], finding['observation'],
                finding['conclusion'], finding['action'], finding['confidence']
            )
        
        # ============================================
        # 2. DETECT OVER-GENERALIZATION
        # Insights that are applied too broadly
        # ============================================
        cursor.execute("""
            SELECT 
                id, description, times_applied, times_helpful, times_failed,
                ROUND(100.0 * times_failed / NULLIF(times_applied, 0), 1) as failure_rate
            FROM insights
            WHERE times_applied > 5
            AND times_failed > times_helpful
        """)
        
        for row in cursor.fetchall():
            finding = {
                'meta_type': 'over_generalization',
                'observation': f"Insight #{row['id']} applied {row['times_applied']}x with {row['failure_rate']}% failure rate",
                'conclusion': f"Insight may be too general: '{row['description'][:50]}...'",
                'action': 'reduce_confidence',
                'confidence': 0.7
            }
            findings.append(finding)
            
            # Reduce confidence of over-generalized insight
            cursor.execute("""
                UPDATE insights SET confidence = confidence * 0.7 WHERE id = ?
            """, (row['id'],))
            
            cursor.execute("""
                INSERT INTO meta_knowledge (meta_type, description, observation, conclusion, action_taken, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                finding['meta_type'],
                f"Over-generalization: insight #{row['id']}",
                finding['observation'],
                finding['conclusion'],
                finding['action'],
                finding['confidence']
            ))
            
            intel_log.log_meta_cognition(
                finding['meta_type'], finding['observation'],
                finding['conclusion'], finding['action'], finding['confidence']
            )
        
        # ============================================
        # 3. ASSESS LEARNING QUALITY
        # Overall health of the learning system
        # ============================================
        cursor.execute("""
            SELECT 
                COUNT(*) as total_insights,
                AVG(confidence) as avg_confidence,
                AVG(times_applied) as avg_applications,
                SUM(CASE WHEN times_applied > 0 THEN 1 ELSE 0 END) as insights_used
            FROM insights
        """)
        quality = cursor.fetchone()
        
        issues = []
        
        if quality['avg_confidence'] and quality['avg_confidence'] < 0.5:
            issues.append("Low average confidence - insights may not be reliable")
        
        if quality['total_insights'] > 20 and quality['insights_used'] < quality['total_insights'] * 0.2:
            issues.append("Many insights never applied - may be too specific")
        
        if quality['avg_applications'] and quality['avg_applications'] < 1:
            issues.append("Low insight application rate - matching may be too strict")
        
        if issues:
            finding = {
                'meta_type': 'learning_quality',
                'observation': f"Found {len(issues)} learning quality issue(s)",
                'conclusion': '; '.join(issues),
                'action': 'review_parameters',
                'confidence': 0.6
            }
            findings.append(finding)
            
            cursor.execute("""
                INSERT INTO meta_knowledge (meta_type, description, observation, conclusion, action_taken, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                finding['meta_type'],
                "Learning quality assessment",
                finding['observation'],
                finding['conclusion'],
                finding['action'],
                finding['confidence']
            ))
            
            intel_log.log_meta_cognition(
                finding['meta_type'], finding['observation'],
                finding['conclusion'], finding['action'], finding['confidence']
            )
        
        self.conn.commit()
        
        stats = {
            'findings_count': len(findings),
            'findings': findings,
            'quality_stats': {
                'total_insights': quality['total_insights'],
                'avg_confidence': round(quality['avg_confidence'] or 0, 3),
                'insights_used': quality['insights_used'],
                'avg_applications': round(quality['avg_applications'] or 0, 2)
            }
        }
        
        intel_log.log_maintenance_run('meta_cognition', stats)
        return stats
    
    async def run_all_maintenance(self, force: bool = False) -> dict[str, Any]:
        """Run all maintenance jobs and return combined results.
        
        Args:
            force: If True, bypass minimum interval check for decay job
        """
        results = {}
        
        results['decay'] = await self.run_decay_job(force=force)
        results['anomalies'] = await self.run_anomaly_detection()
        results['meta_cognition'] = await self.run_meta_cognition()
        
        return results
    
    # ============================================
    # CLEANUP & MAINTENANCE
    # ============================================
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
    
    def get_stats(self) -> dict[str, Any]:
        """Get intelligence layer statistics."""
        cursor = self.conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM experiences")
        exp_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM insights")
        insight_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM reflection_queue WHERE processed = 0")
        pending_reflections = cursor.fetchone()[0]
        
        cursor.execute("SELECT AVG(confidence) FROM insights")
        avg_confidence = cursor.fetchone()[0] or 0
        
        return {
            'experiences': exp_count,
            'insights': insight_count,
            'pending_reflections': pending_reflections,
            'avg_insight_confidence': round(avg_confidence, 3),
            'db_path': self.db_path
        }


# Singleton instance
_intelligence_layer = None
_intelligence_mode = None

def get_intelligence_layer(mode: str = None) -> IntelligenceLayer:
    """Get intelligence layer instance for the current mode."""
    global _intelligence_layer, _intelligence_mode
    
    # Determine current mode from env if not provided
    if mode is None:
        llm_provider = os.environ.get('LLM_PROVIDER', 'anthropic').lower()
        mode = 'local' if llm_provider == 'ollama' else 'cloud'
    
    # Recreate if mode changed or not initialized
    if _intelligence_layer is None or _intelligence_mode != mode:
        if _intelligence_layer is not None:
            _intelligence_layer.close()
        _intelligence_layer = IntelligenceLayer()
        _intelligence_mode = mode
    
    return _intelligence_layer


def reset_intelligence_layer():
    """Reset the intelligence layer singleton (call when mode changes)."""
    global _intelligence_layer, _intelligence_mode
    if _intelligence_layer is not None:
        _intelligence_layer.close()
    _intelligence_layer = None
    _intelligence_mode = None


# ============================================
# CLI for testing
# ============================================

if __name__ == "__main__":
    import asyncio
    
    async def main():
        intel = IntelligenceLayer()
        
        print("Intelligence Layer Stats:")
        print(json.dumps(intel.get_stats(), indent=2))
        
        # Test recording an experience
        print("\nRecording test experience...")
        exp_id = await intel.record_experience(
            query="Is my server running?",
            tools_used=["search_memory", "mcp_fetch_fetch"],
            outcome={"success": True, "turns": 2},
            user_signals={"clarified": False, "thanked": True}
        )
        print(f"Recorded experience ID: {exp_id}")
        
        print("\nUpdated Stats:")
        print(json.dumps(intel.get_stats(), indent=2))
        
        intel.close()
    
    asyncio.run(main())

