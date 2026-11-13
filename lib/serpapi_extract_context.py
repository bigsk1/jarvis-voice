"""Bound normalized SerpApi Extract data for immediate and saved model context.

This pure projector shares no dependencies with the Web application. Retained
URLs stay exact; context limits omit whole metadata fields or collection rows.
"""

from __future__ import annotations

import json
from collections.abc import Callable

_COLLECTION_LIMITS = {'urls': 100, 'candidates': 100, 'pages': 10, 'feeds': 10, 'links': 20}


def _truncate_text(value: str, maximum: int) -> str:
    marker = '... [truncated for context]'
    if len(value) <= maximum:
        return value
    return value[:max(0, maximum - len(marker))].rstrip() + marker


def _has_truncation(value) -> bool:
    if isinstance(value, list):
        return any(_has_truncation(item) for item in value)
    if not isinstance(value, dict):
        return False
    return any(
        (item is True and key.endswith('_truncated'))
        or _has_truncation(item)
        for key, item in value.items()
    )


def project_serpapi_extract_runs(
    value,
    *,
    max_chars: int = 6000,
    truncate_text: Callable[[str, int], str] | None = None,
) -> dict:
    """Keep reader identities and excerpts within a serialized character budget.

    The budget includes metadata, notices, JSON escaping, and repeated-run
    wrappers. It must be at least 256 characters. Root ``context_truncated``
    includes both provider omissions and additional context compaction. The
    reader's own collection limits apply; generic search shortlist caps do not.
    An intentionally unrequested body is not truncated evidence.
    """
    if max_chars < 256:
        raise ValueError("max_chars must be at least 256")
    truncate_text = truncate_text or _truncate_text
    previous_wrapper = (
        isinstance(value, dict) and isinstance(value.get('results'), list)
        and isinstance(value.get('runs_count'), int)
    )
    runs = value['results'] if previous_wrapper else value if isinstance(value, list) else [value]
    runs_count = max(len(runs), value['runs_count']) if previous_wrapper else len(runs)
    inherited_runs_omission = bool(previous_wrapper and value.get('results_truncated'))
    inherited_context_omission = bool(previous_wrapper and value.get('context_truncated'))
    selected = [run for run in runs[-3:] if isinstance(run, dict)]
    if not selected:
        return {}
    while len(selected) > 1 and (max_chars - 180) // len(selected) < 256:
        selected.pop(0)
    repeated = previous_wrapper or len(runs) > 1
    run_budget = (max_chars - 180) // len(selected) if repeated else max_chars

    def project(payload: dict) -> dict:
        result = {field: payload[field] for field in (
            'provider', 'engine', 'mode', 'requested_url', 'url',
            'content_chars', 'content_truncated', 'urls_count', 'provider_urls_count',
            'urls_truncated', 'pages_count', 'provider_pages_count', 'pages_truncated',
            'content_omitted', 'javascript_rendered', 'search_id', 'credits_consumed',
            'external_content_trust',
        ) if isinstance(payload.get(field), (str, int, float, bool))}
        result['context_truncated'] = payload.get('context_truncated') is True
        for field in ('context_truncated', 'context_metadata_truncated', 'context_pages_truncated',
                      'candidates_truncated'):
            if payload.get(field) is True:
                result[field] = True

        def rows(source: dict, field: str, fields: tuple[str, ...]) -> list:
            original = source.get(field)
            if not isinstance(original, list):
                return []
            projected = []
            for ordinal, row in enumerate(original[:_COLLECTION_LIMITS[field]], 1):
                if not isinstance(row, dict):
                    continue
                item = {key: row[key] for key in fields
                        if isinstance(row.get(key), (str, int, float, bool))}
                if field in {'urls', 'candidates'}:
                    previous = row.get('ordinal')
                    item['ordinal'] = previous if type(previous) is int and 1 <= previous <= 100 else ordinal
                if row.get('context_metadata_truncated') is True:
                    item['context_metadata_truncated'] = True
                for key in ('title', 'source', 'type'):
                    if isinstance(item.get(key), str):
                        if len(item[key]) > 240:
                            item['context_metadata_truncated'] = True
                        item[key] = truncate_text(item[key], 240)
                if item:
                    projected.append(item)
            return projected

        def page(source: dict, target: dict) -> None:
            for field in ('feeds_count', 'provider_feeds_count', 'feeds_truncated',
                          'links_count', 'provider_links_count', 'links_truncated'):
                if isinstance(source.get(field), (int, bool)):
                    target[field] = source[field]
            for field in ('context_metadata_truncated', 'context_feeds_truncated', 'context_links_truncated',
                          'content_excerpt_truncated'):
                if source.get(field) is True:
                    target[field] = True
            for field in ('title', 'error'):
                if source.get(field):
                    if len(str(source[field])) > 400:
                        target['context_metadata_truncated'] = True
                    target[field] = truncate_text(str(source[field]), 400)
            info = source.get('page_information')
            if isinstance(info, dict):
                target['page_information'] = {
                    field: truncate_text(info[field], 500)
                    if field in ('title', 'description') else info[field]
                    for field in ('title', 'description', 'canonical', 'final_url', 'language', 'favicon')
                    if isinstance(info.get(field), str) and info[field]
                }
                if any(isinstance(info.get(field), str) and len(info[field]) > 500
                       for field in ('title', 'description')):
                    target['context_metadata_truncated'] = True
            for field, keys in (
                ('feeds', ('title', 'url', 'type')),
                ('links', ('title', 'url', 'internal')),
            ):
                if isinstance(source.get(field), list):
                    target[field] = rows(source, field, keys)
                    target[f'context_{field}_truncated'] = (
                        source.get(f'context_{field}_truncated') is True
                        or len(source[field]) > len(target[field])
                    )

        mode = payload.get('mode', 'scrape')
        page_pairs = []
        if mode == 'map':
            field = 'urls' if isinstance(payload.get('urls'), list) else 'candidates'
            result['candidates'] = rows(payload, field, ('url', 'title', 'source'))
            result['candidates_truncated'] = (
                payload.get('candidates_truncated') is True
                or len(payload.get(field) or []) > len(result['candidates'])
            )
            for row in result['candidates']:
                if row.pop('context_metadata_truncated', False):
                    result['context_metadata_truncated'] = True
        elif mode == 'crawl':
            original = payload.get('pages') or []
            source_pages = [item for item in original if isinstance(item, dict)][:_COLLECTION_LIMITS['pages']]
            result['pages'] = []
            for source in source_pages:
                item = {field: source[field] for field in (
                    'url', 'depth', 'content_chars', 'content_truncated', 'content_omitted',
                ) if isinstance(source.get(field), (str, int, float, bool))}
                page(source, item)
                result['pages'].append(item)
                page_pairs.append((source, item))
            result['context_pages_truncated'] = (
                payload.get('context_pages_truncated') is True or len(original) > len(result['pages'])
            )
        else:
            page(payload, result)
            page_pairs.append((payload, result))

        # Metadata and source addresses take priority over carrying more prose.
        # Trim optional rows before assigning the shared excerpt budget.
        def encoded_size() -> int:
            return len(json.dumps(result, ensure_ascii=False, allow_nan=False))

        targets = [target for _, target in page_pairs]
        for target in reversed(targets):
            for field in ('links', 'feeds'):
                while encoded_size() > run_budget - 300 and target.get(field):
                    target[field].pop()
                    target[f'context_{field}_truncated'] = True
        # Keep ordered map identities ahead of optional labels when the real
        # serialized budget is tight. A map needs no reserved article excerpt.
        for field in ('source', 'title'):
            for row in reversed(result.get('candidates', [])):
                if encoded_size() <= run_budget:
                    break
                if field in row:
                    row.pop(field)
                    result['context_metadata_truncated'] = True
        for field in ('candidates', 'pages'):
            collection_budget = run_budget if field == 'candidates' else run_budget - 300
            while encoded_size() > collection_budget and len(result.get(field) or []) > 1:
                result[field].pop()
                result['candidates_truncated' if field == 'candidates' else 'context_pages_truncated'] = True
        kept_pages = result.get('pages', [result])
        page_pairs = [(source, target) for source, target in page_pairs
                      if any(target is kept for kept in kept_pages)]
        text_budget = max(0, run_budget - encoded_size() - 250)
        per_page = text_budget // max(1, len(page_pairs))
        for source, target in page_pairs:
            already_projected = not isinstance(source.get('content'), str)
            content = source.get('content_excerpt') if already_projected else source['content']
            if not isinstance(content, str) or not content:
                continue
            target['content_excerpt_truncated'] = source.get('content_excerpt_truncated') is True
            if already_projected:
                # Keep an existing excerpt exactly when it still fits, rather
                # than eroding it on each saved-turn/context round trip.
                target['content_excerpt'] = content
            elif per_page >= 100:
                target['content_excerpt_truncated'] = len(content) > per_page
                target['content_excerpt'] = truncate_text(content, per_page)
            else:
                target['content_excerpt_truncated'] = True
        # Escaped quotes and backslashes also consume saved-context space.
        while encoded_size() > run_budget:
            longest = max(targets, key=lambda item: len(item.get('content_excerpt', '')), default={})
            excerpt = longest.get('content_excerpt', '')
            if not excerpt:
                break
            longest['content_excerpt_truncated'] = True
            if len(excerpt) > 200:
                longest['content_excerpt'] = truncate_text(excerpt, len(excerpt) // 2)
            else:
                longest.pop('content_excerpt')
        # Long source metadata can fill the budget without any prose. Omit
        # complete fields/rows with a notice; never shorten a URL into a new one.
        for target in targets:
            info = target.get('page_information', {})
            for field in ('favicon', 'description', 'title', 'language', 'final_url'):
                if encoded_size() > run_budget and field in info:
                    info.pop(field)
                    target['context_metadata_truncated'] = True
        for field in ('candidates', 'pages'):
            while encoded_size() > run_budget and result.get(field):
                result[field].pop()
                result['candidates_truncated' if field == 'candidates' else 'context_pages_truncated'] = True
        for target in targets:
            info = target.get('page_information', {})
            if encoded_size() > run_budget and info.get('canonical'):
                info.pop('canonical')
                target['context_metadata_truncated'] = True
        for field in ('title', 'error', 'requested_url', 'url'):
            if encoded_size() > run_budget and field in result:
                result.pop(field)
                result['context_metadata_truncated'] = True
        result['context_truncated'] = _has_truncation(result)
        # Very small budgets can also require dropping normally short receipt
        # fields. Keep an explicit notice instead of exceeding the caller limit.
        for field in list(result):
            if encoded_size() <= run_budget:
                break
            if field in {'context_truncated', 'context_metadata_truncated'}:
                continue
            result.pop(field)
            result['context_metadata_truncated'] = result['context_truncated'] = True
        return result

    projected = []
    for run in selected:
        payload = run.get('data') if isinstance(run.get('data'), dict) else run
        projected.append(project(payload))
    if not repeated:
        return projected[0]
    omitted_runs = inherited_runs_omission or len(selected) < runs_count
    return {'runs_count': runs_count, 'results': projected,
            'results_truncated': omitted_runs,
            'context_truncated': inherited_context_omission or omitted_runs or _has_truncation(projected)}
