"""Selected backend, read-only protocol, truthful results and credential boundaries."""
import json
import sys
from io import BytesIO
from pathlib import Path

import pytest
import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills"))
import bookmark_plus as bp  # noqa: E402
import bookmark_search as tool  # noqa: E402
from tool_availability import (  # noqa: E402
    MALFORMED_MARKER,
    check_availability_block,
    check_tool_availability,
)
from tool_child_environment import (  # noqa: E402
    parse_child_environment_policy,
    restrict_child_environment,
)

TOKEN = "private-bookmark-token"
CONFIG = {"BOOKMARK_REST_URL": "https://bookmarks.test:8443/api/v1", "BOOKMARK_PLUS_TOKEN": TOKEN}
ROW = {"id": 17, "title": "NTFY", "url": "http://192.168.1.50:8080/", "description": "Phone notifications",
       "notes": "Private note", "collection": "Services/Notifications", "tags": ["self-hosted"],
       "added_at": 1600000001, "updated_at": 1791849600}


class Response:
    def __init__(self, data=None, *, status=200, raw=None, content_type="application/json"):
        self.status_code = status
        self.raw = json.dumps(data).encode() if raw is None else raw
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def iter_content(self, _):
        yield self.raw


@pytest.fixture
def service(monkeypatch):
    config = dict(CONFIG)
    calls = []
    responses = []

    class Session:
        def __init__(self):
            self.headers = {}
            self.trust_env = True
            self.verify = True

        def request(self, method, url, **kwargs):
            assert not self.trust_env
            assert self.verify is not False
            assert self.headers["Authorization"] == "Bearer " + TOKEN
            assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
            calls.append((method, url, kwargs))
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        def close(self):
            pass

    monkeypatch.setattr(bp.requests, "Session", Session)
    monkeypatch.setattr(bp, "get_config_value", lambda key, default=None: config.get(key, default))
    monkeypatch.setattr(bp, "get_active_config_mode", lambda: "local")
    return config, calls, responses


def search_response(**changes):
    return {"items": [dict(ROW)], "total": 200, "mode": "hybrid", "status": "candidates",
            "total_kind": "retrieval_candidates", "offset": 0, "diagnostics": {}, **changes}


def test_search_keeps_candidate_semantics_and_never_fetches_bookmark(service):
    _, calls, responses = service
    responses.append(Response(search_response(warning="Decision model unavailable", diagnostics={
        "candidate_count": 200, "judged_count": 3, "rerank_truncated": True,
        "corrections": [{"from": "nfty", "to": "ntfy"}]})))
    result = bp.run_bookmark_plus({"query": "nfty", "collection": "", "tag": "self-hosted", "favorite": False})
    data = result["data"]
    assert result["ok"] and data["total"] == data["matched_count"] == 200
    assert data["total_kind"] == "retrieval_candidates" and data["warning"]
    assert data["results"][0]["score"] is None and data["results"][0]["url"] == ROW["url"]
    assert data["diagnostics"]["rerank_truncated"] and data["diagnostics"]["corrections"][0]["to"] == "ntfy"
    assert calls[0][0:2] == ("GET", CONFIG["BOOKMARK_REST_URL"] + "/bookmarks")
    assert calls[0][2]["params"]["collection"] == "" and calls[0][2]["params"]["favorite"] == "false"
    assert "not all relevance-judged" in data["count_label"]
    assert data["results"][0]["metadata_truncated"]  # Search omits private notes; get reads them.


def test_ranked_empty_is_not_a_library_wide_absence_claim(service):
    _, _, responses = service
    responses.append(Response(search_response(items=[], total=0, mode="ranked", status="no_confident_matches",
        total_kind="judged_matches", diagnostics={"judged_count": 64, "candidate_count": 200, "rerank_truncated": True})))
    data = bp.run_bookmark_plus({"query": "irrelevant", "search_mode": "ranked"})["data"]
    assert data["status"] == "no_confident_matches" and data["total"] == 0
    assert "only judged candidates" in data["results_for_llm"]


@pytest.mark.parametrize("args", [
    {"domains": ["example.org"]}, {"folders": ["Services"]}, {"file_path": "elsewhere.html"},
    {"query_mode": "all"}, {"tags": ["one", "two"]}, {"sort_by": "domain"},
    {"search_mode": "invented"}, {"unread": "false"}, {"query": "é" * 501},
])
def test_unsupported_filters_fail_before_network(service, args):
    _, calls, _ = service
    with pytest.raises(bp.BookmarkPlusError):
        bp.run_bookmark_plus(args)
    assert not calls


