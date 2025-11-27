#!/usr/bin/env python3
"""
Jarvis Skill: Crypto Price
Get cryptocurrency prices from CoinGecko API.

Input: { "coin": "bitcoin" }
Output: { "ok": bool, "speech": str, "data": dict }
"""
import sys
import os
import json

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
        
        # Extract parameters
        coin = input_data.get("coin", "").lower().strip()
        
        if not coin:
            return_error("Coin name is required")
            return 1
        
        # Normalize coin name to CoinGecko ID
        coin_id = COIN_MAP.get(coin, coin)
        
        # Get API key from config (optional but recommended to avoid rate limits)
        api_key = get_config_value('COINGECKO_API_KEY', '')
        
        # Build request with proper headers
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": coin_id,
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
        
        # Check if coin was found
        if coin_id not in data:
            # Provide helpful suggestions
            suggestions = "bitcoin, ethereum, solana, xrp, cardano, dogecoin"
            return_error(f"Cryptocurrency '{coin}' not found. Try: {suggestions}")
            return 1
        
        price = data[coin_id]["usd"]
        change_24h = data[coin_id].get("usd_24h_change", 0)
        market_cap = data[coin_id].get("usd_market_cap", 0)
        
        # Format coin name for display (use original if not in map)
        display_name = coin_id.replace("-", " ").title()
        if coin_id == "matic-network":
            display_name = "Polygon (MATIC)"
        elif coin_id == "avalanche-2":
            display_name = "Avalanche"
        elif coin_id == "binancecoin":
            display_name = "BNB"
        elif coin_id == "usd-coin":
            display_name = "USD Coin"
        elif coin_id == "shiba-inu":
            display_name = "Shiba Inu"
        elif coin_id == "the-open-network":
            display_name = "Toncoin"
        
        # Format price string (more precision for low-value coins)
        if price >= 1000:
            price_str = f"${price:,.0f}"
        elif price >= 1:
            price_str = f"${price:,.2f}"
        elif price >= 0.01:
            price_str = f"${price:,.4f}"
        else:
            price_str = f"${price:,.8f}"
        
        # Format change string
        if change_24h > 0:
            change_str = f"up {abs(change_24h):.1f}% in the last 24 hours"
        elif change_24h < 0:
            change_str = f"down {abs(change_24h):.1f}% in the last 24 hours"
        else:
            change_str = "unchanged in the last 24 hours"
        
        speech = f"{display_name} is currently {price_str}, {change_str}."
        
        # Check if proxy was configured
        proxy_enabled = get_proxy_config() is not None
        
        return_success(
            speech=speech,
            data={
                "coin": display_name,
                "coin_id": coin_id,
                "price_usd": price,
                "change_24h_percent": round(change_24h, 2) if change_24h else 0,
                "market_cap_usd": round(market_cap, 0) if market_cap else None,
                "source": "CoinGecko",
                "authenticated": bool(api_key),
                "proxy_enabled": proxy_enabled
            }
        )
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

