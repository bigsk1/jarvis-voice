"""Full retained pages become saved reports without model/provider work."""

import importlib
import json
import sys
from types import SimpleNamespace

import pytest

from lib import property_reports


def native(index=1, city="Albany"):
    return {"zpid": str(index), "listingAddress": {"full": f"{index} Example St", "city": city},
            "listingStatus": "forSale", "listingPrice": {"amount": 400000},
            "propertyUrl": f"https://www.zillow.com/homedetails/{index}_zpid/"}


def page(items, *, offset=0, total=None):
    return {"run": {"id": "runA", "actId": "X46xKaa20oUA1fRiP", "status": "SUCCEEDED",
                    "finishedAt": "2026-11-11T05:00:00Z"},
            "dataset": {"id": "datasetA", "itemCount": len(items) if total is None else total},
            "offset": offset, "items": items}


def payload(markdown):
    return json.loads(markdown.split("```property-listings\n", 1)[1].rsplit("\n```", 1)[0])


def test_full_native_page_survives_short_model_preview(monkeypatch):
    monkeypatch.setattr(property_reports, "_read_archive", lambda _source: page([native(i) for i in range(100)]))
    result = payload(property_reports.build_property_report([{"ref": "archiveA", "mode": "cloud"}],
        criteria_text="Requested Albany homes, $300k–$600k"))
    assert len(result["items"]) == 100
    assert result["coverage"] == {"returned_count": 100, "fetched_count": 100,
                                  "unrecognized_count": 0, "total_items": 100,
                                  "offset": 0, "complete": True}
    assert result["snapshot_at"] == "2026-11-11T05:00:00+00:00"
    assert result["items"][0]["days_on_zillow"] is None
    assert "Requested" in result["criteria_text"]


def test_overlapping_pages_deduplicate_native_identity_without_fuzzy_addresses(monkeypatch):
    pages = {"first": page([native(1), native(2)], total=3),
             "second": page([native(2), native(3, "Lebanon")], offset=1, total=3)}
    monkeypatch.setattr(property_reports, "_read_archive", lambda source: pages[source["ref"]])
    result = payload(property_reports.build_property_report([
        {"ref": "first", "mode": "cloud"}, {"ref": "second", "mode": "cloud"}]))
    assert len(result["items"]) == 3 and result["duplicates_removed"] == 1
    assert result["coverage"]["returned_count"] == 4
    assert result["coverage"]["fetched_count"] == 4
    assert result["coverage"]["complete"] is True
    assert result["coverage"]["total_items"] == 3


def test_mixed_native_rows_keep_properties_and_cover_error_positions(monkeypatch):
    archive = page([{"error": "first request failed"}, native(1), None, native(2)])
    original = json.dumps(archive, sort_keys=True)
    monkeypatch.setattr(property_reports, "_read_archive", lambda _source: archive)
    result = payload(property_reports.build_property_report([{"ref": "mixed", "mode": "cloud"}]))
    assert [row["listing_id"] for row in result["items"]] == ["1", "2"]
    assert result["coverage"] == {"returned_count": 2, "fetched_count": 4,
        "unrecognized_count": 2, "total_items": 4, "offset": 0, "complete": True}
    assert result["duplicates_removed"] == 0
    assert json.dumps(archive, sort_keys=True) == original


def test_all_unsupported_native_records_keep_known_source_and_exclusion_evidence(monkeypatch):
    monkeypatch.setattr(property_reports, "_read_archive", lambda _source: page([{"error": "failed"}, None]))
    result = payload(property_reports.build_property_report([{"ref": "errors", "mode": "cloud"}]))
    assert result["source"] == "zillow" and result["items"] == []
    assert result["coverage"] == {"returned_count": 0, "fetched_count": 2,
        "unrecognized_count": 2, "total_items": 2, "offset": 0, "complete": True}


def test_overlapping_mixed_pages_deduplicate_valid_rows_but_keep_native_range_counts(monkeypatch):
    pages = {"first": page([native(1), {"error": "failed"}, native(2)], total=4),
             "second": page([native(2), native(3)], offset=2, total=4)}
    monkeypatch.setattr(property_reports, "_read_archive", lambda source: pages[source["ref"]])
    result = payload(property_reports.build_property_report([
        {"ref": "first", "mode": "cloud"}, {"ref": "second", "mode": "cloud"}]))
    assert result["coverage"] == {"returned_count": 4, "fetched_count": 5,
        "unrecognized_count": 1, "total_items": 4, "offset": 0, "complete": True}
    assert len(result["items"]) == 3 and result["duplicates_removed"] == 1


