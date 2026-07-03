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
import threading

# Add lib to path
sys.path.insert(0, os.path.dirname(__file__))
from config_loader import load_config, get_float, get_int, get_active_config_mode
from security_utils import redact_sensitive_data, redact_sensitive_text
from time_utils import now_utc


def _reflection_cost_from_usage(usage_info: dict) -> "float | None":
    """Preserve unknown hosted cost as NULL instead of fabricating free usage."""
    raw = usage_info.get('cost_usd')
    if (
        usage_info.get('cost_known') is False
        or usage_info.get('billing_mode') == 'ollama_cloud_subscription'
        or raw in (None, '')
    ):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None

logger = logging.getLogger(__name__)

_EXTERNAL_SEARCH_TOOL_PREFIXES = (
    'mcp_brave_search_',
    'mcp_duckduckgo_',
    'serpapi_',
)


def _row_value(row: sqlite3.Row | dict[str, Any], key: str, default: Any = None) -> Any:
    """Read a field from either sqlite Row or plain dict."""
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except Exception:
        return default


def _json_loads_safely(value: Any, default: Any) -> Any:
    """Parse a JSON-ish value without letting malformed legacy rows break learning."""
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return default
    return default


def _coerce_string_list(value: Any) -> list[str]:
    """Normalize reflection/tool metadata into a clean string list."""
    value = _json_loads_safely(value, value)
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        return [str(k).strip() for k in value.keys() if str(k).strip()]
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            if item in (None, ""):
                continue
            text = str(item).strip()
            if text:
                result.append(text)
        return result
    text = str(value).strip()
    return [text] if text else []


def _has_provider_native_search(labels: list[str] | None) -> bool:
    """Return True when provider-native web/X search was used."""
    if not labels:
        return False
    return any(label in {'native:x_search', 'native:web_search'} for label in labels)


def _is_external_search_tool(tool_name: str | None) -> bool:
    """Detect normal Jarvis search tools that should not override native-search lessons."""
    if not tool_name:
        return False
    return any(tool_name.startswith(prefix) for prefix in _EXTERNAL_SEARCH_TOOL_PREFIXES)


