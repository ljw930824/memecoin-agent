import json, os, sys, urllib.request, ssl, time
from datetime import datetime, timezone, timedelta

DATA_DIR = os.path.join(os.path.expanduser("~"), ".qclaw", "workspace", "data")
LOG_FILE = os.path.join(DATA_DIR, "backtest-log.txt")
os.makedirs(DATA_DIR, exist_ok=True)

MIN_SM_ENTRIES = 2
MAX_SPREAD_PCT = 0.20  # Relaxed from 5% to 20% for backtest
CHASE_PUMP_PCT = 0.15
SCALP_THRESHOLD = 28

def score_signal(sig):
    score = 0
    smc = sig.get("smartMoneyCount", 0)
    if smc >= 8: score += 40
    elif smc >= 5: score += 25
    elif smc >= 3: score += 12
    elif smc >= MIN_SM_ENTRIES: score += 5
    else: return 0

    direction = sig.get("direction", "")
    if direction == "buy": score += 10
    elif direction == "sell": return 0

    sc = sig.get("signalCount", 0)
    if sc >= 15: score += 8
    elif sc >= 5: score += 3

    tags = sig.get("tokenTag", {}) or {}
    for cat, tag_list in tags.items():
        for t in (tag_list or []):
            tn = t.get("tagName", "")
            if tn == "Smart Money Add Holdings": score += 12
            elif tn == "Whale Buy": score += 15
            elif tn == "DEX Paid": score += 3
            elif tn == "Smart Money Reduce": score -= 18
            elif tn == "Whale Sell": return 0

    mc = float(sig.get("alertMarketCap", 0) or 0)
    if mc >= 1_000_000: score += 10
    elif mc >= 100_000: score += 5
    elif mc > 0: score -= 5
    else: return 0

    current_price = float(sig.get("currentPrice", 0) or 0)
    alert_price = float(sig.get("alertPrice", 0) or 0)
    if alert_price > 0 and current_price > 0:
        pump_pct = (current_price - alert_price) / alert_price
        if abs(pump_pct) > MAX_SPREAD_PCT: return 0
        if pump_pct < -0.10: score -= 15
        elif pump_pct < -0.05: score += 5
        elif pump_pct <= 0.03: score += 8
        elif pump_pct <= CHASE_PUMP_PCT: score += 3
        elif pump_pct <= 0.25: score -= 8
        else: return 0

    status = sig.get("status", "")
    if status == "active": score += 15
    elif status == "timeout":
        tf = sig.get("timeFrame", 0)
        if tf < 3600000: score += 5
        else: score -= 10
    elif status in ("exitRate", "outDecline"): return 0

    return max(0, min(100, score))

# Fetch signals
ssl_ctx = ssl.create_default_context()
url = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai"
headers = {"Content-Type": "application/json"}
all_sigs = []
for chain_id, chain_name in [("56", "BSC"), ("CT_501", "Solana")]:
    body = json.dumps({"smartSignalType":"","page":1,"pageSize":50,"chainId":chain_id}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as r:
            d = json.loads(r.read().decode("utf-8"))
            items = d.get("data", []) if isinstance(d.get("data"), list) else d.get("data", {}).get("data", [])
            for s in items:
                if isinstance(s, dict):
                    s["chain_name"] = chain_name
                    s["score"] = score_signal(s)
                    all_sigs.append(s)
    except Exception as e:
        print(f"  {chain_name}: FAILED - {e}")

now = datetime.now(timezone(timedelta(hours=8)))
qualified = sorted([s for s in all_sigs if s["score"] >= SCALP_THRESHOLD],
                   key=lambda s: s["score"], reverse=True)

print(f"Backtest {now.strftime('%Y-%m-%d %H:%M')} (spread relaxed to 20%)")
print(f"Total: {len(all_sigs)} | Qualified: {len(qualified)}")
print()
print(f"{'Ticker':<20} {'Chain':<8} {'Score':>5} {'SM':>3} {'Spread':>8} {'Status':<10}")
print("-" * 58)
for s in qualified[:15]:
    ticker = (s.get("ticker", "?") or "?")[:18]
    chain = s.get("chain_name", "?")
    score = s.get("score", 0)
    sm = s.get("smartMoneyCount", 0)
    status = s.get("status", "?")
    cp = float(s.get("currentPrice", 0) or 0)
    ap = float(s.get("alertPrice", 0) or 0)
    spread = f"{(cp-ap)/ap*100:.1f}%" if ap > 0 and cp > 0 else "?"
    print(f"{ticker:<20} {chain:<8} {score:>5} {sm:>3} {spread:>8} {status:<10}")

# Simulate
positions = []
bsc_bal = 28.53
sol_bal = 34.30
for s in qualified:
    if len(positions) >= 3: break
    chain = s.get("chain_name", "?")
    bal = bsc_bal if chain == "BSC" else sol_bal
    if bal < 5: continue
    cp = float(s.get("currentPrice", 0) or s.get("alertPrice", 0) or 0)
    if cp <= 0: continue
    invest = bal * 0.35
    positions.append({
        "ticker": s.get("ticker","?"), "chain": chain,
        "score": s["score"], "ep": cp, "invest": round(invest,2),
        "sl": cp*0.92, "tp": cp*1.12
    })
    if chain == "BSC": bsc_bal -= invest
    else: sol_bal -= invest

print(f"\nSimulated {len(positions)} positions:")
for p in positions:
    print(f"  {p['ticker']} ({p['chain']}) score={p['score']} ep=${p['ep']:.10f} ${p['invest']}")

# Log
log = f"\n{'='*60}\nBACKTEST {now.strftime('%Y-%m-%d %H:%M')} (spread=20%)\n"
log += f"Signals: {len(all_sigs)} | Qualified: {len(qualified)} | Trades: {len(positions)}\n"
for p in positions:
    log += f"  {p['ticker']} ({p['chain']}) score={p['score']} ep=${p['ep']:.10f} ${p['invest']}\n"
log += f"{'='*60}\n"
with open(LOG_FILE, "a", encoding="utf-8") as f:
    f.write(log)
print(f"\nLog saved.")
