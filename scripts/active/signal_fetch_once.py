"""
signal_fetch_once.py - 单次信号抓取 (v3.3 onchainos为主源)
每分钟由 Task Scheduler 调用一次
主信号源: onchainos (solana/base/ethereum)
辅助信号源: Binance Smart Money API (BSC)
soldRatioPercent 纳入评分 + 写入队列供执行器做仓位管理
"""
import sys, os, json, urllib.request, ssl, time, subprocess, re
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding='utf-8')

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from qclaw_trading_common import (
    okx_env_for_subprocess,
    canonical_chain_for_onchainos,
    locked_write_json,
    workspace_root,
)
from okx_dex_ws import OkxDexWs  # optional WS data source

DATA_DIR = os.path.join(workspace_root(__file__), 'data')
QUEUE_FILE = os.path.join(DATA_DIR, 'signal-queue.json')
LOG_FILE = os.path.join(DATA_DIR, 'signal-log.txt')
os.makedirs(DATA_DIR, exist_ok=True)

# ─── Scoring thresholds ───
MIN_WALLETS        = 2      # 最低触发钱包数
MIN_MARKET_CAP_USD = 50_000 # 最低市值
MAX_SOLD_RATIO     = 50     # soldRatio>50% 直接跳过（聪明钱已离场）
CHASE_PUMP_PCT     = 0.15   # 追涨限制
STALE_PENALTY_MIN  = 60     # 60分钟后开始扣分
STALE_PENALTY_MAX  = 180    # 180分钟后0分
SCORE_THRESHOLD    = 28     # 最低入场分数

# ─── onchainos chains ───
OC_CHAINS = [
    ('solana',    'Solana'),
    ('base',      'Base'),
    ('ethereum',  'Ethereum'),
]

# BSC chain mapping
BINANCE_CHAINS = [
    ('56', 'BSC'),
]

# Tracker: smart-money BUY activities (faster than signal list); merged after list fetch
TRACKER_MIN_VOL_USD = float(os.environ.get('TRACKER_MIN_VOL_USD', '400'))

def parse_onchainos_json(raw):
    """Extract last valid JSON object from onchainos output (may have log lines)."""
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


# ═══════════════════════════════════════════════
# Scoring: onchainos signal format
# ═══════════════════════════════════════════════
def score_onchainos(sig):
    """Score onchainos signal (0-100). Returns (score, reason)."""
    score = 0
    token = sig.get('token', {})
    
    # 1. Wallet count (0-35)
    wc = int(sig.get('triggerWalletCount', 0))
    if wc >= 8:   score += 35
    elif wc >= 5: score += 25
    elif wc >= 3: score += 12
    elif wc >= MIN_WALLETS: score += 5
    else: return 0, "WALLETS<2"
    
    # 2. Market cap filter (0-15)
    mcap = float(token.get('marketCapUsd', 0))
    if mcap >= 10_000_000:   score += 15
    elif mcap >= 1_000_000:  score += 10
    elif mcap >= 100_000:    score += 5
    elif mcap >= MIN_MARKET_CAP_USD: score += 2
    else: return 0, "MCAP<50K"
    
    # 3. Holders (0-8)
    holders = int(token.get('holders', 0))
    if holders >= 1000: score += 8
    elif holders >= 500: score += 5
    elif holders >= 100: score += 2
    
    # 4. Top10 holder concentration (risk, -12~+3)
    top10 = float(token.get('top10HolderPercent', 0))
    if top10 > 80:   score -= 12
    elif top10 > 60:  score -= 8
    elif top10 < 20:  score += 3
    elif top10 < 40:  score += 1
    
    # 5. Transaction amount (0-6)
    amt_usd = float(sig.get('amountUsd', 0))
    if amt_usd >= 5000:    score += 6
    elif amt_usd >= 1000:  score += 4
    elif amt_usd >= 500:   score += 2
    elif amt_usd >= 100:   score += 1
    
    # 6. soldRatioPercent (CORE, -30~+25): 建仓评分核心维度
    #    smart money holding → high score; smart money exiting → reject
    sold_ratio = float(sig.get('soldRatioPercent', 0))
    if sold_ratio >= MAX_SOLD_RATIO:  return 0, f"SOLD={sold_ratio:.0f}%"
    elif sold_ratio > 40:             score -= 30
    elif sold_ratio > 30:             score -= 25
    elif sold_ratio > 20:             score -= 15
    elif sold_ratio > 15:             score -= 10
    elif sold_ratio > 10:             score -= 5
    elif sold_ratio == 0:             score += 25  # 聪明钱纯建仓，零减持 = 强烈看多
    elif sold_ratio <= 1:             score += 20  # 极低减持
    elif sold_ratio <= 3:             score += 15  # 轻微获利了结
    elif sold_ratio <= 5:             score += 10  # 正常减仓
    elif sold_ratio <= 8:             score += 5   # 小幅出货
    
    # 7. Freshness
    ts_ms = int(sig.get('timestamp', 0))
    if ts_ms > 0:
        age_min = (time.time() * 1000 - ts_ms) / 60000
        if age_min > STALE_PENALTY_MAX:  return 0, f"STALE({age_min:.0f}m)"
        elif age_min > STALE_PENALTY_MIN:
            s = min(1.0, (age_min - STALE_PENALTY_MIN) / (STALE_PENALTY_MAX - STALE_PENALTY_MIN))
            score -= int(s * 15)
    
    return max(0, min(100, score)), "OK"


