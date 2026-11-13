"""SerpApi Extract result cards and durable follow-up context contracts."""

import importlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from server_package_utils import load_server_package

from lib.serpapi_extract_context import project_serpapi_extract_runs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JS_ROOT = PROJECT_ROOT / 'jarvis-web' / 'client' / 'js'
load_server_package('serpapi_extract_web_server', PROJECT_ROOT / 'jarvis-web' / 'server')
followup = importlib.import_module('serpapi_extract_web_server.services.followup_extractor')


def _payload(mode='scrape', **overrides):
    return {
        'provider': 'serpapi', 'engine': 'extract', 'mode': mode,
        'requested_url': 'https://example.test/start?edition=one&view=all',
        'url': 'https://example.test/final',
        'search_id': 'search-7', 'credits_consumed': 0,
        'external_content_trust': 'untrusted',
        **overrides,
    }


def _extract(payload, **kwargs):
    compact = followup.extract_followup_data({'serpapi_extract': payload}, **kwargs)['serpapi_extract']
    assert json.loads(json.dumps(compact, ensure_ascii=False, allow_nan=False)) == compact
    return compact


def _render(payload):
    paths = [str(JS_ROOT / name) for name in (
        'structured-results-shopping.js', 'structured-results-search.js',
        'structured-results-local-travel.js', 'structured-results.js',
    )]
    script = r"""
const fs = require('fs');
const vm = require('vm');
const escapeHtml = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const sandbox = {URL, window: {}, console, Utils: {
  escapeHtml,
  safeHttpUrlForAttr: value => {
    try {
      const parsed = new URL(String(value));
      return ['http:', 'https:'].includes(parsed.protocol) ? escapeHtml(parsed.href) : '';
    } catch (_) { return ''; }
  },
}};
vm.createContext(sandbox);
vm.runInContext(PATHS.map(path => fs.readFileSync(path, 'utf8')).join('\n'), sandbox);
const renderer = sandbox.window.structuredResultsRenderer;
process.stdout.write(renderer.render({serpapi_extract: PAYLOAD}));
""".replace('PATHS', json.dumps(paths)).replace('PAYLOAD', json.dumps(payload))
    return subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True).stdout


def test_scrape_followup_keeps_distinct_addresses_feed_and_plain_text_without_private_fields():
    body = '# A page\n\nQuoted "text", a backslash \\, and <script>inert()</script>.\n'
    payload = _payload(
        title='Page title', content=body, content_chars=len(body), content_truncated=False,
        page_information={'title': 'Canonical title', 'description': 'Page description',
                          'canonical': 'https://example.test/canonical',
                          'final_url': 'https://example.test/final', 'language': 'en',
                          'favicon': 'https://example.test/favicon.ico', 'api_key': 'SECRET_SENTINEL'},
        feeds=[{'title': 'Updates', 'url': 'https://example.test/feed.xml', 'type': 'rss',
                'raw': 'SECRET_SENTINEL'}],
        feeds_count=1, provider_feeds_count=3, feeds_truncated=True,
        links=[{'title': 'Next', 'url': 'https://example.test/next', 'internal': False}],
        api_key='SECRET_SENTINEL', raw_response={'private': 'SECRET_SENTINEL'},
    )
    before = deepcopy(payload)
    result = _extract({'ok': True, 'data': payload})
    assert result['requested_url'] == payload['requested_url']
    assert result['url'] == payload['url']
    assert result['page_information']['canonical'] == 'https://example.test/canonical'
    assert result['page_information']['final_url'] == payload['url']
    assert result['content_excerpt'] == body
    assert result['content_excerpt_truncated'] is False
    assert result['context_truncated'] is True  # Provider omitted two feeds.
    assert result['content_truncated'] is False
    assert result['credits_consumed'] == 0
    assert result['feeds'] == [{'title': 'Updates', 'url': 'https://example.test/feed.xml', 'type': 'rss'}]
    assert result['feeds_count'] == 1 and result['provider_feeds_count'] == 3
    assert result['feeds_truncated'] is True and result['context_feeds_truncated'] is False
    assert result['links'][0]['internal'] is False
    assert result['external_content_trust'] == 'untrusted'
    assert 'SECRET_SENTINEL' not in json.dumps(result)
    assert 'content' not in result and 'pages' not in result
    assert payload == before


