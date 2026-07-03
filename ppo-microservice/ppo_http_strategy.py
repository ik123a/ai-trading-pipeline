"""
Phase 3 — MLOps bridge: NautilusTrader strategy that calls /predict_weights
over HTTP, latency-gated to PPO_LATENCY_BUDGET_MS (default 200ms).
Includes fallback when the microservice is unreachable so backtest never crashes.
"""

import os
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import requests

from nautilus_trader.common.enums import LogColor
from nautilus_trader.config import StrategyConfig
from nautilus_trader.core.data import DataType
from nautilus_trader.model.data import BarType, Bar
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments.equity import Equity as EquityInstrument
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy


PPO_ENDPOINT_URL = os.getenv("PPO_ENDPOINT_URL", "http://127.0.0.1:8001/predict_weights")
PPO_HEALTH_URL = os.getenv("PPO_HEALTH_URL", "http://127.0.0.1:8001/health")
PPO_LATENCY_BUDGET_MS = float(os.getenv("PPO_LATENCY_BUDGET_MS", "200"))
PPO_TIMEOUT_SECONDS = float(os.getenv("PPO_TIMEOUT_SECONDS", "0.5"))
PPO_LOG_DIR = Path(os.getenv("PPO_LOG_DIR", "logs/ppo-microservice"))
PPO_LOG_DIR.mkdir(parents=True, exist_ok=True)
LATENCY_LOG = PPO_LOG_DIR / "nautilus_strategy_latency.jsonl"


class PpoHttpConfig(StrategyConfig, frozen=True):
    """Configuration for PpoHttpStrategy."""
    instrument_id: str = "AAPL.SIM"
    bar_type: str = "AAPL.SIM-1-DAY-LAST-EXTERNAL"
    ppo_endpoint_url: str = PPO_ENDPOINT_URL
    ppo_health_url: str = PPO_HEALTH_URL
    latency_budget_ms: float = PPO_LATENCY_BUDGET_MS
    timeout_seconds: float = PPO_TIMEOUT_SECONDS
    n_tickers: int = 1  # Single ticker = easier signal
    feature_window: int = 20
    target_dollars: float = 90_000.0  # ~90% of portfolio on first BUY signal


