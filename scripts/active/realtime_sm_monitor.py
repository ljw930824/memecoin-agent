"""


realtime_sm_monitor.py v3.3 ??(Bug ?


onchainos tracker activities REST





: python realtime_sm_monitor.py [--once]





??scripts/simulation/sm_monitor_sim.py


"""





import sys
import json, sys, os, subprocess, re, time


from datetime import datetime, timezone, timedelta


from collections import defaultdict





sys.stdout.reconfigure(encoding='utf-8')

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
try:
    from qclaw_trading_common import okx_env_for_subprocess  # noqa: E402
except ImportError:
    okx_env_for_subprocess = None  # type: ignore


# ===  ===


BASE = os.path.join(os.path.expanduser('~'), '.qclaw', 'workspace')


DATA = os.path.join(BASE, 'data')


WALLET = '77BP1JzBARGaQ8eJWj6B1RYvaB4zRxU7Nx7BDYdgLCAa'


USDT_SOL = 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB'


USDT_BSC = '0x55d398326f99059fF775485246999027B3197955'


BNB_BSC = '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee'





# ?

TP_PCT = 0.12           # BSC  +12% ?

LIMIT_ORDER_TIMEOUT = 1800  # = 30+?
# --- Hot-reload tracking ---
_STATE_FILE_MTIME = 0





def usdt_addr(chain):


    return USDT_BSC if chain == 'bsc' else USDT_SOL





DRY_RUN = False  # ?

STATE_FILE = os.path.join(DATA, 'sm_monitor_state_dryrun.json' if DRY_RUN else 'sm_monitor_state.json')
CMD_FILE = os.path.join(DATA, 'sm_commands.json')



LOG_FILE = os.path.join(DATA, 'sm_trade-log_dryrun.txt' if DRY_RUN else 'sm_trade-log.txt')


WALLET_FILE = os.path.join(DATA, 'sm_wallets.json')





MIN_MCAP = 10000


MIN_VOLUME = 500


MAX_POSITIONS = 3


BUY_SIZE_USDT = 5          # 默认/兜底单笔金额

# === 头寸管理 & 风险控制 ===
RISK_PCT = 0.02            # 单笔风险系数 (账户总资金 x 1%)
SL_PCT_BASE = 0.08         # 基础止损幅度 (8%)
MAX_BUY_SIZE = 15.0        # 单笔最大买入 (USD)
MIN_BUY_SIZE = 3.0         # 单笔最小买入 (USD)
MAX_DAILY_LOSS_PCT = 0.05  # 日亏损上限 5% -> 当天停交易
MAX_MONTHLY_LOSS_PCT = 0.10  # 月亏损上限 10% -> 暂停一周

# Dynamic risk tiers: reduce RISK_PCT when daily loss accumulates
RISK_TIERS = [
    (0.02, 0.015),  # daily loss > 2% -> reduce to 1.5%
    (0.035, 0.01),  # daily loss > 3.5% -> reduce to 1%
]
BASE_RISK_PCT = RISK_PCT


SL_PCT = -0.08


SM_SELL_FOLLOW = 3


TRACKER_POLL_SEC = 10


MIN_WALLET_WINRATE = 0.5


MIN_CONSENSUS_WALLETS = 2


WALLET_HISTORY_WINDOW = 3600


DEAD_POSITION_USD = 0.50   # ?< $0.50


MAX_PRICE_RETRIES = 3      # ?

POSITION_STALE_HOURS = 72  # ?2h





ONCE = '--once' in sys.argv





# ===  ===


PRICE_HISTORY = {}  # {ca: [(ts, price), ...]}


TREND_FILE = os.path.join(DATA, 'sm_price_trends_dryrun.json' if DRY_RUN else 'sm_price_trends.json')








# ===  ===


def load_trends():


    global PRICE_HISTORY


    try:


        with open(TREND_FILE, encoding='utf-8') as f:


            PRICE_HISTORY = json.load(f)


    except:


        PRICE_HISTORY = {}








def save_trends():


    os.makedirs(DATA, exist_ok=True)


    now = time.time()


    trimmed = {}


    for ca, pts in PRICE_HISTORY.items():


        recent = [(t, p) for t, p in pts if now - t < 3600]  # 1h


        if recent:


            trimmed[ca] = recent


    tmp = TREND_FILE + '.tmp'


    with open(tmp, 'w') as f:


        json.dump(trimmed, f)


    os.replace(tmp, TREND_FILE)








def record_price(ca, price):


    if not ca or price <= 0:


        return


    if ca not in PRICE_HISTORY:


        PRICE_HISTORY[ca] = []


    PRICE_HISTORY[ca].append((time.time(), price))








def get_trend(ca, window_sec):


    """?(%/min)


    ?, ?


    """


    if ca not in PRICE_HISTORY:


        return 0.0


    now = time.time()


    pts = [(t, p) for t, p in PRICE_HISTORY[ca] if now - t <= window_sec]


    if len(pts) < 2:


        return 0.0


    t0, p0 = pts[0]


    t1, p1 = pts[-1]


    dt_min = (t1 - t0) / 60


    if dt_min < 0.5 or p0 <= 0:


        return 0.0


    return (p1 - p0) / p0 / dt_min  # % per minute





# ===  +  ===


LADDER_TP = [


    {'threshold': 0.30, 'label': ''},  # +30% ?7%


    {'threshold': 1.00, 'label': ''},  # +100% 50%

    {'threshold': 3.00, 'label': '4'},  # +300% 50%

]


LADDER_RATIOS = [0.77, 0.50, 0.50]





TIME_TIERS = [


    # (hold_hours, ? PnL, , )


    (6,  -0.05, 0.30,  0.50, '6h'),


    (12, -0.03, 0.15,  1.00, '12h'),


    (24,  0.00, 0.05,  1.00, '24h'),


    (48,  0.00, None,  1.00, '48h'),


]





# ===  ===


def get_effective_risk(state):
    """Dynamic risk: reduce when daily loss accumulates"""
    from datetime import datetime
    today_start = int(time.mktime(time.strptime(time.strftime('%Y-%m-%d'), '%Y-%m-%d')))
    realized_daily = 0.0
    for t in state.get('trade_history', []):
        if t.get('exit_ts', 0) >= today_start:
            realized_daily += t.get('exit_usd', t.get('exit_usd_amount', 0)) - t.get('entry_usd_amount', BUY_SIZE_USDT)
    unrealized_daily = 0.0
    for ca, p in state.get('positions', {}).items():
        if int(p.get('entry_ts', 0)) >= today_start:
            entry_usd = float(p.get('entry_usd_amount', BUY_SIZE_USDT))
            pnl_pct = float(p.get('pnl_pct', 0) or 0)
            remaining = 1.0 - float(p.get('sold_pct', 0))
            unrealized_daily += entry_usd * remaining * pnl_pct
    try:
        sol_bal = get_balance('solana')
        bsc_bal = get_balance('bsc')
        usdt_total = sol_bal.get(USDT_SOL.lower(), 0) + sol_bal.get(USDT_SOL, 0)
        usdt_total += bsc_bal.get(USDT_BSC.lower(), 0)
    except:
        usdt_total = 50.0
    account_total = max(usdt_total, 1.0)
    daily_pct = (realized_daily + unrealized_daily) / account_total
    effective = BASE_RISK_PCT
    for threshold, reduced in RISK_TIERS:
        if daily_pct <= -threshold:
            effective = reduced
    if effective != BASE_RISK_PCT:
        log(f'Dynamic risk: {BASE_RISK_PCT:.1%} -> {effective:.1%} (daily PnL {daily_pct:+.1%})')
    return effective

