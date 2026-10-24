"""Bounded, read-only PyPI advisory checks for Jarvis's declared environments."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import sys
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from urllib3.exceptions import HTTPError as Urllib3HTTPError

from lib.http_client import http_request

AUDIT_SECONDS = 40
MAX_PACKAGES = 1000
MAX_QUERY_PAGES = 4
MAX_ADVISORIES = 100
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
OSV_API = 'https://api.osv.dev/v1'
Package = tuple[str, str]
SEVERITY_ORDER = {'unknown': 0, 'low': 1, 'medium': 2, 'high': 3, 'critical': 4}
LIMITATIONS = [
    'Installed metadata describes the selected Python environments; packages are not imported.',
    'The universal uv lock includes conditional packages that may not be installed on this host.',
    'The optional Craft lock describes planned dependencies, not a deployed gateway.',
    'uv executables, containers, operating-system packages, and remote hosts are not audited.',
    'Advisory matches do not prove exploitability; listed fixed versions are not compatibility guarantees.',
]


class AuditError(Exception):
    """Carry a static diagnostic code without network payloads or credentials."""


def _name(value: str) -> str:
    return re.sub(r'[-_.]+', '-', value).lower()


def _package(name: Any, version: Any) -> Package:
    if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,199}', name)
            or not isinstance(version, str)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.!+_-]{0,199}', version.strip())):
        raise AuditError('invalid_package_metadata')
    return _name(name), version.strip()


def _installed(prefix: Path) -> set[Package]:
    paths = sorted((prefix / 'lib').glob('python*/site-packages'))
    windows = prefix / 'Lib/site-packages'
    if windows.is_dir():
        paths.append(windows)
    if not paths:
        raise AuditError('site_packages_missing')
    packages = set()
    for distribution in importlib.metadata.distributions(path=[str(path) for path in paths]):
        packages.add(_package(distribution.metadata.get('Name'), distribution.version))
        if len(packages) > MAX_PACKAGES:
            raise AuditError('inventory_limit')
    if not packages:
        raise AuditError('empty_inventory')
    return packages


def _uv_lock(path: Path) -> set[Package]:
    document = tomllib.loads(path.read_text())
    rows = document.get('package')
    if not isinstance(rows, list) or not rows:
        raise AuditError('empty_lock_inventory')
    packages = set()
    for row in rows:
        if not isinstance(row, dict):
            raise AuditError('invalid_lock_inventory')
        source = row.get('source', {})
        if isinstance(source, dict) and (source.get('virtual') == '.' or source.get('editable') == '.'):
            continue
        packages.add(_package(row.get('name'), row.get('version')))
        if len(packages) > MAX_PACKAGES:
            raise AuditError('inventory_limit')
    if not packages:
        raise AuditError('empty_lock_inventory')
    return packages


def _craft_lock(path: Path) -> set[Package]:
    packages = set()
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(('#', '--hash=')):
            continue
        match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)\s*\\?', stripped)
        if not match:
            raise AuditError('invalid_craft_lock')
        packages.add(_package(*match.groups()))
        if len(packages) > MAX_PACKAGES:
            raise AuditError('inventory_limit')
    if not packages:
        raise AuditError('empty_lock_inventory')
    return packages


def _inventories(root: Path, runtime: Path, errors: list[dict]) -> tuple[list[dict], dict[Package, set[str]]]:
    environments = []
    packages: dict[Package, set[str]] = {}
    targets = [('runtime_installed', runtime, 'installed', True)]
    development = root / '.venv'
    if development.resolve() != runtime.resolve():
        targets.append(('development_installed', development, 'installed', False))
    targets.extend([
        ('uv_lock', root / 'uv.lock', 'universal_lock', True),
        ('craft_lock', root / 'jarvis-craft-tools/requirements.lock.txt', 'planned_lock', False),
    ])
    for label, path, kind, required in targets:
        environment = {'label': label, 'path': str(path), 'kind': kind,
                       'package_count': 0, 'status': 'not_present'}
        environments.append(environment)
        if not path.exists() and not required:
            continue
        try:
            if kind == 'installed':
                found = _installed(path)
            elif kind == 'universal_lock':
                found = _uv_lock(path)
            else:
                found = _craft_lock(path)
            environment.update(package_count=len(found), status='inventoried')
            for package in found:
                packages.setdefault(package, set()).add(label)
        except (AuditError, OSError, ValueError, KeyError, TypeError) as exc:
            environment['status'] = 'incomplete'
            code = str(exc) if isinstance(exc, AuditError) else 'inventory_unavailable'
            errors.append({'stage': 'inventory', 'code': code, 'environment': label})
    return environments, packages


def _request_json(method: str, endpoint: str, deadline: float, payload: dict | None = None) -> dict:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AuditError('deadline_exceeded')
    response = None
    try:
        response = http_request(
            method, OSV_API + endpoint, json=payload, timeout=max(1, min(10, int(remaining))),
            deadline=deadline, allow_redirects=False, stream=True, use_proxy=True,
            fallback_on_proxy_fail=True, headers={'Accept-Encoding': 'identity'},
        )
        if response.status_code != 200:
            raise AuditError('advisory_http_error')
        if response.headers.get('Content-Encoding', '').lower() not in {'', 'identity'}:
            raise AuditError('unsupported_advisory_encoding')
        body = bytearray()
        while True:
            if time.monotonic() >= deadline:
                raise AuditError('deadline_exceeded')
            # read1 performs one underlying read rather than waiting to fill
            # 64 KiB. Avoid decoder loops that can hide a slow encoded body.
            chunk = response.raw.read1(65536, decode_content=False)
            if time.monotonic() >= deadline:
                raise AuditError('deadline_exceeded')
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES:
                raise AuditError('advisory_response_limit')
        result = json.loads(body)
        if not isinstance(result, dict):
            raise AuditError('invalid_advisory_response')
        return result
    except (requests.RequestException, Urllib3HTTPError, OSError):
        raise AuditError('advisory_network_error') from None
    except (ValueError, TypeError):
        raise AuditError('invalid_advisory_response') from None
    finally:
        if response is not None:
            response.close()


def _advisory_id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,199}', value):
        raise AuditError('invalid_advisory_id')
    return value


def _query(packages: list[Package], deadline: float, errors: list[dict]) -> tuple[dict[Package, set[str]], int]:
    matches: dict[Package, set[str]] = {}
    if len(packages) > MAX_PACKAGES:
        errors.append({'stage': 'query', 'code': 'package_limit'})
    pending = [(package, '') for package in packages[:MAX_PACKAGES]]
    queried = 0
    seen_tokens: set[tuple[Package, str]] = set()
    for _ in range(MAX_QUERY_PAGES):
        if not pending:
            return matches, queried
        if time.monotonic() >= deadline:
            errors.append({'stage': 'query', 'code': 'deadline_exceeded'})
            return matches, queried
        queries = []
        for (name, version), token in pending:
            query: dict[str, Any] = {'package': {'name': name, 'ecosystem': 'PyPI'}, 'version': version}
            if token:
                query['page_token'] = token
            queries.append(query)
        try:
            if queried == 0:
                queried = len(pending)
            result = _request_json('POST', '/querybatch', deadline, {'queries': queries})
            slots = result.get('results')
            if not isinstance(slots, list):
                raise AuditError('missing_query_results')
            if len(slots) != len(pending):
                errors.append({'stage': 'query', 'code': 'missing_query_results'})
        except AuditError as exc:
            errors.append({'stage': 'query', 'code': str(exc)})
            return matches, queried
        following = []
        for (package, _), slot in zip(pending, slots):
            try:
                if not isinstance(slot, dict) or not isinstance(slot.get('vulns', []), list):
                    raise AuditError('invalid_query_result')
                if set(slot) - {'vulns', 'next_page_token'}:
                    raise AuditError('invalid_query_result')
                for vulnerability in slot.get('vulns', []):
                    if not isinstance(vulnerability, dict):
                        raise AuditError('invalid_query_result')
                    matches.setdefault(package, set()).add(_advisory_id(vulnerability.get('id')))
                token = slot.get('next_page_token', '')
                if not isinstance(token, str) or len(token) > 4096:
                    raise AuditError('invalid_pagination_token')
                if token:
                    if (package, token) in seen_tokens:
                        raise AuditError('repeated_pagination_token')
                    seen_tokens.add((package, token))
                    following.append((package, token))
            except AuditError as exc:
                errors.append({'stage': 'query', 'code': str(exc)})
        pending = following
    if pending:
        errors.append({'stage': 'query', 'code': 'pagination_limit'})
    return matches, queried


def _severity(record: dict, affected: list[dict]) -> str:
    values = ['unknown']
    for item in [record, *affected]:
        for field in ('database_specific', 'ecosystem_specific'):
            data = item.get(field, {})
            if isinstance(data, dict) and isinstance(data.get('severity'), str):
                value = data['severity'].lower().replace('moderate', 'medium')
                if value in SEVERITY_ORDER:
                    values.append(value)
    return max(values, key=SEVERITY_ORDER.__getitem__)


def _advisory(record: dict, package: Package) -> dict:
    identifier = _advisory_id(record.get('id'))
    affected = record.get('affected')
    if not isinstance(affected, list):
        raise AuditError('invalid_advisory_details')
    matching = [item for item in affected if isinstance(item, dict)
                and isinstance(item.get('package'), dict)
                and item['package'].get('ecosystem') == 'PyPI'
                and isinstance(item['package'].get('name'), str)
                and _name(item['package']['name']) == package[0]]
    if not matching:
        raise AuditError('advisory_package_mismatch')
    aliases = record.get('aliases', [])
    if not isinstance(aliases, list):
        raise AuditError('invalid_advisory_details')
    fixed = set()
    for item in matching:
        for affected_range in item.get('ranges', []):
            if affected_range.get('type') not in {'ECOSYSTEM', 'SEMVER'}:
                continue
            for event in affected_range.get('events', []):
                value = event.get('fixed')
                if value is not None:
                    fixed.add(_package(package[0], value)[1])
    summary = record.get('summary')
    return {
        'id': identifier, 'aliases': sorted({_advisory_id(alias) for alias in aliases}),
        'summary': ' '.join(summary.split())[:600] if isinstance(summary, str) else 'Published advisory match',
        'severity': _severity(record, matching), 'fixed_versions': sorted(fixed),
        'urls': ['https://osv.dev/vulnerability/' + quote(identifier, safe='')],
        'details_complete': True,
    }


def _merge_aliases(records: list[dict]) -> list[dict]:
    groups: list[dict] = []
    for record in records:
        identifiers = {record['id'], *record['aliases']}
        matching = [item for item in groups if identifiers & {item['id'], *item['aliases']}]
        for item in matching:
            identifiers.update([item['id'], *item['aliases']])
        for item in matching:
            groups.remove(item)
        combined = [record, *matching]
        primary = min(identifiers, key=lambda value: (not value.startswith('GHSA-'), value))
        best = next((item for item in combined if item['id'] == primary), record)
        groups.append({
            **best, 'id': primary, 'aliases': sorted(identifiers - {primary}),
            'severity': max((item['severity'] for item in combined), key=SEVERITY_ORDER.__getitem__),
            'fixed_versions': sorted({value for item in combined for value in item['fixed_versions']}),
            'urls': sorted({url for item in combined for url in item['urls']}),
            'details_complete': all(item['details_complete'] for item in combined),
        })
    return sorted(groups, key=lambda item: item['id'])


def _findings(matches: dict[Package, set[str]], environments: dict[Package, set[str]],
              deadline: float, errors: list[dict]) -> list[dict]:
    details = {}
    ids = sorted({identifier for values in matches.values() for identifier in values})
    if len(ids) > MAX_ADVISORIES:
        errors.append({'stage': 'details', 'code': 'advisory_limit'})
    for identifier in ids[:MAX_ADVISORIES]:
        try:
            record = _request_json('GET', '/vulns/' + quote(identifier, safe=''), deadline)
            if record.get('id') != identifier:
                raise AuditError('advisory_id_mismatch')
            details[identifier] = record
        except AuditError as exc:
            errors.append({'stage': 'details', 'code': str(exc)})
    findings = []
    for package, identifiers in sorted(matches.items()):
        records = []
        for identifier in sorted(identifiers):
            record = details.get(identifier)
            try:
                if record is None:
                    raise AuditError('advisory_details_unavailable')
                if record.get('withdrawn') is not None:
                    withdrawn = record['withdrawn']
                    if not isinstance(withdrawn, str):
                        raise AuditError('invalid_advisory_details')
                    datetime.fromisoformat(withdrawn.replace('Z', '+00:00'))
                    continue
                records.append(_advisory(record, package))
            except (AuditError, TypeError, AttributeError, ValueError) as exc:
                code = str(exc) if isinstance(exc, AuditError) else 'invalid_advisory_details'
                errors.append({'stage': 'details', 'code': code})
                records.append({'id': identifier, 'aliases': [], 'summary': 'Advisory match; details unavailable',
                                'severity': 'unknown', 'fixed_versions': [], 'details_complete': False,
                                'urls': ['https://osv.dev/vulnerability/' + quote(identifier, safe='')]})
        if records:
            findings.append({'package': package[0], 'version': package[1],
                             'environments': sorted(environments[package]), 'advisories': _merge_aliases(records)})
    return findings


def _markdown(result: dict) -> str:
    lines = ['## Advisory check', '', f"Status: **{result['status']}**",
             f"Checked at: {result['checked_at']}", f"Unique package/version pairs queried: {result['packages_queried']}",
             '', '### Coverage', '']
    for environment in result['environments']:
        lines.append(f"- {environment['label']}: {environment['package_count']} packages ({environment['status']}; {environment['kind']})")
    lines.extend(['', '### Findings', ''])
    if not result['findings']:
        lines.append('No published advisory matches returned.' if result['complete'] else 'No matches confirmed; the audit is incomplete.')
    for finding in result['findings']:
        lines.append(f"- **{finding['package']} {finding['version']}** ({', '.join(finding['environments'])})")
        for advisory in finding['advisories']:
            fixed = ', '.join(advisory['fixed_versions']) or 'not supplied'
            lines.append(f"  - [{advisory['id']}]({advisory['urls'][0]}): {advisory['severity']}; published fixes: {fixed}")
    if result['errors']:
        lines.extend(['', '### Incomplete checks', ''])
        lines.extend(f"- {item['stage']}: {item['code']}" for item in result['errors'])
    lines.extend(['', '### Limits', '', *('- ' + value for value in LIMITATIONS)])
    return '\n'.join(lines)


def run_audit(project_root: Path, *, runtime_prefix: Path | None = None) -> dict[str, Any]:
    """Audit fixed local inventory scopes against OSV without installing or changing anything."""
    deadline = time.monotonic() + AUDIT_SECONDS
    errors: list[dict] = []
    environments, packages = _inventories(project_root.resolve(), runtime_prefix or Path(sys.prefix), errors)
    matches, queried = _query(sorted(packages), deadline, errors)
    findings = _findings(matches, packages, deadline, errors)
    errors = [json.loads(value) for value in sorted({json.dumps(error, sort_keys=True) for error in errors})]
    complete = not errors
    status = 'incomplete' if errors else 'findings' if findings else 'clear'
    issue_count = len(findings) + bool(errors)
    severity = max((advisory['severity'] for finding in findings for advisory in finding['advisories']),
                   key=SEVERITY_ORDER.__getitem__, default='unknown')
    alert_severity = 'critical' if severity == 'critical' else 'high' if severity == 'high' else 'medium'
    identity = {'findings': findings, 'errors': errors}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    description = f'{len(findings)} package/version advisory match(es); {queried} pairs queried.'
    if errors:
        description += ' Audit incomplete; some inventories or advisory checks could not be verified.'
    result = {
        'status': status, 'complete': complete, 'checked_at': datetime.now(UTC).isoformat(),
        'environments': environments, 'coverage': {'environments': environments, 'limitations': LIMITATIONS},
        'packages_queried': queried, 'findings': findings, 'errors': errors, 'issue_count': issue_count,
        'alert_needed': bool(issue_count), 'alert_title': 'Jarvis dependency security: ' + status,
        'alert_description': description, 'alert_severity': alert_severity,
        'alert_dedupe_key': 'jarvis-dependency-security:' + digest,
    }
    result['summary_markdown'] = _markdown(result)
    return result
