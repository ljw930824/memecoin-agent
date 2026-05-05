"""
realtime_sm_monitor.py v2 - 聪明钱实时跟单监控
基于 onchainos tracker activities REST 轮询 + 差分检测

运行: python realtime_sm_monitor.py
  --dry-run   只输出信号，不执行交易
  --once      跑一轮就退出
"""

import json, sys, os, subprocess, re, time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

# === 配置 ===
BASE = os.path.join(os.path.expanduser('~'), '.qclaw', 'workspace')
DATA = os.path.join(BASE, 'data')
WALLET = '77BP1JzBARGaQ8eJWj6B1RYvaB4zRxU7Nx7BDYdgLCAa'
USDT = 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB'
STATE_FILE = os.path.join(DATA, 'sm_monitor_state.json')
LOG_FILE = os.path.join(DATA, 'sm_trade-log.txt')

MIN_MCAP = 50000          # 最小市值
MIN_VOLUME = 500          # tracker 最小交易额
MAX_POSITIONS = 3         # 最大同时持仓
BUY_SIZE_USDT = 10        # 单笔买入 USDT
SL_PCT = -0.08            # 止损 -8%
TP_PCT = 0.12             # 止盈 +12%
SM_SELL_FOLLOW = 3        # 聪明钱卖 >= N 笔跟卖
TRACKER_POLL_SEC = 30     # 轮询间隔

DRY_RUN = '--dry-run' in sys.argv
ONCE = '--once' in sys.argv

# === 工具 ===
def log(msg):
    ts = datetime.now(timezone(timedelta(hours=8))).strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except: pass

def parse_json(raw):
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m: return None
    try: return json.loads(m.group(0))
    except: return None

def load_state():
    try:
        with open(STATE_FILE, encoding='utf-8') as f:
            return json.load(f)
    except:
        return {'seen_txs': [], 'positions': {}, 'last_ts': 0}

def save_state(state):
    os.makedirs(DATA, exist_ok=True)
    state['seen_txs'] = state['seen_txs'][-1000:]
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def oc_run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding='utf-8')
        return r.stdout, r.returncode
    except Exception as e:
        return str(e), -1

# === 数据采集 ===
def fetch_tracker(chain='solana'):
    """获取 smart money 最近交易"""
    out, rc = oc_run([
        'onchainos', 'tracker', 'activities',
        '--tracker-type', 'smart_money',
        '--chain', chain,
        '--min-volume', str(MIN_VOLUME)
    ])
    d = parse_json(out)
    if not d or not d.get('ok'):
        log(f'tracker error: rc={rc}')
        return []
    return d.get('data', {}).get('trades', [])

def get_balance(chain='solana'):
    """查钱包余额: 返回 {symbol: (balance, contract_address)}"""
    out, _ = oc_run([
        'onchainos', 'portfolio', 'all-balances',
        '--address', WALLET, '--chains', chain, '--chain', chain
    ])
    d = parse_json(out)
    if not d or not d.get('ok'):
        return {}
    result = {}
    for asset in d.get('data', [{}])[0].get('tokenAssets', []):
        sym = asset.get('symbol', '')
        bal = float(asset.get('balance', 0))
        ca = asset.get('tokenContractAddress', '')
        if bal > 0:
            result[sym] = (bal, ca)
    return result

def get_token_price_usd(chain, token_ca):
    """通过 quote 获取 token USD 价格"""
    out, _ = oc_run([
        'onchainos', 'swap', 'quote',
        '--chain', chain,
        '--from', USDT,
        '--to', token_ca,
        '--readable-amount', '1'
    ], timeout=10)
    d = parse_json(out)
    if not d or not d.get('ok'):
        return None
    for route in d.get('data', []):
        tt = route.get('toToken', {})
        if tt.get('tokenContractAddress', '').lower() == token_ca.lower():
            return float(tt.get('tokenUnitPrice', 0))
    return None

# === 交易执行 ===
def execute_buy(chain, token_ca, amount_usdt):
    """买入: USDT -> token"""
    if DRY_RUN:
        log(f'[DRY] BUY ${amount_usdt} -> {token_ca[:12]}...')
        return True, 'dry-tx'
    out, rc = oc_run([
        'onchainos', 'swap', 'execute',
        '--chain', chain,
        '--from', USDT,
        '--to', token_ca,
        '--readable-amount', str(amount_usdt),
        '--wallet', WALLET,
        '--slippage', '15'
    ], timeout=30)
    d = parse_json(out)
    if d and d.get('ok'):
        tx = d['data'].get('swapTxHash', '')
        log(f'BUY OK: tx={tx[:20]}...')
        return True, tx
    else:
        err = d.get('error', 'unknown') if d else out[:100]
        log(f'BUY FAIL: {err}')
        return False, None

def execute_sell(chain, token_ca, token_balance):
    """卖出全部 token -> USDT"""
    if DRY_RUN:
        log(f'[DRY] SELL {token_balance:.0f} {token_ca[:12]}...')
        return True, 'dry-tx'
    out, rc = oc_run([
        'onchainos', 'swap', 'execute',
        '--chain', chain,
        '--from', token_ca,
        '--to', USDT,
        '--readable-amount', str(int(token_balance)),
        '--wallet', WALLET,
        '--slippage', '20'
    ], timeout=30)
    d = parse_json(out)
    if d and d.get('ok'):
        tx = d['data'].get('swapTxHash', '')
        got = int(d['data'].get('toAmount', 0)) / 1e6
        log(f'SELL OK: tx={tx[:20]}... got=${got:.2f}')
        return True, tx
    else:
        err = d.get('error', 'unknown') if d else out[:100]
        log(f'SELL FAIL: {err}')
        return False, None

