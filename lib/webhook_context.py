"""Bound webhook receipts while keeping complete payload contracts intact."""

import copy
import json

try:
    from security_utils import redact_sensitive_data, redact_sensitive_text
except ModuleNotFoundError:
    from lib.security_utils import redact_sensitive_data, redact_sensitive_text

CONTRACT_FIELDS = ('description', 'required_fields', 'optional_fields', 'notes', 'payload_schema', 'example',
                   'contract_available')
RECEIPT_FIELDS = ('webhook', 'request_sent', 'response_received', 'delivery_status', 'retry_safe',
                  'status_code', 'redirect_blocked', 'missing_fields', 'validation_path',
                  'retry_after_seconds', 'contract_truncated', 'context_truncated',
                  'catalog_compacted', 'contract_lookup', 'webhooks_omitted')


def _contract(value):
    result = {key: copy.deepcopy(value[key]) for key in CONTRACT_FIELDS if key in value}
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
    if 'webhooks' in result:
        total = len(result['webhooks'])
        while result['webhooks'] and not fits():
            result['webhooks'].pop()
            result['webhooks_omitted'] = total - len(result['webhooks'])
    if fits():
        return result
    return {'context_truncated': True, 'contract_truncated': True}


def project_webhook_runs(value, max_chars=6500):
    # Stored follow-ups already contain this aggregate. Reprojection must keep
    # their ordered receipts rather than treating the aggregate as a receipt.
    runs = value.get('results') if isinstance(value, dict) and isinstance(value.get('results'), list) else value
    runs = runs if isinstance(runs, list) else [runs]
    selected = [run for run in runs[-3:] if isinstance(run, dict)]
    if not selected:
        return {}
    if len(selected) == 1:
        return project_webhook_data(selected[0], max_chars=max_chars)
    projected = [project_webhook_data(run, max_chars=max_chars) for run in selected]
    result = {'runs_count': len(runs), 'results': projected}
    if len(selected) < len(runs):
        result['results_omitted'] = len(runs) - len(selected)
    while len(json.dumps(result, ensure_ascii=False, separators=(',', ':'))) > max_chars:
        if len(result['results']) == 1:
            result['results'][0] = project_webhook_data(selected[-1], max_chars=max_chars - 150)
            break
        result['results'].pop(0)
        result['results_omitted'] = result.get('results_omitted', 0) + 1
    return result
