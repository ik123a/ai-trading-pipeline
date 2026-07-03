"""
Test client for PPO Weights Microservice.
Tests both /predict_weights and /health endpoints.
"""

import httpx
import pytest
from typing import Dict


BASE_URL = "http://localhost:8000"


def test_health_endpoint():
    """Test the /health endpoint returns correct status."""
    response = httpx.get(f"{BASE_URL}/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "ppo-weights"
    assert data["version"] == "1.0.0"
    print(f"✓ /health returned: {data}")


def test_predict_weights_moderate():
    """Test weight prediction with moderate risk profile."""
    payload = {
        "market_features": [0.1, -0.05, 0.2, 0.15, -0.1],
        "portfolio_value": 100000.0,
        "risk_tolerance": "moderate",
    }
    response = httpx.post(f"{BASE_URL}/predict_weights", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "weights" in data
    assert "confidence" in data
    assert data["agent_id"] == "ppo-agent-v1"
    assert data["portfolio_value"] == 100000.0
    # Verify weights sum to ~1.0
    total = sum(data["weights"].values())
    assert 0.99 <= total <= 1.01, f"Weights sum to {total}, expected ~1.0"
    print(f"✓ /predict_weights (moderate) returned weights: {data['weights']}")


def test_predict_weights_conservative():
    """Test weight prediction with conservative risk profile."""
    payload = {
        "market_features": [0.05, -0.02, 0.1, 0.08, -0.05],
        "portfolio_value": 50000.0,
        "risk_tolerance": "conservative",
    }
    response = httpx.post(f"{BASE_URL}/predict_weights", json=payload)
    assert response.status_code == 200
    data = response.json()
    # Conservative should have higher bonds/cash allocation
    assert data["weights"]["bonds"] > 0.30, "Conservative should have higher bond weight"
    print(f"✓ /predict_weights (conservative) returned weights: {data['weights']}")


def test_predict_weights_aggressive():
    """Test weight prediction with aggressive risk profile."""
    payload = {
        "market_features": [0.3, -0.1, 0.5, 0.2, -0.15],
        "portfolio_value": 250000.0,
        "risk_tolerance": "aggressive",
    }
    response = httpx.post(f"{BASE_URL}/predict_weights", json=payload)
    assert response.status_code == 200
    data = response.json()
    # Aggressive should have higher equity allocation
    assert data["weights"]["equities"] > 0.50, "Aggressive should have higher equity weight"
    print(f"✓ /predict_weights (aggressive) returned weights: {data['weights']}")


def test_predict_weights_invalid_value():
    """Test that negative portfolio value is rejected."""
    payload = {
        "market_features": [0.1, -0.05, 0.2, 0.15, -0.1],
        "portfolio_value": -1000.0,
        "risk_tolerance": "moderate",
    }
    response = httpx.post(f"{BASE_URL}/predict_weights", json=payload)
    assert response.status_code == 422, "Negative portfolio_value should be rejected"


def test_predict_weights_too_few_features():
    """Test that fewer than 5 features is rejected."""
    payload = {
        "market_features": [0.1, 0.2],
        "portfolio_value": 100000.0,
        "risk_tolerance": "moderate",
    }
    response = httpx.post(f"{BASE_URL}/predict_weights", json=payload)
    assert response.status_code == 422, "Fewer than 5 features should be rejected"


if __name__ == "__main__":
    import sys
    print("Running PPO Microservice tests...\n")
    tests = [
        test_health_endpoint,
        test_predict_weights_moderate,
        test_predict_weights_conservative,
        test_predict_weights_aggressive,
        test_predict_weights_invalid_value,
        test_predict_weights_too_few_features,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__} FAILED: {e}")
            failed += 1
    print(f"\n{passed}/{passed+failed} tests passed")
    sys.exit(0 if failed == 0 else 1)