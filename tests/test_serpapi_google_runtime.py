"""Google search budgets and local archive failures respect runtime boundaries."""

import importlib

import pytest
import serpapi_client


@pytest.mark.parametrize("mode,default_timeout", [("cloud", 60), ("local", 75)])
def test_google_search_leaves_room_for_http_and_archive_reads_use_normal_budget(mode, default_timeout):
    executor_class = importlib.import_module("orchestrator.executor").ToolExecutor
    executor = object.__new__(executor_class)
    executor.mode = mode

    assert executor._get_subprocess_timeout("serpapi_google_search") == 120
    assert executor._get_subprocess_timeout("serpapi_google_search", {"action": "search"}) == 120
    assert executor._get_subprocess_timeout("serpapi_google_search", {"action": "read_result"}) == default_timeout


def test_google_search_failure_matches_google_incident_without_retargeting_engine(monkeypatch):
    monkeypatch.setattr(serpapi_client, "fetch_serpapi_unresolved_incidents", lambda: [{
        "name": "[Google Search API] Performance Degradation", "status": "investigating",
        "impact": "major", "incident_updates": [{"body": "Google Search latency is elevated."}],
    }])

    assert serpapi_client.serpapi_engines_for_tool("serpapi_google_search", {"engine": "amazon"}) == ("google",)
    diagnosed = serpapi_client.diagnose_serpapi_tool_failure(
        "serpapi_google_search", {"action": "search", "query": "reference sources"}, "Timeout",
    )
    assert diagnosed is not None
    assert diagnosed["data"]["serpapi_incident"]["engine"] == "google"
    assert "Google Search" in diagnosed["speech"]


@pytest.mark.parametrize("force", [False, True])
def test_local_google_archive_errors_never_query_provider_status(monkeypatch, force):
    def unexpected_network():
        pytest.fail("A retained JSON read must not make an outbound status-page request")

    monkeypatch.setattr(serpapi_client, "fetch_serpapi_unresolved_incidents", unexpected_network)
    arguments = {"action": "read_result", "raw_ref": "stash://space_example/google_response"}
    assert serpapi_client.serpapi_engines_for_tool("serpapi_google_search", arguments) == ()
    assert serpapi_client.diagnose_serpapi_tool_failure(
        "serpapi_google_search", arguments, "Tool timed out", force=force,
    ) is None
