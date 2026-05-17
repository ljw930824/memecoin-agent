import json
from datetime import datetime, timezone, timedelta

path = r'C:\Users\dell\.qclaw\workspace\data\smart-money-state.json'
with open(path, 'r', encoding='utf-8') as f:
    state = json.load(f)

positions = state.get('positions', {})
closed_trades = state.get('closed_trades', [])

# Find and close BABYASTEROID
for ca, pos in list(positions.items()):
    if pos.get('ticker') == 'BABYASTEROID':
        invest = pos.get('invest_amount', 6.61)
        # TP was +12%, received 7.47 USDT
        pnl_pct = 0.12
        pnl_value = 7.47 - invest  # actual received minus invested
        closed = {
            'ticker': 'BABYASTEROID',
            'invest': invest,
            'pnl_value': round(pnl_value, 2),
            'pnl_pct': round(pnl_pct, 4),
            'exit_reason': 'TP_HIT',
            'close_time': datetime.now(timezone(timedelta(hours=8))).isoformat()
        }
        closed_trades.append(closed)
        del positions[ca]
        print(f"Closed BABYASTEROID: invested ${invest}, received $7.47, profit ${pnl_value:+.2f} ({pnl_pct*100:+.0f}%)")

# Update totals
total_pnl = sum(t.get('pnl_value', 0) for t in closed_trades)
profit_pool = sum(t.get('pnl_value', 0) for t in closed_trades if t.get('pnl_value', 0) > 0)
state['total_pnl'] = round(total_pnl, 2)
state['profit_pool'] = round(profit_pool, 2)
state['closed_trades'] = closed_trades

with open(path, 'w', encoding='utf-8') as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print(f"\nTotal P&L: ${total_pnl:.2f}")
print(f"Profit pool: ${profit_pool:.2f}")
print(f"Open positions: {len(positions)}")
for ca, pos in positions.items():
    print(f"  - {pos['ticker']}")
