"""Trader Joe's cards and durable food-evidence follow-up contracts."""

import importlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
JS_ROOT = ROOT / 'jarvis-web' / 'client' / 'js'
load_server_package('trader_joes_web_server', ROOT / 'jarvis-web' / 'server')
followup = importlib.import_module('trader_joes_web_server.services.followup_extractor')


def _product(**overrides):
    return {
        'position': 1, 'product_id': '080794', 'title': 'Cold Brew Coffee Black',
        'url': 'https://www.traderjoes.com/home/products/pdp/cold-brew-coffee-black-080794',
        'image_url': 'https://images.example/080794.png',
        'thumbnail': 'https://images.example/080794-thumb.png',
        'price': 1.99, 'price_formatted': '$1.99', 'currency': 'USD',
        'size': '8.45 Fl Oz', 'category': 'Coffee', 'category_id': '61',
        'category_url': 'https://www.traderjoes.com/home/products/category/coffee-61',
        **overrides,
    }


def _detail(**overrides):
    return _product(**{
        'available': True, 'characteristics': ['vegan', 'gluten_free'], 'label': 'Organic',
        'images': ['https://images.example/080794.png', 'https://images.example/080794-side.png'],
        'description': 'Cold brewed coffee. Plain <b>product</b> details.',
        'fun_tags': ['Alfresco Dining'], 'ingredients': ['WATER', 'ARABICA COFFEE', 'NATURAL FLAVOR'],
        'allergens': ['MAY CONTAIN MILK.'], 'nutrition_facts': [{
            'title': 'Per serving', 'servings_per_container': 'Serves 1',
            'serving_size': '1 can (250mL)', 'calories_per_serving': 10,
            'nutrients': [{'name': 'Total Fat', 'amount': '0g', 'daily_value': '0%'},
                          {'name': 'Sodium', 'amount': '10mg', 'daily_value': 0}],
        }, {
            'title': 'Per container', 'serving_size': '1 container', 'calories_per_serving': 20,
            'nutrients': [{'name': 'Total Sugars', 'amount': '0g', 'daily_value': None}],
        }], **overrides,
    })


def _payload(*, focused=False, **overrides):
    product = _detail() if focused else _product()
    return {
        'engine': 'trader_joes_product' if focused else 'trader_joes',
        'store_id': '147', 'location_context': {
            'store_id': '147', 'store_name': "Trader Joe's Hillsboro",
            'requested_postal_code': '97006', 'source': 'postal_code',
            'store_address': '2285 NW 185th Ave, Hillsboro, OR', 'matching_stores': 1,
            'note': 'ZIP 97006 selected 2285 NW 185th Ave, Hillsboro, OR.',
        },
        'results': [product], 'top_results': [product], 'results_count': 1,
        **({'product_id': '080794', 'product_summary': product} if focused else {'query': 'cold brew'}),
        **overrides,
    }


def _extract(tool, value, **kwargs):
    result = followup.extract_followup_data({tool: value}, **kwargs)[tool]
    assert json.loads(json.dumps(result, allow_nan=False, ensure_ascii=False)) == result
    return result


def _javascript(data, body):
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
const renderer = sandbox.window.structuredResultsRenderer;
const data = DATA;
BODY
""".replace('PATHS', json.dumps(paths)).replace('DATA', json.dumps(data)).replace('BODY', body)
    return subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True).stdout


def _render(data):
    return _javascript(data, 'process.stdout.write(renderer.render(data));')


def _assert_collapsed(html, expected):
    openings = [part.split('>', 1)[0] for part in html.split('<details')[1:]]
    assert len(openings) == expected
    assert all(' open' not in opening for opening in openings)


def test_search_cards_preserve_sku_own_photos_zero_price_and_missing_price_without_reviews():
    products = [
        _product(title='Free sample', price=0, price_formatted=None, product_id='000001'),
        _product(title='No photo or price', product_id='000002', price=None,
                 price_formatted=None, image_url=None, thumbnail=None),
        _product(title='Third product', product_id='000003', image_url='https://images.example/000003.png'),
    ]
    payload = _payload(results=products, top_results=products, results_count=3,
                       top_image_url=products[0]['image_url'], rating=5, reviews=99)
    html = _render({'serpapi_trader_joes_search': {'ok': True, 'data': payload}})
    for value in ('Trader Joe&#39;s results', 'Product 000001', 'Product 000002', 'Product 000003',
                  'USD 0', 'Store 147', '2285 NW 185th Ave'):
        assert value in html
    assert html.count('src="https://images.example/080794.png"') == 1
    assert html.count('src="https://images.example/000003.png"') == 1
    assert '99 reviews' not in html and '★' not in html
    assert html.count('structured-result-primary') == 2  # Missing price stays unknown.
    _assert_collapsed(html, 1)


def test_product_food_reader_retains_all_panels_and_escapes_external_content():
    product = _detail(title='<script>coffee()</script>', ingredients=['WATER', '<img src=x onerror=bad()>'],
                      allergens=['MAY CONTAIN <b>MILK</b>.'])
    payload = _payload(focused=True, product_summary=product, results=[product])
    payload['location_context']['note'] = 'Selected address <script>inert()</script>'
    html = _render({'serpapi_trader_joes_product': payload})
    for value in ('Trader Joe&#39;s product', '$1.99', 'Sold at selected store', '8.45 Fl Oz',
                  'Read food and product details', 'Alfresco Dining', 'Per serving', 'Per container',
                  'Calories: 10', 'Calories: 20', 'Total Fat · 0g · 0% daily value',
                  'Sodium · 10mg · 0 daily value', 'not a live inventory count',
                  '&lt;script&gt;coffee()&lt;/script&gt;', '&lt;img src=x onerror=bad()&gt;',
                  'MAY CONTAIN &lt;b&gt;MILK&lt;/b&gt;', 'Selected address &lt;script&gt;inert()&lt;/script&gt;'):
        assert value in html
    assert '<script>' not in html and '<img src=x' not in html and '<b>MILK</b>' not in html
    assert ' reviews' not in html and '★' not in html
    _assert_collapsed(html, 1)


def test_reader_dialog_receives_complete_plain_text_food_details():
    payload = _payload(focused=True)
    body = r"""
