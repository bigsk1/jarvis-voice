"""Native property snapshots export as usable PDFs, never JSON code dumps."""

from __future__ import annotations

import json
from copy import deepcopy

import fitz
import pytest
from server_package_utils import load_canvas_server_package

load_canvas_server_package("canvas_property_pdf_test_server")

from canvas_property_pdf_test_server.services import pdf_export  # noqa: E402


@pytest.fixture
def snapshot():
    return {
        "version": 1, "source": "zillow", "snapshot_at": "2026-11-11T04:16:52Z",
        "criteria_text": "Albany, OR homes for sale, $300,000–$600,000",
        "coverage": {"returned_count": 3, "total_items": 17, "offset": 0, "complete": False},
        "duplicates_removed": 0,
        "items": [{
            "kind": "property_listing", "source": "zillow", "listing_id": f"private-zpid-{i}",
            "address": f"{100 + i} Example Street, Albany, OR 97321", "city": "Albany",
            "state": "OR", "postal_code": "97321", "price": 425000 + i * 10000,
            "price_text": f"${425000 + i * 10000:,}", "currency": "USD",
            "listing_status": "for_sale", "property_type": "single_family",
            "bedrooms": 3, "bathrooms": 2.5, "area": 1800, "area_unit": "sqft",
            "days_on_zillow": i,
            "url": f"https://www.zillow.com/homedetails/Example-{i}/public-{i}_zpid/",
            "image_url": "https://photos.zillowstatic.com/fp/no-fetch.jpg",
        } for i in range(3)],
    }


def page(data):
    encoded = json.dumps(data, ensure_ascii=False)
    return {"title": "Weekly property snapshot", "content": "Introductory analysis.\n\n"
            + "```property-listings\n" + encoded + "\n```\n\nClosing notes."}


def projection(data):
    return pdf_export.build_canvas_pdf_projection(page(data))


def test_native_snapshot_projection_contains_every_property_and_truthful_coverage(snapshot):
    original = deepcopy(snapshot)
    result = projection(snapshot)
    content = result["content_markdown"]
    assert "Property listings" in content and "Introductory analysis." in content
    assert "Closing notes." in content and "Albany, OR homes for sale" in content
    assert "3 properties from 3 fetched records; dataset total: 17" in content
    assert "Partial dataset coverage" in content and "Duplicates removed: 0" in content
    assert "Snapshot: 2026-11-11T04:16:52Z" in content
    for i, row in enumerate(snapshot["items"]):
        assert row["address"] in content and row["url"] in content
        assert f"days on Zillow: {i}" in content
        assert row["listing_id"] not in content
    assert "Beds: 3; baths: 2.5; area: 1,800 sqft" in content
    assert "```" not in content and '"items"' not in content and '"listing_id"' not in content
    assert result["public_media"] == []
    assert snapshot == original


def test_unknown_fields_and_contact_price_are_explicit(snapshot):
    row = snapshot["items"][0]
    for key in ("price", "bedrooms", "bathrooms", "area", "days_on_zillow", "listing_status"):
        row[key] = None
    row.pop("area_unit")
    row["price_text"] = "Contact Landlord"
    row.pop("url")
    snapshot["snapshot_at"] = None
    result = projection(snapshot)["content_markdown"]
    assert "Snapshot: unknown" in result
    assert "Contact Landlord (amount unknown)" in result
    assert "Status: unknown" in result and "Beds: unknown; baths: unknown" in result
    assert "area: unknown; days on Zillow: unknown" in result
    assert "Listing link: unavailable" in result


def test_complete_coverage_empty_page_and_duplicate_counts(snapshot):
    snapshot["items"] = snapshot["items"][:2]
    snapshot["duplicates_removed"] = 1
    snapshot["coverage"] = {"returned_count": 3, "total_items": 3, "offset": 0, "complete": True}
    result = projection(snapshot)["content_markdown"]
    assert "2 properties from 3 fetched records" in result
    assert "Complete dataset coverage" in result and "Duplicates removed: 1" in result
    snapshot["items"] = []
    snapshot["duplicates_removed"] = 0
    snapshot["coverage"].update(returned_count=0, total_items=0)
    assert "0 properties from 0 fetched records" in projection(snapshot)["content_markdown"]


def test_native_mixed_record_coverage_and_nullable_aggregate_offset_are_readable(snapshot):
    snapshot["coverage"].update(fetched_count=5, unrecognized_count=2, total_items=5,
                                offset=None, complete=True)
    result = projection(snapshot)
    content = result["content_markdown"]
    assert "3 properties from 3 recognized records; 5 fetched records" in content
    assert "Complete dataset coverage" in content and "combined pages or unknown position" in content
    assert "2 unsupported or error records were excluded" in content
    assert "property_rows_excluded" in {finding["code"] for finding in result["findings"]}
    assert "could not be included" not in content


