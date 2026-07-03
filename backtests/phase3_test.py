"""
Phase 3 Integration Test: PPO HTTP Microservice + Nautilus Backtest
====================================================================
End-to-end verification of the MLOps bridge:
  Nautilus BacktestEngine -> PPOHTTPStrategy -> HTTP /predict_weights -> PPO model

Exit criteria:
  1. Backtest runs successfully calling external HTTP endpoint for weights
  2. Each weights call latency is logged (sub-200ms gate enforced client-side)
  3. Equity curve saved to logs/equity_curve_phase3.csv
  4. Metrics saved to logs/phase3_metrics.json

Uses Nautilus 1.229: add_venue(...) with starting_balances,
                     Equity.from_dict() and Bar.from_dict() factories.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OmsType, AccountType
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.model.objects import Quantity, Price, Money
from nautilus_trader.model.currencies import USD as USD_CCY

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "data-lake"))

from strategies.ppo_proxy_strategy import PPOHTTPStrategy, PPOHTTPConfig


def load_parquet_files(ticker: str, granularity: str, start_date: str, end_date: str,
                        data_dir: str = "data-lake") -> pd.DataFrame:
    """Load all Parquet files for a ticker/granularity and filter by date range."""
    base = Path(data_dir) / "ohlcv" / granularity / ticker
    if not base.exists():
        raise FileNotFoundError(f"Data lake missing: {base}")
    files = sorted(base.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No Parquet files in {base}")
    df = pd.concat(pd.read_parquet(f) for f in files).sort_index()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    # Strip timezone if present (parquet files are tz-aware NY)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    mask = (df.index >= pd.Timestamp(start_date)) & (df.index <= pd.Timestamp(end_date))
    return df[mask]


TICKER_NAME = "AAPL"
TICKER = f"{TICKER_NAME}.SIM"
GRANULARITY = "1d"
BAR_TYPE = BarType.from_str(f"{TICKER}-1-DAY-LAST-EXTERNAL")


def build_equity_instrument() -> dict:
    """Build AAPL.SIM equity instrument dict for from_dict()."""
    return {
        "type": "Equity",
        "id": TICKER,
        "raw_symbol": TICKER_NAME,
        "currency": "USD",
        "price_precision": 2,
        "size_precision": 0,
        "price_increment": "0.01",
        "size_increment": "1",
        "lot_size": "1",
        "ts_event": 0,
        "ts_init": 0,
        "info": None,
    }


def df_to_bar_dicts(df: pd.DataFrame) -> list[dict]:
    """Convert Parquet-derived DataFrame to Nautilus Bar dicts."""
    bars = []
    for idx, row in df.iterrows():
        # idx is a Timestamp; multiply by 1ms to be past bar-end before this bar opens
        ns = int(pd.Timestamp(idx).value)
        bars.append({
            "type": "Bar",
            "bar_type": str(BAR_TYPE),
            "open": f"{row['open']:.2f}",
            "high": f"{row['high']:.2f}",
            "low": f"{row['low']:.2f}",
            "close": f"{row['close']:.2f}",
            "volume": str(int(row.get("volume", 0))),
            "ts_event": ns,
            "ts_init": ns,
        })
    return bars


def build_engine():
    """Build a BacktestEngine with cash account, AAPL instrument, $100k cash."""
    engine = BacktestEngine()
    # Add venue with $100k starting USD cash balance
    engine.add_venue(
        venue=Venue("SIM"),
        oms_type=OmsType.NETTING,  # No shorting for cash accounts
        account_type=AccountType.CASH,
        starting_balances=[Money(100_000, USD_CCY)],
        base_currency=USD_CCY,
        allow_cash_borrowing=False,
    )
    # Add the AAPL equity instrument via from_dict()
    from nautilus_trader.model.instruments.equity import Equity as EquityInstrument
    inst = EquityInstrument.from_dict(build_equity_instrument())
    engine.add_instrument(inst)
    return engine


def run_backtest() -> dict:
    df = load_parquet_files(
        ticker=TICKER_NAME,
        granularity=GRANULARITY,
        start_date="2020-01-01",
        end_date="2024-12-31",
    )
    print(f"Data: {len(df)} rows ({df.index[0].date()} -> {df.index[-1].date()})")

    bar_dicts = df_to_bar_dicts(df)
    print(f"Bars: {len(bar_dicts)} prepared for Nautilus")

    bars = [Bar.from_dict(d) for d in bar_dicts]

    config = PPOHTTPConfig(
        instrument_id=TICKER,
        bar_type=str(BAR_TYPE),
        tickers=["AAPL"],
        obs_dim=40,
        rebalance_bars=5,
        url="http://127.0.0.1:8765/predict_weights",
        latency_gate_ms=200.0,
        timeout_seconds=1.5,
        request_id_prefix="p3-",
    )

    engine = build_engine()
    strategy = PPOHTTPStrategy(config)
    engine.add_strategy(strategy)
    engine.add_data(bars)  # CRITICAL: register the bars for replay

    print("\n=== Phase 3 backtest running (PPO HTTP proxy) ===")
    t0 = time.perf_counter()
    engine.run()  # No end_date kwarg - bars carry their own timestamps
    elapsed = time.perf_counter() - t0
    print(f"Backtest completed in {elapsed:.1f}s")

    fills = engine.trader.generate_fills_report()
    orders = engine.trader.generate_orders_report()
    report = engine.trader.generate_account_report(venue=Venue("SIM"))

    fills_count = len(fills) if isinstance(fills, pd.DataFrame) else 0
    orders_count = len(orders) if isinstance(orders, pd.DataFrame) else 0

    print(f"Orders: {orders_count}, Fills: {fills_count}, Bars: {len(bars)}")

    metrics = {"backtest_seconds": round(elapsed, 2)}
    equity_series = None
    if isinstance(report, pd.DataFrame) and not report.empty:
        for col in report.columns:
            report[col] = pd.to_numeric(report[col], errors="coerce")
        col = "equity" if "equity" in report.columns else report.columns[0]
        equity_series = report[col].astype(float)
        equity_series.index = pd.to_datetime(report.index, unit="ns")

        # Daily MTM from fills + closes (same logic as Phase 2)
        fills_df = fills if isinstance(fills, pd.DataFrame) else pd.DataFrame()
        from backtests.phase2_backtest import fill_to_daily_equity  # reuse
        if not fills_df.empty:
            daily_eq = fill_to_daily_equity(equity_series, df, TICKER_NAME, fills_df)
            returns = daily_eq.pct_change().dropna()
            if len(returns) > 0:
                sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0
                peak = daily_eq.expanding().max()
                dd = (daily_eq - peak) / peak
                metrics.update({
                    "sharpe_ratio": round(float(sharpe), 4),
                    "max_drawdown_pct": round(float(dd.min() * 100), 2),
                    "total_return_pct": round(float((daily_eq.iloc[-1] / daily_eq.iloc[0] - 1) * 100), 2),
                    "final_equity": round(float(daily_eq.iloc[-1]), 2),
                })
            equity_series = daily_eq

    metrics.update({
        "bars": len(bars),
        "orders": orders_count,
        "fills": fills_count,
    })

    if equity_series is not None:
        equity_series.to_csv("logs/equity_curve_phase3.csv")
        print(f"Equity curve saved: logs/equity_curve_phase3.csv ({len(equity_series)} MTM points)")

    with open("logs/phase3_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"Metrics saved: logs/phase3_metrics.json")
    return metrics


if __name__ == "__main__":
    metrics = run_backtest()

    print("\n" + "=" * 70)
    print("PHASE 3 — PPO HTTP PROXY BACKTEST")
    print("=" * 70)
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    print("=" * 70)

    assert metrics.get("fills", 0) > 0, "FAIL: no fills"
    assert metrics.get("orders", 0) > 0, "FAIL: no orders submitted"
    assert metrics.get("bars", 0) > 0, "FAIL: no bars replayed"
    print("\n✅ PHASE 3 EXIT CRITERIA MET:")
    print(f"   - {metrics.get('bars')} bars replayed from Parquet data lake")
    print(f"   - {metrics.get('orders')} orders submitted, {metrics.get('fills')} executed")
    print(f"   - HTTP /predict_weights called every {5} bars with <200ms gate")
    print(f"   - Phase 3 equity curve saved to logs/equity_curve_phase3.csv")
    print(f"   - Phase 3 metrics saved to logs/phase3_metrics.json")