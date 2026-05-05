import json, os, subprocess
BAW_CMD = os.path.expanduser('~\\AppData\\Roaming\\QClaw\\npm-global\\baw.cmd')
result = subprocess.run([BAW_CMD, 'wallet', 'balance', '--json'], capture_output=True, text=True, timeout=15)
data = json.loads(result.stdout)
by_ca = {}
for t in data.get('data', []):
    ca = t.get('contractAddress', '').lower()
    by_ca[ca] = {'balance': float(t.get('balance',0)), 'value': float(t.get('value',0)), 'symbol': t.get('symbol')}
print('=== by_ca keys ===')
for k,v in by_ca.items():
    print('  ' + k + ': ' + str(v))
print()
state_file = os.path.expanduser('~/.qclaw/workspace/data/smart-money-state.json')
with open(state_file) as f:
    state = json.load(f)
print('=== State positions ===')
for ca, pos in state.get('positions', {}).items():
    ca_lower = ca.lower()
    match = by_ca.get(ca_lower)
    print('  state: ' + ca_lower + ' -> ' + str(pos.get('ticker')))
    print('  match: ' + str(match))
