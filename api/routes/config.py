"""Config API - Serve configuration files for external systems like n8n"""

from fastapi import APIRouter, HTTPException
from pathlib import Path
import yaml

router = APIRouter(prefix="/api/config", tags=["config"])

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


@router.get("/price-alerts")
async def get_price_alerts_config():
    """
    Get price alert configuration for n8n workflow.
    
    Edit config/price-alerts.yaml to change thresholds.
    n8n fetches this at each run for single source of truth.
    """
    config_file = CONFIG_DIR / "price-alerts.yaml"
    
    if not config_file.exists():
        raise HTTPException(status_code=404, detail="price-alerts.yaml not found")
    
    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        
        # Return just the watchlist for n8n
        return {
            "ok": True,
            "settings": config.get("settings", {}),
            "watchlist": config.get("watchlist", {}),
            "source": "config/price-alerts.yaml"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/price-alerts/thresholds")
async def get_price_thresholds():
    """
    Get just the thresholds in a format ready for n8n Code node.
    """
    config_file = CONFIG_DIR / "price-alerts.yaml"
    
    if not config_file.exists():
        raise HTTPException(status_code=404, detail="price-alerts.yaml not found")
    
    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        
        watchlist = config.get("watchlist", {})
        
        # Transform to n8n-friendly format
        thresholds = {
            "crypto": {},
            "stocks": {}
        }
        
        # Process crypto
        for crypto in watchlist.get("crypto", []):
            if crypto.get("enabled", True):
                symbol = crypto["symbol"]
                thresholds["crypto"][symbol] = {
                    "name": crypto.get("name", symbol),
                    "conditions": {}
                }
                for cond in crypto.get("conditions", []):
                    cond_type = cond["type"]
                    thresholds["crypto"][symbol]["conditions"][cond_type] = cond["value"]
        
        # Process stocks
        for stock in watchlist.get("stocks", []):
            if stock.get("enabled", True):
                symbol = stock["symbol"]
                thresholds["stocks"][symbol] = {
                    "name": stock.get("name", symbol),
                    "conditions": {}
                }
                for cond in stock.get("conditions", []):
                    cond_type = cond["type"]
                    thresholds["stocks"][symbol]["conditions"][cond_type] = cond["value"]
        
        return {
            "ok": True,
            "thresholds": thresholds
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