def should_suppress_preferred_tool_for_native_search(
    reflection: dict[str, Any],
    experience: sqlite3.Row | dict[str, Any],
) -> bool:
    """
    Suppress misleading preferred_tool storage when native search was the key evidence path.

    This prevents reflections like "perform X-targeted searches first" from becoming
    "prefer mcp_brave_search_*" just because the original path ended on Brave.
    """
    raw_data_text = _row_value(experience, 'raw_data', '{}')
    try:
        raw_data = json.loads(raw_data_text) if raw_data_text else {}
    except Exception:
        raw_data = {}

    context_data = raw_data.get('context', {})
    native_labels = context_data.get('provider_native_tools_used', []) or []
    if not _has_provider_native_search(native_labels):
        return False

    preferred_tool = reflection.get('preferred_tool')
    if preferred_tool and _is_external_search_tool(preferred_tool):
        return True

    final_tool = _row_value(experience, 'final_tool')
    if not preferred_tool and final_tool and _is_external_search_tool(final_tool):
        return True

    return False


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
            **redact_sensitive_data(data)
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
            "query": redact_sensitive_text(query)[:200],
            "tools_used": tools,
            "success": success
        })

    def log_reflection_started(self, exp_id: int, query: str):
        """Log when reflection starts."""
        self.log("reflection_started", {
            "experience_id": exp_id,
            "query": redact_sensitive_text(query)[:200]
        })

    def log_reflection_prompt(self, exp_id: int, prompt: str):
        """Log the reflection prompt sent to LLM."""
        self.log("reflection_prompt", {
            "experience_id": exp_id,
            "prompt_preview": redact_sensitive_text(prompt)[:500],
            "prompt_length": len(prompt)
        })

    def log_reflection_response(
        self,
        exp_id: int,
        response: dict[str, Any],
        provider: str,
        model: str,
        usage_info: dict[str, Any] | None = None
    ):
        """Log the reflection response from LLM."""
        self.log("reflection_response", {
            "experience_id": exp_id,
            "provider": provider,
            "model": model,
            "response": response,
            "usage_info": usage_info or {}
        })

    def log_insight_created(self, insight_id: int, constraint_type: str, description: str, confidence: float):
        """Log when a new insight is created."""
        self.log("insight_created", {
            "insight_id": insight_id,
            "constraint_type": constraint_type,
            "description": redact_sensitive_text(description)[:200],
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
            "description": redact_sensitive_text(description)[:200],
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
            "query": redact_sensitive_text(query)[:200],
            "insights_count": len(insights),
            "insights": [{"id": i.get("id"), "relevance": i.get("relevance")} for i in insights[:5]],
            "tool_biases": biases
        })

    def log_insight_skipped(self, reason: str, details: str):
        """Log when an insight is not stored (factual, low generalizability, etc.)"""
        self.log("insight_skipped", {
            "reason": reason,
            "details": redact_sensitive_text(details)[:200]
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

    def __init__(self, db_path: str = None, *, load_runtime_config: bool = True):
        """Initialize the intelligence layer and ensure its database schema."""
        if load_runtime_config or db_path is None:
            load_config()

        if db_path is None:
            project_root = Path(__file__).parent.parent.resolve()
            data_dir = project_root / "data"
            data_dir.mkdir(exist_ok=True)

            # Resolve data mode from the active config scope / JARVIS_MODE,
            # never from the chat provider (matches memory_db selection).
            from config_loader import get_active_config_mode
            mode = get_active_config_mode()
            if mode == 'local':
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

        # SECURITY: Restrict DB file to owner-only (600) since it contains
        # learning data and interaction history. sqlite3.connect() uses the
        # process umask (typically 022 → 644), so we fix it after creation.
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass  # Non-fatal: may fail on some filesystems

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
                preferred_tool_sequence TEXT,  -- JSON list: advisory observed sequence, not a hard workflow
                supporting_tools TEXT,  -- JSON list: useful secondary tools observed with the primary preference
                sequence_required BOOLEAN DEFAULT 0,  -- True only when order is essential
                avoided_tools TEXT,  -- JSON: ["search_memory"] - tools to explicitly avoid
                avoided_patterns TEXT,  -- JSON list of patterns to avoid
                trigger_signals TEXT,  -- JSON list of exact query signals from reflection
                primary_intent TEXT,  -- Compact intent label used for auditing/gating

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
                consecutive_failures INTEGER DEFAULT 0,  -- For rapid decay on repeated failures

                -- Audit provenance for the first experience that created this insight.
                -- Additional supporting/refuting records live in insight_evidence.
                source_experience_id INTEGER,
                source_web_conversation_id TEXT,
                source_query TEXT,
                source_tool_sequence TEXT,
                source_reflection_json TEXT
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

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS insight_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                insight_id INTEGER NOT NULL,
                experience_id INTEGER,
                web_conversation_id TEXT,
                query TEXT,
                tool_sequence TEXT,
                preferred_tool TEXT,
                avoided_tool TEXT,
                preferred_tool_sequence TEXT,
                supporting_tools TEXT,
                reflection_json TEXT,
                confidence REAL,
                confidence_delta REAL,
                action TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (insight_id) REFERENCES insights(id),
                FOREIGN KEY (experience_id) REFERENCES experiences(id)
            )
        """)

        # Indexes for efficient queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_exp_timestamp ON experiences(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_insight_type ON insights(insight_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_insight_confidence ON insights(confidence)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reflection_pending ON reflection_queue(processed, priority)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_insight_evidence_insight ON insight_evidence(insight_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_insight_evidence_experience ON insight_evidence(experience_id)")

        # PHASE 1: Schema migration for existing databases
        self._migrate_schema(cursor)
        self._backfill_insight_sources_from_evidence(cursor)
        self._backfill_raw_data_experience_ids(cursor)

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
            ("trigger_signals", "TEXT"),
            ("primary_intent", "TEXT"),
            ("avoided_tools", "TEXT"),
            ("preferred_tool_sequence", "TEXT"),
            ("supporting_tools", "TEXT"),
            ("sequence_required", "BOOLEAN DEFAULT 0"),
            ("generalizability", "TEXT DEFAULT 'medium'"),
            ("reasoning", "TEXT"),
            ("reflection_provider", "TEXT"),
            ("reflection_model", "TEXT"),
            ("reflection_input_tokens", "INTEGER DEFAULT 0"),
            ("reflection_output_tokens", "INTEGER DEFAULT 0"),
            ("reflection_total_tokens", "INTEGER DEFAULT 0"),
            ("reflection_cost_usd", "REAL DEFAULT 0"),
            ("last_outcome", "TEXT"),
            ("times_failed", "INTEGER DEFAULT 0"),
            ("consecutive_failures", "INTEGER DEFAULT 0"),
            ("source_experience_id", "INTEGER"),
            ("source_web_conversation_id", "TEXT"),
            ("source_query", "TEXT"),
            ("source_tool_sequence", "TEXT"),
            ("source_reflection_json", "TEXT"),
        ]

        for col_name, col_def in new_columns:
            if col_name not in existing_columns:
                try:
                    cursor.execute(f"ALTER TABLE insights ADD COLUMN {col_name} {col_def}")
                    logger.info(f"Added column {col_name} to insights table")
                except sqlite3.OperationalError as e:
                    # Column might already exist or other issue
                    logger.debug(f"Could not add column {col_name}: {e}")

    def _backfill_insight_sources_from_evidence(self, cursor: sqlite3.Cursor) -> None:
        """Populate blank insight source fields from their newest evidence row."""
        try:
            cursor.execute("""
                UPDATE insights
                SET source_experience_id = COALESCE(
                        source_experience_id,
                        (
                            SELECT e.experience_id
                            FROM insight_evidence e
                            WHERE e.insight_id = insights.id
                              AND e.experience_id IS NOT NULL
                            ORDER BY e.id DESC
                            LIMIT 1
                        )
                    ),
                    source_web_conversation_id = COALESCE(
                        NULLIF(source_web_conversation_id, ''),
                        (
                            SELECT e.web_conversation_id
                            FROM insight_evidence e
                            WHERE e.insight_id = insights.id
                              AND e.web_conversation_id IS NOT NULL
                              AND e.web_conversation_id != ''
                            ORDER BY e.id DESC
                            LIMIT 1
                        )
                    ),
                    source_query = COALESCE(
                        NULLIF(source_query, ''),
                        (
                            SELECT e.query
                            FROM insight_evidence e
                            WHERE e.insight_id = insights.id
                              AND e.query IS NOT NULL
                              AND e.query != ''
                            ORDER BY e.id DESC
                            LIMIT 1
                        )
                    ),
                    source_tool_sequence = COALESCE(
                        NULLIF(source_tool_sequence, ''),
                        (
                            SELECT e.tool_sequence
                            FROM insight_evidence e
                            WHERE e.insight_id = insights.id
                              AND e.tool_sequence IS NOT NULL
                              AND e.tool_sequence != ''
                            ORDER BY e.id DESC
                            LIMIT 1
                        )
                    ),
                    source_reflection_json = COALESCE(
                        NULLIF(source_reflection_json, ''),
                        (
                            SELECT e.reflection_json
                            FROM insight_evidence e
                            WHERE e.insight_id = insights.id
                              AND e.reflection_json IS NOT NULL
                              AND e.reflection_json != ''
                            ORDER BY e.id DESC
                            LIMIT 1
                        )
                    )
                WHERE EXISTS (
                    SELECT 1 FROM insight_evidence e WHERE e.insight_id = insights.id
                )
                  AND (
                    source_experience_id IS NULL
                    OR source_web_conversation_id IS NULL OR source_web_conversation_id = ''
                    OR source_query IS NULL OR source_query = ''
                    OR source_tool_sequence IS NULL OR source_tool_sequence = ''
                    OR source_reflection_json IS NULL OR source_reflection_json = ''
                  )
            """)
        except sqlite3.OperationalError as e:
            logger.debug(f"Could not backfill insight provenance: {e}")

    def _backfill_raw_data_experience_ids(self, cursor: sqlite3.Cursor) -> None:
        """Repair older raw_data blobs that captured experience_id before insert."""
        try:
            rows = cursor.execute("""
                SELECT id, raw_data
                FROM experiences
                WHERE raw_data LIKE '%"experience_id": null%'
                   OR raw_data LIKE '%"completion_guard"%'
            """).fetchall()
        except sqlite3.OperationalError as e:
            logger.debug(f"Could not scan raw_data for experience_id backfill: {e}")
            return

        for row in rows:
            try:
                raw_data = json.loads(row['raw_data'] or '{}')
            except Exception:
                continue
            if not isinstance(raw_data, dict):
                continue

            changed = False
            context = raw_data.get('context')
            if isinstance(context, dict) and context.get('experience_id') in (None, '', -1):
                context['experience_id'] = row['id']
                changed = True

            completion_guard = raw_data.get('completion_guard')
            if isinstance(completion_guard, dict) and completion_guard.get('experience_id') in (None, '', -1):
                completion_guard['experience_id'] = row['id']
                changed = True

            if changed:
                cursor.execute(
                    "UPDATE experiences SET raw_data = ? WHERE id = ?",
                    (json.dumps(raw_data, default=str), row['id'])
                )

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

    def _parse_timestamp(self, value: Any) -> datetime | None:
        """Parse SQLite/ISO timestamps defensively for maintenance jobs."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace('Z', '+00:00').replace('+00:00', ''))
        except Exception:
            return None

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
        query = redact_sensitive_text(query or "")
        outcome = redact_sensitive_data(outcome or {})
        context = redact_sensitive_data(context)
        user_signals = redact_sensitive_data(user_signals)

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
        raw_data = {
            'query': query,
            'tools_used': tools_used,
            'outcome': outcome,
            'context': context,
            'user_signals': user_signals,
            'timestamp': datetime.now().isoformat()
        }

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
            json.dumps(raw_data, default=str)
        ))

        experience_id = cursor.lastrowid
        if isinstance(raw_data.get('context'), dict):
            raw_data['context']['experience_id'] = experience_id
            cursor.execute(
                "UPDATE experiences SET raw_data = ? WHERE id = ?",
                (json.dumps(raw_data, default=str), experience_id)
            )

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
        raw_data = redact_sensitive_data(json.loads(exp['raw_data']))
        context_data = raw_data.get('context', {})

        # Extract LLM response and tool results for content evaluation
        llm_response = (
            context_data.get('raw_llm_response')
            or context_data.get('llm_response')
            or '[Not captured]'
        )
        final_speech = context_data.get('final_speech', '[Not captured]')
        corrected_response = context_data.get('corrected_llm_response', '[Not captured]')
        corrected_tools_used = context_data.get('corrected_tools_used', [])
        corrected_tool_results = context_data.get('corrected_tool_results', '[Not captured]')
        tool_results = context_data.get('tool_results', '[Not captured]')
        tool_trace = context_data.get('tool_trace', '[Not captured]')
        server_side_tools = context_data.get('server_side_tools', {})
        provider_native_tools_used = context_data.get('provider_native_tools_used', [])
        completion_guard = raw_data.get('completion_guard', {})
        feedback_record = raw_data.get('feedback', {})
        latest_feedback = (
            feedback_record.get('latest', {})
            if isinstance(feedback_record, dict)
            else {}
        )
        if not isinstance(latest_feedback, dict):
            latest_feedback = {}
        response_style = context_data.get('response_style') or '[Not captured]'
        qa_word_limit = context_data.get('qa_word_limit') or '[Not captured]'
        multi_turn_word_limit = context_data.get('multi_turn_word_limit') or '[Not captured]'

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
        provider_native_tools_str = ', '.join(provider_native_tools_used) if provider_native_tools_used else '(none captured)'
        server_side_tools_str = json.dumps(server_side_tools) if server_side_tools else '(none captured)'
        artifact_tools = [tool for tool in ('canvas', 'stash') if tool in available_tools]
        artifact_tools_str = ', '.join(artifact_tools) if artifact_tools else '(none available)'

        # Identify tools that were available but NOT used (for reflection analysis)
        unused_tools = [t for t in available_tools if t not in tools_used_list] if available_tools else []
        unused_tools_str = ', '.join(unused_tools[:10]) if unused_tools else 'None'  # Limit to 10

        reflection_prompt = f"""
Analyze this interaction to extract a PROCEDURAL insight (not a fact).

**User Query**: {exp['query']}

**AVAILABLE TOOLS** (what the LLM could choose from):
{available_tools_str}

**Tools Actually Used (in order)**: {exp['tools_used']}
**Provider-Native Tools Used**: {provider_native_tools_str}
**Tools Available But NOT Used**: {unused_tools_str}
**Turns Taken**: {exp['turns_taken']}
**Final Tool**: {exp['final_tool']}
**Outcome Status**: {"SUCCESS" if exp['outcome_success'] else "FAILURE"}
**User Satisfied**: {exp['user_satisfied']}
**Had to Clarify**: {exp['had_to_clarify']}
**Had to Retry**: {exp['had_to_retry']}

**Tool Results** (what the tools returned):
{tool_results[:1500] if tool_results != '[Not captured]' else '[Not available]'}

**Tool Attempt Trace** (attempted tools, sanitized arguments, failures, and recovery):
{tool_trace[:2000] if tool_trace != '[Not captured]' else '[Not available]'}

**LLM Response** (what was said to the user):
{llm_response[:1000] if llm_response != '[Not captured]' else '[Not available]'}

**Final Spoken/Display Response**:
{final_speech[:600] if final_speech != '[Not captured]' else '[Not available]'}

**Corrected/Repaired Response** (if Completion Guard found one):
{corrected_response[:1000] if corrected_response != '[Not captured]' else '[Not available]'}

**Corrected Tools Used**:
{', '.join(corrected_tools_used) if corrected_tools_used else '(none captured)'}

**Corrected Tool Results**:
{corrected_tool_results[:1200] if corrected_tool_results != '[Not captured]' else '[Not available]'}

**Completion Guard Outcome**:
- Status: {completion_guard.get('status', 'none')}
- Note: {completion_guard.get('note', '') or '(none)'}
- Metadata: {json.dumps(completion_guard.get('metadata', {}))[:800] if completion_guard else '(none)'}

**Feedback Outcome**:
- Rating: {latest_feedback.get('rating', 'none')}
- Summary: {latest_feedback.get('summary', '') or '(none)'}
- Issues: {json.dumps(latest_feedback.get('issues', []), default=str)[:800] if latest_feedback else '(none)'}
- Analysis: {latest_feedback.get('analysis', '')[:800] if latest_feedback.get('analysis') else '(none)'}

**Presentation Context**:
- Response Style: {response_style}
- Q&A Word Limit: {qa_word_limit}
- Multi-Turn Word Limit: {multi_turn_word_limit}
- Artifact Tools Available: {artifact_tools_str}

**Provider-Native Tool Metadata**:
{server_side_tools_str}

CRITICAL EVALUATION:
1. Did the tool(s) return relevant data for the query? (tool_results vs query)
2. Did the LLM response accurately reflect the tool data? (llm_response vs tool_results)
3. Did the LLM response actually answer what the user asked? (llm_response vs query)
4. Was the FIRST tool the optimal choice, or should a different tool have been used initially?
5. If Completion Guard marked this as repaired, unresolved, or ticket_created, treat that as strong evidence the ORIGINAL answer path was insufficient even if a later repair improved it.
6. If a corrected/repaired response exists, compare the original path with the repaired path and learn from what changed.
7. Provider-native tools are metadata-only evidence paths, not normal Jarvis tool choices. If provider-native tools are listed, do NOT infer "zero-tool hallucination" from an empty tools_used list alone.
8. Do NOT create preferred_tool/avoided_tool insights that tell Jarvis to prefer or avoid provider-native tools such as native:x_search or native:code_interpreter.
9. If provider-native web/X search was part of the successful evidence path, and the lesson is about search targeting or freshness, set preferred_tool to null unless a normal Jarvis tool was clearly the decisive improvement.
10. If Tool Attempt Trace shows a failed tool call that was later corrected, extract the reusable payload/argument lesson.
11. Prefer global argument-shape lessons when they apply across tools, e.g. "tool argument values must be concrete values, not JSON schema objects."
12. Keep insight_summary short; put exact argument-shape details in why_or_why_not/reasoning when needed.
13. If Feedback Outcome has a low rating or concrete issue summary, treat that as direct evidence about why the settled answer was unsatisfactory.
14. If response style is auto/casual and the user asks for multi-item or multi-field details, consider whether an available artifact tool (canvas/stash) should have been used for the full structured output while the spoken response stayed brief. Only recommend artifact tools that appear in Artifact Tools Available.
15. If multiple tools were useful, do not force a rigid workflow. Use preferred_tool_sequence only as an observed/advisory sequence, and set sequence_required true only when the order is essential for correctness.
16. Separate primary intent from content topic. Example: "email this YouTube video" is primarily an email/send action, not a transcript-analysis request.
17. A Web upload query may already contain a completed vision result inside
    "[User uploaded an image. Vision analysis: ...]" (or the multi-image equivalent).
    Treat that attached analysis as evidence gathered BEFORE routing, not as raw user text
    that still requires a lookup.
18. For those pre-analyzed uploads, compare memory tool results against the attached vision
    evidence. If search_memory/semantic_recall only returns the newly stored artifact, the
    same stash reference, or an equivalent description, it added no unique information:
    first_tool_optimal must be false and no positive memory-tool preference should be learned.
19. Memory can still be valuable for a pre-analyzed upload when it contributes distinct,
    relevant prior knowledge (for example, the user's earlier notes about a hand sketch,
    provenance, related projects, previous uploads, or an explicit comparison/history request).
    Judge the incremental evidence; do not create a blanket rule to avoid memory for images.

TOOL CATEGORIES (for understanding what tools do):
- **MEMORY TOOLS** (check stored knowledge): search_memory, recall, semantic_recall, get_recent_conversations, search_conversations
- **ACTION TOOLS** (do something live): mcp_fetch_fetch, execute_bash, api_call, send_webhook, send_email
- **STORAGE TOOLS** (save info): remember, update_memory, forget
- **UTILITY TOOLS** (simple tasks): get_time, crypto_price, list_reminders, list_alerts
- **SEARCH TOOLS** (web search): mcp_brave_search_*, mcp_duckduckgo_*
- **BUILD TOOLS** (create projects): opencode
- **ARTIFACT TOOLS** (save structured/detail-heavy output): canvas, stash
- **PROVIDER-NATIVE TOOLS** (metadata only, not Jarvis routing choices): native:x_search, native:web_search, native:code_interpreter

SYSTEM RULES THE LLM SHOULD HAVE FOLLOWED:
- **MEMORY-FIRST RULE**: For questions about user's info, servers, configs, preferences → SHOULD check memory FIRST
- Memory-first does not require re-fetching the current upload's vision description when that
  description is already attached. Search memory only when it may add distinct stored context.
- If query mentions a server IP/service → memory might have stored health check commands with CORRECT details
- If query asks about "my X" or personal info → memory likely has stored preferences
- Using ACTION TOOLS before MEMORY TOOLS violates system rules for personal/stored data queries
- If memory search was skipped but query was about stored knowledge → first_tool_optimal = FALSE

CRITICAL: Look for signs the user-provided info might be WRONG:
- If a connection/fetch failed → memory might have the CORRECT endpoint stored
- If user says "my server at X" but X fails → the stored server might be at a DIFFERENT address
- A "not running" result could actually mean "wrong IP" if memory wasn't checked first
- When something FAILS and memory wasn't checked → strongly consider first_tool_optimal = FALSE

TOOL FAILURE RECOVERY (important for generation tools):
- If a generation tool (generate_video, generate_image, generate_music) was called multiple times, check WHY
- If the tool returned unexpected results (wrong duration, wrong size) and was retried → the LLM should have searched memory for known provider limitations instead of retrying
- Provider API limitations are NOT fixable by retrying with different params (e.g., xAI video editing cannot change duration)
- Pattern: tool fails/unexpected → retry same tool = BAD. Tool fails/unexpected → search_memory for limitations → inform user = GOOD.
- If multiple turns were used on the SAME generation tool → first_tool_optimal may be true but the RECOVERY STRATEGY was wrong

TOOL ARGUMENT RECOVERY (important for smaller/local models):
- If a failed attempt used schema-shaped values like {{"type": "string"}} instead of concrete user values, create a negative global insight.
- If a later attempt succeeded with corrected arguments, learn the argument convention that made it work.
- Do not store user-specific values as the rule; store the reusable procedure.

RESULT-BASED EVALUATION (most important):
- 1 tool used + good result = likely optimal first choice
- Exception: a memory tool that merely echoes evidence already attached to the query is
  redundant even if the final answer is correct; a direct answer was the optimal path
- Multiple tools + had to retry = first tool probably suboptimal
- Action tool first + connection failed = should have checked memory
- Memory empty + action succeeded = action was correct fallback
- Same generation tool called 2+ times = recovery strategy failure (should search memory or inform user)

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
    "preferred_tool_sequence": ["tool_a", "tool_b"],  // optional/advisory only; [] if order was not the lesson
    "supporting_tools": ["tool_b"],  // optional secondary tools that helped but should not override primary intent
    "sequence_required": false,  // true only if the exact order is essential
    "primary_intent": "compact action/intent label",

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
    "preferred_tool_sequence": [],
    "supporting_tools": [],
    "sequence_required": false,
    "primary_intent": "live server status check",
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
    "preferred_tool_sequence": [],
    "supporting_tools": [],
    "sequence_required": false,
    "primary_intent": "current live data lookup",
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
    "insight_summary": "The Ollama server is at <host-ip> - this is a fact, not a procedure"
}}
```
"""

        # Log reflection start
        intel_log = get_intel_logger()
        intel_log.log_reflection_started(experience_id, exp['query'])
        intel_log.log_reflection_prompt(experience_id, reflection_prompt)

        # Use sequential thinking MCP if available, otherwise direct LLM
        reflection = await self._think_deeply(
            reflection_prompt,
            use_sequential_thinking,
            experience_id=experience_id
        )

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
        use_sequential_thinking: bool = True,
        experience_id: int | None = None
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
            return await self._direct_llm_reflection(prompt, experience_id=experience_id)

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

    async def _direct_llm_reflection(
        self,
        prompt: str,
        experience_id: int | None = None
    ) -> dict[str, Any] | None:
        """Direct LLM call for reflection when sequential thinking unavailable."""
        try:
            from llm_provider import create_provider
            from model_catalog import get_provider_fallback_model
            from model_prompt_overrides import (
                apply_prompt_override_sections,
                load_model_prompt_override,
            )
            from config_loader import load_config, get_config_value

            # Ensure config is loaded
            load_config()

            # Create provider based on current mode (same logic as router_v2.py)
            provider_type = get_config_value('LLM_PROVIDER', 'anthropic')

            if provider_type == "openai":
                provider = create_provider(
                    "openai",
                    api_key=get_config_value("OPENAI_API_KEY"),
                    model=get_config_value("OPENAI_MODEL", get_provider_fallback_model("openai"))
                )
            elif provider_type == "anthropic":
                provider = create_provider(
                    "anthropic",
                    api_key=get_config_value("ANTHROPIC_API_KEY"),
                    model=get_config_value("ANTHROPIC_MODEL", get_provider_fallback_model("anthropic"))
                )
            elif provider_type == "xai":
                provider = create_provider(
                    "xai",
                    api_key=get_config_value("XAI_API_KEY"),
                    model=get_config_value("XAI_MODEL", get_provider_fallback_model("xai"))
                )
            elif provider_type == "ollama":
                from ollama_utils import resolve_ollama_model
                provider = create_provider(
                    "ollama",
                    base_url=get_config_value("OLLAMA_BASE_URL", "http://localhost:11434"),
                    model=resolve_ollama_model()
                )
            else:
                logger.error(f"Unknown provider type: {provider_type}")
                return None

            # Get model name for logging
            model_name = getattr(provider, 'model', 'unknown')
            override_mode = get_active_config_mode()
            override = load_model_prompt_override(
                provider=provider_type,
                model=model_name,
                mode=override_mode,
            )
            prompt = apply_prompt_override_sections(
                prompt,
                override,
                prepend_sections=("intelligence_reflection_prepend",),
            )
            system_prompt = (
                "You are a self-reflective AI analyzing your own behavior to learn and improve. "
                "Output valid JSON only, no markdown formatting."
            )
            usage_info = None

            try:
                response, tool_call, usage_info, _thinking = provider.chat_with_tools(
                    messages=[{"role": "user", "content": prompt}],
                    tools=[],
                    system_prompt=system_prompt,
                    enable_thinking=False
                )
                if tool_call:
                    response = json.dumps({
                        "is_procedural": False,
                        "knowledge_type": "factual",
                        "insight_summary": "Reflection unexpectedly requested a tool instead of returning an insight."
                    })
            except Exception as e:
                logger.debug(f"Usage-aware reflection call failed, falling back to chat(): {e}")
                response = provider.chat(prompt, system_prompt=system_prompt)

            parsed = self._parse_reflection_output(response)
            if parsed:
                parsed['_reflection_usage'] = usage_info or {}
                parsed['_reflection_provider'] = provider_type
                parsed['_reflection_model'] = model_name

            # Log the reflection response
            get_intel_logger().log_reflection_response(
                exp_id=experience_id or 0,
                response=parsed or {"raw": str(response)[:500]},
                provider=provider_type,
                model=model_name,
                usage_info=usage_info
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

    def _get_experience_raw_data(self, experience: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        """Return raw_data as a dict for provenance and reflection metadata."""
        raw_data = _row_value(experience, 'raw_data', '{}')
        parsed = _json_loads_safely(raw_data, {})
        return parsed if isinstance(parsed, dict) else {}

    def _reflection_sequence_required(self, value: Any) -> bool:
        """Parse conservative boolean metadata from LLM reflection output."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {'1', 'true', 'yes', 'required'}
        return False

    def _extract_insight_metadata(
        self,
        reflection: dict[str, Any],
        experience: sqlite3.Row | dict[str, Any],
        suppress_preferred_tool: bool = False
    ) -> dict[str, Any]:
        """
        Normalize reflection output into storable insight metadata.

        Tool sequences are advisory evidence. They help audit and future prompt
        shaping, but they do not force routing to execute a fixed workflow.
        """
        confidence = reflection.get('confidence', 0.5)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.5

        preferred_tools: dict[str, float] = {}
        preferred_tool_names = _coerce_string_list(reflection.get('preferred_tool'))
        if suppress_preferred_tool:
            preferred_tool_names = []
        if not preferred_tool_names and not suppress_preferred_tool:
            final_tool = _row_value(experience, 'final_tool')
            if final_tool:
                # TODO: If the reflection also avoided this same tool, reshape the
                # insight instead of creating contradictory prefer/avoid metadata.
                preferred_tool_names = [str(final_tool)]
        for tool in preferred_tool_names:
            preferred_tools[tool] = confidence

        avoided_tools = _coerce_string_list(reflection.get('avoided_tool'))
        avoided_tools.extend(_coerce_string_list(reflection.get('avoided_tools')))
        avoided_tools = list(dict.fromkeys(avoided_tools))

        preferred_tool_sequence = _coerce_string_list(reflection.get('preferred_tool_sequence'))
        supporting_tools = _coerce_string_list(reflection.get('supporting_tools'))
        trigger_signals = _coerce_string_list(reflection.get('trigger_signals'))

        raw_data = redact_sensitive_data(self._get_experience_raw_data(experience))
        context = raw_data.get('context', {}) if isinstance(raw_data.get('context'), dict) else {}
        source_tool_sequence = _coerce_string_list(_row_value(experience, 'tool_sequence'))
        if not source_tool_sequence:
            source_tool_sequence = _coerce_string_list(_row_value(experience, 'tools_used'))

        return {
            'preferred_tools': preferred_tools,
            'avoided_tools': avoided_tools,
            'preferred_tool_sequence': preferred_tool_sequence,
            'supporting_tools': supporting_tools,
            'sequence_required': self._reflection_sequence_required(reflection.get('sequence_required')),
            'trigger_signals': trigger_signals,
            'primary_intent': str(reflection.get('primary_intent') or '').strip(),
            'source_experience_id': _row_value(experience, 'id'),
            'source_web_conversation_id': context.get('web_conversation_id'),
            'source_query': redact_sensitive_text(_row_value(experience, 'query') or ''),
            'source_tool_sequence': source_tool_sequence,
            'source_reflection_json': json.dumps(redact_sensitive_data(reflection), default=str),
            'confidence': confidence,
            'suppressed_preferred_tool': suppress_preferred_tool,
        }

    def _insight_associations_compatible(
        self,
        existing: sqlite3.Row | dict[str, Any],
        metadata: dict[str, Any]
    ) -> bool:
        """
        Similar prose should not merge if it recommends a different tool.

        The evidence table still records every supporting experience, but
        conflicting tool associations deserve separate insight rows so stale
        preferences do not survive under a freshly reinforced description.
        """
        existing_preferred = set(_coerce_string_list(_row_value(existing, 'preferred_tools')))
        new_preferred = set((metadata.get('preferred_tools') or {}).keys())
        if existing_preferred and not new_preferred and metadata.get('suppressed_preferred_tool'):
            return False
        if existing_preferred and new_preferred and existing_preferred != new_preferred:
            return False

        existing_avoided = set(_coerce_string_list(_row_value(existing, 'avoided_tools')))
        new_avoided = set(metadata.get('avoided_tools') or [])
        if existing_avoided and new_avoided and existing_avoided != new_avoided:
            return False

        existing_sequence = _coerce_string_list(_row_value(existing, 'preferred_tool_sequence'))
        new_sequence = metadata.get('preferred_tool_sequence') or []
        if existing_sequence and new_sequence and existing_sequence != new_sequence:
            return False

        return True

    def _merge_json_list_fields(self, existing_value: Any, new_values: list[str]) -> str:
        """Return a JSON list containing the stable union of old and new values."""
        merged = _coerce_string_list(existing_value)
        for value in new_values:
            if value and value not in merged:
                merged.append(value)
        return json.dumps(merged)

    def _record_insight_evidence(
        self,
        cursor: sqlite3.Cursor,
        insight_id: int,
        metadata: dict[str, Any],
        reflection: dict[str, Any],
        action: str,
        confidence_delta: float | None = None,
    ) -> None:
        """Attach an auditable source experience/reflection to an insight."""
        preferred_tool_names = list((metadata.get('preferred_tools') or {}).keys())
        avoided_tools = metadata.get('avoided_tools') or []
        cursor.execute("""
            INSERT INTO insight_evidence (
                insight_id, experience_id, web_conversation_id, query,
                tool_sequence, preferred_tool, avoided_tool,
                preferred_tool_sequence, supporting_tools, reflection_json,
                confidence, confidence_delta, action
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            insight_id,
            metadata.get('source_experience_id'),
            metadata.get('source_web_conversation_id'),
            metadata.get('source_query'),
            json.dumps(metadata.get('source_tool_sequence') or []),
            preferred_tool_names[0] if preferred_tool_names else None,
            avoided_tools[0] if avoided_tools else None,
            json.dumps(metadata.get('preferred_tool_sequence') or []),
            json.dumps(metadata.get('supporting_tools') or []),
            json.dumps(redact_sensitive_data(reflection), default=str),
            metadata.get('confidence'),
            confidence_delta,
            action,
        ))

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
        reflection = redact_sensitive_data(reflection)

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

        usage_info = reflection.get('_reflection_usage') or {}
        if not isinstance(usage_info, dict):
            usage_info = {}
        reflection_provider = reflection.get('_reflection_provider', '')
        reflection_model = reflection.get('_reflection_model', '')
        reflection_input_tokens = int(usage_info.get('input_tokens') or 0)
        reflection_output_tokens = int(usage_info.get('output_tokens') or 0)
        reflection_total_tokens = int(
            usage_info.get('total_tokens')
            or (reflection_input_tokens + reflection_output_tokens)
            or 0
        )
        reflection_cost_usd = _reflection_cost_from_usage(usage_info)

        # Extract constraint type
        constraint_type = reflection.get('constraint_type', 'positive')

        # Generate embeddings
        insight_embedding = self._get_embedding(insight_text)
        pattern_text = reflection.get('applies_to', '')
        pattern_embedding = self._get_embedding(pattern_text) if pattern_text else None
        trigger_concept = reflection.get('trigger_concept', '')

        suppress_preferred_tool = should_suppress_preferred_tool_for_native_search(reflection, experience)
        if suppress_preferred_tool:
            logger.info(
                "Suppressing preferred_tool for native-search-backed insight: %s",
                reflection.get('insight_summary', reflection.get('rule', ''))[:120]
            )
        metadata = self._extract_insight_metadata(
            reflection,
            experience,
            suppress_preferred_tool=suppress_preferred_tool
        )

        # Check for similar existing insights
        similar = await self._find_similar_insights(insight_embedding, threshold=0.85)
        compatible_similar = [
            row for row in similar
            if self._insight_associations_compatible(row, metadata)
        ]

        cursor = self.conn.cursor()

        if compatible_similar:
            # Update existing insight (blend, don't replace)
            existing = compatible_similar[0]
            new_confidence = self._blend_confidence(
                existing['confidence'],
                metadata['confidence'],
                existing['evidence_count']
            )
            confidence_delta = new_confidence - existing['confidence']

            cursor.execute("""
                UPDATE insights SET
                    confidence = ?,
                    strength = ?,
                    evidence_count = evidence_count + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    reasoning = ?,
                    generalizability = ?,
                    preferred_tool_sequence = CASE
                        WHEN preferred_tool_sequence IS NULL OR preferred_tool_sequence = ''
                        THEN ?
                        ELSE preferred_tool_sequence
                    END,
                    supporting_tools = ?,
                    trigger_signals = ?,
                    primary_intent = COALESCE(NULLIF(primary_intent, ''), ?),
                    source_experience_id = COALESCE(source_experience_id, ?),
                    source_web_conversation_id = COALESCE(NULLIF(source_web_conversation_id, ''), ?),
                    source_query = COALESCE(NULLIF(source_query, ''), ?),
                    source_tool_sequence = COALESCE(NULLIF(source_tool_sequence, ''), ?),
                    source_reflection_json = COALESCE(NULLIF(source_reflection_json, ''), ?),
                    sequence_required = CASE
                        WHEN COALESCE(sequence_required, 0) = 1 OR ? = 1
                        THEN 1
                        ELSE 0
                    END,
                    reflection_provider = ?,
                    reflection_model = ?,
                    reflection_input_tokens = COALESCE(reflection_input_tokens, 0) + ?,
                    reflection_output_tokens = COALESCE(reflection_output_tokens, 0) + ?,
                    reflection_total_tokens = COALESCE(reflection_total_tokens, 0) + ?,
                    reflection_cost_usd = CASE
                        WHEN reflection_cost_usd IS NULL OR ? IS NULL THEN NULL
                        ELSE reflection_cost_usd + ?
                    END
                WHERE id = ?
            """, (
                new_confidence,
                min(1.0, existing['strength'] + 0.1),
                reflection.get('why_or_why_not', ''),
                generalizability,
                json.dumps(metadata['preferred_tool_sequence']),
                self._merge_json_list_fields(existing['supporting_tools'], metadata['supporting_tools']),
                self._merge_json_list_fields(existing['trigger_signals'], metadata['trigger_signals']),
                metadata['primary_intent'],
                metadata['source_experience_id'],
                metadata['source_web_conversation_id'],
                metadata['source_query'],
                json.dumps(metadata['source_tool_sequence']),
                json.dumps(metadata['source_reflection_json']),
                1 if metadata['sequence_required'] else 0,
                reflection_provider,
                reflection_model,
                reflection_input_tokens,
                reflection_output_tokens,
                reflection_total_tokens,
                reflection_cost_usd,
                reflection_cost_usd,
                existing['id']
            ))

            self._record_insight_evidence(
                cursor,
                insight_id=existing['id'],
                metadata=metadata,
                reflection=reflection,
                action='merged',
                confidence_delta=confidence_delta
            )

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
            if similar:
                logger.info(
                    "Creating separate insight for similar text with different tool association: %s",
                    insight_text[:120]
                )

            insight_type = reflection.get('insight_type', 'tool_preference')
            reasoning = reflection.get('why_or_why_not', '')

            cursor.execute("""
                INSERT INTO insights (
                    insight_type, description, insight_embedding,
                    constraint_type, trigger_concept,
                    applies_to_pattern, pattern_embedding,
                    preferred_tools, preferred_tool_sequence, supporting_tools,
                    sequence_required, avoided_tools, trigger_signals, primary_intent,
                    generalizability, reasoning,
                    reflection_provider, reflection_model,
                    reflection_input_tokens, reflection_output_tokens,
                    reflection_total_tokens, reflection_cost_usd,
                    confidence, evidence_count,
                    source_experience_id, source_web_conversation_id,
                    source_query, source_tool_sequence, source_reflection_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                insight_type,
                insight_text,
                self._serialize_embedding(insight_embedding),
                constraint_type,
                trigger_concept,
                pattern_text,
                self._serialize_embedding(pattern_embedding),
                json.dumps(metadata['preferred_tools']),
                json.dumps(metadata['preferred_tool_sequence']),
                json.dumps(metadata['supporting_tools']),
                1 if metadata['sequence_required'] else 0,
                json.dumps(metadata['avoided_tools']),
                json.dumps(metadata['trigger_signals']),
                metadata['primary_intent'],
                generalizability,
                reasoning,
                reflection_provider,
                reflection_model,
                reflection_input_tokens,
                reflection_output_tokens,
                reflection_total_tokens,
                reflection_cost_usd,
                metadata['confidence'],
                1,
                metadata['source_experience_id'],
                metadata['source_web_conversation_id'],
                metadata['source_query'],
                json.dumps(metadata['source_tool_sequence']),
                metadata['source_reflection_json'],
            ))

            insight_id = cursor.lastrowid
            self._record_insight_evidence(
                cursor,
                insight_id=insight_id,
                metadata=metadata,
                reflection=reflection,
                action='created',
                confidence_delta=None
            )
            self.conn.commit()
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

                if relevance > 0.2:  # Minimum relevance threshold Might need to increase if unrelated tools being called or llm not following q&a intent 0.3+
                    insight_data = {
                        'id': row['id'],
                        'insight': row['description'],
                        'applies_to': row['applies_to_pattern'],
                        'preferred_tools': _json_loads_safely(row['preferred_tools'], {}),
                        'confidence': row['confidence'],
                        'relevance': relevance,
                        'evidence_count': row['evidence_count'],
                        # PHASE 1: New fields
                        'constraint_type': row['constraint_type'] if 'constraint_type' in row.keys() else 'positive',
                        'avoided_tools': _json_loads_safely(row['avoided_tools'], []) if 'avoided_tools' in row.keys() else [],
                        'trigger_concept': row['trigger_concept'] if 'trigger_concept' in row.keys() else '',
                        'trigger_signals': _json_loads_safely(row['trigger_signals'], []) if 'trigger_signals' in row.keys() else [],
                        'primary_intent': row['primary_intent'] if 'primary_intent' in row.keys() else '',
                        'preferred_tool_sequence': _json_loads_safely(row['preferred_tool_sequence'], []) if 'preferred_tool_sequence' in row.keys() else [],
                        'supporting_tools': _json_loads_safely(row['supporting_tools'], []) if 'supporting_tools' in row.keys() else [],
                        'sequence_required': bool(row['sequence_required']) if 'sequence_required' in row.keys() else False,
                        'source_experience_id': row['source_experience_id'] if 'source_experience_id' in row.keys() else None,
                        'source_web_conversation_id': row['source_web_conversation_id'] if 'source_web_conversation_id' in row.keys() else None,
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

    async def run_decay_job(self, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
        """
        Apply confidence decay to stale/unused insights.

        Uses INTELLIGENCE_DECAY_RATE from config.
        Insights that haven't been applied recently lose confidence.
        Insights that have failed repeatedly decay faster.

        IMPORTANT: This job should only run once per decay period (default: 7 days).
        Running it multiple times will compound the decay incorrectly.

        Args:
            force: If True, bypass the minimum interval check
            dry_run: If True, calculate changes without writing to the database

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
        last_decay_run = None

        if row and row['last_run'] and not force:
            last_decay_run = self._parse_timestamp(row['last_run'])
            if not last_decay_run:
                last_decay_run = datetime.now()
            days_since_run = max(0, (now_utc().replace(tzinfo=None) - last_decay_run).days)

            if days_since_run < min_interval_days:
                return {
                    'status': 'skipped',
                    'reason': f'Decay job already ran {days_since_run} days ago (minimum interval: {min_interval_days} days)',
                    'last_run': row['last_run'],
                    'next_eligible': (last_decay_run + timedelta(days=min_interval_days)).isoformat()
                }
        elif row and row['last_run']:
            last_decay_run = self._parse_timestamp(row['last_run'])

        # Get insights with tracking data
        cursor.execute("""
            SELECT id, description, confidence, times_applied, times_helpful,
                   times_failed, consecutive_failures, last_applied, created_at,
                   updated_at,
                   (
                       SELECT MAX(e.created_at)
                       FROM insight_evidence e
                       WHERE e.insight_id = insights.id
                   ) AS latest_evidence_at
            FROM insights
            WHERE confidence > 0.1
        """)

        insights = cursor.fetchall()
        stats = {
            'status': 'dry_run' if dry_run else 'ok',
            'dry_run': dry_run,
            'total_checked': len(insights),
            'decayed': 0,
            'boosted': 0,
            'unchanged': 0,
            'pruned': 0
        }

        now = now_utc().replace(tzinfo=None)

        for insight in insights:
            old_confidence = insight['confidence']
            new_confidence = old_confidence
            reasons = []

            # Calculate days since last application
            activity_candidates = [
                self._parse_timestamp(insight['last_applied']),
                self._parse_timestamp(insight['updated_at']),
                self._parse_timestamp(insight['latest_evidence_at']),
                self._parse_timestamp(insight['created_at']),
            ]
            last_activity = max((ts for ts in activity_candidates if ts), default=now)
            days_since = max(0, (now - last_activity).days)

            # Apply decay based on various factors

            # 1. Time-based decay (unused insights fade)
            effective_decay_days = days_since
            if last_decay_run:
                # Confidence is already persisted after each decay run. Only apply
                # the decay that accrued since the last run so stale insights do
                # not get charged for their full age every maintenance cycle.
                days_since_decay_run = max(0, (now - last_decay_run).days)
                effective_decay_days = min(days_since, days_since_decay_run)

            if effective_decay_days > 7:
                decay_factor = self.decay_rate ** (effective_decay_days / 7)  # Compound decay per week
                new_confidence *= decay_factor
                reasons.append(f"time_decay_{effective_decay_days}d")

            # 2. Failure-based decay (failed insights decay faster)
            if insight['consecutive_failures'] and insight['consecutive_failures'] > 0:
                failure_decay = 0.9 ** insight['consecutive_failures']
                new_confidence *= failure_decay
                reasons.append(f"failure_decay_{insight['consecutive_failures']}_consecutive")

            # 3. Success rate boost (proven insights get slight boost)
            if insight['times_applied'] and insight['times_applied'] > 3:
                success_rate = insight['times_helpful'] / insight['times_applied']
                if success_rate > 0.8:
                    # Slight boost for highly successful insights
                    new_confidence = min(1.0, new_confidence * 1.02)
                    reasons.append(f"success_boost_{success_rate:.0%}")

            # Apply change if significant
            if abs(new_confidence - old_confidence) > 0.01:
                if not dry_run:
                    cursor.execute("""
                        UPDATE insights SET confidence = ? WHERE id = ?
                    """, (new_confidence, insight['id']))

                    intel_log.log_decay_applied(
                        insight['id'], old_confidence, new_confidence,
                        days_since, '+'.join(reasons) or 'general_decay'
                    )

                if new_confidence < old_confidence:
                    stats['decayed'] += 1
                elif new_confidence > old_confidence:
                    stats['boosted'] += 1
            else:
                stats['unchanged'] += 1

            # Prune very low confidence insights
            if new_confidence < 0.15:
                if not dry_run:
                    cursor.execute("DELETE FROM insight_evidence WHERE insight_id = ?", (insight['id'],))
                    cursor.execute("DELETE FROM insights WHERE id = ?", (insight['id'],))
                    intel_log.log_insight_pruned(
                        insight['id'], insight['description'],
                        'below_threshold', new_confidence
                    )
                stats['pruned'] += 1

        if not dry_run:
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

    async def run_all_maintenance(self, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
        """Run all maintenance jobs and return combined results.

        Args:
            force: If True, bypass minimum interval check for decay job
            dry_run: If True, calculate decay changes without writing decay updates
        """
        results = {}

        results['decay'] = await self.run_decay_job(force=force, dry_run=dry_run)
        if dry_run:
            results['anomalies'] = {'status': 'skipped_dry_run'}
            results['meta_cognition'] = {'status': 'skipped_dry_run'}
            return results
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


# One instance per data mode. Cloud and local requests may coexist in the Web
# process, so switching one request must never close another request's DB.
_intelligence_layers: dict[str, IntelligenceLayer] = {}
_intelligence_lock = threading.RLock()

# Backward-compatible references to the most recently requested instance.
_intelligence_layer = None
_intelligence_mode = None

def _intelligence_db_path_for_mode(mode: str) -> str:
    """Resolve the Intelligence DB path for an explicit mode."""
    if mode not in {'cloud', 'local'}:
        raise ValueError(f"Invalid intelligence data mode: {mode!r}")
    project_root = Path(__file__).parent.parent.resolve()
    suffix = '_local' if mode == 'local' else ''
    return str(project_root / 'data' / f'jarvis_intelligence{suffix}.db')


def get_intelligence_layer(mode: str = None) -> IntelligenceLayer:
    """Get intelligence layer instance for the current mode."""
    global _intelligence_layer, _intelligence_mode

    # Resolve mode from the active config scope / JARVIS_MODE, never the provider.
    mode = get_active_config_mode(mode)

    with _intelligence_lock:
        layer = _intelligence_layers.get(mode)
        if layer is None or layer.conn is None:
            layer = IntelligenceLayer(db_path=_intelligence_db_path_for_mode(mode))
            _intelligence_layers[mode] = layer
        _intelligence_layer = layer
        _intelligence_mode = mode
        return layer


def reset_intelligence_layer(mode: str = None):
    """Close cached Intelligence layers, optionally for only one data mode."""
    global _intelligence_layer, _intelligence_mode
    with _intelligence_lock:
        if mode is None:
            layers = list(_intelligence_layers.values())
            _intelligence_layers.clear()
        else:
            resolved_mode = get_active_config_mode(mode)
            layer = _intelligence_layers.pop(resolved_mode, None)
            layers = [layer] if layer is not None else []
        for layer in layers:
            layer.close()
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
