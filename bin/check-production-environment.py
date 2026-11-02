#!/usr/bin/env python3
"""Check a clean production install without operator config or provider calls."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PUBLIC_IGNORED_GUIDES = {"data/workflows/AGENTS.md"}


def check_checkout(root: Path, environment: Path | None = None) -> None:
    """Reject force-tracked ignored files and existing private runtime artifacts."""
    root = root.resolve()
    commands = (
        ["git", "ls-files", "--cached", "--ignored", "--exclude-standard", "-z"],
        ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"],
    )
    for number, command in enumerate(commands):
        result = subprocess.run(command, cwd=root, capture_output=True, check=True)
        paths = [value.decode() for value in result.stdout.split(b"\0") if value]
        if not number:
            # This long-standing public workflow-authoring guide predates the
            # generic AGENTS.md ignore rule. Other ignored paths still fail.
            paths = [value for value in paths if value not in PUBLIC_IGNORED_GUIDES]
        else:
            # A newly created venv and interpreter bytecode are expected. Do not
            # exempt logs, runtime data, config, OAuth caches, or private tools.
            candidate = environment.resolve() if environment else None
            allowed_environment = (candidate if candidate and candidate != root
                                   and candidate.is_relative_to(root) else None)
            paths = [value for value in paths
                     if "__pycache__" not in Path(value).parts
                     and not (allowed_environment and
                              (root / value).resolve().is_relative_to(allowed_environment))]
        if paths:
            # Report counts only: neither credential contents nor private names
            # belong in a failed CI run's log.
            kind = "tracked ignored" if not number else "private/runtime"
            raise RuntimeError(f"Found {len(paths)} {kind} checkout path(s); use a clean checkout.")


def smoke_environment(home: Path) -> dict[str, str]:
    """Pass OS essentials, never the caller's application/provider credentials."""
    keep = ("PATH", "LANG", "LC_ALL", "LD_LIBRARY_PATH", "SYSTEMROOT", "WINDIR", "TMPDIR", "TEMP")
    environment = {key: os.environ[key] for key in keep if key in os.environ}
    environment.update(HOME=str(home), JARVIS_MODE="cloud", PYTHONDONTWRITEBYTECODE="1",
                       OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    return environment


def block_network(event: str, _arguments: tuple) -> None:
    """An import/smoke check must never silently become a live provider check."""
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("Network access is disabled during the production smoke check.")


def runtime_smoke(root: Path) -> None:
    """Import actual runtime packages and serve health in-process, without hardware."""
    import importlib
    import importlib.metadata

    sys.addaudithook(block_network)
    # Native entry points support both package imports and legacy lib imports.
    sys.path[:0] = [str(root), str(root / "lib")]

    # Prove that the check did not obtain its dependencies from the dev group.
    dev_tools = {"pytest", "pytest-xdist", "ruff", "pyrefly"}
    installed = {item.metadata.get("Name", "").lower() for item in importlib.metadata.distributions()}
    if dev_tools & installed:
        raise RuntimeError("Development-only tools are installed in the production check environment.")

    modules = (
        "rich.console", "textual", "fastapi", "uvicorn", "pydantic", "flask", "flask_socketio",
        "anthropic", "openai", "xai_sdk", "google.genai", "numpy", "onnxruntime",
        "openwakeword.model", "faster_whisper", "sounddevice", "soundfile", "speexdsp_ns",
        "fpdf", "fitz", "PIL.Image", "cryptography", "filelock", "jsonschema", "yaml",
        "lib.config_loader", "lib.tts_normalizer", "lib.memory_db",
    )
    for name in modules:
        importlib.import_module(name)
        print(f"Imported {name}", flush=True)

    # Bundled ONNX assets are part of the pinned package's installation contract.
    # Use silence, not a microphone or a downloaded STT model.
    import numpy as np
    import openwakeword
    from openwakeword.model import Model

    model_path = openwakeword.models["hey_jarvis"]["model_path"]
    wake = Model(wakeword_model_paths=[model_path], vad_threshold=0.4)
    prediction = wake.predict(np.zeros(1280, dtype=np.int16))
    if not prediction:
        raise RuntimeError("The bundled wake-word model returned no prediction.")
    print("Bundled wake-word model loaded and processed silent audio", flush=True)

    from fastapi.testclient import TestClient

    print("No operator config is supplied; missing-config diagnostics below are expected.", flush=True)
    from api.server import PROMETHEUS_AVAILABLE, app

    if not PROMETHEUS_AVAILABLE:
        raise RuntimeError("Production API metrics dependency is unavailable.")
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.get("/api/health")
    expected_version = (root / "VERSION").read_text().strip()
    if (response.status_code != 200 or response.json().get("status") != "ok"
            or response.json().get("version") != expected_version):
        raise RuntimeError("The production API health check failed.")
    print("Production API health passed without opening a listener", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-checkout", action="store_true", help="Check checkout privacy before installation")
    parser.add_argument("--smoke-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    check_checkout(root, environment=Path(sys.prefix))
    if args.smoke_child:
        runtime_smoke(root)
        return 0
    print("Checkout contains no tracked ignored files or private runtime artifacts", flush=True)
    if args.check_checkout:
        return 0
    with tempfile.TemporaryDirectory(prefix="jarvis-production-smoke-") as temporary:
        result = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).resolve()), "--smoke-child"],
            cwd=root, env=smoke_environment(Path(temporary)), timeout=120, check=False,
        )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
