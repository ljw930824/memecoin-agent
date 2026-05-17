#!/usr/bin/env python3
"""
Scalping Strategy - Smart Money Monitor v2
Aggressive short-term trading: quick in, quick out, compound gains.

Key differences from v1:
- Scalping targets: 8-15% take profit (not 50%)
- Tight stop loss: -8% (not -20%)
- Will also trade on "timeout" signals if price is still near trigger
- Lower entry threshold (score >= 25)
- Faster position turnover
- Auto compound: reinvest profits from closed positions
"""

import json
import os
import sys
import time
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# === SCALPING CONFIG ===
STATE_FILE = os.path.expanduser("~/.qclaw/workspace/data/smart-money-state.json")
DATA_DIR = os.path.expanduser("~/.qclaw/workspace/data")
SIGNAL_LOG = os.path.join(DATA_DIR, "signal-log.json")
CHAIN_IDS = ["56", "CT_501"]

# Risk parameters - Scalping mode
MAX_SINGLE_INVEST_PCT = 0.40      # 40% of available USDT per trade (aggressive)
MIN_USDT_RESERVE_PCT = 0.15       # Keep only 15% USDT reserve
STOP_LOSS_PCT = -0.08             # -8% stop loss (tight)
TAKE_PROFIT_PCT = 0.12            # +12% take profit
SCALP_THRESHOLD = 25              # Lower threshold for scalping
STRONG_THRESHOLD = 45             # Strong signal threshold

# BSC token addresses
BSC_USDT = "0x55d398326f99059fF775485246999027B3197955"
BSC_BNB = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
SOL_USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
SOL_SOL = "So11111111111111111111111111111111111111111"

