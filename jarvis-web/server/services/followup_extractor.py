"""Follow-up data extraction for stored conversation turns.

Extracted from jarvis-web/server/sockets/chat.py to keep the socket handler
focused on request lifecycle. These functions are pure (no ChatHandler state)
and reduce a tool's raw result payload to a compact identifier/reference
bundle that can be replayed cheaply into subsequent router prompts.

Used in two places:
- Conversation history context (compact, FOLLOWUP_DEFAULT_MAX_CANDIDATES)
- Completion Guard effective evidence (richer, FOLLOWUP_EVIDENCE_MAX_CANDIDATES)
"""
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path

# URL extractor for text-oriented MCP results whose content is buried inside
# raw[].text JSON blobs and full_text.
_MCP_URL_RE = re.compile(r'https?://[^\s"\'<>)]+')
_DUCKDUCKGO_RESULT_RE = re.compile(
    r'(?ms)^\s*\d+\.\s+(?P<title>[^\r\n]+)\r?\n'
    r'\s*URL:\s*(?P<url>\S+)\r?\n'
    r'\s*Summary:\s*(?P<snippet>.*?)(?=^\s*\d+\.\s+|\Z)'
)
_DUCKDUCKGO_RESULT_COUNT_RE = re.compile(r'Found\s+(\d+)\s+search results?:', re.IGNORECASE)
_MCP_FETCH_CONTENT_INFO_RE = re.compile(
    r'\[Content info:\s*Showing characters\s+(\d+)-(\d+)\s+of\s+(\d+)\s+total',
    re.IGNORECASE,
)

# Tools whose follow-up shape is handled by a dedicated branch below. Listed
# here so the generic results[]/items[] fallback skips them (otherwise it
# would overwrite or duplicate what the dedicated branch produced).
_AMAZON_FOLLOWUP_TOOL_NAMES = frozenset({
    'serpapi_amazon_search',
    'serpapi_search',  # Read-only compatibility for saved pre-rename turns.
})
_DEDICATED_FOLLOWUP_BRANCHES = (
    'serpapi_amazon_search',
    'serpapi_search',
    'serpapi_home_depot',
    'serpapi_ebay_search',
    'serpapi_ebay_product',
    'serpapi_youtube_search',
    'serpapi_yelp_search',
    'serpapi_search_index',
    'serpapi_google_local',
    'serpapi_google_local_services',
    'serpapi_google_images_light',
    'serpapi_google_news_light',
    'serpapi_google_shopping_light',
    'serpapi_google_sports',
    'serpapi_google_trends',
    'serpapi_google_trending_now',
    'serpapi_travel_explore',
    'serpapi_tripadvisor',
    'trakt_movies',
    'trakt_tv_shows',
    'tmdb_movies',
    'tmdb_tv_shows',
    'flight_search',
    'crawl_url',
    'mcp_brave_search_brave_web_search',
    'mcp_brave_search_brave_news_search',
    'mcp_brave_search_brave_local_search',
    'mcp_duckduckgo_search',
    'mcp_duckduckgo_fetch_content',
    'mcp_fetch_fetch',
    'brave_llm_context',
)

_PRESERVE_RUN_LIST_FOR_DEDICATED_BRANCHES = frozenset({
    'crawl_url',
    'mcp_brave_search_brave_web_search',
    'mcp_brave_search_brave_news_search',
    'mcp_brave_search_brave_local_search',
    'mcp_duckduckgo_search',
    'mcp_duckduckgo_fetch_content',
    'mcp_fetch_fetch',
})

# Follow-up context: keep orchestrator history compact.
FOLLOWUP_DEFAULT_MAX_CANDIDATES = 5
# Completion Guard / effective evidence: allow ranking follow-ups without re-querying.
FOLLOWUP_EVIDENCE_MAX_CANDIDATES = 12
# Keep abstractive summaries available for follow-up turns without dragging
# whole transcript-sized artifacts through every router prompt.
FOLLOWUP_SUMMARY_MAX_CHARS = 6000
_FOLLOWUP_TRUNCATION_SUFFIX = "\n...[summary truncated for follow-up context]"
FOLLOWUP_FETCH_EXCERPT_MAX_CHARS = 2000
_FOLLOWUP_FETCH_TRUNCATION_MARKER = "\n...[content truncated for follow-up context]...\n"
FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS = 2000
FOLLOWUP_DOCUMENT_EXCERPT_MAX_CHARS = 3000
_FOLLOWUP_INLINE_TRUNCATION_SUFFIX = "... [truncated for follow-up context]"
_FOLLOWUP_STRUCTURAL_TRUNCATION_KEY = "_followup_truncated"
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
    'images',
    'flat_results',
    'containers',
    'spaces',
    'hosts',
    'webhooks',
    'sites',
    'issues',
    'processes',
    'disks',
    'daily_forecast',
    'forecast',
    'keywords',
)

GENERIC_FOLLOWUP_OBJECT_KEYS = (
    'session',
    'top_process',
    'cpu',
    'uptime',
    'statistics',
    'sentiment',
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
    'property_id',
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
    'arguments',
    'content',
    'body',
    'html',
    'markdown',
    'raw',
    'raw_data',
    'raw_html',
    'raw_text',
    'raw_output',
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
    'prompt',
    'image',
    'images',
    'summary_markdown',
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

GENERIC_FOLLOWUP_NOISE_KEYS = frozenset({
    'ok',
    'proxy_enabled',
    'proxy_retry_without_proxy',
    'authenticated',
})

GENERIC_FOLLOWUP_MAX_SCALAR_FIELDS = 24
GENERIC_FOLLOWUP_MAX_CANDIDATE_FIELDS = 18
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
    'generate_music': [
        'provider', 'model', 'title', 'duration_seconds',
        'duration_is_estimate', 'requested_duration_seconds', 'genre', 'mood',
        'instrumental', 'tempo', 'mime_type', 'size_bytes', 'song_id',
        'output_format', 'requested_output_format', 'synthid_watermarked',
        'file_path',
    ],
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
    'serpapi_yelp_search': [
        'engine', 'find_desc', 'find_loc', 'attrs', 'sort_by', 'sort_basis',
        'results_count', 'provider_results_count', 'top_url', 'place_id',
        'serpapi_searches_used', 'source',
    ],
    'serpapi_search_index': [
        'engine', 'query', 'mode', 'safe', 'start', 'num_results',
        'results_count', 'provider_results_count', 'total_results', 'top_url',
        'search_id', 'has_more', 'next_start', 'serpapi_searches_used', 'source',
    ],
    'serpapi_google_local': [
        'engine', 'query', 'location', 'location_source', 'uule_used',
        'provider_location_requested', 'provider_location_used', 'country',
        'language', 'google_domain', 'device', 'start', 'place_id', 'tbs',
        'max_results', 'results_count', 'provider_results_count', 'ads_count',
        'provider_ads_count', 'discover_more_count',
        'provider_discover_more_count', 'local_map_image', 'top_url',
        'search_id', 'google_local_url', 'has_more', 'next_start',
        'serpapi_searches_used', 'source',
    ],
    'serpapi_google_local_services': [
        'engine', 'mode', 'query', 'provider_query', 'location', 'location_source',
        'resolved_location', 'data_cid', 'data_cid_source', 'language',
        'job_type', 'cid', 'bid', 'pid', 'max_results', 'results_count',
        'provider_results_count', 'top_url', 'google_local_services_url',
        'search_id', 'serpapi_searches_used', 'us_only', 'source',
    ],
    'serpapi_google_images_light': [
        'engine', 'query', 'query_displayed', 'image_results_state',
        'location', 'country', 'language', 'country_restrict', 'google_domain', 'period_unit',
        'period_value', 'start_date', 'end_date', 'aspect_ratio', 'image_size',
        'image_color', 'image_type', 'license', 'safe', 'device', 'start',
        'max_results', 'results_count', 'provider_results_count', 'top_url',
        'top_source_url', 'stash_after', 'stash_ref', 'stash_error',
        'stashed_image', 'search_id', 'has_more', 'next_start',
        'google_images_light_url', 'serpapi_searches_used',
        'external_content_trust', 'untrusted_external_content',
        'handling_note', 'source',
    ],
    'serpapi_google_news_light': [
        'engine', 'query', 'query_displayed', 'news_results_state', 'location',
        'country', 'language', 'language_restrict', 'google_domain', 'safe',
        'exclude_autocorrected', 'filter_similar', 'device', 'start',
        'max_results', 'results_count', 'provider_results_count',
        'top_stories_count', 'provider_top_story_groups_count',
        'top_story_articles_count', 'provider_top_story_articles_count',
        'top_url', 'search_id', 'has_more', 'next_start',
        'google_news_light_url', 'serpapi_searches_used', 'source',
    ],
    'serpapi_google_shopping_light': [
        'engine', 'query', 'query_displayed', 'shopping_results_state',
        'location', 'location_source', 'uule_used', 'provider_location_used',
        'country', 'language', 'google_domain', 'device', 'sort_by',
        'min_price', 'max_price', 'free_shipping', 'on_sale', 'small_business',
        'start', 'max_results', 'results_count', 'provider_results_count',
        'provider_shopping_results_count', 'provider_inline_results_count',
        'provider_category_groups_count', 'provider_categorized_results_count',
        'merchants_count', 'merchants', 'top_url', 'comparison_note',
        'search_id', 'has_more', 'next_start', 'google_shopping_light_url',
        'serpapi_searches_used', 'source',
    ],
    'serpapi_google_sports': [
        'engine', 'query', 'resolver_query', 'kgmid', 'kgmid_source',
        'sport', 'sport_code', 'entity_type', 'tab', 'tab_code',
        'country', 'language', 'middle_time', 'after_time', 'before_time',
        'selection_mode', 'selection_anchor', 'season_kgmid', 'max_results',
        'results_kind', 'results_count',
        'provider_results_count', 'top_url', 'search_id',
        'google_sports_url', 'serpapi_searches_used', 'available_sections',
        'watch', 'more_info', 'box_score_highlights', 'source',
    ],
    'serpapi_google_trends': [
        'engine', 'query', 'queries', 'data_type', 'provider_data_type',
        'date', 'geo', 'region', 'language', 'timezone_offset', 'category',
        'property', 'results_count', 'provider_results_count', 'latest_period',
        'timeline_points_returned', 'timeline_points_original', 'search_id',
        'trends_url', 'serpapi_searches_used', 'source',
    ],
    'serpapi_google_trending_now': [
        'action', 'engine', 'requested_topic', 'scope_notice', 'trend_query',
        'page_token', 'geo', 'language',
        'hours', 'category_id', 'only_active', 'results_count',
        'provider_results_count', 'active_results_count', 'top_query',
        'top_news_page_token', 'top_url', 'search_id', 'trending_now_url',
        'trends_news_url', 'serpapi_searches_used', 'source',
    ],
    'serpapi_travel_explore': [
        'engine', 'provider', 'planning_stage', 'departure_id',
        'arrival_area_id', 'trip_type', 'date_mode', 'outbound_date',
        'return_date', 'month', 'month_label', 'travel_duration',
        'travel_class', 'travel_mode', 'interest', 'travelers', 'currency',
        'sort_by', 'sort_basis', 'applied_filters', 'results_count',
        'provider_results_count', 'top_url', 'flight_price_basis',
        'hotel_price_basis', 'price_confirmation_required', 'booking_note',
        'serpapi_searches_used', 'google_travel_url', 'source',
    ],
    'serpapi_tripadvisor': [
        'action', 'engine', 'query', 'category', 'tripadvisor_domain',
        'place_id', 'results_count', 'total_reviews', 'review_sort_by',
        'review_filters', 'top_url', 'serpapi_searches_used', 'source',
    ],
    'trakt_movies': [
        'action', 'request', 'query', 'results_count', 'top_url',
        'reference_titles_requested', 'resolved_references', 'genre_hints',
        'filters_used', 'trailers', 'sources_queried', 'warnings',
        'api_requests', 'public_metadata_only', 'streaming_provider_data',
        'external_content_trust', 'source',
    ],
    'trakt_tv_shows': [
        'action', 'request', 'query', 'results_count', 'top_url',
        'reference_titles_requested', 'resolved_references', 'genre_hints',
        'filters_used', 'trailers', 'sources_queried', 'warnings',
        'api_requests', 'public_metadata_only', 'runtime_scope',
        'streaming_provider_data', 'external_content_trust', 'source',
    ],
    'tmdb_movies': [
        'action', 'query', 'image_type', 'image_languages', 'results_count',
        'provider_results_count', 'page', 'total_pages', 'top_url',
        'filters_used', 'api_requests', 'auth_method', 'public_metadata_only',
        'attribution_notice', 'attribution_url', 'external_content_trust', 'source',
    ],
    'tmdb_tv_shows': [
        'action', 'query', 'image_type', 'image_languages', 'results_count',
        'provider_results_count', 'page', 'total_pages', 'top_url',
        'filters_used', 'selection_criteria', 'api_requests', 'auth_method',
        'public_metadata_only', 'runtime_scope', 'attribution_notice',
        'attribution_url', 'external_content_trust', 'source',
    ],
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
    'phone_call': [
        'call_id', 'duration', 'recording_url', 'saved_to_canvas',
        'canvas_location',
    ],
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
    'search_conversations': ['count', 'match_mode'],
    'semantic_recall': ['count'],
    'update_memory': ['memory_id', 'old_value', 'new_value'],
    'forget': ['deleted_id', 'deleted_key', 'deleted_ids', 'deleted_keys', 'missing_ids'],
    'create_reminder': ['reminder_id', 'formatted_time'],
    'acknowledge_alerts': ['alert_id', 'acknowledged', 'cleared_count'],
    'acknowledge_reminders': [
        'acknowledged_count', 'acknowledged_ids', 'already_done',
    ],
    'send_email': ['to', 'subject', 'status'],
    'api_call': ['url', 'method', 'status_code'],
    'serpapi_amazon_search': ['engine', 'query', 'asin', 'results_count', 'top_url'],
    'serpapi_search': ['engine', 'query', 'asin', 'results_count', 'top_url'],
    'serpapi_home_depot': ['engine', 'query', 'country', 'product_id', 'results_count', 'top_url', 'top_image_url'],
    'serpapi_ebay_search': ['engine', 'query', 'category_id', 'ebay_domain', 'product_id', 'results_count', 'top_url'],
    'serpapi_ebay_product': ['engine', 'product_id', 'ebay_domain', 'results_count', 'top_url', 'top_image_url'],
    'serpapi_maps_search': ['engine', 'query', 'results_count'],
    'serpapi_hotel_search': [
        'engine', 'provider', 'query', 'destination', 'check_in_date', 'check_out_date',
        'nights', 'sort_by', 'applied_filters', 'currency', 'results_count', 'cheapest_price_total',
        'cheapest_price_per_night', 'price_basis',
    ],
    'flight_search': [
        'provider', 'trip_type', 'departure_id', 'arrival_id', 'outbound_date', 'return_date',
        'travel_class', 'stops_filter', 'sort_by', 'currency', 'results_count', 'cheapest_price',
        'price_basis', 'booking_url',
    ],
    'spotify': ['name', 'artist'],
    'docker_control': ['container', 'status'],
    'ssh_remote': ['host'],
    'status_recap': ['stash_ref', 'canvas_id'],
    'brave_llm_context': ['query'],
    'supa_crawl_knowledge': [
        'action', 'query', 'site_id', 'page_id', 'base_url', 'count',
        'returned', 'site_name', 'threshold', 'dedupe',
    ],
}


