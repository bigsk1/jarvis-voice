"""Shopping product and merchant follow-up projections.

Called by followup_extractor after common metadata extraction. Each helper
extends the supplied output dict, preserving existing-field precedence.
Shared truncation and bounding policy remains in the public facade.
"""

from collections.abc import Callable


def extend_home_depot(
    value: dict,
    extracted: dict,
    max_candidates: int,
) -> None:
    """Add serpapi_home_depot fields to the common follow-up output."""
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


def extend_ebay_search(
    value: dict,
    extracted: dict,
    max_candidates: int,
) -> None:
    """Add serpapi_ebay_search fields to the common follow-up output."""
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


def extend_ebay_product(
    value: dict,
    extracted: dict,
    max_candidates: int,
) -> None:
    """Add serpapi_ebay_product fields to the common follow-up output."""
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


def extend_google_shopping_light(
    payload: dict,
    extracted: dict,
    max_candidates: int,
    *,
    truncate_text: Callable[[str, int], str],
) -> None:
    """Add serpapi_google_shopping_light fields to the common follow-up output."""
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
                    'immersive_product_page_token',
                    'serpapi_immersive_product_api',
                )
                if item.get(field) not in (None, '', [], {})
            }
            extensions = item.get('extensions')
            if isinstance(extensions, list) and extensions:
                candidate['extensions'] = [
                    truncate_text(str(extension), 200)
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


def extend_google_immersive_product(
    payload: dict,
    extracted: dict,
    max_candidates: int,
    *,
    truncate_text: Callable[[str, int], str],
    bound_structured_value: Callable[..., object],
    bound_immersive_value: Callable[..., object],
) -> None:
    """Add serpapi_google_immersive_product fields to the common follow-up output."""
    summary = payload.get('product_summary')
    if isinstance(summary, dict):
        extracted['product_summary'] = bound_structured_value(
            summary,
            max_chars=3500,
        )

    stores = payload.get('stores') or payload.get('top_results') or []
    if isinstance(stores, list) and stores:
        extracted['stores'] = bound_structured_value(
            stores[:max_candidates],
            max_chars=5000,
        )

    for field, max_chars in (
        ('about_the_product', 4500),
        ('top_insights', 4500),
        ('ratings', 2500),
        ('user_reviews', 5000),
        ('more_options', 3000),
        ('variants', 3500),
        ('related_searches', 2500),
    ):
        section = payload.get(field)
        if section not in (None, '', [], {}):
            extracted[field] = bound_immersive_value(
                section,
                max_chars=max_chars,
            )

    content = payload.get('content')
    if isinstance(content, str) and content.strip():
        extracted['content_chars'] = payload.get('content_chars', len(content))
        extracted['content_excerpt'] = truncate_text(content, 2000)
