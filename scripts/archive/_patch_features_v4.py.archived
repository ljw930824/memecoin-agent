#!/usr/bin/env python3
"""Patch v4: 4 features, no f-string escaping issues."""
import os, py_compile, shutil

SIM = os.path.expanduser("~/.qclaw/workspace/scripts/simulation/sm_monitor_sim.py")
MON = os.path.expanduser("~/.qclaw/workspace/scripts/active/realtime_sm_monitor.py")

def get_indent(lines, func_name="save_trade_history"):
    for i, line in enumerate(lines):
        if func_name in line and 'def ' in line:
            for j in range(i+1, min(i+5, len(lines))):
                s = lines[j].lstrip()
                if s and not s.startswith('"""'):
                    return len(lines[j]) - len(s)
    return 4

def insert_after(lines, marker, new_lines, context_start=0):
    """Insert new_lines after the first line matching marker (after context_start)."""
    for i in range(context_start, len(lines)):
        if marker in lines[i]:
            for j, nl in enumerate(new_lines):
                lines.insert(i + 1 + j, nl)
            return len(new_lines)
    return 0

def insert_before(lines, marker, new_lines, context_start=0):
    for i in range(context_start, len(lines)):
        if marker in lines[i]:
            for j, nl in enumerate(new_lines):
                lines.insert(i + j, nl)
            return len(new_lines)
    return 0

