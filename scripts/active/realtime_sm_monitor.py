"""

realtime_sm_monitor.py v3.3 REST signal monitor

OKX OnchainOS V6 REST signal/price API, with OnchainOS CLI fallback



: python realtime_sm_monitor.py [--once]



??scripts/simulation/sm_monitor_sim.py

"""



import sys
import json, sys, os, subprocess, re, time, math
import threading

from datetime import datetime, timezone, timedelta

from collections import defaultdict

# Auto-archive integration
import sys as _sys_a
_sys_a.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "archive"))
try:
    from data_archive_manager import auto_archive, on_sell_closed
    _ARCHIVE_OK = True
except ImportError:
    _ARCHIVE_OK = False



sys.stdout.reconfigure(encoding='utf-8')

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_WS_CLIENT = None  # Kept for compatibility; REST is the active primary source.
_REST_CLIENT = None  # Direct OKX OnchainOS DEX REST V6 client.
_price_cache = {}  # {token_ca_lower: (price_float, timestamp)}
_ws_sl_lock = None  # threading.Lock — WS instant SL thread safety (init in main)
_ws_last_restart = 0  # throttle WS restart attempts
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
from okx_dex_ws import OkxDexWs
from okx_dex_rest import OkxDexRest

try:
    from qclaw_trading_common import (  # noqa: E402
        okx_env_for_subprocess,
        locked_read_json,
        locked_write_json,
        workspace_root,
    )
except ImportError:
    okx_env_for_subprocess = None  # type: ignore
    locked_read_json = None  # type: ignore
    locked_write_json = None  # type: ignore

    def workspace_root(anchor_file=None):  # type: ignore
        return os.path.abspath(os.path.join(os.path.dirname(anchor_file), "..", ".."))

# Safety check module (honeypot/tax/liquidity pre-buy check)
try:
    from safety_check import check_token, format_safety_report
    _HAS_SAFETY = True
except ImportError:
    _HAS_SAFETY = False

# ===  ===

BASE = workspace_root(__file__)

DATA = os.path.join(BASE, 'data')

BAW_CMD = os.path.expanduser(os.path.join('~', 'AppData', 'Roaming', 'QClaw', 'npm-global', 'baw.cmd')) if sys.platform == 'win32' else 'baw'
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
    if chain == 'bsc':
        return USDT_BSC
    if chain == 'robinhood':
        return ''
    return USDT_SOL



# Parse command line arguments
import sys as _sys_arg
DRY_RUN = True  # default: dry-run
if '--live' in _sys_arg.argv:
    DRY_RUN = False
    _sys_arg.argv.remove('--live')
if '--dry-run' in _sys_arg.argv:
    DRY_RUN = True
    _sys_arg.argv.remove('--dry-run')
del _sys_arg


def _env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


# BSC market data is already supplied by OKX DEX V6 REST.  Keep the legacy
# BAW wallet/order integration paused unless explicitly enabled for a future
# live-execution test.  DRY-RUN never needs BAW at all.
BSC_BAW_ENABLED = _env_flag('BSC_BAW_ENABLED', False)

STATE_FILE = os.path.join(DATA, 'sm_monitor_state_dryrun.json' if DRY_RUN else 'sm_monitor_state.json')
CMD_FILE = os.path.join(DATA, 'sm_commands.json')
CONFIG_FILE = os.path.join(DATA, 'sm_runtime_config.json')


LOG_FILE = os.path.join(DATA, 'sm_trade-log_dryrun.txt' if DRY_RUN else 'sm_trade-log.txt')
# Keep the dashboard status separate from legacy monitor runtime/control files.
# Some local supervisors treat runtime/dryrun filenames as their own control
# files and terminate the monitor after it writes a heartbeat.
RUNTIME_FILE = os.path.join(DATA, 'dashboard_status.json')

WALLET_FILE = os.path.join(DATA, 'sm_wallets.json')

SHARED_DEDUP_FILE = os.path.join(DATA, 'shared_bought.json')
SHARED_DEDUP_TTL = 3600



MIN_MCAP = 30000

MIN_VOLUME = 500

#   Solana 👻
BLACKLIST_TOKENS = {'6SjVTj1VGwFSXn7wEjwFm77LvACeTqB7sQUebYKX8Ds5'}  # ROUTER 🐸

MAX_POSITIONS = 3

BUY_SIZE_USDT = 5          # 默认/兜底单笔金额

# === 头寸管理 & 风险控制 ===
RISK_PCT = 0.02            # 单笔风险系数 (账户总资金 x 1%)
SL_PCT_BASE = 0.08         # 基础止损幅度 (8%)
MAX_BUY_SIZE = 15.0
POST_BUY_DROP_THRESHOLD = 0.05        # 单笔最大买入 (USD)
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

MIN_SOL_BALANCE = 0.005     # Solana 最小 SOL 余额（支付 token account 租金）
BUY_FAIL_COOLDOWN = 300      # 买入失败后冷却 5 分钟
SELL_FAIL_MAX = 8            # 卖出最多重试 8 次后跳过
SELL_FAIL_BACKOFF_BASE = 5   # 卖出失败退避基数(秒)，指数递增

SM_SELL_FOLLOW = 3
CONSEC_SL_LIMIT = 3
CONSEC_SL_FREEZE_SEC = 7200

TRACKER_POLL_SEC = float(os.environ.get('SM_MONITOR_POLL_SEC', '10'))

MIN_WALLET_WINRATE = 0.50

MIN_CONSENSUS_WALLETS = 1

WALLET_HISTORY_WINDOW = 3600

DEAD_POSITION_USD = 0.50   # ?< $0.50

MAX_PRICE_RETRIES = int(os.environ.get('MAX_PRICE_RETRIES', '1'))
PRICE_QUERY_TIMEOUT_SEC = float(os.environ.get('PRICE_QUERY_TIMEOUT_SEC', '5'))
TRACKER_REST_TIMEOUT_SEC = float(os.environ.get('TRACKER_REST_TIMEOUT_SEC', '8'))

POSITION_STALE_HOURS = 72  # ?2h

MAX_HOLD_HOURS = float(os.environ.get('MAX_HOLD_HOURS', '2'))

# The intended strategy is fast follow-through: take the first defined profit
# and leave.  The older multi-tier plan remains available with
# FAST_EXIT_MODE=0 for controlled experiments/backtests.
FAST_EXIT_MODE = os.environ.get('FAST_EXIT_MODE', '1').strip().lower() not in ('0', 'false', 'no')
QUICK_TP_PCT = float(os.environ.get('QUICK_TP_PCT', '0.10'))
QUICK_TP_SELL_PCT = float(os.environ.get('QUICK_TP_SELL_PCT', '1.0'))
QUICK_TP_SELL_PCT = max(0.01, min(1.0, QUICK_TP_SELL_PCT))
SOLD_RATIO_TIMEOUT_SEC = float(os.environ.get('SOLD_RATIO_TIMEOUT_SEC', '2.0'))



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



LEGACY_TIME_TIERS = [

    # (hold_hours, SL PnL, TP PnL, sell_pct, label)
    # v34: softer tiers - sell less early, let winners run
    (0,   None, 0.10,  0.30, 'quick_tp'),   # +10% sell 30% (lock some profit)
    (6,   None, 0.30,  0.40, '6h_tp'),       # 6h +30% sell 40%
    (12,  -0.05, 0.15,  0.80, '12h_tp'),      # 12h: SL -5%, TP +15% sell 80%
    (24,  -0.03, 0.05,  1.00, '24h_exit'),    # 24h: SL -3%, TP +5% sell all
    (48,   0.00, None,  1.00, '48h_force'),    # 48h: force exit
]

TIME_TIERS = (
    [(0, None, QUICK_TP_PCT, QUICK_TP_SELL_PCT, 'quick_tp')]
    if FAST_EXIT_MODE else LEGACY_TIME_TIERS
)


# Runtime-editable strategy controls.  Values are stored as ratios for
# percentages (for example, 0.02 means 2%) and are validated before changing
# the live process globals.
RUNTIME_CONFIG_LIMITS = {
    'min_mcap': (1000, 1_000_000_000),
    'max_positions': (1, 50),
    'min_consensus_wallets': (1, 100),
    'min_wallet_winrate': (0.0, 1.0),
    'buy_size_usdt': (0.10, 10_000.0),
    'min_buy_size': (0.10, 10_000.0),
    'max_buy_size': (0.10, 10_000.0),
    'risk_pct': (0.001, 0.10),
    'stop_loss_pct': (0.005, 0.50),
    'daily_loss_limit_pct': (0.01, 1.0),
    'monthly_loss_limit_pct': (0.01, 1.0),
    'quick_tp_pct': (0.001, 10.0),
    'quick_tp_sell_pct': (0.01, 1.0),
    'max_hold_hours': (0.1, 720.0),
    'poll_sec': (1.0, 300.0),
}

CHAIN_NAMES = ('solana', 'bsc', 'robinhood')
CHAIN_INDEXES = {'solana': '501', 'bsc': '56', 'robinhood': '4663'}
CHAIN_LABELS = {'solana': 'Solana', 'bsc': 'BSC', 'robinhood': 'Robinhood'}
REST_CHAIN_INDEXES = tuple(CHAIN_INDEXES.values())
CHAIN_CONFIG_KEYS = {
    'min_mcap', 'max_positions', 'min_consensus_wallets', 'min_wallet_winrate',
    'buy_size_usdt', 'min_buy_size', 'max_buy_size', 'risk_pct',
    'stop_loss_pct', 'quick_tp_pct', 'quick_tp_sell_pct', 'max_hold_hours',
    'fast_exit_mode',
}
CHAIN_CONFIG_LIMITS = {
    key: RUNTIME_CONFIG_LIMITS[key]
    for key in CHAIN_CONFIG_KEYS
    if key in RUNTIME_CONFIG_LIMITS
}


def _default_chain_config():
    return {
        'min_mcap': int(MIN_MCAP),
        'max_positions': int(MAX_POSITIONS),
        'min_consensus_wallets': int(MIN_CONSENSUS_WALLETS),
        'min_wallet_winrate': float(MIN_WALLET_WINRATE),
        'buy_size_usdt': float(BUY_SIZE_USDT),
        'min_buy_size': float(MIN_BUY_SIZE),
        'max_buy_size': float(MAX_BUY_SIZE),
        'risk_pct': float(RISK_PCT),
        'stop_loss_pct': abs(float(SL_PCT)),
        'quick_tp_pct': float(QUICK_TP_PCT),
        'quick_tp_sell_pct': float(QUICK_TP_SELL_PCT),
        'max_hold_hours': float(MAX_HOLD_HOURS),
        'fast_exit_mode': bool(FAST_EXIT_MODE),
    }


CHAIN_CONFIGS = {chain: _default_chain_config() for chain in CHAIN_NAMES}


def get_chain_config(chain):
    name = str(chain or '').strip().lower()
    return CHAIN_CONFIGS.get(name, _default_chain_config())


def _time_tiers_for_config(config):
    if config.get('fast_exit_mode', FAST_EXIT_MODE):
        return [(0, None, config['quick_tp_pct'], config['quick_tp_sell_pct'], 'quick_tp')]
    return LEGACY_TIME_TIERS


