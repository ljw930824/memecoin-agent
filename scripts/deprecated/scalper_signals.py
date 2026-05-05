#!/usr/bin/env python3
"""
Scalper v3.3 - Signal Scanner (轻量快速版)
只负责：扫信号 + 评分 + 保存可交易机会
运行频率：每 5 分钟
"""

import json, os, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# === CONFIG ===
STATE_FILE     = os.path.expanduser("~/.qclaw/workspace/data/smart-money-state.json")
DATA_DIR       = os.path.expanduser("~/.qclaw/workspace/data")
SIGNAL_QUEUE   = os.path.join(DATA_DIR, "signal-queue.json")
SIGNAL_LOG     = os.path.join(DATA_DIR, "signal-log.json")
CHAIN_IDS      = ["56", "CT_501"]

# 评分阈值
SCALP_THRESHOLD  = 28
STRONG_THRESHOLD = 50
MIN_SM_ENTRIES   = 2
MAX_SPREAD_PCT   = 0.05
STALE_PENALTY_START_MIN = 60
STALE_PENALTY_MAX_MIN   = 180

os.makedirs(DATA_DIR, exist_ok=True)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"positions": {}, "last_signal_ids": [], "cooldowns": {}, "signal_scores": {}}


def save_signal_queue(queue):
    with open(SIGNAL_QUEUE, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)


