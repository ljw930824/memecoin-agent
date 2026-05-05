# -*- coding: utf-8 -*-
"""
paper_trading.py - Paper trading simulator for backtesting
Records signals and simulates trades without real execution
"""
import json
import os
from datetime import datetime, timezone, timedelta

DATA_DIR = os.path.expanduser('~/.qclaw/workspace/data')
PAPER_LOG = os.path.join(DATA_DIR, 'paper-trading-log.json')
SIGNAL_HISTORY = os.path.join(DATA_DIR, 'signal-history.json')
os.makedirs(DATA_DIR, exist_ok=True)

def log_signal(sig, action='OBSERVE'):
    """Log signal for backtesting analysis."""
    entry = {
        'timestamp': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'signalId': sig.get('signalId'),
        'ticker': sig.get('ticker'),
        'chain': sig.get('chain'),
        'contractAddress': sig.get('contractAddress'),
        'score': sig.get('score'),
        'smartMoneyCount': sig.get('smartMoneyCount'),
        'alertPrice': sig.get('alertPrice'),
        'currentPrice': sig.get('currentPrice'),
        'alertMarketCap': sig.get('alertMarketCap'),
        'status': sig.get('status'),
        'action': action,  # OBSERVE, SIMULATE_BUY, WOULD_BUY, SKIPPED
        'reason': ''
    }
    
    history = []
    if os.path.exists(SIGNAL_HISTORY):
        with open(SIGNAL_HISTORY, 'r', encoding='utf-8') as f:
            history = json.load(f)
    
    # Check if already logged
    existing = [h for h in history if h.get('signalId') == entry['signalId'] and 
                h.get('timestamp', '').split('T')[0] == entry['timestamp'].split('T')[0]]
    if not existing:
        history.append(entry)
        if len(history) > 10000:
            history = history[-10000:]
        with open(SIGNAL_HISTORY, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    
    return entry

def simulate_buy(sig, invest_usd):
    """Simulate a buy without real execution."""
    entry = {
        'timestamp': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'type': 'SIMULATED_BUY',
        'signalId': sig.get('signalId'),
        'ticker': sig.get('ticker'),
        'chain': sig.get('chain'),
        'contractAddress': sig.get('contractAddress'),
        'entry_price': sig.get('currentPrice'),
        'invest_amount': invest_usd,
        'score': sig.get('score'),
        'sl_price': round(float(sig.get('currentPrice', 0)) * 0.92, 12),
        'tp_price': round(float(sig.get('currentPrice', 0)) * 1.12, 12),
    }
    
    log = []
    if os.path.exists(PAPER_LOG):
        with open(PAPER_LOG, 'r', encoding='utf-8') as f:
            log = json.load(f)
    
    log.append(entry)
    with open(PAPER_LOG, 'w', encoding='utf-8') as f:
        json.dump(log, f, indent=2, ensure_ascii=False)
    
    return entry

def get_backtest_report(days=7):
    """Generate backtest report from paper trading log."""
    if not os.path.exists(SIGNAL_HISTORY):
        return "No signal history yet."
    
    with open(SIGNAL_HISTORY, 'r', encoding='utf-8') as f:
        history = json.load(f)
    
    # Filter recent signals
    cutoff = datetime.now(timezone(timedelta(hours=8))) - timedelta(days=days)
    recent = [h for h in history if datetime.fromisoformat(h['timestamp']) > cutoff]
    
    # Statistics
    total = len(recent)
    by_chain = {}
    by_action = {}
    score_dist = {'0-20': 0, '21-40': 0, '41-60': 0, '61-80': 0, '81-100': 0}
    
    for h in recent:
        chain = h.get('chain', 'unknown')
        by_chain[chain] = by_chain.get(chain, 0) + 1
        
        action = h.get('action', 'OBSERVE')
        by_action[action] = by_action.get(action, 0) + 1
        
        score = h.get('score', 0)
        if score <= 20:
            score_dist['0-20'] += 1
        elif score <= 40:
            score_dist['21-40'] += 1
        elif score <= 60:
            score_dist['41-60'] += 1
        elif score <= 80:
            score_dist['61-80'] += 1
        else:
            score_dist['81-100'] += 1
    
    report = f"""
=== Paper Trading Backtest Report (Last {days} days) ===
Total Signals: {total}

By Chain:
"""
    for chain, count in by_chain.items():
        report += f"  {chain}: {count}\n"
    
    report += "\nBy Action:\n"
    for action, count in by_action.items():
        report += f"  {action}: {count}\n"
    
    report += "\nScore Distribution:\n"
    for range_name, count in score_dist.items():
        pct = (count / total * 100) if total > 0 else 0
        report += f"  {range_name}: {count} ({pct:.1f}%)\n"
    
    return report

def would_buy_signal(sig, min_score=50):
    """Check if signal would trigger a buy (for simulation)."""
    score = sig.get('score', 0)
    
    if score < min_score:
        return False, f"Score {score} < {min_score}"
    
    # Add other criteria checks here
    chain = sig.get('chain', '')
    if chain == 'CT_501':  # Solana
        # Additional Solana-specific checks
        pass
    
    return True, f"Score {score} >= {min_score}"

if __name__ == '__main__':
    print(get_backtest_report())
