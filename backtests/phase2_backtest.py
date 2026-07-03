"""
Phase 2 Exit Criteria: 5-Year Baseline Backtest
Runs BOTH:
  1. Buy & Hold (true baseline — what an investor gets just holding AAPL)
  2. SMA 50/200 crossover (active strategy) using close_all_positions() for exits

Outputs:
  - logs/equity_curve_bnh.csv
  - logs/equity_curve_sma.csv
  - logs/baseline_metrics_comparison.json
"""
import asyncio
import json
import sys
import pandas as pd
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, OmsType, AccountType
from nautilus_trader.model.identifiers import InstrumentId, Venue, Symbol
from nautilus_trader.indicators import SimpleMovingAverage
from nautilus_trader.model.objects import Price, Quantity, Money
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.instruments.equity import Equity as EquityInstrument
from nautilus_trader.model.currencies import USD as USD_CCY


# ──────────────────────────────────────────
# STRATEGIES
# ──────────────────────────────────────────
class BNHConfig(StrategyConfig, frozen=True):
    instrument_id: str = "AAPL.SIM"
    bar_type: str = "AAPL.SIM-1-DAY-LAST-EXTERNAL"
    target_dollars: float = 95_000.0  # spend ~95% of capital on first bar


class BuyAndHold(Strategy):
    def __init__(self, config: BNHConfig):
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)
        self.target_dollars = config.target_dollars
        self.bought = False

    def on_start(self):
        self.subscribe_bars(self.bar_type)

    def on_bar(self, bar: Bar):
        if self.bought:
            return
        # Buy $95,000 worth of stock on first bar
        price = bar.close.as_double()
        qty = int(self.target_dollars // price)
        if qty > 0:
            self.submit_order(self.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=OrderSide.BUY,
                quantity=Quantity.from_int(qty),
            ))
            self.bought = True
            self.log.info(f"BUY & HOLD: {qty} shares @ {price:.2f} = ${qty*price:,.2f}")


class SMACrossConfig(StrategyConfig, frozen=True):
    instrument_id: str = "AAPL.SIM"
    bar_type: str = "AAPL.SIM-1-DAY-LAST-EXTERNAL"
    short_window: int = 50
    long_window: int = 200
    trade_size: int = 100


class SMACrossFixed(Strategy):
    """
    SMA crossover with proper exits using close_all_positions().
    Uses flat-to-long only logic (no SHORTING) — appropriate for cash account.
    """
    def __init__(self, config: SMACrossConfig):
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)
        self.trade_size = config.trade_size
        self.sma_short = SimpleMovingAverage(config.short_window)
        self.sma_long = SimpleMovingAverage(config.long_window)
        self.in_market = False
        self.signal_count = 0

    def on_start(self):
        self.subscribe_bars(self.bar_type)
        self.log.info(f"SMA Cross started: {self.sma_short.period}/{self.sma_long.period}")

    def on_bar(self, bar: Bar):
        self.sma_short.update_raw(bar.close.as_double())
        self.sma_long.update_raw(bar.close.as_double())
        if not self.sma_short.initialized or not self.sma_long.initialized:
            return
        s = self.sma_short.value
        l = self.sma_long.value
        if s > l and not self.in_market:
            self.signal_count += 1
            self.submit_order(self.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=OrderSide.BUY,
                quantity=Quantity.from_int(self.trade_size),
            ))
            self.in_market = True
            self.log.info(f"BUY #{self.signal_count} @ {bar.close.as_double():.2f}")
        elif s < l and self.in_market:
            self.signal_count += 1
            # Use close_all_positions for clean exit (handles order book + qty)
            self.close_all_positions(self.instrument_id)
            self.in_market = False
            self.log.info(f"EXIT #{self.signal_count} @ {bar.close.as_double():.2f}")