# ═══════════════════════════════════════════════
# Scoring: Binance Smart Money API format (v3.2)
# ═══════════════════════════════════════════════
def score_binance(sig):
    """Score Binance API signal (0-100)."""
    score = 0
    smc = sig.get('smartMoneyCount', 0)
    if smc >= 8:   score += 40
    elif smc >= 5: score += 25
    elif smc >= 3: score += 12
    elif smc >= MIN_WALLETS: score += 5
    else: return 0, "SM<2"
    
    direction = sig.get('direction', '')
    if direction == 'buy':   score += 10
    elif direction == 'sell': return 0, "SELL"
    
    sc = sig.get('signalCount', 0)
    if sc >= 15: score += 8
    elif sc >= 5: score += 3
    
    tags = sig.get('tokenTag', {}) or {}
    for cat, tl in tags.items():
        for t in (tl or []):
            tn = t.get('tagName', '')
            if tn == 'Smart Money Add Holdings': score += 12
            elif tn == 'Whale Buy': score += 15
            elif tn == 'DEX Paid': score += 3
            elif tn == 'Smart Money Reduce': score -= 18
            elif tn == 'Whale Sell': return 0, "WHALE_SELL"
    
    mc = float(sig.get('alertMarketCap', 0) or 0)
    if mc >= 1_000_000: score += 10
    elif mc >= 100_000: score += 5
    elif mc > 0: score -= 5
    else: return 0, "MCAP=0"
    
    cp = float(sig.get('currentPrice', 0) or 0)
    ap = float(sig.get('alertPrice', 0) or 0)
    if ap > 0 and cp > 0:
        spread = (cp - ap) / ap
        if abs(spread) > 0.25: return 0, f"SPREAD={spread:.1%}"
        elif abs(spread) > 0.15: score -= 30
        elif abs(spread) > 0.05: score -= 15
        if spread < -0.10:     score -= 15
        elif spread < -0.05:   score += 5
        elif spread <= 0.03:   score += 8
        elif spread <= CHASE_PUMP_PCT: score += 3
        elif spread <= 0.25:   score -= 8
        else: return 0, "CHASE>25%"
    
    status = sig.get('status', '')
    if status == 'active': score += 15
    elif status == 'timeout':
        tf = sig.get('timeFrame', 0)
        if tf < 3600000: score += 5
        else: score -= 10
    elif status in ('exitRate', 'outDecline'): return 0, f"STATUS={status}"
    
    created_at = sig.get('createdAt', 0) or sig.get('signalTriggerTime', 0)
    if created_at:
        age_min = (time.time() * 1000 - created_at) / 60000
        if age_min > 180: return 0, f"STALE({age_min:.0f}m)"
        elif age_min > 60:
            staleness = min(1.0, (age_min - 60) / 120)
            score -= int(staleness * 15)
    
    return max(0, min(100, score)), "OK"


