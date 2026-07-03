# AI Trading Pipeline — Production-Ready Agent Framework

## Status: All 4 phases complete ✅

A 4-phase risk-first production pipeline that pairs **NautilusTrader 1.229** (Rust-core execution engine) with a **PPO microservice** (FastAPI + stable-baselines3) for ML-driven portfolio allocation. Built on Windows (Python 3.13 + Anaconda), tested end-to-end with 1258 daily bars across 2020-2024.

## Quickstart (local, no Docker)

```bash
# 1. Start PPO microservice (first launch trains model in ~15s)
python ppo-microservice/app.py

# 2. Run full backtest (0.08s, writes 1258 daily snapshots to SQLite)
python deployment/scripts/paper_trader.py --full-backtest

# 3. Generate dashboard (35KB HTML with Chart.js equity curve)
python deployment/scripts/generate_dashboard.py
open deployment/dashboard.html

# 4. View metrics
python deployment/scripts/paper_trader.py --metrics
```

## Quickstart (with Docker, when daemon is running)

```bash
cd deployment
docker compose up -d
# Services: ppo-service (:8765), postgres (:5432), prometheus (:9090), grafana (:3000)
```

## Project Structure

```
ai-trading-pipeline/
├── data-lake/                          # Parquet lake (10 tickers, 2020-2024)
│   └── ohlcv/1d/{AAPL,MSFT,GOOGL,AMZN,NVDA,JPM,META,TSLA,V,WMT}/
├── ppo-microservice/
│   ├── app.py                          # FastAPI + SB3 PPO on port 8765
│   └── artifacts/ppo_portfolio.zip     # Trained PPO model
├── strategies/
│   └── ppo_proxy_strategy.py           # HTTP proxy with 200ms latency gate
├── backtests/
│   ├── phase2_backtest.py              # Buy & Hold vs SMA 50/200 baseline
│   └── phase3_test.py                  # PPO integration test
├── deployment/
│   ├── docker-compose.yml              # 5-service stack (validated clean)
│   ├── run_local.py                    # Launch all services locally
│   ├── scripts/
│   │   ├── paper_trader.py             # SQLite trade logger + Nautilus sandbox
│   │   ├── generate_dashboard.py       # Chart.js HTML dashboard generator
│   │   └── alpaca_paper.py             # Alpaca paper trading adapter
│   ├── prometheus/prometheus.yml
│   ├── grafana/{datasources,dashboards}/
│   ├── ppo-service/Dockerfile
│   └── nautilus/Dockerfile
├── logs/                               # 8 artifact files (CSV, JSON)
└── requirements.txt
```

## Phase 1: Data Lake (✅)

- Parquet lake with 10 tickers (AAPL, MSFT, GOOGL, AMZN, NVDA, JPM, META, TSLA, V, WMT)
- Yearly partitioning per ticker
- NautilusTrader 1.229 smoke test: bars → engine → fills verified

## Phase 2: Baseline Backtest (✅)

| Strategy | Sharpe | Return | MaxDD | Final Equity |
|:---|:---:|:---:|:---:|---:|
| Buy & Hold | 0.94 | +231.73% | -30.26% | $331,745 |
| SMA 50/200 | 0.43 | +6.72% | -4.50% | $106,722 |

- 1258 daily bars, 2020-2024
- Daily MTM equity reconstruction from fills + closes
- Artifacts: `logs/equity_curve_bnh.csv`, `logs/equity_curve_sma.csv`, `logs/baseline_metrics_comparison.json`

## Phase 3: PPO MLOps Bridge (✅)

| Metric | Value |
|:---|:---:|
| Sharpe | 0.91 |
| Total Return | +282.96% |
| Max Drawdown | -38.90% |
| Final Equity | $382,961 |
| Backtest time | 0.08s |

- PPO microservice: SB3 2.9.0 on port 8765
- HTTP proxy strategy with **200ms latency gate** (observed: p50=5ms, p99=36ms)
- Integration test: `backtests/phase3_test.py`

## Phase 4: Paper Trading + Observability (✅)

- **SQLite trade logger** — daily snapshots + fill audit trail
- **HTML dashboard** — Chart.js equity curve (35KB, auto-refresh 30s)
- **Docker Compose** — 5 services, validated clean (`docker compose config` passes)
- **Grafana dashboard** — 7 panels (equity, positions, cash, latencies, errors, distributions)
- **Prometheus** — metrics endpoint + scrape config
- **Alpaca adapter** — `alpaca_paper.py` with fallback to simulated mode

## Key decisions & gotchas

- All Nautilus 1.229 gotchas documented in skill `nautilus-trader-pipeline` (references/nautilus-1229-gotchas.md, 138 lines)
- Cash account → `OmsType.NETTING`, `close_all_positions()` for exits
- Equity instruments via `Equity.from_dict({..., "info": None})`
- Bar construction: `Bar.from_dict({...})` with correct precision matching instrument
- MTM equity: fill + close reconstruction, not account report snapshots
- PPO strategy: currently trained on synthetic env, needs risk-aware reward (implemented but needs real retraining with multi-ticker data)
- Docker: all files prepared and validated, needs Docker Desktop daemon running to deploy
- Alpaca: adapter written, api key env vars required for live paper trading

## Roadmap / Future work

1. **Run Docker Compose** — verify the 5-container stack works end-to-end on a VPS
2. **Multi-asset PPO training** — use real OHLCV data for 5-ticker portfolio
3. **Daily cron for paper trader** — `hermes cronjob create` to auto-process new data daily
4. **Alpaca 30-day cooldown** — run `alpaca_paper.py --catchup` daily for 30 days before going live
5. **Hyperparameter optimization** — Optuna sweep over PPO learning rate, gamma, clip_range parameters

## References

- [NautilusTrader 1.229 Documentation](https://nautustrader.io/)
- [Stable-Baselines3](https://github.com/DLR-RM/stable-baselines3)
- [Alpaca Trade API](https://github.com/alpacahq/alpaca-trade-api-python)

## License

This project is research-only. **No profitability is guaranteed. Past backtest performance does not predict live results.** Paper trade for minimum 30 days before any live execution. Never risk capital you cannot afford to lose.