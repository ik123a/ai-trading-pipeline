#!/usr/bin/env python3
"""Alpaca Paper Trading Adapter - Using direct HTTP requests"""
import os
import requests
from typing import Dict, Any, Optional

# ── Configuration ──
ALPACA_BASE_URL = "https://paper-api.alpaca.markets/v2"
ALPACA_API_KEY_ID = "***"
ALPACA_SECRET_KEY = "***"

HEADERS = {
    "APCA-API-KEY-ID": ALPACA_API_KEY_ID,
    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    "Content-Type": "application/json",
}


# ── Account ──
def get_account() -> Dict[str, Any]:
    """Fetch account information"""
    r = requests.get(f"{ALPACA_BASE_URL}/account", headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()


# ── Orders ──
def submit_order(
    symbol: str,
    qty: int,
    side: str,  # "buy" or "sell"
    order_type: str = "market",  # "market", "limit", etc.
    time_in_force: str = "gtc",  # "gtc", "day", "ioc", "fok"
    limit_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Submit a paper trading order"""
    data = {
        "symbol": symbol,
        "qty": str(qty),
        "side": side,
        "type": order_type,
        "time_in_force": time_in_force,
    }
    if limit_price:
        data["limit_price"] = str(limit_price)
    
    r = requests.post(f"{ALPACA_BASE_URL}/orders", headers=HEADERS, json=data, timeout=10)
    r.raise_for_status()
    return r.json()


def get_orders(status: str = "all") -> list:
    """Get all orders (open, closed, or all)"""
    r = requests.get(f"{ALPACA_BASE_URL}/orders?status={status}", headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()


# ── Positions ──
def get_positions() -> list:
    """Get current positions"""
    r = requests.get(f"{ALPACA_BASE_URL}/positions", headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()


def get_position(symbol: str) -> Dict[str, Any]:
    """Get position for a specific symbol"""
    r = requests.get(f"{ALPACA_BASE_URL}/positions/{symbol}", headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()


# ── Test ──
if __name__ == "__main__":
    print("Testing Alpaca Paper Trading...")
    try:
        account = get_account()
        print(f"✅ Account Status: {account['status']}")
        print(f"   Cash: ${float(account['cash']):,.2f}")
        print(f"   Equity: ${float(account['equity']):,.2f}")
        print(f"   Buying Power: ${float(account['buying_power']):,.2f}")
        print("\nPaper trading is ACTIVE and ready!")
    except Exception as e:
        print(f"❌ Error: {e}")
