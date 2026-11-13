"""Travel cards and saved follow-ups keep provider guarantees truthful."""

import importlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
JS_ROOT = ROOT / 'jarvis-web' / 'client' / 'js'
load_server_package('travel_release_web_server', ROOT / 'jarvis-web' / 'server')
followup = importlib.import_module('travel_release_web_server.services.followup_extractor')


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
const sandbox = {URL, window: {}, Utils: {
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


def _extract(tool, payload):
    original = deepcopy(payload)
    result = followup.extract_followup_data({tool: {'ok': True, 'data': payload}})[tool]
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    assert payload == original
    return result


def _event(**overrides):
    return {'title': 'Park concert', 'url': 'https://events.example/concert',
            'when': 'Friday evening', 'type': 'In-person', **overrides}


def test_events_query_preferences_are_not_result_guarantees_after_saved_reload():
    payload = {'query': 'concerts', 'query_preferences': {'date_filter': 'week', 'virtual': True},
               'query_preferences_note': 'Date and virtual requests are query preferences, not strict filters.',
               'results': [_event()]}
    data = {'serpapi_google_events': {'ok': True, 'data': payload}}
    html = _render(json.loads(json.dumps(data)))
    assert html == _render(data)
    for label in ('Date preference: this week', 'Virtual requested (not guaranteed)',
                  'query preferences, not strict filters', 'In-person', 'Friday evening'):
        assert label in html
    assert 'Virtual only' not in html
    saved = _extract('serpapi_google_events', payload)
    assert saved['query_preferences'] == payload['query_preferences']
    assert saved['pagination_supported'] is False


@pytest.mark.parametrize('legacy', [
    {'date_filter': 'next_week', 'virtual': True},
    {'filters': ['date:week', 'event_type:Virtual-Event']},
])
def test_legacy_event_filters_are_unverified_requests_without_rewriting_saved_data(legacy):
    payload = {'query': 'concerts', 'results': [_event()], 'start': 10,
               'pagination': {'has_more': True, 'next_start': 20}, **legacy}
    html = _render({'serpapi_google_events': json.loads(json.dumps(payload))})
    assert 'Saved filter requests are unverified' in html and 'Virtual only' not in html
    saved = _extract('serpapi_google_events', payload)
    assert 'unverified' in saved['query_preferences_note']
    assert saved['pagination_supported'] is False
    assert not {'filters', 'date_filter', 'virtual', 'pagination', 'start', 'has_more', 'next_start'} & saved.keys()
    assert 'Saved filter requests are unverified' in _render({'serpapi_google_events': saved})


def test_complete_event_token_survives_saved_followup_without_provider_details_url():
    token = 'opaque-provider-event-token.' * 100
    payload = {'query': 'concerts', 'query_preferences': {}, 'results': [_event(
        event_token=token, serpapi_details_link='https://serpapi.com/search?api_key=SECRET_SENTINEL',
    )]}
    saved = _extract('serpapi_google_events', payload)
    assert saved['candidates'][0]['event_token'] == token
    assert 'SECRET_SENTINEL' not in json.dumps(saved)


def test_maps_midnight_zero_price_and_rating_preference_survive_card_and_followup():
    filters = {'min_price': 0, 'max_price': 50, 'min_rating': 4.5,
               'open_on_day': 'fri', 'open_at_hour': 0}
    payload = {'query': 'cafes', 'requested_filters': filters, 'effective_filters': filters,
               'filter_notes': ['Rating is a ranking preference, not a strict cutoff.'],
               'results': [{'title': 'Cafe', 'url': 'https://cafe.example', 'rating': 3.5, 'reviews': 0}]}
    html = _render({'serpapi_maps_search': json.loads(json.dumps(payload))})
    for label in ('Price ranges overlapping 0–50', 'Rating preference: 4.5+',
                  'lower or unrated places may appear', 'Open Friday at 00:00', '★ 3.5', '0 reviews'):
        assert label in html
    saved = _extract('serpapi_maps_search', payload)
    assert saved['requested_filters'] == filters and saved['effective_filters'] == filters
    assert saved['filter_notes'] == payload['filter_notes']
    assert saved['candidates'][0]['rating'] == 3.5 and saved['candidates'][0]['reviews'] == 0


def test_maps_requested_only_filters_are_not_presented_as_verified_saved_filters():
    html = _render({'serpapi_maps_search': {
        'query': 'cafes', 'requested_filters': {'min_rating': 4, 'open_state': '24h'},
        'results': [{'title': 'Cafe'}],
    }})
    assert 'Saved requested filters are unverified' in html
    assert 'Rating preference: 4+' in html and 'Open 24 hours' in html


@pytest.mark.parametrize('enriched', [False, True])
def test_tripadvisor_review_evidence_survives_workflow_reload_and_saved_followup(enriched):
    place = {'title': 'Museum', 'url': 'https://www.tripadvisor.com/Attraction_Review-d123.html',
             'rating': 4.5, 'reviews': 100, 'award': {'type': "Travelers' Choice", 'year': '2026'},
             'award_truncated': False, 'review_distribution': [
                 {'rating': 'Excellent', 'count': 100}, {'rating': 'Terrible', 'count': 0},
             ], 'review_distribution_truncated': False}
    payload = {'action': 'search' if enriched else 'details', 'query': 'museums',
               **({'detail_data': {'place': place}} if enriched else {'place': place})}
    workflow = {'workflow': {'workflow_id': 'travel-fixture', 'action': 'run', 'results': [
        {'tool': 'serpapi_tripadvisor', 'data': payload},
    ]}}
    html = _render(json.loads(json.dumps(workflow)))
    for label in ('Travelers&#39; Choice', '2026', 'Review breakdown: Excellent: 100 · Terrible: 0'):
        assert label in html
    saved = _extract('serpapi_tripadvisor', payload)
    compact_place = saved['detail_data']['place'] if enriched else saved['place']
    assert compact_place['award'] == place['award']
    assert compact_place['review_distribution'] == place['review_distribution']
    assert compact_place['award_truncated'] is False and compact_place['review_distribution_truncated'] is False


def test_tripadvisor_bounded_summary_is_labeled_and_external_review_labels_are_escaped():
    place = {'title': 'Museum', 'award': {'type': '<script>award()</script>' + 'x' * 250, 'year': '2026'},
             'review_distribution': [{'rating': '<img src=x onerror=bad()>', 'count': index} for index in range(7)]}
    payload = {'action': 'details', 'place': place}
    saved = _extract('serpapi_tripadvisor', payload)
    assert len(saved['place']['review_distribution']) == 5
    assert saved['place']['award_truncated'] and saved['place']['review_distribution_truncated']
    assert len(saved['place']['award']['type']) < len(place['award']['type'])
    html = _render({'serpapi_tripadvisor': saved})
    assert 'Some review summary details omitted' in html
    assert '&lt;script&gt;award()&lt;/script&gt;' in html and '&lt;img src=x onerror=bad()&gt;' in html
    assert '<script>' not in html and '<img src=x' not in html
