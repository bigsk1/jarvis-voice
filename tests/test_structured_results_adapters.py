"""Behavior at the extracted structured-result adapter boundaries."""

import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLIENT_JS = PROJECT_ROOT / "jarvis-web" / "client" / "js"


def _run_renderer_assertions(assertions):
    scripts = [
        CLIENT_JS / "structured-results-shopping.js",
        CLIENT_JS / "structured-results-search.js",
        CLIENT_JS / "structured-results-local-travel.js",
        CLIENT_JS / "structured-results.js",
    ]
    script = f"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const escapeHtml = value => String(value)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const sandbox = {{URL, console, Utils: {{
  escapeHtml,
  safeHttpUrlForAttr: value => {{
    try {{
      const url = new URL(String(value));
      return ['http:', 'https:'].includes(url.protocol) ? escapeHtml(url.href) : '';
    }} catch (_error) {{ return ''; }}
  }},
}}}};
sandbox.window = sandbox;
vm.createContext(sandbox);
for (const filename of {json.dumps([str(path) for path in scripts])}) {{
  vm.runInContext(fs.readFileSync(filename, 'utf8'), sandbox, {{filename}});
}}
const renderer = sandbox.structuredResultsRenderer;
{assertions}
"""
    subprocess.run(["node", "-e", script], cwd=PROJECT_ROOT, check=True)


def test_family_registration_is_instance_local_and_keeps_saved_amazon_alias():
    _run_renderer_assertions("""
const first = new sandbox.StructuredResultsRenderer();
const second = new sandbox.StructuredResultsRenderer();
const payload = {
  engine: 'amazon_product',
  asin: 'SAVED-123',
  results: [{title: 'Saved product', url: 'https://example.test/product', price: '$12'}],
};
const saved = first.render({serpapi_search: {data: payload}});
assert.ok(saved.includes('Saved product'));
assert.ok(saved.includes('Amazon product'));
assert.equal(saved, first.render({serpapi_amazon_search: {data: payload}}));
assert.equal(saved, second.render({serpapi_amazon_search: {data: payload}}));

first.register('serpapi_amazon_search', () => ({
  eyebrow: 'Custom adapter', items: [{title: 'Replacement item'}],
}));
assert.ok(first.render({serpapi_amazon_search: payload}).includes('Replacement item'));
assert.equal(second.render({serpapi_amazon_search: payload}), saved);
assert.equal(renderer.render({serpapi_amazon_search: payload}), saved);
assert.equal(first.render({serpapi_search: payload}), saved);
""")


def test_shopping_detail_fallbacks_preserve_bid_images_and_document_formats():
    _run_renderer_assertions("""
const homeDepot = renderer.render({serpapi_home_depot: {
  product_details: {
    title: 'Detail-only drill', url: 'https://example.test/drill',
    brand: {name: 'Example Tools'}, price: {amount: 29, currency: 'USD'},
  },
}});
for (const text of ['Detail-only drill', 'Example Tools', 'USD 29']) {
  assert.ok(homeDepot.includes(text), text);
}
const ebay = renderer.render({serpapi_ebay_product: {
  product_summary: {
    title: 'Auction item', url: 'https://example.test/auction',
    image_urls: ['https://example.test/first.jpg', 'https://example.test/last.jpg'],
    buy: {bid: {price: {currency: 'USD', amount: 15}}},
  },
}});
assert.ok(ebay.includes('Bid USD 15'));
assert.ok(ebay.includes('https://example.test/last.jpg'));
assert.ok(!ebay.includes('https://example.test/first.jpg'));

for (const format of ['html', 'markdown']) {
  const html = renderer.render({serpapi_google_immersive_product: {
    output_format: format,
    content: '<b>Specs & details</b>',
    product_summary: {title: 'Product document'},
    top_url: 'javascript:alert(1)',
  }});
  assert.ok(html.includes('Untrusted external content'));
  assert.ok(html.includes('Specs &amp; details'));
  assert.ok(!html.includes('<b>'));
  assert.ok(!html.includes('href="javascript:'));
  assert.equal(html.includes('&lt;b&gt;'), format === 'markdown');
}
""")


def test_search_family_keeps_row_limits_latest_runs_and_news_order():
    _run_renderer_assertions("""
