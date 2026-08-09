"""Protected Canvas PDF route and browser-surface regression checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "jarvis-canvas", ROOT / "lib"):
    sys.path.insert(0, str(path))

from server.routes import pdf_shares as routes  # noqa: E402


def _app_with_page(tmp_path, monkeypatch, content="Harmless page"):
    routes._PDF_CACHE.clear()
    page = {
        "id": "page_20260808_010101_test",
        "title": "Route PDF",
        "content": content,
        "tags": [],
        "created": "2026-08-08T01:01:01Z",
        "updated": "2026-08-08T01:01:01Z",
    }
    page_path = tmp_path / f"{page['id']}.json"
    page_path.write_text(json.dumps(page), encoding="utf-8")
    monkeypatch.setattr(routes, "get_page_path", lambda page_id: tmp_path / f"{page_id}.json")
    app = Flask(__name__)
    app.register_blueprint(routes.pdf_shares_bp)
    return app, page


def test_pdf_download_and_preview_routes(tmp_path, monkeypatch):
    app, page = _app_with_page(tmp_path, monkeypatch)
    client = app.test_client()

    download = client.get(f"/api/canvas-exports/pages/{page['id']}/pdf")
    preview = client.post(f"/api/xai-pdf-shares/pages/{page['id']}/preview")

    assert download.status_code == 200
    assert download.mimetype == "application/pdf"
    assert download.data.startswith(b"%PDF-")
    assert "attachment" in download.headers["Content-Disposition"]
    assert preview.status_code == 200
    assert preview.json["can_publish"] is True
    assert len(preview.json["pdf_sha256"]) == 64
    assert len(preview.json["source_sha256"]) == 64
    assert preview.json["preview_url"].startswith("/api/canvas-exports/")


def test_unchanged_page_reuses_rendered_pdf(tmp_path, monkeypatch):
    app, page = _app_with_page(tmp_path, monkeypatch)
    original_prepare = routes.prepare_canvas_pdf
    render_calls = []

    def counted_prepare(source_page):
        render_calls.append(source_page["id"])
        return original_prepare(source_page)

    monkeypatch.setattr(routes, "prepare_canvas_pdf", counted_prepare)
    client = app.test_client()
    first = client.get(f"/api/canvas-exports/pages/{page['id']}/pdf")
    second = client.post(f"/api/xai-pdf-shares/pages/{page['id']}/preview")

    assert first.status_code == 200
    assert second.status_code == 200
    assert render_calls == [page["id"]]
    assert first.data == routes._PDF_CACHE[second.json["source_sha256"]][1]


def test_publish_route_requires_confirmation_and_blocks_secrets(tmp_path, monkeypatch):
    app, page = _app_with_page(tmp_path, monkeypatch, content="api_key=secret-value-123")
    client = app.test_client()

    unconfirmed = client.post(
        f"/api/xai-pdf-shares/pages/{page['id']}",
        json={"ttl_days": 7},
    )
    blocked = client.post(
        f"/api/xai-pdf-shares/pages/{page['id']}",
        json={"ttl_days": 7, "confirmed": True},
    )

    assert unconfirmed.status_code == 400
    assert blocked.status_code == 422
    assert any(item["severity"] == "block" for item in blocked.json["findings"])


def test_pdf_render_failure_returns_actionable_422(tmp_path, monkeypatch):
    app, page = _app_with_page(tmp_path, monkeypatch)
    monkeypatch.setattr(
        routes,
        "prepare_canvas_pdf",
        lambda _page: (_ for _ in ()).throw(NotImplementedError("unsupported nested content")),
    )

    response = app.test_client().get(f"/api/canvas-exports/pages/{page['id']}/pdf")

    assert response.status_code == 422
    assert response.is_json
    assert "could not be converted to PDF" in response.json["error"]


def test_publish_rejects_page_changed_after_preview(tmp_path, monkeypatch):
    app, page = _app_with_page(tmp_path, monkeypatch)
    client = app.test_client()
    preview = client.post(f"/api/xai-pdf-shares/pages/{page['id']}/preview").json

    page["content"] = "Changed after the user reviewed the PDF."
    (tmp_path / f"{page['id']}.json").write_text(json.dumps(page), encoding="utf-8")
    response = client.post(
        f"/api/xai-pdf-shares/pages/{page['id']}",
        json={
            "ttl_days": 7,
            "confirmed": True,
            "expected_source_sha256": preview["source_sha256"],
        },
    )

    assert response.status_code == 409
    assert "changed after preview" in response.json["error"]


def test_publish_accepts_the_reviewed_page_fingerprint(tmp_path, monkeypatch):
    app, page = _app_with_page(tmp_path, monkeypatch)

    class FakeShareService:
        def __init__(self):
            self.publish_kwargs = None

        def publish(self, **kwargs):
            self.publish_kwargs = kwargs
            return {
                "share_id": "a" * 32,
                "public_url": "https://files-cdn.x.ai/public/route-test.pdf",
                "status": "active",
            }

    service = FakeShareService()
    monkeypatch.setattr(routes, "share_service", service)
    client = app.test_client()
    preview = client.post(f"/api/xai-pdf-shares/pages/{page['id']}/preview").json
    response = client.post(
        f"/api/xai-pdf-shares/pages/{page['id']}",
        json={
            "ttl_days": 7,
            "confirmed": True,
            "expected_source_sha256": preview["source_sha256"],
        },
    )

    assert response.status_code == 201
    assert response.json["share"]["status"] == "active"
    assert len(service.publish_kwargs["pdf_sha256"]) == 64
    assert service.publish_kwargs["pdf_payload"].startswith(b"%PDF-")


def test_share_routes_are_not_in_canvas_public_api_prefixes():
    app_source = (ROOT / "jarvis-canvas" / "server" / "app.py").read_text(encoding="utf-8")
    public_prefix_line = next(
        line for line in app_source.splitlines() if line.strip().startswith("PUBLIC_API_PREFIXES =")
    )

    assert "/api/pages" in public_prefix_line
    assert "/api/canvas-exports" not in public_prefix_line
    assert "/api/xai-pdf-shares" not in public_prefix_line


def test_canvas_ui_exposes_all_downloads_and_guarded_public_share():
    template = (ROOT / "jarvis-canvas" / "client" / "templates" / "canvas.html").read_text()
    script = (ROOT / "jarvis-canvas" / "client" / "static" / "js" / "canvas.js").read_text()

    assert "Download Page" in template
    assert "JSON" in template and "Markdown" in template and "PDF" in template
    assert "Anyone with the URL can view this PDF" in template
    assert "xaiPdfConfirm" in template
    assert "xaiPdfShareStatus.available" in script
    assert "expected_source_sha256" in script
    assert "files-cdn.x.ai" in script
