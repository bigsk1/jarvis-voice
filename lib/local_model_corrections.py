#!/usr/bin/env python3
"""
Smart corrections for local LLM outputs.
Fixes common formatting issues without breaking legitimate use cases.
"""
import re
from typing import Dict, Any


def normalize_tool_name(tool_name: str) -> str:
    """
    Normalize tool names to snake_case format.
    
    Examples:
        "send webhook" → "send_webhook"
        "mcp-duckduckgo-search" → "mcp_duckduckgo_search"
        "ApiCall" → "api_call"
    
    Args:
        tool_name: Raw tool name from LLM
    
    Returns:
        Normalized tool name
    """
    # Replace spaces and hyphens with underscores
    normalized = tool_name.replace(" ", "_").replace("-", "_")
    
    # Convert camelCase to snake_case
    # ApiCall → api_call
    normalized = re.sub(r'(?<!^)(?=[A-Z])', '_', normalized).lower()
    
    # Remove duplicate underscores
    normalized = re.sub(r'_+', '_', normalized)
    
    return normalized


def normalize_memory_key(key: str) -> str:
    """
    Normalize memory keys to snake_case.
    
    Examples:
        "favorite color" → "favorite_color"
        "My-API-Key" → "my_api_key"
        "webhook URL" → "webhook_url"
    
    Args:
        key: Raw key from LLM
    
    Returns:
        Normalized key
    """
    # Replace spaces and hyphens with underscores
    normalized = key.replace(" ", "_").replace("-", "_")
    
    # Convert to lowercase
    normalized = normalized.lower()
    
    # Remove duplicate underscores
    normalized = re.sub(r'_+', '_', normalized)
    
    # Remove leading/trailing underscores
    normalized = normalized.strip("_")
    
    return normalized


def smart_url_fix(url: str) -> str:
    """
    Intelligently fix URLs without breaking local network services.
    
    Rules:
    - If URL starts with http:// or https://, leave it alone
    - If URL is localhost or 127.0.0.1, prefix with http://
    - If URL is private IP (192.168.x.x, 10.x.x.x), prefix with http://
    - Otherwise (public domains), prefix with https://
    
    Examples:
        "example.com" → "https://example.com"
        "localhost:8080" → "http://localhost:8080"
        "192.168.1.1" → "http://192.168.1.1"
        "10.0.0.5:5000" → "http://10.0.0.5:5000"
        "https://google.com" → "https://google.com" (unchanged)
    
    Args:
        url: Raw URL from LLM
    
    Returns:
        Fixed URL with appropriate scheme
    """
    # Already has scheme
    if url.startswith(("http://", "https://")):
        return url
    
    # Extract hostname (before : if port exists)
    hostname = url.split(":")[0].split("/")[0]
    
    # Local addresses → http://
    if hostname in ["localhost", "127.0.0.1"]:
        return f"http://{url}"
    
    # Private IP ranges → http://
    # 192.168.x.x, 10.x.x.x, 172.16-31.x.x
    private_ip_patterns = [
        r'^192\.168\.\d+\.\d+$',
        r'^10\.\d+\.\d+\.\d+$',
        r'^172\.(1[6-9]|2[0-9]|3[0-1])\.\d+\.\d+$'
    ]
    
    for pattern in private_ip_patterns:
        if re.match(pattern, hostname):
            return f"http://{url}"
    
    # Public domain → https://
    return f"https://{url}"


def correct_tool_call(tool_call: Dict[str, Any], strict_mode: bool = False) -> Dict[str, Any]:
    """
    Apply smart corrections to tool calls from local LLMs.
    
    Args:
        tool_call: Raw tool call dict {"name": str, "arguments": dict}
        strict_mode: If True, be more aggressive with corrections
    
    Returns:
        Corrected tool call dict
    """
    corrected = tool_call.copy()
    
    # Fix tool name
    if "name" in corrected:
        corrected["name"] = normalize_tool_name(corrected["name"])
    
    # Fix arguments
    if "arguments" in corrected and isinstance(corrected["arguments"], dict):
        args = corrected["arguments"].copy()
        
        # Fix URL if present
        if "url" in args and isinstance(args["url"], str):
            args["url"] = smart_url_fix(args["url"])
        
        # Fix memory key if present
        if "key" in args and isinstance(args["key"], str):
            args["key"] = normalize_memory_key(args["key"])
        
        corrected["arguments"] = args
    
    return corrected


def validate_corrections(original: Dict[str, Any], corrected: Dict[str, Any]) -> Dict[str, str]:
    """
    Show what corrections were made (useful for debugging/logging).
    
    Args:
        original: Original tool call
        corrected: Corrected tool call
    
    Returns:
        Dict of changes made
    """
    changes = {}
    
    if original.get("name") != corrected.get("name"):
        changes["tool_name"] = f"{original.get('name')} → {corrected.get('name')}"
    
    orig_args = original.get("arguments", {})
    corr_args = corrected.get("arguments", {})
    
    for key in set(list(orig_args.keys()) + list(corr_args.keys())):
        if orig_args.get(key) != corr_args.get(key):
            changes[f"arg:{key}"] = f"{orig_args.get(key)} → {corr_args.get(key)}"
    
    return changes