def calc_buy_size(state):
    """动态仓位: risk_amount / |SL%| = (total x RISK_PCT) / SL_PCT_BASE"""
    try:
        # 获取 USDT 余额
        sol_bal = get_balance('solana')
        bsc_bal = get_balance('bsc')
        usdt_total = sol_bal.get(USDT_SOL.lower(), 0) + sol_bal.get(USDT_SOL, 0)
        usdt_total += bsc_bal.get(USDT_BSC.lower(), 0)

        # 加上持仓的当前价值
        positions = state.get('positions', {})
        pos_value = 0.0
        for ca, p in positions.items():
            ep = float(p.get('entry_price', 0) or 0)
            bal = float(p.get('balance', 0) or 0)
            pnl = float(p.get('pnl_pct', 0) or 0)
            remaining = 1.0 - float(p.get('sold_pct', 0))
            if ep > 0 and bal > 0:
                pos_value += p.get('entry_usd_amount', BUY_SIZE_USDT) * remaining * (1 + pnl)

        account_total = usdt_total + pos_value
        if account_total <= 0:
            return BUY_SIZE_USDT  # fallback

        effective_risk = get_effective_risk(state)
        risk_amount = account_total * effective_risk
        size = risk_amount / SL_PCT_BASE
        size = max(MIN_BUY_SIZE, min(MAX_BUY_SIZE, size))
        log(f'position_size: account=${account_total:.2f} -> buy=${size:.2f} (risk={effective_risk:.1%})')
        return round(size, 2)
    except Exception as e:
        log(f'calc_buy_size error: {e}')
        return BUY_SIZE_USDT


def check_risk_limits(state):
    """检查日/月亏损限制, 返回 (can_trade: bool, reason: str)"""
    now = int(time.time())
    today_start = int(time.mktime(time.strptime(time.strftime('%Y-%m-%d'), '%Y-%m-%d')))
    month_start = int(time.mktime(time.strptime(time.strftime('%Y-%m-01'), '%Y-%m-%d')))

    # 检查月暂停
    pause_until = state.get('pause_until', 0)
    if pause_until and now < pause_until:
        from datetime import datetime
        pu = datetime.fromtimestamp(pause_until).strftime('%m-%d %H:%M')
        return False, f'monthly pause until {pu}'

    # 已实现 PnL (trade_history)
    realized_daily = 0.0
    realized_monthly = 0.0
    for t in state.get('trade_history', []):
        exit_ts = t.get('exit_ts', 0)
        exit_usd = t.get('exit_usd', t.get('exit_usd_amount', 0))
        entry_usd = t.get('entry_usd_amount', BUY_SIZE_USDT)
        pnl_usd = exit_usd - entry_usd
        if exit_ts >= month_start:
            realized_monthly += pnl_usd
        if exit_ts >= today_start:
            realized_daily += pnl_usd

    # 未实现 PnL (当前持仓)
    unrealized_daily = 0.0
    unrealized_monthly = 0.0
    for ca, p in state.get('positions', {}).items():
        entry_ts = int(p.get('entry_ts', 0))
        entry_usd = float(p.get('entry_usd_amount', BUY_SIZE_USDT))
        pnl_pct = float(p.get('pnl_pct', 0) or 0)
        remaining = 1.0 - float(p.get('sold_pct', 0))
        unrealized_pnl = entry_usd * remaining * pnl_pct
        unrealized_monthly += unrealized_pnl
        if entry_ts >= today_start:
            unrealized_daily += unrealized_pnl

    # 估算账户总资金 (USDT + 持仓价值)
    try:
        sol_bal = get_balance('solana')
        bsc_bal = get_balance('bsc')
        usdt_total = sol_bal.get(USDT_SOL.lower(), 0) + sol_bal.get(USDT_SOL, 0)
        usdt_total += bsc_bal.get(USDT_BSC.lower(), 0)
    except:
        usdt_total = 50.0  # conservative fallback

    pos_value = sum(
        float(p.get('entry_usd_amount', BUY_SIZE_USDT)) * (1.0 - float(p.get('sold_pct', 0)))
        for p in state.get('positions', {}).values()
    )
    account_total = max(usdt_total + pos_value, 1.0)

    # 日亏损检查
    daily_pnl = realized_daily + unrealized_daily
    daily_pct = daily_pnl / account_total
    if daily_pct <= -MAX_DAILY_LOSS_PCT:
        log(f'RISK BLOCK: daily PnL {daily_pct:+.1%} <= -{MAX_DAILY_LOSS_PCT:.0%} limit')
        return False, f'daily loss {daily_pct:+.1%}'

    # 月亏损检查
    monthly_pnl = realized_monthly + unrealized_monthly
    monthly_pct = monthly_pnl / account_total
    if monthly_pct <= -MAX_MONTHLY_LOSS_PCT:
        from datetime import datetime, timedelta
        pause_until = int((datetime.now() + timedelta(days=7)).timestamp())
        state['pause_until'] = pause_until
        pu = datetime.fromtimestamp(pause_until).strftime('%m-%d %H:%M')
        log(f'RISK BLOCK: monthly PnL {monthly_pct:+.1%} <= -{MAX_MONTHLY_LOSS_PCT:.0%} -> pause until {pu}')
        save_state(state)
        return False, f'monthly loss {monthly_pct:+.1%}'

    return True, 'ok'


def log(msg):


    ts = datetime.now(timezone(timedelta(hours=8))).strftime('%H:%M:%S')


    line = f'[{ts}] {msg}'


    print(line)


    try:


        with open(LOG_FILE, 'a', encoding='utf-8') as f:


            f.write(line + '\n')


    except:


        pass





def parse_json(raw):


    m = re.search(r'\{.*\}', raw, re.DOTALL)


    if not m:


        return None


    try:


        return json.loads(m.group(0))


    except:


        return None





def load_state():


    try:


        with open(STATE_FILE, encoding='utf-8') as f:


            return json.load(f)


    except:


        return {'seen_txs': [], 'positions': {}, 'last_ts': 0, 'wallet_stats': {}}






