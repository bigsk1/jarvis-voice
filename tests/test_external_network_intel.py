#!/usr/bin/env python3
"""Regression coverage for passive external network intelligence."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))

import external_network_intel as network_intel  # noqa: E402


class FakeResponse:
    def __init__(self, payload, *, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload


def test_abuseipdb_uses_https_header_auth_and_omits_report_comments():
    response = FakeResponse(
        {
            "data": {
                "ipAddress": "35.190.88.7",
                "abuseConfidenceScore": 33,
                "totalReports": 48,
                "numDistinctUsers": 12,
                "lastReportedAt": "2026-08-01T00:00:00Z",
                "isp": "Google LLC",
                "domain": "google.com",
                "hostnames": ["sessions.bugsnag.com"],
                "reports": [
                    {
                        "reportedAt": "2026-08-01T00:00:00Z",
                        "categories": [14],
                        "reporterCountryCode": "US",
                        "comment": "RAW_REPORT_COMMENT_SENTINEL",
                    }
                ],
            }
        },
        headers={"X-RateLimit-Remaining": "999"},
    )

    with (
        patch.object(network_intel, "get_config_value", return_value="test-secret-key"),
        patch.object(network_intel, "http_request", return_value=response) as request,
    ):
        result = network_intel.lookup_abuseipdb(
            "35.190.88.7",
            max_age_days=90,
            include_reports=True,
        )

    method, url = request.call_args.args
    kwargs = request.call_args.kwargs
    assert method == "GET"
    assert url == "https://api.abuseipdb.com/api/v2/check"
    assert kwargs["headers"]["Key"] == "test-secret-key"
    assert "key" not in {str(key).lower() for key in kwargs["params"]}
    assert kwargs["use_proxy"] is True
    assert kwargs["fallback_on_proxy_fail"] is True
    assert kwargs["allow_redirects"] is False
    assert result["abuse_confidence_score"] == 33
    assert result["rate_limit"]["remaining"] == "999"
    encoded = json.dumps(result)
    assert "test-secret-key" not in encoded
    assert "RAW_REPORT_COMMENT_SENTINEL" not in encoded
    assert result["reports"] == [
        {
            "reported_at": "2026-08-01T00:00:00Z",
            "categories": [14],
            "reporter_country_code": "US",
        }
    ]


def test_keyless_provider_request_supplies_mutable_empty_headers():
    response = FakeResponse({"data": {"prefix": "35.190.0.0/16", "asns": [396982]}})
    with patch.object(network_intel, "http_request", return_value=response) as request:
        payload, _headers = network_intel._request_json(
            network_intel.RIPESTAT_NETWORK_INFO,
            params={"resource": "35.190.88.7"},
        )

    assert payload["data"]["prefix"] == "35.190.0.0/16"
    assert request.call_args.kwargs["headers"] == {}


def test_insecure_provider_redirect_is_rejected_before_following_it():
    response = FakeResponse(
        {},
        status_code=302,
        headers={"Location": "http://insecure.example.test/lookup"},
    )
    with patch.object(network_intel, "http_request", return_value=response) as request:
        with pytest.raises(
            network_intel.ExternalNetworkIntelError,
            match="insecure redirect",
        ):
            network_intel._request_json(network_intel.ARIN_RDAP_IP.format(target="1.1.1.1"))

    request.assert_called_once()


def test_authenticated_abuseipdb_redirect_to_another_https_origin_is_refused():
    response = FakeResponse(
        {},
        status_code=302,
        headers={"Location": "https://redirect.example.test/collect"},
    )
    with patch.object(network_intel, "http_request", return_value=response) as request:
        with pytest.raises(
            network_intel.ExternalNetworkIntelError,
            match="cross-origin redirect",
        ):
            network_intel._request_json(
                network_intel.ABUSEIPDB_CHECK,
                params={"ipAddress": "35.190.88.7", "maxAgeInDays": 90},
                headers={"Accept": "application/json", "Key": "test-secret-key"},
            )

    request.assert_called_once()
    assert request.call_args.args == ("GET", network_intel.ABUSEIPDB_CHECK)
    assert request.call_args.kwargs["headers"]["Key"] == "test-secret-key"
    assert request.call_args.kwargs["allow_redirects"] is False


def test_https_registry_redirect_is_followed_without_forwarding_query_params():
    redirect = FakeResponse(
        {},
        status_code=302,
        headers={"Location": "https://rdap.apnic.net/ip/1.1.1.1"},
    )
    result = FakeResponse({"name": "APNIC-LABS"})
    with patch.object(
        network_intel,
        "http_request",
        side_effect=[redirect, result],
    ) as request:
        payload, _headers = network_intel._request_json(
            network_intel.ARIN_RDAP_IP.format(target="1.1.1.1")
        )

    assert payload["name"] == "APNIC-LABS"
    assert request.call_count == 2
    assert request.call_args_list[1].args[1] == "https://rdap.apnic.net/ip/1.1.1.1"
    assert request.call_args_list[1].kwargs["params"] is None


def test_missing_abuseipdb_key_keeps_keyless_lookup_available():
    with (
        patch.object(network_intel, "get_config_value", return_value=""),
        patch.object(network_intel, "http_request") as request,
    ):
        result = network_intel.lookup_abuseipdb(
            "35.190.88.7",
            max_age_days=90,
            include_reports=False,
        )

    request.assert_not_called()
    assert result["status"] == "not_configured"
    assert result["configured"] is False


@pytest.mark.parametrize(
    "target",
    ["127.0.0.1", "10.0.0.8", "192.168.1.1", "169.254.10.20", "::1"],
)
def test_non_global_ip_is_never_sent_to_public_providers(target):
    with patch.object(
        network_intel,
        "_request_json",
        side_effect=AssertionError("public provider must not be called"),
    ):
        result = network_intel.run_lookup({"target": target})

    assert result["classification"]["is_global"] is False
    assert "external_lookup_skipped" in result
    assert result["sources"] == []


@pytest.mark.parametrize(
    "target",
    ["printer.local", "host.internal", "example.test", "service.onion", "not-a-fqdn"],
)
def test_private_or_non_fqdn_domains_are_rejected(target):
    with pytest.raises(network_intel.ExternalNetworkIntelError):
        network_intel.classify_target(target)


def test_full_ip_lookup_builds_separate_facts_and_cautious_event_summary():
    registration = {
        "name": "GOOGLE-CLOUD",
        "status": ["active"],
        "entities": [{"roles": ["registrant"], "names": ["Google LLC"]}],
    }
    with (
        patch.object(network_intel, "lookup_ip_registration", return_value=registration),
        patch.object(
            network_intel,
            "lookup_network_routing",
            return_value={"prefix": "35.190.0.0/16", "asns": ["396982"]},
        ),
        patch.object(
            network_intel,
            "lookup_published_provider_range",
            return_value={
                "status": "matched",
                "provider": "Google Cloud",
                "prefix": "35.190.64.0/19",
            },
        ),
        patch.object(
            network_intel,
            "lookup_dns",
            return_value={"ptr": ["7.88.190.35.bc.googleusercontent.com"]},
        ),
        patch.object(
            network_intel,
            "lookup_abuseipdb",
            return_value={
                "status": "ok",
                "abuse_confidence_score": 33,
                "total_reports": 48,
            },
        ),
        patch.object(
            network_intel,
            "lookup_shodan_internetdb",
            return_value={
                "status": "ok",
                "hostnames": ["sessions.bugsnag.com"],
                "ports": [80, 443],
            },
        ),
    ):
        result = network_intel.run_lookup(
            {
                "target": "35.190.88.7",
                "direction": "outbound",
                "destination_port": 443,
            }
        )

    assert result["summary"]["owner"] == "Google LLC"
    assert result["summary"]["announcing_asns"] == ["396982"]
    assert result["summary"]["service_candidates"] == [
        "7.88.190.35.bc.googleusercontent.com",
        "sessions.bugsnag.com",
    ]
    assert result["summary"]["abuse_confidence_score"] == 33
    assert result["event_context"] == {"direction": "outbound", "destination_port": 443}
    assert any(
        "cannot identify the initiating local process" in note
        for note in result["confidence_notes"]
    )
    assert result["result_status"] == "complete"
    assert result["external_content_trust"] == "untrusted"


def test_manifest_declares_passive_proxy_aware_safe_tool():
    manifest = json.loads(
        (ROOT / "skills" / "external_network_intel.tool.json").read_text(encoding="utf-8")
    )

    assert manifest["enabled"] is True
    assert manifest["proxy_policy"] == "prefer"
    assert manifest["permissions"] == {
        "dangerous": False,
        "bash": False,
        "network": True,
        "filesystem": False,
        "auto_approve": True,
    }
    assert "port scan" in manifest["description"]
    assert manifest["parameters"]["required"] == ["target"]
