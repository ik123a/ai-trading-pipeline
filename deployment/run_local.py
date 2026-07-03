#!/usr/bin/env python3
"""
Phase 4 Local Runner (no Docker required)
==========================================
Launches the PPO microservice, paper trader, Prometheus metrics endpoint,
and HTML dashboard generator — all as local processes.

Usage:
    python deployment/run_local.py                    # Start all services
    python deployment/run_local.py --generate-dashboard  # Regenerate HTML dashboard
    python deployment/run_local.py --metrics          # Print computed metrics
    python deployment/run_local.py --paper-day 2025-01-02  # Single paper day
    python deployment/run_local.py --paper-catchup    # Run through all available data
"""
import argparse
import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_ROOT / "deployment" / "scripts"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ─── Service start helpers ──────────────────────────────────────

PIDS = []


def start_ppo_microservice():
    """Start the PPO inference FastAPI service on port 8765."""
    log_file = LOG_DIR / "ppo-service.log"
    env = os.environ.copy()
    env["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    proc = subprocess.Popen(
        [sys.executable, "-u", str(PROJECT_ROOT / "ppo-microservice" / "app.py")],
        stdout=open(log_file, "a"),
        stderr=subprocess.STDOUT,
        env=env,
        cwd=str(PROJECT_ROOT),
    )
    PIDS.append(("ppo-service", proc))
    print(f"✅ PPO microservice started (PID {proc.pid}), port 8765")
    print(f"   Log: {log_file}")
    return proc


def start_prometheus_exporter():
    """Start the Prometheus /metrics endpoint on port 8766."""
    log_file = LOG_DIR / "prometheus-exporter.log"
    with open(log_file, "a") as f:
        f.write(f"\n--- Prometheus exporter start at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    # Start a minimal /metrics server that reads paper_trader's SQLite
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", """
import sys, time, json
sys.path.insert(0, '.')
from pathlib import Path
PROJECT_ROOT = Path.cwd()
sys.path.insert(0, str(PROJECT_ROOT / 'deployment' / 'scripts'))
from prometheus_client import start_http_server, Gauge
import sqlite3
from datetime import datetime

PROMETHEUS_PORT = 8766
g_equity = Gauge('paper_equity', 'Paper equity', ['ticker'])
g_cash = Gauge('paper_cash', 'Paper cash')
g_positions = Gauge('paper_open_positions', 'Open positions')
g_trades = Gauge('paper_total_trades', 'Total trades')
g_sharpe = Gauge('paper_sharpe_ratio', 'Sharpe ratio')

DB = PROJECT_ROOT / 'deployment' / 'paper_trades.db'

start_http_server(PROMETHEUS_PORT)
print(f'Prometheus /metrics at :{PROMETHEUS_PORT}')

while True:
    try:
        if DB.exists():
            conn = sqlite3.connect(str(DB))
            c = conn.cursor()
            # Latest daily snapshot
            c.execute('SELECT equity FROM daily_snapshots ORDER BY trade_date DESC LIMIT 1')
            row = c.fetchone()
            if row:
                g_equity.labels(ticker='AAPL').set(row[0])
            # Total trades
            c.execute('SELECT COUNT(*) FROM trades')
            g_trades.set(c.fetchone()[0])
            conn.close()
    except Exception as e:
        print(f'prom error: {e}')
    time.sleep(15)
"""],
        stdout=open(log_file, "a"),
        stderr=subprocess.STDOUT,
        env=env,
        cwd=str(PROJECT_ROOT),
    )
    PIDS.append(("prometheus", proc))
    print(f"✅ Prometheus exporter started (PID {proc.pid}), port 8766")
    print(f"   Log: {log_file}")
    return proc


def start_dashboard_server():
    """Start a simple HTTP server for the HTML dashboard."""
    log_file = LOG_DIR / "dashboard-server.log"
    deploy_dir = PROJECT_ROOT / "deployment"
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", "8888"],
        stdout=open(log_file, "a"),
        stderr=subprocess.STDOUT,
        cwd=str(deploy_dir),
    )
    PIDS.append(("dashboard", proc))
    print(f"✅ Dashboard server started (PID {proc.pid}), http://127.0.0.1:8888/dashboard.html")
    return proc


def run_paper_catchup() -> bool:
    """Run paper trader in catchup mode (full backtest, single engine run)."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["SKIP_INCREMENTAL"] = "1"
    result = subprocess.run(
        [sys.executable, "-u", str(SCRIPTS / "paper_trader.py"), "--full-backtest"],
        capture_output=True, text=True, env=env, cwd=str(PROJECT_ROOT), timeout=600,
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[:500])
    return result.returncode == 0


def generate_dashboard():
    """Generate the HTML dashboard."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "generate_dashboard.py")],
        capture_output=True, text=True, env=env, cwd=str(PROJECT_ROOT), timeout=120,
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[:500])
    return result.returncode == 0


def print_metrics():
    """Print computed paper trading metrics."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "paper_trader.py"), "--metrics"],
        capture_output=True, text=True, env=env, cwd=str(PROJECT_ROOT), timeout=60,
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[:500])


