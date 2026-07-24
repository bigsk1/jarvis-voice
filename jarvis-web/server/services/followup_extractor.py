"""Follow-up data extraction for stored conversation turns.

Extracted from jarvis-web/server/sockets/chat.py to keep the socket handler
focused on request lifecycle. These functions are pure (no ChatHandler state)
and reduce a tool's raw result payload to a compact identifier/reference
bundle that can be replayed cheaply into subsequent router prompts.

Used in two places:
- Conversation history context (compact, FOLLOWUP_DEFAULT_MAX_CANDIDATES)
- Completion Guard effective evidence (richer, FOLLOWUP_EVIDENCE_MAX_CANDIDATES)
"""
import re
import hashlib
from datetime import datetime
from pathlib import Path

# URL extractor for Brave MCP search results whose content is buried inside
# raw[].text JSON blobs and full_text. We only need the URL list for
# "already searched" hints on follow-up turns, not the surrounding content.
_BRAVE_URL_RE = re.compile(r'https?://[^\s"\'<>)]+')

# Tools whose follow-up shape is handled by a dedicated branch below. Listed
# here so the generic results[]/items[] fallback skips them (otherwise it
# would overwrite or duplicate what the dedicated branch produced).
_DEDICATED_FOLLOWUP_BRANCHES = (
    'serpapi_search',
    'serpapi_home_depot',
    'serpapi_ebay_search',
    'serpapi_ebay_product',
    'serpapi_youtube_search',
    'serpapi_yelp_search',
    'crawl_url',
    'mcp_brave_search_brave_web_search',
    'mcp_brave_search_brave_news_search',
    'mcp_brave_search_brave_local_search',
    'brave_llm_context',
)

_PRESERVE_RUN_LIST_FOR_DEDICATED_BRANCHES = frozenset({
    'crawl_url',
    'mcp_brave_search_brave_web_search',
    'mcp_brave_search_brave_news_search',
    'mcp_brave_search_brave_local_search',
})

# Follow-up context: keep orchestrator history compact.
FOLLOWUP_DEFAULT_MAX_CANDIDATES = 5
# Completion Guard / effective evidence: allow ranking follow-ups without re-querying.
FOLLOWUP_EVIDENCE_MAX_CANDIDATES = 12
# Keep abstractive summaries available for follow-up turns without dragging
# whole transcript-sized artifacts through every router prompt.
FOLLOWUP_SUMMARY_MAX_CHARS = 6000
_FOLLOWUP_TRUNCATION_SUFFIX = "\n...[summary truncated for follow-up context]"
MANAGE_INTEL_DIR = Path(__file__).resolve().parents[3] / "jarvis-intel"

GENERIC_FOLLOWUP_LIST_KEYS = (
    'results',
    'top_results',
    'items',
    'pages',
    'chunks',
    'files',
    'matches',
    'conversations',
    'alerts',
    'reminders',
    'tasks',
    'sessions',
    'logs',
    'events',
    'jobs',
    'outputs',
)

GENERIC_FOLLOWUP_SCALAR_KEYS = (
    'id',
    'key',
    'name',
    'title',
    'subject',
    'status',
    'action',
    'source',
    'severity',
    'category',
    'type',
    'url',
    'top_url',
    'link',
    'href',
    'asin',
    'rating',
    'price',
    'price_total',
    'price_per_night',
    'price_formatted',
    'thumbnail',
    'address',
    'reviews',
    'path',
    'file',
    'filename',
    'file_path',
    'stash_ref',
    'ref',
    'space_id',
    'file_id',
    'page_id',
    'canvas_id',
    'canvas_page_id',
    'alert_id',
    'reminder_id',
    'task_id',
    'schedule_id',
    'job_id',
    'call_id',
    'session_id',
    'conversation_id',
    'message_id',
    'created_at',
    'updated_at',
    'due_at',
    'scheduled_for',
    'next_run',
    'formatted_time',
    'count',
    'total',
    'runs_count',
    'results_count',
    'files_count',
    'matches_count',
)

GENERIC_FOLLOWUP_BULKY_OR_UNSAFE_KEYS = frozenset({
    'content',
    'body',
    'html',
    'markdown',
    'raw',
    'raw_data',
    'raw_html',
    'raw_text',
    'transcript',
    'headers',
    'payload',
    'data',
    'json',
    'full_text',
    'description',
    'summary',
    'text',
    'output',
    'stdout',
    'stderr',
    'command',
})

GENERIC_FOLLOWUP_SENSITIVE_KEY_PARTS = (
    'api_key',
    'authorization',
    'bearer',
    'cookie',
    'password',
    'secret',
    'token',
)

GENERIC_FOLLOWUP_STRING_MAX_CHARS = 300
GENERIC_FOLLOWUP_URL_MAX_CHARS = 2048
GENERIC_FOLLOWUP_URLISH_KEYS = frozenset({
    'url',
    'top_url',
    'thumbnail',
    'link',
    'href',
})

FOLLOWUP_DATA_SKIP_KEYS = frozenset({
    'usage',
    'raw_llm_response',
    'vision_analysis',
    '_error',
    '_effective_evidence',
    '_web_message_id',
    '_completion_guard',
    'speech',
    'server_side_tools',
    'experience_id',
    '_tool_trace',
    'provider_continuation',
    '_provider_continuation',
})

