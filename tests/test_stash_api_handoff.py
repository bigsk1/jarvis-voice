"""External handoffs retrieve canonical Stash files without guessing local paths."""

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import config_loader
import pytest
from config_loader import config_scope
from fastapi import FastAPI
from fastapi.testclient import TestClient
from stash_helper import StashFile, open_space

from api.routes import stash as routes


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """Use real scoped configuration and separate stores, never operator mode files."""
    checkout = tmp_path / "checkout"
    config = checkout / "config"
    config.mkdir(parents=True)
    stores = {mode: tmp_path / f"custom-{mode}-stash" for mode in ("cloud", "local")}
    for mode, root in stores.items():
        root.mkdir()
        (config / f"{mode}.env").write_text(f'STASH_DIR="{root}"\n', encoding="utf-8")
    monkeypatch.setattr(config_loader, "get_project_root", lambda: checkout)
    monkeypatch.delenv("JARVIS_OVERRIDE_STASH_DIR", raising=False)
    monkeypatch.setenv("JARVIS_MODE", "cloud")
    # Legacy endpoints inherit startup config instead of opening a request scope.
    monkeypatch.setenv("STASH_DIR", str(stores["cloud"]))
    return stores


@pytest.fixture
def client(storage):
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as value:
        yield value


def save_file(content="A complete research report.", name="research.md", *, mode="cloud", mime=None):
    with config_scope(mode):
        space, _ = open_space(labels=["handoff-test"])
        stash_file = StashFile(space)
        if isinstance(content, bytes):
            saved = stash_file.save_binary(content, name, mime_type=mime)
        else:
            saved = stash_file.save_text(content, name)
        return space, saved


@pytest.mark.parametrize("selector", ["file_id", "name"])
def test_resolves_ids_and_filename_aliases_to_same_canonical_file(client, storage, selector):
    space, saved = save_file(name="chapter #1 café.md")
    ref = f"stash://{space.space_id}/{saved[selector]}"
    response = client.get("/api/stash/resolve", params={"ref": ref})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["ok"] is True
    assert result["mode"] == "cloud"
    assert result["stash_ref"] == saved["ref"]
    assert result["space_id"] == space.space_id
    assert result["file_id"] == saved["file_id"]
    assert result["filename"] == saved["name"]
    assert result["mime_type"] == "text/plain"
    assert result["size_bytes"] == len(Path(saved["path"]).read_bytes())
    assert result["hash_sha256"] == saved["hash_sha256"]
    assert result["text_readable"] is True
    for key in ("read_url", "download_url"):
        assert result[key].startswith("/api/stash/")
        assert "mode=cloud" in result[key]
        assert str(storage["cloud"]) not in result[key]
    assert client.get(result["read_url"]).json()["content"] == "A complete research report."
    assert client.get(result["download_url"]).content == b"A complete research report."
    assert "path" not in result and "stored_name" not in result


def test_normalized_date_reference_returns_real_canonical_space(client):
    space, saved = save_file()
    date = space.space_id.split("_")[1]
    dashed = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    ref = saved["ref"].replace(f"space_{date}_", f"space_{dashed}_")
    result = client.get("/api/stash/resolve", params={"ref": ref}).json()
    assert result["ok"] is True
    assert result["stash_ref"] == saved["ref"]


@pytest.mark.parametrize("route", ["resolve", "read", "download"])
def test_reference_routes_require_ref_query_parameter(client, route):
    _space, saved = save_file()
    url = f"/api/stash/{route}"
    assert client.get(url).status_code == 422
    assert client.get(url, params={"stash_ref": saved["ref"]}).status_code == 422
    assert client.get(url, params={"ref": saved["ref"]}).status_code == 200


