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
from datetime import datetime

# URL extractor for Brave MCP search results whose content is buried inside
# raw[].text JSON blobs and full_text. We only need the URL list for
# "already searched" hints on follow-up turns, not the surrounding content.
_BRAVE_URL_RE = re.compile(r'https?://[^\s"\'<>)]+')

# Tools whose follow-up shape is handled by a dedicated branch below. Listed
# here so the generic results[]/items[] fallback skips them (otherwise it
# would overwrite or duplicate what the dedicated branch produced).
_DEDICATED_FOLLOWUP_BRANCHES = (
    'serpapi_search',
    'serpapi_youtube_search',
    'serpapi_yelp_search',
    'crawl_url',
    'mcp_brave_search_brave_web_search',
    'mcp_brave_search_brave_news_search',
    'mcp_brave_search_brave_local_search',
    'brave_llm_context',
)

# Follow-up context: keep orchestrator history compact.
FOLLOWUP_DEFAULT_MAX_CANDIDATES = 5
# Completion Guard / effective evidence: allow ranking follow-ups without re-querying.
FOLLOWUP_EVIDENCE_MAX_CANDIDATES = 12
# Keep abstractive summaries available for follow-up turns without dragging
# whole transcript-sized artifacts through every router prompt.
FOLLOWUP_SUMMARY_MAX_CHARS = 6000
_FOLLOWUP_TRUNCATION_SUFFIX = "\n...[summary truncated for follow-up context]"

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
    'memory_deduper': ['stash_ref', 'canvas_page_id'],
    'stash': ['space_id', 'file_id', 'name', 'mime_type', 'size_bytes'],
    'screenshot_url': ['url', 'screenshot_path'],
    # --- Knowledge/session refs ---
    'canvas': ['page_id', 'title'],
    'opencode': ['session_id'],
    # --- Entity references (for modify/repeat/cancel follow-ups) ---
    'remember': ['memory_id', 'key', 'category'],
    'create_reminder': ['reminder_id', 'formatted_time'],
    'send_email': ['to', 'subject', 'status'],
    'api_call': ['url', 'method', 'status_code'],
    'serpapi_search': ['engine', 'query', 'asin', 'results_count', 'top_url'],
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
        if key == 'text_summarizer':
            extracted = extract_text_summarizer_followup(value, max_candidates)
            if extracted:
                followup[key] = extracted
            continue
        # List-shaped tool payloads: normalize to dict with results[] (no per-tool registry).
        if isinstance(value, list):
            if not value:
                continue
            if all(isinstance(x, dict) for x in value):
                value = {'results': value}
            else:
                continue
        if not isinstance(value, dict):
            continue
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
            if value.get(field):
                extracted[field] = value[field]

        # Always include provider if present (needed for follow-ups)
        if value.get('provider') and 'provider' not in extracted:
            extracted['provider'] = value['provider']

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
            sources = []
            seen_urls: set[str] = set()

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
                snippets = item.get('snippets')
                if isinstance(snippets, list) and snippets:
                    record['snippet'] = str(snippets[0])[:500]
                sources.append(record)

            for item in grounding.get('generic') or []:
                add_source(item)
                if len(sources) >= max_candidates:
                    break
            if len(sources) < max_candidates:
                add_source(grounding.get('poi'))
            if len(sources) < max_candidates:
                for item in grounding.get('map') or []:
                    add_source(item)
                    if len(sources) >= max_candidates:
                        break
            if sources:
                extracted['sources_count'] = len(sources)
                extracted['sources'] = sources

        # Generic results[] / items[] for tools without explicit branches above
        if (
            not extracted.get('candidates')
            and key not in _DEDICATED_FOLLOWUP_BRANCHES
        ):
            results = (
                value.get('results')
                or value.get('top_results')
                or value.get('items')
                or value.get('pages')
                or value.get('chunks')
            )
            if isinstance(results, list) and results:
                first = results[0] if isinstance(results[0], dict) else {}
                if isinstance(first, dict):
                    if first.get('title'):
                        extracted['title'] = first['title']
                    if first.get('url') and 'top_url' not in extracted:
                        extracted['top_url'] = first['url']
                    if first.get('name') and 'name' not in extracted:
                        extracted['name'] = first['name']
                extracted['results_count'] = value.get('results_count', len(results))
                generic_keys = (
                    'title', 'name', 'url', 'asin', 'place_id', 'video_id',
                    'id', 'rating', 'price', 'thumbnail', 'address', 'reviews',
                )
                candidates = []
                for item in results[:max_candidates]:
                    if not isinstance(item, dict):
                        continue
                    candidate = {k: item[k] for k in generic_keys if item.get(k)}
                    if candidate:
                        candidates.append(candidate)
                if candidates:
                    extracted['candidates'] = candidates

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
