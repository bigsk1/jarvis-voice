"""Walmart shopping cards and durable product/review follow-up contracts."""

import importlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
JS_ROOT = ROOT / 'jarvis-web' / 'client' / 'js'
load_server_package('walmart_web_server', ROOT / 'jarvis-web' / 'server')
followup = importlib.import_module('walmart_web_server.services.followup_extractor')


def _product(**overrides):
    return {
        'position': 1, 'product_id': '4WALMART7', 'us_item_id': '123456789',
        'title': 'Cordless vacuum', 'url': 'https://www.walmart.com/ip/vacuum/123456789',
        'thumbnail': 'https://images.example/thumb.jpg', 'image_url': 'https://images.example/full.jpg',
        'price': 0, 'price_formatted': 'USD 0', 'currency': 'USD',
        'rating': 0, 'reviews': 0, 'seller_name': 'Walmart', 'sponsored': False,
        'in_stock': False, **overrides,
    }


def _reviews():
    return {
        'ratings': [{'stars': 5, 'count': 900}, {'stars': 1, 'count': 150}],
        'reviews': {
            'rating': 4.2, 'count': 1050, 'recommended_percentage': 85,
            'top_positive': {'title': 'Useful suction', 'text': 'The vacuum cleans my stairs.',
                             'rating': 5, 'user_nickname': 'Customer A',
                             'review_submission_time': '2026-10-01', 'customer_type': 'Verified purchaser'},
            'top_negative': {'title': 'Short battery', 'text': 'Runtime was shorter than expected.', 'rating': 1},
            'customer_reviews': [{'title': 'Useful suction', 'text': 'The vacuum cleans my stairs.',
                                  'rating': 5, 'user_nickname': 'Customer A'},
                                 {'title': 'Easy storage', 'text': 'It fits in my closet.', 'rating': 4}],
        },
    }


def _payload(*, focused=False, **overrides):
    product = _product()
    return {
        'engine': 'walmart_product' if focused else 'walmart',
        'country': 'us', 'walmart_domain': 'walmart.com', 'store_id': '1234',
        'location_context': {'store_id': '1234', 'requested_postal_code': '98101', 'source': 'configured_store'},
        'results_count': 1, 'results': [product], 'top_results': [product],
        **({'product_id': '4WALMART7', 'product_summary': product,
            'reviews_results': _reviews()} if focused else {'query': 'cordless vacuum'}),
        **overrides,
    }


def _extract(tool, value, **kwargs):
    result = followup.extract_followup_data({tool: value}, **kwargs)[tool]
    assert json.loads(json.dumps(result, allow_nan=False, ensure_ascii=False)) == result
    return result


def _render(data):
    paths = [str(JS_ROOT / name) for name in (
        'structured-results-shopping.js', 'structured-results-search.js',
        'structured-results-local-travel.js', 'structured-results.js',
    )]
    script = r"""
const fs = require('fs');
const vm = require('vm');
const escapeHtml = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const sandbox = {URL, console, window: {}, Utils: {
  escapeHtml,
  safeHttpUrlForAttr: value => {
    try {
      const parsed = new URL(String(value));
      return ['https:', 'http:'].includes(parsed.protocol) ? escapeHtml(parsed.href) : '';
    } catch (_) { return ''; }
  },
}};
vm.createContext(sandbox);
vm.runInContext(PATHS.map(path => fs.readFileSync(path, 'utf8')).join('\n'), sandbox);
process.stdout.write(sandbox.window.structuredResultsRenderer.render(DATA));
""".replace('PATHS', json.dumps(paths)).replace('DATA', json.dumps(data))
    return subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True).stdout