def reload_positions_if_external_change(state):
    """If state file was modified externally (mtime changed), reload positions."""
    global _STATE_FILE_MTIME
    try:
        current_mtime = os.path.getmtime(STATE_FILE)
    except OSError:
        return  # file doesn't exist yet
    if _STATE_FILE_MTIME == 0:
        _STATE_FILE_MTIME = current_mtime
        return
    if current_mtime != _STATE_FILE_MTIME:
        try:
            with open(STATE_FILE, encoding='utf-8') as f:
                file_state = json.load(f)
            file_positions = file_state.get('positions', {})
            # Compare to detect actual external changes
            current_positions = state.get('positions', {})
            removed = set(current_positions.keys()) - set(file_positions.keys())
            added = set(file_positions.keys()) - set(current_positions.keys())
            if removed or added:
                log(f'[HOT-RELOAD] State file externally modified. '
                    f'Removed: {len(removed)}, Added: {len(added)}')
                state['positions'] = file_positions
                # Also sync trade_history if it changed
                if len(file_state.get('trade_history', [])) > len(state.get('trade_history', [])):
                    state['trade_history'] = file_state.get('trade_history', [])
            _STATE_FILE_MTIME = current_mtime
        except Exception as e:
            log(f'[HOT-RELOAD] Error reloading state: {e}')
        _STATE_FILE_MTIME = current_mtime

def process_commands(state):
    """Read and execute commands from external command file."""
    if not os.path.exists(CMD_FILE):
        return
    try:
        with open(CMD_FILE, 'r', encoding='utf-8') as f:
            commands = json.load(f)
        if not commands:
            return
    except Exception:
        return

    # Clear file immediately to prevent re-execution
    try:
        with open(CMD_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f)
    except Exception:
        pass

    positions = state.get('positions', {})

    for cmd in commands:
        action = cmd.get('action', '')
        log(f'[CMD] Processing: {action} {cmd.get("symbol", cmd.get("contract_address", "")[:16])}')

        if action == 'remove_position':
            ca = cmd.get('contract_address', '')
            reason = cmd.get('reason', 'external_command')
            if ca in positions:
                pos = positions[ca]
                exit_price = float(cmd.get('exit_price', pos.get('entry_price', 0)))
                entry_price = float(pos.get('entry_price', 0))
                pnl_pct = ((exit_price / entry_price) - 1) * 100 if entry_price > 0 else 0
                exit_usd = float(cmd.get('exit_usd', 0))
                _save_trade_history(state, pos, exit_price, pnl_pct, reason, exit_usd)
                del positions[ca]
                log(f'[CMD] Removed {pos.get("symbol", "?")} (PnL={pnl_pct:.1f}%)')
            else:
                log(f'[CMD] Position not found: {ca[:16]}...')

        elif action == 'update_position':
            ca = cmd.get('contract_address', '')
            updates = cmd.get('updates', {})
            if ca in positions:
                positions[ca].update(updates)
                log(f'[CMD] Updated {positions[ca].get("symbol", "?")}: {list(updates.keys())}')
            else:
                log(f'[CMD] Position not found: {ca[:16]}...')

        elif action == 'reload_state':
            try:
                with open(STATE_FILE, encoding='utf-8') as f:
                    file_state = json.load(f)
                state['positions'] = file_state.get('positions', {})
                state['trade_history'] = file_state.get('trade_history', state.get('trade_history', []))
                positions = state['positions']
                log(f'[CMD] State reloaded from file. Positions: {list(positions.keys())}')
            except Exception as e:
                log(f'[CMD] Reload failed: {e}')

        elif action == 'set_risk':
            # Override risk params at runtime
            global RISK_PCT, MAX_DAILY_LOSS_PCT
            if 'risk_pct' in cmd:
                RISK_PCT = float(cmd['risk_pct'])
                log(f'[CMD] RISK_PCT set to {RISK_PCT:.1%}')
            if 'daily_limit' in cmd:
                MAX_DAILY_LOSS_PCT = float(cmd['daily_limit'])
                log(f'[CMD] MAX_DAILY_LOSS_PCT set to {MAX_DAILY_LOSS_PCT:.1%}')

        else:
            log(f'[CMD] Unknown action: {action}')

    state['positions'] = positions

def _save_trade_history(state, pos, exit_price, exit_pnl_pct, reason, exit_usd=0.0):
    """Append closed position to trade_history."""
    entry_ts = int(pos.get('entry_ts', 0))
    now_ts = int(time.time())
    hold_hours = round((now_ts - entry_ts) / 3600, 2) if entry_ts else 0
    entry_price = float(pos.get('entry_price', 0) or 0)
    entry_usd = float(pos.get('entry_usd_amount', BUY_SIZE_USDT))
    record = {
        'symbol': pos.get('symbol', '?'),
        'chain': pos.get('chain', 'solana'),
        'entry_ts': entry_ts,
        'entry_price': entry_price,
        'entry_usd_amount': entry_usd,
        'entry_mcap': pos.get('entry_mcap', 0),
        'buy_tx': pos.get('buy_tx', ''),
        'exit_ts': now_ts,
        'exit_price': exit_price,
        'exit_pnl_pct': round(exit_pnl_pct, 6),
        'exit_usd': round(exit_usd, 4),
        'hold_hours': hold_hours,
        'reason': reason,
    }
    state.setdefault('trade_history', [])
    state['trade_history'].append(record)
    state['trade_history'] = state['trade_history'][-500:]
    sym = pos.get('symbol', '?')
    log(f'trade_history: {sym} closed pnl={exit_pnl_pct:+.1%} hold={hold_hours}h reason={reason}')


def save_state(state):


    os.makedirs(DATA, exist_ok=True)


    state.setdefault('trade_history', [])


    state.setdefault('seen_txs', [])
    state['seen_txs'] = state['seen_txs'][-1000:]


    tmp = STATE_FILE + '.tmp'


    with open(tmp, 'w', encoding='utf-8') as f:


        json.dump(state, f, indent=2, ensure_ascii=False)


    os.replace(tmp, STATE_FILE)  #





def load_wallets():


    try:


        with open(WALLET_FILE, encoding='utf-8') as f:


            return json.load(f)


    except:


        return {}





def save_wallets(wallets):


    os.makedirs(DATA, exist_ok=True)


    tmp = WALLET_FILE + '.tmp'


    with open(tmp, 'w', encoding='utf-8') as f:


        json.dump(wallets, f, indent=2, ensure_ascii=False)


    os.replace(tmp, WALLET_FILE)





