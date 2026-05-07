import sys
sys.stdout.reconfigure(encoding="utf-8")

def fix_file(filepath, label):
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    
    changes = 0
    
    # Fix 1: check_positions signature: add state param
    for i, line in enumerate(lines):
        if "def check_positions(positions):" in line:
            lines[i] = line.replace("def check_positions(positions):", "def check_positions(positions, state=None):")
            print("%s L%d: Added state=None param" % (label, i+1))
            changes += 1
            break
    
    # Fix 2: _save_trade_history calls — add state fallback
    for i, line in enumerate(lines):
        if "_save_trade_history(state, " in line:
            old = "_save_trade_history(state, "
            new = "_save_trade_history(state or {}, "
            lines[i] = line.replace(old, new)
            print("%s L%d: state fallback in _save_trade_history" % (label, i+1))
            changes += 1
    
    # Fix 3: call site in run_once — pass state
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("positions = check_positions(positions)"):
            lines[i] = line.replace("check_positions(positions)", "check_positions(positions, state)")
            print("%s L%d: Pass state to check_positions" % (label, i+1))
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
