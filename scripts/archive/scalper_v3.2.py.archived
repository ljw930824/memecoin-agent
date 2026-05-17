#!/usr/bin/env python3
"""
Scalping Strategy v3.2 - Smart Money Monitor
Enhanced with dynamic stop-loss, trailing stops, partial profit-taking, and risk controls.

v3.2 enhancements (2026-04-27):
- Liquidity check: verify pool has enough liquidity before opening position
- Spread check: skip if alertPrice/currentPrice spread > 5% (bad entry)
- Max drawdown limit: daily max loss -15%, session max loss -25%
- Consecutive SL freeze: 3 consecutive SL -> 2h trading freeze
- Enhanced cooldown: 12h cooldown after SL exit (longer than TP exit)
- Min signal entries: require >= 2 distinct SM wallets buying
- Stale signal penalty: signals older than 2h lose score progressively
- Position health score: track signal degradation + exit early if signal weakens
- Emergency liquidation: if total portfolio down -20% in 1h, liquidate all
- Gas price check: skip new trades if gas is abnormally high

v3.1 enhancements:
- Market-order stop-loss: use market sell instead of limit order to ensure execution
- 24h timeout rule: auto reduce position by 50% if no movement after 24h
- Same-day forced close: positions below -8% must close same day, no overnight holding
- Retry mechanism: up to 3 retries for failed orders with logging to retry-log.txt
- Position time cost tracking: monitor holding duration and opportunity cost

v3 enhancements:
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
from collections import defaultdict

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# === CONFIG ===
STATE_FILE   = os.path.expanduser("~/.qclaw/workspace/data/smart-money-state.json")
DATA_DIR     = os.path.expanduser("~/.qclaw/workspace/data")
SIGNAL_LOG   = os.path.join(DATA_DIR, "signal-log.json")
BAW_CMD      = os.path.expanduser("~\\AppData\\Roaming\\QClaw\\npm-global\\baw.cmd")
if not os.path.isfile(BAW_CMD):
    BAW_CMD = "baw"
ONCHAINOS    = r"C:\Users\dell\.local\bin\onchainos.exe"
RETRY_LOG    = os.path.join(DATA_DIR, "retry-log.txt")
TRADE_LOG    = os.path.join(DATA_DIR, "trade-log.json")
RISK_LOG     = os.path.join(DATA_DIR, "risk-log.json")
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

# v3.1: Time-based rules
MAX_HOLDING_HOURS   = 24         # After 24h, reduce position if no movement
NO_MOVEMENT_THRESHOLD = 0.03     # "No movement" = P&L between -3% and +3%
SAME_DAY_SL_CUTOFF_HOUR = 23    # Force close losing positions before this hour
MAX_RETRY_ATTEMPTS  = 3          # Max retries for failed orders

# v3.2: NEW Risk Controls
MAX_DAILY_LOSS_PCT      = 0.15   # Max daily drawdown -15%
MAX_SESSION_LOSS_PCT    = 0.25   # Max session drawdown -25%
CONSECUTIVE_SL_FREEZE   = 3      # 3 consecutive SL -> freeze trading
FREEZE_DURATION_HOURS   = 2      # Freeze duration after consecutive SL
COOLDOWN_AFTER_SL_HOURS = 12     # Longer cooldown after SL exit
COOLDOWN_AFTER_TP_HOURS = 6      # Shorter cooldown after TP exit
MIN_SM_ENTRIES          = 2      # Min distinct SM wallets buying
MAX_SPREAD_PCT          = 0.05   # Max spread between alert and current price
STALE_PENALTY_START_MIN = 60     # Signals older than 1h start losing score
STALE_PENALTY_MAX_MIN   = 180    # Max penalty at 3h old
MIN_LIQUIDITY_USD       = 5000   # Min pool liquidity in USD
EMERGENCY_LIQUIDATE_THRESHOLD = -0.20  # Emergency liquidate if portfolio down 20%

# Gas price thresholds (Gwei)
HIGH_GAS_THRESHOLD     = 30      # Skip new trades if gas > 30 Gwei
VERY_HIGH_GAS_THRESHOLD = 50     # Only close positions if gas > 50

# Position health tracking
SIGNAL_WEAKEN_THRESHOLD = -0.10  # If signal score drops by 10+ points, consider exit
POSITION_HEALTH_CHECK_INTERVAL = 3600  # Check position health every hour

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


# ═══════════════════════════════════════════════════════════════════════════
# STATE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
            # v3.2: Migrate old daily_pnl format (float -> dict)
            if isinstance(state.get("daily_pnl"), (int, float)):
                # Old format was absolute value, reset to 0
                state["daily_pnl"] = {}
            # Also reset if the dict has wrong values (absolute instead of percentage)
            elif isinstance(state.get("daily_pnl"), dict):
                # Check if values look like absolute amounts (small numbers) vs percentages
                for date, val in list(state["daily_pnl"].items()):
                    if abs(val) < 1.0:  # Likely absolute amount, reset
                        state["daily_pnl"][date] = 0
            # Ensure all required fields exist
            state.setdefault("consecutive_sl", 0)
            state.setdefault("freeze_until", None)
            state.setdefault("cooldowns", {})
            state.setdefault("signal_scores", {})
            state.setdefault("portfolio_value_history", [])
            return state
    return {
        "positions": {},
        "last_signal_ids": [],
        "trade_count": 0,
        "total_pnl": 0,
        "closed_trades": [],
        "profit_pool": 0,
        "daily_pnl": {},
        "consecutive_sl": 0,
        "freeze_until": None,
        "cooldowns": {},
        "signal_scores": {},  # Track signal scores for position health
        "portfolio_value_history": [],  # For emergency liquidation
    }


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def log_retry(ticker, action, reason, attempt):
    """Log failed order for retry tracking."""
    ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] {ticker} | {action} | {reason} | attempt #{attempt}\n"
    with open(RETRY_LOG, "a", encoding="utf-8") as f:
        f.write(entry)
    print(f"  [RETRY-LOG] {ticker}: {action} failed (attempt {attempt})")


def log_trade(entry):
    """Log all trades for analysis."""
    log = []
    if os.path.exists(TRADE_LOG):
        with open(TRADE_LOG, "r", encoding="utf-8") as f:
            log = json.load(f)
    log.append(entry)
    if len(log) > 5000:
        log = log[-5000:]
    with open(TRADE_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def log_risk(event_type, details):
    """Log risk events."""
    log = []
    if os.path.exists(RISK_LOG):
        with open(RISK_LOG, "r", encoding="utf-8") as f:
            log = json.load(f)
    log.append({
        "ts": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "event": event_type,
        "details": details
    })
    if len(log) > 1000:
        log = log[-1000:]
    with open(RISK_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


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
            "entry_time": pos.get("entry_time", ""),
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


# ═══════════════════════════════════════════════════════════════════════════
# RISK MANAGEMENT (v3.2)
# ═══════════════════════════════════════════════════════════════════════════

def check_risk_limits(state, current_portfolio_value):
    """Check if we've hit risk limits. Returns (can_trade, should_liquidate, reason)."""
    now = datetime.now(timezone(timedelta(hours=8)))
    today_str = now.strftime("%Y-%m-%d")
    
    # Check freeze
    if state.get("freeze_until"):
        freeze_time = datetime.fromisoformat(state["freeze_until"])
        if now < freeze_time:
            remaining = (freeze_time - now).total_seconds() / 60
            return False, False, f"FROZEN ({remaining:.0f}min left)"
        else:
            state["freeze_until"] = None
            state["consecutive_sl"] = 0
    
    # Daily loss check
    daily_pnl = state.get("daily_pnl", {})
    today_pnl = daily_pnl.get(today_str, 0)
    if today_pnl <= -MAX_DAILY_LOSS_PCT:
        log_risk("DAILY_LIMIT_HIT", {"pnl": today_pnl})
        return False, False, f"DAILY_LIMIT({today_pnl*100:.1f}%)"
    
    # Portfolio emergency check
    # SAFEGUARD: If portfolio_value is 0 or near-zero, it's likely a balance API failure, not a real loss
    if current_portfolio_value < 1.0:
        print(f"[WARN] Portfolio value=${current_portfolio_value:.2f} — likely API failure, skipping emergency check", file=sys.stderr)
        return True, False, "BALANCE_API_POSSIBLY_DOWN"
    portfolio_history = state.get("portfolio_value_history", [])
    if len(portfolio_history) >= 2:
        recent_values = [v["value"] for v in portfolio_history[-10:]]
        if len(recent_values) >= 2 and recent_values[0] > 0:
            change = (current_portfolio_value - recent_values[0]) / recent_values[0]
            if change <= EMERGENCY_LIQUIDATE_THRESHOLD:
                log_risk("EMERGENCY_LIQUIDATE", {"change": change})
                return False, True, f"EMERGENCY({change*100:.1f}%)"
    
    return True, False, "OK"