# ──────────────────────────────────────────
# DATA + ENGINE
# ──────────────────────────────────────────
def load_ticker(ticker: str) -> pd.DataFrame:
    base = Path("data-lake/ohlcv/1d") / ticker
    files = sorted(base.glob("*.parquet"))
    df = pd.concat(pd.read_parquet(f) for f in files).sort_index()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    return df


def df_to_bars(df: pd.DataFrame, ticker: str) -> list[Bar]:
    bars = []
    bar_type = BarType.from_str(f"{ticker}.SIM-1-DAY-LAST-EXTERNAL")
    for idx, row in df.iterrows():
        ts_ns = int(idx.value)
        bars.append(Bar(
            bar_type=bar_type,
            open=Price.from_str(f"{row['open']:.2f}"),
            high=Price.from_str(f"{row['high']:.2f}"),
            low=Price.from_str(f"{row['low']:.2f}"),
            close=Price.from_str(f"{row['close']:.2f}"),
            volume=Quantity.from_str(f"{row['volume']:.0f}"),
            ts_event=ts_ns + 1_000_000,
            ts_init=ts_ns,
        ))
    return bars


def build_engine(ticker: str):
    engine = BacktestEngine()
    engine.add_venue(
        venue=Venue("SIM"),
        oms_type=OmsType.HEDGING,
        account_type=AccountType.CASH,
        starting_balances=[Money(100_000.0, USD_CCY)],
    )
    inst_id = InstrumentId.from_str(f"{ticker}.SIM")
    inst = EquityInstrument(
        instrument_id=inst_id,
        raw_symbol=Symbol(ticker),
        currency=USD_CCY,
        price_precision=2,
        price_increment=Price.from_str("0.01"),
        lot_size=Quantity.from_int(1),
        ts_event=0,
        ts_init=0,
    )
    engine.add_instrument(inst)
    return engine


def run_strategy(engine: BacktestEngine, ticker: str, bars: list[Bar], strategy_cls, config):
    engine.add_data(bars)
    strat = strategy_cls(config)
    engine.add_strategy(strat)
    engine.run()
    return strat


def collect_results(engine: BacktestEngine, ticker: str, df: pd.DataFrame):
    fills_df = engine.trader.generate_fills_report()
    account = engine.trader.generate_account_report(venue=Venue("SIM"))
    raw_equity = None
    if isinstance(account, pd.DataFrame) and not account.empty:
        for col in account.columns:
            account[col] = pd.to_numeric(account[col], errors="coerce")
        col = "equity" if "equity" in account.columns else account.columns[0]
        raw_equity = account[col].astype(float)
        raw_equity.index = pd.to_datetime(account.index, unit="ns")

    # Always build daily MTM from fills + closes
    equity = fill_to_daily_equity(raw_equity, df, ticker, fills_df if isinstance(fills_df, pd.DataFrame) else pd.DataFrame())

    return equity, equity_to_metrics(equity), {
        "fills": len(fills_df) if isinstance(fills_df, pd.DataFrame) else 0,
        "mtm_points": len(equity),
        "raw_fill_points": len(raw_equity) if raw_equity is not None else 0,
    }


def fill_to_daily_equity(equity: pd.Series, df: pd.DataFrame, ticker: str, fills: pd.DataFrame) -> pd.Series:
    """
    Reconstruct a proper daily mark-to-market equity curve from the fills report
    + daily close prices from the Parquet data lake.

    equity[t] = cash_balance[t] + shares_held[t] * close[t]
    """
    import numpy as np
    if df.empty:
        return pd.Series(dtype=float)

    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        df.index = pd.to_datetime(df.index)

    closes = df["close"].astype(float)
    return _walk_fills_to_equity(fills, closes)


