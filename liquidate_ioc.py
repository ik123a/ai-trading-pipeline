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
        if isinstance(data, dict):
            return [data]
        return data
    return []

def close_position(symbol, qty):
    """Close a position by market order. qty is positive for long, negative for short."""
    if qty == 0:
        return True
    side = 'sell' if qty > 0 else 'buy'
    order_qty = abs(qty)
    # We'll try to liquidate in chunks, starting with full amount, then halving on failure
    chunk = order_qty
    while chunk >= 1:
        order = {
            'symbol': symbol,
            'qty': str(int(chunk)),
            'side': side,
            'type': 'market',
            'time_in_force': 'ioc'  # immediate or cancel: fill what we can, cancel the rest
        }
        r = s.post(f'{BASE}/v2/orders', json=order)
        if r.status_code in (200, 201):
            print(f'  {side} {int(chunk)} {symbol} (IOC) -> order {r.json().get("id")}')
            # Wait a bit for the order to fill
            time.sleep(2)
            # After each chunk, check remaining position
            pos = get_positions()
            remaining_qty = 0
            for p in pos:
                if p['symbol'] == symbol:
                    remaining_qty = float(p['qty'])
                    break
            # If we didn't reduce the position, break to avoid infinite loop
            if abs(remaining_qty) >= abs(qty) - 1e-9:
                print(f'  Position unchanged after IOC order, reducing chunk size')
                chunk = max(1, chunk / 2)
                continue
            else:
                # Update qty to remaining and continue
                qty = remaining_qty
                if abs(qty) < 1e-9:
                    print(f'  Position {symbol} closed.')
                    return True
                else:
                    print(f'  Remaining {symbol}: {qty:.4f}')
                    chunk = abs(qty)  # reset chunk to remaining for next iteration
        else:
            print(f'  Failed to place IOC order for {symbol}: {r.status_code} {r.text[:100]}')
            # If we can't even place an IOC order, try a smaller chunk
            chunk = max(1, chunk / 2)
    return abs(qty) < 1e-9

def main():
    print('=== LIQUIDATE ALL POSITIONS (IOC CHUNKS) ===')
    cancel_open_orders()
    time.sleep(2)
    
    positions = get_positions()
    if not positions:
        print('No positions to liquidate.')
        return
    
    print(f'Found {len(positions)} positions:')
    for p in positions:
        print(f'  {p["symbol"]}: {p["qty"]} @ {p["avg_entry_price"]}')
    
    # Process each position
    for p in positions:
        symbol = p['symbol']
        qty = float(p['qty'])
        print(f'\nLiquidating {symbol}: {qty:.4f}')
        success = close_position(symbol, qty)
        if success:
            print(f'  {symbol} -> closed')
        else:
            print(f'  {symbol} -> failed to close fully')
    
    # Final check
    print('\n=== FINAL POSITIONS ===')
    positions = get_positions()
    if not positions:
        print('No positions remaining.')
    else:
        for p in positions:
            print(f'  {p["symbol"]}: {p["qty"]} @ {p["avg_entry_price"]}')
    
    # Account summary
    acc = s.get(f'{BASE}/v2/account').json()
    equity = float(acc.get('equity', 0))
    cash = float(acc.get('cash', 0))
    print(f'\nAccount: {acc.get("status")}')
    print(f'Equity: ${equity:,.2f}')
    print(f'Cash: ${cash:,.2f}')

if __name__ == '__main__':
    main()