"""The Apps Script service reports provider evidence under per-call budgets."""

import asyncio
import importlib.util
import sys
import time
from contextvars import ContextVar
from http.client import BadStatusLine, ResponseNotReady
from pathlib import Path
from threading import Event
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
META_KEY = "jarvis/background_execution"


@pytest.fixture
def service(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "google_background_service_fixture", ROOT / "google-workspace/entrypoint.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    request_context = ContextVar("google_background_request_fixture", default=None)
    raw_transports = []
    requests = []
    auth_calls = []
    observed_budgets = []

    class AuthSession:
        def request(self, method, url, data=None, headers=None, timeout=None, **kwargs):
            auth_calls.append({"timeout": timeout, "kwargs": kwargs})
            return SimpleNamespace(status_code=500, headers={}, close=lambda: None,
                                   content=b'{"error":"temporarily_unavailable"}')

        def mount(self, *args):
            pass

        def close(self):
            pass

    class AuthRequest:
        def __init__(self, session=None):
            self.session = session or AuthSession()

        def __call__(self, url, method="GET", body=None, headers=None, timeout=120, **kwargs):
            response = self.session.request(method, url, data=body, headers=headers,
                                            timeout=timeout, **kwargs)
            return SimpleNamespace(status=response.status_code, headers=response.headers,
                                   data=response.content)

    class AuthResponse:
        def __init__(self, response):
            self.status, self.headers, self.data = response.status_code, response.headers, response.content

    def token_request(request, token_uri, body, access_token=None, use_json=False,
                      can_retry=True, headers=None, **kwargs):
        for _ in range(3 if can_retry else 1):
            request(token_uri, method="POST", body=b"dummy-token-request", **kwargs)
        return False, {"error": "temporarily_unavailable"}, True

    class Http:
        def __init__(self, timeout):
            self.timeout = timeout
            self.closed = False
            raw_transports.append(self)

        def close(self):
            self.closed = True

    class AuthorizedHttp:
        def __init__(self, credentials, http, max_refresh_attempts=2):
            self.credentials, self.http = credentials, http
            self.max_refresh_attempts = max_refresh_attempts

    class HttpError(Exception):
        def __init__(self, status):
            self.resp = SimpleNamespace(status=status)

    class HttpRequest:
        def __init__(self, outcome, method_id="script.scripts.run"):
            self.http = AuthorizedHttp("fixture-credentials", Http(60))
            self.methodId = method_id
            self.outcome = outcome

        def execute(self, http=None, num_retries=0):
            requests.append((self, http or self.http, num_retries))
            budget = module._script_execution_budget.get()
            if budget is not None:
                observed_budgets.append((budget.job_id, budget.background, budget.deadline))
            if isinstance(self.outcome, Exception):
                raise self.outcome
            if callable(self.outcome):
                return self.outcome()
            return self.outcome

    class ToolResult:
        def __init__(self, content=None, *, meta=None, is_error=False):
            self.content, self.meta, self.is_error = content, meta, is_error

    class Secure:
        async def call_tool(self, name, arguments, *args, **kwargs):
            if arguments.get("middleware_reentry") and kwargs.get("run_middleware", True):
                nested_name = arguments.get("nested_name", name)
                context_token = None
                if arguments.get("nested_job") or arguments.get("nested_deadline") or arguments.get("drop_context"):
                    context = request_context.get()
                    metadata = context.meta if context is not None else {}
                    changed = {**metadata.get(META_KEY, {
                        "version": 1, "job_id": "nested-job", "deadline_unix": 1300,
                    })}
                    if arguments.get("nested_job"):
                        changed["job_id"] = arguments["nested_job"]
                    if arguments.get("nested_deadline"):
                        changed["deadline_unix"] = arguments["nested_deadline"]
                    context_token = request_context.set(None if arguments.get("drop_context") else
                                                        SimpleNamespace(meta={META_KEY: changed}))
                try:
                    result = await self.call_tool(nested_name, arguments, *args,
                                                  run_middleware=arguments.get("nested_middleware_flag", False))
                    if arguments.get("repeat_reentry"):
                        result = await self.call_tool(nested_name, arguments, *args, run_middleware=False)
                    return result
                finally:
                    if context_token is not None:
                        request_context.reset(context_token)
            if arguments.get("refresh_credentials"):
                await asyncio.to_thread(token_module._token_endpoint_request_no_throw,
                                        AuthRequest(), "https://fixture.invalid/token", {})
                return ToolResult("Credentials unavailable", is_error=True)
            if arguments.get("raise_error"):
                raise RuntimeError("Google API rejected this request: HTTP 403 permission denied")
            if arguments.get("no_run"):
                return ToolResult("Execution failed: no deployment")
            if arguments.get("preflight"):
                await asyncio.to_thread(HttpRequest({}, "script.projects.deployments.list").execute)
            request = HttpRequest(arguments.get("outcome", {"response": {"result": "done"}}))
            try:
                response = await asyncio.to_thread(request.execute)
            except Exception as exc:
                return ToolResult(f"Upstream stringified {type(exc).__name__}")
            return ToolResult("Execution failed" if "error" in response else "Execution successful")

    token_module = SimpleNamespace(_token_endpoint_request_no_throw=token_request)
    modules = {
        "googleapiclient": ModuleType("googleapiclient"),
        "googleapiclient.http": SimpleNamespace(HttpRequest=HttpRequest),
        "googleapiclient.errors": SimpleNamespace(HttpError=HttpError),
        "google_auth_httplib2": SimpleNamespace(AuthorizedHttp=AuthorizedHttp),
        "httplib2": SimpleNamespace(Http=Http),
        "fastmcp": ModuleType("fastmcp"),
        "fastmcp.server": ModuleType("fastmcp.server"),
        "fastmcp.server.dependencies": SimpleNamespace(fastmcp_request_ctx=request_context),
        "fastmcp.tools": ModuleType("fastmcp.tools"),
        "fastmcp.tools.base": SimpleNamespace(ToolResult=ToolResult),
        "google": ModuleType("google"),
        "google.auth": ModuleType("google.auth"),
        "google.auth.transport": ModuleType("google.auth.transport"),
        "google.auth.transport.requests": SimpleNamespace(Request=AuthRequest, _Response=AuthResponse),
        "google.oauth2": SimpleNamespace(_client=token_module),
        "google.oauth2._client": token_module,
    }
    for name, stub in modules.items():
        monkeypatch.setitem(sys.modules, name, stub)
    module.configure_background_execution(Secure, auth_session_factory=lambda _source: AuthSession())
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: 1000,
                                                       monotonic=lambda: 100))
    return SimpleNamespace(module=module, Secure=Secure, HttpRequest=HttpRequest,
                           HttpError=HttpError, context=request_context,
                           requests=requests, transports=raw_transports, auth_calls=auth_calls,
                           observed_budgets=observed_budgets)


