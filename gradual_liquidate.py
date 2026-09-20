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

def get_quote(symbol):
    r = s.get(f'{BASE}/v2/stocks/{symbol}/trades/latest')
    if r.status_code == 200:
        return float(r.json()['trade']['p'])
    return None

def main():
    print('=== GRADUAL LIQUIDATION ===')
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
        # We'll slice into 10% chunks
        chunk = max(1, int(abs(qty) * 0.1))
        remaining = abs(qty)
        print(f'{sym}: total {qty:.4f}, will liquidate in chunks of {chunk}')
        while remaining > 0:
            this_chunk = min(chunk, int(remaining))
            if this_chunk < 1:
                break
            price = get_quote(sym)
            if price is None:
                print(f'  Could not get quote for {sym}, skipping chunk')
                break
            # For sell, use price slightly below market; for buy, slightly above
            if side == 'sell':
                limit_price = round(price * 0.999, 2)  # slightly below market
            else:
                limit_price = round(price * 1.001, 2)  # slightly above market
            print(f'  Submitting {side} {this_chunk} {sym} @ limit {limit_price}')
            order = {
                'symbol': sym,
                'qty': str(this_chunk),
                'side': side,
                'type': 'limit',
                'time_in_force': 'day',
                'limit_price': str(limit_price)
            }
            resp = s.post(f'{BASE}/v2/orders', json=order)
            if resp.status_code in (200, 201):
                print(f'    -> order placed: {resp.json().get("id")}')
            else:
                print(f'    -> FAILED: {resp.status_code} {resp.text[:200]}')
                # If limit fails, try market
                order_mkt = {
                    'symbol': sym,
                    'qty': str(this_chunk),
                    'side': side,
                    'type': 'market',
                    'time_in_force': 'day'
                }
                resp2 = s.post(f'{BASE}/v2/orders', json=order_mkt)
                if resp2.status_code in (200, 201):
                    print(f'    -> market order placed: {resp2.json().get("id")}')
                else:
                    print(f'    -> market FAILED: {resp2.status_code} {resp2.text[:200]}')
            remaining -= this_chunk
            print(f'    Remaining to close: {remaining}')
            time.sleep(2)  # pause between chunks
    
    print('\\nWaiting 30 seconds for all chunks to fill...')
    time.sleep(30)
    
    # Final check
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