def test_partial_source_offset_and_all_unsupported_page_are_not_reported_as_empty_success(snapshot):
    snapshot["coverage"].update(fetched_count=5, unrecognized_count=2, offset=20)
    content = projection(snapshot)["content_markdown"]
    assert "offset: 20" in content and "Partial dataset coverage" in content
    snapshot["items"] = []
    snapshot["coverage"].update(returned_count=0, fetched_count=2, unrecognized_count=2,
                                total_items=2, offset=0, complete=True)
    result = projection(snapshot)
    assert "0 properties from 0 recognized records; 2 fetched records" in result["content_markdown"]
    assert "2 unsupported or error records were excluded" in result["content_markdown"]
    assert "property_snapshot_omitted" not in {finding["code"] for finding in result["findings"]}


@pytest.mark.parametrize("attribution,credited", [(None, False), ({"provider": "other"}, False),
                                                 ({"provider": "openstreetmap"}, True)])
def test_geocoder_attribution_is_only_exported_with_explicit_evidence(snapshot, attribution, credited):
    if attribution is not None:
        snapshot["geography_attribution"] = attribution
    content = projection(snapshot)["content_markdown"]
    assert ("OpenStreetMap contributors" in content) is credited
    assert ("https://www.openstreetmap.org/copyright" in content) is credited


def test_actual_pdf_preserves_mixed_record_warning_and_proven_geography_credit(snapshot, monkeypatch):
    snapshot["coverage"].update(fetched_count=5, unrecognized_count=2, total_items=5,
                                offset=None, complete=True)
    snapshot["geography_attribution"] = {"provider": "openstreetmap"}

    def no_fetch(*_args, **_kwargs):
        pytest.fail("Property PDF must not fetch any external media")

    monkeypatch.setattr(pdf_export, "_fetch_public_image_asset", no_fetch)
    result, payload = pdf_export.prepare_canvas_pdf(page(snapshot), theme="light")
    text = pdf_export.validate_canvas_pdf(payload)["text"]
    assert all(row["address"] in text for row in snapshot["items"])
    assert "2 unsupported or error records were excluded" in text
    assert "OpenStreetMap contributors" in text
    assert '"fetched_count"' not in text and "private-zpid" not in text
    assert result["public_media"] == []


@pytest.mark.parametrize("patch", [
    {"fetched_count": 5}, {"unrecognized_count": 2},
    {"fetched_count": 5, "unrecognized_count": 1},
    {"fetched_count": True, "unrecognized_count": 0},
    {"fetched_count": 3, "unrecognized_count": -1},
    {"fetched_count": 3, "unrecognized_count": 0, "offset": -1},
])
def test_inconsistent_explicit_record_counts_produce_notice_instead_of_false_coverage(snapshot, patch):
    snapshot["coverage"].update(patch)
    result = projection(snapshot)
    assert "could not be included" in result["content_markdown"]
    assert "property_snapshot_omitted" in {finding["code"] for finding in result["findings"]}


@pytest.mark.parametrize("url", [
    "https://www.zillow.com/homedetails/Example-(West)-Home/123_zpid/?view=full&source=report",
    "https://www.zillow.com/homedetails/Example-West)-Home/123_zpid/?view=full&source=report",
])
def test_full_property_url_survives_markdown_and_actual_pdf(snapshot, monkeypatch, url):
    snapshot["items"][0]["url"] = url

    def no_fetch(*_args, **_kwargs):
        pytest.fail("A text-only property PDF must not fetch any external media")

    monkeypatch.setattr(pdf_export, "_fetch_public_image_asset", no_fetch)
    result, payload = pdf_export.prepare_canvas_pdf(page(snapshot), theme="light")
    inspection = pdf_export.validate_canvas_pdf(payload)
    assert payload.startswith(b"%PDF-") and inspection["pages"] >= 1
    assert all(row["address"] in inspection["text"] for row in snapshot["items"])
    assert "425,000" in inspection["text"] and "Beds: 3" in inspection["text"]
    assert "private-zpid" not in inspection["text"] and '"listing_id"' not in inspection["text"]
    assert "property-listings" not in inspection["text"] and '"version"' not in inspection["text"]
    assert result["public_media"] == []
    with fitz.open(stream=payload, filetype="pdf") as document:
        links = [link.get("uri") for pdf_page in document for link in pdf_page.get_links()]
    assert url in links


