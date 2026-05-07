#!/usr/bin/env python3
"""
patch_log_and_wallet.py - Add log rotation + date prefix, wallet slimming
"""
import os
import re
import py_compile

SIM = os.path.expanduser("~/.qclaw/workspace/scripts/simulation/sm_monitor_sim.py")
MON = os.path.expanduser("~/.qclaw/workspace/scripts/active/realtime_sm_monitor.py")

# Log rotation function to add after the log() function
LOG_ROTATION_FUNC = '''
LOG_ROTATE_SIZE = 5 * 1024 * 1024  # 5MB

def _rotate_log_if_needed():
    """Rotate log file if exceeds LOG_ROTATE_SIZE. Archive old to archive/logs/."""
    try:
        if not os.path.exists(LOG_FILE):
            return
        if os.path.getsize(LOG_FILE) < LOG_ROTATE_SIZE:
            return
        # Archive current log
        log_dir = os.path.join(DATA, "archive", "logs")
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = os.path.join(log_dir, f"sm_trade-log_{ts}.txt")
        os.rename(LOG_FILE, archive_name)
        # Decay old archived logs (keep 30 days)
        _decay_old_logs(log_dir)
    except Exception:
        pass

def _decay_old_logs(log_dir, max_age_days=30):
    """Remove archived log files older than max_age_days."""
    try:
        cutoff = time.time() - max_age_days * 86400
        for fn in os.listdir(log_dir):
            if fn.startswith("sm_trade-log_") and fn.endswith(".txt"):
                fp = os.path.join(log_dir, fn)
                if os.path.getmtime(fp) < cutoff:
                    os.remove(fp)
    except Exception:
        pass
'''

# Slimmed load_wallets function - replaces the original load_wallets body
# Only keeps winrate and addr fields, drops full buy/sell lists
SLIMMED_LOAD_WALLETS = '''
def load_wallets():
    """Load wallet data from JSON file (slimmed: only winrate per address for sim)."""
    wf = os.path.join(DATA, WALLET_FILE)
    if not os.path.exists(wf):
        return {}
    try:
        with open(wf, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        # Slim: keep only addr + winrate fields, drop buy/sell lists (saves ~90% memory)
        slim = {}
        for addr, info in raw.items():
            if isinstance(info, dict):
                slim[addr] = {
                    'addr': addr,
                    'winrate': info.get('winrate', 0),
                    'total': info.get('total', 0),
                    'wins': info.get('wins', 0),
                    'source_chain': info.get('source_chain', ''),
                }
            else:
                slim[addr] = info
        return slim
    except Exception:
        return {}
'''


def patch_file(filepath, label):
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()

    stripped = [l.rstrip('\n') for l in lines]
    original = list(stripped)
    patches = []

    # --- 1. Change log format: add date ---
    for i, line in enumerate(stripped):
        if "strftime('%H:%M:%S')" in line and 'def log(' not in line:
            stripped[i] = line.replace("strftime('%H:%M:%S')", "strftime('%Y-%m-%d %H:%M:%S')")
            patches.append('log_date_prefix')
            break

    # --- 2. Add rotation call at start of log() ---
    has_rotate_call = any('_rotate_log_if_needed' in l for l in stripped)
    if not has_rotate_call:
        for i, line in enumerate(stripped):
            if "ts = datetime.now" in line and i > 0:
                # Check if this is inside log() function
                for j in range(i-1, max(0, i-5), -1):
                    if 'def log(' in stripped[j]:
                        # Insert _rotate_log_if_needed() call right after ts = ... line
                        indent = '    '
                        stripped.insert(i + 1, f'{indent}_rotate_log_if_needed()')
                        patches.append('log_rotate_call')
                        break
                break

    # --- 3. Add _rotate_log_if_needed + _decay_old_logs after log() function ---
    has_rotate_func = any('def _rotate_log_if_needed' in l for l in stripped)
    if not has_rotate_func:
        # Find end of log() function (next def at same indentation level)
        log_end = -1
        in_log = False
        for i, line in enumerate(stripped):
            if line.startswith('def log('):
                in_log = True
                continue
            if in_log and (line.startswith('def ') or line.startswith('if __name__')):
                log_end = i
                break
        if log_end > 0:
            # Insert rotation functions before the next def
            rot_lines = LOG_ROTATION_FUNC.strip().split('\n')
            for j, rl in enumerate(rot_lines):
                stripped.insert(log_end + j, rl)
            patches.append('log_rotation_funcs')

    # --- 4. Slimmed load_wallets (SIM ONLY) ---
    if label == 'sim':
        has_slim = any('slim[addr]' in l for l in stripped)
        if not has_slim:
            # Find load_wallets function and replace it
            start = -1
            end = -1
            for i, line in enumerate(stripped):
                if line.startswith('def load_wallets('):
                    start = i
                    continue
                if start > 0 and (line.startswith('def ') or (line.startswith('if __name__') and i > start + 2)):
                    end = i
                    break
            if start > 0 and end > 0:
                new_lines = SLIMMED_LOAD_WALLETS.strip().split('\n')
                stripped[start:end] = new_lines
                patches.append('slimmed_load_wallets')

    if stripped == original:
        print(f'  [{label}] no changes')
        return False

    with open(filepath, 'w', encoding='utf-8-sig') as f:
        f.write('\n'.join(stripped) + '\n')

    print(f'  [{label}] patched: {", ".join(patches)}')
    return True


def main():
    print('=== Log Rotation + Wallet Slimming Patch ===\n')

    for fp, label in [(MON, 'monitor'), (SIM, 'sim')]:
        if os.path.exists(fp):
            patch_file(fp, label)
        else:
            print(f'  [{label}] NOT FOUND')

    print('\n=== Compile check ===')
    for fp, label in [(SIM, 'sim'), (MON, 'monitor')]:
        if os.path.exists(fp):
            try:
                py_compile.compile(fp, doraise=True)
                print(f'  [OK] {label}')
            except py_compile.PyCompileError as e:
                print(f'  [FAIL] {label}: {e}')


if __name__ == '__main__':
    main()
