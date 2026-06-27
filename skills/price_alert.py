#!/usr/bin/env python3
"""
Tool Name: price_alert
Manage price alerts for crypto, stocks, and futures.
Input: { "action": "list|add|remove|update", "symbol": "BTC", "condition": "above|below|percent_change", "value": 100000 }
Output: { "ok": bool, "speech": str, "data": dict }
"""

import sys
import os
import json

# Add the project and lib directories to the import path. Import the price-alert
# owner through ``lib`` so API, tool, and tests share one module identity.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'lib'))
from config_loader import load_config  # noqa: E402
from lib.price_alert_config import (  # noqa: E402
    PRICE_ALERT_PATH,
    load_price_alert_config,
    save_price_alert_config,
)

# Symbol mappings (common names to ticker symbols)
SYMBOL_MAP = {
    # Crypto
    "bitcoin": "BTC",
    "btc": "BTC",
    "solana": "SOL",
    "sol": "SOL",
    "ethereum": "ETH",
    "eth": "ETH",
    # Stocks
    "tesla": "TSLA",
    "apple": "AAPL",
    "google": "GOOGL",
    "nvidia": "NVDA",
    "amazon": "AMZN",
    "microsoft": "MSFT",
    # Futures/Commodities
    "gold": "GC=F",
    "silver": "SI=F",
    "oil": "CL=F",
    "crude": "CL=F",
    "natural gas": "NG=F",
}

# CoinGecko ID mappings
COINGECKO_IDS = {
    "BTC": "bitcoin",
    "SOL": "solana",
    "ETH": "ethereum",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "XRP": "ripple",
}

def normalize_symbol(symbol: str) -> str:
    """Convert common names to ticker symbols."""
    symbol_lower = symbol.lower().strip()
    return SYMBOL_MAP.get(symbol_lower, symbol.upper())

def load_config_file() -> dict:
    """Load the price alerts YAML config."""
    return load_price_alert_config()

def save_config_file(config: dict):
    """Save the price alerts YAML config."""
    # Remove internal tracking fields before save
    config.pop('_last_triggered', None)
    save_price_alert_config(config)

def is_crypto(symbol: str) -> bool:
    """Check if symbol is a cryptocurrency."""
    crypto_symbols = ["BTC", "SOL", "ETH", "DOGE", "ADA", "XRP", "DOT", "LINK", "AVAX", "MATIC"]
    return symbol.upper() in crypto_symbols or symbol.upper() in COINGECKO_IDS

def find_asset(config: dict, symbol: str) -> tuple:
    """Find an asset in the config. Returns (asset_type, index, asset) or (None, None, None)."""
    symbol = normalize_symbol(symbol)
    
    # Check crypto
    for i, asset in enumerate(config.get("watchlist", {}).get("crypto", [])):
        if asset.get("symbol", "").upper() == symbol.upper():
            return ("crypto", i, asset)
    
    # Check stocks
    for i, asset in enumerate(config.get("watchlist", {}).get("stocks", [])):
        if asset.get("symbol", "").upper() == symbol.upper():
            return ("stocks", i, asset)
    
    return (None, None, None)

def list_alerts(config: dict) -> dict:
    """List all configured price alerts."""
    alerts = []
    
    # Crypto alerts
    for asset in config.get("watchlist", {}).get("crypto", []):
        if not asset.get("enabled", True):
            continue
        for condition in asset.get("conditions", []):
            alerts.append({
                "symbol": asset["symbol"],
                "name": asset.get("name", asset["symbol"]),
                "type": "crypto",
                "condition": condition["type"],
                "value": condition["value"],
                "severity": condition.get("severity", "medium"),
                "message": condition.get("message", "")
            })
    
    # Stock alerts
    for asset in config.get("watchlist", {}).get("stocks", []):
        if not asset.get("enabled", True):
            continue
        for condition in asset.get("conditions", []):
            alerts.append({
                "symbol": asset["symbol"],
                "name": asset.get("name", asset["symbol"]),
                "type": "stock",
                "condition": condition["type"],
                "value": condition["value"],
                "severity": condition.get("severity", "medium"),
                "message": condition.get("message", "")
            })
    
    return alerts

