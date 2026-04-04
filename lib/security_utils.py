#!/usr/bin/env python3
"""
Security Utilities for Jarvis Voice Assistant

Provides reusable security functions for:
- Prompt injection detection
- Input sanitization
- Content validation
"""

import re
import logging
from typing import Optional

from tts_normalizer import normalize_tts_text

logger = logging.getLogger(__name__)


# Maximum input lengths
MAX_TRANSCRIPT_LENGTH = 10000
MAX_MEMORY_VALUE_LENGTH = 10000
MAX_URL_LENGTH = 2048

# Protected paths - Jarvis cannot modify these
# Used by execute_bash, and can be imported by other tools
PROTECTED_PATHS = [
    '/home/boss/jarvis-voice',  # Jarvis codebase - NO self-modification
    '/home/boss/.ssh',          # SSH keys
    '/home/boss/.gnupg',        # GPG keys  
    '/home/boss/.config',       # User config
    '/etc',                     # System config
    '/usr',                     # System binaries
    '/bin',                     # System binaries
    '/sbin',                    # System binaries
    '/boot',                    # Boot files
    '/root',                    # Root home
    '/var/log',                 # System logs (read OK, write blocked)
]

# Paths where write operations are allowed
ALLOWED_WRITE_PATHS = [
    '/home/boss/jarvis-voice/data',      # Data directory
    '/home/boss/jarvis-voice/logs',      # Logs directory  
    '/home/boss/jarvis-voice/stash',     # Stash artifacts
    '/tmp',                               # Temp files
    '/home/boss/Downloads',               # Downloads
    '/home/boss/Documents',               # Documents
]


# Prompt injection detection patterns
INJECTION_PATTERNS = [
    # Direct instruction override
    r'ignore\s+(all\s+)?(previous\s+)?instructions',
    r'disregard\s+(all\s+)?(previous\s+)?instructions',
    r'forget\s+(all\s+)?(previous\s+)?instructions',
    r'override\s+(all\s+)?(previous\s+)?',
    r'bypass\s+(all\s+)?(previous\s+)?',
    
    # Role/persona injection
    r'you\s+are\s+now\s+',
    r'pretend\s+(you\s+are|to\s+be)\s+',
    r'act\s+as\s+(if\s+)?(you\s+are\s+)?',
    r'from\s+now\s+on\s*,?\s*(you|your)',
    
    # Instruction markers
    r'new\s+instructions\s*:',
    r'updated\s+instructions\s*:',
    r'system\s*:\s*',
    r'IMPORTANT\s*:\s*ignore',
    
    # Model-specific tokens (shouldn't appear in user input)
    r'<\|im_start\|>',
    r'<\|im_end\|>',
    r'<\|system\|>',
    r'<\|user\|>',
    r'<\|assistant\|>',
    r'\[INST\]',
    r'\[/INST\]',
    r'<<SYS>>',
    r'<</SYS>>',
    r'###\s*(instruction|system|human|assistant)',
    
    # Jailbreak keywords
    r'jailbreak',
    r'DAN\s*mode',
    r'developer\s*mode',
    r'admin\s*mode',
    r'maintenance\s*mode',
    r'debug\s*mode\s*enabled',
    
    # Data exfiltration attempts
    r'(repeat|print|show|display)\s+(all|the)\s+(previous|above|system)',
    r'what\s+(are|is)\s+your\s+(system\s+)?instructions',
    r'show\s+me\s+your\s+(system\s+)?prompt',
]


def detect_prompt_injection(text: str) -> tuple[bool, Optional[str]]:
    """
    Detect potential prompt injection in text.
    
    Args:
        text: Input text to check
        
    Returns:
        (is_suspicious, matched_pattern) - tuple of bool and matched pattern or None
    """
    if not text:
        return False, None
    
    text_lower = text.lower()
    
    for pattern in INJECTION_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            return True, pattern
    
    # Check for suspicious base64 that might contain instructions
    # Base64 strings longer than 100 chars that decode to text with injection patterns
    base64_pattern = r'[A-Za-z0-9+/]{100,}={0,2}'
    for match in re.finditer(base64_pattern, text):
        try:
            import base64
            decoded = base64.b64decode(match.group()).decode('utf-8', errors='ignore')
            is_suspicious, _ = detect_prompt_injection(decoded)
            if is_suspicious:
                return True, "base64_encoded_injection"
        except Exception:
            pass
    
    return False, None


