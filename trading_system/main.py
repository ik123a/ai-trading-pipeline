#!/usr/bin/env python3
"""Main execution script for AI Trading System"""
import sys
sys.path.insert(0, '.')

from data_fetcher import DataFetcher
from strategies import *
from risk_manager import RiskManager
from backtester import Backtester

# Configuration
SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
INITIAL_CAPITAL = 100_000.0

def test_strategies():
    """Test all strategies on current data"""
    print("=" * 60)
    print("STRATEGY TESTING")
    print("=" * 60)
    
    fetcher = DataFetcher()
    ensemble = EnsembleStrategy()
    
    for symbol in SYMBOLS[:3]:
        prices = fetcher.get_historical_prices(symbol, days=100)
        signal = ensemble.generate_signal(prices)
        strategy_signals = ensemble.get_strategy_signals(prices)
        
        print(f"\n{symbol}:")
        print(f"  Price: ${prices[-1]:.2f}")
        print(f"  Ensemble Signal: {signal}")
        print(f"  Individual Signals:")
        for name, sig in strategy_signals.items():
            print(f"    {name}: {sig}")

def run_backtests():
    """Run backtests for all strategies"""
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    
    fetcher = DataFetcher()
    risk = RiskManager()
    
    for strategy_name, strategy_class in [
        ("Momentum", MomentumStrategy),
        ("Mean Reversion", MeanReversionStrategy),
        ("Trend Following", TrendFollowingStrategy),
        ("Breakout", BreakoutStrategy),
        ("Ensemble", EnsembleStrategy)
    ]:
        strategy = strategy_class()
        backtester = Backtester(strategy, risk, INITIAL_CAPITAL)
        
        test_prices = fetcher.get_historical_prices("AAPL", days=252)
        results = backtester.run(test_prices)
        
        print(f"\n{strategy_name}:")
        print(f"  Total Return: {results.get('total_return_pct', 0):.2f}%")
        print(f"  Max Drawdown: {results.get('max_drawdown_pct', 0):.2f}%")
        print(f"  Sharpe Ratio: {results.get('sharpe_ratio', 0):.2f}")
        print(f"  Win Rate: {results.get('win_rate', 0):.1f}%")
        print(f"  Trades: {results.get('num_trades', 0)}")

def generate_dashboard():
    """Generate HTML dashboard"""
    print("\n" + "=" * 60)
    print("GENERATING DASHBOARD")
    print("=" * 60)
    
    html = '''<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>AI Trading System</title>
<style>
body{font-family:system-ui;background:#0b0c0e;color:#e2e5ea;margin:0;padding:40px}
.container{max-width:1200px;margin:0 auto}
h1{color:#3b82f6;font-size:28px;margin-bottom:8px}
.subtitle{color:#5a5f6a;font-size:14px;margin-bottom:30px}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:30px}
.metric{background:#1a1d24;border:1px solid #2a2e38;border-radius:12px;padding:20px}
.metric-title{font-size:11px;color:#8b909d;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px}
.metric-value{font-size:28px;font-weight:700;color:#22c55e}
.status{background:#1a1d24;border:1px solid #2a2e38;border-radius:12px;padding:20px;margin-bottom:20px}
.btn{background:#3b82f6;color:#fff;border:none;padding:12px 24px;border-radius:8px;cursor:pointer;font-size:14px;font-weight:600;margin-right:10px}
.btn:hover{background:#2563eb}
</style></head>
<body><div class="container">
<h1>AI Trading Command Center</h1>
<p class="subtitle">Ensemble Strategy Paper Trading System</p>
<div class="metrics">
<div class="metric"><div class="metric-title">Portfolio Equity</div><div class="metric-value">$100,000</div></div>
<div class="metric"><div class="metric-title">Total Return</div><div class="metric-value">+0.00%</div></div>
<div class="metric"><div class="metric-title">Sharpe Ratio</div><div class="metric-value">0.00</div></div>
<div class="metric"><div class="metric-title">Max Drawdown</div><div class="metric-value">0.00%</div></div>
</div>
<div class="status">
<h3>Strategy Testing Complete</h3>
<p>All 5 strategies tested: Momentum, Mean Reversion, Trend Following, Breakout, Ensemble</p>
<p>Backtest results available in terminal output.</p>
</div>
<div>
<a href="http://localhost:8080" class="btn">View Full Dashboard</a>
<a href="http://localhost:8765/health" class="btn" style="background:#1a1d24;border:1px solid #2a2e38">Check PPO Health</a>
</div>
</div></body></html>'''
    
    with open('dashboard/index.html', 'w') as f:
        f.write(html)
    
    print("Dashboard saved to: dashboard/index.html")
    print("Open: http://localhost:8080")

if __name__ == "__main__":
    print("AI TRADING SYSTEM - Paper Trading Pipeline")
    print("=" * 60)
    
    test_strategies()
    run_backtests()
    generate_dashboard()
    
    print("\n" + "=" * 60)
    print("SYSTEM READY")
    print("=" * 60)
    print("Dashboard: http://localhost:8080")