def add_alert(config: dict, symbol: str, condition_type: str, value: float, 
              severity: str = "high", message: str = None) -> str:
    """Add a new price alert condition."""
    symbol = normalize_symbol(symbol)
    asset_type, idx, existing = find_asset(config, symbol)
    
    # Build condition
    new_condition = {
        "type": condition_type,
        "value": value,
        "severity": severity
    }
    if message:
        new_condition["message"] = message
    else:
        # Auto-generate message
        if condition_type == "above":
            new_condition["message"] = f"{symbol} above ${value:,.0f}" if value >= 1000 else f"{symbol} above ${value}"
        elif condition_type == "below":
            new_condition["message"] = f"{symbol} dropped below ${value:,.0f}" if value >= 1000 else f"{symbol} dropped below ${value}"
        else:
            new_condition["message"] = f"{symbol} moved {value}%"
    
    if existing:
        # Add condition to existing asset
        if "conditions" not in existing:
            existing["conditions"] = []
        
        # Check for duplicate
        for cond in existing["conditions"]:
            if cond["type"] == condition_type and cond["value"] == value:
                return f"Alert already exists: {symbol} {condition_type} {value}"
        
        existing["conditions"].append(new_condition)
        config["watchlist"][asset_type][idx] = existing
    else:
        # Create new asset entry
        asset_type = "crypto" if is_crypto(symbol) else "stocks"
        
        new_asset = {
            "symbol": symbol,
            "name": symbol,
            "enabled": True,
            "conditions": [new_condition]
        }
        
        # Add CoinGecko ID for crypto
        if asset_type == "crypto" and symbol in COINGECKO_IDS:
            new_asset["coingecko_id"] = COINGECKO_IDS[symbol]
        
        if asset_type not in config.get("watchlist", {}):
            config["watchlist"][asset_type] = []
        
        config["watchlist"][asset_type].append(new_asset)
    
    save_config_file(config)
    return f"Added alert: {symbol} {condition_type} ${value:,.0f}" if value >= 1000 else f"Added alert: {symbol} {condition_type} {value}"

def remove_alert(config: dict, symbol: str, condition_type: str = None, value: float = None) -> str:
    """Remove a price alert condition or entire asset."""
    symbol = normalize_symbol(symbol)
    asset_type, idx, existing = find_asset(config, symbol)
    
    if not existing:
        return f"No alerts found for {symbol}"
    
    if condition_type is None and value is None:
        # Remove entire asset
        del config["watchlist"][asset_type][idx]
        save_config_file(config)
        return f"Removed all alerts for {symbol}"
    
    # Remove specific condition
    if "conditions" in existing:
        original_count = len(existing["conditions"])
        existing["conditions"] = [
            c for c in existing["conditions"]
            if not (
                (condition_type is None or c["type"] == condition_type) and
                (value is None or c["value"] == value)
            )
        ]
        
        removed_count = original_count - len(existing["conditions"])
        
        if removed_count == 0:
            return f"No matching alert found for {symbol}"
        
        # If no conditions left, remove the asset
        if len(existing["conditions"]) == 0:
            del config["watchlist"][asset_type][idx]
        else:
            config["watchlist"][asset_type][idx] = existing
        
        save_config_file(config)
        return f"Removed {removed_count} alert(s) for {symbol}"
    
    return f"No conditions found for {symbol}"

def update_alert(config: dict, symbol: str, condition_type: str, new_value: float, old_value: float = None) -> str:
    """Update an existing alert value.
    
    If old_value is provided, matches exactly.
    If old_value is None, updates the first matching condition_type.
    """
    symbol = normalize_symbol(symbol)
    asset_type, idx, existing = find_asset(config, symbol)
    
    if not existing:
        return f"No alerts found for {symbol}"
    
    for cond in existing.get("conditions", []):
        # Match by condition_type, and optionally by old_value if provided
        if cond["type"] == condition_type:
            if old_value is not None and cond["value"] != old_value:
                continue  # Skip if old_value provided but doesn't match
            
            old_val = cond["value"]
            cond["value"] = new_value
            # Update message
            if condition_type == "above":
                cond["message"] = f"{symbol} above ${new_value:,.0f}" if new_value >= 1000 else f"{symbol} above ${new_value}"
            elif condition_type == "below":
                cond["message"] = f"{symbol} dropped below ${new_value:,.0f}" if new_value >= 1000 else f"{symbol} dropped below ${new_value}"
            
            config["watchlist"][asset_type][idx] = existing
            save_config_file(config)
            return f"Updated {symbol} {condition_type} alert: ${old_val:,.0f} → ${new_value:,.0f}"
    
    return f"No {condition_type} alert found for {symbol}"

