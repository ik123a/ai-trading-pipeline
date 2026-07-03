"""
Phase 1-2 Bridge: NautilusTrader Backtest with Parquet Data Lake
Runs a 5-year buy-and-hold + SMA crossover backtest and exports baseline metrics + equity curve.
"""
import asyncio
import logging
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import ImportableStrategyConfig
from nautilus_trader.model.data import Bar, BarType, QuoteTick, TradeTick
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.model.enums import PositionSide

# Import our Nautilus strategy
from strategies.baseline_strategy import BaselineStrategy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "V", "WMT"]

def load_parquet_data_lake(ticker: str) -> pd.DataFrame:
    """Load data from our parquet lake into Nautilus-compatible format."""
    base_path = Path("data-lake/ohlcv/1d") / ticker
    files = sorted(base_path.glob("*.parquet"))
    
    if not files:
        logger.warning(f"No data for {ticker}")
        return pd.DataFrame()
    
    dfs = []
    for f in files:
        df = pd.read_parquet(f)
        dfs.append(df)
    
    return pd.concat(dfs).sort_index()


def prepare_bars_for_nautilus(df: pd.DataFrame, ticker: str) -> list[Bar]:
    """Convert DataFrame rows to Nautilus Bar objects."""
    bars = []
    instrument_id = InstrumentId.from_str(f"{ticker}.SIM")
    
    for idx, row in df.iterrows():
        # Convert pandas Timestamp to nanoseconds
        ts_ns = int(idx.asm8)
        ts_event_ns = ts_ns + 1000000  # +1ms for event time
        
        bar = Bar(
            bar_type=BarType.from_str(f"{ticker}.SIM-1-DAY-LAST-INTERNAL"),
            open=Price.from_str(str(row['open'])),
            high=Price.from_str(str(row['high'])),
            low=Price.from_str(str(row['low'])),
            close=Price.from_str(str(row['close'])),
            volume=Quantity.from_str(str(row['volume'])),
            ts_event=ts_event_ns,
            ts_init=ts_ns,
        )
        bars.append(bar)
    
    return bars


async def run_backtest():
    """Main backtest execution."""
    logger.info("=== PHASE 1-2 BACKTEST ===")
    
    # Build backtest engine
    config = BacktestEngineConfig(trader_id="SMOKE_TEST_001")
    engine = BacktestEngine(config=config)
    
    # Register instrument
    instrument_id = InstrumentId.from_str("AAPL.SIM")
    instrument = Equity(
        instrument_id=instrument_id,
        native_symbol="AAPL",
        currency=USD,
        price_precision=2,
        price_increment=Price.from_str("0.01"),
        multiplier=Quantity.from_int(1),
        lot_singular="1",
        lot_plural="1",
        isin="",
        venue=Venue("SIM"),
        ts_event=0,
        ts_init=0,
    )
    engine.add_instrument(instrument)
    
    # Load data from our parquet lake
    logger.info("Loading data from Parquet lake...")
    df = load_parquet_data_lake("AAPL")
    logger.info(f"Loaded {len(df)} rows for AAPL")
    
    if df.empty:
        logger.error("No data available")
        return
    
    # Prepare bars
    bars = prepare_bars_for_nautilus(df, "AAPL")
    logger.info(f"Prepared {len(bars)} bars")
    
    # Add data
    engine.add_data(bars)
    
    # Add strategy
    engine.add_strategy(
        strategy=ImportableStrategyConfig(
            strategy_path="strategies.baseline_strategy:BaselineStrategy",
            config_path="strategies.baseline_strategy",
            config={
                "instrument_id": "AAPL.SIM",
                "bar_type": "AAPL.SIM-1-DAY-LAST-INTERNAL",
                "short_window": 50,
                "long_window": 200,
            }
        )
    )
    
    # Run
    logger.info("Running backtest...")
    result = engine.run()
    
    logger.info("=== BACKTEST COMPLETE ===")
    
    # Export results
    export_results(engine, result)
    
    return result


def export_results(engine: BacktestEngine, result):
    """Export equity curve and metrics to CSV/JSON."""
    # Get account state over time
    states = engine.trader.generate_account_report()
    
    if states.empty:
        logger.error("No account states generated")
        return
    
    # Build equity curve
    equity_rows = []
    for idx, row in states.iterrows():
        equity_rows.append({
            "timestamp": idx,
            "equity": float(row.get("equity", 0)),
            "cash": float(row.get("cash", 0)),
            "positions_value": float(row.get("position_value", 0)),
        })
    
    equity_df = pd.DataFrame(equity_rows)
    equity_df.to_csv("logs/equity_curve_nautilus.csv", index=False)
    logger.info(f"✅ Equity curve saved: {len(equity_df)} rows")
    
    # Calculate baseline metrics
    if len(equity_df) > 1:
        equity_df['returns'] = equity_df['equity'].pct_change()
        
        returns = equity_df['returns'].dropna()
        if len(returns) > 0:
            sharpe = (returns.mean() / returns.std()) * np.sqrt(252)
        else:
            sharpe = 0
        
        peak = equity_df['equity'].expanding().max()
        drawdown = (equity_df['equity'] - peak) / peak
        max_dd = float(drawdown.min())
        
        # Save metrics
        import json
        metrics = {
            "sharpe_ratio": round(sharpe, 4),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "total_return_pct": round(((equity_df['equity'].iloc[-1] / equity_df['equity'].iloc[0]) - 1) * 100, 2),
            "final_equity": round(float(equity_df['equity'].iloc[-1]), 2),
            "start_date": str(equity_df['timestamp'].iloc[0]),
            "end_date": str(equity_df['timestamp'].iloc[-1]),
            "total_days": len(equity_df),
        }
        
        with open("logs/baseline_metrics.json", "w") as f:
            json.dump(metrics, f, indent=2)
        
        logger.info(f"✅ Baseline metrics saved: {json.dumps(metrics, indent=2)}")
    else:
        logger.error("Not enough data for metrics")


if __name__ == "__main__":
    asyncio.run(run_backtest())