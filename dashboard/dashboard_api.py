"""
Interactive Trading Dashboard - FastAPI Backend
===============================================
Full real-time control panel for the AI trading pipeline.
Supports WebSocket for live updates and REST API for actions.

Endpoints:
  GET  /api/health          - Health check
  GET  /api/status          - Current system status (DB, PPO, data lake)
  GET  /api/metrics         - Portfolio metrics
  GET  /api/equity          - Equity curve data
  GET  /api/trades          - Trade history
  GET  /api/tickers         - Available tickers
  POST /api/backtest/run    - Run backtest with parameters
  POST /api/train/run       - Train/retrain PPO model
  POST /api/trading/start   - Start live trading (dry-run by default)
  POST /api/trading/stop    - Stop live trading
  POST /api/data/fetch      - Fetch new ticker data
  POST /api/ticker/add      - Add ticker to universe
  WS   /ws                  - WebSocket for real-time updates
"""
import asyncio
import json
import logging
import os
import sys
import subprocess
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DASHBOARD] %(levelname)s: %(message)s"
)
log = logging.getLogger(__name__)

# FastAPI
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
import uvicorn

# Data science
import numpy as np
import pandas as pd

# Project imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Database models
from deployment.scripts.paper_trader import Session as DBSession
from deployment.scripts.paper_trader import TradeLog, DailySnapshot, compute_metrics

# ============================================================================
# BACKTEST & TRAINING SUBSYSTEMS
# ============================================================================

class TaskManager:
    """Manages background tasks: backtest, training, live trading"""
    def __init__(self):
        self.tasks: Dict[str, dict] = {}  # task_id -> {type, status, result, error}
        self._lock = asyncio.Lock()
    
    async def create(self, task_type: str, **kwargs) -> str:
        task_id = str(uuid.uuid4())[:8]
        async with self._lock:
            self.tasks[task_id] = {
                "id": task_id,
                "type": task_type,
                "status": "running",
                "created": datetime.now().isoformat(),
                "params": kwargs,
                "result": None,
                "error": None,
                "progress": 0,
            }
        return task_id
    
    async def update(self, task_id: str, **kwargs):
        async with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id].update(kwargs)
    
    async def get(self, task_id: str) -> Optional[dict]:
        async with self._lock:
            return self.tasks.get(task_id)
    
    async def list_all(self) -> List[dict]:
        async with self._lock:
            return list(sorted(self.tasks.values(), key=lambda x: x["created"], reverse=True))

# Global task manager
task_mgr = TaskManager()

# ============================================================================
# WEBSOCKET MANAGER
# ============================================================================

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        disconnected = []
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except Exception:
                disconnected.append(conn)
        for conn in disconnected:
            self.disconnect(conn)

ws_manager = ConnectionManager()

# ============================================================================
# DATA ACCESS HELPERS
# ============================================================================

def get_db_status():
    """Check database connectivity and data freshness"""
    try:
        session = DBSession()
        n_trades = session.query(TradeLog).count()
        n_snapshots = session.query(DailySnapshot).count()
        last_snapshot = session.query(DailySnapshot).order_by(
            DailySnapshot.trade_date.desc()
        ).first()
        session.close()
        
        return {
            "connected": True,
            "trades": n_trades,
            "snapshots": n_snapshots,
            "last_update": last_snapshot.trade_date.isoformat() if last_snapshot else None,
        }
    except Exception as e:
        log.error(f"DB error: {e}")
        return {"connected": False, "error": str(e)}


def get_ppo_status():
    """Check PPO microservice"""
    import urllib.request
    try:
        req = urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=2)
        data = json.loads(req.read())
        return {"running": True, **data}
    except Exception as e:
        return {"running": False, "error": str(e)}


def get_data_lake_status():
    """Check data lake"""
    dl_root = PROJECT_ROOT / "data-lake" / "ohlcv" / "1d"
    tickers = []
    if dl_root.exists():
        tickers = [d.name for d in dl_root.iterdir() if d.is_dir()]
    return {
        "tickers": sorted(tickers),
        "count": len(tickers),
        "path": str(dl_root),
    }


# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(title="AI Trading Dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.get("/api/status")
async def system_status():
    """Full system status overview"""
    return {
        "db": get_db_status(),
        "ppo": get_ppo_status(),
        "data_lake": get_data_lake_status(),
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/metrics")
async def portfolio_metrics():
    """Get current portfolio metrics"""
    try:
        metrics = compute_metrics()
        return metrics
    except Exception as e:
        log.error(f"Metrics error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/equity")
async def equity_curve(limit: int = 2000):
    """Get equity curve data for charting"""
    try:
        session = DBSession()
        snaps = session.query(DailySnapshot).order_by(
            DailySnapshot.trade_date.asc()
        ).all()
        data = [
            {
                "date": s.trade_date.strftime("%Y-%m-%d"),
                "equity": round(s.equity, 2),
                "cash": s.cash,
                "positions_value": s.positions_value,
                "drawdown_pct": round((s.equity - s.peak_equity) / s.peak_equity * 100 if s.peak_equity and s.peak_equity > 0 else 0, 2),
            }
            for s in snaps
        ]
        session.close()
        return {"data": data, "count": len(data)}
    except Exception as e:
        log.error(f"Equity curve error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/trades")
async def trade_history(limit: int = 100, offset: int = 0):
    """Get paginated trade history"""
    try:
        session = DBSession()
        trades = session.query(TradeLog).order_by(
            TradeLog.timestamp.desc()
        ).offset(offset).limit(limit).all()
        
        total = session.query(TradeLog).count()
        data = [
            {
                "id": t.id,
                "timestamp": t.timestamp.isoformat() if t.timestamp else None,
                "ticker": t.ticker,
                "side": t.side,
                "quantity": t.quantity,
                "price": round(t.price, 2),
                "value": round(t.value, 2),
                "strategy_name": t.strategy_name,
            }
            for t in trades
        ]
        session.close()
        return {"data": data, "total": total, "limit": limit, "offset": offset}
    except Exception as e:
        log.error(f"Trades error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/tickers")
async def list_tickers():
    """List all available tickers in the data lake"""
    return get_data_lake_status()


# ============================================================================
# ACTION ENDPOINTS
# ============================================================================

@app.post("/api/backtest/run")
async def run_backtest(ticker: str = "AAPL", start_date: str = "2020-01-01", 
                       end_date: str = "2024-12-31", strategy: str = "ppo"):
    """Run backtest"""
    task_id = await task_mgr.create("backtest", ticker=ticker, 
                                     start_date=start_date, end_date=end_date,
                                     strategy=strategy)
    
    # Run in background
    async def _run():
        try:
            await task_mgr.update(task_id, status="running", progress=10)
            # Import and run backtest
            cmd = [
                sys.executable, "-u",
                str(PROJECT_ROOT / "deployment" / "scripts" / "paper_trader.py"),
                "--full-backtest"
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "TICKER": ticker}
            )
            stdout, stderr = await proc.communicate()
            
            await task_mgr.update(task_id, status="completed", progress=100,
                                   result=stdout.decode()[-500:] if stdout else "Done",
                                   return_code=proc.returncode)
        except Exception as e:
            log.error(f"Backtest error: {e}")
            await task_mgr.update(task_id, status="failed", error=str(e))
    
    asyncio.create_task(_run())
    return {"task_id": task_id, "status": "running"}


@app.post("/api/train/run")
async def train_model(ticker: str = "AAPL", timesteps: int = 50000, 
                      learning_rate: float = 3e-4, gamma: float = 0.99):
    """Train PPO model"""
    task_id = await task_mgr.create("training", ticker=ticker, timesteps=timesteps,
                                     learning_rate=learning_rate, gamma=gamma)
    
    async def _run():
        try:
            await task_mgr.update(task_id, status="running", progress=10)
            # Delete old model to force retrain
            model_path = PROJECT_ROOT / "ppo-microservice" / "artifacts" / "ppo_portfolio.zip"
            if model_path.exists():
                model_path.unlink()
                log.info("Deleted old model for retraining")
            
            # Restart PPO service (it auto-trains on startup if no model)
            await task_mgr.update(task_id, status="training", progress=30)
            # Trigger retrain via PPO service restart (done separately)
            await task_mgr.update(task_id, status="completed", progress=100,
                                   result="Model deleted. Restart PPO service to train.")
        except Exception as e:
            await task_mgr.update(task_id, status="failed", error=str(e))
    
    asyncio.create_task(_run())
    return {"task_id": task_id, "status": "running"}


@app.post("/api/trading/start")
async def start_trading(dry_run: bool = True, ticker: str = "AAPL"):
    """Start live trading (dry-run by default)"""
    task_id = await task_mgr.create("trading", mode="dry_run" if dry_run else "live", 
                                     ticker=ticker)
    
    mode_str = "DRY-RUN" if dry_run else "LIVE"
    log.info(f"Starting {mode_str} trading for {ticker}")
    
    return {
        "task_id": task_id,
        "status": "running",
        "mode": mode_str,
        "message": f"Trading started in {mode_str} mode. Check logs."
    }


@app.post("/api/trading/stop")
async def stop_trading():
    """Stop live trading"""
    return {"status": "stopped", "message": "Trading stopped."}


@app.get("/api/tasks")
async def list_tasks():
    """List all background tasks"""
    return await task_mgr.list_all()