def test_search_cards_show_images_zero_price_aggregate_ratings_and_exact_store_note_safely():
    payload = _payload()
    payload['results'][0].update(title='<script>untrusted()</script>', sponsored=True,
                                 price_was=19.99, in_stock=None, out_of_stock=True)
    payload['location_context']['note'] = 'ZIP was not applied <script>inert()</script>'
    html = _render({'serpapi_walmart_search': payload})
    assert 'Walmart results' in html and 'Store 1234' in html
    assert 'src="https://images.example/full.jpg"' in html
    assert 'href="https://www.walmart.com/ip/vacuum/123456789"' in html
    for value in ('USD 0', '★ 0', '0 reviews', 'Sponsored', 'Sold by Walmart', 'Out of stock', 'Was USD 19.99'):
        assert value in html
    assert 'ZIP was not applied &lt;script&gt;inert()&lt;/script&gt;' in html
    assert '<script>' not in html


def test_product_cards_use_summary_images_native_previous_price_and_individual_review_readers():
    product = _product(title='Vacuum details', price=29.99, price_formatted='USD 29.99', rating=4.2,
                       reviews=1050, in_stock=True, description='First line\nPlain <b>product</b> details.',
                       price_was={'price': 49.99, 'currencyUnit': 'USD', 'priceString': '$49.99'})
    payload = _payload(focused=True, product_summary=product)
    html = _render({'serpapi_walmart_product': {'ok': True, 'data': payload}})
    for value in ('Walmart product', 'Vacuum details', 'USD 29.99', 'Was $49.99', '★ 4.2', '1,050 reviews',
                  '85% recommend', '5★: 900', '1★: 150', 'Positive review: Useful suction',
                  'Critical review: Short battery', 'Customer review: Easy storage', 'Read review'):
        assert value in html
    assert html.count('The vacuum cleans my stairs.') == 2  # Preview plus reader, with duplicate review removed.
    assert '3 customer review excerpts shown' in html
    assert 'First line\nPlain &lt;b&gt;product&lt;/b&gt; details.' in html
    assert '<b>product</b>' not in html


def test_missing_price_currency_uses_us_or_mexico_market_and_preserves_zero():
    cases = [
        ('walmart.com', 'us', 'USD'), ('walmart.com.mx', 'mx', 'MXN'), (None, 'MX', 'MXN'),
    ]
    for domain, country, expected in cases:
        for focused in (False, True):
            product = _product(price=0, currency=None, price_formatted=None, price_was={'price': 2})
            payload = _payload(focused=focused, walmart_domain=domain, country=country,
                               results=[product], top_results=[product], product_summary=product)
            tool = 'serpapi_walmart_product' if focused else 'serpapi_walmart_search'
            html = _render({tool: payload})
            assert f'structured-result-primary">{expected} 0</div>' in html
            assert f'Was {expected} 2' in html
            opening = html.split('<details', 1)[1].split('>', 1)[0]
            assert ' open' not in opening


def test_matched_zip_subtitle_names_selected_address_and_same_zip_store_count_once():
    for focused in (False, True):
        location = {'source': 'postal_code', 'requested_postal_code': '98101-1234', 'store_id': '1234',
                    'store_address': '123 Main St <script>inert()</script>', 'matching_stores': 2,
                    'note': 'Selected 1 of 2 stores in ZIP 98101'}
        tool = 'serpapi_walmart_product' if focused else 'serpapi_walmart_search'
        html = _render({tool: _payload(focused=focused, location_context=location)})
        assert 'Store 1234' in html
        assert '123 Main St &lt;script&gt;inert()&lt;/script&gt;' in html
        assert html.count('Selected 1 of 2 stores in ZIP 98101') == 1
        assert '<script>' not in html
        opening = html.split('<details', 1)[1].split('>', 1)[0]
        assert ' open' not in opening
    for source in ('configured_store', 'explicit_store'):
        html = _render({'serpapi_walmart_search': _payload(location_context={'source': source, 'store_id': '1234'})})
        assert 'Store 1234' in html
        assert 'Selected 1 of' not in html and '123 Main St' not in html


