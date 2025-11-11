#!/usr/bin/env python3
"""
Jarvis Skill: Crypto Price
Get cryptocurrency prices from CoinGecko API.
"""
import sys
import json
import requests


def main():
    """Get crypto price from CoinGecko."""
    # Read input from stdin
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return_error("Invalid JSON input")
        return 1
    
    # Extract parameters
    coin = input_data.get("coin", "").lower().strip()
    
    if not coin:
        return_error("Coin name is required")
        return 1
    
    # Normalize common names
    coin_map = {
        "btc": "bitcoin",
        "eth": "ethereum",
        "ada": "cardano",
        "sol": "solana",
        "doge": "dogecoin",
        "xrp": "ripple"
    }
    coin = coin_map.get(coin, coin)
    
    # Call CoinGecko API
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": coin,
            "vs_currencies": "usd",
            "include_24hr_change": "true"
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Check if coin was found
        if coin not in data:
            return_error(f"Cryptocurrency '{coin}' not found. Try: bitcoin, ethereum, cardano, solana")
            return 1
        
        price = data[coin]["usd"]
        change_24h = data[coin].get("usd_24h_change", 0)
        
        # Format speech
        coin_name = coin.capitalize()
        price_str = f"${price:,.2f}" if price < 100 else f"${price:,.0f}"
        
        change_str = ""
        if change_24h > 0:
            change_str = f"up {abs(change_24h):.1f}% in the last 24 hours"
        elif change_24h < 0:
            change_str = f"down {abs(change_24h):.1f}% in the last 24 hours"
        else:
            change_str = "unchanged in the last 24 hours"
        
        speech = f"{coin_name} is currently {price_str}, {change_str}."
        
        return_success(
            speech=speech,
            data={
                "coin": coin_name,
                "price_usd": price,
                "change_24h_percent": round(change_24h, 2),
                "source": "CoinGecko"
            }
        )
        return 0
        
    except requests.Timeout:
        return_error("CoinGecko API request timed out")
        return 1
    except requests.RequestException as e:
        return_error(f"Failed to fetch price: {str(e)}")
        return 1
    except Exception as e:
        return_error(f"Unexpected error: {str(e)}")
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

