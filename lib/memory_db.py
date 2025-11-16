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
            db_path: Path to SQLite database file
        """
        if db_path is None:
            # Default to project data directory
            project_root = Path(__file__).parent.parent.resolve()
            data_dir = project_root / "data"
            data_dir.mkdir(exist_ok=True)
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
                embedding BLOB
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
        
        return [dict(row) for row in results]
    
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
        Search all memories by query.
        
        Args:
            query: Search term
            limit: Max results
            
        Returns:
            List of memories with relevance
        """
        return self.recall(query, limit=limit)
    
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
        Semantic search using vector embeddings.
        Finds memories similar in meaning, not just keywords.
        
        Args:
            query: Search query (can be natural language)
            limit: Maximum number of results
            similarity_threshold: Minimum similarity score (0-1)
                If None, reads from SEMANTIC_SIMILARITY_THRESHOLD env var (default 0.40)
                Lower = more results (may include loosely related)
                Higher = fewer results (only close matches)
            
        Returns:
            List of memories with similarity scores, sorted by relevance
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
                
                # Deserialize embedding
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
            
            return scored_memories[:limit]
            
        except Exception as e:
            # Fallback to keyword search if embedding fails
            return self.recall(query, limit=limit)
    
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