def main():
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        # Load config
        load_config()
        config = load_config_file()
        
        action = args.get('action', 'list').lower()
        symbol = args.get('symbol', '')
        condition_type = args.get('condition', args.get('type', '')).lower()
        value = args.get('value')
        old_value = args.get('old_value')
        severity = args.get('severity', 'high')
        message = args.get('message')
        
        # Map condition aliases
        condition_map = {
            "above": "above",
            "over": "above",
            ">=": "above",
            "below": "below",
            "under": "below",
            "<=": "below",
            "percent": "percent_change_24h",
            "percent_change": "percent_change_24h",
            "change": "percent_change_24h",
            "volatility": "percent_change_24h"
        }
        if condition_type in condition_map:
            condition_type = condition_map[condition_type]
        
        if action == 'list':
            alerts = list_alerts(config)
            
            if not alerts:
                speech = "No price alerts configured."
            else:
                # Group by symbol for speech
                by_symbol = {}
                for a in alerts:
                    if a["symbol"] not in by_symbol:
                        by_symbol[a["symbol"]] = []
                    by_symbol[a["symbol"]].append(a)
                
                speech = f"You have {len(alerts)} price alert"
                if len(alerts) != 1:
                    speech += "s"
                speech += ": "
                
                parts = []
                for sym, sym_alerts in by_symbol.items():
                    conditions = []
                    for a in sym_alerts:
                        if a["condition"] == "above":
                            conditions.append(f"above ${a['value']:,.0f}" if a['value'] >= 1000 else f"above ${a['value']}")
                        elif a["condition"] == "below":
                            conditions.append(f"below ${a['value']:,.0f}" if a['value'] >= 1000 else f"below ${a['value']}")
                        else:
                            conditions.append(f"{a['value']}% move")
                    parts.append(f"{sym} ({', '.join(conditions)})")
                
                speech += ", ".join(parts[:5])
                if len(parts) > 5:
                    speech += f", and {len(parts) - 5} more"
            
            print(json.dumps({
                "ok": True,
                "speech": speech,
                "data": {
                    "alerts": alerts,
                    "count": len(alerts),
                    "config_file": str(PRICE_ALERT_PATH)
                }
            }))
        
        elif action == 'add':
            if not symbol:
                raise ValueError("Symbol is required (e.g., BTC, TSLA, gold)")
            if not condition_type:
                raise ValueError("Condition type is required (above, below, percent_change)")
            if value is None:
                raise ValueError("Value is required")
            
            result = add_alert(config, symbol, condition_type, float(value), severity, message)
            
            print(json.dumps({
                "ok": True,
                "speech": result,
                "data": {
                    "symbol": normalize_symbol(symbol),
                    "condition": condition_type,
                    "value": value,
                    "action": "added"
                }
            }))
        
        elif action == 'remove' or action == 'delete':
            if not symbol:
                raise ValueError("Symbol is required")
            
            result = remove_alert(
                config, 
                symbol, 
                condition_type if condition_type else None,
                float(value) if value is not None else None
            )
            
            print(json.dumps({
                "ok": True,
                "speech": result,
                "data": {
                    "symbol": normalize_symbol(symbol),
                    "action": "removed"
                }
            }))
        
        elif action == 'update':
            if not symbol:
                raise ValueError("Symbol is required")
            if not condition_type:
                # Default to 'above' if not specified (most common case)
                condition_type = 'above'
            if value is None:
                raise ValueError("New value is required")
            
            # old_value is now optional - if not provided, updates first matching condition
            result = update_alert(config, symbol, condition_type, float(value), 
                                  float(old_value) if old_value is not None else None)
            
            print(json.dumps({
                "ok": True,
                "speech": result,
                "data": {
                    "symbol": normalize_symbol(symbol),
                    "condition": condition_type,
                    "old_value": old_value,
                    "new_value": value,
                    "action": "updated"
                }
            }))
        
        else:
            raise ValueError(f"Unknown action: {action}. Use list, add, remove, or update")
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Failed to manage price alerts: {e}"
        }))
        sys.exit(1)

if __name__ == "__main__":
    main()