# ═══════════════════════════════════════════════
# Fetch functions
# ═══════════════════════════════════════════════
def fetch_onchainos(chain_name, chain_display, limit=30):
    """Fetch signals from onchainos. Returns normalized signal list."""
    _okx = okx_env_for_subprocess()
    if not _okx:
        return []
    try:
        r = subprocess.run(
            ['onchainos', 'signal', 'list', '--chain', chain_name, '--limit', str(limit), '--wallet-type', '1'],
            capture_output=True, text=True, timeout=20, encoding='utf-8',
            env=_okx
        )
        d = parse_onchainos_json(r.stdout)
        if not d or not d.get('ok'):
            return []
        items = d.get('data', [])
        signals = []
        for s in items:
            if not isinstance(s, dict):
                continue
            token = s.get('token', {})
            ca = token.get('tokenAddress', '')
            if not ca:
                continue
            score, reason = score_onchainos(s)
            canon = canonical_chain_for_onchainos(chain_name, s.get('chainIndex', ''))
            # Normalize to common format (chain = canonical id for executors: CT_501, 56, …)
            normalized = {
                'source': 'onchainos',
                'chain': canon,
                'chain_slug': chain_name,
                'chain_name': chain_display,
                'chainIndex': s.get('chainIndex', ''),
                'ca': ca,
                'ticker': token.get('symbol', '?'),
                'tokenName': token.get('name', ''),
                'score': score,
                'score_reason': reason,
                'sigId': s.get('cursor', ''),
                'ts': time.time(),
                # Price & trading data
                'currentPrice': float(s.get('price', 0)),
                'amountUsd': float(s.get('amountUsd', 0)),
                'triggerWalletCount': int(s.get('triggerWalletCount', 0)),
                'soldRatioPercent': float(s.get('soldRatioPercent', 0)),
                'timestamp': int(s.get('timestamp', 0)),
                # Token metadata
                'marketCapUsd': float(token.get('marketCapUsd', 0)),
                'holders': int(token.get('holders', 0)),
                'top10HolderPercent': float(token.get('top10HolderPercent', 0)),
            }
            signals.append(normalized)
        return signals
    except Exception as e:
        return []


def fetch_binance(chain_id, chain_name):
    """Fetch signals from Binance Smart Money API. Returns normalized signal list."""
    try:
        ssl_ctx = ssl.create_default_context()
        url = 'https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai'
        body = json.dumps({
            'smartSignalType': '', 'page': 1, 'pageSize': 50, 'chainId': chain_id
        }).encode('utf-8')
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as r:
            d = json.loads(r.read().decode('utf-8'))
            items = d.get('data', []) if isinstance(d.get('data'), list) else d.get('data', {}).get('data', [])
            signals = []
            for s in items:
                if not isinstance(s, dict):
                    continue
                score, reason = score_binance(s)
                normalized = {
                    'source': 'binance',
                    'chain': chain_id,
                    'chain_slug': 'bsc',
                    'chain_name': chain_name,
                    'ca': s.get('contractAddress', ''),
                    'ticker': s.get('tokenSymbol', '?'),
                    'tokenName': s.get('tokenName', ''),
                    'score': score,
                    'score_reason': reason,
                    'sigId': str(s.get('signalId', '')),
                    'ts': time.time(),
                    'currentPrice': float(s.get('currentPrice', 0) or 0),
                    'alertPrice': float(s.get('alertPrice', 0) or 0),
                    'alertMarketCap': float(s.get('alertMarketCap', 0) or 0),
                    'smartMoneyCount': int(s.get('smartMoneyCount', 0)),
                    'signalCount': int(s.get('signalCount', 0)),
                    'direction': s.get('direction', ''),
                    'status': s.get('status', ''),
                    'timeFrame': int(s.get('timeFrame', 0)),
                    'tokenTag': s.get('tokenTag', {}),
                    # soldRatio not available from Binance API
                    'soldRatioPercent': 0,
                }
                signals.append(normalized)
            return signals
    except Exception:
        return []


