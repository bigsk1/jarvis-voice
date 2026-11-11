"""Real Stash receipts and local reads retain native Google evidence offline."""

import importlib
import importlib.util
import json
import sys
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from config_loader import config_scope
from stash_helper import resolve_file_path

ROOT = Path(__file__).resolve().parents[1]


def native_response():
    """Synthetic values use the native panel shapes, without private fixtures."""
    return {
        "search_metadata": {
            "id": "fixture-google-search", "status": "Success",
            "created_at": "2026-11-11 12:00:00 UTC",
            "processed_at": "2026-11-11 12:00:01 UTC",
            "google_url": "https://www.google.com/search?q=fixture+film",
        },
        "search_parameters": {"engine": "google", "q": "Fixture Film watch online",
                              "gl": "us", "hl": "en", "device": "desktop"},
        "search_information": {"query_displayed": "Fixture Film watch online", "total_results": 12345},
        "available_on": [
            {"name": f"Provider {index}", "link": f"https://example.test/offer/{index}",
             "price": "Subscription with add-on" if index == 0 else "$4.99"}
            for index in range(8)
        ],
        "knowledge_graph": {"title": "Fixture Film", "type": "2026 film", "kgmid": "/m/fixture_film",
                            "description": "A synthetic movie for deterministic tests.",
                            "release_date": "November 1, 2026"},
        "organic_results": [
            {"position": index + 1, "title": f"Source {index}",
             "link": f"https://example.test/source/{index}", "snippet": f"Observed evidence {index}.",
             "snippet_highlighted_words": ["evidence"], "source": "Fixture Publisher"}
            for index in range(10)
        ],
        "serpapi_pagination": {"next": "https://serpapi.com/search.json?engine=google&start=10"},
    }


@pytest.fixture
def backend(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / "lib"))
    module = importlib.import_module("serpapi_google")
    payload = native_response()
    provider = Mock(side_effect=lambda *_args, **_kwargs: deepcopy(payload))
    monkeypatch.setattr(module, "request_serpapi", provider)
    stash_root = tmp_path / "selected-mode-artifacts"
    with config_scope("cloud", overrides={
        "SERP_API_KEY": "test-only-serpapi-key", "STASH_DIR": str(stash_root),
        "JARVIS_DEFAULT_LOCATION": "Fixture City, Oregon, United States",
        "JARVIS_DEFAULT_POSTAL_CODE": "97000",
    }):
        yield SimpleNamespace(module=module, provider=provider, payload=payload, stash_root=stash_root)


def panel(result, path):
    return next(item for item in result["data"]["result"]["panels"] if item["path"] == path)


def saved_native(result):
    path = Path(resolve_file_path(stash_ref=result["data"]["raw_ref"]))
    return path, json.loads(path.read_text(encoding="utf-8"))


def read(backend, initial, path, **arguments):
    return backend.module.run_google_search({
        "action": "read_result", "raw_ref": initial["data"]["raw_ref"], "path": path, **arguments,
    })


def test_search_defaults_native_panels_and_exact_receipt_in_custom_stash(backend):
    result = backend.module.run_google_search({"query": "Fixture Film watch online"})
    parameters = backend.provider.call_args.args[0]
    assert {key: parameters[key] for key in ("engine", "q", "gl", "hl", "device", "start", "safe")} == {
        "engine": "google", "q": "Fixture Film watch online", "gl": "us", "hl": "en",
        "device": "desktop", "start": 0, "safe": "active",
    }
    assert parameters["location"] == "Fixture City, Oregon, United States"
    assert parameters["no_cache"] == "false"
    assert backend.provider.call_args.kwargs == {
        "timeout": 90, "use_proxy": False, "fallback_on_proxy_fail": False,
    }
    assert result["ok"] is True
    assert result["data"]["source"] == {
        "provider": "serpapi", "tool": "serpapi_google_search", "mode": "cloud",
    }
    assert result["data"]["execution"]["search_id"] == "fixture-google-search"
    assert result["data"]["execution"]["serpapi_searches_used"] == 1
    assert result["data"]["result"]["pagination"] == {"has_more": True, "next_start": 10}
    assert panel(result, "/available_on")["preview"] == backend.payload["available_on"]
    assert panel(result, "/organic_results")["preview_count"] == 10
    path, native = saved_native(result)
    assert path.is_relative_to(backend.stash_root)
    assert native == backend.payload
    backend.provider.assert_called_once()


