#!/usr/bin/env python3
"""Inspect the local recipient aliases shared by Jarvis email and Gmail tools."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import email_contacts as contact_store  # noqa: E402

SOURCE = 'jarvis_local_contacts'
CONTACTS_FILE_LABEL = 'config/contacts.json'


def _data(status: str, *, complete: bool = False) -> dict[str, Any]:
    return {
        'status': status, 'source': SOURCE, 'contacts_file': CONTACTS_FILE_LABEL,
        'lookup_complete': complete, 'contacts': [], 'count': 0,
        'total_matches': 0, 'truncated': False,
    }


def _unavailable(message: str) -> dict[str, Any]:
    return {'ok': False, 'error': message, 'speech': message, 'data': _data('unavailable')}


def _email_rows(contacts: dict) -> list[dict[str, str]]:
    rows = []
    for key, contact in contacts.items():
        if not isinstance(key, str) or not isinstance(contact, dict):
            continue
        email = contact.get('email')
        if not isinstance(email, str) or '@' not in email or not email.strip():
            continue
        name = contact.get('name', key)
        if not isinstance(name, str):
            name = key
        # Use the outbound resolver for normal aliases. An address-shaped key
        # is treated as a direct recipient by that resolver, so inspect its
        # explicitly configured email field rather than synthesizing an alias.
        if '@' not in key:
            email, name = contact_store.resolve_email(key, {key: contact})
        if email is not None:
            rows.append({'key': key, 'name': name, 'email': email.strip()})
    return sorted(rows, key=lambda row: (row['key'].casefold(), row['key']))


def lookup_contacts(arguments: dict[str, Any]) -> dict[str, Any]:
    """Read only the canonical local contacts map, exposing no policy or notes."""
    if not isinstance(arguments, dict) or set(arguments) - {'query', 'limit'}:
        return _unavailable('Provide only the optional query and limit fields.')
    query = arguments.get('query', '')
    limit = arguments.get('limit', 20)
    if not isinstance(query, str):
        return _unavailable('query must be a string.')
    if type(limit) is not int or not 1 <= limit <= 50:
        return _unavailable('limit must be an integer between 1 and 50.')
    try:
        document = json.loads(contact_store.CONTACTS_FILE.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {
            'ok': True, 'data': _data('not_configured'),
            'speech': 'Local email contacts are not configured. Google Contacts and memory were not checked.',
        }
    except (OSError, ValueError):
        return _unavailable('Local email contacts could not be read; their availability is unknown.')
    if not isinstance(document, dict) or not isinstance(document.get('contacts'), dict):
        return _unavailable('Local email contact configuration must contain a contacts object; lookup is incomplete.')
    rows = _email_rows(document['contacts'])
    query = query.strip().casefold()
    matches = [row for row in rows if not query or any(query in value.casefold() for value in row.values())]
    selected = matches[:limit]
    data = {
        **_data('found' if matches else 'not_found', complete=True),
        'contacts': selected, 'count': len(selected), 'total_matches': len(matches),
        'truncated': len(selected) < len(matches),
    }
    speech = (
        f"Found {len(matches)} matching local email contact(s); showing {len(selected)}."
        if matches else 'No matching local email contacts were found.'
    )
    speech += ' Only email-capable local entries were checked; Google Contacts and memory were not checked.'
    return {'ok': True, 'speech': speech, 'data': data}


def main() -> int:
    """Accept the normal JSON local-tool argument without any sending actions."""
    try:
        arguments = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except (ValueError, TypeError):
        result = _unavailable('Tool arguments must be a JSON object.')
    else:
        result = lookup_contacts(arguments)
    print(json.dumps(result))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
