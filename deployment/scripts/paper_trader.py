"""
Phase 4: Paper Trading Runner
===============================
Standalone NautilusTrader paper trading system that:

1. Reads new daily data from the Parquet lake (simulating "live" bar arrival)
2. Feeds bars to the PPO microservice for weight prediction
3. Simulates order fills using a sandbox execution adapter
4. Logs every trade + daily equity to SQLite via SQLAlchemy
5. Exposes Prometheus metrics for monitoring
6. Can be scheduled to run daily (catching up new data)

This does NOT require Docker, Alpaca, or PostgreSQL.
When Docker is available, the Docker Compose stack (deployment/) wraps
these components into a containerized setup.

Usage:
    # Run one day at a time (incremental mode)
    python deployment/scripts/paper_trader.py --date 2025-01-02

    # Run the entire backlog (catch-up mode)
    python deployment/scripts/paper_trader.py --catchup
"""
import argparse
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

# Nautilus
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Price, Quantity, Money
from nautilus_trader.model.currencies import USD as USD_CCY
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.data import BarType

# SQLAlchemy trade logger
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

# Prometheus
from prometheus_client import start_http_server, Gauge, Histogram, Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "strategies"))
sys.path.insert(0, str(PROJECT_ROOT / "data-lake"))

from strategies.ppo_proxy_strategy import PPOHTTPStrategy, PPOHTTPConfig

# ─── Logging ─────────────────────────────────────────────────────
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PAPER] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "paper_trader.log", mode="a"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("paper_trader")

# ─── DB ──────────────────────────────────────────────────────────
DB_PATH = PROJECT_ROOT / "deployment" / "paper_trades.db"
engine_db = create_engine(f"sqlite:///{DB_PATH}")
Base = declarative_base()


