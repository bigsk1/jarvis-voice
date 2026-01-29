#!/usr/bin/env python3
"""
Remember Tool - Store information in persistent memory

Security:
- Detects potential prompt injection patterns
- Flags suspicious content for review
- Limits content length
"""
import sys
import json
import os
import re
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib'))
from memory_db import get_memory_db
from config_loader import load_config


# Prompt injection detection patterns
INJECTION_PATTERNS = [
    r'ignore\s+(all\s+)?(previous\s+)?instructions',
    r'disregard\s+(all\s+)?(previous\s+)?instructions',
    r'forget\s+(all\s+)?(previous\s+)?instructions',
    r'you\s+are\s+now\s+',
    r'new\s+instructions\s*:',
    r'system\s*:\s*',
    r'<\|im_start\|>',
    r'<\|im_end\|>',
    r'<\|system\|>',
    r'<\|user\|>',
    r'<\|assistant\|>',
    r'\[INST\]',
    r'\[/INST\]',
    r'###\s*(instruction|system|human|assistant)',
    r'IMPORTANT:\s*ignore',
    r'override\s+all',
    r'bypass\s+all',
    r'admin\s*mode',
    r'developer\s*mode',
    r'jailbreak',
    r'DAN\s*mode',
]

# Maximum content length
MAX_VALUE_LENGTH = 10000
MAX_KEY_LENGTH = 500


def detect_injection(text: str) -> tuple[bool, str]:
    """
    Detect potential prompt injection in text.
    
    Returns:
        (is_suspicious, matched_pattern)
    """
    if not text:
        return False, ""
    
    text_lower = text.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            return True, pattern
    
    return False, ""


def sanitize_for_storage(text: str, max_length: int) -> str:
    """Sanitize text for safe storage."""
    if not text:
        return ""
    
    # Truncate to max length
    if len(text) > max_length:
        text = text[:max_length] + "...[truncated]"
    
    return text


def main():
    """Store information in memory."""
    try:
        # CRITICAL: Load config to set correct embedding provider (local vs cloud)
        load_config()  # Auto-detects mode from LLM_PROVIDER
        
        # Read arguments
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        
        category = args.get('category', 'fact')
        key = args.get('key')
        value = args.get('value')
        importance = args.get('importance', 5)
        
        # SECURITY: Sanitize inputs
        if key:
            key = sanitize_for_storage(key, MAX_KEY_LENGTH)
        if value:
            value = sanitize_for_storage(value, MAX_VALUE_LENGTH)
        
        # SECURITY: Check for prompt injection patterns
        key_suspicious, key_pattern = detect_injection(key) if key else (False, "")
        value_suspicious, value_pattern = detect_injection(value) if value else (False, "")
        
        if key_suspicious or value_suspicious:
            pattern = key_pattern or value_pattern
            logger.warning(f"Potential prompt injection detected in memory: pattern='{pattern}', key='{key[:100] if key else ''}'")
            # Don't block, but flag in metadata for review
        
        if not key or not value:
            result = {
                "ok": False,
                "speech": "I need both a key and value to remember something",
                "error": "Missing required parameters"
            }
            print(json.dumps(result))
            return result
        
        # Store in memory with metadata
        from datetime import datetime
        db = get_memory_db()
        
        # Build metadata
        metadata = {
            "created_by": "user_conversation",
            "timestamp": datetime.now().isoformat(),
            "tool": "remember"
        }
        
        # SECURITY: Flag suspicious content in metadata
        if key_suspicious or value_suspicious:
            metadata["security_flag"] = "potential_injection"
            metadata["matched_pattern"] = key_pattern or value_pattern
            # Lower importance for flagged content
            importance = min(importance, 3)
        
        memory_id = db.remember(
            category=category,
            key=key,
            value=value,
            importance=importance,
            source="user_conversation",
            metadata=metadata
        )
        db.close()
        
        result = {
            "ok": True,
            "speech": f"I'll remember that: {key} is {value}",
            "data": {
                "memory_id": memory_id,
                "category": category,
                "key": key,
                "value": value,
                "importance": importance
            }
        }
        
        print(json.dumps(result))
        return result
        
    except Exception as e:
        error_result = {
            "ok": False,
            "speech": f"Failed to store memory: {str(e)}",
            "error": str(e)
        }
        print(json.dumps(error_result))
        return error_result


if __name__ == "__main__":
    main()