# @TOOL_CONFIG: follow-up data extraction — fields extracted from tool results for LLM context
FOLLOWUP_FIELDS: dict[str, list[str]] = {
    # --- Media generation ---
    'generate_video': ['provider', 'model', 'duration', 'aspect_ratio', 'resolution',
                       'video_id', 'video_url', 'generated_from', 'source_image'],
    'generate_image': [
        'provider', 'model', 'aspect_ratio', 'image_size', 'size', 'quality',
        'style', 'is_edit', 'mime_type', 'filename',
    ],
    'generate_music': ['provider', 'model', 'duration'],
    # --- File/artifact producers ---
    'pdf_create': ['ref', 'name', 'size_bytes'],
    'pdf_read': ['page_count', 'stash_ref'],
    'convert_file': ['stash_ref', 'filename', 'source_format', 'target_format'],
    'qr_code_generator': ['stash_ref', 'filename'],
    'upload_cloudflare': ['url', 'image_id', 'filename'],
    'youtube_transcript': ['video_title', 'srt_stash_ref', 'md_stash_ref'],
    'youtube_video': ['video_title', 'stash_ref', 'filename', 'duration_seconds', 'channel'],
    'serpapi_youtube': ['video_id', 'url', 'title', 'channel', 'duration', 'published_date', 'transcript_api_url'],
    'serpapi_youtube_search': ['search_query', 'top_url', 'title'],
    'serpapi_yelp_search': ['find_desc', 'find_loc', 'top_url', 'place_id'],
    'git_release_notes': ['release_tag', 'release_url', 'stash_ref', 'canvas_page_id', 'repo', 'owner'],
    'release_watch': [
        'watch_id', 'source', 'project', 'initialized', 'changed',
        'regression_detected', 'previous_version', 'current_version',
        'normalized_version', 'release_url', 'published_at', 'checked_at',
        'acknowledged', 'version', 'alert_title', 'alert_severity',
        'alert_dedupe_key',
    ],
    'memory_deduper': ['stash_ref', 'canvas_page_id'],
    'stash': ['space_id', 'file_id', 'name', 'mime_type', 'size_bytes'],
    'screenshot_url': ['url', 'screenshot_path'],
    # --- Knowledge/session refs ---
    'canvas': ['page_id', 'title'],
    'crypto_price': [
        'coin', 'coin_id', 'price_usd', 'change_24h_percent',
        'market_cap_usd', 'source',
    ],
    'crypto_chart': [
        'coin', 'coin_id', 'vs_currency', 'days', 'range_label',
        'current_price', 'change_percent', 'points_returned', 'original_points', 'source',
    ],
    'opencode': ['session_id'],
    # --- Entity references (for modify/repeat/cancel follow-ups) ---
    'remember': ['memory_id', 'key', 'category'],
    'search_memory': ['count', 'by_category'],
    'semantic_recall': ['count'],
    'update_memory': ['memory_id', 'old_value', 'new_value'],
    'forget': ['deleted_id', 'deleted_key', 'deleted_ids', 'deleted_keys', 'missing_ids'],
    'create_reminder': ['reminder_id', 'formatted_time'],
    'send_email': ['to', 'subject', 'status'],
    'api_call': ['url', 'method', 'status_code'],
    'serpapi_search': ['engine', 'query', 'asin', 'results_count', 'top_url'],
    'serpapi_home_depot': ['engine', 'query', 'country', 'product_id', 'results_count', 'top_url', 'top_image_url'],
    'serpapi_ebay_search': ['engine', 'query', 'category_id', 'ebay_domain', 'product_id', 'results_count', 'top_url'],
    'serpapi_ebay_product': ['engine', 'product_id', 'ebay_domain', 'results_count', 'top_url', 'top_image_url'],
    'serpapi_maps_search': ['engine', 'query', 'results_count'],
    'serpapi_hotel_search': ['engine', 'query', 'destination', 'check_in_date', 'check_out_date', 'results_count'],
    'spotify': ['name', 'artist'],
    'docker_control': ['container', 'status'],
    'ssh_remote': ['host'],
    'status_recap': ['stash_ref', 'canvas_id'],
    'brave_llm_context': ['query'],
    'supa_crawl_knowledge': [
        'action', 'query', 'site_id', 'page_id', 'base_url', 'count',
        'returned', 'sites', 'site_name', 'threshold', 'dedupe',
    ],
}


def workflow_result_payload(data: dict) -> dict | None:
    """Return either an explicit-slash or autonomous nested workflow payload."""
    if not isinstance(data, dict):
        return None
    nested = data.get('workflow')
    nested_runs = nested if isinstance(nested, list) else [nested]
    for candidate in reversed(nested_runs):
        if (
            isinstance(candidate, dict)
            and candidate.get('action') == 'run'
            and isinstance(candidate.get('results'), list)
        ):
            return candidate
    if data.get('workflow_id') and isinstance(data.get('results'), list):
        return data
    return None


def workflow_step_tool_results(workflow_data: dict) -> dict:
    """Flatten workflow step envelopes into tool-name-keyed result payloads."""
    if not isinstance(workflow_data, dict):
        return {}

    flattened: dict = {}

    def add(tool_name, payload):
        name = str(tool_name or '').strip()
        if not name or name == 'unknown' or payload in (None, ''):
            return
        if name not in flattened:
            flattened[name] = payload
            return
        existing = flattened[name]
        if not isinstance(existing, list):
            flattened[name] = [existing]
        flattened[name].append(payload)

    for step in workflow_data.get('results') or []:
        if not isinstance(step, dict):
            continue
        tool_name = step.get('tool')
        outputs = step.get('outputs')
        if isinstance(outputs, list) and outputs:
            for output in outputs:
                if isinstance(output, dict):
                    payload = output.get('data') if isinstance(output.get('data'), dict) else output
                else:
                    payload = output
                add(tool_name, payload)
            continue

        payload = step.get('data')
        if payload in (None, '', {}):
            error = step.get('error') or step.get('speech')
            if error:
                payload = {'error': str(error)[:500]}
        add(tool_name, payload)

    return flattened


def _compact_memory_candidate(item: dict) -> dict:
    """Keep only the fields needed for follow-up memory actions."""
    candidate = {}
    for field in (
        'id', 'key', 'value', 'category', 'importance',
        'similarity', 'relevance',
    ):
        value = item.get(field)
        if value not in (None, '', [], {}):
            candidate[field] = value
    return candidate


def _extract_memory_candidates(payload: dict, max_candidates: int) -> dict:
    """Extract compact memory refs from tools that return memories."""
    memories = payload.get('memories')
    if not isinstance(memories, list) or not memories:
        return {}

    candidates = []
    for item in memories[:max_candidates]:
        if not isinstance(item, dict):
            continue
        candidate = _compact_memory_candidate(item)
        if candidate:
            candidates.append(candidate)

    if not candidates:
        return {}

    extracted = {
        'memory_count': payload.get('count', len(memories)),
        'candidates': candidates,
    }

    first = candidates[0]
    for field in ('id', 'key', 'value', 'category'):
        if first.get(field) not in (None, '', [], {}):
            extracted[field] = first[field]

    return extracted