# === 核心逻辑 ===
def process_new_trades(trades, state):
    """差分检测新交易，处理买卖信号"""
    positions = state.get('positions', {})
    seen = set(state.get('seen_txs', []))

    # 找新交易
    new = [t for t in trades if t.get('txHash') and t['txHash'] not in seen]
    if not new:
        return positions

    # 更新 seen
    for t in new:
        seen.add(t['txHash'])
    state['seen_txs'] = list(seen)

    # 按 token 分组
    activity = defaultdict(lambda: {'buys': 0, 'sells': 0, 'latest': None})
    for t in new:
        ca = t.get('tokenContractAddress', '')
        tt = int(t.get('tradeType', 0))
        if tt == 1:
            activity[ca]['buys'] += 1
        else:
            activity[ca]['sells'] += 1
        activity[ca]['latest'] = t

    log(f'New trades: {len(new)} across {len(activity)} tokens')

    for ca, act in activity.items():
        lat = act['latest']
        sym = lat.get('tokenSymbol', '?')
        mcap = float(lat.get('marketCap', 0))
        chain_idx = lat.get('chainIndex', '')
        chain = 'solana' if chain_idx == '501' else 'unknown'

        # --- 持仓中: 检测聪明钱卖出 ---
        if ca in positions:
            if act['sells'] > 0:
                positions[ca]['sm_sells'] = positions[ca].get('sm_sells', 0) + act['sells']
                total_sells = positions[ca]['sm_sells']
                log(f'SM SELL on {sym}: total_sm_sells={total_sells}')
                if total_sells >= SM_SELL_FOLLOW:
                    log(f'TRIGGER SELL {sym} (SM sells={total_sells})')
                    bal_info = get_balance(chain)
                    token_bal = bal_info.get(sym, (0, ''))[0]
                    if token_bal > 0:
                        ok, _ = execute_sell(chain, ca, token_bal)
                        if ok:
                            del positions[ca]
            continue

        # --- 新 token: 检测聪明钱买入 ---
        if act['buys'] > 0:
            if mcap < MIN_MCAP:
                log(f'SKIP {sym}: mcap=${mcap:,.0f} < ${MIN_MCAP:,}')
                continue
            if len(positions) >= MAX_POSITIONS:
                log(f'SKIP {sym}: max positions ({MAX_POSITIONS})')
                continue
            if chain == 'unknown':
                log(f'SKIP {sym}: unsupported chain')
                continue

            log(f'SM BUY: {sym} (buys={act["buys"]}, mcap=${mcap:,.0f})')
            ok, tx = execute_buy(chain, ca, BUY_SIZE_USDT)
            if ok:
                positions[ca] = {
                    'symbol': sym,
                    'chain': chain,
                    'entry_ts': int(time.time()),
                    'entry_mcap': mcap,
                    'sm_buys': act['buys'],
                    'sm_sells': 0,
                    'buy_tx': tx
                }

    return positions


def check_positions(positions):
    """检查持仓 P&L，执行 SL/TP"""
    if not positions:
        return positions

    to_sell = []
    for ca, pos in list(positions.items()):
        chain = pos.get('chain', 'solana')
        sym = pos.get('symbol', '?')
        entry_mcap = pos.get('entry_mcap', 0)

        # 通过 signal list 查当前市值
        out, _ = oc_run([
            'onchainos', 'signal', 'list',
            '--chain', chain,
            '--token-address', ca,
            '--limit', '1'
        ], timeout=10)
        d = parse_json(out)
        current_mcap = 0
        if d and d.get('ok') and d.get('data'):
            current_mcap = float(d['data'][0].get('token', {}).get('marketCapUsd', 0))

        if current_mcap <= 0 or entry_mcap <= 0:
            continue

        pnl = (current_mcap - entry_mcap) / entry_mcap
        pos['current_mcap'] = current_mcap
        pos['pnl_pct'] = pnl

        if pnl <= SL_PCT:
            log(f'SL HIT: {sym} PnL={pnl:.1%} -> SELLING')
            to_sell.append(ca)
        elif pnl >= TP_PCT:
            log(f'TP HIT: {sym} PnL={pnl:.1%} -> SELLING')
            to_sell.append(ca)

    for ca in to_sell:
        pos = positions.get(ca, {})
        chain = pos.get('chain', 'solana')
        sym = pos.get('symbol', '?')
        bal_info = get_balance(chain)
        token_bal = bal_info.get(sym, (0, ''))[0]
        if token_bal > 0:
            ok, _ = execute_sell(chain, ca, token_bal)
            if ok:
                del positions[ca]

    return positions


# === 主循环 ===
def run_once(state):
    trades = fetch_tracker('solana')
    positions = process_new_trades(trades, state)
    positions = check_positions(positions)
    state['positions'] = positions
    state['last_poll'] = int(time.time())
    save_state(state)

    if positions:
        log(f'Open: {len(positions)}')
        for ca, p in positions.items():
            pnl = p.get('pnl_pct', 0)
            log(f'  {p.get("symbol","?")}: PnL={pnl:+.1%} SM_sells={p.get("sm_sells",0)}')
    else:
        log('No open positions')

    return positions

def main():
    mode = 'DRY-RUN' if DRY_RUN else 'LIVE'
    log(f'=== SM Monitor v2 [{mode}] ===')

    state = load_state()

    if ONCE:
        run_once(state)
        return

    # 持续轮询
    try:
        while True:
            run_once(state)
            log(f'--- sleep {TRACKER_POLL_SEC}s ---')
            time.sleep(TRACKER_POLL_SEC)
    except KeyboardInterrupt:
        log('Stopped by user')
        save_state(state)

if __name__ == '__main__':
    main()
