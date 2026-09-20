#!/usr/bin/env python3
import os, requests, sys, time

KEY = os.environ.get('ALPACA_KEY', 'PK2DSJZMBJIFKC4DLTGRFPKJLT')
SECRET = os.environ.get('ALPACA_SECRET', '5CqLyMPPk1htPPAZYdPCv3TMaoRQGGjZ8kjd8bPVKyjB')
BASE = 'https://paper-api.alpaca.markets'
s = requests.Session()
s.headers.update({'APCA-API-KEY-ID': KEY, 'APCA-API-SECRET-KEY': SECRET})

def cancel_all():
    try:
        r = s.get(f'{BASE}/v2/orders?status=open')
        if r.status_code == 200:
            for o in r.json():
                sid = o['id']
                delr = s.delete(f'{BASE}/v2/orders/{sid}')
                if delr.status_code == 204:
                    print(f'Cancelled {sid}')
                else:
                    print(f'Failed cancel {sid}: {delr.status_code}')
    except Exception as e:
        print(f'Error cancelling: {e}')

def get_positions():
    r = s.get(f'{BASE}/v2/positions')
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, dict):
            return [data]
        return data
    return []

def main():
    print('=== FLATTEN ALL POSITIONS ===')
    cancel_all()
    time.sleep(2)
    positions = get_positions()
    if not positions:
        print('No positions.')
        return
    for p in positions:
        sym = p['symbol']
        qty = float(p['qty'])
        if abs(qty) < 0.001:
            continue
        side = 'sell' if qty > 0 else 'buy'
        order_qty = abs(qty)
        print(f'Closing {sym}: {side} {order_qty:.4f}')
        order = {'symbol': sym, 'qty': str(order_qty), 'side': side, 'type': 'market', 'time_in_force': 'day'}
        resp = s.post(f'{BASE}/v2/orders', json=order)
        if resp.status_code in (200, 201):
            print(f'  -> order placed: {resp.json().get("id")}')
        else:
            print(f'  -> FAILED: {resp.status_code} {resp.text[:200]}')
    print('\\nWaiting 15 seconds for fills...')
    time.sleep(15)
    # Check remaining
    positions = get_positions()
    remaining = [p for p in positions if abs(float(p.get('qty',0))) > 0.001]
    if not remaining:
        print('\\n✅ All positions closed.')
    else:
        print('\\n⚠️  Remaining positions:')
        for p in remaining:
            sym = p['symbol']
            qty = float(p['qty'])
            print(f'  {sym}: {qty:.4f}')
    # Account
    acc = s.get(f'{BASE}/v2/account').json()
    equity = float(acc.get('equity',0))
    cash = float(acc.get('cash',0))
    print(f'\\nAccount: {acc.get("status")}')
    print(f'Equity: ${equity:,.2f}')
    print(f'Cash: ${cash:,.2f}')

if __name__ == '__main__':
    main()