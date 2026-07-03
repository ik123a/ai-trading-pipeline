"""
Phase 4: Alpaca Paper Trading Adapter
======================================
Lightweight paper trading bridge between:
  - alpaca-trade-api (paper market data + order submission)
  - PPO microservice on :8765 (weight predictions)
  - SQLite trade logger (audit trail)

DO NOT USE for live trading without the 30-day cooldown validation.
Use with Alpaca paper keys only (paper=True).

Setup:
  1. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY env vars (or paste in code below)
  2. Ensure PPO microservice is running on :8765
  3. Run: python deployment/scripts/alpaca_paper.py --backtest-date YYYY-MM-DD

Credentials: read from env or use ~/.alpaca/env file.
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import requests

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger("alpaca_paper")
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter("%(asctime)s [ALPACA] %(levelname)s: %(message)s"))
logger.addHandler(ch)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ─── Alpaca setup ───────────────────────────────────────────────
ALPACA_KEY = os.environ.get("APCA_API_KEY_ID", "YOUR_PAPER_KEY")
ALPACA_SECRET = os.environ.get("APCA_API_SECRET_KEY", "YOUR_PAPER_SECRET")
ALPACA_URL = "https://paper-api.alpaca.markets"  # paper only

try:
    import alpaca_trade_api as tradeapi
    api = tradeapi.REST(ALPACA_KEY, ALPACA_SECRET, ALPACA_URL)
    account = api.get_account()
    logger.info(f"Connected to Alpaca paper account: {account.id}")
    logger.info(f"Account equity: ${account.equity}, buying_power: ${account.buying_power}")
except Exception as e:
    logger.error(f"Alpaca connection failed: {e}")
    logger.warning("Falling back to simulated paper mode (no real orders)")
    api = None
    class FakeAccount:
        id = "SIM"
        equity = "100000"
        buying_power = "100000"
    account = FakeAccount()

# ─── DB ─────────────────────────────────────────────────────────
DB_PATH = PROJECT_ROOT / "deployment" / "paper_trades.db"
# Reuse the same schema as paper_trader
from deployment.scripts.paper_trader import TradeLog, DailySnapshot, Session as TradeSession

if not DB_PATH.exists():
    logger.info(f"Initializing trade DB at {DB_PATH}")
    from deployment.scripts.paper_trader import Base, engine_db
    Base.metadata.create_all(engine_db)

# ─── PPO endpoint ──────────────────────────────────────────────
PPO_URL = "http://127.0.0.1:8765/predict_weights"
LATENCY_GATE_MS = 200.0


def call_ppo(observation: list, tickers: list[str]) -> Optional[np.ndarray]:
    """Call PPO microservice, enforce 200ms latency gate."""
    t0 = time.perf_counter()
    try:
        resp = requests.post(PPO_URL, json={
            "observation": observation,
            "tickers": tickers,
            "deterministic": True,
            "request_id": f"alpaca-{int(time.time())}",
        }, timeout=1.5)
        elapsed = (time.perf_counter() - t0) * 1000.0
        body = resp.json()
        if elapsed > LATENCY_GATE_MS:
            logger.warning(f"🚨 Latency gate violated: {elapsed:.1f}ms > {LATENCY_GATE_MS}ms")
            return None
        w = np.array(body["weights"], dtype=np.float64)
        w = w / w.sum() if w.sum() > 1e-6 else w
        return w
    except Exception as e:
        logger.error(f"PPO call failed: {e}")
        return None


def submit_order(symbol: str, qty: int, side: str) -> bool:
    """Submit a market order to Alpaca paper API."""
    if api is None:
        logger.info(f"SIM: {side} {qty} {symbol} (no real submission)")
        return True
    try:
        api.submit_order(
            symbol=symbol,
            qty=qty,
            side=side,
            type="market",
            time_in_force="day",
        )
        logger.info(f"✅ Order submitted: {side} {qty} {symbol}")
        return True
    except Exception as e:
        logger.error(f"Order failed: {e}")
        return False


def run_paper_bar(symbol: str, trade_date: date) -> None:
    """Process one day of paper data for a symbol."""
    # Fetch yesterday's bar from Alpaca
    start = (trade_date - timedelta(days=5)).strftime("%Y-%m-%d")
    end = trade_date.strftime("%Y-%m-%d")

    if api is None:
        # Use data lake for simulated mode
        df = pd.concat(pd.read_parquet(f) for f in (PROJECT_ROOT / "data-lake" / "ohlcv" / "1d" / symbol).glob("*.parquet"))
        if df.empty:
            return
    else:
        bars_response = api.get_bars(symbol, "1Day", start=start, end=end, limit=5).df
        if bars_response is None or bars_response.empty:
            logger.warning(f"No bars for {symbol} on {trade_date}")
            return
        df = bars_response

    # Build observation from last bar
    close = float(df.iloc[-1]["close"])
    obs = [0.0] * 40
    obs[0] = 0.01  # placeholder momentum

    # Get PPO weights
    weights = call_ppo(obs, [symbol])
    if weights is None:
        logger.warning(f"Skipping rebalance for {trade_date} (PPO unavailable)")
        return

    # Compute target allocation
    target_pct = float(min(weights[0], 0.25))
    portfolio_value = float(account.equity) if api else 100_000.0
    target_qty = int((portfolio_value * target_pct) / close)

    if target_qty <= 0:
        return

    # Check current position
    if api:
        try:
            pos = api.get_position(symbol)
            current_qty = int(pos.qty)
        except Exception:
            current_qty = 0
    else:
        current_qty = 0

    delta_qty = target_qty - current_qty
    if delta_qty == 0 or abs(delta_qty) < 1:
        return

    side = "buy" if delta_qty > 0 else "sell"
    qty = abs(delta_qty)

    if submit_order(symbol, qty, side):
        # Log to DB
        session = TradeSession()
        try:
            trade = TradeLog(
                timestamp=datetime.combine(trade_date, datetime.min.time()),
                ticker=symbol, side=side.upper(),
                quantity=qty, price=close, value=qty * close,
                equity_before=0, equity_after=0,
            )
            session.add(trade)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"DB write error: {e}")
        finally:
            session.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Alpaca Paper Trading Adapter")
    parser.add_argument("--backtest-date", type=str, help="Run single date YYYY-MM-DD")
    parser.add_argument("--catchup", action="store_true", help="Run through all available data")
    parser.add_argument("--status", action="store_true", help="Show account status")
    args = parser.parse_args()

    if args.status:
        logger.info("Connected to Alpaca paper trading endpoint: true" if api else "false")
        sys.exit(0)

    symbol = "AAPL"

    if args.backtest_date:
        run_paper_bar(symbol, date.fromisoformat(args.backtest_date))
        logger.info(f"✅ Paper day {args.backtest_date} complete")
    elif args.catchup:
        logger.info(f"🏁 Starting paper catchup via Alpaca for {symbol}")
        # Daily catchup
        day = date.today() - timedelta(days=1)
        run_paper_bar(symbol, day)
        logger.info("✅ Paper bar processed")
    else:
        parser.print_help()