"""
Phase 3 — HTTP Proxy Strategy (NautilusTrader → PPO Microservice)
Wires the Rust execution engine to the FastAPI PPO inference service.

Key behavior:
  1. on_bar() accumulates bars and builds a feature vector
  2. Calls POST /predict_weights on the microservice
  3. Enforces 200ms latency budget — if exceeded, skip this bar
  4. Rebalances portfolio toward target weights
  5. Logs every API call latency for observability
"""
import time
from typing import Optional

import numpy as np
import pandas as pd
import requests
from requests.exceptions import RequestException, Timeout

from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity, Price
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.orders import MarketOrder
from nautilus_trader.model.currencies import USD


# ── Config ────────────────────────────────────────────────────────────────────

from dataclasses import dataclass, field
from nautilus_trader.config.strategy import StrategyConfig


@dataclass(frozen=True)
class PPORESTConfig(StrategyConfig):
    instrument_id: str = "AAPL.SIM"
    bar_type: str = "AAPL.SIM-1-DAY-LAST-EXTERNAL"
    # API endpoint (the microservice running in Docker/localhost)
    api_url: str = "http://localhost:8001/predict_weights"
    health_url: str = "http://localhost:8001/health"
    # How often to call the model (every N bars)
    signal_interval_bars: int = 5
    # Latency budget in seconds
    latency_budget_ms: float = 200.0
    # Minimum change in weight to trigger a rebalance
    rebalance_threshold: float = 0.02  # 2% shift minimum
    max_position_pct: float = 0.25  # max 25% of portfolio in one asset
    # Indicators window sizes
    sma_short_period: int = 20
    sma_long_period: int = 50
    rsi_period: int = 14


# ── Simple Technical Indicator helpers ───────────────────────────────────────

class SimpleSMA:
    def __init__(self, period: int):
        self.period = period
        self.values: list[float] = []
        self.result: Optional[float] = None

    def update(self, value: float) -> Optional[float]:
        self.values.append(value)
        if len(self.values) > self.period:
            self.values.pop(0)
        if len(self.values) == self.period:
            self.result = sum(self.values) / self.period
        return self.result

    @property
    def initialized(self) -> bool:
        return self.result is not None


class SimpleRSI:
    def __init__(self, period: int = 14):
        self.period = period
        self.gains: list[float] = []
        self.losses: list[float] = []
        self.result: Optional[float] = None

    def update(self, price: float, prev_price: Optional[float]) -> Optional[float]:
        if prev_price is None:
            return None
        delta = price - prev_price
        if delta > 0:
            self.gains.append(delta)
            self.losses.append(0.0)
        else:
            self.gains.append(0.0)
            self.losses.append(abs(delta))
        if len(self.gains) > self.period:
            self.gains.pop(0)
            self.losses.pop(0)
        if len(self.gains) == self.period:
            avg_gain = sum(self.gains) / self.period
            avg_loss = sum(self.losses) / self.period
            if avg_loss < 1e-10:
                self.result = 100.0
            else:
                rs = avg_gain / avg_loss
                self.result = 100.0 - (100.0 / (1.0 + rs))
        return self.result


# ── HTTP Proxy Strategy ──────────────────────────────────────────────────────

