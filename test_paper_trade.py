#!/usr/bin/env python3
"""Test paper trading with Alpaca"""
import requests, json

# Paper trading endpoint
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

# Step 1: Check account
try:
    r = requests.get(f"{BASE_URL}/v2/account", headers=headers, timeout=10)
    print(f"
1. Account Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"   Account: {data.get('id')}")
        print(f"   Status: {data.get('status')}")
        print(f"   Cash: ${float(data.get('cash', 0)):,.2f}")
        print(f"   Portfolio: ${float(data.get('portfolio_value', 0)):,.2f}")
    else:
        print(f"   Error: {r.text}")
except Exception as e:
    print(f"   Error: {e}")

# Step 2: Submit paper order
try:
    order = {
        "symbol": "AAPL",
        "qty": "1",
        "side": "buy",
        "type": "market",
        "time_in_force": "day"
    }
    r = requests.post(f"{BASE_URL}/v2/orders", headers=headers, json=order, timeout=10)
    print(f"
2. Order Submission: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"   Order ID: {data.get('id')}")
        print(f"   Symbol: {data.get('symbol')}")
        print(f"   Qty: {data.get('qty')}")
        print(f"   Side: {data.get('side')}")
        print(f"   Status: {data.get('status')}")
    else:
        print(f"   Error: {r.text}")
except Exception as e:
    print(f"   Error: {e}")

# Step 3: List positions
try:
    r = requests.get(f"{BASE_URL}/v2/positions", headers=headers, timeout=10)
    print(f"
3. Positions: {r.status_code}")
    if r.status_code == 200:
        positions = r.json()
        print(f"   Count: {len(positions)}")
        for p in positions:
            print(f"   - {p.get('symbol')}: {p.get('qty')} shares")
    else:
        print(f"   Error: {r.text}")
except Exception as e:
    print(f"   Error: {e}")

print("
" + "=" * 50)
