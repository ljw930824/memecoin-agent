"""
backtest_analysis.py v2 - 聪明钱跟单策略回测分析
修复: signal list limit=50, tracker PnL 字段 = realizedPnlUsd
"""

import json, sys, os, subprocess, re, time
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter

sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.join(os.path.expanduser('~'), '.qclaw', 'workspace')
DATA = os.path.join(BASE, 'data')

def parse_json(raw):
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m: return None
    try: return json.loads(m.group(0))
    except: return None

def oc_run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding='utf-8')
        return r.stdout, r.returncode
    except Exception as e:
        return str(e), -1

def fetch_signals(chain='solana', limit=50):
    out, _ = oc_run(['onchainos', 'signal', 'list', '--chain', chain, '--limit', str(limit)])
    d = parse_json(out)
    if not d or not d.get('ok'): return []
    return d.get('data', [])

def fetch_tracker(chain='solana', min_vol=500):
    out, _ = oc_run(['onchainos', 'tracker', 'activities', '--tracker-type', 'smart_money', '--chain', chain, '--min-volume', str(min_vol)])
    d = parse_json(out)
    if not d or not d.get('ok'): return []
    return d.get('data', {}).get('trades', [])

def main():
    print('=== 聪明钱跟单策略回测分析 v2 ===')
    print(f'Time: {datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")}')

    # 1. 采集数据
    print('\n[1/6] 采集 signal list (limit=50)...')
    signals = fetch_signals('solana', 50)
    print(f'  {len(signals)} signals')

    print('[2/6] 采集 tracker activities...')
    trades = fetch_tracker('solana', 500)
    sells = [t for t in trades if t.get('tradeType') == '2']
    buys = [t for t in trades if t.get('tradeType') == '1']
    print(f'  {len(trades)} trades ({len(buys)} buys, {len(sells)} sells)')

    # === A. soldRatio 分布 ===
    print('\n=== A. soldRatio 分布 ===')
    sold_buckets = defaultdict(list)
    for s in signals:
        tok = s.get('token', {})
        sold = float(tok.get('soldRatioPercent', 100))
        mcap = float(tok.get('marketCapUsd', 0))
        wallets = int(tok.get('triggerWalletCount', 0))
        sym = tok.get('symbol', '?')
        holders = int(tok.get('holders', 0))
        top10 = float(tok.get('top10HolderPercent', 100))
        amt = float(s.get('amountUsd', 0))

        b = '0-5%' if sold <= 5 else '5-20%' if sold <= 20 else '20-50%' if sold <= 50 else '50-80%' if sold <= 80 else '80-100%'
        sold_buckets[b].append({'sym': sym, 'sold': sold, 'mcap': mcap, 'wallets': wallets, 'holders': holders, 'top10': top10, 'amt': amt})

    for b in ['0-5%', '5-20%', '20-50%', '50-80%', '80-100%']:
        items = sold_buckets.get(b, [])
        n = len(items)
        if n == 0:
            print(f'  SOLD {b:>10}: 0 signals')
            continue
        am = sum(i['mcap'] for i in items) / n
        aw = sum(i['wallets'] for i in items) / n
        aa = sum(i['amt'] for i in items) / n
        print(f'  SOLD {b:>10}: n={n:>2} | avg_mcap=${am:>12,.0f} | avg_wallets={aw:.1f} | avg_amt=${aa:,.0f}')

    # === B. Tracker 盈亏分析 ===
    print('\n=== B. Tracker 盈亏分析 ===')
    pnls = []
    for t in sells:
        raw = t.get('realizedPnlUsd', '0')
        try:
            pnl = float(raw)
            pnls.append(pnl)
        except:
            pass

    if pnls:
        profitable = [p for p in pnls if p > 0]
        losing = [p for p in pnls if p < 0]
        total = sum(pnls)
        print(f'  卖出笔数: {len(pnls)}')
        print(f'  盈利: {len(profitable)} ({len(profitable)/len(pnls)*100:.0f}%) | 亏损: {len(losing)} ({len(losing)/len(pnls)*100:.0f}%)')
        print(f'  总 PnL: ${total:+,.2f}')
        if profitable:
            print(f'  平均盈利: ${sum(profitable)/len(profitable):+,.2f} | 最大盈利: ${max(profitable):+,.2f}')
        if losing:
            print(f'  平均亏损: ${sum(losing)/len(losing):+,.2f} | 最大亏损: ${min(losing):+,.2f}')
        if profitable and losing:
            print(f'  盈亏比: {abs(sum(profitable)/len(profitable)) / abs(sum(losing)/len(losing)):.2f}')
    else:
        print('  无有效 PnL 数据')

    # === C. Token 盈亏排行 ===
    print('\n=== C. Token 盈亏排行 ===')
    token_pnl = defaultdict(lambda: {'pnl': 0, 'sym': '', 'trades': 0})
    for t in sells:
        ca = t.get('tokenContractAddress', '')
        sym = t.get('tokenSymbol', '?')
        try:
            pnl = float(t.get('realizedPnlUsd', 0))
            token_pnl[ca]['pnl'] += pnl
            token_pnl[ca]['sym'] = sym
            token_pnl[ca]['trades'] += 1
        except: pass

    sorted_tokens = sorted(token_pnl.items(), key=lambda x: x[1]['pnl'], reverse=True)
    print('  最盈利:')
    for ca, info in sorted_tokens[:8]:
        print(f'    {info["sym"]:>12} PnL=${info["pnl"]:>+10,.2f} trades={info["trades"]}')
    print('  最亏损:')
    for ca, info in sorted_tokens[-5:]:
        print(f'    {info["sym"]:>12} PnL=${info["pnl"]:>+10,.2f} trades={info["trades"]}')

    # === D. 钱包行为模式 ===
    print('\n=== D. 钱包行为模式 ===')
    wallet_trades = defaultdict(list)
    for t in trades:
        wa = t.get('walletAddress', '')
        if wa: wallet_trades[wa].append(t)

    print(f'  {len(wallet_trades)} 钱包, {len(trades)} 交易')

    # 钱包盈亏
    wallet_pnl = {}
    for wa, ts in wallet_trades.items():
        total_pnl = 0
        for t in ts:
            if t.get('tradeType') == '2':
                try: total_pnl += float(t.get('realizedPnlUsd', 0))
                except: pass
        wallet_pnl[wa] = total_pnl

    top_wallets = sorted(wallet_pnl.items(), key=lambda x: x[1], reverse=True)
    print('  最赚钱钱包:')
    for wa, pnl in top_wallets[:5]:
        ts = wallet_trades[wa]
        wbuys = sum(1 for t in ts if t.get('tradeType') == '1')
        wsells = sum(1 for t in ts if t.get('tradeType') == '2')
        tokens = set(t.get('tokenSymbol', '?') for t in ts)
        print(f'    {wa[:12]}... PnL=${pnl:>+10,.2f} B={wbuys} S={wsells} tokens={len(tokens)}')
    print('  最亏钱钱包:')
    for wa, pnl in top_wallets[-3:]:
        ts = wallet_trades[wa]
        wbuys = sum(1 for t in ts if t.get('tradeType') == '1')
        wsells = sum(1 for t in ts if t.get('tradeType') == '2')
        print(f'    {wa[:12]}... PnL=${pnl:>+10,.2f} B={wbuys} S={wsells}')

    # === E. 信号时效性 ===
    print('\n=== E. 信号时效性 ===')
    early = sum(1 for s in signals if float(s.get('token', {}).get('soldRatioPercent', 100)) < 10)
    mid = sum(1 for s in signals if 10 <= float(s.get('token', {}).get('soldRatioPercent', 100)) < 50)
    late = sum(1 for s in signals if 50 <= float(s.get('token', {}).get('soldRatioPercent', 100)) < 90)
    dead = sum(1 for s in signals if float(s.get('token', {}).get('soldRatioPercent', 100)) >= 90)
    total = len(signals)
    print(f'  及时 (sold<10%):   {early:>2} ({early/max(total,1)*100:.0f}%) ← 跟单窗口')
    print(f'  延迟 (10-50%):     {mid:>2} ({mid/max(total,1)*100:.0f}%)')
    print(f'  严重延迟 (50-90%): {late:>2} ({late/max(total,1)*100:.0f}%) ← 做 exit liquidity')
    print(f'  完全滞后 (90%+):   {dead:>2} ({dead/max(total,1)*100:.0f}%) ← 绝不能入场')

    # === F. Tracker vs Signal 交叉验证 ===
    print('\n=== F. Tracker vs Signal 交叉验证 ===')
    tracker_buy_tokens = set(t.get('tokenContractAddress', '') for t in buys)
    tracker_sell_tokens = set(t.get('tokenContractAddress', '') for t in sells)
    signal_tokens = set(s.get('token', {}).get('tokenContractAddress', '') for s in signals)
    tracker_all = tracker_buy_tokens | tracker_sell_tokens
    overlap = signal_tokens & tracker_all
    print(f'  Signal tokens: {len(signal_tokens)}')
    print(f'  Tracker tokens: {len(tracker_all)}')
    print(f'  重叠: {len(overlap)} ({len(overlap)/max(len(tracker_all),1)*100:.0f}%)')
    print(f'  Tracker 独有 (signal 没收录): {len(tracker_all - signal_tokens)}')
    if tracker_all - signal_tokens:
        print('  → 这些 token 只有 tracker 看到，signal list 遗漏了')

    # === G. 跟单可行性评估 ===
    print('\n=== G. 跟单可行性评估 ===')
    # tracker 中有买入的 token，如果 soldRatio < 50% 在 signal list 中，评估跟单效果
    followable = []
    for s in signals:
        tok = s.get('token', {})
        sold = float(tok.get('soldRatioPercent', 100))
        ca = tok.get('tokenContractAddress', '')
        mcap = float(tok.get('marketCapUsd', 0))
        sym = tok.get('symbol', '?')

        if ca in tracker_buy_tokens and sold < 50:
            # 这个 token 聪明钱买过，且 soldRatio < 50%（还有持仓）
            tpnl = token_pnl.get(ca, {}).get('pnl', 0)
            followable.append({'sym': sym, 'sold': sold, 'mcap': mcap, 'pnl': tpnl, 'ca': ca})

    if followable:
        print(f'  跟单候选 (tracker 有买入 + signal sold<50%): {len(followable)}')
        for f in sorted(followable, key=lambda x: x['pnl'], reverse=True):
            print(f'    {f["sym"]:>12} sold={f["sold"]:.0f}% mcap=${f["mcap"]:>12,.0f} SM_PnL=${f["pnl"]:>+10,.2f}')
    else:
        print('  无跟单候选信号')

    # 时间窗口分析
    print('\n  === Tracker 时间窗口 ===')
    if trades:
        newest = max(int(t.get('tradeTime', 0)) for t in trades)
        oldest = min(int(t.get('tradeTime', 0)) for t in trades)
        span_h = (newest - oldest) / 1000 / 3600
        print(f'  时间跨度: {span_h:.1f} 小时')
        print(f'  最新交易: {datetime.fromtimestamp(newest/1000, tz=timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")}')
        print(f'  最旧交易: {datetime.fromtimestamp(oldest/1000, tz=timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")}')

    # 总结
    print('\n' + '='*50)
    print('=== 策略评估总结 ===')
    print('='*50)

    if pnls:
        wr = len(profitable) / len(pnls) * 100
        avg_p = sum(profitable) / len(profitable) if profitable else 0
        avg_l = sum(losing) / len(losing) if losing else 0
        print(f'  聪明钱胜率: {wr:.0f}%')
        print(f'  平均盈利: ${avg_p:+,.2f} | 平均亏损: ${avg_l:+,.2f}')
        print(f'  总 PnL: ${sum(pnls):+,.2f}')
        if wr < 50:
            print(f'  ⚠️ 聪明钱胜率仅 {wr:.0f}%，不是所有聪明钱都赚钱')
        if abs(avg_l) > abs(avg_p):
            print(f'  ⚠️ 亏大赢小 (avg_loss > avg_profit)，需要严格的止损')

    timely_pct = early / max(total, 1) * 100
    print(f'  信号及时率: {timely_pct:.0f}%')
    if timely_pct < 10:
        print(f'  ❌ 仅 {timely_pct:.0f}% 信号是及时的，跟单数据源延迟严重')
        print(f'  → 建议: 改用 tracker activities 实时差分，而非 signal list')

    print('\n=== 分析完成 ===')

if __name__ == '__main__':
    main()
