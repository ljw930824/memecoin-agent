# -*- coding: utf-8 -*-
"""
signal_listener.py - Real-time Smart Money signal listener
Runs as background process (pythonw.exe)
Polls API every 20 seconds, pushes new signals via Telegram
Auto-executes strong signals (score>=50) after safety check
v1.2 - SSL cert fix for Windows Python 3.10
"""
import json, os, ssl, sys, time, traceback
from datetime import datetime, timezone, timedelta

# Import paper trading module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from paper_trading import log_signal, simulate_buy, would_buy_signal
    PAPER_TRADING_AVAILABLE = True
except ImportError:
    PAPER_TRADING_AVAILABLE = False
    def log_signal(sig, action='OBSERVE'): pass
    def simulate_buy(sig, invest_usd): pass
    def would_buy_signal(sig, min_score=50): return False, 'Module not available'

# pythonw.exe has no stdout - wrap safely
if sys.platform == 'win32':
    try:
        if sys.stdout:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

DATA_DIR   = os.path.expanduser('~/.qclaw/workspace/data')
QUEUE_FILE = os.path.join(DATA_DIR, 'signal-queue.json')
SEEN_FILE  = os.path.join(DATA_DIR, 'seen_signal_ids.json')
STATE_FILE = os.path.join(DATA_DIR, 'smart-money-state.json')
LOG_FILE   = os.path.join(DATA_DIR, 'listener.log')
ERROR_LOG  = os.path.join(DATA_DIR, 'listener-error.log')
os.makedirs(DATA_DIR, exist_ok=True)

ONCHAINOS   = r'C:\Users\dell\.local\bin\onchainos.exe'
WALLET_ADDR = '77BP1JzBARGaQ8eJWj6B1RYvaB4zRxU7Nx7BDYdgLCAa'
SOL_USDT    = 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB'
SOL_CHAIN   = '501'

TG_TOKEN   = '8781701155:AAGdKt0oZm5bfaEY39ItcGkiW4phMfYkfbI'
TG_CHAT_ID = '821225400'

SCAN_INTERVAL_SEC = 20
AUTO_BUY_SCORE = 999  # DISABLED - Require manual confirmation after backtesting
NOTIFY_SCORE = 40
MAX_POSITIONS = 3
MIN_INVEST_USD = 5.0

# v3.2 scoring constants
MIN_SM_ENTRIES          = 2      # Min distinct SM wallets buying
MAX_SPREAD_PCT          = 0.05   # Max spread between alert and current price
CHASE_PUMP_PCT          = 0.15   # If already pumped >15% from alert, skip
STALE_PENALTY_START_MIN = 60     # Signals older than 1h start losing score
STALE_PENALTY_MAX_MIN   = 180    # Max penalty at 3h old

def log(msg):
    ts = datetime.now(timezone(timedelta(hours=8))).strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    try:
        print(line)
    except Exception:
        pass
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

def log_error(msg):
    ts = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] ERROR: {msg}'
    with open(ERROR_LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

def notify(msg):
    if not TG_TOKEN:
        return
    try:
        import urllib.request
        url = f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage'
        data = json.dumps({'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'}).encode()
        req  = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as e:
        log_error(f'Notify error: {str(e)[:60]}')

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'positions': {}, 'cooldowns': {}}

def save_state(s):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(s, f, indent=2, ensure_ascii=False)

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, 'r', encoding='utf-8') as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(SEEN_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(seen), f)

def ocoin_run(args, timeout=30):
    cmd = [ONCHAINOS] + args
    try:
        import subprocess
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=timeout, encoding='utf-8', errors='replace')
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except Exception as e:
        return '', str(e), 999

def get_usdt_balance():
    out, err, code = ocoin_run(['wallet', 'balance'], timeout=20)
    if code == 0:
        try:
            d = json.loads(out)
            details = d.get('data', {}).get('details', d.get('details', []))
            for detail in details:
                for ta in detail.get('tokenAssets', []):
                    if str(ta.get('chainIndex', '')) != SOL_CHAIN:
                        continue
                    if ta.get('tokenAddress', '').lower() == SOL_USDT.lower():
                        return float(ta.get('balance', 0))
        except Exception:
            pass
    return 0.0