def test_explicit_mode_uses_its_configured_store_and_generated_urls_keep_mode(client, storage):
    _space, cloud = save_file("Cloud evidence")
    _space, local = save_file("Local evidence", mode="local")
    assert Path(cloud["path"]).is_relative_to(storage["cloud"])
    assert Path(local["path"]).is_relative_to(storage["local"])
    assert client.get("/api/stash/resolve", params={"ref": local["ref"]}).status_code == 404
    result = client.get(
        "/api/stash/resolve", params={"ref": local["ref"], "mode": "local"}
    ).json()
    assert result["mode"] == "local"
    assert client.get(result["read_url"]).json()["content"] == "Local evidence"
    assert client.get(result["download_url"]).content == b"Local evidence"
    assert client.get(
        "/api/stash/read", params={"ref": cloud["ref"], "mode": "cloud"}
    ).json()["content"] == "Cloud evidence"


def test_omitted_mode_honors_active_scope_and_restores_outer_mode(storage):
    _space, saved = save_file(mode="local")
    with config_scope("local"):
        result = routes.resolve_reference(ref=saved["ref"], mode=None)
        assert result["mode"] == "local"
        assert config_loader.get_active_config_mode() == "local"
    assert config_loader.get_active_config_mode() == "cloud"


def test_unicode_pagination_is_lossless_and_next_urls_pin_hash(client):
    content = "héllo🙂\r\n研究 café\n" * 9
    _space, saved = save_file(content)
    response = client.get("/api/stash/read", params={"ref": saved["ref"], "max_chars": 7})
    recovered = []
    offset = 0
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    while True:
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["offset"] == offset
        assert page["returned_chars"] == len(page["content"])
        assert page["total_chars"] == len(content)
        assert page["content_sha256"] == content_hash
        recovered.append(page["content"])
        offset += len(page["content"])
        if not page["has_more"]:
            assert page["next_offset"] is None
            assert page["next_url"] is None
            break
        assert page["next_offset"] == offset
        assert f"expected_sha256={content_hash}" in page["next_url"]
        response = client.get(page["next_url"])
    assert "".join(recovered) == content


def test_file_change_between_pages_rejected_instead_of_combining_snapshots(client):
    _space, saved = save_file("first version")
    first = client.get(
        "/api/stash/read", params={"ref": saved["ref"], "max_chars": 5}
    ).json()
    Path(saved["path"]).write_text("replacement version", encoding="utf-8")
    response = client.get(first["next_url"])
    assert response.status_code == 409
    assert "restart" in response.json()["detail"]


def test_end_offset_empty_file_and_default_page_limit(client):
    _space, saved = save_file("x" * 20_001)
    first = client.get("/api/stash/read", params={"ref": saved["ref"]}).json()
    assert len(first["content"]) == 20_000 and first["next_offset"] == 20_000
    last = client.get(
        "/api/stash/read", params={"ref": saved["ref"], "offset": 20_001}
    ).json()
    assert last["content"] == "" and last["has_more"] is False
    assert client.get(
        "/api/stash/read", params={"ref": saved["ref"], "offset": 20_002}
    ).status_code == 416
    _space, empty = save_file("")
    result = client.get("/api/stash/read", params={"ref": empty["ref"]}).json()
    assert result["content"] == "" and result["next_url"] is None


def test_binary_download_retains_original_bytes_and_mime_type(client):
    data = b"\x89PNG\r\n\x1a\n\x00\xfftest"
    _space, saved = save_file(data, "diagram.png", mime="image/png")
    result = client.get("/api/stash/resolve", params={"ref": saved["ref"]}).json()
    assert result["text_readable"] is False and result["read_url"] is None
    response = client.get(result["download_url"])
    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"] == "image/png"
    assert "diagram.png" in response.headers["content-disposition"]
    assert client.get("/api/stash/read", params={"ref": saved["ref"]}).status_code == 415


@pytest.mark.parametrize("data", [b"\xff\xfe\x80", b"plain\x00binary"])
def test_text_mime_does_not_silently_decode_binary(client, data):
    _space, saved = save_file(data, "broken.txt", mime="text/plain")
    response = client.get("/api/stash/read", params={"ref": saved["ref"]})
    assert response.status_code == 415
    assert "download" in response.json()["detail"]
    assert client.get("/api/stash/download", params={"ref": saved["ref"]}).content == data