def fetch_tracker_buy_signals():
    """
    Recent smart-money BUY trades (tracker activities) — fills gaps vs delayed signal list.
    Returns normalized entries compatible with execute_* / monitor (canonical `chain`).
    """
    env = okx_env_for_subprocess()
    if not env:
        return []
    out_rows = []
    # (onchainos --chain name, canonical queue chain id)
    chains = [('solana', 'CT_501'), ('bsc', '56')]
    for cli_name, canon in chains:
        try:
            r = subprocess.run(
                [
                    'onchainos', 'tracker', 'activities',
                    '--tracker-type', 'smart_money',
                    '--chain', cli_name,
                    '--min-volume', str(int(TRACKER_MIN_VOL_USD)),
                ],
                capture_output=True, text=True, timeout=25, encoding='utf-8',
                env=env,
            )
            d = parse_onchainos_json(r.stdout)
            if not d or not d.get('ok'):
                continue
            trades = d.get('data', {}).get('trades') or []
            for t in trades:
                if not isinstance(t, dict):
                    continue
                if str(t.get('tradeType', '')) != '1':
                    continue
                ca = (t.get('tokenContractAddress') or t.get('tokenAddress') or '').strip()
                if not ca:
                    continue
                vol = float(
                    t.get('amountUsd', 0)
                    or t.get('volumeUsd', 0)
                    or t.get('tradeAmountUsd', 0)
                    or 0
                )
                if vol < TRACKER_MIN_VOL_USD:
                    continue
                sym = t.get('tokenSymbol', '?') or '?'
                px = float(t.get('price', 0) or t.get('tokenPrice', 0) or 0)
                boost = min(22, int(vol / 700))
                sc = min(58, SCORE_THRESHOLD + 2 + boost)
                sig_tail = str(t.get('tradeTime', t.get('id', '')))[-12:]
                out_rows.append({
                    'source': 'onchainos_tracker',
                    'chain': canon,
                    'chain_slug': cli_name,
                    'chain_name': 'Solana' if cli_name == 'solana' else 'BSC',
                    'chainIndex': '501' if canon == 'CT_501' else '56',
                    'ca': ca,
                    'ticker': sym,
                    'tokenName': sym,
                    'score': sc,
                    'score_reason': 'TRACKER_BUY',
                    'sigId': f"trk_{cli_name}_{ca[:8]}_{sig_tail}",
                    'ts': time.time(),
                    'currentPrice': px,
                    'amountUsd': vol,
                    'triggerWalletCount': 1,
                    'soldRatioPercent': 0.0,
                    'timestamp': int(t.get('tradeTime', 0) or 0),
                    'marketCapUsd': 0.0,
                    'holders': 0,
                    'top10HolderPercent': 0.0,
                })
        except Exception:
            continue
    return out_rows


# ═══════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════
def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    ts = now.strftime('%H:%M:%S')
    signals = []
    
    # 1. Fetch from onchainos (primary)
    for chain_name, chain_display in OC_CHAINS:
        items = fetch_onchainos(chain_name, chain_display, 50)
        for s in items:
            signals.append(s)
    
    # 2. Fetch from Binance (secondary — BSC only)
    for chain_id, chain_name in BINANCE_CHAINS:
        items = fetch_binance(chain_id, chain_name)
        for s in items:
            # Dedup: skip if same CA already in signals from onchainos
            ca = s.get('ca', '').lower()
            if ca and any(x.get('ca', '').lower() == ca for x in signals):
                continue
            signals.append(s)

    # 3. Tracker BUYs (not already in list — faster path for memecoin windows)
    try:
        seen = {s.get('ca', '').lower() for s in signals if s.get('ca')}
        for row in fetch_tracker_buy_signals():
            k = row.get('ca', '').lower()
            if k and k not in seen:
                signals.append(row)
                seen.add(k)
    except Exception:
        pass

    # 4. Write queue (atomic + lock)
    locked_write_json(QUEUE_FILE, signals, indent=2)
    
    # 5. Stats
    qualified = [s for s in signals if s['score'] >= SCORE_THRESHOLD]
    sources = {}
    for s in signals:
        src = s.get('source', '?')
        sources[src] = sources.get(src, 0) + 1
    src_str = ', '.join(f'{k}:{v}' for k, v in sources.items())
    
    print(f'[{ts}] {len(signals)} signals ({src_str}) | {len(qualified)} qualified')
    
    # Log
    log_line = f'[{now.strftime("%Y-%m-%d %H:%M")}] {len(signals)} fetched, {len(qualified)} pass'
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_line + '\n')


if __name__ == '__main__':
    main()