@pytest.mark.parametrize("arguments,expected", [
    ({"location": "Explicit City", "country": "CA", "language": "FR", "device": "mobile"},
     {"location": "Explicit City", "gl": "ca", "hl": "fr", "device": "mobile"}),
    ({"uule": "fixture-encoded-location"}, {"uule": "fixture-encoded-location"}),
    ({"extra_params": {"lat": "45.0", "lon": "-122.0"}}, {"lat": "45.0", "lon": "-122.0"}),
])
def test_explicit_localization_and_coordinates_replace_configured_defaults(backend, arguments, expected):
    backend.module.run_google_search({"query": "reference", **arguments})
    submitted = backend.provider.call_args.args[0]
    assert all(submitted[key] == value for key, value in expected.items())
    if "location" not in expected:
        assert "location" not in submitted


def test_postal_fallback_and_missing_location_are_mode_configured(backend):
    with config_scope("cloud", overrides={"JARVIS_DEFAULT_LOCATION": "", "JARVIS_DEFAULT_POSTAL_CODE": "97000"}):
        params, _source = backend.module.build_search_params({"query": "reference"})
        assert params["location"] == "97000"
    with config_scope("cloud", overrides={"JARVIS_DEFAULT_LOCATION": "", "JARVIS_DEFAULT_POSTAL_CODE": ""}):
        params, _source = backend.module.build_search_params({"query": "reference"})
        assert "location" not in params


@pytest.mark.parametrize("extra", [
    {"engine": "google_light"}, {"api_key": "must-not-be-sent"}, {"output": "html"},
    {"async": True}, {"json_restrictor": "organic_results"}, {"q": "different query"},
    {"gl": "ca"}, {"tbm": "nws", "udm": "14"}, {"lat": "45.0"},
    {"a": ["nested"]}, {"a": float("nan")}, {"bad key": "value"},
])
def test_invalid_or_reserved_extra_controls_fail_before_provider(backend, extra):
    with pytest.raises(ValueError):
        backend.module.run_google_search({"query": "reference", "extra_params": extra})
    backend.provider.assert_not_called()


def test_local_panel_pages_preserve_entity_inventory_and_do_not_repeat_search(backend):
    initial = backend.module.run_google_search({"query": "Fixture Film watch online"})
    first = read(backend, initial, "/available_on", limit=4)
    assert panel(first, "/available_on")["preview"] == backend.payload["available_on"][:4]
    assert first["data"]["result"]["returned_count"] == 4
    assert first["data"]["result"]["has_more"] is True
    assert first["data"]["result"]["next_offset"] == 4
    assert panel(first, "/knowledge_graph")["preview"]["title"] == "Fixture Film"
    assert {item["path"] for item in first["data"]["result"]["section_inventory"]} == {
        "/" + key for key in backend.payload
    }
    second = read(backend, initial, "/available_on", limit=4, offset=4)
    assert panel(second, "/available_on")["preview"] == backend.payload["available_on"][4:]
    assert second["data"]["result"]["returned_count"] == 4
    assert second["data"]["result"]["has_more"] is False
    assert second["data"]["result"]["next_offset"] is None
    assert second["data"]["execution"]["serpapi_searches_used"] == 0
    assert second["data"]["raw_ref"] == initial["data"]["raw_ref"]
    assert saved_native(second)[1] == backend.payload
    backend.provider.assert_called_once()


def test_unknown_heterogeneous_panel_and_escaped_pointer_keep_native_values(backend):
    backend.payload["future/panel"] = {"~values": [None, False, 0, "word", [], {}, {"flag": False}]}
    initial = backend.module.run_google_search({"query": "reference", "limit": 50, "max_chars": 60000})
    assert panel(initial, "/future~1panel")["preview"] == backend.payload["future/panel"]
    inspected = read(backend, initial, "/future~1panel/~0values", limit=50, max_chars=60000)
    assert panel(inspected, "/future~1panel/~0values")["preview"] == backend.payload["future/panel"]["~values"]
    assert inspected["data"]["result"]["returned_count"] == 7
    assert inspected["data"]["result"]["has_more"] is False
    assert saved_native(inspected)[1] == backend.payload
    backend.provider.assert_called_once()


