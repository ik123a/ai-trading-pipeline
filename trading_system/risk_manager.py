"""Risk management module"""
from typing import Dict

class RiskManager:
    """Manages risk for trading positions"""
    
    def __init__(self, max_risk_per_trade: float = 0.02, 
                 max_portfolio_risk: float = 0.06,
                 stop_loss_atr_multiplier: float = 2.0,
                 take_profit_atr_multiplier: float = 3.0):
        self.max_risk_per_trade = max_risk_per_trade
        self.max_portfolio_risk = max_portfolio_risk
        self.stop_loss_atr_multiplier = stop_loss_atr_multiplier
        self.take_profit_atr_multiplier = take_profit_atr_multiplier
    
    def calculate_position_size(self, capital: float, entry_price: float, stop_loss: float) -> int:
        risk_per_share = abs(entry_price - stop_loss)
        if risk_per_share == 0:
            return 0
        max_risk_amount = capital * self.max_risk_per_trade
        return max(0, int(max_risk_amount / risk_per_share))
    
    def calculate_stop_loss(self, entry_price: float, atr: float, side: str = "long") -> float:
        if side == "long":
            return entry_price - (atr * self.stop_loss_atr_multiplier)
        return entry_price + (atr * self.stop_loss_atr_multiplier)
    
    def calculate_take_profit(self, entry_price: float, atr: float, side: str = "long") -> float:
        if side == "long":
            return entry_price + (atr * self.take_profit_atr_multiplier)
        return entry_price - (atr * self.take_profit_atr_multiplier)
