"""Property previews preserve native evidence without wide nested listing data."""

from __future__ import annotations

from copy import deepcopy

import pytest

from lib.apify_actors import normalize_property_page

ZILLOW = "X46xKaa20oUA1fRiP"
ZIP = "l7auNT3I30CssRrvO"
DETAIL = "ENK9p4RZHg0iVso52"
REDFIN = "fSNRlNbcFgtHBFBE9"
PROPERTY_URL = "https://www.zillow.com/homedetails/Example-Home/12345678_zpid/"
PHOTO_URL = "https://photos.zillowstatic.com/fp/example-p_e.jpg"


@pytest.fixture
def zillow_listing():
    # Curated fields verified against the current search/ZIP/detail schemas and
    # a real search dataset. Values are public-shaped fixtures, not user data.
    return {
        "zpid": "12345678",
        "listingAddress": {
            "street": "130 Example St", "city": "Albany", "state": "OR",
            "zipCode": "97321", "full": "130 Example St, Albany, OR 97321",
        },
        "listingPrice": {"amount": 425000, "currency": "USD", "formatted": "$425,000"},
        "listingStatus": "forSale", "homeType": "SINGLE_FAMILY",
        "bedrooms": 3, "bathrooms": 2.5, "livingArea": 1800, "livingAreaUnit": "sqft",
        "daysOnZillow": 0, "propertyUrl": PROPERTY_URL, "mainImage": PHOTO_URL,
        "scrapedAt": "2026-11-11T04:16:52.440Z", "isValid": True,
        "factsAndFeatures": {"wide": {"nested": ["not a preview column"] * 500}},
        "listingPhotos": [{"url": PHOTO_URL}] * 100,
    }


@pytest.mark.parametrize("actor", [ZILLOW, ZIP, DETAIL])
def test_curated_zillow_page_keeps_useful_scalar_evidence(actor, zillow_listing):
    original = deepcopy(zillow_listing)
    page = normalize_property_page(actor, [zillow_listing])
    assert page == {
        "kind": "property_listings", "source": "zillow", "input_count": 1,
        "unrecognized_count": 0, "items": [{
            "kind": "property_listing", "source": "zillow", "listing_id": "12345678",
            "address": "130 Example St, Albany, OR 97321", "city": "Albany",
            "state": "OR", "postal_code": "97321", "price": 425000,
            "price_text": "$425,000", "currency": "USD", "listing_status": "for_sale",
            "property_type": "single_family", "bedrooms": 3, "bathrooms": 2.5,
            "area": 1800, "area_unit": "sqft", "days_on_zillow": 0,
            "url": PROPERTY_URL, "image_url": PHOTO_URL,
            "scraped_at": "2026-11-11T04:16:52.440Z",
        }],
    }
    assert zillow_listing == original


def _row(actor, item):
    page = normalize_property_page(actor, [item])
    assert page is not None
    return page["items"][0]


@pytest.mark.parametrize("status,expected", [
    ("forSale", "for_sale"), ("forRent", "for_rent"), ("sold", "sold"),
    ("pending", "pending"), ("comingSoon", "coming_soon"),
    ("foreclosure", "foreclosure"), ("Unrecognized native status", "Unrecognized native status"),
    (None, None),
])
def test_native_status_is_never_assumed_to_match_a_sale_request(zillow_listing, status, expected):
    zillow_listing["listingStatus"] = status
    assert _row(ZILLOW, zillow_listing)["listing_status"] == expected


def test_missing_listing_price_and_age_remain_unknown(zillow_listing):
    for key in ("listingPrice", "daysOnZillow", "homeType"):
        zillow_listing.pop(key)
    row = _row(ZILLOW, zillow_listing)
    assert row["price"] is None
    assert row["days_on_zillow"] is None
    assert "price_text" not in row and "property_type" not in row
    assert row["listing_status"] == "for_sale"
    assert row["address"] == "130 Example St, Albany, OR 97321"


def test_detail_image_resolutions_use_safe_medium_and_numeric_identifier(zillow_listing):
    zillow_listing["zpid"] = 9007199254740993
    zillow_listing["mainImage"] = {
        "medium": "https://evil.example/image.jpg", "hiRes": PHOTO_URL,
        "thumbnail": "https://photos.zillowstatic.com/fp/thumb.jpg",
    }
    row = _row(DETAIL, zillow_listing)
    assert row["listing_id"] == "9007199254740993"
    assert row["image_url"] == PHOTO_URL


@pytest.mark.parametrize("value", [
    None, True, False, -1, "425000", {}, [], float("nan"), float("inf"), 10 ** 500,
])
def test_malformed_nonfinite_or_negative_numeric_evidence_is_not_coerced(zillow_listing, value):
    zillow_listing["listingPrice"]["amount"] = value
    for key in ("daysOnZillow", "bedrooms", "bathrooms", "livingArea"):
        zillow_listing[key] = value
    row = _row(ZILLOW, zillow_listing)
    assert row["price"] is None and row["days_on_zillow"] is None
    assert all(key not in row for key in ("bedrooms", "bathrooms", "area"))


@pytest.mark.parametrize("value", [
    "javascript:alert(1)", "data:text/html,hi", "http://www.zillow.com/123",
    "https://www.zillow.com.evil.example/123", "https://evil.example/www.zillow.com",
    "https://www.zillow.com@evil.example/123", "https://user@www.zillow.com/123",
    "https://www.zillow.com:5001/123", "https://www.zillow.com\\@evil.example/123",
    "https://www.zillow.com/with space", "https://www.zillow.com/with\nnewline",
    "https://www.zillow.com/" + "x" * 2048, "https://[broken/",
])
def test_listing_urls_require_safe_source_host(zillow_listing, value):
    zillow_listing["propertyUrl"] = value
    row = _row(ZILLOW, zillow_listing)
    assert "url" not in row
    assert row["price"] == 425000


