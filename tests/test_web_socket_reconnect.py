"""Regression coverage for long-outage WebSocket recovery and vendor assets."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_socket_retries_until_server_returns():
    source = (ROOT / "jarvis-web" / "client" / "js" / "socket.js").read_text(
        encoding="utf-8"
    )

    assert "reconnectionAttempts: Infinity" in source
    assert "reconnectionAttempts: 10" not in source


def test_vendored_socket_bundle_does_not_reference_missing_source_map():
    vendor_dir = ROOT / "jarvis-web" / "client" / "vendor"
    bundle = (vendor_dir / "socket.io.min.js").read_text(encoding="utf-8")

    assert "sourceMappingURL=socket.io.min.js.map" not in bundle
    assert not (vendor_dir / "socket.io.min.js.map").exists()
