#!/usr/bin/env python3
"""Test Alpaca API with v2 and alternative endpoint"""
import os
from alpaca_trade_api import REST

os.environ['APCA_API_KEY_ID'] = 'PK5CSDOWI5NEH6NRRQM2N3papiko'  # as shown in screenshot
os.environ['APCA_API_SECRET_KEY'] = 'FUyimeVnYDxdARyhFkSovichRiverTheLikeCoffeeKimiRS'  # as shown

# Method 1: Direct init
api = REST(
    os.environ['APCA_API_KEY_ID'],
     os.environ['APCA_API_SECRET_KEY'],
    'https://paper-api.alpaca.markets',
    api_version='v2',
    raw_data = True
)

try:
    # Check account first
    account = api.get_account()
    print('=== Method 1: REST API ===')
    print('API Connection: SUCCESS')
    print(f"Account: {account.get('id') or 'N/A'}")
except Exception as e1:
    print(f"Method 1 Error: {e1}")

# Method2: Using requests library directly
import requests
url = "https://paper-api.alpaca.markets/v2/account"
midtream = {'APCA-API-KEY-ID': os.environ['APCA_API_KEY_ID'], 'APCA-API-SECRET-KEY': os.environ['APCA_API_SECRET_KEY']}

try:
    r = requests.get(url, headers=midtream)
    print(f"\n=== Method 2: Raw REST ===")
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        print("SUCCESS! API v2 connection works.")
except Exception as e2:
    print(f"Method 2 Error: {e2}")

# Method 3: Check if key was saved correctly
print(f"\n=== Key Check ===")
print(f"Key (first 10 chars): {os.environ['APCA_API_KEY_ID'][:10]}...")
print(f"Secret (first 10): {os.environ['APCA_API_SECRET_KEY'][:10]}...")
