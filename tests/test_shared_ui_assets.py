"""Shared UI branding assets must not depend on checkout symlink support."""

import importlib
from pathlib import Path

import pytest
from PIL import Image
from server_package_utils import load_canvas_server_package, load_server_package

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_ASSETS = PROJECT_ROOT / "jarvis-web" / "client" / "assets"


def _load_app(ui_name):
    alias = f"shared_assets_{ui_name.replace('-', '_')}_test_server"
    if ui_name == "jarvis-canvas":
        load_canvas_server_package(alias)
    else:
        load_server_package(alias, PROJECT_ROOT / ui_name / "server")
    app_module = importlib.import_module(f"{alias}.app")
    return app_module.create_app("cloud") if ui_name == "jarvis-canvas" else app_module.app


@pytest.mark.parametrize(
    ("ui_name", "asset_prefix", "route_endpoint"),
    (
        ("jarvis-canvas", "/static/assets", "shared_assets"),
        ("jarvis-memory", "/assets", "serve_brand_assets"),
        ("jarvis-intelligence", "/assets", "serve_brand_assets"),
        ("jarvis-docs", "/assets", "serve_brand_assets"),
    ),
)
def test_shared_brand_assets_use_explicit_canonical_route(
    ui_name, asset_prefix, route_endpoint
):
    app = _load_app(ui_name)
    endpoint, values = app.url_map.bind("").match(
        f"{asset_prefix}/jarvis-voice.png"
    )

    assert endpoint == route_endpoint
    assert values == {"path": "jarvis-voice.png"}

    with app.test_client() as client:
        png = client.get(f"{asset_prefix}/jarvis-voice.png")
        svg = client.get(f"{asset_prefix}/jarvis-hud-logo.svg")
        touch_icon = client.get(f"{asset_prefix}/apple-touch-icon.png")

    assert png.status_code == 200
    assert png.data == (CANONICAL_ASSETS / "jarvis-voice.png").read_bytes()
    assert svg.status_code == 200
    assert svg.data == (CANONICAL_ASSETS / "jarvis-hud-logo.svg").read_bytes()
    assert touch_icon.status_code == 200
    assert touch_icon.data == (CANONICAL_ASSETS / "apple-touch-icon.png").read_bytes()


def test_apple_touch_icon_has_opaque_jarvis_black_background():
    icon_path = CANONICAL_ASSETS / "apple-touch-icon.png"

    with Image.open(icon_path) as icon:
        assert icon.size == (180, 180)
        assert icon.mode == "RGB"
        assert icon.getpixel((0, 0)) == (10, 10, 15)


def test_pages_reference_dedicated_apple_touch_icon():
    pages = (
        PROJECT_ROOT / "jarvis-web" / "client" / "index.html",
        PROJECT_ROOT / "jarvis-web" / "client" / "login.html",
        PROJECT_ROOT / "jarvis-web" / "client" / "logs.html",
        PROJECT_ROOT / "jarvis-canvas" / "client" / "templates" / "base.html",
        PROJECT_ROOT / "jarvis-docs" / "client" / "index.html",
        PROJECT_ROOT / "jarvis-docs" / "client" / "login.html",
    )

    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert 'rel="apple-touch-icon" sizes="180x180"' in html
        assert "apple-touch-icon.png" in html
