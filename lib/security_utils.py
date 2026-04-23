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
from typing import Any, Optional

from tts_normalizer import normalize_tts_text
from paths import get_allowed_write_paths, get_protected_paths

logger = logging.getLogger(__name__)


# Maximum input lengths
MAX_TRANSCRIPT_LENGTH = 10000
MAX_MEMORY_VALUE_LENGTH = 10000
MAX_URL_LENGTH = 2048

SENSITIVE_VALUE_REPLACEMENT = "[redacted]"

_SENSITIVE_KEY_EXACT = {
    "api_key",
    "apikey",
    "x_api_key",
    "xapikey",
    "authorization",
    "auth_header",
    "bearer",
    "cookie",
    "password",
    "passwd",
    "pwd",
    "secret",
    "client_secret",
    "clientsecret",
    "private_key",
    "privatekey",
    "access_token",
    "refresh_token",
    "auth_token",
    "session_id",
    "sessionid",
}

_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "cookie",
    "password",
    "passwd",
    "client_secret",
    "private_key",
)

_SECRET_TEXT_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Private key blocks.
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.IGNORECASE | re.DOTALL,
        ),
        "-----BEGIN PRIVATE KEY-----[redacted]-----END PRIVATE KEY-----",
    ),
    # Authorization headers / bearer tokens.
    (
        re.compile(r"(?i)\b(Authorization\s*:\s*Bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
        r"\1[redacted]",
    ),
    (
        re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]{16,}"),
        r"\1[redacted]",
    ),
    # Key/value assignments in prose, shell, JSON-ish, YAML-ish, or logs.
    (
        re.compile(
            r"(?i)(\b(?:api[_-]?key|x-api-key|password|passwd|pwd|secret|client[_-]?secret|private[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|session[_-]?id)\b\s*[:=]\s*[\"']?)([^\"'\s,;}{]{4,})"
        ),
        r"\1[redacted]",
    ),
    (
        re.compile(
            r"(?i)([\"'](?:api[_-]?key|x-api-key|password|passwd|pwd|secret|client[_-]?secret|private[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|session[_-]?id)[\"']\s*:\s*[\"'])([^\"']+)([\"'])"
        ),
        r"\1[redacted]\3",
    ),
    # Natural language forms like "secret key 'dev-secret-123'".
    (
        re.compile(r"(?i)\b(secret\s+key\s+(?:is\s+)?[\"']?)([^\"'\s,;]{4,})"),
        r"\1[redacted]",
    ),
    # Credentialed URLs.
    (
        re.compile(r"(?i)\b(https?://)([^/\s:@]+):([^@\s/]+)@"),
        r"\1\2:[redacted]@",
    ),
    # Common provider/token formats.
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}\b"), "sk-ant-[redacted]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "sk-[redacted]"),
    (re.compile(r"\bxai-[A-Za-z0-9_-]{20,}\b", re.IGNORECASE), "xai-[redacted]"),
    (re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"), "ghp_[redacted]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AKIA[redacted]"),
    # JWTs.
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        "jwt-[redacted]",
    ),
]


def _normalize_sensitive_key(key: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", key.lower().replace("-", "_"))


def is_sensitive_key(key: str) -> bool:
    """Return True when a mapping key is likely to contain a secret."""
    normalized = _normalize_sensitive_key(str(key))
    if not normalized:
        return False

    # Usage/cost metadata has token counts and should remain useful.
    if normalized.endswith("tokens") or normalized in {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cache_read_tokens",
        "cache_creation_tokens",
    }:
        return False

    if normalized in _SENSITIVE_KEY_EXACT:
        return True
    if normalized.endswith("_token") or normalized == "token":
        return True
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def redact_sensitive_text(text: str) -> str:
    """
    Redact secret-looking values from free text while preserving normal PII.

    Email addresses, names, and ordinary URLs are intentionally left intact. This
    function targets credentials that should not become permanent DB/log data.
    """
    if not isinstance(text, str) or not text:
        return text

    redacted = text
    for pattern, replacement in _SECRET_TEXT_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_sensitive_data(
    value: Any,
    *,
    depth: int = 0,
    max_depth: int = 8,
    max_items: int = 200,
) -> Any:
    """
    Recursively redact secret-like values from JSON-serializable structures.

    This is intended for logs, reflection payloads, and Intelligence DB records.
    It does not try to remove all personal data; it removes credential material.
    """
    if depth > max_depth:
        return "[max depth]"

    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                redacted["__truncated__"] = f"{len(value) - max_items} more item(s)"
                break
            key_str = str(key)
            if is_sensitive_key(key_str):
                redacted[key_str] = SENSITIVE_VALUE_REPLACEMENT
            else:
                redacted[key_str] = redact_sensitive_data(
                    item,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_items=max_items,
                )
        return redacted

    if isinstance(value, list):
        items = [
            redact_sensitive_data(item, depth=depth + 1, max_depth=max_depth, max_items=max_items)
            for item in value[:max_items]
        ]
        if len(value) > max_items:
            items.append(f"[truncated {len(value) - max_items} more item(s)]")
        return items

    if isinstance(value, tuple):
        return tuple(
            redact_sensitive_data(item, depth=depth + 1, max_depth=max_depth, max_items=max_items)
            for item in value[:max_items]
        )

    if isinstance(value, str):
        return redact_sensitive_text(value)

    return value

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


def sanitize_for_speech(text: str, *, preserve_xai_tags: bool = False) -> str:
    """
    Backward-compatible wrapper around the shared TTS normalizer.
    """
    return normalize_tts_text(text, preserve_xai_tags=preserve_xai_tags)


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
    for protected in get_protected_paths():
        protected_norm = os.path.normpath(protected)
        
        # Check if path starts with protected path
        if path == protected_norm or path.startswith(protected_norm + os.sep):
            # Check if it's in an allowed subdirectory
            for allowed in get_allowed_write_paths():
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
        "protected_paths": get_protected_paths(),
        "allowed_write_paths": get_allowed_write_paths(),
        "max_transcript_length": MAX_TRANSCRIPT_LENGTH,
        "injection_patterns_count": len(INJECTION_PATTERNS),
    }
