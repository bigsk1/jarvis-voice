"""Verified sale and rental listing output from tri_angle/redfin-search."""

from collections.abc import Mapping

from .properties import _address, _compact, _identifier, _mapping, _number, _text, _url

ACTORS = frozenset({"fSNRlNbcFgtHBFBE9"})
_PROPERTY_HOSTS = {"redfin": frozenset({"redfin.com", "www.redfin.com"})}
_REDFIN_STATUSES = {
    "for sale": "for_sale", "for rent": "for_rent", "sold": "sold",
    "pending": "pending", "coming soon": "coming_soon",
}

def normalize(item: Mapping[str, object]) -> dict[str, object] | None:
    address = _mapping(item.get("addressInfo"))
    street = _mapping(item.get("streetLine")).get("value")
    if not address and not street:
        return None
    city = address.get("city") if address else item.get("city")
    state = address.get("state") if address else item.get("state")
    postal = address.get("zip") if address else item.get("zip")
    status = _text(item.get("mlsStatus"), 64)
    if status:
        status = _REDFIN_STATUSES.get(status.lower(), status)
    else:
        status = {"sale": "for_sale", "rent": "for_rent"}.get(_text(item.get("offerType")))
    price = _number(_mapping(item.get("price")).get("value"))
    price_text = None
    rent = _mapping(item.get("rentPriceRange"))
    low, high = _number(rent.get("min")), _number(rent.get("max"))
    if low is not None and high is not None and low <= high:
        # A range does not establish one property's exact asking price.
        price_text = f"{low:,}–{high:,}" if low != high else f"{low:,}"
        if low == high:
            price = low
    return _compact({
        "kind": "property_listing", "source": "redfin",
        "listing_id": next((value for value in (
            _identifier(item.get(key)) for key in ("listingId", "rentalId", "propertyId")
        ) if value), None),
        "address": _address(address.get("formattedStreetLine") if address else street,
                            city, state, postal),
        "city": _text(city, 100), "state": _text(state, 64),
        "postal_code": _text(postal, 24), "price": price, "price_text": price_text,
        "listing_status": status,
        # Redfin's numeric propertyType/searchStatus enums and its dom field do
        # not establish a Zillow property type or days-on-Zillow value.
        "property_type": _text(item.get("propertyType"), 64),
        "bedrooms": _number(item.get("beds")), "bathrooms": _number(item.get("baths")),
        "area": _number(_mapping(item.get("sqFt")).get("value")),
        "area_unit": "sqft" if _number(_mapping(item.get("sqFt")).get("value"))
        is not None else None,
        "days_on_zillow": None,
        "url": _url(item.get("url"), _PROPERTY_HOSTS["redfin"]),
    })
