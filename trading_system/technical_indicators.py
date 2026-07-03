"""Technical indicators for trading strategies"""
from typing import List, Tuple

class TechnicalIndicators:
    """Calculate technical indicators"""
    
    @staticmethod
    def sma(prices: List[float], period: int) -> List[float]:
        """Simple Moving Average"""
        if len(prices) < period:
            return prices[:]
        return [sum(prices[i:i+period])/period for i in range(len(prices)-period+1)]
    
    @staticmethod
    def ema(prices: List[float], period: int) -> List[float]:
        """Exponential Moving Average"""
        if len(prices) < period:
            return prices[:]
        multiplier = 2 / (period + 1)
        ema = [prices[0]]
        for price in prices[1:]:
            ema.append((price - ema[-1]) * multiplier + ema[-1])
        return ema
    
    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> float:
        """Relative Strength Index"""
        if len(prices) < period + 1:
            return 50.0
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [max(0, d) for d in deltas[-period:]]
        losses = [abs(min(0, d)) for d in deltas[-period:]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        return 100 - (100 / (1 + avg_gain / avg_loss))
    
    @staticmethod
    def bollinger_bands(prices: List[float], period: int = 20) -> Tuple[float, float, float]:
        """Bollinger Bands - returns (upper, middle, lower)"""
        if len(prices) < period:
            p = prices[-1]
            return p, p, p
        recent = prices[-period:]
        mean = sum(recent) / period
        std = (sum((p - mean) ** 2 for p in recent) / period) ** 0.5
        return mean + 2*std, mean, mean - 2*std
    
    @staticmethod
    def atr(prices: List[float], period: int = 14) -> float:
        """Average True Range"""
        if len(prices) < 2:
            return 0.0
        changes = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        if len(changes) < period:
            return sum(changes) / len(changes) if changes else 0.0
        return sum(changes[-period:]) / period