def test_map_followup_preserves_returned_urls_and_distinguishes_provider_omissions():
    urls = [{'url': f'https://example.test/page/{i}?a=1&b=2', 'title': f'Page {i}', 'source': 'sitemap'}
            for i in range(5)]
    result = _extract(_payload('map', urls=urls, urls_count=5, provider_urls_count=40,
                               urls_truncated=True), max_candidates=2)
    assert result['candidates'] == [{**row, 'ordinal': index + 1} for index, row in enumerate(urls)]
    assert result['candidates_truncated'] is False
    assert result['urls_count'] == 5 and result['provider_urls_count'] == 40
    assert result['urls_truncated'] is True


def test_crawl_followup_preserves_per_page_identity_errors_and_shortened_excerpt_notice():
    pages = [{
        'url': f'https://example.test/page/{i}', 'depth': i, 'title': f'Page {i}',
        'content': 'article evidence ' * 1000, 'content_chars': 17000,
        'content_truncated': i == 0,
        'page_information': {'canonical': f'https://example.test/canonical/{i}'},
        'feeds': [{'title': 'News', 'url': f'https://example.test/feed/{i}', 'type': 'atom'}],
        'links': [],
    } for i in range(4)]
    pages[1]['error'] = 'One section unavailable'
    result = _extract(_payload('crawl', pages=pages, pages_count=4, provider_pages_count=8,
                               pages_truncated=True), max_candidates=2)
    assert result['pages_count'] == 4 and result['provider_pages_count'] == 8
    assert result['pages_truncated'] is True and result['context_pages_truncated'] is False
    assert [row['url'] for row in result['pages']] == [row['url'] for row in pages]
    for i, row in enumerate(result['pages']):
        assert row['depth'] == i
        assert row['page_information'] == pages[i]['page_information']
        assert row['feeds'] == pages[i]['feeds']
        assert row['content_chars'] == 17000
        assert row['content_truncated'] is (i == 0)
        assert row['content_excerpt_truncated'] is True
        assert row['content_excerpt'].endswith('[truncated for follow-up context]')
        assert 'content' not in row
    assert result['pages'][1]['error'] == 'One section unavailable'
    assert len(json.dumps(result, ensure_ascii=False)) < 10000


def test_repeated_reader_modes_keep_separate_runs_and_shared_followup_budget():
    runs = [_payload(content='obsolete'),
            _payload('map', urls=[{'url': 'https://example.test/candidate'}], urls_count=1),
            _payload(content='evidence ' * 3000, content_truncated=False),
            _payload('crawl', pages=[{'url': 'https://example.test/child',
                                      'content': 'child evidence ' * 2000}], pages_count=1)]
    result = _extract(runs)
    assert result['runs_count'] == 4 and result['results_truncated'] is True
    assert [row['mode'] for row in result['results']] == ['map', 'scrape', 'crawl']
    assert result['results'][0]['candidates'][0]['url'] == 'https://example.test/candidate'
    assert 'obsolete' not in json.dumps(result)
    assert len(json.dumps(result, ensure_ascii=False)) < 10000


def test_escape_heavy_excerpts_still_fit_saved_context_without_corrupting_plain_text():
    body = ('"quoted"\\value\n' * 3000)
    result = _extract([_payload(content=body), _payload(content=body), _payload(content=body)])
    assert len(json.dumps(result, ensure_ascii=False, separators=(',', ':'))) < 10000
    for row in result['results']:
        assert row['content_excerpt_truncated'] is True
        assert row['content_excerpt'].startswith('"quoted"\\value\n')


def test_shared_context_budget_retains_more_immediate_article_text_and_aggregates_omissions():
    body = 'article evidence ' * 1000
    result = project_serpapi_extract_runs(_payload(content=body, content_truncated=False), max_chars=10000)
    assert len(result['content_excerpt']) >= 6000
    assert len(json.dumps(result, ensure_ascii=False)) <= 10000
    assert result['context_truncated'] is True
    assert result['content_excerpt'].endswith('[truncated for context]')
    complete = project_serpapi_extract_runs(_payload(content='A complete page.', content_truncated=False))
    assert complete['context_truncated'] is False
    provider_excerpt = project_serpapi_extract_runs(_payload(content='A short excerpt.', content_truncated=True))
    assert provider_excerpt['context_truncated'] is True


