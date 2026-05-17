#!/usr/bin/env python3
"""Scalper v3.3 - Position Manager (Dynamic SL/TP + Signal Health)"""

import json, os, sys, time, subprocess
from datetime import datetime, timezone, timedelta

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STATE_FILE = os.path.expanduser("~/.qclaw/workspace/data/smart-money-state.json")
DATA_DIR = os.path.expanduser("~/.qclaw/workspace/data")
SIGNAL_QUEUE = os.path.join(DATA_DIR, "signal-queue.json")
RETRY_LOG = os.path.join(DATA_DIR, "retry-log.txt")
CHAIN_IDS = ["56", "CT_501"]

MAX_POSITIONS = 3
STOP_LOSS_PCT = -0.08
TAKE_PROFIT_PCT = 0.12
BREAKEVEN_TRIGGER = 0.05
TRAILING_TRIGGER = 0.08
TRAILING_DISTANCE = 0.02
PARTIAL_TP_TRIGGER = 0.10
MAX_HOLDING_HOURS = 24
NO_MOVEMENT_THRESHOLD = 0.03
SAME_DAY_SL_CUTOFF_HOUR = 23
MAX_RETRY_ATTEMPTS = 3
CONSECUTIVE_SL_FREEZE = 3
FREEZE_DURATION_HOURS = 2
COOLDOWN_AFTER_SL_HOURS = 12
COOLDOWN_AFTER_TP_HOURS = 6
SIGNAL_WEAKEN_THRESHOLD = 15

BSC_USDT = "0x55d398326f99059fF775485246999027B3197955"
SOL_USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