def reconcile_wallet(state):


    """Scan wallet, align state with reality"""


    positions = state.get('positions', {})


    now_ts = int(time.time())


    # Migration: backfill missing fields for old positions
    for ca, pos in positions.items():
        if pos.get('entry_usd_amount') is None:
            pos['entry_usd_amount'] = BUY_SIZE_USDT
        if 'last_update_ts' not in pos:
            pos['last_update_ts'] = now_ts


    wallet_tokens = {}


    # Solana


    try:


        out, _ = oc_run(['onchainos', 'portfolio', 'all-balances', '--address', WALLET, '--chains', 'solana', '--chain', 'solana'])


        d = parse_json(out)


        if d:


            for t in d.get('data', [{}])[0].get('tokenAssets', []):


                bal = float(t.get('balance', 0))


                ca = t.get('tokenContractAddress', '')


                sym = t.get('symbol', '?')


                price = float(t.get('tokenPrice', 0) or 0)


                if bal > 0.01 and ca and sym not in ('USDT', 'USDC', 'SOL', 'wSOL'):


                    wallet_tokens[ca] = {'symbol': sym, 'balance': bal, 'price': price, 'chain': 'solana'}


    except Exception as e:


        log('reconcile: solana fail: ' + str(e))


    # BSC


    try:


        r = subprocess.run([os.path.expanduser('~\\AppData\\Roaming\\QClaw\\npm-global\\baw.cmd') if sys.platform == 'win32' else 'baw', 'wallet', 'balance', '--json'], capture_output=True, timeout=10, encoding='utf-8', errors='replace')


        if r.returncode == 0:


            bd = parse_json(r.stdout)


            if bd:


                items = bd if isinstance(bd, list) else bd.get('data', bd.get('tokens', []))


                for item in items:


                    addr = item.get('contractAddress', '') or item.get('address', '')


                    sym = item.get('symbol', '?')


                    bal = float(item.get('balance', 0) or 0)


                    if addr and addr != 'native' and bal > 0.01 and sym not in ('BNB', 'WBNB'):


                        wallet_tokens[addr] = {'symbol': sym, 'balance': bal, 'price': 0, 'chain': 'bsc'}


    except Exception as e:


        log('reconcile: bsc fail: ' + str(e))


    # Align


    #  BSC ()


    bsc_limit_orders = {}


    try:


        lo_out, _ = baw_run(['limit-order', 'list', '--binanceChainId', '56', '--status', 'WORKING', '--json'], timeout=15)


        lo_d = parse_baw_json(lo_out)


        if lo_d and lo_d.get('success'):


            for order in lo_d.get('data', {}).get('list', []):


                from_tok = order.get('fromToken', '').lower()


                if from_tok:


                    bsc_limit_orders[from_tok] = {


                        'strategyId': order.get('strategyId', ''),


                        'triggerPrice': order.get('triggerPrice', ''),


                        'status': order.get('status', ''),


                    }


    except:


        pass





    added, removed = 0, 0


    # Step 1: Add new tokens from wallet not in state


    for ca, info in wallet_tokens.items():


        value_usd = info['balance'] * info['price']


        if ca not in positions and value_usd >= DEAD_POSITION_USD:


            pos_data = {'symbol': info['symbol'], 'chain': info['chain'], 'entry_ts': now_ts, 'entry_mcap': 0, 'entry_price': info['price'], 'entry_usd_amount': BUY_SIZE_USDT, 'last_update_ts': now_ts, 'sm_buys': 0, 'sm_sells': 0, 'buy_tx': 'recovered', 'sold_pct': 0.0, 'ladder_step': 0, 'current_price': info['price'], 'pnl_pct': 0.0, 'recovered': True, 'entry_price_est': True}


            if info['chain'] == 'bsc':


                lo = bsc_limit_orders.get(ca.lower())


                if lo:


                    pos_data['limit_order_id'] = lo['strategyId']


                    pos_data['limit_order_ts'] = now_ts


                    log(f'reconcile: {info["symbol"]} ?{lo["strategyId"]} (TP=${lo["triggerPrice"]})')


            positions[ca] = pos_data


            added += 1


            log('reconcile: +' + info['symbol'] + ' recovered')


    # Step 2: Update balance + price for existing positions (preserve entry_price/entry_ts)


    for ca, info in wallet_tokens.items():


        if ca in positions:


            pos = positions[ca]


            old_balance = pos.get('balance', 0)


            pos['balance'] = info['balance']


            pos['current_price'] = info['price']


            if abs(old_balance - info['balance']) > 0.01:


                log(f'reconcile: {pos["symbol"]} balance {old_balance} ?{info["balance"]}')


    # Step 3: Remove positions no longer in wallet


    for ca in list(positions.keys()):


        if ca not in wallet_tokens:


            pos = positions[ca]


            log('reconcile: -' + pos.get('symbol', '?') + ' gone -> removed')


            removed += 1


            del positions[ca]


    state['positions'] = positions


    if added or removed:


        log('reconcile: +' + str(added) + ' -' + str(removed) + ' (total ' + str(len(positions)) + ')')


    return state


def oc_run(cmd, timeout=20):


    try:


        env = okx_env_for_subprocess() if okx_env_for_subprocess else None
        if not env:
            env = dict(os.environ)


        env['PYTHONIOENCODING'] = 'utf-8'


        r = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env,


                           encoding='utf-8', errors='replace')


        out = r.stdout or ''


        return out, r.returncode


    except Exception as e:


        return str(e), -1





def baw_run(args, timeout=30):


    """ BAW CLI ,?(stdout, returncode)"""


    try:


        r = subprocess.run([os.path.expanduser('~\\AppData\\Roaming\\QClaw\\npm-global\\baw.cmd') if sys.platform == 'win32' else 'baw'] + args, capture_output=True, timeout=timeout,


                           encoding='utf-8', errors='replace')


        return (r.stdout or '') + '\n' + (r.stderr or ''), r.returncode


    except Exception as e:


        return str(e), -1





def parse_baw_json(raw):


    """?BAW ?JSON"""


    m = re.search(r'\{.*\}', raw, re.DOTALL)


    if m:


        try:


            return json.loads(m.group())


        except:


            pass


    return None





# ===  ===


def update_wallet_stats(wallets, trades):


    now_ms = int(time.time() * 1000)


    cutoff_ms = now_ms - (WALLET_HISTORY_WINDOW * 1000)


    for t in trades:


        w = t.get('walletAddress', '')


        if not w:


            continue


        pnl = float(t.get('realizedPnlUsd', '0') or '0')


        tt = int(t.get('tradeType', 0))


        ts = int(t.get('tradeTime', '0') or '0')


        if w not in wallets:


            wallets[w] = {'wins': 0, 'losses': 0, 'total_pnl': 0, 'recent_trades': []}


        if tt == 2 and ts > cutoff_ms:


            if pnl > 0:


                wallets[w]['wins'] += 1


            elif pnl < 0:


                wallets[w]['losses'] += 1


            wallets[w]['total_pnl'] += pnl


        wallets[w]['recent_trades'].append({


            'ts': ts, 'type': tt, 'token': t.get('tokenContractAddress', ''), 'pnl': pnl


        })


        wallets[w]['recent_trades'] = wallets[w]['recent_trades'][-50:]


    return wallets





