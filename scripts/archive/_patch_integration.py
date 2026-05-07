#!/usr/bin/env python3
"""
patch_archive_integration.py
Integrates data_archive_manager into sim and monitor scripts.
Three changes per file:
  1. Import at top
  2. on_sell_closed() in _save_trade_history()
  3. auto_archive() in run_once()
"""
import re
import sys
import os
import py_compile

SIM_FILE = os.path.expanduser("~/.qclaw/workspace/scripts/simulation/sm_monitor_sim.py")
MON_FILE = os.path.expanduser("~/.qclaw/workspace/scripts/active/realtime_sm_monitor.py")

# Import block to add after "from collections import defaultdict"
ARCHIVE_IMPORT_BLOCK = '''
# Auto-archive integration
import sys as _sys_a
_sys_a.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'archive'))
try:
    from data_archive_manager import auto_archive, on_sell_closed
    _ARCHIVE_OK = True
except ImportError:
    _ARCHIVE_OK = False
'''

# on_sell_closed call to add at end of _save_trade_history
ONSELL_BLOCK = '''
    # Archive closed position
    if _ARCHIVE_OK:
        try:
            on_sell_closed({
                'token_address': pos.get('token_address', pos.get('ca', '')),
                'chain': pos.get('chain', 'unknown'),
                'buy_time': pos.get('buy_time', ''),
                'last_sell_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'pnl_pct': exit_pnl_pct,
                'symbol': pos.get('symbol', '?'),
                'reason': reason,
                'exit_usd': exit_usd,
                'hold_hours': hold_hours,
            })
        except Exception:
            pass
'''

# auto_archive call to add before "return positions" in run_once
AUTOARCH_BLOCK = '''    # Auto-archive: decay backups, archive closed positions
    if _ARCHIVE_OK:
        try:
            _ar = auto_archive(state_file=STATE_FILE)
            if _ar:
                log(f'[ARCHIVE] {_ar}')
        except Exception:
            pass
'''


def patch_file(filepath, label):
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        content = f.read()

    original = content
    patches = []

    # --- Patch 1: Import ---
    if '_ARCHIVE_OK' not in content:
        anchor = 'from collections import defaultdict'
        idx = content.find(anchor)
        if idx >= 0:
            end = content.find('\n', idx)
            if end < 0:
                end = idx + len(anchor)
            content = content[:end+1] + ARCHIVE_IMPORT_BLOCK + content[end+1:]
            patches.append('import')

    # --- Patch 2: on_sell_closed in _save_trade_history ---
    if 'on_sell_closed' not in content:
        # Find the log() line at end of _save_trade_history
        # Pattern: log(f'trade_history: ...') followed by blank lines then def save_state
        pat = re.compile(
            r"(    log\(f'trade_history:.*?\))\n"
            r"(\s*\n)"
            r"(def save_state)",
            re.DOTALL
        )
        m = pat.search(content)
        if m:
            content = content[:m.start(2)] + ONSELL_BLOCK + '\n' + content[m.start(2):]
            patches.append('on_sell_closed')
        else:
            # Fallback: find the log line and add after it
            log_pat = re.compile(r"    log\(f'trade_history:.*?\)\n")
            matches = list(log_pat.finditer(content))
            if len(matches) >= 2:  # first is _save_trade_history, others might be elsewhere
                # Use the first occurrence (inside _save_trade_history)
                m = matches[0]
                # Verify it's in _save_trade_history
                func_start = content.rfind('\ndef ', 0, m.start())
                if func_start > 0 and '_save_trade_history' in content[func_start:m.start()]:
                    content = content[:m.end()] + ONSELL_BLOCK + content[m.end():]
                    patches.append('on_sell_closed (fallback)')

    # --- Patch 3: auto_archive in run_once ---
    if 'auto_archive(state_file=' not in content:
        # Find run_once function, then find "return positions" inside it
        run_once_match = re.search(r'def run_once\(state, wallets\):', content)
        if run_once_match:
            # Find next top-level def
            after = run_once_match.end()
            next_def = re.search(r'\ndef [a-z]', content[after+5:])
            if next_def:
                region_end = after + 5 + next_def.start()
            else:
                # Find if __name__
                name_match = re.search(r'\nif __name__', content[after:])
                if name_match:
                    region_end = after + name_match.start()
                else:
                    region_end = len(content)
            
            region = content[after:region_end]
            # Find last "return positions" in this region
            ret_idx = region.rfind('return positions')
            if ret_idx >= 0:
                abs_idx = after + ret_idx
                # Insert before the return
                indent_match = re.match(r'(\s+)', content[abs_idx:abs_idx+20])
                content = content[:abs_idx] + AUTOARCH_BLOCK + '\n' + content[abs_idx:]
                patches.append('auto_archive')

    if content != original:
        with open(filepath, 'w', encoding='utf-8-sig') as f:
            f.write(content)
        print(f'  [OK] {label}: {", ".join(patches)}')
        return True
    else:
        print(f'  [SKIP] {label}: no changes')
        return False


def main():
    print('=== Patching archive integration ===')
    for f, label in [(SIM_FILE, 'sim'), (MON_FILE, 'monitor')]:
        if os.path.exists(f):
            patch_file(f, label)
        else:
            print(f'  [SKIP] not found: {f}')

    print('\n=== Compile check ===')
    for f, label in [(SIM_FILE, 'sim'), (MON_FILE, 'monitor')]:
        if os.path.exists(f):
            try:
                py_compile.compile(f, doraise=True)
                print(f'  [OK] {label} compiles')
            except py_compile.PyCompileError as e:
                print(f'  [FAIL] {label}: {e}')

    # Count on_sell_closed occurrences
    for f, label in [(SIM_FILE, 'sim'), (MON_FILE, 'monitor')]:
        if os.path.exists(f):
            with open(f, 'r', encoding='utf-8-sig') as fh:
                c = fh.read()
            n = c.count('on_sell_closed(')
            a = c.count('auto_archive(')
            print(f'  [{label}] on_sell_closed: {n}, auto_archive: {a}')


if __name__ == '__main__':
    main()