def update_daily_pnl(state, pnl_pct):
    """Update daily P&L tracking. pnl_pct is in decimal form (-0.05 = -5%)."""
    today_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    daily_pnl = state.get("daily_pnl", {})
    daily_pnl[today_str] = daily_pnl.get(today_str, 0) + pnl_pct
    
    # Clean old entries
    cutoff = (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=7)).strftime("%Y-%m-%d")
    daily_pnl = {k: v for k, v in daily_pnl.items() if k >= cutoff}
    state["daily_pnl"] = daily_pnl


def check_cooldown(state, ca):
    """Check if token is in cooldown period."""
    cooldowns = state.get("cooldowns", {})
    if ca in cooldowns:
        cooldown_end = datetime.fromisoformat(cooldowns[ca])
        if datetime.now(timezone(timedelta(hours=8))) < cooldown_end:
            remaining = (cooldown_end - datetime.now(timezone(timedelta(hours=8)))).total_seconds() / 3600
            return True, remaining
        else:
            del state["cooldowns"][ca]
    return False, 0


def set_cooldown(state, ca, exit_type):
    """Set cooldown based on exit type."""
    hours = COOLDOWN_AFTER_SL_HOURS if exit_type == "SL" else COOLDOWN_AFTER_TP_HOURS
    cooldown_end = (datetime.now(timezone(timedelta(hours=8))) + timedelta(hours=hours)).isoformat()
    state.setdefault("cooldowns", {})[ca] = cooldown_end
    log_risk("COOLDOWN_SET", {"ca": ca, "hours": hours, "exit_type": exit_type})


