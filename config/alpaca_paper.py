#!/usr/bin/env python3
"""
Alpaca Paper Trading - Direct REST API
Uses requests library (avoids alpaca-trade-api v1/v2 issues)
"""
import os, requests, json
from pathlib import Path

# API Configuration
API_KEY = "***"
API_SECRET = "***"
BASE_URL = "https://paper-api.alpaca.markets/v2"

def get_headers():
    return {
        "APCA-API-KEY-ID": API_KEY,
        "APCA-API-SECRET-KEY": API_SECRET
    }

def get_account():
    """Get account info"""
    r = requests.get(f"{BASE_URL}/account", headers=get_headers())
    r.raise_for_status()
    return r.json()

def submit_order(symbol, qty, side="buy", order_type="market", time_in_force="gtc"):
    """Submit a paper trade"""
    data = {
        "symbol": symbol,
        "qty": str(qty),
        "side": side,
        "type": order_type,
        "time_in_force": time_in_force
    }
    r = requests.post(f"{BASE_URL}/orders", headers=get_headers(), json=data)
    r.raise_for_status()
    return r.json()

def get_positions():
    """Get current positions"""
    r = requests.get(f"{BASE_URL}/positions", headers=get_headers())
    r.raise_for_status()
    return r.json()

def get_orders(status="all"):
    """Get orders"""
    r = requests.get(f"{BASE_URL}/orders?status={status}", headers=get_headers())
    r.raise_for_status()
    return r.json()

def get_assets(active_only=True):
    """Get tradeable assets"""
    url = f"{BASE_URL}/assets"
    if active_only:
        url += "?status=active"
    r = requests.get(url, headers=get_headers())
    r.raise_for_status()
    return r.json()

if __name__ == "__main__":
    print("🔍 Testing Alpaca Paper Trading...")
    try:
        account = get_account()
        print(f"✅ Account Active!")
        print(f"   Status: {account.get('status')}")
        print(f"   Cash: ${float(account.get('cash', 0)):,.2f}")
        print(f"   Equity: ${float(account.get('equity', 0)):,.2f}")
        print(f"   Buying Power: ${float(account.get('buying_power', 0)):,.2f}")
    except Exception as e:
        print(f"❌ Error: {e}")
