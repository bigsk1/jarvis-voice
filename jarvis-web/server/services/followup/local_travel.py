"""Local business, review, event, and destination follow-up projections.

Called by followup_extractor after common metadata extraction. Each helper
extends the supplied output dict, preserving existing-field precedence.
Shared truncation and bounding policy remains in the public facade.
"""

from collections.abc import Callable


def extend_yelp_search(
    value: dict,
    extracted: dict,
    max_candidates: int,
    *,
    truncate_text: Callable[[str, int], str],
) -> None:
    """Add serpapi_yelp_search fields to the common follow-up output."""
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
                candidate['snippet'] = truncate_text(
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
                compact_review['text'] = truncate_text(
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


def extend_open_table_reviews(
    payload: dict,
    extracted: dict,
    max_candidates: int,
    *,
    truncate_text: Callable[[str, int], str],
) -> None:
    """Add serpapi_open_table_reviews fields to the common follow-up output."""
    summary = payload.get('reviews_summary')
    if isinstance(summary, dict):
        compact_summary = {
            field: summary[field]
            for field in ('reviews_count', 'ratings_count', 'ratings_summary')
            if summary.get(field) not in (None, '', [], {})
        }
        if summary.get('ai_summary'):
            compact_summary['ai_summary'] = truncate_text(
                str(summary['ai_summary']), 1200
            )
        if compact_summary:
            extracted['reviews_summary'] = compact_summary

    reviews = payload.get('reviews') or payload.get('top_results') or []
    if isinstance(reviews, list) and reviews:
        extracted['results_count'] = payload.get('results_count', len(reviews))
        compact_reviews = []
        for review in reviews[:max_candidates]:
            if not isinstance(review, dict):
                continue
            compact_review = {
                field: review[field]
                for field in ('id', 'dined_at', 'submitted_at', 'rating', 'user')
                if review.get(field) not in (None, '', [], {})
            }
            if review.get('text'):
                compact_review['text'] = truncate_text(
                    str(review['text']), 700
                )
            response = review.get('response')
            if isinstance(response, dict):
                compact_response = {
                    field: response[field]
                    for field in ('date',)
                    if response.get(field) not in (None, '')
                }
                if response.get('content'):
                    compact_response['content'] = truncate_text(
                        str(response['content']), 500
                    )
                if compact_response:
                    compact_review['response'] = compact_response
            images = review.get('images')
            if isinstance(images, list) and images:
                compact_review['images'] = [
                    {
                        field: image[field]
                        for field in ('id', 'url')
                        if image.get(field) not in (None, '')
                    }
                    for image in images[:2]
                    if isinstance(image, dict) and image.get('url')
                ]
            if compact_review:
                compact_reviews.append(compact_review)
        if compact_reviews:
            extracted['reviews'] = compact_reviews

    content = payload.get('content')
    if isinstance(content, str) and content.strip():
        extracted['content_chars'] = payload.get('content_chars', len(content))
        extracted['content_excerpt'] = truncate_text(content, 2000)


def extend_google_events(
    payload: dict,
    extracted: dict,
    max_candidates: int,
) -> None:
    """Add serpapi_google_events fields to the common follow-up output."""
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
                    'position', 'title', 'url', 'link', 'type',
                    'start_date', 'when', 'date_text', 'time',
                    'address', 'address_text', 'description', 'price',
                    'extracted_price', 'ticket_info', 'venue',
                    'event_location_map', 'thumbnail', 'image',
                )
                if item.get(field) not in (None, '', [], {})
            }
            if candidate.get('title') or candidate.get('url'):
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


def extend_google_local(
    payload: dict,
    extracted: dict,
    max_candidates: int,
) -> None:
    """Add serpapi_google_local fields to the common follow-up output."""
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


def extend_google_local_services(
    payload: dict,
    extracted: dict,
    max_candidates: int,
) -> None:
    """Add serpapi_google_local_services fields to the common follow-up output."""
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


def extend_tripadvisor(
    payload: dict,
    extracted: dict,
    max_candidates: int,
    *,
    truncate_text: Callable[[str, int], str],
) -> None:
    """Add serpapi_tripadvisor fields to the common follow-up output."""
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
                    candidate['text'] = truncate_text(
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
                    candidate['description'] = truncate_text(
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
            compact_place['description'] = truncate_text(
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
                compact_detail['place']['description'] = truncate_text(
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
                compact['text'] = truncate_text(
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


def extend_travel_explore(
    payload: dict,
    extracted: dict,
    max_candidates: int,
) -> None:
    """Add serpapi_travel_explore fields to the common follow-up output."""
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


def extend_flight_search(
    payload: dict,
    extracted: dict,
    max_candidates: int,
) -> None:
    """Add flight_search fields to the common follow-up output."""
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
