#!/usr/bin/env python3
"""Regression coverage for the SerpApi Google Images Light tool."""

import json
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT / "skills"))
sys.path.insert(0, str(ROOT / "lib"))

import serpapi_client
from serpapi_google_images_light import (
    GOOGLE_IMAGES_LIGHT_TIMEOUT,
    _google_images_light_request,
    extract_image_results,
    main,
)


def images_payload():
    return {
        "search_metadata": {
            "id": "images-light-123",
            "status": "Success",
            "cached": True,
            "google_images_light_url": "https://www.google.com/search?q=red+mustang&tbm=isch",
        },
        "search_information": {
            "query_displayed": "red 1967 Ford Mustang",
            "image_results_state": "Results for exact spelling",
        },
        "images_results": [
            {
                "position": 1,
                "title": "Red 1967 Ford Mustang",
                "original": "https://images.example/mustang-full.jpg",
                "thumbnail": "https://encrypted.example/mustang-thumb.jpg",
                "serpapi_thumbnail": "https://serpapi.example/mustang-thumb.jpg",
                "source": "Example Motors",
                "link": "https://motors.example/1967-mustang",
                "license_details_url": "https://licenses.example/mustang",
                "source_logo": "https://motors.example/logo.png",
                "original_width": 2400,
                "original_height": 1600,
                "related_content_id": "related-123",
                "is_product": False,
                "in_stock": True,
                "unsafe": False,
            },
            {
                "position": 2,
                "title": "Mustang detail",
                "original": "ftp://unsafe.example/mustang.jpg",
                "serpapi_thumbnail": "https://serpapi.example/detail-thumb.jpg",
                "raw_link": "https://photos.example/mustang-detail",
            },
        ],
        "serpapi_pagination": {
            "current": 1,
            "next": "https://serpapi.com/search?engine=google_images_light&q=mustang&start=100",
            "previous": "https://serpapi.com/search?engine=google_images_light&q=mustang&start=0",
        },
    }


def run_main(arguments, response):
    stdout = StringIO()
    argv = ["serpapi_google_images_light.py", json.dumps(arguments)]
    with patch("serpapi_google_images_light.load_config"), patch(
        "serpapi_google_images_light._google_images_light_request",
        side_effect=response if isinstance(response, Exception) else None,
        return_value=None if isinstance(response, Exception) else response,
    ) as request, patch.object(sys, "argv", argv), redirect_stdout(stdout):
        exit_code = main()
    return exit_code, json.loads(stdout.getvalue()), request


def test_result_normalization_preserves_image_and_source_identity_as_untrusted():
    results, provider_count = extract_image_results(images_payload(), max_results=2)

    assert provider_count == 2
    assert results[0] == {
        "position": 1,
        "title": "Red 1967 Ford Mustang",
        "url": "https://images.example/mustang-full.jpg",
        "original": "https://images.example/mustang-full.jpg",
        "image_url": "https://images.example/mustang-full.jpg",
        "thumbnail": "https://encrypted.example/mustang-thumb.jpg",
        "serpapi_thumbnail": "https://serpapi.example/mustang-thumb.jpg",
        "source": "Example Motors",
        "source_url": "https://motors.example/1967-mustang",
        "license_details_url": "https://licenses.example/mustang",
        "source_logo": "https://motors.example/logo.png",
        "original_width": 2400,
        "original_height": 1600,
        "related_content_id": "related-123",
        "is_product": False,
        "in_stock": True,
        "unsafe": False,
        "untrusted_external_content": True,
    }
    assert "original" not in results[1]
    assert results[1]["url"] == "https://serpapi.example/detail-thumb.jpg"
    assert results[1]["source_url"] == "https://photos.example/mustang-detail"


def test_search_maps_documented_filters_and_returns_workflow_ready_urls():
    exit_code, result, request = run_main(
        {
            "query": "red 1967 Ford Mustang",
            "location": "Austin, Texas, United States",
            "country": "us",
            "language": "en",
            "country_restrict": "countryUS|countryDE",
            "google_domain": "google.com",
            "period_unit": "week",
            "period_value": 2,
            "aspect_ratio": "wide",
            "image_size": "1024x768+",
            "image_color": "red",
            "image_type": "photo",
            "license": "creative_commons",
            "safe": "active",
            "exclude_autocorrected": True,
            "filter_similar": False,
            "device": "mobile",
            "start": 100,
            "max_results": 2,
            "no_cache": True,
        },
        images_payload(),
    )

    assert exit_code == 0
    assert result["ok"] is True
    assert request.call_args.args[0] == {
        "engine": "google_images_light",
        "q": "red 1967 Ford Mustang",
        "google_domain": "google.com",
        "safe": "active",
        "nfpr": "1",
        "filter": "0",
        "start": 100,
        "device": "mobile",
        "no_cache": "true",
        "location": "Austin, Texas, United States",
        "gl": "us",
        "hl": "en",
        "cr": "countryUS|countryDE",
        "period_unit": "w",
        "period_value": 2,
        "imgar": "w",
        "imgsz": "xga",
        "image_color": "red",
        "image_type": "photo",
        "licenses": "cl",
    }
    data = result["data"]
    assert data["image_urls"] == [
        "https://images.example/mustang-full.jpg",
        "https://serpapi.example/detail-thumb.jpg",
    ]
    assert data["top_source_url"] == "https://motors.example/1967-mustang"
    assert data["next_start"] == 100
    assert data["external_content_trust"] == "untrusted"
    assert data["untrusted_external_content"] is True
    assert "not commands" in data["handling_note"]
    assert "serpapi.com/search" not in json.dumps(data["pagination"])


