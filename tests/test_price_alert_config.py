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

from api.routes import price_alerts as price_alert_routes
from lib import price_alert_config, rate_limiter
from skills import price_alert


def _set_paths(monkeypatch: pytest.MonkeyPatch, root: Path) -> tuple[Path, Path]:
    target = root / "data" / "price-alerts.yaml"
    example = root / "data" / "price-alerts.yaml.example"
    monkeypatch.setattr(price_alert_config, "PRICE_ALERT_PATH", target)
    monkeypatch.setattr(price_alert_config, "PRICE_ALERT_EXAMPLE_PATH", example)
    return target, example


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


def test_existing_data_wins_over_example(monkeypatch, tmp_path):
    target, example = _set_paths(monkeypatch, tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text(yaml.safe_dump(_valid_config("ETH")))
    example.write_text(yaml.safe_dump(_valid_config("BTC")))

    loaded = price_alert_config.load_price_alert_config()

    assert loaded["watchlist"]["crypto"][0]["symbol"] == "ETH"


def test_valid_data_example_is_copied_losslessly(monkeypatch, tmp_path):
    target, example = _set_paths(monkeypatch, tmp_path)
    example.parent.mkdir(parents=True)
    content = "# personal comments stay intact\n" + yaml.safe_dump(_valid_config())
    example.write_text(content)

    assert price_alert_config.ensure_price_alert_config() == target
    assert target.read_text() == content
    assert example.read_text() == content


def test_missing_state_seeds_safe_empty_example(monkeypatch, tmp_path):
    target, example = _set_paths(monkeypatch, tmp_path)
    example.parent.mkdir(parents=True)
    example.write_text(yaml.safe_dump(price_alert_config.DEFAULT_PRICE_ALERT_CONFIG))

    loaded = price_alert_config.load_price_alert_config()

    assert target.exists()
    assert loaded["watchlist"] == {"crypto": [], "stocks": []}


def test_missing_state_without_example_generates_safe_default(monkeypatch, tmp_path):
    target, _example = _set_paths(monkeypatch, tmp_path)

    loaded = price_alert_config.load_price_alert_config()

    assert target.exists()
    assert loaded["watchlist"] == {"crypto": [], "stocks": []}


def test_invalid_data_example_does_not_create_target(monkeypatch, tmp_path):
    target, example = _set_paths(monkeypatch, tmp_path)
    example.parent.mkdir(parents=True)
    example.write_text("watchlist: not-a-mapping\n")

    with pytest.raises(price_alert_config.PriceAlertConfigError):
        price_alert_config.ensure_price_alert_config()

    assert not target.exists()


def test_invalid_existing_data_is_not_replaced(monkeypatch, tmp_path):
    target, example = _set_paths(monkeypatch, tmp_path)
    target.parent.mkdir(parents=True)
    example.parent.mkdir(parents=True, exist_ok=True)
    invalid_content = "watchlist:\n  crypto: wrong\n"
    target.write_text(invalid_content)
    example.write_text(yaml.safe_dump(price_alert_config.DEFAULT_PRICE_ALERT_CONFIG))

    with pytest.raises(price_alert_config.PriceAlertConfigError):
        price_alert_config.load_price_alert_config()

    assert target.read_text() == invalid_content


def test_failed_validation_preserves_previous_file(monkeypatch, tmp_path):
    target, _example = _set_paths(monkeypatch, tmp_path)
    target.parent.mkdir(parents=True)
    original = yaml.safe_dump(_valid_config())
    target.write_text(original)

    with pytest.raises(price_alert_config.PriceAlertConfigError):
        price_alert_config.save_price_alert_config({"watchlist": {"crypto": "bad"}})

    assert target.read_text() == original


def test_concurrent_initializers_converge(monkeypatch, tmp_path):
    target, example = _set_paths(monkeypatch, tmp_path)
    example.parent.mkdir(parents=True)
    example.write_text(yaml.safe_dump(_valid_config()))

    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(lambda _index: price_alert_config.ensure_price_alert_config(), range(24)))

    assert paths == [target] * 24
    assert price_alert_config.load_price_alert_config()["watchlist"]["crypto"][0]["symbol"] == "BTC"


