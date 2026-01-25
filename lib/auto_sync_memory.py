#!/usr/bin/env python3
"""
Auto-sync memory databases between modes.
Called at startup to ensure both databases are current.
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))


def should_sync(source_db: Path, target_db: Path) -> bool:
    """Check if target DB needs syncing from source."""
    if not target_db.exists():
        # Target doesn't exist - needs initial sync
        return True
    
    if not source_db.exists():
        # Source doesn't exist - no sync needed
        return False
    
    # Compare modification times
    source_time = source_db.stat().st_mtime
    target_time = target_db.stat().st_mtime
    
    # Sync if source is newer
    return source_time > target_time


def auto_sync_on_startup(current_mode: str, verbose: bool = False):
    """
    Auto-sync databases when Jarvis starts.
    
    Syncs FROM the other mode TO current mode if needed.
    This ensures current mode has latest data.
    
    Args:
        current_mode: 'cloud' or 'local'
        verbose: Print sync status
    """
    project_root = Path(__file__).parent.parent
    
    cloud_db = project_root / 'data' / 'jarvis_memory.db'
    local_db = project_root / 'data' / 'jarvis_memory_local.db'
    
    # Determine source and target
    if current_mode == 'local':
        source_db = cloud_db
        target_db = local_db
        source_mode = 'cloud'
        target_mode = 'local'
    else:
        source_db = local_db
        target_db = cloud_db
        source_mode = 'local'
        target_mode = 'cloud'
    
    # Check if sync needed
    if not should_sync(source_db, target_db):
        if verbose:
            print(f"📊 Memory sync: {target_mode} DB is current")
        return False
    
    # Perform sync
    if verbose:
        print(f"🔄 Auto-syncing memory: {source_mode} → {target_mode}")
    
    try:
        # Import and run sync
        import subprocess
        
        sync_script = project_root / 'bin' / 'sync-memory-db.py'
        result = subprocess.run(
            [sys.executable, str(sync_script), 
             '--from', source_mode, '--to', target_mode,
             '--quiet'],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            if verbose:
                print(f"✅ Memory synced successfully")
            return True
        else:
            if verbose:
                print(f"⚠️  Sync warning: {result.stderr}")
            return False
    
    except Exception as e:
        if verbose:
            print(f"⚠️  Auto-sync failed: {e}")
        return False


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Auto-sync memory on startup')
    parser.add_argument('mode', choices=['cloud', 'local'], 
                       help='Current mode being started')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Verbose output')
    
    args = parser.parse_args()
    
    auto_sync_on_startup(args.mode, verbose=args.verbose)
