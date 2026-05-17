#!/usr/bin/env python3
"""
Patch main loop error handling in sim and monitor.
Critical fix: wrap run_once() in try/except so API errors don't kill the process.
"""
import os, py_compile

SIM = os.path.expanduser("~/.qclaw/workspace/scripts/simulation/sm_monitor_sim.py")
MON = os.path.expanduser("~/.qclaw/workspace/scripts/active/realtime_sm_monitor.py")

OLD_LOOP = """        while True:


            run_once(state, wallets)


            log(f'--- sleep {TRACKER_POLL_SEC}s ---')


            time.sleep(TRACKER_SEC)"""

NEW_LOOP = """        while True:

            try:
                run_once(state, wallets)
            except Exception as e:
                import traceback
                log(f'ERROR in run_once: {e}')
                traceback.print_exc()
                # Save state on error to prevent data loss
                try:
                    save_state(state)
                    save_wallets(wallets)
                except:
                    pass
                # Reload wallets on error (might be corrupted)
                try:
                    wallets = load_wallets()
                except:
                    pass
                # Wait longer on error to avoid tight loops
                log(f'Retrying in {TRACKER_POLL_SEC * 3}s...')
                time.sleep(TRACKER_POLL_SEC * 3)
                continue

            log(f'--- sleep {TRACKER_POLL_SEC}s ---')


            time.sleep(TRACKER_POLL_SEC)"""


def patch_file(filepath, label):
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        content = f.read()

    if 'try:\n                run_once(state, wallets)' in content:
        print(f'  [{label}] already patched, skip')
        return False

    # The monitor uses TRACKER_POLL_SEC, sim might use different
    # Let's find the exact pattern
    lines = content.split('\n')
    found = False
    for i, line in enumerate(lines):
        if 'run_once(state, wallets)' in line and i > 2000:  # in main()
            # Check if already wrapped in try
            if i > 0 and 'try:' in lines[i-1]:
                print(f'  [{label}] already has try block, skip')
                return False
            found = True
            break

    if not found:
        print(f'  [{label}] run_once not found in main loop')
        return False

    # Build the patched version by replacing the loop body
    new_content = content.replace(
        "        while True:\n\n\n            run_once(state, wallets)\n\n\n            log(f'--- sleep {TRACKER_POLL_SEC}s ---')\n\n\n            time.sleep(TRACKER_POLL_SEC)",
        """        while True:

            try:
                run_once(state, wallets)
            except Exception as e:
                import traceback
                log(f'ERROR in run_once: {e}')
                traceback.print_exc()
                try:
                    save_state(state)
                    save_wallets(wallets)
                except:
                    pass
                try:
                    wallets = load_wallets()
                except:
                    pass
                log(f'Retrying in {TRACKER_POLL_SEC * 3}s...')
                time.sleep(TRACKER_POLL_SEC * 3)
                continue

            log(f'--- sleep {TRACKER_POLL_SEC}s ---')


            time.sleep(TRACKER_POLL_SEC)"""
    )

    if new_content == content:
        # Try alternative pattern (single newline)
        new_content = content.replace(
            "        while True:\n\n            run_once(state, wallets)\n\n            log(f'--- sleep {TRACKER_POLL_SEC}s ---')\n\n            time.sleep(TRACKER_POLL_SEC)",
            """        while True:

            try:
                run_once(state, wallets)
            except Exception as e:
                import traceback
                log(f'ERROR in run_once: {e}')
                traceback.print_exc()
                try:
                    save_state(state)
                    save_wallets(wallets)
                except:
                    pass
                try:
                    wallets = load_wallets()
                except:
                    pass
                log(f'Retrying in {TRACKER_POLL_SEC * 3}s...')
                time.sleep(TRACKER_POLL_SEC * 3)
                continue

            log(f'--- sleep {TRACKER_POLL_SEC}s ---')


            time.sleep(TRACKER_POLL_SEC)"""
        )

    if new_content == content:
        print(f'  [{label}] no match found, skip')
        return False

    with open(filepath, 'w', encoding='utf-8-sig') as f:
        f.write(new_content)

    print(f'  [{label}] patched: run_once wrapped in try/except')
    return True


def main():
    print('=== Main Loop Error Handling Patch ===\n')

    for fp, label in [(SIM, 'sim'), (MON, 'monitor')]:
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
