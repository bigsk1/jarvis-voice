"""Regression tests for canonical price-alert storage and API wiring."""

from __future__ import annotations

import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from fastapi import HTTPException

from api.routes import config as config_routes
from lib import price_alert_config
from skills import price_alert


def _set_paths(monkeypatch: pytest.MonkeyPatch, root: Path) -> tuple[Path, Path, Path]:
    target = root / "data" / "price-alerts.yaml"
    legacy = root / "config" / "price-alerts.yaml"
    example = root / "config" / "price-alerts.yaml.example"
    monkeypatch.setattr(price_alert_config, "PRICE_ALERT_PATH", target)
    monkeypatch.setattr(price_alert_config, "LEGACY_PRICE_ALERT_PATH", legacy)
    monkeypatch.setattr(price_alert_config, "PRICE_ALERT_EXAMPLE_PATH", example)
    return target, legacy, example


def _valid_config(symbol: str = "BTC") -> dict:
    return {
        "settings": {
            "check_interval_minutes": 5,
            "cooldown_hours": 2,
            "jarvis_api_url": "http://localhost:8880",
        },
        "sources": {"crypto": {"api": "coingecko"}},
        "watchlist": {
            "crypto": [
                {
                    "symbol": symbol,
                    "enabled": True,
                    "conditions": [{"type": "above", "value": 100_000}],
                }
            ],
            "stocks": [],
        },
    }


def test_existing_data_wins_over_legacy(monkeypatch, tmp_path):
    target, legacy, _example = _set_paths(monkeypatch, tmp_path)
    target.parent.mkdir(parents=True)
    legacy.parent.mkdir(parents=True)
    target.write_text(yaml.safe_dump(_valid_config("ETH")))
    legacy.write_text(yaml.safe_dump(_valid_config("BTC")))

    loaded = price_alert_config.load_price_alert_config()

    assert loaded["watchlist"]["crypto"][0]["symbol"] == "ETH"


def test_valid_legacy_file_is_copied_losslessly(monkeypatch, tmp_path):
    target, legacy, _example = _set_paths(monkeypatch, tmp_path)
    legacy.parent.mkdir(parents=True)
    content = "# personal comments stay intact\n" + yaml.safe_dump(_valid_config())
    legacy.write_text(content)

    assert price_alert_config.ensure_price_alert_config() == target
    assert target.read_text() == content
    assert legacy.read_text() == content


def test_missing_state_seeds_safe_empty_example(monkeypatch, tmp_path):
    target, _legacy, example = _set_paths(monkeypatch, tmp_path)
    example.parent.mkdir(parents=True)
    example.write_text(yaml.safe_dump(price_alert_config.DEFAULT_PRICE_ALERT_CONFIG))

    loaded = price_alert_config.load_price_alert_config()

    assert target.exists()
    assert loaded["watchlist"] == {"crypto": [], "stocks": []}


def test_missing_state_without_example_generates_safe_default(monkeypatch, tmp_path):
    target, _legacy, _example = _set_paths(monkeypatch, tmp_path)

    loaded = price_alert_config.load_price_alert_config()

    assert target.exists()
    assert loaded["watchlist"] == {"crypto": [], "stocks": []}


def test_invalid_legacy_file_does_not_create_target(monkeypatch, tmp_path):
    target, legacy, _example = _set_paths(monkeypatch, tmp_path)
    legacy.parent.mkdir(parents=True)
    legacy.write_text("watchlist: not-a-mapping\n")

    with pytest.raises(price_alert_config.PriceAlertConfigError):
        price_alert_config.ensure_price_alert_config()

    assert not target.exists()


def test_invalid_existing_data_is_not_replaced(monkeypatch, tmp_path):
    target, _legacy, example = _set_paths(monkeypatch, tmp_path)
    target.parent.mkdir(parents=True)
    example.parent.mkdir(parents=True)
    invalid_content = "watchlist:\n  crypto: wrong\n"
    target.write_text(invalid_content)
    example.write_text(yaml.safe_dump(price_alert_config.DEFAULT_PRICE_ALERT_CONFIG))

    with pytest.raises(price_alert_config.PriceAlertConfigError):
        price_alert_config.load_price_alert_config()

    assert target.read_text() == invalid_content