async def call(service, arguments=None, *, deadline=1300, job_id="job-fixture", name="run_script_function"):
    meta = {META_KEY: {"version": 1, "job_id": job_id, "deadline_unix": deadline}}
    token = service.context.set(SimpleNamespace(meta=meta))
    try:
        return await service.Secure().call_tool(name, arguments or {})
    finally:
        service.context.reset(token)


@pytest.mark.parametrize("provider_error", [False, True])
def test_provider_reply_settles_success_and_script_error(service, provider_error):
    outcome = {"error": {"message": "script threw"}} if provider_error else {"response": {"result": "done"}}
    result = asyncio.run(call(service, {"outcome": outcome, "preflight": True}))
    assert result.meta[META_KEY] == {"version": 1, "job_id": "job-fixture", "completion": "completed"}
    assert result.is_error is provider_error
    assert len(service.requests) == 2
    for request, http, retries in service.requests:
        assert http is not request.http
        assert http.http.timeout == 300
        assert http.max_refresh_attempts == 0
        assert retries == 0
        assert http.http.closed
    assert all(transport.timeout == 60 for transport in service.transports[::2])


@pytest.mark.parametrize("outcome,completion,error", [
    ({"response": {"result": {"phase": "complete", "invocationCount": 1}}}, "completed", False),
    ({"error": {"message": "The script threw"}}, "completed", True),
    (TimeoutError("Lost response"), "unknown", True),
])
def test_fastmcp_middleware_reentry_preserves_the_provider_execution_budget(service, outcome, completion, error):
    # FastMCP 4.1.4 calls self.call_tool(..., run_middleware=False) from its
    # outer middleware dispatch. Both entries belong to the same invocation.
    result = asyncio.run(call(service, {"middleware_reentry": True, "outcome": outcome}))
    assert result.meta[META_KEY]["completion"] == completion
    assert result.is_error is error
    assert len(service.requests) == 1


@pytest.mark.parametrize("change", [
    {"nested_job": "other-job"}, {"nested_deadline": 1400}, {"nested_name": "create_script_project"},
    {"nested_middleware_flag": True}, {"drop_context": True},
])
def test_nested_calls_cannot_borrow_or_change_the_middleware_execution_authority(service, change):
    result = asyncio.run(call(service, {"middleware_reentry": True, **change}))
    assert result.is_error and result.meta[META_KEY]["completion"] == "rejected"
    assert service.requests == []


def test_middleware_cannot_repeat_the_same_background_execution(service):
    result = asyncio.run(call(service, {"middleware_reentry": True, "repeat_reentry": True}))
    assert result.is_error and result.meta[META_KEY]["completion"] == "completed"
    assert len(service.requests) == 1


