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
        for symbol in crypto.split(","):
            symbol = symbol.strip()
            if symbol:
                result = call_tool("crypto_price", {"coin": symbol.lower()})
                if result.get("ok"):
                    results["crypto"][symbol] = {
                        "price": result["data"].get("price_usd"),
                        "change_percent": result["data"].get("change_24h_percent"),
                        "name": result["data"].get("name")
                    }
                else:
                    results["crypto"][symbol] = {"error": result.get("error")}
    
    return results
