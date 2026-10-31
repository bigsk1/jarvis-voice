"""Bound webhook receipts while keeping complete payload contracts intact."""

import copy
import json
import re

try:
    from security_utils import redact_sensitive_data, redact_sensitive_text
except ModuleNotFoundError:
    from lib.security_utils import redact_sensitive_data, redact_sensitive_text

CONTRACT_FIELDS = ('description', 'required_fields', 'optional_fields', 'notes', 'payload_schema', 'example',
                   'contract_available', 'artifact_handoff')
RECEIPT_FIELDS = ('webhook', 'request_sent', 'response_received', 'delivery_status', 'retry_safe',
                  'status_code', 'redirect_blocked', 'missing_fields', 'validation_path',
                  'retry_after_seconds', 'contract_truncated', 'context_truncated',
                  'catalog_compacted', 'contract_lookup', 'webhooks_omitted')
_HANDOFF_ARTIFACT_LIMIT = 12
_STASH_REF = re.compile(r'stash://space_[A-Za-z0-9_-]{1,180}/([^/\\\x00-\x1f\x7f]{1,512})\Z')
_CANVAS_PAGE_ID = re.compile(r'[A-Za-z0-9_-]{1,200}\Z')


def _nonnegative_count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 1_000_000 else 0


def _handoff_receipt(data):
    """Keep correlation and explicit artifact handles, never the task or credentials."""
    result = {}
    handoff_id = data.get('handoff_id')
    if isinstance(handoff_id, str) and 0 < len(handoff_id) <= 200:
        result['handoff_id'] = handoff_id
    raw = data.get('handoff_artifacts')
    if not isinstance(raw, list):
        return result
    artifacts = []
    for item in raw[:_HANDOFF_ARTIFACT_LIMIT]:
        if not isinstance(item, dict):
            continue
        if item.get('kind') == 'stash':
            ref = item.get('ref')
            mode = item.get('mode')
            match = _STASH_REF.fullmatch(ref) if isinstance(ref, str) and len(ref) <= 1024 else None
            if match and match.group(1) not in ('.', '..') and mode in ('cloud', 'local'):
                artifacts.append({'kind': 'stash', 'ref': ref, 'mode': mode})
        elif item.get('kind') == 'canvas':
            page_id = item.get('page_id')
            if isinstance(page_id, str) and _CANVAS_PAGE_ID.fullmatch(page_id):
                artifacts.append({'kind': 'canvas', 'page_id': page_id})
    total = max(
        _nonnegative_count(data.get('handoff_artifacts_count')),
        len(raw) + _nonnegative_count(data.get('handoff_artifacts_omitted')),
    )
    result.update(handoff_artifacts_count=total, handoff_artifacts=artifacts)
    if total > len(artifacts):
        result['handoff_artifacts_omitted'] = total - len(artifacts)
        result['context_truncated'] = True
    return result


def _proxy_route(value):
    """Keep route decisions in follow-ups without copying proxy credentials."""
    if not isinstance(value, dict):
        return {}
    allowed = {
        'policy': ('off', 'prefer', 'require'),
        'slot': ('LOCAL_PROXY', 'LOCAL_PROXY2'),
        'basis': ('webhook_route',),
        'direct_reason': ('policy_off', 'no_reachable_proxy'),
    }
    route = {key: value[key] for key, choices in allowed.items() if value.get(key) in choices}
    if 'used' in value and (isinstance(value['used'], bool) or value['used'] is None):
        route['used'] = value['used']
    return route


def _contract(value):
    result = {key: copy.deepcopy(value[key]) for key in CONTRACT_FIELDS if key in value}
    if result.get('artifact_handoff') != 'jarvis_v1':
        result.pop('artifact_handoff', None)
    if 'example' in result:
        result['example'] = redact_sensitive_data(result['example'])
    return result