def test_repeated_pages_cannot_cover_a_gap_even_when_fetched_count_reaches_total(monkeypatch):
    pages = {"first": page([native(1)], total=3), "third": page([native(3)], offset=2, total=3)}
    monkeypatch.setattr(property_reports, "_read_archive", lambda source: pages[source["ref"]])
    result = payload(property_reports.build_property_report([
        {"ref": "first", "mode": "cloud"}, {"ref": "first", "mode": "cloud"},
        {"ref": "third", "mode": "cloud"}]))
    assert result["coverage"]["fetched_count"] == result["coverage"]["total_items"] == 3
    assert result["coverage"]["complete"] is False


def test_partial_mixed_page_retains_native_start_offset(monkeypatch):
    monkeypatch.setattr(property_reports, "_read_archive", lambda _source:
                        page([native(1), {"error": "failed"}], offset=20, total=100))
    result = payload(property_reports.build_property_report([{"ref": "partial", "mode": "cloud"}]))
    assert result["coverage"] == {"returned_count": 1, "fetched_count": 2,
        "unrecognized_count": 1, "total_items": 100, "offset": 20, "complete": False}


def test_multiple_datasets_have_aggregate_totals_but_no_shared_offset(monkeypatch):
    first, second = page([native(1)]), page([native(2)])
    second["run"]["id"], second["dataset"]["id"] = "runB", "datasetB"
    archives = {"first": first, "second": second}
    monkeypatch.setattr(property_reports, "_read_archive", lambda source: archives[source["ref"]])
    result = payload(property_reports.build_property_report([
        {"ref": "first", "mode": "cloud"}, {"ref": "second", "mode": "cloud"}]))
    assert result["coverage"] == {"returned_count": 2, "fetched_count": 2,
        "unrecognized_count": 0, "total_items": 2, "offset": None, "complete": True}


def test_reused_named_dataset_is_counted_once_across_successful_runs(monkeypatch):
    first, second = page([native(1)], total=2), page([native(2)], offset=1, total=2)
    second["run"]["id"] = "runB"
    archives = {"first": first, "second": second}
    monkeypatch.setattr(property_reports, "_read_archive", lambda source: archives[source["ref"]])
    result = payload(property_reports.build_property_report([
        {"ref": "first", "mode": "cloud"}, {"ref": "second", "mode": "cloud"}]))
    assert result["coverage"]["total_items"] == 2
    assert result["coverage"]["complete"] is True


def test_total_becomes_unknown_when_previously_observed_count_lags_new_native_positions(monkeypatch):
    archives = {"first": page([native(1)], total=1),
                "second": page([native(2)], offset=1, total=1)}
    monkeypatch.setattr(property_reports, "_read_archive", lambda source: archives[source["ref"]])
    result = payload(property_reports.build_property_report([
        {"ref": "first", "mode": "cloud"}, {"ref": "second", "mode": "cloud"}]))
    assert result["coverage"]["total_items"] is None and result["coverage"]["complete"] is False


@pytest.mark.parametrize("attribution,expected", [(None, False), ({"provider": "unknown"}, False),
                                                  ({"provider": "openstreetmap"}, True)])
def test_geography_credit_only_comes_from_proven_archive_metadata(monkeypatch, attribution, expected):
    archive = page([native()])
    if attribution is not None:
        archive["geography_attribution"] = attribution
    monkeypatch.setattr(property_reports, "_read_archive", lambda _source: archive)
    result = payload(property_reports.build_property_report([{"ref": "first", "mode": "cloud"}]))
    assert ("geography_attribution" in result) is expected
    if expected:
        assert result["geography_attribution"] == {"provider": "openstreetmap"}


@pytest.mark.parametrize("counts", [
    {"input_count": True, "unrecognized_count": 0},
    {"input_count": 0, "unrecognized_count": 0},
    {"input_count": 1, "unrecognized_count": 1},
    {"input_count": 2, "unrecognized_count": -1},
])
def test_inconsistent_canonical_native_counts_cannot_claim_coverage(monkeypatch, counts):
    archive = {"presentation": {"kind": "property_listings", "source": "zillow",
        "items": [{"kind": "property_listing", "source": "zillow"}], **counts}}
    monkeypatch.setattr(property_reports, "_read_archive", lambda _source: archive)
    with pytest.raises(ValueError, match="inconsistent"):
        property_reports.build_property_report([{"ref": "first", "mode": "cloud"}])


