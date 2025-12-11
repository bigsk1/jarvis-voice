#!/usr/bin/env python3
"""
Stash Helper Library
Generic artifact storage layer for the Jarvis ecosystem.

This module provides the core functionality for the stash system,
allowing tools and internal services to store and retrieve artifacts.
"""

import os
import sys
import json
import hashlib
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import mimetypes

# Add lib to path for config
sys.path.insert(0, os.path.dirname(__file__))
from config_loader import get_config_value, get_int


# ============================================================================
# Configuration
# ============================================================================

def get_stash_dir() -> Path:
    """Get the stash directory path."""
    stash_dir = get_config_value('STASH_DIR', 'data/stash')
    # Handle relative paths
    if not os.path.isabs(stash_dir):
        project_root = Path(__file__).parent.parent
        stash_dir = project_root / stash_dir
    return Path(stash_dir)


def get_default_ttl() -> int:
    """Get default TTL in days."""
    return get_int('STASH_DEFAULT_TTL_DAYS', 7)


def get_max_space_size() -> int:
    """Get max space size in bytes."""
    mb = get_int('STASH_MAX_SPACE_SIZE_MB', 500)
    return mb * 1024 * 1024


def get_max_total_size() -> int:
    """Get max total stash size in bytes."""
    gb = get_int('STASH_MAX_TOTAL_SIZE_GB', 5)
    return gb * 1024 * 1024 * 1024


# ============================================================================
# Security Helpers
# ============================================================================

def sanitize_filename(name: str) -> str:
    """Sanitize filename to prevent path traversal and invalid characters."""
    if not name:
        return 'unnamed_file'
    
    # Remove path separators
    name = os.path.basename(name)
    
    # Remove dangerous characters
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    
    # Limit length
    name = name[:200]
    
    # Ensure not empty or dangerous
    if not name or name in ['.', '..']:
        name = 'unnamed_file'
    
    return name


def generate_file_id(name: str) -> str:
    """Generate a unique file ID based on name and timestamp."""
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
    hash_input = f"{name}_{timestamp}"
    short_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:12]
    return f"f_{short_hash}"


def generate_space_id() -> str:
    """Generate a unique space ID."""
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    random_suffix = hashlib.sha256(os.urandom(16)).hexdigest()[:8]
    return f"space_{timestamp}_{random_suffix}"


def compute_hash(data: bytes) -> str:
    """Compute SHA256 hash of data."""
    return hashlib.sha256(data).hexdigest()


# ============================================================================
# Space Management
# ============================================================================