def _truncate_followup_text(
    value: str,
    max_chars: int,
    *,
    suffix: str = _FOLLOWUP_INLINE_TRUNCATION_SUFFIX,
) -> str:
    """Bound text while making every shortened value explicit to the model."""
    if not isinstance(value, str):
        value = str(value)
    if len(value) <= max_chars:
        return value
    if max_chars <= len(suffix):
        # Clarity wins over an unrealistically tiny caller budget. Production
        # budgets are all larger than the marker.
        return suffix
    return value[: max_chars - len(suffix)].rstrip() + suffix


def _bounded_head_tail_excerpt(text: str, max_chars: int) -> str:
    """Keep useful head/tail content with an unmistakable omission marker."""
    text = text.strip()
    if len(text) <= max_chars:
        return text

    marker = _FOLLOWUP_FETCH_TRUNCATION_MARKER
    remaining = max_chars - len(marker)
    if remaining <= 0:
        return marker.strip()
    head_length = remaining * 3 // 4
    tail_length = remaining - head_length
    return (
        text[:head_length].rstrip()
        + marker
        + text[-tail_length:].lstrip()
    )


def _strict_json_text(value) -> str:
    """Serialize a follow-up value as strict, compact JSON."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(',', ':'),
    )


def _normalize_strict_json_value(value):
    """Normalize legacy/non-standard values before returning follow-up data."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return (
            f"{value} "
            "[non-finite number normalized for follow-up context]"
        )
    if isinstance(value, dict):
        return {
            str(key): _normalize_strict_json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_strict_json_value(item) for item in value]
    normalized = (
        f"{value} "
        "[non-JSON value normalized for follow-up context]"
    )
    return _truncate_followup_text(normalized, 300)


def _annotate_candidate_truncation(value) -> None:
    """Make ranked shortlist compaction explicit wherever a total is known."""
    if isinstance(value, list):
        for item in value:
            _annotate_candidate_truncation(item)
        return
    if not isinstance(value, dict):
        return

    candidates = value.get('candidates')
    if isinstance(candidates, list):
        total = next(
            (
                value.get(field)
                for field in (
                    'results_count',
                    'candidates_count',
                    'count',
                    'runs_count',
                )
                if isinstance(value.get(field), (int, float))
            ),
            None,
        )
        if total is not None and total > len(candidates):
            value['candidates_truncated'] = True

    for item in value.values():
        _annotate_candidate_truncation(item)


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
                payload = {
                    'error': _truncate_followup_text(str(error), 500),
                }
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
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    if (
        lowered in GENERIC_FOLLOWUP_BULKY_OR_UNSAFE_KEYS
        or lowered in GENERIC_FOLLOWUP_NOISE_KEYS
    ):
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
        value = _truncate_followup_text(value, limit)
    return value


def _compact_generic_scalars(
    payload: dict,
    *,
    max_fields: int,
    include_dynamic: bool = True,
) -> dict:
    """Keep preferred handles first, then bounded safe scalar payload fields."""
    compacted = {}
    ordered_fields = list(GENERIC_FOLLOWUP_SCALAR_KEYS)
    if include_dynamic:
        ordered_fields.extend(
            field
            for field in payload
            if isinstance(field, str) and field not in GENERIC_FOLLOWUP_SCALAR_KEYS
        )

    for field in ordered_fields:
        if (
            field in compacted
            or field not in payload
            or not _safe_generic_key(field)
        ):
            continue
        compact = _compact_generic_scalar(field, payload.get(field))
        if compact in (None, '', [], {}):
            continue
        compacted[field] = compact
        if len(compacted) >= max_fields:
            break
    return compacted


def _generic_candidate_from_item(item: dict) -> dict:
    candidate = _compact_generic_scalars(
        item,
        max_fields=GENERIC_FOLLOWUP_MAX_CANDIDATE_FIELDS,
    )

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
            if len(candidate) >= GENERIC_FOLLOWUP_MAX_CANDIDATE_FIELDS:
                break

    return candidate