def get_wallet_winrate(wallets, addr):


    w = wallets.get(addr, {})


    wins = w.get('wins', 0)


    losses = w.get('losses', 0)


    total = wins + losses


    if total < 3:


        return None


    return wins / total





def is_good_wallet(wallets, addr):


    wr = get_wallet_winrate(wallets, addr)


    if wr is None:


        return True


    return wr >= MIN_WALLET_WINRATE





# ===  ===


def fetch_tracker():


    """Fetch recent smart money trades (solana + bsc)"""


    all_trades = []


    for ch in ['solana', 'bsc']:


        out, _ = oc_run([


            'onchainos', 'tracker', 'activities',


            '--tracker-type', 'smart_money',


            '--chain', ch,


            '--min-volume', str(MIN_VOLUME)


        ])


        d = parse_json(out)


        if d and d.get('ok'):


            all_trades.extend(d.get('data', {}).get('trades', []))


    return all_trades





# === BSC  ===


def get_balance_bsc():


    """BSC : ?baw wallet balance,?{contract_address: balance}"""


    out, _ = baw_run(['wallet', 'balance', '--json'], timeout=15)


    d = parse_baw_json(out)


    if not d or not d.get('success'):


        log(f'get_balance_bsc fail: {out[:100]}')


        return {}


    result = {}


    for item in d.get('data', {}).get('balances', []):


        bal = float(item.get('balance', 0) or 0)


        ca = item.get('contractAddress', '')


        if bal > 0 and ca:


            result[ca.lower()] = bal


    return result





def bsc_market_buy(token_ca, amount_usdt):


    """BSC """


    out, _ = baw_run([


        'market-order', 'swap',


        '--binanceChainId', '56',


        '--fromTokenQty', str(amount_usdt),


        '--fromToken', USDT_BSC,


        '--toToken', token_ca,


        '--slippage', '15',


        '--json'


    ], timeout=30)


    d = parse_baw_json(out)


    if d and d.get('success'):


        tx = d.get('data', {}).get('txHash', '')


        log(f'BAW BUY OK: tx={tx[:20]}...')


        return True, tx


    err = d.get('error', out[:100]) if d else out[:100]


    log(f'BAW BUY FAIL: {err}')


    return False, None





def bsc_market_sell(token_ca, token_balance):


    """BSC """


    out, _ = baw_run([


        'market-order', 'swap',


        '--binanceChainId', '56',


        '--fromTokenQty', str(token_balance),


        '--fromToken', token_ca,


        '--toToken', USDT_BSC,


        '--slippage', '20',


        '--json'


    ], timeout=30)


    d = parse_baw_json(out)


    if d and d.get('success'):


        tx = d.get('data', {}).get('txHash', '')


        log(f'BAW SELL OK: tx={tx[:20]}...')


        return True, tx


    err = d.get('error', out[:100]) if d else out[:100]


    log(f'BAW SELL FAIL: {err}')


    return False, None





def place_tp_limit_order(token_ca, token_balance, entry_price, sym):


    """BSC  TP """


    tp_price = entry_price * (1 + TP_PCT)


    out, _ = baw_run([


        'limit-order', 'sell',


        '--binanceChainId', '56',


        '--triggerPrice', f'${tp_price:.10f}',


        '--fromTokenQty', str(token_balance),


        '--fromToken', token_ca,


        '--toToken', USDT_BSC,


        '--slippage', '15',


        '--json'


    ], timeout=20)


    d = parse_baw_json(out)


    if d and d.get('success'):


        oid = d.get('data', {}).get('strategyId', '')


        log(f'TP LIMIT OK: {sym} ${tp_price:.8f} ({TP_PCT:+.0%}) id={oid}')


        return oid


    err = d.get('error', out[:100]) if d else out[:100]


    log(f'TP LIMIT FAIL: {sym} {err}')


    return None






def place_sl_limit_order(token_ca, token_balance, entry_price, sym):
    """BSC SL"""
    sl_price = entry_price * (1 + SL_PCT)
    out, _ = baw_run([
        'limit-order', 'sell',
        '--binanceChainId', '56',
        '--triggerPrice', f'${sl_price:.10f}',
        '--fromTokenQty', str(token_balance),
        '--fromToken', token_ca,
        '--toToken', USDT_BSC,
        '--slippage', '15',
        '--json'
    ], timeout=20)
    d = parse_baw_json(out)
    if d and d.get('success'):
        oid = d.get('data', {}).get('strategyId', '')
        log(f'SL LIMIT OK: {sym} ${sl_price:.8f} ({SL_PCT:+.0%}) id={oid}')
        return True, str(oid)
    else:
        log(f'SL LIMIT FAIL: {sym} {(out or "?")[:80]}')
        return False, ''

def cancel_limit_order(order_id, sym):


    """"""


    out, _ = baw_run([


        'limit-order', 'cancel',


        '--strategyId', str(order_id),


        '--json'


    ], timeout=15)


    d = parse_baw_json(out)


    if d and d.get('success'):


        log(f'CANCEL LIMIT OK: {sym} id={order_id}')


        return True


    log(f'CANCEL LIMIT FAIL: {sym} id={order_id} {out[:80]}')


    return False





def check_limit_order_status(order_id):


    """  status """


    out, _ = baw_run([


        'limit-order', 'list',


        '--strategyId', str(order_id),


        '--json'


    ], timeout=15)


    d = parse_baw_json(out)


    if d and d.get('success'):


        orders = d.get('data', {}).get('list', [])


        if orders:


            return orders[0].get('status', 'UNKNOWN')


    return 'UNKNOWN'





def check_bsc_limit_orders(positions):


    """ BSC  -  + """


    now_ts = int(time.time())


    for ca, pos in list(positions.items()):


        if pos.get('chain') != 'bsc':


            continue


        oid = pos.get('limit_order_id')


        if not oid:


            continue


        order_ts = int(pos.get('limit_order_ts', 0))


        sym = pos.get('symbol', '?')





        # ?

        status = check_limit_order_status(oid)


        if status == 'FINISHED':


            log(f'TP TRIGGERED: {sym} limit order filled')


            positions.pop(ca, None)


            continue


        if status in ('CANCELED', 'FAILED', 'EXPIRED'):


            log(f'TP GONE: {sym} limit order status={status}, closing position')


            positions.pop(ca, None)


            continue





        # ?

        elapsed = now_ts - order_ts


        if elapsed > LIMIT_ORDER_TIMEOUT:


            log(f'TP TIMEOUT: {sym} {elapsed}s?-> +?')


            cancel_limit_order(oid, sym)


            time.sleep(2)  #


            # ?

            bal_info = get_balance_bsc()


            token_bal = bal_info.get(ca.lower(), 0)


            if token_bal > 0:


                ok, _ = bsc_market_sell(ca, round(token_bal, 6))


                if ok:


                    positions.pop(ca, None)


                    pos['limit_order_id'] = None


            else:


                # ?


                log(f'TP TIMEOUT: {sym} bal=0, limit order filled or tokens moved, skip')


                positions.pop(ca, None)


    return positions