@pytest.mark.parametrize("offset,total,expected", [(20, 100, False), (0, 100, False), (0, 0, False), (0, 1, True)])
def test_coverage_never_promotes_partial_or_lagging_dataset_counts(monkeypatch, offset, total, expected):
    monkeypatch.setattr(property_reports, "_read_archive", lambda _source: page([native()], offset=offset, total=total))
    result = payload(property_reports.build_property_report([{"ref": "first", "mode": "local"}]))
    assert result["coverage"]["complete"] is expected
    assert result["coverage"]["offset"] == offset
    if total == 0:
        assert result["coverage"]["total_items"] is None


def test_report_accepts_canonical_provider_pages_and_mixed_sources(monkeypatch):
    archives = {
        source: {"presentation": {"kind": "property_listings", "items": [
            {"kind": "property_listing", "source": source, "listing_id": "1", "price": None,
             "listing_status": None, "days_on_zillow": None}]}} for source in ("zillow", "redfin")}
    monkeypatch.setattr(property_reports, "_read_archive", lambda source: archives[source["ref"]])
    result = payload(property_reports.build_property_report([
        {"ref": "zillow", "mode": "cloud"}, {"ref": "redfin", "mode": "local"}]))
    assert result["source"] == "mixed" and len(result["items"]) == 2
    assert result["coverage"]["complete"] is False


def test_json_survives_canvas_escaped_newline_handling(monkeypatch):
    monkeypatch.setattr(property_reports, "_read_archive", lambda _source: page([native()]))
    text = "Literal \\n is text; real\nnewline is whitespace"
    markdown = property_reports.build_property_report([{"ref": "first", "mode": "cloud"}], criteria_text=text)
    assert payload(markdown.replace("\\n", "\n"))["criteria_text"] == " ".join(text.split())


@pytest.mark.parametrize("archive", [[], {}, {"items": [{"error": "No results found"}]},
    {"presentation": {"kind": "property_listings", "items": [{"source": "zillow"}]}}])
def test_unknown_or_invalid_pages_are_not_published_as_property_results(monkeypatch, archive):
    monkeypatch.setattr(property_reports, "_read_archive", lambda _source: archive)
    with pytest.raises(ValueError):
        property_reports.build_property_report([{"ref": "first", "mode": "cloud"}])


def test_source_ref_requires_saved_mode_and_canonical_stash_identity():
    for source in ({"ref": "file:///etc/passwd", "mode": "cloud"},
                   {"ref": "stash://space_example/f_example", "mode": "guess"}):
        with pytest.raises(ValueError, match="canonical Stash ref"):
            property_reports._read_archive(source)


def test_source_is_read_under_saved_mode_and_cannot_escape_space(tmp_path, monkeypatch):
    import config_loader
    import stash_helper

    space = tmp_path / "space"
    space.mkdir()
    document = space / "page.json"
    document.write_text(json.dumps(page([native()])))
    modes = []
    monkeypatch.setattr(stash_helper, "resolve_file_path", lambda **_kwargs: str(document))
    monkeypatch.setattr(stash_helper, "get_space", lambda _sid: (
        modes.append(config_loader.get_active_config_mode()) or SimpleNamespace(space_path=space)))
    source = {"ref": "stash://space_example/f_example", "mode": "local"}
    assert property_reports._read_archive(source)["items"]
    assert modes == ["local"]
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    document.unlink()
    document.symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        property_reports._read_archive(source)


def test_canvas_tool_can_create_complete_report_without_copying_rows_into_prompt(monkeypatch, capsys):
    import skills.canvas as tool

    bridge = importlib.import_module("property_reports")
    monkeypatch.setattr(bridge, "_read_archive", lambda _source: page([native(i) for i in range(8)]))
    monkeypatch.setattr(tool, "load_config", lambda: None)
    captured = []
    monkeypatch.setattr(tool, "create_page", lambda *args, **_kwargs: (captured.append(args[1]) or {"ok": True}))
    monkeypatch.setattr(sys, "argv", ["canvas.py", json.dumps({"action": "create", "title": "Property test",
        "property_sources": [{"ref": "stash://space_example/f_example", "mode": "cloud"}]})])
    tool.main()
    assert json.loads(capsys.readouterr().out)["ok"]
    assert len(payload(captured[0])["items"]) == 8
