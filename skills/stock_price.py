#!/usr/bin/env python3
"""
Jarvis Skill: Stock Price
Get stock prices from Yahoo Finance using yfinance.

Input: { "symbol": "TSLA" } or { "symbol": "Tesla" }
Output: { "ok": bool, "speech": str, "data": dict }
"""
import sys
import os
import json

# Add lib to path for config_loader
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value

# yfinance for Yahoo Finance API
import yfinance as yf

# Common company names to ticker symbols (LLM can also use general knowledge)
STOCK_MAP = {
    # Tech giants
    "tesla": "TSLA",
    "apple": "AAPL",
    "microsoft": "MSFT",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "amazon": "AMZN",
    "meta": "META",
    "facebook": "META",
    "nvidia": "NVDA",
    "netflix": "NFLX",
    "amd": "AMD",
    "intel": "INTC",
    "ibm": "IBM",
    "oracle": "ORCL",
    "salesforce": "CRM",
    "adobe": "ADBE",
    "palantir": "PLTR",
    "snowflake": "SNOW",
    "uber": "UBER",
    "airbnb": "ABNB",
    "spotify": "SPOT",
    "zoom": "ZM",
    "shopify": "SHOP",
    "square": "SQ",
    "block": "SQ",
    "paypal": "PYPL",
    "coinbase": "COIN",
    "robinhood": "HOOD",
    # EV & Auto
    "ford": "F",
    "gm": "GM",
    "general motors": "GM",
    "rivian": "RIVN",
    "lucid": "LCID",
    "nio": "NIO",
    "toyota": "TM",
    # Finance
    "jpmorgan": "JPM",
    "jp morgan": "JPM",
    "goldman": "GS",
    "goldman sachs": "GS",
    "morgan stanley": "MS",
    "bank of america": "BAC",
    "wells fargo": "WFC",
    "visa": "V",
    "mastercard": "MA",
    "american express": "AXP",
    "amex": "AXP",
    # Retail & Consumer
    "walmart": "WMT",
    "costco": "COST",
    "target": "TGT",
    "nike": "NKE",
    "starbucks": "SBUX",
    "mcdonalds": "MCD",
    "coca cola": "KO",
    "coke": "KO",
    "pepsi": "PEP",
    "disney": "DIS",
    # Healthcare
    "johnson": "JNJ",
    "johnson and johnson": "JNJ",
    "pfizer": "PFE",
    "moderna": "MRNA",
    "unitedhealth": "UNH",
    # Energy
    "exxon": "XOM",
    "chevron": "CVX",
    # Aerospace & Defense
    "boeing": "BA",
    "lockheed": "LMT",
    "raytheon": "RTX",
    # Indices (ETFs)
    "spy": "SPY",
    "s&p": "SPY",
    "s&p 500": "SPY",
    "qqq": "QQQ",
    "nasdaq": "QQQ",
    "dow": "DIA",
    "ark": "ARKK",
    "arkk": "ARKK",
    # Commodities & Futures (use =F suffix for futures)
    "gold": "GC=F",
    "gold futures": "GC=F",
    "silver": "SI=F",
    "silver futures": "SI=F",
    "oil": "CL=F",
    "crude": "CL=F",
    "crude oil": "CL=F",
    "wti": "CL=F",
    "natural gas": "NG=F",
    "nat gas": "NG=F",
    "copper": "HG=F",
    "platinum": "PL=F",
    "palladium": "PA=F",
    # Crypto futures (CME)
    "bitcoin futures": "BTC=F",
    "btc futures": "BTC=F",
    "ethereum futures": "ETH=F",
    "eth futures": "ETH=F",
    # Index futures
    "sp500 futures": "ES=F",
    "es futures": "ES=F",
    "nasdaq futures": "NQ=F",
    "nq futures": "NQ=F",
    "dow futures": "YM=F",
    # Forex pairs
    "eurusd": "EURUSD=X",
    "eur/usd": "EURUSD=X",
    "usdjpy": "USDJPY=X",
    "usd/jpy": "USDJPY=X",
    "gbpusd": "GBPUSD=X",
    "gbp/usd": "GBPUSD=X",
    # Gold/Silver ETFs (if user wants ETF not futures)
    "gld": "GLD",
    "gold etf": "GLD",
    "slv": "SLV",
    "silver etf": "SLV",
}


