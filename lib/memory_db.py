#!/usr/bin/env python3
"""
Jarvis Memory Database
SQLite-based memory system for storing facts, conversations, and learned patterns.
Supports semantic search with vector embeddings.
"""
import hashlib
import sqlite3
import json
import os
import pickle
import logging
from pathlib import Path


def _tool_definition_content_hash(name: str, description: str, schema_json: str, enabled: bool) -> str:
    """SHA-256 of inputs that affect Tool RAG embedding and tool identity."""
    payload = f"{name}\x00{description}\x00{schema_json}\x00{1 if enabled else 0}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
        self.last_semantic_search_meta = {"fallback_embeddings": None}
        self.last_tool_search_meta = {"fallback_embeddings": None}
        self._init_db()
    
    def _init_db(self):
        """Initialize database and create tables."""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Return rows as dictionaries
        
        # SECURITY: Restrict DB file to owner-only (600) since it contains
        # conversations, memories, and personal data. sqlite3.connect() uses
        # the process umask (typically 022 → 644), so we fix it after creation.
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass  # Non-fatal: may fail on some filesystems
        
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

        # Self-heal older DBs created before newer conversation metadata support.
        self._ensure_column(cursor, "conversations", "metadata", "TEXT")
        
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
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                embedding_input_hash TEXT
            )
        """)
        self._ensure_column(cursor, "tool_definitions", "embedding_input_hash", "TEXT")
        
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

    def _ensure_column(self, cursor: sqlite3.Cursor, table: str, column: str, definition: str) -> None:
        """Add a missing column to an existing SQLite table."""
        columns = {
            row["name"] if isinstance(row, sqlite3.Row) else row[1]
            for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    
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
            except Exception:
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
    
    def recall(self, query: str, category: str = None, limit: int = 5) -> list[dict]:
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

    def _get_sibling_db_path(self) -> Path | None:
        """Return the sibling cloud/local DB path for standard memory DB names."""
        path = Path(self.db_path)
        if path.name == "jarvis_memory.db":
            return path.with_name("jarvis_memory_local.db")
        if path.name == "jarvis_memory_local.db":
            return path.with_name("jarvis_memory.db")
        return None

    def _update_matching_memory_in_sibling(
        self,
        category: str,
        key: str,
        *,
        value: str | None,
        importance: int | None,
    ) -> int:
        """
        Update the equivalent logical memory in the sibling DB by category+key.

        Safety:
        - Skips if sibling DB does not exist
        - Does not create missing DBs on fresh installs
        """
        sibling_path = self._get_sibling_db_path()
        if not sibling_path or not sibling_path.exists():
            return 0

        conn = sqlite3.connect(str(sibling_path))
        try:
            cursor = conn.cursor()
            updates = []
            params = []

            if value is not None:
                updates.append("value = ?")
                params.append(value)
            if importance is not None:
                updates.append("importance = ?")
                params.append(importance)
            if not updates:
                return 0

            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.extend([category, key])
            cursor.execute(
                f"UPDATE knowledge_base SET {', '.join(updates)} WHERE category = ? AND key = ?",
                params,
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def _delete_matching_memory_from_sibling(self, category: str, key: str) -> int:
        """
        Delete the equivalent logical memory from the sibling DB by category+key.

        Safety:
        - Skips if sibling DB does not exist
        - Does not create missing DBs on fresh installs
        """
        sibling_path = self._get_sibling_db_path()
        if not sibling_path or not sibling_path.exists():
            return 0

        conn = sqlite3.connect(str(sibling_path))
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM knowledge_base WHERE category = ? AND key = ?",
                (category, key),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
    
    def update_memory(self, memory_id: int, value: str = None, importance: int = None) -> bool:
        """Update an existing memory."""
        cursor = self.conn.cursor()
        existing = cursor.execute(
            "SELECT category, key FROM knowledge_base WHERE id = ?",
            (memory_id,),
        ).fetchone()
        if not existing:
            return False
        
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
        updated = cursor.rowcount > 0
        if updated:
            self._update_matching_memory_in_sibling(
                existing["category"],
                existing["key"],
                value=value,
                importance=importance,
            )

        return updated
    
    def forget(self, memory_id: int, *, mirror_sibling: bool = True) -> bool:
        """
        Delete a memory from this DB.

        When mirror_sibling is True (default), also deletes the sibling cloud/local row
        matching the same category+key if that sibling DB exists.

        Use mirror_sibling=False for callers that remove duplicate rows by id on only the
        active DB (e.g. memory_deduper apply): the sibling may hold a single correct row
        while this DB has multiple identical keys.
        """
        cursor = self.conn.cursor()
        row = cursor.execute(
            "SELECT category, key FROM knowledge_base WHERE id = ?",
            (memory_id,),
        ).fetchone()
        if not row:
            return False

        cursor.execute("DELETE FROM knowledge_base WHERE id = ?", (memory_id,))
        self.conn.commit()
        deleted = cursor.rowcount > 0
        if deleted and mirror_sibling:
            self._delete_matching_memory_from_sibling(row["category"], row["key"])
        return deleted
    
    def search_memory(self, query: str, limit: int = 10) -> list[dict]:
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
    
    def fts_search(self, query: str, limit: int = 10) -> list[dict]:
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
        
        def _try_fts_query(fts_query: str) -> list[dict]:
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
    
    def get_all_memories(self, category: str = None) -> list[dict]:
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
    
    def get_addressing_preferences(self, limit: int = 2) -> list[dict]:
        """
        Get ONLY addressing/response-style preferences that affect every response.
        E.g. how_to_address_user, address_user, response_tone, response_style.
        These are the only memories that should be always-included regardless of query.
        Topic-specific preferences (dog, Spotify, etc.) go through semantic search only.
        """
        cursor = self.conn.cursor()
        # Use ESCAPE for underscore - in LIKE, _ matches any char; we want literal "how_to"
        results = cursor.execute(
            """SELECT id, category, key, value, importance, created_at, updated_at, source, metadata
               FROM knowledge_base
               WHERE (
                   key LIKE '%address%' ESCAPE '\\'
                   OR key LIKE '%how\\_to%' ESCAPE '\\'
                   OR key LIKE '%response_tone%' OR key LIKE '%response_style%'
                   OR key LIKE '%preferred_language%'
               )
               ORDER BY importance DESC, updated_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in results]
    
    def semantic_search(self, query: str, limit: int = 5, similarity_threshold: float = None) -> list[dict]:
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
        logger = logging.getLogger(__name__)
        self.last_semantic_search_meta = {"fallback_embeddings": None}
        try:
            from embeddings import (
                get_embedding,
                cosine_similarity,
                reset_embedding_fallback_tracking,
                consume_embedding_fallback_tracking,
            )
            from config_loader import get_float
            
            # Use provided threshold or read from config
            if similarity_threshold is None:
                similarity_threshold = get_float('SEMANTIC_SIMILARITY_THRESHOLD', 0.40)
            
            # Generate embedding for query
            reset_embedding_fallback_tracking()
            query_embedding = get_embedding(query)
            self.last_semantic_search_meta = consume_embedding_fallback_tracking()
            if self.last_semantic_search_meta.get("fallback_embeddings"):
                logger.warning(
                    "[SEMANTIC_SEARCH] Fallback embeddings used for query: '%s...'",
                    query[:120],
                )
            
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
                except (json.JSONDecodeError, AttributeError, UnicodeDecodeError):
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
            
        except Exception:
            # If embedding generation fails, fall back to FTS5
            self.last_semantic_search_meta = {"fallback_embeddings": None}
            return self.fts_search(query, limit=limit)
    
    # ========== Conversation History ==========
    
    def log_conversation(self, user_query: str, jarvis_response: str, 
                        tools_used: list[str] = None, session_id: str = None,
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
    
    def get_recent_conversations(self, limit: int = 10, session_id: str = None) -> list[dict]:
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
    
    def search_conversations(self, query: str, limit: int = 5, 
                             web_conversation_id: str = None) -> list[dict]:
        """
        Search conversation history with tiered approach.
        
        Search strategy (similar to fts_search):
        1. Try exact phrase match (original query as-is)
        2. Try ANY term match (OR logic - finds conversations with any keyword)
        3. Search metadata for web_conversation_id if provided
        
        Args:
            query: Search query (supports multiple words)
            limit: Max results
            web_conversation_id: Optional - filter by web UI conversation ID
            
        Returns:
            List of matching conversations
        """
        cursor = self.conn.cursor()
        
        # If searching by web conversation ID, filter by metadata
        if web_conversation_id:
            results = cursor.execute("""
                SELECT * FROM conversations
                WHERE metadata LIKE ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (f'%"web_conversation_id": "{web_conversation_id}"%', limit)).fetchall()
            if results:
                return [dict(row) for row in results]
        
        # Stop words to filter out for term extraction
        stop_words = {'the', 'is', 'at', 'on', 'and', 'or', 'to', 'a', 'an', 'in', 
                      'of', 'for', 'with', 'as', 'by', 'my', 'can', 'you', 'check', 
                      'see', 'if', 'up', 'what', 'how', 'when', 'where', 'why', 'do',
                      'did', 'does', 'was', 'were', 'have', 'has', 'had', 'about',
                      'this', 'that', 'these', 'those', 'it', 'its', 'i', 'me', 'we'}
        
        # 1. Try exact phrase match first
        results = cursor.execute("""
            SELECT * FROM conversations
            WHERE user_query LIKE ? OR jarvis_response LIKE ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (f"%{query}%", f"%{query}%", limit)).fetchall()
        
        if results:
            return [dict(row) for row in results]
        
        # 2. Extract terms and try ANY match (OR logic)
        # Handle "term1 OR term2" syntax and plain space-separated words
        if ' OR ' in query.upper():
            # Explicit OR syntax: "video OR poster OR pickle"
            terms = [t.strip() for t in query.upper().split(' OR ')]
            terms = [t for t in terms if t.lower() not in stop_words and len(t) > 1]
        else:
            # Space-separated: treat as implicit OR
            terms = [t.strip('?,!.').lower() for t in query.split() 
                     if t.lower() not in stop_words and len(t) > 2]
        
        if terms:
            # Build OR query: (user_query LIKE '%term1%' OR user_query LIKE '%term2%' ...)
            conditions = []
            params = []
            for term in terms:
                conditions.append("(user_query LIKE ? OR jarvis_response LIKE ?)")
                params.extend([f"%{term}%", f"%{term}%"])
            
            where_clause = " OR ".join(conditions)
            params.append(limit)
            
            results = cursor.execute(f"""
                SELECT * FROM conversations
                WHERE {where_clause}
                ORDER BY timestamp DESC
                LIMIT ?
            """, params).fetchall()
            
            if results:
                return [dict(row) for row in results]
        
        # 3. Try metadata search (for queries about tools, providers, etc.)
        results = cursor.execute("""
            SELECT * FROM conversations
            WHERE metadata LIKE ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (f"%{query}%", limit)).fetchall()
        
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
    
    def get_preference(self, key: str, default: str = None) -> str | None:
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
    
    def upsert_tool(
        self,
        name: str,
        description: str,
        schema_json: str,
        enabled: bool = True,
        force_reembed: bool = False,
    ) -> str:
        """
        Insert or update a tool definition in the database.
        Generates an embedding for semantic search unless content hash matches
        the stored row and force_reembed is False (skips embedding API).

        Returns:
            "skipped" — embedding reused (hash unchanged)
            "embedded" — new or regenerated embedding
        """
        cursor = self.conn.cursor()
        new_hash = _tool_definition_content_hash(name, description, schema_json, enabled)

        embedding_blob = None
        skip_embed = False
        if not force_reembed:
            row = cursor.execute(
                "SELECT embedding, embedding_input_hash FROM tool_definitions WHERE name = ?",
                (name,),
            ).fetchone()
            if (
                row
                and row["embedding"] is not None
                and row["embedding_input_hash"] is not None
                and row["embedding_input_hash"] == new_hash
            ):
                skip_embed = True
                embedding_blob = row["embedding"]

        if not skip_embed:
            try:
                from embeddings import get_embedding
                text = f"Tool {name}: {description}"
                embedding_vector = get_embedding(text)
                embedding_blob = pickle.dumps(embedding_vector)
            except Exception as e:
                print(f"⚠️ Failed to generate embedding for tool {name}: {e}")

        cursor.execute("""
            INSERT OR REPLACE INTO tool_definitions (
                name, description, schema_json, embedding, enabled, updated_at, embedding_input_hash
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
        """, (name, description, schema_json, embedding_blob, enabled, new_hash))

        self.conn.commit()
        return "skipped" if skip_embed else "embedded"
    
    def search_tools(self, query: str, limit: int = 5, threshold: float = 0.0) -> list[dict]:
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
        self.last_tool_search_meta = {"fallback_embeddings": None}
        
        try:
            from embeddings import (
                get_embedding,
                cosine_similarity,
                reset_embedding_fallback_tracking,
                consume_embedding_fallback_tracking,
            )
            logger = logging.getLogger(__name__)
            
            # 1. Generate query embedding
            reset_embedding_fallback_tracking()
            query_embedding = get_embedding(query)
            self.last_tool_search_meta = consume_embedding_fallback_tracking()
            if self.last_tool_search_meta.get("fallback_embeddings"):
                logger.warning(
                    "[TOOL_SEARCH] Fallback embeddings used for query: '%s...'",
                    query[:120],
                )
            
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
            self.last_tool_search_meta = {"fallback_embeddings": None}
            print(f"⚠️ Semantic tool search failed: {e}. Falling back to keyword search.")
            results = cursor.execute("""
                SELECT name, description, schema_json 
                FROM tool_definitions 
                WHERE enabled = 1 AND (name LIKE ? OR description LIKE ?)
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit)).fetchall()
            
            return [dict(row) for row in results]

    def get_tool_definition(self, name: str) -> dict | None:
        """Get specific tool definition by name."""
        cursor = self.conn.cursor()
        result = cursor.execute(
            "SELECT name, description, schema_json FROM tool_definitions WHERE name = ?",
            (name,)
        ).fetchone()
        
        if result:
            return dict(result)
        return None

    def get_enabled_tool_names(self) -> list[str]:
        """
        Get list of all enabled tool names.
        Used for filtering insights to only recommend available tools.
        """
        cursor = self.conn.cursor()
        results = cursor.execute(
            "SELECT name FROM tool_definitions WHERE enabled = 1"
        ).fetchall()
        return [row[0] for row in results]

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
