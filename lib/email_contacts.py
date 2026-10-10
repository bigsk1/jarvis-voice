"""Shared local contact lookup for Jarvis email tools."""

from __future__ import annotations

import json
from pathlib import Path

CONTACTS_FILE = Path(__file__).resolve().parents[1] / "config" / "contacts.json"


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
