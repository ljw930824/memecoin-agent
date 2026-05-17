"""
Patch scalper_v3.py:
1. Add swap_bnb_to_usdt() function
2. Add BNB auto-refill when USDT < threshold
3. Add position snapshot tracking for change monitoring
"""
import re

path = r'C:\Users\dell\.qclaw\workspace\scripts\scalper_v3.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# === 1. Add BNB config constants after MIN_USDT_RESERVE_PCT ===
old_reserve = 'MIN_USDT_RESERVE_PCT = 0.15'
new_reserve = '''MIN_USDT_RESERVE_PCT = 0.15
BNB_TOPUP_THRESHOLD = 10.0     # Auto swap BNB->USDT when USDT below this
BNB_TOPUP_AMOUNT_BNB = 0.008   # BNB amount to swap (~$5 worth)'''
content = content.replace(old_reserve, new_reserve)

# === 2. Add swap_bnb_to_usdt() function after execute_swap() ===
old_baw = '''def set_limit_sell(token_addr, qty, trigger_price, chain_id, to_token=None):'''
new_baw = '''def swap_bnb_to_usdt(bnb_amount, chain_id="56"):
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


def set_limit_sell(token_addr, qty, trigger_price, chain_id, to_token=None):'''
content = content.replace(old_baw, new_baw)

# === 3. Add snapshot tracking in state ===
old_snap = '''def append_signal_log(entry):'''
new_snap = '''SNAPSHOT_FILE = os.path.join(DATA_DIR, "position-snapshot.json")

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


def append_signal_log(entry):'''
content = content.replace(old_snap, new_snap)

# === 4. Add BNB top-up logic in _scan_signals before budget calc ===
old_budget = '''    usdt_bal = balances.get("by_sym", {}).get("USDT", {}).get("value", 0)
    profit_pool = state.get("profit_pool", 0)

    print(f"\\n[BALANCE] USDT: ${usdt_bal:.2f} | Profit pool: ${profit_pool:.2f}")

    # Effective budget = USDT + reinvestable profits
    effective_budget = usdt_bal + max(0, profit_pool)'''

new_budget = '''    usdt_bal = balances.get("by_sym", {}).get("USDT", {}).get("value", 0)
    bnb_bal  = balances.get("by_sym", {}).get("BNB", {}).get("balance", 0)
    bnb_value = balances.get("by_sym", {}).get("BNB", {}).get("value", 0)
    profit_pool = state.get("profit_pool", 0)

    print(f"\\n[BALANCE] USDT: ${usdt_bal:.2f} | BNB: {bnb_bal:.5f} (${bnb_value:.2f}) | Profit pool: ${profit_pool:.2f}")

    # Auto top-up USDT from BNB if running low
    if usdt_bal < BNB_TOPUP_THRESHOLD and bnb_bal > BNB_TOPUP_AMOUNT_BNB and not skip_trade:
        swap_bnb_to_usdt(BNB_TOPUP_AMOUNT_BNB)
        time.sleep(3)
        balances = get_wallet_balances()
        usdt_bal = balances.get("by_sym", {}).get("USDT", {}).get("value", 0)
        bnb_bal  = balances.get("by_sym", {}).get("BNB", {}).get("balance", 0)
        print(f"  [BALANCE-UPDATED] USDT: ${usdt_bal:.2f} | BNB: {bnb_bal:.5f}")

    # Effective budget = USDT + reinvestable profits
    effective_budget = usdt_bal + max(0, profit_pool)'''

content = content.replace(old_budget, new_budget)

# === 5. Add position change monitoring in main() after positions display ===
old_pos_end = '''    else:
        print("  No open positions")

    # ── Profit pool summary ──'''

new_pos_end = '''    else:
        print("  No open positions")

    # ── Position change monitoring ──
    prev_snap = load_previous_snapshot()
    if positions and prev_snap:
        prev_positions = prev_snap.get("positions", {})
        prev_ts = prev_snap.get("ts", "?")
        print(f"\\n[POSITION CHANGES] vs snapshot ({prev_ts})")
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
        print(f"\\n[POSITION CHANGES] No previous snapshot (first run with monitoring)")

    save_position_snapshot(state.get("positions", {}))

    # ── Profit pool summary ──'''

content = content.replace(old_pos_end, new_pos_end)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Patch applied successfully!")
