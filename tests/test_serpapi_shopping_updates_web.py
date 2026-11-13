"""Shopping evidence survives saved follow-ups and renders safely in existing cards."""
from __future__ import annotations

import importlib
import json
import re
import subprocess
from copy import deepcopy
from pathlib import Path

from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
JS_ROOT = ROOT / "jarvis-web/client/js"
load_server_package("shopping_updates_server", ROOT / "jarvis-web/server")
followup = importlib.import_module("shopping_updates_server.services.followup_extractor")


def amazon_payload():
    return {
        "engine": "amazon_product", "asin": "B000000001", "amazon_domain": "amazon.ae",
        "delivery_city": "Dubai", "delivery_localized": True, "delivery_location_source": "explicit_city",
        "results": [{"title": "Fixture coffee", "asin": "B000000001", "url": "https://www.amazon.ae/dp/B000000001",
                     "thumbnail": "https://images.example/coffee.jpg", "price": "$10", "prime": False,
                     "item_ingredients": ["COFFEE", "WATER"], "product_evidence_truncated": False,
                     "important_information": [{"title": "Safety Information", "text": "Contains caffeine."},
                                               {"title": "Directions", "text": "Keep chilled."}]}],
    }


def extract(name, value):
    result = followup.extract_followup_data({name: json.loads(json.dumps(value))})
    assert isinstance(result, dict)
    return result[name]


def render(data):
    paths = [str(JS_ROOT / name) for name in ("structured-results-shopping.js", "structured-results-search.js",
                                             "structured-results-local-travel.js", "structured-results.js")]
    script = r"""
const fs = require('fs');
const vm = require('vm');
const escapeHtml = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const sandbox = {URL, console, window: {}, Utils: {
  escapeHtml,
  safeHttpUrlForAttr: value => {
    try { const url = new URL(String(value)); return ['http:', 'https:'].includes(url.protocol) ? escapeHtml(url.href) : ''; }
    catch (_) { return ''; }
  },
}};
vm.createContext(sandbox);
vm.runInContext(PATHS.map(path => fs.readFileSync(path, 'utf8')).join('\n'), sandbox);
process.stdout.write(sandbox.window.structuredResultsRenderer.render(DATA));
""".replace("PATHS", json.dumps(paths)).replace("DATA", json.dumps(data))
    return subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True).stdout


def test_saved_amazon_followup_preserves_callable_location_and_structured_warnings_twice():
    source = amazon_payload()
    untouched = deepcopy(source)
    result = extract("serpapi_amazon_search", source)
    assert result["amazon_domain"] == "amazon.ae" and result["delivery_city"] == "Dubai"
    assert result["delivery_localized"] is True and result["delivery_location_source"] == "explicit_city"
    candidate = result["candidates"][0]
    assert candidate["item_ingredients"] == ["COFFEE", "WATER"]
    assert candidate["important_information"] == source["results"][0]["important_information"]
    assert candidate["prime"] is False and candidate["product_evidence_truncated"] is False
    restored = extract("serpapi_amazon_search", result)
    assert restored["candidates"][0] == candidate and restored["delivery_city"] == "Dubai"
    assert source == untouched


def test_oversized_followup_keeps_warning_labels_and_marks_new_omissions():
    source = amazon_payload()
    source["results"][0].update(item_ingredients=["ingredient " * 1000] * 30,
                                important_information=[{"title": "Safety Information", "text": "caution " * 1000}] * 30)
    result = extract("serpapi_amazon_search", source)
    candidate = result["candidates"][0]
    assert candidate["important_information"][0]["title"] == "Safety Information"
    assert len(candidate["important_information"][0]["text"]) >= 600
    assert candidate["product_evidence_truncated"] is True
    assert len(json.dumps(result)) < 7000


def test_saved_home_depot_sku_keeps_resolved_identity_availability_and_disclosure():
    source = {"engine": "home_depot_product", "product_id": "304163165", "requested_store_sku": "1002991354",
              "lookup_note": "A Store SKU can match several products; reuse the returned product_id.",
              "results": [{"title": "Fixture board", "product_id": "304163165", "store_sku_number": "1002991354",
                           "url": "https://www.homedepot.com/p/fixture/304163165", "price": 0,
                           "availability_type": "Discontinued"}]}
    result = extract("serpapi_home_depot", source)
    assert result["product_id"] == "304163165" and result["requested_store_sku"] == "1002991354"
    assert result["candidates"][0]["availability_type"] == "Discontinued"
    assert result["candidates"][0]["store_sku_number"] == "1002991354"
    assert result["candidates"][0]["price"] == 0 and result["lookup_note"] == source["lookup_note"]
    restored = extract("serpapi_home_depot", result)
    assert restored["candidates"][0] == result["candidates"][0]


def test_amazon_cards_show_escaped_bounded_ingredients_warnings_and_delivery_city():
    source = amazon_payload()
    product = source["results"][0]
    product["item_ingredients"] = ["COFFEE", "<img src=x onerror=alert(1)>"]
    product["important_information"] = [{"title": "Safety Information", "text": "Contains caffeine <script>unsafe()</script>"}]
    product["product_evidence_truncated"] = True
    html = render({"serpapi_amazon_search": json.loads(json.dumps(source))})
    for text in ("Ingredients: COFFEE", "Safety Information: Contains caffeine", "Delivery city: Dubai",
                 "Product information is partial", "&lt;script&gt;unsafe()&lt;/script&gt;", "&lt;img src=x onerror=alert(1)&gt;",
                 'href="https://www.amazon.ae/dp/B000000001"', 'src="https://images.example/coffee.jpg"'):
        assert text in html
    assert "<script>" not in html and "<img src=x" not in html
    legacy = deepcopy(source)
    for field in ("item_ingredients", "important_information", "product_evidence_truncated"):
        legacy["results"][0].pop(field)
    baseline = render({"serpapi_amazon_search": legacy})
    assert bool(re.search(r"<details[^>]*\sopen(?:\s|=|>)", html)) == bool(re.search(r"<details[^>]*\sopen(?:\s|=|>)", baseline))


def test_home_depot_cards_show_resolved_product_and_unavailable_status_without_hiding_price_zero():
    html = render({"serpapi_home_depot": {"engine": "home_depot_product", "requested_store_sku": "1002991354",
                   "lookup_note": "A Store SKU can match several products <script>inert()</script>",
                   "product_details": {"title": "Fixture board", "product_id": "304163165", "price": 0,
                                       "url": "https://www.homedepot.com/p/fixture/304163165", "availability_type": "Out of Stock"}}})
    assert "Product 304163165" in html and "Availability: Out of Stock" in html
    assert "A Store SKU can match several products &lt;script&gt;inert()&lt;/script&gt;" in html
    assert "<script>" not in html and 'class="structured-result-primary">0<' in html
    baseline = render({"serpapi_home_depot": {"product_details": {
        "title": "Fixture board", "product_id": "304163165", "price": 0,
        "url": "https://www.homedepot.com/p/fixture/304163165",
    }}})
    assert bool(re.search(r"<details[^>]*\sopen(?:\s|=|>)", html)) == bool(re.search(r"<details[^>]*\sopen(?:\s|=|>)", baseline))
