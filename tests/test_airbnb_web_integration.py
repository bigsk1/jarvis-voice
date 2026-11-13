"""Airbnb cards keep listing photos, stay dates and total-price semantics together."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_ROOT = ROOT / 'jarvis-web' / 'client' / 'js'


def _listing(**overrides):
    return {
        'position': 1, 'listing_id': '1516509370603548960',
        'name': 'Private pool and hot tub', 'title': 'Home in Austin',
        'url': 'https://www.airbnb.com/rooms/1516509370603548960?check_in=2026-11-29&check_out=2026-12-04',
        'description': 'A quiet home near the river.',
        'thumbnail': 'https://a0.muscache.com/im/pictures/first.jpeg',
        'image_url': 'https://a0.muscache.com/im/pictures/first.jpeg',
        'images': ['https://a0.muscache.com/im/pictures/first.jpeg'],
        'rating': 4.95, 'reviews': 61, 'total_price': 1582, 'price_formatted': '$1,582',
        'price_qualifier': 'for 5 nights', 'currency': 'USD',
        'check_in_date': '2026-11-29', 'check_out_date': '2026-12-04',
        'nights': 5, 'dates_mode': 'suggested', 'nightly_average': 316.4,
        'bedrooms': 3, 'beds': 7, 'bathrooms': 3.5,
        'badges': ['Guest favorite'], 'free_cancellation': True, **overrides,
    }


def _payload(**overrides):
    row = _listing()
    return {
        'engine': 'airbnb', 'query': 'Austin, TX', 'currency': 'USD', 'dates_mode': 'suggested',
        'results': [row], 'top_results': [row], 'results_count': 1,
        'search_context': {'query': 'Austin, TX', 'dates_mode': 'suggested', 'adults': 2,
                           'room_type': 'entire_home', 'property_types': ['house']},
        'budget_context': {'enabled': True, 'min_price_per_night': 125, 'max_price_per_night': 250,
                           'filter_nights': 5, 'provider_min_price': 625, 'provider_max_price': 1250,
                           'note': 'Requested $125–$250 per night; provider filters a 5-night stay total. Actual listing dates may differ.'},
        **overrides,
    }


def _render(data):
    paths = [str(JS_ROOT / name) for name in (
        'structured-results-shopping.js', 'structured-results-search.js',
        'structured-results-local-travel.js', 'structured-results.js',
    )]
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const escapeHtml = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const sandbox = {URL, console, window: {}, Utils: {
  escapeHtml, safeHttpUrlForAttr: value => {
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


def _assert_open(html, count=1):
    openings = [part.split('>', 1)[0] for part in html.split('<details')[1:]]
    assert len(openings) == count
    assert all(' open' in opening for opening in openings)


def test_airbnb_cards_keep_total_fees_qualifier_average_rooms_rating_and_exact_listing_link():
    html = _render({'serpapi_airbnb_search': {'ok': True, 'data': _payload()}})
    for value in ('Airbnb stays', 'Austin, TX', 'Private pool and hot tub', 'Home in Austin',
                  '$1,582 total incl. fees', 'for 5 nights',
                  '$316.40/night average (stay total ÷ 5 nights, including fees)',
                  'Suggested dates: 2026-11-29 → 2026-12-04', '★ 4.95', '61 reviews',
                  '3 bedrooms', '7 beds', '3.5 baths', 'Guest favorite', 'Free cancellation',
                  'View on Airbnb', 'entire home · houses · 2 adults', '$125–$250/night budget',
                  'Airbnb-suggested dates; budget based on 5 nights'):
        assert value in html
    assert 'href="https://www.airbnb.com/rooms/1516509370603548960?check_in=2026-11-29&amp;check_out=2026-12-04"' in html
    assert 'src="https://a0.muscache.com/im/pictures/first.jpeg"' in html
    assert '$1,582/night' not in html and 'base nightly rate' not in html
    _assert_open(html)


def test_each_listing_keeps_its_actual_suggested_dates_outlier_price_and_own_photo():
    first = _listing()
    second = _listing(name='Different trip', listing_id='222', total_price=2500, price_formatted='$2,500',
                      price_qualifier='for 3 nights', check_in_date='2026-12-15', check_out_date='2026-12-18',
                      nights=3, nightly_average=2500 / 3,
                      url='https://www.airbnb.com/rooms/222?check_in=2026-12-15&check_out=2026-12-18',
                      thumbnail='https://a0.muscache.com/im/pictures/second.jpeg')
    third = _listing(name='No photo', listing_id='333', thumbnail=None, image_url=None, images=[])
    html = _render({'serpapi_airbnb_search': _payload(
        results=[first, second, third], top_results=[first, second, third], top_image_url=first['thumbnail'],
    )})
    articles = html.split('<article')[1:]
    assert len(articles) == 3
    assert 'first.jpeg' in articles[0] and 'second.jpeg' not in articles[0]
    assert 'second.jpeg' in articles[1] and 'first.jpeg' not in articles[1]
    assert '<img' not in articles[2]
    assert 'Suggested dates: 2026-11-29 → 2026-12-04' in articles[0]
    assert 'Suggested dates: 2026-12-15 → 2026-12-18' in articles[1]
    assert '$2,500 total incl. fees' in articles[1] and '$833.33/night average' in articles[1]
    assert 'rooms/222?check_in=2026-12-15&amp;check_out=2026-12-18' in articles[1]
    assert 'within budget' not in html.lower()
    _assert_open(html)


def test_zero_values_stay_visible_but_false_cancellation_and_missing_prices_are_not_invented():
    zero = _listing(name='Zero evidence', total_price=0, price_formatted=None, nightly_average=0,
                    rating=0, reviews=0, bedrooms=0, beds=0, bathrooms=0,
                    free_cancellation=False, is_new_listing=False)
    missing = _listing(name='Price unknown', total_price=None, price_formatted=None,
                       nightly_average=None, nights=None, rating=None, reviews=None,
                       bedrooms=None, beds=None, bathrooms=None, free_cancellation=False)
    html = _render({'serpapi_airbnb_search': _payload(results=[zero, missing], top_results=[zero, missing])})
    first, second = html.split('<article')[1:]
    for value in ('$0 total incl. fees', '$0.00/night average', '★ 0', '0 reviews', '0 bedrooms', '0 beds', '0 baths'):
        assert value in first
    assert 'Free cancellation' not in html and 'New listing' not in html
    assert 'Price not returned' in second and '/night average' not in second and '$0' not in second


def test_explicit_dates_stay_per_listing_through_saved_and_workflow_reload():
    row = _listing(dates_mode='explicit')
    payload = _payload(dates_mode='explicit', results=[row], top_results=[row])
    raw = {'serpapi_airbnb_search': payload}
    restored_html = _render(json.loads(json.dumps(raw)))
    assert _render(raw) == restored_html
    _assert_open(restored_html)
    assert 'Dates: 2026-11-29 → 2026-12-04' in _render(raw)
    assert 'Suggested dates:' not in _render(raw)
    workflow = {'workflow': {'workflow_id': 'stay-fixture', 'action': 'run', 'results': [
        {'tool': 'serpapi_airbnb_search', 'data': payload},
        {'tool': 'serpapi_airbnb_search', 'data': _payload()},
    ]}}
    html = _render(json.loads(json.dumps(workflow)))
    assert html.count('data-workflow-tool="serpapi_airbnb_search"') == 2
    assert 'Dates: 2026-11-29 → 2026-12-04' in html
    assert 'Suggested dates: 2026-11-29 → 2026-12-04' in html
    _assert_open(html, 2)


def test_external_listing_fields_are_escaped_and_unsafe_media_actions_are_rejected():
    row = _listing(name='<script>bad()</script>', title='<b>Home</b>',
                   url='javascript:bad()', thumbnail='data:text/html,bad',
                   price_formatted='<img src=x onerror=bad()>', badges=['<script>badge()</script>'],
                   price_disclaimers=['<iframe>inert</iframe>'])
    payload = _payload(results=[row], top_results=[row],
                       budget_context={'note': '<script>budget()</script>'})
    html = _render({'serpapi_airbnb_search': payload})
    for value in ('&lt;script&gt;bad()&lt;/script&gt;', '&lt;b&gt;Home&lt;/b&gt;',
                  '&lt;img src=x onerror=bad()&gt;', '&lt;iframe&gt;inert&lt;/iframe&gt;'):
        assert value in html
    assert 'budget()' not in html
    assert '<script>' not in html and '<iframe>' not in html and '<img src=x' not in html
    assert 'href="javascript:' not in html and 'src="data:' not in html


def test_malformed_or_empty_results_have_a_truthful_empty_state():
    for results in (None, {}, [None, False, 1, 'bad', [], {}, {'name': {'unexpected': 'object'}}]):
        html = _render({'serpapi_airbnb_search': _payload(
            results=results, top_results=None, search_context=[], budget_context=[],
        )})
        assert 'No Airbnb listings returned' in html
        assert 'undefined' not in html and '[object Object]' not in html
        _assert_open(html)


def test_bounded_preview_labels_remaining_listings_without_borrowing_the_top_photo():
    rows = [_listing(name=f'Listing {index}', listing_id=str(index),
                     thumbnail=f'https://a0.muscache.com/im/pictures/{index}.jpeg')
            for index in range(7)]
    html = _render({'serpapi_airbnb_search': _payload(results=rows, top_results=rows, results_count=7)})
    assert '5 of 7 listings shown' in html
    assert 'Listing 4' in html and 'Listing 5' not in html
    assert html.count('<img ') == 5
    _assert_open(html)


def test_budget_subtitle_uses_effective_bounds_and_dates_without_internal_conversion_prose():
    cases = [
        ({'enabled': True, 'min_price_per_night': 125, 'max_price_per_night': 250}, '$125–$250/night budget'),
        ({'enabled': True, 'max_price_per_night': 100}, 'Up to $100/night'),
        ({'enabled': True, 'min_price_per_night': 0}, 'From $0/night'),
        ({'enabled': False, 'min_price_per_night': 125, 'max_price_per_night': 250}, 'No price filter'),
    ]
    for budget, expected in cases:
        budget.update(filter_nights=5, note='INTERNAL_CONVERSION_PROSE should stay in model data.')
        html = _render({'serpapi_airbnb_search': _payload(budget_context=budget)})
        assert expected in html and 'INTERNAL_CONVERSION_PROSE' not in html
        if budget['enabled']:
            assert 'Airbnb-suggested dates; budget based on 5 nights' in html
        else:
            assert 'Airbnb-suggested dates' in html and 'budget based on' not in html
    html = _render({'serpapi_airbnb_search': _payload(
        dates_mode='explicit', search_context={'dates_mode': 'explicit',
                                              'check_in_date': '2026-12-11', 'check_out_date': '2026-12-15'},
    )})
    assert '$125–$250/night budget' in html and '2026-12-11 → 2026-12-15' in html
    assert 'Airbnb-suggested dates' not in html


def test_rich_party_property_types_and_requested_amenities_survive_saved_reload():
    context = {**_payload()['search_context'], 'property_types': ['house', 'guesthouse'],
               'children': 3, 'infants': 1, 'pets': 2, 'amenities': ['pool', 'wifi', 'air_conditioning']}
    raw = {'serpapi_airbnb_search': _payload(search_context=context)}
    html = _render(raw)
    assert html == _render(json.loads(json.dumps(raw)))
    assert ('entire home · houses, guesthouses · 2 adults · 3 children · 1 infant · 2 pets · '
            'Requested amenities: pool, Wi-Fi, air conditioning') in html
    assert 'air_conditioning' not in html
    assert '$1,582 total incl. fees' in html and '$125–$250/night budget' in html
    _assert_open(html)


def test_private_room_optional_party_counts_and_omitted_property_filters_stay_truthful():
    context = {'room_type': 'private_room', 'property_types': ['apartment'], 'adults': 1,
               'children': 0, 'infants': 0, 'pets': 0, 'amenities': []}
    html = _render({'serpapi_airbnb_search': _payload(search_context=context)})
    subtitle = html.split('class="structured-results-subtitle">', 1)[1].split('</div>', 1)[0]
    assert 'private room · apartments · 1 adult' in subtitle
    for unwanted in ('child', 'infant', 'pet', 'Requested amenities:'):
        assert unwanted not in subtitle
    assert 'pet-free' not in html and 'pet friendly' not in html.lower()

    context.update(children=1, infants=2, pets=1)
    html = _render({'serpapi_airbnb_search': _payload(search_context=context)})
    assert '1 child · 2 infants · 1 pet' in html

    context.update(property_types=[])
    html = _render({'serpapi_airbnb_search': _payload(search_context=context)})
    subtitle = html.split('class="structured-results-subtitle">', 1)[1].split('</div>', 1)[0]
    assert 'private room' in subtitle and 'apartments' not in subtitle and 'houses' not in subtitle

    html = _render({'serpapi_airbnb_search': _payload(search_context={})})
    subtitle = html.split('class="structured-results-subtitle">', 1)[1].split('</div>', 1)[0]
    for invented in ('entire home', 'houses', 'adult', 'child', 'infant', 'pet', 'Requested amenities:'):
        assert invented not in subtitle


def test_external_amenity_names_are_readable_and_escaped_in_the_search_subtitle():
    context = {**_payload()['search_context'], 'amenities': ['wifi', 'hot_tub', '<img src=x onerror=bad()>']}
    html = _render({'serpapi_airbnb_search': _payload(search_context=context)})
    assert 'Requested amenities: Wi-Fi, hot tub, &lt;img src=x onerror=bad()&gt;' in html
    assert 'hot_tub' not in html and '<img src=x' not in html
    _assert_open(html)
