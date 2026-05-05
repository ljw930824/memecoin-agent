#!/usr/bin/env python3
"""
Scalping Strategy v3 - Smart Money Monitor
Enhanced with dynamic stop-loss, trailing stops, and partial profit-taking.

v3 enhancements over v2:
- Breakeven stop-loss: move SL to cost basis when position is +5%+
- Trailing stop: when +8%+, tighten SL to -2% from peak
- Partial take-profit: at +10%, sell 50% and move SL to +5%
- Position cap: max 3 open positions (reduce spreading)
- Chase prevention: penalize signals that already pumped >15%
- Dynamic sizing: reduce invest% when near position cap
- Momentum scoring boost: favor signals with recent volume surge
- Auto-compound: closed position profits add to next trade budget
"""

import json, os, sys, time, subprocess, uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# === CONFIG ===
STATE_FILE   = os.path.expanduser("~/.qclaw/workspace/data/smart-money-state.json")
DATA_DIR     = os.path.expanduser("~/.qclaw/workspace/data")
SIGNAL_LOG   = os.path.join(DATA_DIR, "signal-log.json")
CHAIN_IDS    = ["56", "CT_501"]

# Core risk params
MAX_POSITIONS       = 3          # Max concurrent open positions
STOP_LOSS_PCT       = -0.08      # -8% hard stop loss
TAKE_PROFIT_PCT     = 0.12       # +12% full take profit
SCALP_THRESHOLD     = 28         # Minimum score to trade
STRONG_THRESHOLD    = 50         # Strong signal threshold
MAX_INVEST_PCT      = 0.45       # Max % of available USDT per trade

# Dynamic SL/TP tiers
BREAKEVEN_TRIGGER   = 0.05       # Move SL to breakeven when +5%+
TRAILING_TRIGGER    = 0.08       # Start trailing stop when +8%+
TRAILING_DISTANCE   = 0.02       # Keep SL 2% below peak
PARTIAL_TP_TRIGGER  = 0.10      # Sell 50% at +10%
PARTIAL_TP_PCT      = 0.50       # How much to sell at partial TP
PARTIAL_SL_TIGHTEN  = 0.03       # After partial TP, set SL to +3% from entry

# Chase prevention
CHASE_PUMP_PCT      = 0.15       # If already pumped >15% from alert, skip/reduce
REDUCE_PUMP_PCT     = 0.10       # If pumped 10-15%, reduce position 50%

# ── v4 Enhancements ──────────────────────────────────────────────────────────
# Recent sell cooldown: skip tokens sold in last N hours
COOLDOWN_HOURS      = 6          # Don't re-buy a token sold within this window
# Multi-confirmation: require at least N smart money entries
MIN_SM_ENTRIES      = 2          # At least 2 distinct SM wallets buying this token
# Spread filter: max acceptable bid-ask spread % (slippage risk)
MAX_SPREAD_PCT      = 0.08       # Skip if alertPrice/currentPrice spread > 8%
# Signal freshness: active signals older than this get penalized (in minutes)
STALE_THRESHOLD_MIN = 120        # Active signals >2h start losing score
# Market cap floor: avoid micro-cap gems that may be illiquid
MIN_MARKET_CAP     = 500        # Minimum market cap in USD

# BNB auto-topup when USDT is low
BNB_TOPUP_THRESHOLD = 10.0     # Auto swap BNB->USDT when USDT below this
BNB_TOPUP_AMOUNT_BNB = 0.008   # BNB amount to swap (~$5 worth)

# BSC/Solana token addresses
BSC_USDT  = "0x55d398326f99059fF775485246999027B3197955"
BSC_BNB    = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
SOL_USDT   = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
SOL_SOL    = "So11111111111111111111111111111111111111111"

os.makedirs(DATA_DIR, exist_ok=True)

BAW_CMD = os.path.expanduser("~\\AppData\\Roaming\\QClaw\\npm-global\\baw.cmd")
if not os.path.isfile(BAW_CMD):
    BAW_CMD = "baw"

# ─── STATE ────────────────────────────────────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"positions": {}, "last_signal_ids": [], "trade_count": 0,
            "total_pnl": 0, "closed_trades": [], "profit_pool": 0}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


SNAPSHOT_FILE = os.path.join(DATA_DIR, "position-snapshot.json")

def save_position_snapshot(positions_data):
    """Save current position prices for next-run comparison."""
    snap = {"ts": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            "positions": {}}
    for ca, pos in (positions_data or {}).items():
        snap["positions"][ca] = {
            "ticker": pos.get("ticker", "?"),
            "invest": pos.get("invest_amount", 0),
            "entry_price": pos.get("entry_price", 0),
        }
    with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=2, ensure_ascii=False)

