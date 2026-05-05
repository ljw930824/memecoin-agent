import json, subprocess, re, sys
sys.stdout.reconfigure(encoding='utf-8')

# Check tracker PnL field format
r = subprocess.run(['onchainos', 'tracker', 'activities', '--tracker-type', 'smart_money', '--chain', 'solana', '--min-volume', '500'],
                  capture_output=True, text=True, timeout=20, encoding='utf-8')
m = re.search(r'\{.*\}', r.stdout, re.DOTALL)
d = json.loads(m.group(0))
trades = d.get('data', {}).get('trades', [])
sells = [t for t in trades if t.get('tradeType') == '2']

print(f'Total trades: {len(trades)}, Sells: {len(sells)}')
print()
print('=== SELL trades PnL analysis ===')
for t in sells[:15]:
    sym = t.get('tokenSymbol', '?')
    pnl_raw = t.get('pnl', 'MISSING')
    pnl_val = t.get('pnlAmount', 'MISSING')
    trade_type = t.get('tradeType')
    mcap = float(t.get('marketCap', 0))
    vol = float(t.get('volume', 0))
    print(f'  {sym:>12} | pnl={pnl_raw!r} | pnlAmount={pnl_val!r} | mcap=${mcap:>12,.0f} | vol=${vol:>8,.0f}')

# Check all keys in a sell trade
if sells:
    print()
    print('=== All keys in first sell trade ===')
    for k, v in sells[0].items():
        print(f'  {k}: {v!r}')
