#!/usr/bin/env python3
import os, requests

os.environ['APCA_API_KEY_ID'] = 'PK5CSDOWI5NEH6NRRQM2N3papiko'
os.environ['APCA_API_SECRET_KEY'] = 'FUyimeVnYDxdARyhFkSovichRiverTheLikeCoffeeKimiRS'

url = "https://paper-api.alpaca.markets/v2/account"
headers = {
    'APCA-API-KEY-ID': os.environ['APCA_API_KEY_ID'],
    'APCA-API-SECRET-KEY': os.environ['APCA_API_SECRET_KEY']
}
try:
    r = requests.get(url, headers=headers)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text[:200]}")
except Exception as e:
    print(f"Error: {e}")
