"""analysis_soldratio.py - 分析 soldRatio 过滤是否过度"""
import json, sys, os
sys.stdout.reconfigure(encoding='utf-8')

DATA_DIR = os.path.join(os.path.expanduser('~'), '.qclaw', 'workspace', 'data')
QUEUE_FILE = os.path.join(DATA_DIR, 'signal-queue.json')

with open(QUEUE_FILE, encoding='utf-8') as f:
    q = json.load(f)

onchainos = [s for s in q if s.get('source') == 'onchainos']
print(f"=== onchainos 信号分布 (n={len(onchainos)}) ===\n")

# 1. soldRatio 分布（不做任何过滤）
sold_buckets = {
    '0%': 0, '1-5%': 0, '5-10%': 0, '10-20%': 0,
    '20-30%': 0, '30-40%': 0, '40-50%': 0, '50-60%': 0,
    '60-70%': 0, '70-80%': 0, '80-90%': 0, '90-100%': 0
}
for s in onchainos:
    sr = s.get('soldRatioPercent', 0)
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
    bar = '#' * min(count, 50)
    print(f"  {bucket:>10}: {count:>3} {bar}")

# 2. 不同 soldRatio 阈值下的通过量
print("\n=== 不同 soldRatio 阈值的影响 ===\n")
thresholds = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
for thresh in thresholds:
    passing = [s for s in onchainos if s.get('soldRatioPercent', 0) <= thresh]
    # 也要减去 MCAP<50K
    passing = [s for s in passing if s.get('marketCapUsd', 0) >= 50000]
    print(f"  soldRatio <= {thresh:>3}%: {len(passing):>3} 个信号通过市值过滤")

# 3. 按 walletCount 分层看 soldRatio
print("\n=== 按钱包数分层 ===\n")
for min_wc in [3, 5, 8, 10]:
    subset = [s for s in onchainos if s.get('triggerWalletCount', 0) >= min_wc]
    if not subset:
        continue
    avg_sold = sum(s.get('soldRatioPercent', 0) for s in subset) / len(subset)
    low_sold = len([s for s in subset if s.get('soldRatioPercent', 0) <= 20])
    print(f"  wallets >= {min_wc:>2}: {len(subset):>3} signals, avg_sold={avg_sold:.1f}%, sold<=20%: {low_sold}")

# 4. 高钱包数 + 低 soldRatio 的信号（最有价值的）
print("\n=== 最佳信号: wallets>=3, sold<=20%, mcap>=50K ===\n")
best = [s for s in onchainos
        if s.get('triggerWalletCount', 0) >= 3
        and s.get('soldRatioPercent', 0) <= 20
        and s.get('marketCapUsd', 0) >= 50000]
best.sort(key=lambda x: -x.get('score', 0))
for s in best[:15]:
    t = s.get('ticker', '?')
    sc = s.get('score', 0)
    sold = s.get('soldRatioPercent', 0)
    mcap = s.get('marketCapUsd', 0)
    wc = s.get('triggerWalletCount', 0)
    holders = s.get('holders', 0)
    top10 = s.get('top10HolderPercent', 0)
    print(f"  {t:>10} score={sc:>3} sold={sold:>5.1f}% mcap=${mcap:>12,.0f} wallets={wc} holders={holders} top10={top10:.0f}%")

print(f"\n总计最佳信号: {len(best)}")

# 5. 放宽 soldRatio 后能多拿到多少信号？
print("\n=== 放宽 soldRatio 阈值的信号量变化 ===\n")
for sold_limit in [10, 15, 20, 30, 40, 50, 60, 70]:
    cands = [s for s in onchainos
             if s.get('soldRatioPercent', 0) <= sold_limit
             and s.get('marketCapUsd', 0) >= 50000
             and s.get('triggerWalletCount', 0) >= 2]
    # 重新评分这些信号（用当前评分函数但去掉 soldRatio 过滤）
    # 简单估算：原 score 中 soldRatio 贡献 +25(0%), +20(1%), +15(3%), +10(5%), +5(8%), 0(10%), -5(15%), -10(20%), -15(30%), -25(40%), -30(>40%)
    # 放宽后 soldRatio 加分会变
    scored = []
    for s in cands:
        sold = s.get('soldRatioPercent', 0)
        base_score = s.get('score', 0)
        # 粗略调整：soldRatio 阈值放宽后，原来 sold>50 的信号进来，评分会根据 sold 调整
        if sold <= 0: sold_score = 25
        elif sold <= 1: sold_score = 20
        elif sold <= 3: sold_score = 15
        elif sold <= 5: sold_score = 10
        elif sold <= 8: sold_score = 5
        elif sold <= 10: sold_score = 0
        elif sold <= 15: sold_score = -5
        elif sold <= 20: sold_score = -10
        elif sold <= 30: sold_score = -15
        elif sold <= 40: sold_score = -25
        else: sold_score = -30
        adj_score = base_score + (sold_score - (25 if sold <= 0 else 20 if sold <= 1 else 15 if sold <= 3 else 10 if sold <= 5 else 5 if sold <= 8 else 0 if sold <= 10 else -5 if sold <= 15 else -10 if sold <= 20 else -15 if sold <= 30 else -25))
        # Actually, let me just count raw
        scored.append((s, base_score))
    pass_28 = len([x for _, x in scored if x >= 28])
    pass_20 = len([x for _, x in scored if x >= 20])
    pass_15 = len([x for _, x in scored if x >= 15])
    print(f"  soldRatio <= {sold_limit:>3}%: {len(cands):>3} signals, score>=28: {pass_28}, >=20: {pass_20}, >=15: {pass_15}")