class PPORESTStrategy(Strategy):
    """
    Calls a remote PPO microservice for portfolio weights instead of running
    inference locally. This keeps Python RL isolated from the Rust execution
    engine, enabling independent scaling of each component.

    The strategy:
      - Accumulates a rolling window of bars
      - Builds OHLCV + tech indicator features
      - POSTs to /predict_weights with a 200ms timeout
      - If the call succeeds within budget: rebalances to target weights
      - If the call fails or times out: skips, logs, continues on next bar
    """

    def __init__(self, config: PPORESTConfig):
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type_str = config.bar_type
        self.bar_type = self.bar_type.from_str(config.bar_type)
        self.api_url = config.api_url
        self.health_url = config.health_url
        self.signal_interval = config.signal_interval_bars
        self.latency_budget_ms = config.latency_budget_ms
        self.rebalance_threshold = config.rebalance_threshold
        self.max_position_pct = config.max_position_pct

        # Indicators
        self.sma_short = SimpleSMA(config.sma_short_period)
        self.sma_long = SimpleSMA(config.sma_long_period)
        self.rsi = SimpleRSI(config.rsi_period)
        self.prev_close: Optional[float] = None
        self.bar_count = 0

        # Last weights from model (for rebalance delta check)
        self.last_weights: Optional[list[float]] = None
        self.last_api_latency_ms: Optional[float] = None
        self.api_errors: int = 0
        self.api_timeouts: int = 0
        self.api_success: int = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_start(self):
        self.subscribe_bars(self.bar_type)
        self.log.info(f"PPO REST Strategy starting | API: {self.api_url} | budget: {self.latency_budget_ms}ms")

    def on_stop(self):
        self.log.info(
            f"PPO REST Strategy stopped | "
            f"API calls: {self.api_success} ok, {self.api_errors} errors, "
            f"{self.api_timeouts} timeouts"
        )

    # ── Main decision loop ──────────────────────────────────────────────────────

    def on_bar(self, bar: Bar):
        self.bar_count += 1

        # Update indicators
        close = bar.close.as_double()
        self.sma_short.update(close)
        rsi_val = self.rsi.update(close, self.prev_close)
        self.sma_long.update(close)
        self.prev_close = close

        # Only call the model every N bars (avoid excessive API calls in backtest)
        if self.bar_count % self.signal_interval != 0:
            return

        # Build feature vector: OHLCV + indicators
        features = self._build_features(bar)
        if features is None:
            self.log.warning("Features not ready yet, skipping bar")
            return

        # Call PPO microservice
        weights, latency_ms = self._call_ppo_api(features)

        if weights is None:
            return  # error/timeout, already logged inside _call_ppo_api

        self.last_weights = weights
        self.last_api_latency_ms = latency_ms

        # Check latency budget
        if latency_ms > self.latency_budget_ms:
            self.log.warning(
                f"⏱️  Latency over budget: {latency_ms:.1f}ms > {self.latency_budget_ms}ms — skipping rebalance"
            )
            return

        # Rebalance toward target weights
        self._rebalance(weights)

    # ── Feature engineering ────────────────────────────────────────────────────

    def _build_features(self, bar: Bar) -> Optional[list[float]]:
        """Build flat feature vector from current bar + indicators."""
        if not self.sma_short.initialized:
            return None

        close = bar.close.as_double()
        high = bar.high.as_double()
        low = bar.low.as_double()
        open_ = bar.open.as_double()
        volume = bar.volume.as_double()

        sma_s = self.sma_short.result or 0.0
        sma_l = self.sma_long.result or 0.0
        rsi = self.rsi.result or 50.0

        # Feature vector: [open, high, low, close, volume,
        #                   sma_short, sma_long, price/sma_short, price/sma_long, rsi]
        features = [
            float(open_),
            float(high),
            float(low),
            float(close),
            float(volume),
            float(sma_s),
            float(sma_l),
            float(close / sma_s) if sma_s != 0 else 1.0,
            float(close / sma_l) if sma_l != 0 else 1.0,
            float(rsi),
        ]
        return features

    # ── HTTP call to PPO microservice ─────────────────────────────────────────

    def _call_ppo_api(self, features: list[float]) -> tuple[Optional[list[float]], float]:
        """
        POST to the microservice.
        Returns (weights, latency_ms) on success, (None, latency_ms) on failure.
        """
        payload = {
            "features": features,
            "ticker": str(self.instrument_id.symbol),
            "portfolio_value": float(self.portfolio.total_value().as_decimal()),
        }

        t0 = time.perf_counter()
        try:
            resp = requests.post(
                self.api_url,
                json=payload,
                timeout=self.latency_budget_ms / 1000.0,  # convert to seconds
                headers={"Content-Type": "application/json"},
            )
            latency_ms = (time.perf_counter() - t0) * 1000

            if resp.status_code == 408:
                # Latency budget exceeded by the service itself
                self.api_timeouts += 1
                self.log.error(f"⏱️  PPO service latency budget exceeded: {latency_ms:.1f}ms")
                return None, latency_ms

            if resp.status_code != 200:
                self.api_errors += 1
                self.log.error(f"PPO API error {resp.status_code}: {resp.text[:200]}")
                return None, latency_ms

            data = resp.json()
            weights = data.get("weights", [])
            self.api_success += 1

            self.log.info(
                f"📡 PPO API | latency={latency_ms:.1f}ms | weights={[round(w,3) for w in weights]} "
                f"| action={data.get('action','?')} | model={data.get('model_version','?')}"
            )
            return weights, latency_ms

        except Timeout:
            latency_ms = (time.perf_counter() - t0) * 1000
            self.api_timeouts += 1
            self.log.error(f"⏱️  PPO API timeout after {latency_ms:.1f}ms")
            return None, latency_ms
        except RequestException as e:
            latency_ms = (time.perf_counter() - t0) * 1000
            self.api_errors += 1
            self.log.error(f"PPO API connection error: {e}")
            return None, latency_ms

    # ── Rebalance logic ────────────────────────────────────────────────────────

    def _rebalance(self, target_weights: list[float]):
        """
        Compare current portfolio weights to target, issue market orders
        to close the gap. Only issues orders when delta > rebalance_threshold.
        """
        if len(target_weights) == 0:
            return

        portfolio_value = float(self.portfolio.total_value().as_decimal())
        if portfolio_value <= 0:
            return

        # Single-asset case: target_weights[0] is the target position fraction
        # We only support one ticker for now, but the API may return multi-asset weights
        target_frac = float(target_weights[0]) if target_weights else 1.0
        target_frac = max(0.0, min(1.0, target_frac))  # clamp to [0, 1]

        # Get current position
        positions = self.cache.positions_open(instrument_id=self.instrument_id)
        current_position = positions[0] if positions else None
        current_qty = float(current_position.last_qty.as_decimal()) if current_position else 0.0
        current_value = current_qty * self._last_close()

        current_frac = current_value / portfolio_value if portfolio_value > 0 else 0.0
        delta_frac = target_frac - current_frac

        if abs(delta_frac) < self.rebalance_threshold:
            self.log.debug(f"No rebalance needed: delta={delta_frac:.3f} < threshold={self.rebalance_threshold}")
            return

        # Target value in dollars
        target_value = portfolio_value * target_frac
        delta_value = target_value - current_value

        if abs(delta_value) < portfolio_value * 0.001:  # skip < 0.1% moves
            return

        side = OrderSide.BUY if delta_value > 0 else OrderSide.SELL
        price = self._last_close()
        if price <= 0:
            return

        qty = abs(delta_value) / price
        max_qty = portfolio_value * self.max_position_pct / price
        qty = min(qty, max_qty)

        if qty < 1e-6:
            return

        order = self.order_factory.market(
            instrument_id=self.instrument_id,
            order_side=side,
            quantity=Quantity.from_float(qty),
        )
        self.submit_order(order)
        self.log.info(
            f"{'BUY' if side == OrderSide.BUY else 'SELL'} {qty:.2f} shares "
            f"@ ~${price:.2f} (target frac: {target_frac:.2%}, delta: {delta_frac:+.2%})"
        )

    def _last_close(self) -> float:
        """Get last close price from cache or 0."""
        bar = self.cache.bar(self.bar_type, instrument_id=self.instrument_id)
        return bar.close.as_double() if bar else 0.0