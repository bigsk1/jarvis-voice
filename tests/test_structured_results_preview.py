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
  'serpapi_amazon_search',
  'serpapi_search',
  'serpapi_home_depot',
  'serpapi_ebay_search',
  'serpapi_ebay_product',
  'serpapi_hotel_search',
  'serpapi_yelp_search',
  'serpapi_search_index',
  'serpapi_google_news_light',
  'serpapi_google_trends',
  'serpapi_google_trending_now',
  'serpapi_tripadvisor',
  'flight_search',
  'serpapi_google_local',
  'serpapi_maps_search',
  'serpapi_youtube_search',
  'weather'
];
if (JSON.stringify(renderer.registeredTools()) !== JSON.stringify(expectedTools)) process.exit(2);

const html = renderer.render({{
  serpapi_amazon_search: {{
    engine: 'amazon',
    query: 'coffee grinder',
    results: [{{
      title: 'Precision Coffee Grinder',
      url: 'https://amazon.example/grinder',
      thumbnail: 'https://images.example/grinder.jpg',
      price: '$99',
      rating: 4.7,
      reviews: 1200,
      asin: 'B000TEST01'
    }}, {{
      title: 'Compact Coffee Grinder',
      url: 'https://amazon.example/compact-grinder',
      thumbnail: 'https://images.example/compact-grinder.jpg',
      price: '$49',
      asin: 'B000TEST02'
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
    }}, {{
      title: 'Compact Drill',
      url: 'https://homedepot.example/compact-drill',
      thumbnail: 'https://images.example/compact-drill.jpg',
      price_formatted: '$89',
      product_id: 'HD-8'
    }}]
  }},
  serpapi_ebay_search: {{
    query: 'vintage receiver',
    results: [{{
      title: 'Classic Stereo Receiver',
      url: 'https://ebay.example/classic-receiver',
      thumbnail: 'https://images.example/classic-receiver.jpg',
      price: {{from: {{raw: '$180'}}, to: {{raw: '$220'}}}},
      condition: 'Used',
      shipping: {{raw: 'Free shipping'}},
      seller: {{username: 'seller-one', reviews: 42}}
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
  serpapi_search_index: {{
    query: 'PostgreSQL queue patterns',
    mode: 'deep',
    results_count: 1,
    total_results: 314,
    related_searches: ['SKIP LOCKED queue', 'durable job queue'],
    results: [{{
      title: 'PostgreSQL as a durable queue',
      url: 'https://example.test/postgres-queue',
      displayed_link: 'example.test/postgres-queue',
      snippet: 'A practical guide to durable workers backed by PostgreSQL.',
      date: 'Aug 1, 2026',
      language: 'en',
      image_url: 'https://images.example/postgres.jpg',
      sitelinks: [{{title: 'Queue schema', url: 'https://example.test/schema'}}]
    }}]
  }},
  serpapi_google_news_light: {{
    query: 'agentic AI',
    query_displayed: 'agentic AI news',
    country: 'us',
    provider_results_count: 2,
    provider_top_story_articles_count: 1,
    google_news_light_url: 'https://www.google.com/search?q=agentic+AI&tbm=nws',
    top_stories: [{{
      title: 'AI funding',
      stories: [{{
        title: 'Investors return to AI agents',
        url: 'https://finance.example/ai-agents',
        source: 'Finance Example',
        date: '1 hour ago'
      }}]
    }}],
    results: [{{
      title: 'Agentic AI attracts new funding',
      url: 'https://news.example/agentic-funding',
      source: 'Example News',
      thumbnail: 'https://images.example/funding.jpg',
      snippet: 'Several agent startups announced new funding rounds.',
      date: '2 hours ago'
    }}]
  }},
  serpapi_google_trends: {{
    query: 'AI agents, AI assistants',
    data_type: 'interest_over_time',
    date: 'now 7-d',
    geo: 'US',
    trends_url: 'https://trends.google.com/trends/explore?q=AI+agents,AI+assistants',
    results: [{{
      title: 'AI agents',
      query: 'AI agents',
      latest_date: 'Aug 5, 2026',
      latest_value: 83,
      direction: 'rising',
      average_value: 61,
      peak_value: 83,
      change_from_previous: 9,
      change_over_period: 28
    }}]
  }},
  serpapi_google_trending_now: {{
    action: 'trending_now',
    geo: 'US',
    hours: 24,
    provider_results_count: 50,
    active_results_count: 42,
    trending_now_url: 'https://trends.google.com/trending?geo=US',
    results: [{{
      title: 'agentic ai',
      query: 'agentic ai',
      active: true,
      search_volume: 200000,
      increase_percentage: 1000,
      category_names: ['Technology', 'Business and Finance'],
      trend_breakdown: ['ai agents', 'agent frameworks'],
      google_trends_url: 'https://trends.google.com/trends/explore?q=agentic+ai'
    }}]
  }},
  serpapi_tripadvisor: {{
    action: 'search',
    query: 'Rome',
    category: 'things_to_do',
    results: [{{
      title: 'Colosseum',
      url: 'https://www.tripadvisor.com/Attraction_Review-d192285.html',
      thumbnail: 'https://images.example/colosseum.jpg',
      place_id: '192285',
      place_type: 'ATTRACTION',
      rating: 4.7,
      reviews: 155000,
      location: 'Rome, Italy',
      description: 'Ancient amphitheatre in the center of Rome.'
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
  serpapi_google_local: {{
    query: 'coffee',
    location: 'Portland, Oregon',
    provider_location_used: 'Portland,Oregon,United States',
    provider_results_count: 10,
    google_local_url: 'https://www.google.com/search?q=coffee&tbm=lcl',
    results: [{{
      title: 'North Star Coffee',
      url: 'https://northstar.example/',
      website: 'https://northstar.example/',
      thumbnail: 'https://images.example/northstar.jpg',
      rating: 4.8,
      reviews: 321,
      price: '$$',
      type: 'Coffee shop',
      address: '123 Market St',
      hours: 'Open until 8 PM',
      description: 'Independent neighborhood coffee shop',
      service_options: {{dine_in: true, takeout: true}}
    }}],
    ads: [{{
      title: 'Sponsored Coffee',
      url: 'https://sponsor.example/',
      rating: 4.1,
      sponsored: true
    }}],
    discover_more_places: [{{
      title: 'Best coffee',
      url: 'https://www.google.com/search?q=best+coffee&tbm=lcl',
      places: ['North Star Coffee', 'River Coffee']
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
  }},
  serpapi_youtube_search: {{
    search_query: 'woodworking basics',
    results: [{{
      video_id: 'abc123def45',
      title: 'Woodworking for Beginners',
      url: 'https://www.youtube.com/watch?v=abc123def45',
      thumbnail: 'https://images.example/woodworking.jpg',
      channel: 'Workshop School',
      duration: '12:34',
      views: 1200000,
      published_date: '2 years ago',
      description: 'A practical introduction to safe woodworking and essential tools.'
    }}]
  }},
  weather: {{
    location: 'Hillsboro, Oregon',
    temperature: 72,
    feels_like: 71,
    condition: 'partly cloudy',
    daily_forecast: [{{
      day: 'Mon',
      date: '2099-08-03',
      high: 78,
      low: 58,
      condition: 'partly cloudy',
      precip_probability: 20,
      wind_max: 12
    }}]
  }}
}});

for (const expected of [
  'Precision Coffee Grinder', '$99', 'ASIN B000TEST01', 'Compact Coffee Grinder',
  'Cordless Drill', '$129', 'Product HD-7', 'Compact Drill',
  'Classic Stereo Receiver', '$180 – $220', 'Free shipping', 'seller-one',
  'Vintage Receiver', 'USD 299', 'Item EB-9',
  'Desert Hotel', '$120/night', '$240 total', 'Pet-friendly',
  'Society Pie', 'Open until 8:00 PM', 'Pizza · Salad',
  'Search Index · Deep recall', 'PostgreSQL queue patterns',
  'PostgreSQL as a durable queue', 'example.test/postgres-queue',
  'A practical guide to durable workers', 'Aug 1, 2026', '1 related links',
  '314 indexed matches', 'Related: SKIP LOCKED queue · durable job queue',
  'Google News Light', 'agentic AI news', '2 news results',
  '1 top-story article', 'US', 'Investors return to AI agents',
  'Finance Example', 'Top story', 'AI funding',
  'Agentic AI attracts new funding', 'Example News',
  'Several agent startups announced new funding rounds', 'Open Google News',
  'Google Trends', 'AI agents, AI assistants', 'Latest 83', 'Average 61',
  'Peak 83', '+9 from previous', '+28 over period', 'Open Google Trends',
  'Google Trends · Trending Now', 'Current trends in US', 'Past 24 hours',
  '42 active · 50 total', 'agentic ai', '200,000 searches', 'Active now',
  '+1000%', 'Technology · Business and Finance',
  'Related: ai agents · agent frameworks', 'Open Trending Now',
  'Colosseum', '155000 reviews', 'Rome, Italy', 'Ancient amphitheatre',
  'PDX → PHX', '$257', 'Alaska', 'AS 1349',
  'Departs 09/15/2099 · 7:03 AM', 'Open Google Flights',
  'Google Local', 'Portland,Oregon,United States', '10 local results',
  'North Star Coffee', '321 reviews', 'Dine In', 'Takeout',
  'Open website', 'Sponsored Coffee', 'Sponsored',
  'Best coffee', 'Related search', 'Explore nearby', 'Open Google Local',
  'Pup Cup Coffee', '123 Market St',
  'Woodworking for Beginners', 'Workshop School', '12:34', '1,200,000 views',
  'Hillsboro, Oregon', 'Currently 72°', 'Mon · 2099-08-03', '78° / 58°',
  'Previous results', 'Next results', 'structured-results-layout-metrics'
]) {{
  if (!html.includes(expected)) {{
    console.error('Missing expected preview text:', expected, html);
    process.exit(3);
  }}
}}
if (html.includes('flight_numbers')) process.exit(4);
if ((html.match(/structured-results-preview/g) || []).length !== 16) process.exit(5);

if (!renderer.register('custom_demo', payload => ({{
  kind: 'generic',
  layout: 'list',
  eyebrow: 'Custom',
  heading: payload.heading,
  items: [{{title: payload.title, primary: payload.value}}]
}}))) process.exit(6);
const customHtml = renderer.render({{
  custom_demo: {{heading: 'Extension works', title: 'New adapter', value: 'Ready'}}
}});
for (const expected of ['Custom', 'Extension works', 'New adapter', 'Ready', 'structured-results-layout-list']) {{
  if (!customHtml.includes(expected)) process.exit(7);
}}
if (customHtml.includes('structured-results-scroll-button')) process.exit(8);
"""

    subprocess.run(["node", "-e", script], cwd=PROJECT_ROOT, check=True)


def test_google_trends_renderer_formats_regional_and_related_views():
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(RENDERER_JS))}, 'utf8');
const escapeHtml = value => String(value)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const sandbox = {{
  URL, window: {{}}, console,
  Utils: {{
    escapeHtml,
    safeHttpUrlForAttr: value => {{
      try {{
        const parsed = new URL(String(value));
        return ['http:', 'https:'].includes(parsed.protocol) ? escapeHtml(parsed.href) : '';
      }} catch (_error) {{ return ''; }}
    }}
  }}
}};
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
const renderer = sandbox.window.structuredResultsRenderer;

const regionHtml = renderer.render({{
  serpapi_google_trends: {{
    query: 'coffee, tea', data_type: 'compared_by_region', date: 'today 3-m', geo: 'US',
    results: [{{
      title: 'Oregon', location: 'Oregon', geo: 'US-OR',
      top_query: 'coffee', top_value: 70,
      values: [
        {{query: 'coffee', extracted_value: 70}},
        {{query: 'tea', extracted_value: 30}}
      ]
    }}]
  }}
}});
for (const expected of [
  'compared by region', 'Oregon', 'US-OR', 'coffee · 70', 'coffee 70 · tea 30'
]) if (!regionHtml.includes(expected)) process.exit(2);

const relatedHtml = renderer.render({{
  serpapi_google_trends: {{
    query: 'AI agents', data_type: 'related_topics', date: 'now 7-d', geo: 'US',
    results: [{{
      title: 'Agentic AI', topic_id: '/m/agentic', topic_type: 'Technology',
      trend_type: 'rising', value: '+1,200%',
      url: 'https://trends.google.com/trends/explore?q=agentic+AI'
    }}]
  }}
}});
for (const expected of [
  'related topics', 'Agentic AI', '+1,200%', 'rising', 'Technology',
  '/m/agentic', 'Open trend'
]) if (!relatedHtml.includes(expected)) process.exit(3);

const newsHtml = renderer.render({{
  serpapi_google_trending_now: {{
    action: 'news', trend_query: 'agentic ai', provider_results_count: 2,
    results: [{{
      title: 'Agentic AI moves into enterprise software',
      url: 'https://news.example/agentic-enterprise',
      source: 'Example News', date: '2 hours ago',
      thumbnail: 'https://images.example/agentic.jpg'
    }}]
  }}
}});
for (const expected of [
  'Google Trends News', 'agentic ai', '2 articles found',
  'Agentic AI moves into enterprise software', 'Example News',
  '2 hours ago', 'Read article'
]) if (!newsHtml.includes(expected)) process.exit(4);
"""

    subprocess.run(["node", "-e", script], cwd=PROJECT_ROOT, check=True)


def test_tripadvisor_renderer_formats_details_nearby_places_and_reviews():
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
const renderer = sandbox.window.structuredResultsRenderer;
const detailsHtml = renderer.render({{
  serpapi_tripadvisor: {{
    action: 'details',
    place: {{
      title: 'Rome, Italy',
      url: 'https://www.tripadvisor.com/Tourism-g187791-Rome.html',
      rating: 4.8,
      reviews: 245000,
      address: 'Lazio, Italy',
      categories: ['Destination'],
      description: 'Ancient sites and lively neighborhoods.'
    }},
    interesting_places: [{{
      title: 'Roman Table',
      url: 'https://www.tripadvisor.com/Restaurant_Review-d7.html',
      rating: 4.6,
      distance: '0.2 mi',
      group: 'restaurants',
      categories: ['Italian', 'Roman']
    }}]
  }}
}});
for (const expected of [
  'Tripadvisor details', 'Rome, Italy', '245000 reviews',
  'Roman Table', '0.2 mi', 'Italian · Roman', '1 nearby suggestions shown'
]) {{
  if (!detailsHtml.includes(expected)) process.exit(2);
}}

const reviewsHtml = renderer.render({{
  serpapi_tripadvisor: {{
    action: 'reviews',
    place_id: '187791',
    total_reviews: 47,
    reviews: [{{
      title: 'Wonderful history and food',
      url: 'https://www.tripadvisor.com/ShowUserReviews-r1.html',
      rating: 5,
      date: '2026-07-20',
      author_name: 'Traveler Seven',
      trip_type: 'FAMILY',
      text: 'We loved walking the old streets and finding neighborhood restaurants.'
    }}]
  }}
}});
for (const expected of [
  'Tripadvisor reviews', 'Place 187791', '47 total reviews',
  'Wonderful history and food', 'Traveler Seven', 'family',
  'We loved walking the old streets'
]) {{
  if (!reviewsHtml.includes(expected)) process.exit(3);
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


def test_youtube_search_keeps_one_large_player_and_uses_cards_for_the_full_shortlist():
    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(CHAT_JS))}, 'utf8');
const start = source.indexOf('  _extractYouTubeVideoId(');
const end = source.indexOf('  _shouldPreferRawForDisplay(', start);
const classSource = `class YouTubeHarness {{\n${{source.slice(start, end)}}\n}}; YouTubeHarness;`;
const sandbox = {{
  URL,
  window: {{location: {{origin: 'https://web.test'}}}}
}};
vm.createContext(sandbox);
const YouTubeHarness = vm.runInContext(classSource, sandbox);
const harness = new YouTubeHarness();
const results = [
  {{video_id: 'abc123def45', title: 'First video', url: 'https://www.youtube.com/watch?v=abc123def45'}},
  {{video_id: 'def456ghi78', title: 'Second video', url: 'https://www.youtube.com/watch?v=def456ghi78'}},
  {{video_id: 'ghi789jkl01', title: 'Third video', url: 'https://www.youtube.com/watch?v=ghi789jkl01'}}
];
const displayText = results.map(item => item.url).join(' ');
const searchEmbeds = harness._collectYouTubeEmbeds(displayText, '', {{
  serpapi_youtube_search: {{
    top_url: results[0].url,
    results,
    top_results: results
  }}
}});
if (searchEmbeds.length !== 1) process.exit(2);
if (searchEmbeds[0].videoId !== 'abc123def45') process.exit(3);
if (searchEmbeds[0].title !== 'First video') process.exit(4);

const detailEmbeds = harness._collectYouTubeEmbeds('', '', {{
  serpapi_youtube: {{
    title: 'Selected video',
    video_id: 'selected123',
    url: 'https://www.youtube.com/watch?v=selected123'
  }}
}});
if (detailEmbeds.length !== 1) process.exit(5);
if (detailEmbeds[0].videoId !== 'selected123') process.exit(6);
if (detailEmbeds[0].title !== 'Selected video') process.exit(7);
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
    assert ".structured-results-layout-list .structured-results-track" in css
    assert ".structured-results-layout-metrics .structured-results-track" in css
    assert ".structured-result-card-video" in css
    assert ".structured-results-scroll-button" in css
    assert "scrollbar-color:" in css
    assert "track.scrollBy({left: direction * distance, behavior: 'smooth'})" in RENDERER_JS.read_text(
        encoding="utf-8"
    )
