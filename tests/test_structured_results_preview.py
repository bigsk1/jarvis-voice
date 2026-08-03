#!/usr/bin/env python3
"""Regression coverage for shared structured tool-result previews."""

import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RENDERER_JS = PROJECT_ROOT / "jarvis-web" / "client" / "js" / "structured-results.js"
CHAT_JS = PROJECT_ROOT / "jarvis-web" / "client" / "js" / "chat.js"
INDEX_HTML = PROJECT_ROOT / "jarvis-web" / "client" / "index.html"
MAIN_CSS = PROJECT_ROOT / "jarvis-web" / "client" / "css" / "main.css"


def test_shared_renderer_formats_registered_hotel_yelp_flight_and_maps_results():
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(RENDERER_JS))}, 'utf8');
const escapeHtml = value => String(value)
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;');
const sandbox = {{
  URL,
  window: {{}},
  console,
  Utils: {{
    escapeHtml,
    safeHttpUrlForAttr: value => {{
      try {{
        const parsed = new URL(String(value));
        if (!['http:', 'https:'].includes(parsed.protocol)) return '';
        return escapeHtml(parsed.href);
      }} catch (_error) {{
        return '';
      }}
    }}
  }}
}};
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
const renderer = sandbox.window.structuredResultsRenderer;
const expectedTools = [
  'serpapi_search',
  'serpapi_home_depot',
  'serpapi_ebay_product',
  'serpapi_hotel_search',
  'serpapi_yelp_search',
  'flight_search',
  'serpapi_maps_search'
];
if (JSON.stringify(renderer.registeredTools()) !== JSON.stringify(expectedTools)) process.exit(2);

const html = renderer.render({{
  serpapi_search: {{
    engine: 'amazon_product',
    query: 'coffee grinder',
    results: [{{
      title: 'Precision Coffee Grinder',
      url: 'https://amazon.example/grinder',
      thumbnail: 'https://images.example/grinder.jpg',
      price: '$99',
      rating: 4.7,
      reviews: 1200,
      asin: 'B000TEST01'
    }}]
  }},
  serpapi_home_depot: {{
    query: 'drill',
    results: [{{
      title: 'Cordless Drill',
      url: 'https://homedepot.example/drill',
      thumbnail: 'https://images.example/drill.jpg',
      price_formatted: '$129',
      product_id: 'HD-7'
    }}]
  }},
  serpapi_ebay_product: {{
    product_id: 'EB-9',
    product_summary: {{
      title: 'Vintage Receiver',
      url: 'https://ebay.example/receiver',
      image_urls: ['https://images.example/receiver.jpg'],
      buy: {{buy_it_now: {{price: {{currency: 'USD', amount: 299}}}}}}
    }}
  }},
  serpapi_hotel_search: {{
    destination: 'Phoenix',
    check_in_date: '2099-08-11',
    check_out_date: '2099-08-13',
    top_results: [{{
      title: 'Desert Hotel',
      url: 'https://hotels.example/desert',
      thumbnail: 'https://images.example/desert.jpg',
      price_per_night: '$120',
      price_total: '$240',
      rating: 4.6,
      reviews: 800,
      amenities: ['Pool', 'Pet-friendly']
    }}]
  }},
  serpapi_yelp_search: {{
    find_desc: 'pizza',
    find_loc: 'Hillsboro, OR',
    sort_by: 'rating',
    results: [{{
      title: 'Society Pie',
      url: 'https://www.yelp.com/biz/society-pie',
      thumbnail: 'https://images.example/pizza.jpg',
      rating: 4.6,
      reviews: 113,
      price: '$$',
      neighborhoods: 'Hillsboro',
      open_state: 'Open until 8:00 PM',
      categories: ['Pizza', 'Salad']
    }}]
  }},
  flight_search: {{
    departure_id: 'PDX',
    arrival_id: 'PHX',
    outbound_date: '2099-09-15',
    return_date: '2099-09-20',
    currency: 'USD',
    booking_url: 'https://www.google.com/travel/flights',
    results: [{{
      price: 257,
      airlines: ['Alaska'],
      flight_numbers: ['AS 1349'],
      departure_airport: 'PDX',
      departure_time: '2099-09-15 07:03',
      arrival_airport: 'PHX',
      arrival_time: '2099-09-15 09:51',
      duration_display: '2h 48m',
      stops_label: 'Nonstop'
    }}]
  }},
  serpapi_maps_search: {{
    query: 'coffee',
    results: [{{
      title: 'Pup Cup Coffee',
      url: 'https://maps.example/pup',
      rating: 4.8,
      address: '123 Market St'
    }}]
  }}
}});

