import subprocess, os, json, time, sys
sys.stdout.reconfigure(encoding='utf-8')
env = dict(os.environ)

# Test 1: OnChainOS wallet balance (Solana)
print('=== Test 1: Wallet balance (solana) ===')
t0 = time.time()
r = subprocess.run(['onchainos', 'wallet', 'balance', '--chain', 'solana'],
                    capture_output=True, text=True, timeout=25, encoding='utf-8', env=env)
elapsed = time.time() - t0
print(f'  Time: {elapsed:.1f}s, RC: {r.returncode}')
if r.stdout:
    import re
    m = re.search(r'\{.*\}', r.stdout, re.DOTALL)
    if m:
        d = json.loads(m.group(0))
        details = d.get('data', {}).get('details', [])
        for det in details:
            for ta in det.get('tokenAssets', []):
                if str(ta.get('chainIndex', '')) == '501':
                    sym = ta.get('tokenSymbol', '?')
                    bal = ta.get('balance', 0)
                    print(f'  Solana: {sym} = {bal}')

# Test 2: Tracker activities (Solana)
print()
print('=== Test 2: Tracker activities (solana) ===')
t0 = time.time()
r = subprocess.run(
    ['onchainos', 'tracker', 'activities', '--tracker-type', 'smart_money', '--chain', 'solana', '--min-volume', '400'],
    capture_output=True, text=True, timeout=25, encoding='utf-8', env=env
)
elapsed = time.time() - t0
print(f'  Time: {elapsed:.1f}s, RC: {r.returncode}')
if r.stdout:
    m = re.search(r'\{.*\}', r.stdout, re.DOTALL)
    if m:
        d = json.loads(m.group(0))
        trades = d.get('data', {}).get('trades', [])
        print(f'  Signals: {len(trades)} trades')
        for t in trades[:3]:
            sym = t.get('tokenSymbol', '?')
            amt = t.get('amountUsd', 0)
            print(f'    {sym}: ${amt}')

# Test 3: Signal list (Solana)
print()
print('=== Test 3: Signal list (solana) ===')
t0 = time.time()
r = subprocess.run(
    ['onchainos', 'signal', 'list', '--chain', 'solana', '--limit', '5', '--wallet-type', '1'],
    capture_output=True, text=True, timeout=20, encoding='utf-8', env=env
)
elapsed = time.time() - t0
print(f'  Time: {elapsed:.1f}s, RC: {r.returncode}')
if r.stdout:
    m = re.search(r'\{.*\}', r.stdout, re.DOTALL)
    if m:
        d = json.loads(m.group(0))
        items = d.get('data', [])
        print(f'  Signals: {len(items)} items')
        for s in items[:3]:
            if isinstance(s, dict):
                tok = s.get('token', {})
                print(f'    {tok.get("symbol","?")}: score={s.get("triggerWalletCount",0)} wallets, mcap=${tok.get("marketCapUsd",0)}')

# Test 4: BAW wallet balance (BSC)
print()
print('=== Test 4: BAW balance (BSC) ===')
baw_cmd = os.path.expanduser(r'~\AppData\Roaming\QClaw\npm-global\baw.cmd')
t0 = time.time()
r = subprocess.run([baw_cmd, 'wallet', 'balance', '--json'],
                    capture_output=True, text=True, timeout=15, encoding='utf-8')
elapsed = time.time() - t0
print(f'  Time: {elapsed:.1f}s, RC: {r.returncode}')
if r.stdout:
    m = re.search(r'\{.*\}', r.stdout, re.DOTALL)
    if m:
        d = json.loads(m.group(0))
        items = d if isinstance(d, list) else d.get('data', d.get('tokens', []))
        if isinstance(items, dict):
            items = items.get('data', items.get('tokens', []))
        print(f'  Tokens: {len(items)}')
        for item in items[:5]:
            if isinstance(item, dict):
                sym = item.get('symbol', '?')
                bal = item.get('balance', 0)
                addr = item.get('address', item.get('contractAddress', ''))
                print(f'    {sym}: {bal} ({addr[:16]}...)')

print()
print('=== All tests complete ===')
