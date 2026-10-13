"""Exercise the real Web route/auth/mode decorator and classic JS result renderer."""
import ast
import functools
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Blueprint, Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import bookmark_plus  # noqa: E402
import config_loader  # noqa: E402
import webui_auth  # noqa: E402

LOGIN = {"Authorization": "Bearer test-login"}


@pytest.fixture
def route_client(monkeypatch):
    monkeypatch.setattr(webui_auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(webui_auth, "get_token_from_request", lambda req: req.headers.get("Authorization"))
    monkeypatch.setattr(webui_auth, "verify_token", lambda token: token == "Bearer test-login")
    settings = {"enabled": True, "backend": "bookmark_plus", "blocked": "", "error": False}
    monkeypatch.setattr(config_loader, "_load_mode_config", lambda mode: {
        "BOOKMARK_BACKEND": settings["backend"], "BLOCKED_TOOLS": settings["blocked"],
        "BOOKMARK_PLUS_TOKEN": f"private-{mode}-token"})
    calls = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs == {"icon_request": True}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def icon(self, identifier):
            calls.append((identifier, config_loader.get_active_config_mode(), config_loader.get_config_value("BOOKMARK_PLUS_TOKEN")))
            if settings["error"]:
                raise bookmark_plus.BookmarkPlusError("private-token invalid image")
            return b"PNG-tested-by-client"

    monkeypatch.setattr(bookmark_plus, "BookmarkPlusClient", Client)
    app = Flask(__name__)
    blueprint = Blueprint("api", __name__, url_prefix="/api")
    scope = {"api_bp": blueprint, "require_auth": webui_auth.require_auth,
             "functools": functools, "request": request, "jsonify": jsonify,
             "get_web_setting": lambda k, default=None: default,
             "_apply_tts_provider_override": lambda mode: None,
             "_get_status_overrides": lambda mode: {},
             "get_tool_service": lambda: SimpleNamespace(get_tool=lambda _: {"enabled": settings["enabled"]})}
    tree = ast.parse((ROOT / "jarvis-web/server/routes/api.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in {"_scoped_request_config", "get_bookmark_plus_icon"}:
            exec(compile(ast.Module(body=[node], type_ignores=[]), "api.py", "exec"), scope)
    app.register_blueprint(blueprint)
    return app.test_client(), settings, calls


def test_icon_login_and_mode_are_required_and_kept_server_side(route_client):
    client, _, calls = route_client
    assert client.get("/api/bookmarks/plus/17/icon?mode=cloud").status_code == 401
    assert not calls
    for mode in ("cloud", "local"):
        result = client.get(f"/api/bookmarks/plus/17/icon?mode={mode}", headers=LOGIN)
        assert result.status_code == 200 and result.content_type == "image/png"
        assert result.headers["Cache-Control"] == "private, no-store"
        assert result.headers["X-Content-Type-Options"] == "nosniff"
        assert b"token" not in result.data
        assert calls[-1] == (17, mode, f"private-{mode}-token")
    assert client.get("/api/bookmarks/plus/17/icon?mode=invalid", headers=LOGIN).status_code == 400
    assert len(calls) == 2


@pytest.mark.parametrize("setting,value", [("enabled", False), ("backend", "builtin"), ("backend", "typo"), ("blocked", "bookmark_search")])
def test_disabled_or_wrong_backend_never_fetches_icons(route_client, setting, value):
    client, settings, calls = route_client
    settings[setting] = value
    assert client.get("/api/bookmarks/plus/17/icon?mode=cloud", headers=LOGIN).status_code == 404
    assert not calls


def test_proxy_failure_is_a_safe_placeholder_response(route_client):
    client, settings, calls = route_client
    settings["error"] = True
    response = client.get("/api/bookmarks/plus/17/icon?mode=local", headers=LOGIN)
    assert response.status_code == 404 and "token" not in response.get_data(as_text=True)
    assert len(calls) == 1


def test_bookmark_renderer_links_private_urls_escapes_metadata_and_loads_only_proxy_icons():
    scripts = [ROOT / f"jarvis-web/client/js/{name}" for name in (
        "structured-results-shopping.js", "structured-results-search.js", "structured-results-local-travel.js", "structured-results.js")]
    script = f"""
const fs = require('fs'), vm = require('vm');
const escapeHtml = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\"/g, '&quot;').replace(/'/g, '&#39;');
const events = {{}};
const sandbox = {{URL, console, window: {{location: {{origin: 'https://jarvis.test'}}}},
  document: {{addEventListener: (name, handler) => events[name] = handler}},
  Utils: {{escapeHtml, safeHttpUrlForAttr: value => {{try {{const u = new URL(String(value)); return ['http:', 'https:'].includes(u.protocol) ? escapeHtml(u.href) : '';}} catch (_) {{return '';}}}}}}
}};
vm.createContext(sandbox);
for (const file of {json.dumps([str(p) for p in scripts])}) vm.runInContext(fs.readFileSync(file, 'utf8'), sandbox);
const renderer = sandbox.window.structuredResultsRenderer;
const payload = {{backend: 'bookmark_plus', action: 'search', query: 'ntfy', total: 200,
  total_kind: 'retrieval_candidates', search_mode: 'hybrid', diagnostics: {{rerank_truncated: true}},
  results: [{{id: 17, title: '<img src=x onerror=evil()>', url: 'http://192.168.1.50:8080/',
    description: '<script>evil()</script>', folder_path: 'Services', tags: ['self-hosted'], score: .88,
    icon_url: '/api/bookmarks/plus/17/icon?mode=local'}},
    {{id: 18, title: 'External icon', url: 'https://example.org/', icon_url: 'https://attacker.test/icon'}}]}};
const html = renderer.render({{bookmark_search: payload}}, {{}}, ['bookmark_search']);
const empty = renderer.render({{bookmark_search: {{...payload, results: [], total: 0, status: 'no_confident_matches'}}}}, {{}}, ['bookmark_search']);
const target = {{hidden: false, matches: () => true}};
events.error({{target}});
console.log(JSON.stringify({{html, empty, fallback: target.hidden}}));
"""
    completed = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    result = json.loads(completed.stdout)
    html = result["html"]
    assert 'href="http://192.168.1.50:8080/"' in html
    assert 'src="https://jarvis.test/api/bookmarks/plus/17/icon?mode=local"' in html
    assert "attacker.test" not in html and "<script>" not in html and "<img src=x" not in html
    assert "&lt;script&gt;" in html and "Relevance 88%" in html
    assert "200 retrieved candidates" in html and "Only part of the candidate set was judged" in html
    assert result["fallback"]
    assert "No judged candidates met the relevance cutoff" in result["empty"] and "0 shown" in result["empty"]
