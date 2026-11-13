"""Google Maps filter contracts and reviewed travel-tool child environments."""

import importlib
import json
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from jsonschema import ValidationError, validate

ROOT = Path(__file__).resolve().parents[1]
for directory in ("lib", "skills"):
    sys.path.insert(0, str(ROOT / directory))
tool = importlib.import_module("serpapi_maps_search")
ToolSchema = importlib.import_module("tool_schema").ToolSchema
restrict_child_environment = importlib.import_module("tool_child_environment").restrict_child_environment


def run_main(arguments):
    payload = {"local_results": [{"title": "Cafe", "rating": 3.5, "reviews": 0,
                                   "website": "https://cafe.example", "hours": "Open 24 hours"}]}
    stdout = StringIO()
    with patch.object(tool, "load_config"), patch.object(tool, "request_serpapi", return_value=payload) as request, \
            patch.object(sys, "argv", ["serpapi_maps_search.py", json.dumps(arguments)]), redirect_stdout(stdout):
        code = tool.main()
    return code, json.loads(stdout.getvalue()), request


def test_first_class_filters_are_sent_and_rating_is_a_preference_not_a_verified_cutoff():
    filters = {"min_price": 0, "max_price": 50, "min_rating": 4.5,
               "open_on_day": "fri", "open_at_hour": 0}
    code, result, request = run_main({"query": "cafes", "ll": "@30.2,-97.7,14z", **filters})
    assert code == 0
    assert {key: request.call_args.args[0][key] for key in filters} == filters
    assert result["data"]["requested_filters"] == filters
    assert result["data"]["effective_filters"] == filters
    assert result["data"]["results"][0]["rating"] == 3.5
    assert "ranking preference" in result["data"]["filter_notes"][0]
    assert "not a strict cutoff" in result["speech"]
    assert "overlapping place price ranges" in result["data"]["filter_notes"][1]


def test_existing_extra_parameters_use_the_same_validation_and_canonical_output():
    code, result, request = run_main({"query": "cafes", "extra_params": {
        "min_price": "0", "max_price": "50", "min_rating": "4.0", "open_state": "NOW", "custom_option": "kept",
    }})
    assert code == 0
    assert result["data"]["effective_filters"] == {"min_price": 0, "max_price": 50, "min_rating": 4, "open_state": "now"}
    assert result["data"]["requested_filters"]["min_rating"] == "4.0"
    assert request.call_args.args[0]["open_state"] == "now"
    assert request.call_args.args[0]["custom_option"] == "kept"
    code, _, request = run_main({"query": "cafes", "min_rating": 4, "extra_params": {"min_rating": "4.0"}})
    assert code == 0 and request.call_count == 1


@pytest.mark.parametrize("arguments, expected", [
    ({"min_price": -1}, "nonnegative"), ({"max_price": float('inf')}, "finite"),
    ({"min_price": True}, "number"), ({"min_rating": 5}, "ranking preference"),
    ({"min_price": 50, "max_price": 20}, "below"),
    ({"open_state": "closed"}, "open_state"), ({"open_on_day": "Friday"}, "open_on_day"),
    ({"open_at_hour": 0}, "requires"), ({"open_on_day": "fri", "open_at_hour": 24}, "0 to 23"),
    ({"open_on_day": "fri", "open_at_hour": 1.5}, "integer"),
    ({"open_state": "now", "open_on_day": "fri"}, "cannot be combined"),
    ({"open_state": "24h", "open_at_hour": 0}, "cannot be combined"),
    ({"min_rating": 4, "extra_params": {"min_rating": 4.5}}, "Conflicting"),
    ({"extra_params": {"open_state": "now", "open_on_day": "fri"}}, "cannot be combined"),
    ({"extra_params": {"min_rating": "NaN"}}, "finite"), ({"extra_params": []}, "object"),
])
def test_invalid_or_conflicting_filters_fail_before_any_provider_request(arguments, expected):
    code, result, request = run_main({"query": "cafes", **arguments})
    assert code == 1 and expected in result["error"]
    request.assert_not_called()


def test_default_search_has_no_invented_filters_and_open_24_hours_is_supported():
    code, result, request = run_main({"query": "cafes"})
    assert code == 0 and result["data"]["effective_filters"] == {}
    assert result["data"]["requested_filters"] == {} and result["data"]["filter_notes"] == []
    assert not tool.FILTER_FIELDS.intersection(request.call_args.args[0])
    code, result, request = run_main({"query": "cafes", "open_state": "24h"})
    assert code == 0 and request.call_args.args[0]["open_state"] == "24h"


def test_maps_manifest_validates_current_filters_and_reviewed_travel_children_keep_only_required_settings():
    manifest = json.loads((ROOT / "skills/serpapi_maps_search.tool.json").read_text())
    validate({"query": "cafes", "min_price": 0, "min_rating": 4.5,
              "open_on_day": "fri", "open_at_hour": 0}, manifest["parameters"])
    with pytest.raises(ValidationError):
        validate({"query": "cafes", "min_rating": 5}, manifest["parameters"])
    for name in ("serpapi_google_events", "serpapi_maps_search", "serpapi_tripadvisor"):
        schema = ToolSchema.from_json_file(str(ROOT / "skills" / f"{name}.tool.json"))
        optional = {"JARVIS_DEFAULT_LOCATION", "JARVIS_DEFAULT_POSTAL_CODE"} if name == "serpapi_google_events" else set()
        assert schema.child_environment_names == frozenset({"SERP_API_KEY", *optional})
        for mode in ("cloud", "local"):
            child = restrict_child_environment({
                "PATH": "/usr/bin", "JARVIS_MODE": mode, "SERP_API_KEY": "base-key",
                "JARVIS_OVERRIDE_SERP_API_KEY": "selected-key", "JARVIS_DEFAULT_LOCATION": "City, Region",
                "JARVIS_DEFAULT_POSTAL_CODE": "12345", "OPENAI_API_KEY": "unrelated-secret",
            }, schema.child_environment_names, home="/tmp/travel-child-test", proxy_policy="off")
            assert child["SERP_API_KEY"] == "selected-key" and child["JARVIS_MODE"] == mode
            assert "OPENAI_API_KEY" not in child
            assert optional.issubset(child)
            assert {"JARVIS_DEFAULT_LOCATION", "JARVIS_DEFAULT_POSTAL_CODE"}.intersection(child) == optional
