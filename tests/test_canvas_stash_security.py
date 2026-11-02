"""Canvas artifact bytes and metadata stay inside the selected Stash space."""

import json
from urllib.parse import quote

import pytest
from flask import Flask
from server_package_utils import load_canvas_server_package

load_canvas_server_package("canvas_stash_security_test_server")

from canvas_stash_security_test_server.routes import stash as routes  # noqa: E402


@pytest.fixture
def stash_client(tmp_path, monkeypatch):
    root = tmp_path / "stash"
    root.mkdir()
    monkeypatch.setattr(routes, "get_stash_dir", lambda: root)
    app = Flask(__name__)
    app.register_blueprint(routes.stash_bp)
    return app.test_client(), root


@pytest.mark.parametrize("suffix", ["", "/metadata"])
@pytest.mark.parametrize("space_id", ["..", "%2e%2e"])
def test_parent_space_is_rejected(stash_client, suffix, space_id):
    client, root = stash_client
    (root.parent / "outside.txt").write_text("outside sentinel")
    response = client.get(f"/api/stash/{space_id}/outside.txt{suffix}")
    assert response.status_code == 404
    assert b"outside sentinel" not in response.data


@pytest.mark.parametrize("suffix", ["", "/metadata"])
@pytest.mark.parametrize("link_kind", ["space", "metadata", "file", "sibling-file"])
def test_symlinks_cannot_escape_the_selected_space(stash_client, suffix, link_kind):
    client, root = stash_client
    space = root / "space_test"
    outside = root.parent / "outside"
    outside.mkdir()
    (outside / "report.txt").write_text("outside sentinel")
    if link_kind == "space":
        space.symlink_to(outside, target_is_directory=True)
    else:
        space.mkdir()
        if link_kind == "metadata":
            (outside / "meta.json").write_text(json.dumps({"files": []}))
            (space / "meta.json").symlink_to(outside / "meta.json")
            (space / "report.txt").write_text("otherwise safe fallback")
        else:
            destination = outside / "report.txt"
            if link_kind == "sibling-file":
                sibling = root / "space_other"
                sibling.mkdir()
                destination = sibling / "report.txt"
                destination.write_text("sibling sentinel")
            (space / "report.txt").symlink_to(destination)
    response = client.get(f"/api/stash/space_test/report.txt{suffix}")
    assert response.status_code == 404


@pytest.mark.parametrize("suffix", ["", "/metadata"])
@pytest.mark.parametrize("field", ["stored_name", "name"])
@pytest.mark.parametrize("absolute", [False, True])
def test_metadata_cannot_select_an_outside_file(stash_client, suffix, field, absolute):
    client, root = stash_client
    space = root / "space_test"
    space.mkdir()
    outside = root.parent / "outside.txt"
    outside.write_text("outside sentinel")
    stored_name = str(outside) if absolute else "../../outside.txt"
    (space / "meta.json").write_text(json.dumps({"files": [
        {"file_id": "f_report", field: stored_name},
    ]}))
    # A rejected metadata entry must not silently become a direct-file fallback.
    (space / "f_report").write_text("fallback sentinel")
    response = client.get(f"/api/stash/space_test/f_report{suffix}")
    assert response.status_code == 404


@pytest.mark.parametrize("suffix", ["", "/metadata"])
def test_directory_is_not_an_artifact(stash_client, suffix):
    client, root = stash_client
    (root / "space_test" / "directory").mkdir(parents=True)
    assert client.get(f"/api/stash/space_test/directory{suffix}").status_code == 404


@pytest.mark.parametrize("metadata", [None, "broken JSON", {"files": [
    {"file_id": "f_report", "name": "Résumé..txt", "mime_type": "text/plain"},
]}])
def test_legacy_names_direct_files_and_date_aliases_still_work(stash_client, metadata):
    client, root = stash_client
    space = root / "space_20261031_123456_test"
    space.mkdir()
    (space / "Résumé..txt").write_text("safe artifact")
    if metadata is not None:
        (space / "meta.json").write_text(
            metadata if isinstance(metadata, str) else json.dumps(metadata),
        )
    selector = "f_report" if isinstance(metadata, dict) else "Résumé..txt"
    url = f"/api/stash/space_2026-10-31_123456_test/{quote(selector)}"
    response = client.get(url)
    assert response.status_code == 200
    assert response.data == b"safe artifact"
    details = client.get(url + "/metadata")
    assert details.status_code == 200
    assert details.json["space_id"] == space.name


def test_symlinked_configured_root_still_works(stash_client, monkeypatch):
    client, root = stash_client
    space = root / "space_test"
    space.mkdir()
    (space / "report.txt").write_text("safe artifact")
    configured = root.parent / "configured-stash"
    configured.symlink_to(root, target_is_directory=True)
    monkeypatch.setattr(routes, "get_stash_dir", lambda: configured)
    assert client.get("/api/stash/space_test/report.txt").data == b"safe artifact"
