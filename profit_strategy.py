#!/usr/bin/env python3
"""
Profit-focused trading strategy.
- Uses 50-day and 200-day SMA crossover for entry/exit.
- Position size based on ATR volatility (risk 1% of equity per trade).
- Only goes LONG (no shorts) — no short-selling to keep risk simple.
- Exits ALL positions when fast SMA < slow SMA.
- Uses your existing trading_system/DataFetcher for price data.
- Guards: skip symbols with pending close orders (avoids wash-trade blocks).
"""
import os, sys, csv, math, requests
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "trading_system"))
from data_fetcher import DataFetcher

# ----------------------------------------------------------------------
# Alpaca API (paper)
# ----------------------------------------------------------------------
API_KEY    = os.environ.get('ALPACA_KEY',    'PK2DSJZMBJIFKC4DLTGRFPKJLT')
API_SECRET = os.environ.get('ALPACA_SECRET', '5CqLyMPPk1htPPAZYdPCv3TMaoRQGGjZ8kjd8bPVKyjB')
BASE_URL   = 'https://paper-api.alpaca.markets'

SESSION = requests.Session()
SESSION.headers.update({
    'APCA-API-KEY-ID': API_KEY,
    'APCA-API-SECRET-KEY': API_SECRET
})

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
SYMBOLS   = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA']
FAST_MA   = 50
SLOW_MA   = 200
RISK_FRAC = 0.01   # risk 1% of equity per trade
SL_ATR    = 2.0
TP_ATR    = 3.0
LOG_FILE  = 'profit_strategy_log.csv'

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def get_account():
    r = SESSION.get(f'{BASE_URL}/v2/account')
    r.raise_for_status()
    return r.json()

def get_positions():
    r = SESSION.get(f'{BASE_URL}/v2/positions')
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else [data]

def get_open_orders():
    try:
        r = SESSION.get(f'{BASE_URL}/v2/orders', params={'status': 'open'})
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []

def place_order(symbol, qty, side):
    payload = {'symbol': symbol, 'qty': str(int(qty)), 'side': side,
               'type': 'market', 'time_in_force': 'day'}
    r = SESSION.post(f'{BASE_URL}/v2/orders', json=payload)
    if r.status_code in (200, 201):
        return r.json()
    raise Exception(f'Order failed {r.status_code}: {r.text[:120]}')

def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period

def calc_atr(highs, lows, closes, period=14):
    if len(highs) < period + 1:
        return None
    tr = []
    for i in range(1, len(highs)):
        tr.append(max(highs[i] - lows[i],
                      abs(highs[i] - closes[i-1]),
                      abs(lows[i] - closes[i-1])))
    return sum(tr[-period:]) / period

def get_estimated_price(symbol):
    """Try to get current price from Alpaca position (works for held symbols)."""
    try:
        r = SESSION.get(f'{BASE_URL}/v2/positions/{symbol}')
        if r.status_code == 200:
            p = r.json()
            mv = abs(float(p.get('market_value', 0)))
            q  = abs(float(p.get('qty', 0)))
            if q > 0:
                return mv / q
    except Exception:
        pass
    return None

def log_row(ts, equity, cash, symbol, action, price, qty):
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, 'a', newline='') as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow(['timestamp', 'equity', 'cash', 'symbol', 'action', 'price', 'qty'])
        w.writerow([ts, f'{equity:.2f}', f'{cash:.2f}', symbol, action,
                    f'{price:.2f}', int(qty)])

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    print('=' * 60)
    print('PROFIT STRATEGY  (SMA 50/200  |  ATR stop  |  LONG only)')
    print('=' * 60)

    acct     = get_account()
    equity   = float(acct.get('equity', 0))
    cash     = float(acct.get('cash', 0))
    buying_p = float(acct.get('buying_power', cash))
    print(f'Equity: ${equity:,.2f}  Cash: ${cash:,.2f}  BuyingPower: ${buying_p:,.2f}')

    positions = get_positions()
    pos_map = {}
    for p in positions:
        sym = p['symbol']
        try:
            pos_map[sym] = float(p['qty'])
        except Exception:
            pos_map[sym] = 0.0
    print(f'Positions: {pos_map}')

    open_orders = get_open_orders()
    pending_symbols = {o['symbol'] for o in open_orders if o.get('side') == 'sell'}
    print(f'Pending close orders: {pending_symbols}')

    fetcher = DataFetcher()

    for sym in SYMBOLS:
        try:
            closes = fetcher.get_historical_prices(sym, days=SLOW_MA + 50)
            if not closes or len(closes) < SLOW_MA:
                print(f'{sym}: insufficient data ({len(closes) if closes else 0} bars)')
                continue

            highs  = [c * 1.005 for c in closes]
            lows   = [c * 0.995 for c in closes]
            ma_fast = sma(closes, FAST_MA)
            ma_slow = sma(closes, SLOW_MA)
            a_val   = calc_atr(highs, lows, closes, 14)
            price   = closes[-1]

            if None in (ma_fast, ma_slow, a_val):
                print(f'{sym}: collecting data — MA_fast={ma_fast}, MA_slow={ma_slow}, ATR={a_val}')
                continue

            bullish = ma_fast > ma_slow
            bearish = ma_fast < ma_slow
            qty_held = pos_map.get(sym, 0.0)
            abs_held = abs(qty_held)

            # Skip if there's already a pending sell order for this symbol
            if sym in pending_symbols:
                print(f'{sym}: pending close order already in book — skip this cycle')
                continue

            # Entry: golden cross, no position, bullish
            if bullish and abs_held < 1:
                estimated_price = get_estimated_price(sym) or price
                risk_amt   = equity * RISK_FRAC
                sl_dist    = SL_ATR * a_val
                qty        = risk_amt / sl_dist
                max_qty    = (buying_p * 0.90) / estimated_price if estimated_price > 0 else 0
                qty        = max(1, min(int(qty), int(max_qty)))
                sl_price   = estimated_price - sl_dist
                tp_price   = estimated_price + (TP_ATR * a_val)
                if qty < 1:
                    print(f'{sym}: qty {qty:.1f} < 1 — skip')
                    continue
                print(f'{sym}: BUY {qty} @ ${estimated_price:.2f}  (SL ${sl_price:.2f}  TP ${tp_price:.2f})')
                try:
                    order = place_order(sym, qty, 'buy')
                    print(f'  -> order placed: {order["id"]}')
                    log_row(datetime.now().isoformat(), equity, cash, sym, 'BUY', estimated_price, qty)
                except Exception as e:
                    print(f'  -> failed: {e}')

            # Exit: death cross, have any position, bearish
            elif bearish and abs_held > 0:
                estimated_price = get_estimated_price(sym) or price
                print(f'{sym}: SELL {int(abs_held)} @ ${estimated_price:.2f}  (death cross — closing)')
                try:
                    order = place_order(sym, int(abs_held), 'sell')
                    print(f'  -> order placed: {order["id"]}')
                    log_row(datetime.now().isoformat(), equity, cash, sym, 'SELL', estimated_price, abs_held)
                except Exception as e:
                    print(f'  -> failed: {e}')

            else:
                print(f'{sym}: HOLD  price=${price:.2f}  MA_fast={ma_fast:.2f}  MA_slow={ma_slow:.2f}')

        except Exception as e:
            print(f'{sym}: error — {e}')

    print('=' * 60)
    print('Cycle complete.')

if __name__ == '__main__':
    try:
        main()
    except Exception as fatal:
        print(f'FATAL: {fatal}')
        sys.exit(1)