def test_json_pointer_preserves_literal_key_whitespace(backend):
    backend.payload[" panel "] = {" values ": [False, None, 0]}
    initial = backend.module.run_google_search({"query": "reference"})
    inspected = read(backend, initial, "/ panel / values ")
    assert panel(inspected, "/ panel / values ")["preview"] == [False, None, 0]
    assert inspected["data"]["result"]["selected_path"] == "/ panel / values "
    backend.provider.assert_called_once()


@pytest.mark.parametrize("value", [None, False, 0, True, 1])
@pytest.mark.parametrize("offset", [0, 1])
def test_present_scalar_null_boolean_and_zero_have_truthful_paging(backend, value, offset):
    backend.payload["scalar"] = value
    initial = backend.module.run_google_search({"query": "reference"})
    inspected = read(backend, initial, "/scalar", offset=offset)
    result = inspected["data"]["result"]
    assert result["returned_count"] == (1 if offset == 0 else 0)
    assert result["has_more"] is False
    assert result["next_offset"] is None
    if offset == 0:
        assert panel(inspected, "/scalar")["preview"] is value
    backend.provider.assert_called_once()


def test_budgeted_object_pages_advance_over_original_key_prefix_without_skips(backend):
    backend.payload["group"] = {
        **{f"field_{index}": "Observed text " * 250 for index in range(8)},
        "title": "Identity is last in native key order",
    }
    initial = backend.module.run_google_search({"query": "reference"})
    expected, seen, offset = list(backend.payload["group"]), [], 0
    for _attempt in range(20):
        inspected = read(backend, initial, "/group", offset=offset, limit=10, max_chars=2000)
        keys = list(panel(inspected, "/group").get("preview", {}))
        assert keys == expected[offset:offset + len(keys)]
        assert inspected["data"]["result"]["returned_count"] == len(keys)
        seen.extend(keys)
        if not inspected["data"]["result"]["has_more"]:
            break
        next_offset = inspected["data"]["result"]["next_offset"]
        assert next_offset > offset
        offset = next_offset
    assert seen == expected
    backend.provider.assert_called_once()


def test_long_text_over_ten_thousand_characters_remains_readable_from_retained_source(backend):
    long_text = "Retained textual evidence. " * 700 + "EXACT_FINAL_MARKER"
    backend.payload["knowledge_graph"]["description"] = long_text
    initial = backend.module.run_google_search({"query": "reference"})
    inspected = read(backend, initial, "/knowledge_graph/description", max_chars=60000)
    assert panel(inspected, "/knowledge_graph/description")["preview"] == long_text
    assert inspected["data"]["result"]["returned_count"] == len(long_text)
    assert inspected["data"]["result"]["has_more"] is False
    assert len(json.dumps(inspected["data"], ensure_ascii=True, separators=(",", ":"))) <= 60000
    assert saved_native(inspected)[1]["knowledge_graph"]["description"] == long_text
    backend.provider.assert_called_once()


def test_long_legal_query_with_minimum_budget_keeps_paid_search_receipt(backend):
    query = "q" * 1500
    backend.payload.clear()
    backend.payload.update({"search_metadata": {"id": "paid-search-receipt", "status": "Success"},
                            "organic_results": []})
    result = backend.module.run_google_search({"query": query, "max_chars": 2000})
    assert result["ok"] is True
    assert result["data"]["execution"]["search_id"] == "paid-search-receipt"
    assert result["data"]["raw_ref"].startswith("stash://")
    assert result["data"]["limits"]["truncated"] is True
    assert len(json.dumps(result["data"], ensure_ascii=True, separators=(",", ":"))) <= 2000
    assert saved_native(result)[1] == backend.payload
    backend.provider.assert_called_once()


def test_panel_only_response_is_successful_evidence_with_empty_organic_results(backend):
    backend.payload["organic_results"] = []
    result = backend.module.run_google_search({"query": "Fixture Film watch online"})
    assert result["ok"] is True
    assert panel(result, "/organic_results")["count"] == 0
    assert panel(result, "/available_on")["count"] == 8
    assert panel(result, "/knowledge_graph")["preview"]["title"] == "Fixture Film"
    assert "available_on" in result["speech"]
    backend.provider.assert_called_once()


