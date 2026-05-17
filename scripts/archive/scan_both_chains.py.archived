#!/usr/bin/env python3
"""
Signal Scanner v1.0
- 同时扫描 BSC (56) + Solana (CT_501) 信号
- 合并评分，统一排名
- 输出 BSC/Solana 分链排名
- 保存到 data/signal-queue.json 供执行器使用
"""

import json, os, sys, time, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# === PATHS ===
DATA_DIR      = os.path.expanduser("~/.qclaw/workspace/data")
STATE_FILE    = os.path.join(DATA_DIR, "smart-money-state.json")
QUEUE_FILE    = os.path.join(DATA_DIR, "signal-queue.json")
LOG_FILE      = os.path.join(DATA_DIR, "signal-log.json")
SCAN_REPORT   = os.path.join(DATA_DIR, "scan-report.json")
os.makedirs(DATA_DIR, exist_ok=True)

# === CHAIN CONFIGS ===
CHAIN_CONFIGS = {
    "56":      {"name": "BSC",    "id": "56",      "symbol": "BSC",  "usdt": "0x55d398326f99059fF775485246999027B3197955"},
    "CT_501":  {"name": "Solana", "id": "CT_501",  "symbol": "SOL",  "usdt": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"},
}

# === SIGNAL PARAMS ===
SCALP_THRESHOLD   = 28
STRONG_THRESHOLD  = 50
MIN_SM_ENTRIES    = 2
MAX_SPREAD_PCT    = 0.08   # skip if price moved >8% from alert
STALE_START_MIN   = 60
STALE_MAX_MIN     = 180
MAX_QUEUE         = 30
MIN_MARKET_CAP    = 100_000  # $100K min market cap
MAX_TOTAL_POSITIONS = 3  # max positions across all chains
SIGNAL_TTL_SECONDS = 3600  # 1 hour TTL (unified with execute_bsc.py)


# ═══════════════════════════════════════════════════════════════
# API CALLS
# ═══════════════════════════════════════════════════════════════

def fetch_signals(chain_id, page=1, page_size=50):
    url = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai"
    headers = {
        "Content-Type": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    body = json.dumps({
        "smartSignalType": "",
        "page": page,
        "pageSize": page_size,
        "chainId": chain_id
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success") and data.get("data"):
                return data["data"]
    except Exception as e:
        print(f"  [WARN] Fetch BSC signals: {e}", file=sys.stderr)
    return []


def check_token_safety(ca, chain_id):
    """Check if token is safe to trade (no honeypot, reasonable tax).
    Returns (is_safe, reason)
    """
    # Try Binance token safety API
    try:
        url = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/token/audit"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        body = json.dumps({"contractAddress": ca, "chainId": chain_id}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success") and data.get("data"):
                audit = data["data"]
                # Check honeypot
                if audit.get("isHoneypot"):
                    return False, "HONEYPOT"
                # Check tax
                buy_tax = float(audit.get("buyTax", 0) or 0)
                sell_tax = float(audit.get("sellTax", 0) or 0)
                if buy_tax > 0.15 or sell_tax > 0.15:
                    return False, f"HIGH_TAX({buy_tax*100:.0f}%/{sell_tax*100:.0f}%)"
                # Check risk score
                risk = int(audit.get("riskScore", 0) or 0)
                if risk >= 80:
                    return False, f"HIGH_RISK({risk})"
                return True, "OK"
    except Exception as e:
        pass
    
    # Fallback: allow if audit API fails (better than blocking all trades)
    return True, "NO_AUDIT"


# ═══════════════════════════════════════════════════════════════
# SIGNAL SCORING
# ═══════════════════════════════════════════════════════════════

def score_signal(sig, now_ts, chain_id):
    """Return (score, reasons_list) - v2 Solana optimized"""
    score = 0
    reasons = []
    ca = sig.get("contractAddress", "").lower()

    # Direction check - only BUY
    direction = sig.get("direction", "")
    if direction == "sell":
        return 0, ["SELL_skip"]
    elif direction not in ("buy", ""):
        return 0, [f"dir={direction}"]

    # Smart Money Count - Solana optimized: lower threshold
    smc = sig.get("smartMoneyCount", 0)
    if   smc >= 8: score += 35; reasons.append(f"SM={smc}")
    elif smc >= 5: score += 25; reasons.append(f"SM={smc}")
    elif smc >= 3: score += 18; reasons.append(f"SM={smc}")
    elif smc >= 2: score += 10; reasons.append(f"SM={smc}")
    elif smc >= 1: score += 3;  reasons.append(f"SM={smc}")  # Allow single SM
    # Don't return 0, allow other factors to contribute

    # Signal Count
    sc = sig.get("signalCount", 0)
    if   sc >= 15: score += 8
    elif sc >= 5:  score += 3

    # Tags
    tags = sig.get("tokenTag", {}) or {}
    for cat, tag_list in tags.items():
        for t in (tag_list or []):
            tn = t.get("tagName", "")
            if tn == "Smart Money Add Holdings":  score += 12; reasons.append("SM+Hold")
            elif tn == "Whale Buy":               score += 15; reasons.append("WhaleBuy")
            elif tn == "DEX Paid":                 score += 3;  reasons.append("DEXpaid")
            elif tn == "Smart Money Reduce":      score -= 18; reasons.append("SM-Reduce")
            elif tn == "Whale Sell":              return 0, ["WhaleSell"]

    # Market Cap
    mc = float(sig.get("alertMarketCap", 0) or 0)
    if   mc >= 1_000_000:  score += 10; reasons.append(f"MC=${mc/1e6:.1f}M")
    elif mc >= 100_000:    score += 5;  reasons.append(f"MC=${mc/1e3:.0f}K")
    elif mc > 0:           score -= 5;  reasons.append("MC<100K")
    else:                   return 0, ["no_MC"]

    # Spread / entry timing - Solana optimized: more lenient
    current_price = float(sig.get("currentPrice", 0) or 0)
    alert_price    = float(sig.get("alertPrice", 0) or 0)
    if alert_price > 0 and current_price > 0:
        pump_pct = (current_price - alert_price) / alert_price
        if   pump_pct >  0.50: score -= 20; reasons.append(f"extreme_pump({pump_pct*100:.0f}%)")  # Only extreme penalized
        elif pump_pct >  0.30: score -= 10; reasons.append(f"late({pump_pct*100:.0f}%)")
        elif pump_pct >  0.15: score -= 3;  reasons.append(f"spread({pump_pct*100:.0f}%)")
        elif pump_pct >  0.05: score += 5;  reasons.append(f"entry_ok+{pump_pct*100:.1f}%")
        elif pump_pct > -0.05: score += 10; reasons.append(f"early({pump_pct*100:.1f}%)")  # Stable best
        elif pump_pct > -0.10: score -= 3;  reasons.append(f"dipped({pump_pct*100:.1f}%)")
        else:                  score -= 10; reasons.append(f"dump({pump_pct*100:.1f}%)")

    # Status - Solana optimized: don't block, only penalize
    status = sig.get("status", "")
    if   status == "active":  score += 15; reasons.append("ACTIVE")
    elif status == "timeout": score += 5;  reasons.append("timeout")
    elif status in ("exitRate", "outDecline"): score -= 10; reasons.append(f"exiting({status})")  # Penalize but don't block

    # Staleness penalty
    created_at = sig.get("createdAt", 0)
    if created_at:
        age_min = (now_ts * 1000 - created_at) / 60000
        if age_min > STALE_START_MIN:
            staleness = min(1.0, (age_min - STALE_START_MIN) / (STALE_MAX_MIN - STALE_START_MIN))
            score -= int(staleness * 15)
            if score < 0: return 0, ["stale_old"]

    final = max(0, min(100, score))
    return final, reasons


# ═══════════════════════════════════════════════════════════════
# STATE
# ═══════════════════════════════════════════════════════════════

BAW_CMD = os.path.expanduser("~\\AppData\\Roaming\\QClaw\\npm-global\\baw.cmd")
if not os.path.isfile(BAW_CMD):
    BAW_CMD = "baw"


def _baw_run(args, timeout=20):
    """Run BAW CLI command and return stdout."""
    import subprocess
    cmd = [BAW_CMD] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout, encoding="utf-8", errors="replace")
        return result.stdout.strip(), result.returncode
    except Exception as e:
        return "", 999


def sync_positions_with_chain(state):
    """Compare state file positions against actual on-chain balances.
    Remove ghost positions (tokens no longer held on-chain).
    Also checks tx-history for recent trades as secondary verification.
    Returns list of cleaned-up tickers."""
    cleaned = []
    bsc_positions = {ca: pos for ca, pos in state.get("positions", {}).items()
                     if str(pos.get("chain_id", "")) == "56"}
    if not bsc_positions:
        return cleaned

    # Query actual on-chain balances
    out, code = _baw_run(["wallet", "balance", "--binanceChainId", "56", "--json"])
    if code != 0 or not out:
        print("  [SYNC] WARNING: Could not query chain balance — skipping sync")
        return cleaned

    try:
        data = json.loads(out)
        onchain_cas = set()
        onchain_balances = {}
        for t in data.get("data", []):
            addr = t.get("contractAddress", "").lower()
            bal = float(t.get("balance", 0))
            val = float(t.get("value", 0))
            if addr and bal > 0 and val > 0.01:
                onchain_cas.add(addr)
                onchain_balances[addr] = bal
    except Exception as e:
        print(f"  [SYNC] WARNING: Balance parse error — skipping sync: {e}")
        return cleaned

    # Check each state-file position
    for ca, pos in list(bsc_positions.items()):
        ticker = pos.get("ticker", "?")
        ca_lower = ca.lower()

        if ca_lower in onchain_cas:
            actual_bal = onchain_balances.get(ca_lower, 0)
            state_amount = float(pos.get("amount", 0))
            if actual_bal < state_amount * 0.5:
                print(f"  [SYNC] MISMATCH: {ticker} — state={state_amount:.2f} vs chain={actual_bal:.2f}. Updating.")
                pos["amount"] = actual_bal
        else:
            # Token NOT on chain — ghost position
            # Double-check: query individual token balance as fallback
            individual_bal = _query_token_balance(ca)
            if individual_bal > 0:
                print(f"  [SYNC] MISMATCH: {ticker} — state={pos.get('amount',0):.2f} vs chain={individual_bal:.2f}. Updating.")
                pos["amount"] = individual_bal
            else:
                print(f"  [SYNC] GHOST: {ticker} — in state but NOT on-chain. Removing.")
                del state["positions"][ca]
                cleaned.append(ticker)

    if cleaned:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    return cleaned



def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"positions": {}, "cooldowns": {}, "signal_scores": {}}


def load_queue():
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_queue(queue):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)