def runtime_config_snapshot():
    """Return the effective controls in a JSON/dashboard-friendly shape."""
    return {
        'min_mcap': int(MIN_MCAP),
        'max_positions': int(MAX_POSITIONS),
        'min_consensus_wallets': int(MIN_CONSENSUS_WALLETS),
        'min_wallet_winrate': float(MIN_WALLET_WINRATE),
        'buy_size_usdt': float(BUY_SIZE_USDT),
        'min_buy_size': float(MIN_BUY_SIZE),
        'max_buy_size': float(MAX_BUY_SIZE),
        'risk_pct': float(RISK_PCT),
        'stop_loss_pct': abs(float(SL_PCT)),
        'daily_loss_limit_pct': float(MAX_DAILY_LOSS_PCT),
        'monthly_loss_limit_pct': float(MAX_MONTHLY_LOSS_PCT),
        'quick_tp_pct': float(QUICK_TP_PCT),
        'quick_tp_sell_pct': float(QUICK_TP_SELL_PCT),
        'max_hold_hours': float(MAX_HOLD_HOURS),
        'poll_sec': float(TRACKER_POLL_SEC),
        'fast_exit_mode': bool(FAST_EXIT_MODE),
        'bsc_baw_enabled': bool(BSC_BAW_ENABLED),
        'chains': {chain: dict(get_chain_config(chain)) for chain in CHAIN_NAMES},
    }


def _runtime_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ('1', 'true', 'yes', 'on'):
        return True
    if isinstance(value, str) and value.strip().lower() in ('0', 'false', 'no', 'off'):
        return False
    raise ValueError('fast_exit_mode must be a boolean')


def _normalize_runtime_updates(updates, limits=None):
    if not isinstance(updates, dict) or not updates:
        raise ValueError('updates must be a non-empty object')
    limits = limits or RUNTIME_CONFIG_LIMITS
    normalized = {}
    for key, value in updates.items():
        if key == 'fast_exit_mode':
            normalized[key] = _runtime_bool(value)
            continue
        if key not in limits:
            raise ValueError(f'unsupported config: {key}')
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f'{key} must be numeric')
        if not math.isfinite(number):
            raise ValueError(f'{key} must be finite')
        lower, upper = limits[key]
        if number < lower or number > upper:
            raise ValueError(f'{key} must be between {lower} and {upper}')
        if key in ('min_mcap', 'max_positions', 'min_consensus_wallets'):
            if not number.is_integer():
                raise ValueError(f'{key} must be an integer')
            normalized[key] = int(number)
        else:
            normalized[key] = number
    return normalized


def _write_runtime_config(snapshot):
    os.makedirs(DATA, exist_ok=True)
    editable = set(RUNTIME_CONFIG_LIMITS) | {'fast_exit_mode'}
    payload = {
        'updated_ts': time.time(),
        'values': {key: snapshot[key] for key in editable if key in snapshot},
        'chains': snapshot.get('chains', {}),
    }
    tmp_path = CONFIG_FILE + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(tmp_path, CONFIG_FILE)


def apply_runtime_config(updates, persist=True):
    """Validate and apply dashboard controls without restarting the monitor."""
    global MIN_MCAP, MAX_POSITIONS, MIN_CONSENSUS_WALLETS
    global MIN_WALLET_WINRATE, BUY_SIZE_USDT, MIN_BUY_SIZE, MAX_BUY_SIZE
    global RISK_PCT, BASE_RISK_PCT, SL_PCT_BASE, SL_PCT
    global MAX_DAILY_LOSS_PCT, MAX_MONTHLY_LOSS_PCT, QUICK_TP_PCT
    global QUICK_TP_SELL_PCT, MAX_HOLD_HOURS, TRACKER_POLL_SEC
    global FAST_EXIT_MODE, TIME_TIERS

    normalized = _normalize_runtime_updates(updates)
    candidate = runtime_config_snapshot()
    candidate.update(normalized)
    if candidate['min_buy_size'] > candidate['max_buy_size']:
        raise ValueError('min_buy_size cannot exceed max_buy_size')
    if not candidate['min_buy_size'] <= candidate['buy_size_usdt'] <= candidate['max_buy_size']:
        raise ValueError('buy_size_usdt must be between min_buy_size and max_buy_size')

    MIN_MCAP = int(candidate['min_mcap'])
    MAX_POSITIONS = int(candidate['max_positions'])
    MIN_CONSENSUS_WALLETS = int(candidate['min_consensus_wallets'])
    MIN_WALLET_WINRATE = float(candidate['min_wallet_winrate'])
    BUY_SIZE_USDT = float(candidate['buy_size_usdt'])
    MIN_BUY_SIZE = float(candidate['min_buy_size'])
    MAX_BUY_SIZE = float(candidate['max_buy_size'])
    RISK_PCT = float(candidate['risk_pct'])
    BASE_RISK_PCT = RISK_PCT
    SL_PCT_BASE = float(candidate['stop_loss_pct'])
    SL_PCT = -SL_PCT_BASE
    MAX_DAILY_LOSS_PCT = float(candidate['daily_loss_limit_pct'])
    MAX_MONTHLY_LOSS_PCT = float(candidate['monthly_loss_limit_pct'])
    QUICK_TP_PCT = float(candidate['quick_tp_pct'])
    QUICK_TP_SELL_PCT = float(candidate['quick_tp_sell_pct'])
    MAX_HOLD_HOURS = float(candidate['max_hold_hours'])
    TRACKER_POLL_SEC = float(candidate['poll_sec'])
    FAST_EXIT_MODE = bool(candidate['fast_exit_mode'])
    TIME_TIERS = (
        [(0, None, QUICK_TP_PCT, QUICK_TP_SELL_PCT, 'quick_tp')]
        if FAST_EXIT_MODE else LEGACY_TIME_TIERS
    )
    snapshot = runtime_config_snapshot()
    if persist:
        _write_runtime_config(snapshot)
    return snapshot


def apply_chain_config(chain, updates, persist=True):
    """Validate and apply one chain's entry/position/exit controls."""
    name = str(chain or '').strip().lower()
    if name not in CHAIN_NAMES:
        raise ValueError(f'unsupported chain: {chain}')
    normalized = _normalize_runtime_updates(updates, CHAIN_CONFIG_LIMITS)
    candidate = dict(get_chain_config(name))
    candidate.update(normalized)
    if candidate['min_buy_size'] > candidate['max_buy_size']:
        raise ValueError('min_buy_size cannot exceed max_buy_size')
    if not candidate['min_buy_size'] <= candidate['buy_size_usdt'] <= candidate['max_buy_size']:
        raise ValueError('buy_size_usdt must be between min_buy_size and max_buy_size')
    CHAIN_CONFIGS[name] = candidate
    if persist:
        _write_runtime_config(runtime_config_snapshot())
    return dict(candidate)


def load_runtime_config():
    """Load the last dashboard configuration, if one has been saved."""
    global CHAIN_CONFIGS
    if not os.path.exists(CONFIG_FILE):
        CHAIN_CONFIGS = {chain: _default_chain_config() for chain in CHAIN_NAMES}
        return runtime_config_snapshot()
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
        values = payload.get('values', payload) if isinstance(payload, dict) else {}
        apply_runtime_config(values, persist=False)
        stored_chains = payload.get('chains', {}) if isinstance(payload, dict) else {}
        CHAIN_CONFIGS = {chain: _default_chain_config() for chain in CHAIN_NAMES}
        if isinstance(stored_chains, dict):
            for chain, chain_values in stored_chains.items():
                if chain in CHAIN_NAMES and isinstance(chain_values, dict):
                    try:
                        apply_chain_config(chain, chain_values, persist=False)
                    except (TypeError, ValueError) as exc:
                        log(f'[CONFIG] ignored invalid {chain} config: {exc}')
        return runtime_config_snapshot()
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        log(f'[CONFIG] ignored invalid runtime config: {exc}')
        return runtime_config_snapshot()



# ===  ===

def get_effective_risk(state, base_risk=None):
    """Dynamic risk: reduce when daily loss accumulates"""
    from datetime import datetime
    today_start = int(time.mktime(time.strptime(time.strftime('%Y-%m-%d'), '%Y-%m-%d')))
    realized_daily = 0.0
    for t in state.get('trade_history', []):
        exit_ts = t.get('exit_ts') or 0
        exit_usd = t.get('exit_usd') or t.get('exit_usd_amount') or 0
        entry_usd = t.get('entry_usd_amount') or 0
        if not exit_ts or not exit_usd or not entry_usd:
            continue  # skip corrupted entries
        if exit_ts >= today_start:
            realized_daily += exit_usd - entry_usd
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
    base_risk = float(BASE_RISK_PCT if base_risk is None else base_risk)
    effective = base_risk
    for threshold, reduced in RISK_TIERS:
        if daily_pct <= -threshold:
            reduction_ratio = reduced / BASE_RISK_PCT if BASE_RISK_PCT > 0 else 1.0
            effective = min(effective, base_risk * reduction_ratio)
    if effective != base_risk:
        log(f'Dynamic risk: {base_risk:.1%} -> {effective:.1%} (daily PnL {daily_pct:+.1%})')
    return effective