def test_strings_are_bounded_and_no_wide_or_untrusted_fields_are_copied(zillow_listing):
    zillow_listing["listingAddress"]["full"] = "<img onerror=evil()>\n" + "x" * 5000
    zillow_listing["listingPrice"]["formatted"] = "x" * 5000
    zillow_listing["scrapedAt"] = {"not": "a timestamp"}
    zillow_listing["mainImage"] = "https://maps.googleapis.com/maps/api/staticmap?key=not-for-preview"
    row = _row(ZILLOW, zillow_listing)
    assert len(row["address"]) <= 300 and len(row["price_text"]) <= 100
    assert row["address"].startswith("<img onerror=evil()> ")
    assert all(not isinstance(value, (list, dict)) for value in row.values())
    assert not {"factsAndFeatures", "listingPhotos", "scraped_at", "image_url"} & row.keys()


def test_compose_missing_full_address_from_native_components(zillow_listing):
    zillow_listing["listingAddress"].pop("full")
    assert _row(ZILLOW, zillow_listing)["address"] == "130 Example St, Albany, OR 97321"


@pytest.mark.parametrize("items", [
    [{"title": "unrecognized native shape"}], [None], ["not an object"],
    [{"error": "property failed", "zpid": "123"}],
    [{"listingAddress": {"full": "Native failure"}, "error": "request failed"}],
    [{"listingAddress": {"full": "Invalid native property"}, "isValid": False}],
])
def test_unsupported_and_failed_records_are_explicitly_counted(items):
    assert normalize_property_page(ZILLOW, items) == {
        "kind": "property_listings", "source": "zillow", "items": [],
        "input_count": len(items), "unrecognized_count": len(items),
    }


def test_mixed_page_keeps_valid_listings_and_counts_unsupported_native_records(zillow_listing):
    items = [zillow_listing, {"error": "missing property"}, zillow_listing]
    original = deepcopy(items)
    result = normalize_property_page(ZILLOW, items)
    assert result is not None
    assert len(result["items"]) == 2
    assert result["input_count"] == 3 and result["unrecognized_count"] == 1
    assert items == original


def test_unknown_actor_never_uses_property_projection(zillow_listing):
    assert normalize_property_page("UnreviewedActor", [zillow_listing]) is None
    assert normalize_property_page("maxcopell/zillow-scraper", [zillow_listing]) is None


@pytest.mark.parametrize("actor,source", [(ZILLOW, "zillow"), (REDFIN, "redfin")])
def test_known_empty_page_preserves_property_presentation(actor, source):
    assert normalize_property_page(actor, []) == {
        "kind": "property_listings", "source": source, "items": [],
        "input_count": 0, "unrecognized_count": 0,
    }


def test_redfin_sale_uses_documented_values_not_numeric_status_or_property_enums():
    item = {
        "listingId": 180102965, "propertyId": 125891238,
        "streetLine": {"value": "172 Example Dr", "level": 1},
        "city": "Meridianville", "state": "AL", "zip": "35759",
        "price": {"value": 425000, "level": 1}, "sqFt": {"value": 2139, "level": 1},
        "beds": 5, "baths": 2.5, "dom": {"value": 2}, "searchStatus": 8,
        "propertyType": 6, "mlsStatus": "Coming Soon", "offerType": "sale",
        "url": "https://www.redfin.com/AL/Meridianville/Example/home/125891238",
    }
    row = _row(REDFIN, item)
    assert row["listing_id"] == "180102965"
    assert row["address"] == "172 Example Dr, Meridianville, AL 35759"
    assert row["price"] == 425000 and row["listing_status"] == "coming_soon"
    assert row["area"] == 2139 and row["area_unit"] == "sqft"
    assert row["bedrooms"] == 5 and row["bathrooms"] == 2.5
    assert row["days_on_zillow"] is None
    assert "property_type" not in row and "currency" not in row


def test_redfin_rental_ranges_do_not_invent_exact_price_or_room_counts():
    item = {
        "propertyId": "186342666", "rentalId": "native-rental-id", "offerType": "rent",
        "addressInfo": {"formattedStreetLine": "16620 Example Ave", "city": "Jamaica",
                        "state": "NY", "zip": "11432"},
        "rentPriceRange": {"min": 2850, "max": 3995}, "bedRange": {"min": 0, "max": 2},
        "bathRange": {"min": 1, "max": 2}, "status": 1,
        "url": "https://www.redfin.com/NY/Jamaica/Example/apartment/186342666",
    }
    row = _row(REDFIN, item)
    assert row["listing_id"] == "native-rental-id"
    assert row["price"] is None and row["price_text"] == "2,850–3,995"
    assert row["listing_status"] == "for_rent" and row["days_on_zillow"] is None
    assert "bedrooms" not in row and "bathrooms" not in row
    item["rentPriceRange"]["max"] = 2850
    assert _row(REDFIN, item)["price"] == 2850


def test_malformed_redfin_offer_type_is_unknown_not_an_exception():
    row = _row(REDFIN, {"streetLine": {"value": "Known address"}, "offerType": {"bad": "value"}})
    assert row["price"] is None and row["listing_status"] is None


def test_page_keeps_order_cardinality_and_duplicates_as_native_evidence(zillow_listing):
    second = {**zillow_listing, "zpid": "AnotherListing"}
    page = normalize_property_page(ZILLOW, [zillow_listing, second, zillow_listing])
    assert page is not None
    assert [row["listing_id"] for row in page["items"]] == [
        "12345678", "AnotherListing", "12345678",
    ]
