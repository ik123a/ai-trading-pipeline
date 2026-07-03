#!/usr/bin/env python3
"""Generate full OpenAlice-style dark dashboard"""
import json, sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "deployment" / "paper_trades.db"
conn = sqlite3.connect(str(DB_PATH))

# Fetch data
snapshots = conn.execute("SELECT trade_date, equity FROM daily_snapshots ORDER BY trade_date").fetchall()
trades = conn.execute("SELECT timestamp, ticker, side, quantity, price, value FROM trades ORDER BY timestamp DESC").fetchall()
conn.close()

dates = [s[0][:7] for s in snapshots[::30]]
equity_vals = [s[1] for s in snapshots[::30]]
start_eq, end_eq = 100000.0, snapshots[-1][1]
ret_pct = round((end_eq - start_eq) / start_eq * 100, 2)

# Trade rows
trade_html = ""
for t in trades[:10]:
    date_str = t[0][:10] if t[0] else "N/A"
    side_cls = "buy" if t[2] == "BUY" else "sell"
    trade_html += f"<tr><td>{date_str}</td><td class='ticker'>{t[1]}</td><td class='{side_cls}'>{t[2]}</td><td>{t[3]}</td><td>${t[4]:.2f}</td><td>${t[5]:,.0f}</td></tr>"

# Output
print("Dashboard data loaded successfully")
print(f"Snapshots: {len(snapshots)}, Trades: {len(trades)}")
print(f"Equity: ${end_eq:,.0f} (+{ret_pct}%)")
