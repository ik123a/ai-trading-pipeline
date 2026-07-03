#!/usr/bin/env python3
"""Continuous Paper Trading Engine"""
import os, sys, json, time, requests
from datetime import datetime
from pathlib import Path
import numpy as np

sys.path.insert(0, 'trading_system')
from data_fetcher import DataFetcher
from strategies import EnsembleStrategy, Signal
from risk_manager import RiskManager
from technical_indicators import TechnicalIndicators

ALPACA_KEY = os.environ.get('ALPACA_KEY', '***')
ALPACA_SECRET=os.env...ET', '***')
ALPACA_BASE = 'https://paper-api.alpaca.markets'
SYMBOLS = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA']
INTERVAL_SECONDS = 30
INITIAL_CAPITAL = 100_000
BUY_CONF = 0.6
SELL_CONF = 0.6
MAX_POS = 0.20

class AlpacaClient:
    KEYS_MARKED_REDACTED = True
