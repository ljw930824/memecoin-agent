import sys
sys.stdout.reconfigure(encoding="utf-8")

def fix_file(filepath, label):
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    
    changes = 0
    
    # Fix 1: _save_trade_history DEFINITION — revert "state or {}" back to "state"
    for i, line in enumerate(lines):
        if "def _save_trade_history(state or {}" in line:
            lines[i] = line.replace("def _save_trade_history(state or {},", "def _save_trade_history(state,")
            print("%s L%d: Reverted definition" % (label, i+1))
            changes += 1
    
    # Fix 2: _save_trade_history CALLS — keep "state or {}" (already done)
    # But also need to check — the calls should use state or {}
    # Actually, since we pass state from run_once which has it, the calls inside
    # check_positions should just use "state" directly (it's passed as param now)
    # Revert the "state or {}" in calls too since state is now a param
    for i, line in enumerate(lines):
        if "_save_trade_history(state or {}, " in line and "def " not in line:
            lines[i] = line.replace("_save_trade_history(state or {}, ", "_save_trade_history(state, ")
            print("%s L%d: Reverted call (state is now param)" % (label, i+1))
            changes += 1
    
    print("%s total changes: %d" % (label, changes))
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(lines)
    
    import py_compile
    try:
        py_compile.compile(filepath, doraise=True)
        print("%s COMPILE: OK" % label)
    except py_compile.PyCompileError as e:
        print("%s COMPILE ERROR: %s" % (label, str(e)[:200]))
    
    return changes

c1 = fix_file("scripts/simulation/sm_monitor_sim.py", "SIM")
c2 = fix_file("scripts/active/realtime_sm_monitor.py", "ACTIVE")
print("\nTotal: SIM=%d, ACTIVE=%d" % (c1, c2))
