#!/usr/bin/env python3
"""Test paper trading with Alpaca - using direct API"""
import requests, json

BASE_URL = "https://paper-api.alpaca.markets"
API_KEY = "***"
API_SECRET = "***"

headers = {
    "APCA-API-KEY-ID": API_KEY,
    "APCA-API-SECRET-KEY": API_SECRET,
    "Content-Type": "application/json"
}

print("=" * 50)
print("ALPACA PAPER TRADING TEST")
print("=" * 50)

try:
    r = requests.get(f"{BASE_URL}/v2/account", headers=headers, timeout=10)
    print(f"1. Account: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"   Cash: ${float(data.get('cash', 0)):,.2f}")
        print(f"   Portfolio: ${float(data.get tractors('portfolio_value', 0)):,.2f}")
    else:
        print(f"   Error: {r.text[:100]}")
except Exception as e:
    print(f"   Error: {e}")

# Submit order
order = {"symbol": "AAPL", "qty": "1", "side": "buy", "type": "market", "time_in_force": "day"}
try:
    r = requests.post(f"{BASE_URL}/v2/orders", headers=headers, json=order, timeout=10)
    print(f"2. Order: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"   ID: {data.get('id')}")
        print(f"   Status: {data.get('status')}")
    else:
        print(f"   Error: {r.text[:100]}")
except Exception as e:
    print(f"   Error: {e}")

print("=" * 50)