def test_all_rows_beyond_web_preview_are_in_pdf_projection(snapshot):
    base = snapshot["items"][0]
    snapshot["items"] = [{**base, "address": f"Property address number {i}"} for i in range(201)]
    snapshot["coverage"].update(returned_count=201, total_items=201, complete=True)
    content = projection(snapshot)["content_markdown"]
    assert content.count("### ") == 201
    assert "Property address number 200" in content


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "http://www.zillow.com/homedetails/unsafe",
    "https://127.0.0.1/private", "https://localhost/private", "https://evil.example/phishing",
    "https://www.zillow.com@evil.example/phishing", "https://user:secret@www.zillow.com/private",
    "https://www.zillow.com:5001/private", "https://www.zillow.com\\@evil.example/private",
    "https://www.zillow.com/homedetails/with space", "https://[broken/private",
    "https://www.zillow.com/" + "x" * 2048,
])
def test_unsafe_or_other_source_links_are_omitted_without_echoing_them(snapshot, url):
    snapshot["items"][0]["url"] = url
    result = projection(snapshot)
    assert url not in result["content_markdown"]
    assert "Listing link: unavailable" in result["content_markdown"]
    assert "property_listing_link_omitted" in {finding["code"] for finding in result["findings"]}


def test_unsafe_untrusted_text_is_escaped_then_existing_pdf_safety_still_applies(snapshot):
    snapshot["items"][0]["address"] = '<img src=x onerror=alert(1)> **bold** | ![fake](https://evil.example/img.jpg)'
    snapshot["criteria_text"] = "See https://127.0.0.1/internal or /home/boss/private.json"
    result = projection(snapshot)
    html = pdf_export._markdown_to_html(result["content_markdown"])
    assert "<img" not in html and "<strong>bold</strong>" not in html
    assert result["public_media"] == []
    assert "127.0.0.1" not in result["content_markdown"] and "/home/boss" not in result["content_markdown"]
    assert {"local_link_omitted", "local_path_omitted"} <= {
        finding["code"] for finding in result["findings"]}


@pytest.mark.parametrize("patch", [
    {"version": True}, {"version": 2}, {"source": "unknown"}, {"source": []},
    {"items": [None]}, {"items": [{"kind": "other"}]}, {"items": [None] * 2001},
    {"criteria_text": "x" * 2001}, {"snapshot_at": "not ISO"},
    {"snapshot_at": "2026-11-11T04:16:52"}, {"duplicates_removed": -1},
    {"coverage": {}}, {"coverage": {"returned_count": 3, "total_items": None,
                                     "offset": 0, "complete": True}},
])
def test_malformed_schema_has_readable_notice_not_raw_json(snapshot, patch):
    snapshot.update(patch)
    result = projection(snapshot)
    assert "Property listings could not be included" in result["content_markdown"]
    assert '"version"' not in result["content_markdown"] and '"items"' not in result["content_markdown"]
    assert "property_snapshot_omitted" in {finding["code"] for finding in result["findings"]}


@pytest.mark.parametrize("raw", ["{not JSON}", "null", "[]", '{"number":NaN}',
                                 '{"number":Infinity}', '{"number":1e999}',
                                 "[" * 1200 + "]" * 1200, "x" * (4 * 1024 * 1024 + 1)])
def test_invalid_nonfinite_nested_or_oversized_json_is_never_printed(raw):
    result = pdf_export.build_canvas_pdf_projection({
        "content": "```property-listings\n" + raw + "\n```"})
    assert "Property listings could not be included" in result["content_markdown"]
    assert raw not in result["content_markdown"]
    assert "property_snapshot_omitted" in {finding["code"] for finding in result["findings"]}


def test_fence_like_text_inside_another_code_block_is_not_parsed_as_a_report(snapshot):
    nested = "````text\n" + page(snapshot)["content"] + "\n````"
    result = pdf_export.build_canvas_pdf_projection({"content": nested})
    assert "### 1." not in result["content_markdown"]
    assert "Property listings could not be included" not in result["content_markdown"]
    assert '"items"' in result["content_markdown"]


def test_multiple_genuine_fences_expand_without_reordering_neighboring_content(snapshot):
    encoded = json.dumps(snapshot)
    content = f"Before\n\n```property-listings\n{encoded}\n```\n\nBetween\n\n"
    content += f"~~~property-listings\n{encoded}\n~~~\n\nAfter"
    result = pdf_export.build_canvas_pdf_projection({"content": content})["content_markdown"]
    assert result.count("## Property listings") == 2
    assert result.index("Before") < result.index("## Property listings") < result.index("Between")
    assert result.rindex("## Property listings") < result.index("After")


def test_redfin_and_mixed_sources_use_only_their_property_links(snapshot):
    snapshot["source"] = "mixed"
    snapshot["items"][0].update(source="redfin", url="https://www.redfin.com/OR/Albany/Example/home/123")
    content = projection(snapshot)["content_markdown"]
    assert "Source: Mixed" in content
    assert "[View Redfin listing](https://www.redfin.com/OR/Albany/Example/home/123)" in content
    assert "[View Zillow listing]" in content