def test_save_preserves_supported_extra_fields(monkeypatch, tmp_path):
    target, _example = _set_paths(monkeypatch, tmp_path)
    config = _valid_config()
    config["future_extension"] = {"enabled": True}

    price_alert_config.save_price_alert_config(config)

    loaded = yaml.safe_load(target.read_text())
    assert loaded["future_extension"] == {"enabled": True}


def test_price_alert_api_uses_shared_loader_and_truthful_source():
    with patch.object(price_alert_routes, "load_price_alert_config", return_value=_valid_config()) as loader:
        response = asyncio.run(price_alert_routes.get_price_alerts())

    loader.assert_called_once_with()
    assert response["ok"] is True
    assert response["source"] == "data/price-alerts.yaml"
    assert response["watchlist"]["crypto"][0]["symbol"] == "BTC"


def test_price_alert_api_uses_first_class_routes():
    paths = {route.path for route in price_alert_routes.router.routes}

    assert "/api/price-alerts" in paths
    assert "/api/price-alerts/thresholds" in paths
    assert not any(path.startswith("/api/config/") for path in paths)


def test_price_alert_api_has_dedicated_30_rpm_bucket(monkeypatch):
    calls = []

    def fake_get_int(key, default):
        calls.append((key, default))
        return default

    monkeypatch.setattr("lib.config_loader.get_int", fake_get_int)

    assert rate_limiter._bucket_for_path("/api/price-alerts") == "price-alerts"
    assert (
        rate_limiter._bucket_for_path("/api/price-alerts/thresholds")
        == "price-alerts"
    )
    assert rate_limiter._rpm_for_bucket("price-alerts") == 30
    assert calls == [("API_RATE_LIMIT_PRICE_ALERTS_PER_MINUTE", -1)]


def test_threshold_api_uses_shared_loader_and_truthful_source():
    with patch.object(price_alert_routes, "load_price_alert_config", return_value=_valid_config()) as loader:
        response = asyncio.run(price_alert_routes.get_price_thresholds())

    loader.assert_called_once_with()
    assert response["source"] == "data/price-alerts.yaml"
    assert response["thresholds"]["crypto"]["BTC"]["conditions"]["above"] == 100_000


def test_price_alert_api_does_not_expose_storage_error_details():
    error = price_alert_config.PriceAlertConfigError("secret host path: /private/config")
    with patch.object(price_alert_routes, "load_price_alert_config", side_effect=error):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(price_alert_routes.get_price_alerts())

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


def test_percent_change_update_refreshes_message_and_uses_percent_format(monkeypatch, tmp_path):
    _set_paths(monkeypatch, tmp_path)
    price_alert_config.save_price_alert_config({
        "watchlist": {
            "crypto": [
                {
                    "symbol": "BTC",
                    "enabled": True,
                    "conditions": [
                        {
                            "type": "percent_change_24h",
                            "value": 5,
                            "message": "BTC moved 5%",
                        }
                    ],
                }
            ],
            "stocks": [],
        }
    })

    config = price_alert_config.load_price_alert_config()
    speech = price_alert.update_alert(config, "BTC", "percent_change_24h", 10.5)
    updated = price_alert_config.load_price_alert_config()
    condition = updated["watchlist"]["crypto"][0]["conditions"][0]

    assert speech == "Updated BTC percent_change_24h alert: 5% → 10.5%"
    assert condition["value"] == 10.5
    assert condition["message"] == "BTC moved 10.5%"


def test_percent_change_add_uses_percent_message_and_speech(monkeypatch, tmp_path):
    _set_paths(monkeypatch, tmp_path)
    price_alert_config.save_price_alert_config({"watchlist": {}})

    config = price_alert_config.load_price_alert_config()
    speech = price_alert.add_alert(config, "BTC", "percent_change_24h", 5.5)
    saved = price_alert_config.load_price_alert_config()
    condition = saved["watchlist"]["crypto"][0]["conditions"][0]

    assert speech == "Added alert: BTC 5.5% move"
    assert condition["value"] == 5.5
    assert condition["message"] == "BTC moved 5.5%"