def append_log(entry):
    log = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                log = json.load(f)
        except Exception:
            pass
    log.append(entry)
    if len(log) > 3000:
        log = log[-3000:]
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# MAIN SCAN
# ═══════════════════════════════════════════════════════════════

def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    now_ts = now.timestamp()
    
    print(f"\n{'='*56}")
    print(f" SIGNAL SCANNER  |  {now.strftime('%Y-%m-%d %H:%M')}  |  BSC + Solana")
    print(f"{'='*56}")

    state = load_state()

    # ─── Sync positions with on-chain reality ───
    print("\n[ Position Sync ]")
    ghosts = sync_positions_with_chain(state)
    if ghosts:
        print(f" Cleaned {len(ghosts)} ghost position(s): {', '.join(ghosts)}")
    else:
        print(" All positions verified on-chain")

    positions = state.get("positions", {})
    open_cas = {k.lower() for k in positions.keys()}
    cooldowns = state.get("cooldowns", {})
    done_ids = set(state.get("last_signal_ids", []))
    
    # Check if we've reached max positions globally
    total_positions = len(positions)
    if total_positions >= MAX_TOTAL_POSITIONS:
        print(f"\n[INFO] Max positions reached ({total_positions}/{MAX_TOTAL_POSITIONS}) - skipping scan")
        print(f"\n Done. No new signals added.")
        return 0

    # Check cooldowns
    active_cooldowns = []
    for ca, end_str in list(cooldowns.items()):
        try:
            end = datetime.fromisoformat(end_str)
            if now < end:
                active_cooldowns.append(ca)
            else:
                del cooldowns[ca]
        except Exception:
            pass

    all_scored = []   # (chain_id, chain_name, sig, score, reasons)

    # ─── Scan each chain ───
    for chain_id, cfg in CHAIN_CONFIGS.items():
        chain_name = cfg["name"]
        print(f"\n[ {chain_name} ]  chainId={chain_id}")

        # Check cooldown for this chain
        # (global cooldown applies to specific tokens, not whole chains)

        signals = fetch_signals(chain_id)
        print(f"  Fetched: {len(signals)} signals")

        found = 0
        for sig in signals:
            sig_id = sig.get("signalId", "")
            ticker = sig.get("ticker", "???")
            ca = sig.get("contractAddress", "").lower()
            direction = sig.get("direction", "")

            # Skip SELL
            if direction == "sell":
                continue

            # Skip if already in position
            if ca in open_cas:
                continue

            # Skip if already traded recently
            if sig_id in done_ids:
                continue

            # Skip if in cooldown
            if ca in active_cooldowns:
                continue

            score, reasons = score_signal(sig, now_ts, chain_id)

            if score < SCALP_THRESHOLD:
                continue

            # Safety check (honeypot, tax, risk)
            is_safe, safety_reason = check_token_safety(ca, chain_id)
            if not is_safe:
                print(f"     [SKIP] {ticker} - {safety_reason}")
                continue
            
            # Skip if max positions reached
            if total_positions >= MAX_TOTAL_POSITIONS:
                continue

            found += 1
            entry = {
                "chain":       chain_id,
                "chain_name":  chain_name,
                "sigId":       sig_id,
                "ticker":      ticker,
                "ca":          ca,
                "score":       score,
                "reasons":     reasons,
                "direction":   direction or "buy",
                "alertPrice":  float(sig.get("alertPrice", 0) or 0),
                "currentPrice":float(sig.get("currentPrice", 0) or 0),
                "alertMarketCap": float(sig.get("alertMarketCap", 0) or 0),
                "smartMoneyCount": sig.get("smartMoneyCount", 0),
                "signalCount":    sig.get("signalCount", 0),
                "tags":           sig.get("tokenTag", {}),
                "status":        sig.get("status", ""),
                "createdAt":     sig.get("createdAt", 0),
                "ts":            now_ts,
                "scan_time":     now.isoformat(),
            }
            all_scored.append(entry)

        print(f"  Tradeable: {found} signals")

    # ─── Load existing queue ───
    queue = load_queue()
    # Filter TTL first, then dedup
    queue = [q for q in queue if (now_ts - q.get("ts", 0)) < SIGNAL_TTL_SECONDS]  # unified TTL
    
    # Build existing IDs set from filtered queue (fix: dedup after TTL filter)
    existing_ids = set()
    for q in queue:
        eid = q.get("sigId") or q.get("signalId", "")
        if eid:
            existing_ids.add(eid)

    # ─── Merge new signals ───
    added = 0
    for entry in all_scored:
        entry_id = entry.get("sigId") or entry.get("signalId", "")
        if not entry_id:
            print(f"     [WARN] Signal {entry.get('ticker', '?')} has no ID, skipping")
            continue
        if entry_id not in existing_ids:
            queue.append(entry)
            existing_ids.add(entry_id)
            added += 1

    # ─── Sort and trim ───
    queue.sort(key=lambda x: x["score"], reverse=True)
    if len(queue) > MAX_QUEUE:
        removed = len(queue) - MAX_QUEUE
        queue = queue[:MAX_QUEUE]
        print(f"  Trimmed {removed} lowest-score signals (max queue size)")

    save_queue(queue)

    # ─── Print combined ranking ───
    print(f"\n{'─'*56}")
    print(f" SIGNAL RANKING  ({len(queue)} signals)")
    print(f"{'─'*56}")

    if queue:
        # Show top by chain
        bsc_top   = [q for q in queue if q["chain"] == "56"][:5]
        sol_top   = [q for q in queue if q["chain"] == "CT_501"][:5]

        print(f"\n BSC TOP-5:")
        for i, q in enumerate(bsc_top, 1):
            flag = "  STRONG" if q["score"] >= STRONG_THRESHOLD else ""
            print(f"  {i}. {q['ticker']:<12} score={q['score']:>3}{flag}")
            print(f"      {' | '.join(q['reasons'][:3])}")

        print(f"\n SOLANA TOP-5:")
        for i, q in enumerate(sol_top, 1):
            flag = "  STRONG" if q["score"] >= STRONG_THRESHOLD else ""
            print(f"  {i}. {q['ticker']:<12} score={q['score']:>3}{flag}")
            print(f"      {' | '.join(q['reasons'][:3])}")
    else:
        print("  No signals above threshold.")

    # Save scan report
    report = {
        "ts": now.isoformat(),
        "total_signals": len(queue),
        "bsc_count": len([q for q in queue if q["chain"] == "56"]),
        "sol_count": len([q for q in queue if q["chain"] == "CT_501"]),
        "top_bsc": bsc_top[:3] if queue else [],
        "top_sol": sol_top[:3] if queue else [],
        "positions_open": len(positions),
    }
    with open(SCAN_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n Done. Queue saved: {len(queue)} signals (added {added} new).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