class StashSpace:
    """Represents a stash space (task bucket)."""
    
    def __init__(self, space_id: str, stash_dir: Path = None):
        self.space_id = space_id
        self.stash_dir = stash_dir or get_stash_dir()
        self.space_path = self.stash_dir / space_id
        self.meta_path = self.space_path / 'meta.json'
        self._meta = None
    
    @property
    def exists(self) -> bool:
        return self.space_path.exists() and self.meta_path.exists()
    
    @property
    def meta(self) -> Dict:
        if self._meta is None:
            self._load_meta()
        return self._meta
    
    def _load_meta(self):
        """Load metadata from disk."""
        if self.meta_path.exists():
            with open(self.meta_path, 'r') as f:
                self._meta = json.load(f)
        else:
            self._meta = {}
    
    def _save_meta(self):
        """Save metadata to disk."""
        with open(self.meta_path, 'w') as f:
            json.dump(self._meta, f, indent=2)
    
    def create(self, labels: List[str] = None, scope: str = 'session', 
               ttl_days: int = None, owner: str = 'jarvis') -> Dict:
        """Create a new space."""
        if self.exists:
            raise ValueError(f"Space {self.space_id} already exists")
        
        # Create directory
        self.space_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize metadata
        now = datetime.utcnow().isoformat() + 'Z'
        self._meta = {
            'space_id': self.space_id,
            'created_at': now,
            'last_used_at': now,
            'labels': labels or [],
            'owner': owner,
            'scope': scope,
            'ttl_days': ttl_days or get_default_ttl(),
            'pinned': False,
            'files': []
        }
        self._save_meta()
        
        return self._meta
    
    def touch(self):
        """Update last_used_at timestamp."""
        if self.exists:
            self._meta['last_used_at'] = datetime.utcnow().isoformat() + 'Z'
            self._save_meta()
    
    def update(self, ttl_days: int = None, pinned: bool = None, 
               labels: List[str] = None) -> Dict:
        """Update space metadata."""
        if not self.exists:
            raise ValueError(f"Space {self.space_id} does not exist")
        
        # Ensure meta is loaded
        _ = self.meta
        
        if ttl_days is not None:
            self._meta['ttl_days'] = ttl_days
        if pinned is not None:
            self._meta['pinned'] = pinned
        if labels is not None:
            self._meta['labels'] = labels
        
        self._meta['last_used_at'] = datetime.utcnow().isoformat() + 'Z'
        self._save_meta()
        
        return self._meta
    
    def info(self) -> Dict:
        """Get space info summary."""
        if not self.exists:
            raise ValueError(f"Space {self.space_id} does not exist")
        
        # Calculate total size
        total_size = sum(
            f.get('size_bytes', 0) for f in self.meta.get('files', [])
        )
        
        return {
            'space_id': self.space_id,
            'created_at': self.meta.get('created_at'),
            'last_used_at': self.meta.get('last_used_at'),
            'labels': self.meta.get('labels', []),
            'scope': self.meta.get('scope', 'session'),
            'ttl_days': self.meta.get('ttl_days'),
            'pinned': self.meta.get('pinned', False),
            'total_size_bytes': total_size,
            'file_count': len(self.meta.get('files', []))
        }
    
    def is_expired(self) -> bool:
        """Check if space has expired based on TTL."""
        if self.meta.get('pinned', False):
            return False
        
        ttl_days = self.meta.get('ttl_days', get_default_ttl())
        last_used = datetime.fromisoformat(
            self.meta.get('last_used_at', self.meta.get('created_at', '')).rstrip('Z')
        )
        expiry = last_used + timedelta(days=ttl_days)
        
        return datetime.utcnow() > expiry
    
    def delete(self) -> int:
        """Delete the space and return freed bytes."""
        if not self.exists:
            return 0
        
        # Calculate size before deletion
        total_size = 0
        for root, dirs, files in os.walk(self.space_path):
            for f in files:
                total_size += os.path.getsize(os.path.join(root, f))
        
        # Delete
        shutil.rmtree(self.space_path)
        self._meta = None
        
        return total_size


# ============================================================================
# File Operations
# ============================================================================

