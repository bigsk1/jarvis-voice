"""Small explicit registry of reviewed Actor input and presentation adapters.

Ordinary Actors use their own input schema and the generic result envelope.
Adding an adapter does not grant trust or another execution path.
"""

from __future__ import annotations

from typing import Any

from . import redfin, zillow
from .properties import _mapping


def actor_input(arguments: dict[str, Any]) -> dict[str, Any]:
    """Require exactly one input source on every foreground/background caller."""
    if ("input" in arguments) == ("search" in arguments):
        raise ValueError("Provide exactly one of input or search, together with actor")
    if "search" in arguments:
        from . import zillow_search

        # Input preparation is deliberately opt-in for a reviewed Actor family.
        return zillow_search.compile_search(arguments.get("actor"), arguments["search"])
    value = arguments["input"]
    if not isinstance(value, dict):
        raise ValueError("Actor input must be a JSON object")
    return value


def normalize_property_page(actor_id: str, items: list[object]) -> dict[str, object] | None:
    """Keep valid rows and count exclusions; the retained native page stays intact."""
    if actor_id in zillow.ACTORS:
        source, normalize = "zillow", zillow.normalize
    elif actor_id in redfin.ACTORS:
        source, normalize = "redfin", redfin.normalize
    else:
        return None
    rows: list[dict[str, object]] = []
    for item in items:
        row = normalize(_mapping(item))
        if row is not None:
            rows.append(row)
    return {"kind": "property_listings", "source": source, "items": rows,
            "input_count": len(items), "unrecognized_count": len(items) - len(rows)}