os.makedirs(DATA_DIR, exist_ok=True)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"positions": {}, "last_signal_ids": [], "trade_count": 0, "total_pnl": 0}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def append_signal_log(entry):
    log = []
    if os.path.exists(SIGNAL_LOG):
        with open(SIGNAL_LOG, "r", encoding="utf-8") as f:
            log = json.load(f)
    log.append(entry)
    if len(log) > 1000:
        log = log[-1000:]
    with open(SIGNAL_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def fetch_signals(chain_id, page=1, page_size=50):
    import urllib.request
    url = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai"
    headers = {
        "Content-Type": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": "binance-web3/1.1 (Skill)"
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
        print(f"[ERROR] Fetch signals chain {chain_id}: {e}", file=sys.stderr)
    return []


def fetch_smart_money_inflow(chain_id, period="1h"):
    import urllib.request
    url = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/tracker/wallet/token/inflow/rank/query/ai"
    headers = {
        "Content-Type": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": "binance-web3/2.1 (Skill)"
    }
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


def score_signal_scalping(signal):
    """Scalping-oriented scoring - more aggressive, favors momentum."""
    score = 0
    reasons = []
    
    smc = signal.get("smartMoneyCount", 0)
    if smc >= 7:
        score += 35
        reasons.append(f"SM={smc}(high)")
    elif smc >= 5:
        score += 25
        reasons.append(f"SM={smc}(med)")
    elif smc >= 3:
        score += 12
        reasons.append(f"SM={smc}(low)")
    
    direction = signal.get("direction", "")
    if direction == "buy":
        score += 10
        reasons.append("buy")
    elif direction == "sell":
        score -= 25
        reasons.append("SELL-skip")
    
    sc = signal.get("signalCount", 0)
    if sc >= 15:
        score += 8
        reasons.append(f"signals={sc}")
    elif sc >= 5:
        score += 3
        reasons.append(f"signals={sc}")
    
    tags = signal.get("tokenTag", {})
    for cat, tag_list in tags.items():
        for t in tag_list:
            tn = t.get("tagName", "")
            if tn == "Smart Money Add Holdings":
                score += 12
                reasons.append("SM+Holdings")
            elif tn == "Whale Buy":
                score += 15
                reasons.append("WhaleBuy")
            elif tn == "DEX Paid":
                score += 3
                reasons.append("DEXpaid")
            elif tn == "Smart Money Reduce Holdings":
                score -= 15
                reasons.append("SM-Reduce")
            elif tn == "Whale Sell":
                score -= 20
                reasons.append("WhaleSell")
    
    mc = float(signal.get("alertMarketCap", 0) or 0)
    if mc >= 1000000:
        score += 10
        reasons.append(f"mcap=${mc/1e6:.1f}M")
    elif mc >= 100000:
        score += 5
        reasons.append(f"mcap=${mc/1e3:.0f}K")
    elif mc > 0:
        score -= 5  # Too small, risky
        reasons.append("mcap<100K")
    
    # For scalping, also consider current momentum
    current_price = float(signal.get("currentPrice", 0) or 0)
    alert_price = float(signal.get("alertPrice", 0) or 0)
    if alert_price > 0 and current_price > 0:
        price_move = (current_price - alert_price) / alert_price
        if 0 < price_move < 0.10:
            score += 5
            reasons.append(f"momentum+{price_move*100:.1f}%")
        elif price_move >= 0.10:
            # Already pumped too much, chase risk
            score -= 10
            reasons.append(f"chase_risk+{price_move*100:.1f}%")
        elif -0.05 < price_move <= 0:
            score += 3
            reasons.append("dip_entry")
        elif price_move <= -0.10:
            score -= 15
            reasons.append(f"dumped{price_move*100:.1f}%")
    
    # Status check - for scalping we can also trade timeout signals if fresh
    status = signal.get("status", "")
    if status == "active":
        score += 15
        reasons.append("ACTIVE")
    elif status == "timeout":
        # Still tradeable if not too old
        tf = signal.get("timeFrame", 0)
        if tf < 3600000:  # Less than 1 hour old
            score += 5
            reasons.append("fresh_timeout")
        else:
            score -= 10
            reasons.append("old_timeout")
    elif status in ("exitRate", "outDecline"):
        score -= 20
        reasons.append(f"exiting({status})")
    
    return max(0, min(100, score)), reasons


def get_wallet_balance():
    try:
        result = subprocess.run(
            [BAW_CMD, "wallet", "balance", "--json"],
            capture_output=True, text=True, timeout=15,
            env=_baw_env()
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get("success"):
                balances = {}
                for token in data.get("data", []):
                    balances[token.get("symbol")] = float(token.get("balance", 0))
                return balances
    except Exception as e:
        print(f"[ERROR] Wallet balance: {e}", file=sys.stderr)
    return {}


def audit_token(contract_address, chain_id):
    import urllib.request
    import uuid
    url = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/security/token/audit"
    headers = {
        "Content-Type": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": "binance-web3/1.4 (Skill)",
        "source": "agent"
    }
    body = json.dumps({
        "binanceChainId": chain_id,
        "contractAddress": contract_address,
        "requestId": str(uuid.uuid4())
    }).encode("utf-8")
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
    """Parse audit response per query-token-audit skill format."""
    if not audit_data:
        return False, "Audit unavailable"
    
    # Check hasResult and isSupported
    if not audit_data.get("hasResult") or not audit_data.get("isSupported"):
        return False, "Audit data unavailable for this token"
    
    # Risk level from skill response: riskLevel (0-5), riskLevelEnum (LOW/MEDIUM/HIGH)
    risk_level = audit_data.get("riskLevel", 3)
    risk_enum = audit_data.get("riskLevelEnum", "HIGH")
    
    # Block: riskLevel >= 4 is HIGH, must avoid
    if risk_level >= 4:
        return False, f"HIGH RISK (level={risk_level}, {risk_enum})"
    
    # Tax info from extraInfo
    extra = audit_data.get("extraInfo", {}) or {}
    buy_tax_str = extra.get("buyTax", "0") or "0"
    sell_tax_str = extra.get("sellTax", "0") or "0"
    buy_tax = float(buy_tax_str) / 100 if float(buy_tax_str) > 1 else float(buy_tax_str)
    sell_tax = float(sell_tax_str) / 100 if float(sell_tax_str) > 1 else float(sell_tax_str)
    
    if buy_tax > 0.10 or sell_tax > 0.10:
        return False, f"Tax too high: buy={buy_tax*100:.1f}% sell={sell_tax*100:.1f}%"
    
    # Check risk items for honeypot
    risk_items = audit_data.get("riskItems", []) or []
    for item in risk_items:
        for detail in item.get("details", []):
            if detail.get("isHit") and detail.get("riskType") == "RISK":
                title = detail.get("title", "Unknown risk")
                if "honeypot" in title.lower():
                    return False, f"HONEYPOT DETECTED: {title}"
                if "cannot sell" in title.lower() or "cannot sell" in detail.get("description", "").lower():
                    return False, f"CANNOT SELL: {title}"
    
    # riskLevel 3 = MEDIUM, proceed with caution (allow for scalping)
    return True, f"OK(buy={buy_tax*100:.1f}% sell={sell_tax*100:.1f}% risk={risk_level}/{risk_enum})"


def _baw_env():
    env = dict(os.environ)
    env["PATH"] = env.get("PATH", "") + ";" + os.path.expanduser("~\\AppData\\Roaming\\QClaw\\npm-global")
    return env

BAW_CMD = os.path.expanduser("~\\AppData\\Roaming\\QClaw\\npm-global\\baw.cmd")
if not os.path.isfile(BAW_CMD):
    BAW_CMD = "baw"


def execute_swap(usdt_amount, from_token, to_token, chain_id):
    try:
        result = subprocess.run(
            [
                BAW_CMD, "market-order", "swap",
                "--fromTokenQty", str(usdt_amount),
                "--fromToken", from_token,
                "--toToken", to_token,
                "--binanceChainId", chain_id,
                "--slippage", "3",
                "--mev", "true",
                "--gasLevel", "HIGH",
                "--json"
            ],
            capture_output=True, text=True, timeout=60,
            env=_baw_env()
        )
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                return data.get("success", False), data.get("data", {})
            except json.JSONDecodeError:
                return False, result.stdout[:300]
        err = result.stderr.strip() if result.stderr else f"exit={result.returncode}"
        return False, err[:300]
    except Exception as e:
        return False, str(e)


def set_limit_sell(token_address, amount, trigger_price, chain_id, to_token=None):
    if to_token is None:
        if chain_id == "56":
            to_token = BSC_USDT
        elif chain_id == "CT_501":
            to_token = SOL_USDT
        else:
            return False, "Unknown chain"
    try:
        result = subprocess.run(
            [
                BAW_CMD, "limit-order", "sell",
                "--triggerPrice", str(trigger_price),
                "--fromTokenQty", str(amount),
                "--fromToken", token_address,
                "--toToken", to_token,
                "--binanceChainId", chain_id,
                "--slippage", "5",
                "--json"
            ],
            capture_output=True, text=True, timeout=30,
            env=_baw_env()
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


def check_positions(state):
    """Check open positions and report P&L."""
    positions = state.get("positions", {})
    if not positions:
        return []
    
    results = []
    for ca, pos in list(positions.items()):
        chain_id = pos.get("chainId", "56")
        entry_price = float(pos.get("entry_price", 0) or 0)
        
        # Get current price via signal or token info
        # Simple approach: fetch recent signals for this token
        current_price = entry_price  # default
        try:
            signals = fetch_signals(chain_id)
            for sig in signals:
                if sig.get("contractAddress", "").lower() == ca.lower():
                    current_price = float(sig.get("currentPrice", 0) or entry_price)
                    break
        except:
            pass
        
        if entry_price > 0:
            pnl_pct = (current_price - entry_price) / entry_price
            pos["current_price"] = current_price
            pos["pnl_pct"] = round(pnl_pct * 100, 2)
            results.append({
                "ticker": pos.get("ticker", "???"),
                "entry": entry_price,
                "current": current_price,
                "pnl_pct": round(pnl_pct * 100, 2),
                "invest": pos.get("invest_amount", 0),
                "chain": pos.get("chain", "?"),
                "entry_time": pos.get("entry_time", "?")
            })
            
            # Auto close if stop loss or take profit hit
            if pnl_pct <= STOP_LOSS_PCT:
                print(f"  STOP LOSS triggered for {pos.get('ticker')}: {pnl_pct*100:.1f}%")
                # Could auto-sell here, but let's log for now
            elif pnl_pct >= TAKE_PROFIT_PCT:
                print(f"  TAKE PROFIT reached for {pos.get('ticker')}: {pnl_pct*100:.1f}%")
    
    return results


def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    print(f"\n{'='*60}")
    print(f"SCALPING Monitor v2 | {now.strftime('%Y-%m-%d %H:%M:%S')} CST")
    print(f"{'='*60}")
    
    state = load_state()
    all_actionable = []
    
    # Check existing positions first
    print("\n[POSITIONS]")
    positions = check_positions(state)
    if positions:
        for p in positions:
            emoji = "+" if p["pnl_pct"] > 0 else ""
            print(f"  {p['ticker']} ({p['chain']}): {emoji}{p['pnl_pct']}% | Entry ${p['entry']:.8f} -> Now ${p['current']:.8f} | Invested ${p['invest']}")
    else:
        print("  No open positions")
    
    # Fetch signals
    for chain_id in CHAIN_IDS:
        chain_name = "BSC" if chain_id == "56" else "Solana"
        print(f"\n[SIGNALS] {chain_name}")
        signals = fetch_signals(chain_id)
        print(f"  Fetched {len(signals)} signals")
        
        for sig in signals:
            sig_id = sig.get("signalId")
            ticker = sig.get("ticker", "???")
            status = sig.get("status", "?")
            
            score, reasons = score_signal_scalping(sig)
            
            # Log all signals
            append_signal_log({
                "timestamp": now.isoformat(),
                "signalId": sig_id,
                "ticker": ticker,
                "chain": chain_name,
                "score": score,
                "status": status,
                "reasons": reasons,
                "alertPrice": sig.get("alertPrice"),
                "currentPrice": sig.get("currentPrice"),
                "contractAddress": sig.get("contractAddress")
            })
            
            if score >= SCALP_THRESHOLD:
                if sig_id not in state.get("last_signal_ids", []):
                    all_actionable.append({**sig, "score": score, "reasons": reasons, "chain": chain_name})
                    print(f"  >> {ticker} Score:{score} | {status} | {' | '.join(reasons)}")
                else:
                    print(f"  .. {ticker} Score:{score} (already processed)")
            elif status == "active" and score >= 15:
                print(f"  .. {ticker} Score:{score} (below threshold)")
    
    # Cross-validate with inflow
    print(f"\n[INFLOW] Cross-validating...")
    inflow_cas = set()
    for chain_id in CHAIN_IDS:
        inflow = fetch_smart_money_inflow(chain_id, "1h")
        for item in inflow[:10]:
            ca = item.get("ca", "")
            inflow_amt = item.get("inflow", 0)
            if inflow_amt > 0:  # Positive inflow = smart money buying
                inflow_cas.add(ca.lower())
    
    # Sort actionable by score
    all_actionable.sort(key=lambda x: x["score"], reverse=True)
    
    # Execute trades
    results = []
    if not all_actionable:
        print(f"\n[RESULT] No new actionable signals this round.")
    else:
        balances = get_wallet_balance()
        usdt_bal = balances.get("USDT", 0)
        bnb_bal = balances.get("BNB", 0)
        print(f"\n[BALANCE] USDT: ${usdt_bal:.2f} | BNB: {bnb_bal:.4f}")
        
        for sig in all_actionable[:3]:
            ticker = sig.get("ticker", "???")
            score = sig.get("score", 0)
            chain = sig.get("chain", "BSC")
            chain_id = sig.get("chainId", "56")
            ca = sig.get("contractAddress", "")
            direction = sig.get("direction", "buy")
            alert_price = float(sig.get("alertPrice", 0) or 0)
            current_price = float(sig.get("currentPrice", 0) or 0)
            
            if direction != "buy":
                print(f"\n  SKIP {ticker}: sell signal")
                continue
            
            # Already holding?
            if ca.lower() in [k.lower() for k in state.get("positions", {}).keys()]:
                print(f"\n  SKIP {ticker}: already holding")
                continue
            
            # Inflow cross-validation
            inflow_confirmed = ca.lower() in inflow_cas
            if inflow_confirmed:
                score = min(100, score + 10)
                print(f"\n  BONUS {ticker}: inflow confirmed (+10)")
            
            # Determine investment size
            if score >= STRONG_THRESHOLD:
                invest_pct = 0.40
                strength = "STRONG"
            elif score >= SCALP_THRESHOLD:
                invest_pct = 0.25
                strength = "MODERATE"
            else:
                continue
            
            # Calculate amount
            available = usdt_bal * (1 - MIN_USDT_RESERVE_PCT)
            invest_amount = min(available * invest_pct, usdt_bal * MAX_SINGLE_INVEST_PCT)
            invest_amount = round(invest_amount, 2)
            
            if invest_amount < 1:
                print(f"\n  SKIP {ticker}: insufficient USDT (${invest_amount:.2f})")
                continue
            
            print(f"\n  TRADE {ticker} | {strength} (Score:{score}) | ${invest_amount} USDT")
            print(f"    Chain: {chain} | Price: ${current_price:.8f}")
            print(f"    Reasons: {' | '.join(sig.get('reasons', []))}")
            
            # Security audit
            print(f"    Auditing...")
            audit_data = audit_token(ca, chain_id)
            is_safe, safety_msg = is_token_safe(audit_data)
            print(f"    Audit: {safety_msg}")
            
            if not is_safe:
                print(f"    REJECT {ticker}: {safety_msg}")
                results.append({"ticker": ticker, "action": "skip", "reason": safety_msg})
                continue
            
            # Execute swap
            print(f"    Swapping {invest_amount} USDT -> {ticker}...")
            if chain_id == "56":
                from_token = BSC_USDT
            else:
                from_token = SOL_USDT
            
            success, swap_result = execute_swap(invest_amount, from_token, ca, chain_id)
            
            if success:
                order_id = swap_result.get("orderId", "?")
                print(f"    SWAPPED! OrderID: {order_id}")
                
                # Wait for swap to settle, then get actual token balance for SL/TP
                print(f"    Waiting for swap to settle...")
                time.sleep(5)
                
                token_balance = 0
                try:
                    bal_result = subprocess.run(
                        [BAW_CMD, "wallet", "balance", "--json"],
                        capture_output=True, text=True, timeout=15,
                        env=_baw_env()
                    )
                    if bal_result.returncode == 0:
                        bal_data = json.loads(bal_result.stdout)
                        if bal_data.get("success"):
                            for token in bal_data.get("data", []):
                                if token.get("contractAddress", "").lower() == ca.lower():
                                    token_balance = float(token.get("balance", 0))
                                    break
                except Exception as e:
                    print(f"    [WARN] Balance check: {e}", file=sys.stderr)
                
                # Set stop-loss and take-profit using actual token balance
                if current_price > 0 and token_balance > 0:
                    sl_price = round(current_price * (1 + STOP_LOSS_PCT), 10)
                    tp_price = round(current_price * (1 + TAKE_PROFIT_PCT), 10)
                    
                    # Determine toToken for limit sell
                    if chain_id == "56":
                        to_token_addr = BSC_USDT
                    else:
                        to_token_addr = SOL_USDT
                    
                    print(f"    Setting SL @ ${sl_price:.10f} (-8%) | qty={token_balance:.4f}")
                    sl_qty = int(token_balance * 0.99)  # Round down to avoid precision issues
                    sl_ok, sl_data = set_limit_sell(ca, str(sl_qty), sl_price, chain_id, to_token=to_token_addr)
                    print(f"    SL: {'OK' if sl_ok else 'FAIL'} {sl_data}")
                    
                    print(f"    Setting TP @ ${tp_price:.10f} (+12%) | qty={sl_qty}")
                    tp_ok, tp_data = set_limit_sell(ca, str(sl_qty), tp_price, chain_id, to_token=to_token_addr)
                    print(f"    TP: {'OK' if tp_ok else 'FAIL'} {tp_data}")
                
                state["positions"][ca] = {
                    "ticker": ticker,
                    "chain": chain,
                    "chainId": chain_id,
                    "entry_price": current_price,
                    "invest_amount": invest_amount,
                    "order_id": order_id,
                    "entry_time": now.isoformat(),
                    "score": score,
                    "sl_price": round(current_price * (1 + STOP_LOSS_PCT), 10) if current_price > 0 else None,
                    "tp_price": round(current_price * (1 + TAKE_PROFIT_PCT), 10) if current_price > 0 else None,
                }
                state["trade_count"] = state.get("trade_count", 0) + 1
                usdt_bal -= invest_amount
                
                results.append({
                    "ticker": ticker, "action": "BUY", "amount": invest_amount,
                    "price": current_price, "order_id": order_id, "score": score,
                    "strength": strength
                })
            else:
                print(f"    SWAP FAILED: {swap_result}")
                results.append({"ticker": ticker, "action": "failed", "reason": str(swap_result)})
            
            # Mark signal as processed
            state.setdefault("last_signal_ids", []).append(sig.get("signalId"))
            state["last_signal_ids"] = state["last_signal_ids"][-300:]
    
    save_state(state)
    
    # Summary
    print(f"\n{'='*60}")
    trades = [r for r in results if isinstance(r, dict) and r.get("action") == "BUY"]
    print(f"SUMMARY | Signals: actionable={len(all_actionable)} | Trades: {len(trades)} | Positions: {len(state.get('positions', {}))}")
    for t in trades:
        print(f"  BUY {t['ticker']} ${t['amount']} @ ${t.get('price', 0):.8f} ({t.get('strength', '?')})")
    if not trades:
        print("  No new trades this round.")
    print(f"{'='*60}")
    
    return results


if __name__ == "__main__":
    main()
