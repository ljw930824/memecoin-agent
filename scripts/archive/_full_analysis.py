"""full_analysis.py - 跑信号 + 分析 soldRatio 分布，不依赖队列文件"""
import json, sys, os, subprocess, urllib.request, ssl, time, re
sys.stdout.reconfigure(encoding='utf-8')

def parse_onchainos_json(raw):
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except:
        return None

def fetch_onchainos(chain, limit=50):
    try:
        r = subprocess.run(['onchainos', 'signal', 'list', '--chain', chain, '--limit', str(limit), '--wallet-type', '1'],
                          capture_output=True, text=True, timeout=20, encoding='utf-8')
        d = parse_onchainos_json(r.stdout)
        if not d or not d.get('ok'):
            return []
        return d.get('data', [])
    except:
        return []

def fetch_binance(chain_id):
    try:
        ssl_ctx = ssl.create_default_context()
        url = 'https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai'
        body = json.dumps({'smartSignalType': '', 'page': 1, 'pageSize': 50, 'chainId': chain_id}).encode()
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as r:
            d = json.loads(r.read().decode())
            items = d.get('data', []) if isinstance(d.get('data'), list) else d.get('data', {}).get('data', [])
            return items
    except:
        return []

# Fetch all signals
all_signals = []
for chain in ['solana', 'base', 'ethereum']:
    for s in fetch_onchainos(chain, 50):
        s['_chain'] = chain
        all_signals.append(('onchainos', chain, s))

for chain_id in ['56']:
    for s in fetch_binance(chain_id):
        all_signals.append(('binance', 'BSC', s))

onchainos = [s for src, ch, s in all_signals if src == 'onchainos']
n = len(onchainos)
print(f"=== onchainos 信号分布 (n={n}) ===\n")

# 1. soldRatio distribution
sold_buckets = {
    '0%': 0, '1-5%': 0, '5-10%': 0, '10-20%': 0,
    '20-30%': 0, '30-40%': 0, '40-50%': 0, '50-60%': 0,
    '60-70%': 0, '70-80%': 0, '80-90%': 0, '90-100%': 0
}
for s in onchainos:
    sr = float(s.get('soldRatioPercent', 0))
    if sr == 0: sold_buckets['0%'] += 1
    elif sr <= 5: sold_buckets['1-5%'] += 1
    elif sr <= 10: sold_buckets['5-10%'] += 1
    elif sr <= 20: sold_buckets['10-20%'] += 1
    elif sr <= 30: sold_buckets['20-30%'] += 1
    elif sr <= 40: sold_buckets['30-40%'] += 1
    elif sr <= 50: sold_buckets['40-50%'] += 1
    elif sr <= 60: sold_buckets['50-60%'] += 1
    elif sr <= 70: sold_buckets['60-70%'] += 1
    elif sr <= 80: sold_buckets['70-80%'] += 1
    elif sr <= 90: sold_buckets['80-90%'] += 1
    else: sold_buckets['90-100%'] += 1

print("soldRatioPercent 分布:")
for bucket, count in sold_buckets.items():
    pct = count / n * 100 if n > 0 else 0
    bar = '#' * int(pct / 2)
    print(f"  {bucket:>10}: {count:>3} ({pct:>5.1f}%) {bar}")

# 2. Different soldRatio thresholds
print("\n=== 不同 soldRatio 阈值的影响 ===")
print("  soldRatio <= X% 且 mcap >= 50K:")
for thresh in [0, 5, 10, 15, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
    passing = [s for s in onchainos
               if float(s.get('soldRatioPercent', 0)) <= thresh
               and float(s.get('token', {}).get('marketCapUsd', 0)) >= 50000]
    print(f"    <= {thresh:>3}%: {len(passing):>3} signals")

# 3. Wallet count tiers
print("\n=== 按钱包数分层 ===")
for min_wc in [2, 3, 5, 8, 10]:
    subset = [s for s in onchainos if int(s.get('triggerWalletCount', 0)) >= min_wc]
    if not subset:
        continue
    avg_sold = sum(float(s.get('soldRatioPercent', 0)) for s in subset) / len(subset)
    low_sold = len([s for s in subset if float(s.get('soldRatioPercent', 0)) <= 20])
    total_low_sold = len([s for s in subset if float(s.get('soldRatioPercent', 0)) <= 30])
    print(f"  wallets >= {min_wc:>2}: {len(subset):>3} signals, avg_sold={avg_sold:.1f}%, sold<=20%: {low_sold}, sold<=30%: {total_low_sold}")

# 4. Best signals: high wallets + low sold + good mcap
print("\n=== 最佳信号: wallets>=3, sold<=20%, mcap>=50K ===")
best = [s for s in onchainos
        if int(s.get('triggerWalletCount', 0)) >= 3
        and float(s.get('soldRatioPercent', 0)) <= 20
        and float(s.get('token', {}).get('marketCapUsd', 0)) >= 50000]
best.sort(key=lambda x: -int(x.get('triggerWalletCount', 0)))
for s in best[:15]:
    token = s.get('token', {})
    t = token.get('symbol', '?')
    sold = float(s.get('soldRatioPercent', 0))
    mcap = float(token.get('marketCapUsd', 0))
    wc = int(s.get('triggerWalletCount', 0))
    holders = int(token.get('holders', 0))
    top10 = float(token.get('top10HolderPercent', 0))
    amt = float(s.get('amountUsd', 0))
    print(f"  {t:>12} sold={sold:>5.1f}% mcap=${mcap:>12,.0f} wallets={wc} holders={holders} top10={top10:.0f}% amt=${amt:.0f}")
print(f"  总计: {len(best)}")

# 5. What if we ignore soldRatio entirely?
print("\n=== 如果完全忽略 soldRatio ===")
no_sold_filter = [s for s in onchainos
                  if int(s.get('triggerWalletCount', 0)) >= 2
                  and float(s.get('token', {}).get('marketCapUsd', 0)) >= 50000]
print(f"  wallets>=2, mcap>=50K, 不看 soldRatio: {len(no_sold_filter)} signals")
for s in no_sold_filter[:10]:
    token = s.get('token', {})
    t = token.get('symbol', '?')
    sold = float(s.get('soldRatioPercent', 0))
    mcap = float(token.get('marketCapUsd', 0))
    wc = int(s.get('triggerWalletCount', 0))
    print(f"    {t:>12} sold={sold:>5.1f}% mcap=${mcap:>12,.0f} wallets={wc}")

# 6. soldRatio correlation analysis
print("\n=== soldRatio 与信号质量的相关性 ===")
# Group by soldRatio bucket, show avg wallets
for label, lo, hi in [('0%', 0, 0), ('1-5%', 1, 5), ('5-20%', 5, 20), ('20-50%', 20, 50), ('50-100%', 50, 100)]:
    subset = [s for s in onchainos if lo <= float(s.get('soldRatioPercent', 0)) <= hi]
    if not subset:
        continue
    avg_wc = sum(int(s.get('triggerWalletCount', 0)) for s in subset) / len(subset)
    avg_mcap = sum(float(s.get('token', {}).get('marketCapUsd', 0)) for s in subset) / len(subset)
    avg_holders = sum(int(s.get('token', {}).get('holders', 0)) for s in subset) / len(subset)
    print(f"  sold {label:>10}: n={len(subset):>3}, avg_wallets={avg_wc:.1f}, avg_mcap=${avg_mcap:>12,.0f}, avg_holders={avg_holders:.0f}")
