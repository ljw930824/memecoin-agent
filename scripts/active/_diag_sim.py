import time, os, json, sys
sys.stdout.reconfigure(encoding='utf-8')

t0 = time.time()
DATA_DIR = os.path.expanduser('~/.qclaw/workspace/data')

# Step 1: Load state
print('[1] Loading state...')
t = time.time()
state_file = os.path.join(DATA_DIR, 'sm_monitor_state_dryrun.json')
if os.path.exists(state_file):
    with open(state_file, 'r', encoding='utf-8') as f:
        state = json.load(f)
    print(f'    {time.time()-t:.1f}s, {len(state.get("positions",{}))} positions')
else:
    print(f'    {time.time()-t:.1f}s, file not found')

# Step 2: Load wallets (10MB file!)
print('[2] Loading wallets...')
t = time.time()
wf = os.path.join(DATA_DIR, 'sm_wallets_dryrun.json')
if os.path.exists(wf):
    sz = os.path.getsize(wf) / 1024 / 1024
    with open(wf, 'r', encoding='utf-8') as f:
        wallets = json.load(f)
    print(f'    {time.time()-t:.1f}s, {sz:.1f}MB, {len(wallets)} wallets')
else:
    print(f'    {time.time()-t:.1f}s, file not found')

# Step 3: Load trade log
print('[3] Loading trade log...')
t = time.time()
tl = os.path.join(DATA_DIR, 'sm_trade-log_dryrun.txt')
if os.path.exists(tl):
    sz = os.path.getsize(tl) / 1024 / 1024
    with open(tl, 'r', encoding='utf-8') as f:
        trades = json.load(f)
    print(f'    {time.time()-t:.1f}s, {sz:.1f}MB, {len(trades)} trades')
else:
    print(f'    {time.time()-t:.1f}s, file not found')

# Step 4: OnChainOS wallet balance
print('[4] OnChainOS wallet balance (solana)...')
t = time.time()
import subprocess
env = dict(os.environ)
env['PYTHONIOENCODING'] = 'utf-8'
r = subprocess.run(['onchainos', 'wallet', 'balance', '--chain', 'solana'],
                    capture_output=True, text=True, timeout=25, encoding='utf-8', errors='replace', env=env)
print(f'    {time.time()-t:.1f}s, RC={r.returncode}')

# Step 5: BAW wallet balance
print('[5] BAW wallet balance (BSC)...')
t = time.time()
baw_cmd = os.path.expanduser(r'~\AppData\Roaming\QClaw\npm-global\baw.cmd')
r = subprocess.run([baw_cmd, 'wallet', 'balance', '--json'],
                    capture_output=True, text=True, timeout=15, encoding='utf-8', errors='replace')
print(f'    {time.time()-t:.1f}s, RC={r.returncode}')

# Step 6: Tracker fetch (solana)
print('[6] Tracker fetch (solana)...')
t = time.time()
r = subprocess.run(
    ['onchainos', 'tracker', 'activities', '--tracker-type', 'smart_money', '--chain', 'solana', '--min-volume', '400'],
    capture_output=True, text=True, timeout=25, encoding='utf-8', errors='replace', env=env
)
print(f'    {time.time()-t:.1f}s, RC={r.returncode}')

# Step 7: Tracker fetch (BSC)
print('[7] Tracker fetch (BSC)...')
t = time.time()
r = subprocess.run(
    ['onchainos', 'tracker', 'activities', '--tracker-type', 'smart_money', '--chain', 'bsc', '--min-volume', '400'],
    capture_output=True, text=True, timeout=25, encoding='utf-8', errors='replace', env=env
)
print(f'    {time.time()-t:.1f}s, RC={r.returncode}')

# Step 8: Signal fetch
print('[8] Signal fetch (solana)...')
t = time.time()
r = subprocess.run(
    ['onchainos', 'signal', 'list', '--chain', 'solana', '--limit', '50', '--wallet-type', '1'],
    capture_output=True, text=True, timeout=20, encoding='utf-8', errors='replace', env=env
)
print(f'    {time.time()-t:.1f}s, RC={r.returncode}')

print()
print(f'Total: {time.time()-t0:.1f}s')
print('=== All steps completed ===')
