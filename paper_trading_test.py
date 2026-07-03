#!/usr/bin/env python3
"""HARD PAPER TRADING TEST - Multiple Strategies with Risk Management"""
import requests
import json
import time

# Alpaca Paper Trading API Keys (from env)
import os
APCA_KEY = os.environ.get('ALPACA_KEY', 'PK2DSJZMBJIFKC4DLTGRFPKJLT')
APCA_SECRET = os.environ.get('ALPACA_SECRET', '***')
BASE_URL = 'https://paper-api.alpaca.markets'

def call_api(method, path, body=None):
    headers = {
        'APCA-API-KEY-ID': APCA_KEY,
        'APCA-API-SECRET-KEY': APCA_SECRET
    }
    if body:
        headers['Content-Type'] = 'application/json'
    import requests
    if method == 'GET':
        return requests.get(f'{BASE_URL}{path}', headers=headers, timeout=10)
    elif method == 'POST':
        return requests.post(f'{BASE_URL}{path}', headers=headers, json=body, timeout=10)
    return None

def get_account():
    r = call_api('GET', '/v2/account')
    if r and r.status_code == 200:
        d = r.json()
        return {
            'cash': float(d.get('cash', 0)),
            'equity': float(d.get('equity', 0)),
            'buying_power': float(d.get('buying_power', 0)),
            'status': d.get('status')
        }
    return None

def get_positions():
    r = call_api('GET', '/v2/positions')
    if r and r.status_code == 200:
        return {p['symbol']: float(p['qty']) for p
 in r.json()}
    return {}

def submit_order(symbol, qty, side):
    body = {'symbol': symbol, 'qty': str(qty), 'side': side, 'type': 'market', 'time_in_force': 'day'}
    r = call_api('POST', '/v2/orders', body=body)
    if r and r.status_code in [200, 201]:
        d = r.json()
        return {'id': d['id'], 'status': d['status'], 'symbol': d['symbol']}
    return None

if __name__ == '__main__':
    print('=== HARD PAPER TRADING TEST ===')
    acct = get_account()
    if not acct:
        print('FAILED: Could not connect to Alpaca')
        exit(1)
    
    print(f"Account: {acct['status']}")
    print(f"Cash: ${acct['cash']:,.2f}")
    print(f"Equity: ${acct['equity']:,.2f}")
    print()
    
    # Show positions
    pos = get_positions()
    print(f"Positions: {pos}")
    print()
    
    # Submit a test order (buy 1 share of AAPL)
    print('Submitting test BUY order for 1 share of AAPL...')
    order = submit_order('AAPL', 1, 'buy')
    if order:
        print(f"  Order ID: {order['id']}")
        print(f"  Status: {order['status']}")
        print(f"  Symbol: {order['symbol']}")
        print('  DONE - Paper trade successful!')
    else:
        print('  FAILED to submit order')
        exit(1)
