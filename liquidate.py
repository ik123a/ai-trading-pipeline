#!/usr/bin/env python3
import os, requests, sys
from datetime import datetime

KEY = os.environ.get('ALPACA_KEY', 'PK2DSJZMBJIFKC4DLTGRFPKJLT')
SECRET = os.environ.get('ALPACA_SECRET', '5CqLyMPPk1htPPAZYdPCv3TMaoRQGGjZ8kjd8bPVKyjB')
BASE = 'https://paper-api.alpaca.markets'
s = requests.Session()
s.headers.update({'APCA-API-KEY-ID': KEY, 'APCA-API-SECRET-KEY': SECRET})

print('Fetching positions...')
pos = s.get(f'{BASE}/v2/positions').json()
if not isinstance(pos, list):
    pos = [pos]

print(f'Found {len(pos)} positions to close:')
for p in pos:
    sym = p['symbol']
    qty = float(p['qty'])
    side = 'sell' if qty > 0 else 'buy'
    order_qty = abs(qty)
    print(f'  {sym}: {qty:,.4f} -> {side} {order_qty:,.4f}')
    # Use market order to close
    order = {
        'symbol': sym,
        'qty': str(order_qty),
        'side': side,
        'type': 'market',
        'time_in_force': 'day'
    }
    r = s.post(f'{BASE}/v2/orders', json=order)
    if r.status_code in (200, 201):
        print(f'    -> order placed: {r.json().get("id")}')
    else:
        print(f'    -> FAILED: {r.status_code} {r.text[:200]}')

print('Waiting 5 seconds for fills...')
import time; time.sleep(5)

# Check remaining
pos2 = s.get(f'{BASE}/v2/positions').json()
if not isinstance(pos2, list):
    pos2 = [pos2]
remaining = [p for p in pos2 if abs(float(p.get('qty',0))) > 0.0001]
if remaining:
    print('Still have positions:')
    for p in remaining:
        print(f"  {p['symbol']}: {p['qty']}")
else:
    print('All positions closed.')

# Show account
acc = s.get(f'{BASE}/v2/account').json()
print(f"Account: {acc.get('status')}  Equity: ${float(ac.get('equity',0)):,.2f}  Cash: ${float(ac.get('cash',0)):,.2f}")