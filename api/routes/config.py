"""Config API - Serve configuration files for external systems like n8n"""

import logging

from fastapi import APIRouter, HTTPException

from lib.price_alert_config import load_price_alert_config

router = APIRouter(prefix="/api/config", tags=["config"])
logger = logging.getLogger(__name__)


@router.get("/price-alerts")
async def get_price_alerts_config():
    """
    Get price alert configuration for n8n workflow.
    
    Edit data/price-alerts.yaml to change thresholds.
    n8n fetches this at each run for single source of truth.
    """
    try:
        config = load_price_alert_config()
        
        # Return just the watchlist for n8n
        return {
            "ok": True,
            "settings": config.get("settings", {}),
            "watchlist": config.get("watchlist", {}),
            "source": "data/price-alerts.yaml"
        }
    except Exception as e:
        logger.exception("Unable to load price-alert configuration: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Unable to load price-alert configuration",
        ) from e


@router.get("/price-alerts/thresholds")
async def get_price_thresholds():
    """
    Get just the thresholds in a format ready for n8n Code node.
    """
    try:
        config = load_price_alert_config()
        
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
            "thresholds": thresholds,
            "source": "data/price-alerts.yaml",
        }
    except Exception as e:
        logger.exception("Unable to load price-alert thresholds: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Unable to load price-alert configuration",
        ) from e