@pytest.mark.parametrize("response", [
    Response(status=302), Response(status=401), Response(raw=b"not JSON"),
    requests.exceptions.SSLError(TOKEN), requests.exceptions.ConnectionError(TOKEN),
    requests.exceptions.Timeout(TOKEN),
])
def test_failures_do_not_leak_credentials_or_follow_redirects(service, response):
    _, calls, responses = service
    responses.append(response)
    with pytest.raises(bp.BookmarkPlusError) as error:
        bp.run_bookmark_plus({"query": "ntfy"})
    assert TOKEN not in str(error.value)
    assert len(calls) == 1


def test_metadata_redacted_and_external_icons_ignored(service):
    _, _, responses = service
    row = {**ROW, "title": TOKEN, "description": "x" * 5000,
           "icon": {"url": "https://attacker.test/icon"}}
    responses.append(Response(search_response(items=[row], warning=TOKEN)))
    data = bp.run_bookmark_plus({})["data"]
    assert TOKEN not in json.dumps(data)
    assert "icon_url" not in data["results"][0]
    assert data["results"][0]["metadata_truncated"]
    assert len(data["results"][0]["description"]) == 1000


def test_get_exact_id_and_authenticated_icon_reference(service):
    _, calls, responses = service
    responses.append(Response({**ROW, "icon": {"url": "/api/v1/bookmarks/17/icon"}}))
    data = bp.run_bookmark_plus({"action": "get", "bookmark_id": 17})["data"]
    assert data["bookmark"]["id"] == 17 and data["bookmark"]["notes"] == "Private note"
    assert data["bookmark"]["icon_url"] == "/api/bookmarks/plus/17/icon?mode=local"
    assert calls[0][1].endswith("/bookmarks/17")
    responses.append(Response({**ROW, "id": 18}))
    with pytest.raises(bp.BookmarkPlusError, match="different bookmark ID"):
        bp.run_bookmark_plus({"action": "get", "bookmark_id": 17})


def test_rank_accepts_only_returned_ids_and_finite_scores(service):
    _, calls, responses = service
    responses.append(Response({"model": "tev1", "results": [{"bookmark": ROW, "relevance": .87}]}))
    data = bp.run_bookmark_plus({"action": "rank", "query": "phone notifications", "bookmark_ids": [17]})["data"]
    assert calls[0][0] == "POST" and calls[0][1].endswith("/decisions")
    assert data["results"][0]["score"] == .87
    responses.append(Response({"model": "tev1", "results": [{"bookmark": ROW, "relevance": float("nan")}]}))
    with pytest.raises(bp.BookmarkPlusError, match="invalid relevance"):
        bp.run_bookmark_plus({"action": "rank", "query": "phone", "bookmark_ids": [17]})
    with pytest.raises(bp.BookmarkPlusError):
        bp.run_bookmark_plus({"action": "rank", "query": "phone", "bookmark_ids": [True]})


def test_response_and_icon_size_limits(service, monkeypatch):
    _, _, responses = service
    monkeypatch.setattr(bp, "MAX_RESPONSE_BYTES", 32)
    responses.append(Response(raw=b"x" * 33))
    with bp.BookmarkPlusClient() as client:
        with pytest.raises(bp.BookmarkPlusError, match="size limit"):
            client.search({})
    image = BytesIO()
    Image.new("RGB", (32, 32), "blue").save(image, format="PNG")
    png = image.getvalue()
    responses.append(Response(raw=png, content_type="image/png"))
    with bp.BookmarkPlusClient(icon_request=True) as client:
        assert client.icon(17) == png
    for raw, mime in ((b"<html>" + TOKEN.encode(), "text/html"), (png, "image/svg+xml"), (png[:33], "image/png")):
        responses.append(Response(raw=raw, content_type=mime))
        with bp.BookmarkPlusClient(icon_request=True) as client:
            with pytest.raises(bp.BookmarkPlusError, match="invalid icon"):
                client.icon(17)


def test_legacy_token_ca_and_selected_backend_validation(service, tmp_path):
    config, calls, _ = service
    config["BOOKMARK_PLUS_TOKEN"] = "   "
    config["BOOKMARK_PLUS_tOKEN"] = TOKEN
    ca = tmp_path / "ca.crt"
    ca.write_text("public certificate")
    config["BOOKMARK_PLUS_CA_FILE"] = str(ca)
    with bp.BookmarkPlusClient() as client:
        assert client.session.verify == str(ca)
    config["BOOKMARK_PLUS_CA_FILE"] = str(ca) + "missing"
    with pytest.raises(bp.BookmarkPlusError, match="CA certificate"):
        bp.BookmarkPlusClient()
    config["BOOKMARK_BACKEND"] = "typo"
    with pytest.raises(bp.BookmarkPlusError):
        bp.selected_backend()
    assert not calls


