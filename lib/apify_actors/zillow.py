"""Verified Zillow listing shapes from the reviewed Search, ZIP and Detail Actors."""

from collections.abc import Mapping

from .properties import _address, _compact, _identifier, _mapping, _number, _text, _url

ACTORS = frozenset({"X46xKaa20oUA1fRiP", "l7auNT3I30CssRrvO", "ENK9p4RZHg0iVso52"})
_PROPERTY_HOSTS = {"zillow": frozenset({"zillow.com", "www.zillow.com"})}
_ZILLOW_IMAGE_HOSTS = frozenset({"photos.zillowstatic.com"})
_STATUSES = {
    "forSale": "for_sale", "forRent": "for_rent", "sold": "sold",
    "pending": "pending", "comingSoon": "coming_soon",
}
_PROPERTY_TYPES = {
    "SINGLE_FAMILY": "single_family", "MULTI_FAMILY": "multi_family",
    "CONDO": "condo", "TOWNHOUSE": "townhouse", "APARTMENT": "apartment",
    "MANUFACTURED": "manufactured", "LOT": "lot", "LAND": "land",
    "COOPERATIVE": "cooperative",
}



def normalize(item: Mapping[str, object]) -> dict[str, object] | None:
    if item.get("isValid") is False or item.get("error") not in (None, ""):
        return None
    address = _mapping(item.get("listingAddress"))
    price = _mapping(item.get("listingPrice"))
    if not address and not price and not any(
        key in item for key in ("listingStatus", "propertyUrl")
    ):
        return None
    status = _text(item.get("listingStatus"), 64)
    home_type = _text(item.get("homeType"), 64)
    image = item.get("mainImage")
    if isinstance(image, dict):
        sizes = _mapping(image)
        image = next((sizes.get(key) for key in ("medium", "hiRes", "thumbnail")
                      if _url(sizes.get(key), _ZILLOW_IMAGE_HOSTS)), None)
    return _compact({
        "kind": "property_listing", "source": "zillow",
        "listing_id": _identifier(item.get("zpid")),
        "address": _text(address.get("full"), 300) or _address(
            address.get("street"), address.get("city"), address.get("state"),
            address.get("zipCode"),
        ),
        "city": _text(address.get("city"), 100),
        "state": _text(address.get("state"), 64),
        "postal_code": _text(address.get("zipCode"), 24),
        "price": _number(price.get("amount")),
        "price_text": _text(price.get("formatted"), 100),
        "currency": _text(price.get("currency"), 12),
        "listing_status": _STATUSES.get(status, status) if status else None,
        "property_type": _PROPERTY_TYPES.get(home_type, home_type) if home_type else None,
        "bedrooms": _number(item.get("bedrooms")),
        "bathrooms": _number(item.get("bathrooms")),
        "area": _number(item.get("livingArea")),
        "area_unit": _text(item.get("livingAreaUnit"), 24),
        "days_on_zillow": _number(item.get("daysOnZillow")),
        "url": _url(item.get("propertyUrl"), _PROPERTY_HOSTS["zillow"]),
        "image_url": _url(image, _ZILLOW_IMAGE_HOSTS),
        "scraped_at": _text(item.get("scrapedAt"), 48),
    })