def _walk_fills_to_equity(fills: pd.DataFrame, closes: pd.Series) -> pd.Series:
    """Walk fills chronologically, track cash + shares, MTM daily."""
    initial_cash = 100_000.0
    cash = initial_cash
    shares = 0
    last_fill_idx = 0
    last_fill_ts_ns = -1

    # Try to extract side/price/qty from fills; fallback to first available columns
    fill_records = []
    if isinstance(fills, pd.DataFrame) and not fills.empty:
        for _, row in fills.iterrows():
            rec = {}
            for col in row.index:
                rec[col] = row[col]
            fill_records.append(rec)

    # Build event timeline: for each fill, derive (ts_ns, side, qty, px)
    events = []

    def _to_ns(v):
        """Convert any timestamp-like to int nanoseconds."""
        if v is None or v == 0 or v == "":
            return 0
        # Try numeric first
        try:
            x = float(v)
            if x < 10**15:  # seconds, convert to ns
                return int(x * 1_000_000_000)
            return int(x)  # already nanoseconds
        except (TypeError, ValueError):
            pass
        # Try pandas Timestamp
        try:
            return int(pd.Timestamp(v).value)
        except Exception:
            return 0

    for rec in fill_records:
        ts_candidates = [
            rec.get("ts_event"),
            rec.get("ts_last"),
            rec.get("ts_init"),
            rec.get("ts_opened"),
        ]
        ts = 0
        for cand in ts_candidates:
            ns = _to_ns(cand)
            if ns > 0:
                ts = ns
                break
        side_raw = rec.get("order_side", rec.get("side", "BUY"))
        side = str(side_raw).upper() if side_raw is not None else "BUY"
        # Handle enum-style side like "OrderSide.BUY"
        if "BUY" in side:
            side = "BUY"
        elif "SELL" in side:
            side = "SELL"
        try:
            qty = float(rec.get("last_qty", rec.get("quantity", rec.get("qty", 0))) or 0)
        except (TypeError, ValueError):
            qty = 0.0
        try:
            px = float(rec.get("last_px", rec.get("price", rec.get("avg_px_open", 0))) or 0)
        except (TypeError, ValueError):
            px = 0.0
        if qty > 0 and px > 0:
            events.append((ts, side, qty, px))

    events.sort(key=lambda e: e[0])

    # Walk through closes, applying events as they happen
    equity_series = pd.Series(index=closes.index, dtype=float)
    ev_idx = 0
    for ts, c in zip(closes.index, closes.values):
        # Apply any fills that happened AT or BEFORE this bar
        while ev_idx < len(events) and events[ev_idx][0] <= int(ts.value):
            _, side, qty, px = events[ev_idx]
            if side == "BUY":
                cash -= qty * px
                shares += qty
            elif side == "SELL":
                cash += qty * px
                shares -= qty
            ev_idx += 1
        equity_series.loc[ts] = cash + shares * float(c)
    return equity_series


def equity_to_metrics(equity: pd.Series) -> dict:
    equity = equity.dropna()
    if len(equity) < 2:
        return {"sharpe_ratio": 0, "max_drawdown_pct": 0, "total_return_pct": 0, "final_equity": 0}
    returns = equity.pct_change().dropna()
    sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0.0
    peak = equity.expanding().max()
    dd = (equity - peak) / peak
    total_ret = float((equity.iloc[-1] / equity.iloc[0] - 1) * 100)
    wins = int((returns > 0).sum())
    losses = int((returns < 0).sum())
    win_loss = round(wins / losses, 3) if losses > 0 else float("inf") if wins else 0
    return {
        "sharpe_ratio": round(float(sharpe), 4),
        "max_drawdown_pct": round(float(dd.min() * 100), 2),
        "total_return_pct": round(total_ret, 2),
        "final_equity": round(float(equity.iloc[-1]), 2),
        "start": str(equity.index[0]),
        "end": str(equity.index[-1]),
        "win_rate_proxy": round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0,
        "win_loss_ratio": win_loss,
        "trading_days": len(equity),
    }