class TradeLog(Base):
    """One row per executed fill during paper trading."""
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False)
    ticker = Column(String(16), nullable=False)
    side = Column(String(8), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    value = Column(Float, nullable=False)
    equity_before = Column(Float, nullable=False)
    equity_after = Column(Float, nullable=False)
    weight_target = Column(Float, nullable=True)
    inference_ms = Column(Float, nullable=True)
    strategy_name = Column(String(64), default="PPOHTTPProxy")


class DailySnapshot(Base):
    """Daily portfolio summary."""
    __tablename__ = "daily_snapshots"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(DateTime, nullable=False, unique=True)
    equity = Column(Float, nullable=False)
    cash = Column(Float, nullable=False)
    positions_value = Column(Float, nullable=False)
    n_positions = Column(Integer, default=0)
    peak_equity = Column(Float, nullable=True)
    drawdown_pct = Column(Float, nullable=True)


Base.metadata.create_all(engine_db)
Session = sessionmaker(bind=engine_db)

# ─── Prometheus Metrics ─────────────────────────────────────────
PROMETHEUS_PORT = 8766

prom_equity = Gauge("paper_equity", "Current paper portfolio equity", ["ticker"])
prom_cash = Gauge("paper_cash", "Current paper cash balance")
prom_positions = Gauge("paper_open_positions", "Number of open positions")
prom_fill_latency = Histogram("paper_fill_latency_ms", "Order fill latency", buckets=[1, 5, 10, 25, 50, 100])
prom_inference_latency = Histogram("paper_inference_latency_ms", "PPO inference latency", buckets=[1, 5, 10, 25, 50, 100, 200])
prom_errors = Counter("paper_errors_total", "Total errors", ["type"])

# ─── Config ─────────────────────────────────────────────────────
TICKER_NAME = "AAPL"
TICKER = f"{TICKER_NAME}.SIM"
GRANULARITY = "1d"
BAR_TYPE = BarType.from_str(f"{TICKER}-1-DAY-LAST-EXTERNAL")
PPO_URL = "http://127.0.0.1:8765/predict_weights"
INITIAL_CASH = 100_000
DATA_LAKE_DIR = PROJECT_ROOT / "data-lake"


def load_parquet_files(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Load Parquet files for ticker within date range."""
    base = DATA_LAKE_DIR / "ohlcv" / GRANULARITY / ticker
    if not base.exists():
        raise FileNotFoundError(f"Data lake missing: {base}")
    files = sorted(base.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No Parquet files in {base}")
    df = pd.concat(pd.read_parquet(f) for f in files).sort_index()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    mask = (df.index >= pd.Timestamp(start_date)) & (df.index <= pd.Timestamp(end_date))
    return df[mask]


def run_paper_day(trade_date: date, is_first: bool = False) -> dict:
    """
    Run one day of paper trading.
    - trade_date: the date to simulate (must exist in data lake)
    - is_first: if True, run from 2020-01-01 through trade_date
    Returns daily metrics dict.
    """
    start_str = "2020-01-01" if is_first else (trade_date - timedelta(days=60)).strftime("%Y-%m-%d")
    end_str = trade_date.strftime("%Y-%m-%d")

    # Load data up to this day
    df = load_parquet_files(TICKER_NAME, start_str, end_str)
    if df.empty:
        log.warning(f"No data for {trade_date}, skipping")
        return {}

    # Build bars
    bars = []
    for idx, row in df.iterrows():
        ns = int(pd.Timestamp(idx).value)
        bars.append(Bar.from_dict({
            "type": "Bar",
            "bar_type": str(BAR_TYPE),
            "open": f"{row['open']:.2f}",
            "high": f"{row['high']:.2f}",
            "low": f"{row['low']:.2f}",
            "close": f"{row['close']:.2f}",
            "volume": str(int(row.get("volume", 0))),
            "ts_event": ns,
            "ts_init": ns,
        }))

    # Run Nautilus backtest for this window
    engine = BacktestEngine()
    engine.add_venue(
        venue=Venue("SIM"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        starting_balances=[Money(INITIAL_CASH, USD_CCY)],
        base_currency=USD_CCY,
        allow_cash_borrowing=False,
    )
    from nautilus_trader.model.instruments.equity import Equity as EquityInstrument
    inst = EquityInstrument.from_dict({
        "type": "Equity", "id": TICKER, "raw_symbol": TICKER_NAME,
        "currency": "USD", "price_precision": 2, "size_precision": 0,
        "price_increment": "0.01", "size_increment": "1",
        "lot_size": "1", "ts_event": 0, "ts_init": 0, "info": None,
    })
    engine.add_instrument(inst)

    config = PPOHTTPConfig(
        instrument_id=TICKER, bar_type=str(BAR_TYPE), tickers=[TICKER_NAME],
        obs_dim=40, rebalance_bars=5,
        url=PPO_URL, latency_gate_ms=200.0, timeout_seconds=1.5,
    )
    strategy = PPOHTTPStrategy(config)
    engine.add_strategy(strategy)
    engine.add_data(bars)
    engine.run()

    # Collect results
    fills = engine.trader.generate_fills_report()
    report = engine.trader.generate_account_report(venue=Venue("SIM"))

    # Parse fills
    session = Session()
    try:
        if isinstance(fills, pd.DataFrame) and not fills.empty:
            for _, fill in fills.iterrows():
                # Only log fills for this trade date
                ts_val = fill.get("ts_event", 0)
                if isinstance(ts_val, pd.Timestamp):
                    fill_date = ts_val.date()
                else:
                    fill_date = trade_date

                if fill_date == trade_date:
                    side = str(fill.get("order_side", "BUY"))
                    if "BUY" in side: side = "BUY"
                    elif "SELL" in side: side = "SELL"
                    else: side = "UNKNOWN"

                    qty = int(fill.get("last_qty", 0))
                    price = float(fill.get("last_px", 0))
                    value = qty * price

                    trade = TradeLog(
                        timestamp=datetime.combine(trade_date, datetime.min.time()),
                        ticker=TICKER_NAME, side=side, quantity=qty,
                        price=price, value=value,
                        equity_before=0, equity_after=0,  # placeholder
                    )
                    session.add(trade)
                    log.info(f"📝 Trade: {side} {qty} {TICKER_NAME} @ ${price:.2f} = ${value:,.0f}")

        # Save daily snapshot
        if isinstance(report, pd.DataFrame) and not report.empty:
            for col in report.columns:
                report[col] = pd.to_numeric(report[col], errors="coerce")
            col = "equity" if "equity" in report.columns else report.columns[0]
            eq_series = report[col].astype(float)
            eq_series.index = pd.to_datetime(report.index, unit="ns")

            # Find equity closest to trade_date
            target_ts = pd.Timestamp(trade_date).tz_localize(None)
            # Ensure eq_series index is tz-naive for comparison
            if hasattr(eq_series.index, 'tz') and eq_series.index.tz is not None:
                eq_idx_naive = eq_series.index.tz_localize(None)
            else:
                eq_idx_naive = eq_series.index
            idx_closest = eq_idx_naive.searchsorted(target_ts)
            if idx_closest < len(eq_series):
                equity_val = float(eq_series.iloc[idx_closest])
            else:
                equity_val = float(eq_series.iloc[-1])

            # Check for existing snapshot (idempotent)
            existing = session.query(DailySnapshot).filter(
                DailySnapshot.trade_date == datetime.combine(trade_date, datetime.min.time())
            ).first()
            if not existing:
                snap = DailySnapshot(
                    trade_date=datetime.combine(trade_date, datetime.min.time()),
                    equity=round(equity_val, 2),
                    cash=round(equity_val, 2),  # simplified
                    positions_value=0,
                    n_positions=0,
                )
                session.add(snap)
                prom_equity.labels(ticker=TICKER_NAME).set(equity_val)
                log.info(f"📊 Daily snapshot: ${equity_val:,.2f} equity on {trade_date}")

        session.commit()
    except Exception as e:
        session.rollback()
        prom_errors.labels(type="db").inc()
        log.error(f"DB error: {e}")
    finally:
        session.close()

    return {"trade_date": str(trade_date), "status": "ok"}


def run_full_backtest() -> dict:
    """Single Nautilus backtest across full 2020-2024 period, write daily snapshots to DB."""
    df = load_parquet_files(TICKER_NAME, "2020-01-01", "2024-12-31")
    if df.empty:
        log.error("No data for full backtest")
        return {"status": "error", "error": "no data"}

    log.info(f"Full backtest: {len(df)} bars ({df.index[0].date()} -> {df.index[-1].date()})")

    # Build bars
    bars = []
    for idx, row in df.iterrows():
        ns = int(pd.Timestamp(idx).value)
        bars.append(Bar.from_dict({
            "type": "Bar",
            "bar_type": str(BAR_TYPE),
            "open": f"{row['open']:.2f}",
            "high": f"{row['high']:.2f}",
            "low": f"{row['low']:.2f}",
            "close": f"{row['close']:.2f}",
            "volume": str(int(row.get("volume", 0))),
            "ts_event": ns,
            "ts_init": ns,
        }))

    # Build engine
    engine = BacktestEngine()
    engine.add_venue(
        venue=Venue("SIM"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        starting_balances=[Money(INITIAL_CASH, USD_CCY)],
        base_currency=USD_CCY,
        allow_cash_borrowing=False,
    )
    from nautilus_trader.model.instruments.equity import Equity as EquityInstrument
    inst = EquityInstrument.from_dict({
        "type": "Equity", "id": TICKER, "raw_symbol": TICKER_NAME,
        "currency": "USD", "price_precision": 2, "size_precision": 0,
        "price_increment": "0.01", "size_increment": "1",
        "lot_size": "1", "ts_event": 0, "ts_init": 0, "info": None,
    })
    engine.add_instrument(inst)

    config = PPOHTTPConfig(
        instrument_id=TICKER, bar_type=str(BAR_TYPE), tickers=[TICKER_NAME],
        obs_dim=40, rebalance_bars=5,
        url=PPO_URL, latency_gate_ms=200.0, timeout_seconds=1.5,
    )
    strategy = PPOHTTPStrategy(config)
    engine.add_strategy(strategy)
    engine.add_data(bars)
    t0 = time.time()
    engine.run()
    elapsed = time.time() - t0
    log.info(f"Backtest completed in {elapsed:.1f}s")

    # Extract equity curve from fills + closes (same reconstruction as Phase 2)
    fills_df = engine.trader.generate_fills_report()
    closes = df["close"].astype(float)

    n_trades = 0
    session = Session()
    try:
        # Parse fills and write to trade_log
        if isinstance(fills_df, pd.DataFrame) and not fills_df.empty:
            for _, fill in fills_df.iterrows():
                ts_val = fill.get("ts_event", 0)
                try:
                    fill_ts = pd.Timestamp(ts_val) if pd.notna(ts_val) else None
                except Exception:
                    fill_ts = None

                side = str(fill.get("order_side", "BUY"))
                if "BUY" in side: side = "BUY"
                elif "SELL" in side: side = "SELL"
                else: side = "UNKNOWN"

                qty = int(float(fill.get("last_qty", 0) or 0))
                px = float(fill.get("last_px", 0) or 0)
                value = qty * px
                fill_date = fill_ts.date() if fill_ts else trade_date

                trade = TradeLog(
                    timestamp=datetime.combine(fill_date, datetime.min.time()),
                    ticker=TICKER_NAME,
                    side=side,
                    quantity=qty,
                    price=px,
                    value=value,
                    equity_before=0,
                    equity_after=0,
                )
                session.add(trade)
                n_trades += 1
                if n_trades <= 5:
                    log.info(f"📝 Trade: {side} {qty} {TICKER_NAME} @ ${px:.2f} = ${value:,.0f}")

        # Write daily snapshots to DB
        from backtests.phase2_backtest import _walk_fills_to_equity
        daily_eq = _walk_fills_to_equity(
            fills_df if isinstance(fills_df, pd.DataFrame) else pd.DataFrame(),
            closes,
        )

        for ts, eq_val in daily_eq.items():
            d = ts.date() if hasattr(ts, "date") else ts
            existing = session.query(DailySnapshot).filter(
                DailySnapshot.trade_date == datetime.combine(d, datetime.min.time())
            ).first()
            if not existing:
                snap = DailySnapshot(
                    trade_date=datetime.combine(d, datetime.min.time()),
                    equity=round(float(eq_val), 2),
                    cash=0,
                    positions_value=0,
                    n_positions=0,
                )
                session.add(snap)
        session.commit()
        log.info(f"✅ Wrote {len(daily_eq)} daily snapshots + {n_trades} trades to DB")
    except Exception as e:
        session.rollback()
        log.error(f"DB write error: {e}")
    finally:
        session.close()

    # Metrics
    returns = daily_eq.pct_change().dropna()
    sharpe = float((returns.mean() / returns.std()) * np.sqrt(252)) if returns.std() > 0 else 0
    peak = daily_eq.expanding().max()
    dd = ((daily_eq - peak) / peak).min()

    metrics = {
        "trading_days": len(daily_eq),
        "total_trades": n_trades,
        "start_equity": round(float(daily_eq.iloc[0]), 2),
        "end_equity": round(float(daily_eq.iloc[-1]), 2),
        "total_return_pct": round(float((daily_eq.iloc[-1] / daily_eq.iloc[0] - 1) * 100), 2),
        "sharpe_ratio": round(float(sharpe), 4),
        "max_drawdown_pct": round(float(dd * 100), 2),
        "backtest_seconds": round(elapsed, 2),
    }
    return metrics


def compute_metrics() -> dict:
    """Compute paper trading metrics from the trade log and daily snapshots."""
    session = Session()
    try:
        snapshots = session.query(DailySnapshot).order_by(DailySnapshot.trade_date).all()
        if len(snapshots) < 2:
            return {"status": "insufficient_data", "trading_days": len(snapshots)}

        eq_vals = [s.equity for s in snapshots]
        eq_series = pd.Series(eq_vals)
        returns = eq_series.pct_change().dropna()

        if len(returns) < 2:
            return {"trading_days": len(eq_vals)}

        sharpe = float((returns.mean() / returns.std()) * np.sqrt(252)) if returns.std() > 0 else 0.0
        peak = eq_series.expanding().max()
        dd = ((eq_series - peak) / peak).min()

        trades = session.query(TradeLog).count()
        total_return = ((eq_vals[-1] / eq_vals[0]) - 1) * 100

        metrics = {
            "trading_days": len(eq_vals),
            "total_trades": trades,
            "start_equity": round(eq_vals[0], 2),
            "end_equity": round(eq_vals[-1], 2),
            "total_return_pct": round(total_return, 2),
            "sharpe_ratio": round(sharpe, 4),
            "max_drawdown_pct": round(float(dd * 100), 2),
            "win_rate": 0,  # placeholder: need fill-level P&L
        }
        return metrics
    finally:
        session.close()


def run_prometheus_server():
    """Start /metrics endpoint for Prometheus scraping."""
    start_http_server(PROMETHEUS_PORT)
    log.info(f"📊 Prometheus metrics at http://127.0.0.1:{PROMETHEUS_PORT}/metrics")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 4 Paper Trading Runner")
    parser.add_argument("--date", type=str, help="Run a single date (YYYY-MM-DD)")
    parser.add_argument("--catchup", action="store_true", help="Run all available data from yesterday")
    parser.add_argument("--full-backtest", action="store_true", help="Run single full backtest 2020-2024 (fast)")
    parser.add_argument("--metrics", action="store_true", help="Compute and print metrics from DB")
    parser.add_argument("--prometheus", action="store_true", help="Start Prometheus metrics server")
    args = parser.parse_args()

    if args.prometheus:
        run_prometheus_server()
        print(f"Prometheus /metrics at :{PROMETHEUS_PORT}")
        sys.exit(0)

    if args.metrics:
        m = compute_metrics()
        print(json.dumps(m, indent=2))
        sys.exit(0)

    if args.date:
        run_paper_day(date.fromisoformat(args.date), is_first=True)
        print(f"Day {args.date} completed.")
    elif args.full_backtest:
        m = run_full_backtest()
        print(json.dumps(m, indent=2))
        print("\n✅ Full backtest complete. Run --metrics after DB write.")
    elif args.catchup:
        # Run all available data: 2020-01-01 through yesterday
        # Determine latest trade we've already processed
        session = Session()
        latest = session.query(DailySnapshot).order_by(DailySnapshot.trade_date.desc()).first()
        session.close()

        start_date = (latest.trade_date + timedelta(days=1)).date() if latest else date(2020, 1, 2)
        end_date = date.today() - timedelta(days=1)

        log.info(f"🏁 Catchup mode: {start_date} through {end_date}")
        day = start_date
        while day <= end_date:
            is_first = (day == start_date and not latest)
            run_paper_day(day, is_first=is_first)
            day += timedelta(days=1)

        m = compute_metrics()
        print("\n" + "=" * 60)
        print("PAPER TRADING CATCHUP RESULTS")
        print("=" * 60)
        for k, v in m.items():
            print(f"  {k}: {v}")
        print("=" * 60)
    else:
        parser.print_help()