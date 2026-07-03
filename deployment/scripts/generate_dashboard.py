#!/usr/bin/env python3
"""
Phase 4: HTML Dashboard Generator
==================================
Reads the SQLite paper_trades.db and generates a live-updating HTML dashboard
with equity curve, trade log, and metrics summary. No Grafana needed.

Usage:
    python deployment/scripts/generate_dashboard.py          # Generate HTML
    python deployment/scripts/serve_dashboard.py             # Auto-refresh every 30s via HTTP
"""
import json
import sys
from datetime import datetime, date
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from deployment.scripts.paper_trader import compute_metrics, Session, DailySnapshot, TradeLog

OUTPUT = PROJECT_ROOT / "deployment" / "dashboard.html"


def generate_html():
    session = Session()
    trades = session.query(TradeLog).order_by(TradeLog.timestamp).all()
    snapshots = session.query(DailySnapshot).order_by(DailySnapshot.trade_date).all()
    session.close()

    metrics = compute_metrics()

    # Build equity curve JSON for Chart.js
    eq_dates = [s.trade_date.strftime("%Y-%m-%d") for s in snapshots]
    eq_values = [s.equity for s in snapshots]

    # Trade table rows
    trade_rows = ""
    for t in trades[-20:]:  # last 20 trades
        date_str = t.timestamp.strftime("%Y-%m-%d")
        trade_rows += f"""<tr class="{'bg-green-50' if t.side == 'BUY' else 'bg-red-50'}">
            <td class="px-3 py-1 text-sm">{date_str}</td>
            <td class="px-3 py-1 text-sm font-bold">{t.side}</td>
            <td class="px-3 py-1 text-sm">{t.quantity}</td>
            <td class="px-3 py-1 text-sm">${t.price:.2f}</td>
            <td class="px-3 py-1 text-sm">${t.value:,.0f}</td>
        </tr>"""

    last_snapshot = snapshots[-1] if snapshots else None

    start_eq = metrics.get("start_equity", 100000)
    end_eq = metrics.get("end_equity", 100000)
    ret_pct = metrics.get("total_return_pct", 0)
    sharpe = metrics.get("sharpe_ratio", 0)
    max_dd = metrics.get("max_drawdown_pct", 0)
    trading_days = metrics.get("trading_days", 0)
    total_trades = metrics.get("total_trades", 0)

    # Color coding
    ret_color = "text-green-600" if ret_pct >= 0 else "text-red-600"
    sharpe_color = "text-green-600" if sharpe >= 0.5 else "text-yellow-600" if sharpe >= 0 else "text-red-600"
    dd_color = "text-green-600" if max_dd >= -10 else "text-yellow-600" if max_dd >= -25 else "text-red-600"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Phase 4 — Paper Trading Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <meta http-equiv="refresh" content="30">
