FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install NautilusTrader + deps
RUN pip install --no-cache-dir \
    nautilus-trader pandas numpy requests sqlalchemy \
    prometheus-client pydantic 2>&1 | tail -3

# Copy project structure
COPY ppo-microservice      /app/ppo-microservice
COPY strategies            /app/strategies
COPY data-lake             /app/data-lake
COPY backtests             /app/backtests
COPY deployment/scripts    /app/deployment/scripts
COPY deployment/run_local.py /app/deployment/run_local.py 2>/dev/null || true
COPY deployment/paper_trades.db /app/deployment/paper_trades.db 2>/dev/null || true

# Initialize SQLite database on first build
RUN python -c "import sys; sys.path.insert(0, '/app'); from deployment.scripts.paper_trader import Base, engine_db; Base.metadata.create_all(engine_db)" 2>/dev/null || true

ENV PYTHONPATH=/app:/app/strategies:/app/data-lake:/app/deployment/scripts
ENV PPO_URL=http://ppo-service:8765/predict_weights
ENV CATCHUP=true
ENV INITIAL_CASH=100000
ENV TICKER=AAPL
ENV KMP_DUPLICATE_LIB_OK=TRUE

CMD ["python", "-u", "deployment/scripts/paper_trader.py", "--full-backtest"]