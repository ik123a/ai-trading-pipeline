import requests

API_KEY = "***"
API_SECRET = "***"
BASE_URL = "https://paper-api.alpaca.markets"

headers = {
    "APCA-API-KEY-ID": API_KEY,
    "APCA-API-SECRET-KEY": API_SECRET
}

print("=" * 50)
print("ALPACA PAPER TRADING TEST")
print("=" * 50)

# Check account
r = requests.get(f"{BASE_URL}/v2/account", headers=headers, timeout=10)
print(f"Account: {r.status_code}")
if r.status_code == 200:
    d = r.json()
    print(f"  Cash: ${float(d['cash']):,.2f}")
    print(f"  Portfolio: ${float(d['portfolio_value']):,.2f}")

# Submit order
order = {"symbol": "AAPL", "qty": "1", "side": "buy", "type": "market", "time_in_force": "day"}
r = requests.post(f"{BASE_URL}/v2/orders", headers={**headers, "Content-Type": "application/json"}, json=order, timeout=10)
print(f"Order: {r.status_code}")
if r.status_code in [200, 201]:
    d = r.json()
    print(f"  ID: {d.get('id')}")
    print(f"  Status: {d.get('status')}")

# Check positions
r = requests.get(f"{BASE_URL}/v2/positions", headers=headers, timeout=10)
print(f"Positions: {r.status_code}")
if r.status_code == 200:
    positions = r.json()
    print(f"  Count: {len(positions)}")
    for p in positions:
        print(f"  - {p['symbol']}: {p['qty']} shares")

print("=" * 50)