def test_lost_google_response_stays_unknown_even_if_upstream_returns_text(service):
    result = asyncio.run(call(service, {"outcome": TimeoutError("response lost")}))
    assert result.is_error
    assert result.meta[META_KEY]["completion"] == "unknown"
    assert len(service.requests) == 1


@pytest.mark.parametrize("status,completion", [(400, "rejected"), (401, "rejected"),
                                               (403, "rejected"), (404, "rejected"),
                                               (429, "rejected"), (500, "unknown")])
def test_only_positive_google_rejections_release_an_execution(service, status, completion):
    result = asyncio.run(call(service, {"outcome": service.HttpError(status)}))
    assert result.is_error and result.meta[META_KEY]["completion"] == completion
    assert len(service.requests) == 1


def test_missing_deployment_is_known_not_submitted(service):
    result = asyncio.run(call(service, {"no_run": True}))
    assert result.is_error and result.meta[META_KEY]["completion"] == "rejected"
    assert service.requests == []


def test_upstream_error_details_are_retained_without_parsing_them_as_completion(service):
    result = asyncio.run(call(service, {"raise_error": True}))
    assert result.is_error and result.meta[META_KEY]["completion"] == "rejected"
    assert "HTTP 403 permission denied" in result.content


def test_authentication_preflight_uses_remaining_budget_without_token_retries(service):
    result = asyncio.run(call(service, {"refresh_credentials": True}, deadline=1005))
    assert result.is_error and result.meta[META_KEY]["completion"] == "rejected"
    assert len(service.auth_calls) == 1
    timeout = service.auth_calls[0]["timeout"]
    assert all(part <= 5 for part in (timeout if isinstance(timeout, tuple) else (timeout,)))
    assert service.requests == []


def test_foreground_authentication_keeps_existing_default_timeout_and_retry_policy(service):
    result = asyncio.run(service.Secure().call_tool("list_gmail_labels", {"refresh_credentials": True}))
    assert result.is_error and result.meta is None
    assert len(service.auth_calls) == 3
    assert all(call["timeout"] == 120 for call in service.auth_calls)


def test_concurrent_authentication_keeps_scoped_and_foreground_retry_budgets_separate(service):
    async def run():
        return await asyncio.gather(
            call(service, {"refresh_credentials": True}, deadline=1005),
            service.Secure().call_tool("list_gmail_labels", {"refresh_credentials": True}),
        )

    background, foreground = asyncio.run(run())
    assert background.meta[META_KEY]["completion"] == "rejected"
    assert foreground.meta is None
    assert len(service.auth_calls) == 4
    assert sum(item["timeout"] == 120 for item in service.auth_calls) == 3
    bounded = [item["timeout"] for item in service.auth_calls if item["timeout"] != 120]
    assert len(bounded) == 1 and all(part <= 5 for part in bounded[0])


def test_ordinary_foreground_transport_and_result_are_unchanged(service):
    result = asyncio.run(service.Secure().call_tool("get_doc_content", {}))
    assert result.meta is None and not result.is_error
    request, http, retries = service.requests[0]
    assert http is request.http
    assert http.http.timeout == 60
    assert not http.http.closed


@pytest.mark.parametrize("deadline", [999, 1000, float("nan"), float("inf"), True, "1300"])
def test_bad_or_expired_budget_is_rejected_before_google_request(service, deadline):
    result = asyncio.run(call(service, deadline=deadline))
    assert result.is_error
    assert result.meta[META_KEY]["completion"] == "rejected"
    assert service.requests == []


def test_budget_cannot_extend_an_unreviewed_tool(service):
    result = asyncio.run(call(service, name="create_script_project"))
    assert result.is_error and result.meta[META_KEY]["completion"] == "rejected"
    assert service.requests == []


def test_budget_context_is_reset_after_call(service):
    asyncio.run(call(service))
    service.requests.clear()
    asyncio.run(service.Secure().call_tool("get_doc_content", {}))
    request, http, _ = service.requests[0]
    assert http is request.http and http.http.timeout == 60


def test_foreground_script_uses_390_second_owned_transport_without_background_metadata(service):
    result = asyncio.run(service.Secure().call_tool("run_script_function", {}))
    assert not result.is_error and result.meta is None
    request, http, retries = service.requests[0]
    assert http is not request.http
    assert http.http.timeout == 390
    assert http.http.closed and retries == 0
    assert service.observed_budgets == [(None, False, 490)]
    assert service.module._script_execution_budget.get() is None


def test_foreground_script_authentication_uses_its_390_second_scope(service):
    result = asyncio.run(service.Secure().call_tool("run_script_function", {"refresh_credentials": True}))
    assert result.is_error and result.meta is None
    assert len(service.auth_calls) == 1
    assert service.auth_calls[0]["timeout"] == (390, 390)
    assert service.requests == []