@pytest.mark.parametrize("mime", ["application/json", "application/xml", "application/problem+json"])
def test_structured_text_formats_are_readable(client, mime):
    _space, saved = save_file(b'{"evidence":true}', "evidence.data", mime=mime)
    result = client.get("/api/stash/read", params={"ref": saved["ref"]})
    assert result.status_code == 200
    assert result.json()["content"] == '{"evidence":true}'


def test_large_text_is_rejected_before_reading_and_actual_read_is_bounded(client, monkeypatch):
    _space, saved = save_file("x" * 33)
    monkeypatch.setattr(routes, "TEXT_READ_MAX_BYTES", 32)
    original_open = Path.open

    def disallow_artifact_open(path, *args, **kwargs):
        if path == Path(saved["path"]):
            pytest.fail("Oversized file must be rejected before it is opened")
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as check:
        check.setattr(Path, "open", disallow_artifact_open)
        response = client.get("/api/stash/read", params={"ref": saved["ref"]})
        assert response.status_code == 413

    # Simulate growth after stat by lowering only the reported metadata size.
    original_resolve = routes._resolve_stash_reference

    def stale_size(ref):
        path, metadata = original_resolve(ref)
        return path, {**metadata, "size_bytes": 1}

    monkeypatch.setattr(routes, "_resolve_stash_reference", stale_size)
    assert client.get("/api/stash/read", params={"ref": saved["ref"]}).status_code == 413


@pytest.mark.parametrize("route", ["resolve", "read", "download"])
@pytest.mark.parametrize("missing", ["space", "file", "bytes"])
def test_missing_references_never_report_success(client, route, missing):
    space, saved = save_file()
    if missing == "space":
        ref = "stash://space_missing/f_missing"
    elif missing == "file":
        ref = f"stash://{space.space_id}/missing.txt"
    else:
        Path(saved["path"]).unlink()
        ref = saved["ref"]
    response = client.get(f"/api/stash/{route}", params={"ref": ref})
    assert response.status_code == 404


@pytest.mark.parametrize("route", ["resolve", "read", "download"])
@pytest.mark.parametrize(
    "ref",
    [
        "https://example.com/evidence.txt", "stash://space_missing", "stash://space_missing/",
        "stash:///evidence.txt", "stash://../secrets", "stash://space_missing/../secret",
        "stash://space_missing/..\\secret", "stash://space_missing/.",
        "stash://space_missing/..", " stash://space_missing/file", "stash://space_missing/file\x00",
    ],
)
def test_malformed_and_traversing_references_are_rejected(client, route, ref):
    assert client.get(f"/api/stash/{route}", params={"ref": ref}).status_code == 400


@pytest.mark.parametrize("escape", ["space", "metadata", "file", "stored_name"])
@pytest.mark.parametrize("route", ["resolve", "read", "download"])
def test_symlink_and_manifest_escape_are_rejected(client, tmp_path, escape, route):
    space, saved = save_file()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("DO NOT DISCLOSE", encoding="utf-8")
    if escape == "space":
        moved = outside / space.space_id
        space.space_path.rename(moved)
        space.space_path.symlink_to(moved, target_is_directory=True)
    elif escape == "metadata":
        moved = outside / "meta.json"
        space.meta_path.rename(moved)
        space.meta_path.symlink_to(moved)
    elif escape == "file":
        Path(saved["path"]).unlink()
        Path(saved["path"]).symlink_to(secret)
    else:
        meta = json.loads(space.meta_path.read_text())
        meta["files"][0]["stored_name"] = str(secret)
        space.meta_path.write_text(json.dumps(meta), encoding="utf-8")
    response = client.get(f"/api/stash/{route}", params={"ref": saved["ref"]})
    assert response.status_code == 403
    assert "DO NOT DISCLOSE" not in response.text
    assert str(outside) not in response.text