def get_token_balance(ca):
    out, err, code = ocoin_run(['wallet', 'balance'], timeout=20)
    if code == 0:
        try:
            d = json.loads(out)
            details = d.get('data', {}).get('details', d.get('details', []))
            for detail in details:
                for ta in detail.get('tokenAssets', []):
                    if str(ta.get('chainIndex', '')) != SOL_CHAIN:
                        continue
                    if ta.get('tokenAddress', '').lower() == ca.lower():
                        return float(ta.get('balance', 0)), int(ta.get('rawBalance', 0)), int(ta.get('decimal', 6))
        except Exception:
            pass
    return 0.0, 0, 6

def swap_execute(from_token, to_token, amount, slippage='1.0'):
    out, err, code = ocoin_run([
        'swap', 'execute',
        '--from', from_token, '--to', to_token,
        '--chain', 'Solana', '--wallet', WALLET_ADDR,
        '--slippage', slippage, '--readable-amount', str(amount),
    ], timeout=120)
    if code != 0:
        return False, err or out[:100]
    try:
        d = json.loads(out)
        if d.get('ok'):
            tx = d.get('data', {}).get('swapTxHash', d.get('data', {}).get('txHash', 'unknown'))
            return True, tx
        return False, str(d.get('error', out[:100]))
    except Exception:
        return False, err or out[:100]

def swap_execute_raw(from_token, to_token, amount_raw, slippage='1.0'):
    out, err, code = ocoin_run([
        'swap', 'execute',
        '--from', from_token, '--to', to_token,
        '--chain', 'Solana', '--wallet', WALLET_ADDR,
        '--slippage', slippage, '--amount', str(int(amount_raw)),
    ], timeout=120)
    if code != 0:
        return False, err or out[:100]
    try:
        d = json.loads(out)
        if d.get('ok'):
            tx = d.get('data', {}).get('swapTxHash', d.get('data', {}).get('txHash', 'unknown'))
            return True, tx
        return False, str(d.get('error', out[:100]))
    except Exception:
        return False, err or out[:100]

def preflight_safety_check(ca, invest_usdt):
    out, err, code = ocoin_run([
        'swap', 'quote',
        '--chain', 'Solana',
        '--from', SOL_USDT,
        '--to',   ca,
        '--readable-amount', str(min(invest_usdt, 1.0)),
    ], timeout=30)
    if code != 0:
        return False, 'quote_failed'
    try:
        d = json.loads(out)
        if not (d.get('ok') and d.get('data')):
            return False, 'no_quote_data'
        data = d['data'][0]
        to_token = data.get('toToken', {})
        if to_token.get('isHoneyPot', False):
            return False, 'HONEYPOT'
        tax = float(to_token.get('taxRate', 0))
        if tax > 5.0:
            return False, f'TAX_{tax}%'
        impact = float(data.get('priceImpactPercent', 0))
        if impact > 10.0:
            return False, f'IMPACT_{impact}%'
        routers = data.get('dexRouterList', [])
        if not routers:
            return False, 'NO_ROUTERS'
        max_pct = max([float(r.get('dexProtocol', {}).get('percent', 0)) for r in routers])
        if max_pct < 50:
            return False, f'LOW_LIQUIDITY_{max_pct}%'
        return True, ''
    except Exception as e:
        return False, f'exception_{e}'

def buy_token(ca, ticker, amount_usdt, entry_price):
    log(f'BUY {ticker} | ${amount_usdt:.2f}')
    safe, reason = preflight_safety_check(ca, amount_usdt)
    if not safe:
        log(f'  SAFETY FAIL: {reason}')
        notify(f'&#x26A0; <b>{ticker} SAFETY FAIL</b>\nReason: {reason}')
        return False, reason
    log('  Safety OK')
    for attempt in range(1, 4):
        success, tx = swap_execute(SOL_USDT, ca, amount_usdt)
        if success:
            log(f'  SUCCESS | TX: {tx}')
            return True, tx
        log(f'  Attempt {attempt} failed: {tx}')
        time.sleep(8)
    notify(f'&#x1F6A8; <b>{ticker} BUY FAILED</b>\n3 attempts exhausted')
    return False, ''

