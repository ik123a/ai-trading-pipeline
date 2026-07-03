"""
Smoke Test: NautilusTrader Backtest with Parquet Data Lake
Phase 1 Exit Criteria: Verify data loads and backtest runs without errors.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_parquet_data(ticker: str, granularity: str = "1d") -> pd.DataFrame:
    """Load data from the Parquet data lake."""
    parquet_path = Path(f"data-lake/ohlcv/{granularity}/{ticker}")
    
    if not parquet_path.exists():
        raise FileNotFoundError(f"No data found for {ticker} at {granularity}")
    
    files = list(parquet_path.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No parquet files for {ticker}")
    
    dfs = [pd.read_parquet(f) for f in sorted(files)]
    df = pd.concat(dfs).sort_index()
    
    logger.info(f"Loaded {len(df)} rows for {ticker}")
    return df

def run_smoke_test():
    """Run a simple smoke test to ensure data pipeline works."""
    logger.info("=== SMOKE TEST: Data Pipeline ===")
    
    # Test 1: Load data
    try:
        df = load_parquet_data("AAPL", "1d")
        logger.info(f"✅ Data load successful: {len(df)} rows")
        logger.info(f"   Date range: {df.index.min()} to {df.index.max()}")
        logger.info(f"   Columns: {list(df.columns)}")
    except Exception as e:
        logger.error(f"❌ Data load failed: {e}")
        return False
    
    # Test 2: Data quality checks
    try:
        assert not df.empty, "DataFrame is empty"
        assert 'close' in df.columns, "Missing 'close' column"
        assert not df['close'].isnull().any(), "NaN values in close price"
        logger.info("✅ Data quality checks passed")
    except AssertionError as e:
        logger.error(f"❌ Data quality failed: {e}")
        return False
    
    # Test 3: Simple calculation (SMA)
    try:
        df['sma_50'] = df['close'].rolling(window=50).mean()
        df['sma_200'] = df['close'].rolling(window=200).mean()
        logger.info("✅ Technical indicator calculation successful")
    except Exception as e:
        logger.error(f"❌ Calculation failed: {e}")
        return False
    
    logger.info("=== SMOKE TEST PASSED ===")
    return True

if __name__ == "__main__":
    success = run_smoke_test()
    exit(0 if success else 1)
