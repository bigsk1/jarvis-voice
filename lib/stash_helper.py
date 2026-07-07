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
import socket
import ipaddress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import mimetypes

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import magic
    HAS_MAGIC = True
except ImportError:
    HAS_MAGIC = False

# Add lib to path for config
sys.path.insert(0, os.path.dirname(__file__))
from config_loader import get_config_value, get_int
from http_client import http_request
from paths import assert_not_restricted_read_path, get_restricted_read_match


# ============================================================================
# URL Download Security (SSRF Protection)
# ============================================================================

ALLOWED_SCHEMES = ['http', 'https']
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_REDIRECTS = 3
DOWNLOAD_TIMEOUT = 30

# Allowed MIME types for downloads
ALLOWED_MIME_TYPES = [
    # Images
    'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml',
    # Documents
    'application/pdf',
    # Text
    'text/plain', 'text/csv', 'text/html', 'text/markdown',
    # Data
    'application/json', 'application/xml', 'text/xml',
    # Audio (for future TTS/STT workflows)
    'audio/mpeg', 'audio/wav', 'audio/ogg',
]

# Blocked IP ranges (prevent SSRF to internal networks)
BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network('127.0.0.0/8'),       # Loopback
    ipaddress.ip_network('10.0.0.0/8'),        # Private Class A
    ipaddress.ip_network('172.16.0.0/12'),     # Private Class B
    ipaddress.ip_network('192.168.0.0/16'),    # Private Class C
    ipaddress.ip_network('169.254.0.0/16'),    # Link-local
    ipaddress.ip_network('0.0.0.0/8'),         # Current network
    ipaddress.ip_network('224.0.0.0/4'),       # Multicast
    ipaddress.ip_network('240.0.0.0/4'),       # Reserved
]

# IPv6 blocked ranges
BLOCKED_IP6_NETWORKS = [
    ipaddress.ip_network('::1/128'),           # Loopback
    ipaddress.ip_network('fe80::/10'),         # Link-local
    ipaddress.ip_network('fc00::/7'),          # Unique local
    ipaddress.ip_network('ff00::/8'),          # Multicast
]


class SecurityError(Exception):
    """Raised when a security check fails."""
    pass


def is_blocked_ip(ip_str: str) -> bool:
    """Check if an IP address is in a blocked range."""
    try:
        ip = ipaddress.ip_address(ip_str)
        
        if isinstance(ip, ipaddress.IPv4Address):
            return any(ip in network for network in BLOCKED_IP_NETWORKS)
        else:
            return any(ip in network for network in BLOCKED_IP6_NETWORKS)
    except ValueError:
        # Invalid IP = treat as blocked
        return True


def validate_url(url: str) -> str:
    """
    Validate a URL for safe downloading.
    
    Checks:
    - Scheme is http/https
    - Host resolves to a non-private IP
    - Returns the validated URL
    
    Raises SecurityError if validation fails.
    """
    parsed = urlparse(url)
    
    # Check scheme
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise SecurityError(f"URL scheme '{parsed.scheme}' not allowed. Use http or https.")
    
    hostname = parsed.hostname
    if not hostname:
        raise SecurityError("URL has no hostname")
    
    # Resolve hostname to IP and check for private ranges
    try:
        # Get all IPs for the hostname
        ips = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        resolved_ips = set(ip[4][0] for ip in ips)
        
        for ip_str in resolved_ips:
            if is_blocked_ip(ip_str):
                raise SecurityError(f"URL hostname '{hostname}' resolves to blocked IP range")
        
    except socket.gaierror as e:
        raise SecurityError(f"Cannot resolve hostname '{hostname}': {e}")
    
    return url


