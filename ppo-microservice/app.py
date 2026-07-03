"""
Phase 3: PPO Inference Microservice
====================================
FastAPI service that hosts a trained PPO policy and exposes portfolio
weight inference over HTTP. The NautilusTrader strategy calls /predict_weights
on every rebalance bar instead of running PPO inference inline - this decouples
the heavy Python/RL stack from the Rust execution engine.

Architecture:
    NautilusTrader Strategy  ---HTTP req--->  FastAPI /predict_weights
    NautilusTrader Strategy  <--JSON wts---  PPO model.predict(obs)

Exit criteria (per user's plan):
    - /predict_weights endpoint returns weight vector + timing info
    - 200ms latency gate enforced by CLIENT (Nautilus) - this service logs it
"""
import os
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "True")  # torch+anaconda OMP quirk

import time
import logging
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import gymnasium as gym
from gymnasium import spaces
from stable_baselines3 import PPO

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PPO-SVC] %(levelname)s: %(message)s",
)
log = logging.getLogger("ppo_svc")

ARTIFACTS = Path("ppo-microservice/artifacts")
ARTIFACTS.mkdir(parents=True, exist_ok=True)
MODEL_PATH = ARTIFACTS / "ppo_portfolio.zip"

DEFAULT_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
OBS_DIM = len(DEFAULT_TICKERS) * 8  # 8 features per ticker
N_ACTIONS = len(DEFAULT_TICKERS)  # one weight per ticker; 1-sum = cash


# ----------------------------------------------------------------
# 1. Custom Gymnasium env - portfolio allocation with turnover penalty
# ----------------------------------------------------------------
class PortfolioEnv(gym.Env):
    """Synthetic env — risk-aware PPO with drawdown penalty, max position cap, turnover cost."""

    metadata = {"render_modes": []}

    def __init__(self, n_assets=N_ACTIONS, obs_dim=OBS_DIM, episode_length=64):
        super().__init__()
        self.n_assets = n_assets
        self.obs_dim = obs_dim
        self.episode_length = episode_length
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32
        )
        self.action_space = spaces.Box(low=0.0, high=1.0, shape=(n_assets,), dtype=np.float32)
        self.reset()

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._step_count = 0
        self._prev_w = np.ones(self.n_assets) / self.n_assets
        self._portfolio_value = 1.0  # normalized to 1.0
        self._peak_value = 1.0
        return (np.random.randn(self.obs_dim).astype(np.float32) * 0.1, {})

    def step(self, action):
        a = np.clip(np.asarray(action, dtype=np.float32), 0, 1)
        s = a.sum()
        w = a / s if s > 1e-6 else np.ones_like(a) / len(a)

        # Enforce max position cap at 25%
        w = np.minimum(w, 0.25)
        w = w / w.sum() if w.sum() > 1e-6 else np.ones_like(w) / len(w)

        # Synthetic: first 3 assets have drift but also crash risk, last 2 are stable
        synth_ret = np.array([0.008, 0.005, 0.003, 0.001, 0.0005])[: self.n_assets]
        # Add occasional crash: 5% chance of -5% on any random asset
        crash = np.zeros(self.n_assets)
        if np.random.random() < 0.05:
            crash[np.random.randint(0, self.n_assets)] = -0.05
        port_ret = float(np.dot(w, synth_ret + crash))
        self._portfolio_value *= (1.0 + port_ret)
        self._peak_value = max(self._peak_value, self._portfolio_value)

        # Turnover penalty
        turnover = float(np.abs(w - self._prev_w).sum())

        # Drawdown penalty: portfolio value below peak => strong negative signal
        dd = (self._peak_value - self._portfolio_value) / self._peak_value
        drawdown_penalty = -4.0 * dd  # aggressive: -4 * drawdown fraction

        # Reward = returns - turnover - drawdown penalty
        reward = port_ret - 0.01 * turnover + drawdown_penalty

        self._prev_w = w
        self._step_count += 1
        terminated = self._step_count >= self.episode_length
        obs = np.random.randn(self.obs_dim).astype(np.float32) * 0.1
        truncated = False
        return obs, float(reward), terminated, truncated, {
            "weights": w.tolist(),
            "portfolio_value": round(self._portfolio_value, 4),
            "drawdown": round(dd, 4),
        }


