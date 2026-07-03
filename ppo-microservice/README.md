# PPO Weights Microservice

FastAPI microservice that generates portfolio allocation weights based on a PPO (Proximal Policy Optimization) agent's predictions.

## Endpoints

### `GET /health`
Returns service health status.

**Response:**
```json
{
  "status": "healthy",
  "service": "ppo-weights",
  "version": "1.0.0"
}
```

### `POST /predict_weights`
Generates portfolio allocation weights from PPO agent predictions.

**Request Body:**
```json
{
  "market_features": [0.1, -0.05, 0.2, 0.15, -0.1],
  "portfolio_value": 100000.0,
  "risk_tolerance": "moderate"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `market_features` | List[float] | Yes | Normalized market feature vector (min 5 elements) |
| `portfolio_value` | float | Yes | Current portfolio value in USD (must be > 0) |
| `risk_tolerance` | string | No | `conservative`, `moderate`, or `aggressive` (default: `moderate`) |

**Response:**
```json
{
  "weights": {
    "equities": 0.42,
    "bonds": 0.25,
    "commodities": 0.08,
    "cash": 0.15,
    "alternatives": 0.10
  },
  "confidence": 0.85,
  "agent_id": "ppo-agent-v1",
  "portfolio_value": 100000.0
}
```

## Setup

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

The service starts on `http://0.0.0.0:8000`.

## Test

```bash
python test_client.py
```

Or with pytest:
```bash
pytest test_client.py -v
```