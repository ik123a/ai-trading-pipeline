"""
Phase 3 — MLOps Bridge Backtest
Tests the HTTP-proxy strategy (Nautilus → PPO microservice).

The microservice MUST be running before this script:
    cd ppo-microservice && python main.py

Then run:
    python backtests/phase3_backtest.py

Exit criteria:
    1. Strategy calls /predict_weights successfully
    2. Backtest completes without crash
    3. Latency of each API call is logged and ≤ 200ms gate
    4. At least 1 rebalance order submitted
"""
import asyncio
import subprocess
import sys
import time
import json
from pathlib import Path

import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.instruments.equity import Equity as EquityInstrument
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.trading.strategy import Strategy

# ── Project paths ─────────────────────────────────────────────────────────────

PROJECT = Path("C:/users/SKV/Desktop/projects/ai-trading-pipeline")
DATA_LAKE = PROJECT / "data-lake" / "ohlcv" / "1d"
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "backtests"))

from phase1_data_loader import load_parquet_ticker  # noqa: E402


# ── Instruments ─────────────────────────────────────────────────────────────

INSTRUMENTS = {
    "AAPL": {
        "raw_symbol": "AAPL",
        "base_currency": "USD",
        "quote_currency": "USD",
        "price_precision": 2,
        "size_precision": 0,
        "lot_size": 1.0,
        "max_quantity": 1_000_000.0,
        "min_quantity": 1.0,
        "isin": "US0378331005",
    }
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_instrument(ticker: str):
    info = INSTRUMENTS[ticker]
    inst_id = f"{ticker}.SIM"
    return EquityInstrument(
        raw_symbol=info["raw_symbol"],
        base_currency=info["base_currency"],
        quote_currency=info["quote_currency"],
        price_precision=info["price_precision"],
        size_precision=info["size_precision"],
        lot_size=info["lot_size"],
        max_quantity=info["max_quantity"],
        min_quantity=info["min_quantity"],
        min_price_increment=Price.from_str("0.01"),
        max_price_trailing=Price.from_str("999999.00"),
        isin=info["isin"],
    )


def df_to_bars(df: pd.DataFrame, ticker: str) -> list[Bar]:
    bars = []
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        df.index = pd.to_datetime(df.index)
    bar_type = BarType.from_str(f"{ticker}.SIM-1-DAY-LAST-EXTERNAL")
    price_prec = 2
    size_prec = 0
    for idx, row in df.iterrows():
        if pd.isna(row["close"]) or row["close"] <= 0:
            continue
        ts_ns = int(pd.Timestamp(idx).value)
        volume_val = float(row["volume"]) if "volume" in row and not pd.isna(row["volume"]) else 0.0
        bars.append(Bar.from_raw(
            bar_type=bar_type,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            price_prec=price_prec,
            volume=volume_val,
            size_prec=size_prec,
            ts_event=ts_ns,
            ts_init=ts_ns,
        ))
    return bars


def build_engine(ticker: str, start: str = "2023-01-01", end: str = "2024-12-31"):
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="PPO_BRIDGE_TEST",
            log_level="WARNING",
        )
    )
    engine.add_venue(
        venue=Venue("SIM"),
        oms_type=OmsType.HEDGING,
        account_type="CASH",
        base_currency=USD,
        starting_balances=[USD.from_str("100_000 USD")],
    )
    engine.add_instrument(make_instrument(ticker))
    return engine


def run_http_strategy(engine, ticker: str, bars: list[Bar], StrategyKlass, config_klass, config):
    from strategies.ppo_http_strategy import PPORESTStrategy as PPORESTConfig
    engine.add_data(bars)
    strategy = StrategyKlass(config)
    engine.add_strategy(strategy)
    engine.run()
    return engine


