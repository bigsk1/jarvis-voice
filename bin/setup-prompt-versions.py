#!/usr/bin/env python3
"""
Setup prompt_versions table for self-evolving prompts.
Run once to create the schema, safe to run multiple times.
"""

import os
import sys
import sqlite3

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

def get_db_path(mode: str = None) -> str:
    """Get database path based on mode."""
    if mode is None:
        mode = 'local' if os.environ.get('LLM_PROVIDER') == 'ollama' else 'cloud'
    
    base_path = os.path.join(os.path.dirname(__file__), '..', 'data')
    if mode == 'local':
        return os.path.join(base_path, 'jarvis_memory_local.db')
    return os.path.join(base_path, 'jarvis_memory.db')


def create_schema(db_path: str):
    """Create prompt_versions table."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create prompt_versions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prompt_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            
            -- What this prompt is for
            component TEXT NOT NULL,           -- 'system_prompt', 'tool:search_memory', etc.
            component_type TEXT NOT NULL,      -- 'system', 'tool_description', 'tool_schema'
            
            -- Version tracking
            version INTEGER NOT NULL,
            content TEXT NOT NULL,             -- The actual prompt/description text
            
            -- Lineage
            parent_version_id INTEGER,         -- Which version this evolved from
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT 'human',   -- 'human', 'auto_evolution', 'rollback'
            
            -- Performance metrics
            times_used INTEGER DEFAULT 0,
            total_rating_sum REAL DEFAULT 0,
            
            -- Status
            is_active BOOLEAN DEFAULT FALSE,
            is_archived BOOLEAN DEFAULT FALSE,
            
            -- Audit trail
            trigger_feedback_ids TEXT,         -- JSON array of feedback IDs that triggered this
            change_summary TEXT,               -- LLM-generated summary of what changed
            
            FOREIGN KEY (parent_version_id) REFERENCES prompt_versions(id)
        )
    """)
    
    # Create indexes
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_prompt_active 
        ON prompt_versions(component, is_active)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_prompt_component 
        ON prompt_versions(component, version DESC)
    """)
    
    # Create prompt_evolution_log table for audit
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prompt_evolution_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            action TEXT NOT NULL,              -- 'evolution', 'rollback', 'ab_test_start', 'ab_test_end'
            component TEXT NOT NULL,
            from_version_id INTEGER,
            to_version_id INTEGER,
            trigger_type TEXT,                 -- 'low_feedback', 'degradation', 'manual'
            trigger_details TEXT,              -- JSON with details
            status TEXT,                       -- 'success', 'failed', 'pending'
            notes TEXT
        )
    """)
    
    # Create prompt_backups table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prompt_backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            component TEXT NOT NULL,
            version_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            reason TEXT,                       -- 'pre_evolution', 'manual_backup', 'pre_rollback'
            FOREIGN KEY (version_id) REFERENCES prompt_versions(id)
        )
    """)
    
    conn.commit()
    conn.close()
    print(f"✅ Schema created in {db_path}")


def seed_initial_versions(db_path: str):
    """Seed initial prompt versions from current tool descriptions."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if we already have data
    cursor.execute("SELECT COUNT(*) FROM prompt_versions")
    if cursor.fetchone()[0] > 0:
        print("ℹ️  prompt_versions already has data, skipping seed")
        conn.close()
        return
    
    skills_dir = os.path.join(os.path.dirname(__file__), '..', 'skills')
    import json
    
    seeded = 0
    for filename in os.listdir(skills_dir):
        if filename.endswith('.tool.json'):
            filepath = os.path.join(skills_dir, filename)
            try:
                with open(filepath, 'r') as f:
                    tool_data = json.load(f)
                
                tool_name = tool_data.get('name', filename.replace('.tool.json', ''))
                description = tool_data.get('description', '')
                
                if description:
                    cursor.execute("""
                        INSERT INTO prompt_versions 
                        (component, component_type, version, content, created_by, is_active)
                        VALUES (?, 'tool_description', 1, ?, 'human', TRUE)
                    """, (f"tool:{tool_name}", description))
                    seeded += 1
                    
            except Exception as e:
                print(f"⚠️  Error reading {filename}: {e}")
    
    # Seed system prompt (extract from router_v2.py later, for now placeholder)
    cursor.execute("""
        INSERT INTO prompt_versions 
        (component, component_type, version, content, created_by, is_active)
        VALUES ('system_prompt', 'system', 1, 'See router_v2.py SYSTEM_PROMPT', 'human', TRUE)
    """)
    seeded += 1
    
    conn.commit()
    conn.close()
    print(f"✅ Seeded {seeded} initial prompt versions")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Setup prompt_versions schema')
    parser.add_argument('mode', nargs='?', choices=['cloud', 'local', 'both'], default='both',
                       help='Which database to setup (default: both)')
    parser.add_argument('--seed', action='store_true', help='Seed initial versions from tools')
    args = parser.parse_args()
    
    if args.mode == 'both':
        modes = ['cloud', 'local']
    else:
        modes = [args.mode]
    
    for mode in modes:
        print(f"\n{'='*50}")
        print(f"Setting up {mode} database")
        print('='*50)
        
        db_path = get_db_path(mode)
        create_schema(db_path)
        
        if args.seed:
            seed_initial_versions(db_path)


if __name__ == "__main__":
    main()

