#!/usr/bin/env python3
"""Paper trading test using env vars"""
import os, requests

# Read keys from env (set by you)
KEY = 'PK2DSJZMBJIFKC4DLTGRFPKJLT'
SECRET='***'

print(f"Using provided keys")
print(f"Key length: {len(KEY)}")
print(f"Secret length: {len(SECRET)}")

if not KEY or not SECRET:
    print("Set ALPACA_KEY and ALPACA_SECRET env vars")
    exit(1)

headers = {
    'APCA-API-KEY-ID': KEY,
    'APCA-API-SECRET-KEY': SECRET
}

# Test paper endpoint
r = requests.get('https://paper-api.alpaca.markets/v2/account', headers=headers)
print(f"Status: {r.status_code}")

if r.status_code == 200:
    data = r.json()
    print(f"Account: {data.get('id')}")
    print(f"Cash: ${float(data.get('cash', 0)):,.2f}")
    print(f"Portfolio: ${float(data.get('portfolio_value', 0)):,.2f}")
    
    # Submit test order
    order = {
        "symbol": "AAPL",
        "qty": "1",
        "side": "buy",
        "type": "market",
        "time_in_force": "day"
    }
    r2 = requests.post('https://paper-api.alpaca.markets/v2/orders', headers=headers, json=order)
    print(f"Order Status: {r2.status_code}")
    if r2.status_code == 200:
        d2 = r2.json()
        print(f"Order ID: {d2.get('id')}")
        print(f"Status: {d2.get('status')}")
    else:
        print(f"Order Error: {r2.text[:100]}")
else:
    print(f"Error: {r.text[:100]}")