@pytest.mark.parametrize(
    "params",
    [
        {"offset": -1}, {"max_chars": 0}, {"max_chars": 40_001}, {"mode": "unknown"},
        {"expected_sha256": "not-a-hash"},
    ],
)
def test_query_bounds_are_validated_before_resolution(client, params):
    response = client.get(
        "/api/stash/read", params={"ref": "stash://space_missing/file", **params}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("route", ["resolve", "read", "download", "legacy_download"])
def test_retrieval_routes_use_existing_external_api_auth(storage, monkeypatch, route):
    from api import server

    monkeypatch.setattr(
        server, "get_config_value", lambda key, default="": {
            "JARVIS_API_AUTH": "true", "JARVIS_API_KEY": "stash-handoff-test-key",
        }.get(key, default),
    )
    space, saved = save_file()
    app = FastAPI()
    app.include_router(routes.router)
    app.add_middleware(server.APIAuthMiddleware)
    with TestClient(app, client=("198.51.100.42", 54321)) as client:
        url = f"/api/stash/{route}"
        params = {"ref": saved["ref"]}
        if route == "legacy_download":
            url = f"/api/stash/space/{space.space_id}/file/{saved['file_id']}/download"
            params = {}
        assert client.get(url, params=params).status_code == 401
        assert client.get(url, params=params, headers={"Authorization": "Bearer wrong"}).status_code == 403
        assert client.get(
            url, params=params, headers={"Authorization": "Bearer stash-handoff-test-key"}
        ).status_code == 200


def test_real_app_registers_new_retrieval_routes():
    from api.server import app

    schema = app.openapi()
    for route in ("resolve", "read", "download"):
        operation = schema["paths"][f"/api/stash/{route}"]["get"]
        parameters = {param["name"]: param for param in operation["parameters"]}
        assert parameters["ref"]["required"] is True
        assert "stash_ref" not in parameters


@pytest.mark.parametrize("escape", ["relative", "absolute", "file_link", "sibling_link"])
def test_legacy_download_rejects_manifest_and_artifact_escapes(client, tmp_path, escape):
    space, saved = save_file()
    outside = tmp_path / "outside.txt"
    outside.write_text("OUTSIDE FILE SENTINEL", encoding="utf-8")
    meta = json.loads(space.meta_path.read_text())
    if escape == "relative":
        meta["files"][0]["stored_name"] = "../../outside.txt"
    elif escape == "absolute":
        meta["files"][0]["stored_name"] = str(outside)
    else:
        if escape == "sibling_link":
            _other, sibling = save_file("OUTSIDE FILE SENTINEL")
            outside = Path(sibling["path"])
        Path(saved["path"]).unlink()
        Path(saved["path"]).symlink_to(outside)
    space.meta_path.write_text(json.dumps(meta), encoding="utf-8")
    response = client.get(
        f"/api/stash/space/{space.space_id}/file/{saved['file_id']}/download"
    )
    assert response.status_code == 403
    assert "OUTSIDE FILE SENTINEL" not in response.text
    assert str(tmp_path) not in response.text


@pytest.mark.parametrize("escape", ["space", "metadata"])
@pytest.mark.parametrize("route", ["space", "info", "download"])
def test_legacy_routes_reject_escaped_metadata(client, tmp_path, escape, route):
    space, saved = save_file("OUTSIDE METADATA SENTINEL")
    if escape == "space":
        target = tmp_path / "outside-space"
        space.space_path.rename(target)
        space.space_path.symlink_to(target, target_is_directory=True)
    else:
        target = tmp_path / "outside-meta.json"
        space.meta_path.rename(target)
        space.meta_path.symlink_to(target)
    url = f"/api/stash/space/{space.space_id}"
    if route != "space":
        url += f"/file/{saved['file_id']}"
    if route == "download":
        url += "/download"
    response = client.get(url)
    assert response.status_code == 404
    assert str(tmp_path) not in response.text


@pytest.mark.parametrize("selector", ["%2e%2e", ".%2e", "%2E%2E"])
@pytest.mark.parametrize("route", ["space", "info", "download"])
def test_legacy_routes_reject_encoded_parent_space(client, tmp_path, selector, route):
    space, saved = save_file()
    meta = json.loads(space.meta_path.read_text())
    meta["labels"] = ["PARENT METADATA SENTINEL"]
    meta["files"][0]["stored_name"] = "outside.txt"
    (tmp_path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (tmp_path / "outside.txt").write_text("OUTSIDE FILE SENTINEL", encoding="utf-8")
    url = f"/api/stash/space/{selector}"
    if route != "space":
        url += f"/file/{saved['file_id']}"
    if route == "download":
        url += "/download"
    response = client.get(url)
    assert response.status_code == 404
    assert "SENTINEL" not in response.text
    assert str(tmp_path) not in response.text


@pytest.mark.parametrize("endpoint", ["", "/stats", "/recent", "/search?q=handoff", "/labels"])
def test_legacy_aggregates_skip_escaped_metadata(client, storage, tmp_path, endpoint):
    space, _saved = save_file()
    outside = tmp_path / "outside-space"
    outside.mkdir()
    meta = json.loads(space.meta_path.read_text())
    meta["space_id"] = "space_UNTRUSTED"
    meta["labels"] = ["handoff-test", "UNTRUSTED"]
    (outside / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (storage["cloud"] / "space_bad").symlink_to(outside, target_is_directory=True)
    response = client.get(f"/api/stash{endpoint}")
    assert response.status_code == 200, response.text
    assert "UNTRUSTED" not in response.text
    if endpoint == "/stats":
        assert response.json()["total_spaces"] == 1
    elif endpoint != "/labels":
        assert [row["space_id"] for row in response.json()["spaces"]] == [space.space_id]


@pytest.mark.parametrize("root_link", [False, True])
def test_legacy_download_preserves_aliases_ranges_and_file_identity(client, storage, tmp_path, root_link):
    space, saved = save_file(b"0123456789", "Résumé..txt", mime="text/plain")
    if root_link:
        target = tmp_path / "configured-root-target"
        storage["cloud"].rename(target)
        storage["cloud"].symlink_to(target, target_is_directory=True)
    date = space.space_id.split("_")[1]
    dashed = space.space_id.replace(date, f"{date[:4]}-{date[4:6]}-{date[6:8]}", 1)
    for space_id in (space.space_id, dashed):
        url = f"/api/stash/space/{space_id}/file/{saved['file_id']}/download"
        response = client.get(url)
        assert response.status_code == 200
        assert response.content == b"0123456789"
        assert response.headers["content-type"].startswith("text/plain")
        assert f"filename*=utf-8''{quote(saved['name'])}" in response.headers["content-disposition"]
        partial = client.get(url, headers={"Range": "bytes=1-3", "If-Range": response.headers["etag"]})
        assert partial.status_code == 206
        assert partial.content == b"123"
        assert partial.headers["content-range"] == "bytes 1-3/10"
    # This older endpoint accepts an ID, not the filename alias supported by ?ref=.
    base = f"/api/stash/space/{space.space_id}/file"
    assert client.get(f"{base}/{quote(saved['name'])}/download").status_code == 404
    assert client.get(f"{base}/f_missing/download").status_code == 404
    Path(saved["path"]).unlink()
    assert client.get(f"{base}/{saved['file_id']}/download").status_code == 404


def test_legacy_download_uses_active_store_without_adding_mode_parameter(storage):
    import asyncio

    space, saved = save_file("Local legacy evidence", mode="local")
    with config_scope("local"):
        response = asyncio.run(routes.download_file(space.space_id, saved["file_id"]))
        assert Path(response.path).read_text() == "Local legacy evidence"
        assert config_loader.get_active_config_mode() == "local"
    assert config_loader.get_active_config_mode() == "cloud"
