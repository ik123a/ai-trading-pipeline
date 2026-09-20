#!/usr/bin/env python3
import os, requests, sys, time

KEY = os.environ.get('ALPACA_KEY', 'PK2DSJZMBJIFKC4DLTGRFPKJLT')
SECRET = os.environ.get('ALPACA_SECRET', '5CqLyMPPk1htPPAZYdPCv3TMaoRQGGjZ8kjd8bPVKyjB')
BASE = 'https://paper-api.alpaca.markets'
s = requests.Session()
s.headers.update({'APCA-API-KEY-ID': KEY, 'APCA-API-SECRET-KEY': SECRET})

def cancel_open_orders():
    try:
        r = s.get(f'{BASE}/v2/orders?status=open')
        if r.status_code == 200:
            for o in r.json():
                s.delete(f'{BASE}/v2/orders/{o["id"]}')
                print(f'Cancelled order {o["id"]} for {o["symbol"]}')
    except Exception as e:
        print(f'Error cancelling orders: {e}')

def get_positions():
    r = s.get(f'{BASE}/v2/positions')
    if r.status_code == 200:
        data = r.json()
        if not isinstance(data, list):
            data = [data]
        return data
    return []

def main():
    print('=== LIQUIDATE ALL POSITIONS (STAGED) ===')
    cancel_open_orders()
    time.sleep(2)
    
    positions = get_positions()
    if not positions:
        print('No positions to liquidate.')
    else:
        longs = []
        shorts = []
        for p in positions:
            sym = p['symbol']
            qty = float(p['qty'])
            if qty > 0:
                longs.append((sym, qty))
            elif qty < 0:
                shorts.append((sym, -qty))  # store positive magnitude
        print(f'Longs: {len(longs)}, Shorts: {len(shorts)}')
        # Sell longs
        for sym, qty in longs:
            print(f'Selling LONG {sym}: {qty:,.4f}')
            order = {'symbol': sym, 'qty': str(qty), 'side': 'sell', 'type': 'market', 'time_in_force': 'day'}
            r = s.post(f'{BASE}/v2/orders', json=order)
            if r.status_code in (200, 201):
                print(f'  -> order placed: {r.json().get("id")}')
            else:
                print(f'  -> FAILED: {r.status_code} {r.text[:200]}')
        print('Waiting 8 seconds for sells to settle...')
        time.sleep(8)
        # Refresh buying power
        acc = s.get(f'{BASE}/v2/account').json()
        cash = float(acc.get('cash', 0))
        buying = float(acc.get('buying_power', 0))
        print(f'After sells: cash=${cash:,.2f}, buying power=${buying:,.2f}')
        # Buy to cover shorts
        for sym, qty in shorts:
            print(f'Buying to COVER SHORT {sym}: {qty:,.4f}')
            order = {'symbol': sym, 'qty': str(qty), 'side': 'buy', 'type': 'market', 'time_in_force': 'day'}
            r = s.post(f'{BASE}/v2/orders', json=order)
            if r.status_code in (200, 201):
                print(f'  -> order placed: {r.json().get("id")}')
            else:
                print(f'  -> FAILED: {r.status_code} {r.text[:200]}')
        print('Waiting 8 seconds for buys to settle...')
        time.sleep(8)
    # Final check
    print('\n=== FINAL POSITIONS ===')
    positions = get_positions()
    if not positions:
        print('No positions.')
    else:
        for p in positions:
            sym = p['symbol']
            qty = float(p['qty'])
            print(f'{sym}: {qty:,.4f}')
    # Account summary
    acc = s.get(f'{BASE}/v2/account').json()
    equity = float(acc.get('equity', 0))
    cash = float(acc.get('cash', 0))
    buying = float(acc.get('buying_power', 0))
    print(f'\nAccount: {acc.get("status")}')
    print(f'Equity: ${equity:,.2f}')
    print(f'Cash: ${cash:,.2f}')
    print(f'Buying Power: ${buying:,.2f}')

if __name__ == '__main__':
    main()