os.makedirs(DATA_DIR, exist_ok=True)
BAW_CMD = os.path.expanduser("~\\AppData\\Roaming\\QClaw\\npm-global\\baw.cmd")
if not os.path.isfile(BAW_CMD):
    BAW_CMD = "baw"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"positions": {}, "last_signal_ids": [], "cooldowns": {}}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def load_signal_queue():
    if os.path.exists(SIGNAL_QUEUE):
        with open(SIGNAL_QUEUE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def log_retry(ticker, action, reason, attempt):
    ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    with open(RETRY_LOG, "a", encoding="utf-8") as f:
        f.write("[{}] {} | {} | {} | #{}\n".format(ts, ticker, action, reason, attempt))

def _baw_env():
    env = dict(os.environ)
    env["PATH"] = env.get("PATH", "") + ";" + os.path.expanduser("~\\AppData\\Roaming\\QClaw\\npm-global")
    return env

def get_wallet_balances():
    try:
        result = subprocess.run([BAW_CMD, "wallet", "balance", "--json"],
                                capture_output=True, text=True, timeout=15, env=_baw_env())
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get("success"):
                by_ca, by_sym = {}, {}
                for t in data.get("data", []):
                    ca = t.get("contractAddress", "").strip().lower()
                    sym = t.get("symbol", "").strip().upper()
                    entry = {"balance": float(t.get("balance", 0)), "price": float(t.get("price", 0)),
                             "value": float(t.get("value", 0)), "chainId": t.get("binanceChainId", "56")}
                    if ca: by_ca[ca] = entry
                    by_sym[sym] = entry
                return {"by_ca": by_ca, "by_sym": by_sym}
    except Exception as e:
        print("[ERROR] Balance: {}".format(e), file=sys.stderr)
    return {"by_ca": {}, "by_sym": {}}

def fetch_signals(chain_id):
    import urllib.request
    url = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai"
    headers = {"Content-Type": "application/json"}
    body = json.dumps({"smartSignalType": "", "page": 1, "pageSize": 50, "chainId": chain_id}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success"):
                return data.get("data", [])
    except Exception as e:
        print("[ERROR] Signals: {}".format(e), file=sys.stderr)
    return []

def execute_swap(qty, from_token, to_token, chain_id, slippage=3):
    try:
        result = subprocess.run(
            [BAW_CMD, "market-order", "swap", "--fromTokenQty", str(qty),
             "--fromToken", from_token, "--toToken", to_token,
             "--binanceChainId", chain_id, "--slippage", str(slippage),
             "--mev", "true", "--gasLevel", "HIGH", "--json"],
            capture_output=True, text=True, timeout=60, env=_baw_env())
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("success", False), data.get("data", {})
        return False, "exit={}".format(result.returncode)
    except Exception as e:
        return False, str(e)

def market_sell(token_addr, qty, chain_id, slippage=10):
    usdt = BSC_USDT if chain_id == "56" else SOL_USDT
    for i in range(1, MAX_RETRY_ATTEMPTS + 1):
        ok, res = execute_swap(qty, token_addr, usdt, chain_id, slippage)
        if ok:
            return True, res
        log_retry(token_addr[:8], "SELL", str(res)[:50], i)
        if i < MAX_RETRY_ATTEMPTS:
            time.sleep(3)
    return False, res

def set_cooldown(state, ca, exit_type):
    hours = COOLDOWN_AFTER_SL_HOURS if exit_type == "SL" else COOLDOWN_AFTER_TP_HOURS
    end = (datetime.now(timezone(timedelta(hours=8))) + timedelta(hours=hours)).isoformat()
    state.setdefault("cooldowns", {})[ca] = end

def get_positions(state, balances):
    positions = state.get("positions", {})
    results = []
    now = datetime.now(timezone(timedelta(hours=8)))

    signals = {}
    for cid in CHAIN_IDS:
        for s in fetch_signals(cid):
            ca = s.get("contractAddress", "").lower()
            signals[ca] = {"price": float(s.get("currentPrice", 0) or 0),
                           "smc": s.get("smartMoneyCount", 0)}

    for ca, pos in list(positions.items()):
        entry = float(pos.get("entry_price", 0))
        chain_id = pos.get("chainId", "56")
        ticker = pos.get("ticker", "???")
        invest = float(pos.get("invest_amount", 0))
        entry_time = pos.get("entry_time", "")

        price = entry
        sig = signals.get(ca.lower(), {})
        if sig.get("price", 0) > 0:
            price = sig["price"]

        hours = 0
        if entry_time:
            try:
                et = datetime.fromisoformat(entry_time.replace("+08:00", "+08:00"))
                hours = (now - et).total_seconds() / 3600
            except:
                pass

        bal = balances.get("by_ca", {}).get(ca.lower(), {}).get("balance", 0)
        val = balances.get("by_ca", {}).get(ca.lower(), {}).get("value", 0)

        if entry > 0 and invest > 0:
            pnl_pct = (price - entry) / entry
            pnl_val = val - invest
            score_drop = pos.get("score", 0) - sig.get("smc", 0) * 5

            results.append({
                "ca": ca, "ticker": ticker, "chainId": chain_id,
                "entry": entry, "price": price, "bal": bal, "invest": invest,
                "pnl_pct": pnl_pct, "pnl_val": pnl_val, "hours": hours,
                "score_drop": score_drop, "sl": pos.get("sl_price"),
                "partial_tp": pos.get("partial_tp_done", False),
                "breakeven": pos.get("breakeven_done", False),
                "trailing": pos.get("trailing_done", False),
                "peak": pos.get("peak_price", entry),
            })

    results.sort(key=lambda x: x["pnl_pct"])
    return results

def adjust(pos, state):
    pnl = pos["pnl_pct"]
    ca = pos["ca"]
    ticker = pos["ticker"]
    cid = pos["chainId"]
    entry = pos["entry"]
    bal = pos["bal"]
    hours = pos["hours"]
    now_hr = datetime.now(timezone(timedelta(hours=8))).hour

    if bal <= 0:
        return state, []

    acts = []

    # Signal weak (score drop alone triggers reduction)
    # Threshold: original score dropped by 30+ points = 6+ smart money addresses left
    if pos.get("score_drop", 0) >= 30:
        qty = int(bal * 0.5)
        if qty > 0:
            ok, _ = market_sell(ca, qty, cid, 15)
            if ok:
                acts.append("REDUCED 50% (score drop: {})".format(int(pos.get("score_drop", 0))))
                state["positions"][ca]["invest_amount"] *= 0.5
                return state, acts

    # 24h timeout
    if hours >= MAX_HOLDING_HOURS and abs(pnl) < NO_MOVEMENT_THRESHOLD:
        qty = int(bal * 0.5)
        if qty > 0:
            ok, _ = market_sell(ca, qty, cid, 15)
            if ok:
                acts.append("TIMEOUT 24h: reduced 50%")
                state["positions"][ca]["invest_amount"] *= 0.5
                return state, acts

    # Same-day SL
    if pnl <= STOP_LOSS_PCT and now_hr >= SAME_DAY_SL_CUTOFF_HOUR:
        ok, _ = market_sell(ca, bal, cid, 20)
        if ok:
            acts.append("SAME_DAY_CLOSE: {}".format(ticker))
            state["consecutive_sl"] = state.get("consecutive_sl", 0) + 1
            if state["consecutive_sl"] >= CONSECUTIVE_SL_FREEZE:
                fr = (datetime.now(timezone(timedelta(hours=8))) + timedelta(hours=FREEZE_DURATION_HOURS)).isoformat()
                state["freeze_until"] = fr
            set_cooldown(state, ca, "SL")
            state.setdefault("closed_trades", []).append({
                "ticker": ticker, "pnl_pct": pnl, "pnl_val": pos["pnl_val"],
                "exit_time": datetime.now(timezone(timedelta(hours=8))).isoformat(),
                "exit_reason": "SL_HIT"
            })
            state["total_pnl"] = state.get("total_pnl", 0) + pos["pnl_val"]
            if ca in state["positions"]:
                del state["positions"][ca]
            return state, acts

    # Dynamic SL/TP
    if pnl >= PARTIAL_TP_TRIGGER and not pos.get("partial_tp"):
        acts.append("PARTIAL_TP: +{:.1f}%".format(pnl * 100))
        state["positions"][ca]["partial_tp_done"] = True
        state["positions"][ca]["sl_price"] = round(entry * 1.03, 10)

    elif pnl >= TRAILING_TRIGGER and not pos.get("trailing"):
        new_sl = round(pos.get("peak", entry) * (1 - TRAILING_DISTANCE), 10)
        if new_sl > entry * (1 + STOP_LOSS_PCT):
            acts.append("TRAILING: SL -> {:.8f}".format(new_sl))
            state["positions"][ca]["trailing_done"] = True
            state["positions"][ca]["sl_price"] = new_sl

    elif pnl >= BREAKEVEN_TRIGGER and not pos.get("breakeven"):
        new_sl = round(entry * 1.001, 10)
        acts.append("BREAKEVEN: SL -> {:.8f}".format(new_sl))
        state["positions"][ca]["breakeven_done"] = True
        state["positions"][ca]["sl_price"] = new_sl

    # Hard SL
    if pnl <= STOP_LOSS_PCT:
        ok, _ = market_sell(ca, bal, cid, 15)
        if ok:
            acts.append("HARD_SL: {:.1f}% -> CLOSED".format(pnl * 100))
            state["consecutive_sl"] = state.get("consecutive_sl", 0) + 1
            state["profit_pool"] = state.get("profit_pool", 0) + pnl * pos["invest"]
            if state["consecutive_sl"] >= CONSECUTIVE_SL_FREEZE:
                fr = (datetime.now(timezone(timedelta(hours=8))) + timedelta(hours=FREEZE_DURATION_HOURS)).isoformat()
                state["freeze_until"] = fr
            set_cooldown(state, ca, "SL")
            state.setdefault("closed_trades", []).append({
                "ticker": ticker, "pnl_pct": pnl, "pnl_val": pos["pnl_val"],
                "exit_time": datetime.now(timezone(timedelta(hours=8))).isoformat(),
                "exit_reason": "SL_HIT"
            })
            state["total_pnl"] = state.get("total_pnl", 0) + pos["pnl_val"]
            if ca in state["positions"]:
                del state["positions"][ca]
            return state, acts

    # Full TP
    if pnl >= TAKE_PROFIT_PCT:
        usdt = BSC_USDT if cid == "56" else SOL_USDT
        ok, _ = execute_swap(bal, ca, usdt, cid, 5)
        if ok:
            acts.append("FULL_TP: +{:.1f}% -> CLOSED".format(pnl * 100))
            state["consecutive_sl"] = 0
            state["profit_pool"] = state.get("profit_pool", 0) + pnl * pos["invest"]
            set_cooldown(state, ca, "TP")
            state.setdefault("closed_trades", []).append({
                "ticker": ticker, "pnl_pct": pnl, "pnl_val": pos["pnl_val"],
                "exit_time": datetime.now(timezone(timedelta(hours=8))).isoformat(),
                "exit_reason": "TP_HIT"
            })
            state["total_pnl"] = state.get("total_pnl", 0) + pos["pnl_val"]
            if ca in state["positions"]:
                del state["positions"][ca]
            return state, acts

    # Update peak
    if pos["price"] > state["positions"].get(ca, {}).get("peak_price", entry):
        state["positions"][ca]["peak_price"] = pos["price"]

    return state, acts

def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    print("\n" + "=" * 50)
    print("MANAGER v3.3 | {}".format(now.strftime("%Y-%m-%d %H:%M:%S")))
    print("=" * 50)

    state = load_state()
    balances = get_wallet_balances()

    if state.get("freeze_until"):
        ft = datetime.fromisoformat(state["freeze_until"])
        if now < ft:
            print("\n[FROZEN] {:.0f} min left".format((ft - now).total_seconds() / 60))
            return

    positions = get_positions(state, balances)

    if not positions:
        print("\n[POSITIONS] None open")
        return

    print("\n[POSITIONS] {} active".format(len(positions)))
    for p in positions:
        e = "🟢" if p["pnl_pct"] > 0.05 else ("🔴" if p["pnl_pct"] < -0.03 else "🟡")
        w = "⚠️ drop:{}".format(int(p.get("score_drop", 0))) if p.get("score_drop", 0) >= 30 else ""
        print("  {} {}: {:+.2f}% | ${:.2f} | {:.1f}h {}".format(
            e, p["ticker"], p["pnl_pct"] * 100, p["invest"], p["hours"], w))

    print("\n[ADJUSTMENTS]")
    for p in positions:
        state, acts = adjust(p, state)
        for a in acts:
            print("  >> {}: {}".format(p["ticker"], a))

    save_state(state)

    oc = len(state.get("positions", {}))
    tp = state.get("total_pnl", 0)
    print("\n[SUMMARY] Positions: {}/{} | P&L: ${:.2f}".format(oc, MAX_POSITIONS, tp))
    print("=" * 50)

if __name__ == "__main__":
    main()
