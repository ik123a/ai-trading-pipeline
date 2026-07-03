"""Trading strategies with ensemble voting"""
from typing import List, Dict
from technical_indicators import TechnicalIndicators

class Signal:
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

class Strategy:
    """Base class for trading strategies"""
    def __init__(self, name: str):
        self.name = name
    def generate_signal(self, prices: List[float]) -> str:
        raise NotImplementedError
    def get_confidence(self, prices: List[float]) -> float:
        return 0.5

class MomentumStrategy(Strategy):
    """Momentum strategy using EMA crossover + RSI + MACD"""
    def __init__(self):
        super().__init__("Momentum")
    def generate_signal(self, prices: List[float]) -> str:
        if len(prices) < 50:
            return Signal.HOLD
        ema_fast = TechnicalIndicators.ema(prices, 12)
        ema_slow = TechnicalIndicators.ema(prices, 26)
        if len(ema_fast) < 2 or len(ema_slow) < 2:
            return Signal.HOLD
        rsi_val = TechnicalIndicators.rsi(prices)
        ema_bullish = ema_fast[-1] > ema_slow[-1]
        rsi_ok = 30 < rsi_val < 70
        if ema_bullish and rsi_val < 65:
            return Signal.BUY
        elif not ema_bullish and rsi_val > 35:
            return Signal.SELL
        return Signal.HOLD
    def get_confidence(self, prices: List[float]) -> float:
        if len(prices) < 26:
            return 0.5
        ema_fast = TechnicalIndicators.ema(prices, 12)
        ema_slow = TechnicalIndicators.ema(prices, 26)
        if len(ema_fast) < 1 or len(ema_slow) < 1:
            return 0.5
        diff_pct = abs(ema_fast[-1] - ema_slow[-1]) / ema_slow[-1]
        return min(1.0, diff_pct * 10 + 0.5)

class MeanReversionStrategy(Strategy):
    """Mean reversion using Bollinger Bands"""
    def __init__(self):
        super().__init__("MeanReversion")
    def generate_signal(self, prices: List[float]) -> str:
        if len(prices) < 20:
            return Signal.HOLD
        upper, middle, lower = TechnicalIndicators.bollinger_bands(prices)
        current = prices[-1]
        rsi_val = TechnicalIndicators.rsi(prices)
        if current <= lower and rsi_val < 40:
            return Signal.BUY
        if current >= upper and rsi_val > 60:
            return Signal.SELL
        return Signal.HOLD
    def get_confidence(self, prices: List[float]) -> float:
        if len(prices) < 20:
            return 0.5
        upper, middle, lower = TechnicalIndicators.bollinger_bands(prices)
        current = prices[-1]
        distance = abs(current - middle) / (upper - lower) if upper != lower else 0
        return min(1.0, distance * 2)

class TrendFollowingStrategy(Strategy):
    """Trend following using SMA crossover"""
    def __init__(self):
        super().__init__("TrendFollowing")
    def generate_signal(self, prices: List[float]) -> str:
        if len(prices) < 50:
            return Signal.HOLD
        sma_short = TechnicalIndicators.sma(prices, 10)
        sma_long = TechnicalIndicators.sma(prices, 50)
        if len(sma_short) < 2 or len(sma_long) < 2:
            return Signal.HOLD
        if sma_short[-1] > sma_long[-1] and sma_short[-2] <= sma_long[-2]:
            return Signal.BUY
        if sma_short[-1] < sma_long[-1] and sma_short[-2] >= sma_long[-2]:
            return Signal.SELL
        return Signal.HOLD
    def get_confidence(self, prices: List[float]) -> float:
        if len(prices) < 50:
            return 0.5
        sma_short = TechnicalIndicators.sma(prices, 10)
        sma_long = TechnicalIndicators.sma(prices, 50)
        if len(sma_short) < 1 or len(sma_long) < 1:
            return 0.5
        diff_pct = abs(sma_short[-1] - sma_long[-1]) / sma_long[-1]
        return min(1.0, diff_pct * 10 + 0.5)

class BreakoutStrategy(Strategy):
    """Breakout strategy using recent highs/lows"""
    def __init__(self, lookback: int = 20):
        super().__init__("Breakout")
        self.lookback = lookback
    def generate_signal(self, prices: List[float]) -> str:
        if len(prices) < self.lookback + 5:
            return Signal.HOLD
        recent = prices[-self.lookback:]
        current = prices[-1]
        highest = max(recent)
        lowest = min(recent)
        if current > highest * 0.99:
            return Signal.BUY
        if current < lowest * 1.01:
            return Signal.SELL
        return Signal.HOLD
    def get_confidence(self, prices: List[float]) -> float:
        if len(prices) < self.lookback:
            return 0.5
        recent = prices[-self.lookback:]
        current = prices[-1]
        highest = max(recent)
        lowest = min(recent)
        range_size = highest - lowest
        if range_size == 0:
            return 0.5
        from_low = (current - lowest) / range_size
        return max(0.0, min(1.0, from_low))

class EnsembleStrategy(Strategy):
    """Combines multiple strategies using weighted voting"""
    def __init__(self):
        super().__init__("Ensemble")
        self.strategies = {
            "momentum": MomentumStrategy(),
            "mean_reversion": MeanReversionStrategy(),
            "trend_following": TrendFollowingStrategy(),
            "breakout": BreakoutStrategy()
        }
        self.weights = {
            "momentum": 0.3,
            "mean_reversion": 0.25,
            "trend_following": 0.25,
            "breakout": 0.2
        }
    def generate_signal(self, prices: List[float]) -> str:
        votes = {Signal.BUY: 0.0, Signal.SELL: 0.0, Signal.HOLD: 0.0}
        for name, strategy in self.strategies.items():
            signal = strategy.generate_signal(prices)
            confidence = strategy.get_confidence(prices)
            weight = self.weights[name]
            if signal in votes:
                votes[signal] += weight * confidence
        return max(votes, key=votes.get)
    def get_strategy_signals(self, prices: List[float]) -> Dict[str, str]:
        return {name: strategy.generate_signal(prices) for name, strategy in self.strategies.items()}