def _generic_item_identity(item: dict):
    for field in (
        'property_id',
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


def _extract_generic_followup(
    payload: dict,
    max_candidates: int,
    *,
    include_dynamic_scalars: bool = True,
) -> dict:
    """Conservative fallback for tools without dedicated follow-up adapters."""
    extracted = _compact_generic_scalars(
        payload,
        max_fields=GENERIC_FOLLOWUP_MAX_SCALAR_FIELDS,
        include_dynamic=include_dynamic_scalars,
    )

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

    if not extracted.get('candidates'):
        for object_key in GENERIC_FOLLOWUP_OBJECT_KEYS:
            value = payload.get(object_key)
            if not isinstance(value, dict):
                continue
            candidate = _generic_candidate_from_item(value)
            if not candidate:
                continue
            extracted['candidate_source'] = object_key
            extracted['candidates'] = [candidate]
            break

    return extracted


def _successful_tool_trace_arguments(data: dict, tool_name: str) -> list[dict]:
    """Return successful argument payloads for one tool in execution order."""
    trace = data.get('_tool_trace')
    if not isinstance(trace, list):
        return []

    arguments = []
    for entry in trace:
        if not isinstance(entry, dict) or entry.get('tool') != tool_name:
            continue
        if entry.get('ok') is False:
            continue
        entry_arguments = entry.get('arguments')
        arguments.append(entry_arguments if isinstance(entry_arguments, dict) else {})
    return arguments


def _compact_request_arguments(arguments: dict) -> dict:
    """Bound safe request fields so empty/sparse results still retain intent."""
    if not isinstance(arguments, dict):
        return {}

    compact = _compact_generic_scalars(
        arguments,
        max_fields=GENERIC_FOLLOWUP_MAX_SCALAR_FIELDS,
    )
    for field, value in arguments.items():
        if (
            field in compact
            or not _safe_generic_key(field)
            or not isinstance(value, list)
            or not value
        ):
            continue
        items = []
        for item in value[:10]:
            if not _is_generic_scalar(item):
                continue
            item_value = _compact_generic_scalar(field, item)
            if item_value not in (None, '', [], {}):
                items.append(item_value)
        if len(value) > 10:
            items.append(
                f"... [{len(value) - 10} items truncated for follow-up context]"
            )
        if items:
            compact[field] = items
    return compact


def _extract_generic_tool_request(data: dict, tool_name: str) -> dict:
    arguments = _successful_tool_trace_arguments(data, tool_name)
    if not arguments:
        return {}
    request = _compact_request_arguments(arguments[-1])
    if len(arguments) > 1:
        request['runs_count'] = len(arguments)
    return request


_SPOTIFY_ARGUMENT_FIELDS = (
    'action',
    'query',
    'type',
    'device',
    'device_id',
    'level',
    'state',
    'mood',
    'genre',
    'time_range',
    'limit',
)

_SPOTIFY_SCALAR_FIELDS = (
    'action',
    'query',
    'type',
    'time_range',
    'count',
    'total_followed',
    'has_more',
    'playing',
    'name',
    'artist',
    'album',
    'progress',
    'duration',
    'device',
    'volume',
    'shuffle',
    'device_id',
    'device_name',
    'uri',
    'spotify_url',
    'show',
    'show_uri',
    'source',
    'publisher',
)

_SPOTIFY_LIST_FIELDS = (
    'results',
    'items',
    'artists',
    'devices',
    'playlists',
    'tracks',
    'episodes',
    'suggestions',
)

_SPOTIFY_CANDIDATE_FIELDS = (
    'id',
    'number',
    'name',
    'artist',
    'uri',
    'spotify_url',
    'type',
    'owner',
    'publisher',
    'show',
    'show_uri',
    'date',
    'duration',
    'duration_min',
    'release_date',
    'total_episodes',
    'active',
    'volume',
    'why',
    'followers',
    'popularity',
)


def _extract_spotify_followup(
    data: dict,
    payload: dict,
    max_candidates: int,
) -> dict:
    """Project Spotify's varied action payloads into durable chat references."""
    extracted = {}

    arguments = _successful_tool_trace_arguments(data, 'spotify')
    if arguments:
        latest_arguments = arguments[-1]
        for field in _SPOTIFY_ARGUMENT_FIELDS:
            value = latest_arguments.get(field)
            if value not in (None, '', [], {}):
                extracted[field] = value

    for field in _SPOTIFY_SCALAR_FIELDS:
        if field in extracted:
            continue
        value = payload.get(field)
        if value not in (None, '', [], {}):
            extracted[field] = value

    for list_field in _SPOTIFY_LIST_FIELDS:
        items = payload.get(list_field)
        if not isinstance(items, list) or not items:
            continue

        # Recommendation playback returns artist names rather than result rows.
        if all(isinstance(item, str) for item in items):
            extracted[f'{list_field}_names'] = [
                _truncate_followup_text(item, GENERIC_FOLLOWUP_STRING_MAX_CHARS)
                for item in items[:max_candidates]
            ]
            extracted[f'{list_field}_count'] = len(items)
            if len(items) > max_candidates:
                extracted[f'{list_field}_truncated'] = True
            continue

        candidates = []
        for item in items[:max_candidates]:
            if not isinstance(item, dict):
                continue
            candidate = {}
            for field in _SPOTIFY_CANDIDATE_FIELDS:
                value = item.get(field)
                if value not in (None, '', [], {}):
                    candidate[field] = value
            genres = item.get('genres')
            if isinstance(genres, list) and genres:
                candidate['genres'] = [
                    _truncate_followup_text(
                        genre,
                        GENERIC_FOLLOWUP_STRING_MAX_CHARS,
                    )
                    for genre in genres[:5]
                    if isinstance(genre, str) and genre
                ]
                if len(genres) > 5:
                    candidate['genres_count'] = len(genres)
                    candidate['genres_truncated'] = True
            if candidate:
                candidates.append(candidate)

        if candidates:
            extracted['candidate_source'] = list_field
            extracted['candidates'] = candidates
            extracted.setdefault('count', len(items))
            break

    return extracted


def _extract_spotify_runs_followup(
    data: dict,
    runs: list[dict],
    max_candidates: int,
) -> dict:
    """Preserve the useful browse result and final reference from a Spotify tool loop."""
    extracted = _extract_spotify_followup(data, {}, max_candidates)
    extracted['runs_count'] = len(runs)

    # Work backward so a later corrective browse supersedes an earlier wrong result.
    for run in reversed(runs):
        payload = run.get('data') if isinstance(run.get('data'), dict) else run
        if not isinstance(payload, dict):
            continue
        browse = _extract_spotify_followup({}, payload, max_candidates)
        if not browse.get('candidates'):
            continue
        for field in (
            'show',
            'show_uri',
            'count',
            'candidate_source',
            'candidates',
        ):
            if field in browse:
                extracted[field] = browse[field]
        break

    # Successful result aggregation is chronological, so retain the final played
    # URI/type without replacing the richer episode/track browse candidates.
    if runs:
        final_run = runs[-1]
        final_payload = (
            final_run.get('data')
            if isinstance(final_run.get('data'), dict)
            else final_run
        )
        if isinstance(final_payload, dict):
            for field in ('uri', 'type'):
                value = final_payload.get(field)
                if value not in (None, '', [], {}):
                    extracted[field] = value

    return extracted


def _mcp_text_runs(value: dict) -> list[dict]:
    """Normalize one or repeated text-oriented MCP results into runs."""
    results = value.get('results')
    if isinstance(results, list):
        return [run for run in results if isinstance(run, dict)]
    return [value]


def _mcp_text_from_run(run: dict) -> str:
    """Prefer normalized MCP full_text, falling back to raw text parts."""
    full_text = run.get('full_text')
    if isinstance(full_text, str) and full_text:
        return full_text

    raw = run.get('raw')
    if not isinstance(raw, list):
        return ''
    return '\n'.join(
        part['text']
        for part in raw
        if isinstance(part, dict) and isinstance(part.get('text'), str)
    )


def _bounded_fetch_excerpt(text: str) -> str:
    """Keep the useful beginning and pagination-bearing tail of fetched text."""
    return _bounded_head_tail_excerpt(
        text,
        FOLLOWUP_FETCH_EXCERPT_MAX_CHARS,
    )


def _extract_duckduckgo_search_followup(
    data: dict,
    value: dict,
    max_candidates: int,
) -> dict:
    """Compact DuckDuckGo's numbered text results into durable candidates."""
    runs = _mcp_text_runs(value)
    arguments = _successful_tool_trace_arguments(data, 'mcp_duckduckgo_search')
    extracted = {'runs_count': len(runs)}

    if arguments:
        latest = arguments[-1]
        for field in ('query', 'region', 'max_results'):
            if latest.get(field) not in (None, '', [], {}):
                extracted[field] = latest[field]
        queries = []
        for argument in arguments:
            query = argument.get('query')
            if isinstance(query, str) and query and query not in queries:
                queries.append(query)
        if len(queries) > 1:
            extracted['queries'] = queries

    candidates = []
    urls_seen = []
    seen_urls: set[str] = set()
    advertised_count = 0
    found_advertised_count = False

    for run in runs:
        text = _mcp_text_from_run(run)
        count_match = _DUCKDUCKGO_RESULT_COUNT_RE.search(text)
        if count_match:
            advertised_count += int(count_match.group(1))
            found_advertised_count = True

        parsed_result = False
        for match in _DUCKDUCKGO_RESULT_RE.finditer(text):
            parsed_result = True
            url = match.group('url').rstrip(').,;')
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            if len(urls_seen) < max_candidates * 2:
                urls_seen.append(_truncate_followup_text(url, 2048))
            if len(candidates) >= max_candidates:
                continue
            candidate = {
                'title': _truncate_followup_text(
                    ' '.join(match.group('title').split()),
                    300,
                ),
                'url': _truncate_followup_text(url, 2048),
            }
            snippet = ' '.join(match.group('snippet').split())
            if snippet:
                candidate['snippet'] = _truncate_followup_text(snippet, 500)
            candidates.append(candidate)

        # Preserve URL grounding if the upstream human-readable format changes.
        if not parsed_result:
            for url in _MCP_URL_RE.findall(text):
                url = url.rstrip(').,;')
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                if len(urls_seen) < max_candidates * 2:
                    urls_seen.append(_truncate_followup_text(url, 2048))

    if found_advertised_count:
        extracted['results_count'] = advertised_count
    elif urls_seen or candidates:
        extracted['results_count'] = len(seen_urls) or len(candidates)
    if urls_seen:
        extracted['top_url'] = urls_seen[0]
        extracted['urls_seen'] = urls_seen
    if candidates:
        extracted['candidates'] = candidates
    return extracted


_BRAVE_RESULT_LIST_KEYS = (
    'results',
    'items',
    'videos',
    'locations',
    'cities',
    'addresses',
    'streets',
)


def _mcp_json_values(run: dict) -> list:
    """Decode JSON-oriented MCP text parts without replaying their raw bodies."""
    texts = []
    full_text = run.get('full_text')
    if isinstance(full_text, str) and full_text.strip():
        texts.append(full_text)
    raw = run.get('raw')
    if isinstance(raw, list):
        for part in raw:
            text = part.get('text') if isinstance(part, dict) else None
            if isinstance(text, str) and text.strip() and text not in texts:
                texts.append(text)

    decoded = []
    for text in texts:
        try:
            decoded.append(json.loads(text))
        except (TypeError, ValueError):
            continue
    return decoded


def _brave_result_rows(value) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for field in _BRAVE_RESULT_LIST_KEYS:
        rows = value.get(field)
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    if any(value.get(field) for field in ('url', 'title', 'name')):
        return [value]
    return []


def _compact_brave_candidate(item: dict) -> dict:
    candidate = _generic_candidate_from_item(item)

    description = item.get('description')
    if isinstance(description, str) and description.strip():
        candidate['description'] = _truncate_followup_text(
            description.strip(),
            500,
        )

    properties = item.get('properties')
    if isinstance(properties, dict):
        image_url = properties.get('url')
        if isinstance(image_url, str) and image_url:
            candidate['image_url'] = _truncate_followup_text(
                image_url,
                GENERIC_FOLLOWUP_URL_MAX_CHARS,
            )
        for field in ('width', 'height'):
            if properties.get(field) is not None:
                candidate[field] = properties[field]

    thumbnail = item.get('thumbnail')
    if isinstance(thumbnail, dict):
        thumbnail_url = thumbnail.get('src') or thumbnail.get('url')
        if isinstance(thumbnail_url, str) and thumbnail_url:
            candidate['thumbnail'] = _truncate_followup_text(
                thumbnail_url,
                GENERIC_FOLLOWUP_URL_MAX_CHARS,
            )

    coordinates = item.get('coordinates')
    if (
        isinstance(coordinates, list)
        and 1 < len(coordinates) <= 3
        and all(isinstance(part, (int, float)) for part in coordinates)
    ):
        candidate['coordinates'] = coordinates
    return candidate


def _extract_brave_search_followup(
    data: dict,
    tool_name: str,
    value: dict,
    max_candidates: int,
) -> dict:
    """Compact every Brave MCP search shape, including newly added tools."""
    runs = _mcp_text_runs(value)
    extracted = {'runs_count': len(runs)}

    request = _extract_generic_tool_request(data, tool_name)
    for field, field_value in request.items():
        extracted[field] = field_value

    candidates = []
    urls_seen = []
    seen_urls: set[str] = set()
    max_urls = max_candidates * 2
    parsed_results_count = 0

    def add_url(url):
        if not isinstance(url, str):
            return
        url = url.rstrip(').,;')
        if not url or url in seen_urls:
            return
        seen_urls.add(url)
        if len(urls_seen) < max_urls:
            urls_seen.append(
                _truncate_followup_text(
                    url,
                    GENERIC_FOLLOWUP_URL_MAX_CHARS,
                )
            )

    for run in runs:
        parsed_rows = []
        for decoded in _mcp_json_values(run):
            parsed_rows.extend(_brave_result_rows(decoded))
        parsed_results_count += len(parsed_rows)

        for row in parsed_rows:
            candidate = _compact_brave_candidate(row)
            for field in (
                'url', 'image_url', 'thumbnail_url', 'provider_url', 'thumbnail',
            ):
                add_url(candidate.get(field))
            if candidate and len(candidates) < max_candidates:
                candidates.append(candidate)

        text = _mcp_text_from_run(run)
        for url in _MCP_URL_RE.findall(text):
            add_url(url)

    if candidates:
        extracted['results_count'] = parsed_results_count or len(candidates)
        extracted['candidates'] = candidates
        first = candidates[0]
        if first.get('title'):
            extracted['title'] = first['title']
        if first.get('url'):
            extracted['top_url'] = first['url']
    if urls_seen:
        extracted.setdefault('top_url', urls_seen[0])
        extracted['urls_seen'] = urls_seen
    return extracted


def _extract_mcp_fetch_followup(data: dict, tool_name: str, value: dict) -> dict:
    """Compact DuckDuckGo/Fetch page retrieval for persisted follow-up turns."""
    runs = _mcp_text_runs(value)
    arguments = _successful_tool_trace_arguments(data, tool_name)
    extracted = {'runs_count': len(runs)}

    fetched_urls = []
    for argument in arguments:
        url = argument.get('url')
        if isinstance(url, str) and url and url not in fetched_urls:
            fetched_urls.append(_truncate_followup_text(url, 2048))
    if arguments:
        latest = arguments[-1]
        for field in ('url', 'start_index', 'max_length', 'raw', 'backend'):
            if latest.get(field) not in (None, '', [], {}):
                extracted[field] = latest[field]
    if fetched_urls:
        extracted['fetched_urls'] = fetched_urls

    latest_text = ''
    for run in runs:
        text = _mcp_text_from_run(run)
        if text:
            latest_text = text
    if not latest_text:
        return extracted

    extracted['content_characters'] = len(latest_text)
    extracted['content_excerpt'] = _bounded_fetch_excerpt(latest_text)
    content_info = _MCP_FETCH_CONTENT_INFO_RE.search(latest_text)
    if content_info:
        start, end, total = (int(value) for value in content_info.groups())
        extracted['content_start'] = start
        extracted['content_end'] = end
        extracted['content_total'] = total
        if end < total:
            extracted['has_more'] = True
    return extracted


def truncate_followup_summary(summary: str, max_chars: int = FOLLOWUP_SUMMARY_MAX_CHARS) -> str:
    """Trim stored summaries to a stable prompt-sized excerpt."""
    if not isinstance(summary, str):
        return ''
    summary = summary.strip()
    return _truncate_followup_text(
        summary,
        max_chars,
        suffix=_FOLLOWUP_TRUNCATION_SUFFIX,
    )


def compact_text_summarizer_item(
    item,
    max_candidates: int = FOLLOWUP_DEFAULT_MAX_CANDIDATES,
    summary_max_chars: int = FOLLOWUP_SUMMARY_MAX_CHARS,
) -> dict | None:
    """Compact any text_summarizer operation for history/evidence storage."""
    if not isinstance(item, dict):
        return None

    extracted = {}
    summary = item.get('summary')
    if isinstance(summary, str) and summary.strip():
        extracted['summary'] = truncate_followup_summary(
            summary,
            max_chars=summary_max_chars,
        )

    source = item.get('source') if isinstance(item.get('source'), dict) else {}
    for field in ('stash_ref', 'file_id', 'space_id', 'source', 'characters_loaded'):
        if source.get(field) not in (None, '', [], {}):
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

    keywords = item.get('keywords')
    if isinstance(keywords, list) and keywords:
        compact_keywords = []
        for keyword in keywords[:max_candidates]:
            if not isinstance(keyword, dict):
                continue
            compact = _generic_candidate_from_item(keyword)
            if compact:
                compact_keywords.append(compact)
        if compact_keywords:
            extracted['keywords_count'] = len(keywords)
            extracted['keywords'] = compact_keywords

    for field in ('statistics', 'sentiment'):
        value = item.get(field)
        if not isinstance(value, dict):
            continue
        compact = _generic_candidate_from_item(value)
        if compact:
            extracted[field] = compact

    return extracted or None


def extract_text_summarizer_followup(value, max_candidates: int) -> dict | None:
    """Preserve summaries plus keywords/count/sentiment operation results."""
    if isinstance(value, list):
        selected = value[:max_candidates]
        summary_max_chars = max(
            800,
            FOLLOWUP_SUMMARY_MAX_CHARS // max(1, len(selected)),
        )
        items = [
            compact_text_summarizer_item(
                item,
                max_candidates=max_candidates,
                summary_max_chars=summary_max_chars,
            )
            for item in selected
        ]
        items = [item for item in items if item]
        if not items:
            return None
        latest = items[-1]
        extracted = {'results_count': len(value)}
        if all(item.get('summary') for item in items):
            extracted['summaries'] = items
        else:
            extracted['latest'] = latest
            extracted['results'] = items
        if latest.get('stash_ref'):
            extracted['latest_stash_ref'] = latest['stash_ref']
        return extracted

    if isinstance(value, dict):
        return compact_text_summarizer_item(value, max_candidates=max_candidates)
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
        compact['warning'] = _truncate_followup_text(
            str(ingest['warning']),
            500,
        )
    if ingest.get('error'):
        compact['error'] = _truncate_followup_text(
            str(ingest['error']),
            500,
        )
    return compact


def _manage_intel_document_meta(doc: dict) -> dict:
    return {
        key: value
        for key, value in doc.items()
        if key not in {'content', 'appended_content'} and value not in (None, '', [], {})
    }


def _extract_manage_intel_followup(data: dict, max_candidates: int) -> dict | None:
    all_payloads = _manage_intel_payloads(data.get('manage_intel'))
    payloads = all_payloads[-max_candidates:]
    if not payloads:
        return None

    trace_args = _manage_intel_trace_arguments(data)[-max_candidates:]
    operations = []
    documents = []

    trace_offset = max(0, len(payloads) - len(trace_args))
    for index, payload in enumerate(payloads):
        trace_index = index - trace_offset
        args = (
            trace_args[trace_index]
            if 0 <= trace_index < len(trace_args)
            else {}
        )
        action = payload.get('action') or args.get('action')
        file_name = payload.get('file') or args.get('path')

        operation = {}
        for field, value in (
            ('action', action),
            ('file', file_name),
            ('size_bytes', payload.get('size_bytes')),
            ('created', payload.get('created')),
            ('versioned', payload.get('versioned')),
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
            match_limit = 5 if max_candidates > FOLLOWUP_DEFAULT_MAX_CANDIDATES else 2
            compact_matches = [
                _generic_candidate_from_item(item)
                for item in payload['matches'][:match_limit]
                if isinstance(item, dict)
            ]
            compact_matches = [item for item in compact_matches if item]
            if compact_matches:
                operation['matches'] = compact_matches

        content = payload.get('content')
        content_source = 'tool_result'
        doc_meta = None
        if not isinstance(content, str) and action in {'create', 'read', 'update', 'append'}:
            doc_meta = _read_manage_intel_document(file_name)
            if doc_meta:
                content = doc_meta['content']
                content_source = 'jarvis-intel/current_file'

        if isinstance(content, str):
            compact_content = (
                content
                if len(content) <= FOLLOWUP_DOCUMENT_EXCERPT_MAX_CHARS
                else truncate_followup_summary(
                    content,
                    max_chars=FOLLOWUP_DOCUMENT_EXCERPT_MAX_CHARS,
                )
            )
            doc = {
                'action': action,
                'file': file_name,
                'content': compact_content,
                'content_source': content_source,
                'size_bytes': payload.get('size_bytes', len(content)),
                'content_characters': len(content),
                'content_truncated': len(compact_content) < len(content.strip()),
                'content_sha256': (
                    payload.get('file_sha256')
                    or (doc_meta or {}).get('content_sha256')
                    or hashlib.sha256(content.encode('utf-8')).hexdigest()
                ),
            }
            if isinstance(payload.get('appended_content'), str):
                appended_content = payload['appended_content']
                doc['appended_content'] = (
                    appended_content
                    if len(appended_content) <= 1000
                    else truncate_followup_summary(
                        appended_content,
                        max_chars=1000,
                    )
                )
            documents.append(doc)
            operation['document_available'] = True
            operation['content_source'] = content_source

        if operation:
            operations.append(operation)

    if not operations and not documents:
        return None

    extracted = {
        'operation_count': len(operations),
        'operations_total': len(all_payloads),
        'operations': operations,
    }
    if len(all_payloads) > len(payloads):
        extracted['operations_truncated'] = True
    if operations:
        latest = operations[-1]
        for field in (
            'action',
            'file',
            'size_bytes',
            'created',
            'versioned',
            'updated',
            'appended',
            'deleted',
        ):
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


_SERPAPI_CANDIDATE_FIELDS = (
    'title',
    'asin',
    'url',
    'thumbnail',
    'price',
    'extracted_price',
    'old_price',
    'extracted_old_price',
    'rating',
    'reviews',
    'prime',
    'prime_eligible',
    'delivery',
    'shipping',
    'stock',
    'availability',
    'bought_last_month',
    'badges',
    'save_with_coupon',
)


def _compact_serpapi_list(field: str, value: list) -> list:
    """Bound the few small list fields retained for shopping follow-ups."""
    limit = 3 if field == 'delivery' else 5
    max_chars = 500 if field == 'delivery' else 120
    compact = [
        _truncate_followup_text(str(item), max_chars)
        for item in value[:limit]
        if item not in (None, '', [], {})
    ]
    if len(value) > limit:
        compact.append(
            f"... [{len(value) - limit} items truncated for follow-up context]"
        )
    return compact


def _compact_serpapi_candidate(item: dict) -> dict:
    """Keep product identity plus decision-relevant shopping signals."""
    candidate = {}
    for field in _SERPAPI_CANDIDATE_FIELDS:
        field_value = item.get(field)
        if field_value in (None, '', [], {}):
            continue
        if isinstance(field_value, list):
            compact_list = _compact_serpapi_list(field, field_value)
            if compact_list:
                candidate[field] = compact_list
            continue
        compact_value = _compact_generic_scalar(field, field_value)
        if compact_value not in (None, '', [], {}):
            candidate[field] = compact_value
    return candidate


def _serpapi_result_rows(payload: dict) -> list[dict]:
    rows = payload.get('results') or payload.get('top_results') or []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _merge_serpapi_candidate(base: dict, detail: dict) -> dict:
    """Overlay richer detail signals while preserving the discovery identity."""
    merged = dict(base)
    for field, field_value in detail.items():
        if field in {'title', 'url', 'thumbnail'} and merged.get(field):
            continue
        merged[field] = field_value
    return merged


def _extract_serpapi_followup(value, max_candidates: int) -> dict:
    """Join discovery and product-detail runs into one compact shortlist."""
    raw_runs = value if isinstance(value, list) else [value]
    runs = []
    for raw_run in raw_runs:
        if not isinstance(raw_run, dict):
            continue
        payload = (
            raw_run.get('data')
            if isinstance(raw_run.get('data'), dict)
            else raw_run
        )
        if isinstance(payload, dict):
            runs.append(payload)

    if not runs:
        return {}

    discovery = next(
        (
            run for run in runs
            if run.get('engine') != 'amazon_product'
            and _serpapi_result_rows(run)
        ),
        None,
    )
    primary = discovery or runs[0]

    details_by_asin = {}
    for run in runs:
        if run.get('engine') != 'amazon_product':
            continue
        for row in _serpapi_result_rows(run):
            candidate = _compact_serpapi_candidate(row)
            asin = candidate.get('asin') or run.get('asin')
            if not asin:
                continue
            candidate.setdefault('asin', asin)
            prior = details_by_asin.get(asin, {})
            details_by_asin[asin] = _merge_serpapi_candidate(prior, candidate)

    candidates = []
    seen = set()
    candidate_runs = [discovery] if discovery else runs
    for run in candidate_runs:
        if not isinstance(run, dict):
            continue
        for row in _serpapi_result_rows(run):
            candidate = _compact_serpapi_candidate(row)
            if not candidate:
                continue
            if run.get('engine') == 'amazon_product' and run.get('asin'):
                candidate.setdefault('asin', run['asin'])
            identity = (
                candidate.get('asin')
                or candidate.get('url')
                or candidate.get('title')
            )
            if identity in seen:
                continue
            seen.add(identity)
            detail = details_by_asin.get(candidate.get('asin'))
            if detail:
                candidate = _merge_serpapi_candidate(candidate, detail)
            candidates.append(candidate)
            if len(candidates) >= max_candidates:
                break
        if len(candidates) >= max_candidates:
            break

    extracted = {}
    for field in (
        'engine',
        'query',
        'query_effective',
        'query_was_optimized',
        'asin',
        'delivery_localized',
        'delivery_location_source',
        'shipping_location',
    ):
        field_value = primary.get(field)
        if field_value not in (None, '', [], {}):
            extracted[field] = field_value

    extracted['runs_count'] = len(runs)
    extracted['results_count'] = primary.get('results_count', len(candidates))
    if primary.get('top_url'):
        extracted['top_url'] = primary['top_url']

    if candidates:
        first = candidates[0]
        for field, field_value in first.items():
            if field == 'url':
                extracted.setdefault('top_url', field_value)
            else:
                extracted.setdefault(field, field_value)
        extracted['candidates'] = candidates

    return extracted


def _bounded_content_excerpt(
    value,
    *,
    max_chars: int = FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS,
) -> str:
    text = value if isinstance(value, str) else str(value)
    text = text.strip()
    if not text:
        return ''
    return _bounded_head_tail_excerpt(text, max_chars)


def _nested_followup_field_is_sensitive(field: str) -> bool:
    lowered = field.lower()
    return (
        lowered in {'headers', 'cookies', 'set-cookie'}
        or any(part in lowered for part in GENERIC_FOLLOWUP_SENSITIVE_KEY_PARTS)
    )


def _sanitize_nested_followup_value(
    value,
    *,
    depth: int = 0,
    max_depth: int = 4,
    max_fields: int = 30,
    max_items: int = 10,
    max_string_chars: int = 1000,
):
    """Return a secret-safe, strict-JSON value with explicit compaction sentinels."""
    if depth > max_depth:
        return {
            _FOLLOWUP_STRUCTURAL_TRUNCATION_KEY: True,
            '_followup_reason': 'depth_limit',
        }
    if isinstance(value, dict):
        compact = {}
        safe_items = []
        redacted_fields = 0
        for field, field_value in value.items():
            if not isinstance(field, str):
                continue
            if _nested_followup_field_is_sensitive(field):
                redacted_fields += 1
                continue
            safe_items.append((field, field_value))

        for field, field_value in safe_items[:max_fields]:
            sanitized = _sanitize_nested_followup_value(
                field_value,
                depth=depth + 1,
                max_depth=max_depth,
                max_fields=max_fields,
                max_items=max_items,
                max_string_chars=max_string_chars,
            )
            if sanitized not in (None, '', [], {}):
                compact[field] = sanitized
        omitted_fields = max(0, len(safe_items) - max_fields)
        if omitted_fields:
            compact[_FOLLOWUP_STRUCTURAL_TRUNCATION_KEY] = True
            compact['_followup_omitted_fields'] = omitted_fields
        if redacted_fields:
            compact['_followup_redacted_fields'] = redacted_fields
        return compact
    if isinstance(value, list):
        compact = []
        for item in value[:max_items]:
            sanitized = _sanitize_nested_followup_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_fields=max_fields,
                max_items=max_items,
                max_string_chars=max_string_chars,
            )
            if sanitized not in (None, '', [], {}):
                compact.append(sanitized)
        omitted_items = max(0, len(value) - max_items)
        if omitted_items:
            compact.append(
                {
                    _FOLLOWUP_STRUCTURAL_TRUNCATION_KEY: True,
                    '_followup_omitted_items': omitted_items,
                }
            )
        return compact
    if isinstance(value, str):
        return _truncate_followup_text(value, max_string_chars)
    if isinstance(value, float) and not math.isfinite(value):
        return (
            f"{value} "
            "[non-finite number normalized for follow-up context]"
        )
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _truncate_followup_text(str(value), 300)


def _bounded_structured_followup_value(
    value,
    *,
    max_chars: int = FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS,
):
    """Compact nested data structurally without ever slicing serialized JSON."""
    profiles = (
        (30, 10, 1000),
        (20, 8, 500),
        (12, 6, 250),
        (8, 4, 120),
        (5, 3, 60),
    )
    for max_fields, max_items, max_string_chars in profiles:
        compact = _sanitize_nested_followup_value(
            value,
            max_fields=max_fields,
            max_items=max_items,
            max_string_chars=max_string_chars,
        )
        if len(_strict_json_text(compact)) <= max_chars:
            return compact

    if isinstance(value, dict):
        return {
            _FOLLOWUP_STRUCTURAL_TRUNCATION_KEY: True,
            '_followup_reason': 'size_limit',
            '_followup_original_fields': len(value),
        }
    if isinstance(value, list):
        return [
            {
                _FOLLOWUP_STRUCTURAL_TRUNCATION_KEY: True,
                '_followup_reason': 'size_limit',
                '_followup_original_items': len(value),
            }
        ]
    return _truncate_followup_text(str(value), max_chars)


def _extract_query_service_logs_followup(
    payload: dict,
    max_candidates: int,
) -> dict:
    extracted = {}
    compact_logs = []
    logs = payload.get('logs')
    if isinstance(logs, list):
        sources = [(None, logs)]
    elif isinstance(logs, dict):
        sources = [
            (service, rows)
            for service, rows in logs.items()
            if isinstance(rows, list)
        ]
    else:
        sources = []

    for service, rows in sources:
        for item in rows:
            if not isinstance(item, dict):
                continue
            candidate = _generic_candidate_from_item(item)
            if service:
                candidate.setdefault('service', service)
            if candidate:
                compact_logs.append(candidate)
            if len(compact_logs) >= max_candidates:
                break
        if len(compact_logs) >= max_candidates:
            break
    if compact_logs:
        extracted['logs'] = compact_logs
        extracted['logs_count'] = sum(len(rows) for _, rows in sources)

    stats = payload.get('stats')
    if isinstance(stats, dict):
        compact_stats = _generic_candidate_from_item(stats)
        if not compact_stats:
            compact_stats = {}
            for service, values in stats.items():
                if not isinstance(values, dict):
                    continue
                candidate = _generic_candidate_from_item(values)
                if candidate:
                    compact_stats[service] = candidate
        if compact_stats:
            extracted['stats'] = compact_stats
    return extracted


def _extract_system_monitor_followup(payload: dict) -> dict:
    snapshot = {}
    for field in ('cpu', 'uptime', 'top_process'):
        value = payload.get(field)
        if not isinstance(value, dict):
            continue
        compact = _generic_candidate_from_item(value)
        if compact:
            snapshot[field] = compact

    memory = payload.get('memory')
    if isinstance(memory, dict):
        compact_memory = {}
        for field in ('ram', 'swap'):
            value = memory.get(field)
            if not isinstance(value, dict):
                continue
            compact = _generic_candidate_from_item(value)
            if compact:
                compact_memory[field] = compact
        if compact_memory:
            snapshot['memory'] = compact_memory
    return {'system_snapshot': snapshot} if snapshot else {}


def _extract_bounded_content_followup(
    key: str,
    payload: dict,
    max_candidates: int,
) -> dict:
    """Dedicated excerpts for result bodies that the scalar fallback omits."""
    extracted = {}

    text_fields = {
        'analyze_image': (
            ('analysis', 'analysis', FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS),
        ),
        'canvas': (
            ('content', 'content_excerpt', FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS),
        ),
        'stash': (
            ('content', 'content_excerpt', FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS),
        ),
        'pdf_read': (
            ('text', 'text_excerpt', FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS),
        ),
        'execute_bash': (
            ('stdout', 'stdout_excerpt', FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS),
            ('stderr', 'stderr_excerpt', FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS),
        ),
        'ssh_remote': (
            ('stdout', 'stdout_excerpt', FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS),
            ('stderr', 'stderr_excerpt', FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS),
            ('output', 'output_excerpt', FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS),
            ('upgrade_output', 'upgrade_output_excerpt', FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS),
        ),
        'docker_control': (
            ('logs', 'logs_excerpt', FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS),
            ('output', 'output_excerpt', FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS),
        ),
        'phone_call': (
            ('summary', 'summary', 1200),
            ('transcript', 'transcript_excerpt', FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS),
            ('follow_up_hints', 'follow_up_hints', 1200),
        ),
        'opencode': (
            ('opencode_result', 'result_preview', FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS),
        ),
        'api_call': (
            ('response', 'response_preview', FOLLOWUP_CONTENT_EXCERPT_MAX_CHARS),
        ),
        'system_monitor': (
            ('summary_markdown', 'summary_markdown_excerpt', 1200),
            ('issue_summary', 'issue_summary', 600),
        ),
        'search_docs': (
            ('documentation', 'documentation_excerpt', 1200),
        ),
    }

    for source_field, target_field, limit in text_fields.get(key, ()):
        value = payload.get(source_field)
        if value in (None, '', [], {}):
            continue
        if not isinstance(value, str):
            preview = _bounded_structured_followup_value(
                value,
                max_chars=limit,
            )
            if preview not in (None, '', [], {}):
                extracted[target_field] = preview
            continue
        excerpt = _bounded_content_excerpt(value, max_chars=limit)
        if excerpt:
            extracted[target_field] = excerpt

    if key == 'api_call' and isinstance(payload.get('response'), dict):
        response_keys = [
            field
            for field in payload['response']
            if isinstance(field, str)
            and not _nested_followup_field_is_sensitive(field)
        ]
        extracted['response_keys_count'] = len(response_keys)
        extracted['response_keys'] = response_keys[:20]
        if len(response_keys) > 20:
            extracted['response_keys_truncated'] = True

    if key == 'analyze_image':
        sources = payload.get('sources')
        if isinstance(sources, list):
            extracted['sources'] = [
                _truncate_followup_text(
                    str(source),
                    GENERIC_FOLLOWUP_URL_MAX_CHARS,
                )
                for source in sources[:max_candidates]
                if source not in (None, '')
            ]
            if len(sources) > max_candidates:
                extracted['sources_truncated'] = True
                extracted['sources_count'] = len(sources)

    if key == 'query_service_logs':
        extracted.update(
            _extract_query_service_logs_followup(payload, max_candidates)
        )

    if key == 'system_monitor':
        extracted.update(_extract_system_monitor_followup(payload))

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
        request_context = _extract_generic_tool_request(data, key)
        if (
            key == 'spotify'
            and isinstance(value, list)
            and value
            and all(isinstance(run, dict) for run in value)
        ):
            extracted = _extract_spotify_runs_followup(data, value, max_candidates)
            if extracted:
                followup[key] = extracted
            continue
        if key == 'manage_intel':
            extracted = _extract_manage_intel_followup(data, max_candidates)
            if request_context:
                extracted = extracted or {}
                extracted.setdefault('request', request_context)
            if extracted:
                followup[key] = extracted
            continue
        if key == 'text_summarizer':
            extracted = extract_text_summarizer_followup(value, max_candidates)
            if request_context:
                extracted = extracted or {}
                extracted.setdefault('request', request_context)
            if extracted:
                followup[key] = extracted
            continue
        if key == 'workflow':
            workflow_value = workflow_result_payload({'workflow': value})
            if workflow_value:
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
                if request_context:
                    workflow_meta['request'] = request_context
                if workflow_meta:
                    followup['workflow'] = workflow_meta
                component_results = workflow_step_tool_results(workflow_value)
                for component_name, component_value in component_results.items():
                    if component_name in _AMAZON_FOLLOWUP_TOOL_NAMES:
                        component_followup = extract_followup_data(
                            {component_name: component_value},
                            max_candidates=max_candidates,
                        )
                        if component_followup:
                            followup['serpapi_amazon_search'] = component_followup.get(
                                component_name,
                                component_followup.get('serpapi_amazon_search'),
                            )
                        continue
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
        if key in _AMAZON_FOLLOWUP_TOOL_NAMES:
            extracted = _extract_serpapi_followup(value, max_candidates)
            if extracted:
                followup['serpapi_amazon_search'] = extracted
            continue
        # List-shaped tool payloads: normalize to dict with results[] (no per-tool registry).
        if isinstance(value, list):
            if not value:
                if request_context:
                    followup[key] = {'request': request_context}
                continue
            if all(isinstance(x, dict) for x in value):
                if key in _PRESERVE_RUN_LIST_FOR_DEDICATED_BRANCHES:
                    value = {'results': value}
                else:
                    value = _collapse_repeated_tool_runs(value) or {'results': value}
            else:
                if request_context:
                    followup[key] = {'request': request_context}
                continue
        if not isinstance(value, dict):
            if request_context:
                followup[key] = {'request': request_context}
            continue

        payload = value.get('data') if isinstance(value.get('data'), dict) else value
        # Auto-stashed web uploads are also stored under top-level "stash".
        # Keep skipping those lightweight upload refs here, but preserve actual
        # stash tool outputs so later follow-up turns can reference them.
        if key == 'stash' and payload.get('stash_ref') and not any(
            marker in payload for marker in ('ref', 'content', 'mime_type', 'size_bytes', 'name')
        ):
            continue
        if (
            key == 'stash'
            and payload.get('stash_ref')
            and payload.get('tool_origin') == 'web_upload'
        ):
            continue

        extracted = {}
        if (
            request_context
            and key != 'spotify'
            and not key.startswith('mcp_')
        ):
            extracted['request'] = request_context

        # Extract stash_ref from nested 'saved' object (common pattern)
        if 'saved' in payload and isinstance(payload['saved'], dict):
            saved = payload['saved']
            if saved.get('stash_ref'):
                extracted['stash_ref'] = saved['stash_ref']
            if saved.get('filename'):
                extracted['filename'] = saved['filename']

        # Direct stash_ref on the object
        if payload.get('stash_ref'):
            extracted['stash_ref'] = payload['stash_ref']

        # Some tools use 'ref' instead of 'stash_ref' (e.g. pdf_create, stash)
        # Include it as-is so the LLM sees the actual field name the tool uses
        if payload.get('ref') and 'stash_ref' not in extracted:
            extracted['ref'] = payload['ref']

        # Get tool-specific fields
        fields_to_extract = FOLLOWUP_FIELDS.get(key, [])
        for field in fields_to_extract:
            if field in extracted:
                continue  # Already got it above
            field_value = payload.get(field)
            if field_value not in (None, '', [], {}):
                extracted[field] = field_value

        if key == 'spotify':
            extracted.update(
                _extract_spotify_followup(data, payload, max_candidates)
            )
        elif key.startswith('mcp_brave_search_'):
            extracted.update(
                _extract_brave_search_followup(
                    data,
                    key,
                    value,
                    max_candidates,
                )
            )
        elif key == 'mcp_duckduckgo_search':
            extracted.update(
                _extract_duckduckgo_search_followup(data, value, max_candidates)
            )
        elif key in ('mcp_duckduckgo_fetch_content', 'mcp_fetch_fetch'):
            extracted.update(_extract_mcp_fetch_followup(data, key, value))

        if payload.get('runs_count') and 'runs_count' not in extracted:
            extracted['runs_count'] = payload['runs_count']

        # Always include provider if present (needed for follow-ups)
        if payload.get('provider') and 'provider' not in extracted:
            extracted['provider'] = payload['provider']

        # Preserve compact memory refs for follow-up turns like
        # "forget those", "update that birthday memory", or "show me the other one".
        extracted.update(_extract_memory_candidates(payload, max_candidates))
        extracted.update(_extract_memory_mutation_refs(payload, max_candidates))
        extracted.update(
            _extract_bounded_content_followup(key, payload, max_candidates)
        )

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
                    for field in ('reviews', 'categories', 'neighborhoods', 'open_state'):
                        field_value = first.get(field)
                        if field_value not in (None, '', [], {}):
                            extracted[field] = field_value
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
                    if item.get('rating') is not None:
                        candidate['rating'] = item['rating']
                    if item.get('reviews') is not None:
                        candidate['reviews'] = item['reviews']
                    if item.get('price'):
                        candidate['price'] = item['price']
                    if item.get('address'):
                        candidate['address'] = item['address']
                    if item.get('categories'):
                        candidate['categories'] = item['categories']
                    if item.get('neighborhoods'):
                        candidate['neighborhoods'] = item['neighborhoods']
                    if item.get('open_state'):
                        candidate['open_state'] = item['open_state']
                    if item.get('snippet'):
                        candidate['snippet'] = _truncate_followup_text(
                            str(item['snippet']), 500
                        )
                    if item.get('thumbnail'):
                        candidate['thumbnail'] = item['thumbnail']
                    candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

            review_data = value.get('review_data')
            if isinstance(review_data, dict):
                compact_reviews = []
                for review in (review_data.get('reviews') or [])[:max_candidates]:
                    if not isinstance(review, dict):
                        continue
                    compact_review = {}
                    for field in ('rating', 'date', 'user_name', 'user_location'):
                        field_value = review.get(field)
                        if field_value not in (None, ''):
                            compact_review[field] = field_value
                    if review.get('text'):
                        compact_review['text'] = _truncate_followup_text(
                            str(review['text']), 700
                        )
                    if compact_review:
                        compact_reviews.append(compact_review)
                extracted['review_data'] = {
                    field: review_data[field]
                    for field in ('place_id', 'business', 'total_results', 'results_count')
                    if review_data.get(field) not in (None, '')
                }
                if compact_reviews:
                    extracted['review_data']['reviews'] = compact_reviews

        if key == 'serpapi_search_index':
            results = payload.get('results') or payload.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = payload.get('results_count', len(results))
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    candidate = {
                        field: item[field]
                        for field in (
                            'position', 'title', 'url', 'displayed_link',
                            'date', 'language', 'image_url', 'source',
                        )
                        if item.get(field) not in (None, '', [], {})
                    }
                    if item.get('snippet'):
                        candidate['snippet'] = _truncate_followup_text(
                            str(item['snippet']), 700
                        )
                    sitelinks = item.get('sitelinks')
                    if isinstance(sitelinks, list) and sitelinks:
                        candidate['sitelinks'] = [
                            {
                                field: link[field]
                                for field in ('title', 'url', 'date')
                                if link.get(field) not in (None, '')
                            }
                            for link in sitelinks[:5]
                            if isinstance(link, dict)
                            and (link.get('title') or link.get('url'))
                        ]
                    if candidate.get('title') or candidate.get('url'):
                        candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

            related = payload.get('related_searches')
            if isinstance(related, list) and related:
                extracted['related_searches'] = [
                    _truncate_followup_text(str(query), 300)
                    for query in related[:max_candidates]
                    if str(query).strip()
                ]

            pagination = payload.get('pagination')
            if isinstance(pagination, dict):
                compact_pagination = {
                    field: pagination[field]
                    for field in ('start', 'num_results', 'has_more', 'next_start')
                    if pagination.get(field) not in (None, '')
                    or field == 'has_more'
                }
                if compact_pagination:
                    extracted['pagination'] = compact_pagination

        if key == 'serpapi_google_images_light':
            results = payload.get('results') or payload.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = payload.get('results_count', len(results))
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    candidate = {
                        field: item[field]
                        for field in (
                            'position', 'title', 'url', 'original', 'image_url',
                            'thumbnail', 'serpapi_thumbnail', 'source',
                            'source_url', 'license_details_url', 'source_logo',
                            'original_width', 'original_height',
                            'related_content_id', 'is_product', 'in_stock', 'unsafe',
                            'untrusted_external_content',
                        )
                        if item.get(field) not in (None, '', [], {})
                    }
                    if candidate.get('image_url') or candidate.get('url'):
                        candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

            pagination = payload.get('pagination')
            if isinstance(pagination, dict):
                compact_pagination = {
                    field: pagination[field]
                    for field in (
                        'current', 'start', 'has_more', 'next_start',
                        'previous_start',
                    )
                    if pagination.get(field) not in (None, '')
                    or field == 'has_more'
                }
                if compact_pagination:
                    extracted['pagination'] = compact_pagination

        if key == 'serpapi_google_news_light':
            results = payload.get('results') or payload.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = payload.get('results_count', len(results))
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    candidate = {
                        field: item[field]
                        for field in (
                            'position', 'title', 'url', 'source', 'date',
                            'thumbnail',
                        )
                        if item.get(field) not in (None, '', [], {})
                    }
                    if item.get('snippet'):
                        candidate['snippet'] = _truncate_followup_text(
                            str(item['snippet']), 700
                        )
                    if candidate.get('title') or candidate.get('url'):
                        candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

            top_story_groups = payload.get('top_stories')
            if isinstance(top_story_groups, list) and top_story_groups:
                compact_groups = []
                for group in top_story_groups[:max_candidates]:
                    if not isinstance(group, dict):
                        continue
                    compact_group = {
                        field: group[field]
                        for field in (
                            'position', 'title', 'stories_count',
                            'provider_stories_count',
                        )
                        if group.get(field) not in (None, '')
                    }
                    stories = []
                    for story in (group.get('stories') or [])[:max_candidates]:
                        if not isinstance(story, dict):
                            continue
                        compact_story = {
                            field: story[field]
                            for field in ('position', 'title', 'url', 'source', 'date')
                            if story.get(field) not in (None, '')
                        }
                        if compact_story.get('title') or compact_story.get('url'):
                            stories.append(compact_story)
                    if stories:
                        compact_group['stories'] = stories
                    if compact_group:
                        compact_groups.append(compact_group)
                if compact_groups:
                    extracted['top_stories'] = compact_groups

            pagination = payload.get('pagination')
            if isinstance(pagination, dict):
                compact_pagination = {
                    field: pagination[field]
                    for field in (
                        'current', 'start', 'has_more', 'next_start',
                        'previous_start',
                    )
                    if pagination.get(field) not in (None, '')
                    or field == 'has_more'
                }
                if compact_pagination:
                    extracted['pagination'] = compact_pagination

        if key == 'serpapi_google_shopping_light':
            results = payload.get('results') or payload.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = payload.get('results_count', len(results))
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    candidate = {
                        field: item[field]
                        for field in (
                            'position', 'provider_position', 'section', 'category',
                            'title', 'url', 'merchant_url', 'product_link',
                            'product_id', 'source', 'price', 'extracted_price',
                            'old_price', 'extracted_old_price', 'rating', 'reviews',
                            'delivery', 'thumbnail', 'serpapi_thumbnail', 'tag',
                            'block_position', 'multiple_sources',
                        )
                        if item.get(field) not in (None, '', [], {})
                    }
                    extensions = item.get('extensions')
                    if isinstance(extensions, list) and extensions:
                        candidate['extensions'] = [
                            _truncate_followup_text(str(extension), 200)
                            for extension in extensions[:8]
                            if str(extension).strip()
                        ]
                    installment = item.get('installment')
                    if isinstance(installment, dict):
                        compact_installment = {
                            field: installment[field]
                            for field in ('price', 'extracted_price', 'period')
                            if installment.get(field) not in (None, '')
                        }
                        if compact_installment:
                            candidate['installment'] = compact_installment
                    if candidate.get('title') or candidate.get('url'):
                        candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

            lowest = payload.get('lowest_returned_price')
            if isinstance(lowest, dict):
                compact_lowest = {
                    field: lowest[field]
                    for field in (
                        'position', 'title', 'url', 'source', 'price',
                        'extracted_price',
                    )
                    if lowest.get(field) not in (None, '')
                }
                if compact_lowest:
                    extracted['lowest_returned_price'] = compact_lowest

            pagination = payload.get('pagination')
            if isinstance(pagination, dict):
                compact_pagination = {
                    field: pagination[field]
                    for field in (
                        'current', 'start', 'has_more', 'next_start',
                        'previous_start',
                    )
                    if pagination.get(field) not in (None, '')
                    or field == 'has_more'
                }
                if compact_pagination:
                    extracted['pagination'] = compact_pagination

        if key == 'serpapi_google_sports':
            results = payload.get('results') or payload.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = payload.get('results_count', len(results))
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    candidate = {
                        field: item[field]
                        for field in (
                            'kind', 'position', 'group', 'division', 'rank',
                            'title', 'name', 'url', 'serpapi_link', 'kgmid', 'thumbnail',
                            'status', 'status_original', 'date', 'time',
                            'start_time', 'end_time', 'tournament', 'stadium',
                            'league_movement', 'highlighted', 'player_position',
                            'jersey_number', 'team', 'value',
                        )
                        if item.get(field) not in (None, '', [], {})
                    }
                    for nested_field, nested_limit in (
                        ('teams', 4),
                        ('stats', 12),
                        ('highlights', 4),
                        ('more_info', 8),
                    ):
                        nested = item.get(nested_field)
                        if isinstance(nested, list) and nested:
                            candidate[nested_field] = nested[:nested_limit]
                    for nested_field in ('league', 'venue'):
                        nested = item.get(nested_field)
                        if isinstance(nested, dict) and nested:
                            candidate[nested_field] = nested
                    watch = item.get('watch')
                    if isinstance(watch, dict) and watch:
                        candidate['watch'] = watch
                    if candidate.get('title') or candidate.get('name') or candidate.get('kgmid'):
                        candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

            seasons = payload.get('seasons')
            if isinstance(seasons, list) and seasons:
                extracted['seasons'] = [
                    {
                        field: item[field]
                        for field in ('name', 'kgmid', 'url', 'selected', 'league')
                        if item.get(field) not in (None, '', [], {})
                    }
                    for item in seasons[:12]
                    if isinstance(item, dict)
                ]

            team_stats = payload.get('team_stats')
            if isinstance(team_stats, dict):
                extracted['team_stats'] = {
                    str(field): value
                    for field, value in list(team_stats.items())[:20]
                    if value not in (None, '', [], {})
                }
            elif isinstance(team_stats, list):
                extracted['team_stats'] = team_stats[:12]

        if key in {'trakt_movies', 'trakt_tv_shows'}:
            results = payload.get('candidates') or payload.get('results') or payload.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = payload.get('results_count', len(results))
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    candidate = {
                        field: item[field]
                        for field in (
                            'title', 'year', 'ids', 'trakt_url', 'imdb_url',
                            'tagline', 'runtime_minutes', 'rating', 'votes',
                            'episode_runtime_minutes', 'network', 'status',
                            'show_type', 'aired_episodes', 'first_aired', 'airs',
                            'genres', 'subgenres', 'certification', 'trailer_url',
                            'source_signals', 'related_to', 'match_score',
                            'streaming_signal', 'videos',
                        )
                        if item.get(field) not in (None, '', [], {})
                    }
                    if item.get('overview'):
                        candidate['overview'] = _truncate_followup_text(
                            str(item['overview']), 700
                        )
                    if candidate.get('title') or candidate.get('trakt_url'):
                        candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

        if key in {'tmdb_movies', 'tmdb_tv_shows'}:
            media_key = 'show' if key == 'tmdb_tv_shows' else 'movie'
            media = payload.get(media_key)
            if isinstance(media, dict):
                extracted[media_key] = {
                    field: media[field]
                    for field in (
                        'id', 'tmdb_id', 'title', 'original_title', 'release_date',
                        'first_air_date', 'last_air_date', 'year', 'overview',
                        'tagline', 'runtime_minutes', 'episode_runtime_minutes',
                        'episode_run_times', 'rating', 'votes', 'genres',
                        'certification', 'content_rating', 'status', 'show_type',
                        'number_of_seasons', 'number_of_episodes', 'created_by',
                        'networks', 'origin_countries', 'next_episode', 'last_episode',
                        'collection',
                        'tmdb_url', 'imdb_id', 'imdb_url', 'poster_url',
                        'poster_thumbnail', 'poster_original_url', 'backdrop_url',
                        'backdrop_thumbnail', 'backdrop_original_url',
                    )
                    if media.get(field) not in (None, '', [], {})
                }

            results = payload.get('results') or payload.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = payload.get('results_count', len(results))
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    candidate = {
                        field: item[field]
                        for field in (
                            'id', 'tmdb_id', 'title', 'name', 'year', 'release_date',
                            'first_air_date', 'runtime_minutes',
                            'episode_runtime_minutes', 'rating', 'votes', 'genres',
                            'certification', 'content_rating', 'status', 'show_type',
                            'number_of_seasons', 'number_of_episodes', 'networks',
                            'tmdb_url', 'imdb_url', 'source_signal',
                            'image_type', 'width', 'height', 'language',
                            'thumbnail', 'image_url', 'original_url', 'source_url',
                            'character', 'job', 'profile_thumbnail', 'profile_url',
                            'url', 'site', 'type', 'official', 'published_at',
                        )
                        if item.get(field) not in (None, '', [], {})
                    }
                    if item.get('overview'):
                        candidate['overview'] = _truncate_followup_text(
                            str(item['overview']), 700
                        )
                    if candidate.get('title') or candidate.get('name') or candidate.get('image_url'):
                        candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

            for source_key in (
                'images', 'cast', 'crew', 'videos', 'recommendations', 'similar', 'seasons'
            ):
                rows = payload.get(source_key)
                if isinstance(rows, list) and rows:
                    extracted[source_key] = rows[:max_candidates]

        if key == 'serpapi_google_local':
            results = payload.get('results') or payload.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = payload.get('results_count', len(results))
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    candidate = {
                        field: item[field]
                        for field in (
                            'position', 'title', 'url', 'website',
                            'directions_url', 'google_maps_url',
                            'place_id_search', 'place_id',
                            'provider_id', 'rating', 'reviews',
                            'reviews_original', 'price', 'type', 'address',
                            'hours', 'description', 'gps_coordinates',
                            'thumbnail', 'thumbnail_small', 'extensions',
                            'links', 'service_options', 'sponsored',
                        )
                        if item.get(field) not in (None, '', [], {})
                    }
                    if candidate.get('title') or candidate.get('url'):
                        candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

            ads = payload.get('ads')
            if isinstance(ads, list) and ads:
                compact_ads = []
                for item in ads[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    ad = {
                        field: item[field]
                        for field in (
                            'position', 'title', 'url', 'website',
                            'directions_url', 'google_maps_url', 'place_id',
                            'rating', 'reviews',
                            'price', 'type', 'address', 'hours', 'description',
                            'gps_coordinates', 'thumbnail', 'links',
                            'service_options', 'sponsored', 'ad_title',
                            'displayed_link',
                        )
                        if item.get(field) not in (None, '', [], {})
                    }
                    if ad.get('title') or ad.get('url'):
                        compact_ads.append(ad)
                if compact_ads:
                    extracted['ads'] = compact_ads

            discover_more = payload.get('discover_more_places')
            if isinstance(discover_more, list) and discover_more:
                extracted['discover_more_places'] = [
                    {
                        field: item[field]
                        for field in ('title', 'url', 'thumbnail', 'places', 'images')
                        if item.get(field) not in (None, '', [], {})
                    }
                    for item in discover_more[:max_candidates]
                    if isinstance(item, dict)
                    and (item.get('title') or item.get('url'))
                ]

            pagination = payload.get('pagination')
            if isinstance(pagination, dict):
                compact_pagination = {
                    field: pagination[field]
                    for field in (
                        'current', 'start', 'has_more', 'next_start',
                        'previous_start',
                    )
                    if pagination.get(field) not in (None, '')
                    or field == 'has_more'
                }
                if compact_pagination:
                    extracted['pagination'] = compact_pagination

        if key == 'serpapi_google_local_services':
            results = payload.get('results') or payload.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = payload.get('results_count', len(results))
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    candidate = {
                        field: item[field]
                        for field in (
                            'position', 'title', 'url', 'website', 'rating',
                            'reviews', 'rating_stars', 'phone', 'badge', 'type',
                            'address', 'service_area', 'years_in_business',
                            'bookings_nearby', 'thumbnail', 'images',
                            'hours_current', 'hours_week', 'checks',
                            'description', 'services', 'covid_measures',
                            'at_this_place', 'cid', 'bid', 'pid',
                        )
                        if item.get(field) not in (None, '', [], {})
                    }
                    if candidate.get('title') or candidate.get('url'):
                        candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

            detail = payload.get('detail')
            if isinstance(detail, dict) and detail:
                extracted['detail'] = {
                    field: detail[field]
                    for field in (
                        'position', 'title', 'url', 'website', 'rating',
                        'reviews', 'rating_stars', 'phone', 'badge', 'type',
                        'address', 'service_area', 'years_in_business',
                        'bookings_nearby', 'thumbnail', 'images',
                        'hours_current', 'hours_week', 'checks',
                        'description', 'services', 'covid_measures',
                        'at_this_place', 'cid', 'bid', 'pid',
                    )
                    if detail.get(field) not in (None, '', [], {})
                }

        if key == 'serpapi_google_trends':
            results = payload.get('results') or payload.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = payload.get('results_count', len(results))
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    candidate = {
                        field: item[field]
                        for field in (
                            'title', 'query', 'url', 'trend_type', 'topic_id',
                            'topic_type', 'location', 'geo', 'latest_date',
                            'latest_value', 'previous_value',
                            'change_from_previous', 'change_over_period',
                            'direction', 'average_value', 'peak_value',
                            'peak_date', 'value', 'extracted_value', 'top_query',
                            'top_value', 'values',
                        )
                        if item.get(field) not in (None, '', [], {})
                    }
                    if candidate:
                        candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

            averages = payload.get('averages')
            if isinstance(averages, list) and averages:
                extracted['averages'] = [
                    {
                        field: item[field]
                        for field in ('query', 'value')
                        if item.get(field) not in (None, '')
                    }
                    for item in averages[:max_candidates]
                    if isinstance(item, dict)
                ]

            timeline = payload.get('timeline_data')
            if isinstance(timeline, list) and timeline:
                extracted['latest_timeline'] = [
                    {
                        field: point[field]
                        for field in ('date', 'timestamp', 'values')
                        if point.get(field) not in (None, '', [], {})
                    }
                    for point in timeline[-3:]
                    if isinstance(point, dict)
                ]

        if key == 'serpapi_google_trending_now':
            action = str(payload.get('action') or 'trending_now').strip().lower()
            results = payload.get('results') or payload.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = payload.get('results_count', len(results))
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    if action == 'news':
                        candidate = {
                            field: item[field]
                            for field in (
                                'position', 'title', 'url', 'source', 'date',
                                'thumbnail',
                            )
                            if item.get(field) not in (None, '')
                        }
                    else:
                        candidate = {
                            field: item[field]
                            for field in (
                                'position', 'title', 'query', 'start_timestamp',
                                'start_time', 'end_timestamp', 'end_time',
                                'active', 'search_volume', 'increase_percentage',
                                'categories', 'category_names', 'trend_breakdown',
                                'google_trends_url', 'trends_api_url',
                                'news_page_token', 'news_api_url',
                            )
                            if item.get(field) not in (None, '', [], {})
                            or field == 'active' and item.get(field) is False
                        }
                    if candidate:
                        candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

        if key == 'serpapi_tripadvisor':
            action = str(payload.get('action') or 'search').strip().lower()
            results = payload.get('results') or payload.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = payload.get('results_count', len(results))
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    if action == 'reviews':
                        candidate = {
                            field: item[field]
                            for field in (
                                'title', 'rating', 'date', 'trip_type',
                                'author_name', 'review_id', 'url',
                            )
                            if item.get(field) not in (None, '')
                        }
                        if item.get('text'):
                            candidate['text'] = _truncate_followup_text(
                                str(item['text']), 700
                            )
                    else:
                        candidate = {
                            field: item[field]
                            for field in (
                                'title', 'place_id', 'place_type', 'url',
                                'rating', 'reviews', 'location', 'address',
                                'thumbnail',
                            )
                            if item.get(field) not in (None, '', [], {})
                        }
                        if item.get('description'):
                            candidate['description'] = _truncate_followup_text(
                                str(item['description']), 500
                            )
                    if candidate:
                        candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

            place = payload.get('place')
            if isinstance(place, dict):
                compact_place = {
                    field: place[field]
                    for field in (
                        'title', 'place_id', 'place_type', 'url', 'rating',
                        'reviews', 'ranking', 'address', 'phone', 'website',
                        'price_level', 'categories', 'amenities',
                        'gps_coordinates', 'thumbnail',
                    )
                    if place.get(field) not in (None, '', [], {})
                }
                if place.get('description'):
                    compact_place['description'] = _truncate_followup_text(
                        str(place['description']), 700
                    )
                if compact_place:
                    extracted['place'] = compact_place

            interesting = payload.get('interesting_places')
            if isinstance(interesting, list) and interesting:
                compact_interesting = []
                for item in interesting[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    compact = {
                        field: item[field]
                        for field in (
                            'title', 'place_id', 'place_type', 'url', 'rating',
                            'reviews', 'distance', 'address', 'categories',
                            'additional_info', 'price', 'group', 'thumbnail',
                        )
                        if item.get(field) not in (None, '', [], {})
                    }
                    if compact:
                        compact_interesting.append(compact)
                if compact_interesting:
                    extracted['interesting_places'] = compact_interesting

            detail_data = payload.get('detail_data')
            if isinstance(detail_data, dict):
                compact_detail = {
                    field: detail_data[field]
                    for field in ('place_id', 'interesting_places_count')
                    if detail_data.get(field) not in (None, '')
                }
                detail_place = detail_data.get('place')
                if isinstance(detail_place, dict):
                    compact_detail['place'] = {
                        field: detail_place[field]
                        for field in (
                            'title', 'place_id', 'place_type', 'url', 'rating',
                            'reviews', 'ranking', 'address', 'price_level',
                            'categories', 'amenities', 'thumbnail',
                        )
                        if detail_place.get(field) not in (None, '', [], {})
                    }
                    if detail_place.get('description'):
                        compact_detail['place']['description'] = _truncate_followup_text(
                            str(detail_place['description']), 700
                        )
                detail_interesting = detail_data.get('interesting_places')
                if isinstance(detail_interesting, list) and detail_interesting:
                    compact_detail['interesting_places'] = [
                        {
                            field: item[field]
                            for field in (
                                'title', 'place_id', 'place_type', 'url',
                                'rating', 'reviews', 'distance', 'group',
                            )
                            if item.get(field) not in (None, '', [], {})
                        }
                        for item in detail_interesting[:max_candidates]
                        if isinstance(item, dict)
                    ]
                if compact_detail:
                    extracted['detail_data'] = compact_detail

            review_data = payload.get('review_data')
            review_source = review_data if isinstance(review_data, dict) else payload
            review_rows = review_source.get('reviews') if isinstance(review_source, dict) else None
            if isinstance(review_rows, list) and review_rows:
                compact_reviews = []
                for item in review_rows[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    compact = {
                        field: item[field]
                        for field in (
                            'title', 'rating', 'date', 'trip_type',
                            'author_name', 'review_id', 'url',
                        )
                        if item.get(field) not in (None, '')
                    }
                    if item.get('text'):
                        compact['text'] = _truncate_followup_text(
                            str(item['text']), 700
                        )
                    if compact:
                        compact_reviews.append(compact)
                if compact_reviews:
                    if isinstance(review_data, dict):
                        extracted['review_data'] = {
                            field: review_data[field]
                            for field in ('place_id', 'total_reviews', 'results_count')
                            if review_data.get(field) not in (None, '')
                        }
                        extracted['review_data']['reviews'] = compact_reviews
                    else:
                        extracted['reviews'] = compact_reviews

        # --- Travel Explore: destination identity drives later tool handoffs ---
        if key == 'serpapi_travel_explore':
            results = payload.get('results') or payload.get('top_results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = payload.get('results_count', len(results))
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    candidate = {
                        field: item[field]
                        for field in (
                            'position', 'destination_id', 'name', 'country',
                            'gps_coordinates', 'airport_code', 'airport_location',
                            'airport_location_id', 'start_date', 'end_date',
                            'nights', 'flight_price', 'hotel_price',
                            'flight_duration_minutes', 'flight_duration_display',
                            'number_of_stops', 'stops_label', 'airline',
                            'airline_code', 'ground_transfer_minutes',
                            'ground_transfer_display', 'thumbnail',
                            'google_travel_url',
                        )
                        if item.get(field) not in (None, '', [], {})
                    }
                    if candidate:
                        candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

        # --- flight_search: itineraries are deeply nested (segments, layovers) ---
        # Keep the shortlist needed to compare or refer to a specific option on
        # a later turn ("compare the second one", "when does the cheapest land?").
        if key == 'flight_search':
            results = payload.get('results') or []
            if isinstance(results, list) and results:
                extracted['results_count'] = payload.get('results_count', len(results))
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    candidate = {}
                    for field in (
                        'price', 'departure_time', 'arrival_time', 'duration_display',
                        'stops_label', 'departure_airport', 'arrival_airport',
                    ):
                        field_value = item.get(field)
                        if field_value not in (None, '', [], {}):
                            candidate[field] = field_value
                    airlines = item.get('airlines')
                    if isinstance(airlines, list) and airlines:
                        candidate['airlines'] = ', '.join(str(name) for name in airlines[:3])
                    numbers = item.get('flight_numbers')
                    if isinstance(numbers, list) and numbers:
                        candidate['flight_numbers'] = ', '.join(str(num) for num in numbers[:4])
                    if candidate:
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

        if key == 'brave_llm_context':
            grounding = value.get('grounding') if isinstance(value.get('grounding'), dict) else {}
            sources_meta = value.get('sources') if isinstance(value.get('sources'), dict) else {}
            sources = []
            seen_urls: set[str] = set()
            source_limit = max_candidates

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
                    record['age'] = _truncate_followup_text(str(age[0]), 120)
                elif isinstance(age, str) and age.strip():
                    record['age'] = _truncate_followup_text(age.strip(), 120)
                snippets = item.get('snippets')
                if isinstance(snippets, list) and snippets:
                    record['snippet'] = _truncate_followup_text(
                        str(snippets[0]),
                        500,
                    )
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
            generic = _extract_generic_followup(
                payload,
                max_candidates,
                include_dynamic_scalars=key not in FOLLOWUP_FIELDS,
            )
            for field, generic_value in generic.items():
                if field not in extracted:
                    extracted[field] = generic_value

        # @TOOL_CONFIG: video URL expiration — provider URLs have time limits
        # xAI ~4h, OpenAI 60min
        if key == 'generate_video' and extracted.get('video_url'):
            try:
                saved = payload.get('saved', {})
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
            for item in stash['uploaded_images'][:max(max_candidates, 6)]:
                if not isinstance(item, dict) or not item.get('stash_ref'):
                    continue
                compact_upload = {
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
                }
                uploaded_images.append({
                    field: field_value
                    for field, field_value in compact_upload.items()
                    if field_value not in (None, '')
                })
                if item.get('vision_analysis'):
                    uploaded_images[-1]['vision_analysis'] = _bounded_content_excerpt(
                        item.get('vision_analysis'),
                        max_chars=1200,
                    )

        compact_primary = {
            'stash_ref': stash.get('stash_ref'),
            'space_id': stash.get('space_id'),
            'file_id': stash.get('file_id'),
            'filename': stash.get('filename'),
            'mime_type': stash.get('mime_type'),
            'action': stash.get('action'),
            'tool_origin': stash.get('tool_origin'),
            'has_vision_analysis': bool(stash.get('has_vision_analysis')),
        }
        followup['uploaded_image'] = {
            field: field_value
            for field, field_value in compact_primary.items()
            if field_value not in (None, '')
        }
        if stash.get('vision_analysis'):
            followup['uploaded_image']['vision_analysis'] = _bounded_content_excerpt(
                stash.get('vision_analysis'),
            )
        if uploaded_images:
            followup['uploaded_images'] = uploaded_images

    # Extract error details (enables "what went wrong?" follow-ups)
    if data.get('_error') and isinstance(data['_error'], dict):
        err = data['_error']
        error_info = {
            'tool_failed': err.get('tool_failed'),
            'message': _truncate_followup_text(
                str(err.get('message', '')),
                500,
            ),
            'retries': err.get('retries', 0),
        }
        # Include tool arguments so LLM can see what was passed when it failed
        if isinstance(err.get('tool_args'), dict):
            compact_args = _compact_request_arguments(err['tool_args'])
            if compact_args:
                error_info['tool_args'] = compact_args
        followup['error'] = error_info

    if not followup:
        return None
    _annotate_candidate_truncation(followup)
    return _normalize_strict_json_value(followup)
