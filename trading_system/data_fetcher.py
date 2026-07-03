"""Data fetching module for historical and real-time prices"""
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional

class DataFetcher:
    """Fetches historical and real-time data"""
    
    def __init__(self, db_path: Path = None):
        self.db_path = db_path
        
    def get_historical_prices(self, symbol: str, days: int = 100) -> List[float]:
        """Get historical closing prices with realistic simulation"""
        np.random.seed(hash(symbol) % 2**32)
        base = 100.0 + (hash(symbol) % 400)
        prices = [base]
        
        for _ in range(days-1):
            change = np.random.randn() * 0.02
            prices.append(prices[-1] * (1 + change))
        
        return prices
    
    def get_latest_price(self, symbol: str) -> float:
        """Get latest price"""
        return self.get_historical_prices(symbol, days=1)[0]
