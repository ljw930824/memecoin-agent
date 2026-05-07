import subprocess, os, json, time, sys
sys.stdout.reconfigure(encoding='utf-8')

# Run sim with timeout - just do 1 cycle
sim_script = os.path.expanduser('~/.qclaw/workspace/scripts/simulation/sm_monitor_sim.py')
env = dict(os.environ)
env['PYTHONIOENCODING'] = 'utf-8'

print('Running 1 sim cycle...')
t0 = time.time()
r = subprocess.run(
    ['C:\\Users\\dell\\AppData\\Local\\Programs\\Python\\Python310\\python.exe', sim_script],
    capture_output=True, text=True, timeout=120, encoding='utf-8', errors='replace',
    env=env
)
elapsed = time.time() - t0
print(f'Time: {elapsed:.1f}s, RC: {r.returncode}')
print()
print('=== STDOUT (last 60 lines) ===')
lines = (r.stdout or '').strip().split('\n')
for line in lines[-60:]:
    print(line)
if r.stderr:
    print()
    print('=== STDERR (last 20 lines) ===')
    for line in (r.stderr or '').strip().split('\n')[-20:]:
        print(line)