def safe_download(url: str, max_size: int = None) -> tuple[bytes, str, str]:
    """
    Safely download content from a URL with SSRF protection.
    
    Args:
        url: URL to download
        max_size: Maximum file size in bytes (default: MAX_FILE_SIZE)
    
    Returns:
        Tuple of (data, content_type, final_url)
    
    Raises:
        SecurityError: If security validation fails
        ValueError: If content type not allowed or file too large
    """
    if not HAS_REQUESTS:
        raise ImportError("requests library required for URL downloads. pip install requests")
    
    max_size = max_size or MAX_FILE_SIZE
    
    # Validate initial URL
    validate_url(url)
    
    # Download with manual redirect handling for security (LOCAL_PROXY → LOCAL_PROXY2 → direct)
    current_url = url
    redirects = 0
    
    while True:
        try:
            response = http_request(
                'GET',
                current_url,
                stream=True,
                timeout=DOWNLOAD_TIMEOUT,
                allow_redirects=False,
                use_proxy=True,
                fallback_on_proxy_fail=True,
                headers={'User-Agent': 'Jarvis-Stash/1.0'},
            )
        except requests.exceptions.RequestException as e:
            raise SecurityError(f"Download failed: {e}")
        
        # Handle redirects manually (validate each redirect URL)
        if response.is_redirect:
            redirects += 1
            if redirects > MAX_REDIRECTS:
                raise SecurityError(f"Too many redirects (max {MAX_REDIRECTS})")
            
            redirect_url = response.headers.get('Location')
            if not redirect_url:
                raise SecurityError("Redirect without Location header")
            
            # Handle relative redirects
            if redirect_url.startswith('/'):
                parsed = urlparse(current_url)
                redirect_url = f"{parsed.scheme}://{parsed.netloc}{redirect_url}"
            
            # Validate redirect URL (SSRF check)
            validate_url(redirect_url)
            current_url = redirect_url
            continue
        
        break
    
    response.raise_for_status()
    
    # Check content type
    content_type = response.headers.get('Content-Type', '').split(';')[0].strip()
    if not content_type:
        content_type = 'application/octet-stream'
    
    # Allow through if MIME type is in allowed list
    mime_allowed = content_type in ALLOWED_MIME_TYPES
    
    # Check content length if provided
    content_length = response.headers.get('Content-Length')
    if content_length and int(content_length) > max_size:
        raise ValueError(f"File too large: {int(content_length)} bytes (max {max_size})")
    
    # Stream download with size check
    data = b''
    for chunk in response.iter_content(chunk_size=8192):
        data += chunk
        if len(data) > max_size:
            raise ValueError(f"File exceeded max size during download ({max_size} bytes)")
    
    # Verify content type with magic if available
    if HAS_MAGIC and data:
        detected_type = magic.from_buffer(data, mime=True)
        
        # If claimed type is generic but detected is specific and not allowed
        if content_type == 'application/octet-stream':
            content_type = detected_type
        
        # Check if detected type is allowed
        if detected_type not in ALLOWED_MIME_TYPES and not mime_allowed:
            raise SecurityError(f"Detected content type '{detected_type}' not allowed")
    
    # Final MIME check
    if not mime_allowed and content_type not in ALLOWED_MIME_TYPES:
        raise SecurityError(f"Content type '{content_type}' not allowed")
    
    return data, content_type, current_url


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


def get_retention_policy(labels: list[str] = None, scope: str = 'session') -> tuple[str, int]:
    """Return the automatic retention class and TTL for a stash space."""
    normalized = {str(label).strip().lower() for label in (labels or [])}
    if normalized & {'generated_images', 'generated_videos', 'generated_music'}:
        return 'generated_media', get_int('STASH_GENERATED_MEDIA_TTL_DAYS', 30)
    if scope in {'project', 'user'} or normalized & {
        'web_upload', 'uploaded', 'youtube_downloads', 'youtube_transcripts',
        'pdf', 'pdf_images',
    }:
        return 'source_artifact', get_int('STASH_SOURCE_ARTIFACT_TTL_DAYS', 120)
    return 'temporary', get_default_ttl()


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
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
    hash_input = f"{name}_{timestamp}"
    short_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:12]
    return f"f_{short_hash}"