def get_balance(chain='solana'):


    """?  {contract_address: balance}"""


    if chain == 'bsc':


        return get_balance_bsc()


    out, _ = oc_run([


        'onchainos', 'portfolio', 'all-balances',


        '--address', WALLET, '--chains', chain, '--chain', chain


    ])


    d = parse_json(out)


    if not d or not d.get('ok'):


        return {}


    result = {}


    for asset in d.get('data', [{}])[0].get('tokenAssets', []):


        bal = float(asset.get('balance', 0))


        ca = asset.get('tokenContractAddress', '')


        if bal > 0 and ca:


            result[ca] = bal


    return result





def get_token_price_usd(chain, token_ca, retries=MAX_PRICE_RETRIES):


    """Fetch real-time price (onchainos token price-info)"""


    for attempt in range(retries + 1):


        out, _ = oc_run([


            'onchainos', 'token', 'price-info',


            '--chain', chain, '--address', token_ca


        ], timeout=10)


        d = parse_json(out)


        if d and d.get('ok'):


            for item in d.get('data', []):


                if item.get('tokenContractAddress', '').lower() == token_ca.lower():


                    price = float(item.get('price', 0))


                    if price > 0:


                        return price


        if attempt < retries:


            time.sleep(1 + attempt)  #


    return None





# ===  ===


def execute_buy(chain, token_ca, amount_usdt):


    """:BSC ?BAW,Solana ?onchainos"""


    if DRY_RUN:


        log(f'[DRY] BUY ${amount_usdt} -> {token_ca[:12]}...')


        return True, 'dry-tx'


    if chain == 'bsc':


        return bsc_market_buy(token_ca, amount_usdt)


    # Solana


    out, _ = oc_run([


        'onchainos', 'swap', 'execute',


        '--chain', chain,


        '--from', usdt_addr(chain),


        '--to', token_ca,


        '--readable-amount', str(round(amount_usdt, 6)),


        '--wallet', WALLET,


        '--slippage', '15'


    ], timeout=30)


    d = parse_json(out)


    if d and d.get('ok'):


        tx = d['data'].get('swapTxHash', '')


        log(f'BUY OK: tx={tx[:20]}...')


        return True, tx


    err = d.get('error', 'unknown') if d else out[:100]


    log(f'BUY FAIL: {err}')


    return False, None





def execute_sell(chain, token_ca, token_balance):


    """:BSC ?BAW ,Solana ?onchainos"""


    if DRY_RUN:


        log(f'[DRY] SELL {token_balance} {token_ca[:12]}...')


        return True, 'dry-tx'


    if chain == 'bsc':


        return bsc_market_sell(token_ca, round(token_balance, 6))


    # Solana


    out, _ = oc_run([


        'onchainos', 'swap', 'execute',


        '--chain', chain,


        '--from', token_ca,


        '--to', usdt_addr(chain),


        '--readable-amount', str(round(token_balance, 6)),


        '--wallet', WALLET,


        '--slippage', '20'


    ], timeout=30)


    d = parse_json(out)


    if d and d.get('ok'):


        tx = d['data'].get('swapTxHash', '')


        got = int(d['data'].get('toAmount', 0)) / 1e6


        log(f'SELL OK: tx={tx[:20]}... got=${got:.2f}')


        return True, tx


    err = d.get('error', 'unknown') if d else out[:100]


    log(f'SELL FAIL: {err}')


    return False, None





# ===  ===


def process_new_trades(trades, state, wallets):


    positions = state.get('positions', {})


    seen = set(state.get('seen_txs', []))


    wallets = update_wallet_stats(wallets, trades)





    new = [t for t in trades if t.get('txHash') and t['txHash'] not in seen]


    if not new:


        return positions





    for t in new:


        seen.add(t['txHash'])


    state['seen_txs'] = list(seen)





    activity = defaultdict(lambda: {'buys': 0, 'sells': 0, 'latest': None,


                                     'buy_wallets': set(), 'sell_wallets': set()})


    for t in new:


        ca = t.get('tokenContractAddress', '')


        tt = int(t.get('tradeType', 0))


        w = t.get('walletAddress', '')


        if tt == 1:


            activity[ca]['buys'] += 1


            if w:


                activity[ca]['buy_wallets'].add(w)


        else:


            activity[ca]['sells'] += 1


            if w:


                activity[ca]['sell_wallets'].add(w)


        activity[ca]['latest'] = t





    log(f'New trades: {len(new)} across {len(activity)} tokens')





    for ca, act in activity.items():


        lat = act['latest']


        sym = lat.get('tokenSymbol', '?')


        mcap = float(lat.get('marketCap', 0))


        chain_idx = str(lat.get('chainIndex', ''))


        chain_map = {'501': 'solana', '56': 'bsc'}


        chain = chain_map.get(chain_idx, 'unknown')





        # ? ?

        if ca in positions:


            if act['sells'] > 0:


                positions[ca]['sm_sells'] = positions[ca].get('sm_sells', 0) + act['sells']


                log(f'SM SELL on {sym}: total_sm_sells={positions[ca]["sm_sells"]}')


            continue





        # ?token ?

        if act['buys'] > 0:


            if mcap < MIN_MCAP:


                log(f'SKIP {sym}: mcap=${mcap:,.0f} < ${MIN_MCAP:,}')


                continue


            if len(positions) >= MAX_POSITIONS:


                log(f'SKIP {sym}: max positions ({MAX_POSITIONS})')


                continue


            if chain == 'unknown':


                log(f'SKIP {sym}: unsupported chain (idx={chain_idx})')


                continue


            good_wallets = [w for w in act['buy_wallets'] if is_good_wallet(wallets, w)]


            if not good_wallets and act['buy_wallets']:


                log(f'SKIP {sym}: all buy wallets low winrate ({len(act["buy_wallets"])})')


                continue





            good_buyers = len(good_wallets)


            if good_buyers < MIN_CONSENSUS_WALLETS:


                log(f'SKIP {sym}: consensus fail (good={good_buyers}, need>={MIN_CONSENSUS_WALLETS})')


                continue





            entry_price = get_token_price_usd(chain, ca)


            if not entry_price or entry_price <= 0:


                log(f'SKIP {sym}: cannot get price')


                continue





            # trend entry filter (low weight - smart money primary)
            trend_3m_entry = get_trend(ca, 180)
            if trend_3m_entry < -0.08:  # 3min >8%/min crash = skip
                log(f"SKIP {sym}: extreme dump (3min={trend_3m_entry:.1%}/min)")
                continue
            trend_tag = ''
            if trend_3m_entry != 0:
                trend_tag = f' trend={trend_3m_entry:+.1%}/min'
            log(f'SM BUY: {sym} (buyers={len(act["buy_wallets"])}/{good_buyers}good, mcap=${mcap:,.0f}{trend_tag})')


            # risk control check
            can_trade, risk_reason = check_risk_limits(state)
            if not can_trade:
                log(f'SKIP {sym}: risk blocked ({risk_reason})')
                continue

            dynamic_buy = calc_buy_size(state)

            # Shared dedup: check if BAW already bought this token
            if chain == 'bsc' and 'shared_is_bought' in dir():
                if shared_is_bought(ca):
                    log(f'SKIP {sym}: already bought by BAW (shared dedup)')
                    continue

            ok, tx = execute_buy(chain, ca, dynamic_buy)


            if ok:


                pos_data = {


                    'symbol': sym, 'chain': chain,


                    'entry_ts': int(time.time()),


                    'entry_mcap': mcap,


                    'entry_price': entry_price,


                    'entry_usd_amount': dynamic_buy,


                    'last_update_ts': int(time.time()),


                    'sm_buys': act['buys'], 'sm_sells': 0,


                    'buy_tx': tx,


                    'sold_pct': 0.0, 'ladder_step': 0,


                }


                # BSC:  TP ?

                if chain == 'bsc' and not DRY_RUN:


                    time.sleep(3)  #


                    bal = get_balance_bsc()


                    token_bal = bal.get(ca.lower(), 0)


                    if token_bal > 0:


                        oid = place_tp_limit_order(ca, token_bal, entry_price, sym)
                        sl_oid = place_sl_limit_order(ca, token_bal, entry_price, sym)


                        if oid:


                            pos_data['limit_order_id'] = oid


                            pos_data['limit_order_ts'] = int(time.time())


                        else:


                            log(f'WARN: {sym} TP limit order failed, position unprotected')


                positions[ca] = pos_data


    return positions








