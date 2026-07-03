FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential && \
    rm -rf /var/lib/apt/lists/*

# Install PPO deps
RUN pip install --no-cache-dir \
    fastapi 'uvicorn[standard]' \
    stable-baselines3 numpy requests pydantic 2>&1 | tail -3

# Copy ONLY what's needed for the PPO service
COPY ppo-microservice/app.py      /app/app.py
COPY ppo-microservice/README.md   /app/README.md 2>/dev/null || true
COPY ppo-microservice/artifacts   /app/artifacts
RUN mkdir -p /app/ppo-microservice && ln -sf /app/artifacts /app/ppo-microservice/artifacts 2>/dev/null || true

# Ensure artifacts directory exists (model is downloaded from host or trained on startup)
RUN mkdir -p /app/ppo-microservice/artifacts

ENV KMP_DUPLICATE_LIB_OK=TRUE
ENV MODEL_TRAIN_STEPS=3000
ENV PYTHONPATH=/app
EXPOSE 8765

CMD ["python", "-u", "app.py"]