@pytest.mark.parametrize("arguments", [
    {"path": "/does_not_exist"}, {"path": "/future~2panel"},
    {"raw_ref": "https://example.test/response.json"},
    {"raw_ref": "stash://../secrets"}, {"query": "must not search on a read"},
])
def test_invalid_read_inputs_never_fall_back_to_provider(backend, arguments):
    initial = backend.module.run_google_search({"query": "reference"})
    with pytest.raises((ValueError, OSError)):
        backend.module.run_google_search({
            "action": "read_result", "raw_ref": initial["data"]["raw_ref"], **arguments,
        })
    backend.provider.assert_called_once()


def test_stash_retention_failure_keeps_provider_evidence_without_false_download(backend, monkeypatch):
    import stash_helper

    def unavailable(*_args, **_kwargs):
        raise OSError("private filesystem details must not be echoed")

    monkeypatch.setattr(stash_helper.StashFile, "save_binary", unavailable)
    result = backend.module.run_google_search({"query": "reference"})
    assert result["ok"] is True
    assert result["data"]["execution"]["search_id"] == "fixture-google-search"
    assert result["data"]["raw_ref"] is None
    assert result["data"]["limits"]["raw_retention_error"] == "OSError"
    assert "do not repeat the paid search automatically" in result["speech"]
    assert "private filesystem" not in json.dumps(result)
    assert panel(result, "/available_on")["count"] == 8
    backend.provider.assert_called_once()