def test_fulfillment_options_show_named_availability_instead_of_raw_booleans():
    product = _product(shipping_option={'available': True, 'location': 'Beaverton, 97006',
                                        'arrival_date': '2026-11-13T22:59:00.000Z'},
                       pickup_option={'available': False, 'location': 'Hillsboro Neighborhood Market'},
                       delivery_option={'available': False, 'location': 'Beaverton, 97006'})
    html = _render({'serpapi_walmart_product': _payload(focused=True, product_summary=product)})
    assert 'Shipping: available · Beaverton, 97006' in html
    assert 'Pickup: unavailable · Hillsboro Neighborhood Market' in html
    assert 'Delivery: unavailable · Beaverton, 97006' in html
    assert 'true · Beaverton' not in html and 'false · Hillsboro' not in html
    assert '2026-11-13T22:59:00.000Z' not in html


def test_empty_review_breakdown_preserves_product_aggregate_without_claiming_zero_recommendations():
    product = _product(title='Coffee', rating=4.5, reviews=7275)
    empty_reviews = {
        'ratings': [{'stars': star, 'count': 0} for star in range(1, 6)],
        'reviews': {'rating': 0, 'count': 0, 'recommended_percentage': 0,
                    'top_positive': {}, 'top_negative': {}, 'customer_reviews': []},
    }
    html = _render({'serpapi_walmart_product': _payload(
        focused=True, product_summary=product, results=[product], reviews_results=empty_reviews,
    )})
    assert '★ 4.5' in html and '7,275 reviews' in html
    assert 'Review text and rating breakdown were not returned.' in html
    assert '0% recommend' not in html
    assert all(f'{star}★: 0' not in html for star in range(1, 6))
    assert 'Read review' not in html


def test_unsafe_product_image_and_page_urls_never_become_actions():
    product = _product(url='javascript:bad()', image_url='data:text/html,bad', thumbnail='javascript:bad()')
    html = _render({'serpapi_walmart_search': _payload(results=[product], top_results=[product])})
    assert 'href="javascript:' not in html
    assert 'src="data:' not in html and 'src="javascript:' not in html
    assert 'Cordless vacuum' in html


def test_search_item_without_image_does_not_borrow_another_products_picture():
    products = [_product(title='First product'), _product(title='Second product', image_url=None, thumbnail=None)]
    html = _render({'serpapi_walmart_search': _payload(
        results=products, top_results=products, top_image_url=products[0]['image_url'], results_count=2,
    )})
    assert 'First product' in html and 'Second product' in html
    assert html.count('src="https://images.example/full.jpg"') == 1


def test_search_preview_limit_and_workflow_reload_keep_product_sections_and_images():
    products = [_product(product_id=f'ITEM{i}', us_item_id=str(i), title=f'Item {i}') for i in range(7)]
    payload = _payload(results=products, top_results=products[:5], results_count=7)
    html = _render({'serpapi_walmart_search': payload})
    assert '5 of 7 returned products shown' in html
    assert 'Item 4' in html and 'Item 5' not in html
    workflow = {'workflow': {'workflow_id': 'shopping-fixture', 'action': 'run', 'results': [
        {'tool': 'serpapi_walmart_search', 'data': payload},
        {'tool': 'serpapi_walmart_product', 'data': _payload(focused=True)},
    ]}}
    reloaded = json.loads(json.dumps(workflow))
    html = _render(reloaded)
    assert 'data-workflow-tool="serpapi_walmart_search"' in html
    assert 'data-workflow-tool="serpapi_walmart_product"' in html
    assert 'https://images.example/full.jpg' in html
    assert 'Positive review: Useful suction' in html


