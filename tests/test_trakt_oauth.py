from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lib.trakt_oauth import (
    TraktOAuthError,
    get_fresh_credentials,
    save_token_response,
)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


def _token(access="access-one", refresh="refresh-one", *, created_at=1000, expires_in=604800):
    return {
        "access_token": access,
        "refresh_token": refresh,
        "created_at": created_at,
        "expires_in": expires_in,
        "token_type": "bearer",
        "scope": "public",
    }


def test_token_cache_is_private_and_never_stores_client_secret(tmp_path: Path):
    path = tmp_path / ".trakt_oauth.json"
    credentials = save_token_response(
        _token(), client_id="client-id", redirect_uri="urn:ietf:wg:oauth:2.0:oob", path=path
    )
    payload = json.loads(path.read_text())
    assert credentials.access_token == "access-one"
    assert "client_secret" not in payload
    assert "client-id" not in path.read_text()
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0


def test_cache_rejects_wrong_client_id(tmp_path: Path):
    path = tmp_path / ".trakt_oauth.json"
    save_token_response(_token(), client_id="one", redirect_uri="oob", path=path)
    with pytest.raises(TraktOAuthError, match="different Client ID"):
        get_fresh_credentials(
            client_id="two", client_secret="secret", redirect_uri="oob", path=path, now_func=lambda: 1001
        )


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_cache_rejects_group_or_world_permissions(tmp_path: Path):
    path = tmp_path / ".trakt_oauth.json"
    save_token_response(_token(), client_id="client", redirect_uri="oob", path=path)
    path.chmod(0o644)
    with pytest.raises(TraktOAuthError, match="chmod 600"):
        get_fresh_credentials(
            client_id="client", client_secret="secret", redirect_uri="oob", path=path, now_func=lambda: 1001
        )


def test_expired_cache_rotates_single_use_refresh_token(tmp_path: Path):
    path = tmp_path / ".trakt_oauth.json"
    save_token_response(
        _token(created_at=100, expires_in=10), client_id="client", redirect_uri="oob", path=path
    )
    seen = {}

    def request(method, url, **kwargs):
        seen.update(kwargs["json"])
        return FakeResponse(200, _token("access-two", "refresh-two", created_at=2000))

    credentials = get_fresh_credentials(
        client_id="client",
        client_secret="secret-sentinel",
        redirect_uri="oob",
        path=path,
        request_func=request,
        now_func=lambda: 2000,
    )
    assert seen["refresh_token"] == "refresh-one"
    assert credentials.refresh_token == "refresh-two"
    assert json.loads(path.read_text())["refresh_token"] == "refresh-two"


def test_refresh_failure_is_sanitized(tmp_path: Path):
    path = tmp_path / ".trakt_oauth.json"
    save_token_response(_token(created_at=100, expires_in=10), client_id="client", redirect_uri="oob", path=path)

    def request(*_args, **_kwargs):
        return FakeResponse(400, {"error": "invalid_grant", "refresh_token": "refresh-one"})

    with pytest.raises(TraktOAuthError) as raised:
        get_fresh_credentials(
            client_id="client", client_secret="secret-sentinel", redirect_uri="oob",
            path=path, request_func=request, now_func=lambda: 2000
        )
    assert "secret-sentinel" not in str(raised.value)
    assert "refresh-one" not in str(raised.value)