def calc_buy_size(state, config=None):
    """动态仓位: risk_amount / |SL%| = (total x RISK_PCT) / SL_PCT_BASE"""
    config = config or runtime_config_snapshot()
    try:
        # 获取账户总资产和 USDT 余额（从 onchainos totalValueUsd 取最可靠）
        sol_out, sol_code = oc_run(['onchainos', 'wallet', 'balance', '--chain', 'solana'], timeout=20)
        usdt_total = 0
        if sol_code == 0 and sol_out:
            d = parse_json(sol_out)
            if d and d.get('ok'):
                account_total = float(d.get('data', {}).get('totalValueUsd', 0))
                # Extract USDT balance from tokenAssets
                for detail in d.get('data', {}).get('details', []):
                    for ta in detail.get('tokenAssets', []):
                        if str(ta.get('chainIndex', '')) != '501': continue
                        bal = float(ta.get('balance', 0) or 0)
                        addr = ta.get('tokenAddress', '')
                        if addr == USDT_SOL and bal > 0:
                            usdt_total = bal
                            break
                    if usdt_total > 0: break
            else:
                account_total = 0
        else:
            account_total = 0

        if account_total <= 0:
            # Fallback to old method
            sol_bal = get_balance('solana')
            bsc_bal = get_balance('bsc')
            usdt_total = sol_bal.get(USDT_SOL.lower(), 0) + sol_bal.get(USDT_SOL, 0)
            usdt_total += bsc_bal.get(USDT_BSC.lower(), 0)
            # 加上持仓的当前价值
            account_total = usdt_total
            positions = state.get('positions', {})
            for ca, p in positions.items():
                ep = float(p.get('entry_price', 0) or 0)
                bal = float(p.get('balance', 0) or 0)
                pnl = float(p.get('pnl_pct', 0) or 0)
                remaining = 1.0 - float(p.get('sold_pct', 0))
                eusd = float(p.get('entry_usd_amount', 0) or 0)
                if eusd > 0:
                    account_total += eusd * remaining * (1 + pnl)
                elif ep > 0 and bal > 0:
                    account_total += p.get('entry_usd_amount', BUY_SIZE_USDT) * remaining * (1 + pnl)
        if account_total <= 0:
            return config['buy_size_usdt']  # fallback

        effective_risk = get_effective_risk(state, config['risk_pct'])
        risk_amount = account_total * effective_risk
        size = risk_amount / config['stop_loss_pct']
        size = max(config['min_buy_size'], min(config['max_buy_size'], size))
        # 不能超过可用 USDT 余额（留 5% gas buffer）
        affordable = usdt_total * 0.95 if usdt_total > 0 else 0
        if size > affordable and affordable >= 1.0:
            size = round(affordable, 2)
        elif size > affordable:
            size = round(usdt_total, 2) if usdt_total > 0 else config['min_buy_size']
        log(f'position_size: account=${account_total:.2f} -> buy=${size:.2f} (risk={effective_risk:.1%}, usdt=${usdt_total:.2f})')
        return round(size, 2)
    except Exception as e:
        log(f'calc_buy_size error: {e}')
        return config['buy_size_usdt']

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
    # Consecutive SL freeze check
    consec_sl = state.get('consec_sl', 0)
    freeze_until = state.get('consec_sl_freeze_until', 0)
    if freeze_until and now < freeze_until:
        from datetime import datetime
        fu = datetime.fromtimestamp(freeze_until).strftime('%m-%d %H:%M')
        return False, f'consec SL freeze until {fu}'


    # 已实现 PnL (trade_history)
    realized_daily = 0.0
    realized_monthly = 0.0
    for t in state.get('trade_history', []):
        exit_ts = t.get('exit_ts') or 0
        exit_usd = t.get('exit_usd') or t.get('exit_usd_amount') or 0
        entry_usd = t.get('entry_usd_amount') or 0
        if not exit_ts or not exit_usd or not entry_usd:
            continue  # skip corrupted entries
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

    # 估算账户总资金 (取 onchainos totalValueUsd + 持仓)
    try:
        sol_out, sol_code = oc_run(['onchainos', 'wallet', 'balance', '--chain', 'solana'], timeout=20)
        if sol_code == 0 and sol_out:
            d = parse_json(sol_out)
            if d and d.get('ok'):
                account_total = float(d.get('data', {}).get('totalValueUsd', 0))
            else:
                account_total = 0
        else:
            account_total = 0
    except:
        account_total = 0

    if account_total <= 0:
        # Fallback
        try:
            sol_bal = get_balance('solana')
            bsc_bal = get_balance('bsc')
            usdt_total = sol_bal.get(USDT_SOL.lower(), 0) + sol_bal.get(USDT_SOL, 0)
            usdt_total += bsc_bal.get(USDT_BSC.lower(), 0)
        except:
            usdt_total = 50.0
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

    ts = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
    _rotate_log_if_needed()

    line = f'[{ts}] {msg}'

    print(line)

    try:

        with open(LOG_FILE, 'a', encoding='utf-8') as f:

            f.write(line + '\n')

    except:

        pass


def write_runtime_status(status, state=None, note=''):
    """Publish a small read-only heartbeat for the local dashboard."""
    ws_client = _WS_CLIENT
    rest_client = _REST_CLIENT
    try:
        rest_status = rest_client.status() if rest_client else {}
    except Exception:
        rest_status = {}
    ready_attr = (
        getattr(ws_client, 'is_feed_ready', getattr(ws_client, 'is_ready', False))
        if ws_client else False
    )
    try:
        ws_ready = ready_attr() if callable(ready_attr) else bool(ready_attr)
    except Exception:
        ws_ready = False
    auth_attr = (
        getattr(ws_client, 'is_authenticated', getattr(ws_client, 'is_ready', False))
        if ws_client else False
    )
    try:
        ws_authenticated = auth_attr() if callable(auth_attr) else bool(auth_attr)
    except Exception:
        ws_authenticated = False
    try:
        ws_alive = bool(ws_client and ws_client.is_alive()) if ws_client else False
    except Exception:
        ws_alive = False
    payload = {
        'pid': os.getpid(),
        'mode': 'DRY-RUN' if DRY_RUN else 'LIVE',
        'dry_run': DRY_RUN,
        'status': status,
        'note': note,
        'updated_ts': time.time(),
        'updated_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'ws_ready': ws_ready,
        'ws_authenticated': ws_authenticated,
        'ws_alive': ws_alive,
        'ws_feed_status': getattr(ws_client, 'feed_status', '') if ws_client else '',
        'ws_subscribed_channels': getattr(ws_client, 'subscribed_channels', []) if ws_client else [],
        'ws_subscription_errors': getattr(ws_client, 'subscription_errors', []) if ws_client else [],
        'rest_primary': bool(rest_client and getattr(rest_client, 'enabled', False)),
        'rest_mode': rest_status.get('mode', ''),
        'rest_last_signal_ok': rest_status.get('last_signal_ok'),
        'rest_last_signal_error': rest_status.get('last_signal_error', ''),
        'rest_last_signal_count': rest_status.get('last_signal_count', 0),
        'rest_last_signal_raw_count': rest_status.get('last_signal_raw_count', 0),
        'rest_last_signal_counts_by_chain': rest_status.get('last_signal_counts_by_chain', {}),
        'rest_last_signal_raw_counts_by_chain': rest_status.get('last_signal_raw_counts_by_chain', {}),
        'rest_last_price_ok': rest_status.get('last_price_ok'),
        'rest_last_price_error': rest_status.get('last_price_error', ''),
        'rest_last_price_count': rest_status.get('last_price_count', 0),
        'rest_last_price_counts_by_chain': rest_status.get('last_price_counts_by_chain', {}),
        'rest_request_count': rest_status.get('request_count', 0),
        'rest_last_request_ts': rest_status.get('last_request_ts', 0),
        'rest_chain_indexes': rest_status.get('chain_indexes', []),
        'bsc_market_data_source': 'okx_v6_rest',
        'bsc_baw_enabled': BSC_BAW_ENABLED,
        'config': runtime_config_snapshot(),
        'state_last_poll': (state or {}).get('last_poll', 0),
        'positions': len((state or {}).get('positions', {})),
    }
    try:
        os.makedirs(DATA, exist_ok=True)
        if locked_write_json:
            locked_write_json(RUNTIME_FILE, payload, indent=2)
        else:
            tmp = RUNTIME_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, RUNTIME_FILE)
    except Exception:
        pass


def start_runtime_heartbeat(state):
    """Keep the dashboard heartbeat alive while a bounded CLI call runs."""
    stop_event = threading.Event()

    def _loop():
        while not stop_event.wait(5):
            write_runtime_status('running', state)

    thread = threading.Thread(target=_loop, daemon=True, name='sm-monitor-heartbeat')
    thread.start()
    return stop_event, thread



LOG_ROTATE_SIZE = 5 * 1024 * 1024  # 5MB

def _rotate_log_if_needed():
    """Rotate log file if exceeds LOG_ROTATE_SIZE. Archive old to archive/logs/."""
    try:
        if not os.path.exists(LOG_FILE):
            return
        if os.path.getsize(LOG_FILE) < LOG_ROTATE_SIZE:
            return
        # Archive current log
        log_dir = os.path.join(DATA, "archive", "logs")
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = os.path.join(log_dir, f"sm_trade-log_{ts}.txt")
        os.rename(LOG_FILE, archive_name)
        # Decay old archived logs (keep 30 days)
        _decay_old_logs(log_dir)
    except Exception:
        pass

def _decay_old_logs(log_dir, max_age_days=30):
    """Remove archived log files older than max_age_days."""
    try:
        cutoff = time.time() - max_age_days * 86400
        for fn in os.listdir(log_dir):
            if fn.startswith("sm_trade-log_") and fn.endswith(".txt"):
                fp = os.path.join(log_dir, fn)
                if os.path.getmtime(fp) < cutoff:
                    os.remove(fp)
    except Exception:
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
        if callable(locked_read_json):
            return locked_read_json(
                STATE_FILE,
                {'seen_txs': [], 'positions': {}, 'last_ts': 0, 'wallet_stats': {}},
            )
        with open(STATE_FILE, encoding='utf-8') as f:
            return json.load(f)

    except:

        return {'seen_txs': [], 'positions': {}, 'last_ts': 0, 'wallet_stats': {}}






