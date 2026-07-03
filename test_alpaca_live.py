#!/usr/bin/env python3
"""Test Alpaca API with fresh keys"""
import os, requests

os.environ['APCA_API_KEY_ID'] = 'PKRUAZIR3U6K24TSBSO54JEWXN'
os.environ['APCA_API_SECRET_KEY'] = '6LuvEybilLpM7DGJyqSeM1FJTnapC5V1B7eyW'

url = "https://paper-api.alpaca.markets/v2/account"
headers = {
    'APCA-API-KEY-ID': os.environ['APCA_API_KEY_ID'],
    'APCA-API-SECRET-KEY': os.environ['APCA_API_SECRET_KEY']
}

try:
    r = requests.get(url, headers=headers)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print("\n✅ API Connection: SUCCESS")
        print(f"Account: {data.get('id')}")
        print(f"Status: {data.get('status')}")
        print(f"Portfolio: ${float(data.get('portfolio_value', 0)):,.2f}")
        print(f"Cash: ${float(data.get('cash', 0)):,.2f}")
        print(f"Buying Power: ${float(data.get('buying_power', 0)):,.2f}")
    else:
        print(f"Response: {r.text[:200]}")
except Exception as e:
    print(f"Error: {e}")