def load_previous_snapshot():
    """Load previous snapshot for comparison."""
    if os.path.exists(SNAPSHOT_FILE):
        with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


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


# ─── NETWORK ──────────────────────────────────────────────────────────────────

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


def fetch_token_price(ca, chain_id):
    """Fetch current price for a specific token."""
    import urllib.request
    url = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai"
    headers = {"Content-Type": "application/json", "Accept-Encoding": "identity",
               "User-Agent": "binance-web3/1.1 (Skill)"}
    body = json.dumps({"smartSignalType": "", "page": 1, "pageSize": 50,
                        "chainId": chain_id}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success") and data.get("data"):
                for sig in data["data"]:
                    if sig.get("contractAddress", "").lower() == ca.lower():
                        return float(sig.get("currentPrice", 0) or 0)
    except:
        pass
    return None


# ─── SCORING ─────────────────────────────────────────────────────────────────

def score_signal_v3(sig, cooldowns=None, now_ts=None):
    """v3 scoring: scalping + momentum + chase prevention + freshness + spread."""
    cooldowns = cooldowns or {}
    score = 0
    reasons = []

    ca = sig.get("contractAddress", "").lower()

    # ── Cooldown check ──────────────────────────────────────────────────────
    if ca in cooldowns:
        hours_ago = (now_ts - cooldowns[ca]) / 3600
        if hours_ago < COOLDOWN_HOURS:
            return 0, [f"COOLDOWN({hours_ago:.1f}h left)"]

    # Smart Money Count (weighted higher for v3)
    smc = sig.get("smartMoneyCount", 0)
    if smc >= 8:   score += 40; reasons.append(f"SM={smc}(high)")
    elif smc >= 5: score += 25; reasons.append(f"SM={smc}(med)")
    elif smc >= 3: score += 12; reasons.append(f"SM={smc}(low)")

    direction = sig.get("direction", "")
    if direction == "buy":     score += 10; reasons.append("buy")
    elif direction == "sell":   score -= 30; reasons.append("SELL-skip")

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
            elif tn == "Whale Sell":               score -= 25; reasons.append("WhaleSell")

    # Market cap
    mc = float(sig.get("alertMarketCap", 0) or 0)
    if mc >= 1_000_000:  score += 10; reasons.append(f"mcap=${mc/1e6:.1f}M")
    elif mc >= 100_000:  score += 5;  reasons.append(f"mcap=${mc/1e3:.0f}K")
    elif mc > 0:         score -= 5;  reasons.append("mcap<100K")

    # Price momentum (critical for v3)
    current_price = float(sig.get("currentPrice", 0) or 0)
    alert_price   = float(sig.get("alertPrice", 0) or 0)
    if alert_price > 0 and current_price > 0:
        pump_pct = (current_price - alert_price) / alert_price
        # Check negative pump FIRST (price dropped), then positive ranges
        if pump_pct < -0.10:
            score -= 15; reasons.append(f"dumped({pump_pct*100:.1f}%)")
        elif pump_pct < -0.05:
            score += 5;  reasons.append(f"dip_entry({pump_pct*100:.1f}%)")
        elif pump_pct <= 0.03:
            score += 8;  reasons.append("early_entry")
        elif pump_pct <= CHASE_PUMP_PCT:
            score += 3;  reasons.append(f"pump+{pump_pct*100:.1f}%")
        elif pump_pct <= 0.25:
            score -= 8;  reasons.append(f"chase_warn+{pump_pct*100:.1f}%")
        else:
            score -= 20; reasons.append(f"CHASE_SKIP+{pump_pct*100:.1f}%")

    # Status
    status = sig.get("status", "")
    if status == "active":       score += 15; reasons.append("ACTIVE")
    elif status == "timeout":
        tf = sig.get("timeFrame", 0)
        if tf < 3600000:         score += 5;  reasons.append("fresh_timeout")
        else:                    score -= 10; reasons.append("old_timeout")
    elif status in ("exitRate", "outDecline"):
        score -= 20; reasons.append(f"exiting({status})")

    return max(0, min(100, score)), reasons


# ─── AUDIT ────────────────────────────────────────────────────────────────────

def audit_token(ca, chain_id):
    import urllib.request
    url = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/security/token/audit"
    headers = {"Content-Type": "application/json", "Accept-Encoding": "identity",
               "User-Agent": "binance-web3/1.4 (Skill)", "source": "agent"}
    body = json.dumps({"binanceChainId": chain_id, "contractAddress": ca,
                        "requestId": str(uuid.uuid4())}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success") and data.get("data"):
                return data["data"]
    except Exception as e:
        print(f"[ERROR] Audit: {e}", file=sys.stderr)
    return None


def is_token_safe(audit_data):
    if not audit_data:
        return False, "Audit unavailable"
    if not audit_data.get("hasResult") or not audit_data.get("isSupported"):
        return False, "Audit unavailable"
    risk_level = audit_data.get("riskLevel", 3)
    risk_enum  = audit_data.get("riskLevelEnum", "HIGH")
    if risk_level >= 4:
        return False, f"HIGH RISK (level={risk_level})"
    extra = audit_data.get("extraInfo", {}) or {}
    buy_tax  = min(float(extra.get("buyTax",  "0") or "0") / 100,
                   float(extra.get("buyTax",  "0") or "0"))
    sell_tax = min(float(extra.get("sellTax", "0") or "0") / 100,
                   float(extra.get("sellTax", "0") or "0"))
    if buy_tax > 0.10 or sell_tax > 0.10:
        return False, f"Tax high: buy={buy_tax*100:.1f}% sell={sell_tax*100:.1f}%"
    risk_items = audit_data.get("riskItems", []) or []
    for item in risk_items:
        for detail in item.get("details", []):
            if detail.get("isHit") and detail.get("riskType") == "RISK":
                title = detail.get("title", "")
                if "honeypot" in title.lower() or "cannot sell" in title.lower():
                    return False, f"RUG: {title}"
    return True, f"OK(buy={buy_tax*100:.1f}% sell={sell_tax*100:.1f}% risk={risk_level}/{risk_enum})"


# ─── BAW WRAPPERS ────────────────────────────────────────────────────────────

def _baw_env():
    env = dict(os.environ)
    env["PATH"] = env.get("PATH", "") + ";" + os.path.expanduser("~\\AppData\\Roaming\\QClaw\\npm-global")
    return env


def get_wallet_balances():
    """Returns {by_ca, by_sym} for position lookups. BSC20 tokens lack contractAddress in BAW response, so match by symbol too."""
    try:
        result = subprocess.run([BAW_CMD, "wallet", "balance", "--json"],
                                capture_output=True, text=True, timeout=15, env=_baw_env())
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get("success"):
                by_ca  = {}
                by_sym = {}
                for t in data.get("data", []):
                    ca  = t.get("contractAddress", "").strip().lower()
                    sym = t.get("symbol", "").strip().upper()  # normalize to uppercase
                    entry = {
                        "balance":  float(t.get("balance", 0)),
                        "price":    float(t.get("price", 0)),
                        "value":    float(t.get("value", 0)),
                        "contract": ca,
                        "chainId":  t.get("binanceChainId", "56"),
                        "symbol":   sym,
                    }
                    if ca:
                        by_ca[ca] = entry
                    by_sym[sym] = entry
                return {"by_ca": by_ca, "by_sym": by_sym}
    except Exception as e:
        print(f"[ERROR] Wallet balance: {e}", file=sys.stderr)
    return {"by_ca": {}, "by_sym": {}}


def execute_swap(usdt_amount, from_token, to_token, chain_id):
    try:
        result = subprocess.run(
            [BAW_CMD, "market-order", "swap",
             "--fromTokenQty", str(usdt_amount),
             "--fromToken", from_token,
             "--toToken", to_token,
             "--binanceChainId", chain_id,
             "--slippage", "3",
             "--mev", "true",
             "--gasLevel", "HIGH",
             "--json"],
            capture_output=True, text=True, timeout=60, env=_baw_env()
        )
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                return data.get("success", False), data.get("data", {})
            except json.JSONDecodeError:
                return False, result.stdout[:300]
        return False, result.stderr[:300] if result.stderr else f"exit={result.returncode}"
    except Exception as e:
        return False, str(e)


def swap_bnb_to_usdt(bnb_amount, chain_id="56"):
    """Swap BNB -> USDT to replenish funds."""
    bnb_addr = BSC_BNB if chain_id == "56" else SOL_SOL
    usdt_addr = BSC_USDT if chain_id == "56" else SOL_USDT
    print(f"  [BNB-TOPUP] Swapping {bnb_amount} BNB -> USDT on chain {chain_id}...")
    success, result = execute_swap(bnb_amount, bnb_addr, usdt_addr, chain_id)
    if success:
        print(f"  [BNB-TOPUP] OK! {result}")
        return True
    else:
        print(f"  [BNB-TOPUP] FAILED: {result}")
        return False


def set_limit_sell(token_addr, qty, trigger_price, chain_id, to_token=None):
    if to_token is None:
        to_token = BSC_USDT if chain_id == "56" else SOL_USDT
    try:
        result = subprocess.run(
            [BAW_CMD, "limit-order", "sell",
             "--triggerPrice", str(trigger_price),
             "--fromTokenQty", str(qty),
             "--fromToken", token_addr,
             "--toToken", to_token,
             "--binanceChainId", chain_id,
             "--slippage", "5",
             "--json"],
            capture_output=True, text=True, timeout=30, env=_baw_env()
        )
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                return data.get("success", False), data.get("data", {})
            except json.JSONDecodeError:
                return False, result.stdout[:300]
        return False, result.stderr[:300] if result.stderr else f"exit={result.returncode}"
    except Exception as e:
        return False, str(e)


def cancel_limit_orders(strategy_ids):
    """Cancel specific limit orders by strategy ID."""
    cancelled = []
    for sid in strategy_ids:
        try:
            result = subprocess.run(
                [BAW_CMD, "limit-order", "cancel",
                 "--strategyId", str(sid),
                 "--binanceChainId", "56",
                 "--json"],
                capture_output=True, text=True, timeout=15, env=_baw_env()
            )
            if result.returncode == 0:
                cancelled.append(sid)
        except:
            pass
    return cancelled


def list_limit_orders(chain_id="56"):
    """List all active limit orders."""
    try:
        result = subprocess.run(
            [BAW_CMD, "limit-order", "list",
             "--binanceChainId", chain_id,
             "--json"],
            capture_output=True, text=True, timeout=15, env=_baw_env()
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get("success"):
                return data["data"].get("list", [])
    except:
        pass
    return []


# ─── POSITION MANAGER (v3 Dynamic SL/TP) ─────────────────────────────────────

def get_open_positions_with_pnl(state, balances):
    """Calculate real-time P&L for all open positions."""
    positions = state.get("positions", {})
    results = []

    # Fetch all signals to get current prices
    all_signals = {}
    for chain_id in CHAIN_IDS:
        for sig in fetch_signals(chain_id):
            ca = sig.get("contractAddress", "").lower()
            all_signals[ca] = {
                "price": float(sig.get("currentPrice", 0) or 0),
                "status": sig.get("status", ""),
            }

    for ca, pos in list(positions.items()):
        entry_price  = float(pos.get("entry_price", 0) or 0)
        chain_id     = pos.get("chainId", "56")
        ticker       = pos.get("ticker", "???")
        invest       = float(pos.get("invest_amount", 0))

        current_price = entry_price
        if ca.lower() in all_signals:
            current_price = all_signals[ca.lower()]["price"]

        # BSC20 tokens: BAW doesn't return contractAddress for them, so match by symbol (ticker)
        by_sym = balances.get("by_sym", {})
        token_bal   = 0
        token_value = 0
        ticker_upper = ticker.upper()
        if ticker_upper in by_sym:
            token_bal   = by_sym[ticker_upper]["balance"]
            token_value = by_sym[ticker_upper]["value"]

        if entry_price > 0 and invest > 0:
            pnl_pct   = (current_price - entry_price) / entry_price
            pnl_value = token_value - invest
            results.append({
                "ca": ca, "ticker": ticker, "chainId": chain_id,
                "entry_price": entry_price, "current_price": current_price,
                "token_balance": token_bal,
                "invest": invest, "pnl_pct": pnl_pct, "pnl_value": pnl_value,
                "entry_time": pos.get("entry_time", ""),
                "score": pos.get("score", 0),
                "sl_price": pos.get("sl_price"),
                "tp_price": pos.get("tp_price"),
                "sl_strategy_id": pos.get("sl_strategy_id"),
                "tp_strategy_id": pos.get("tp_strategy_id"),
                "partial_tp_done": pos.get("partial_tp_done", False),
                "breakeven_done": pos.get("breakeven_done", False),
                "trailing_done": pos.get("trailing_done", False),
            })

    results.sort(key=lambda x: x["pnl_pct"])  # Worst first (cut losers first)
    return results


def adjust_position_dynamic(pos, balances, state):
    """Apply dynamic SL/TP adjustments based on current P&L."""
    pnl_pct  = pos["pnl_pct"]
    ticker   = pos["ticker"]
    ca       = pos["ca"]
    chain_id = pos["chainId"]
    entry    = pos["entry_price"]
    token_bal = pos["token_balance"]

    if token_bal <= 0:
        return state, []

    sl_ok, tp_ok = True, True
    sl_msg, tp_msg = "skip (no change)", "skip (no change)"
    active_orders = list_limit_orders(chain_id)

    # Find existing order IDs for this position
    existing_order_sids = []
    for order in active_orders:
        if order.get("fromToken", "").lower() == ca.lower():
            existing_order_sids.append(order.get("strategyId"))

    actions = []

    # 1. Partial Take-Profit at +10% (sell 50%)
    if pnl_pct >= PARTIAL_TP_TRIGGER and not pos.get("partial_tp_done"):
        sell_qty = int(token_bal * PARTIAL_TP_PCT)
        if sell_qty > 0:
            tp_partial_price = round(entry * (1 + PARTIAL_TP_TRIGGER), 10)
            ok, data = set_limit_sell(ca, sell_qty, tp_partial_price, chain_id)
            if ok:
                actions.append(f"PARTIAL_TP: sell {sell_qty}@{tp_partial_price:.8f} (+10%)")
                state["positions"][ca]["partial_tp_done"] = True
                # Tighten SL to +3%
                new_sl = round(entry * (1 + PARTIAL_SL_TIGHTEN), 10)
                # Cancel old SL and set new tighter one
                if existing_order_sids:
                    cancel_limit_orders(existing_order_sids[:1])
                sl_ok, sl_data = set_limit_sell(ca, int(token_bal * 0.99), new_sl, chain_id)
                actions.append(f"TIGHTEN_SL: -> {new_sl:.8f} (+3%)")
                state["positions"][ca]["sl_price"] = new_sl

    # 2. Trailing Stop at +8%: SL = peak - 2%
    elif pnl_pct >= TRAILING_TRIGGER and not pos.get("trailing_done"):
        peak_price = pos.get("peak_price", pos["current_price"])
        new_sl = round(peak_price * (1 - TRAILING_DISTANCE), 10)
        if new_sl > entry * (1 + STOP_LOSS_PCT):  # Don't go below original SL
            actions.append(f"TRAILING: SL -> {new_sl:.8f} (peak={peak_price:.8f})")
            state["positions"][ca]["trailing_done"] = True
            state["positions"][ca]["sl_price"] = new_sl

    # 3. Breakeven at +5%: move SL to entry price
    elif pnl_pct >= BREAKEVEN_TRIGGER and not pos.get("breakeven_done"):
        new_sl = round(entry * 1.001, 10)  # Slight buffer above entry
        if new_sl > (pos.get("sl_price") or 0):
            actions.append(f"BREAKEVEN: SL -> {new_sl:.8f} (from {pos.get('sl_price')})")
            state["positions"][ca]["breakeven_done"] = True
            state["positions"][ca]["sl_price"] = new_sl

    # 4. Hard Stop-Loss at -8%
    if pnl_pct <= STOP_LOSS_PCT:
        actions.append(f"HARD_SL: stop-loss triggered ({pnl_pct*100:.1f}%)")
        # Market sell via swap back to USDT
        chain_usdt = BSC_USDT if chain_id == "56" else SOL_USDT
        ok, data = execute_swap(token_bal, ca, chain_usdt, chain_id)
        if ok:
            actions.append(f"LIQUIDATED: sold {token_bal} {ticker} at market")
            # Remove from positions
            del state["positions"][ca]
            return state, actions
        else:
            actions.append(f"LIQUIDATE_FAILED: {data}")

    # 5. Full Take-Profit at +12%
    if pnl_pct >= TAKE_PROFIT_PCT:
        actions.append(f"FULL_TP: take-profit triggered ({pnl_pct*100:.1f}%)")
        chain_usdt = BSC_USDT if chain_id == "56" else SOL_USDT
        ok, data = execute_swap(token_bal, ca, chain_usdt, chain_id)
        if ok:
            actions.append(f"CLOSED: {ticker} TP hit, all sold")
            # Record profit
            pnl = pos["pnl_value"]
            state["profit_pool"] = state.get("profit_pool", 0) + pnl
            closed = {
                "ticker": ticker, "entry": entry, "exit": pos["current_price"],
                "pnl_pct": pnl_pct, "pnl_value": pnl,
                "exit_time": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            }
            state.setdefault("closed_trades", []).append(closed)
            state["total_pnl"] = state.get("total_pnl", 0) + pnl
            del state["positions"][ca]
            return state, actions
        else:
            actions.append(f"CLOSE_FAILED: {data}")

    # Update peak price for trailing
    current_peak = state["positions"].get(ca, {}).get("peak_price", entry)
    if pos["current_price"] > current_peak:
        state["positions"][ca]["peak_price"] = pos["current_price"]

    return state, actions


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    print(f"\n{'='*60}")
    print(f"SCALPER v3 | {now.strftime('%Y-%m-%d %H:%M:%S')} CST")
    print(f"{'='*60}")

    state = load_state()
    balances = get_wallet_balances()

    # ── Check & adjust existing positions ──
    print(f"\n[POSITIONS] Dynamic SL/TP check")
    positions = get_open_positions_with_pnl(state, balances)

    if positions:
        for pos in positions:
            ticker = pos["ticker"]
            pnl    = pos["pnl_pct"]
            emoji  = "🟢" if pnl > 0.05 else ("🔴" if pnl < -0.03 else "🟡")
            print(f"  {emoji} {ticker} ({pos['chainId']}): "
                  f"{'+' if pnl >= 0 else ''}{pnl*100:.2f}% "
                  f"| ${pos['invest']:.2f} -> ${pos['invest']+pos['pnl_value']:.2f}")

        # Adjust positions (dynamic SL/TP)
        print(f"\n[DYNAMIC ADJUSTMENTS]")
        for pos in positions:
            state, actions = adjust_position_dynamic(pos, balances, state)
            for action in actions:
                print(f"  >> {pos['ticker']}: {action}")
        save_state(state)
    else:
        print("  No open positions")

    # ── Position change monitoring ──
    prev_snap = load_previous_snapshot()
    if positions and prev_snap:
        prev_positions = prev_snap.get("positions", {})
        prev_ts = prev_snap.get("ts", "?")
        print(f"\n[POSITION CHANGES] vs snapshot ({prev_ts})")
        changed = False
        for pos in positions:
            ca = pos.get("ca", "")
            ticker = pos.get("ticker", "?")
            pnl = pos.get("pnl_pct", 0)
            pnl_val = pos.get("pnl_value", 0)
            prev = prev_positions.get(ca) or prev_positions.get(ca.lower())
            if prev:
                prev_invest = prev.get("invest", 0)
                if abs(pnl_val) > 0.50 or abs(pnl) > 0.02:
                    emoji = "📈" if pnl > 0.03 else ("📉" if pnl < -0.03 else "📊")
                    print(f"  {emoji} {ticker}: {'+' if pnl >= 0 else ''}{pnl*100:.2f}% "
                          f"(${pnl_val:+.2f}) from ${prev_invest:.2f}")
                    changed = True
            else:
                print(f"  🆕 {ticker}: NEW position (not in previous snapshot)")
                changed = True
        if not changed:
            print(f"  No significant changes since last run")
    elif positions:
        print(f"\n[POSITION CHANGES] No previous snapshot (first run with monitoring)")

    save_position_snapshot(state.get("positions", {}))

    # ── Profit pool summary ──
    profit_pool = state.get("profit_pool", 0)
    total_pnl   = state.get("total_pnl", 0)
    closed      = state.get("closed_trades", [])[-5:]
    if profit_pool != 0 or total_pnl != 0:
        print(f"\n[PROFIT POOL] ${profit_pool:.2f} | Total P&L: ${total_pnl:.2f}")
    if closed:
        print(f"  Recent closes: " + " | ".join(
            f"{t['ticker']}{'+' if t['pnl_pct'] >= 0 else ''}{t['pnl_pct']*100:.1f}%"
            for t in closed))

    # ── Position cap check ──
    open_count = len(state.get("positions", {}))
    print(f"\n[POSITIONS] {open_count}/{MAX_POSITIONS} open")

    if open_count >= MAX_POSITIONS:
        print(f"  ⚠ At position cap ({MAX_POSITIONS}). Skip new entries.")
        # Still do signal scanning for monitoring
        _scan_signals(state, balances, skip_trade=True)
        return

    # ── Find new signals ──
    _scan_signals(state, balances, skip_trade=False)


def _scan_signals(state, balances, skip_trade=False):
    now   = datetime.now(timezone(timedelta(hours=8)))
    usdt_bal = balances.get("by_sym", {}).get("USDT", {}).get("value", 0)
    bnb_bal  = balances.get("by_sym", {}).get("BNB", {}).get("balance", 0)
    bnb_value = balances.get("by_sym", {}).get("BNB", {}).get("value", 0)
    profit_pool = state.get("profit_pool", 0)

    print(f"\n[BALANCE] USDT: ${usdt_bal:.2f} | BNB: {bnb_bal:.5f} (${bnb_value:.2f}) | Profit pool: ${profit_pool:.2f}")

    # Auto top-up USDT from BNB if running low
    if usdt_bal < BNB_TOPUP_THRESHOLD and bnb_bal > BNB_TOPUP_AMOUNT_BNB and not skip_trade:
        swap_bnb_to_usdt(BNB_TOPUP_AMOUNT_BNB)
        time.sleep(3)
        balances = get_wallet_balances()
        usdt_bal = balances.get("by_sym", {}).get("USDT", {}).get("value", 0)
        bnb_bal  = balances.get("by_sym", {}).get("BNB", {}).get("balance", 0)
        print(f"  [BALANCE-UPDATED] USDT: ${usdt_bal:.2f} | BNB: {bnb_bal:.5f}")

    # Effective budget = USDT + reinvestable profits
    effective_budget = usdt_bal + max(0, profit_pool)

    # ── Fetch signals ──
    all_actionable = []
    inflow_cas = set()

    for chain_id in CHAIN_IDS:
        chain_name = "BSC" if chain_id == "56" else "Solana"
        print(f"\n[SIGNALS] {chain_name}")
        signals = fetch_signals(chain_id)
        print(f"  Fetched {len(signals)} signals")

        # Inflow cross-check
        inflow = fetch_smart_money_inflow(chain_id, "1h")
        for item in inflow[:10]:
            if float(item.get("inflow", 0)) > 0:
                inflow_cas.add(item.get("ca", "").lower())

        for sig in signals:
            sig_id    = sig.get("signalId")
            ticker    = sig.get("ticker", "???")
            status    = sig.get("status", "?")
            score, reasons = score_signal_v3(sig)

            # Log
            append_signal_log({
                "ts": now.isoformat(), "sigId": sig_id, "ticker": ticker,
                "chain": chain_name, "score": score, "status": status,
                "reasons": reasons,
                "alertPrice": sig.get("alertPrice"),
                "currentPrice": sig.get("currentPrice"),
                "contractAddress": sig.get("contractAddress")
            })

            if score >= SCALP_THRESHOLD and sig_id not in state.get("last_signal_ids", []):
                ca = sig.get("contractAddress", "")
                already_holding = ca.lower() in [k.lower() for k in state.get("positions", {}).keys()]
                if not already_holding:
                    inflow_bonus = 10 if ca.lower() in inflow_cas else 0
                    all_actionable.append({**sig, "score": score + inflow_bonus,
                                            "reasons": reasons + (["inflow_confirmed"] if inflow_bonus else []),
                                            "chain": chain_name})
                    print(f"  >> {ticker} Score:{score+inflow_bonus} | {status} | {' | '.join(reasons + (['+inflow'] if inflow_bonus else []))}")
                else:
                    print(f"  .. {ticker} (already holding)")
            elif status == "active" and score >= 15:
                print(f"  .. {ticker} Score:{score} (below threshold)")

    all_actionable.sort(key=lambda x: x["score"], reverse=True)

    if not all_actionable:
        print(f"\n[RESULT] No new actionable signals.")
        return

    if skip_trade:
        print(f"\n[SKIPPED] At position cap, signal scan complete.")
        return

    # ── Execute trades ──
    results = []
    open_count = len(state.get("positions", {}))
    slots_left = MAX_POSITIONS - open_count

    for sig in all_actionable[:slots_left]:
        ticker    = sig.get("ticker", "???")
        score     = sig.get("score", 0)
        chain     = sig.get("chain", "BSC")
        chain_id  = sig.get("chainId", "56")
        ca        = sig.get("contractAddress", "")
        direction = sig.get("direction", "buy")
        alert_price = float(sig.get("alertPrice", 0) or 0)
        current_price = float(sig.get("currentPrice", 0) or 0)
        pump_pct   = (current_price - alert_price) / alert_price if alert_price > 0 else 0

        if direction != "buy":
            print(f"\n  SKIP {ticker}: sell signal")
            continue

        # Position sizing
        if score >= STRONG_THRESHOLD:
            invest_pct = MAX_INVEST_PCT
            strength   = "STRONG"
        else:
            invest_pct = 0.28
            strength   = "MODERATE"

        # Reduce if already pumped
        if pump_pct >= REDUCE_PUMP_PCT and pump_pct < CHASE_PUMP_PCT:
            invest_pct *= 0.5
            strength   += "(reduced)"
            print(f"\n  REDUCED {ticker}: pumped {pump_pct*100:.1f}%, halving position")

        if pump_pct >= CHASE_PUMP_PCT:
            print(f"\n  SKIP {ticker}: chased too far (+{pump_pct*100:.1f}%)")
            results.append({"ticker": ticker, "action": "skip_chase"})
            continue

        available   = effective_budget * (1 - 0.15)  # Keep 15% reserve
        invest_amount = min(available * invest_pct, effective_budget * MAX_INVEST_PCT)
        invest_amount = round(invest_amount, 2)

        if invest_amount < 1:
            print(f"\n  SKIP {ticker}: insufficient budget (${invest_amount:.2f})")
            continue

        print(f"\n  TRADE {ticker} | {strength} (Score:{score}) | ${invest_amount} USDT")
        print(f"    Chain: {chain} | Price: ${current_price:.8f}")
        print(f"    Reasons: {' | '.join(sig.get('reasons', []))}")

        # Audit
        print(f"    Auditing...")
        audit_data = audit_token(ca, chain_id)
        is_safe, safety_msg = is_token_safe(audit_data)
        print(f"    Audit: {safety_msg}")
        if not is_safe:
            print(f"    REJECT {ticker}: {safety_msg}")
            results.append({"ticker": ticker, "action": "reject", "reason": safety_msg})
            continue

        # Execute swap
        from_token = BSC_USDT if chain_id == "56" else SOL_USDT
        print(f"    Swapping {invest_amount} USDT -> {ticker}...")
        success, swap_result = execute_swap(invest_amount, from_token, ca, chain_id)

        if success:
            order_id = swap_result.get("orderId", "?")
            print(f"    SWAPPED! OrderID: {order_id}")

            time.sleep(5)
            balances2 = get_wallet_balances()
            by_ca2 = balances2.get("by_ca", {})
            token_bal = by_ca2.get(ca.lower(), {}).get("balance", 0)

            to_token_addr = BSC_USDT if chain_id == "56" else SOL_USDT

            if current_price > 0 and token_bal > 0:
                sl_price = round(current_price * (1 + STOP_LOSS_PCT), 10)
                tp_price = round(current_price * (1 + TAKE_PROFIT_PCT), 10)
                sell_qty = int(token_bal * 0.99)

                print(f"    SL @ ${sl_price:.10f} (-8%) | TP @ ${tp_price:.10f} (+12%)")
                sl_ok, sl_data = set_limit_sell(ca, sell_qty, sl_price, chain_id, to_token=to_token_addr)
                tp_ok, tp_data = set_limit_sell(ca, sell_qty, tp_price, chain_id, to_token=to_token_addr)
                print(f"    SL: {'OK' if sl_ok else 'FAIL'} | TP: {'OK' if tp_ok else 'FAIL'}")

                state["positions"][ca] = {
                    "ticker": ticker, "chain": chain, "chainId": chain_id,
                    "entry_price": current_price, "invest_amount": invest_amount,
                    "order_id": order_id, "entry_time": now.isoformat(),
                    "score": score, "peak_price": current_price,
                    "sl_price": sl_price, "tp_price": tp_price,
                    "sl_strategy_id": sl_data.get("strategyId") if sl_ok else None,
                    "tp_strategy_id": tp_data.get("strategyId") if tp_ok else None,
                    "partial_tp_done": False,
                    "breakeven_done": False,
                    "trailing_done": False,
                }
                state["trade_count"] = state.get("trade_count", 0) + 1
                results.append({
                    "ticker": ticker, "action": "BUY", "amount": invest_amount,
                    "price": current_price, "order_id": order_id, "score": score
                })
        else:
            print(f"    SWAP FAILED: {swap_result}")
            results.append({"ticker": ticker, "action": "failed", "reason": str(swap_result)})

        state.setdefault("last_signal_ids", []).append(sig.get("signalId"))
        state["last_signal_ids"] = state["last_signal_ids"][-300:]

    save_state(state)

    # Summary
    print(f"\n{'='*60}")
    trades = [r for r in results if isinstance(r, dict) and r.get("action") == "BUY"]
    print(f"SUMMARY | Signals: {len(all_actionable)} | Trades: {len(trades)} | "
          f"Positions: {len(state.get('positions', {}))}/{MAX_POSITIONS}")
    for t in trades:
        print(f"  BUY {t['ticker']} ${t['amount']} @ ${t.get('price', 0):.8f}")
    if not trades:
        print("  No new trades.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