def run_single_day(date_str: str):
    """Run one day of paper trading."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "paper_trader.py"), "--date", date_str],
        capture_output=True, text=True, env=env, cwd=str(PROJECT_ROOT), timeout=300,
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[:500])

    # Regenerate dashboard
    generate_dashboard()


def cleanup():
    """Kill all started background processes."""
    print("\n🛑 Stopping all services...")
    for name, proc in PIDS:
        try:
            proc.terminate()
            proc.wait(timeout=3)
            print(f"   {name} (PID {proc.pid}) stopped")
        except Exception:
            try:
                proc.kill()
                print(f"   {name} (PID {proc.pid}) killed")
            except Exception:
                print(f"   {name} (PID {proc.pid}) already exited")


# ─── Main ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Phase 4 Local Runner")
    parser.add_argument("--start", action="store_true", help="Start all local services")
    parser.add_argument("--paper-catchup", action="store_true", help="Run paper trader catchup")
    parser.add_argument("--paper-day", type=str, help="Run single paper day (YYYY-MM-DD)")
    parser.add_argument("--generate-dashboard", action="store_true", help="Regenerate HTML dashboard")
    parser.add_argument("--metrics", action="store_true", help="Print metrics from DB")
    parser.add_argument("--open", action="store_true", help="Open dashboard in browser")
    args = parser.parse_args()

    if args.start:
        print("=" * 60)
        print("PHASE 4 — Starting Local Services")
        print("=" * 60)
        start_ppo_microservice()
        start_prometheus_exporter()
        start_dashboard_server()
        print(f"\n📊 Dashboard:  http://127.0.0.1:8888/dashboard.html")
        print(f"📈 Prometheus: http://127.0.0.1:8766/metrics")
        print(f"🤖 PPO /health: http://127.0.0.1:8765/health")
        print(f"\nRun `python {Path(__file__).relative_to(PROJECT_ROOT)} --paper-catchup` to start trading")
        print(f"Press Ctrl+C to stop all services")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            cleanup()
        return

    if args.paper_catchup:
        print("=" * 60)
        print("PHASE 4 — Paper Catchup")
        print("=" * 60)
        success = run_paper_catchup()
        if success:
            generate_dashboard()
            print_metrics()
            print("\n✅ Catchup complete. Regenerated dashboard and metrics.")
        else:
            print("\n❌ Catchup failed. Check logs/paper_trader.log")
        return

    if args.paper_day:
        run_single_day(args.paper_day)
        return

    if args.generate_dashboard:
        generate_dashboard()
        return

    if args.metrics:
        print_metrics()
        return

    if args.open:
        import webbrowser
        dash = PROJECT_ROOT / "deployment" / "dashboard.html"
        if dash.exists():
            webbrowser.open(f"file://{dash.resolve()}")
            print(f"✅ Opened {dash}")
        else:
            print("⚠️  Dashboard not generated yet. Run --generate-dashboard first.")
        return

    parser.print_help()
    print("\nCommon workflows:")
    print("  Start services:    python deployment/run_local.py --start")
    print("  Run catchup:       python deployment/run_local.py --paper-catchup")
    print("  Generate dashboard: python deployment/run_local.py --generate-dashboard")
    print("  View metrics:      python deployment/run_local.py --metrics")


if __name__ == "__main__":
    main()