for (const expected of [
  'Precision Coffee Grinder', '$99', 'ASIN B000TEST01',
  'Cordless Drill', '$129', 'Product HD-7',
  'Vintage Receiver', 'USD 299', 'Item EB-9',
  'Desert Hotel', '$120/night', '$240 total', 'Pet-friendly',
  'Society Pie', 'Open until 8:00 PM', 'Pizza · Salad',
  'PDX → PHX', '$257', 'Alaska', 'AS 1349',
  'Departs 09/15/2099 · 7:03 AM', 'Open Google Flights',
  'Pup Cup Coffee', '123 Market St', 'Previous results', 'Next results'
]) {{
  if (!html.includes(expected)) {{
    console.error('Missing expected preview text:', expected, html);
    process.exit(3);
  }}
}}
if (html.includes('flight_numbers')) process.exit(4);
if ((html.match(/structured-results-preview/g) || []).length !== 7) process.exit(5);

if (!renderer.register('custom_demo', payload => ({{
  kind: 'generic',
  eyebrow: 'Custom',
  heading: payload.heading,
  items: [{{title: payload.title, primary: payload.value}}]
}}))) process.exit(6);
const customHtml = renderer.render({{
  custom_demo: {{heading: 'Extension works', title: 'New adapter', value: 'Ready'}}
}});
for (const expected of ['Custom', 'Extension works', 'New adapter', 'Ready']) {{
  if (!customHtml.includes(expected)) process.exit(7);
}}
"""

    subprocess.run(["node", "-e", script], cwd=PROJECT_ROOT, check=True)


def test_shared_renderer_escapes_content_and_rejects_unsafe_urls():
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(RENDERER_JS))}, 'utf8');
const escapeHtml = value => String(value)
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;');
const sandbox = {{
  URL,
  window: {{}},
  console,
  Utils: {{
    escapeHtml,
    safeHttpUrlForAttr: value => {{
      try {{
        const parsed = new URL(String(value));
        return ['http:', 'https:'].includes(parsed.protocol) ? escapeHtml(parsed.href) : '';
      }} catch (_error) {{
        return '';
      }}
    }}
  }}
}};
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
const html = sandbox.window.structuredResultsRenderer.render({{
  serpapi_maps_search: {{
    query: '<img src=x onerror=alert(1)>',
    results: [{{
      title: '<script>alert(1)</script>',
      url: 'javascript:alert(1)',
      thumbnail: 'data:text/html,unsafe',
      address: '<b>Unsafe</b>'
    }}]
  }}
}});
if (html.includes('<script>') || html.includes('<img src=x')) process.exit(2);
if (html.includes('javascript:') || html.includes('data:text/html')) process.exit(3);
if (!html.includes('&lt;script&gt;alert(1)&lt;/script&gt;')) process.exit(4);
if (!html.includes('&lt;b&gt;Unsafe&lt;/b&gt;')) process.exit(5);
"""

    subprocess.run(["node", "-e", script], cwd=PROJECT_ROOT, check=True)


def test_renderer_is_loaded_before_chat_and_uses_shared_responsive_styles():
    index = INDEX_HTML.read_text(encoding="utf-8")
    chat = CHAT_JS.read_text(encoding="utf-8")
    css = MAIN_CSS.read_text(encoding="utf-8")

    assert index.index('/js/structured-results.js') < index.index('/js/chat.js')
    assert "window.structuredResultsRenderer.render(toolResultsData, data)" in chat
    assert "${structuredResultsHtml}" in chat
    assert ".structured-results-track" in css
    assert "grid-auto-flow: column" in css
    assert "scroll-snap-type: inline proximity" in css
    assert "grid-auto-columns: minmax(235px, 82vw)" in css
    assert ".structured-results-scroll-button" in css
    assert "scrollbar-color:" in css
    assert "track.scrollBy({left: direction * distance, behavior: 'smooth'})" in RENDERER_JS.read_text(
        encoding="utf-8"
    )
