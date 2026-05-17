#!/usr/bin/env python3
"""
Smart Money Signal Monitor & Auto-Trader
Monitors Binance smart money signals and executes trades based on strategy rules.

Strategy Rules:
1. Only trade ACTIVE signals (status == "active")
2. Signal Strength Score (0-100):
   - smartMoneyCount >= 5: +30 points
   - smartMoneyCount >= 3: +15 points
   - Signal is "buy" direction: +10 points
   - launchPlatform is Pumpfun/Four.meme: +5 points (high volatility)
   - Token has "DEX Paid" tag: +5 points
   - Token has "Smart Money Add Holdings" tag: +10 points
   - Token has "Whale Buy" tag: +10 points
   - Market cap > $100k: +10 points
   - Market cap > $1M: +5 points
   - Multiple signals (signalCount >= 10): +5 points
3. Score >= 50: STRONG signal -> invest up to 30% of available USDT
4. Score >= 35: MODERATE signal -> invest up to 15% of available USDT
5. Score < 35: WEAK signal -> skip, notify only
6. Always do security audit before trading
7. Stop-loss: -20% from buy price (via limit sell)
8. Take-profit: +50% from buy price (via limit sell)
9. Never invest more than 30% of total portfolio in a single token
10. Keep at least 20% USDT reserve

State file: ~/.qclaw/workspace/data/smart-money-state.json
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

# Config
STATE_FILE = os.path.expanduser("~/.qclaw/workspace/data/smart-money-state.json")
DATA_DIR = os.path.expanduser("~/.qclaw/workspace/data")
TRADE_LOG = os.path.join(DATA_DIR, "trade-log.json")
SIGNAL_LOG = os.path.join(DATA_DIR, "signal-log.json")
CHAIN_IDS = ["56", "CT_501"]  # BSC + Solana
MAX_SINGLE_INVEST_PCT = 0.30   # Max 30% of USDT in single token
MIN_USDT_RESERVE_PCT = 0.20    # Keep at least 20% USDT
STOP_LOSS_PCT = -0.20          # -20% stop loss
TAKE_PROFIT_PCT = 0.50         # +50% take profit
STRONG_THRESHOLD = 50          # Score >= 50: strong signal
MODERATE_THRESHOLD = 35        # Score >= 35: moderate signal

# Ensure data dir exists
os.makedirs(DATA_DIR, exist_ok=True)

def load_state():
    """Load state from JSON file."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"positions": {}, "last_signal_ids": [], "daily_pnl": 0, "trade_count": 0}

