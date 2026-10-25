"""Stash filenames must survive real HTTP header encoding, not just test_client."""

import importlib
import json
from contextlib import contextmanager
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

import pytest
from flask import Flask
from server_package_utils import load_server_package
from werkzeug.http import parse_options_header
from werkzeug.serving import make_server


@contextmanager
def _serve(app):
    server = make_server("127.0.0.1", 0, app)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive(), "Disposable Stash HTTP server did not stop"


@pytest.mark.parametrize("filename", ["Pokémon 👍✅✨ #title.mp4", "plain #title.mp4"])
def test_stash_filename_preserves_http_delivery_and_byte_ranges(tmp_path, monkeypatch, filename):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root))
    monkeypatch.syspath_prepend(str(root / "jarvis-web"))
    namespace = "web_stash_unicode_headers_test"
    load_server_package(namespace, root / "jarvis-web" / "server")
    api = importlib.import_module(namespace + ".routes.api")
    monkeypatch.setattr(api, "get_stash_dir", lambda: tmp_path)
    space_id, file_id = "space_unicode_video", "f_unicode_video"
    space = tmp_path / space_id
    space.mkdir()
    content = b"0123456789abcdef"
    (space / filename).write_bytes(content)
    (space / "meta.json").write_text(json.dumps({"files": [{
        "file_id": file_id, "name": filename, "stored_name": filename, "mime_type": "video/mp4",
    }]}))
    app = Flask(__name__)
    app.register_blueprint(api.api_bp)

    with _serve(app) as port:
        connection = HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            path = f"/api/stash/{space_id}/{file_id}"
            for range_header, expected_status, expected in (
                ({}, 200, content),
                ({"Range": "bytes=4-9"}, 206, content[4:10]),
            ):
                connection.request("GET", path, headers=range_header)
                response = connection.getresponse()
                assert response.status == expected_status
                assert response.read() == expected
                assert response.getheader("Content-Type") == "video/mp4"
                assert response.getheader("X-Stash-Filename") is None
                assert response.getheader("X-Stash-Ref") == f"stash://{space_id}/{file_id}"
                disposition = response.getheader("Content-Disposition")
                assert disposition is not None
                assert parse_options_header(disposition)[1]["filename"] == filename
                if any(ord(character) > 127 for character in filename):
                    assert "filename*=UTF-8''" in disposition
                for key, value in response.getheaders():
                    (key + value).encode("latin-1")
                if range_header:
                    assert response.getheader("Content-Range") == f"bytes 4-9/{len(content)}"
        finally:
            connection.close()
