"""Tests for permanent Cloudflare Images deletion."""

import sys
from pathlib import Path
from unittest.mock import Mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import upload_cloudflare


def test_delete_from_cloudflare_encodes_custom_image_id(monkeypatch):
    monkeypatch.setattr(upload_cloudflare, "CLOUDFLARE_API_TOKEN", "secret-token")
    monkeypatch.setattr(upload_cloudflare, "CLOUDFLARE_ACCOUNT_ID", "account-id")
    response = Mock(status_code=200, ok=True)
    response.json.return_value = {"success": True, "result": {}}
    delete = Mock(return_value=response)
    monkeypatch.setattr(upload_cloudflare.requests, "delete", delete)

    result = upload_cloudflare.delete_from_cloudflare(
        "gallery/2026-07-13/generated/example"
    )

    assert result == {
        "ok": True,
        "image_id": "gallery/2026-07-13/generated/example",
    }
    delete.assert_called_once_with(
        "https://api.cloudflare.com/client/v4/accounts/account-id/images/v1/"
        "gallery%2F2026-07-13%2Fgenerated%2Fexample",
        headers={"Authorization": "Bearer secret-token"},
        timeout=30,
    )


def test_delete_from_cloudflare_does_not_treat_not_found_as_success(monkeypatch):
    monkeypatch.setattr(upload_cloudflare, "CLOUDFLARE_API_TOKEN", "secret-token")
    monkeypatch.setattr(upload_cloudflare, "CLOUDFLARE_ACCOUNT_ID", "account-id")
    response = Mock(status_code=404, ok=False)
    response.json.return_value = {
        "success": False,
        "errors": [{"message": "Image not found"}],
    }
    monkeypatch.setattr(upload_cloudflare.requests, "delete", Mock(return_value=response))

    result = upload_cloudflare.delete_from_cloudflare("missing")

    assert result["ok"] is False
    assert result["error"] == "Image not found"
    assert result["status_code"] == 404