def load_signal_queue():
    if os.path.exists(SIGNAL_QUEUE):
        with open(SIGNAL_QUEUE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def append_signal_log(entry):
    log = []
    if os.path.exists(SIGNAL_LOG):
        with open(SIGNAL_LOG, "r", encoding="utf-8") as f:
            log = json.load(f)
    log.append(entry)
    if len(log) > 2000:
        log = log[-2000:]
    with open(SIGNAL_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def fetch_signals(chain_id, page=1, page_size=50):
    import urllib.request
    url = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai"
    headers = {"Content-Type": "application/json", "Accept-Encoding": "identity",
               "User-Agent": "binance-web3/1.1 (Skill)"}
    body = json.dumps({"smartSignalType": "", "page": page, "pageSize": page_size,
                        "chainId": chain_id}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success") and data.get("data"):
                return data["data"]
    except Exception as e:
        print(f"[ERROR] Fetch signals chain {chain_id}: {e}", file=sys.stderr)
    return []


def fetch_smart_money_inflow(chain_id, period="1h"):
    import urllib.request
    url = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/tracker/wallet/token/inflow/rank/query/ai"
    headers = {"Content-Type": "application/json", "Accept-Encoding": "identity",
               "User-Agent": "binance-web3/2.1 (Skill)"}
    body = json.dumps({"chainId": chain_id, "period": period, "tagType": 2}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success") and data.get("data"):
                return data["data"]
    except Exception as e:
        print(f"[ERROR] Inflow chain {chain_id}: {e}", file=sys.stderr)
    return []


def check_cooldown(state, ca):
    cooldowns = state.get("cooldowns", {})
    if ca in cooldowns:
        cooldown_end = datetime.fromisoformat(cooldowns[ca])
        if datetime.now(timezone(timedelta(hours=8))) < cooldown_end:
            remaining = (cooldown_end - datetime.now(timezone(timedelta(hours=8)))).total_seconds() / 3600
            return True, remaining
        else:
            del state["cooldowns"][ca]
    return False, 0


def score_signal(sig, state, now_ts):
    """快速评分"""
    score = 0
    reasons = []
    penalties = []

    ca = sig.get("contractAddress", "").lower()
    
    # Cooldown check
    in_cooldown, remaining = check_cooldown(state, ca)
    if in_cooldown:
        return 0, [f"COOLDOWN({remaining:.1f}h)"]

    # Smart Money Count
    smc = sig.get("smartMoneyCount", 0)
    if smc >= 8:   score += 40; reasons.append(f"SM={smc}")
    elif smc >= 5: score += 25; reasons.append(f"SM={smc}")
    elif smc >= 3: score += 12; reasons.append(f"SM={smc}")
    elif smc >= MIN_SM_ENTRIES:
        score += 5; reasons.append(f"SM={smc}")
    else:
        return 0, [f"INSUFFICIENT_SM({smc}<{MIN_SM_ENTRIES})"]

    direction = sig.get("direction", "")
    if direction == "buy":    score += 10; reasons.append("buy")
    elif direction == "sell": return 0, ["SELL-skip"]

    sc = sig.get("signalCount", 0)
    if sc >= 15:  score += 8; reasons.append(f"signals={sc}")
    elif sc >= 5: score += 3; reasons.append(f"signals={sc}")

    # Tags
    tags = sig.get("tokenTag", {})
    for cat, tag_list in tags.items():
        for t in tag_list:
            tn = t.get("tagName", "")
            if tn == "Smart Money Add Holdings":  score += 12; reasons.append("SM+Holdings")
            elif tn == "Whale Buy":                score += 15; reasons.append("WhaleBuy")
            elif tn == "DEX Paid":                 score += 3;  reasons.append("DEXpaid")
            elif tn == "Smart Money Reduce":       score -= 18; reasons.append("SM-Reduce")
            elif tn == "Whale Sell":               return 0, ["WhaleSell"]

    # Market cap
    mc = float(sig.get("alertMarketCap", 0) or 0)
    if mc >= 1_000_000:  score += 10; reasons.append(f"mcap=${mc/1e6:.1f}M")
    elif mc >= 100_000:  score += 5;  reasons.append(f"mcap=${mc/1e3:.0f}K")
    elif mc > 0:         score -= 5;  reasons.append("mcap<100K")

    # Spread check
    current_price = float(sig.get("currentPrice", 0) or 0)
    alert_price   = float(sig.get("alertPrice", 0) or 0)
    if alert_price > 0 and current_price > 0:
        pump_pct = (current_price - alert_price) / alert_price
        if abs(pump_pct) > MAX_SPREAD_PCT:
            return 0, [f"SPREAD({pump_pct*100:.1f}%)"]
        if pump_pct < -0.10:
            score -= 15; reasons.append(f"dumped({pump_pct*100:.1f}%)")
        elif pump_pct < -0.05:
            score += 5;  reasons.append(f"dip({pump_pct*100:.1f}%)")
        elif pump_pct <= 0.03:
            score += 8;  reasons.append("early_entry")
        elif pump_pct <= 0.15:
            score += 3;  reasons.append(f"pump+{pump_pct*100:.1f}%")
        elif pump_pct <= 0.25:
            score -= 8;  reasons.append(f"chase+{pump_pct*100:.1f}%")
        else:
            return 0, [f"CHASE_SKIP+{pump_pct*100:.1f}%"]

    # Status
    status = sig.get("status", "")
    if status == "active":
        score += 15; reasons.append("ACTIVE")
    elif status == "timeout":
        score += 5; reasons.append("fresh_timeout")
    elif status in ("exitRate", "outDecline"):
        return 0, [f"exiting({status})"]

    # Staleness penalty
    created_at = sig.get("createdAt", 0)
    if created_at:
        age_min = (now_ts * 1000 - created_at) / 60000
        if age_min > STALE_PENALTY_START_MIN:
            staleness = min(1.0, (age_min - STALE_PENALTY_START_MIN) / 
                           (STALE_PENALTY_MAX_MIN - STALE_PENALTY_START_MIN))
            penalty = int(staleness * 15)
            score -= penalty
            if penalty > 0:
                penalties.append(f"stale(-{penalty})")

    final_score = max(0, min(100, score))
    return final_score, reasons + penalties


def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    now_ts = now.timestamp()
    print(f"\n{'='*50}")
    print(f"SCANNER v3.3 | {now.strftime('%Y-%m-%d %H:%M:%S')} | 信号扫描")
    print(f"{'='*50}")

    state = load_state()
    positions = state.get("positions", {})
    open_count = len(positions)

    # Load existing queue
    queue = load_signal_queue()
    
    # Filter out old signals (> 30 min) and already traded
    sig_ids_done = set(state.get("last_signal_ids", []))
    queue = [q for q in queue if q.get("ts") and 
             (now_ts - q.get("ts", 0)) < 1800 and  # 30 min TTL
             q.get("sigId") not in sig_ids_done]
    
    new_signals_found = 0

    # Fetch from all chains
    inflow_cas = set()
    for chain_id in CHAIN_IDS:
        chain_name = "BSC" if chain_id == "56" else "Solana"
        
        # Get inflow tokens
        inflow = fetch_smart_money_inflow(chain_id, "1h")
        for item in inflow[:10]:
            if float(item.get("inflow", 0)) > 0:
                inflow_cas.add(item.get("ca", "").lower())
        
        # Fetch signals
        signals = fetch_signals(chain_id)
        
        for sig in signals:
            sig_id = sig.get("signalId")
            ticker = sig.get("ticker", "???")
            ca = sig.get("contractAddress", "").lower()
            
            # Skip if already have position
            if ca in [k.lower() for k in positions.keys()]:
                continue
            
            # Score
            score, reasons = score_signal(sig, state, now_ts)
            
            # Log
            append_signal_log({
                "ts": now.isoformat(),
                "sigId": sig_id,
                "ticker": ticker,
                "chain": chain_name,
                "score": score,
                "status": sig.get("status", "?"),
                "reasons": reasons,
                "currentPrice": sig.get("currentPrice"),
                "alertPrice": sig.get("alertPrice"),
            })
            
            if score >= SCALP_THRESHOLD:
                inflow_bonus = 10 if ca.lower() in inflow_cas else 0
                final_score = score + inflow_bonus
                
                # Add to queue
                entry = {
                    "ts": now_ts,
                    "sigId": sig_id,
                    "ticker": ticker,
                    "chain": chain_name,
                    "chainId": chain_id,
                    "ca": ca,
                    "score": final_score,
                    "reasons": reasons + (["inflow"] if inflow_bonus else []),
                    "alertPrice": sig.get("alertPrice"),
                    "currentPrice": sig.get("currentPrice"),
                    "direction": sig.get("direction", "buy"),
                    "smartMoneyCount": sig.get("smartMoneyCount", 0),
                    "status": sig.get("status", "active"),
                    "entry_time": now.isoformat(),
                }
                
                # Update if already in queue, else append
                found = False
                for i, q in enumerate(queue):
                    if q.get("ca") == ca:
                        if final_score > q.get("score", 0):
                            queue[i] = entry
                            new_signals_found += 1
                        found = True
                        break
                if not found:
                    queue.append(entry)
                    new_signals_found += 1
                    
                print(f"  📡 {ticker} Score:{final_score} | {chain_name} | {' | '.join(reasons)}")
    
    # Sort queue by score
    queue.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    # Keep only top 20
    queue = queue[:20]
    
    # Save queue
    save_signal_queue(queue)
    
    print(f"\n[SUMMARY]")
    print(f"  持仓数: {open_count}/3")
    print(f"  新信号: +{new_signals_found}")
    print(f"  队列总数: {len(queue)}")
    if queue:
        top = queue[0]
        print(f"  最佳信号: {top['ticker']} (Score:{top['score']})")
    
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