class StashFile:
    """Represents a file in a stash space."""
    
    def __init__(self, space: StashSpace, file_id: str = None, name: str = None):
        self.space = space
        self.file_id = file_id
        self.name = name
        self._file_meta = None
    
    def _find_by_id(self) -> Optional[Dict]:
        """Find file metadata by file_id."""
        for f in self.space.meta.get('files', []):
            if f.get('file_id') == self.file_id:
                return f
        return None
    
    def _find_by_name(self) -> Optional[Dict]:
        """Find file metadata by name."""
        for f in self.space.meta.get('files', []):
            if f.get('name') == self.name:
                return f
        return None
    
    @property
    def exists(self) -> bool:
        if self.file_id:
            return self._find_by_id() is not None
        if self.name:
            return self._find_by_name() is not None
        return False
    
    @property
    def meta(self) -> Optional[Dict]:
        if self._file_meta is None:
            if self.file_id:
                self._file_meta = self._find_by_id()
            elif self.name:
                self._file_meta = self._find_by_name()
        return self._file_meta
    
    @property
    def path(self) -> Optional[Path]:
        if self.meta:
            return self.space.space_path / self.meta.get('stored_name')
        return None
    
    def save_text(self, content: str, name: str, on_conflict: str = 'error',
                  tags: List[str] = None, tool_origin: str = None) -> Dict:
        """Save text content to a file."""
        data = content.encode('utf-8')
        return self._save_data(data, name, 'text/plain', on_conflict, tags, tool_origin)
    
    def save_json(self, content: Any, name: str, on_conflict: str = 'error',
                  tags: List[str] = None, tool_origin: str = None) -> Dict:
        """Save JSON content to a file."""
        data = json.dumps(content, indent=2).encode('utf-8')
        return self._save_data(data, name, 'application/json', on_conflict, tags, tool_origin)
    
    def save_binary(self, data: bytes, name: str, mime_type: str = None,
                    on_conflict: str = 'error', tags: List[str] = None,
                    tool_origin: str = None) -> Dict:
        """Save binary data to a file."""
        if mime_type is None:
            mime_type, _ = mimetypes.guess_type(name)
            mime_type = mime_type or 'application/octet-stream'
        return self._save_data(data, name, mime_type, on_conflict, tags, tool_origin)
    
    def _save_data(self, data: bytes, name: str, mime_type: str,
                   on_conflict: str, tags: List[str], tool_origin: str) -> Dict:
        """Internal method to save data."""
        sanitized_name = sanitize_filename(name)
        
        # Check for existing file
        self.name = name
        existing = self._find_by_name()
        
        if existing:
            if on_conflict == 'error':
                raise ValueError(f"File '{name}' already exists. Use on_conflict='overwrite' or 'version'")
            elif on_conflict == 'version':
                # Auto-version the filename
                base, ext = os.path.splitext(sanitized_name)
                version = 2
                while True:
                    new_name = f"{base}_{version}{ext}"
                    self.name = new_name
                    if not self._find_by_name():
                        sanitized_name = new_name
                        break
                    version += 1
            # else: overwrite - we'll update the existing entry
        
        # Generate file ID
        file_id = generate_file_id(sanitized_name)
        
        # Compute hash
        file_hash = compute_hash(data)
        
        # Write file
        file_path = self.space.space_path / sanitized_name
        with open(file_path, 'wb') as f:
            f.write(data)
        
        # Create file metadata
        now = datetime.utcnow().isoformat() + 'Z'
        file_meta = {
            'file_id': file_id,
            'name': name,
            'stored_name': sanitized_name,
            'mime_type': mime_type,
            'size_bytes': len(data),
            'hash_sha256': file_hash,
            'tags': tags or [],
            'tool_origin': tool_origin,
            'created_at': now
        }
        
        # Update space metadata
        if existing and on_conflict == 'overwrite':
            # Remove old entry
            self.space._meta['files'] = [
                f for f in self.space._meta['files'] 
                if f.get('name') != name
            ]
        
        self.space._meta['files'].append(file_meta)
        self.space.touch()
        
        # Build reference
        ref = f"stash://{self.space.space_id}/{file_id}"
        
        return {
            'file_id': file_id,
            'name': name,
            'stored_name': sanitized_name,
            'ref': ref,
            'path': str(file_path),
            'mime_type': mime_type,
            'size_bytes': len(data),
            'hash_sha256': file_hash
        }
    
    def read(self, mode: str = 'auto') -> Dict:
        """Read file content or get path."""
        if not self.meta:
            raise ValueError(f"File not found")
        
        file_path = self.path
        if not file_path.exists():
            raise ValueError(f"File data missing: {file_path}")
        
        mime_type = self.meta.get('mime_type', 'application/octet-stream')
        size = self.meta.get('size_bytes', 0)
        
        # Determine if we should return content or path
        is_text = mime_type.startswith('text/') or mime_type == 'application/json'
        is_small = size < 100 * 1024  # 100KB threshold
        
        result = {
            'file_id': self.meta.get('file_id'),
            'name': self.meta.get('name'),
            'mime_type': mime_type,
            'size_bytes': size,
            'ref': f"stash://{self.space.space_id}/{self.meta.get('file_id')}"
        }
        
        if mode == 'metadata':
            return result
        
        if mode == 'path' or (mode == 'auto' and not (is_text and is_small)):
            result['path'] = str(file_path)
        else:
            # Return content
            with open(file_path, 'r' if is_text else 'rb') as f:
                content = f.read()
            result['content'] = content
        
        return result