def project_webhook_data(value, max_chars=6000):
    """Allowlist registry guidance and delivery state; never slice a JSON schema."""
    if not isinstance(value, dict):
        return {}
    data = value.get('data', value)
    if not isinstance(data, dict):
        return {}
    result = {key: copy.deepcopy(data[key]) for key in RECEIPT_FIELDS if key in data}
    result.update(_handoff_receipt(data))
    proxy = _proxy_route(data.get('proxy'))
    if proxy:
        result['proxy'] = proxy
    result.update(_contract(data))
    for key in ('error', 'speech'):
        if value.get(key):
            result[key] = redact_sensitive_text(str(value[key]))[:700]
    for key in ('response', 'error'):
        if data.get(key):
            result[key] = redact_sensitive_text(str(data[key]))[:700]
    if 'ok' in value:
        result['ok'] = bool(value['ok'])
    entries = data.get('webhooks')
    if isinstance(entries, list):
        result['webhooks'] = [
            {'name': str(item['name']), **_contract(item)}
            for item in entries if isinstance(item, dict) and item.get('name')
        ]

    def fits():
        return len(json.dumps(result, ensure_ascii=False, separators=(',', ':'))) <= max_chars

    if fits():
        return result
    # Larger catalogs retain destination names and requirements; inspect the
    # selected destination with describe=true rather than using a partial schema.
    if 'webhooks' in result:
        for item in result['webhooks']:
            for key in ('payload_schema', 'example'):
                if key in item:
                    item.pop(key)
                    item['contract_available'] = True
            for key in ('description', 'notes'):
                if isinstance(item.get(key), str) and len(item[key]) > 180:
                    item[key] = item[key][:180]
                    item['contract_available'] = True
        result['catalog_compacted'] = True
        result['contract_lookup'] = 'Use webhook=<selected name>, describe=true, data={} for its complete contract.'
        if fits():
            return result
    # Drop whole optional units with explicit omission markers. Schema strings
    # such as patterns and nested required fields must remain exact when present.
    for key in ('response', 'example', 'notes', 'optional_fields', 'description', 'speech', 'payload_schema'):
        if key in result:
            result.pop(key)
            result['contract_truncated' if key in CONTRACT_FIELDS else 'context_truncated'] = True
        if fits():
            return result
    if 'handoff_artifacts' in result:
        while result['handoff_artifacts'] and not fits():
            result['handoff_artifacts'].pop()
            result['handoff_artifacts_omitted'] = result['handoff_artifacts_count'] - len(result['handoff_artifacts'])
            result['context_truncated'] = True
        if fits():
            return result
    if 'webhooks' in result:
        total = len(result['webhooks'])
        while result['webhooks'] and not fits():
            result['webhooks'].pop()
            result['webhooks_omitted'] = total - len(result['webhooks'])
    if fits():
        return result
    # Exact IDs must never become a different ID by truncation. At very small
    # budgets retain delivery state before optional correlation and contracts.
    for key in ('handoff_id', 'error', 'proxy', 'contract_lookup', 'required_fields',
                'missing_fields', 'validation_path', 'webhooks'):
        if key in result:
            result.pop(key)
            result['context_truncated'] = True
        if fits():
            return result
    fallback = {'context_truncated': True, 'contract_truncated': True}
    if len(json.dumps(fallback, separators=(',', ':'))) <= max_chars:
        return fallback
    fallback = {'context_truncated': True}
    return fallback if len(json.dumps(fallback, separators=(',', ':'))) <= max_chars else {}


def project_webhook_runs(value, max_chars=6500):
    # Stored follow-ups already contain this aggregate. Reprojection must keep
    # their ordered receipts rather than treating the aggregate as a receipt.
    saved_aggregate = isinstance(value, dict) and isinstance(value.get('results'), list)
    runs = value.get('results') if saved_aggregate else value
    runs = runs if isinstance(runs, list) else [runs]
    selected = [run for run in runs[-3:] if isinstance(run, dict)]
    if not selected:
        return {}
    if len(selected) == 1 and not saved_aggregate:
        return project_webhook_data(selected[0], max_chars=max_chars)
    projected = [project_webhook_data(run, max_chars=max_chars) for run in selected]
    total = max(len(runs), _nonnegative_count(value.get('runs_count'))) if saved_aggregate else len(runs)
    result = {'runs_count': total, 'results': projected}
    if len(selected) < total:
        result['results_omitted'] = total - len(selected)
    while len(json.dumps(result, ensure_ascii=False, separators=(',', ':'))) > max_chars:
        if len(result['results']) == 1:
            envelope = {**result, 'results': []}
            available = max_chars - len(json.dumps(envelope, ensure_ascii=False, separators=(',', ':')))
            result['results'][0] = project_webhook_data(selected[-1], max_chars=max(2, available))
            break
        result['results'].pop(0)
        result['results_omitted'] = result.get('results_omitted', 0) + 1
    if len(json.dumps(result, ensure_ascii=False, separators=(',', ':'))) <= max_chars:
        return result
    # The aggregate envelope itself may not fit. Keep the latest receipt when
    # possible, and explicitly acknowledge that earlier runs were omitted.
    latest = project_webhook_data(selected[-1], max_chars=max_chars - 55)
    latest.update(context_truncated=True, results_omitted=max(0, total - 1))
    if len(json.dumps(latest, ensure_ascii=False, separators=(',', ':'))) <= max_chars:
        return latest
    return {'context_truncated': True} if max_chars >= 26 else {}