def _load_shared_dedup():
    try:
        if os.path.exists(SHARED_DEDUP_FILE):
            if callable(locked_read_json):
                return locked_read_json(SHARED_DEDUP_FILE, {})
            with open(SHARED_DEDUP_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except:
        pass
    return {}


def _save_shared_dedup(data):
    try:
        if callable(locked_write_json):
            locked_write_json(SHARED_DEDUP_FILE, data, indent=2)
            return
        with open(SHARED_DEDUP_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f)
    except:
        pass


def _check_shared_dedup(ca):
    now = int(time.time())
    dedup = _load_shared_dedup()
    entry = dedup.get(ca, {})
    if entry and (now - entry.get('ts', 0)) < SHARED_DEDUP_TTL:
        return True
    return False


def _record_shared_dedup(ca, chain, sym):
    now = int(time.time())
    dedup = _load_shared_dedup()
    dedup[ca] = {'ts': now, 'chain': chain, 'sym': sym}
    cutoff = now - SHARED_DEDUP_TTL * 2
    dedup = {k: v for k, v in dedup.items() if v.get('ts', 0) > cutoff}
    _save_shared_dedup(dedup)
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

        elif action == 'set_config':
            try:
                target_chain = cmd.get('chain')
                if target_chain:
                    snapshot = apply_chain_config(target_chain, cmd.get('updates', {}), persist=True)
                    log(f'[CMD] {target_chain} config applied: {", ".join(sorted(cmd.get("updates", {}).keys()))}')
                    log(f'[CONFIG] {target_chain} positions={snapshot["max_positions"]}, mcap=${snapshot["min_mcap"]:,}, risk={snapshot["risk_pct"]:.1%}, tp={snapshot["quick_tp_pct"]:.1%}, sl={snapshot["stop_loss_pct"]:.1%}')
                else:
                    snapshot = apply_runtime_config(cmd.get('updates', {}), persist=True)
                    log(f'[CMD] Runtime config applied: {", ".join(sorted(cmd.get("updates", {}).keys()))}')
                    log(f'[CONFIG] global positions={snapshot["max_positions"]}, mcap=${snapshot["min_mcap"]:,}, risk={snapshot["risk_pct"]:.1%}, tp={snapshot["quick_tp_pct"]:.1%}, sl={snapshot["stop_loss_pct"]:.1%}')
            except (TypeError, ValueError, OSError) as exc:
                log(f'[CMD] Runtime config rejected: {exc}')

        elif action == 'set_risk':
            # Backward-compatible adapter for the old command shape.
            updates = {}
            if 'risk_pct' in cmd:
                updates['risk_pct'] = cmd['risk_pct']
            if 'daily_limit' in cmd:
                updates['daily_loss_limit_pct'] = cmd['daily_limit']
            try:
                apply_runtime_config(updates, persist=True)
                log(f'[CMD] Legacy risk config applied: {", ".join(sorted(updates))}')
            except (TypeError, ValueError, OSError) as exc:
                log(f'[CMD] Legacy risk config rejected: {exc}')

        else:
            log(f'[CMD] Unknown action: {action}')

    state['positions'] = positions

def _save_trade_history(state, pos, exit_price, exit_pnl_pct, reason, exit_usd=0.0, sold_pct=1.0):
    """Append closed position to trade_history."""
    entry_ts = int(pos.get('entry_ts', 0))
    now_ts = int(time.time())
    hold_hours = round((now_ts - entry_ts) / 3600, 2) if entry_ts else 0
    entry_price = float(pos.get('entry_price', 0) or 0)
    entry_usd = float(pos.get('entry_usd_amount', BUY_SIZE_USDT))
    # Normalize to fraction (e.g., 0.05 = 5%) - some callers pass percentage
    if abs(exit_pnl_pct) > 1.0:
        exit_pnl_pct = exit_pnl_pct / 100.0
    exit_usd_total = entry_usd * (1 + exit_pnl_pct) if entry_usd > 0 else exit_usd
    # Fix: partial sells must prorate entry cost by sold_pct
    sold_frac = max(0.0, min(1.0, float(sold_pct)))
    if sold_frac <= 0:
        sold_frac = 1.0  # safety fallback
    prorated_entry = round(entry_usd * sold_frac, 6)
    prorated_exit = round(exit_usd_total * sold_frac, 6) if exit_usd_total > 0 else round(exit_usd * sold_frac, 6)
    record = {
        'symbol': pos.get('symbol', '?'),
        'chain': pos.get('chain', 'solana'),
        'entry_ts': entry_ts,
        'entry_price': entry_price,
        'entry_usd_amount': prorated_entry,
        'sold_pct': round(sold_frac, 4),
        'entry_mcap': pos.get('entry_mcap', 0),
        'buy_tx': pos.get('buy_tx', ''),
        'exit_ts': now_ts,
        'exit_price': exit_price,
        'exit_pnl_pct': round(exit_pnl_pct, 6),
        'exit_usd': prorated_exit,
        'hold_hours': hold_hours,
        'reason': reason,
    }
    state.setdefault('trade_history', [])
    state['trade_history'].append(record)
    state['trade_history'] = state['trade_history'][-500:]
    sym = pos.get('symbol', '?')
    log(f'trade_history: {sym} closed pnl={exit_pnl_pct:+.1%} hold={hold_hours}h reason={reason}')
    # Track consecutive stop losses
    if reason == 'stop_loss':
        state['consec_sl'] = state.get('consec_sl', 0) + 1
        cs = state['consec_sl']
        if cs >= CONSEC_SL_LIMIT:
            state['consec_sl_freeze_until'] = int(time.time()) + CONSEC_SL_FREEZE_SEC
            log(f'CONSEC SL: {cs} losses -> freeze 2h')
        else:
            log(f'CONSEC SL: {cs}/{CONSEC_SL_LIMIT}')
    elif reason not in ('dead_position',):
        if int(state.get('consec_sl') or 0) > 0:
            log('CONSEC SL reset')
        state['consec_sl'] = 0
        state['consec_sl_freeze_until'] = 0
    # Archive closed position to daily file
    if _ARCHIVE_OK:
        try:
            on_sell_closed({
                'token_address': pos.get('token_address', pos.get('ca', '')),
                'chain': pos.get('chain', 'unknown'),
                'buy_time': pos.get('buy_time', ''),
                'last_sell_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'pnl_pct': exit_pnl_pct,
                'symbol': pos.get('symbol', '?'),
                'reason': reason,
                'exit_usd': exit_usd,
                'hold_hours': hold_hours,
            })
        except Exception:
            pass
            save_state(state)

def save_state(state):

    os.makedirs(DATA, exist_ok=True)

    state.setdefault('trade_history', [])

    state.setdefault('seen_txs', [])
    state['seen_txs'] = state['seen_txs'][-1000:]

    if callable(locked_write_json):
        locked_write_json(STATE_FILE, state, indent=2)
        return

    tmp = STATE_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)



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

    # Solana - use OnChainOS wallet balance API (BAW CLI不支持Solana)

    try:

        for attempt in range(3):

            sol_out, sol_code = oc_run(['onchainos', 'wallet', 'balance', '--chain', 'solana'], timeout=25)

            if sol_code == 0 and sol_out:

                sol_d = parse_json(sol_out)

                if sol_d and sol_d.get('ok'):

                    details = sol_d.get('data', {}).get('details', [])

                    for detail in details:

                        for ta in detail.get('tokenAssets', []):

                            if str(ta.get('chainIndex', '')) != '501':

                                continue

                            sym = ta.get('symbol') or ta.get('tokenSymbol', '?')

                            bal = float(ta.get('balance', 0) or 0)

                            addr = ta.get('tokenAddress', '')

                            price = float(ta.get('tokenPrice', 0) or 0)

                            if addr and bal > 0 and sym not in ('USDT', 'USDC', 'SOL', 'wSOL') and addr not in BLACKLIST_TOKENS:

                                wallet_tokens[addr] = {'symbol': sym, 'balance': bal, 'price': price, 'chain': 'solana'}

                    break  # success

            if attempt < 2:

                time.sleep(2 * (attempt + 1))

    except Exception as e:

        log('reconcile: solana onchainos fail: ' + str(e))


    # BSC wallet/order reconciliation is paused with BAW.  BSC market data
    # (signals and prices) continues through the direct OKX V6 REST client.
    if BSC_BAW_ENABLED:
        try:
            bsc_out, bsc_code = baw_run(['wallet', 'balance', '--json'], timeout=10)

            if bsc_code == 0:
                bd = parse_json(bsc_out)

                if bd:
                    items = bd if isinstance(bd, list) else bd.get('data', bd.get('tokens', []))

                    for item in items:
                        addr = item.get('address') or item.get('contractAddress', '') or item.get('address', '')
                        sym = item.get('symbol', '?')
                        bal = float(item.get('balance', 0) or 0)
                        if addr and addr != 'native' and bal > 0.01 and sym not in ('BNB', 'WBNB'):
                            wallet_tokens[addr] = {'symbol': sym, 'balance': bal, 'price': 0, 'chain': 'bsc'}

        except Exception as e:
            log('reconcile: bsc fail: ' + str(e))

    # Align

    #  BSC ()

    bsc_limit_orders = {}

    if BSC_BAW_ENABLED:
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
        except Exception:
            pass



    added, removed = 0, 0

    # Step 1: Add new tokens from wallet not in state

    for ca, info in wallet_tokens.items():

        value_usd = info['balance'] * info['price']

        if ca not in positions and value_usd >= DEAD_POSITION_USD and info['symbol'] and info['symbol'] != '?' and ca not in BLACKLIST_TOKENS:

            chain_config = get_chain_config(info['chain'])
            sl_price = info['price'] * (1 - chain_config['stop_loss_pct'])
            pos_data = {'symbol': info['symbol'], 'chain': info['chain'], 'entry_ts': now_ts, 'entry_mcap': 0, 'entry_price': info['price'], 'entry_usd_amount': chain_config['buy_size_usdt'], 'last_update_ts': now_ts, 'sm_buys': 0, 'sm_sells': 0, 'buy_tx': 'recovered', 'sold_pct': 0.0, 'ladder_step': 0, 'current_price': info['price'], 'pnl_pct': 0.0, 'recovered': True, 'entry_price_est': True, 'sl': sl_price, 'sl_pct': -chain_config['stop_loss_pct']}

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

            sym = pos.get('symbol', '?')

            chain = pos.get('chain', 'solana')

            # Without BAW there is no BSC wallet snapshot to reconcile
            # against.  Preserve BSC simulation/live state for the OKX price
            # and signal path instead of treating it as an orphan.
            if chain == 'robinhood' or (chain == 'bsc' and not BSC_BAW_ENABLED):
                continue

            orphan_bal = pos.get('balance', 0)

            # Auto-sell orphan tokens before removing, unless blacklisted

            if orphan_bal > 0 and ca not in BLACKLIST_TOKENS:

                log(f'reconcile: {sym} orphan balance={orphan_bal}, selling...')

                try:

                    ok, tx = execute_sell(chain, ca, orphan_bal)

                    if ok:

                        log(f'reconcile: {sym} orphan sold tx={str(tx)[:20]}')

                        # Record trade in history

                        pnl = float(pos.get('sold_pct', 0)) * BUY_SIZE_USDT / 100.0

                        _save_trade_history(state, ca, sym, chain, 'sold', float(pos.get('entry_price', 0)),

                                           BUY_SIZE_USDT, now_ts,

                                           pnl_pct=pnl / BUY_SIZE_USDT * 100 if BUY_SIZE_USDT > 0 else 0,

                                           reason='orphan_cleanup')

                    else:

                        log(f'reconcile: {sym} orphan sell FAIL: {tx}')

                except Exception as e:

                    log(f'reconcile: {sym} orphan sell error: {e}')

            log('reconcile: -' + sym + ' gone -> removed')

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

    if not BSC_BAW_ENABLED:
        return 'BAW integration paused (BSC_BAW_ENABLED=0)', -2

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


def trade_time_ms(value):
    """Normalize WS/REST timestamps to epoch milliseconds."""
    try:
        ts = int(float(value or 0))
    except (TypeError, ValueError):
        return 0
    if 0 < ts < 10_000_000_000:  # epoch seconds
        ts *= 1000
    return ts



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

        ts = trade_time_ms(t.get('tradeTime', '0'))

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



def is_good_wallet(wallets, addr, min_winrate=None):

    wr = get_wallet_winrate(wallets, addr)

    if wr is None:

        return True

    return wr >= (MIN_WALLET_WINRATE if min_winrate is None else min_winrate)



# ===  ===

def _ws_chain_index(chain):
    """Map the monitor's chain names to OKX WS chain indexes."""
    text = str(chain or "").strip().lower()
    return CHAIN_INDEXES.get(text, text)


def _is_evm_chain(chain):
    return _ws_chain_index(chain) in {'56', '4663'}


def sync_ws_price_subscriptions(positions):
    """Keep WS price feeds aligned with the currently held positions."""
    if not _WS_CLIENT or not hasattr(_WS_CLIENT, 'sync_price_subscriptions'):
        return
    items = []
    for position_key, pos in (positions or {}).items():
        token_ca = str(pos.get('token_ca') or position_key or '').strip()
        if not token_ca:
            continue
        items.append({
            'chainIndex': _ws_chain_index(pos.get('chain', 'solana')),
            'tokenContractAddress': token_ca,
        })
    try:
        _WS_CLIENT.sync_price_subscriptions(items)
    except Exception as exc:
        log(f'WS price subscription sync failed: {exc}')


