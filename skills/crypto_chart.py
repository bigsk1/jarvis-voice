#!/usr/bin/env python3
"""
Jarvis Skill: Crypto Chart
Get historical cryptocurrency chart data from CoinGecko API.

Input: {
  "coin": "bitcoin",
  "days": "30",
  "vs_currency": "usd",
  "points_limit": 120
}
Output: { "ok": bool, "speech": str, "data": dict }
"""
import json
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value
from http_client import http_request, get_proxy_config


COIN_MAP = {
    "btc": "bitcoin",
    "bitcoin": "bitcoin",
    "eth": "ethereum",
    "ethereum": "ethereum",
    "sol": "solana",
    "solana": "solana",
    "xrp": "ripple",
    "ripple": "ripple",
    "ada": "cardano",
    "cardano": "cardano",
    "doge": "dogecoin",
    "dogecoin": "dogecoin",
    "dot": "polkadot",
    "polkadot": "polkadot",
    "matic": "matic-network",
    "polygon": "matic-network",
    "avax": "avalanche-2",
    "avalanche": "avalanche-2",
    "link": "chainlink",
    "chainlink": "chainlink",
    "ltc": "litecoin",
    "litecoin": "litecoin",
    "bnb": "binancecoin",
    "binance": "binancecoin",
    "binance coin": "binancecoin",
    "usdt": "tether",
    "tether": "tether",
    "usdc": "usd-coin",
    "usd coin": "usd-coin",
    "dai": "dai",
    "uni": "uniswap",
    "uniswap": "uniswap",
    "aave": "aave",
    "atom": "cosmos",
    "cosmos": "cosmos",
    "near": "near",
    "ftm": "fantom",
    "fantom": "fantom",
    "algo": "algorand",
    "algorand": "algorand",
    "xlm": "stellar",
    "stellar": "stellar",
    "trx": "tron",
    "tron": "tron",
    "shib": "shiba-inu",
    "shiba": "shiba-inu",
    "shiba inu": "shiba-inu",
    "arb": "arbitrum",
    "arbitrum": "arbitrum",
    "op": "optimism",
    "optimism": "optimism",
    "apt": "aptos",
    "aptos": "aptos",
    "sui": "sui",
    "sei": "sei-network",
    "inj": "injective-protocol",
    "injective": "injective-protocol",
    "render": "render-token",
    "rndr": "render-token",
    "fet": "fetch-ai",
    "fetch": "fetch-ai",
    "pepe": "pepe",
    "wif": "dogwifcoin",
    "dogwifhat": "dogwifcoin",
    "bonk": "bonk",
    "floki": "floki",
    "hbar": "hedera-hashgraph",
    "hedera": "hedera-hashgraph",
    "fil": "filecoin",
    "filecoin": "filecoin",
    "icp": "internet-computer",
    "internet computer": "internet-computer",
    "vet": "vechain",
    "vechain": "vechain",
    "kas": "kaspa",
    "kaspa": "kaspa",
    "ton": "the-open-network",
    "toncoin": "the-open-network",
}

ALLOWED_DAYS = {"1", "7", "14", "30", "90", "180", "365", "max"}


def normalize_days(value) -> str:
    """Normalize supported day ranges to CoinGecko-friendly strings."""
    if value is None or value == "":
        return "7"
    normalized = str(value).strip().lower()
    if normalized.endswith("d") and normalized[:-1].isdigit():
        normalized = normalized[:-1]
    if normalized in ALLOWED_DAYS:
        return normalized
    if normalized.isdigit():
        return normalized
    raise ValueError("days must be one of 1, 7, 14, 30, 90, 180, 365, max, or another numeric day count")


def normalize_points_limit(value) -> int | None:
    """Normalize an optional max-point limit."""
    if value in (None, ""):
        return None
    limit = int(value)
    if limit <= 0:
        raise ValueError("points_limit must be greater than 0")
    return limit


def format_coin_name(coin_id: str) -> str:
    """Friendly display name for common CoinGecko IDs."""
    special = {
        "matic-network": "Polygon (MATIC)",
        "avalanche-2": "Avalanche",
        "binancecoin": "BNB",
        "usd-coin": "USD Coin",
        "shiba-inu": "Shiba Inu",
        "the-open-network": "Toncoin",
    }
    return special.get(coin_id, coin_id.replace("-", " ").title())


