# -*- coding: utf-8 -*-
"""
scan_signals_minute.py - 每分钟扫描 Smart Money 信号
高频轮询版本 - 1分钟间隔
"""
import sys
import os
sys.stdout.reconfigure(encoding='utf-8')

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import time
from datetime import datetime, timezone, timedelta
import requests

# Import paper trading v2
from paper_trading_v2 import load_paper_positions, get_position_key, check_signal_trend, simulate_trade_v2

DATA_DIR = os.path.expanduser('~/.qclaw/workspace/data')
SIGNAL_LOG = os.path.join(DATA_DIR, 'signal-history.json')
os.makedirs(DATA_DIR, exist_ok=True)

API_URL = "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai"
MIN_SCORE = 40  # 最低信号分
INVEST_USD = 5.0  # 每次投入金额

def fetch_signals():
    """Fetch Smart Money signals from Binance API."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0',
            'Accept': 'application/json',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        response = requests.get(API_URL, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if data.get('success') and 'data' in data:
            signals = data['data'].get('signals', [])
            return signals
        return []
    except Exception as e:
        print(f"[{now_str()}] API Error: {e}")
        return []

def now_str():
    return datetime.now(timezone(timedelta(hours=8))).strftime('%H:%M:%S')

def process_signals(signals):
    """Process signals and execute paper trades."""
    if not signals:
        return
    
    # Sort by score desc
    signals = sorted(signals, key=lambda x: x.get('score', 0), reverse=True)
    
    actions_taken = []
    
    for sig in signals:
        score = sig.get('score', 0)
        ticker = sig.get('ticker', sig.get('tokenInfo', {}).get('ticker', 'UNKNOWN'))
        
        # Skip low score
        if score < MIN_SCORE:
            continue
            
        # Check position state
        state = load_paper_positions()
        pos_key = get_position_key(sig)
        pos = state['positions'].get(pos_key)
        
        # Determine trend
        trend = check_signal_trend(pos, sig)
        
        if trend == 'STABLE':
            continue
            
        # Execute trade
        result = simulate_trade_v2(sig, trend, INVEST_USD)
        
        if result:
            actions_taken.append({
                'time': now_str(),
                'ticker': ticker,
                'action': result['type'],
                'score': score,
                'trend': trend
            })
            print(f"[{now_str()}] {result['type']} | {ticker} | Score:{score} | Trend:{trend}")
    
    return actions_taken

def save_signals(signals):
    """Append signals to history log."""
    history = []
    if os.path.exists(SIGNAL_LOG):
        try:
            with open(SIGNAL_LOG, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except:
            history = []
    
    # Add timestamp to each signal
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    for sig in signals:
        sig['_recorded_at'] = now
    
    history.extend(signals)
    
    # Keep last 10000 records
    if len(history) > 10000:
        history = history[-10000:]
    
    with open(SIGNAL_LOG, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

def main():
    print(f"[{now_str()}] === Smart Money Scanner (1-min interval) ===")
    
    signals = fetch_signals()
    
    if not signals:
        print(f"[{now_str()}] No signals fetched")
        return
    
    print(f"[{now_str()}] Fetched {len(signals)} signals")
    
    # Save raw signals
    save_signals(signals)
    
    # Process and trade
    actions = process_signals(signals)
    
    if actions:
        print(f"[{now_str()}] Actions taken: {len(actions)}")
        for a in actions:
            print(f"  - {a['action']} {a['ticker']} (score:{a['score']})")
    else:
        print(f"[{now_str()}] No actions taken")

if __name__ == '__main__':
    main()
