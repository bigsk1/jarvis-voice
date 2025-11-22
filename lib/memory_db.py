#!/usr/bin/env python3
"""
Jarvis Memory Database
SQLite-based memory system for storing facts, conversations, and learned patterns.
Supports semantic search with vector embeddings.
"""
import sqlite3
import json
import os
import pickle
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional


class MemoryDB:
    """Manages Jarvis's persistent memory."""
    
    def __init__(self, db_path: str = None):
        """
        Initialize memory database.
        
        Args:
            db_path: Path to SQLite database file (auto-detects cloud vs local mode)
        """
        if db_path is None:
            # Auto-detect mode and use appropriate database
            project_root = Path(__file__).parent.parent.resolve()
            data_dir = project_root / "data"
            data_dir.mkdir(exist_ok=True)
            
            # Check if we're in local mode (ollama provider)
            llm_provider = os.environ.get('LLM_PROVIDER', 'anthropic').lower()
            
            if llm_provider == 'ollama':
                # Local mode - use separate database with nomic embeddings
                db_path = str(data_dir / "jarvis_memory_local.db")
            else:
                # Cloud mode - use main database with OpenAI embeddings
                db_path = str(data_dir / "jarvis_memory.db")
        
        self.db_path = db_path
        self.conn = None
        self._init_db()
    
    def _init_db(self):
        """Initialize database and create tables."""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Return rows as dictionaries
        
        cursor = self.conn.cursor()
        
        # Knowledge base - facts the AI should remember
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_base (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                importance INTEGER DEFAULT 5,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                source TEXT,
                metadata TEXT,
                embedding BLOB,
                long_form TEXT
            )
        """)
        
        # Conversation history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                session_id TEXT,
                user_query TEXT NOT NULL,
                jarvis_response TEXT,
                tools_used TEXT,
                success BOOLEAN DEFAULT 1,
                metadata TEXT
            )
        """)
        
        # Note: tool_patterns and preferences tables removed (not used)
        # Memory now uses metadata field in knowledge_base for flexible data
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge_base(category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_key ON knowledge_base(key)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp)")
        
        # FTS5 Full-Text Search Virtual Table (BM25 ranking)
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_base_fts USING fts5(
                category, key, value, long_form,
                content='knowledge_base',
                content_rowid='id',
                tokenize='porter unicode61'
            )
        """)
        
        # Tool Definitions (for Dynamic Retrieval)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tool_definitions (
                name TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                schema_json TEXT NOT NULL,
                embedding BLOB,
                enabled BOOLEAN DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Triggers to keep FTS5 in sync with knowledge_base
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS kb_fts_insert AFTER INSERT ON knowledge_base BEGIN
                INSERT INTO knowledge_base_fts(rowid, category, key, value, long_form)
                VALUES (new.id, new.category, new.key, new.value, new.long_form);
            END
        """)
        
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS kb_fts_update AFTER UPDATE ON knowledge_base BEGIN
                UPDATE knowledge_base_fts SET 
                    category = new.category,
                    key = new.key,
                    value = new.value,
                    long_form = new.long_form
                WHERE rowid = new.id;
            END
        """)
        
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS kb_fts_delete AFTER DELETE ON knowledge_base BEGIN
                DELETE FROM knowledge_base_fts WHERE rowid = old.id;
            END
        """)
        
        self.conn.commit()
    
    # ========== Knowledge Base Operations ==========
    
    def remember(self, category: str, key: str, value: str, importance: int = 5, source: str = None, 
                 generate_embedding: bool = True, metadata: dict = None) -> int:
        """
        Store a fact in memory with optional semantic embedding and metadata.
        
        Args:
            category: Type of information (contact, fact, preference, etc.)
            key: What this is about
            value: The information to remember
            importance: 1-10 scale (higher = more important)
            source: Where this came from
            generate_embedding: Whether to generate vector embedding for semantic search
            metadata: Optional dict with tags, expiration, related info
            
        Returns:
            ID of the stored memory
        """
        cursor = self.conn.cursor()
        
        # Generate embedding if requested
        embedding_blob = None
        if generate_embedding:
            try:
                from embeddings import get_embedding
                # Combine key and value for richer semantic context
                text = f"{key}: {value}"
                embedding_vector = get_embedding(text)
                # Serialize vector as blob
                embedding_blob = pickle.dumps(embedding_vector)
            except Exception as e:
                # Silently fail - memory still gets stored without embedding
                pass
        
        # Serialize metadata to JSON string
        metadata_json = json.dumps(metadata) if metadata else None
        
        # Check if similar memory exists
        existing = cursor.execute(
            "SELECT id FROM knowledge_base WHERE category = ? AND key = ?",
            (category, key)
        ).fetchone()
        
        if existing:
            # Update existing memory
            cursor.execute("""
                UPDATE knowledge_base 
                SET value = ?, importance = ?, updated_at = CURRENT_TIMESTAMP, source = ?, embedding = ?, metadata = ?
                WHERE id = ?
            """, (value, importance, source, embedding_blob, metadata_json, existing['id']))
            self.conn.commit()
            return existing['id']
        else:
            # Insert new memory
            cursor.execute("""
                INSERT INTO knowledge_base (category, key, value, importance, source, embedding, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (category, key, value, importance, source, embedding_blob, metadata_json))
            self.conn.commit()
            return cursor.lastrowid
    
    def recall(self, query: str, category: str = None, limit: int = 5) -> List[Dict]:
        """
        Search memories by query.
        
        Args:
            query: What to search for
            category: Optional category filter
            limit: Maximum results
            
        Returns:
            List of matching memories
        """
        cursor = self.conn.cursor()
        
        if category:
            results = cursor.execute("""
                SELECT * FROM knowledge_base
                WHERE category = ? AND (key LIKE ? OR value LIKE ?)
                ORDER BY importance DESC, updated_at DESC
                LIMIT ?
            """, (category, f"%{query}%", f"%{query}%", limit)).fetchall()
        else:
            results = cursor.execute("""
                SELECT * FROM knowledge_base
                WHERE key LIKE ? OR value LIKE ?
                ORDER BY importance DESC, updated_at DESC
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit)).fetchall()
        
        # Add relevance field for consistency with FTS5 search
        memories = []
        for row in results:
            memory = dict(row)
            memory['relevance'] = 0.5  # Default relevance for LIKE search (not as precise as FTS5)
            # Remove embedding blob (too large for JSON serialization)
            if 'embedding' in memory:
                del memory['embedding']
            memories.append(memory)
        
        return memories
    
    def update_memory(self, memory_id: int, value: str = None, importance: int = None) -> bool:
        """Update an existing memory."""
        cursor = self.conn.cursor()
        
        updates = []
        params = []
        
        if value is not None:
            updates.append("value = ?")
            params.append(value)
        
        if importance is not None:
            updates.append("importance = ?")
            params.append(importance)
        
        if not updates:
            return False
        
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(memory_id)
        
        query = f"UPDATE knowledge_base SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, params)
        self.conn.commit()
        
        return cursor.rowcount > 0
    
    def forget(self, memory_id: int) -> bool:
        """Delete a memory."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM knowledge_base WHERE id = ?", (memory_id,))
        self.conn.commit()
        return cursor.rowcount > 0
    
    def search_memory(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Full-text search using FTS5 with BM25 ranking.
        Much faster and more accurate than SQL LIKE.
        
        Args:
            query: Search term (supports phrases, AND/OR operators)
            limit: Max results
            
        Returns:
            List of memories ranked by relevance (BM25 score)
        """
        return self.fts_search(query, limit=limit)
    
    def fts_search(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Full-text search with BM25 ranking (industry-standard relevance).
        
        Features:
        - Stemming: "running" matches "run"
        - Porter algorithm for English text
        - BM25 ranking (better than simple LIKE matching)
        - Phrase search: "Flask API" in quotes
        - Boolean operators: "flask OR express"
        - Smart query expansion: tries AND first (precise), then OR (broad) if no results
        
        Strategy:
        1. Try original query (may use implicit AND for multi-word)
        2. Try explicit AND with quoted terms (handles hyphens like "Mini-AI")
        3. Try OR with quoted terms (broader match)
        4. Fall back to LIKE search (last resort)
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of memories ranked by relevance
        """
        cursor = self.conn.cursor()
        
        def _try_fts_query(fts_query: str) -> List[Dict]:
            """Internal helper to execute FTS query."""
            try:
                results = cursor.execute("""
                    SELECT kb.*, bm25(knowledge_base_fts) as relevance_score
                    FROM knowledge_base kb
                    JOIN knowledge_base_fts ON kb.id = knowledge_base_fts.rowid
                    WHERE knowledge_base_fts MATCH ?
                    ORDER BY relevance_score ASC, kb.importance DESC
                    LIMIT ?
                """, (fts_query, limit)).fetchall()
                
                memories = []
                for row in results:
                    memory = dict(row)
                    # Convert BM25 to 0-1 score (lower is better, so invert)
                    memory['relevance'] = 1 / (1 + abs(memory['relevance_score']))
                    del memory['relevance_score']
                    # Remove embedding blob (too large for JSON serialization)
                    if 'embedding' in memory:
                        del memory['embedding']
                    memories.append(memory)
                
                return memories
            except sqlite3.OperationalError:
                return []
        
        def _prepare_terms(query_str: str) -> list:
            """Extract and quote key terms from query."""
            stop_words = {'the', 'is', 'at', 'on', 'and', 'or', 'to', 'a', 'an', 'in', 'of', 'for', 'with', 'as', 'by', 'my', 'can', 'you', 'check', 'see', 'if', 'up', 'running', 'status'}
            terms = [word.strip('?,!.') for word in query_str.split() if word.lower() not in stop_words and len(word) > 2]
            
            # Quote terms with hyphens or special chars to prevent FTS5 operator interpretation
            quoted_terms = []
            for term in terms:
                if '-' in term or any(c in term for c in [':', '*', '(', ')']):
                    # FTS5 phrase syntax: wrap in quotes
                    quoted_terms.append(f'"{term}"')
                else:
                    quoted_terms.append(term)
            
            return quoted_terms
        
        # 1. Try original query first (as-is)
        results = _try_fts_query(query)
        
        # If no results and query has multiple words, try AND then OR
        if not results and len(query.split()) > 1:
            quoted_terms = _prepare_terms(query)
            
            if quoted_terms:
                # 2. Try explicit AND with quoted terms (precise match)
                and_query = ' AND '.join(quoted_terms)
                results = _try_fts_query(and_query)
                
                # 3. If still no results, try OR (broader match)
                if not results:
                    or_query = ' OR '.join(quoted_terms)
                    results = _try_fts_query(or_query)
        
        # 4. Final fallback: try LIKE search
        if not results:
            return self.recall(query, limit=limit)
        
        return results
    
    def get_all_memories(self, category: str = None) -> List[Dict]:
        """Get all stored memories, optionally filtered by category."""
        cursor = self.conn.cursor()
        
        if category:
            results = cursor.execute(
                "SELECT * FROM knowledge_base WHERE category = ? ORDER BY importance DESC, updated_at DESC",
                (category,)
            ).fetchall()
        else:
            results = cursor.execute(
                "SELECT * FROM knowledge_base ORDER BY importance DESC, updated_at DESC"
            ).fetchall()
        
        return [dict(row) for row in results]
    
    def semantic_search(self, query: str, limit: int = 5, similarity_threshold: float = None) -> List[Dict]:
        """
        Semantic search using vector embeddings with smart fallback.
        Finds memories similar in meaning, not just keywords.
        
        Strategy:
        1. Try semantic search with embeddings (meaning-based)
        2. If 0 results (threshold too high), fall back to FTS5 (keyword-based)
        3. If FTS5 fails, fall back to LIKE (substring-based)
        
        Args:
            query: Search query (can be natural language)
            limit: Maximum number of results
            similarity_threshold: Minimum similarity score (0-1)
                If None, reads from SEMANTIC_SIMILARITY_THRESHOLD env var (default 0.40)
                Lower = more results (may include loosely related)
                Higher = fewer results (only close matches)
            
        Returns:
            List of memories with similarity/relevance scores, sorted by relevance
        """
        try:
            from embeddings import get_embedding, cosine_similarity
            from config_loader import get_float
            
            # Use provided threshold or read from config
            if similarity_threshold is None:
                similarity_threshold = get_float('SEMANTIC_SIMILARITY_THRESHOLD', 0.40)
            
            # Generate embedding for query
            query_embedding = get_embedding(query)
            
            # Get all memories with embeddings
            cursor = self.conn.cursor()
            results = cursor.execute(
                "SELECT * FROM knowledge_base WHERE embedding IS NOT NULL"
            ).fetchall()
            
            # Calculate similarity scores
            scored_memories = []
            for row in results:
                memory = dict(row)
                
                # Deserialize embedding (handle both pickle and JSON formats)
                try:
                    # Try JSON first (newer format)
                    stored_embedding = json.loads(memory['embedding'].decode('utf-8'))
                except (json.JSONDecodeError, AttributeError):
                    # Fall back to pickle (older format)
                    stored_embedding = pickle.loads(memory['embedding'])
                
                # Calculate similarity
                similarity = cosine_similarity(query_embedding, stored_embedding)
                
                # Only include if above threshold
                if similarity >= similarity_threshold:
                    memory['similarity'] = similarity
                    # Remove the embedding blob from result (too large)
                    del memory['embedding']
                    scored_memories.append(memory)
            
            # Sort by similarity (highest first), then by importance
            scored_memories.sort(key=lambda x: (x['similarity'], x['importance']), reverse=True)
            
            # If no results, fall back to FTS5 keyword search
            if not scored_memories:
                # FTS5 has its own AND→OR→LIKE fallback
                return self.fts_search(query, limit=limit)
            
            return scored_memories[:limit]
            
        except Exception as e:
            # If embedding generation fails, fall back to FTS5
            return self.fts_search(query, limit=limit)
    
    # ========== Conversation History ==========
    
    def log_conversation(self, user_query: str, jarvis_response: str, 
                        tools_used: List[str] = None, session_id: str = None,
                        success: bool = True, metadata: dict = None) -> int:
        """
        Log a conversation exchange with optional metadata.
        
        Args:
            user_query: What the user asked
            jarvis_response: How Jarvis responded
            tools_used: List of tools executed
            session_id: Session identifier
            success: Whether the task succeeded
            metadata: Optional dict with model, timing, cost, etc.
        
        Returns:
            Conversation ID
        """
        cursor = self.conn.cursor()
        
        tools_json = json.dumps(tools_used) if tools_used else None
        metadata_json = json.dumps(metadata) if metadata else None
        
        cursor.execute("""
            INSERT INTO conversations (user_query, jarvis_response, tools_used, session_id, success, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_query, jarvis_response, tools_json, session_id, success, metadata_json))
        
        self.conn.commit()
        return cursor.lastrowid
    
    def get_recent_conversations(self, limit: int = 10, session_id: str = None) -> List[Dict]:
        """Get recent conversation history."""
        cursor = self.conn.cursor()
        
        if session_id:
            results = cursor.execute("""
                SELECT * FROM conversations 
                WHERE session_id = ?
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (session_id, limit)).fetchall()
        else:
            results = cursor.execute("""
                SELECT * FROM conversations 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (limit,)).fetchall()
        
        return [dict(row) for row in results]
    
    def search_conversations(self, query: str, limit: int = 5) -> List[Dict]:
        """Search conversation history."""
        cursor = self.conn.cursor()
        
        results = cursor.execute("""
            SELECT * FROM conversations
            WHERE user_query LIKE ? OR jarvis_response LIKE ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (f"%{query}%", f"%{query}%", limit)).fetchall()
        
        return [dict(row) for row in results]
    
    # ========== Preferences ==========
    
    def set_preference(self, key: str, value: str):
        """Set a user preference."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO preferences (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (key, value))
        self.conn.commit()
    
    def get_preference(self, key: str, default: str = None) -> Optional[str]:
        """Get a user preference."""
        cursor = self.conn.cursor()
        result = cursor.execute(
            "SELECT value FROM preferences WHERE key = ?",
            (key,)
        ).fetchone()
        
        return result['value'] if result else default
    
    # ========== FTS5 Management ==========
    
    def rebuild_fts_index(self) -> int:
        """
        Rebuild FTS5 index from existing knowledge_base data.
        Call this after upgrading to FTS5 or if index is corrupted.
        
        Returns:
            Number of records indexed
        """
        cursor = self.conn.cursor()
        
        # Rebuild FTS5 index using the 'rebuild' command
        # This is the proper way to rebuild an FTS5 index
        try:
            cursor.execute("INSERT INTO knowledge_base_fts(knowledge_base_fts) VALUES('rebuild')")
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            # Table needs to be populated from scratch
            # This happens on first run after upgrade
            cursor.execute("""
                INSERT INTO knowledge_base_fts(rowid, category, key, value, long_form)
                SELECT id, category, key, value, long_form FROM knowledge_base
            """)
        
        self.conn.commit()
        
        # Return count
        count = cursor.execute("SELECT COUNT(*) FROM knowledge_base_fts").fetchone()[0]
        return count
    
    # ========== Tool RAG Operations ==========
    
    def upsert_tool(self, name: str, description: str, schema_json: str, enabled: bool = True) -> None:
        """
        Insert or update a tool definition in the database.
        Automatically generates embedding for semantic search.
        """
        cursor = self.conn.cursor()
        
        # Generate embedding
        embedding_blob = None
        try:
            from embeddings import get_embedding
            # Combine name and description for embedding
            text = f"Tool {name}: {description}"
            embedding_vector = get_embedding(text)
            embedding_blob = pickle.dumps(embedding_vector)
        except Exception as e:
            # Log warning but continue (tool will only be findable by name)
            print(f"⚠️ Failed to generate embedding for tool {name}: {e}")
        
        cursor.execute("""
            INSERT OR REPLACE INTO tool_definitions (name, description, schema_json, embedding, enabled, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (name, description, schema_json, embedding_blob, enabled))
        
        self.conn.commit()
    
    def search_tools(self, query: str, limit: int = 5, threshold: float = 0.0) -> List[Dict]:
        """
        Semantically search for relevant tools.
        
        Args:
            query: User's natural language request
            limit: Max number of tools to return
            threshold: Minimum similarity score (0.0-1.0). Set to 0.0 to disable.
            
        Returns:
            List of tool definitions with similarity scores
        """
        cursor = self.conn.cursor()
        
        try:
            from embeddings import get_embedding, cosine_similarity
            import logging
            logger = logging.getLogger(__name__)
            
            # 1. Generate query embedding
            query_embedding = get_embedding(query)
            
            # 2. Get all ENABLED tools with embeddings
            results = cursor.execute("""
                SELECT name, description, schema_json, embedding 
                FROM tool_definitions 
                WHERE enabled = 1 AND embedding IS NOT NULL
            """).fetchall()
            
            logger.info(f"[TOOL_SEARCH] Searching {len(results)} enabled tools for query: '{query[:100]}...'")
            
            # 3. Calculate similarity
            scored_tools = []
            for row in results:
                tool = dict(row)
                try:
                    # Deserialize embedding
                    blob = tool['embedding']
                    stored_embedding = None
                    
                    # Try pickle first (since we know it's pickle from debug)
                    try:
                        stored_embedding = pickle.loads(blob)
                    except Exception:
                        # If pickle fails, try JSON (newer format)
                        try:
                            if isinstance(blob, bytes):
                                stored_embedding = json.loads(blob.decode('utf-8'))
                            else:
                                stored_embedding = json.loads(blob)
                        except Exception:
                            pass
                    
                    if stored_embedding:
                        similarity = cosine_similarity(query_embedding, stored_embedding)
                        tool['similarity'] = similarity
                        del tool['embedding']  # Remove blob to save memory
                        scored_tools.append(tool)
                except Exception as e:
                    logger.warning(f"⚠️ Error processing tool {tool.get('name')}: {e}")
                    continue
            
            # 4. Sort by similarity
            scored_tools.sort(key=lambda x: x['similarity'], reverse=True)
            
            # 5. Apply threshold filter if set
            if threshold > 0.0:
                filtered = [t for t in scored_tools if t['similarity'] >= threshold]
                logger.info(f"[TOOL_SEARCH] Threshold {threshold}: {len(filtered)}/{len(scored_tools)} tools passed")
                scored_tools = filtered
            
            # 6. Limit results
            final_tools = scored_tools[:limit]
            
            # Log top results for debugging
            for i, tool in enumerate(final_tools[:5]):  # Show top 5
                logger.info(f"[TOOL_SEARCH]   #{i+1}: {tool['name']} (score: {tool['similarity']:.4f})")
            
            return final_tools
            
        except Exception as e:
            # Fallback: Basic keyword match
            print(f"⚠️ Semantic tool search failed: {e}. Falling back to keyword search.")
            results = cursor.execute("""
                SELECT name, description, schema_json 
                FROM tool_definitions 
                WHERE enabled = 1 AND (name LIKE ? OR description LIKE ?)
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit)).fetchall()
            
            return [dict(row) for row in results]

    def get_tool_definition(self, name: str) -> Optional[Dict]:
        """Get specific tool definition by name."""
        cursor = self.conn.cursor()
        result = cursor.execute(
            "SELECT name, description, schema_json FROM tool_definitions WHERE name = ?",
            (name,)
        ).fetchone()
        
        if result:
            return dict(result)
        return None

    # ========== Utility ==========
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def get_memory_db() -> MemoryDB:
    """Get memory database instance."""
    return MemoryDB()