# ──────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────
async def main():
    print("=" * 70)
    print(" PHASE 2: 5-YEAR BASELINE BACKTEST (AAPL, 2020-2024)")
    print("=" * 70)

    ticker = "AAPL"
    df = load_ticker(ticker)
    print(f"Data: {len(df)} rows ({df.index[0].date()} -> {df.index[-1].date()})")
    bars = df_to_bars(df, ticker)
    print(f"Bars: {len(bars)} prepared for Nautilus\n")

    # ── Strategy 1: Buy & Hold ──
    print(">>> Running Buy & Hold strategy...")
    engine1 = build_engine(ticker)
    run_strategy(engine1, ticker, bars, BuyAndHold, BNHConfig())
    equity_bnh, metrics_bnh, info_bnh = collect_results(engine1, ticker, df)
    if equity_bnh is not None:
        equity_bnh.to_csv("logs/equity_curve_bnh.csv")
        print(f"  → Fills: {info_bnh['fills']}, MTM points: {info_bnh['mtm_points']}, Final equity: ${metrics_bnh['final_equity']}")
        print(f"  → Sharpe: {metrics_bnh['sharpe_ratio']}, Max DD: {metrics_bnh['max_drawdown_pct']}%\n")

    # ── Strategy 2: SMA 50/200 (fixed exits) ──
    print(">>> Running SMA 50/200 crossover strategy...")
    engine2 = build_engine(ticker)
    run_strategy(engine2, ticker, bars, SMACrossFixed, SMACrossConfig())
    equity_sma, metrics_sma, info_sma = collect_results(engine2, ticker, df)
    if equity_sma is not None:
        equity_sma.to_csv("logs/equity_curve_sma.csv")
        print(f"  → Fills: {info_sma['fills']}, MTM points: {info_sma['mtm_points']}, Final equity: ${metrics_sma['final_equity']}")
        print(f"  → Sharpe: {metrics_sma['sharpe_ratio']}, Max DD: {metrics_sma['max_drawdown_pct']}%\n")

    # Side-by-side comparison
    Path("logs").mkdir(exist_ok=True)
    comparison = {
        "ticker": ticker,
        "backtest_period": f"{df.index[0].date()} to {df.index[-1].date()}",
        "bars_replayed": len(bars),
        "buy_and_hold": metrics_bnh,
        "sma_50_200": metrics_sma,
        "delta_vs_bnh_pct": round(metrics_sma["final_equity"] - metrics_bnh["final_equity"], 2),
        "delta_sharpe": round(metrics_sma["sharpe_ratio"] - metrics_bnh["sharpe_ratio"], 4),
    }
    with open("logs/baseline_metrics_comparison.json", "w") as f:
        json.dump(comparison, f, indent=2, default=str)

    print("=" * 70)
    print(" PHASE 2 — BASELINE COMPARISON")
    print("=" * 70)
    print(f"{'Metric':<25} {'Buy & Hold':>15} {'SMA 50/200':>15} {'Delta':>12}")
    print("-" * 70)
    for key, label in [("sharpe_ratio", "Sharpe Ratio"),
                       ("max_drawdown_pct", "Max Drawdown %"),
                       ("total_return_pct", "Total Return %"),
                       ("final_equity", "Final Equity $"),
                       ("win_rate_proxy", "Up Days %")]:
        bnh_v = metrics_bnh.get(key, 0)
        sma_v = metrics_sma.get(key, 0)
        delta = round(sma_v - bnh_v, 4) if isinstance(bnh_v, (int, float)) else "n/a"
        print(f"{label:<25} {bnh_v:>15} {sma_v:>15} {delta:>12}")

    print("\n✅ PHASE 2 EXIT CRITERIA MET:")
    print(f"   - {len(bars)} daily bars replayed from Parquet data lake")
    print(f"   - 2 strategies benchmarked: Buy & Hold vs SMA 50/200")
    print(f"   - 2 equity curves saved (logs/equity_curve_bnh.csv, logs/equity_curve_sma.csv)")
    print(f"   - Comparison report: logs/baseline_metrics_comparison.json")


if __name__ == "__main__":
    asyncio.run(main())