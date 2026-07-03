"""Backtesting engine"""
from typing import List, Dict
from datetime import datetime
from strategies import Signal
from risk_manager import RiskManager
from technical_indicators import TechnicalIndicators

class Portfolio:
    """Manages trading portfolio"""
    def __init__(self, initial_capital: float):
        self.cash = initial_capital
        self.initial = initial_capital
        self.positions = {}
        self.trades = []
    
    def get_equity(self, current_prices: Dict[str, float]) -> float:
        equity = self.cash
        for symbol, pos in self.positions.items():
            if symbol in current_prices:
                equity += pos["qty"] * current_prices[symbol]
        return equity
    
    def buy(self, symbol: str, qty: int, price: float):
        if qty <= 0:
            return False
        cost = qty * price
        if cost > self.cash:
            return False
        self.cash -= cost
        self.positions[symbol] = {"qty": qty, "entry": price}
        self.trades.append({"date": datetime.now().isoformat(), "symbol": symbol, "side": "BUY", "qty": qty, "price": price})
        return True
    
    def sell(self, symbol: str, qty: int, price: float):
        if symbol not in self.positions:
            return False
        sell_qty = min(qty, self.positions[symbol]["qty"])
        self.cash += sell_qty * price
        self.positions[symbol]["qty"] -= sell_qty
        if self.positions[symbol]["qty"] <= 0:
            del self.positions[symbol]
        self.trades.append({"date": datetime.now().isoformat(), "symbol": symbol, "side": "SELL", "qty": sell_qty, "price": price})
        return True

class Backtester:
    """Backtests strategies on historical data"""
    
    def __init__(self, strategy, risk_manager: RiskManager, initial_capital: float = 100_000):
        self.strategy = strategy
        self.risk = risk_manager
        self.portfolio = Portfolio(initial_capital)
        self.results = {"dates": [], "equity": [], "signals": []}
    
    def run(self, prices: List[float], dates: List[str] = None) -> Dict:
        if dates is None:
            dates = [str(i) for i in range(len(prices))]
        
        for i in range(50, len(prices)):
            current_prices = {"TEST": prices[i]}
            signal = self.strategy.generate_signal(prices[:i+1])
            
            if signal == Signal.BUY and "TEST" not in self.portfolio.positions:
                entry = prices[i]
                atr = TechnicalIndicators.atr(prices[:i+1])
                stop = self.risk.calculate_stop_loss(entry, atr)
                qty = self.risk.calculate_position_size(self.portfolio.cash, entry, stop)
                if qty > 0:
                    self.portfolio.buy("TEST", qty, entry)
                    self.results["signals"].append({"date": dates[i], "signal": "BUY", "price": entry})
                    
            elif signal == Signal.SELL and "TEST" in self.portfolio.positions:
                self.portfolio.sell("TEST", self.portfolio.positions["TEST"]["qty"], prices[i])
                self.results["signals"].append({"date": dates[i], "signal": "SELL", "price": prices[i]})
            
            self.results["dates"].append(dates[i])
            self.results["equity"].append(self.portfolio.get_equity(current_prices))
        
        return self._calculate_metrics()
    
    def _calculate_metrics(self) -> Dict:
        equity = self.results["equity"]
        if not equity:
            return {}
        initial = equity[0]
        final = equity[-1]
        total_return = ((final - initial) / initial) * 100 if initial > 0 else 0
        
        peak = initial
        max_drawdown = 0
        for e in equity:
            if e > peak:
                peak = e
            drawdown = (peak - e) / peak if peak > 0 else 0
            max_drawdown = max(max_drawdown, drawdown)
        
        returns = [(equity[i] - equity[i-1]) / equity[i-1] for i in range(1, len(equity))]
        if returns:
            avg_return = sum(returns) / len(returns)
            std_return = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5
            sharpe = (avg_return / std_return) * (252 ** 0.5) if std_return > 0 else 0
        else:
            sharpe = 0
        
        return {
            "total_return_pct": round(total_return, 2),
            "max_drawdown_pct": round(max_drawdown * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "final_equity": round(final, 2),
            "num_trades": len(self.portfolio.trades),
            "win_rate": self._calculate_win_rate()
        }
    
    def _calculate_win_rate(self) -> float:
        if not self.portfolio.trades:
            return 0.0
        buys = [t for t in self.portfolio.trades if t["side"] == "BUY"]
        sells = [t for t in self.portfolio.trades if t["side"] == "SELL"]
        if not sells:
            return 0.0
        wins = sum(1 for s in sells if any(b["price"] < s["price"] for b in buys if b["symbol"] == s["symbol"]))
        return round((wins / len(sells)) * 100, 2)
