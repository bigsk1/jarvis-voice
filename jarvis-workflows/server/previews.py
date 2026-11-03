"""Bounded, explicitly reduced projections of results and prepared arguments."""
from __future__ import annotations

import json
import math

from security_utils import is_sensitive_key, redact_sensitive_text

RECOVERY_KEYS = frozenset({'video_id', 'video_ids', 'provider_video_id', 'request_id', 'request_ref',
                          'receipt_id', 'receipt_path', 'receipt_stash_ref', 'task_id', 'recovery',
                          'recovery_handles', 'job_kind', 'kind', 'provider', 'stash_ref',
                          'canvas_url', 'page_id', 'url', 'artifact', 'artifacts'})
OMITTED_KEYS = frozenset({'variables', 'raw_output', 'environment'})


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _make_preview(value, *, budget: int, max_string_chars: int, max_list_items: int,
                  max_dict_items: int, max_depth: int):
    """Return the projection and truthful metadata about every kind of reduction."""
    if budget < 256:
        raise ValueError('Preview budget must be at least 256 bytes')
    changes: dict[str, int] = {}
    metadata = {'kind': 'bounded_redacted_preview', 'redacted': False, 'truncated': False,
                'limit_bytes': budget, 'changes': changes}

    def reduced(kind: str, count: int = 1):
        metadata['truncated'] = True
        changes[kind] = changes.get(kind, 0) + count

    def trim(item, depth=0):
        if depth > max_depth:
            reduced('depth_limits')
            return '[preview depth limit; content omitted]'
        if isinstance(item, dict):
            # Provider receipts are kept first when a large result is reduced.
            pairs = sorted(item.items(), key=lambda pair: str(pair[0]) not in RECOVERY_KEYS)
            result = {}
            omitted = 0
            for key, child in pairs[:max_dict_items]:
                key = str(key)
                if key in OMITTED_KEYS:
                    omitted += 1
                    continue
                if is_sensitive_key(key):
                    metadata['redacted'] = True
                    result[key] = '[redacted]'
                else:
                    result[key] = trim(child, depth + 1)
            omitted += max(0, len(pairs) - max_dict_items)
            if omitted:
                reduced('omitted_fields', omitted)
                result['_preview_omitted_fields'] = omitted
            return result
        if isinstance(item, (list, tuple)):
            result = [trim(child, depth + 1) for child in item[:max_list_items]]
            omitted = max(0, len(item) - max_list_items)
            if omitted:
                reduced('omitted_items', omitted)
                result.append(f'[preview omitted {omitted} more items]')
            return result
        if isinstance(item, str):
            safe = redact_sensitive_text(item)
            if safe != item:
                metadata['redacted'] = True
            omitted = max(0, len(safe) - max_string_chars)
            if omitted:
                reduced('shortened_strings')
                return safe[:max_string_chars] + f' [preview truncated {omitted} characters]'
            return safe
        if isinstance(item, float) and not math.isfinite(item):
            reduced('non_json_values')
            return '[non-finite number omitted from preview]'
        if item is None or isinstance(item, (int, float, bool)):
            return item
        reduced('non_json_values')
        return '[non-JSON value: ' + redact_sensitive_text(str(item))[:max_string_chars] + ']'

    safe = trim(value)
    raw = _json(safe)
    if len(raw.encode()) > budget:
        reduced('total_budget_limits')
        recovery = {}
        if isinstance(safe, dict):
            for key, child in safe.items():
                if key not in RECOVERY_KEYS:
                    continue
                # Preserve ordinary receipt identifiers, without letting an
                # unexpected large recovery payload defeat the total bound.
                projected = child
                if len(_json(projected).encode()) > min(1000, budget // 4):
                    projected = '[recovery preview truncated; inspect the emitted receipt]'
                    reduced('shortened_recovery_fields')
                recovery[key] = projected
        safe = {**recovery, 'preview': '', '_preview': metadata}
        while len(_json(safe).encode()) > budget and recovery:
            recovery.pop(next(reversed(recovery)))
            reduced('omitted_recovery_fields')
            safe = {**recovery, 'preview': '', '_preview': metadata}
        # The serialized text is itself JSON-escaped in the envelope. Find a
        # prefix that keeps the complete retained object within the byte limit.
        lower, upper = 0, len(raw)
        while lower < upper:
            middle = (lower + upper + 1) // 2
            safe['preview'] = raw[:middle] + ' [preview truncated by total byte limit]'
            if len(_json(safe).encode()) <= budget:
                lower = middle
            else:
                upper = middle - 1
        safe['preview'] = raw[:lower] + ' [preview truncated by total byte limit]'
        if len(_json(safe).encode()) > budget:
            safe = {'preview': '[preview truncated]', '_preview': {
                'redacted': metadata['redacted'], 'truncated': True, 'limit_bytes': budget}}
    elif isinstance(safe, dict) and (metadata['redacted'] or metadata['truncated']):
        safe['_preview'] = metadata
        # Metadata counts toward the retained bound as well.
        if len(_json(safe).encode()) > budget:
            reduced('total_budget_limits')
            safe = {'preview': '[preview omitted to retain reduction metadata]', '_preview': metadata}
    return safe, metadata


def bounded_preview(value, budget: int = 10000):
    """Bound event/history data and explicitly mark every truncation or omission."""
    return _make_preview(value, budget=budget, max_string_chars=2000,
                         max_list_items=20, max_dict_items=40, max_depth=6)[0]


def approval_argument_preview(arguments, budget: int = 20000):
    """Keep ordinary long calls reviewable; identify redaction and truncation."""
    preview, metadata = _make_preview(
        arguments, budget=budget, max_string_chars=budget,
        max_list_items=200, max_dict_items=200, max_depth=12,
    )
    metadata = dict(metadata)
    metadata['note'] = (
        'This is a bounded preview of the prepared arguments. Credential-looking values '
        'are redacted. ' + ('Some content was truncated or omitted; review the marked limits '
                           'before approving.' if metadata['truncated'] else 'No content was truncated.')
    )
    return preview, metadata