def test_provider_failure_produces_one_error_json_without_inventing_saved_receipt(backend, monkeypatch):
    backend.provider.side_effect = RuntimeError("SerpApi request failed with HTTP 429.")
    spec = importlib.util.spec_from_file_location("google_search_cli_test", ROOT / "skills/serpapi_google_search.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "load_config", lambda: None)
    monkeypatch.setattr(sys, "argv", ["serpapi_google_search.py", json.dumps({"query": "reference"})])
    output = StringIO()
    with redirect_stdout(output):
        code = module.main()
    result = json.loads(output.getvalue())
    assert code == 1 and result["ok"] is False
    assert "HTTP 429" in result["error"]
    assert "raw_ref" not in json.dumps(result)
    assert not backend.stash_root.exists()
    backend.provider.assert_called_once()


def test_every_root_section_can_be_inventoried_with_small_local_pages(backend):
    backend.payload.update({f"unfamiliar_google_section_{index:02d}": {"flag": False} for index in range(40)})
    initial = backend.module.run_google_search({"query": "reference", "max_chars": 2000})
    expected, seen, offset = list(backend.payload), [], 0
    for _attempt in range(50):
        inspected = read(backend, initial, "", offset=offset, limit=10, max_chars=2000)
        result = inspected["data"]["result"]
        keys = [item["key"] for item in result["panels"]]
        assert result["panels_count"] == len(expected)
        assert keys == expected[offset:offset + len(keys)]
        assert result["returned_count"] == len(keys)
        seen.extend(keys)
        if not result["has_more"]:
            break
        assert result["next_offset"] > offset
        offset = result["next_offset"]
    assert seen == expected
    backend.provider.assert_called_once()


def test_subsequent_projection_recomputes_local_text_cursor_from_shown_characters(backend):
    value = "Original text evidence. " * 700 + "RETAINED_END_MARKER"
    backend.payload["knowledge_graph"]["description"] = value
    initial = backend.module.run_google_search({"query": "reference"})
    inspected = read(backend, initial, "/knowledge_graph/description", max_chars=60000)
    projected = backend.module.project_google_result(inspected, max_chars=2000)
    selected = next(item for item in projected["result"]["panels"]
                    if item["path"] == "/knowledge_graph/description")
    shown = selected["preview"]
    assert 0 < len(shown) < len(value)
    assert value.startswith(shown)
    assert projected["result"]["returned_count"] == len(shown)
    assert projected["result"]["next_offset"] == len(shown)
    assert projected["result"]["has_more"] is True
    assert projected["raw_ref"] == inspected["data"]["raw_ref"]
    assert len(json.dumps(projected, ensure_ascii=True, separators=(",", ":"))) <= 2000
    backend.provider.assert_called_once()


@pytest.mark.parametrize("value", [[False, 1, None], [None, False, 0], [True, False, None]])
def test_tight_preview_never_substitutes_null_for_an_omitted_native_scalar(backend, value):
    helper = importlib.import_module("serpapi_google_result")
    for budget in range(4, 25):
        preview, truncated = helper.preview_value(value, budget)
        assert isinstance(preview, list)
        assert json.dumps(preview) == json.dumps(value[:len(preview)])
        assert len(helper.json_text(preview)) <= budget
        assert truncated is (len(preview) < len(value))


def test_projector_ignores_noncontract_wrappers_and_rejects_impostor_shape(backend):
    initial = backend.module.run_google_search({"query": "reference"})
    helper = importlib.import_module("serpapi_google_result")
    initial["data"]["unrelated_runtime_config"] = {"private": "must not enter evidence"}
    projected = helper.project_google_result(initial)
    assert "unrelated_runtime_config" not in projected
    assert "must not enter evidence" not in json.dumps(projected)
    impostor = deepcopy(initial)
    impostor["data"]["source"]["provider"] = "another_provider"
    assert helper.project_google_result(impostor) == {}
    for malformed in ({"source": []}, {"result": []}, {"source": None}, {"result": None}):
        candidate = {**initial["data"], **malformed}
        assert helper.is_google_result(candidate) is False


def test_other_tool_artifact_is_not_a_google_read_capability(backend):
    from external_results import make_external_result_data

    other = make_external_result_data(
        provider="unrelated", tool="serpapi_google_search", result={"kind": "object"},
        raw_payload={"arbitrary": "A canonical artifact is not sufficient ownership evidence."},
    )
    with pytest.raises(ValueError, match="not a serpapi_google_search response"):
        backend.module.run_google_search({"action": "read_result", "raw_ref": other["raw_ref"]})
    backend.provider.assert_not_called()


def test_unsafe_native_integer_is_exact_in_archive_and_explicitly_encoded_for_browser(backend):
    integer = 9007199254740993
    backend.payload["future_integer"] = {"record_id": integer, "enabled": False, "empty": None}
    initial = backend.module.run_google_search({"query": "reference"})
    assert saved_native(initial)[1]["future_integer"]["record_id"] == integer
    assert type(saved_native(initial)[1]["future_integer"]["record_id"]) is int
    assert panel(initial, "/future_integer")["preview"] == {
        "record_id": str(integer), "enabled": False, "empty": None,
    }
    assert initial["data"]["limits"]["integer_strings"] is True
    backend.provider.assert_called_once()


def test_opaque_url_omitted_by_budget_has_explicit_nonadvancing_cursor(backend):
    url = "https://example.test/" + "x" * 10000
    backend.payload["long_url"] = url
    initial = backend.module.run_google_search({"query": "reference"})
    inspected = read(backend, initial, "/long_url", max_chars=2000)
    selected = panel(inspected, "/long_url")
    assert "preview" not in selected
    assert selected["truncated"] is True
    assert inspected["data"]["result"]["returned_count"] == 0
    assert inspected["data"]["result"]["has_more"] is True
    assert inspected["data"]["result"]["next_offset"] is None
    assert inspected["data"]["limits"]["page_blocked_by_budget"] is True
    assert saved_native(inspected)[1]["long_url"] == url
    backend.provider.assert_called_once()


def test_explicit_large_read_budget_survives_archive_envelope_construction(backend):
    value = "Retained evidence with a literal tail. " * 4000
    backend.payload["long_text"] = value
    initial = backend.module.run_google_search({"query": "reference"})
    inspected = read(backend, initial, "/long_text", max_chars=60000)
    shown = panel(inspected, "/long_text")["preview"]
    assert len(shown) > 48000
    assert value.startswith(shown)
    assert inspected["data"]["result"]["next_offset"] == len(shown)
    assert len(json.dumps(inspected["data"], separators=(",", ":"))) <= 60000
    backend.provider.assert_called_once()


def test_foreign_country_override_does_not_inherit_us_origin(backend):
    initial = backend.module.run_google_search({"query": "film availability", "country": "fr"})
    params = backend.provider.call_args.args[0]
    assert params["gl"] == "fr"
    assert "location" not in params
    assert initial["data"]["result"]["inventory_complete"] is True


def test_preview_truncation_does_not_imply_missing_inventory(backend):
    backend.payload["future_panel"] = {"long_text": "a" * 30000}
    initial = backend.module.run_google_search({"query": "reference"})
    assert initial["data"]["limits"]["truncated"] is True
    assert initial["data"]["result"]["inventory_complete"] is True
    assert {item["key"] for item in initial["data"]["result"]["panels"]} == set(backend.payload)
