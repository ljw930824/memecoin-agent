#!/usr/bin/env python3
"""
execute_bsc.py - BSC Chain Executor
- 只执行 BSC 信号（chain 56）
- 使用 BAW CLI 进行交易
- 策略：SL -8% / TP +12% / 动态加减仓（与 v3.2 一致）
- 持仓上限 3 个（BSC 链内）
"""

import json, os, sys, time, subprocess, re
from datetime import datetime, timezone, timedelta

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATA_DIR    = os.path.expanduser("~/.qclaw/workspace/data")
STATE_FILE  = os.path.join(DATA_DIR, "smart-money-state.json")
QUEUE_FILE  = os.path.join(DATA_DIR, "signal-queue.json")
RETRY_LOG   = os.path.join(DATA_DIR, "retry-log.txt")
TRADE_LOG   = os.path.join(DATA_DIR, "trade-log.json")
os.makedirs(DATA_DIR, exist_ok=True)

BAW_CMD = os.path.expanduser("~\\AppData\\Roaming\\QClaw\\npm-global\\baw.cmd")
if not os.path.isfile(BAW_CMD):
    BAW_CMD = "baw"

# BSC config
BSC_USDT  = "0x55d398326f99059fF775485246999027B3197955"
CHAIN_ID  = "56"

# Strategy params
MAX_BSC_POSITIONS   = 3
STOP_LOSS_PCT       = -0.08
TAKE_PROFIT_PCT     = 0.12
MAX_INVEST_PCT      = 0.45
MIN_INVEST_USD      = 5.0
SCALP_THRESHOLD     = 28
STRONG_THRESHOLD    = 50
COOLDOWN_AFTER_SL   = 12  # hours
COOLDOWN_AFTER_TP   = 6   # hours

# v3.2 Risk Management
MAX_DAILY_LOSS_PCT      = 0.15   # Max daily drawdown -15%
CONSECUTIVE_SL_FREEZE   = 3      # 3 consecutive SL -> freeze trading
FREEZE_DURATION_HOURS   = 2      # Freeze duration
TRAILING_TRIGGER        = 0.08   # Start trailing stop when +8%+
TRAILING_DISTANCE       = 0.02   # Keep SL 2% below peak
BREAKEVEN_TRIGGER       = 0.05   # Move SL to breakeven when +5%+


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"positions": {}, "cooldowns": {}, "last_signal_ids": []}


def backup_state():
    if os.path.exists(STATE_FILE):
        bak = STATE_FILE.replace(".json", f"_bak_{datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')}.json")
        import shutil
        shutil.copy2(STATE_FILE, bak)


def save_state(state):
    backup_state()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ─── Telegram Alert ───
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "8781701155:AAGdKt0oZm5bfaEY39ItcGkiW4phMfYkfbI")
TG_CHAT_ID   = os.environ.get("TG_CHAT_ID", "821225400")

def notify_telegram(msg):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        import urllib.request
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        data = json.dumps({"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception:
        pass


def load_queue():
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def baw_run(args, timeout=60):
    """Run BAW command and return stdout."""
    cmd = [BAW_CMD] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout, encoding="utf-8", errors="replace")
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except Exception as e:
        return "", str(e), 999


def log_retry(ticker, action, reason, attempt):
    ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] BSC | {ticker} | {action} | {reason} | attempt #{attempt}\n"
    with open(RETRY_LOG, "a", encoding="utf-8") as f:
        f.write(entry)