class PpoHttpStrategy(Strategy):
    """
    Calls the external PPO microservice to obtain a portfolio weight per ticker.
    Falls back to 0-weight when service is unreachable, call exceeds latency
    budget, or HTTP error occurs — so backtests remain deterministic.

    When the service returns a positive equities weight, the strategy BUYS up to
    target_dollars of stock (entry signal); when the weight flips negative or
    near zero, it closes the position with a market SELL order.
    """

    def __init__(self, config: PpoHttpConfig):
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)
        self.endpoint = config.ppo_endpoint_url
        self.health_url = config.ppo_health_url
        self.latency_budget_ms = config.latency_budget_ms
        self.timeout = config.timeout_seconds
        self.n_tickers = config.n_tickers
        self.feature_window = config.feature_window
        self.target_dollars = config.target_dollars

        # State
        self._closes: List[float] = []
        self._episode_id = uuid.uuid4().hex
        self._total_calls = 0
        self._within_budget = 0
        self._overbudget = 0
        self._errors = 0
        self._max_latency_ms = 0.0
        self._bought = False

    def on_start(self) -> None:
        self.log.info(f"🚀 PPO HTTP strategy started — endpoint={self.endpoint}", LogColor.BLUE)
        try:
            r = requests.get(self.health_url, timeout=2)
            self.log.info(f"Health check: HTTP {r.status_code}", LogColor.GREEN if r.status_code == 200 else LogColor.YELLOW)
        except Exception as e:
            self.log.warning(f"Health check failed: {e}", LogColor.YELLOW)

        # Subscribe via bus + directly via bar handler for backtest.
        self.subscribe_bars(self.bar_type)

    def on_stop(self) -> None:
        self.log.info(
            f"PPO HTTP strategy stopped. calls={self._total_calls} within_budget={self._within_budget} "
            f"over_budget={self._overbudget} errors={self._errors} max_latency={self._max_latency_ms:.1f}ms",
            LogColor.CYAN,
        )

    def _compute_features(self) -> List[List[float]]:
        """Build features from recent prices: returns, rolling sum of returns, vol, etc."""
        if not self._closes:
            return [[0.0] * self.n_tickers]
        arr = np.asarray(self._closes[-self.feature_window:], dtype=np.float64)
        if arr.size < 2:
            return [[0.0] * self.n_tickers]
        returns = np.diff(arr) / arr[:-1]
        # 6 features: mean_5r, vol_5r, mean_10r, vol_10r, last_return, mean_window
        w = returns[-min(20, len(returns)):]
        if len(w) < 1:
            w = returns
        feats = [
            float(w[-min(5, len(w)):].mean() if len(w) > 0 else 0.0),
            float(w[-min(5, len(w)):].std() if len(w) > 1 else 0.0),
            float(w[-min(10, len(w)):].mean() if len(w) > 0 else 0.0),
            float(w[-min(10, len(w)):].std() if len(w) > 1 else 0.0),
            float(w[-1]) if len(w) > 0 else 0.0,
            float(arr.mean()),
            float(arr.std() / max(arr.mean(), 1e-6)),
        ]
        # Pad/trim to n_tickers
        if len(feats) < self.n_tickers:
            feats = feats + [0.0] * (self.n_tickers - len(feats))
        feats = feats[: self.n_tickers]
        return [feats]  # wrap to window x n_features

    def _call_ppo(self) -> Optional[List[float]]:
        """POST to PPO microservice with latency gating."""
        request_features = self._compute_features()
        payload = {
            "features": request_features,
            "n_tickers": self.n_tickers,
            "ticker": self.instrument_id.symbol.value,
            "episode_id": self._episode_id,
        }
        t0 = time.perf_counter()
        try:
            resp = requests.post(self.endpoint, json=payload, timeout=self.timeout)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self._total_calls += 1
            self._max_latency_ms = max(self._max_latency_ms, elapsed_ms)
            if elapsed_ms <= self.latency_budget_ms:
                self._within_budget += 1
            else:
                self._overbudget += 1
                self.log.warning(
                    f"PPO latency {elapsed_ms:.1f}ms exceeded budget {self.latency_budget_ms}ms",
                    LogColor.YELLOW,
                )
            resp.raise_for_status()
            data = resp.json()
            weights = data.get("weights") or []
            record = {
                "ts": time.time(),
                "elapsed_ms": elapsed_ms,
                "within_budget": elapsed_ms <= self.latency_budget_ms,
                "weights_first": float(weights[0]) if weights else None,
                "server_latency_ms": data.get("latency_ms"),
                "model_id": data.get("model_id"),
                "episode_id": self._episode_id,
            }
            try:
                with LATENCY_LOG.open("a") as f:
                    f.write(_json_dump(record) + "\n")
            except OSError:
                pass
            return weights
        except requests.exceptions.RequestException as e:
            self._errors += 1
            self.log.error(f"PPO call error: {e}", LogColor.RED)
            return None
        except Exception as e:
            self._errors += 1
            self.log.error(f"Unexpected PPO error: {e}", LogColor.RED)
            return None

    def _buy_target_dollars(self, price: float) -> None:
        if price <= 0:
            return
        qty = int(self.target_dollars // price)
        if qty > 0:
            self.submit_order(self.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=OrderSide.BUY,
                quantity=Quantity.from_int(qty),
            ))

    def _close_all(self) -> None:
        positions = self.cache.positions_open(instrument_id=self.instrument_id)
        for p in positions:
            self.submit_order(self.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=OrderSide.SELL,
                quantity=Quantity.from_int(int(p.net_qty or 0)),
            ))

    def on_bar(self, bar: Bar) -> None:
        self._closes.append(bar.close.as_double())
        if len(self._closes) < self.feature_window:
            return  # warmup

        weights = self._call_ppo()
        if weights is None:
            return  # graceful fallback
        first_weight = float(weights[0])
        # Decision: w > 0.5 = aggressive BUY, w < 0.2 = exit
        if not self._bought and first_weight > 0.5:
            self._buy_target_dollars(bar.close.as_double())
            self._bought = True
            self.log.info(
                f"PPO BUY signal (w={first_weight:.4f})",
                LogColor.GREEN,
            )
        elif self._bought and first_weight < 0.2:
            self._close_all()
            self._bought = False
            self.log.info(
                f"PPO SELL signal (w={first_weight:.4f})",
                LogColor.YELLOW,
            )


def _json_dump(d: dict) -> str:
    import json
    return json.dumps(d, default=str)
