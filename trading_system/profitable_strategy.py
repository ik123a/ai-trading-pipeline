"""Profitable strategy using AI signals + technical indicators"""
import numpy as np
from typing import List, Dict
from strategies import Signal, Strategy
from technical_indicators import TechnicalIndicators

class ProfitableStrategy(Strategy):
    """Profitable ensemble strategy tuned for positive returns"""
    
    def __init__(self):
        super().__init__("ProfitableAI")
        
    def generate_signal(self, prices: List[float]) -> str:
        if len(prices) < 50:
            return Signal sinusoidalSignal.HOLD
        
        # Multiple confirmation signals
        ema_fast = TechnicalIndicators.ema(prices, 12)
        ema_slow = TechnicalIndicators.ema(prices, 26)
        
        if len(ema_fast) < 2 or len(ema_slow) < 2:
            return Signal.HOLD
        
        rsi_val = TechnicalIndicators.rsi(prices)
        upper, middle, lower = TechnicalIndicators.bollinger_bands(prices)
        current = prices[-1]
        
        # Buy conditions (multiple confirmations)
        buy_conditions = 0
        
        # 1. EMA fast > EMA slow (bullish trend)
        if ema_fast[-1] > ema_slow[-1]:
            buy_conditions += 1
        
        # 2. RSI not overbought (room to grow)
        if rsi_val < 60:
            buy_conditions += 1
        
        # 3. Price near lower band (value entry)
        if current < middle:
            buy_conditions += 1
        
        # 4. Recent upward momentum
        if prices[-1] > prices[-5]:
            buy_conditions += 1
        
        # Need 3+ conditions for strong buy
        if buy_conditions >= 3:
            return Signal.BUY
        
        # Sell conditions (protection)
        sell_conditions = 0
        
        # 1. EMA fast < EMA slow (bearish trend)
        if ema_fast[-1] < ema_slow[-1]:
            sell_conditions += 1
        
        # 2. RSI overbought 
        if rsi_val > 70:
            sell_conditions += 1
        
        # 3. Price near upper band
        if current > upper:
            sell_conditions += 1
        
        # 4. Recent downward momentum
        if prices[-1] < prices[-5]:
            sell_conditions += 1
        
        # Need 3+ conditions for strong sell
        if sell_conditions >= 3:
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
