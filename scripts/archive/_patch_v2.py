#!/usr/bin/env python3
"""
patch_archive_v2.py - Line-based patching for archive integration
More reliable than regex for these files.
"""
import os
import sys
import py_compile

SIM = os.path.expanduser("~/.qclaw/workspace/scripts/simulation/sm_monitor_sim.py")
MON = os.path.expanduser("~/.qclaw/workspace/scripts/active/realtime_sm_monitor.py")

IMPORT_LINES = [
    '# Auto-archive integration',
    'import sys as _sys_a',
    '_sys_a.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "archive"))',
    'try:',
    '    from data_archive_manager import auto_archive, on_sell_closed',
    '    _ARCHIVE_OK = True',
    'except ImportError:',
    '    _ARCHIVE_OK = False',
]

ONSELL_LINES = [
    '    # Archive closed position to daily file',
    '    if _ARCHIVE_OK:',
    "        try:",
    "            on_sell_closed({",
    "                'token_address': pos.get('token_address', pos.get('ca', '')),",
    "                'chain': pos.get('chain', 'unknown'),",
    "                'buy_time': pos.get('buy_time', ''),",
    "                'last_sell_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),",
    "                'pnl_pct': exit_pnl_pct,",
    "                'symbol': pos.get('symbol', '?'),",
    "                'reason': reason,",
    "                'exit_usd': exit_usd,",
    "                'hold_hours': hold_hours,",
    '            })',
    '        except Exception:',
    '            pass',
]

AUTOARCH_LINES = [
    '    # Auto-archive: decay backups, archive closed positions',
    '    if _ARCHIVE_OK:',
    '        try:',
    '            _ar = auto_archive(state_file=STATE_FILE)',
    "            if _ar:",
    "                log(f'[ARCHIVE] {_ar}')",
    '        except Exception:',
    '            pass',
    '',
]


def find_import_insert(lines):
    """Find line after 'from collections import defaultdict'"""
    for i, line in enumerate(lines):
        if line.strip() == 'from collections import defaultdict':
            return i + 1
    return -1


def find_tradelog_insert(lines):
    """Find the log() line at end of _save_trade_history, return line after it"""
    in_func = False
    for i, line in enumerate(lines):
        if line.startswith('def _save_trade_history('):
            in_func = True
            continue
        if in_func and line.strip().startswith("log(f'trade_history:"):
            # Return line after this (insert before the blank lines)
            return i + 1
    return -1


def find_return_positions_insert(lines):
    """Find the LAST 'return positions' in run_once function"""
    in_run_once = False
    last_return = -1
    for i, line in enumerate(lines):
        if line.startswith('def run_once('):
            in_run_once = True
            continue
        if in_run_once:
            if line.startswith('def ') or line.startswith('if __name__'):
                break
            if line.strip() == 'return positions':
                last_return = i
    return last_return


def patch(filepath, label):
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()

    # Strip trailing newlines for easier manipulation
    stripped = [l.rstrip('\n') for l in lines]
    original = list(stripped)
    inserts = []  # (line_index, [lines_to_insert])

    # Patch 1: Import
    has_import = any('_ARCHIVE_OK' in l for l in stripped)
    if not has_import:
        idx = find_import_insert(stripped)
        if idx > 0:
            inserts.append((idx, [''] + IMPORT_LINES))
            print(f'  [{label}] import at L{idx+1}')

    # Patch 2: on_sell_closed in _save_trade_history
    has_onsell = any('on_sell_closed' in l for l in stripped)
    if not has_onsell:
        idx = find_tradelog_insert(stripped)
        if idx > 0:
            inserts.append((idx, ONSELL_LINES))
            print(f'  [{label}] on_sell_closed at L{idx+1}')

    # Patch 3: auto_archive in run_once
    has_autoarch = any('auto_archive(state_file=' in l for l in stripped)
    if not has_autoarch:
        idx = find_return_positions_insert(stripped)
        if idx > 0:
            inserts.append((idx, AUTOARCH_LINES))
            print(f'  [{label}] auto_archive at L{idx+1}')

    if not inserts:
        print(f'  [{label}] no changes needed')
        return False

    # Apply inserts in reverse order so indices don't shift
    inserts.sort(key=lambda x: x[0], reverse=True)
    for line_idx, new_lines in inserts:
        for j, nl in enumerate(new_lines):
            stripped.insert(line_idx + j, nl)

    # Write back
    with open(filepath, 'w', encoding='utf-8-sig') as f:
        f.write('\n'.join(stripped) + '\n')

    return True


def main():
    print('=== Archive Integration Patch v2 ===\n')

    for fp, label in [(SIM, 'sim'), (MON, 'monitor')]:
        if os.path.exists(fp):
            patch(fp, label)
        else:
            print(f'  [{label}] NOT FOUND')

    print('\n=== Compile check ===')
    ok = True
    for fp, label in [(SIM, 'sim'), (MON, 'monitor')]:
        if os.path.exists(fp):
            try:
                py_compile.compile(fp, doraise=True)
                print(f'  [OK] {label}')
            except py_compile.PyCompileError as e:
                print(f'  [FAIL] {label}: {e}')
                ok = False

    print('\n=== Verify integration ===')
    for fp, label in [(SIM, 'sim'), (MON, 'monitor')]:
        if os.path.exists(fp):
            with open(fp, 'r', encoding='utf-8-sig') as f:
                c = f.read()
            n_onsell = c.count('on_sell_closed(')
            n_autoarch = c.count('auto_archive(state_file=')
            n_import = c.count('_ARCHIVE_OK')
            print(f'  [{label}] import: {n_import}, on_sell_closed: {n_onsell}, auto_archive: {n_autoarch}')

    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