@pytest.mark.parametrize('mode', ['scrape', 'map', 'crawl'])
def test_shared_projection_roundtrips_saved_modes_without_eroding_excerpts_or_addresses(mode):
    payload = _payload(mode, content='article evidence ' * 1000, content_truncated=False)
    if mode == 'map':
        payload.update(urls=[{'url': f'https://example.test/{i}', 'title': f'Page {i}'} for i in range(8)],
                       urls_count=8, provider_urls_count=10, urls_truncated=True)
    if mode == 'crawl':
        payload.update(pages=[{'url': 'https://example.test/child', 'content': 'child evidence ' * 1000,
                              'content_truncated': False}], pages_count=1)
    first = project_serpapi_extract_runs(payload)
    second = project_serpapi_extract_runs(first)
    assert second == first
    assert project_serpapi_extract_runs(second) == first
    smaller = project_serpapi_extract_runs(second, max_chars=1000)
    assert len(json.dumps(smaller, ensure_ascii=False)) <= 1000
    assert smaller['context_truncated'] is True


@pytest.mark.parametrize('run_count', [3, 4])
def test_projected_repeated_run_wrapper_retains_original_counts_and_omission_flags(run_count):
    raw = [_payload(content='article evidence ' * 1000) for _ in range(run_count)]
    first = project_serpapi_extract_runs(raw)
    second = project_serpapi_extract_runs(first)
    assert second == first
    assert second['runs_count'] == run_count and second['results_truncated'] is (run_count > 3)
    assert second['context_truncated'] is True


def test_long_source_metadata_omits_whole_fields_with_notice_instead_of_corrupting_urls():
    url = 'https://example.test/' + 'a' * 2000
    payload = _payload(requested_url=url + '?requested', url=url + '?final',
                       page_information={'final_url': url + '?final', 'canonical': url + '?canonical',
                                         'favicon': url + '?favicon', 'description': 'detail ' * 400},
                       feeds=[{'url': url + '?feed', 'title': 'Updates'}],
                       content='evidence ' * 1000)
    result = _extract(payload)
    assert len(json.dumps(result, ensure_ascii=False, separators=(',', ':'))) < 10000
    assert result['context_metadata_truncated'] is True
    assert result['requested_url'] == payload['requested_url']
    assert result['url'] == payload['url']
    assert result['context_feeds_truncated'] is True
    smallest = project_serpapi_extract_runs(payload, max_chars=256)
    assert len(json.dumps(smallest, ensure_ascii=False)) <= 256
    assert smallest['context_truncated'] is True


def test_scrape_cards_keep_plain_reader_content_and_safe_feed_and_link_actions():
    body = 'First line\n<script>inert()</script>\nLast line'
    html = _render(_payload(
        title='<img src=x onerror=evil()>', content=body, content_truncated=True,
        page_information={'canonical': 'https://example.test/canonical'},
        feeds=[{'title': 'Updates & news', 'url': 'https://example.test/feed?a=1&b=2', 'type': 'rss'}],
        links=[{'title': 'Unsafe link', 'url': 'javascript:evil()', 'internal': False}],
    ))
    assert html.lstrip().startswith('<details ')
    assert ' open' not in html.split('>', 1)[0]
    assert 'SerpApi Extract' in html and 'Read returned content' in html
    assert 'Content shortened' in html and 'returned page content was shortened' in html
    assert 'Canonical: https://example.test/canonical' in html
    assert 'Requested: https://example.test/start?edition=one&amp;view=all' in html
    assert 'href="https://example.test/feed?a=1&amp;b=2"' in html
    assert 'Updates &amp; news' in html
    assert '<script>' not in html and '<img src=x' not in html
    assert 'href="javascript:' not in html
    assert 'First line\n&lt;script&gt;inert()&lt;/script&gt;\nLast line' in html


def test_discovery_cards_show_all_returned_urls_and_feed_only_scrapes_stay_truthful():
    urls = [{'url': f'https://example.test/{i}'} for i in range(25)]
    html = _render(_payload('map', urls=urls, urls_count=25, provider_urls_count=25, urls_truncated=False))
    assert '25 URLs shown' in html
    assert 'href="https://example.test/19"' in html
    assert 'href="https://example.test/20"' in html
    assert 'href="https://example.test/24"' in html
    html = _render(_payload(content='', content_omitted=True, feeds=[{
        'title': 'News', 'url': 'https://example.test/feed', 'type': 'atom',
    }], feeds_count=1, provider_feeds_count=4, feeds_truncated=True))
    assert 'Page content not requested' in html and '1 of 4 feeds shown' in html
    assert 'Read returned content' not in html
    assert 'Open feed' in html