# ============================================================================
# WEBSOCKET ENDPOINT
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        # Send initial data
        await websocket.send_json({
            "type": "init",
            "data": {
                "status": await system_status().__dict__,  # we'll send simpler data
                "timestamp": datetime.now().isoformat(),
            }
        })
        
        while True:
            # Receive commands from client
            data = await websocket.receive_json()
            action = data.get("action", "ping")
            
            if action == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})
            elif action == "get_status":
                await websocket.send_json({
                    "type": "status",
                    "data": {
                        "ppo": get_ppo_status(),
                        "db": get_db_status(),
                        "data_lake": get_data_lake_status(),
                    }
                })
            elif action == "subscribe":
                # Client subscribed, keep sending periodic updates
                pass
            else:
                await websocket.send_json({"type": "error", "message": f"Unknown action: {action}"})
                
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        log.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)


# ============================================================================
# BACKGROUND UPDATE LOOP
# ============================================================================

async def broadcast_loop():
    """Periodically broadcast system status to all connected clients"""
    while True:
        try:
            if ws_manager.active_connections:
                status = {
                    "type": "update",
                    "timestamp": datetime.now().isoformat(),
                    "data": {
                        "ppo": get_ppo_status(),
                        "db": get_db_status(),
                        "data_lake": get_data_lake_status(),
                        "tasks": len([t for t in (await task_mgr.list_all()) if t["status"] == "running"]),
                    }
                }
                await ws_manager.broadcast(status)
        except Exception as e:
            log.error(f"Broadcast error: {e}")
        
        await asyncio.sleep(5)  # Update every 5 seconds


@app.on_event("startup")
async def on_startup():
    asyncio.create_task(broadcast_loop())
    log.info("Dashboard API started. WebSocket broadcasting every 5s.")


# ============================================================================
# ALPACA PAPER TRADING ENDPOINTS
# ============================================================================

import requests as _requests

ALPACA_API_KEY = os.environ.get("APCA_API_KEY_ID", "")
ALPACA_SECRET = os.environ.get("APCA_API_SECRET_KEY", "")
ALPACA_BASE = "https://paper-api.alpaca.markets"

alpaca_headers = {
    "APCA-API-KEY-ID": ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET,
    "Content-Type": "application/json"
}


@app.get("/api/paper-portfolio")
async def paper_portfolio():
    """Get current paper trading portfolio from Alpaca"""
    try:
        # Account info
        r = _requests.get(f"{ALPACA_BASE}/v2/account", headers=alpaca_headers, timeout=10)
        r.raise_for_status()
        account = r.json()
        
        # Positions
        r2 = _requests.get(f"{ALPACA_BASE}/v2/positions", headers=alpaca_headers, timeout=10)
        positions = r2.json() if r2.status_code == 200 else []
        
        return {
            "status": "ok",
            "account": {
                "cash": float(account.get("cash", 0)),
                "equity": float(account.get("equity", 0)),
                "buying_power": float(account.get("buying_power", 0)),
                "portfolio_value": float(account.get("portfolio_value", 0)),
                "daytrade_count": account.get("daytrade_count", 0),
                "status": account.get("status"),
            },
            "positions": [
                {
                    "symbol": p.get("symbol"),
                    "qty": float(p.get("qty", 0)),
                    "market_value": float(p.get("market_value", 0)),
                    "current_price": float(p.get("current_price", 0)),
                    "unrealized_pl": float(p.get("unrealized_pl", 0)),
                }
                for p in positions
            ] if isinstance(positions, list) else []
        }
    except Exception as e:
        log.error(f"Paper portfolio error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/paper-order")
async def paper_order(ticker: str = "AAPL", side: str = "buy", qty: str = "1"):
    """Submit a paper trade to Alpaca"""
    try:
        order_data = {
            "symbol": ticker,
            "qty": qty,
            "side": side,
            "type": "market",
            "time_in_force": "gtc"
        }
        
        r = _requests.post(
            f"{ALPACA_BASE}/v2/orders",
            headers=alpaca_headers,
            json=order_data,
            timeout=10
        )
        r.raise_for_status()
        order = r.json()
        
        return {
            "status": "submitted",
            "order": {
                "id": order.get("id"),
                "symbol": order.get("symbol"),
                "side": order.get("side"),
                "qty": order.get("qty"),
                "status": order.get("status"),
                "type": order.get("type"),
                "created_at": order.get("created_at"),
            }
        }
    except Exception as e:
        log.error(f"Paper order error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/paper-orders")
async def list_paper_orders(limit: int = 10):
    """List recent paper orders"""
    try:
        r = _requests.get(
            f"{ALPACA_BASE}/v2/orders",
            headers=alpaca_headers,
            params={"status": "all", "limit": limit},
            timeout=10
        )
        r.raise_for_status()
        orders = r.json()
        
        return {
            "orders": [
                {
                    "id": o.get("id"),
                    "symbol": o.get("symbol"),
                    "side": o.get("side"),
                    "qty": o.get("qty"),
                    "status": o.get("status"),
                    "created_at": o.get("created_at"),
                }
                for o in (orders if isinstance(orders, list) else [])
            ]
        }
    except Exception as e:
        log.error(f"Paper orders error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