def sell_token(ca, ticker, pct=1.0, reason=''):
    bal, raw_bal, dec = get_token_balance(ca)
    if bal <= 0:
        return False, 'no_balance'
    if pct >= 0.99:
        sell_raw = int(raw_bal * pct)
        if sell_raw <= 0:
            return False, 'zero'
        log(f'SELL {ticker} | ALL raw={sell_raw} ({reason})')
        for attempt in range(1, 4):
            success, tx = swap_execute_raw(ca, SOL_USDT, sell_raw, slippage='2.0')
            if success:
                log(f'  SUCCESS | TX: {tx}')
                return True, tx
            log(f'  Attempt {attempt} failed: {tx}')
            time.sleep(5)
    else:
        import math
        sell_amt = math.floor(bal * pct * (10 ** dec)) / (10 ** dec)
        if sell_amt <= 0:
            return False, 'zero'
        log(f'SELL {ticker} | {sell_amt} ({reason})')
        for attempt in range(1, 4):
            success, tx = swap_execute(ca, SOL_USDT, sell_amt, slippage='2.0')
            if success:
                log(f'  SUCCESS | TX: {tx}')
                return True, tx
            log(f'  Attempt {attempt} failed: {tx}')
            time.sleep(5)
    notify(f'&#x1F6A8; <b>SELL FAILED</b>\n{ticker} | {reason}')
    return False, ''

def is_pumpfun_address(ca):
    # 移除过滤 - pump.fun 是 Solana 主流发射平台，允许交易
    return False

def score_signal(sig):
    """Calculate signal score from API fields - v3.2 with spread/chase/stale filtering."""
    score = 0
    reasons = []

    # Smart Money Count
    smc = sig.get('smartMoneyCount', 0)
    if smc >= 8:   score += 40; reasons.append(f'SM={smc}(high)')
    elif smc >= 5: score += 25; reasons.append(f'SM={smc}(med)')
    elif smc >= 3: score += 12; reasons.append(f'SM={smc}(low)')
    elif smc >= MIN_SM_ENTRIES:
        score += 5; reasons.append(f'SM={smc}(min)')
    else:
        return 0  # INSUFFICIENT_SM

    # Direction
    direction = sig.get('direction', '')
    if direction == 'buy':     score += 10; reasons.append('buy')
    elif direction == 'sell':   return 0  # SELL-skip

    sc = sig.get('signalCount', 0)
    if sc >= 15:  score += 8; reasons.append(f'signals={sc}')
    elif sc >= 5: score += 3; reasons.append(f'signals={sc}')

    # Tags
    tags = sig.get('tokenTag', {}) or {}
    for cat, tag_list in tags.items():
        for t in (tag_list or []):
            tn = t.get('tagName', '')
            if tn == 'Smart Money Add Holdings':  score += 12; reasons.append('SM+Holdings')
            elif tn == 'Whale Buy':                score += 15; reasons.append('WhaleBuy')
            elif tn == 'DEX Paid':                 score += 3;  reasons.append('DEXpaid')
            elif tn == 'Smart Money Reduce':       score -= 18; reasons.append('SM-Reduce')
            elif tn == 'Whale Sell':               return 0  # WhaleSell

    # Market cap
    mc = float(sig.get('alertMarketCap', 0) or 0)
    if mc >= 1_000_000:  score += 10; reasons.append(f'mcap=${mc/1e6:.1f}M')
    elif mc >= 100_000:  score += 5;  reasons.append(f'mcap=${mc/1e3:.0f}K')
    elif mc > 0:         score -= 5;  reasons.append('mcap<100K')
    else: return 0

    # Price momentum + Spread check (v3.2)
    current_price = float(sig.get('currentPrice', 0) or 0)
    alert_price   = float(sig.get('alertPrice', 0) or 0)
    if alert_price > 0 and current_price > 0:
        pump_pct = (current_price - alert_price) / alert_price
        # v3.2: Spread check
        if abs(pump_pct) > MAX_SPREAD_PCT:
            return 0  # SPREAD_TOO_HIGH
        if pump_pct < -0.10:
            score -= 15; reasons.append(f'dumped({pump_pct*100:.1f}%)')
        elif pump_pct < -0.05:
            score += 5;  reasons.append(f'dip_entry({pump_pct*100:.1f}%)')
        elif pump_pct <= 0.03:
            score += 8;  reasons.append('early_entry')
        elif pump_pct <= CHASE_PUMP_PCT:
            score += 3;  reasons.append(f'pump+{pump_pct*100:.1f}%')
        elif pump_pct <= 0.25:
            score -= 8;  reasons.append(f'chase_warn+{pump_pct*100:.1f}%')
        else:
            return 0  # CHASE_SKIP

    # Status
    status = sig.get('status', '')
    if status == 'active':
        score += 15; reasons.append('ACTIVE')
    elif status == 'timeout':
        tf = sig.get('timeFrame', 0)
        if tf < 3600000:
            score += 5; reasons.append('fresh_timeout')
        else:
            score -= 10; reasons.append('old_timeout')
    elif status in ('exitRate', 'outDecline'):
        return 0  # exiting

    # v3.2: Staleness penalty
    created_at = sig.get('createdAt', 0) or sig.get('signalTriggerTime', 0)
    if created_at:
        import time
        now_ts = time.time()
        age_min = (now_ts * 1000 - created_at) / 60000
        if age_min > STALE_PENALTY_START_MIN:
            staleness = min(1.0, (age_min - STALE_PENALTY_START_MIN) /
                           (STALE_PENALTY_MAX_MIN - STALE_PENALTY_START_MIN))
            penalty = int(staleness * 15)
            score -= penalty

    return max(0, min(100, score))

