"""xAI public Canvas PDF lifecycle regression coverage."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "jarvis-canvas", ROOT / "lib"):
    sys.path.insert(0, str(path))

from server.services import xai_pdf_share  # noqa: E402
from server.services.pdf_export import prepare_canvas_pdf  # noqa: E402
from server.services.xai_pdf_share import (  # noqa: E402
    XaiPdfShareError,
    XaiPdfShareRegistry,
    XaiPdfShareService,
    get_xai_pdf_share_status,
)


SHARE_NOW = datetime(2026, 8, 8, tzinfo=timezone.utc)
SHARE_EXPIRES_AT = SHARE_NOW + timedelta(days=7)


@pytest.fixture(autouse=True)
def _freeze_share_clock(monkeypatch):
    monkeypatch.setattr(xai_pdf_share, "_utc_now", lambda: SHARE_NOW)


class FakeTimestamp:
    def __init__(self, value: datetime):
        self.value = value

    def ToDatetime(self, tzinfo=None):
        return self.value.astimezone(tzinfo or timezone.utc)


class FakeFilesClient:
    def __init__(self):
        self.upload_calls = []
        self.created = []
        self.revoked = []
        self.deleted = []

    def upload(self, payload, *, filename, expires_after):
        self.upload_calls.append((payload, filename, expires_after))
        return SimpleNamespace(id="file_canvas_pdf")

    def create_public_url(self, file_id):
        self.created.append(file_id)
        return SimpleNamespace(
            public_url="https://files-cdn.x.ai/public/test-canvas.pdf",
            expires_at=FakeTimestamp(SHARE_EXPIRES_AT),
        )

    def revoke_public_url(self, file_id):
        self.revoked.append(file_id)

    def delete(self, file_id):
        self.deleted.append(file_id)


def _enable_sharing(monkeypatch):
    monkeypatch.setenv("CANVAS_XAI_PDF_SHARE", "true")
    monkeypatch.setenv("XAI_API_KEY", "test-key-not-sent")
    monkeypatch.delenv("JARVIS_OVERRIDE_CANVAS_XAI_PDF_SHARE", raising=False)
    monkeypatch.delenv("JARVIS_OVERRIDE_XAI_API_KEY", raising=False)


def _pdf():
    page = {
        "id": "page_20260808_010101_test",
        "title": "Share lifecycle",
        "content": "A harmless public snapshot.",
        "updated": "2026-08-08T01:01:01Z",
    }
    return page, *prepare_canvas_pdf(page)


def test_publish_catalog_and_revoke_lifecycle(tmp_path, monkeypatch):
    _enable_sharing(monkeypatch)
    files = FakeFilesClient()
    client = SimpleNamespace(files=files)
    registry = XaiPdfShareRegistry(tmp_path / ".shares" / "registry.json")
    service = XaiPdfShareService(client_factory=lambda: client, registry=registry)
    page, projection, payload = _pdf()

    record = service.publish(
        page_id=page["id"],
        title=page["title"],
        source_updated_at=page["updated"],
        pdf_payload=payload,
        projection=projection,
        ttl_days=7,
        pdf_sha256="a" * 64,
        pdf_theme="dark",
    )

    assert record["status"] == "active"
    assert record["pdf_theme"] == "dark"
    assert record["expires_at"] == (
        SHARE_EXPIRES_AT.isoformat().replace("+00:00", "Z")
    )
    assert files.upload_calls[0][2].days == 7
    assert files.created == ["file_canvas_pdf"]
    assert service.list_for_page(page["id"])[0]["share_id"] == record["share_id"]

    revoked = service.revoke(record["share_id"])
    assert revoked["status"] == "revoked"
    assert files.revoked == ["file_canvas_pdf"]
    assert files.deleted == ["file_canvas_pdf"]


def test_publish_cleanup_runs_when_catalog_write_fails(tmp_path, monkeypatch):
    _enable_sharing(monkeypatch)
    files = FakeFilesClient()
    client = SimpleNamespace(files=files)

    class BrokenRegistry(XaiPdfShareRegistry):
        def add(self, _record):
            raise XaiPdfShareError("catalog unavailable")

    service = XaiPdfShareService(
        client_factory=lambda: client,
        registry=BrokenRegistry(tmp_path / "registry.json"),
    )
    page, projection, payload = _pdf()

    with pytest.raises(XaiPdfShareError, match="catalog unavailable"):
        service.publish(
            page_id=page["id"],
            title=page["title"],
            source_updated_at=page["updated"],
            pdf_payload=payload,
            projection=projection,
            ttl_days=7,
            pdf_sha256="b" * 64,
            pdf_theme="dark",
        )

    assert files.revoked == ["file_canvas_pdf"]
    assert files.deleted == ["file_canvas_pdf"]


def test_revoked_file_cleanup_can_be_retried(tmp_path, monkeypatch):
    _enable_sharing(monkeypatch)

    class DeleteFailsOnce(FakeFilesClient):
        def __init__(self):
            super().__init__()
            self.delete_attempts = 0

        def delete(self, file_id):
            self.delete_attempts += 1
            if self.delete_attempts == 1:
                raise RuntimeError("temporary delete failure")
            self.deleted.append(file_id)

    files = DeleteFailsOnce()
    client = SimpleNamespace(files=files)
    service = XaiPdfShareService(
        client_factory=lambda: client,
        registry=XaiPdfShareRegistry(tmp_path / "registry.json"),
    )
    page, projection, payload = _pdf()
    record = service.publish(
        page_id=page["id"],
        title=page["title"],
        source_updated_at=page["updated"],
        pdf_payload=payload,
        projection=projection,
        ttl_days=7,
        pdf_sha256="c" * 64,
        pdf_theme="dark",
    )

    pending = service.revoke(record["share_id"])
    cleaned = service.revoke(record["share_id"])

    assert pending["status"] == "revoked_cleanup_pending"
    assert cleaned["status"] == "revoked"
    assert files.revoked == ["file_canvas_pdf"]
    assert files.delete_attempts == 2
    assert files.deleted == ["file_canvas_pdf"]


def test_status_requires_both_explicit_opt_in_and_api_key(monkeypatch):
    monkeypatch.setenv("CANVAS_XAI_PDF_SHARE", "false")
    monkeypatch.setenv("XAI_API_KEY", "present")
    assert not get_xai_pdf_share_status()["available"]

    monkeypatch.setenv("CANVAS_XAI_PDF_SHARE", "true")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert not get_xai_pdf_share_status()["available"]

    monkeypatch.setenv("XAI_API_KEY", "present")
    status = get_xai_pdf_share_status()
    assert status["available"]
    assert status["default_ttl_days"] == 7
    assert status["allowed_ttl_days"] == [1, 7, 30]