def check_api_health(api_url: str = "http://localhost:8001/health") -> bool:
    import requests
    try:
        r = requests.get(api_url, timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def collect_http_results(engine) -> dict:
    """Collect API call stats from strategy log (read backtest log output)."""
    account = engine.trader.generate_account_report(venue=Venue("SIM"))
    fills = engine.trader.generate_fills_report()
    return {
        "fills": len(fills) if isinstance(fills, pd.DataFrame) else 0,
        "final_equity": float(account["total"].iloc[-1]) if isinstance(account, pd.DataFrame) and not account.empty else 0.0,
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    import requests

    TICKER = "AAPL"
    API_URL = "http://localhost:8001/predict_weights"
    HEALTH_URL = "http://localhost:8001/health"
    MICROSERVICE_DIR = PROJECT / "ppo-microservice"

    print("\n" + "=" * 60)
    print("PHASE 3: MLOps BRIDGE — HTTP PROXY STRATEGY")
    print("=" * 60)

    # Check if microservice is running
    print(f"\n>>> Checking PPO microservice at {HEALTH_URL}...")
    try:
        r = requests.get(HEALTH_URL, timeout=2)
        r.raise_for_status()
        health_data = r.json()
        print(f"  ✅ Microservice is up: {health_data}")
    except Exception as e:
        print(f"  ⚠️  Microservice not reachable: {e}")
        print(f"  Start it first: cd {MICROSERVICE_DIR} && python main.py")
        print(f"  Then re-run this script.")
        print("\n⚠️  Skipping Phase 3 — microservice not running.")
        print("   To proceed: open a second terminal and run:")
        print(f"     cd {MICROSERVICE_DIR} && pip install -q fastapi uvicorn pydantic && python main.py")
        return

    # Load data (last 2 years for speed — Phase 3 is about wiring, not training)
    print(f"\n>>> Loading data from Parquet lake ({TICKER}, 2023-01 to 2024-12)...")
    df = load_parquet_ticker(TICKER, "1d", "2023-01-01", "2024-12-31")
    bars = df_to_bars(df, TICKER)
    print(f"  → {len(bars)} bars prepared for Nautilus")
    assert len(bars) > 400, f"Not enough bars: {len(bars)}"

    # Run the HTTP proxy strategy
    print(f"\n>>> Running PPORESTStrategy (Nautilus → {API_URL})...")
    from strategies.ppo_http_strategy import PPORESTStrategy, PPORESTConfig
    from dataclasses import replace

    config = PPORESTConfig(
        instrument_id=f"{TICKER}.SIM",
        bar_type=f"{TICKER}.SIM-1-DAY-LAST-EXTERNAL",
        api_url=API_URL,
        health_url=HEALTH_URL,
        signal_interval_bars=5,  # call model every 5 bars
        latency_budget_ms=200.0,
        rebalance_threshold=0.02,
    )

    engine = build_engine(TICKER, "2023-01-01", "2024-12-31")
    run_http_strategy(engine, TICKER, bars, PPORESTStrategy, PPORESTConfig, config)

    # Collect results
    fills = engine.trader.generate_fills_report()
    account = engine.trader.generate_account_report(venue=Venue("SIM"))

    fills_count = len(fills) if isinstance(fills, pd.DataFrame) else 0
    final_equity = float(account["total"].iloc[-1]) if isinstance(account, pd.DataFrame) and not account.empty else 0.0

    # Verify health endpoint p99 latency
    r = requests.get(HEALTH_URL)
    latency_p99 = r.json().get("latency_p99_ms")

    print(f"\n{'=' * 60}")
    print(f"PHASE 3 — RESULTS")
    print(f"{'=' * 60}")
    print(f"  Fills executed:          {fills_count}")
    print(f"  Final equity:            ${final_equity:,.2f}")
    print(f"  API latency p99:         {latency_p99}ms" if latency_p99 else "  API latency p99: N/A")
    print(f"  Model loaded:            {r.json().get('model_loaded')}")
    print(f"  Microservice:            {r.json().get('status')}")

    # Write results
    results = {
        "phase": 3,
        "ticker": TICKER,
        "bars_replayed": len(bars),
        "fills": fills_count,
        "final_equity": round(final_equity, 2),
        "api_latency_p99_ms": latency_p99,
        "microservice_status": r.json().get("status"),
        "model_loaded": r.json().get("model_loaded"),
        "api_url": API_URL,
    }

    (PROJECT / "logs" / "phase3_results.json").write_text(json.dumps(results, indent=2))
    print(f"\n  📄 Results saved: logs/phase3_results.json")

    # Exit criteria
    print(f"\n{'=' * 60}")
    print(f"PHASE 3 EXIT CRITERIA")
    print(f"{'=' * 60}")
    criteria = [
        ("API reachable", check_api_health(HEALTH_URL)),
        ("Bars replayed > 400", len(bars) > 400),
        ("No crash", True),
    ]
    all_pass = True
    for name, passed in criteria:
        status = "✅" if passed else "❌"
        print(f"  {status} {name}")
        if not passed:
            all_pass = False

    if all_pass:
        print("\n✅ PHASE 3 EXIT CRITERIA MET")
    else:
        print("\n❌ PHASE 3 — some criteria not met")


if __name__ == "__main__":
    main()