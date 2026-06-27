"""Canonical storage and migration helpers for price-alert configuration."""

from __future__ import annotations

import copy
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRICE_ALERT_PATH = PROJECT_ROOT / "data" / "price-alerts.yaml"
LEGACY_PRICE_ALERT_PATH = PROJECT_ROOT / "config" / "price-alerts.yaml"
PRICE_ALERT_EXAMPLE_PATH = PROJECT_ROOT / "config" / "price-alerts.yaml.example"

DEFAULT_PRICE_ALERT_CONFIG: dict[str, Any] = {
    "settings": {
        "check_interval_minutes": 10,
        "cooldown_hours": 4,
        "jarvis_api_url": "http://localhost:8880",
    },
    "sources": {
        "crypto": {
            "api": "coingecko",
            "base_url": "https://api.coingecko.com/api/v3",
        },
        "stocks": {"api": "yfinance"},
    },
    "watchlist": {"crypto": [], "stocks": []},
}

_HEADER = """# Price Alert Configuration
# ========================
# Managed by Jarvis. The n8n workflow reads it through the Jarvis API.

"""


class PriceAlertConfigError(ValueError):
    """Raised when price-alert state cannot be loaded or validated."""


def _config_error(message: str, path: Path | None = None) -> PriceAlertConfigError:
    if path is None:
        return PriceAlertConfigError(message)
    return PriceAlertConfigError(f"{message}: {path}")


def validate_price_alert_config(config: Any) -> dict[str, Any]:
    """Validate and normalize a price-alert document without dropping extras."""
    if not isinstance(config, dict):
        raise PriceAlertConfigError("price-alert configuration must be a mapping")

    normalized = copy.deepcopy(config)

    for section in ("settings", "sources"):
        value = normalized.get(section)
        if value is None:
            normalized[section] = copy.deepcopy(DEFAULT_PRICE_ALERT_CONFIG[section])
        elif not isinstance(value, dict):
            raise PriceAlertConfigError(f"{section} must be a mapping")

    for key, value in DEFAULT_PRICE_ALERT_CONFIG["settings"].items():
        normalized["settings"].setdefault(key, value)

    for key, value in DEFAULT_PRICE_ALERT_CONFIG["sources"].items():
        normalized["sources"].setdefault(key, copy.deepcopy(value))

    watchlist = normalized.get("watchlist")
    if watchlist is None:
        watchlist = {"crypto": [], "stocks": []}
        normalized["watchlist"] = watchlist
    elif not isinstance(watchlist, dict):
        raise PriceAlertConfigError("watchlist must be a mapping")

    for asset_type in ("crypto", "stocks"):
        assets = watchlist.setdefault(asset_type, [])
        if not isinstance(assets, list):
            raise PriceAlertConfigError(f"watchlist.{asset_type} must be a list")

        for index, asset in enumerate(assets):
            location = f"watchlist.{asset_type}[{index}]"
            if not isinstance(asset, dict):
                raise PriceAlertConfigError(f"{location} must be a mapping")
            if not isinstance(asset.get("symbol"), str) or not asset["symbol"].strip():
                raise PriceAlertConfigError(f"{location}.symbol must be a non-empty string")

            conditions = asset.get("conditions", [])
            if not isinstance(conditions, list):
                raise PriceAlertConfigError(f"{location}.conditions must be a list")
            asset.setdefault("conditions", conditions)

            for condition_index, condition in enumerate(conditions):
                condition_location = f"{location}.conditions[{condition_index}]"
                if not isinstance(condition, dict):
                    raise PriceAlertConfigError(
                        f"{condition_location} must be a mapping"
                    )
                if not isinstance(condition.get("type"), str) or not condition["type"].strip():
                    raise PriceAlertConfigError(
                        f"{condition_location}.type must be a non-empty string"
                    )
                value = condition.get("value")
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise PriceAlertConfigError(
                        f"{condition_location}.value must be a number"
                    )

    return normalized


def _load_and_validate(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _config_error("unable to read price-alert configuration", path) from exc

    try:
        config = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise _config_error("invalid YAML in price-alert configuration", path) from exc

    try:
        return validate_price_alert_config(config)
    except PriceAlertConfigError as exc:
        raise _config_error(str(exc), path) from exc


def _atomic_write_text(path: Path, content: str, *, replace: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=".price-alerts-",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temporary_path.chmod(0o600)
        except OSError:
            pass

        if not replace and path.exists():
            return
        os.replace(temporary_path, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except OSError as exc:
        raise _config_error("unable to write price-alert configuration", path) from exc
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def ensure_price_alert_config() -> Path:
    """Return the canonical path, migrating or safely seeding it when absent."""
    if PRICE_ALERT_PATH.exists():
        _load_and_validate(PRICE_ALERT_PATH)
        return PRICE_ALERT_PATH

    source: Path | None = None
    if LEGACY_PRICE_ALERT_PATH.exists():
        source = LEGACY_PRICE_ALERT_PATH
    elif PRICE_ALERT_EXAMPLE_PATH.exists():
        source = PRICE_ALERT_EXAMPLE_PATH

    if source is not None:
        _load_and_validate(source)
        try:
            content = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise _config_error("unable to read price-alert configuration", source) from exc
        _atomic_write_text(PRICE_ALERT_PATH, content, replace=False)
        if PRICE_ALERT_PATH.exists():
            _load_and_validate(PRICE_ALERT_PATH)
            logger.info("Initialized price-alert configuration from %s", source)
            return PRICE_ALERT_PATH

    save_price_alert_config(copy.deepcopy(DEFAULT_PRICE_ALERT_CONFIG))
    logger.info("Initialized empty price-alert configuration")
    return PRICE_ALERT_PATH


def load_price_alert_config() -> dict[str, Any]:
    """Load and validate the canonical price-alert document."""
    path = ensure_price_alert_config()
    return _load_and_validate(path)


def save_price_alert_config(config: dict[str, Any]) -> None:
    """Validate and atomically replace the canonical price-alert document."""
    normalized = validate_price_alert_config(config)
    try:
        body = yaml.safe_dump(
            normalized,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
    except yaml.YAMLError as exc:
        raise PriceAlertConfigError("unable to serialize price-alert configuration") from exc
    _atomic_write_text(PRICE_ALERT_PATH, _HEADER + body, replace=True)
