"""Optional navigation overrides preserve existing LAN defaults and host scope."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from flask import Flask
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import ui_navigation  # noqa: E402


def write_config(path, hosts):
    path.write_text(json.dumps({"hosts": hosts}), encoding="utf-8")


@pytest.mark.parametrize("contents", [None, "broken JSON", "[]", "null", '{"hosts":[]}', '{"hosts":null}', "\udcff"])
def test_absent_or_malformed_config_keeps_existing_navigation(tmp_path, contents):
    path = tmp_path / "ui_urls.json"
    if contents is not None:
        path.write_text(contents, encoding="utf-8", errors="surrogateescape")
    assert ui_navigation.navigation_for_host("jarvis.example.test", path) == {}


def test_only_the_matching_host_and_known_services_are_exposed(tmp_path):
    path = tmp_path / "ui_urls.json"
    write_config(path, {
        "JARVIS.EXAMPLE.TEST.": {"web": "https://jarvis.example.test/", "canvas": "https://jarvis.example.test:8443", "unknown": "https://unrelated.test"},
        "other.example.test": {"web": "https://other.example.test"},
    })
    assert ui_navigation.navigation_for_host("jarvis.example.test", path) == {
        "web": "https://jarvis.example.test", "canvas": "https://jarvis.example.test:8443",
    }
    assert ui_navigation.navigation_for_host("192.0.2.5", path) == {}
    assert ui_navigation.navigation_for_host("localhost", path) == {}


@pytest.mark.parametrize("url", [
    None, 123, "", "//jarvis.example.test", "javascript:alert(1)", "file:///tmp/local",
    "https://user:password@jarvis.example.test", "https://jarvis.example.test/page",
    "https://jarvis.example.test?", "https://jarvis.example.test#", "https://jarvis.example.test/?token=example",
    "https://jarvis.example.test/#tab", "https://jarvis.example.test:bad", "https://jarvis.example.test:65536",
    "https://jarvis.example.test:0", "https://jarvis.example.test\\@other.test", " https://jarvis.example.test",
    "https://jarvis.example.test\n", "\x00https://jarvis.example.test", "https://bad<host.test", "https://-bad.test",
])
def test_invalid_origin_is_ignored_without_discarding_valid_services(tmp_path, url):
    path = tmp_path / "ui_urls.json"
    write_config(path, {"jarvis.example.test": {"web": url, "canvas": "http://localhost:8890"}})
    assert ui_navigation.navigation_for_host("jarvis.example.test", path) == {"canvas": "http://localhost:8890"}


def test_valid_origins_accept_ports_and_ipv6_without_paths(tmp_path):
    path = tmp_path / "ui_urls.json"
    write_config(path, {"jarvis.example.test": {
        "web": "HTTPS://JARVIS.EXAMPLE.TEST:443/", "canvas": "http://127.0.0.1:8890",
        "memory": "https://[::1]:8444", "intelligence": "http://localhost:80", "docs": "https://docs.example.test",
    }})
    assert ui_navigation.navigation_for_host("jarvis.example.test", path) == {
        "web": "https://jarvis.example.test", "canvas": "http://127.0.0.1:8890",
        "memory": "https://[::1]:8444", "intelligence": "http://localhost", "docs": "https://docs.example.test",
    }


def test_oversized_or_non_object_host_entry_fails_to_defaults(tmp_path):
    path = tmp_path / "ui_urls.json"
    write_config(path, {"jarvis.example.test": ["https://jarvis.example.test"]})
    assert ui_navigation.navigation_for_host("jarvis.example.test", path) == {}
    path.write_bytes(b" " * (ui_navigation.MAX_CONFIG_BYTES + 1))
    assert ui_navigation.navigation_for_host("jarvis.example.test", path) == {}


def test_script_route_is_uncached_host_scoped_and_picks_up_config_edits(tmp_path):
    path = tmp_path / "ui_urls.json"
    write_config(path, {
        "jarvis.example.test": {"web": "https://jarvis.example.test"},
        "other.example.test": {"web": "https://other.example.test"},
    })
    app = Flask(__name__)
    ui_navigation.register_ui_navigation(app, path)
    client = app.test_client()
    response = client.get("/ui-navigation.js", base_url="http://jarvis.example.test:5001")
    assert response.status_code == 200
    assert response.mimetype == "application/javascript"
    assert response.headers["Cache-Control"] == "private, no-store, max-age=0"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "ETag" not in response.headers
    script = response.get_data(as_text=True)
    assert '"hostname":"jarvis.example.test"' in script
    assert '"web":"https://jarvis.example.test"' in script
    assert "other.example.test" not in script
    write_config(path, {"jarvis.example.test": {"web": "https://jarvis.example.test:8443"}})
    assert '"web":"https://jarvis.example.test:8443"' in client.get(
        "/ui-navigation.js", base_url="http://jarvis.example.test:5001"
    ).get_data(as_text=True)
    lan_script = client.get("/ui-navigation.js", base_url="http://192.0.2.5:5001",
                            headers={"X-Forwarded-Host": "jarvis.example.test"}).get_data(as_text=True)
    assert '"urls":{}' in lan_script
    assert "jarvis.example.test" not in lan_script


def test_bootstrap_escapes_script_delimiters_and_unicode_separators(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_navigation, "navigation_for_host", lambda *args: {"web": "</script>&\u2028\u2029"})
    app = Flask(__name__)
    ui_navigation.register_ui_navigation(app, tmp_path / "absent.json")
    bootstrap = app.test_client().get("/ui-navigation.js").get_data(as_text=True).splitlines()[0]
    assert "</script>" not in bootstrap and "&" not in bootstrap
    assert "\\u003c/script\\u003e\\u0026\\u2028\\u2029" in bootstrap


def test_classic_helper_applies_only_matching_host_origins_and_preserves_fallbacks():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(SOURCE, 'utf8');
function boot(hostname, configuration) {
  const window = {location: {hostname}, __jarvisUINavigationConfig: configuration};
  vm.runInNewContext(source, {window});
  assert.equal(window.__jarvisUINavigationConfig, undefined);
  return window.JarvisUINavigation;
}
const config = {hostname:'jarvis.example.test', urls:{web:'https://jarvis.example.test', canvas:'https://jarvis.example.test:8443'}};
const helper = boot('JARVIS.EXAMPLE.TEST.', config);
assert.equal(helper.url('canvas', 'http://jarvis.example.test:8890'), 'https://jarvis.example.test:8443');
assert.equal(helper.url('memory', 'http://jarvis.example.test:5003'), 'http://jarvis.example.test:5003');
assert.equal(helper.url('constructor', 'original'), 'original');
assert.equal(Object.isFrozen(helper), true);
assert.equal(boot('192.0.2.5', config).url('web', 'http://192.0.2.5:5001'), 'http://192.0.2.5:5001');
assert.equal(boot('localhost', undefined).url('web', 'http://localhost:5001'), 'http://localhost:5001');
assert.equal(boot('jarvis.example.test', {hostname:'jarvis.example.test', urls:null}).url('web', 'original'), 'original');
"""
    prelude = f"const SOURCE = {json.dumps(str(ui_navigation.SCRIPT_PATH))};\n"
    subprocess.run(["node", "-e", prelude + script], cwd=ROOT, check=True, timeout=15)