def generate_space_id() -> str:
    """Generate a unique space ID."""
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
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
    def meta(self) -> dict:
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
    
    def create(self, labels: list[str] = None, scope: str = 'session', 
               ttl_days: int = None, owner: str = 'jarvis') -> dict:
        """Create a new space."""
        if self.exists:
            raise ValueError(f"Space {self.space_id} already exists")
        
        # Create directory
        self.space_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize metadata
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
        if ttl_days is None:
            retention_policy, resolved_ttl_days = get_retention_policy(labels, scope)
        else:
            retention_policy, resolved_ttl_days = 'explicit', ttl_days

        self._meta = {
            'space_id': self.space_id,
            'created_at': now,
            'last_used_at': now,
            'labels': labels or [],
            'owner': owner,
            'scope': scope,
            'ttl_days': resolved_ttl_days,
            'retention_policy': retention_policy,
            'pinned': False,
            'files': []
        }
        self._save_meta()
        
        return self._meta
    
    def touch(self):
        """Update last_used_at timestamp."""
        if self.exists:
            _ = self.meta
            self._meta['last_used_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
            self._save_meta()
    
    def update(self, ttl_days: int = None, pinned: bool = None, 
               labels: list[str] = None) -> dict:
        """Update space metadata."""
        if not self.exists:
            raise ValueError(f"Space {self.space_id} does not exist")
        
        # Ensure meta is loaded
        _ = self.meta
        
        if ttl_days is not None:
            self._meta['ttl_days'] = ttl_days
            self._meta['retention_policy'] = 'explicit'
        if pinned is not None:
            self._meta['pinned'] = pinned
        if labels is not None:
            self._meta['labels'] = labels
        
        self._meta['last_used_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
        self._save_meta()
        
        return self._meta
    
    def info(self) -> dict:
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
    
    @property
    def is_expired(self) -> bool:
        """Check if space has expired based on TTL."""
        if self.meta.get('pinned', False):
            return False
        
        ttl_days = self.meta.get('ttl_days', get_default_ttl())
        last_used = datetime.fromisoformat(
            self.meta.get('last_used_at', self.meta.get('created_at', '')).rstrip('Z')
        )
        expiry = last_used + timedelta(days=ttl_days)
        
        return datetime.now(timezone.utc).replace(tzinfo=None) > expiry
    
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
    
    def _find_by_id(self) -> dict | None:
        """Find file metadata by file_id."""
        for f in self.space.meta.get('files', []):
            if f.get('file_id') == self.file_id:
                return f
        return None
    
    def _find_by_name(self) -> dict | None:
        """Find file metadata by name."""
        for f in self.space.meta.get('files', []):
            if f.get('name') == self.name:
                return f
        return None

    def _find_by_stored_name(self, stored_name: str) -> dict | None:
        """Find metadata by its sanitized on-disk filename."""
        for f in self.space.meta.get('files', []):
            if f.get('stored_name') == stored_name:
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
    def meta(self) -> dict | None:
        if self._file_meta is None:
            if self.file_id:
                self._file_meta = self._find_by_id()
            elif self.name:
                self._file_meta = self._find_by_name()
        return self._file_meta
    
    @property
    def path(self) -> Path | None:
        if self.meta:
            candidate = self.space.space_path / self.meta.get('stored_name')
            return assert_not_restricted_read_path(candidate, label="Stash file")
        return None
    
    def save_text(self, content: str, name: str, on_conflict: str = 'error',
                  tags: list[str] = None, tool_origin: str = None) -> dict:
        """Save text content to a file."""
        data = content.encode('utf-8')
        return self._save_data(data, name, 'text/plain', on_conflict, tags, tool_origin)
    
    def save_json(self, content: Any, name: str, on_conflict: str = 'error',
                  tags: list[str] = None, tool_origin: str = None) -> dict:
        """Save JSON content to a file."""
        data = json.dumps(content, indent=2).encode('utf-8')
        return self._save_data(data, name, 'application/json', on_conflict, tags, tool_origin)
    
    def save_binary(self, data: bytes, name: str, mime_type: str = None,
                    on_conflict: str = 'error', tags: list[str] = None,
                    tool_origin: str = None) -> dict:
        """Save binary data to a file."""
        if mime_type is None:
            mime_type, _ = mimetypes.guess_type(name)
            mime_type = mime_type or 'application/octet-stream'
        return self._save_data(data, name, mime_type, on_conflict, tags, tool_origin)
    
    def save_from_url(self, url: str, name: str = None, on_conflict: str = 'error',
                      tags: list[str] = None, tool_origin: str = None) -> dict:
        """
        Download content from URL and save to stash.
        
        Includes full SSRF protection:
        - Validates URL scheme (http/https only)
        - Blocks private/internal IP ranges
        - Validates redirect URLs
        - Checks content type
        - Enforces size limits
        
        Args:
            url: URL to download
            name: Filename (optional, derived from URL if not provided)
            on_conflict: error, overwrite, or version
            tags: Optional tags for the file
            tool_origin: Tool that initiated the download
        
        Returns:
            File metadata dict with file_id, ref, path, etc.
        """
        # Download with security checks
        data, content_type, final_url = safe_download(url)
        
        # Derive filename from URL if not provided
        if not name:
            parsed = urlparse(final_url)
            path_name = os.path.basename(parsed.path)
            if path_name and '.' in path_name:
                name = path_name
            else:
                # Generate name from content type
                ext = mimetypes.guess_extension(content_type) or ''
                name = f"download_{datetime.now(timezone.utc).strftime('%H%M%S')}{ext}"
        
        # Save the data
        result = self._save_data(data, name, content_type, on_conflict, tags, tool_origin)
        
        # Add source URL to result
        result['source_url'] = url
        if final_url != url:
            result['final_url'] = final_url
        
        return result
    
    def _save_data(self, data: bytes, name: str, mime_type: str,
                   on_conflict: str, tags: list[str], tool_origin: str) -> dict:
        """Internal method to save data."""
        sanitized_name = sanitize_filename(name)
        effective_name = name
        
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
                    if not self._find_by_name() and not self._find_by_stored_name(new_name):
                        sanitized_name = new_name
                        effective_name = new_name
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
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
        file_meta = {
            'file_id': file_id,
            'name': effective_name,
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
            'name': effective_name,
            'stored_name': sanitized_name,
            'ref': ref,
            'path': str(file_path),
            'mime_type': mime_type,
            'size_bytes': len(data),
            'hash_sha256': file_hash
        }
    
    def read(self, mode: str = 'auto') -> dict:
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

def open_space(space_id: str = None, labels: list[str] = None,
               scope: str = 'session', ttl_days: int = None) -> tuple[StashSpace, bool]:
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


def list_spaces() -> list[dict]:
    """List all stash spaces."""
    stash_dir = get_stash_dir()
    if not stash_dir.exists():
        return []
    
    spaces = []
    items = sorted(stash_dir.iterdir(), key=lambda path: path.stat().st_mtime)
    for item in items:
        if item.is_dir() and item.name.startswith('space_'):
            try:
                space = StashSpace(item.name, stash_dir)
                if space.exists:
                    spaces.append(space.info())
            except Exception:
                pass
    
    return sorted(spaces, key=lambda x: x.get('last_used_at', ''), reverse=True)


def _space_expires_at(space: StashSpace) -> datetime:
    """Return when a stash space expires based on last use and TTL."""
    ttl_days = space.meta.get('ttl_days', get_default_ttl())
    last_used_str = space.meta.get('last_used_at', space.meta.get('created_at', ''))
    last_used = datetime.fromisoformat(last_used_str.rstrip('Z'))
    return last_used + timedelta(days=ttl_days)


def _migrate_retention_policy(space: StashSpace, *, dry_run: bool = False) -> bool:
    """Classify legacy spaces without overwriting known custom TTL values."""
    if space.meta.get('retention_policy'):
        return False
    current_ttl = space.meta.get('ttl_days')
    if current_ttl not in (None, 7):
        policy, ttl_days = 'legacy_explicit', current_ttl
    else:
        policy, ttl_days = get_retention_policy(
            space.meta.get('labels', []),
            space.meta.get('scope', 'session'),
        )
    space._meta['retention_policy'] = policy
    space._meta['ttl_days'] = ttl_days
    if not dry_run:
        space._save_meta()
    return True


def cleanup_expired(
    *,
    dry_run: bool = False,
    protected_space_ids: set[str] | frozenset[str] | None = None,
    stash_dir: Path = None,
    max_delete_spaces: int | None = None,
    max_delete_bytes: int | None = None,
) -> dict:
    """Clean up expired spaces after applying retention policy migration."""
    stash_dir = stash_dir or get_stash_dir()
    if protected_space_ids is None:
        try:
            from retention_cleanup import collect_conversation_asset_references
            conversations_dir = Path(__file__).parent.parent / 'data' / 'web_conversations'
            protected_space_ids = collect_conversation_asset_references(
                conversations_dir
            ).stash_space_ids
        except Exception:
            protected_space_ids = frozenset()
    if max_delete_spaces is None:
        max_delete_spaces = get_int('STASH_CLEANUP_MAX_SPACES', 100)
    if max_delete_bytes is None:
        max_delete_bytes = get_int('STASH_CLEANUP_MAX_BYTES_MB', 512) * 1024 * 1024
    if not stash_dir.exists():
        return {
            'deleted_spaces': 0, 'expired_spaces': 0, 'freed_bytes': 0,
            'protected_spaces': 0, 'migrated_spaces': 0, 'candidates': [],
            'deferred_spaces': 0, 'errors': [],
        }
    
    deleted = 0
    freed = 0
    expired = 0
    protected = 0
    migrated = 0
    candidates = []
    deferred = 0
    errors = []
    expired_queue: list[tuple[datetime, str, StashSpace, int]] = []

    for item in stash_dir.iterdir():
        if item.is_dir() and item.name.startswith('space_'):
            try:
                space = StashSpace(item.name, stash_dir)
                if not space.exists:
                    continue
                if _migrate_retention_policy(space, dry_run=dry_run):
                    migrated += 1
                if item.name in protected_space_ids:
                    protected += 1
                    continue
                if space.is_expired:
                    expired += 1
                    candidates.append(item.name)
                    candidate_size = sum(
                        path.stat().st_size
                        for path in item.rglob('*')
                        if path.is_file()
                    )
                    expired_queue.append(
                        (_space_expires_at(space), item.name, space, candidate_size)
                    )
            except Exception as exc:
                errors.append({'space_id': item.name, 'error': str(exc)})

    expired_queue.sort(key=lambda entry: (entry[0], entry[1]))
    for _expires_at, _space_id, space, candidate_size in expired_queue:
        if dry_run:
            freed += candidate_size
            continue
        limit_reached = deleted >= max_delete_spaces
        byte_limit_reached = deleted > 0 and freed + candidate_size > max_delete_bytes
        if limit_reached or byte_limit_reached:
            deferred += 1
            continue
        freed += space.delete()
        deleted += 1

    return {
        'deleted_spaces': deleted,
        'expired_spaces': expired,
        'freed_bytes': freed,
        'protected_spaces': protected,
        'migrated_spaces': migrated,
        'candidates': candidates,
        'deferred_spaces': deferred,
        'errors': errors,
    }


def normalize_space_id(space_id: str) -> str:
    """
    Normalize space_id to handle date format variations.
    
    LLMs sometimes reformat dates from 20260127 to 2026-01-27.
    This normalizes both formats to the canonical no-dash format.
    
    Examples:
        space_2026-01-27_095852_abc123 -> space_20260127_095852_abc123
        space_20260127_095852_abc123 -> space_20260127_095852_abc123 (unchanged)
    """
    import re
    # Match space_YYYY-MM-DD_ pattern and convert to space_YYYYMMDD_
    pattern = r'^(space_)(\d{4})-(\d{2})-(\d{2})(_.*)'
    match = re.match(pattern, space_id)
    if match:
        return f"{match.group(1)}{match.group(2)}{match.group(3)}{match.group(4)}{match.group(5)}"
    return space_id


def parse_stash_ref(ref: str) -> tuple[str, str]:
    """Parse a stash:// reference into (space_id, file_id)."""
    if not ref.startswith('stash://'):
        raise ValueError(f"Invalid stash reference: {ref}")
    
    parts = ref[8:].split('/', 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid stash reference format: {ref}")
    
    # Normalize space_id to handle LLM date reformatting
    space_id = normalize_space_id(parts[0])
    
    return space_id, parts[1]


def resolve_file_path(space_id: str = None, file_id: str = None,
                      stash_ref: str = None, file_path: str = None) -> str:
    """
    Resolve a file path from various input formats.
    
    This is a helper for tools that want to accept stash references.
    """
    # Direct path
    if file_path:
        return str(assert_not_restricted_read_path(file_path, label="File path"))
    
    # Stash URI
    if stash_ref:
        space_id, file_id = parse_stash_ref(stash_ref)
    
    # Explicit space_id + file_id
    if space_id and file_id:
        space = get_space(space_id)
        stash_file = StashFile(space, file_id=file_id)
        if stash_file.path:
            return str(assert_not_restricted_read_path(stash_file.path, label="Stash file"))
        # Try by name if file_id doesn't match
        stash_file = StashFile(space, name=file_id)
        if stash_file.path:
            return str(assert_not_restricted_read_path(stash_file.path, label="Stash file"))
        raise ValueError(f"File {file_id} not found in space {space_id}")
    
    raise ValueError("Provide file_path, stash_ref, or space_id+file_id")


def safe_resolve_file(stash_ref: str = None, file_path: str = None, 
                      fallback_paths: list[str] = None) -> dict[str, Any]:
    """
    Safely resolve a file from stash or path, handling expired/missing stash gracefully.
    
    This is the preferred way for tools to access stash files - it handles:
    - Expired stash spaces (TTL)
    - Deleted files
    - Fallback to alternative paths (e.g., generated_images/)
    
    Args:
        stash_ref: Stash URI like "stash://space_xxx/file_id"
        file_path: Direct file path
        fallback_paths: List of paths to try if stash is unavailable
    
    Returns:
        {
            "found": bool,
            "path": str or None,
            "source": "stash" | "path" | "fallback" | None,
            "error": str or None (why it failed),
            "stash_expired": bool
        }
    """
    result = {
        "found": False,
        "path": None,
        "source": None,
        "error": None,
        "stash_expired": False
    }
    
    # 1. Try direct file path first
    if file_path:
        matched = get_restricted_read_match(file_path)
        if matched:
            result["error"] = f"File path is in a restricted location ({matched})"
        elif os.path.exists(file_path):
            result["found"] = True
            result["path"] = file_path
            result["source"] = "path"
            return result
        else:
            result["error"] = f"File not found: {file_path}"
    
    # 2. Try stash reference
    if stash_ref:
        try:
            resolved = resolve_file_path(stash_ref=stash_ref)
            matched = get_restricted_read_match(resolved)
            if matched:
                result["error"] = f"Stash file is in a restricted location ({matched})"
            elif os.path.exists(resolved):
                result["found"] = True
                result["path"] = resolved
                result["source"] = "stash"
                return result
            else:
                result["error"] = f"Stash file missing (may have been deleted)"
                result["stash_expired"] = True
        except ValueError as e:
            error_str = str(e)
            if "does not exist" in error_str:
                result["stash_expired"] = True
                result["error"] = f"Stash space expired (TTL): {stash_ref}"
            else:
                result["error"] = f"Stash error: {error_str}"
    
    # 3. Try fallback paths
    if fallback_paths:
        for fallback in fallback_paths:
            if get_restricted_read_match(fallback):
                continue
            if os.path.exists(fallback):
                result["found"] = True
                result["path"] = fallback
                result["source"] = "fallback"
                result["error"] = None  # Clear error since we found it
                return result
    
    # Nothing found
    if not result["error"]:
        result["error"] = "No valid file reference provided"
    
    return result


def extract_filename_from_stash_ref(stash_ref: str) -> str | None:
    """Extract filename from a stash reference for fallback lookups."""
    if not stash_ref:
        return None
    try:
        # stash://space_xxx/file_id or stash://space_xxx/filename.ext
        parts = stash_ref.replace("stash://", "").split("/")
        if len(parts) >= 2:
            return parts[-1]
    except:
        pass
    return None