def save_state(state):
    """Save state to JSON file."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def load_signal_log():
    """Load signal log."""
    if os.path.exists(SIGNAL_LOG):
        with open(SIGNAL_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def append_signal_log(entry):
    """Append to signal log."""
    log = load_signal_log()
    log.append(entry)
    # Keep last 500 entries
    if len(log) > 500:
        log = log[-500:]
    with open(SIGNAL_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

def fetch_signals(chain_id, page=1, page_size=50):
    """Fetch smart money signals from Binance API."""
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
        print(f"[ERROR] Fetch signals failed for chain {chain_id}: {e}", file=sys.stderr)
    return []

def fetch_smart_money_inflow(chain_id, period="24h"):
    """Fetch smart money inflow ranking for cross-validation."""
    import urllib.request
    url = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/tracker/wallet/token/inflow/rank/query/ai"
    headers = {
        "Content-Type": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": "binance-web3/2.1 (Skill)"
    }
    body = json.dumps({
        "chainId": chain_id,
        "period": period,
        "tagType": 2
    }).encode("utf-8")
    
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success") and data.get("data"):
                return data["data"]
    except Exception as e:
        print(f"[ERROR] Fetch inflow failed for chain {chain_id}: {e}", file=sys.stderr)
    return []

def score_signal(signal):
    """
    Calculate signal strength score (0-100).
    Higher score = stronger signal = more confidence to trade.
    """
    score = 0
    reasons = []
    
    # Smart money count (more = better)
    smc = signal.get("smartMoneyCount", 0)
    if smc >= 5:
        score += 30
        reasons.append(f"smartMoneyCount={smc}(>=5)")
    elif smc >= 3:
        score += 15
        reasons.append(f"smartMoneyCount={smc}(>=3)")
    
    # Direction (buy is what we want)
    direction = signal.get("direction", "")
    if direction == "buy":
        score += 10
        reasons.append("direction=buy")
    elif direction == "sell":
        # Sell signals from smart money are warnings, not buy opportunities
        score -= 20
        reasons.append("direction=sell(BEARISH)")
    
    # Signal count (more = stronger consensus)
    sc = signal.get("signalCount", 0)
    if sc >= 10:
        score += 5
        reasons.append(f"signalCount={sc}(>=10)")
    
    # Token tags
    tags = signal.get("tokenTag", {})
    for category, tag_list in tags.items():
        for tag_item in tag_list:
            tag_name = tag_item.get("tagName", "")
            if tag_name == "Smart Money Add Holdings":
                score += 10
                reasons.append("tag:SmartMoneyAddHoldings")
            elif tag_name == "Whale Buy":
                score += 10
                reasons.append("tag:WhaleBuy")
            elif tag_name == "DEX Paid":
                score += 5
                reasons.append("tag:DEXPaid")
            elif tag_name == "Smart Money Reduce Holdings":
                score -= 15
                reasons.append("tag:SmartMoneyReduce(BEARISH)")
            elif tag_name == "Whale Sell":
                score -= 15
                reasons.append("tag:WhaleSell(BEARISH)")
    
    # Market cap (need some liquidity)
    mc = float(signal.get("alertMarketCap", 0) or 0)
    if mc >= 1000000:
        score += 15
        reasons.append(f"mcap=${mc/1e6:.1f}M(>=1M)")
    elif mc >= 100000:
        score += 10
        reasons.append(f"mcap=${mc/1e3:.0f}K(>=100K)")
    
    # Launch platform
    lp = signal.get("launchPlatform", "")
    if lp in ("Pumpfun", "Four.meme"):
        score += 5
        reasons.append(f"platform={lp}")
    
    # Status must be active
    status = signal.get("status", "")
    if status != "active":
        score = 0
        reasons.insert(0, f"NOT ACTIVE(status={status})")
    
    return max(0, min(100, score)), reasons

def get_wallet_balance():
    """Get current USDT balance from wallet."""
    try:
        result = subprocess.run(
            ["baw", "wallet", "balance", "--json"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get("success"):
                for token in data.get("data", []):
                    if "USDT" in token.get("symbol", "").upper():
                        return float(token.get("balance", 0))
    except Exception as e:
        print(f"[ERROR] Get wallet balance: {e}", file=sys.stderr)
    return 0

def audit_token(contract_address, chain_id):
    """Run token security audit."""
    import urllib.request
    if chain_id == "CT_501":
        url = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/token/security/audit/ai"
    else:
        url = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/token/security/audit/ai"
    
    headers = {
        "Content-Type": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": "binance-web3/1.4 (Skill)"
    }
    body = json.dumps({
        "chainId": chain_id,
        "contractAddress": contract_address
    }).encode("utf-8")
    
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success") and data.get("data"):
                return data["data"]
    except Exception as e:
        print(f"[ERROR] Token audit failed: {e}", file=sys.stderr)
    return None

def is_token_safe(audit_data):
    """Check if token passes security audit."""
    if not audit_data:
        return False, "Audit data unavailable"
    
    # Check for honeypot
    if audit_data.get("isHoneypot"):
        return False, "HONEYPOT detected!"
    
    # Check buy/sell tax
    buy_tax = float(audit_data.get("buyTax", 0) or 0)
    sell_tax = float(audit_data.get("sellTax", 0) or 0)
    if buy_tax > 0.10 or sell_tax > 0.10:
        return False, f"High tax: buy={buy_tax*100:.1f}%, sell={sell_tax*100:.1f}%"
    
    # Check risk level
    risk = audit_data.get("riskLevel", 3)
    if risk >= 3:
        return False, f"High risk level: {risk}"
    
    return True, f"Safe (buyTax={buy_tax*100:.1f}%, sellTax={sell_tax*100:.1f}%, risk={risk})"

def execute_swap(usdt_amount, from_token, to_token, chain_id):
    """Execute a market swap via baw CLI."""
    try:
        result = subprocess.run(
            [
                "baw", "market-order", "swap",
                "--fromTokenQty", str(usdt_amount),
                "--fromToken", from_token,
                "--toToken", to_token,
                "--binanceChainId", chain_id,
                "--slippage", "5",
                "--mev", "true",
                "--gasLevel", "HIGH",
                "--json"
            ],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("success", False), data.get("data", {})
        return False, result.stderr
    except Exception as e:
        return False, str(e)

def set_limit_sell(token_address, amount, trigger_price, chain_id, to_token=None):
    """Set a limit sell order for take-profit or stop-loss."""
    if to_token is None:
        # Default to USDT
        if chain_id == "56":
            to_token = "0x55d398326f99059fF775485246999027B3197955"
        elif chain_id == "CT_501":
            to_token = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
        else:
            return False, "Unknown chain"
    
    try:
        result = subprocess.run(
            [
                "baw", "limit-order", "sell",
                "--triggerPrice", str(trigger_price),
                "--fromTokenQty", str(amount),
                "--fromToken", token_address,
                "--toToken", to_token,
                "--binanceChainId", chain_id,
                "--slippage", "5",
                "--json"
            ],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("success", False), data.get("data", {})
        return False, result.stderr
    except Exception as e:
        return False, str(e)

def main():
    """Main monitoring loop - runs once per invocation."""
    now = datetime.now(timezone(timedelta(hours=8)))
    print(f"\n{'='*60}")
    print(f"Smart Money Monitor | {now.strftime('%Y-%m-%d %H:%M:%S')} CST")
    print(f"{'='*60}")
    
    state = load_state()
    all_signals = []
    actionable_signals = []
    
    # Fetch signals from all chains
    for chain_id in CHAIN_IDS:
        chain_name = "BSC" if chain_id == "56" else "Solana"
        print(f"\n📡 Fetching {chain_name} signals...")
        signals = fetch_signals(chain_id)
        print(f"   Found {len(signals)} signals on {chain_name}")
        
        for sig in signals:
            sig_id = sig.get("signalId")
            ticker = sig.get("ticker", "???")
            direction = sig.get("direction", "?")
            status = sig.get("status", "?")
            smc = sig.get("smartMoneyCount", 0)
            
            # Score the signal
            score, reasons = score_signal(sig)
            
            # Log signal
            log_entry = {
                "timestamp": now.isoformat(),
                "signalId": sig_id,
                "ticker": ticker,
                "chain": chain_name,
                "direction": direction,
                "status": status,
                "smartMoneyCount": smc,
                "score": score,
                "alertPrice": sig.get("alertPrice"),
                "currentPrice": sig.get("currentPrice"),
                "contractAddress": sig.get("contractAddress"),
                "reasons": reasons
            }
            append_signal_log(log_entry)
            
            # Track actionable signals
            if score >= MODERATE_THRESHOLD and status == "active":
                # Skip if we already processed this signal
                if sig_id in state.get("last_signal_ids", []):
                    continue
                actionable_signals.append({**sig, "score": score, "reasons": reasons, "chain": chain_name})
                print(f"   ⚡ {ticker} ({direction}) | Score: {score} | SM: {smc} | {' | '.join(reasons)}")
            elif status == "active":
                print(f"   📊 {ticker} ({direction}) | Score: {score} | SM: {smc} | (below threshold)")
    
    # Sort by score (highest first)
    actionable_signals.sort(key=lambda x: x["score"], reverse=True)
    
    # Fetch smart money inflow for cross-validation
    print(f"\n📡 Cross-validating with Smart Money Inflow rankings...")
    inflow_tokens = {}
    for chain_id in CHAIN_IDS:
        inflow_data = fetch_smart_money_inflow(chain_id, "24h")
        for item in inflow_data[:20]:
            ca = item.get("ca", "")
            inflow_tokens[ca] = {
                "inflow": item.get("inflow", 0),
                "traders": item.get("traders", 0),
                "priceChangeRate": item.get("priceChangeRate", "0")
            }
    
    # Process actionable signals
    results = []
    if not actionable_signals:
        print(f"\n✅ No new actionable signals this round.")
        results.append("no_action")
    else:
        usdt_balance = get_wallet_balance()
        print(f"\n💰 Available USDT: ${usdt_balance:.2f}")
        
        for sig in actionable_signals[:3]:  # Max 3 signals per round
            ticker = sig.get("ticker", "???")
            score = sig.get("score", 0)
            chain = sig.get("chain", "BSC")
            chain_id = sig.get("chainId", "56")
            ca = sig.get("contractAddress", "")
            direction = sig.get("direction", "buy")
            alert_price = float(sig.get("alertPrice", 0) or 0)
            current_price = float(sig.get("currentPrice", 0) or 0)
            
            # Skip sell signals
            if direction != "buy":
                print(f"\n   ⏭️ {ticker}: Sell signal - skipping (not a buy opportunity)")
                continue
            
            # Cross-validate with inflow data
            inflow_info = inflow_tokens.get(ca, {})
            inflow_amount = inflow_info.get("inflow", 0)
            if inflow_amount > 0:
                print(f"\n   ✅ {ticker}: Confirmed by inflow data (${inflow_amount:.0f} net inflow)")
                # Bonus points for inflow confirmation
                score = min(100, score + 10)
            else:
                print(f"\n   ⚠️ {ticker}: No inflow confirmation found")
            
            # Determine investment amount
            if score >= STRONG_THRESHOLD:
                invest_pct = 0.30
                strength = "STRONG"
            elif score >= MODERATE_THRESHOLD:
                invest_pct = 0.15
                strength = "MODERATE"
            else:
                continue
            
            # Calculate amount
            available = usdt_balance * (1 - MIN_USDT_RESERVE_PCT)  # Reserve 20%
            invest_amount = min(available * invest_pct, usdt_balance * MAX_SINGLE_INVEST_PCT)
            invest_amount = round(invest_amount, 2)
            
            if invest_amount < 1:
                print(f"   ❌ {ticker}: Insufficient USDT (${invest_amount:.2f} < $1 minimum)")
                continue
            
            print(f"\n   🎯 {ticker} | Score: {score} ({strength})")
            print(f"      Chain: {chain} | Price: ${current_price:.6f}")
            print(f"      Plan: Invest ${invest_amount:.2f} USDT")
            print(f"      Reasons: {' | '.join(sig.get('reasons', []))}")
            
            # Security audit
            print(f"      🔍 Running security audit...")
            audit_data = audit_token(ca, chain_id)
            is_safe, safety_msg = is_token_safe(audit_data)
            print(f"      🛡️ Audit: {safety_msg}")
            
            if not is_safe:
                print(f"      ❌ {ticker}: FAILED security audit - {safety_msg}")
                results.append({"ticker": ticker, "action": "skip", "reason": safety_msg})
                continue
            
            # Execute trade
            print(f"      🔄 Executing swap: {invest_amount} USDT → {ticker}...")
            
            # Determine fromToken (USDT address)
            if chain_id == "56":
                from_token = "0x55d398326f99059fF775485246999027B3197955"
            elif chain_id == "CT_501":
                from_token = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
            else:
                continue
            
            success, swap_result = execute_swap(invest_amount, from_token, ca, chain_id)
            
            if success:
                order_id = swap_result.get("orderId", "unknown")
                print(f"      ✅ Swap submitted! OrderID: {order_id}")
                
                # Set stop-loss and take-profit limit orders
                if current_price > 0:
                    sl_price = round(current_price * (1 + STOP_LOSS_PCT), 8)
                    tp_price = round(current_price * (1 + TAKE_PROFIT_PCT), 8)
                    
                    # Estimate token amount received
                    est_tokens = invest_amount / current_price
                    
                    print(f"      📉 Setting stop-loss at ${sl_price:.8f} (-20%)")
                    sl_ok, sl_result = set_limit_sell(ca, f"{est_tokens:.6f}", sl_price, chain_id)
                    if sl_ok:
                        print(f"         ✅ Stop-loss set: {sl_result.get('strategyId')}")
                    else:
                        print(f"         ❌ Stop-loss failed: {sl_result}")
                    
                    print(f"      📈 Setting take-profit at ${tp_price:.8f} (+50%)")
                    tp_ok, tp_result = set_limit_sell(ca, f"{est_tokens:.6f}", tp_price, chain_id)
                    if tp_ok:
                        print(f"         ✅ Take-profit set: {tp_result.get('strategyId')}")
                    else:
                        print(f"         ❌ Take-profit failed: {tp_result}")
                
                # Update state
                state["positions"][ca] = {
                    "ticker": ticker,
                    "chain": chain,
                    "chainId": chain_id,
                    "entry_price": current_price,
                    "invest_amount": invest_amount,
                    "order_id": order_id,
                    "entry_time": now.isoformat(),
                    "score": score,
                    "stop_loss_price": round(current_price * (1 + STOP_LOSS_PCT), 8) if current_price > 0 else None,
                    "take_profit_price": round(current_price * (1 + TAKE_PROFIT_PCT), 8) if current_price > 0 else None,
                }
                state["trade_count"] = state.get("trade_count", 0) + 1
                usdt_balance -= invest_amount
                
                results.append({
                    "ticker": ticker, "action": "buy", "amount": invest_amount,
                    "price": current_price, "order_id": order_id, "score": score
                })
            else:
                print(f"      ❌ Swap failed: {swap_result}")
                results.append({"ticker": ticker, "action": "failed", "reason": str(swap_result)})
            
            # Record signal as processed
            state.setdefault("last_signal_ids", []).append(sig.get("signalId"))
            # Keep only last 200 signal IDs
            state["last_signal_ids"] = state["last_signal_ids"][-200:]
    
    # Save state
    save_state(state)
    
    # Summary
    print(f"\n{'='*60}")
    print(f"📊 Monitor Summary | {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"   Signals scanned: {sum(len(fetch_signals(c)) for c in CHAIN_IDS)}")
    print(f"   Actionable: {len(actionable_signals)}")
    print(f"   Trades executed: {len([r for r in results if isinstance(r, dict) and r.get('action') == 'buy'])}")
    print(f"   Open positions: {len(state.get('positions', {}))}")
    print(f"{'='*60}")
    
    return results

if __name__ == "__main__":
    main()
