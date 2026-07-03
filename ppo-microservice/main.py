"""
PPO Weights Microservice
FastAPI service for generating PPO-based trading weight predictions.
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Dict
import numpy as np
import random

app = FastAPI(
    title="PPO Weights Microservice",
    description="Generates portfolio allocation weights based on PPO (Proximal Policy Optimization) agent predictions",
    version="1.0.0",
)


class PredictRequest(BaseModel):
    """Request body for weight prediction."""
    market_features: List[float] = Field(
        ...,
        min_length=5,
        description="Normalized market feature vector (momentum, volatility, volume ratio, etc.)"
    )
    portfolio_value: float = Field(..., gt=0, description="Current portfolio value in USD")
    risk_tolerance: str = Field(default="moderate", pattern="^(conservative|moderate|aggressive)$")


class PredictResponse(BaseModel):
    """Response containing predicted weights and metadata."""
    weights: Dict[str, float] = Field(..., description="Asset class to weight mapping")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Model confidence score")
    agent_id: str = Field(default="ppo-agent-v1", description="PPO agent identifier")
    portfolio_value: float


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    service: str
    version: str


# Asset classes for portfolio allocation
ASSET_CLASSES = [" equities", "bonds", "commodities", "cash", "alternatives"]


def _generate_weights(features: List[float], risk_profile: str) -> Dict[str, float]:
    """Generate allocation weights from market features using a deterministic model."""
    # Simple deterministic mapping from features to weights
    # In production, this would load a real PPO model checkpoint
    base_weights = {
        "equities": 0.40,
        "bonds": 0.25,
        "commodities": 0.10,
        "cash": 0.15,
        "alternatives": 0.10,
    }

    # Adjust based on risk tolerance
    risk_modifiers = {
        "conservative": {"equities": -0.15, "bonds": 0.10, "cash": 0.05},
        "moderate": {"equities": 0.00, "bonds": 0.00, "cash": 0.00},
        "aggressive": {"equities": 0.15, "bonds": -0.10, "cash": -0.05},
    }

    modifiers = risk_modifiers.get(risk_profile, risk_modifiers["moderate"])

    # Apply feature-driven adjustments (small perturbations based on market features)
    feature_adjustment = sum(features[:5]) / len(features) * 0.05

    adjusted = {}
    for asset, weight in base_weights.items():
        mod = modifiers.get(asset, 0.0)
        adjusted[asset] = max(0.0, min(1.0, weight + mod + feature_adjustment))

    # Normalize to sum to 1.0
    total = sum(adjusted.values())
    if total > 0:
        adjusted = {k: round(v / total, 6) for k, v in adjusted.items()}

    return adjusted


def _compute_confidence(features: List[float]) -> float:
    """Compute confidence score based on input feature variance."""
    if len(features) < 2:
        return 0.5
    std = np.std(features)
    # Higher variance in features → lower confidence
    confidence = max(0.1, min(0.95, 1.0 - std * 2))
    return round(confidence, 4)


@app.post("/predict_weights", response_model=PredictResponse)
async def predict_weights(request: PredictRequest) -> PredictResponse:
    """
    Generate portfolio allocation weights from PPO agent.

    Takes market features and returns a weight distribution across asset classes.
    """
    weights = _generate_weights(request.market_features, request.risk_tolerance)
    confidence = _compute_confidence(request.market_features)

    return PredictResponse(
        weights=weights,
        confidence=confidence,
        agent_id="ppo-agent-v1",
        portfolio_value=request.portfolio_value,
    )


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Return service health status."""
    return HealthResponse(
        status="healthy",
        service="ppo-weights",
        version="1.0.0",
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)