def _extract_memory_mutation_refs(payload: dict, max_candidates: int) -> dict:
    """Extract compact refs from tools that changed or deleted memories."""
    extracted = {}

    if payload.get('deleted_id') is not None:
        extracted['deleted_id'] = payload['deleted_id']
    if payload.get('deleted_key'):
        extracted['deleted_key'] = payload['deleted_key']
    if payload.get('deleted_ids'):
        extracted['deleted_ids'] = payload['deleted_ids']
    if payload.get('deleted_keys'):
        extracted['deleted_keys'] = payload['deleted_keys']
    if payload.get('missing_ids'):
        extracted['missing_ids'] = payload['missing_ids']

    deleted = payload.get('deleted')
    if isinstance(deleted, list) and deleted:
        deleted_candidates = []
        for item in deleted[:max_candidates]:
            if not isinstance(item, dict):
                continue
            candidate = {}
            for field in ('id', 'key'):
                value = item.get(field)
                if value not in (None, '', [], {}):
                    candidate[field] = value
            if candidate:
                deleted_candidates.append(candidate)
        if deleted_candidates:
            extracted['deleted'] = deleted_candidates

    return extracted


def _safe_generic_key(key: str) -> bool:
    lowered = (key or '').lower()
    if lowered in GENERIC_FOLLOWUP_BULKY_OR_UNSAFE_KEYS:
        return False
    return not any(part in lowered for part in GENERIC_FOLLOWUP_SENSITIVE_KEY_PARTS)


def _is_generic_scalar(value) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _is_generic_urlish_key(key: str) -> bool:
    return key.endswith(('_url', '_uri')) or key in GENERIC_FOLLOWUP_URLISH_KEYS


def _compact_generic_scalar(key: str, value):
    if value in (None, '', [], {}):
        return None
    if not _is_generic_scalar(value):
        return None
    if isinstance(value, str):
        limit = (
            GENERIC_FOLLOWUP_URL_MAX_CHARS
            if _is_generic_urlish_key(key)
            else GENERIC_FOLLOWUP_STRING_MAX_CHARS
        )
        if len(value) > limit:
            suffix = '... [truncated]'
            value = value[: max(0, limit - len(suffix))].rstrip() + suffix
    return value


def _generic_candidate_from_item(item: dict) -> dict:
    candidate = {}
    for field in GENERIC_FOLLOWUP_SCALAR_KEYS:
        if field not in item or not _safe_generic_key(field):
            continue
        value = _compact_generic_scalar(field, item.get(field))
        if value not in (None, '', [], {}):
            candidate[field] = value

    for field, value in item.items():
        if (
            field in candidate
            or not field.endswith(('_id', '_ref', '_url', '_uri'))
            or not _safe_generic_key(field)
        ):
            continue
        compact = _compact_generic_scalar(field, value)
        if compact not in (None, '', [], {}):
            candidate[field] = compact

    return candidate


def _generic_item_identity(item: dict):
    for field in (
        'url',
        'top_url',
        'place_id',
        'data_id',
        'asin',
        'product_id',
        'video_id',
        'id',
        'title',
        'name',
    ):
        value = item.get(field)
        if value not in (None, '', [], {}):
            return field, str(value)
    return None


def _collapse_repeated_tool_runs(runs: list[dict]) -> dict | None:
    """Flatten repeated tool-call run envelopes into their nested result rows."""
    if not runs or not all(isinstance(run, dict) for run in runs):
        return None

    rows = []
    seen = set()
    runs_with_rows = 0
    collapsed = {}

    for run in runs:
        payload = run.get('data') if isinstance(run.get('data'), dict) else run
        if not isinstance(payload, dict):
            continue

        nested = None
        for list_key in GENERIC_FOLLOWUP_LIST_KEYS:
            candidate_list = payload.get(list_key)
            if (
                isinstance(candidate_list, list)
                and any(isinstance(item, dict) for item in candidate_list)
            ):
                nested = candidate_list
                break
        if nested is None:
            continue

        runs_with_rows += 1
        for field, value in payload.items():
            if field in GENERIC_FOLLOWUP_LIST_KEYS or not _safe_generic_key(field):
                continue
            compact = _compact_generic_scalar(field, value)
            if compact not in (None, '', [], {}):
                collapsed[field] = compact

        for item in nested:
            if not isinstance(item, dict):
                continue
            identity = _generic_item_identity(item)
            if identity is not None:
                if identity in seen:
                    continue
                seen.add(identity)
            rows.append(item)

    if not rows:
        return None

    collapsed['results'] = rows
    collapsed['results_count'] = len(rows)
    collapsed['runs_count'] = runs_with_rows
    return collapsed


def _generic_list_count(payload: dict, list_key: str, results: list) -> int:
    list_count_key = f'{list_key}_count'
    if isinstance(payload.get(list_count_key), (int, float)):
        return payload[list_count_key]
    if list_key == 'results' and isinstance(payload.get('results_count'), (int, float)):
        return payload['results_count']
    if isinstance(payload.get('count'), (int, float)):
        return payload['count']
    return len(results)


def _extract_generic_followup(payload: dict, max_candidates: int) -> dict:
    """Conservative fallback for tools without dedicated follow-up adapters."""
    extracted = {}

    for field in GENERIC_FOLLOWUP_SCALAR_KEYS:
        if field not in payload or not _safe_generic_key(field):
            continue
        value = _compact_generic_scalar(field, payload.get(field))
        if value not in (None, '', [], {}):
            extracted[field] = value

    for field, value in payload.items():
        if (
            field in extracted
            or not field.endswith(('_id', '_ref', '_url', '_uri'))
            or not _safe_generic_key(field)
        ):
            continue
        compact = _compact_generic_scalar(field, value)
        if compact not in (None, '', [], {}):
            extracted[field] = compact

    for list_key in GENERIC_FOLLOWUP_LIST_KEYS:
        results = payload.get(list_key)
        if not isinstance(results, list) or not results:
            continue

        candidates = []
        for item in results[:max_candidates]:
            if not isinstance(item, dict):
                continue
            candidate = _generic_candidate_from_item(item)
            if candidate:
                candidates.append(candidate)

        if not candidates:
            continue

        count_key = f'{list_key}_count'
        extracted[count_key] = _generic_list_count(payload, list_key, results)
        first = candidates[0]
        if first.get('title') and 'title' not in extracted:
            extracted['title'] = first['title']
        if first.get('name') and 'name' not in extracted:
            extracted['name'] = first['name']
        if first.get('url') and 'top_url' not in extracted:
            extracted['top_url'] = first['url']
        # Keep the established generic "candidates" key for compatibility,
        # and record the source list so prompt consumers know what it represents.
        extracted['candidate_source'] = list_key
        extracted['candidates'] = candidates
        break

    return extracted