def check_positions(positions):


    """docstring"""

    if not positions:


        return positions





    # BSC (+)


    positions = check_bsc_limit_orders(positions)


    if not positions:


        return positions





    to_sell_all = []


    to_sell_partial = []


    to_remove = []  # FIX: ?

    now_ts = int(time.time())





    for ca, pos in list(positions.items()):


        chain = pos.get('chain', 'solana')


        sym = pos.get('symbol', '?')


        entry_price = float(pos.get('entry_price', 0) or 0)


        ladder_step = int(pos.get('ladder_step', 0))


        entry_ts = int(pos.get('entry_ts', now_ts))


        hold_hours = (now_ts - entry_ts) / 3600





        if entry_price <= 0:


            continue





        current_price = get_token_price_usd(chain, ca)





        pos['last_update_ts'] = now_ts

        # FIX: ?

        if not current_price:


            if hold_hours > POSITION_STALE_HOURS:


                log(f'DEAD: {sym} {hold_hours:.0f}h  -> ')


                to_remove.append(ca)


            else:


                log(f'WARN: {sym} price query failed, skipping')


            continue





        pnl = (current_price - entry_price) / entry_price


        pos['current_price'] = current_price


        pos['pnl_pct'] = pnl





        #


        record_price(ca, current_price)





        # FIX: ???

        # ?=   (1 + pnl)


        position_value = BUY_SIZE_USDT * (1.0 - float(pos.get('sold_pct', 0))) * (1 + pnl)


        if position_value < DEAD_POSITION_USD and hold_hours > 1:


            log(f'DEAD: {sym} ?${position_value:.2f} < ${DEAD_POSITION_USD} -> ')


            to_remove.append(ca)


            continue





        # ?

        if pos.get('sm_sells', 0) >= SM_SELL_FOLLOW:


            log(f'SM FOLLOW SELL: {sym} (sm_sells={pos["sm_sells"]})')


            to_sell_all.append((ca, 'sm_follow'))


            continue





        #


        dynamic_sl = SL_PCT


        triggered = False


        is_recovered = pos.get('entry_price_est', False)





        #  + (,entry_price )


        if not is_recovered:


            for tier_hours, tier_sl, tier_tp, sell_pct, label in TIME_TIERS:


                if hold_hours < tier_hours:


                    break


                dynamic_sl = tier_sl


                if tier_tp is None:


                    log(f'{label}: {sym}  {hold_hours:.1f}h ->  ?')


                    to_sell_all.append((ca, label))


                    triggered = True


                    break


                elif pnl >= tier_tp:


                    if sell_pct >= 1.0:


                        log(f'{label}: {sym} {hold_hours:.1f}h PnL={pnl:.1%} -> ')


                        to_sell_all.append((ca, label))


                    else:


                        log(f'{label}: {sym} {hold_hours:.1f}h PnL={pnl:.1%} -> {sell_pct:.0%}')


                        to_sell_partial.append((ca, sell_pct, label))


                    triggered = True


                    break


        if triggered:


            continue





        #


        trend_3m = get_trend(ca, 180)   # %/min ?


        trend_15m = get_trend(ca, 900)  # %/min ?5


        trend_adj = 0.0


        if trend_15m < -0.02:   # 15min >2%/min


            trend_adj += 0.02   # 2%


            log(f'TREND: {sym} 15min{trend_15m:.1%}/min -> SL+2%')


        if trend_3m < -0.05:    # 3min >5%/min


            trend_adj += 0.03   # 3%


            log(f'TREND: {sym} 3min{trend_3m:.1%}/min -> SL+3%')


        if trend_3m > 0.03 and trend_15m > 0.01:  #


            trend_adj -= 0.01   # 1%





        effective_sl = dynamic_sl + trend_adj  # ??

        if pnl <= effective_sl:


            sl_label = f'({effective_sl:.0%})' if effective_sl != SL_PCT else ''


            trend_info = f' trend3m={trend_3m:.1%}/min 15m={trend_15m:.1%}/min'


            log(f'{sl_label}: {sym} {hold_hours:.1f}h PnL={pnl:.1%}{trend_info} -> ')


            to_sell_all.append((ca, 'stop_loss'))


            continue





        # ()


        if not is_recovered and ladder_step < len(LADDER_TP):


            step = LADDER_TP[ladder_step]


            if pnl >= step['threshold']:


                ratio = LADDER_RATIOS[ladder_step] if ladder_step < len(LADDER_RATIOS) else 0


                log(f'{step["label"]}: {sym} PnL={pnl:.1%} -> {ratio:.0%}')


                to_sell_partial.append((ca, ratio, step['label']))





    # FIX: (,???gas?

    for ca in to_remove:


        pos = positions.pop(ca, {})


        sym = pos.get('symbol', '?')


        exit_price = float(pos.get('current_price', pos.get('entry_price', 0)))


        ep = float(pos.get('entry_price', 0) or 0)


        exit_pnl = (exit_price - ep) / ep if ep > 0 else 0


        _save_trade_history(state, pos, exit_price, exit_pnl, 'dead_position')


        log(f'? {sym} (?')





    #


    for ca, reason in to_sell_all:


        pos = positions.get(ca, {})


        chain = pos.get('chain', 'solana')


        sym = pos.get('symbol', '?')


        # BSC:


        if chain == 'bsc' and not DRY_RUN:


            oid = pos.get('limit_order_id')


            if oid:


                cancel_limit_order(oid, sym)


                pos['limit_order_id'] = None


        if DRY_RUN:


            entry_price = float(pos.get('entry_price', 0) or 0)


            remaining = 1.0 - float(pos.get('sold_pct', 0))


            token_bal = (BUY_SIZE_USDT * remaining) / entry_price if entry_price > 0 else 0


        else:


            bal_info = get_balance(chain)


            token_bal = bal_info.get(ca, 0)


        if token_bal > 0:


            ok, _ = execute_sell(chain, ca, round(token_bal, 6))


            if ok:


                exit_price = float(pos.get('current_price', pos.get('entry_price', 0)))


                ep = float(pos.get('entry_price', 0) or 0)


                exit_pnl = (exit_price - ep) / ep if ep > 0 else 0


                exit_usd = token_bal * exit_price


                _save_trade_history(state, pos, exit_price, exit_pnl, reason, exit_usd)


                del positions[ca]





    # ?

    for ca, ratio, label in to_sell_partial:


        pos = positions.get(ca, {})


        chain = pos.get('chain', 'solana')


        sym = pos.get('symbol', '?')


        sold_pct = float(pos.get('sold_pct', 0))


        remaining = 1.0 - sold_pct


        sell_pct = remaining * ratio





        # BSC: ?

        if chain == 'bsc' and not DRY_RUN:


            oid = pos.get('limit_order_id')


            if oid:


                cancel_limit_order(oid, sym)


                pos['limit_order_id'] = None





        if DRY_RUN:


            entry_price = float(pos.get('entry_price', 0) or 0)


            token_remaining = (BUY_SIZE_USDT * remaining) / entry_price if entry_price > 0 else 0


            sell_amount = token_remaining * ratio


        else:


            bal_info = get_balance(chain)


            token_remaining = bal_info.get(ca, 0)


            sell_amount = token_remaining * ratio





        if sell_amount > 0:


            ok, _ = execute_sell(chain, ca, round(sell_amount, 6))


            if ok:


                pos['sold_pct'] = sold_pct + sell_pct


                pos['ladder_step'] = pos.get('ladder_step', 0) + 1


                new_remaining = 1.0 - pos['sold_pct']


                log(f'{label} done: {sym} ={pos["sold_pct"]:.0%} ={new_remaining:.0%}')


                if new_remaining <= 0.05:


                    exit_price = float(pos.get('current_price', pos.get('entry_price', 0)))


                    ep = float(pos.get('entry_price', 0) or 0)


                    exit_pnl = (exit_price - ep) / ep if ep > 0 else 0


                    remaining_bal = (BUY_SIZE_USDT * new_remaining) / ep if ep > 0 else 0


                    exit_usd = remaining_bal * exit_price


                    _save_trade_history(state, pos, exit_price, exit_pnl, f'{label}_dust', exit_usd)


                    del positions[ca]


                # BSC:  TP ?

                elif chain == 'bsc' and not DRY_RUN:


                    time.sleep(2)


                    bal2 = get_balance_bsc()


                    remain_bal = bal2.get(ca.lower(), 0)


                    current_price = pos.get('current_price', pos.get('entry_price', 0))


                    if remain_bal > 0 and current_price > 0:


                        oid = place_tp_limit_order(ca, remain_bal, current_price, sym)


                        if oid:


                            pos['limit_order_id'] = oid


                            pos['limit_order_ts'] = int(time.time())





    return positions