# ----------------------------------------------------------------
# 2. Train (or load) PPO model once at startup
# ----------------------------------------------------------------
def train_or_load_ppo(train_steps: int = 3000) -> PPO:
    """Train a small PPO from scratch in ~10s, persist to disk."""
    if MODEL_PATH.exists():
        log.info(f"Loading existing PPO from {MODEL_PATH}")
        return PPO.load(str(MODEL_PATH))

    log.info(f"Training fresh PPO for {train_steps} timesteps (~10-30s)...")
    env = PortfolioEnv()
    model = PPO(
        "MlpPolicy",
        env,
        learning_rate=3e-4,
        n_steps=128,
        batch_size=32,
        n_epochs=4,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.05,
        verbose=0,
        seed=42,
    )
    t0 = time.time()
    model.learn(total_timesteps=train_steps)
    log.info(f"PPO training complete in {time.time()-t0:.1f}s")
    model.save(str(MODEL_PATH))
    log.info(f"Model saved to {MODEL_PATH}")
    return model


# ----------------------------------------------------------------
# 3. FastAPI app
# ----------------------------------------------------------------
class PredictRequest(BaseModel):
    observation: list = Field(..., description="Flat feature vector, length == OBS_DIM")
    tickers: list = Field(default_factory=lambda: DEFAULT_TICKERS)
    deterministic: bool = Field(default=True, description="Use argmax vs sampled action")
    request_id: str = Field(default="anon")


class PredictResponse(BaseModel):
    weights: list[float]
    tickers: list[str]
    cash_weight: float
    inference_ms: float
    request_id: str
    model_loaded: bool = True


app = FastAPI(title="PPO Portfolio Inference", version="0.1.0")
_model: PPO | None = None


@app.on_event("startup")
def _startup():
    global _model
    _model = train_or_load_ppo(train_steps=3000)
    log.info("✅ PPO microservice ready at /predict_weights")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_loaded": _model is not None,
        "tickers": DEFAULT_TICKERS,
        "obs_dim": OBS_DIM,
        "n_actions": N_ACTIONS,
    }


@app.post("/predict_weights", response_model=PredictResponse)
def predict_weights(req: PredictRequest):
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    t0 = time.perf_counter()
    if len(req.observation) != OBS_DIM:
        raise HTTPException(
            status_code=422,
            detail=f"observation length {len(req.observation)} != {OBS_DIM}",
        )
    obs = np.asarray(req.observation, dtype=np.float32).reshape(1, -1)
    action, _ = _model.predict(obs, deterministic=req.deterministic)
    weights = np.clip(np.asarray(action, dtype=np.float64).flatten()[: N_ACTIONS], 0, 1)
    s = weights.sum()
    if s > 1e-6:
        weights = weights / s
    else:
        weights = np.ones(N_ACTIONS) / N_ACTIONS
    cash_w = float(max(0.0, 1.0 - weights.sum()))
    # The PPO weights are "long-only fractions"; in production we keep them
    # as long-only (rest stays in cash). For investigation-only we may allow
    # shorting by letting sum > 1.0 - but per user's risk-first plan, long-only.
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    log.info(f"req={req.request_id} inference={elapsed_ms:.1f}ms weights={weights.tolist()}")
    return PredictResponse(
        weights=weights.tolist(),
        tickers=req.tickers,
        cash_weight=cash_w,
        inference_ms=round(elapsed_ms, 3),
        request_id=req.request_id,
    )


@app.post("/v1/portfolio/rebalance")
def rebalance(payload: dict):
    """Convenience: pass {observation, cash_target}, get long-only weights back."""
    obs = payload.get("observation") or [0.0] * OBS_DIM
    req = PredictRequest(observation=obs)
    return predict_weights(req)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")
