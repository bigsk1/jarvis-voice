"""Protected Canvas PDF export and xAI public-share routes."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import OrderedDict
from io import BytesIO

from flask import Blueprint, current_app, jsonify, request, send_file
from werkzeug.utils import secure_filename

from server.pages import get_page_path
from server.services.pdf_export import has_blocking_findings, prepare_canvas_pdf
from server.services.xai_pdf_share import (
    ALLOWED_TTL_DAYS,
    XaiPdfShareDisabled,
    XaiPdfShareError,
    XaiPdfShareService,
    get_xai_pdf_share_status,
)


pdf_shares_bp = Blueprint("pdf_shares", __name__)
_PAGE_ID_RE = re.compile(r"^page_[A-Za-z0-9_-]+$")
share_service = XaiPdfShareService()
_PDF_CACHE_MAX_ENTRIES = 8
_PDF_CACHE: OrderedDict[str, tuple[dict, bytes]] = OrderedDict()
_PDF_CACHE_LOCK = threading.RLock()


class CanvasPdfRenderError(RuntimeError):
    """Safe route-level wrapper for unsupported PDF source content."""


def _load_page(page_id: str) -> dict | None:
    if not _PAGE_ID_RE.fullmatch(page_id):
        return None
    path = get_page_path(page_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _pdf_download_name(page: dict) -> str:
    stem = secure_filename(str(page.get("title") or "canvas-page")) or "canvas-page"
    return f"{stem[:100]}.pdf"


def _source_sha256(page: dict) -> str:
    public_projection_source = {
        key: page.get(key)
        for key in ("title", "content", "tags", "created", "updated")
    }
    canonical = json.dumps(
        public_projection_source,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _prepare(page_id: str):
    page = _load_page(page_id)
    if page is None:
        return None, None, None
    cache_key = _source_sha256(page)
    with _PDF_CACHE_LOCK:
        cached = _PDF_CACHE.get(cache_key)
        if cached is not None:
            _PDF_CACHE.move_to_end(cache_key)
            projection, payload = cached
            return page, projection, payload
    try:
        projection, payload = prepare_canvas_pdf(page)
    except (OSError, RuntimeError, ValueError):
        current_app.logger.exception("Canvas PDF rendering failed for page %s", page_id)
        raise CanvasPdfRenderError(
            "This Canvas page could not be converted to PDF. Review its formatting and try again."
        ) from None
    with _PDF_CACHE_LOCK:
        _PDF_CACHE[cache_key] = (projection, payload)
        _PDF_CACHE.move_to_end(cache_key)
        while len(_PDF_CACHE) > _PDF_CACHE_MAX_ENTRIES:
            _PDF_CACHE.popitem(last=False)
    return page, projection, payload


def _safe_error(message: str, status_code: int):
    return jsonify({"ok": False, "error": message}), status_code


@pdf_shares_bp.route("/api/canvas-exports/pages/<page_id>/pdf", methods=["GET"])
def export_page_pdf(page_id: str):
    try:
        page, _projection, payload = _prepare(page_id)
    except CanvasPdfRenderError as exc:
        return _safe_error(str(exc), 422)
    if page is None:
        return _safe_error("Page not found", 404)

    disposition = request.args.get("disposition", "attachment").strip().lower()
    if disposition not in {"attachment", "inline"}:
        return _safe_error("disposition must be inline or attachment", 400)
    return send_file(
        BytesIO(payload),
        mimetype="application/pdf",
        as_attachment=disposition == "attachment",
        download_name=_pdf_download_name(page),
        max_age=0,
    )


@pdf_shares_bp.route("/api/xai-pdf-shares/status", methods=["GET"])
def xai_pdf_share_status():
    return jsonify({"ok": True, **get_xai_pdf_share_status()})


@pdf_shares_bp.route("/api/xai-pdf-shares/pages/<page_id>/preview", methods=["POST"])
def preview_xai_pdf_share(page_id: str):
    try:
        page, projection, payload = _prepare(page_id)
    except CanvasPdfRenderError as exc:
        return _safe_error(str(exc), 422)
    if page is None:
        return _safe_error("Page not found", 404)
    return jsonify(
        {
            "ok": True,
            "page_id": page_id,
            "title": projection["title"],
            "findings": projection["findings"],
            "can_publish": not has_blocking_findings(projection),
            "pdf": projection["pdf"],
            "pdf_sha256": hashlib.sha256(payload).hexdigest(),
            "source_sha256": _source_sha256(page),
            "preview_url": f"/api/canvas-exports/pages/{page_id}/pdf?disposition=inline",
        }
    )


@pdf_shares_bp.route("/api/xai-pdf-shares/pages/<page_id>", methods=["POST"])
def publish_xai_pdf_share(page_id: str):
    data = request.get_json(silent=True) or {}
    if data.get("confirmed") is not True:
        return _safe_error("Confirm that this PDF will be public before publishing.", 400)
    try:
        ttl_days = int(data.get("ttl_days", get_xai_pdf_share_status()["default_ttl_days"]))
    except (TypeError, ValueError):
        return _safe_error("Expiration must be 1, 7, or 30 days.", 400)
    if ttl_days not in ALLOWED_TTL_DAYS:
        return _safe_error("Expiration must be 1, 7, or 30 days.", 400)

    try:
        page, projection, payload = _prepare(page_id)
    except CanvasPdfRenderError as exc:
        return _safe_error(str(exc), 422)
    if page is None:
        return _safe_error("Page not found", 404)
    if has_blocking_findings(projection):
        return jsonify(
            {
                "ok": False,
                "error": "Publishing was blocked by the PDF safety check.",
                "findings": projection["findings"],
            }
        ), 422

    pdf_sha256 = hashlib.sha256(payload).hexdigest()
    expected_source_sha256 = str(data.get("expected_source_sha256") or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{64}", expected_source_sha256):
        return _safe_error("Preview this PDF again before publishing.", 400)
    if expected_source_sha256 != _source_sha256(page):
        return _safe_error("The Canvas page changed after preview. Review the new PDF before publishing.", 409)

    try:
        record = share_service.publish(
            page_id=page_id,
            title=projection["title"],
            source_updated_at=projection.get("updated"),
            pdf_payload=payload,
            projection=projection,
            ttl_days=ttl_days,
            pdf_sha256=pdf_sha256,
        )
    except XaiPdfShareDisabled as exc:
        return _safe_error(str(exc), 503)
    except XaiPdfShareError as exc:
        return _safe_error(str(exc), 502)

    return jsonify({"ok": True, "share": record}), 201


@pdf_shares_bp.route("/api/xai-pdf-shares/pages/<page_id>", methods=["GET"])
def list_xai_pdf_shares(page_id: str):
    if _load_page(page_id) is None:
        return _safe_error("Page not found", 404)
    try:
        shares = share_service.list_for_page(page_id)
    except XaiPdfShareError as exc:
        return _safe_error(str(exc), 500)
    return jsonify({"ok": True, "shares": shares})


@pdf_shares_bp.route("/api/xai-pdf-shares/<share_id>", methods=["DELETE"])
def revoke_xai_pdf_share(share_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", share_id):
        return _safe_error("Invalid share identifier", 400)
    try:
        record = share_service.revoke(share_id)
    except XaiPdfShareDisabled as exc:
        return _safe_error(str(exc), 503)
    except XaiPdfShareError as exc:
        return _safe_error(str(exc), 502)
    return jsonify({"ok": True, "share": record})