def sanitize_user_input(transcript: str, max_length: int = MAX_TRANSCRIPT_LENGTH) -> tuple[str, dict]:
    """
    Sanitize user input before processing.
    
    Args:
        transcript: Raw user input
        max_length: Maximum allowed length
        
    Returns:
        (sanitized_transcript, security_info) - cleaned text and metadata about any issues found
    """
    security_info = {
        "original_length": len(transcript) if transcript else 0,
        "truncated": False,
        "injection_detected": False,
        "injection_pattern": None,
    }
    
    if not transcript:
        return "", security_info
    
    # Truncate if too long
    if len(transcript) > max_length:
        transcript = transcript[:max_length]
        security_info["truncated"] = True
        logger.warning(f"Input truncated from {security_info['original_length']} to {max_length} chars")
    
    # Check for prompt injection (don't block, just flag)
    is_suspicious, pattern = detect_prompt_injection(transcript)
    if is_suspicious:
        security_info["injection_detected"] = True
        security_info["injection_pattern"] = pattern
        logger.warning(f"Potential prompt injection detected: pattern='{pattern}', input preview='{transcript[:100]}'")
    
    return transcript, security_info


def sanitize_for_speech(text: str) -> str:
    """
    Backward-compatible wrapper around the shared TTS normalizer.
    """
    return normalize_tts_text(text)


def is_safe_url(url: str) -> bool:
    """
    Quick check if URL is potentially safe.
    For comprehensive SSRF protection, use stash_helper.validate_url().
    """
    if not url:
        return False
    
    url_lower = url.lower()
    
    # Block obvious internal URLs
    blocked_hosts = [
        'localhost',
        '127.0.0.1',
        '0.0.0.0',
        '169.254.',  # Link-local/cloud metadata
        '10.',
        '192.168.',
        '172.16.', '172.17.', '172.18.', '172.19.',
        '172.20.', '172.21.', '172.22.', '172.23.',
        '172.24.', '172.25.', '172.26.', '172.27.',
        '172.28.', '172.29.', '172.30.', '172.31.',
    ]
    
    for blocked in blocked_hosts:
        if blocked in url_lower:
            return False
    
    # Block non-http schemes
    if not (url_lower.startswith('http://') or url_lower.startswith('https://')):
        return False
    
    return True


def is_path_protected(path: str, for_write: bool = True) -> tuple[bool, Optional[str]]:
    """
    Check if a path is protected from modification.
    
    Args:
        path: File or directory path to check
        for_write: If True, check for write protection. If False, always allow.
        
    Returns:
        (is_protected, matched_protected_path)
    """
    import os
    
    if not path:
        return False, None
    
    # Normalize path
    path = os.path.expanduser(path)
    path = os.path.normpath(path)
    
    # If not checking for write, return not protected
    if not for_write:
        return False, None
    
    # Check if path is under a protected directory
    for protected in PROTECTED_PATHS:
        protected_norm = os.path.normpath(protected)
        
        # Check if path starts with protected path
        if path == protected_norm or path.startswith(protected_norm + os.sep):
            # Check if it's in an allowed subdirectory
            for allowed in ALLOWED_WRITE_PATHS:
                allowed_norm = os.path.normpath(allowed)
                if path == allowed_norm or path.startswith(allowed_norm + os.sep):
                    return False, None  # Allowed
            
            return True, protected
    
    return False, None


def get_security_summary() -> dict:
    """
    Get a summary of security settings for debugging/logging.
    """
    return {
        "protected_paths": PROTECTED_PATHS,
        "allowed_write_paths": ALLOWED_WRITE_PATHS,
        "max_transcript_length": MAX_TRANSCRIPT_LENGTH,
        "injection_patterns_count": len(INJECTION_PATTERNS),
    }