const current = {
  query: 'Current search',
  results: Array.from({length: 7}, (_, index) => ({
    title: `Source ${index + 1}`, url: `https://example.test/${index + 1}`,
  })),
};
const html = renderer.render({serpapi_search_index: [
  {query: 'Earlier search', results: [{title: 'Stale source'}]}, current,
]});
assert.ok(html.includes('Current search'));
assert.ok(html.includes('Source 5'));
assert.ok(!html.includes('Source 6'));
assert.ok(!html.includes('Earlier search'));
assert.ok(!html.includes('Stale source'));
const news = renderer.render({serpapi_google_news_light: {
  top_stories: [{title: 'Top stories', stories: [{title: 'Lead story'}]}],
  results: [{title: 'Ordinary story'}],
}});
assert.ok(news.includes('Lead story'));
assert.ok(news.includes('Ordinary story'));
assert.ok(news.indexOf('Lead story') < news.indexOf('Ordinary story'));
const trendNews = renderer.render({serpapi_google_trending_now: {
  action: 'news', trend_query: 'Follow-up trend',
  results: [{title: 'Trend article', source: 'Example News'}],
}});
assert.ok(trendNews.includes('Google Trends News'));
assert.ok(trendNews.includes('Follow-up trend'));
assert.ok(trendNews.includes('Trend article'));
""")


def test_local_travel_helpers_preserve_currency_zero_prices_and_provider_times():
    _run_renderer_assertions("""
const flights = renderer.render({flight_search: {
  currency: 'EUR', departure_id: 'AMS', arrival_id: 'CDG',
  results: [{
    price: 0, airlines: 'Example Air', flight_numbers: 'EA 123',
    departure_time: '2099-08-11 00:05', arrival_time: '2099-08-11 12:30',
  }],
}});
for (const text of [
  'EUR 0', 'AMS → CDG', 'Example Air', 'EA 123',
  'Departs 08/11/2099 · 12:05 AM', 'Arrives 08/11/2099 · 12:30 PM',
]) assert.ok(flights.includes(text), text);

const travel = renderer.render({serpapi_travel_explore: {
  currency: 'EUR', departure_id: 'AMS',
  results: [{name: 'Paris', flight_price: 0, hotel_price: 0}],
}});
assert.ok(travel.includes('EUR 0 flight signal'));
assert.ok(travel.includes('Hotel signal EUR 0'));
""")


def test_local_places_keep_organic_ad_and_discovery_order_and_independent_limits():
    _run_renderer_assertions("""
const html = renderer.render({serpapi_google_local: {
  results: Array.from({length: 6}, (_, index) => ({
    title: `Organic ${index + 1}`, website: 'https://example.test/cafe',
    description: '<script>Untrusted text</script>',
    service_options: {dine_in: true, takeout: true, delivery: false},
  })),
  ads: Array.from({length: 4}, (_, index) => ({title: `Advert ${index + 1}`})),
  discover_more_places: Array.from({length: 4}, (_, index) => ({
    title: `Discovery ${index + 1}`, places: ['Cafe One', 'Cafe Two'],
  })),
}});
for (const text of [
  'Organic 5', 'Advert 3', 'Discovery 3', 'Sponsored', 'Dine In', 'Takeout',
  'Cafe One · Cafe Two', 'Open website', '&lt;script&gt;Untrusted text&lt;/script&gt;',
]) assert.ok(html.includes(text), text);
for (const text of ['Organic 6', 'Advert 4', 'Discovery 4', '<script>', 'Delivery']) {
  assert.ok(!html.includes(text), text);
}
assert.ok(html.indexOf('Organic 5') < html.indexOf('Advert 1'));
assert.ok(html.indexOf('Advert 3') < html.indexOf('Discovery 1'));

const provider = renderer.render({serpapi_google_local_services: {
  mode: 'provider_details',
  results: [{title: 'Provider', website: 'https://example.test/provider',
    years_in_business: 1, bookings_nearby: 0, services: ['Repair', 'Install']}],
}});
for (const text of ['Provider details', '1 year in business', '0 bookings nearby',
  'Repair · Install', 'Open website']) assert.ok(provider.includes(text), text);
""")
