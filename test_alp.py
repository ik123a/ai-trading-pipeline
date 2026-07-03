#!/usr/bin/env python3
"""Test Alpaca with fresh keys"""
import os, requests

os.environ['APCA_API_KEY_ID'] = '***'
os.environ['APCA_API_SECRET_KEY'] = '***'

url = "https://paper-api.alpaca.markets/v2/account"
headers = {
    'APCA-API-KEY-ID': os.environ['APCA_API_KEY_ID'],
    'APCA-API-SECRET-KEY': os.environ['APCA_API_SECRET_KEY']
}

try:
    r = requests.get(url, headers=headers, timeout=10)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print("\nAPI Connection: SUCCESS")
        print(f"Account: {data.get('id')}")
        print(f"Status: {data.get('status')}")
        print(f"Portfolio: ${float(data.get('portfolio_value', 0)):,.2f}")
        print(f"Cash: ${float(data.get('cash', 0)):,.2f}")
    else:
        print(f"Response: {r.text[:200]}")
except Exception as e:
    print(f"Error: {e}")