@pytest.mark.parametrize('count', [50, 100])
def test_complete_map_followups_and_cards_share_every_returned_url_including_fifteenth(count):
    # Compact rows fit the reader's 10000-character saved-context budget, even at
    # the tool's maximum 100 returned URLs. Generic search limits do not apply.
    urls = [{'url': f'https://e.test/{i}', 'title': f'Page {i}', 'source': 'sitemap'}
            for i in range(count)]
    payload = _payload('map', urls=urls, urls_count=count, provider_urls_count=count,
                       urls_truncated=False)
    saved = _extract(payload)
    assert len(json.dumps(saved, ensure_ascii=False)) <= 10000
    assert saved['candidates'] == [{**row, 'ordinal': index + 1} for index, row in enumerate(urls)]
    assert saved['candidates'][14]['url'] == urls[14]['url']
    assert saved['candidates'][14]['ordinal'] == 15
    assert saved['candidates'][-1]['url'] == urls[-1]['url']
    assert saved['candidates_truncated'] is False and saved['context_truncated'] is False
    html = _render(payload)
    assert f'{count} URLs shown' in html
    assert f'href="{urls[14]["url"]}"' in html
    assert f'href="{urls[-1]["url"]}"' in html
    assert '15. Page 14' in html
    assert f'{count}. Page {count - 1}' in html
    assert html.index(f'href="{urls[14]["url"]}"') < html.index(f'href="{urls[-1]["url"]}"')
    assert 'Results shortened' not in html


def test_complete_crawl_retains_ten_pages_and_each_page_reference_collection():
    pages = [{
        'url': f'https://e.test/{i}', 'depth': 1, 'content': f'Page {i} fact.',
        'content_truncated': False,
    } for i in range(10)]
    result = _extract(_payload('crawl', pages=pages, pages_count=10, provider_pages_count=10,
                               pages_truncated=False), max_candidates=2)
    assert [row['url'] for row in result['pages']] == [row['url'] for row in pages]
    assert result['context_pages_truncated'] is False and result['context_truncated'] is False
    links = [{'url': f'https://e.test/link/{i}', 'title': str(i), 'internal': True}
             for i in range(20)]
    feeds = [{'url': f'https://e.test/feed/{i}', 'title': str(i), 'type': 'rss'}
             for i in range(10)]
    page = {**pages[0], 'links': links, 'feeds': feeds}
    result = _extract(_payload('crawl', pages=[page], pages_count=1), max_candidates=2)
    assert result['pages'][0]['links'] == links and result['pages'][0]['feeds'] == feeds
    assert result['pages'][0]['context_links_truncated'] is False
    assert result['pages'][0]['context_feeds_truncated'] is False
    assert result['context_truncated'] is False


@pytest.mark.parametrize('provider_omission', [False, True])
def test_metadata_only_followup_does_not_confuse_unrequested_body_with_truncation(provider_omission):
    payload = _payload(
        content='', content_chars=0, content_omitted=True, content_truncated=False,
        page_information={'title': 'Site metadata', 'canonical': 'https://example.test/canonical',
                          'final_url': 'https://example.test/final', 'language': 'en'},
        feeds=[{'title': 'Site updates', 'url': 'https://example.test/feed', 'type': 'rss'}],
        feeds_count=1, provider_feeds_count=2 if provider_omission else 1,
        feeds_truncated=provider_omission,
    )
    result = _extract(payload)
    assert result['content_omitted'] is True and result['content_truncated'] is False
    assert 'content_excerpt' not in result
    assert result['requested_url'] == payload['requested_url']
    assert result['url'] == payload['url']
    assert result['page_information'] == payload['page_information']
    assert result['feeds'] == payload['feeds']
    assert result['context_truncated'] is provider_omission
    html = _render(payload)
    assert 'Page content not requested' in html and 'Read returned content' not in html
    assert ('more feeds omitted' in html) is provider_omission


