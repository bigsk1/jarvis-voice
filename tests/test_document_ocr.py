"""Focused contract and safety coverage for the optional OVIS OCR tool."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills"))
sys.path.insert(0, str(ROOT / "lib"))

import document_ocr  # noqa: E402


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload=None,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload
        self._body = body if body is not None else json.dumps(payload).encode("utf-8")
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def iter_content(self, chunk_size=1):
        for offset in range(0, len(self._body), chunk_size):
            yield self._body[offset : offset + chunk_size]


@pytest.fixture
def input_pdf(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.4\nsynthetic")
    return path


def test_manifest_is_optional_network_file_tool():
    manifest = json.loads((ROOT / "skills" / "document_ocr.tool.json").read_text())
    assert manifest["name"] == "document_ocr"
    assert manifest["proxy_policy"] == "off"
    assert manifest["availability"]["all_of_env"] == ["OVIS_OCR_URL"]
    assert manifest["permissions"] == {
        "dangerous": False,
        "bash": False,
        "network": True,
        "filesystem": True,
        "auto_approve": True,
    }
    assert set(manifest["parameters"]["properties"]["action"]["enum"]) == {
        "status",
        "ocr",
        "extract",
        "archive",
    }
    assert manifest["parameters"]["additionalProperties"] is False


@pytest.mark.parametrize(
    "value",
    (
        "ftp://ocr.example.test",
        "http://user:secret@ocr.example.test",
        "http://ocr.example.test/v1",
        "http://ocr.example.test?token=secret",
    ),
)
def test_base_url_rejects_unsafe_or_non_root_values(monkeypatch, value):
    monkeypatch.setenv("OVIS_OCR_URL", value)
    with pytest.raises(document_ocr.OvisToolError) as error:
        document_ocr.get_ovis_base_url()
    assert error.value.code == "ovis_invalid_url"


def test_base_url_allows_admin_configured_lan_service(monkeypatch):
    monkeypatch.setenv("OVIS_OCR_URL", "http://192.0.2.10:17860/")
    assert document_ocr.get_ovis_base_url() == "http://192.0.2.10:17860"


def test_request_timeout_is_bounded_below_subprocess_limit(monkeypatch):
    monkeypatch.setenv("OVIS_OCR_CONNECT_TIMEOUT_SECONDS", "99")
    monkeypatch.setenv("OVIS_OCR_TIMEOUT_SECONDS", "9999")
    assert document_ocr._request_timeout() == (30, 1100)


def test_direct_input_path_uses_shared_file_policy(input_pdf):
    assert document_ocr._resolve_input_path({"file_path": str(input_pdf)}) == input_pdf
    with pytest.raises(ValueError, match="restricted location"):
        document_ocr._resolve_input_path(
            {"file_path": str(ROOT / "config" / "cloud.env.example")}
        )


def test_input_sources_are_mutually_exclusive(input_pdf):
    with pytest.raises(ValueError, match="exactly one input source"):
        document_ocr._resolve_input_path(
            {
                "file_path": str(input_pdf),
                "stash_ref": "stash://uploads/scan",
            }
        )
    with pytest.raises(ValueError, match="must be provided together"):
        document_ocr._resolve_input_path({"space_id": "uploads"})


def test_ocr_preflights_uploads_and_returns_stash_refs(input_pdf):
    payload = {
        "request_id": "ocr-7",
        "filename": "scan.pdf",
        "document_type": "pdf",
        "model": "ATH-MaaS/OvisOCR2",
        "pages_processed": 2,
        "total_pages": 2,
        "elapsed_seconds": 1.25,
        "markdown": "# Invoice\n" + ("line item\n" * 900),
        "pages": [
            {"page_number": 1, "markdown": "page one", "elapsed_seconds": 0.5},
            {"page_number": 2, "markdown": "page two", "elapsed_seconds": 0.7},
        ],
    }
    space = SimpleNamespace(space_id="space_ocr")
    with (
        patch("document_ocr._resolve_input_path", return_value=input_pdf),
        patch("document_ocr._ready_preflight") as ready,
        patch("document_ocr._request_json", return_value=payload) as request_json,
        patch("document_ocr._output_space", return_value=space),
        patch("document_ocr._save_text", return_value="stash://space_ocr/markdown") as save_text,
        patch("document_ocr._save_json", return_value="stash://space_ocr/json") as save_json,
    ):
        result = document_ocr.action_ocr(
            {
                "stash_ref": "stash://uploads/scan",
                "page_start": 1,
                "page_end": 2,
            }
        )

    assert result["ok"] is True
    assert result["data"]["pages_processed"] == 2
    assert result["data"]["markdown_stash_ref"] == "stash://space_ocr/markdown"
    assert result["data"]["json_stash_ref"] == "stash://space_ocr/json"
    assert result["data"]["stash_ref"] == "stash://space_ocr/markdown"
    assert len(result["data"]["markdown_excerpt"]) <= document_ocr.INLINE_EXCERPT_CHARS
    assert "full result saved to Stash" in result["data"]["markdown_excerpt"]
    assert result["data"]["pages"] == [
        {"page_number": 1, "elapsed_seconds": 0.5},
        {"page_number": 2, "elapsed_seconds": 0.7},
    ]
    ready.assert_called_once_with()
    endpoint = request_json.call_args.args[1]
    form = request_json.call_args.kwargs["data"]
    assert endpoint == "/v1/ocr"
    assert form == {
        "page_start": "1",
        "page_end": "2",
        "keep_region_tags": "true",
        "include_region_data": "false",
    }
    save_text.assert_called_once()
    save_json.assert_called_once_with(
        space,
        payload,
        "scan_ocr.json",
        ["document_ocr", "ocr", "json"],
    )


def test_extract_sends_strict_json_contract_and_preserves_parsed_result(input_pdf):
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"invoice_number": {"type": "string"}},
        "required": ["invoice_number"],
    }
    payload = {
        "request_id": "gen-7",
        "filename": "scan.pdf",
        "scope": "document",
        "response_format": "json",
        "output": '{"invoice_number":"48217"}',
        "parsed_json": {"invoice_number": "48217"},
        "ocr_model": "ATH-MaaS/OvisOCR2",
        "generation_model": "gemma4:latest",
        "pages_processed": 1,
        "total_pages": 1,
        "elapsed_seconds": 5.9,
        "ocr_elapsed_seconds": 1.5,
        "generation_elapsed_seconds": 4.4,
    }
    space = SimpleNamespace(space_id="space_extract")
    with (
        patch("document_ocr._resolve_input_path", return_value=input_pdf),
        patch("document_ocr._ready_preflight"),
        patch("document_ocr._request_json", return_value=payload) as request_json,
        patch("document_ocr._output_space", return_value=space),
        patch("document_ocr._save_json", side_effect=[
            "stash://space_extract/output",
            "stash://space_extract/response",
        ]),
    ):
        result = document_ocr.action_extract(
            {
                "prompt": "Extract the invoice number.",
                "response_format": "json",
                "json_schema": schema,
                "max_new_tokens": 512,
            }
        )

    form = request_json.call_args.kwargs["data"]
    assert request_json.call_args.args[1] == "/v1/generate"
    assert json.loads(form["json_schema"]) == schema
    assert form["scope"] == "document"
    assert form["response_format"] == "json"
    assert form["max_new_tokens"] == "512"
    assert result["data"]["parsed_json"] == {"invoice_number": "48217"}
    assert result["data"]["generation_model"] == "gemma4:latest"
    assert result["data"]["output_stash_ref"] == "stash://space_extract/output"
    assert result["data"]["response_json_stash_ref"] == "stash://space_extract/response"
    assert result["data"]["stash_ref"] == "stash://space_extract/output"


def test_page_scoped_json_returns_bounded_objects_and_primary_artifact(input_pdf):
    pages = [
        {
            "page_number": page_number,
            "output": json.dumps({"invoice_number": f"INV-{page_number:03d}"}),
            "parsed_json": {"invoice_number": f"INV-{page_number:03d}"},
            "elapsed_seconds": 0.25,
        }
        for page_number in range(1, 13)
    ]
    payload = {
        "request_id": "gen-pages",
        "filename": "scan.pdf",
        "scope": "page",
        "response_format": "json",
        "pages": pages,
        "pages_processed": len(pages),
        "total_pages": len(pages),
    }
    space = SimpleNamespace(space_id="space_extract")
    with (
        patch("document_ocr._resolve_input_path", return_value=input_pdf),
        patch("document_ocr._ready_preflight"),
        patch("document_ocr._request_json", return_value=payload),
        patch("document_ocr._output_space", return_value=space),
        patch(
            "document_ocr._save_json",
            side_effect=[
                "stash://space_extract/page-results",
                "stash://space_extract/response",
            ],
        ) as save_json,
    ):
        result = document_ocr.action_extract(
            {
                "prompt": "Extract the invoice number.",
                "scope": "page",
                "response_format": "json",
            }
        )

    data = result["data"]
    assert data["page_outputs_total"] == 12
    assert data["page_outputs_included"] == document_ocr.MAX_INLINE_PAGE_ITEMS
    assert data["page_outputs_truncated"] is True
    assert data["page_outputs_notice"] == (
        "Additional page results are available in the Stash artifacts."
    )
    assert data["page_outputs"][0]["parsed_json"] == {"invoice_number": "INV-001"}
    assert (
        document_ocr._compact_json_size(data["page_outputs"])
        <= document_ocr.MAX_INLINE_PAGE_OUTPUT_CHARS
    )
    assert data["page_results_stash_ref"] == "stash://space_extract/page-results"
    assert data["output_stash_ref"] == "stash://space_extract/page-results"
    assert data["stash_ref"] == "stash://space_extract/page-results"
    primary_payload = save_json.call_args_list[0].args[1]
    assert primary_payload["scope"] == "page"
    assert primary_payload["pages"][0]["parsed_json"] == {
        "invoice_number": "INV-001"
    }
    assert "output" not in primary_payload["pages"][0]
    assert len(primary_payload["pages"]) == 12
    assert save_json.call_args_list[1].args[1] is payload


def test_large_page_json_uses_truthful_omission_notice_without_stash(input_pdf):
    large_json = {"lines": ["recognized content" * 50] * 20}
    payload = {
        "scope": "page",
        "response_format": "json",
        "pages": [
            {
                "page_number": 1,
                "output": json.dumps(large_json),
                "parsed_json": large_json,
            }
        ],
    }
    with (
        patch("document_ocr._resolve_input_path", return_value=input_pdf),
        patch("document_ocr._ready_preflight"),
        patch("document_ocr._request_json", return_value=payload),
    ):
        result = document_ocr.action_extract(
            {
                "prompt": "Extract the page as JSON.",
                "scope": "page",
                "response_format": "json",
                "save_to_stash": False,
            }
        )

    data = result["data"]
    assert data["page_outputs_truncated"] is True
    assert data["page_outputs_notice"] == (
        "Additional page results were omitted and were not saved."
    )
    assert data["page_outputs"][0]["parsed_json_omitted"] is True
    assert "full result not saved" in data["page_outputs"][0]["output_excerpt"]
    assert (
        document_ocr._compact_json_size(data["page_outputs"])
        <= document_ocr.MAX_INLINE_PAGE_OUTPUT_CHARS
    )


def test_no_stash_truncation_notice_is_truthful(input_pdf):
    payload = {
        "scope": "document",
        "response_format": "text",
        "output": "x" * (document_ocr.INLINE_EXCERPT_CHARS + 100),
        "pages": [],
    }
    with (
        patch("document_ocr._resolve_input_path", return_value=input_pdf),
        patch("document_ocr._ready_preflight"),
        patch("document_ocr._request_json", return_value=payload),
    ):
        result = document_ocr.action_extract(
            {
                "prompt": "Summarize.",
                "save_to_stash": False,
            }
        )

    excerpt = result["data"]["output_excerpt"]
    assert len(excerpt) <= document_ocr.INLINE_EXCERPT_CHARS
    assert "full result not saved" in excerpt
    assert "full result saved to Stash" not in excerpt


def test_schema_requires_json_response_format(input_pdf):
    with patch("document_ocr._resolve_input_path", return_value=input_pdf), patch(
        "document_ocr._ready_preflight"
    ):
        with pytest.raises(ValueError, match="response_format=json"):
            document_ocr.action_extract(
                {
                    "prompt": "Extract fields.",
                    "response_format": "text",
                    "json_schema": {"type": "object"},
                }
            )


def test_preflight_failure_prevents_document_upload(input_pdf):
    unavailable = document_ocr.OvisToolError(
        "not ready", code="ovis_not_ready", retryable=True
    )
    with (
        patch("document_ocr._resolve_input_path", return_value=input_pdf),
        patch("document_ocr._ready_preflight", side_effect=unavailable),
        patch("document_ocr._request_json") as request_json,
    ):
        with pytest.raises(document_ocr.OvisToolError) as error:
            document_ocr.action_ocr({})
    assert error.value.code == "ovis_not_ready"
    request_json.assert_not_called()


def test_post_timeout_is_not_retryable_and_not_retried(monkeypatch):
    monkeypatch.setenv("OVIS_OCR_URL", "http://ocr.example.test:17860")
    with patch("document_ocr.requests.request", side_effect=requests.Timeout()) as request:
        with pytest.raises(document_ocr.OvisToolError) as error:
            document_ocr._request_json("POST", "/v1/ocr", files={}, data={})
    assert error.value.code == "ovis_timeout"
    assert error.value.retryable is False
    request.assert_called_once()
    assert request.call_args.kwargs["allow_redirects"] is False


def test_generate_backend_unavailable_preserves_service_error_code(monkeypatch):
    monkeypatch.setenv("OVIS_OCR_URL", "http://ocr.example.test:17860")
    response = FakeResponse(
        status_code=503,
        payload={
            "detail": {
                "code": "generate_backend_unavailable",
                "message": "The configured generation backend is unavailable.",
                "request_id": "req-7",
            }
        },
    )
    with patch("document_ocr.requests.request", return_value=response):
        with pytest.raises(document_ocr.OvisToolError) as error:
            document_ocr._request_json("POST", "/v1/generate", files={}, data={})
    assert error.value.code == "generate_backend_unavailable"
    assert error.value.retryable is True
    assert "generation backend" in str(error.value)


@pytest.mark.parametrize(
    ("status_code", "code"),
    (
        (502, "invalid_model_output"),
        (502, "invalid_backend_response"),
        (504, "generate_backend_timeout"),
    ),
)
def test_ambiguous_or_invalid_generation_failures_are_not_retryable(
    monkeypatch, status_code, code
):
    monkeypatch.setenv("OVIS_OCR_URL", "http://ocr.example.test:17860")
    response = FakeResponse(
        status_code=status_code,
        payload={"detail": {"code": code, "message": "Generation failed."}},
    )
    with patch("document_ocr.requests.request", return_value=response):
        with pytest.raises(document_ocr.OvisToolError) as error:
            document_ocr._request_json("POST", "/v1/generate", files={}, data={})
    assert error.value.code == code
    assert error.value.retryable is False


def test_server_busy_preserves_retry_after(monkeypatch):
    monkeypatch.setenv("OVIS_OCR_URL", "http://ocr.example.test:17860")
    response = FakeResponse(
        status_code=503,
        payload={
            "detail": {
                "code": "server_busy",
                "message": "The OCR worker is busy.",
            }
        },
        headers={"Retry-After": "5"},
    )
    with patch("document_ocr.requests.request", return_value=response):
        with pytest.raises(document_ocr.OvisToolError) as error:
            document_ocr._request_json("POST", "/v1/ocr", files={}, data={})
    assert error.value.code == "server_busy"
    assert error.value.retryable is True
    assert error.value.retry_after_seconds == 5


def test_archive_is_always_saved_to_stash(input_pdf):
    space = SimpleNamespace(space_id="space_archive")
    with (
        patch("document_ocr._resolve_input_path", return_value=input_pdf),
        patch("document_ocr._ready_preflight"),
        patch("document_ocr._request_archive", return_value=b"PK archive") as request,
        patch("document_ocr._output_space", return_value=space),
        patch("document_ocr._save_binary", return_value="stash://space_archive/archive") as save,
    ):
        result = document_ocr.action_archive({"save_to_stash": False})

    assert request.call_args.args[0] == "/v1/ocr/archive"
    assert result["data"]["archive_stash_ref"] == "stash://space_archive/archive"
    assert result["data"]["stash_ref"] == "stash://space_archive/archive"
    save.assert_called_once_with(
        space,
        b"PK archive",
        "scan_ocr.zip",
        "application/zip",
        ["document_ocr", "ocr", "archive"],
    )


def test_archive_upload_does_not_follow_redirects(monkeypatch):
    monkeypatch.setenv("OVIS_OCR_URL", "http://ocr.example.test:17860")
    response = FakeResponse(body=b"PK archive")
    with patch("document_ocr.requests.post", return_value=response) as post:
        archive = document_ocr._request_archive("/v1/ocr/archive", files={}, data={})
    assert archive == b"PK archive"
    assert post.call_args.kwargs["allow_redirects"] is False


def test_status_collects_health_readiness_and_capabilities():
    responses = [
        {"status": "ok", "current_device": "cpu", "last_inference_device": "cuda"},
        {"status": "ready", "ready": True},
        {
            "structured_json_extraction": True,
            "generation_backend": "ollama",
            "generation_model": "gemma4:latest",
        },
    ]
    with patch("document_ocr._request_json", side_effect=responses) as request:
        result = document_ocr.action_status({})
    assert request.call_count == 3
    assert request.call_args_list[0].args[1] == "/health/live"
    assert result["ok"] is True
    assert result["data"]["ready"] is True
    assert result["data"]["capabilities"]["generation_backend"] == "ollama"


def test_json_response_size_limit_is_enforced(monkeypatch):
    monkeypatch.setenv("OVIS_OCR_URL", "http://ocr.example.test:17860")
    response = FakeResponse(
        payload={},
        body=b"{}",
        headers={"Content-Length": str(document_ocr.MAX_JSON_RESPONSE_BYTES + 1)},
    )
    with patch("document_ocr.requests.request", return_value=response):
        with pytest.raises(document_ocr.OvisToolError) as error:
            document_ocr._request_json("GET", "/health")
    assert error.value.code == "ovis_response_too_large"
