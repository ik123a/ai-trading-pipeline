#!/usr/bin/env python3
"""Generate production dashboard with all features"""
import sqlite3, json
from pathlib import Path

# Read DB
conn = sqlite3.connect(str(Path(__file__).parent / "deployment" / "paper_trades.db"))
c = conn.cursor()

c.execute("SELECT trade_date, equity FROM daily_snapshots ORDER BY trade_date")
snapshots = c.fetchall()

c.execute("SELECT timestamp, ticker, side, quantity, price, value FROM trades ORDER BY timestamp DESC")
trades = c.fetchall()

conn.close()

# Process data
chart_data = [(s[0][:7], s[1]) for s in snapshots[::10]]
chart_labels = [d[0] for d in chart_data]
chart_values = [d[1] for d in chart_data]

start_eq = 100000.0
end_eq = snapshots[-1][1] if snapshots else start_eq
ret_pct = round((end_eq - start_eq) / start_eq * 100, 2)

# Max drawdown
max_dd_val = 0.0
peak = start_eq
for date, eq in snapshots:
    if eq > peak:
        peak = eq
    dd = (eq - peak) / peak * 100
    if dd < max_dd_val:
        max_dd_val = dd

# Drawdown for chart
peak = start_eq
dd_values = []
for d in snapshots[::10]:
    if d[1] > peak:
        peak = d[1]
    dd_values.append(round((d[1] - peak) / peak * 100, 2))

# Unique trades
seen = set()
unique_trades = []
for t in trades:
    key = (t[0][:10] if t[0] else "", t[1], t[2], t[3])
    if key not in seen:
        seen.add(key)
        unique_trades.append(t)

# JSON data
chart_labels_json = json.dumps(chart_labels)
chart_values_json = json.dumps(chart_values)
dd_values_json = json.dumps(dd_values)

# HTML template
html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Trading Command Center</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,400;0,500;0,600;0,700;1,400&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root{{"bg":"#0b0c0e","bg2":"#0f1116","bg3":"#1a1d24","bg4":"#242830","bdr":"#2a2e38","txt":"#e2e5ea","muted":"#8b909d","faint":"#5a5f6a","acc":"#3b82f6","grn":"#22c55e","red":"#ef4444","gold":"#eab308"}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Inter',sans-serif;background:var(--bg);color:var(--txt);min-height:100vh}}
.app{{display:flex;height:100vh}}
.rail{{width:56px;background:var(--bg2);border-right:1px solid var(--bdr);display:flex;flex-direction:column;align-items:center;padding:12px 0;flex-shrink:0}}
.logo{{width:36px;height:36px;border-radius:10px;background:rgba(59,130,246,0.14);color:#3b82f6;display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:800;margin-bottom:20px}}
.nav-item{{width:40px;height:40px;border-radius:10px;display:flex;align-items:center;justify-content:center;margin:3px 0;cursor:pointer;transition:.15s;color:#8b909d;font-size:18px}}
.nav-item:hover{{background:var(--bg3);color:var(--txt)}}
.nav-item.active{{color:#3b82f6;background:rgba(59,130,246,0.14)}}
.sep{{width:24px;height:1px;background:var(--bdr);margin:10px 0}}
.nav-bot{{margin-top:auto}}
.main{{flex:1;display:flex;flex-direction:column;overflow:hidden}}
.header{{height:52px;background:var(--bg2);border-bottom:1px solid var(--bdr);display:flex;align-items:center;justify-content:space-between;padding:0 24px;flex-shrink:0}}
.hl,.hr{{display:flex;align-items:center;gap:12px}}
.ht{{font-size:14px;font-weight:700;letter-spacing:.2px}}
.hs{{font-size:12px;color:#8b909d;font-family:'JetBrains Mono',monospace;background:var(--bg3);padding:2px 8px;border-radius:4px}}
.pill{{display:flex;align-items:center;gap:6px;font-size:11px;padding:4px 12px;border-radius:20px;background:var(--bg3);border:1px solid var(--bdr);color:#8b909d;font-family:'JetBrains Mono',monospace}}
.pill .dot{{width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 6px #22c55e}}
.pill.warn .dot{{background:#eab308;box-shadow:0 0 6px #eab308}}
.content{{flex:1;overflow:auto;padding:24px}}
.grid{{display:grid;gap:16px}}.g4{grid-template-columns:repeat(4,1fr)}.g3{grid-template-columns:repeat(3,1fr)}.g2{grid-template-columns:repeat(2,1fr)}@media(max-width:1200px){.g4{grid-template-columns:repeat(2,1fr)}}@media(max-width:768px){.g2,.g3,.g4{grid-template-columns:1fr}}
.card{{background:var(--bg2);border:1px watches]);border-radius:12px;overflow:hidden;transition:.2s}}
