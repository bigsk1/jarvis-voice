"""Shopping product and merchant follow-up projections.

Most helpers extend the common follow-up output with product fields.
Amazon returns a fresh shortlist before common metadata extraction, merging
discovery and detail runs. Shared truncation, scalar-compaction, and bounding
policy remains in the public facade.
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


_AMAZON_CANDIDATE_FIELDS = (
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


def _compact_amazon_list(
    field: str,
    value: list,
    *,
    truncate_text: Callable[[str, int], str],
) -> list:
    """Bound the few small list fields retained for shopping follow-ups."""
    limit = 3 if field == 'delivery' else 5
    max_chars = 500 if field == 'delivery' else 120
    compact = [
        truncate_text(str(item), max_chars)
        for item in value[:limit]
        if item not in (None, '', [], {})
    ]
    if len(value) > limit:
        compact.append(
            f"... [{len(value) - limit} items truncated for follow-up context]"
        )
    return compact


def _compact_amazon_candidate(
    item: dict,
    *,
    truncate_text: Callable[[str, int], str],
    compact_scalar: Callable[[str, object], object],
) -> dict:
    """Keep product identity plus decision-relevant shopping signals."""
    candidate = {}
    for field in _AMAZON_CANDIDATE_FIELDS:
        field_value = item.get(field)
        if field_value in (None, '', [], {}):
            continue
        if isinstance(field_value, list):
            compact_list = _compact_amazon_list(
                field, field_value, truncate_text=truncate_text
            )
            if compact_list:
                candidate[field] = compact_list
            continue
        compact_value = compact_scalar(field, field_value)
        if compact_value not in (None, '', [], {}):
            candidate[field] = compact_value
    return candidate


def _amazon_result_rows(payload: dict) -> list[dict]:
    rows = payload.get('results') or payload.get('top_results') or []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _merge_amazon_candidate(base: dict, detail: dict) -> dict:
    """Overlay richer detail signals while preserving the discovery identity."""
    merged = dict(base)
    for field, field_value in detail.items():
        if field in {'title', 'url', 'thumbnail'} and merged.get(field):
            continue
        merged[field] = field_value
    return merged


def extract_amazon_followup(
    value,
    max_candidates: int,
    *,
    truncate_text: Callable[[str, int], str],
    compact_scalar: Callable[[str, object], object],
) -> dict:
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
            and _amazon_result_rows(run)
        ),
        None,
    )
    primary = discovery or runs[0]

    details_by_asin = {}
    for run in runs:
        if run.get('engine') != 'amazon_product':
            continue
        for row in _amazon_result_rows(run):
            candidate = _compact_amazon_candidate(
                row, truncate_text=truncate_text, compact_scalar=compact_scalar
            )
            asin = candidate.get('asin') or run.get('asin')
            if not asin:
                continue
            candidate.setdefault('asin', asin)
            prior = details_by_asin.get(asin, {})
            details_by_asin[asin] = _merge_amazon_candidate(prior, candidate)

    candidates = []
    seen = set()
    candidate_runs = [discovery] if discovery else runs
    for run in candidate_runs:
        if not isinstance(run, dict):
            continue
        for row in _amazon_result_rows(run):
            candidate = _compact_amazon_candidate(
                row, truncate_text=truncate_text, compact_scalar=compact_scalar
            )
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
                candidate = _merge_amazon_candidate(candidate, detail)
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