def setup_proxy():
    """Configure proxy for yfinance via environment variables."""
    proxy = get_config_value('LOCAL_PROXY', '')
    if proxy:
        os.environ['http_proxy'] = proxy
        os.environ['https_proxy'] = proxy
        os.environ['HTTP_PROXY'] = proxy
        os.environ['HTTPS_PROXY'] = proxy
        return True
    return False


def clear_proxy():
    """Remove proxy environment variables for direct network access."""
    for key in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
        os.environ.pop(key, None)


def is_proxy_tunnel_error(error_text: str) -> bool:
    """Detect proxy-related curl_cffi/yfinance failures worth a direct retry."""
    error_lower = error_text.lower()
    return (
        'connect tunnel failed' in error_lower
        or 'curl: (56)' in error_lower
        or 'curl: (7)' in error_lower
        or 'curl: (5)' in error_lower
        or 'response 503' in error_lower
        or 'could not connect to server' in error_lower
        or 'could not resolve proxy' in error_lower
        or 'failed to perform, curl:' in error_lower
    )


def fetch_stock_snapshot(ticker: str, symbol: str) -> dict:
    """Fetch and normalize stock/futures data from Yahoo Finance."""
    stock = yf.Ticker(ticker)

    # Get info first (works better for futures outside market hours)
    info = stock.info

    # Try history first for most accurate current data
    hist = stock.history(period='1d')

    if not hist.empty:
        # Use history data (most accurate during market hours)
        current_price = hist['Close'].iloc[-1]
        open_price = hist['Open'].iloc[0]
        day_change = current_price - open_price
        day_change_pct = (day_change / open_price) * 100 if open_price else 0
    else:
        # Fall back to info data (works for futures/commodities outside hours)
        current_price = info.get('regularMarketPrice') or info.get('currentPrice') or info.get('previousClose')
        prev_close = info.get('regularMarketPreviousClose') or info.get('previousClose')

        if not current_price:
            raise ValueError(f"No data found for '{symbol}'. Check if the ticker symbol is correct.")

        if prev_close:
            day_change = current_price - prev_close
            day_change_pct = (day_change / prev_close) * 100
        else:
            day_change = 0
            day_change_pct = 0

    # Additional data from info
    company_name = info.get('shortName', info.get('longName', ticker))
    market_cap = info.get('marketCap')
    # Get volume from info first, fall back to history if available
    volume = info.get('volume') or info.get('regularMarketVolume')
    if not volume and not hist.empty and 'Volume' in hist.columns:
        volume = hist['Volume'].iloc[-1]
    pe_ratio = info.get('trailingPE')
    fifty_two_week_high = info.get('fiftyTwoWeekHigh')
    fifty_two_week_low = info.get('fiftyTwoWeekLow')
    sector = info.get('sector')

    return {
        "symbol": ticker,
        "company": company_name,
        "price_usd": current_price,
        "change_today_usd": day_change,
        "change_today_percent": day_change_pct,
        "volume": volume,
        "market_cap_usd": market_cap,
        "pe_ratio": pe_ratio,
        "52_week_high": fifty_two_week_high,
        "52_week_low": fifty_two_week_low,
        "sector": sector,
    }


