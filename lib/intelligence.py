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
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import numpy as np
import logging

# Add lib to path
sys.path.insert(0, os.path.dirname(__file__))
from config_loader import load_config, get_config_value, get_float

logger = logging.getLogger(__name__)


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
                insight_type TEXT,  -- 'tool_preference', 'query_pattern', 'error_pattern', etc.
                description TEXT,  -- Natural language description
                insight_embedding BLOB,
                
                -- What this insight applies to
                applies_to_pattern TEXT,  -- e.g., "status queries", "memory lookups"
                pattern_embedding BLOB,
                
                -- Learned associations
                preferred_tools TEXT,  -- JSON: {"mcp_fetch": 0.8, "search_memory": 0.3}
                avoided_patterns TEXT,  -- JSON list of things to avoid
                
                -- Confidence and strength
                confidence REAL DEFAULT 0.5,  -- 0.0 to 1.0
                strength REAL DEFAULT 0.5,  -- How strongly to apply this
                evidence_count INTEGER DEFAULT 1,  -- How many experiences support this
                
                -- For gradual learning
                last_applied TIMESTAMP,
                times_applied INTEGER DEFAULT 0,
                times_helpful INTEGER DEFAULT 0  -- When applied, was it helpful?
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
        
        self.conn.commit()
    
    # ============================================
    # EMBEDDING UTILITIES
    # ============================================
    
    def _get_embedding(self, text: str) -> Optional[np.ndarray]:
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
    
    def _deserialize_embedding(self, blob: bytes) -> Optional[np.ndarray]:
        """Deserialize numpy array from database."""
        if blob is None:
            return None
        return pickle.loads(blob)
    
    # ============================================
    # EXPERIENCE RECORDING
    # ============================================
    
    async def record_experience(
        self,
        query: str,
        tools_used: List[str],
        outcome: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        user_signals: Optional[Dict[str, Any]] = None
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
        context_summary = json.dumps(context)[:500] if context else ""
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
        return experience_id
    
    def _describe_outcome(
        self,
        query: str,
        tools_used: List[str],
        outcome: Dict[str, Any],
        user_signals: Dict[str, Any]
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
        outcome: Dict[str, Any],
        user_signals: Dict[str, Any]
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
        outcome: Dict[str, Any],
        user_signals: Dict[str, Any],
        tools_used: List[str]
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
    ) -> Optional[Dict[str, Any]]:
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
        
        reflection_prompt = f"""
Reflect deeply on this interaction:

**User Query**: {exp['query']}

**Tools Used**: {exp['tools_used']}
**Turns Taken**: {exp['turns_taken']}
**Final Tool**: {exp['final_tool']}

**Outcome**:
- Success: {exp['outcome_success']}
- User Satisfied: {exp['user_satisfied']}
- Had to Clarify: {exp['had_to_clarify']}
- Had to Retry: {exp['had_to_retry']}
- Error: {exp['error_occurred']}

**Questions to Consider**:
1. Was the first tool choice optimal? Why or why not?
2. What SIGNAL in the query should have indicated the best approach?
3. What's the DEEPER PATTERN here that applies to similar queries?
4. How confident are you in this insight? (0.0-1.0)
5. What category of queries does this apply to?

**Provide your reflection as JSON**:
```json
{{
    "first_tool_optimal": true/false,
    "why_or_why_not": "explanation",
    "key_signal": "what in the query indicated the best approach",
    "pattern": "the generalizable pattern",
    "applies_to": "category of similar queries",
    "preferred_approach": "what should be done for similar queries",
    "confidence": 0.0-1.0,
    "insight_summary": "one sentence insight"
}}
```
"""
        
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
    ) -> Optional[Dict[str, Any]]:
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
    
    async def _call_sequential_thinking(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Call the sequential thinking MCP server for structured reasoning."""
        try:
            from mcp_client import MCPClient
            
            # Initialize MCP client
            project_root = Path(__file__).parent.parent
            mcp_config_path = project_root / "config" / "mcp-servers.json"
            
            client = MCPClient(str(mcp_config_path))
            await client.initialize()
            
            # Call sequential thinking
            result = await client.call_tool(
                "mcp_sequentialthinking_sequentialthinking",
                {
                    "thought": prompt,
                    "nextThoughtNeeded": True
                }
            )
            
            if result and result.get('ok'):
                # Parse the thinking result
                thinking_output = result.get('data', {})
                return self._parse_reflection_output(thinking_output)
            
        except Exception as e:
            logger.warning(f"Sequential thinking unavailable: {e}")
        
        return None
    
    async def _direct_llm_reflection(self, prompt: str) -> Optional[Dict[str, Any]]:
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
                    model=get_config_value("CHAT_MODEL", "gpt-4o-mini")
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
                    model=get_config_value("OLLAMA_MODEL", "qwen3-vl:latest")
                )
            else:
                logger.error(f"Unknown provider type: {provider_type}")
                return None
            
            response = provider.chat(
                prompt,
                system_prompt="You are a self-reflective AI analyzing your own behavior to learn and improve. Output valid JSON only, no markdown formatting."
            )
            
            return self._parse_reflection_output(response)
            
        except Exception as e:
            logger.error(f"Direct LLM reflection failed: {e}")
        
        return None
    
    def _parse_reflection_output(self, output: Any) -> Optional[Dict[str, Any]]:
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
        reflection: Dict[str, Any],
        experience: sqlite3.Row
    ) -> int:
        """Store a new insight or update existing similar insight."""
        
        insight_text = reflection.get('insight_summary', reflection.get('pattern', ''))
        if not insight_text:
            return 0
        
        # Generate embeddings
        insight_embedding = self._get_embedding(insight_text)
        pattern_text = reflection.get('applies_to', '')
        pattern_embedding = self._get_embedding(pattern_text) if pattern_text else None
        
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
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                new_confidence,
                min(1.0, existing['strength'] + 0.1),
                existing['id']
            ))
            
            self.conn.commit()
            return existing['id']
        
        else:
            # Create new insight
            preferred_tools = {}
            if reflection.get('preferred_approach'):
                # Extract tool preferences from the reflection
                final_tool = experience['final_tool']
                if final_tool:
                    preferred_tools[final_tool] = reflection.get('confidence', 0.5)
            
            cursor.execute("""
                INSERT INTO insights (
                    insight_type, description, insight_embedding,
                    applies_to_pattern, pattern_embedding,
                    preferred_tools, confidence, evidence_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                'tool_preference',
                insight_text,
                self._serialize_embedding(insight_embedding),
                pattern_text,
                self._serialize_embedding(pattern_embedding),
                json.dumps(preferred_tools),
                reflection.get('confidence', 0.5),
                1
            ))
            
            self.conn.commit()
            return cursor.lastrowid
    
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
    ) -> List[Dict[str, Any]]:
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
    ) -> List[Dict[str, Any]]:
        """
        Get insights relevant to a query.
        
        This is called BEFORE routing to bias tool selection
        based on learned patterns.
        """
        query_embedding = self._get_embedding(query)
        if query_embedding is None:
            return []
        
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM insights 
            WHERE confidence >= ? 
            AND pattern_embedding IS NOT NULL
        """, (self.min_confidence,))
        
        relevant = []
        for row in cursor.fetchall():
            pattern_embedding = self._deserialize_embedding(row['pattern_embedding'])
            if pattern_embedding is not None:
                similarity = self._cosine_similarity(query_embedding, pattern_embedding)
                
                # Weight by confidence and similarity
                relevance = similarity * row['confidence']
                
                if relevance > 0.2:  # Minimum relevance threshold
                    relevant.append({
                        'insight': row['description'],
                        'applies_to': row['applies_to_pattern'],
                        'preferred_tools': json.loads(row['preferred_tools'] or '{}'),
                        'confidence': row['confidence'],
                        'relevance': relevance,
                        'evidence_count': row['evidence_count']
                    })
        
        # Sort by relevance
        relevant.sort(key=lambda x: x['relevance'], reverse=True)
        return relevant[:top_k]
    
    async def get_tool_biases(self, query: str) -> Dict[str, float]:
        """
        Get tool preference biases based on learned insights.
        
        Returns dict of tool_name -> bias score
        Positive bias = prefer this tool
        Negative bias = avoid this tool
        """
        insights = await self.get_relevant_insights(query)
        
        biases = {}
        for insight in insights:
            for tool, preference in insight['preferred_tools'].items():
                # Weight by relevance
                weighted_preference = preference * insight['relevance']
                biases[tool] = biases.get(tool, 0) + weighted_preference
        
        return biases
    
    # ============================================
    # META-COGNITION
    # ============================================
    
    async def evaluate_learning_quality(self) -> Dict[str, Any]:
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
    # CLEANUP & MAINTENANCE
    # ============================================
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
    
    def get_stats(self) -> Dict[str, Any]:
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

def get_intelligence_layer() -> IntelligenceLayer:
    """Get singleton intelligence layer instance."""
    global _intelligence_layer
    if _intelligence_layer is None:
        _intelligence_layer = IntelligenceLayer()
    return _intelligence_layer


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

