"""Trakt and TMDB follow-up projections.

Called by followup_extractor after common metadata extraction. Each helper
extends the supplied output dict, preserving existing-field precedence.
Shared truncation policy remains in the public facade.
"""

from collections.abc import Callable


def extend_trakt(
    payload: dict,
    extracted: dict,
    max_candidates: int,
    *,
    truncate_text: Callable[[str, int], str],
) -> None:
    """Add trakt fields to the common follow-up output."""
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
                    'media_type', 'user_rating', 'rated_at', 'watched_at',
                    'listed_at', 'history_id', 'progress', 'notes',
                    'privacy', 'share_link', 'item_count', 'comment_count',
                    'name', 'description', 'sort_by', 'sort_how',
                    'display_numbers',
                )
                if item.get(field) not in (None, '', [], {})
            }
            if item.get('overview'):
                candidate['overview'] = truncate_text(
                    str(item['overview']), 700
                )
            if candidate.get('title') or candidate.get('trakt_url'):
                candidates.append(candidate)
        if candidates:
            extracted['candidates'] = candidates


def extend_tmdb(
    tool_name: str,
    payload: dict,
    extracted: dict,
    max_candidates: int,
    *,
    truncate_text: Callable[[str, int], str],
) -> None:
    """Add tmdb fields to the common follow-up output."""
    media_key = 'show' if tool_name == 'tmdb_tv_shows' else 'movie'
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
                candidate['overview'] = truncate_text(
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
