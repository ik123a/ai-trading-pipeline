"""
Phase 3 — Python PPO microservice exposing /predict_weights over HTTP.

Exposes the inference interface contract between the trained PPO model
and the NautilusTrader execution engine.

DESIGN: this is a *real* HTTP microservice with a deterministic placeholder
PPO engine that produces weight vectors from a market feature snapshot.
To swap in a real FinRL-X trained model later, set PPO_MODEL_PATH to point
at ppo_stock_trader.zip — the model loader is already wired.

Includes latency tracking, request validation, request logging,
and a /health endpoint for orchestrators.
"""

import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, conlist

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
PPO_MODEL_PATH = os.getenv("PPO_MODEL_PATH", "")
PPO_MODEL_TYPE = os.getenv("PPO_MODEL_TYPE", "deterministic_placeholder")  # or "sb3_ppo"
LOG_DIR = Path(os.getenv("PPO_LOG_DIR", "logs/ppo-microservice"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LATENCY_BUDGET_MS = int(os.getenv("PPO_LATENCY_BUDGET_MS", "200"))
PORT = int(os.getenv("PPO_PORT", "8001"))
INFERENCE_LOG = LOG_DIR / "inference_log.jsonl"
LATENCY_LOG = LOG_DIR / "latency_log.jsonl"

# -----------------------------------------------------------------------------
# PPO Engine (placeholder; SB3 loader is implemented and ready behind a flag)
# -----------------------------------------------------------------------------
class PPOEngine:
    """
    Produces a portfolio weight vector given a market feature snapshot.

    Contract for /predict_weights input (see PPORequest / PPOFeatureVector below):
        - features: list of float with shape (window, n_features)
        - ticker: symbol string
        - episode_id: client-provided UUID for tracing
    Output (PPOResponse):
        - weights: list of n_tickers floats summing to ≤1.0
        - latency_ms: server-side inference latency
        - model_id: which model served this request

    To plug in a real FinRL-X SB3 model:
        1. Set PPO_MODEL_TYPE=sb3_ppo
        2. Set PPO_MODEL_PATH=/path/to/ppo_stock_trader.zip
        3. Ensure the model was trained with the same feature order and length.
    """

    def __init__(self):
        self.model_id = f"{PPO_MODEL_TYPE}@{getattr(__import__('socket').gethostname(), '__str__', lambda: 'localhost')()}-{PORT}"
        self.realtime = None
        self.cache = {}

    def _warmup(self):
        """Optional warmup — pre-allocate caches, compare expected obs shape, etc."""
        pass

    def predict(self, features: List[List[float]], n_tickers: int) -> List[float]:
        """
        Compute weight vector for `n_tickers` assets from features (window x n_feats).
        This is the deterministic PLACEHOLDER — to be replaced by SB3 model.predict().
        """
        if n_tickers <= 0:
            return [0.0]
        arr = np.asarray(features, dtype=np.float64)
        if arr.size == 0:
            return [1.0 / n_tickers] * n_tickers
        # Mean-reverting / contrarian toy: bias weights by inverse momentum
        # (the last feature column is treated as momentum proxy; configurable later)
        last_window = arr[-10:].mean(axis=0) if arr.shape[0] >= 1 else arr.flatten()
        if last_window.size < n_tickers:
            last_window = np.pad(last_window, (0, n_tickers - last_window.size), mode="constant")
        # Score: inverse of momentum (negative Sharpe -> positive weight)
        score = -last_window[:n_tickers]
        # softmax with temperature
        score = (score - score.mean()) / (score.std() + 1e-9)
        score = np.exp(score * 2.0)
        weights = score / score.sum()
        # Force non-negative for cash account; weight 1st ticker if tiny history
        weights = np.maximum(weights, 0.0)
        if weights.sum() < 1e-6:
            weights = np.zeros(n_tickers)
            weights[0] = 1.0
        else:
            weights = weights / weights.sum()
        return [float(w) for w in weights]


class SB3Engine(PPOEngine):
    """Real Stable-Baselines3 PPO engine — used when PPO_MODEL_TYPE=sb3_ppo."""
    def __init__(self, model_path: str):
        super().__init__()
        try:
            from stable_baselines3 import PPO
            self.model = PPO.load(model_path)
            self.model_id = f"sb3_ppo@{Path(model_path).stem}"
        except ImportError:
            raise RuntimeError(
                "stable_baselines3 not installed. Install with: pip install stable-baselines3"
            )

    def predict(self, features: List[List[float]], n_tickers: int) -> List[float]:
        arr = np.asarray(features, dtype=np.float32)
        action, _ = self.model.predict(arr, deterministic=True)
        w = np.asarray(action).flatten()[:n_tickers].astype(np.float64)
        w = np.maximum(w, 0.0)
        if w.sum() > 0:
            w = w / w.sum()
        else:
            w = np.zeros(n_tickers)
            w[0] = 1.0
        return [float(x) for x in w]


# -----------------------------------------------------------------------------
# Resolve engine from env
# -----------------------------------------------------------------------------
if PPO_MODEL_TYPE == "sb3_ppo" and PPO_MODEL_PATH:
    try:
        ENGINE = SB3Engine(PPO_MODEL_PATH)
    except Exception as e:
        print(f"[PPO] Failed to load SB3 model: {e}. Falling back to deterministic placeholder.")
        ENGINE = PPOEngine()
else:
    ENGINE = PPOEngine()

ENGINE._warmup()

# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------
class PPOFeatureVector(BaseModel):
    features: List[List[float]] = Field(..., description="window x n_features")
    n_tickers: int = Field(..., ge=1, le=50)
    ticker: str = Field(..., description="primary symbol")
    episode_id: Optional[str] = Field(None, description="client UUID for tracing")

    class Config:
        schema_extra = {
            "example": {
                "features": [[0.01, 0.02, 0.03], [0.015, 0.025, 0.04]],
                "n_tickers": 5,
                "ticker": "AAPL",
                "episode_id": "abc-123",
            }
        }


class PPOResponse(BaseModel):
    weights: List[float] = Field(..., description="portfolio target weights summing to ≤1.0")
    latency_ms: float
    model_id: str
    episode_id: Optional[str]
    server_ts: str

# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = FastAPI(title="PPO Microservice", version="0.1.0")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model_id": ENGINE.model_id,
        "model_type": PPO_MODEL_TYPE,
        "latency_budget_ms": LATENCY_BUDGET_MS,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/predict_weights", response_model=PPOResponse)
async def predict_weights(req: PPOFeatureVector):
    t0 = time.perf_counter()
    try:
        weights = ENGINE.predict(req.features, req.n_tickers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inference failed: {e}")
    latency_ms = (time.perf_counter() - t0) * 1000.0
    response = PPOResponse(
        weights=weights,
        latency_ms=latency_ms,
        model_id=ENGINE.model_id,
        episode_id=req.episode_id,
        server_ts=datetime.now(timezone.utc).isoformat(),
    )
    # Append to logs
    record = {
        "server_ts": response.server_ts,
        "request": req.dict(),
        "response": response.dict(),
    }
    lat_record = {
        "server_ts": response.server_ts,
        "latency_ms": latency_ms,
        "episode_id": req.episode_id,
        "ticker": req.ticker,
        "n_tickers": req.n_tickers,
        "model_id": ENGINE.model_id,
        "within_budget": latency_ms <= LATENCY_BUDGET_MS,
    }
    try:
        with INFERENCE_LOG.open("a") as f:
            f.write(json.dumps(record) + "\n")
        with LATENCY_LOG.open("a") as f:
            f.write(json.dumps(lat_record) + "\n")
    except OSError:
        pass

    if latency_ms > LATENCY_BUDGET_MS:
        return JSONResponse(
            status_code=200,
            content={
                **response.dict(),
                "warning": f"Latency {latency_ms:.1f}ms exceeded budget {LATENCY_BUDGET_MS}ms",
            },
        )
    return response


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    rid = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = rid
    response = await call_next(request)
    response.headers["x-request-id"] = rid
    return response


if __name__ == "__main__":
    import uvicorn
    print(f"[PPO] starting on :{PORT} with model_id={ENGINE.model_id}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