@pytest.mark.parametrize("outcome,error", [
    ({"response": {"result": "finished"}}, False),
    ({"error": {"message": "The script threw"}}, True),
    (TimeoutError("Response was lost"), True),
])
def test_foreground_script_middleware_reentry_keeps_provider_status_without_job_metadata(service, outcome, error):
    result = asyncio.run(service.Secure().call_tool("run_script_function", {
        "middleware_reentry": True, "outcome": outcome,
    }))
    assert result.meta is None and result.is_error is error
    assert len(service.requests) == 1
    assert service.requests[0][1].http.timeout == 390


def test_concurrent_foreground_script_background_script_and_other_google_tool_are_isolated(service):
    async def run():
        return await asyncio.gather(
            call(service, deadline=1120),
            service.Secure().call_tool("run_script_function", {"middleware_reentry": True}),
            service.Secure().call_tool("get_doc_content", {}),
        )

    background, foreground, ordinary = asyncio.run(run())
    assert background.meta[META_KEY]["completion"] == "completed"
    assert foreground.meta is None and ordinary.meta is None
    assert sorted(http.http.timeout for _, http, _ in service.requests) == [60, 120, 390]


@pytest.mark.parametrize("change", [
    {"nested_job": "forged-job"}, {"nested_deadline": 1400},
    {"nested_name": "create_script_project"}, {"nested_middleware_flag": True},
])
def test_foreground_script_reentry_cannot_acquire_background_or_other_tool_authority(service, change):
    result = asyncio.run(service.Secure().call_tool("run_script_function", {
        "middleware_reentry": True, **change,
    }))
    assert result.is_error and result.meta is None
    assert service.requests == []


@pytest.mark.parametrize("failure", [BadStatusLine("lost response"), ResponseNotReady(),
                                    TimeoutError("lost response")])
def test_low_level_google_connection_never_resends_after_lost_response(service, failure):
    asyncio.run(call(service))
    transport = service.requests[0][1].http
    transport._observer = SimpleNamespace(track_socket=lambda sock: None)
    conn = Mock()
    conn.getresponse.side_effect = failure
    token = service.module._script_execution_budget.set(
        service.module._AppsScriptBudget("job-fixture", 400))
    try:
        with pytest.raises(type(failure)):
            transport._conn_request(conn, "/v1/scripts/fixture:run", "POST", b"{}", {})
    finally:
        service.module._script_execution_budget.reset(token)
    assert transport.follow_redirects is False
    conn.request.assert_called_once_with("POST", "/v1/scripts/fixture:run", b"{}", {})
    conn.getresponse.assert_called_once()


def test_google_connection_setup_cannot_outlive_budget_then_submit(service):
    asyncio.run(call(service))
    transport = service.requests[0][1].http
    transport._observer = SimpleNamespace(track_socket=lambda sock: None)
    sock = Mock()
    conn = Mock(sock=None)
    elapsed = [100]
    service.module.time.monotonic = lambda: elapsed[0]

    def connect():
        elapsed[0] = 401
        conn.sock = sock

    conn.connect.side_effect = connect
    token = service.module._script_execution_budget.set(
        service.module._AppsScriptBudget("job-fixture", 400))
    try:
        with pytest.raises(TimeoutError, match="deadline"):
            transport._conn_request(conn, "/v1/scripts/fixture:run", "POST", b"{}", {})
    finally:
        service.module._script_execution_budget.reset(token)
    conn.request.assert_not_called()


def test_concurrent_service_calls_keep_their_own_deadline_and_completion_identity(service):
    async def run():
        return await asyncio.gather(call(service, deadline=1300, job_id="first-job"),
                                    call(service, deadline=1120, job_id="second-job"))

    left, right = asyncio.run(run())
    assert left.meta[META_KEY]["job_id"] == "first-job"
    assert right.meta[META_KEY]["job_id"] == "second-job"
    assert sorted(http.http.timeout for _, http, _ in service.requests) == [120, 300]
    assert all(transport.timeout == 60 for transport in service.transports[::2])


def test_service_observation_timeout_does_not_claim_a_blocked_script_stopped(service):
    entered, release = Event(), Event()
    service.module.time.monotonic = time.monotonic

    def provider_call():
        entered.set()
        release.wait(timeout=1)
        return {"response": {"result": "eventually finished"}}

    async def run():
        try:
            result = await call(service, {"outcome": provider_call}, deadline=1000.03)
            assert entered.is_set()
            assert result.is_error and result.meta[META_KEY]["completion"] == "unknown"
            return result
        finally:
            release.set()

    result = asyncio.run(run())
    assert result.meta[META_KEY]["completion"] == "unknown"
    assert len(service.requests) == 1