def main():
    """Get stock price from Yahoo Finance."""
    try:
        # Load config
        load_config()
        
        # Setup proxy (required for yfinance on some networks)
        proxy_enabled = setup_proxy()
        
        # Read input from command line argument
        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1
        
        # Extract parameters
        symbol = input_data.get("symbol", "").strip()
        
        if not symbol:
            return_error("Stock symbol or company name is required")
            return 1
        
        # Normalize: check if it's a common name, otherwise assume ticker
        symbol_lower = symbol.lower()
        ticker = STOCK_MAP.get(symbol_lower, symbol.upper())
        
        # Fetch stock data
        used_proxy_fallback = False
        try:
            stock_data = fetch_stock_snapshot(ticker, symbol)
        except Exception as e:
            error_str = str(e)
            if proxy_enabled and is_proxy_tunnel_error(error_str):
                try:
                    # Proxy occasionally returns transient CONNECT 503; retry direct once.
                    clear_proxy()
                    stock_data = fetch_stock_snapshot(ticker, symbol)
                    proxy_enabled = False
                    used_proxy_fallback = True
                except Exception as retry_error:
                    retry_error_str = str(retry_error)
                    if 'No data found' in retry_error_str or 'delisted' in retry_error_str.lower():
                        return_error(f"Stock '{symbol}' not found or may be delisted.")
                    else:
                        return_error(f"Failed to fetch stock data: {retry_error_str}")
                    return 1
            elif 'No data found' in error_str or 'delisted' in error_str.lower():
                return_error(f"Stock '{symbol}' not found or may be delisted.")
            else:
                return_error(f"Failed to fetch stock data: {error_str}")
            return 1

        current_price = stock_data["price_usd"]
        day_change = stock_data["change_today_usd"]
        day_change_pct = stock_data["change_today_percent"]
        company_name = stock_data["company"]
        market_cap = stock_data["market_cap_usd"]
        volume = stock_data["volume"]
        pe_ratio = stock_data["pe_ratio"]
        fifty_two_week_high = stock_data["52_week_high"]
        fifty_two_week_low = stock_data["52_week_low"]
        sector = stock_data["sector"]
        
        # Format price string
        if current_price >= 1000:
            price_str = f"${current_price:,.0f}"
        elif current_price >= 1:
            price_str = f"${current_price:,.2f}"
        else:
            price_str = f"${current_price:,.4f}"
        
        # Format change string
        if day_change > 0:
            change_str = f"up {abs(day_change_pct):.1f}% today"
            change_emoji = "📈"
        elif day_change < 0:
            change_str = f"down {abs(day_change_pct):.1f}% today"
            change_emoji = "📉"
        else:
            change_str = "unchanged today"
            change_emoji = "➡️"
        
        # Build speech (TTS friendly)
        speech = f"{company_name} is currently {price_str}, {change_str}."
        
        # Format market cap for display
        market_cap_display = None
        if market_cap:
            if market_cap >= 1e12:
                market_cap_display = f"${market_cap/1e12:.2f}T"
            elif market_cap >= 1e9:
                market_cap_display = f"${market_cap/1e9:.2f}B"
            elif market_cap >= 1e6:
                market_cap_display = f"${market_cap/1e6:.2f}M"
        
        return_success(
            speech=speech,
            data={
                "symbol": ticker,
                "company": company_name,
                "price_usd": round(current_price, 2),
                "change_today_usd": round(day_change, 2),
                "change_today_percent": round(day_change_pct, 2),
                "change_emoji": change_emoji,
                "volume": volume,
                "market_cap_usd": market_cap,
                "market_cap_display": market_cap_display,
                "pe_ratio": round(pe_ratio, 2) if pe_ratio else None,
                "52_week_high": fifty_two_week_high,
                "52_week_low": fifty_two_week_low,
                "sector": sector,
                "source": "Yahoo Finance",
                "proxy_enabled": proxy_enabled,
                "proxy_retry_without_proxy": used_proxy_fallback
            }
        )
        return 0
        
    except Exception as e:
        error_msg = str(e)
        if 'timeout' in error_msg.lower() or 'Timeout' in type(e).__name__:
            return_error("Yahoo Finance request timed out")
        elif 'Connection' in type(e).__name__:
            return_error(f"Failed to connect to Yahoo Finance: {error_msg}")
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