def test_search_followup_keeps_both_ids_store_country_zero_values_and_labels_shortlist():
    products = [_product(product_id=f'ITEM{i}', us_item_id=str(i)) for i in range(3)]
    payload = _payload(results=products, top_results=products, results_count=3,
                       pagination={'current_page': 1, 'next_page': 2}, api_token='SECRET_SENTINEL')
    before = deepcopy(payload)
    result = _extract('serpapi_walmart_search', payload, max_candidates=2)
    assert result['store_id'] == '1234' and result['country'] == 'us'
    assert result['walmart_domain'] == 'walmart.com'
    assert result['location_context'] == payload['location_context']
    assert result['pagination'] == payload['pagination']
    assert [row['product_id'] for row in result['candidates']] == ['ITEM0', 'ITEM1']
    assert result['candidates'][0]['us_item_id'] == '0'
    for key in ('price', 'rating', 'reviews'):
        assert result['candidates'][0][key] == 0
    assert result['candidates'][0]['sponsored'] is False
    assert result['candidates'][0]['in_stock'] is False
    assert result['results_count'] == 3 and result['candidates_truncated'] is True
    assert 'SECRET_SENTINEL' not in json.dumps(result)
    assert payload == before


def test_product_followup_keeps_bounded_review_text_aggregate_ratings_and_native_previous_price():
    product = _product(description='Useful description. ' * 1000,
                       specifications=[{'name': 'Runtime', 'value': '20 minutes'}],
                       images=['https://images.example/full.jpg', 'https://images.example/alternate.jpg'],
                       price_was={'price': 19.99, 'currencyUnit': 'USD', 'priceString': '$19.99'},
                       in_stock=None, out_of_stock=True)
    payload = _payload(focused=True, product_summary=product, results=[product])
    payload['reviews_results']['reviews']['top_positive']['text'] = 'Evidence about suction. ' * 1000
    payload['reviews_results']['reviews']['top_positive']['api_key'] = 'SECRET_SENTINEL'
    before = deepcopy(payload)
    result = _extract('serpapi_walmart_product', {'ok': True, 'data': payload})
    assert result['product_id'] == '4WALMART7' and result['store_id'] == '1234'
    assert result['candidates'][0]['us_item_id'] == '123456789'
    assert result['candidates'][0]['out_of_stock'] is True
    assert result['candidates'][0]['price_was'] == product['price_was']
    assert result['product_summary']['images'] == product['images']
    assert result['product_summary']['description_excerpt'].endswith('[truncated for follow-up context]')
    reviews = result['reviews_results']['reviews']
    assert reviews['rating'] == 4.2 and reviews['count'] == 1050
    assert reviews['top_positive']['text'].startswith('Evidence about suction.')
    assert reviews['top_negative']['text'] == 'Runtime was shorter than expected.'
    assert reviews['customer_reviews'][1]['text'] == 'It fits in my closet.'
    assert result['reviews_results']['ratings'] == payload['reviews_results']['ratings']
    assert 'SECRET_SENTINEL' not in json.dumps(result)
    assert len(json.dumps(result, ensure_ascii=False)) <= 8000
    assert payload == before


def test_repeated_search_followups_keep_each_store_attached_to_its_own_product_price():
    runs = [_payload(store_id=store, results=[_product(price=price)],
                     location_context={'store_id': store, 'source': 'explicit_store'})
            for store, price in (('1001', 15), ('1002', 20))]
    result = _extract('serpapi_walmart_search', runs)
    assert result['runs_count'] == 2 and result['results_truncated'] is False
    assert [(row['store_id'], row['candidates'][0]['price']) for row in result['results']] == [
        ('1001', 15), ('1002', 20),
    ]


def test_unmapped_zip_note_survives_saved_history_without_claiming_a_store_was_applied():
    location = {'requested_postal_code': '00000', 'store_id': None, 'source': 'provider_default',
                'note': 'ZIP was not applied; specify store_id for local results.'}
    result = _extract('serpapi_walmart_search', _payload(store_id=None, location_context=location,
                                                       country='mx', walmart_domain='walmart.com.mx'))
    assert 'store_id' not in result
    assert result['country'] == 'mx' and result['walmart_domain'] == 'walmart.com.mx'
    assert result['location_context'] == {key: value for key, value in location.items() if value is not None}
