#!/usr/bin/env python3
"""
Jarvis Skill: Crypto Price
Get cryptocurrency prices from CoinGecko API.

Input:
  { "coin": "bitcoin" }
  { "coin": "bitcoin, solana" }
  { "coins": ["bitcoin", "solana"] }
Output: { "ok": bool, "speech": str, "data": dict }
"""
import sys
import os
import json
import re

# Add lib to path for config_loader and http_client
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value
from http_client import http_request, get_proxy_config


# Extended coin mapping - symbols and common names to CoinGecko IDs
COIN_MAP = {
    # Major coins
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
    # Stablecoins
    "usdt": "tether",
    "tether": "tether",
    "usdc": "usd-coin",
    "usd coin": "usd-coin",
    "dai": "dai",
    # DeFi & Layer 2
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


DISPLAY_NAME_MAP = {
    "matic-network": "Polygon (MATIC)",
    "avalanche-2": "Avalanche",
    "binancecoin": "BNB",
    "usd-coin": "USD Coin",
    "shiba-inu": "Shiba Inu",
    "the-open-network": "Toncoin",
}


def normalize_coin_inputs(input_data):
    """Accept legacy single-coin input plus newer multi-coin input."""
    parsed = []

    def add_coin(value):
        if value is None:
            return
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return
            # Support comma-separated legacy input like "bitcoin, solana".
            parts = re.split(r"\s*(?:,|&|\band\b)\s*", text, flags=re.IGNORECASE)
            for part in parts:
                part = part.strip().lower()
                if part:
                    parsed.append(part)
            return

        parsed.append(str(value).strip().lower())

    add_coin(input_data.get("coin"))

    coins = input_data.get("coins")
    if isinstance(coins, list):
        for coin in coins:
            add_coin(coin)
    elif coins is not None:
        add_coin(coins)

    normalized = []
    seen = set()
    for coin in parsed:
        if coin and coin not in seen:
            normalized.append(coin)
            seen.add(coin)

    return normalized


def format_coin_name(coin_id):
    """Convert CoinGecko IDs to user-friendly display names."""
    return DISPLAY_NAME_MAP.get(coin_id, coin_id.replace("-", " ").title())


def format_price_string(price):
    """Format price string with sensible precision."""
    if price >= 1000:
        return f"${price:,.0f}"
    if price >= 1:
        return f"${price:,.2f}"
    if price >= 0.01:
        return f"${price:,.4f}"
    return f"${price:,.8f}"


def format_change_string(change_24h):
    """Format 24h change for speech output."""
    if change_24h > 0:
        return f"up {abs(change_24h):.1f}% in the last 24 hours"
    if change_24h < 0:
        return f"down {abs(change_24h):.1f}% in the last 24 hours"
    return "unchanged in the last 24 hours"


def main():
    """Get crypto price from CoinGecko."""
    try:
        # Load config for API key
        load_config()
        
        # Read input from command line argument
        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1
        
        requested_coins = normalize_coin_inputs(input_data)

        if not requested_coins:
            return_error("Coin name is required")
            return 1

        # Normalize coin names to CoinGecko IDs
        coin_ids = [COIN_MAP.get(coin, coin) for coin in requested_coins]
        requested_by_coin_id = {}
        for requested_coin, coin_id in zip(requested_coins, coin_ids):
            requested_by_coin_id.setdefault(coin_id, requested_coin)
        unique_coin_ids = []
        seen_coin_ids = set()
        for coin_id in coin_ids:
            if coin_id not in seen_coin_ids:
                unique_coin_ids.append(coin_id)
                seen_coin_ids.add(coin_id)
        
        # Get API key from config (optional but recommended to avoid rate limits)
        api_key = get_config_value('COINGECKO_API_KEY', '')
        
        # Build request with proper headers
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": ",".join(unique_coin_ids),
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_market_cap": "true"
        }
        
        # Use header authentication (recommended by CoinGecko docs)
        headers = {
            "Accept": "application/json"
        }
        
        if api_key:
            # Demo API key authentication via header (more secure than query param)
            headers["x-cg-demo-api-key"] = api_key
        
        # Use http_client with proxy support (falls back to direct if proxy fails)
        # Proxy status will be logged to stderr
        response = http_request(
            'GET', 
            url, 
            params=params, 
            headers=headers, 
            timeout=15,
            use_proxy=True,
            fallback_on_proxy_fail=True
        )
        response.raise_for_status()
        
        data = response.json()

        found_ids = [coin_id for coin_id in unique_coin_ids if coin_id in data]
        missing_ids = [coin_id for coin_id in unique_coin_ids if coin_id not in data]

        # Check if any requested coins were found
        if not found_ids:
            # Provide helpful suggestions
            suggestions = "bitcoin, ethereum, solana, xrp, cardano, dogecoin"
            requested_label = ", ".join(requested_coins)
            return_error(f"Cryptocurrency '{requested_label}' not found. Try: {suggestions}")
            return 1

        # Check if proxy was configured
        proxy_enabled = get_proxy_config() is not None

        coin_results = []
        for coin_id in found_ids:
            price = data[coin_id]["usd"]
            change_24h = data[coin_id].get("usd_24h_change", 0)
            market_cap = data[coin_id].get("usd_market_cap", 0)
            display_name = format_coin_name(coin_id)
            coin_results.append({
                "requested": requested_by_coin_id.get(coin_id, coin_id),
                "coin": display_name,
                "coin_id": coin_id,
                "price_usd": price,
                "change_24h_percent": round(change_24h, 2) if change_24h else 0,
                "market_cap_usd": round(market_cap, 0) if market_cap else None,
            })

        # Preserve exact legacy response shape for single-coin requests.
        if len(coin_results) == 1 and len(requested_coins) == 1:
            result = coin_results[0]
            result.pop("requested", None)
            speech = (
                f"{result['coin']} is currently {format_price_string(result['price_usd'])}, "
                f"{format_change_string(result['change_24h_percent'])}."
            )
            result["source"] = "CoinGecko"
            result["authenticated"] = bool(api_key)
            result["proxy_enabled"] = proxy_enabled
            return_success(speech=speech, data=result)
            return 0

        speech_parts = []
        for result in coin_results:
            speech_parts.append(
                f"{result['coin']} is currently {format_price_string(result['price_usd'])}, "
                f"{format_change_string(result['change_24h_percent'])}."
            )

        if missing_ids:
            missing_display = ", ".join(format_coin_name(coin_id) for coin_id in missing_ids)
            speech_parts.append(f"I couldn't find {missing_display}.")

        response_data = {
            "coins": coin_results,
            "count": len(coin_results),
            "source": "CoinGecko",
            "authenticated": bool(api_key),
            "proxy_enabled": proxy_enabled,
        }
        if missing_ids:
            response_data["missing_coins"] = missing_ids

        return_success(speech=" ".join(speech_parts), data=response_data)
        return 0
        
    except Exception as e:
        error_msg = str(e)
        if 'timeout' in error_msg.lower() or 'Timeout' in type(e).__name__:
            return_error("CoinGecko API request timed out")
        elif 'Request' in type(e).__name__ or 'Connection' in type(e).__name__:
            return_error(f"Failed to fetch price: {error_msg}")
        else:
            return_error(f"Unexpected error: {error_msg}")
        return 1


def return_success(speech, data=None):
    """Return success response."""
    result = {
        "ok": True,
        "speech": speech
    }
    if data:
        result["data"] = data
    print(json.dumps(result))


def return_error(speech, data=None):
    """Return error response."""
    result = {
        "ok": False,
        "speech": speech,
        "error": speech
    }
    if data:
        result["data"] = data
    print(json.dumps(result))


if __name__ == "__main__":
    sys.exit(main())