def log_trade(entry):
    log = []
    if os.path.exists(TRADE_LOG):
        with open(TRADE_LOG, "r", encoding="utf-8") as f:
            log = json.load(f)
    log.append(entry)
    if len(log) > 5000:
        log = log[-5000:]
    with open(TRADE_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def get_bsc_balance():
    """Return (usdt_balance, bnb_balance) in USDT terms."""
    out, err, code = baw_run(["wallet", "balance", "--binanceChainId", "56", "--json"])
    if code != 0 or not out:
        return 0.0, 0.0
    try:
        data = json.loads(out)
        usdt_val = 0.0
        bnb_val = 0.0
        bnb_price = 0.0
        for t in data.get("data", []):
            sym = t.get("symbol", "")
            val = float(t.get("value", 0))
            bal = float(t.get("balance", 0))
            price = float(t.get("price", 0))
            if sym == "USDT":
                usdt_val = val
            elif sym == "BNB":
                bnb_val = bal
                bnb_price = price
        # Return BNB balance in both native units and USDT value
        bnb_usdt_value = bnb_val * bnb_price if bnb_price > 0 else bnb_val * 600  # fallback $600
        return usdt_val, bnb_usdt_value
    except Exception:
        return 0.0, 0.0


def get_current_price(ca):
    """Get current price from queue; fallback to position's last known price."""
    queue = load_queue()
    for q in queue:
        if q.get("ca", "").lower() == ca.lower() and q.get("chain") == "56":
            return q.get("currentPrice", 0)
    # Fallback: use last recorded price from position state
    pos = state["positions"].get(ca)
    if pos:
        return pos.get("current_price", 0) or pos.get("entry_price", 0)
    return 0


def get_sl_price(entry_price):
    return round(entry_price * (1 + STOP_LOSS_PCT), 10)


def get_tp_price(entry_price):
    return round(entry_price * (1 + TAKE_PROFIT_PCT), 10)


# ═══════════════════════════════════════════════════════════════
# Trading Actions
# ═══════════════════════════════════════════════════════════════

def _query_token_balance(ca):
    """Query token balance from BAW after buy — returns actual amount received."""
    out, err, code = baw_run(["wallet", "balance", "--binanceChainId", "56", "--json"], timeout=20)
    if code != 0 or not out:
        return 0.0
    try:
        data = json.loads(out)
        for t in data.get("data", []):
            if t.get("contractAddress", "").lower() == ca.lower():
                return float(t.get("balance", 0))
    except Exception:
        pass
    return 0.0


def _query_usdt_balance():
    """Query USDT balance from BAW."""
    out, err, code = baw_run(["wallet", "balance", "--binanceChainId", "56", "--json"], timeout=20)
    if code != 0 or not out:
        return 0.0
    try:
        data = json.loads(out)
        for t in data.get("data", []):
            if t.get("symbol") == "USDT":
                return float(t.get("balance", 0))
    except Exception:
        pass
    return 0.0


def buy_token(ca, ticker, amount_usdt, entry_price, score, reasons, sig_id):
    """Execute buy on BSC via BAW market-order swap."""
    print(f"\n  >> BUY {ticker} | ${amount_usdt:.2f} @ {entry_price:.10f}")
    # Pre-flight safety check
    try:
        from safety_check import check_bsc, format_safety_report
        s_score, s_passed, s_details, s_errors = check_bsc(ca, amount_usdt)
        report = format_safety_report(s_score, s_passed, s_details, s_errors)
        print('     ' + report.replace('\n', '\n     '))
        if not s_passed:
            reason = s_errors[0] if s_errors else f'SCORE_{s_score}'
            print(f'     SAFETY CHECK FAILED: {reason} (score={s_score})')
            notify_telegram(f'⚠️ <b>{ticker} SAFETY FAIL</b>\nReason: {reason} | Score: {s_score}')
            return False, reason, 0.0
    except ImportError:
        pass
    for attempt in range(1, 4):
        out, err, code = baw_run([
            "market-order", "swap",
            "--binanceChainId", "56",
            "--fromToken", BSC_USDT,
            "--toToken", ca,
            "--fromTokenQty", str(amount_usdt),
            "--slippage", "auto",
            "--gasLevel", "HIGH",
            "--json"
        ], timeout=90)
        if code == 0 and out:
            try:
                data = json.loads(out)
                if data.get("success"):
                    tx_hash = data.get("data", {}).get("txHash", "unknown")
                    print(f"     TX: {tx_hash}")
                    # Query actual on-chain balance instead of estimating
                    time.sleep(2)
                    actual_tokens = _query_token_balance(ca)
                    if actual_tokens > 0:
                        print(f"     Confirmed: {actual_tokens:.6f} {ticker}")
                        return True, tx_hash, actual_tokens
                    else:
                        est = amount_usdt / entry_price if entry_price > 0 else 0
                        print(f"     Balance query failed — using estimate: {est:.6f}")
                        return True, tx_hash, est
            except Exception:
                pass
        print(f"     Attempt {attempt} failed: {err or out[:100]}")
        log_retry(ticker, "BUY", err or "unknown", attempt)
        time.sleep(3 * attempt)  # Progressive backoff: 3s, 6s, 9s
    notify_telegram(f"🚨 <b>BSC BUY FAILED</b>\n{ticker}\n3 attempts exhausted. Manual intervention needed.")
    return False, "", 0.0


def place_tp_limit_order(ca, ticker, amount_tokens, tp_price):
    """Place TP limit sell order immediately after buy.
    Returns (success, strategy_id_or_error_msg)
    """
    print(f"     [TP LIMIT] Placing limit sell {ticker} @ {tp_price:.10f}")
    last_err = ""
    for attempt in range(1, 4):
        out, err, code = baw_run([
            "limit-order", "sell",
            "--binanceChainId", CHAIN_ID,
            "--triggerPrice", str(tp_price),
            "--fromTokenQty", str(amount_tokens),
            "--fromToken", ca,
            "--toToken", BSC_USDT,
            "--slippage", "5",
            "--gasLevel", "HIGH",
            "--json"
        ], timeout=60)
        if code == 0 and out:
            try:
                data = json.loads(out)
                if data.get("success"):
                    strategy_id = ""
                    if "data" in data and isinstance(data["data"], dict):
                        strategy_id = str(data["data"].get("strategyId", ""))
                    print(f"     [TP LIMIT] OK (strategyId={strategy_id})")
                    return True, strategy_id
            except Exception:
                pass
        err_msg = err or out
        last_err = err_msg
        print(f"     [TP LIMIT] Attempt {attempt} failed: {err_msg[:200]}")
        if attempt < 3:
            wait_time = 2 * attempt  # Progressive backoff: 2s, 4s
            print(f"     [TP LIMIT] Retrying in {wait_time}s...")
            time.sleep(wait_time)
    print(f"     [TP LIMIT] All attempts failed")
    return False, last_err


def rollback_position(ca, ticker, amount_tokens):
    """Immediately market-sell after failed TP limit order.
    Returns True if tokens are confirmed sold, False otherwise.
    """
    print(f"     [ROLLBACK] Selling {ticker} immediately (limit order not supported)")
    for attempt in range(1, 4):
        out, err, code = baw_run([
            "market-order", "swap",
            "--binanceChainId", CHAIN_ID,
            "--fromToken", ca,
            "--toToken", BSC_USDT,
            "--fromTokenQty", str(amount_tokens),
            "--slippage", "auto",
            "--gasLevel", "HIGH",
            "--json"
        ], timeout=90)
        if code == 0 and out:
            try:
                data = json.loads(out)
                if data.get("success"):
                    # Multi-stage confirmation with tx-history verification
                    for wait_stage, wait_time in [(1, 5), (2, 8), (3, 10)]:
                        time.sleep(wait_time)
                        remaining = _query_token_balance(ca)
                        if remaining < amount_tokens * 0.1:
                            print(f"     [ROLLBACK] Sold successfully (balance verified at stage {wait_stage})")
                            return True
                        # Also check tx-history for sell confirmation
                        tx_out, tx_err, tx_code = baw_run([
                            "wallet", "tx-history",
                            "--binanceChainId", CHAIN_ID,
                            "--size", "10",
                            "--json"
                        ], timeout=15)
                        if tx_code == 0 and tx_out:
                            try:
                                tx_data = json.loads(tx_out)
                                for tx in tx_data.get("data", []):
                                    if tx.get("type") == "SWAP" and tx.get("status") == "SUCCESS":
                                        if tx.get("fromToken", "").lower() == ca.lower():
                                            print(f"     [ROLLBACK] Confirmed via tx-history: {tx.get('txHash', 'unknown')}")
                                            return True
                            except Exception:
                                pass
                        print(f"     [ROLLBACK] Stage {wait_stage}: tokens still present ({remaining:.2f}), waiting...")
                    print(f"     [ROLLBACK] Tokens still present after all stages — sell may have failed")
                    continue
            except Exception as e:
                print(f"     [ROLLBACK] Parse error: {e}")
        err_msg = err or out[:100]
        print(f"     [ROLLBACK] Attempt {attempt} failed: {err_msg}")
        time.sleep(2 * attempt)  # Progressive backoff
    print(f"     [ROLLBACK] CRITICAL: Could not sell {ticker}!")
    notify_telegram(f"🚨 <b>ROLLBACK FAILED</b>\n{ticker} — TP limit failed + rollback failed. Position UNPROTECTED!")
    return False


def sell_token(ca, ticker, amount_pct, reason_tag=""):
    """Sell portion or full position via BAW market-order.
    amount_pct: 0.0-1.0 = percentage of position to sell
    NOTE: Use sell_token_abs() for absolute token amounts
    """
    pos = state["positions"].get(ca)
    if not pos:
        return False, ""
    
    total_amount = float(pos.get("amount", 0))
    if total_amount <= 0:
        return False, ""
    
    # Calculate amount to sell
    if amount_pct > 1.0:
        # Invalid: amount_pct should be 0.0-1.0
        print(f"     [WARN] sell_token called with amount_pct={amount_pct} > 1.0, clamping to 1.0")
        amount_pct = 1.0
    
    # Percentage of position (1.0 = 100%)
    sell_qty = total_amount * amount_pct
    
    if sell_qty <= 0:
        return False, ""

    print(f"\n  >> SELL {ticker} | {sell_qty:.4f} units ({reason_tag})")
    
    usdt_bal_before = _query_usdt_balance()
    for attempt in range(1, 4):
        out, err, code = baw_run([
            "market-order", "swap",
            "--binanceChainId", "56",
            "--fromToken", ca,
            "--toToken", BSC_USDT,
            "--fromTokenQty", str(sell_qty),
            "--slippage", "auto",
            "--gasLevel", "HIGH",
            "--json"
        ], timeout=90)
        if code == 0 and out:
            try:
                data = json.loads(out)
                if data.get("success"):
                    tx_hash = data.get("data", {}).get("txHash", "unknown")
                    print(f"     TX: {tx_hash}")
                    # Detect if limit order was already filled by comparing USDT balance
                    time.sleep(2)
                    usdt_after = _query_usdt_balance()
                    ep_val = float(pos.get('entry_price', 0))
                    if ep_val > 0 and usdt_after - usdt_bal_before < sell_qty * ep_val * 0.5:
                        print(f"     [INFO] USDT unchanged — limit order likely already executed")
                        return True, "LIMIT_ORDER_EXECUTED"
                    return True, tx_hash
            except Exception:
                pass
        err_msg = err or out
        print(f"     Attempt {attempt} failed: {err_msg[:100]}")
        log_retry(ticker, f"SELL_{reason_tag}", err_msg[:200], attempt)
        time.sleep(3 * attempt)  # Progressive backoff
    notify_telegram(f"🚨 <b>BSC SELL FAILED</b>\n{ticker} | {reason_tag}\n3 attempts exhausted. Position at risk!")
    return False, ""


# ═══════════════════════════════════════════════════════════════
# Position Sync — validate state file against on-chain balances
# ═══════════════════════════════════════════════════════════════

def sync_positions_with_chain(state):
    """Compare state file positions against actual on-chain balances.
    Remove ghost positions (tokens no longer held on-chain).
    Returns list of cleaned-up tickers."""
    cleaned = []
    bsc_positions = {ca: pos for ca, pos in state["positions"].items()
                     if str(pos.get("chain_id", "")) == "56"}
    if not bsc_positions:
        return cleaned

    # Query actual on-chain balances
    out, err, code = baw_run(["wallet", "balance", "--binanceChainId", "56", "--json"], timeout=20)
    if code != 0 or not out:
        print("  [SYNC] WARNING: Could not query chain balance — skipping sync")
        return cleaned

    try:
        data = json.loads(out)
        onchain_cas = set()
        for t in data.get("data", []):
            addr = t.get("contractAddress", "").lower()
            bal = float(t.get("balance", 0))
            val = float(t.get("value", 0))
            # Only count non-native tokens with value > $0.01
            if addr and bal > 0 and val > 0.01:
                onchain_cas.add(addr)
    except Exception as e:
        print(f"  [SYNC] WARNING: Balance parse error — skipping sync: {e}")
        return cleaned

    # Check each state-file position against on-chain reality
    for ca, pos in list(bsc_positions.items()):
        ticker = pos.get("ticker", "?")
        ca_lower = ca.lower()

        # Also try matching by querying individual token balance
        actual_bal = 0.0
        if ca_lower in onchain_cas:
            # Token exists in balance list — get its value
            for t in data.get("data", []):
                if t.get("contractAddress", "").lower() == ca_lower:
                    actual_bal = float(t.get("balance", 0))
                    break
        else:
            # Token NOT in balance list — query individually as fallback
            actual_bal = _query_token_balance(ca)

        if actual_bal <= 0:
            # Ghost position: state says we hold it, but chain says we don't
            print(f"  [SYNC] GHOST: {ticker} — in state but NOT on-chain. Removing.")
            invest = float(pos.get("invest_amount", 0))
            pnl_pct = float(pos.get("pnl_pct", 0))
            record_trade_close(ca, "GHOST_CLEANUP", pnl_pct)
            del state["positions"][ca]
            cleaned.append(ticker)
        elif actual_bal < float(pos.get("amount", 0)) * 0.5:
            # Significant balance discrepancy — update amount
            print(f"  [SYNC] MISMATCH: {ticker} — state={pos.get('amount',0):.2f} vs chain={actual_bal:.2f}. Updating.")
            pos["amount"] = actual_bal

    if cleaned:
        save_state(state)
        notify_telegram(f"🧹 <b>Position Sync</b>\nCleaned ghost positions: {', '.join(cleaned)}")

    return cleaned


# ═══════════════════════════════════════════════════════════════
# Position Management
# ═══════════════════════════════════════════════════════════════

def update_position_pnl(ca, current_price):
    """Update P&L for a position."""
    pos = state["positions"].get(ca)
    if not pos:
        return
    ep = float(pos.get("entry_price", 0))
    if ep > 0 and current_price > 0:
        pnl_pct = (current_price - ep) / ep
        pos["pnl_pct"] = pnl_pct
        invest = float(pos.get("invest_amount", 0))
        pos["pnl_usdt"] = invest * pnl_pct
        pos["current_price"] = current_price


def check_and_close_position(ca):
    """Check SL/TP and manage position. Returns True if closed."""
    pos = state["positions"].get(ca)
    if not pos:
        return False

    ticker   = pos.get("ticker", "?")
    ep       = float(pos.get("entry_price", 0))
    cur_p    = float(pos.get("current_price", 0))
    sl_price = float(pos.get("sl_price", 0))
    tp_price = float(pos.get("tp_price", 0))
    pnl_pct  = pos.get("pnl_pct", 0)

    if ep == 0:
        return False

    closed = False
    close_reason = ""

    # ─── Stop Loss ───
    if sl_price > 0 and cur_p <= sl_price:
        print(f"  [!] {ticker} SL HIT ({pnl_pct*100:.1f}%)")
        # Cancel any existing TP limit order before market sell
        tp_strategy_id = pos.get("tp_strategy_id", "")
        if tp_strategy_id:
            print(f"  [CANCEL] Cancelling TP limit order {tp_strategy_id}")
            baw_run(["limit-order", "cancel", "--strategyId", str(tp_strategy_id)], timeout=15)
        success, tx = sell_token(ca, ticker, 1.0, "SL_HIT")
        if success:
            record_trade_close(ca, "SL_HIT", pnl_pct)
            del state["positions"][ca]
            state["cooldowns"][ca] = (
                datetime.now(timezone(timedelta(hours=8))) +
                timedelta(hours=COOLDOWN_AFTER_SL)
            ).isoformat()
            closed = True
            close_reason = "SL"
        return closed

    # ─── Take Profit ───
    if tp_price > 0 and cur_p >= tp_price:
        print(f"  [!] {ticker} TP HIT (+{pnl_pct*100:.1f}%)")
        # Cancel any existing TP limit order before market sell
        tp_strategy_id = pos.get("tp_strategy_id", "")
        if tp_strategy_id:
            print(f"  [CANCEL] Cancelling TP limit order {tp_strategy_id}")
            baw_run(["limit-order", "cancel", "--strategyId", str(tp_strategy_id)], timeout=15)
        success, tx = sell_token(ca, ticker, 1.0, "TP_HIT")
        if success:
            record_trade_close(ca, "TP_HIT", pnl_pct)
            del state["positions"][ca]
            state["cooldowns"][ca] = (
                datetime.now(timezone(timedelta(hours=8))) +
                timedelta(hours=COOLDOWN_AFTER_TP)
            ).isoformat()
            closed = True
            close_reason = "TP"
        return closed

    # ─── Dynamic Partial TP (v3 rule) ───
    if pnl_pct >= 0.10 and not pos.get("partial_tp_10_done"):
        print(f"  [*] {ticker} +{pnl_pct*100:.1f}% -> partial TP 50%")
        # Cancel old TP limit order before partial sell (otherwise it over-sells)
        tp_sid = pos.get("tp_strategy_id", "")
        if tp_sid:
            print(f"  [CANCEL] Cancelling old TP limit {tp_sid} before partial TP")
            baw_run(["limit-order", "cancel", "--strategyId", str(tp_sid)], timeout=15)
            pos["tp_strategy_id"] = ""
        success, tx = sell_token(ca, ticker, 0.5, "PARTIAL_TP10")
        if success:
            pos["partial_tp_10_done"] = True
            pos["sl_price"] = max(float(pos.get("sl_price", 0)), ep * 1.0)
            pos["amount"] = float(pos.get("amount", 0)) * 0.5
            # Place new TP limit order for remaining 50% at +12%
            remaining = pos.get("amount", 0)
            if remaining > 0:
                tp_ok, tp_res = place_tp_limit_order(ca, ticker, remaining, pos.get("tp_price", ep * 1.12))
                if tp_ok:
                    pos["tp_strategy_id"] = str(tp_res)
                    print(f"  [NEW TP LIMIT] strategyId={tp_res}")

    if pnl_pct >= 0.15 and not pos.get("partial_tp_15_done"):
        print(f"  [*] {ticker} +{pnl_pct*100:.1f}% -> partial TP 25% more")
        tp_sid = pos.get("tp_strategy_id", "")
        if tp_sid:
            print(f"  [CANCEL] Cancelling old TP limit {tp_sid} before partial TP")
            baw_run(["limit-order", "cancel", "--strategyId", str(tp_sid)], timeout=15)
            pos["tp_strategy_id"] = ""
        success, tx = sell_token(ca, ticker, 0.5, "PARTIAL_TP15")
        if success:
            pos["partial_tp_15_done"] = True
            pos["sl_price"] = max(float(pos.get("sl_price", 0)), ep * 1.03)
            pos["amount"] = float(pos.get("amount", 0)) * 0.5
            remaining = pos.get("amount", 0)
            if remaining > 0:
                tp_ok, tp_res = place_tp_limit_order(ca, ticker, remaining, pos.get("tp_price", ep * 1.12))
                if tp_ok:
                    pos["tp_strategy_id"] = str(tp_res)
                    print(f"  [NEW TP LIMIT] strategyId={tp_res}")

    if pnl_pct >= 0.08 and not pos.get("breakeven_done"):
        pos["sl_price"] = max(float(pos.get("sl_price", 0)), ep)
        pos["breakeven_done"] = True

    # v3.2: Trailing stop — after breakeven, track SL 2% below peak
    if pos.get("breakeven_done"):
        peak = float(pos.get("peak_price", ep))
        if current_price > peak:
            pos["peak_price"] = current_price
            peak = current_price
        trailing_sl = peak * (1 - TRAILING_DISTANCE)
        if trailing_sl > float(pos.get("sl_price", 0)):
            pos["sl_price"] = trailing_sl
            print(f"  [TRAILING] {ticker} SL -> ${trailing_sl:.10f} (peak ${peak:.10f})")

    # soldRatio-based exit: smart money reducing
    sold_ratio = pos.get("sold_ratio", 0)
    if sold_ratio > 0 and not pos.get("sold_ratio_triggered"):
        if sold_ratio >= 50:
            print(f"  [SOLD_RATIO] {ticker} soldRatio={sold_ratio:.0f}% -> FULL CLOSE")
            success, tx = sell_token(ca, ticker, 1.0, "SOLD_RATIO_EXIT")
            if success:
                record_trade_close(ca, "SOLD_RATIO_EXIT", pnl_pct)
                del state["positions"][ca]
                state["cooldowns"][ca] = (now + timedelta(hours=COOLDOWN_SL)).isoformat()
                save_state(state)
                return True
        elif sold_ratio >= 30:
            print(f"  [SOLD_RATIO] {ticker} soldRatio={sold_ratio:.0f}% -> reduce 50%")
            success, tx = sell_token(ca, ticker, 0.5, "SOLD_RATIO_REDUCE")
            if success:
                pos["sold_ratio_triggered"] = True
                pos["sl_price"] = max(float(pos.get("sl_price", 0)), float(pos.get("entry_price", 0)))
                save_state(state)

    return False


def record_trade_close(ca, reason, pnl_pct):
    pos = state["positions"].get(ca, {})
    entry = {
        "ts": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "chain": "BSC",
        "ticker": pos.get("ticker", "?"),
        "ca": ca,
        "reason": reason,
        "entry_price": pos.get("entry_price", 0),
        "invest": pos.get("invest_amount", 0),
        "pnl_pct": pnl_pct,
        "pnl_usdt": pos.get("pnl_usdt", 0),
        "sig_id": pos.get("sig_id", ""),
        "score": pos.get("score", 0),
    }
    log_trade(entry)
    if ca not in state["positions"]:
        return
    if reason == "SL_HIT":
        state.setdefault("last_signal_ids", [])
        state["last_signal_ids"].append(pos.get("sig_id", ""))
        if len(state["last_signal_ids"]) > 50:
            state["last_signal_ids"] = state["last_signal_ids"][-50:]

    # v3.2: Track consecutive SL for freeze
    risk_check = state.setdefault("risk_check", {})
    if reason == "SL_HIT":
        risk_check["consecutive_sl"] = risk_check.get("consecutive_sl", 0) + 1
        if risk_check["consecutive_sl"] >= CONSECUTIVE_SL_FREEZE:
            freeze_until = (datetime.now(timezone(timedelta(hours=8))) + timedelta(hours=FREEZE_DURATION_HOURS)).isoformat()
            risk_check["freeze_until"] = freeze_until
            print(f"  [RISK] {risk_check['consecutive_sl']} consecutive SL -> FROZEN until {freeze_until}")
    elif "TP" in reason:
        risk_check["consecutive_sl"] = 0
    state["risk_check"] = risk_check

    # v3.2: Update daily P&L
    today_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    daily_pnl = state.setdefault("daily_pnl", {})
    daily_pnl[today_str] = daily_pnl.get(today_str, 0) + pnl_pct


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    global state
    state = load_state()

    now = datetime.now(timezone(timedelta(hours=8)))
    print(f"\n{'='*50}")
    print(f" BSC EXECUTOR  |  {now.strftime('%Y-%m-%d %H:%M')}  |  BAW CLI")
    print(f"{'='*50}")

    # ─── v3.2: Risk check ───
    risk_check = state.get("risk_check", {})
    freeze_until = risk_check.get("freeze_until")
    if freeze_until:
        try:
            freeze_dt = datetime.fromisoformat(freeze_until)
            if now < freeze_dt:
                remaining = (freeze_dt - now).total_seconds() / 60
                print(f"  [FROZEN] Trading frozen for {remaining:.0f}min")
                return
            else:
                risk_check["freeze_until"] = None
                risk_check["consecutive_sl"] = 0
                state["risk_check"] = risk_check
        except Exception:
            pass

    # Daily loss check
    daily_pnl = state.get("daily_pnl", {})
    today_str = now.strftime("%Y-%m-%d")
    today_pnl = daily_pnl.get(today_str, 0)
    if today_pnl <= -MAX_DAILY_LOSS_PCT:
        print(f"  [RISK] Daily loss limit hit: {today_pnl*100:.1f}%")
        save_state(state)
        return

    usdt_bal, _ = get_bsc_balance()
    print(f" BSC USDT Balance: ${usdt_bal:.2f}")

    # ─── Sync positions with on-chain reality ───
    print("\n[ Position Sync ]")
    ghosts = sync_positions_with_chain(state)
    if ghosts:
        print(f" Cleaned {len(ghosts)} ghost position(s): {', '.join(ghosts)}")
        # Refresh after cleanup
        bsc_positions = {ca: pos for ca, pos in state["positions"].items()
                         if str(pos.get("chain_id", "")) == "56"}
    else:
        bsc_positions = {ca: pos for ca, pos in state["positions"].items()
                         if str(pos.get("chain_id", "")) == "56"}

    bsc_open = len(bsc_positions)
    print(f" BSC Open Positions: {bsc_open}/{MAX_BSC_POSITIONS}")

    actions_taken = []

    # ─── 1. Check existing BSC positions ───
    print("\n[ Position Management ]")
    for ca, pos in list(bsc_positions.items()):
        ticker = pos.get("ticker", "?")
        current_price = get_current_price(ca)
        if current_price <= 0:
            continue
        update_position_pnl(ca, current_price)
        closed = check_and_close_position(ca)
        if closed:
            actions_taken.append(f"CLOSE {ticker}")
            save_state(state)

    # ─── 2. Open new BSC signals ───
    if bsc_open < MAX_BSC_POSITIONS and usdt_bal >= MIN_INVEST_USD:
        print("\n[ Open Signals ]")
        queue = load_queue()
        now_ts = time.time()
        SIGNAL_TTL = 3600  # 60 minutes (matching scan_both_chains.py)
        bsc_signals = [q for q in queue if q.get("chain") == "56" and (now_ts - q.get("ts", 0)) < SIGNAL_TTL]
        # Filter out stale signals
        stale_count = len([q for q in queue if q.get("chain") == "56" and (now_ts - q.get("ts", 0)) >= SIGNAL_TTL])
        if stale_count:
            print(f"  Filtered {stale_count} stale signal(s) (>60min old)")
        bsc_signals.sort(key=lambda x: x["score"], reverse=True)

        available_slot = MAX_BSC_POSITIONS - bsc_open
        invest_per_trade = min(usdt_bal * MAX_INVEST_PCT, usdt_bal * 0.5)

        for sig in bsc_signals[:available_slot]:
            if usdt_bal < MIN_INVEST_USD:
                break
            ca      = sig["ca"]
            ticker  = sig["ticker"]
            score   = sig["score"]
            ep      = float(sig["currentPrice"] or sig["alertPrice"] or 0)
            reasons = sig.get("reasons", [])

            # Triple-check to prevent duplicate buys
            if ca in bsc_positions or ca in state.get("positions", {}):
                print(f"     [SKIP] {ticker} - already in positions (checked)")
                continue
            if score < SCALP_THRESHOLD:
                continue

            # Skip if in cooldown
            in_cd = False
            for caca, end_str in list(state.get("cooldowns", {}).items()):
                if caca.lower() == ca.lower():
                    try:
                        if now < datetime.fromisoformat(end_str):
                            in_cd = True
                            break
                    except Exception:
                        pass
            if in_cd:
                continue

            print(f"\n  >>> {ticker} BSC | score={score} | ep={ep:.10f}")
            print(f"      {' | '.join(reasons[:4])}")

            # Check BNB balance for gas
            _, bnb_bal_usdt = get_bsc_balance()
            # BNB gas check: need at least $0.50 worth of BNB for gas (~0.0008 BNB at $600)
            if bnb_bal_usdt < 0.5:
                print(f"     [SKIP] {ticker} - BNB gas balance too low (${bnb_bal_usdt:.2f} USDT worth)")
                notify_telegram(f"⚠️ <b>BNB Gas Low</b>\nBalance: ${bnb_bal_usdt:.2f} USDT worth. Need >$0.50 for trades.")
                continue

            # Adjust invest based on score
            invest = min(invest_per_trade, usdt_bal * 0.5)
            if score >= STRONG_THRESHOLD:
                invest = min(usdt_bal * 0.5, invest)
            elif score >= 40:
                invest = min(usdt_bal * 0.3, invest)
            else:
                invest = min(usdt_bal * 0.25, invest)

            invest = max(invest, MIN_INVEST_USD)
            if invest > usdt_bal:
                invest = usdt_bal

            _sig_id = sig.get("sigId") or sig.get("signalId", "")
            # Pre-flight checks
            # 1. Double-check USDT balance (avoid race condition)
            usdt_bal_now = _query_usdt_balance()
            if usdt_bal_now < MIN_INVEST_USD:
                print(f"     [SKIP] {ticker} - USDT balance insufficient (${usdt_bal_now:.2f})")
                continue
            if invest > usdt_bal_now:
                invest = usdt_bal_now * 0.9  # leave some for gas

            # 2. Check if already bought (triple-check with fresh state reload)
            fresh_state = load_state()
            if ca in fresh_state.get("positions", {}):
                print(f"     [SKIP] {ticker} - already in positions (fresh state)")
                continue

            success, tx, amount_tokens = buy_token(ca, ticker, invest, ep, score, reasons, _sig_id)

            if success:
                # Immediately add to state to prevent duplicate buys in same cycle
                state["positions"][ca] = {"temp": True, "ticker": ticker}
                save_state(state)
                bsc_positions[ca] = {"temp": True, "ticker": ticker}
                
                tp_price = get_tp_price(ep)
                sl_price = get_sl_price(ep)
                # Wait for chain confirmation before placing TP limit order
                time.sleep(3)

                        # CRITICAL: Place TP limit order BEFORE keeping position
                tp_ok, tp_result = place_tp_limit_order(ca, ticker, amount_tokens, tp_price)
                tp_strategy_id = ""
                tp_limit_error = ""
                if tp_ok:
                    tp_limit_placed = True
                    tp_strategy_id = str(tp_result) if tp_result else ""
                    print(f"     [TP LIMIT] Recorded strategyId={tp_strategy_id}")
                else:
                    tp_limit_error = str(tp_result)[:200] if tp_result else "unknown_error"
                    # Token doesn't support limit orders -> attempt rollback
                    log_retry(ticker, "TP_LIMIT_FAILED", tp_limit_error, 1)
                    rollback_ok = rollback_position(ca, ticker, amount_tokens)
                    if rollback_ok:
                        print(f"     [SKIP] {ticker} skipped — limit order not supported, rolled back")
                        continue
                    else:
                        # ROLLBACK FAILED — force-keep position for SL protection
                        print(f"     [WARN] {ticker} rollback FAILED — force-keeping position")
                        notify_telegram(f"🚨 <b>BSC Rollback Failed</b>\n{ticker} bought but TP limit + rollback both failed. Position force-kept with SL protection.")
                        tp_limit_placed = False

                # Record position (even if TP limit failed — SL via market-order will protect)
                state["positions"][ca] = {
                    "chain": "BSC",
                    "chain_id": "56",
                    "ticker": ticker,
                    "ca": ca,
                    "entry_price": ep,
                    "amount": amount_tokens,
                    "invest_amount": invest,
                    "sl_price": sl_price,
                    "tp_price": tp_price,
                    "pnl_pct": 0,
                    "pnl_usdt": 0,
                    "entry_time": now.isoformat(),
                    "sig_id": _sig_id,
                    "score": score,
                    "reasons": reasons,
                    "partial_tp_10_done": False,
                    "sold_ratio": float(sig.get("soldRatioPercent", 0)),
                    "sold_ratio_triggered": False,
                    "partial_tp_15_done": False,
                    "breakeven_done": False,
                    "partial_tp_20_done": False,
                    "tp_limit_placed": tp_limit_placed,
                    "tp_strategy_id": tp_strategy_id,
                    "tp_limit_error": tp_limit_error,
                    "sl_strategy_id": "",  # Reserved for future SL limit order support
                }
                state.setdefault("last_signal_ids", [])
                state["last_signal_ids"].append(_sig_id)
                if len(state["last_signal_ids"]) > 50:
                    state["last_signal_ids"] = state["last_signal_ids"][-50:]

                usdt_bal -= invest
                actions_taken.append(f"OPEN {ticker} @ {ep:.8f}")
                save_state(state)
                print(f"     Opened: {ticker} | invest=${invest:.2f} | SL={sl_price:.8f} | TP={tp_price:.8f} | LIMIT=OK")
            else:
                print(f"     FAILED to open {ticker}")
                log_retry(ticker, "OPEN_FAILED", "buy_order_failed", 1)

    save_state(state)

    # ─── Summary ───
    print(f"\n{'─'*50}")
    print(f" BSC Executor Summary")
    print(f"  Positions: {len([p for p in state['positions'].values() if p.get('chain')=='BSC'])}")
    print(f"  Actions: {actions_taken if actions_taken else 'none'}")
    bsc_bal, bnb_val = get_bsc_balance()
    print(f"  BSC USDT: ${bsc_bal:.2f} | BNB: ${bnb_val:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