def fetch_tracker(state=None):

    """Fetch recent Smart Money trades from OKX V6 REST first.

    The direct V6 REST endpoint is the active source.  The legacy WS path is
    retained only for compatibility tests/launchers, and the OnchainOS CLI
    remains a secondary fallback when the direct REST entitlement fails.
    """

    global _WS_CLIENT, _REST_CLIENT

    if _REST_CLIENT is not None:
        rest_trades = _REST_CLIENT.fetch_signal_events()
        if getattr(_REST_CLIENT, 'last_signal_ok', False):
            return rest_trades
        log('OKX V6 REST signal unavailable, using secondary fallback: ' + str(
            getattr(_REST_CLIENT, 'last_signal_error', 'unknown error')
        ))

    # Drain WS first even if the socket closed after buffering an event.
    if _WS_CLIENT:
        ws_events = _WS_CLIENT.get_events()
        if ws_events:
            # Update price cache from WS events (tokenPrice field)
            _now = time.time()
            for _evt in ws_events:
                try:
                    _ca = str(_evt.get('tokenContractAddress', '')).lower()
                    _price = float(_evt.get('tokenPrice', 0) or 0)
                    if _ca and _price > 0:
                        _price_cache[_ca] = (_price, _now)
                except (ValueError, TypeError):
                    pass
            # WS instant SL/TP: executed by the main thread, never by the
            # socket callback, so state and order paths remain serialized.
            _ws_instant_sl_check(state)
            # Price pushes drive exits but are not smart-money entry signals.
            return [evt for evt in ws_events if evt.get('event_type') != 'price']

        # A healthy WS is event-driven. Do not call REST while it is merely
        # idle: that would block the main thread and defeat the wake-up path.
        ws_ready_attr = getattr(
            _WS_CLIENT,
            'is_feed_ready',
            getattr(_WS_CLIENT, 'is_ready', False),
        )
        ws_ready = ws_ready_attr() if callable(ws_ready_attr) else bool(ws_ready_attr)
        if ws_ready:
            return []

    # REST fallback (onchainos CLI) when WS is down or has no events
    all_trades = []

    for ch in ['solana', 'bsc']:

        out, _ = oc_run([

            'onchainos', 'tracker', 'activities',

            '--tracker-type', 'smart_money',

            '--chain', ch,

            '--min-volume', str(MIN_VOLUME)

        ], timeout=TRACKER_REST_TIMEOUT_SEC)

        d = parse_json(out)

        if d and d.get('ok'):

            all_trades.extend(d.get('data', {}).get('trades', []))

    return all_trades




def _ws_instant_sl_check(state):
    """WS-driven instant stop-loss: check held positions against latest WS prices.
    Called from fetch_tracker() when WS price_cache is updated.
    Thread-safe via _ws_sl_lock. Only handles: stop_loss, trailing_stop, quick_tp (first tier).
    Full tier logic (6h_tp, 12h_tp, etc.) still handled by check_positions() in run_once().
    """
    if _ws_sl_lock is None:
        return  # not initialized yet
    if not _ws_sl_lock.acquire(blocking=False):
        return  # check_positions() is running, skip to avoid race

    try:
        positions = state.get('positions', {})
        if not positions:
            return

        now_ts = int(time.time())
        to_sell = []  # list of (ca, reason, sell_pct)

        for ca, pos in list(positions.items()):
            ca_lower = ca.lower()
            cached = _price_cache.get(ca_lower)
            if not cached:
                continue  # no WS price for this token

            ws_price, ws_ts = cached
            # Only use WS price if it's fresh (< 5s old)
            if time.time() - ws_ts > 5:
                continue

            entry_price = float(pos.get('entry_price', 0) or 0)
            if entry_price <= 0:
                continue

            chain = pos.get('chain', 'solana')
            sym = pos.get('symbol', '?')
            pnl = (ws_price - entry_price) / entry_price
            hold_hours = (now_ts - int(pos.get('entry_ts', now_ts))) / 3600

            # Update position price immediately
            pos['current_price'] = ws_price
            pos['pnl_pct'] = pnl
            pos['last_update_ts'] = now_ts

            # ── Stop-loss check ──
            dynamic_sl = SL_PCT  # -0.08
            # Apply TIME_TIERS SL override
            for tier_hours, tier_sl, tier_tp, sell_pct, label in TIME_TIERS:
                if hold_hours < tier_hours:
                    break
                if tier_sl is not None:
                    dynamic_sl = tier_sl

            # Trend adjustment (simplified — use cached trend if available)
            trend_3m = get_trend(ca, 180)
            trend_15m = get_trend(ca, 900)
            trend_adj = 0.0
            if trend_15m < -0.02:
                trend_adj += 0.02
            if trend_3m < -0.05:
                trend_adj += 0.03

            effective_sl = dynamic_sl + trend_adj

            if pnl <= effective_sl:
                log(f'[WS-SL] {sym} PnL={pnl:+.1%} <= SL={effective_sl:+.0%} hold={hold_hours:.1f}h -> INSTANT SELL')
                to_sell.append((ca, 'stop_loss', 1.0))
                continue

            # ── Trailing stop check ──
            trailing_sl = pos.get('trailing_sl', None)
            if pnl >= 0.20:
                trailing_sl = 0.10
            elif pnl >= 0.10:
                trailing_sl = 0.05
            elif pnl >= 0.05:
                trailing_sl = 0.02

            if trailing_sl is not None:
                pos['trailing_sl'] = trailing_sl
                if pnl <= trailing_sl and hold_hours > 0.1:
                    log(f'[WS-TRAIL] {sym} PnL={pnl:+.1%} <= trail={trailing_sl:.0%} -> INSTANT SELL')
                    to_sell.append((ca, 'trailing_stop', 1.0))
                    continue

            # ── Quick TP (first tier, full exit by default) ──
            if pnl >= TIME_TIERS[0][2]:
                ladder_step = int(pos.get('ladder_step', 0))
                if ladder_step < 1:  # only first quick_tp tier
                    quick_sell = TIME_TIERS[0][3]
                    log(f'[WS-TP] {sym} PnL={pnl:+.1%} >= {TIME_TIERS[0][2]:+.0%} -> quick_tp {quick_sell:.0%}')
                    to_sell.append((ca, 'quick_tp', quick_sell))
                    pos['ladder_step'] = 1
                    continue

        # ── Execute sells ──
        for ca, reason, sell_pct in to_sell:
            pos = positions.get(ca)
            if not pos:
                continue

            chain = pos.get('chain', 'solana')
            sym = pos.get('symbol', '?')
            entry_price = float(pos.get('entry_price', 0) or 0)
            current_price = float(pos.get('current_price', entry_price))
            exit_pnl = (current_price - entry_price) / entry_price if entry_price > 0 else -1.0

            if sell_pct >= 1.0:
                # Full sell
                remaining = 1.0 - float(pos.get('sold_pct', 0))
                entry_usd = float(pos.get('entry_usd_amount', BUY_SIZE_USDT) or BUY_SIZE_USDT)
                token_bal = (entry_usd * remaining) / entry_price if entry_price > 0 else 0

                if DRY_RUN:
                    log(f'[DRY][WS] SELL ALL {sym} reason={reason} PnL={exit_pnl:+.1%}')
                else:
                    ok, tx = execute_sell(chain, ca, round(token_bal, 6))
                    if ok:
                        log(f'[WS] SELL OK {sym} reason={reason} tx={tx[:20]}...')
                    else:
                        log(f'[WS] SELL FAIL {sym} reason={reason}')
                        pos['sell_fail_count'] = pos.get('sell_fail_count', 0) + 1
                        pos['sell_last_attempt'] = int(time.time())
                        continue  # skip removal, let check_positions retry

                _save_trade_history(state, pos, current_price, exit_pnl, reason, sold_pct=1.0)
                del positions[ca]
            else:
                # Partial sell (quick_tp 30%)
                remaining = 1.0 - float(pos.get('sold_pct', 0))
                sell_amount = remaining * sell_pct
                entry_usd = float(pos.get('entry_usd_amount', BUY_SIZE_USDT) or BUY_SIZE_USDT)
                token_bal = (entry_usd * remaining) / entry_price if entry_price > 0 else 0
                sell_bal = token_bal * sell_pct

                if DRY_RUN:
                    log(f'[DRY][WS] SELL {sell_pct:.0%} {sym} reason={reason} PnL={exit_pnl:+.1%}')
                else:
                    ok, tx = execute_sell(chain, ca, round(sell_bal, 6))
                    if ok:
                        log(f'[WS] PARTIAL SELL OK {sym} {sell_pct:.0%} reason={reason}')
                    else:
                        log(f'[WS] PARTIAL SELL FAIL {sym}')
                        continue

                _save_trade_history(state, pos, current_price, exit_pnl, reason, sold_pct=sell_pct)
                pos['sold_pct'] = float(pos.get('sold_pct', 0)) + sell_pct

        if to_sell:
            state['positions'] = positions
            save_state(state)

    finally:
        _ws_sl_lock.release()


# === BSC  ===

def get_balance_bsc():

    """BSC : ?baw wallet balance,?{contract_address: balance}"""

    if not BSC_BAW_ENABLED:
        return {}

    out, _ = baw_run(['wallet', 'balance', '--json'], timeout=15)

    d = parse_baw_json(out)

    if not d or not d.get('success'):

        log(f'get_balance_bsc fail: {out[:100]}')

        return {}

    result = {}

    for item in d.get('data', []) if isinstance(d.get('data'), list) else d.get('data', {}).get('balances', []):

        bal = float(item.get('balance', 0) or 0)

        ca = item.get('address') or item.get('contractAddress', '')

        if bal > 0 and ca:

            result[ca.lower()] = bal

    return result



