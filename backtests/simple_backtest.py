"""
Lightweight Backtest Engine (Phase 1 - Smoke Test)
Mimics NautilusTrader's core functionality for rapid validation.
Will be replaced with NautilusTrader in Phase 2.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Callable
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SimpleBacktestEngine:
    """Minimal backtest engine for smoke testing data pipeline."""
    
    def __init__(self, initial_cash: float = 100000.0):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions = {}  # ticker -> shares
        self.trades = []
        self.equity_curve = []
        
    def load_data(self, ticker: str, path: Path) -> pd.DataFrame:
        """Load OHLCV data from parquet data lake."""
        files = sorted(path.glob("*.parquet"))
        if not files:
            raise FileNotFoundError(f"No data for {ticker}")
        
        dfs = [pd.read_parquet(f) for f in files]
        df = pd.concat(dfs).sort_index()
        logger.info(f"Loaded {len(df)} rows for {ticker}")
        return df
    
    def run_sma_strategy(self, df: pd.DataFrame, short_period: int = 50, long_period: int = 200) -> pd.DataFrame:
        """Run simple SMA crossover strategy."""
        df = df.copy()
        df['sma_short'] = df['close'].rolling(window=short_period).mean()
        df['sma_long'] = df['close'].rolling(window=long_period).mean()
        
        position = 0
        for i in range(len(df)):
            row = df.iloc[i]
            price = row['close']
            
            if pd.isna(row['sma_short']) or pd.isna(row['sma_long']):
                continue
            
            # Buy signal
            if position == 0 and row['sma_short'] > row['sma_long']:
                position = self.cash // price
                self.cash -= position * price
                self.trades.append({
                    'date': df.index[i],
                    'action': 'BUY',
                    'price': price,
                    'shares': position
                })
            
            # Sell signal
            elif position > 0 and row['sma_short'] < row['sma_long']:
                self.cash += position * price
                self.trades.append({
                    'date': df.index[i],
                    'action': 'SELL',
                    'price': price,
                    'shares': position
                })
                position = 0
            
            # Track equity
            equity = self.cash + (position * price if position > 0 else 0)
            self.equity_curve.append({
                'date': df.index[i],
                'equity': equity
            })
        
        return df
    
    def calculate_metrics(self) -> Dict:
        """Calculate basic performance metrics."""
        if not self.equity_curve:
            return {}
        
        equity_df = pd.DataFrame(self.equity_curve)
        equity_df['returns'] = equity_df['equity'].pct_change()
        
        # Sharpe Ratio (annualized, assuming 252 trading days)
        excess_returns = equity_df['returns'].dropna()
        if len(excess_returns) > 1:
            sharpe = (excess_returns.mean() / excess_returns.std()) * np.sqrt(252)
        else:
            sharpe = 0
        
        # Max Drawdown
        equity_series = equity_df['equity']
        peak = equity_series.expanding(min_periods=1).max()
        drawdown = (equity_series - peak) / peak
        max_drawdown = drawdown.min()
        
        # Win/Loss Ratio
        wins = len([t for t in self.trades if t['action'] == 'SELL' and t['price'] > self.trades[self.trades.index(t)-1]['price']])
        losses = len([t for t in self.trades if t['action'] == 'SELL' and t['price'] <= self.trades[self.trades.index(t)-1]['price']])
        win_loss = wins / losses if losses > 0 else float('inf') if wins > 0 else 0
        
        return {
            'sharpe_ratio': round(sharpe, 4),
            'max_drawdown': round(max_drawdown * 100, 2),  # percentage
            'win_loss_ratio': round(win_loss, 2),
            'total_trades': len(self.trades),
            'final_equity': round(self.equity_curve[-1]['equity'], 2) if self.equity_curve else self.initial_cash
        }


def run_smoke_test():
    """Execute Phase 1 smoke test."""
    logger.info("=== PHASE 1 SMOKE TEST ===")
    
    engine = SimpleBacktestEngine(initial_cash=100000)
    
    # Test data loading
    try:
        df = engine.load_data("AAPL", Path("data-lake/ohlcv/1d/AAPL"))
        logger.info(f"✅ Data loaded: {len(df)} rows")
    except Exception as e:
        logger.error(f"❌ Data load failed: {e}")
        return False
    
    # Test strategy execution
    try:
        engine.run_sma_strategy(df)
        logger.info(f"✅ Backtest completed")
        logger.info(f"   Trades executed: {len(engine.trades)}")
    except Exception as e:
        logger.error(f"❌ Backtest failed: {e}")
        return False
    
    # Calculate metrics
    metrics = engine.calculate_metrics()
    logger.info(f"✅ Metrics calculated:")
    totally_metrics = f"""
    Sharpe Ratio: {metrics['sharpe_ratio']}
    Max Drawdown: {metrics['max_drawdown']}%
    Win/Loss Ratio: {metrics['win_loss_ratio']}
    Total Trades: {metrics['total_trades']}
    Final Equity: ${metrics['final_equity']:,}
    """
    logger.info(totally_metrics)
    
    # Save equity curve for Phase 2 baseline
    equity_df = pd.DataFrame(engine.equity_curve)
    equity_df.to_csv("logs/equity_curve_baseline.csv", index=False)
    logger.info("✅ Equity curve saved to logs/equity_curve_baseline.csv")
    
    return True


if __name__ == "__main__":
    success = run_smoke_test()
    exit(0 if success else 1)