def _timestamp_to_iso(timestamp_ms: int | float) -> str:
    """Convert a millisecond timestamp to an ISO UTC string."""
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def _downsample_pairs(pairs: list[list[float]], points_limit: int | None) -> list[list[float]]:
    """Reduce point count while preserving first and last points."""
    if not points_limit or len(pairs) <= points_limit:
        return pairs
    if points_limit == 1:
        return [pairs[-1]]

    step = (len(pairs) - 1) / (points_limit - 1)
    sampled: list[list[float]] = []
    last_index = -1
    for i in range(points_limit):
        index = min(len(pairs) - 1, round(i * step))
        if index == last_index:
            continue
        sampled.append(pairs[index])
        last_index = index
    if sampled[-1] != pairs[-1]:
        sampled[-1] = pairs[-1]
    return sampled


def _format_series(pairs: list[list[float]], points_limit: int | None) -> list[dict]:
    """Convert CoinGecko [timestamp, value] pairs into structured chart points."""
    sampled = _downsample_pairs(pairs, points_limit)
    return [
        {
            "timestamp_ms": int(timestamp_ms),
            "iso": _timestamp_to_iso(timestamp_ms),
            "value": value,
        }
        for timestamp_ms, value in sampled
    ]


def build_chart_payload(
    coin_id: str,
    vs_currency: str,
    days: str,
    api_data: dict,
    points_limit: int | None,
    authenticated: bool,
    proxy_enabled: bool,
) -> dict:
    """Build a chart-friendly response payload from CoinGecko market chart data."""
    prices_raw = api_data.get("prices", [])
    market_caps_raw = api_data.get("market_caps", [])
    total_volumes_raw = api_data.get("total_volumes", [])

    if not prices_raw:
        raise ValueError("CoinGecko returned no price data for this chart")

    prices = _format_series(prices_raw, points_limit)
    market_caps = _format_series(market_caps_raw, points_limit) if market_caps_raw else []
    total_volumes = _format_series(total_volumes_raw, points_limit) if total_volumes_raw else []

    first_price = prices[0]["value"]
    last_price = prices[-1]["value"]
    change_percent = ((last_price - first_price) / first_price * 100) if first_price else 0

    return {
        "coin": format_coin_name(coin_id),
        "coin_id": coin_id,
        "vs_currency": vs_currency,
        "days": days,
        "range_label": f"{days}-day" if days != "max" else "max",
        "current_price": last_price,
        "change_percent": round(change_percent, 2),
        "points_returned": len(prices),
        "original_points": len(prices_raw),
        "source": "CoinGecko",
        "authenticated": authenticated,
        "proxy_enabled": proxy_enabled,
        "series": {
            "prices": prices,
            "market_caps": market_caps,
            "total_volumes": total_volumes,
        },
    }


def _format_price(value: float) -> str:
    """Format a price for short speech output."""
    if value >= 1000:
        return f"${value:,.0f}"
    if value >= 1:
        return f"${value:,.2f}"
    if value >= 0.01:
        return f"${value:,.4f}"
    return f"${value:,.8f}"


def return_success(speech, data=None):
    result = {"ok": True, "speech": speech}
    if data:
        result["data"] = data
    print(json.dumps(result))


def return_error(speech, data=None):
    result = {"ok": False, "speech": speech, "error": speech}
    if data:
        result["data"] = data
    print(json.dumps(result))


def main():
    """Get crypto chart data from CoinGecko."""
    try:
        load_config()

        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        coin = input_data.get("coin", "").lower().strip()
        if not coin:
            return_error("Coin name is required")
            return 1

        days = normalize_days(input_data.get("days", "7"))
        vs_currency = str(input_data.get("vs_currency", "usd")).lower().strip() or "usd"
        points_limit = normalize_points_limit(input_data.get("points_limit"))

        coin_id = COIN_MAP.get(coin, coin)
        api_key = get_config_value("COINGECKO_API_KEY", "")

        headers = {"Accept": "application/json"}
        if api_key:
            headers["x-cg-demo-api-key"] = api_key

        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
        response = http_request(
            "GET",
            url,
            params={
                "vs_currency": vs_currency,
                "days": days,
            },
            headers=headers,
            timeout=20,
            use_proxy=True,
            fallback_on_proxy_fail=True,
        )
        response.raise_for_status()

        payload = build_chart_payload(
            coin_id=coin_id,
            vs_currency=vs_currency,
            days=days,
            api_data=response.json(),
            points_limit=points_limit,
            authenticated=bool(api_key),
            proxy_enabled=get_proxy_config() is not None,
        )

        speech = (
            f"{payload['coin']} {payload['range_label']} chart loaded with "
            f"{payload['points_returned']} points. Current price is {_format_price(payload['current_price'])}."
        )
        return_success(speech, payload)
        return 0

    except ValueError as e:
        return_error(str(e))
        return 1
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg:
            return_error(f"Cryptocurrency '{coin}' not found")
        elif "timeout" in error_msg.lower():
            return_error("CoinGecko chart request timed out")
        else:
            return_error(f"Failed to fetch crypto chart: {error_msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