# ============================================================================
# High-Level API
# ============================================================================

def open_space(space_id: str = None, labels: List[str] = None,
               scope: str = 'session', ttl_days: int = None) -> Tuple[StashSpace, bool]:
    """
    Open or create a stash space.
    
    Returns:
        Tuple of (space, is_new)
    """
    stash_dir = get_stash_dir()
    stash_dir.mkdir(parents=True, exist_ok=True)
    
    if space_id:
        space = StashSpace(space_id, stash_dir)
        if space.exists:
            space.touch()
            return space, False
    else:
        space_id = generate_space_id()
    
    space = StashSpace(space_id, stash_dir)
    space.create(labels=labels, scope=scope, ttl_days=ttl_days)
    return space, True


def get_space(space_id: str) -> StashSpace:
    """Get an existing space."""
    stash_dir = get_stash_dir()
    space = StashSpace(space_id, stash_dir)
    if not space.exists:
        raise ValueError(f"Space {space_id} does not exist")
    return space


def list_spaces() -> List[Dict]:
    """List all stash spaces."""
    stash_dir = get_stash_dir()
    if not stash_dir.exists():
        return []
    
    spaces = []
    for item in stash_dir.iterdir():
        if item.is_dir() and item.name.startswith('space_'):
            try:
                space = StashSpace(item.name, stash_dir)
                if space.exists:
                    spaces.append(space.info())
            except Exception:
                pass
    
    return sorted(spaces, key=lambda x: x.get('last_used_at', ''), reverse=True)


def cleanup_expired() -> Dict:
    """Clean up expired spaces."""
    stash_dir = get_stash_dir()
    if not stash_dir.exists():
        return {'deleted_spaces': 0, 'freed_bytes': 0}
    
    deleted = 0
    freed = 0
    
    for item in stash_dir.iterdir():
        if item.is_dir() and item.name.startswith('space_'):
            try:
                space = StashSpace(item.name, stash_dir)
                if space.exists and space.is_expired():
                    freed += space.delete()
                    deleted += 1
            except Exception:
                pass
    
    return {'deleted_spaces': deleted, 'freed_bytes': freed}


def parse_stash_ref(ref: str) -> Tuple[str, str]:
    """Parse a stash:// reference into (space_id, file_id)."""
    if not ref.startswith('stash://'):
        raise ValueError(f"Invalid stash reference: {ref}")
    
    parts = ref[8:].split('/', 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid stash reference format: {ref}")
    
    return parts[0], parts[1]


def resolve_file_path(space_id: str = None, file_id: str = None,
                      stash_ref: str = None, file_path: str = None) -> str:
    """
    Resolve a file path from various input formats.
    
    This is a helper for tools that want to accept stash references.
    """
    # Direct path
    if file_path:
        return file_path
    
    # Stash URI
    if stash_ref:
        space_id, file_id = parse_stash_ref(stash_ref)
    
    # Explicit space_id + file_id
    if space_id and file_id:
        space = get_space(space_id)
        stash_file = StashFile(space, file_id=file_id)
        if stash_file.path:
            return str(stash_file.path)
        # Try by name if file_id doesn't match
        stash_file = StashFile(space, name=file_id)
        if stash_file.path:
            return str(stash_file.path)
        raise ValueError(f"File {file_id} not found in space {space_id}")
    
    raise ValueError("Provide file_path, stash_ref, or space_id+file_id")