def run_once(state, wallets):


    reload_positions_if_external_change(state)
    positions = state.get("positions", {})  # refresh after hot-reload
    process_commands(state)
    save_state(state)  # persist command results immediately (cmd file already cleared)
    positions = state.get("positions", {})  # refresh after commands

    trades = fetch_tracker()


    positions = state.get('positions', {})





    if trades:


        positions = process_new_trades(trades, state, wallets)





    positions = check_positions(positions)


    state['positions'] = positions


    state['last_poll'] = int(time.time())


    save_state(state)


    save_wallets(wallets)


    save_trends()  # ?




    # risk summary
    can_trade, reason = check_risk_limits(state)
    risk_status = 'OK' if can_trade else f'BLOCKED({reason})'
    log(f'Risk status: {risk_status}')

    if positions:

        log(f'Open: {len(positions)}')


        for ca, p in positions.items():


            pnl = p.get('pnl_pct', 0)


            entry_ts = int(p.get('entry_ts', 0))


            hold_h = (int(time.time()) - entry_ts) / 3600 if entry_ts else 0


            is_est = p.get('entry_price_est', False)


            prefix = '~' if is_est else ''


            log(f'  {p.get("symbol","?")}: PnL={prefix}{pnl:+.1%} ={hold_h:.1f}h SM_sells={p.get("sm_sells",0)}')


    else:


        log(f'No positions (wallets tracked: {len(wallets)})')


    return positions








def main():


    mode = 'DRY-RUN' if DRY_RUN else 'LIVE'


    log(f'=== SM Monitor v3.3 [{mode}] ===')
    log(f'Risk: per-trade={RISK_PCT:.0%} of account, SL={SL_PCT_BASE:.0%}, daily_limit={MAX_DAILY_LOSS_PCT:.0%}, monthly_limit={MAX_MONTHLY_LOSS_PCT:.0%}')
    log(f'Position: min=${MIN_BUY_SIZE}, max=${MAX_BUY_SIZE}')





    state = load_state()


    load_trends()  #


    state = reconcile_wallet(state)  # ?

    save_state(state)


    wallets = load_wallets()





    if ONCE:


        run_once(state, wallets)


        return





    try:


        # Initialize mtime tracking
        global _STATE_FILE_MTIME
        try:
            _STATE_FILE_MTIME = os.path.getmtime(STATE_FILE)
        except:
            _STATE_FILE_MTIME = 0

        while True:


            run_once(state, wallets)


            log(f'--- sleep {TRACKER_POLL_SEC}s ---')


            time.sleep(TRACKER_POLL_SEC)


    except KeyboardInterrupt:


        log('Stopped by user')


        save_state(state)


        save_wallets(wallets)





if __name__ == '__main__':


    main()