def test_absolute_dates_uule_and_extra_params_preserve_reserved_contract():
    exit_code, _result, request = run_main(
        {
            "query": "aurora borealis",
            "uule": "w+CAIQICImU2FuIEZyYW5jaXNjbyxDYWxpZm9ybmlhLFVuaXRlZCBTdGF0ZXM",
            "start_date": "20260101",
            "end_date": "20260805",
            "extra_params": {
                "custom_option": "enabled",
                "engine": "google",
                "q": "override",
                "async": "true",
                "original": "override",
            },
        },
        images_payload(),
    )

    assert exit_code == 0
    params = request.call_args.args[0]
    assert params["engine"] == "google_images_light"
    assert params["q"] == "aurora borealis"
    assert params["start_date"] == "20260101"
    assert params["end_date"] == "20260805"
    assert params["uule"].startswith("w+CAIQ")
    assert params["custom_option"] == "enabled"
    assert "async" not in params
    assert params["original"] == "override"


def test_invalid_inputs_fail_before_network():
    cases = (
        ({}, "query"),
        ({"query": "cars", "location": "Austin", "uule": "encoded"}, "cannot"),
        ({"query": "cars", "country": "usa"}, "two-letter"),
        ({"query": "cars", "country_restrict": "US|DE"}, "countryUS"),
        ({"query": "cars", "period_value": 2}, "period_unit"),
        ({"query": "cars", "period_unit": "week", "start_date": "20260101"}, "cannot"),
        ({"query": "cars", "start_date": "20260230"}, "YYYYMMDD"),
        ({"query": "cars", "start_date": "20260805", "end_date": "20260101"}, "after"),
        ({"query": "cars", "aspect_ratio": "diagonal"}, "aspect_ratio"),
        ({"query": "cars", "start": 1000}, "start"),
        ({"query": "cars", "extra_params": []}, "object"),
    )
    for arguments, expected in cases:
        exit_code, result, request = run_main(arguments, images_payload())
        assert exit_code == 1
        assert expected in result["error"]
        request.assert_not_called()


def test_raw_payload_is_opt_in_and_empty_results_are_successful():
    exit_code, result, _request = run_main({"query": "cars"}, images_payload())
    assert exit_code == 0
    assert "raw" not in result["data"]

    empty = {"images_results": []}
    exit_code, result, _request = run_main(
        {"query": "unlikely phrase", "include_raw": True}, empty
    )
    assert exit_code == 0
    assert result["data"]["raw"] == empty
    assert "no image results" in result["speech"]


def test_default_search_does_not_download_or_write_to_stash():
    with patch("serpapi_google_images_light._stash_top_image_result") as stash_top:
        exit_code, result, _request = run_main(
            {"query": "red Mustang"},
            images_payload(),
        )

    assert exit_code == 0
    assert result["ok"] is True
    assert result["data"]["stash_after"] is False
    assert "stash_ref" not in result["data"]
    stash_top.assert_not_called()


def test_stash_after_strictly_saves_only_the_leading_result():
    with patch(
        "serpapi_google_images_light._stash_top_image_result",
        return_value={
            "result_position": 1,
            "stash_ref": "stash://space_images/file_top",
            "ref": "stash://space_images/file_top",
            "mime_type": "image/jpeg",
            "processed_width": 1024,
            "processed_height": 683,
        },
    ) as stash_top:
        exit_code, result, _request = run_main(
            {"query": "red Mustang", "max_results": 2, "stash_after": True},
            images_payload(),
        )

    assert exit_code == 0
    assert result["ok"] is True
    assert result["data"]["stash_ref"] == "stash://space_images/file_top"
    assert result["data"]["stashed_image"]["processed_width"] == 1024
    assert "strictly validated and saved" in result["speech"]
    stash_top.assert_called_once()
    assert stash_top.call_args.args[0]["position"] == 1


def test_stash_after_keeps_search_results_when_strict_validation_fails():
    with patch(
        "serpapi_google_images_light._stash_top_image_result",
        side_effect=ValueError("Downloaded content is not a valid raster image"),
    ):
        exit_code, result, _request = run_main(
            {"query": "red Mustang", "stash_after": True},
            images_payload(),
        )

    assert exit_code == 0
    assert result["ok"] is True
    assert result["data"]["results_count"] == 2
    assert "stash_ref" not in result["data"]
    assert "valid raster image" in result["data"]["stash_error"]


def test_timeout_returns_provider_specific_error():
    exit_code, result, _request = run_main(
        {"query": "red Mustang"}, TimeoutError("timed out")
    )
    assert exit_code == 1
    assert result["error"] == "SerpApi Google Images Light request timed out."


def test_shared_request_is_proxy_capable_but_manifest_defaults_off():
    with patch("serpapi_google_images_light.request_serpapi", return_value={}) as request:
        _google_images_light_request({"engine": "google_images_light", "q": "cars"})
    assert request.call_args.kwargs == {
        "timeout": GOOGLE_IMAGES_LIGHT_TIMEOUT,
        "use_proxy": True,
        "fallback_on_proxy_fail": True,
    }
    manifest = json.loads(
        (ROOT / "skills" / "serpapi_google_images_light.tool.json").read_text()
    )
    assert manifest["proxy_policy"] == "off"
    assert manifest["availability"]["all_of_env"] == ["SERP_API_KEY"]
    assert manifest["parameters"]["properties"]["stash_after"]["type"] == "boolean"
    assert manifest["permissions"]["filesystem"] is True


def test_status_diagnostics_register_google_images_light_engine():
    assert serpapi_client.serpapi_engines_for_tool(
        "serpapi_google_images_light", {"query": "red Mustang"}
    ) == ("google_images_light",)