def truncate_followup_summary(summary: str, max_chars: int = FOLLOWUP_SUMMARY_MAX_CHARS) -> str:
    """Trim stored summaries to a stable prompt-sized excerpt."""
    if not isinstance(summary, str):
        return ''
    summary = summary.strip()
    if len(summary) <= max_chars:
        return summary
    suffix_budget = len(_FOLLOWUP_TRUNCATION_SUFFIX)
    if max_chars <= suffix_budget:
        return summary[:max_chars].rstrip()
    return summary[:max_chars - suffix_budget].rstrip() + _FOLLOWUP_TRUNCATION_SUFFIX


def compact_text_summarizer_item(item) -> dict | None:
    """Compact one text_summarizer result for history/evidence storage."""
    if not isinstance(item, dict):
        return None

    summary = item.get('summary')
    if not isinstance(summary, str) or not summary.strip():
        return None

    extracted = {
        'summary': truncate_followup_summary(summary),
    }

    source = item.get('source') if isinstance(item.get('source'), dict) else {}
    for field in ('stash_ref', 'file_id', 'space_id', 'source', 'characters_loaded'):
        if source.get(field):
            extracted[field] = source[field]

    meta = item.get('summary_meta') if isinstance(item.get('summary_meta'), dict) else {}
    for field in (
        'summary_method',
        'llm_used',
        'llm_provider',
        'llm_model',
        'chunks_used',
        'chunks_total',
        'input_characters',
        'fallback_reason',
    ):
        if field in meta and meta[field] not in (None, ''):
            extracted[field] = meta[field]

    return extracted


def extract_text_summarizer_followup(value, max_candidates: int) -> dict | None:
    """Preserve text_summarizer summaries and source refs for follow-up turns."""
    if isinstance(value, list):
        items = [compact_text_summarizer_item(item) for item in value[:max_candidates]]
        items = [item for item in items if item]
        if not items:
            return None
        latest = items[-1]
        extracted = {
            'results_count': len(value),
            'latest_summary': latest.get('summary'),
            'summaries': items,
        }
        if latest.get('stash_ref'):
            extracted['latest_stash_ref'] = latest['stash_ref']
        return extracted

    if isinstance(value, dict):
        return compact_text_summarizer_item(value)
    return None


def _manage_intel_payloads(value) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _manage_intel_trace_arguments(data: dict) -> list[dict]:
    trace = data.get('_tool_trace')
    if not isinstance(trace, list):
        return []

    args = []
    for entry in trace:
        if not isinstance(entry, dict) or entry.get('tool') != 'manage_intel':
            continue
        if entry.get('ok') is False:
            continue
        entry_args = entry.get('arguments')
        args.append(entry_args if isinstance(entry_args, dict) else {})
    return args


def _safe_intel_file_from_name(file_name: str | None) -> Path | None:
    if not isinstance(file_name, str) or not file_name.strip():
        return None

    name = file_name.strip().lstrip('/')
    if '/' in name or '\\' in name:
        return None
    if name == 'README.md':
        return None

    candidate = (MANAGE_INTEL_DIR / name).resolve()
    root = MANAGE_INTEL_DIR.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if candidate.suffix not in ('.md', '.txt', ''):
        return None
    if candidate.suffix == '':
        candidate = candidate.with_suffix('.md')
    return candidate


def _read_manage_intel_document(file_name: str | None) -> dict | None:
    path = _safe_intel_file_from_name(file_name)
    if not path or not path.exists() or not path.is_file():
        return None

    try:
        content = path.read_text(encoding='utf-8')
    except OSError:
        return None

    return {
        'content': content,
        'size_bytes': len(content),
        'content_sha256': hashlib.sha256(content.encode('utf-8')).hexdigest(),
    }


def _compact_ingest_summary(ingest: dict) -> dict:
    if not isinstance(ingest, dict):
        return {}
    compact = {}
    for field in ('ingested', 'new_files', 'total_facts', 'modes', 'partial', 'failed_modes'):
        if ingest.get(field) not in (None, '', [], {}):
            compact[field] = ingest[field]
    if ingest.get('warning'):
        compact['warning'] = str(ingest['warning'])[:500]
    if ingest.get('error'):
        compact['error'] = str(ingest['error'])[:500]
    return compact


def _manage_intel_document_meta(doc: dict) -> dict:
    return {
        key: value
        for key, value in doc.items()
        if key not in {'content', 'appended_content'} and value not in (None, '', [], {})
    }


def _extract_manage_intel_followup(data: dict, max_candidates: int) -> dict | None:
    payloads = _manage_intel_payloads(data.get('manage_intel'))
    if not payloads:
        return None

    trace_args = _manage_intel_trace_arguments(data)
    operations = []
    documents = []

    for index, payload in enumerate(payloads):
        args = trace_args[index] if index < len(trace_args) else {}
        action = payload.get('action') or args.get('action')
        file_name = payload.get('file') or args.get('path')

        operation = {}
        for field, value in (
            ('action', action),
            ('file', file_name),
            ('size_bytes', payload.get('size_bytes')),
            ('created', payload.get('created')),
            ('updated', payload.get('updated')),
            ('appended', payload.get('appended')),
            ('deleted', payload.get('deleted')),
            ('count', payload.get('count')),
            ('match_count', payload.get('match_count')),
            ('matches_returned', payload.get('matches_returned')),
            ('matches_truncated', payload.get('matches_truncated')),
            ('line_count', payload.get('line_count')),
            ('file_sha256', payload.get('file_sha256')),
        ):
            if value not in (None, '', [], {}):
                operation[field] = value

        ingest = _compact_ingest_summary(payload.get('ingest'))
        if ingest:
            operation['ingest'] = ingest

        if isinstance(payload.get('files'), list):
            operation['files_count'] = payload.get('count', len(payload['files']))
            operation['files'] = [
                {
                    key: item[key]
                    for key in ('path', 'size_bytes', 'modified')
                    if isinstance(item, dict) and item.get(key) not in (None, '', [], {})
                }
                for item in payload['files'][:max_candidates]
                if isinstance(item, dict)
            ]

        if isinstance(payload.get('matches'), list):
            operation['matches'] = payload['matches'][:max_candidates]

        content = payload.get('content')
        content_source = 'tool_result'
        doc_meta = None
        if not isinstance(content, str) and action in {'create', 'read', 'update', 'append'}:
            doc_meta = _read_manage_intel_document(file_name)
            if doc_meta:
                content = doc_meta['content']
                content_source = 'jarvis-intel/current_file'

        if isinstance(content, str):
            doc = {
                'action': action,
                'file': file_name,
                'content': content,
                'content_source': content_source,
                'size_bytes': payload.get('size_bytes', len(content)),
                'content_sha256': (
                    payload.get('file_sha256')
                    or (doc_meta or {}).get('content_sha256')
                    or hashlib.sha256(content.encode('utf-8')).hexdigest()
                ),
            }
            if isinstance(payload.get('appended_content'), str):
                doc['appended_content'] = payload['appended_content']
            documents.append(doc)
            operation['document_available'] = True
            operation['content_source'] = content_source

        if operation:
            operations.append(operation)

    if not operations and not documents:
        return None

    extracted = {
        'operation_count': len(operations),
        'operations': operations,
    }
    if operations:
        latest = operations[-1]
        for field in ('action', 'file', 'size_bytes', 'created', 'updated', 'appended', 'deleted'):
            if latest.get(field) not in (None, '', [], {}):
                extracted[f'latest_{field}'] = latest[field]
    if documents:
        extracted['documents'] = [
            _manage_intel_document_meta(doc)
            for doc in documents[:max_candidates]
        ]
        extracted['latest_document'] = _manage_intel_document_meta(documents[-1])
        extracted['latest_content'] = documents[-1]['content']
        extracted['latest_content_source'] = documents[-1]['content_source']
        if documents[-1].get('appended_content'):
            extracted['latest_appended_content'] = documents[-1]['appended_content']
    return extracted