def test_selected_provider_gate_preserves_default_multi_provider_rule(monkeypatch):
    values = {}
    monkeypatch.setattr("tool_availability.get_config_value", lambda k, d=None: values.get(k, d))
    manifest = json.loads((ROOT / "skills/bookmark_search.tool.json").read_text())
    assert check_tool_availability(manifest).available
    values["BOOKMARK_BACKEND"] = "bookmark_plus"
    assert not check_tool_availability(manifest).available
    values.update(BOOKMARK_REST_URL="https://bookmarks.test/api/v1", BOOKMARK_PLUS_tOKEN=TOKEN)
    assert check_tool_availability(manifest).available
    values["BOOKMARK_BACKEND"] = "unknown"
    assert not check_tool_availability(manifest).available
    legacy = {"provider_setting": "CHOICE", "provider_requirements": {"a": {"all_of_env": ["A"]}, "b": {"all_of_env": ["B"]}}}
    values.update(CHOICE="b", A="configured")
    assert check_availability_block(legacy).available
    for block in ({"require_selected_provider": True}, {"require_selected_provider": "true"},
                  {"require_selected_provider": True, "provider_setting": "CHOICE", "provider_requirements": {"a": {"typo": []}}}):
        assert check_availability_block(block).missing == [MALFORMED_MARKER]


def test_child_environment_retains_only_selected_bookmark_settings():
    manifest = json.loads((ROOT / "skills/bookmark_search.tool.json").read_text())
    names = parse_child_environment_policy(manifest["child_environment"], manifest["availability"])
    env = restrict_child_environment({"BOOKMARK_PLUS_tOKEN": TOKEN, "BOOKMARK_PLUS_CA_FILE": "ca.crt",
        "BOOKMARK_BACKEND": "bookmark_plus", "JARVIS_MODE": "local", "OPENAI_API_KEY": "unrelated",
        "HTTPS_PROXY": "http://proxy.test", "GOOGLE_WORKSPACE_MCP_TOKEN": "unrelated"}, names, home="/tmp/test-home", proxy_policy="off")
    assert env["BOOKMARK_PLUS_tOKEN"] == TOKEN and env["JARVIS_MODE"] == "local"
    assert "OPENAI_API_KEY" not in env and "GOOGLE_WORKSPACE_MCP_TOKEN" not in env and "HTTPS_PROXY" not in env


def test_backend_selection_is_mode_scoped_and_executor_waits_for_adapter(monkeypatch):
    import config_loader

    from orchestrator.executor import ToolExecutor

    monkeypatch.setattr(config_loader, "_load_mode_config", lambda mode: (
        {"BOOKMARK_BACKEND": "bookmark_plus", "BOOKMARK_REST_URL": CONFIG["BOOKMARK_REST_URL"],
         "BOOKMARK_PLUS_TOKEN": TOKEN, "BOOKMARK_PLUS_TIMEOUT_SECONDS": "300"}
        if mode == "cloud" else {"BOOKMARK_BACKEND": "builtin"}
    ))
    manifest = json.loads((ROOT / "skills/bookmark_search.tool.json").read_text())
    with config_loader.config_scope("cloud"):
        assert bp.selected_backend() == "bookmark_plus" and check_tool_availability(manifest).available
        executor = ToolExecutor.__new__(ToolExecutor)
        executor.mode = "cloud"
        assert executor._get_subprocess_timeout("bookmark_search") == 330
    with config_loader.config_scope("local"):
        assert bp.selected_backend() == "builtin" and check_tool_availability(manifest).available
        executor = ToolExecutor.__new__(ToolExecutor)
        executor.mode = "local"
        assert executor._get_subprocess_timeout("bookmark_search") == 75


def test_facade_builtin_still_searches_custom_html_and_plus_never_opens_it(monkeypatch, tmp_path, capsys):
    path = tmp_path / "bookmarks.html"
    path.write_text('<DL><DT><A HREF="http://192.168.1.50">NTFY phone notifications</A></DL>')
    monkeypatch.setattr(tool, "load_config", lambda: None)
    monkeypatch.setattr(tool, "get_config_value", lambda k, default=None: default)
    monkeypatch.setattr(sys, "argv", ["bookmark_search", json.dumps({"file_path": str(path), "query": "ntfy"})])
    tool.main()
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["backend"] == "builtin" and data["matched_count"] == 1 and data["total_kind"] == "lexical_matches"
    monkeypatch.setattr(tool, "get_config_value", lambda k, default=None: "bookmark_plus")
    monkeypatch.setattr(tool, "resolve_bookmark_path", lambda *_: pytest.fail("Builtin file opened for external backend"))
    monkeypatch.setattr(bp, "run_bookmark_plus", lambda args: {"ok": True, "data": {"backend": "bookmark_plus"}})
    tool.main()
    assert json.loads(capsys.readouterr().out)["data"]["backend"] == "bookmark_plus"
