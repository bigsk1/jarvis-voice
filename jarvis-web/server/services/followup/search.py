"""Web, media, sports, and trend search follow-up projections.

Called by followup_extractor after common metadata extraction. Each helper
extends the supplied output dict, preserving existing-field precedence.
Shared truncation and bounding policy remains in the public facade.
"""

from collections.abc import Callable


def extend_searxng_search(
    payload: dict,
    extracted: dict,
    max_candidates: int,
    *,
    truncate_text: Callable[[str, int], str],
) -> None:
    """Keep SearXNG source attribution and URLs for later turns."""
    results = payload.get('results') or []
    candidates = []
    if isinstance(results, list):
        for item in results[:max_candidates]:
            if not isinstance(item, dict) or not item.get('url'):
                continue
            candidate = {
                field: item[field]
                for field in ('title', 'url', 'engine', 'category', 'published_date')
                if item.get(field) not in (None, '')
            }
            if item.get('snippet'):
                candidate['snippet'] = truncate_text(str(item['snippet']), 700)
            candidates.append(candidate)
    if candidates:
        extracted['candidates'] = candidates


def extend_tavily_search(
    payload: dict,
    extracted: dict,
    max_candidates: int,
    *,
    truncate_text: Callable[[str, int], str],
) -> None:
    """Keep source links and enough evidence for a later question."""
    results = payload.get('results') or []
    candidates = []
    if isinstance(results, list):
        for item in results[:max_candidates]:
            if not isinstance(item, dict) or not item.get('url'):
                continue
            candidate = {
                field: item[field] for field in ('title', 'url', 'published_date')
                if item.get(field) not in (None, '')
            }
            if item.get('snippet'):
                candidate['snippet'] = truncate_text(str(item['snippet']), 700)
            candidates.append(candidate)
    if candidates:
        extracted['candidates'] = candidates


def extend_tavily_extract(
    payload: dict,
    extracted: dict,
    *,
    truncate_text: Callable[[str, int], str],
) -> None:
    """Keep the URL and a bounded page excerpt for follow-up turns."""
    if payload.get('content'):
        extracted['content_excerpt'] = truncate_text(str(payload['content']), 2000)


def extend_youtube_search(
    value: dict,
    extracted: dict,
    max_candidates: int,
) -> None:
    """Add serpapi_youtube_search fields to the common follow-up output."""
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


def extend_search_index(
    payload: dict,
    extracted: dict,
    max_candidates: int,
    *,
    truncate_text: Callable[[str, int], str],
) -> None:
    """Add serpapi_search_index fields to the common follow-up output."""
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
                candidate['snippet'] = truncate_text(
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
            truncate_text(str(query), 300)
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


def extend_google_images_light(
    payload: dict,
    extracted: dict,
    max_candidates: int,
) -> None:
    """Add serpapi_google_images_light fields to the common follow-up output."""
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


def extend_google_news_light(
    payload: dict,
    extracted: dict,
    max_candidates: int,
    *,
    truncate_text: Callable[[str, int], str],
) -> None:
    """Add serpapi_google_news_light fields to the common follow-up output."""
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
                candidate['snippet'] = truncate_text(
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


def extend_google_sports(
    payload: dict,
    extracted: dict,
    max_candidates: int,
) -> None:
    """Add serpapi_google_sports fields to the common follow-up output."""
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


def extend_google_trends(
    payload: dict,
    extracted: dict,
    max_candidates: int,
) -> None:
    """Add serpapi_google_trends fields to the common follow-up output."""
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


def extend_google_trending_now(
    payload: dict,
    extracted: dict,
    max_candidates: int,
) -> None:
    """Add serpapi_google_trending_now fields to the common follow-up output."""
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