def extract_followup_data(data: dict, max_candidates: int | None = None) -> dict | None:
    """
    Extract key data from tool results that enables follow-up actions.
    Returns a dict of tool_name -> relevant fields for each tool result.

    This allows the LLM to:
    - Edit/remix videos using stash_ref or video_id
    - Reference previous images for variations
    - Act on created PDFs, converted files, transcripts, canvas pages
    - Continue multi-step workflows across separate API calls

    Mostly extracts identifiers and references. For text_summarizer, also
    preserves the compact structured summary because it may be the durable
    working copy of a much larger stash artifact.

    max_candidates: cap for ranked list tools (default FOLLOWUP_DEFAULT; use
    FOLLOWUP_EVIDENCE_MAX for Completion Guard grounding bundles).
    """
    if max_candidates is None:
        max_candidates = FOLLOWUP_DEFAULT_MAX_CANDIDATES
    followup: dict = {}

    for key, value in data.items():
        if key in FOLLOWUP_DATA_SKIP_KEYS:
            continue
        if key == 'manage_intel':
            extracted = _extract_manage_intel_followup(data, max_candidates)
            if extracted:
                followup[key] = extracted
            continue
        if key == 'text_summarizer':
            extracted = extract_text_summarizer_followup(value, max_candidates)
            if extracted:
                followup[key] = extracted
            continue
        if key == 'workflow':
            workflow_value = workflow_result_payload({'workflow': value})
            if not workflow_value:
                continue
            workflow_meta = {
                field: workflow_value[field]
                for field in (
                    'workflow_id',
                    'workflow_name',
                    'execution',
                    'workflow_started',
                    'workflow_completed',
                    'steps_completed',
                )
                if workflow_value.get(field) not in (None, '', [], {})
            }
            if workflow_meta:
                followup['workflow'] = workflow_meta
            component_results = workflow_step_tool_results(workflow_value)
            for component_name, component_value in component_results.items():
                if isinstance(component_value, list) and component_name != 'text_summarizer':
                    runs = []
                    for run_value in component_value[:max_candidates]:
                        run_followup = extract_followup_data(
                            {component_name: run_value},
                            max_candidates=max_candidates,
                        ) or {}
                        compact_run = run_followup.get(component_name)
                        if isinstance(compact_run, dict) and compact_run:
                            runs.append(compact_run)
                    if runs:
                        combined = dict(runs[-1])
                        combined['runs_count'] = len(component_value)
                        combined['candidates'] = runs
                        followup[component_name] = combined
                    continue
                component_followup = extract_followup_data(
                    {component_name: component_value},
                    max_candidates=max_candidates,
                )
                if component_followup:
                    followup.update(component_followup)
            continue
        # List-shaped tool payloads: normalize to dict with results[] (no per-tool registry).
        if isinstance(value, list):
            if not value:
                continue
            if all(isinstance(x, dict) for x in value):
                if key in _PRESERVE_RUN_LIST_FOR_DEDICATED_BRANCHES:
                    value = {'results': value}
                else:
                    value = _collapse_repeated_tool_runs(value) or {'results': value}
            else:
                continue
        if not isinstance(value, dict):
            continue

        payload = value.get('data') if isinstance(value.get('data'), dict) else value
        # Auto-stashed web uploads are also stored under top-level "stash".
        # Keep skipping those lightweight upload refs here, but preserve actual
        # stash tool outputs so later follow-up turns can reference them.
        if key == 'stash' and value.get('stash_ref') and not any(
            marker in value for marker in ('ref', 'content', 'mime_type', 'size_bytes', 'name')
        ):
            continue
        if key == 'stash' and value.get('stash_ref') and value.get('tool_origin') == 'web_upload':
            continue

        extracted = {}

        # Extract stash_ref from nested 'saved' object (common pattern)
        if 'saved' in value and isinstance(value['saved'], dict):
            saved = value['saved']
            if saved.get('stash_ref'):
                extracted['stash_ref'] = saved['stash_ref']
            if saved.get('filename'):
                extracted['filename'] = saved['filename']

        # Direct stash_ref on the object
        if value.get('stash_ref'):
            extracted['stash_ref'] = value['stash_ref']

        # Some tools use 'ref' instead of 'stash_ref' (e.g. pdf_create, stash)
        # Include it as-is so the LLM sees the actual field name the tool uses
        if value.get('ref') and 'stash_ref' not in extracted:
            extracted['ref'] = value['ref']

        # Get tool-specific fields
        fields_to_extract = FOLLOWUP_FIELDS.get(key, [])
        for field in fields_to_extract:
            if field in extracted:
                continue  # Already got it above
            field_value = payload.get(field)
            if field_value:
                extracted[field] = field_value
            elif key == 'release_watch' and isinstance(field_value, bool):
                # False is meaningful for change detection and first-run state.
                extracted[field] = field_value

        if payload.get('runs_count') and 'runs_count' not in extracted:
            extracted['runs_count'] = payload['runs_count']

        # Always include provider if present (needed for follow-ups)
        if payload.get('provider') and 'provider' not in extracted:
            extracted['provider'] = payload['provider']

        # Preserve compact memory refs for follow-up turns like
        # "forget those", "update that birthday memory", or "show me the other one".
        extracted.update(_extract_memory_candidates(payload, max_candidates))
        extracted.update(_extract_memory_mutation_refs(payload, max_candidates))

        if key == 'crypto_chart':
            series = payload.get('series') if isinstance(payload.get('series'), dict) else {}
            prices = series.get('prices') if isinstance(series.get('prices'), list) else []
            if prices:
                first = prices[0] if isinstance(prices[0], dict) else {}
                last = prices[-1] if isinstance(prices[-1], dict) else {}
                if first.get('iso'):
                    extracted['start_iso'] = first['iso']
                if first.get('value') is not None:
                    extracted['start_price'] = first['value']
                if last.get('iso'):
                    extracted['end_iso'] = last['iso']
                if last.get('value') is not None:
                    extracted['end_price'] = last['value']

        if key == 'crypto_price':
            coins = payload.get('coins') if isinstance(payload.get('coins'), list) else []
            if coins:
                extracted['count'] = payload.get('count', len(coins))
                first = coins[0] if isinstance(coins[0], dict) else {}
                if isinstance(first, dict):
                    for field in (
                        'requested', 'coin', 'coin_id', 'price_usd',
                        'change_24h_percent', 'market_cap_usd',
                    ):
                        value = first.get(field)
                        if value not in (None, '', [], {}):
                            extracted[field] = value

                candidates = []
                for item in coins[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    candidate = {}
                    for field in (
                        'requested', 'coin', 'coin_id', 'price_usd',
                        'change_24h_percent', 'market_cap_usd',
                    ):
                        value = item.get(field)
                        if value not in (None, '', [], {}):
                            candidate[field] = value
                    if candidate:
                        candidates.append(candidate)

                if candidates:
                    extracted['candidates'] = candidates

                if payload.get('missing_coins'):
                    extracted['missing_coins'] = payload['missing_coins']

        # Preserve compact focused product details for shopping follow-ups.
        if key == 'serpapi_search':
            results = value.get('results') or value.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = value.get('results_count', len(results))
                first = results[0] if isinstance(results[0], dict) else {}
                if isinstance(first, dict):
                    if first.get('title'):
                        extracted['title'] = first['title']
                    if first.get('url') and 'top_url' not in extracted:
                        extracted['top_url'] = first['url']
                    if first.get('thumbnail'):
                        extracted['thumbnail'] = first['thumbnail']
                    if first.get('price'):
                        extracted['price'] = first['price']
                    if first.get('rating'):
                        extracted['rating'] = first['rating']
                    if first.get('reviews'):
                        extracted['reviews'] = first['reviews']
                # Preserve a compact shortlist so follow-ups like
                # "tell me more about the Aura frame" can resolve against
                # prior candidates instead of guessing a new ASIN.
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    title = item.get('title')
                    asin = item.get('asin')
                    url = item.get('url')
                    if not (title or asin or url):
                        continue
                    candidate = {}
                    if title:
                        candidate['title'] = title
                    if asin:
                        candidate['asin'] = asin
                    if url:
                        candidate['url'] = url
                    if item.get('price'):
                        candidate['price'] = item['price']
                    if item.get('rating'):
                        candidate['rating'] = item['rating']
                    if item.get('reviews'):
                        candidate['reviews'] = item['reviews']
                    if item.get('thumbnail'):
                        candidate['thumbnail'] = item['thumbnail']
                    candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

        if key == 'serpapi_home_depot':
            results = value.get('results') or value.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = value.get('results_count', len(results))
                first = results[0] if isinstance(results[0], dict) else {}
                if isinstance(first, dict):
                    if first.get('title'):
                        extracted['title'] = first['title']
                    if first.get('url') and 'top_url' not in extracted:
                        extracted['top_url'] = first['url']
                    if first.get('product_id') and 'product_id' not in extracted:
                        extracted['product_id'] = first['product_id']
                    if first.get('brand'):
                        extracted['brand'] = first['brand']
                    if first.get('model_number'):
                        extracted['model_number'] = first['model_number']
                    if first.get('price_formatted'):
                        extracted['price'] = first['price_formatted']
                    elif first.get('price') is not None:
                        extracted['price'] = first['price']
                    if first.get('rating'):
                        extracted['rating'] = first['rating']
                    if first.get('reviews'):
                        extracted['reviews'] = first['reviews']
                    if first.get('thumbnail'):
                        extracted['thumbnail'] = first['thumbnail']
                    if first.get('image_url'):
                        extracted['image_url'] = first['image_url']
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    title = item.get('title')
                    url = item.get('url')
                    product_id = item.get('product_id')
                    if not (title or url or product_id):
                        continue
                    candidate = {}
                    if title:
                        candidate['title'] = title
                    if url:
                        candidate['url'] = url
                    if product_id:
                        candidate['product_id'] = product_id
                    if item.get('brand'):
                        candidate['brand'] = item['brand']
                    if item.get('model_number'):
                        candidate['model_number'] = item['model_number']
                    if item.get('price_formatted'):
                        candidate['price'] = item['price_formatted']
                    elif item.get('price') is not None:
                        candidate['price'] = item['price']
                    if item.get('rating'):
                        candidate['rating'] = item['rating']
                    if item.get('reviews'):
                        candidate['reviews'] = item['reviews']
                    if item.get('thumbnail'):
                        candidate['thumbnail'] = item['thumbnail']
                    if item.get('image_url'):
                        candidate['image_url'] = item['image_url']
                    candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

        if key == 'serpapi_ebay_search':
            results = value.get('results') or value.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = value.get('results_count', len(results))
                first = results[0] if isinstance(results[0], dict) else {}
                if isinstance(first, dict):
                    if first.get('title'):
                        extracted['title'] = first['title']
                    if first.get('url') and 'top_url' not in extracted:
                        extracted['top_url'] = first['url']
                    if first.get('product_id') and 'product_id' not in extracted:
                        extracted['product_id'] = first['product_id']
                    price = first.get('price')
                    if isinstance(price, dict) and price.get('raw') and 'price' not in extracted:
                        extracted['price'] = price['raw']
                    elif isinstance(price, dict) and price.get('extracted') is not None:
                        extracted['price'] = price['extracted']
                    if first.get('condition'):
                        extracted['condition'] = first['condition']
                    if first.get('thumbnail'):
                        extracted['thumbnail'] = first['thumbnail']
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    title = item.get('title')
                    url = item.get('url')
                    pid = item.get('product_id')
                    if not (title or url or pid):
                        continue
                    candidate = {}
                    if title:
                        candidate['title'] = title
                    if url:
                        candidate['url'] = url
                    if pid:
                        candidate['product_id'] = pid
                    price = item.get('price')
                    if isinstance(price, dict) and price.get('raw'):
                        candidate['price'] = price['raw']
                    elif isinstance(price, dict) and price.get('extracted') is not None:
                        candidate['price'] = price['extracted']
                    if item.get('condition'):
                        candidate['condition'] = item['condition']
                    if item.get('thumbnail'):
                        candidate['thumbnail'] = item['thumbnail']
                    candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

        if key == 'serpapi_ebay_product':
            results = value.get('results') or value.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = value.get('results_count', len(results))
                first = results[0] if isinstance(results[0], dict) else {}
                if isinstance(first, dict):
                    if first.get('title'):
                        extracted['title'] = first['title']
                    if first.get('url') and 'top_url' not in extracted:
                        extracted['top_url'] = first['url']
                    if first.get('product_id') and 'product_id' not in extracted:
                        extracted['product_id'] = first['product_id']
                    if first.get('thumbnail'):
                        extracted['thumbnail'] = first['thumbnail']
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    title = item.get('title')
                    url = item.get('url')
                    pid = item.get('product_id')
                    if not (title or url or pid):
                        continue
                    candidate = {}
                    if title:
                        candidate['title'] = title
                    if url:
                        candidate['url'] = url
                    if pid:
                        candidate['product_id'] = pid
                    if item.get('thumbnail'):
                        candidate['thumbnail'] = item['thumbnail']
                    candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

        if key == 'serpapi_youtube_search':
            results = value.get('results') or value.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = value.get('results_count', len(results))
                first = results[0] if isinstance(results[0], dict) else {}
                if isinstance(first, dict):
                    if first.get('title'):
                        extracted['title'] = first['title']
                    if first.get('url') and 'top_url' not in extracted:
                        extracted['top_url'] = first['url']
                    if first.get('thumbnail'):
                        extracted['thumbnail'] = first['thumbnail']
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    title = item.get('title')
                    url = item.get('url')
                    video_id = item.get('video_id')
                    if not (title or url or video_id):
                        continue
                    candidate = {}
                    if title:
                        candidate['title'] = title
                    if url:
                        candidate['url'] = url
                    if video_id:
                        candidate['video_id'] = video_id
                    if item.get('channel'):
                        candidate['channel'] = item['channel']
                    if item.get('duration'):
                        candidate['duration'] = item['duration']
                    if item.get('thumbnail'):
                        candidate['thumbnail'] = item['thumbnail']
                    candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

        if key == 'serpapi_yelp_search':
            results = value.get('results') or value.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = value.get('results_count', len(results))
                first = results[0] if isinstance(results[0], dict) else {}
                if isinstance(first, dict):
                    if first.get('title'):
                        extracted['title'] = first['title']
                    if first.get('url') and 'top_url' not in extracted:
                        extracted['top_url'] = first['url']
                    if first.get('place_id') and 'place_id' not in extracted:
                        extracted['place_id'] = first['place_id']
                    if first.get('rating'):
                        extracted['rating'] = first['rating']
                    if first.get('price'):
                        extracted['price'] = first['price']
                    if first.get('address'):
                        extracted['address'] = first['address']
                    if first.get('thumbnail'):
                        extracted['thumbnail'] = first['thumbnail']
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    title = item.get('title')
                    url = item.get('url')
                    place_id = item.get('place_id')
                    if not (title or url or place_id):
                        continue
                    candidate = {}
                    if title:
                        candidate['title'] = title
                    if url:
                        candidate['url'] = url
                    if place_id:
                        candidate['place_id'] = place_id
                    if item.get('rating'):
                        candidate['rating'] = item['rating']
                    if item.get('price'):
                        candidate['price'] = item['price']
                    if item.get('address'):
                        candidate['address'] = item['address']
                    if item.get('thumbnail'):
                        candidate['thumbnail'] = item['thumbnail']
                    candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

        # --- crawl_url: nested list of runs, each with results[{url, title, success}] ---
        # Preserve the list of crawled URLs so follow-up turns don't re-crawl the same pages.
        # Skip the raw markdown content (too large) — URL + success is enough context.
        if key == 'crawl_url':
            runs = value.get('results') or []
            if isinstance(runs, list) and runs:
                crawled = []
                seen_urls: set[str] = set()
                for run in runs:
                    if not isinstance(run, dict):
                        continue
                    inner = run.get('results') or []
                    if not isinstance(inner, list):
                        continue
                    for item in inner:
                        if not isinstance(item, dict):
                            continue
                        url = item.get('url')
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)
                        record = {'url': url}
                        if item.get('title'):
                            record['title'] = item['title']
                        if 'success' in item:
                            record['success'] = bool(item['success'])
                        crawled.append(record)
                        if len(crawled) >= max_candidates * 2:
                            break
                    if len(crawled) >= max_candidates * 2:
                        break
                if crawled:
                    extracted['runs_count'] = len(runs)
                    extracted['crawled_urls'] = crawled

        # --- Brave MCP search tools: list of runs, each with raw[] + full_text ---
        # Extract URLs from full_text via regex (fastest, shape-agnostic) so
        # follow-up turns know which URLs already appeared in prior searches
        # without carrying multi-KB snippets forward.
        if key in (
            'mcp_brave_search_brave_web_search',
            'mcp_brave_search_brave_news_search',
            'mcp_brave_search_brave_local_search',
        ):
            runs = value.get('results') or []
            if isinstance(runs, list) and runs:
                urls_seen: list[str] = []
                seen_set: set[str] = set()
                max_urls = max_candidates * 2
                for run in runs:
                    if not isinstance(run, dict):
                        continue
                    texts = []
                    full_text = run.get('full_text', '')
                    if isinstance(full_text, str) and full_text:
                        texts.append(full_text)
                    raw = run.get('raw')
                    if isinstance(raw, list):
                        for part in raw:
                            if isinstance(part, dict) and isinstance(part.get('text'), str):
                                texts.append(part['text'])
                    for text in texts:
                        for match in _BRAVE_URL_RE.findall(text):
                            match = match.rstrip(').,;')
                            if match in seen_set:
                                continue
                            seen_set.add(match)
                            urls_seen.append(match)
                            if len(urls_seen) >= max_urls:
                                break
                        if len(urls_seen) >= max_urls:
                            break
                    if len(urls_seen) >= max_urls:
                        break
                extracted['runs_count'] = len(runs)
                if urls_seen:
                    extracted['urls_seen'] = urls_seen

        if key == 'brave_llm_context':
            grounding = value.get('grounding') if isinstance(value.get('grounding'), dict) else {}
            sources_meta = value.get('sources') if isinstance(value.get('sources'), dict) else {}
            sources = []
            seen_urls: set[str] = set()
            source_limit = max(max_candidates, 8)

            def add_source(item):
                if not isinstance(item, dict):
                    return
                url = item.get('url')
                title = item.get('title') or item.get('name')
                if not (url or title):
                    return
                if url and url in seen_urls:
                    return
                if url:
                    seen_urls.add(url)
                record = {}
                if title:
                    record['title'] = title
                if url:
                    record['url'] = url
                if item.get('site_name'):
                    record['site_name'] = item['site_name']
                elif url:
                    meta = sources_meta.get(url)
                    if isinstance(meta, dict) and meta.get('site_name'):
                        record['site_name'] = meta['site_name']
                age = item.get('age')
                if not age and url:
                    meta = sources_meta.get(url)
                    if isinstance(meta, dict):
                        age = meta.get('age')
                if isinstance(age, list) and age:
                    record['age'] = str(age[0])[:120]
                elif isinstance(age, str) and age.strip():
                    record['age'] = age.strip()[:120]
                snippets = item.get('snippets')
                if isinstance(snippets, list) and snippets:
                    record['snippet'] = str(snippets[0])[:500]
                sources.append(record)

            for item in grounding.get('generic') or []:
                add_source(item)
                if len(sources) >= source_limit:
                    break
            if len(sources) < source_limit:
                add_source(grounding.get('poi'))
            if len(sources) < source_limit:
                for item in grounding.get('map') or []:
                    add_source(item)
                    if len(sources) >= source_limit:
                        break
            if sources:
                extracted['sources_count'] = len(sources)
                extracted['sources'] = sources

        # Generic handle/candidate fallback for tools without explicit branches above.
        # This is intentionally conservative: preserve IDs, refs, URLs, titles,
        # statuses, and small candidate lists, but do not carry bulky text bodies.
        if (
            not extracted.get('candidates')
            and key not in _DEDICATED_FOLLOWUP_BRANCHES
        ):
            generic = _extract_generic_followup(payload, max_candidates)
            for field, value in generic.items():
                if field not in extracted:
                    extracted[field] = value

        # @TOOL_CONFIG: video URL expiration — provider URLs have time limits
        # xAI ~4h, OpenAI 60min
        if key == 'generate_video' and extracted.get('video_url'):
            try:
                saved = value.get('saved', {})
                created_str = saved.get('source_url_created', '')
                if created_str:
                    created_dt = datetime.fromisoformat(created_str)
                    age_hours = (datetime.now() - created_dt).total_seconds() / 3600
                    if age_hours > 4:
                        extracted['video_url'] = '(expired)'
            except Exception:
                pass

        if extracted:
            followup[key] = extracted

    # Also extract top-level upload stash info (from image uploads)
    if (
        data.get('stash')
        and isinstance(data['stash'], dict)
        and data['stash'].get('stash_ref')
        and (
            data['stash'].get('tool_origin') == 'web_upload'
            or not any(marker in data['stash'] for marker in ('ref', 'content', 'mime_type', 'size_bytes', 'name'))
        )
    ):
        stash = data['stash']
        uploaded_images = []
        if isinstance(stash.get('uploaded_images'), list):
            for item in stash['uploaded_images']:
                if not isinstance(item, dict) or not item.get('stash_ref'):
                    continue
                uploaded_images.append({
                    'stash_ref': item.get('stash_ref'),
                    'space_id': item.get('space_id'),
                    'file_id': item.get('file_id'),
                    'filename': item.get('filename'),
                    'source_filename': item.get('source_filename'),
                    'mime_type': item.get('mime_type'),
                    'action': item.get('action'),
                    'tool_origin': item.get('tool_origin'),
                    'ordinal': item.get('ordinal'),
                    'batch_id': item.get('batch_id'),
                    'batch_index': item.get('batch_index'),
                    'batch_total': item.get('batch_total'),
                    'batch_label': item.get('batch_label'),
                    'vision_analysis_scope': item.get('vision_analysis_scope'),
                    'has_vision_analysis': bool(item.get('has_vision_analysis')),
                })
                if item.get('vision_analysis'):
                    uploaded_images[-1]['vision_analysis'] = item.get('vision_analysis')

        followup['uploaded_image'] = {
            'stash_ref': stash.get('stash_ref'),
            'space_id': stash.get('space_id'),
            'file_id': stash.get('file_id'),
            'filename': stash.get('filename'),
            'mime_type': stash.get('mime_type'),
            'action': stash.get('action'),
            'tool_origin': stash.get('tool_origin'),
            'has_vision_analysis': bool(stash.get('has_vision_analysis')),
        }
        if stash.get('vision_analysis'):
            followup['uploaded_image']['vision_analysis'] = stash.get('vision_analysis')
        if uploaded_images:
            followup['uploaded_images'] = uploaded_images

    # Extract error details (enables "what went wrong?" follow-ups)
    if data.get('_error') and isinstance(data['_error'], dict):
        err = data['_error']
        error_info = {
            'tool_failed': err.get('tool_failed'),
            'message': err.get('message', '')[:500],
            'retries': err.get('retries', 0),
        }
        # Include tool arguments so LLM can see what was passed when it failed
        if err.get('tool_args'):
            error_info['tool_args'] = err['tool_args']
        followup['error'] = error_info

    return followup if followup else None
