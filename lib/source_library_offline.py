"""Strict host-local readiness and an optional real, network-blocked exercise."""

from __future__ import annotations

import ipaddress
import socket
import tempfile
from contextlib import contextmanager
from urllib.parse import urlsplit

from config_loader import config_scope, get_config_value, get_project_root
from embeddings import get_embedding, get_embedding_base_urls
from ollama_utils import (
    OLLAMA_EXECUTION_LOCAL_DAEMON,
    get_ollama_execution_class,
    get_ollama_request_urls,
    resolve_ollama_model,
)
from source_library import LibraryError, SourceLibrary


def _is_loopback_url(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    if parsed.hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        return False


def preflight() -> dict:
    """Reject all configured non-loopback embedding/LLM fallback hosts."""
    provider = str(get_config_value("LLM_PROVIDER", "") or "").strip().lower()
    model = resolve_ollama_model("local") if provider == "ollama" else ""
    embedding_hosts = get_embedding_base_urls()
    llm_hosts = get_ollama_request_urls(
        cloud_access=False,
        base_url=get_config_value("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        include_localhost_fallback=True,
    ) if provider == "ollama" else []
    client = get_project_root() / "jarvis-web" / "client"
    asset_paths = [client / name for name in (
        "library.html", "js/library.js", "js/utils.js", "css/library.css", "css/fonts.css",
    )]
    local_assets = all(path.is_file() for path in asset_paths) and all(
        not any(value in path.read_text().lower() for value in ("https://", "http://", "//cdn"))
        for path in asset_paths
    )
    checks = {
        "local_llm_provider": provider == "ollama",
        "local_model": bool(model) and get_ollama_execution_class(model, "local") == OLLAMA_EXECUTION_LOCAL_DAEMON,
        "embedding_hosts_loopback": bool(embedding_hosts) and all(map(_is_loopback_url, embedding_hosts)),
        "llm_hosts_loopback": bool(llm_hosts) and all(map(_is_loopback_url, llm_hosts)),
        "library_assets_self_hosted": local_assets,
    }
    return {"ready": all(checks.values()), "checks": checks, "provider": provider, "model": model}


@contextmanager
def _no_external_sockets():
    """Allow a local Ollama daemon, but make outbound Internet impossible here."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded_connect(self, address):
        if isinstance(address, tuple):
            try:
                if not ipaddress.ip_address(address[0]).is_loopback:
                    raise OSError("Offline exercise blocked a non-loopback connection.")
            except ValueError as exc:
                raise OSError("Offline exercise blocked an unresolved host.") from exc
        return original_connect(self, address)

    def guarded_connect_ex(self, address):
        if isinstance(address, tuple):
            try:
                if not ipaddress.ip_address(address[0]).is_loopback:
                    raise OSError("Offline exercise blocked a non-loopback connection.")
            except ValueError as exc:
                raise OSError("Offline exercise blocked an unresolved host.") from exc
        return original_connect_ex(self, address)

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex


def exercise() -> dict:
    """Use a temporary library and a real local model with external sockets blocked."""
    report = preflight()
    if not report["ready"]:
        raise LibraryError("Offline preflight failed; use only loopback Ollama hosts and a local model.")
    with tempfile.TemporaryDirectory(prefix="jarvis-offline-library-") as temporary:
        with config_scope("local", {"SOURCE_LIBRARY_DIR": temporary}):
            with _no_external_sockets():
                library = SourceLibrary("local")
                source = library.save(b"# Emergency notes\nThe offline checkpoint is CEDAR-731.", "offline.md")
                if "<h1>Emergency notes</h1>" not in library.rendered_markdown(source["source_id"]):
                    raise LibraryError("Offline Markdown rendering failed.")
                if not library.search("CEDAR-731", semantic=False)["passages"]:
                    raise LibraryError("Offline keyword retrieval failed.")
                import fitz

                with fitz.open() as pdf:
                    pdf.new_page().insert_text((72, 72), "Offline PDF atlas")
                    pdf_source = library.save(pdf.tobytes(), "offline.pdf")
                if not library.rendered_pdf_page(pdf_source["source_id"], 1).startswith(b"\x89PNG"):
                    raise LibraryError("Offline PDF rendering failed.")
                from llm_provider import create_configured_provider

                _, _, provider = create_configured_provider(mode="local", disable_server_side_tools=True)
                provider.force_no_thinking = True
                answer = provider.chat(
                    "From this retrieved excerpt, what is the offline checkpoint? "
                    "Excerpt: The offline checkpoint is CEDAR-731.",
                    system_prompt="Answer only with the checkpoint code from the supplied excerpt.",
                    max_tokens=256,
                )
                if "CEDAR-731" not in answer:
                    raise LibraryError(
                        "The local LLM did not ground its answer in the synthetic excerpt: "
                        + repr(str(answer)[:160])
                    )
                if len(get_embedding("offline checkpoint", role="query")) != 768:
                    raise LibraryError("The local embedding model did not return 768 dimensions.")
    return {**report, "exercise_passed": True, "external_connections_blocked": True}
