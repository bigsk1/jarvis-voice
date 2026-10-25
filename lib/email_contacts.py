"""Shared local contact lookup for Jarvis email tools."""

from __future__ import annotations

import json
from pathlib import Path

CONTACTS_FILE = Path(__file__).resolve().parents[1] / "config" / "contacts.json"

DEFAULT_EMAIL_TOOLS = [
    "get_time",
    "stash",
    "stock_price",
    "crypto_price",
    "weather",
    "calculator",
    "mcp_brave_search_brave_web_search",
    "brave_llm_context",
    "tavily_search",
    "tavily_extract",
]
_FORBIDDEN_EMAIL_TOOLS = {
    "email_inbox",
    "workflow",
    "send_email",
    "mcp_google_workspace_send_gmail_message",
    "mcp_google_workspace_draft_gmail_message",
}


def _email_tools(value, field: str, *, single: bool = False) -> list[str]:
    if single and isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or any(not isinstance(t, str) or not t.strip() for t in value):
        raise ValueError(f"{field} must contain exact tool names")
    if single and any(t != t.strip() for t in value):
        raise ValueError(f"{field} must contain exact tool names without surrounding whitespace")
    if _FORBIDDEN_EMAIL_TOOLS.intersection(value):
        raise ValueError("Email delivery and workflows belong to the dispatcher, not email requests")
    return sorted(set(value) | {"tool_search"})


def _sender_tool_limits(contacts: dict, approved: set[str]) -> dict[str, list[str]]:
    """Bind contact limits to canonical sender addresses, independent of aliases."""
    limits = {}
    for contact in contacts.values():
        if not isinstance(contact, dict):
            continue
        if "allowed_tools_limted" in contact:
            raise ValueError("Use the contact field allowed_tools_limited, not allowed_tools_limted")
        if "allowed_tools_limited" not in contact:
            continue
        sender = canonical_email(contact.get("email", ""))
        extras = _email_tools(contact["allowed_tools_limited"], "allowed_tools_limited", single=True)
        effective = sorted(set(DEFAULT_EMAIL_TOOLS) | set(extras))
        if sender in limits and limits[sender] != effective:
            raise ValueError("Contacts sharing an email address have conflicting allowed_tools_limited")
        limits[sender] = effective
    return {sender: tools for sender, tools in limits.items() if sender in approved}


def canonical_email(value: str) -> str:
    """Require a single bare address, never a display name or recipient list."""
    from email.headerregistry import Address

    if not isinstance(value, str) or any(c.isspace() for c in value.strip()):
        raise ValueError("Expected a single email address")
    value = value.strip()
    try:
        address = Address(addr_spec=value)
    except ValueError as exc:
        raise ValueError("Invalid email address") from exc
    if not address.username or not address.domain or address.addr_spec != value:
        raise ValueError("Expected a single bare email address")
    return value.casefold()


def load_email_channel(mode: str) -> dict:
    """Reload operator-owned inbound policy without changing outgoing contacts."""
    try:
        data = json.loads(CONTACTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # Fail closed without interpreting a partial write/outage as revocation.
        raise ValueError("Email policy could not be read; pending requests are preserved") from exc
    if not isinstance(data, dict):
        raise ValueError("Email policy must be a JSON object")
    settings = data.get("jarvis_email", {}) if isinstance(data, dict) else {}
    if not isinstance(settings, dict) or settings.get("enabled") is not True:
        return {"enabled": False}
    if settings.get("mode", "cloud") not in {"cloud", "local"}:
        raise ValueError("jarvis_email.mode must be cloud or local")
    if settings.get("mode", "cloud") != mode:
        return {"enabled": False}
    contacts = data.get("contacts", {})
    contacts = contacts if isinstance(contacts, dict) else {}
    approved = settings.get("approved_senders", [])
    if not isinstance(approved, list) or not approved:
        raise ValueError("jarvis_email.approved_senders must contain addresses or contact names")
    senders = set()
    for value in approved:
        if not isinstance(value, str):
            raise ValueError("Approved senders must be addresses or contact names")
        resolved, _ = resolve_email(value, contacts)
        if not resolved:
            raise ValueError("An approved sender does not resolve to a contact address")
        senders.add(canonical_email(resolved))
    tools = _email_tools(settings.get("allowed_tools", DEFAULT_EMAIL_TOOLS), "jarvis_email.allowed_tools")
    policy = {
        "enabled": True,
        "senders": sorted(senders),
        "allowed_tools": tools,
        "sender_allowed_tools": _sender_tool_limits(contacts, senders),
    }
    attachments = settings.get("attachments_enabled", True)
    if type(attachments) is not bool:
        raise ValueError("jarvis_email.attachments_enabled must be true or false")
    policy["attachments_enabled"] = attachments
    for name, default, maximum in (
        ("max_attachment_bytes", 50 * 1024 * 1024, 50 * 1024 * 1024),
        ("max_attachments", 500, 500),
    ):
        value = settings.get(name, default)
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f"jarvis_email.{name} must be between 1 and {maximum}")
        policy[name] = value
    for name, default, maximum in (("max_messages_per_poll", 1, 5), ("lookback_days", 1, 30)):
        value = settings.get(name, default)
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f"jarvis_email.{name} must be between 1 and {maximum}")
        policy[name] = value
    return policy


def load_contacts() -> dict:
    """Read the optional contacts map; malformed or unreadable files add no contacts."""
    try:
        data = json.loads(CONTACTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    contacts = data.get("contacts") if isinstance(data, dict) else None
    return contacts if isinstance(contacts, dict) else {}


def resolve_email(to: str, contacts: dict) -> tuple[str | None, str]:
    """Resolve a contact key or display name case-insensitively, or accept an email."""
    if "@" in to:
        return to, to.split("@")[0]
    name = to.lower().strip()
    for key, contact in contacts.items():
        if not isinstance(contact, dict):
            continue
        display_name = contact.get("name", key)
        if not isinstance(display_name, str):
            display_name = key
        if key.lower() == name or display_name.lower() == name:
            email = contact.get("email")
            if isinstance(email, str) and "@" in email and email.strip():
                return email.strip(), display_name
    return None, to


def resolve_email_recipients(value: str, contacts: dict) -> str:
    """Resolve comma-separated recipients while preserving quoted address names."""
    if not isinstance(value, str):
        raise ValueError("Email recipients must be a contact name or email address string")
    # An exact contact name can itself contain commas or spaces.
    if "@" not in value:
        email, _ = resolve_email(value, contacts)
        if email:
            return email
    parts = []
    start = 0
    quoted = escaped = False
    comment_depth = 0
    in_angle = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
        elif character == "\\" and (quoted or comment_depth):
            escaped = True
        elif character == '"' and not comment_depth:
            quoted = not quoted
        elif character == "(" and not quoted:
            comment_depth += 1
        elif character == ")" and not quoted:
            comment_depth = max(0, comment_depth - 1)
        elif character == "<" and not quoted and not comment_depth:
            in_angle = True
        elif character == ">" and not quoted and not comment_depth:
            in_angle = False
        elif character == "," and not quoted and not comment_depth and not in_angle:
            parts.append(value[start:index].strip())
            start = index + 1
    parts.append(value[start:].strip())
    if quoted or comment_depth or in_angle or any(not part for part in parts):
        raise ValueError("Invalid or empty email recipient")

    resolved = []
    for part in parts:
        email, _ = resolve_email(part, contacts)
        if not email:
            available = ", ".join(contacts) or "none configured"
            raise ValueError(f"Contact '{part}' not found. Available contacts: {available}")
        resolved.append(email)
    return ", ".join(resolved)