def patch_file(filepath, label):
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()

    bi = get_indent(lines)
    ind = ' ' * bi
    ind2 = ' ' * (bi + 4)
    ind3 = ' ' * (bi + 8)
    print(f"  [{label}] body indent={bi}")
    changes = 0

    # === FEATURE 1: Shared dedup ===
    content = ''.join(lines)
    if 'SHARED_DEDUP_FILE' not in content:
        # Insert constant after WALLET_FILE
        for i, line in enumerate(lines):
            if line.strip().startswith("WALLET_FILE = "):
                lines.insert(i+1, "\nSHARED_DEDUP_FILE = os.path.join(DATA, 'shared_bought.json')\nSHARED_DEDUP_TTL = 3600\n")
                changes += 1
                print(f"  [{label}] +SHARED const")
                break

    content = ''.join(lines)
    if '_load_shared_dedup' not in content:
        # Insert functions before reload_positions
        funcs = [
            "\n\n",
            "def _load_shared_dedup():\n",
            "    try:\n",
            "        if os.path.exists(SHARED_DEDUP_FILE):\n",
            "            with open(SHARED_DEDUP_FILE, 'r', encoding='utf-8') as f:\n",
            "                return json.load(f)\n",
            "    except:\n",
            "        pass\n",
            "    return {}\n\n\n",
            "def _save_shared_dedup(data):\n",
            "    try:\n",
            "        with open(SHARED_DEDUP_FILE, 'w', encoding='utf-8') as f:\n",
            "            json.dump(data, f)\n",
            "    except:\n",
            "        pass\n\n\n",
            "def _check_shared_dedup(ca):\n",
            "    now = int(time.time())\n",
            "    dedup = _load_shared_dedup()\n",
            "    entry = dedup.get(ca, {})\n",
            "    if entry and (now - entry.get('ts', 0)) < SHARED_DEDUP_TTL:\n",
            "        return True\n",
            "    return False\n\n\n",
            "def _record_shared_dedup(ca, chain, sym):\n",
            "    now = int(time.time())\n",
            "    dedup = _load_shared_dedup()\n",
            "    dedup[ca] = {'ts': now, 'chain': chain, 'sym': sym}\n",
            "    cutoff = now - SHARED_DEDUP_TTL * 2\n",
            "    dedup = {k: v for k, v in dedup.items() if v.get('ts', 0) > cutoff}\n",
            "    _save_shared_dedup(dedup)\n",
        ]
        for i, line in enumerate(lines):
            if line.strip().startswith("def reload_positions_if_external_change"):
                for j, fl in enumerate(funcs):
                    lines.insert(i + j, fl)
                changes += 1
                print(f"  [{label}] +SHARED funcs")
                break

    content = ''.join(lines)
    if '_check_shared_dedup(ca)' not in content:
        # Insert after "recently traded (cooldown)" + continue
        for i, line in enumerate(lines):
            if "recently traded (cooldown)" in line:
                for j in range(i+1, min(i+3, len(lines))):
                    if 'continue' in lines[j]:
                        check = [
                            "\n",
                            "            # Cross-chain dedup\n",
                            "            if _check_shared_dedup(ca):\n",
                            "                log(f'SKIP {sym}: cross-chain dedup')\n",
                            "                continue\n",
                        ]
                        for k, cl in enumerate(check):
                            lines.insert(j + 1 + k, cl)
                        changes += 1
                        print(f"  [{label}] +SHARED check")
                        break
                break

    content = ''.join(lines)
    if '_record_shared_dedup' not in content:
        for i, line in enumerate(lines):
            if "Record in trade_history for dedup" in line:
                lines.insert(i, "                _record_shared_dedup(ca, chain, sym)\n\n")
                changes += 1
                print(f"  [{label}] +SHARED record")
                break

    # === FEATURE 2: Consecutive SL ===
    content = ''.join(lines)
    if 'CONSEC_SL_LIMIT' not in content:
        for i, line in enumerate(lines):
            if line.strip() == "SM_SELL_FOLLOW = 3":
                lines.insert(i+1, "CONSEC_SL_LIMIT = 3\nCONSEC_SL_FREEZE_SEC = 7200\n")
                changes += 1
                print(f"  [{label}] +CONSEC const")
                break

    content = ''.join(lines)
    if 'consec_sl_freeze_until' not in content:
        for i, line in enumerate(lines):
            if "monthly pause until" in line and "return False" in line:
                check = [
                    "    # Consecutive SL freeze check\n",
                    "    consec_sl = state.get('consec_sl', 0)\n",
                    "    freeze_until = state.get('consec_sl_freeze_until', 0)\n",
                    "    if freeze_until and now < freeze_until:\n",
                    "        from datetime import datetime\n",
                    "        fu = datetime.fromtimestamp(freeze_until).strftime('%m-%d %H:%M')\n",
                    "        return False, f'consec SL freeze until {fu}'\n\n",
                ]
                for j, cl in enumerate(check):
                    lines.insert(i + 1 + j, cl)
                changes += 1
                print(f"  [{label}] +CONSEC check")
                break

    content = ''.join(lines)
    if "state['consec_sl']" not in content:
        for i, line in enumerate(lines):
            if "trade_history:" in line and "closed pnl" in line and "reason" in line:
                # Build lines WITHOUT f-strings to avoid escaping issues
                incr = []
                incr.append(ind + "# Track consecutive stop losses\n")
                incr.append(ind + "if reason == 'stop_loss':\n")
                incr.append(ind2 + "state['consec_sl'] = state.get('consec_sl', 0) + 1\n")
                incr.append(ind2 + "cs = state['consec_sl']\n")
                incr.append(ind2 + "if cs >= CONSEC_SL_LIMIT:\n")
                incr.append(ind3 + "state['consec_sl_freeze_until'] = int(time.time()) + CONSEC_SL_FREEZE_SEC\n")
                incr.append(ind3 + "log(f'CONSEC SL: {cs} losses -> freeze 2h')\n")
                incr.append(ind2 + "else:\n")
                incr.append(ind3 + "log(f'CONSEC SL: {cs}/{CONSEC_SL_LIMIT}')\n")
                incr.append(ind + "elif reason not in ('dead_position',):\n")
                incr.append(ind2 + "if state.get('consec_sl', 0) > 0:\n")
                incr.append(ind3 + "log('CONSEC SL reset')\n")
                incr.append(ind2 + "state['consec_sl'] = 0\n")
                incr.append(ind2 + "state['consec_sl_freeze_until'] = 0\n")
                for j, il in enumerate(incr):
                    lines.insert(i + 1 + j, il)
                changes += 1
                print(f"  [{label}] +CONSEC incr")
                break

    # === FEATURE 3: soldRatio ===
    content = ''.join(lines)
    if '_check_sold_ratio' not in content:
        for i, line in enumerate(lines):
            if line.strip().startswith("def execute_sell("):
                func = [
                    "\n\n",
                    "def _check_sold_ratio(chain, ca):\n",
                    '    """Check soldRatio from onchainos API."""\n',
                    "    try:\n",
                    "        r = subprocess.run(\n",
                    "            ['onchainos', 'token', 'price-info', '--address', ca, '--chain', chain],\n",
                    "            capture_output=True, timeout=8, encoding='utf-8', errors='replace'\n",
                    "        )\n",
                    "        if r.returncode == 0 and r.stdout.strip():\n",
                    "            data = json.loads(r.stdout.strip())\n",
                    "            sr = data.get('soldRatio')\n",
                    "            if sr is not None:\n",
                    "                return float(sr)\n",
                    "    except:\n",
                    "        pass\n",
                    "    return None\n",
                ]
                for j, fl in enumerate(func):
                    lines.insert(i + j, fl)
                changes += 1
                print(f"  [{label}] +SOLDRATIO func")
                break

    content = ''.join(lines)
    if 'soldRatio=' not in content:
        for i, line in enumerate(lines):
            if line.strip().startswith("entry_price = get_token_price_usd") and i > 1500:
                check = [
                    "            # soldRatio check\n",
                    "            sr = _check_sold_ratio(chain, ca)\n",
                    "            if sr is not None:\n",
                    "                if sr >= 0.50:\n",
                    "                    log(f'SKIP {sym}: soldRatio={sr:.0%} (holder dump)')\n",
                    "                    continue\n",
                    "                elif sr >= 0.30:\n",
                    "                    log(f'WARN {sym}: soldRatio={sr:.0%} (penalty)')\n",
                    "                    if good_buyers < MIN_CONSENSUS_WALLETS + 1:\n",
                    "                        log(f'SKIP {sym}: soldRatio penalty')\n",
                    "                        continue\n\n",
                ]
                for j, cl in enumerate(check):
                    lines.insert(i + j, cl)
                changes += 1
                print(f"  [{label}] +SOLDRATIO check")
                break

    # === FEATURE 4: Breakeven tier ===
    content = ''.join(lines)
    if 'breakeven' not in content:
        for i, line in enumerate(lines):
            if line.strip().startswith("TIME_TIERS = ["):
                breakeven = [
                    "\n",
                    "    # (hold_hours, SL PnL, TP PnL, sell_pct, label)\n",
                    "\n",
                    "    # breakeven: at +5% sell ~77% to recover cost\n",
                    "    (0,   None, 0.05,  0.77, 'breakeven'),\n",
                    "\n",
                ]
                for j, bl in enumerate(breakeven):
                    lines.insert(i + 1 + j, bl)
                changes += 1
                print(f"  [{label}] +BREAKEVEN")
                break

    if changes > 0:
        bak = filepath + '.pre_feat4'
        if not os.path.exists(bak):
            shutil.copy2(filepath, bak)
        with open(filepath, 'w', encoding='utf-8-sig') as f:
            f.writelines(lines)
        print(f"  [{label}] wrote {changes} changes")
    else:
        print(f"  [{label}] no changes")


def main():
    print("=== Feature Patch v4 ===\n")
    for fp, label in [(SIM, 'sim'), (MON, 'monitor')]:
        if os.path.exists(fp):
            patch_file(fp, label)
        else:
            print(f"  [{label}] NOT FOUND")

    print("\n=== Compile check ===")
    for fp, label in [(SIM, 'sim'), (MON, 'monitor')]:
        if os.path.exists(fp):
            try:
                py_compile.compile(fp, doraise=True)
                print(f"  [OK] {label}")
            except py_compile.PyCompileError as e:
                print(f"  [FAIL] {label}: {e}")

if __name__ == '__main__':
    main()