def test_actual_map_budget_omissions_remain_explicit_and_sources_are_never_partial():
    urls = [{'url': f'https://example.test/documentation/{i}', 'title': f'Page {i}',
             'source': 'sitemap'} for i in range(100)]
    result = project_serpapi_extract_runs(_payload(
        'map', urls=urls, urls_count=100, provider_urls_count=100, urls_truncated=False,
    ), max_chars=1000)
    assert len(json.dumps(result, ensure_ascii=False)) <= 1000
    assert result['context_truncated'] is True and result['candidates_truncated'] is True
    assert 0 < len(result['candidates']) < len(urls)
    assert [row['url'] for row in result['candidates']] == [row['url'] for row in urls[:len(result['candidates'])]]


def test_metadata_only_crawl_pages_are_complete_without_body_truncation():
    pages = [{
        'url': f'https://example.test/page/{i}', 'depth': 1,
        'content': '', 'content_omitted': True, 'content_truncated': False,
        'page_information': {'title': f'Page {i}', 'canonical': f'https://example.test/canonical/{i}'},
    } for i in range(3)]
    result = _extract(_payload('crawl', pages=pages, pages_count=3,
                               provider_pages_count=3, pages_truncated=False))
    assert result['context_truncated'] is False and result['context_pages_truncated'] is False
    for index, page in enumerate(result['pages']):
        assert page['content_omitted'] is True and page['content_truncated'] is False
        assert 'content_excerpt' not in page
        assert page['url'] == pages[index]['url']


def test_map_ordinals_survive_followup_roundtrip_and_metadata_compaction():
    urls = [{'url': f'https://e.test/page/{i}', 'title': f'Page {i}'} for i in range(50)]
    urls[14] = {'url': 'https://e.test/music_14', 'title': 'Music'}
    urls[15] = {'url': 'https://e.test/default_15', 'title': 'Default'}
    payload = _payload('map', urls=urls, urls_count=50, provider_urls_count=50, urls_truncated=False)
    saved = _extract(payload)
    assert saved['candidates'][14] == {'url': 'https://e.test/music_14', 'title': 'Music', 'ordinal': 15}
    assert saved['candidates'][15]['ordinal'] == 16
    assert project_serpapi_extract_runs(saved, max_chars=10000) == saved
    assert _extract(saved) == saved
    html = _render(payload)
    assert '15. Music' in html and '16. Default' in html

    long_labels = _payload('map', urls=[{**row, 'title': 'Long optional metadata ' * 30}
                                      for row in urls], urls_count=50, provider_urls_count=50,
                           urls_truncated=False)
    compact = project_serpapi_extract_runs(long_labels, max_chars=4500)
    assert compact['context_metadata_truncated'] is True
    assert [row['url'] for row in compact['candidates']] == [row['url'] for row in urls]
    assert [row['ordinal'] for row in compact['candidates']] == list(range(1, 51))
    assert project_serpapi_extract_runs(compact, max_chars=4500) == compact


@pytest.mark.parametrize(('mode', 'payload', 'expected'), [
    ('map', {'urls': [{'title': 'Documentation', 'url': 'https://example.test/docs', 'source': 'sitemap'}],
             'urls_count': 1, 'provider_urls_count': 9, 'urls_truncated': True},
     ['Discovered URLs', '1 of 9 URLs shown', 'sitemap', 'https://example.test/docs']),
    ('crawl', {'pages': [{'title': 'Child page', 'url': 'https://example.test/child', 'depth': 2,
                         'content': 'Child page body', 'content_truncated': False},
                        {'url': 'https://example.test/failed', 'error': '<b>Timed out</b>'}],
               'pages_count': 2, 'provider_pages_count': 4, 'pages_truncated': True},
     ['Crawled pages', '2 of 4 pages shown', 'Depth 2', 'Child page body', '&lt;b&gt;Timed out&lt;/b&gt;']),
])
def test_discovery_and_crawl_cards_keep_mode_counts_and_page_actions(mode, payload, expected):
    html = _render(_payload(mode, **payload))
    assert html.lstrip().startswith('<details ')
    assert ' open' not in html.split('>', 1)[0]
    for text in expected:
        assert text in html
    assert 'Results shortened' in html
    assert 'rel="noopener noreferrer"' in html
    assert '<b>Timed out</b>' not in html