def make_ssl_context():
    """Create SSL context compatible with Windows Python 3.10."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()

def fetch_signals():
    headers = {'Content-Type': 'application/json'}
    signals = []
    ssl_context = make_ssl_context()
    
    for chain_id, chain_name in [('56', 'BSC'), ('CT_501', 'Solana')]:
        try:
            import urllib.request
            url = 'https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai'
            body = json.dumps({
                'smartSignalType': '',
                'page': 1,
                'pageSize': 50,
                'chainId': chain_id
            }).encode('utf-8')
            req = urllib.request.Request(url, data=body, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=15, context=ssl_context) as r:
                d = json.loads(r.read().decode('utf-8'))
                items = []
                if isinstance(d, list):
                    items = d
                elif isinstance(d, dict):
                    code = d.get('code', '')
                    if (code == '000000' or d.get('ok')) and d.get('data'):
                        if isinstance(d['data'], list):
                            items = d['data']
                        elif isinstance(d['data'], dict):
                            items = d['data'].get('data', [])
                for item in items:
                    if isinstance(item, dict):
                        item['chain'] = chain_id
                        item['chain_name'] = chain_name
                        item['ca'] = item.get('contractAddress', '')
                        item['sigId'] = str(item.get('signalId', ''))  # Copy signalId to sigId for compatibility
                        item['score'] = score_signal(item)
                        signals.append(item)
        except Exception as e:
            err_msg = str(e)
            if 'No such file or directory' in err_msg:
                log_error(f'SSL cert missing. Run: pip install certifi')
                log(f'API error ({chain_name}): SSL_CERT_MISSING - install certifi')
            else:
                log(f'API error ({chain_name}): {err_msg[:80]}')
    return signals

def process_signal(sig):
    sid    = str(sig.get('signalId', ''))
    ticker = sig.get('ticker', '?')
    ca     = sig.get('contractAddress', '')
    score  = sig.get('score', 0)
    chain  = sig.get('chain', '')
    ep     = float(sig.get('currentPrice') or sig.get('alertPrice') or 0)
    mc     = float(sig.get('alertMarketCap', 0) or 0)
    sm     = sig.get('smartMoneyCount', 0)

    log(f'NEW SIGNAL | {ticker} | {chain} | score={score} | MC=${mc/1000:.0f}K | SM={sm}')

    if score < NOTIFY_SCORE:
        log(f'  -> Score < {NOTIFY_SCORE}, ignoring')
        return False

    msg = (
        f'&#x1F6A8; <b>New Smart Money Signal</b>\n\n'
        f'<b>{ticker}</b> ({chain})\n'
        f'Score: <b>{score}</b> | SM: {sm} wallets\n'
        f'MC: ${mc/1000000:.2f}M\n'
        f'Price: ${ep}\n'
        f'CA: <code>{ca}</code>'
    )

    if chain == 'CT_501':
        state = load_state()
        sol_pos = {c: p for c, p in state.get('positions', {}).items()
                   if str(p.get('chain_id', '')) == SOL_CHAIN}
        if ca in sol_pos:
            log('  -> Already in position, skipping')
            return False
        if len(sol_pos) >= MAX_POSITIONS:
            log('  -> Max positions reached, notifying only')
            notify(msg + '\n\n<i>Max positions reached. Manual entry required.</i>')
            return False

        # pump.fun check removed - pump.fun is main Solana launchpad

        # Paper trading mode - log and simulate instead of real trading
        if AUTO_BUY_SCORE >= 999:
            # Log signal for backtesting
            log_signal(sig, 'OBSERVE')
            
            # Check if would buy (for simulation)
            would_buy, reason = would_buy_signal(sig, min_score=50)
            if would_buy:
                log_signal(sig, 'WOULD_BUY')
                usdt_bal = get_usdt_balance()
                invest = usdt_bal * (0.45 if score >= 55 else 0.35 if score >= 50 else 0.3)
                invest = max(min(invest, usdt_bal * 0.5), MIN_INVEST_USD)
                simulate_buy(sig, invest)
                notify(msg + f'\n\n<i>[PAPER TRADING] Would buy ${invest:.2f}</i>\nReason: {reason}')
            else:
                log_signal(sig, 'SKIPPED')
                notify(msg + f'\n\n<i>[PAPER TRADING] Skipped</i>\nReason: {reason}')
            return False
        
        # Real trading mode (AUTO_BUY_SCORE < 999)
        if score >= AUTO_BUY_SCORE:
            usdt_bal = get_usdt_balance()
            if usdt_bal < MIN_INVEST_USD:
                notify(msg + '\n\n<i>Balance too low for auto-buy.</i>')
                return False

            safe, reason = preflight_safety_check(ca, 5.0)
            if not safe:
                log(f'  -> SAFETY FAIL: {reason}')
                notify(msg + f'\n\n&#x274C; <b>AUTO-BUY BLOCKED</b>\nReason: {reason}')
                return False

            notify(msg + '\n\n&#x2705; Safety OK, auto-buying...')
            invest = usdt_bal * (0.45 if score >= 55 else 0.35 if score >= 50 else 0.3)
            invest = max(min(invest, usdt_bal * 0.5), MIN_INVEST_USD)

            success, tx = buy_token(ca, ticker, invest, ep)
            if success:
                actual_ep = ep
                state['positions'][ca] = {
                    'chain': 'Solana', 'chain_id': SOL_CHAIN,
                    'ticker': ticker, 'ca': ca,
                    'entry_price': actual_ep,
                    'invest_amount': invest,
                    'amount': 0,
                    'sl_price': round(actual_ep * 0.92, 12),
                    'tp_price': round(actual_ep * 1.12, 12),
                    'pnl_pct': 0, 'pnl_usdt': 0,
                    'entry_time': datetime.now(timezone(timedelta(hours=8))).isoformat(),
                    'sig_id': sig.get('sigId') or sig.get('signalId', ''),
                    'score': score,
                    'reasons': sig.get('reasons', []),
                    'partial_tp_10': False,
                    'partial_tp_15': False,
                    'breakeven_done': False,
                }
                save_state(state)
                notify(f'&#x2705; <b>{ticker} BOUGHT</b>\nInvest: ${invest:.2f}\nTX: {tx}')
                return True
            else:
                notify(f'&#x274C; <b>{ticker} BUY FAILED</b>\n{tx}')
                return False
        else:
            notify(msg + '\n\n<i>Score 40-49. Notify only, waiting for user confirmation.</i>')
            return False
    else:
        notify(msg + '\n\n<i>BSC signal. Please check BAW CLI.</i>')
        return False

def main():
    log('='*50)
    log('SIGNAL LISTENER v1.2 STARTED (SSL-fixed)')
    log(f'Scan interval: {SCAN_INTERVAL_SEC}s')
    log(f'Auto-buy: {AUTO_BUY_SCORE}+ | Notify: {NOTIFY_SCORE}+')
    log('='*50)

    seen = load_seen()

    while True:
        try:
            signals = fetch_signals()
            new_count = 0
            for sig in signals:
                sid = str(sig.get('sigId') or sig.get('signalId', ''))
                if not sid or sid in seen:
                    continue
                seen.add(sid)
                if process_signal(sig):
                    new_count += 1
            if new_count > 0:
                save_seen(seen)

            # Save current signals to queue for execute scripts
            try:
                with open(QUEUE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(signals, f, indent=2, ensure_ascii=False)
            except Exception as e:
                log_error(f'Save queue failed: {str(e)[:60]}')

            time.sleep(SCAN_INTERVAL_SEC)
        except KeyboardInterrupt:
            log('Interrupted by user, exiting')
            save_seen(seen)
            break
        except Exception as e:
            log_error(f'Main loop: {str(e)[:100]}')
            time.sleep(SCAN_INTERVAL_SEC)

if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        log_error(f'FATAL: {str(e)}')
        log_error(traceback.format_exc())
        sys.exit(1)