def test_failed_validation_preserves_previous_file(monkeypatch, tmp_path):
    target, _legacy, _example = _set_paths(monkeypatch, tmp_path)
    target.parent.mkdir(parents=True)
    original = yaml.safe_dump(_valid_config())
    target.write_text(original)

    with pytest.raises(price_alert_config.PriceAlertConfigError):
        price_alert_config.save_price_alert_config({"watchlist": {"crypto": "bad"}})

    assert target.read_text() == original


def test_concurrent_initializers_converge(monkeypatch, tmp_path):
    target, legacy, _example = _set_paths(monkeypatch, tmp_path)
    legacy.parent.mkdir(parents=True)
    legacy.write_text(yaml.safe_dump(_valid_config()))

    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(lambda _index: price_alert_config.ensure_price_alert_config(), range(24)))

    assert paths == [target] * 24
    assert price_alert_config.load_price_alert_config()["watchlist"]["crypto"][0]["symbol"] == "BTC"


def test_save_preserves_supported_extra_fields(monkeypatch, tmp_path):
    target, _legacy, _example = _set_paths(monkeypatch, tmp_path)
    config = _valid_config()
    config["future_extension"] = {"enabled": True}

    price_alert_config.save_price_alert_config(config)

    loaded = yaml.safe_load(target.read_text())
    assert loaded["future_extension"] == {"enabled": True}


def test_config_api_uses_shared_loader_and_truthful_source():
    with patch.object(config_routes, "load_price_alert_config", return_value=_valid_config()) as loader:
        response = asyncio.run(config_routes.get_price_alerts_config())

    loader.assert_called_once_with()
    assert response["ok"] is True
    assert response["source"] == "data/price-alerts.yaml"
    assert response["watchlist"]["crypto"][0]["symbol"] == "BTC"


def test_threshold_api_uses_shared_loader_and_truthful_source():
    with patch.object(config_routes, "load_price_alert_config", return_value=_valid_config()) as loader:
        response = asyncio.run(config_routes.get_price_thresholds())

    loader.assert_called_once_with()
    assert response["source"] == "data/price-alerts.yaml"
    assert response["thresholds"]["crypto"]["BTC"]["conditions"]["above"] == 100_000


def test_config_api_does_not_expose_storage_error_details():
    error = price_alert_config.PriceAlertConfigError("secret host path: /private/config")
    with patch.object(config_routes, "load_price_alert_config", side_effect=error):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(config_routes.get_price_alerts_config())

    assert raised.value.status_code == 500
    assert "/private/config" not in raised.value.detail


def test_tool_list_reports_canonical_data_path(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["price_alert.py", json.dumps({"action": "list"})])
    with (
        patch.object(price_alert, "load_config"),
        patch.object(price_alert, "load_config_file", return_value=_valid_config()),
    ):
        price_alert.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["config_file"].endswith("/data/price-alerts.yaml")


def test_tool_save_failure_returns_explicit_error(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "price_alert.py",
            json.dumps(
                {
                    "action": "add",
                    "symbol": "ETH",
                    "condition": "above",
                    "value": 5_000,
                }
            ),
        ],
    )
    empty = price_alert_config.validate_price_alert_config({"watchlist": {}})
    with (
        patch.object(price_alert, "load_config"),
        patch.object(price_alert, "load_config_file", return_value=empty),
        patch.object(price_alert, "save_price_alert_config", side_effect=PermissionError("read only")),
        pytest.raises(SystemExit) as raised,
    ):
        price_alert.main()

    payload = json.loads(capsys.readouterr().out)
    assert raised.value.code == 1
    assert payload["ok"] is False
    assert "read only" in payload["error"]


def test_tool_add_update_remove_persist_through_shared_storage(monkeypatch, tmp_path):
    _set_paths(monkeypatch, tmp_path)
    price_alert_config.save_price_alert_config({"watchlist": {}})

    config = price_alert_config.load_price_alert_config()
    price_alert.add_alert(config, "BTC", "above", 100_000)
    saved = price_alert_config.load_price_alert_config()
    assert saved["watchlist"]["crypto"][0]["conditions"][0]["value"] == 100_000

    saved["_last_triggered"] = {"BTC": "runtime-only"}
    price_alert.update_alert(saved, "BTC", "above", 110_000)
    updated = price_alert_config.load_price_alert_config()
    assert updated["watchlist"]["crypto"][0]["conditions"][0]["value"] == 110_000
    assert "_last_triggered" not in updated

    price_alert.remove_alert(updated, "BTC")
    removed = price_alert_config.load_price_alert_config()
    assert removed["watchlist"]["crypto"] == []