const adapter = renderer.adapters.get('serpapi_trader_joes_product');
const item = adapter(data).items[0];
const fields = Object.fromEntries(['title', 'meta', 'text', 'note'].map(key => [key, {textContent: '', hidden: false}]));
const dialog = {open: false, querySelector: selector => fields[selector.match(/reader-(\w+)/)[1]],
  showModal() { this.open = true; }};
renderer._ensureReaderDialog = () => dialog;
const cardFields = {
  '.structured-result-full-text': {textContent: item.expandText},
  '.structured-result-full-note': {textContent: item.expandNote},
  '.structured-result-title': {textContent: item.title},
  '.structured-result-primary': {textContent: item.primary},
  '.structured-result-expand-button': {isConnected: true},
};
renderer._openExpandedResult({querySelector: selector => cardFields[selector]});
process.stdout.write(JSON.stringify({open: dialog.open, fields}));
"""
    result = json.loads(_javascript(payload, body))
    assert result['open'] is True
    assert result['fields']['title']['textContent'] == 'Cold Brew Coffee Black'
    text = result['fields']['text']['textContent']
    assert 'Plain <b>product</b> details.' in text  # A textContent assignment, never HTML.
    assert 'Ingredients: WATER, ARABICA COFFEE, NATURAL FLAVOR' in text
    assert 'Allergens: MAY CONTAIN MILK.' in text
    assert 'Per serving' in text and 'Per container' in text
    assert result['fields']['meta']['textContent'] == '$1.99 · Plain text'
    assert result['fields']['note']['hidden'] is False


def test_unavailable_product_has_no_invented_price_or_realtime_stock_claim():
    for price in (None, 0):
        product = _detail(product_id='084844', title='Spaghetti', available=False,
                          price=price, price_formatted=None)
        html = _render({'serpapi_trader_joes_product': _payload(focused=True, product_summary=product)})
        assert 'Not sold at selected store' in html
        assert 'USD 0' not in html and 'In stock' not in html and 'Out of stock' not in html
        assert 'structured-result-primary' not in html
        _assert_collapsed(html, 1)


def test_unsafe_product_links_and_images_are_inert():
    product = _product(url='javascript:bad()', image_url='data:text/html,bad', thumbnail=None)
    html = _render({'serpapi_trader_joes_search': _payload(results=[product], top_results=[product])})
    assert 'Cold Brew Coffee Black' in html
    assert 'href="javascript:' not in html and 'src="data:' not in html


def test_workflow_reload_keeps_both_sections_collapsed_and_correct_images():
    search = _payload()
    product = _detail(product_id='090874', title='Apple Blossoms', image_url='https://images.example/090874.png')
    workflow = {'workflow': {'workflow_id': 'grocery-fixture', 'action': 'run', 'results': [
        {'tool': 'serpapi_trader_joes_search', 'data': search},
        {'tool': 'serpapi_trader_joes_product', 'data': _payload(focused=True, product_summary=product)},
    ]}}
    html = _render(json.loads(json.dumps(workflow)))
    assert 'data-workflow-tool="serpapi_trader_joes_search"' in html
    assert 'data-workflow-tool="serpapi_trader_joes_product"' in html
    assert html.count('src="https://images.example/080794.png"') == 1
    assert html.count('src="https://images.example/090874.png"') == 1
    assert 'Per serving' in html and 'Per container' in html
    _assert_collapsed(html, 2)


def test_default_saved_search_retains_ten_ordered_skus_filters_store_and_zero_values():
    products = [_product(product_id=f'{number:06}', title=f'Product {number}', price=0,
                         price_formatted=None, available=False) for number in range(1, 11)]
    filters = {'category_id': '61', 'characteristics': ['vegan'], 'tags': ['cold_brew'],
               'new_products': False, 'sort_by': 'price_low_to_high'}
    payload = _payload(results=products, top_results=products[:3], results_count=10,
                       requested_filters=filters, api_key='SECRET_SENTINEL')
    before = deepcopy(payload)
    result = _extract('serpapi_trader_joes_search', {'ok': True, 'data': payload})
    assert [row['product_id'] for row in result['candidates']] == [f'{number:06}' for number in range(1, 11)]
    assert result['candidates'][0]['price'] == 0 and result['candidates'][0]['available'] is False
    assert result['candidates'][0]['price_formatted'] is None
    assert result['store_id'] == '147' and result['location_context'] == payload['location_context']
    assert result['requested_filters'] == filters and result['results_count'] == 10
    assert not result.get('candidates_truncated')
    assert 'SECRET_SENTINEL' not in json.dumps(result)
    assert len(json.dumps(result, ensure_ascii=False)) <= 8000
    assert payload == before


def test_saved_food_evidence_survives_strict_json_and_reprojection_with_explicit_shortlist():
    product = _detail(available=False, price=None, price_formatted=None)
    payload = _payload(focused=True, product_summary=product, results=[product])
    result = _extract('serpapi_trader_joes_product', payload)
    restored = _extract('serpapi_trader_joes_product', json.loads(json.dumps(result)))
    for projection in (result, restored):
        assert projection['product_id'] == '080794' and projection['store_id'] == '147'
        assert projection['candidates'][0]['product_id'] == '080794'
        assert projection['candidates'][0]['price'] is None
        detail = projection['product_summary']
        assert detail['available'] is False and detail['images'] == product['images']
        assert detail['ingredients'] == product['ingredients'] and detail['allergens'] == product['allergens']
        assert detail['nutrition_facts'] == product['nutrition_facts']
        assert detail['fun_tags'] == product['fun_tags']
        assert 'reviews_results' not in projection
    products = [_product(product_id=f'{number:06}') for number in range(1, 4)]
    shortlist = _extract('serpapi_trader_joes_search', _payload(results=products), max_candidates=2)
    assert [row['product_id'] for row in shortlist['candidates']] == ['000001', '000002']
    assert shortlist['candidates_truncated'] is True and shortlist['candidates_omitted'] == 1


def test_saved_long_description_is_labeled_without_crowding_out_food_evidence():
    product = _detail(description='Long product description. ' * 1000)
    payload = _payload(focused=True, product_summary=product, results=[product])
    result = _extract('serpapi_trader_joes_product', payload)
    detail = result['product_summary']
    assert result['context_truncated'] is True and detail['description_truncated'] is True
    assert detail['description'].startswith('Long product description.')
    assert detail['description'].endswith('[truncated]')
    assert detail['ingredients'] == product['ingredients']
    assert detail['allergens'] == product['allergens']
    assert detail['nutrition_facts'] == product['nutrition_facts']
    assert len(json.dumps(result, ensure_ascii=False)) <= 8000


def test_repeated_saved_runs_keep_recent_store_prices_and_failure_provenance():
    runs = [
        {'ok': True, 'data': _payload(store_id=str(store), results=[_product(price=price)],
                                    location_context={'store_id': str(store), 'source': 'explicit_store'})}
        for store, price in ((100, 1), (200, 2), (300, 3))
    ]
    runs.append({'ok': False, 'completion': 'rejected', 'error': 'Provider did not return product data.'})
    result = _extract('serpapi_trader_joes_search', runs)
    restored = _extract('serpapi_trader_joes_search', json.loads(json.dumps(result)))
    for projection in (result, restored):
        assert projection['runs_count'] == 4 and projection['results_truncated'] is True
        assert [(row['store_id'], row['candidates'][0]['price']) for row in projection['results'][:2]] == [
            ('200', 2), ('300', 3),
        ]
        failed = projection['results'][-1]
        assert failed['ok'] is False and failed['completion'] == 'rejected'
        assert failed['error'] == 'Provider did not return product data.'
        assert failed['candidates'] == []
        assert len(json.dumps(projection, ensure_ascii=False)) <= 8000


def test_nested_workflow_saved_evidence_keeps_exact_product_and_food_fields():
    workflow = {'workflow': {'workflow_id': 'grocery-fixture', 'action': 'run', 'results': [
        {'tool': 'serpapi_trader_joes_search', 'data': _payload()},
        {'tool': 'serpapi_trader_joes_product', 'data': _payload(focused=True)},
    ]}}
    result = followup.extract_followup_data(json.loads(json.dumps(workflow)))
    encoded = json.dumps(result, allow_nan=False, ensure_ascii=False)
    assert 'serpapi_trader_joes_search' in result and 'serpapi_trader_joes_product' in result
    detail = result['serpapi_trader_joes_product']['product_summary']
    assert detail['product_id'] == '080794' and detail['allergens'] == ['MAY CONTAIN MILK.']
    assert len(detail['nutrition_facts']) == 2
    assert 'WATER' in encoded and '97006' in encoded