</head>
<body class="bg-gray-100 p-6">
    <div class="max-w-6xl mx-auto">
        <h1 class="text-3xl font-bold mb-2 text-gray-800">📊 AI Trading Pipeline — Paper Trading</h1>
        <p class="text-gray-500 mb-6">Last updated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | Auto-refreshes every 30s</p>

        <!-- KPI Cards -->
        <div class="grid grid-cols-4 gap-4 mb-6">
            <div class="bg-white rounded-lg shadow p-4">
                <div class="text-sm text-gray-500">Current Equity</div>
                <div class="text-2xl font-bold">${end_eq:,.0f}</div>
                <div class="text-xs text-gray-400">from ${start_eq:,.0f} initial</div>
            </div>
            <div class="bg-white rounded-lg shadow p-4">
                <div class="text-sm text-gray-500">Total Return</div>
                <div class="text-2xl font-bold {ret_color}">{ret_pct:+.2f}%</div>
            </div>
            <div class="bg-white rounded-lg shadow p-4">
                <div class="text-sm text-gray-500">Sharpe Ratio</div>
                <div class="text-2xl font-bold {sharpe_color}">{sharpe:.4f}</div>
            </div>
            <div class="bg-white rounded-lg shadow p-4">
                <div class="text-sm text-gray-500">Max Drawdown</div>
                <div class="text-2xl font-bold {dd_color}">{max_dd:.2f}%</div>
            </div>
        </div>

        <div class="grid grid-cols-4 gap-4 mb-6">
            <div class="bg-white rounded-lg shadow p-4">
                <div class="text-sm text-gray-500">Trading Days</div>
                <div class="text-xl font-bold">{trading_days}</div>
            </div>
            <div class="bg-white rounded-lg shadow p-4">
                <div class="text-sm text-gray-500">Total Trades</div>
                <div class="text-xl font-bold">{total_trades}</div>
            </div>
            <div class="bg-white rounded-lg shadow p-4">
                <div class="text-sm text-gray-500">30-Day Cooldown</div>
                <div class="text-xl font-bold">{min(trading_days, 30)} / 30</div>
                <div class="w-full bg-gray-200 rounded-full h-2 mt-1">
                    <div class="bg-blue-500 h-2 rounded-full" style="width: {min(trading_days/30*100, 100)}%"></div>
                </div>
            </div>
        </div>

        <!-- Equity Curve Chart -->
        <div class="bg-white rounded-lg shadow mb-6 p-4">
            <h2 class="text-lg font-semibold mb-3">📈 Equity Curve</h2>
            <canvas id="equityChart" height="80"></canvas>
        </div>

        <!-- Recent Trades -->
        <div class="bg-white rounded-lg shadow mb-6 p-4">
            <h2 class="text-lg font-semibold mb-3">📝 Recent Trades (last 20)</h2>
            {('<table class="w-full text-left"><thead><tr class="border-b">'
              '<th class="px-3 py-2 text-sm text-gray-500">Date</th>'
              '<th class="px-3 py-2 text-sm text-gray-500">Side</th>'
              '<th class="px-3 py-2 text-sm text-gray-500">Qty</th>'
              '<th class="px-3 py-2 text-sm text-gray-500">Price</th>'
              '<th class="px-3 py-2 text-sm text-gray-500">Value</th>'
              '</tr></thead><tbody>' + trade_rows + '</tbody></table>') if trade_rows else '<p class="text-gray-400">No trades yet.</p>'}
        </div>

        <!-- Exit Criteria Check -->
        <div class="bg-white rounded-lg shadow mb-6 p-4">
            <h2 class="text-lg font-semibold mb-3">✅ Phase 4 Exit Criteria</h2>
            <ul class="space-y-1">
                <li class="{'text-green-600' if trading_days >= 30 else 'text-yellow-600'}">
                    {'✅' if trading_days >= 30 else '⏳'} 30-day cooldown: {trading_days}/30
                </li>
                <li class="{'text-green-600' if sharpe > 0 else 'text-red-600'}">
                    {'✅' if sharpe > 0 else '❌'} Positive Sharpe: {sharpe:.4f}
                </li>
                <li class="{'text-green-600' if max_dd >= -30 else 'text-red-600'}">
                    {'✅' if max_dd >= -30 else '❌'} Max Drawdown within limits: {max_dd:.2f}%
                </li>
            </ul>
        </div>
    </div>

    <script>
    const ctx = document.getElementById('equityChart').getContext('2d');
    new Chart(ctx, {{
        type: 'line',
        data: {{
            labels: {json.dumps(eq_dates)},
            datasets: [{{
                label: 'Portfolio Equity ($)',
                data: {json.dumps(eq_values)},
                borderColor: 'rgb(59, 130, 246)',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                fill: true,
                tension: 0.2,
                pointRadius: 0,
            }}]
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                x: {{ grid: {{ display: false }} }},
                y: {{ beginAtZero: false, ticks: {{ callback: v => '$' + v.toLocaleString() }} }}
            }}
        }}
    }});
    </script>
</body>
</html>"""

    with open(OUTPUT, "w") as f:
        f.write(html)
    print(f"✅ Dashboard generated: {OUTPUT}")
    return OUTPUT


if __name__ == "__main__":
    generate_html()