def bsc_market_buy(token_ca, amount_usdt):

    """BSC """

    if not BSC_BAW_ENABLED:
        log('BSC BUY blocked: BAW integration is paused')
        return False, None

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

    if not BSC_BAW_ENABLED:
        log('BSC SELL blocked: BAW integration is paused')
        return False, None

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

    if not BSC_BAW_ENABLED:
        return None

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
    if not BSC_BAW_ENABLED:
        return False, ''
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

    if not BSC_BAW_ENABLED:
        return False

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

    if not BSC_BAW_ENABLED:
        return 'UNKNOWN'

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

    if not BSC_BAW_ENABLED:
        return positions

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

    if chain == 'robinhood':
        # No wallet/execution adapter is enabled for Robinhood yet.  Market
        # data remains fully available through OKX V6 REST.
        return {}

    # Solana - use OnChainOS wallet balance API (with Solana RPC fallback)

    result = {}

    # Try OnChainOS first

    try:

        for attempt in range(3):

            sol_out, sol_code = oc_run(['onchainos', 'wallet', 'balance', '--chain', 'solana'], timeout=25)

            if sol_code == 0 and sol_out:

                sol_d = parse_json(sol_out)

                if sol_d and sol_d.get('ok'):

                    details = sol_d.get('data', {}).get('details', [])

                    for detail in details:

                        for ta in detail.get('tokenAssets', []):

                            if str(ta.get('chainIndex', '')) != '501':

                                continue

                            bal = float(ta.get('balance', 0) or 0)

                            addr = ta.get('tokenAddress', '')

                            if addr and bal > 0 and addr != 'So11111111111111111111111111111111111111111':

                                result[addr.lower()] = bal

                    if result:

                        return result

                    break  # API returned OK but no tokens

            if attempt < 2:

                time.sleep(2 * (attempt + 1))

    except Exception as e:

        log('get_balance solana onchainos fail: ' + str(e))

    # Fallback: Solana RPC direct query

    if not result and WALLET:

        try:

            rpc_payload = json.dumps({

                'jsonrpc': '2.0', 'id': 1,

                'method': 'getTokenAccountsByOwner',

                'params': [WALLET, {'programId': 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'}, {'encoding': 'jsonParsed'}]

            }).encode('utf-8')

            req = __import__('urllib.request', fromlist=['Request', 'urlopen'])

            r = req.Request('https://api.mainnet-beta.solana.com', data=rpc_payload,

                           headers={'Content-Type': 'application/json'}, method='POST')

            with req.urlopen(r, timeout=15) as resp:

                rpc_data = json.loads(resp.read().decode('utf-8'))

            for v in rpc_data.get('result', {}).get('value', []):

                info = v.get('account', {}).get('data', {}).get('parsed', {}).get('info', {})

                mint = info.get('mint', '')

                ui = info.get('tokenAmount', {})

                bal = float(ui.get('uiAmount', 0) or 0)

                if mint and bal > 0 and mint != 'So11111111111111111111111111111111111111111':

                    result[mint] = bal

        except Exception as e:

            log('get_balance solana rpc fail: ' + str(e))

    return result



def get_token_price_usd(chain, token_ca, retries=MAX_PRICE_RETRIES):

    """Fetch price -- OKX V6 REST first, then cache/CLI fallback."""

    _ca = token_ca.lower()
    _now = time.time()

    # Check cache first (valid for 10 seconds)
    _cached = _price_cache.get(_ca)
    if _cached:
        _price, _ts = _cached
        if _now - _ts < 10:
            return _price

    # Cache miss or stale -- use the direct OKX V6 REST price endpoint.
    if _REST_CLIENT is not None:
        rest_prices = _REST_CLIENT.fetch_prices([{
            'chainIndex': _ws_chain_index(chain),
            'tokenContractAddress': token_ca,
        }])
        _rest_key = f"{_ws_chain_index(chain)}:{token_ca.lower() if _is_evm_chain(chain) else token_ca}"
        _rest_price = rest_prices.get(_rest_key)
        if _rest_price and _rest_price > 0:
            _price_cache[_ca] = (_rest_price, _now)
            return _rest_price

    # Secondary fallback through the OnchainOS CLI.
    for attempt in range(retries + 1):

        out, _ = oc_run([

            'onchainos', 'token', 'price-info',

            '--chain', chain, '--address', token_ca

        ], timeout=PRICE_QUERY_TIMEOUT_SEC)


        d = parse_json(out)


        if d and d.get('ok'):

            for item in d.get('data', []):

                if item.get('tokenContractAddress', '').lower() == _ca:

                    price = float(item.get('price', 0))


                    if price > 0:

                        # Update cache
                        _price_cache[_ca] = (price, _now)
                        return price


        if attempt < retries:

            time.sleep(1 + attempt)  #

    # REST failed -- return stale cache if available (better than None)
    if _cached:
        return _cached[0]

    return None




# === SOL 余额检查（用于买入前）===
def _get_sol_balance():
    """返回 SOL 原生余额（浮点数），失败返回 None。"""
    try:
        out, code = oc_run(['onchainos', 'wallet', 'balance', '--chain', 'solana'], timeout=15)
        if code != 0 or not out:
            return None
        d = parse_json(out)
        if d and d.get('ok'):
            details = d.get('data', {}).get('details', [])
            for detail in details:
                for ta in detail.get('tokenAssets', []):
                    if ta.get('tokenAddress') == 'So11111111111111111111111111111111111111111':
                        return float(ta.get('balance', 0) or 0)
        # 可能返回 totalSolValue 或 nativeBalance
        nd = d.get('data', {}) if d else {}
        nb = nd.get('nativeBalance') or nd.get('totalSolValue')
        if nb is not None:
            return float(nb)
    except Exception:
        pass
    return None


# ===  ===

def execute_buy(chain, token_ca, amount_usdt):

    """:BSC ?BAW,Solana ?onchainos"""

    if DRY_RUN:

        log(f'[DRY] BUY ${amount_usdt} -> {token_ca[:12]}...')

        return True, 'dry-tx'

    if chain == 'robinhood':
        log('ROBINHOOD BUY blocked: market-data-only chain, no live executor')
        return False, None

    if chain == 'bsc':

        return bsc_market_buy(token_ca, amount_usdt)

    # Solana
    # Pre-check: SOL balance for token account rent
    sol_bal = _get_sol_balance()
    if sol_bal is not None and sol_bal < MIN_SOL_BALANCE:
        log(f'BUY SKIP: SOL too low (${sol_bal:.4f} < ${MIN_SOL_BALANCE})')
        return False, None

    # Pre-check: swap quote to verify pool is tradeable (catches ~90% of InstErr)
    q_out, q_code = oc_run([
        'onchainos', 'swap', 'quote',
        '--chain', chain,
        '--from', usdt_addr(chain),
        '--to', token_ca,
        '--readable-amount', str(round(amount_usdt, 6)),
    ], timeout=20)
    if q_code != 0 or not q_out or 'InstructionError' in (q_out or ''):
        log(f'BUY SKIP: quote failed (pool not tradeable)')
        return False, None

    out, _ = oc_run([

        'onchainos', 'swap', 'execute',

        '--chain', chain,

        '--from', usdt_addr(chain),

        '--to', token_ca,

        '--readable-amount', str(round(amount_usdt, 6)),

        '--wallet', WALLET,

        '--gas-level', 'fast',

        '--max-auto-slippage', '25'

    ], timeout=30)

    d = parse_json(out)

    if d and d.get('ok'):

        tx = d['data'].get('swapTxHash', '')

        log(f'BUY OK: tx={tx[:20]}...')

        return True, tx

    err = d.get('error', 'unknown') if d else out[:100]

    log(f'BUY FAIL: {err}')

    return False, None





def _check_sold_ratio(chain, ca):
    """Check soldRatio from onchainos API."""
    if chain == 'robinhood':
        return None
    try:
        r = subprocess.run(
            ['onchainos', 'token', 'price-info', '--address', ca, '--chain', chain],
            capture_output=True, timeout=SOLD_RATIO_TIMEOUT_SEC,
            encoding='utf-8', errors='replace',
            env=okx_env_for_subprocess() if okx_env_for_subprocess else None,
        )
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout.strip())
            sr = data.get('soldRatio')
            if sr is not None:
                return float(sr)
    except:
        pass
    return None
def execute_sell(chain, token_ca, token_balance):

    """:BSC ?BAW ,Solana ?onchainos"""

    if DRY_RUN:

        log(f'[DRY] SELL {token_balance} {token_ca[:12]}...')

        return True, 'dry-tx'

    if chain == 'robinhood':
        log('ROBINHOOD SELL blocked: market-data-only chain, no live executor')
        return False, None

    if chain == 'bsc':

        return bsc_market_sell(token_ca, round(token_balance, 6))

    # Solana - retry with increasingly wide slippage

    for slippage in [25, 35, 49]:

        out, _ = oc_run([

            'onchainos', 'swap', 'execute',

            '--chain', chain,

            '--from', token_ca,

            '--to', usdt_addr(chain),

            '--readable-amount', str(round(token_balance, 6)),

            '--wallet', WALLET,

            '--gas-level', 'fast',

            '--max-auto-slippage', str(slippage)

        ], timeout=30)

        d = parse_json(out)

        if d and d.get('ok'):

            tx = d['data'].get('swapTxHash', '')

            got = int(d['data'].get('toAmount', 0)) / 1e6

            log(f'SELL OK (slippage={slippage}%): tx={tx[:20]}... got=${got:.2f}')

            return True, tx

        time.sleep(2)

    err = d.get('error', 'unknown') if d else out[:100]

    log(f'SELL FAIL (all slippage): {err}')

    return False, None



# ===  ===

def process_new_trades(trades, state, wallets):

    positions = state.get('positions', {})

    seen = set(state.get('seen_txs', []))

    new = [t for t in trades if t.get('txHash') and t['txHash'] not in seen]

    if not new:

        return positions

    # Only learn from unseen events. REST fallback returns overlapping windows;
    # updating before this filter would inflate wallet win rates on every poll.
    wallets = update_wallet_stats(wallets, new)



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



    now = time.time()
    session_bought = set()  # P2: prevent same-token duplicate buy in single call
    # Process the newest token activity first when a burst arrives.
    activities = sorted(
        activity.items(),
        key=lambda item: trade_time_ms((item[1].get('latest') or {}).get('tradeTime')),
        reverse=True,
    )
    for ca, act in activities:

        lat = act['latest']

        sym = lat.get('tokenSymbol', '?')

        mcap = float(
            lat.get('marketCap')
            or lat.get('marketCapUsd')
            or lat.get('mcap')
            or 0
        )

        chain_idx = str(lat.get('chainIndex', ''))

        chain_map = {'501': 'solana', '56': 'bsc', '4663': 'robinhood'}

        chain = chain_map.get(chain_idx, 'unknown')
        chain_config = get_chain_config(chain) if chain != 'unknown' else {}



        # ? ?

        if ca in positions:

            if act['sells'] > 0:
                prev_sm = positions[ca].get('_prev_sm_sells', 0)
                positions[ca]['sm_sells'] = positions[ca].get('sm_sells', 0) + act['sells']
                log(f'SM SELL on {sym}: total_sm_sells={positions[ca]["sm_sells"]}')
                # P3: SM follow sell立即触发，不等下轮check_positions
                new_s = positions[ca]['sm_sells'] - prev_sm
                if new_s >= SM_SELL_FOLLOW:
                    positions[ca]['_prev_sm_sells'] = positions[ca]['sm_sells']
                    pos = positions[ca]
                    bal = pos.get('balance', 0)
                    entry_price = float(pos.get('entry_price', 0) or 0)
                    if bal > 0:
                        ok, tx = execute_sell(chain, ca, round(bal, 6))
                        if ok:
                            exit_price = float(pos.get('current_price', entry_price))
                            exit_pnl = (exit_price - entry_price) / entry_price if entry_price > 0 else 0
                            _save_trade_history(state, pos, exit_price, exit_pnl, 'sm_follow', exit_usd=0, sold_pct=1.0)
                            log(f'SM FOLLOW IMMEDIATE: {sym} tx={tx[:20] if tx else ""}')
                            del positions[ca]
                            save_state(state)
                        else:
                            log(f'SM FOLLOW SELL FAIL: {sym}')
                    else:
                        # balance=0, clean dead position
                        exit_price = float(pos.get('current_price', entry_price))
                        exit_pnl = (exit_price - entry_price) / entry_price if entry_price > 0 else 0
                        _save_trade_history(state, pos, exit_price, exit_pnl, 'sm_follow_dead', exit_usd=0, sold_pct=1.0)
                        log(f'SM FOLLOW IMMEDIATE: {sym} (balance=0, cleaned)')
                        del positions[ca]
                        save_state(state)

            continue




        # ?token ?
        # Dedup: skip if recently bought (crash-recovery protection)
        recent_trades = [t for t in state.get('buy_signals', [])
            if t.get('contract_address') == ca and t.get('reason') in ('buy','sm_buy')
            and now - t.get('ts', 0) < 3600]
        if _check_shared_dedup(ca):
            log(f'SKIP {sym}: cross-chain dedup')
            continue

        if recent_trades:
            log(f'SKIP {sym}: recently traded (cooldown)')
            continue

        # Session dedup: same token in this process_new_trades call
        if ca in session_bought:
            log(f'SKIP {sym}: already bought this cycle')
            continue

        if act['buys'] > 0:

            if mcap < chain_config['min_mcap']:

                log(f'SKIP {sym}: mcap=${mcap:,.0f} < ${chain_config["min_mcap"]:,} ({chain})')

                continue

            chain_position_count = sum(
                1 for position in positions.values()
                if position.get('chain') == chain
            )
            if chain_position_count >= chain_config['max_positions']:

                log(f'SKIP {sym}: {chain} max positions ({chain_config["max_positions"]})')

                continue

            if chain == 'unknown':

                log(f'SKIP {sym}: unsupported chain (idx={chain_idx})')

                continue

            good_wallets = [
                w for w in act['buy_wallets']
                if is_good_wallet(wallets, w, chain_config['min_wallet_winrate'])
            ]

            if not good_wallets and act['buy_wallets']:

                log(f'SKIP {sym}: all buy wallets low winrate ({len(act["buy_wallets"])})')

                continue



            good_buyers = len(good_wallets)

            if good_buyers < chain_config['min_consensus_wallets']:

                log(f'SKIP {sym}: consensus fail (good={good_buyers}, need>={chain_config["min_consensus_wallets"]})')

                continue



            # Signal freshness: skip if SM signal > 60s old
            sig_ts = trade_time_ms(lat.get('tradeTime', 0))
            sig_age = int(time.time() * 1000) - sig_ts if sig_ts else 999999999
            if sig_age < 0 or sig_age > 60000:
                log(f'SKIP {sym}: stale signal ({sig_age//1000}s old)')
                continue
            # Concurrent sell filter: skip if SM is also selling this token
            if act['sells'] >= act['buys']:
                log(f'SKIP {sym}: SM selling (b={act["buys"]} s={act["sells"]})')
                continue
            # soldRatio check
            sr = _check_sold_ratio(chain, ca)
            if sr is not None:
                if sr >= 0.50:
                    log(f'SKIP {sym}: soldRatio={sr:.0%} (holder dump)')
                    continue
                elif sr >= 0.30:
                    log(f'WARN {sym}: soldRatio={sr:.0%} (penalty)')
                    if good_buyers < chain_config['min_consensus_wallets'] + 1:
                        log(f'SKIP {sym}: soldRatio penalty')
                        continue

            # The WS event price is the fastest consistent entry reference;
            # REST is only needed when the event did not include one.
            try:
                entry_price = float(lat.get('tokenPrice') or 0)
            except (TypeError, ValueError):
                entry_price = 0
            if entry_price <= 0:
                entry_price = get_token_price_usd(chain, ca)

            if not entry_price or entry_price <= 0:

                log(f'SKIP {sym}: cannot get price')

                continue

            # Entry timing: skip if price already dropped >2% below signal reference
            signal_price = float(lat.get('tokenPrice', 0) or 0)

            if signal_price > 0 and entry_price / signal_price < 0.98:

                drop_pct = (1 - entry_price / signal_price) * 100

                log(f'SKIP {sym}: price dropped {drop_pct:.1f}% from signal (arrived late)')

                continue



            # trend entry filter (low weight - smart money primary)
            trend_3m_entry = get_trend(ca, 180)
            if trend_3m_entry < -0.08:  # 3min >8%/min crash = skip
                log(f"SKIP {sym}: extreme dump (3min={trend_3m_entry:.1%}/min)")
                continue
            trend_tag = ''
            if trend_3m_entry != 0:
                trend_tag = f' trend={trend_3m_entry:+.1%}/min'
            log(f'SM BUY: {sym} ({chain}) (buyers={len(act["buy_wallets"])}/{good_buyers}good, mcap=${mcap:,.0f}{trend_tag})')

            # risk control check
            can_trade, risk_reason = check_risk_limits(state)
            if not can_trade:
                log(f'SKIP {sym}: risk blocked ({risk_reason})')
                continue

            dynamic_buy = calc_buy_size(state, chain_config)

            # Shared dedup belongs to the optional BAW executor.  Do not let
            # stale BAW records block the OKX REST-only BSC dry-run path.
            if chain == 'bsc' and BSC_BAW_ENABLED and 'shared_is_bought' in dir():
                if shared_is_bought(ca):
                    log(f'SKIP {sym}: already bought by BAW (shared dedup)')
                    continue


            # Buy failure cooldown check
            now_ts = int(time.time())
            buy_fails = state.get('buy_failures', {})
            last_fail = buy_fails.get(ca, 0)
            if last_fail and (now_ts - last_fail) < BUY_FAIL_COOLDOWN:
                remaining_cooldown = BUY_FAIL_COOLDOWN - (now_ts - last_fail)
                log(f'SKIP {sym}: buy cooldown ({remaining_cooldown}s left)')
                continue
            # Permanent fail skip: tokens that hit InstErr >= PERMANENT_FAIL_THRESHOLD
            inst_fails = state.get('perm_fail_tokens', {})
            if inst_fails.get(ca, 0) >= 2:
                log(f'SKIP {sym}: PERMANENT FAIL (InstErr x{inst_fails[ca]})')
                continue

            # Pre-buy safety check (honeypot, tax, liquidity)
            if _HAS_SAFETY and not DRY_RUN:
                s_score, s_passed, s_details, s_errors = check_token(chain, ca, dynamic_buy)
                if not s_passed:
                    reason = ', '.join(s_errors) if s_errors else 'low_score'
                    log(f'SKIP {sym}: SAFETY FAIL ({reason}, score={s_score})')
                    continue
                log(f'Safety OK: {sym} score={s_score} hp={s_details.get("is_honeypot", "?")}')
            elif not _HAS_SAFETY:
                log('WARN: safety_check module not available')
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

                # Store actual balance after buy
                if chain == 'bsc' and not DRY_RUN:
                    try:
                        bal_now = get_balance_bsc()
                        pos_data['balance'] = bal_now.get(ca.lower(), 0)
                    except: pass
                elif chain == 'solana' and not DRY_RUN:
                    try:
                        got = 0
                        for _retry in range(5):
                            time.sleep(3)
                            bal_now = get_balance('solana')
                            got = bal_now.get(ca.lower(), 0)
                            if got > 0:
                                break
                        pos_data['balance'] = got
                    except: pass
                positions[ca] = pos_data

                # Record in trade_history for dedup (cross-cycle protection)
                session_bought.add(ca)
                _record_shared_dedup(ca, chain, sym)

                state.setdefault('buy_signals', []).append({
                    'contract_address': ca, 'symbol': sym, 'reason': 'sm_buy',
                    'ts': int(time.time()), 'amount_usd': dynamic_buy, 'chain': chain
                })
                if len(state.get('buy_signals', [])) > 500:
                    state['buy_signals'] = state['buy_signals'][-500:]
                save_state(state)  # immediate persist after buy (dedup + crash protection)
            else:
                # Record buy failure for cooldown
                now_ts2 = int(time.time())
                state.setdefault('buy_failures', {})[ca] = now_ts2
                # Clean old entries (>1h)
                state['buy_failures'] = {k: v for k, v in state.get('buy_failures', {}).items()
                                         if now_ts2 - v < 3600}
                # Track InstErr for permanent fail (check last log line)
                try:
                    with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as _f:
                        _lines = _f.readlines()
                        _last = _lines[-1] if _lines else ''
                    if 'InstructionError' in _last:
                        ic = state.setdefault('perm_fail_tokens', {}).get(ca, 0) + 1
                        state['perm_fail_tokens'][ca] = ic
                        if ic >= 2:
                            log(f'PERMANENT FAIL: {sym} (InstErr x{ic})')
                except: pass
                log(f'BUY COOLDOWN: {sym} cooldown {BUY_FAIL_COOLDOWN}s')

    return positions





def check_positions(positions, state=None):

    """docstring"""

    if not positions:

        return positions



    # BSC (+)

    positions = check_bsc_limit_orders(positions)

    if not positions:

        return positions



    to_sell_all = []

    to_sell_partial = []

    # to_remove removed — dead positions go through to_sell_all for proper selling

    now_ts = int(time.time())



    for ca, pos in list(positions.items()):

        chain = pos.get('chain', 'solana')
        chain_config = get_chain_config(chain)
        chain_time_tiers = _time_tiers_for_config(chain_config)

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

                log(f'DEAD: {sym} {hold_hours:.0f}h  -> selling')
                to_sell_all.append((ca, 'dead_position'))
                continue

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

        entry_usd = float(pos.get('entry_usd_amount', BUY_SIZE_USDT) or BUY_SIZE_USDT)
        position_value = entry_usd * (1.0 - float(pos.get('sold_pct', 0))) * (1 + pnl)

        if position_value < DEAD_POSITION_USD and hold_hours > 1:

            log(f'DEAD: {sym} ${position_value:.2f} < $DEAD_POSITION_USD -> selling')
            to_sell_all.append((ca, 'dead_position'))
            continue



        # ?

        # Max hold time check (force sell after N hours)
        if hold_hours > chain_config['max_hold_hours']:
            log(f'MAX HOLD: {sym} {hold_hours:.1f}h > {chain_config["max_hold_hours"]}h -> force sell')
            to_sell_all.append((ca, 'max_hold_time'))
            continue

        # SM follow sell: trigger only on NEW sells (not cumulative)
        prev = pos.get('_prev_sm_sells', 0)
        curr = pos.get('sm_sells', 0)
        new_s = max(0, curr - prev)
        pos['_prev_sm_sells'] = curr
        if new_s >= SM_SELL_FOLLOW:
            log(f'SM FOLLOW SELL: {sym} (+{new_s}new, total={curr})')
            to_sell_all.append((ca, 'sm_follow'))
            continue
            continue



        #

        dynamic_sl = -chain_config['stop_loss_pct']

        triggered = False

        is_recovered = pos.get('entry_price_est', False)



        #  + (,entry_price )

        if not is_recovered:

            for tier_hours, tier_sl, tier_tp, sell_pct, label in chain_time_tiers:

                if hold_hours < tier_hours:

                    break

                if tier_sl is not None:
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



        effective_sl = (dynamic_sl if dynamic_sl is not None else -chain_config['stop_loss_pct']) + trend_adj  # double guard

        # Trailing stop: lock profits

        trailing_sl = pos.get('trailing_sl', None)

        if pnl >= 0.20:

            trailing_sl = 0.10

        elif pnl >= 0.10:

            trailing_sl = 0.05

        elif pnl >= 0.05:

            trailing_sl = 0.02

        if trailing_sl is not None:

            pos['trailing_sl'] = trailing_sl

            if pnl <= trailing_sl and hold_hours > 0.1:

                log(f'TRAIL: {sym} PnL={pnl:.1%} < trailing_sl={trailing_sl:.0%} -> lock')

                to_sell_all.append((ca, 'trailing_stop'))

                continue

        if pnl <= effective_sl:

            sl_label = f'({effective_sl:.0%})' if effective_sl != -chain_config['stop_loss_pct'] else ''

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



    # (Dead position removal loop removed — dead positions now go through to_sell_all)



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

            entry_usd = float(pos.get('entry_usd_amount', BUY_SIZE_USDT) or BUY_SIZE_USDT)
            token_bal = (entry_usd * remaining) / entry_price if entry_price > 0 else 0

        else:

            # Sell failure backoff: skip if max retries exceeded or in cooldown
            sell_fails = pos.get('sell_fail_count', 0)
            sell_last_attempt = pos.get('sell_last_attempt', 0)
            if sell_fails >= SELL_FAIL_MAX:
                log(f'  {sym}: sell failed {sell_fails} times, cleaning dead position')
                ep = float(pos.get('entry_price', 0) or 0)
                cp = float(pos.get('current_price', ep))
                exit_pnl = (cp - ep) / ep if ep > 0 else -1.0
                _save_trade_history(state, pos, cp, exit_pnl, f'{reason}_sell_fail_max', 0)
                del positions[ca]
                save_state(state)
                continue
            if sell_fails > 0 and sell_last_attempt > 0:
                backoff_sec = min(SELL_FAIL_BACKOFF_BASE * (2 ** (sell_fails - 1)), 300)
                elapsed = int(time.time()) - sell_last_attempt
                if elapsed < backoff_sec:
                    log(f'  {sym}: sell backoff ({elapsed}s / {backoff_sec}s, fail#{sell_fails})')
                    continue
            # Primary: use stored balance from buy-time (reliable, no API call)
            token_bal = pos.get('balance', 0)
            # Fallback: get_balance API (with retry)
            if token_bal <= 0:
                for _retry in range(3):
                    bal_info = get_balance(chain)
                    token_bal = bal_info.get(ca.lower(), 0)
                    if token_bal > 0:
                        pos['balance'] = token_bal
                        break
                    time.sleep(2)

        if token_bal > 0:

            ok, tx_id = execute_sell(chain, ca, round(token_bal, 6))
            if ok:
                pos['sell_fail_count'] = 0  # reset on success
                exit_price = float(pos.get('current_price', pos.get('entry_price', 0)))
                ep = float(pos.get('entry_price', 0) or 0)
                exit_pnl = (exit_price - ep) / ep if ep > 0 else 0
                exit_usd = token_bal * exit_price
                _save_trade_history(state, pos, exit_price, exit_pnl, reason, exit_usd)
                del positions[ca]
            else:
                pos['sell_fail_count'] = pos.get('sell_fail_count', 0) + 1
                pos['sell_last_attempt'] = int(time.time())

        else:

            # Balance still 0: try selling with estimated balance from entry data
            remaining = 1.0 - float(pos.get('sold_pct', 0))
            entry_price = float(pos.get('entry_price', 0) or 0)
            entry_usd = float(pos.get('entry_usd_amount', 0) or 0)
            current_price = float(pos.get('current_price', entry_price))
            if remaining > 0 and entry_price > 0 and entry_usd > 0:
                # Try selling with estimated balance from entry data
                est_bal = (entry_usd * remaining) / entry_price
                log(f'  {sym}: balance api=0, selling est_bal={est_bal:.2f} (from entry)')
                ok, tx_id = execute_sell(chain, ca, round(est_bal, 6))
                if ok:
                    pos['sell_fail_count'] = 0
                else:
                    pos['sell_fail_count'] = pos.get('sell_fail_count', 0) + 1
                    pos['sell_last_attempt'] = int(time.time())
            else:
                # Truly dead: clean up
                log(f'  {sym}: balance=0, cleaning dead position')
                exit_pnl = (current_price - entry_price) / entry_price if entry_price > 0 else 0
                _save_trade_history(state, pos, current_price, exit_pnl, f'{reason}_dead', 0)
                del positions[ca]
                save_state(state)
                continue

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

            entry_usd = float(pos.get('entry_usd_amount', BUY_SIZE_USDT) or BUY_SIZE_USDT)
            token_remaining = (entry_usd * remaining) / entry_price if entry_price > 0 else 0

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
    # Clean up old buy_signals (older than 1 hour)
    now_ts = int(time.time())
    if 'buy_signals' in state:
        state['buy_signals'] = [s for s in state['buy_signals'] if now_ts - s.get('ts', 0) < 3600]


    save_state(state)  # persist command results immediately (cmd file already cleared)
    positions = state.get("positions", {})  # refresh after commands

    # WS health check: restart if dead (throttled to once per 60s)
    global _WS_CLIENT, _ws_last_restart
    if _WS_CLIENT is not None:
        # Check if WS thread is alive (try is_alive() method, fallback to _thread.is_alive())
        ws_alive = False
        try:
            if hasattr(_WS_CLIENT, 'is_alive') and callable(_WS_CLIENT.is_alive):
                ws_alive = _WS_CLIENT.is_alive()
            elif hasattr(_WS_CLIENT, '_thread') and _WS_CLIENT._thread:
                ws_alive = _WS_CLIENT._thread.is_alive()
        except Exception:
            ws_alive = False
        ws_authenticated = True
        try:
            auth_attr = getattr(
                _WS_CLIENT,
                'is_authenticated',
                getattr(_WS_CLIENT, 'is_ready', True),
            )
            ws_authenticated = auth_attr() if callable(auth_attr) else bool(auth_attr)
        except Exception:
            ws_authenticated = False
        if not ws_alive or not ws_authenticated:
            if time.time() - _ws_last_restart > 60:
                log('WS client unavailable, restarting...')
                try:
                    _WS_CLIENT.stop()
                except Exception:
                    pass
                try:
                    _WS_CLIENT = OkxDexWs()
                    started = _WS_CLIENT.start()
                    if not started:
                        log('WS unavailable, using REST fallback')
                        _WS_CLIENT = None
                    else:
                        log('WS client restarted')
                    _ws_last_restart = time.time()
                except Exception as e:
                    log(f'WS restart failed: {e}')
                    _WS_CLIENT = None
                    _ws_last_restart = time.time()
            else:
                log('WS client dead, restart throttled (wait 60s)')

    # Existing positions must have a dedicated low-latency price feed before
    # the event-driven tracker wait begins.
    sync_ws_price_subscriptions(positions)
    trades = fetch_tracker(state)

    # Update held positions' current_price from WS price cache (immediate, no REST call)
    _now = time.time()
    for _pos_key, _pos in positions.items():
        _pos_ca = (_pos.get('token_ca') or _pos_key or '').lower()
        _cached = _price_cache.get(_pos_ca)
        if _cached:
            _price, _ts = _cached
            if _now - _ts < 30:  # cache valid for 30s for position updates
                _pos['current_price'] = _price

    positions = state.get('positions', {})



    if trades:

        positions = process_new_trades(trades, state, wallets)



    # A new position can be created by the signal just consumed. Subscribe
    # before the next price event so the fast-exit path starts immediately.
    sync_ws_price_subscriptions(positions)
    positions = check_positions(positions, state)

    # Remove feeds for positions that were fully closed and retain feeds for
    # positions that are still awaiting an exit.
    sync_ws_price_subscriptions(positions)

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

    # Auto-archive: decay backups, archive closed positions
    if _ARCHIVE_OK:
        try:
            _ar = auto_archive(state_file=STATE_FILE)
            if _ar:
                log(f'[ARCHIVE] {_ar}')
        except Exception:
            pass

    return positions





def main():

    mode = 'DRY-RUN' if DRY_RUN else 'LIVE'

    load_runtime_config()
    write_runtime_status('starting')

    log(f'=== SM Monitor v3.3 [{mode}] ===')
    log(f'Risk: per-trade={RISK_PCT:.0%} of account, SL={SL_PCT_BASE:.0%}, daily_limit={MAX_DAILY_LOSS_PCT:.0%}, monthly_limit={MAX_MONTHLY_LOSS_PCT:.0%}')
    log(f'Position: min=${MIN_BUY_SIZE}, max=${MAX_BUY_SIZE}')
    log(f'BSC market data: OKX V6 REST; BAW executor: {"enabled" if BSC_BAW_ENABLED else "paused"}')
    log(f'OKX REST chains: {", ".join(f"{CHAIN_LABELS[name]}({CHAIN_INDEXES[name]})" for name in CHAIN_NAMES)}')



    state = load_state()

    load_trends()  #

    state = reconcile_wallet(state)  # ?

    save_state(state)

    wallets = load_wallets()

    # Use direct OKX OnchainOS REST V6 for signals and prices.  The WS client
    # is intentionally not started while the account is not whitelisted.
    global _WS_CLIENT, _REST_CLIENT, _ws_sl_lock
    _ws_sl_lock = threading.Lock()
    _WS_CLIENT = None
    try:
        _REST_CLIENT = OkxDexRest(chain_indexes=REST_CHAIN_INDEXES)
        if _REST_CLIENT.enabled:
            log('OKX V6 REST signal/price source started')
            write_runtime_status('running', state, 'OKX V6 REST primary')
        else:
            log('OKX V6 REST credentials unavailable, using OnchainOS fallback')
            write_runtime_status('running', state, 'OnchainOS secondary fallback')
    except Exception as e:
        log(f'OKX V6 REST start failed: {e}, using OnchainOS fallback')
        _REST_CLIENT = None
        write_runtime_status('running', state, 'OnchainOS secondary fallback')


    runtime_stop, runtime_thread = start_runtime_heartbeat(state)

    if ONCE:

        run_once(state, wallets)

        runtime_stop.set()
        runtime_thread.join(timeout=1)
        write_runtime_status('stopped', state, 'once complete')

        return



    try:

        # Initialize mtime tracking
        global _STATE_FILE_MTIME
        try:
            _STATE_FILE_MTIME = os.path.getmtime(STATE_FILE)
        except:
            _STATE_FILE_MTIME = 0

        while True:

            try:
                run_once(state, wallets)
                write_runtime_status('running', state)
            except Exception as e:
                import traceback
                log(f'ERROR in run_once: {e}')
                write_runtime_status('error', state, str(e))
                traceback.print_exc()
                try:
                    save_state(state)
                    save_wallets(wallets)
                except:
                    pass
                try:
                    wallets = load_wallets()
                except:
                    pass
                log(f'Retrying in {TRACKER_POLL_SEC * 3}s...')
                time.sleep(TRACKER_POLL_SEC * 3)
                continue

            log(f'--- REST poll again in {TRACKER_POLL_SEC}s ---')
            time.sleep(TRACKER_POLL_SEC)

    except KeyboardInterrupt:

        log('Stopped by user')

        runtime_stop.set()
        runtime_thread.join(timeout=1)

        write_runtime_status('stopped', state, 'keyboard interrupt')

        if _WS_CLIENT:
            try:
                _WS_CLIENT.stop()
                log('WS data source stopped')
            except:
                pass

        save_state(state)

        save_wallets(wallets)



if __name__ == '__main__':

    main()
