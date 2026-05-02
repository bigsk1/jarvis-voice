"""Direct price lookup API - bypasses LLM for efficiency"""

from fastapi import APIRouter, HTTPException, Query
import sys
import json
import subprocess
from pathlib import Path

router = APIRouter(prefix="/api/prices", tags=["prices"])

# Path to tools
SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"

def call_tool(tool_name: str, args: dict) -> dict:
    """Call a Jarvis tool directly without LLM routing."""
    tool_path = SKILLS_DIR / f"{tool_name}.py"
    
    if not tool_path.exists():
        raise HTTPException(status_code=404, detail=f"Tool {tool_name} not found")
    
    try:
        result = subprocess.run(
            [sys.executable, str(tool_path), json.dumps(args)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(SKILLS_DIR.parent)
        )
        
        if result.stdout:
            return json.loads(result.stdout)
        else:
            return {"ok": False, "error": result.stderr or "No output"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Tool timed out"}
    except json.JSONDecodeError:
        return {"ok": False, "error": "Invalid JSON from tool", "raw": result.stdout}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _extract_crypto_batch_items(result: dict) -> list[dict]:
    """Normalize single and multi-coin crypto_price responses for batch APIs."""
    data = result.get("data", {}) if isinstance(result, dict) else {}
    if isinstance(data.get("coins"), list):
        return data["coins"]

    if data.get("coin_id"):
        return [data]

    return []


@router.get("/stock/{symbol}")
async def get_stock_price(symbol: str):
    """
    Get stock/futures/forex price directly (no LLM routing).
    
    Fast, silent, and efficient for monitoring.
    
    Examples:
    - /api/prices/stock/TSLA
    - /api/prices/stock/AAPL
    - /api/prices/stock/GC=F (gold futures)
    - /api/prices/stock/gold (mapped to GC=F)
    """
    result = call_tool("stock_price", {"symbol": symbol})
    
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Failed to get price"))
    
    return result


@router.get("/crypto/{symbol}")
async def get_crypto_price(symbol: str):
    """
    Get cryptocurrency price directly (no LLM routing).
    
    Examples:
    - /api/prices/crypto/BTC or /api/prices/crypto/btc
    - /api/prices/crypto/SOL or /api/prices/crypto/solana
    - /api/prices/crypto/ETH or /api/prices/crypto/ethereum
    
    Accepts both ticker symbols (BTC) and full names (bitcoin), case-insensitive.
    """
    # Tool expects "coin" param, lowercase for COIN_MAP lookup
    result = call_tool("crypto_price", {"coin": symbol.lower()})
    
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Failed to get price"))
    
    return result


@router.get("/crypto/{symbol}/chart")
async def get_crypto_chart(
    symbol: str,
    days: str = Query("7", description="Chart range, e.g. 1, 7, 30, 90, 365, max"),
    vs_currency: str = Query("usd", description="Quote currency, usually usd"),
    points_limit: int | None = Query(None, description="Optional max number of points to return"),
):
    """
    Get cryptocurrency chart data directly (no LLM routing).

    Examples:
    - /api/prices/crypto/BTC/chart
    - /api/prices/crypto/ethereum/chart?days=30
    - /api/prices/crypto/sol/chart?days=90&points_limit=120
    """
    args = {
        "coin": symbol.lower(),
        "days": days,
        "vs_currency": vs_currency.lower(),
    }
    if points_limit is not None:
        args["points_limit"] = points_limit

    result = call_tool("crypto_chart", args)

    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Failed to get chart"))

    return result


@router.get("/batch")
async def get_batch_prices(
    stocks: str | None = Query(None, description="Comma-separated stock symbols (e.g., TSLA,AAPL,GC=F)"),
    crypto: str | None = Query(None, description="Comma-separated crypto symbols (e.g., BTC,SOL)")
):
    """
    Get multiple prices in one call (no LLM routing).
    
    Example: /api/prices/batch?stocks=TSLA,GC=F&crypto=BTC,SOL
    """
    results = {"stocks": {}, "crypto": {}, "ok": True}
    
    if stocks:
        for symbol in stocks.split(","):
            symbol = symbol.strip()
            if symbol:
                result = call_tool("stock_price", {"symbol": symbol})
                if result.get("ok"):
                    results["stocks"][symbol] = {
                        "price": result["data"].get("price_usd"),
                        "change_percent": result["data"].get("change_today_percent"),
                        "name": result["data"].get("company")
                    }
                else:
                    results["stocks"][symbol] = {"error": result.get("error")}
    
    if crypto:
        crypto_symbols = [symbol.strip() for symbol in crypto.split(",") if symbol.strip()]
        if crypto_symbols:
            result = call_tool("crypto_price", {"coins": [symbol.lower() for symbol in crypto_symbols]})
            if result.get("ok"):
                items = _extract_crypto_batch_items(result)
                items_by_id = {item.get("coin_id"): item for item in items}
                items_by_requested = {item.get("requested"): item for item in items}
                for symbol in crypto_symbols:
                    lookup_id = symbol.lower()
                    item = items_by_requested.get(lookup_id) or items_by_id.get(lookup_id)
                    if item:
                        results["crypto"][symbol] = {
                            "price": item.get("price_usd"),
                            "change_percent": item.get("change_24h_percent"),
                            "name": item.get("coin")
                        }
                    else:
                        results["crypto"][symbol] = {"error": f"No data found for '{symbol}'."}
            else:
                for symbol in crypto_symbols:
                    results["crypto"][symbol] = {"error": result.get("error")}
    
    return results
