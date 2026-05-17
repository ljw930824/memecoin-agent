import json
from datetime import datetime

# Load data
with open('C:/Users/dell/.qclaw/workspace/data/signal-history.json', 'r') as f:
    signals = json.load(f)

with open('C:/Users/dell/.qclaw/workspace/data/paper-trading-log.json', 'r') as f:
    trades = json.load(f)

print('=' * 60)
print('  SOLANA SIGNAL BACKTEST REPORT')
print('  Period: 2026-05-01 01:34 - 04:28 (3 hours)')
print('=' * 60)

# Signal statistics
print('\n[ SIGNAL STATISTICS ]')
print(f'  Total signals received: {len(signals)}')

by_chain = {}
for s in signals:
    c = s['chain']
    by_chain[c] = by_chain.get(c, 0) + 1
print(f'  By chain: {by_chain}')

by_score = {'<40': 0, '40-49': 0, '50-59': 0, '60+': 0}
for s in signals:
    sc = s['score']
    if sc < 40: by_score['<40'] += 1
    elif sc < 50: by_score['40-49'] += 1
    elif sc < 60: by_score['50-59'] += 1
    else: by_score['60+'] += 1
print(f'  By score tier: {by_score}')

# Unique tokens
unique_tokens = set(s['ticker'] for s in signals)
print(f'  Unique tokens: {len(unique_tokens)} - {sorted(unique_tokens)}')

# Trade statistics  
print('\n[ SIMULATED TRADES ]')
buys = [t for t in trades if t['type'] == 'SIMULATED_BUY']
print(f'  Total buys: {len(buys)}')

# Group by token
by_token = {}
for b in buys:
    t = b['ticker']
    if t not in by_token:
        by_token[t] = {'count': 0, 'invested': 0, 'entries': []}
    by_token[t]['count'] += 1
    by_token[t]['invested'] += b['invest_amount']
    by_token[t]['entries'].append(float(b['entry_price']))

print('\n  By token:')
for t, d in sorted(by_token.items()):
    avg = sum(d['entries']) / len(d['entries'])
    print(f'    {t}: {d["count"]} buys, ${d["invested"]:.2f} invested, avg entry ${avg:.6f}')

# Calculate P&L for positions
print('\n[ OPEN POSITIONS (Paper Trading) ]')
latest_prices = {}
for s in signals:
    t = s['ticker']
    if t not in latest_prices or s['timestamp'] > latest_prices[t]['ts']:
        latest_prices[t] = {'price': float(s['currentPrice']), 'ts': s['timestamp']}

for t, d in by_token.items():
    avg_entry = sum(d['entries']) / len(d['entries'])
    if t in latest_prices:
        current = latest_prices[t]['price']
        pnl_pct = (current - avg_entry) / avg_entry * 100
        invested = d['invested']
        pnl_val = invested * pnl_pct / 100
        status = f'{pnl_pct:+.1f}%' if abs(pnl_pct) < 8 else ('TP HIT' if pnl_pct >= 12 else 'SL HIT' if pnl_pct <= -8 else f'{pnl_pct:+.1f}%')
        print(f'  {t}: ${invested:.2f} @ ${avg_entry:.6f} | ${current:.6f} | {status} (${pnl_val:+.2f})')

# Issues
print('\n[ ISSUES IDENTIFIED ]')
wish_count = by_token.get('Wish', {}).get('count', 0)
if wish_count > 1:
    print(f'  ! Duplicate buys: Wish bought {wish_count} times (same token, different signals)')
    print('    Fix: Add cooldown or check existing positions before buying')
print('  ! No sell triggers yet (need longer observation period for SL/TP)')

# Score validation
print('\n[ SCORE VALIDATION ]')
high_score = [s for s in signals if s['score'] >= 50]
print(f'  High-quality signals (>=50): {len(high_score)}/{len(signals)} ({100*len(high_score)//len(signals)}%)')
for s in high_score:
    print(f'    {s["ticker"]}: score={s["score"]}, SM={s["smartMoneyCount"]}, MC=${float(s["alertMarketCap"])/1e6:.1f}M')

# Recommendation
print('\n[ RECOMMENDATION ]')
if wish_count > 3:
    print('  1. CRITICAL: Fix duplicate buy logic - same token being bought repeatedly')
if len(buys) > 0:
    print(f'  2. Run for 24+ hours to see SL/TP hit rates')
    print(f'  3. Currently {len(buys)} paper positions open, ${sum(b["invest_amount"] for b in buys):.2f} at risk')

print('\n' + '=' * 60)
