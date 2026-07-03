"""
Paper Trading System Configuration
"""
import os

# Alpaca Paper Trading API
ALPACA_API_KEY = os.getenv("PAPER_API_KEY",
                           "***")
ALPACA_SECRET = os.getenv("PAPER_SECRET_KEY",
                          "***")
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"

# Trading Parameters
SYMBOL = "AAPL"
CASH_RESERVE = 0.2  # 20% cash reserve
MAX_POSITIONS = 5
RISK_PER_TRADE = 0.02  # 2% risk per trade
STOP_LOSS_PCT = 0.05  # 5% stop loss
TAKE_PROFIT_PCT = 0.10  # 10% take profit

# Strategy Parameters
LOOKBACK = 20
SHORT_EMA = 9
MEDIUM_EMA = 21
LONG_EMA = 50
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
BB_PERIOD = 20
BB_STD = 2.0

# Backtest
START_DATE = "2020-01-01"
END_DATE = "2024-12-31"
INITIAL_CAPITAL = 100000.0

# Logging
LOG_LEVEL = "INFO"
DATA_DIR = "./data"