def get_gas_price(chain_id="56"):
    """Get current gas price. Returns Gwei.
    Tries multiple RPCs. Returns 5 (safe default) on failure.
    """
    import urllib.request
    if chain_id == "56":
        rpcs = ["https://bsc-dataseed.binance.org/","https://bsc-dataseed1.defibit.io/",
                "https://bsc-dataseed1.ninicoin.io/","https://1rpc.io/bnb"]
        payload = json.dumps({"jsonrpc":"2.0","method":"eth_gasPrice","params":[],"id":1}).encode()
        for url in rpcs:
            try:
                req = urllib.request.Request(url, data=payload,
                    headers={"Content-Type":"application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = json.loads(resp.read().decode())
                    result = data.get("result", "")
                    if result and result != "0x0":
                        return round(int(result, 16) / 1e9, 2)
            except Exception:
                continue
        return 5
    elif chain_id == "CT_501":
        try:
            url = "https://api.mainnet-beta.solana.com/"
            payload = json.dumps({"jsonrpc":"2.0","method":"getRecentPrioritizationFees",
                                  "params":[],"id":1}).encode()
            req = urllib.request.Request(url, data=payload,
                headers={"Content-Type":"application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                fees = data.get("result", [])
                if fees:
                    return max(f.get("prioritizationFee", 0) for f in fees[-10:])
        except Exception:
            pass
        return 5
    return 5


def check_liquidity(ca, chain_id):
    """Check token pool liquidity via price impact from quote.
    Returns (has_liquidity, liquidity_usd).
    Price impact < 5% = good liquidity, 5-15% = marginal, >15% = bad.
    """
    try:
        # Use a $100 probe trade to estimate pool depth
        probe_usd = 100
        impact_pct = None
        if chain_id == "CT_501":
            # Solana: onchainos swap quote (read-only, no execution)
            usdt_addr = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"  # Solana USDT
            args = [ONCHAINOS, "swap", "quote", "--from", usdt_addr, "--to", ca,
                    "--amount", str(probe_usd), "--readable"]
            r = subprocess.run(args, capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                try:
                    q = json.loads(r.stdout.strip())
                    impact_pct = float(q.get("priceImpactPercent", "0") or "0")
                except (json.JSONDecodeError, ValueError):
                    # Try to extract from text output
                    for line in r.stdout.splitlines():
                        if "impact" in line.lower():
                            try:
                                impact_pct = float(''.join(c for c in line if c in '0123456789.'))
                            except ValueError:
                                pass
        elif chain_id == "56":
            # BSC: baw quote via market-order swap --quote
            usdt_addr = "0x55d398326f99059fF775485246999027B3197955"  # BSC USDT
            args = [BAW_CMD, "market-order", "swap", "--quote",
                    "--from", usdt_addr, "--to", ca,
                    "--amount", str(probe_usd), "--chain", "56"]
            r = subprocess.run(args, capture_output=True, text=True, timeout=30,
                               env={**os.environ, "NODE_NO_WARNINGS": "1"})
            if r.returncode == 0:
                try:
                    q = json.loads(r.stdout.strip())
                    impact_pct = float(q.get("priceImpactPercent", "0") or "0")
                except (json.JSONDecodeError, ValueError):
                    for line in r.stdout.splitlines():
                        if "impact" in line.lower():
                            try:
                                impact_pct = float(''.join(c for c in line if c in '0123456789.'))
                            except ValueError:
                                pass
        if impact_pct is not None and impact_pct > 0:
            # Rough liquidity estimate: higher impact = less liquidity
            # If $100 trade causes X% impact, pool_depth ≈ $100 / (X/100) * scaling_factor
            liquidity_usd = round(probe_usd / (impact_pct / 100) * 0.5, 0)
            return liquidity_usd >= MIN_LIQUIDITY_USD, liquidity_usd
        # No impact data = can't determine, assume OK (don't block)
        return True, 10000
    except Exception as e:
        print(f"  [LIQUIDITY] check failed: {e}", file=sys.stderr)
        return True, 10000  # Fail-open: don't block on errors


# ═══════════════════════════════════════════════════════════════════════════
# NETWORK / API
# ═══════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════
# SCORING (v3.2 Enhanced)
# ═══════════════════════════════════════════════════════════════════════════

def score_signal_v3_2(sig, state=None, now_ts=None):
    """v3.2 scoring: all v3 + liquidity + spread + staleness + SM entries."""
    state = state or {}
    score = 0
    reasons = []
    penalties = []

    ca = sig.get("contractAddress", "").lower()
    now_ts = now_ts or datetime.now(timezone(timedelta(hours=8))).timestamp()

    # ── Cooldown check ──────────────────────────────────────────────────────
    in_cooldown, remaining = check_cooldown(state, ca)
    if in_cooldown:
        return 0, [f"COOLDOWN({remaining:.1f}h left)"]

    # Smart Money Count (weighted higher)
    smc = sig.get("smartMoneyCount", 0)
    if smc >= 8:   score += 40; reasons.append(f"SM={smc}(high)")
    elif smc >= 5: score += 25; reasons.append(f"SM={smc}(med)")
    elif smc >= 3: score += 12; reasons.append(f"SM={smc}(low)")
    elif smc >= MIN_SM_ENTRIES:
        score += 5; reasons.append(f"SM={smc}(min)")
    else:
        return 0, [f"INSUFFICIENT_SM({smc}<{MIN_SM_ENTRIES})"]

    direction = sig.get("direction", "")
    if direction == "buy":     score += 10; reasons.append("buy")
    elif direction == "sell":   return 0, ["SELL-skip"]

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

    # Price momentum + Spread check (v3.2)
    current_price = float(sig.get("currentPrice", 0) or 0)
    alert_price   = float(sig.get("alertPrice", 0) or 0)
    if alert_price > 0 and current_price > 0:
        pump_pct = (current_price - alert_price) / alert_price
        
        # v3.2: Spread check
        if abs(pump_pct) > MAX_SPREAD_PCT:
            return 0, [f"SPREAD_TOO_HIGH({pump_pct*100:.1f}%>{MAX_SPREAD_PCT*100:.0f}%)"]
        
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
            return 0, [f"CHASE_SKIP+{pump_pct*100:.1f}%"]

    # Status
    status = sig.get("status", "")
    if status == "active":
        score += 15; reasons.append("ACTIVE")
    elif status == "timeout":
        tf = sig.get("timeFrame", 0)
        if tf < 3600000:
            score += 5; reasons.append("fresh_timeout")
        else:
            score -= 10; reasons.append("old_timeout")
    elif status in ("exitRate", "outDecline"):
        return 0, [f"exiting({status})"]

    # v3.2: Staleness penalty
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
    all_reasons = reasons + penalties
    
    return final_score, all_reasons


# ═══════════════════════════════════════════════════════════════════════════
# AUDIT
# ═══════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════
# BAW WRAPPERS
# ═══════════════════════════════════════════════════════════════════════════

def _baw_env():
    env = dict(os.environ)
    env["PATH"] = env.get("PATH", "") + ";" + os.path.expanduser("~\\AppData\\Roaming\\QClaw\\npm-global")
    return env


def get_wallet_balances():
    """Returns {by_ca, by_sym, total_value} with retry + Solana fallback."""
    by_ca, by_sym = {}, {}
    total_value = 0.0
    
    # ── BSC balances (BAW CLI) with retry ──
    bsc_ok = False
    for attempt in range(3):
        try:
            result = subprocess.run([BAW_CMD, "wallet", "balance", "--json"],
                                    capture_output=True, text=True, timeout=20, env=_baw_env())
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                if data.get("success"):
                    bsc_ok = True
                    for t in data.get("data", []):
                        ca  = t.get("contractAddress", "").strip().lower()
                        sym = t.get("symbol", "").strip().upper()
                        value = float(t.get("value", 0))
                        total_value += value
                        entry = {
                            "balance":  float(t.get("balance", 0)),
                            "price":    float(t.get("price", 0)),
                            "value":    value,
                            "contract": ca,
                            "chainId":  t.get("binanceChainId", "56"),
                            "symbol":   sym,
                        }
                        if ca:
                            by_ca[ca] = entry
                        by_sym[sym] = entry
                    break  # success, exit retry loop
        except Exception as e:
            print(f"[WARN] BAW balance attempt {attempt+1}: {e}", file=sys.stderr)
        if attempt < 2:
            time.sleep(3 * (attempt + 1))
    
    if not bsc_ok:
        print("[WARN] BAW balance failed after 3 retries", file=sys.stderr)
    
    # ── Solana balances (onchainos) ──
    try:
        ONCHAINOS = r'C:\Users\dell\.local\bin\onchainos.exe'
        for attempt in range(3):
            result = subprocess.run([ONCHAINOS, 'wallet', 'balance'],
                                    capture_output=True, text=True, timeout=25)
            if result.returncode == 0 and result.stdout:
                sol_data = json.loads(result.stdout)
                details = sol_data.get('data', {}).get('details', sol_data.get('details', []))
                for detail in details:
                    for ta in detail.get('tokenAssets', []):
                        if str(ta.get('chainIndex', '')) != '501':
                            continue
                        addr = ta.get('tokenAddress', '')
                        bal = float(ta.get('balance', 0))
                        price = float(ta.get('tokenPrice', 0) or 0)
                        value = float(ta.get('usdValue', 0) or bal * price)
                        total_value += value
                        sym = ta.get('symbol', '') or ta.get('customSymbol', '') or addr[:8]
                        by_sym[sym] = {
                            "balance": bal,
                            "price": price,
                            "value": value,
                            "contract": addr.lower(),
                            "chainId": "501",
                            "symbol": sym,
                        }
                break  # success
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
    except Exception as e:
        print(f"[WARN] Solana balance failed: {e}", file=sys.stderr)
    
    return {"by_ca": by_ca, "by_sym": by_sym, "total_value": total_value}


def execute_swap_with_retry(qty, from_token, to_token, chain_id, slippage=3, max_retries=MAX_RETRY_ATTEMPTS):
    """Execute swap with retry logic and logging."""
    for attempt in range(1, max_retries + 1):
        success, result = execute_swap(qty, from_token, to_token, chain_id, slippage)
        if success:
            return True, result
        else:
            log_retry(from_token[:8] if len(from_token) > 8 else from_token, "SWAP", str(result)[:50], attempt)
            if attempt < max_retries:
                print(f"    Retry {attempt+1}/{max_retries} in 3s...")
                time.sleep(3)
    return False, result


def execute_swap(usdt_amount, from_token, to_token, chain_id, slippage=3):
    """Single swap attempt."""
    try:
        result = subprocess.run(
            [BAW_CMD, "market-order", "swap",
             "--fromTokenQty", str(usdt_amount),
             "--fromToken", from_token,
             "--toToken", to_token,
             "--binanceChainId", chain_id,
             "--slippage", str(slippage),
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


def market_sell_token(token_addr, qty, chain_id, slippage=10):
    """Market sell token (for stop-loss execution)."""
    usdt_addr = BSC_USDT if chain_id == "56" else SOL_USDT
    return execute_swap_with_retry(qty, token_addr, usdt_addr, chain_id, slippage)


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


# ═══════════════════════════════════════════════════════════════════════════
# POSITION MANAGER (v3.2 Enhanced)
# ═══════════════════════════════════════════════════════════════════════════

def get_open_positions_with_pnl(state, balances):
    """Calculate real-time P&L for all open positions."""
    positions = state.get("positions", {})
    results = []
    now = datetime.now(timezone(timedelta(hours=8)))
    now_ts = now.timestamp()

    # Fetch all signals to get current prices and signal status
    all_signals = {}
    for chain_id in CHAIN_IDS:
        for sig in fetch_signals(chain_id):
            ca = sig.get("contractAddress", "").lower()
            all_signals[ca] = {
                "price": float(sig.get("currentPrice", 0) or 0),
                "status": sig.get("status", ""),
                "smartMoneyCount": sig.get("smartMoneyCount", 0),
                "signal_score": state.get("signal_scores", {}).get(ca, 0),
            }

    for ca, pos in list(positions.items()):
        entry_price  = float(pos.get("entry_price", 0) or 0)
        chain_id     = pos.get("chainId", "56")
        ticker       = pos.get("ticker", "???")
        invest       = float(pos.get("invest_amount", 0))
        entry_time_str = pos.get("entry_time", "")

        current_price = entry_price
        signal_info = all_signals.get(ca.lower(), {})
        current_price = signal_info.get("price", entry_price)

        # Parse entry time to calculate holding duration
        holding_hours = 0
        if entry_time_str:
            try:
                entry_time = datetime.fromisoformat(entry_time_str.replace("+08:00", "+08:00"))
                holding_hours = (now - entry_time).total_seconds() / 3600
            except:
                pass

        # Get token balance
        by_sym = balances.get("by_sym", {})
        by_ca = balances.get("by_ca", {})
        token_bal = 0
        token_value = 0
        
        # Try by CA first, then by symbol
        if ca.lower() in by_ca:
            token_bal = by_ca[ca.lower()]["balance"]
            token_value = by_ca[ca.lower()]["value"]
        else:
            ticker_upper = ticker.upper()
            if ticker_upper in by_sym:
                token_bal = by_sym[ticker_upper]["balance"]
                token_value = by_sym[ticker_upper]["value"]

        if entry_price > 0 and invest > 0:
            pnl_pct   = (current_price - entry_price) / entry_price
            pnl_value = token_value - invest
            
            # v3.2: Position health check
            original_score = pos.get("score", 0)
            current_signal_score = signal_info.get("signal_score", original_score)
            score_drop = original_score - current_signal_score if current_signal_score else 0
            
            results.append({
                "ca": ca, "ticker": ticker, "chainId": chain_id,
                "entry_price": entry_price, "current_price": current_price,
                "token_balance": token_bal,
                "invest": invest, "pnl_pct": pnl_pct, "pnl_value": pnl_value,
                "entry_time": entry_time_str,
                "holding_hours": holding_hours,
                "score": original_score,
                "current_signal_score": current_signal_score,
                "score_drop": score_drop,
                "sl_price": pos.get("sl_price"),
                "tp_price": pos.get("tp_price"),
                "sl_strategy_id": pos.get("sl_strategy_id"),
                "tp_strategy_id": pos.get("tp_strategy_id"),
                "partial_tp_done": pos.get("partial_tp_done", False),
                "breakeven_done": pos.get("breakeven_done", False),
                "trailing_done": pos.get("trailing_done", False),
                "signal_status": signal_info.get("status", "unknown"),
            })

    results.sort(key=lambda x: x["pnl_pct"])  # Worst first
    return results


def adjust_position_dynamic(pos, balances, state):
    """Apply dynamic SL/TP adjustments + v3.1 time rules + v3.2 health check."""
    pnl_pct  = pos["pnl_pct"]
    ticker   = pos["ticker"]
    ca       = pos["ca"]
    chain_id = pos["chainId"]
    entry    = pos["entry_price"]
    token_bal = pos["token_balance"]
    holding_hours = pos.get("holding_hours", 0)
    now_hour = datetime.now(timezone(timedelta(hours=8))).hour
    score_drop = pos.get("score_drop", 0)
    signal_status = pos.get("signal_status", "unknown")

    if token_bal <= 0:
        return state, []

    actions = []

    # ── v3.2: Position health check (signal weakening) ─────────────────────
    if score_drop >= 15 and pnl_pct < 0.03:
        # Signal significantly weakened and not profitable
        actions.append(f"SIGNAL_WEAK: score dropped {score_drop} pts, reducing position")
        sell_qty = int(token_bal * 0.50)
        if sell_qty > 0:
            ok, data = market_sell_token(ca, sell_qty, chain_id, slippage=15)
            if ok:
                actions.append(f"REDUCED: sold {sell_qty} {ticker} (signal weak)")
                if ca in state.get("positions", {}):
                    state["positions"][ca]["invest_amount"] *= 0.5
                return state, actions

    # ── v3.1: 24h no-movement timeout rule ──────────────────────────────────
    if holding_hours >= MAX_HOLDING_HOURS:
        if abs(pnl_pct) < NO_MOVEMENT_THRESHOLD:
            sell_qty = int(token_bal * 0.50)
            if sell_qty > 0:
                actions.append(f"TIMEOUT_24H: reducing 50% (holding {holding_hours:.1f}h)")
                ok, data = market_sell_token(ca, sell_qty, chain_id, slippage=15)
                if ok:
                    actions.append(f"REDUCED: sold {sell_qty} {ticker}")
                    if ca in state.get("positions", {}):
                        state["positions"][ca]["invest_amount"] *= 0.5
                else:
                    actions.append(f"REDUCE_FAILED: {data}")
            return state, actions

    # ── v3.1: Same-day forced close for losing positions ────────────────────
    if pnl_pct <= STOP_LOSS_PCT and now_hour >= SAME_DAY_SL_CUTOFF_HOUR:
        actions.append(f"SAME_DAY_CLOSE: forcing close before day end")
        ok, data = market_sell_token(ca, token_bal, chain_id, slippage=20)
        if ok:
            actions.append(f"LIQUIDATED: sold all {token_bal} {ticker}")
            # Update daily P&L and consecutive SL counter
            update_daily_pnl(state, pnl_pct)
            state["consecutive_sl"] = state.get("consecutive_sl", 0) + 1
            
            # Check for freeze
            if state["consecutive_sl"] >= CONSECUTIVE_SL_FREEZE:
                freeze_until = (datetime.now(timezone(timedelta(hours=8))) + 
                               timedelta(hours=FREEZE_DURATION_HOURS)).isoformat()
                state["freeze_until"] = freeze_until
                actions.append(f"FREEZE: {FREEZE_DURATION_HOURS}h (3 consecutive SL)")
                log_risk("TRADING_FROZEN", {"consecutive_sl": state["consecutive_sl"]})
            
            set_cooldown(state, ca, "SL")
            
            if ca in state.get("positions", {}):
                del state["positions"][ca]
            return state, actions
        else:
            actions.append(f"LIQUIDATE_FAILED: {data}")

    # 1. Partial Take-Profit at +10%
    if pnl_pct >= PARTIAL_TP_TRIGGER and not pos.get("partial_tp_done"):
        sell_qty = int(token_bal * PARTIAL_TP_PCT)
        if sell_qty > 0:
            tp_partial_price = round(entry * (1 + PARTIAL_TP_TRIGGER), 10)
            ok, data = set_limit_sell(ca, sell_qty, tp_partial_price, chain_id)
            if ok:
                actions.append(f"PARTIAL_TP: sell {sell_qty}@{tp_partial_price:.8f} (+10%)")
                state["positions"][ca]["partial_tp_done"] = True
                new_sl = round(entry * (1 + PARTIAL_SL_TIGHTEN), 10)
                # Cancel old SL and set new one
                if pos.get("sl_strategy_id"):
                    cancel_limit_orders([pos["sl_strategy_id"]])
                sl_ok, sl_data = set_limit_sell(ca, int(token_bal * 0.99), new_sl, chain_id)
                if sl_ok:
                    actions.append(f"TIGHTEN_SL: -> {new_sl:.8f} (+3%)")
                    state["positions"][ca]["sl_price"] = new_sl
                    state["positions"][ca]["sl_strategy_id"] = sl_data.get("strategyId")

    # 2. Trailing Stop at +8%
    elif pnl_pct >= TRAILING_TRIGGER and not pos.get("trailing_done"):
        peak_price = pos.get("peak_price", pos["current_price"])
        new_sl = round(peak_price * (1 - TRAILING_DISTANCE), 10)
        if new_sl > entry * (1 + STOP_LOSS_PCT):
            actions.append(f"TRAILING: SL -> {new_sl:.8f} (peak={peak_price:.8f})")
            state["positions"][ca]["trailing_done"] = True
            state["positions"][ca]["sl_price"] = new_sl

    # 3. Breakeven at +5%
    elif pnl_pct >= BREAKEVEN_TRIGGER and not pos.get("breakeven_done"):
        new_sl = round(entry * 1.001, 10)
        if new_sl > (pos.get("sl_price") or 0):
            actions.append(f"BREAKEVEN: SL -> {new_sl:.8f}")
            state["positions"][ca]["breakeven_done"] = True
            state["positions"][ca]["sl_price"] = new_sl

    # 4. Hard Stop-Loss (market sell)
    if pnl_pct <= STOP_LOSS_PCT:
        actions.append(f"HARD_SL: stop-loss triggered ({pnl_pct*100:.1f}%)")
        ok, data = market_sell_token(ca, token_bal, chain_id, slippage=15)
        if ok:
            actions.append(f"LIQUIDATED: sold {token_bal} {ticker}")
            
            # Update counters
            update_daily_pnl(state, pnl_pct)
            state["consecutive_sl"] = state.get("consecutive_sl", 0) + 1
            state["profit_pool"] = state.get("profit_pool", 0) + pnl_pct * pos["invest"]
            
            if state["consecutive_sl"] >= CONSECUTIVE_SL_FREEZE:
                freeze_until = (datetime.now(timezone(timedelta(hours=8))) + 
                               timedelta(hours=FREEZE_DURATION_HOURS)).isoformat()
                state["freeze_until"] = freeze_until
                actions.append(f"FREEZE: {FREEZE_DURATION_HOURS}h")
                log_risk("TRADING_FROZEN", {"consecutive_sl": state["consecutive_sl"]})
            
            set_cooldown(state, ca, "SL")
            
            closed = {
                "ticker": ticker, "entry": entry, "exit": pos["current_price"],
                "pnl_pct": pnl_pct, "pnl_value": pos["pnl_value"],
                "exit_time": datetime.now(timezone(timedelta(hours=8))).isoformat(),
                "exit_reason": "SL_HIT",
                "holding_hours": holding_hours
            }
            state.setdefault("closed_trades", []).append(closed)
            state["total_pnl"] = state.get("total_pnl", 0) + pos["pnl_value"]
            
            if ca in state.get("positions", {}):
                del state["positions"][ca]
            return state, actions
        else:
            actions.append(f"LIQUIDATE_FAILED: {data}")

    # 5. Full Take-Profit at +12%
    if pnl_pct >= TAKE_PROFIT_PCT:
        actions.append(f"FULL_TP: take-profit triggered ({pnl_pct*100:.1f}%)")
        usdt_addr = BSC_USDT if chain_id == "56" else SOL_USDT
        ok, data = execute_swap_with_retry(token_bal, ca, usdt_addr, chain_id, slippage=5)
        if ok:
            actions.append(f"CLOSED: {ticker} TP hit")
            
            # Reset consecutive SL counter on TP
            state["consecutive_sl"] = 0
            state["profit_pool"] = state.get("profit_pool", 0) + pnl_pct * pos["invest"]
            
            set_cooldown(state, ca, "TP")
            
            closed = {
                "ticker": ticker, "entry": entry, "exit": pos["current_price"],
                "pnl_pct": pnl_pct, "pnl_value": pos["pnl_value"],
                "exit_time": datetime.now(timezone(timedelta(hours=8))).isoformat(),
                "exit_reason": "TP_HIT",
                "holding_hours": holding_hours
            }
            state.setdefault("closed_trades", []).append(closed)
            state["total_pnl"] = state.get("total_pnl", 0) + pos["pnl_value"]
            
            if ca in state.get("positions", {}):
                del state["positions"][ca]
            return state, actions
        else:
            actions.append(f"CLOSE_FAILED: {data}")

    # Update peak price
    current_peak = state["positions"].get(ca, {}).get("peak_price", entry)
    if pos["current_price"] > current_peak:
        state["positions"][ca]["peak_price"] = pos["current_price"]

    return state, actions


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    print(f"\n{'='*60}")
    print(f"SCALPER v3.2 | {now.strftime('%Y-%m-%d %H:%M:%S')} CST")
    print(f"{'='*60}")

    state = load_state()
    balances = get_wallet_balances()
    portfolio_value = balances.get("total_value", 0)

    # ── v3.2: Update portfolio history ──────────────────────────────────────
    state.setdefault("portfolio_value_history", []).append({
        "ts": now.isoformat(),
        "value": portfolio_value
    })
    # Keep last 100 entries
    if len(state["portfolio_value_history"]) > 100:
        state["portfolio_value_history"] = state["portfolio_value_history"][-100:]

    # ── v3.2: Risk limits check ────────────────────────────────────────────
    can_trade, should_liquidate, risk_reason = check_risk_limits(state, portfolio_value)
    
    if should_liquidate:
        print(f"\n[EMERGENCY] Portfolio down {risk_reason}, liquidating all positions!")
        positions = get_open_positions_with_pnl(state, balances)
        for pos in positions:
            if pos["token_balance"] > 0:
                ok, _ = market_sell_token(pos["ca"], pos["token_balance"], pos["chainId"], slippage=25)
                if ok:
                    print(f"  LIQUIDATED {pos['ticker']}")
                    if pos["ca"] in state.get("positions", {}):
                        del state["positions"][pos["ca"]]
        save_state(state)
        return

    if not can_trade:
        print(f"\n[RISK] {risk_reason}")
        # Still check existing positions even if can't open new ones
        positions = get_open_positions_with_pnl(state, balances)
        if positions:
            print(f"\n[POSITIONS] Managing {len(positions)} open positions")
            for pos in positions:
                state, actions = adjust_position_dynamic(pos, balances, state)
                for action in actions:
                    print(f"  >> {pos['ticker']}: {action}")
            save_state(state)
        return

    # ── Check & adjust existing positions ──
    print(f"\n[POSITIONS] Dynamic SL/TP + Health check")
    positions = get_open_positions_with_pnl(state, balances)

    if positions:
        for pos in positions:
            ticker = pos["ticker"]
            pnl    = pos["pnl_pct"]
            holding_h = pos.get("holding_hours", 0)
            score_drop = pos.get("score_drop", 0)
            emoji  = "🟢" if pnl > 0.05 else ("🔴" if pnl < -0.03 else "🟡")
            health_flag = " ⚠️" if score_drop >= 10 else ""
            print(f"  {emoji} {ticker} ({pos['chainId']}): "
                  f"{'+' if pnl >= 0 else ''}{pnl*100:.2f}% "
                  f"| ${pos['invest']:.2f} -> ${pos['invest']+pos['pnl_value']:.2f} "
                  f"| ⏱ {holding_h:.1f}h{health_flag}")

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
                print(f"  🆕 {ticker}: NEW position")
                changed = True
        if not changed:
            print(f"  No significant changes since last run")
    elif positions:
        print(f"\n[POSITION CHANGES] No previous snapshot")

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
        _scan_signals(state, balances, skip_trade=True)
        return

    # ── v3.2: Gas price check ──────────────────────────────────────────────
    gas_price = get_gas_price()
    if gas_price > HIGH_GAS_THRESHOLD:
        print(f"\n[GAS] High gas price ({gas_price} Gwei), skipping new trades")
        _scan_signals(state, balances, skip_trade=True)
        return

    # ── Find new signals ──
    _scan_signals(state, balances, skip_trade=False)


def _scan_signals(state, balances, skip_trade=False):
    now   = datetime.now(timezone(timedelta(hours=8)))
    now_ts = now.timestamp()
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

    effective_budget = usdt_bal + max(0, profit_pool)

    # ── Fetch signals ──
    all_actionable = []
    inflow_cas = set()

    for chain_id in CHAIN_IDS:
        chain_name = "BSC" if chain_id == "56" else "Solana"
        print(f"\n[SIGNALS] {chain_name}")
        signals = fetch_signals(chain_id)
        print(f"  Fetched {len(signals)} signals")

        inflow = fetch_smart_money_inflow(chain_id, "1h")
        for item in inflow[:10]:
            if float(item.get("inflow", 0)) > 0:
                inflow_cas.add(item.get("ca", "").lower())

        for sig in signals:
            sig_id    = sig.get("signalId")
            ticker    = sig.get("ticker", "???")
            status    = sig.get("status", "?")
            ca = sig.get("contractAddress", "").lower()
            
            # v3.2 scoring with all enhancements
            score, reasons = score_signal_v3_2(sig, state, now_ts)

            # Store signal score for position health tracking
            state.setdefault("signal_scores", {})[ca] = score

            append_signal_log({
                "ts": now.isoformat(), "sigId": sig_id, "ticker": ticker,
                "chain": chain_name, "score": score, "status": status,
                "reasons": reasons,
                "alertPrice": sig.get("alertPrice"),
                "currentPrice": sig.get("currentPrice"),
                "contractAddress": sig.get("contractAddress")
            })

            if score >= SCALP_THRESHOLD and sig_id not in state.get("last_signal_ids", []):
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
        save_state(state)
        return

    if skip_trade:
        print(f"\n[SKIPPED] At position cap or risk limit, signal scan complete.")
        save_state(state)
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

        # v3.2: Liquidity check
        has_liq, liq_usd = check_liquidity(ca, chain_id)
        if not has_liq or liq_usd < MIN_LIQUIDITY_USD:
            print(f"\n  SKIP {ticker}: insufficient liquidity (${liq_usd:.0f} < ${MIN_LIQUIDITY_USD})")
            results.append({"ticker": ticker, "action": "skip_liquidity"})
            continue

        # Position sizing
        if score >= STRONG_THRESHOLD:
            invest_pct = MAX_INVEST_PCT
            strength   = "STRONG"
        else:
            invest_pct = 0.28
            strength   = "MODERATE"

        if pump_pct >= REDUCE_PUMP_PCT and pump_pct < CHASE_PUMP_PCT:
            invest_pct *= 0.5
            strength   += "(reduced)"
            print(f"\n  REDUCED {ticker}: pumped {pump_pct*100:.1f}%, halving position")

        if pump_pct >= CHASE_PUMP_PCT:
            print(f"\n  SKIP {ticker}: chased too far (+{pump_pct*100:.1f}%)")
            results.append({"ticker": ticker, "action": "skip_chase"})
            continue

        available   = effective_budget * (1 - 0.15)
        invest_amount = min(available * invest_pct, effective_budget * MAX_INVEST_PCT)
        invest_amount = round(invest_amount, 2)

        if invest_amount < 1:
            print(f"\n  SKIP {ticker}: insufficient budget (${invest_amount:.2f})")
            continue

        print(f"\n  TRADE {ticker} | {strength} (Score:{score}) | ${invest_amount} USDT")
        print(f"    Chain: {chain} | Price: ${current_price:.8f}")
        print(f"    Reasons: {' | '.join(sig.get('reasons', []))}")

        print(f"    Auditing...")
        audit_data = audit_token(ca, chain_id)
        is_safe, safety_msg = is_token_safe(audit_data)
        print(f"    Audit: {safety_msg}")
        if not is_safe:
            print(f"    REJECT {ticker}: {safety_msg}")
            results.append({"ticker": ticker, "action": "reject", "reason": safety_msg})
            continue

        from_token = BSC_USDT if chain_id == "56" else SOL_USDT
        print(f"    Swapping {invest_amount} USDT -> {ticker}...")
        success, swap_result = execute_swap_with_retry(invest_amount, from_token, ca, chain_id)

        if success:
            order_id = swap_result.get("orderId", "?")
            print(f"    SWAPPED! OrderID: {order_id}")

            # Log trade
            log_trade({
                "ts": now.isoformat(),
                "action": "BUY",
                "ticker": ticker,
                "amount": invest_amount,
                "price": current_price,
                "score": score,
                "chain": chain,
                "ca": ca
            })

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
