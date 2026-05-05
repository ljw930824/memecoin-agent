# -*- coding: utf-8 -*-
import json, math, os, sys, time, subprocess
from datetime import datetime, timezone, timedelta

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DATA_DIR   = os.path.expanduser('~/.qclaw/workspace/data')
STATE_FILE = os.path.join(DATA_DIR, 'smart-money-state.json')
QUEUE_FILE = os.path.join(DATA_DIR, 'signal-queue.json')
RETRY_LOG  = os.path.join(DATA_DIR, 'retry-log.txt')
TRADE_LOG  = os.path.join(DATA_DIR, 'trade-log.json')
os.makedirs(DATA_DIR, exist_ok=True)

ONCHAINOS   = r'C:\Users\dell\.local\bin\onchainos.exe'
WALLET_ADDR = '77BP1JzBARGaQ8eJWj6B1RYvaB4zRxU7Nx7BDYdgLCAa'
SOL_USDT    = 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB'
SOL_CHAIN   = '501'
SOLANA_RPC  = 'https://api.mainnet-beta.solana.com'
MAX_POSITIONS   = 3
MIN_INVEST_USD = 5.0
STOP_LOSS_PCT  = -0.08
TAKE_PROFIT_PCT = 0.12
COOLDOWN_SL    = 12
COOLDOWN_TP    = 6

# v3.2 Risk Management
MAX_DAILY_LOSS_PCT      = 0.15   # Max daily drawdown -15%
CONSECUTIVE_SL_FREEZE   = 3      # 3 consecutive SL -> freeze trading
FREEZE_DURATION_HOURS   = 2      # Freeze duration
TG_TOKEN   = os.environ.get('TG_BOT_TOKEN', '8781701155:AAGdKt0oZm5bfaEY39ItcGkiW4phMfYkfbI')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID', '821225400')

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'positions': {}, 'cooldowns': {}, 'last_signal_ids': []}

def save_state(s):
    import shutil
    if os.path.exists(STATE_FILE):
        shutil.copy2(STATE_FILE, STATE_FILE.replace('.json', '_bak.json'))
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(s, f, indent=2, ensure_ascii=False)

def notify(msg):
    if not TG_TOKEN:
        return
    try:
        import urllib.request
        url = 'https://api.telegram.org/bot' + TG_TOKEN + '/sendMessage'
        data = json.dumps({'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'}).encode()
        req  = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception:
        pass

def log_trade(entry):
    log = []
    if os.path.exists(TRADE_LOG):
        with open(TRADE_LOG, 'r', encoding='utf-8') as f:
            log = json.load(f)
    log.append(entry)
    if len(log) > 5000:
        log = log[-5000:]
    with open(TRADE_LOG, 'w', encoding='utf-8') as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

def log_retry(ticker, action, reason, attempt):
    ts = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
    entry = '[' + ts + '] SOL | ' + ticker + ' | ' + action + ' | ' + reason + ' | attempt #' + str(attempt) + chr(10)
    with open(RETRY_LOG, 'a', encoding='utf-8') as f:
        f.write(entry)

# Note: pump.fun addresses may fail onchainos base58 validation.
# We no longer pre-skip them; let get_quote() fail naturally if unsupported.
def is_pumpfun_address(ca):
    return False

OKX_ENV = os.environ.copy()
OKX_ENV['OKX_PROD_API_KEY'] = OKX_ENV.get('OKX_PROD_API_KEY') or OKX_ENV.get('OKX_API_KEY', '***REMOVED***')
OKX_ENV['OKX_PROD_SECRET_KEY'] = OKX_ENV.get('OKX_PROD_SECRET_KEY') or OKX_ENV.get('OKX_SECRET_KEY', '***REMOVED***')
OKX_ENV['OKX_PROD_PASSPHRASE'] = OKX_ENV.get('OKX_PROD_PASSPHRASE') or OKX_ENV.get('OKX_PASSPHRASE', '***REMOVED***')
OKX_ENV['OKX_API_KEY'] = OKX_ENV['OKX_PROD_API_KEY']
OKX_ENV['OKX_SECRET_KEY'] = OKX_ENV['OKX_PROD_SECRET_KEY']
OKX_ENV['OKX_PASSPHRASE'] = OKX_ENV['OKX_PROD_PASSPHRASE']

def ocoin_run(args, timeout=90, retries=1):
    """Run onchainos command with optional retry on failure."""
    cmd = [ONCHAINOS] + args
    for attempt in range(max(1, retries)):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=timeout, encoding='utf-8', errors='replace',
                                    env=OKX_ENV)
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            code = result.returncode
            # Retry on non-zero exit or empty stdout (transient failure)
            if code == 0 and stdout:
                return stdout, stderr, code
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return stdout, stderr, code
        except subprocess.TimeoutExpired:
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            return '', 'timeout', 998
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return '', str(e), 999
    return '', 'max_retries', 999

def rpc_call(method, params):
    payload = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}
    try:
        import urllib.request
        req = urllib.request.Request(
            SOLANA_RPC,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print('  [WARN] RPC ' + method + ' failed: ' + str(e))
        return None

def get_token_balance_rpc(mint):
    result = rpc_call('getTokenAccountsByOwner', [
        WALLET_ADDR, {'mint': mint}, {'encoding': 'jsonParsed'}
    ])
    if not result:
        return 0.0, 0, 6
    vals = result.get('result', {}).get('value', [])
    total, dec = 0.0, 6
    for v in vals:
        info = v.get('account', {}).get('data', {}).get('parsed', {}).get('info', {})
        ta   = info.get('tokenAmount', {})
        total += float(ta.get('uiAmount', 0))
        dec  = int(ta.get('decimals', 6))
    raw_total = int(total * (10 ** dec))
    return total, raw_total, dec

def get_usdt_balance():
    """Get USDT balance with retry + RPC fallback."""
    for attempt in range(3):
        out, err, code = ocoin_run(['wallet', 'balance'], timeout=25)
        if code == 0 and out:
            try:
                d = json.loads(out)
                details = d.get('data', {}).get('details', d.get('details', []))
                for detail in details:
                    for ta in detail.get('tokenAssets', []):
                        if str(ta.get('chainIndex', '')) != SOL_CHAIN:
                            continue
                        if ta.get('tokenAddress', '').lower() == SOL_USDT.lower():
                            bal = float(ta.get('balance', 0))
                            if bal > 0:
                                return bal
                return 0.0
            except Exception:
                pass
        if attempt < 2:
            time.sleep(3 * (attempt + 1))
    # Fallback: RPC
    bal, _, _ = get_token_balance_rpc(SOL_USDT)
    return bal

def get_token_balance(ca):
    """Get token balance with retry + RPC fallback."""
    for attempt in range(3):
        out, err, code = ocoin_run(['wallet', 'balance'], timeout=25)
        if code == 0 and out:
            try:
                d = json.loads(out)
                details = d.get('data', {}).get('details', d.get('details', []))
                for detail in details:
                    for ta in detail.get('tokenAssets', []):
                        if str(ta.get('chainIndex', '')) != SOL_CHAIN:
                            continue
                        if ta.get('tokenAddress', '').lower() == ca.lower():
                            bal = float(ta.get('balance', 0))
                            raw = int(ta.get('rawBalance', 0))
                            dec = int(ta.get('decimal', 6))
                            return bal, raw, dec
                return 0.0, 0, 6
            except Exception:
                pass
        if attempt < 2:
            time.sleep(3 * (attempt + 1))
    return get_token_balance_rpc(ca)

def get_quote(from_token, to_token, amount, chain='Solana'):
    """Get swap quote with retry logic."""
    for attempt in range(3):
        out, err, code = ocoin_run([
            'swap', 'quote',
            '--chain', chain,
            '--from', from_token,
            '--to',   to_token,
            '--readable-amount', str(amount),
        ], timeout=30)
        if code == 0 and out:
            try:
                d = json.loads(out)
                if d.get('ok') and d.get('data'):
                    data = d['data'][0]
                    to_amt = float(data.get('toTokenAmount', 0))
                    if to_amt > 0:
                        return to_amt, float(data.get('fromTokenAmount', 0)), data.get('router', '')
            except Exception:
                pass
        if attempt < 2:
            time.sleep(2 * (attempt + 1))
    return 0, 0, ''

def get_price_usd(ca):
    """Get token price in USD with retry logic."""
    for attempt in range(3):
        out, err, code = ocoin_run([
            'swap', 'quote',
            '--chain', 'Solana',
            '--from', SOL_USDT,
            '--to',   ca,
            '--readable-amount', '1.0',
        ], timeout=30)
        if code == 0 and out:
            try:
                d = json.loads(out)
                if d.get('ok') and d.get('data'):
                    price = float(d['data'][0]['toToken'].get('tokenUnitPrice', 0))
                    if price > 0:
                        return price
            except Exception:
                pass
        if attempt < 2:
            time.sleep(2 * (attempt + 1))
    return 0.0

def swap_execute(from_token, to_token, amount, chain='Solana', slippage='1.0'):
    args = [
        'swap', 'execute',
        '--from', from_token,
        '--to',   to_token,
        '--chain', chain,
        '--wallet', WALLET_ADDR,
        '--slippage', slippage,
        '--readable-amount', str(amount),
    ]
    out, err, code = ocoin_run(args, timeout=120)
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

def swap_execute_raw(from_token, to_token, amount_raw, chain='Solana', slippage='1.0'):
    """Execute swap using raw amount (integer in smallest units). Zero-error for 100% sells."""
    args = [
        'swap', 'execute',
        '--from', from_token,
        '--to',   to_token,
        '--chain', chain,
        '--wallet', WALLET_ADDR,
        '--slippage', slippage,
        '--amount', str(int(amount_raw)),
    ]
    out, err, code = ocoin_run(args, timeout=120)
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

def preflight_safety_check(ca, ticker, invest_usdt):
    """Return (ok, reason, score) tuple. ok=True means safe to buy."""
    try:
        from safety_check import check_solana, format_safety_report
        score, passed, details, errors = check_solana(ca, invest_usdt)
        report = format_safety_report(score, passed, details, errors)
        print('     ' + report.replace('\n', '\n     '))
        if not passed:
            reason = errors[0] if errors else f'SCORE_{score}'
            return False, reason, score
        return True, '', score
    except ImportError:
        # fallback: 基础检查
        out, err, code = ocoin_run(['swap', 'quote', '--chain', 'Solana',
            '--from', SOL_USDT, '--to', ca, '--readable-amount', str(min(invest_usdt, 1.0))], timeout=30)
        if code != 0:
            return False, 'quote_failed', 0
        try:
            d = json.loads(out)
            data = d['data'][0]
            to_token = data.get('toToken', {})
            if to_token.get('isHoneyPot', False):
                return False, 'HONEYPOT', 0
            tax = float(to_token.get('taxRate', 0) or 0)
            if tax > 10.0:
                return False, f'TAX_{tax}%', 0
            return True, '', 50
        except Exception:
            return False, 'exception', 0

def buy_token(ca, ticker, amount_usdt, entry_price):
    print('')
    print('  >> BUY ' + ticker + ' | $' + str(round(amount_usdt, 2)) + ' on Solana')
    safe, reason, score = preflight_safety_check(ca, ticker, amount_usdt)
    if not safe:
        print('     SAFETY CHECK FAILED: ' + reason + ' (score=' + str(score) + ')')
        notify('&#x26A0; <b>' + ticker + ' SAFETY FAIL</b>\nReason: ' + reason + ' | Score: ' + str(score))
        return False, reason
    print('     Safety OK (score=' + str(score) + ')')
    for attempt in range(1, 4):
        success, tx = swap_execute(SOL_USDT, ca, amount_usdt)
        if success:
            print('     SUCCESS | TX: ' + tx)
            return True, tx
        print('     Attempt ' + str(attempt) + ' failed: ' + tx)
        log_retry(ticker, 'BUY', tx, attempt)
        time.sleep(8)
    notify('&#x1F6A8; <b>Solana BUY FAILED</b>\n' + ticker + '\n3 attempts exhausted. Signal missed.')
    return False, ''

def sell_token(ca, ticker, pct=1.0, reason=''):
    bal, raw_bal, dec = get_token_balance(ca)
    if bal <= 0:
        return False, 'no_balance'
    if pct >= 0.99:
        # 100% sell: use raw amount for zero error
        sell_raw = int(raw_bal * pct)
        if sell_raw <= 0:
            return False, 'zero'
        print('')
        print('  >> SELL ' + ticker + ' | ALL (raw=' + str(sell_raw) + ') (' + reason + ')')
        for attempt in range(1, 4):
            success, tx = swap_execute_raw(ca, SOL_USDT, sell_raw, slippage='2.0')
            if success:
                print('     SUCCESS | TX: ' + tx)
                return True, tx
            print('     Attempt ' + str(attempt) + ' failed: ' + tx)
            log_retry(ticker, 'SELL_' + reason, tx, attempt)
            time.sleep(8)
    else:
        # Partial sell: floor to decimal places to avoid oversell
        sell_amt = math.floor(bal * pct * (10 ** dec)) / (10 ** dec)
        if sell_amt <= 0:
            return False, 'zero'
        print('')
        print('  >> SELL ' + ticker + ' | ' + str(sell_amt) + ' (' + reason + ')')
        for attempt in range(1, 4):
            success, tx = swap_execute(ca, SOL_USDT, sell_amt, slippage='2.0')
            if success:
                print('     SUCCESS | TX: ' + tx)
                return True, tx
            print('     Attempt ' + str(attempt) + ' failed: ' + tx)
            log_retry(ticker, 'SELL_' + reason, tx, attempt)
            time.sleep(8)
    notify('&#x1F6A8; <b>Solana SELL FAILED</b>\n' + ticker + ' | ' + reason + '\n3 attempts exhausted!')
    return False, ''

def update_position_pnl(ca, current_price):
    pos = state['positions'].get(ca)
    if not pos:
        return
    ep = float(pos.get('entry_price', 0))
    if ep > 0 and current_price > 0:
        pnl = (current_price - ep) / ep
        pos['pnl_pct']  = pnl
        invest = float(pos.get('invest_amount', 0))
        pos['pnl_usdt'] = invest * pnl
        pos['current_price'] = current_price
        # Track peak price for trailing stop
        peak = float(pos.get('peak_price', ep))
        if current_price > peak:
            pos['peak_price'] = current_price

def check_position(ca, force_sell=False, force_sell_pct=1.0, force_reason=''):
    pos = state['positions'].get(ca)
    if not pos:
        return False
    ticker   = pos.get('ticker', '?')
    cur_p    = float(pos.get('current_price', 0))
    ep       = float(pos.get('entry_price', 0))
    sl_price = float(pos.get('sl_price', 0))
    tp_price = float(pos.get('tp_price', 0))
    pnl_pct  = pos.get('pnl_pct', 0)
    now      = datetime.now(timezone(timedelta(hours=8)))
    if ep == 0:
        return False
    if force_sell:
        print('  [*] Force selling ' + ticker + ' @ ' + str(cur_p) + ' (' + force_reason + ')')
        success, tx = sell_token(ca, ticker, force_sell_pct, force_reason)
        if success:
            record_close(ca, force_reason, pnl_pct)
            del state['positions'][ca]
            state['cooldowns'][ca] = (now + timedelta(hours=COOLDOWN_SL)).isoformat()
            save_state(state)
            return True
        return False
    if sl_price > 0 and cur_p <= sl_price:
        print('  [!] ' + ticker + ' SL HIT (' + str(round(pnl_pct*100,1)) + '%)')
        success, tx = sell_token(ca, ticker, 1.0, 'SL_HIT')
        if success:
            record_close(ca, 'SL_HIT', pnl_pct)
            del state['positions'][ca]
            state['cooldowns'][ca] = (now + timedelta(hours=COOLDOWN_SL)).isoformat()
            save_state(state)
            return True
        return False
    if tp_price > 0 and cur_p >= tp_price:
        print('  [!] ' + ticker + ' TP HIT (+' + str(round(pnl_pct*100,1)) + '%)')
        success, tx = sell_token(ca, ticker, 1.0, 'TP_HIT')
        if success:
            record_close(ca, 'TP_HIT', pnl_pct)
            del state['positions'][ca]
            state['cooldowns'][ca] = (now + timedelta(hours=COOLDOWN_TP)).isoformat()
            save_state(state)
            return True
        return False
    if pnl_pct >= 0.10 and not pos.get('partial_tp_10'):
        bal, _, _ = get_token_balance(ca)
        if bal > 0:
            print('  [*] ' + ticker + ' +' + str(round(pnl_pct*100,1)) + '% -> partial TP 50%')
            success, _ = sell_token(ca, ticker, 0.5, 'PARTIAL_TP10')
            if success:
                pos['partial_tp_10'] = True
                pos['sl_price'] = max(float(pos['sl_price']), ep)
    if pnl_pct >= 0.15 and not pos.get('partial_tp_15'):
        success, _ = sell_token(ca, ticker, 0.5, 'PARTIAL_TP15')
        if success:
            pos['partial_tp_15'] = True
            pos['sl_price'] = max(float(pos['sl_price']), ep * 1.03)
    if pnl_pct >= 0.08 and not pos.get('breakeven_done'):
        pos['sl_price'] = max(float(pos['sl_price']), ep)
        pos['breakeven_done'] = True
    # Trailing stop: after breakeven, track SL 2% below peak
    if pos.get('breakeven_done'):
        peak = float(pos.get('peak_price', ep))
        trailing_sl = peak * 0.98  # 2% below peak
        if trailing_sl > float(pos.get('sl_price', 0)):
            pos['sl_price'] = trailing_sl
    # Time-based exit: 24h no-movement reduce 50%, 48h force close
    entry_time_str = pos.get('entry_time', '')
    if entry_time_str:
        try:
            entry_dt = datetime.fromisoformat(entry_time_str)
            holding_hours = (now - entry_dt).total_seconds() / 3600
            if holding_hours >= 48:
                print('  [TIMEOUT] ' + ticker + ' held ' + str(int(holding_hours)) + 'h -> force close')
                success, _ = sell_token(ca, ticker, 1.0, 'TIMEOUT_48H')
                if success:
                    record_close(ca, 'TIMEOUT_48H', pnl_pct)
                    del state['positions'][ca]
                    save_state(state)
                    return True
            elif holding_hours >= 24 and abs(pnl_pct) < 0.03 and not pos.get('timeout_24h_done'):
                print('  [TIMEOUT] ' + ticker + ' held ' + str(int(holding_hours)) + 'h no movement -> reduce 50%')
                success, _ = sell_token(ca, ticker, 0.5, 'TIMEOUT_24H')
                if success:
                    pos['timeout_24h_done'] = True
                    pos['sl_price'] = max(float(pos.get('sl_price', 0)), ep)
        except Exception:
            pass

    # soldRatio-based exit: smart money reducing -> reduce position
    sold_ratio = pos.get('sold_ratio', 0)
    if sold_ratio > 0 and not pos.get('sold_ratio_triggered'):
        if sold_ratio >= 50:
            print(f'  [SOLD_RATIO] {ticker} soldRatio={sold_ratio:.0f}% -> FULL CLOSE')
            success, _ = sell_token(ca, ticker, 1.0, 'SOLD_RATIO_EXIT')
            if success:
                record_close(ca, 'SOLD_RATIO_EXIT', pnl_pct)
                del state['positions'][ca]
                state['cooldowns'][ca] = (now + timedelta(hours=COOLDOWN_SL)).isoformat()
                save_state(state)
                return True
        elif sold_ratio >= 30:
            print(f'  [SOLD_RATIO] {ticker} soldRatio={sold_ratio:.0f}% -> reduce 50%')
            success, _ = sell_token(ca, ticker, 0.5, 'SOLD_RATIO_REDUCE')
            if success:
                pos['sold_ratio_triggered'] = True
                pos['sl_price'] = max(float(pos.get('sl_price', 0)), float(pos.get('entry_price', 0)))
                save_state(state)
    return False

def record_close(ca, reason, pnl_pct):
    pos   = state['positions'].get(ca, {})
    entry = {
        'ts': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'chain': 'Solana',
        'ticker': pos.get('ticker', '?'),
        'ca': ca,
        'reason': reason,
        'entry_price': pos.get('entry_price', 0),
        'invest': pos.get('invest_amount', 0),
        'pnl_pct': pnl_pct,
        'pnl_usdt': pos.get('pnl_usdt', 0),
        'sig_id': pos.get('sig_id', ''),
        'score': pos.get('score', 0),
    }
    log_trade(entry)
    state.setdefault('last_signal_ids', [])
    state['last_signal_ids'].append(pos.get('sig_id', ''))
    if len(state['last_signal_ids']) > 50:
        state['last_signal_ids'] = state['last_signal_ids'][-50:]

    # v3.2: Track consecutive SL for freeze
    risk_check = state.setdefault("risk_check", {})
    if reason == "SL_HIT":
        risk_check["consecutive_sl"] = risk_check.get("consecutive_sl", 0) + 1
        if risk_check["consecutive_sl"] >= CONSECUTIVE_SL_FREEZE:
            freeze_until = (datetime.now(timezone(timedelta(hours=8))) + timedelta(hours=FREEZE_DURATION_HOURS)).isoformat()
            risk_check["freeze_until"] = freeze_until
            print(f"  [RISK] {risk_check['consecutive_sl']} consecutive SL -> FROZEN until {freeze_until}")
    elif "TP" in reason:
        risk_check["consecutive_sl"] = 0
    state["risk_check"] = risk_check

    # v3.2: Update daily P&L
    today_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    daily_pnl = state.setdefault("daily_pnl", {})
    daily_pnl[today_str] = daily_pnl.get(today_str, 0) + pnl_pct

def monitor_signal_decay(ca, ticker, entry_price, score, sig_id,
                          duration_min=20, interval_sec=45):
    print('')
    print('  [MONITOR] ' + ticker + ' | Entry: ' + str(entry_price) + ' | Score: ' + str(score))
    print('  Monitoring for ' + str(duration_min) + 'min (every ' + str(interval_sec) + 's)')
    end_time = time.time() + duration_min * 60
    last_action = 0
    cooldown_sec = 180
    while time.time() < end_time:
        time.sleep(interval_sec)
        state_now = load_state()
        pos = state_now['positions'].get(ca)
        if not pos:
            print('  [MONITOR] ' + ticker + ' position gone, exiting')
            return
        queue = []
        if os.path.exists(QUEUE_FILE):
            with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
                queue = json.load(f)
        sig = next((s for s in queue
                    if s.get('ca', '').lower() == ca.lower()
                    and s.get('chain') == 'CT_501'), None)
        current_score = sig['score'] if sig else None
        current_price = sig['currentPrice'] if sig else 0
        if not current_price or current_price <= 0:
            current_price = get_price_usd(ca)
        if not current_price or current_price <= 0:
            current_price = pos.get('current_price', 0)
        pnl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0
        ts = datetime.now(timezone(timedelta(hours=8))).strftime('%H:%M:%S')
        score_str = str(current_score) if current_score is not None else '?'
        print('  [' + ts + '] ' + ticker + ' | price=' + str(round(current_price, 10)) + ' (' + str(round(pnl_pct*100,1)) + '%) | score=' + score_str)
        pos['pnl_pct'] = pnl_pct
        pos['current_price'] = current_price
        save_state(state_now)
        if check_position(ca):
            print('  [MONITOR] ' + ticker + ' closed by SL/TP, exiting')
            return
        if time.time() - last_action < cooldown_sec:
            continue
        if current_score is not None:
            drop = score - current_score
            if drop >= 35:
                print('  [!] Score dropped ' + str(drop) + 'pts -> FULL CLOSE')
                check_position(ca, force_sell=True, force_sell_pct=1.0, force_reason='SCORE_DECAY_' + str(drop))
                return
            if drop >= 20:
                bal, _, _ = get_token_balance(ca)
                if bal > 0:
                    print('  [*] Score dropped ' + str(drop) + 'pts -> reduce 50%')
                    sell_token(ca, ticker, 0.5, 'SCORE_DECAY_' + str(drop))
                    last_action = time.time()
        if pnl_pct <= -0.08:
            print('  [!] SL level (' + str(round(pnl_pct*100,1)) + '%), closing full')
            check_position(ca, force_sell=True, force_sell_pct=1.0, force_reason='MONITOR_SL')
            return
        if pnl_pct <= -0.05:
            bal, _, _ = get_token_balance(ca)
            if bal > 0:
                print('  [*] Price crashed ' + str(round(pnl_pct*100,1)) + '% -> reduce 50%')
                sell_token(ca, ticker, 0.5, 'PRICE_CRASH')
                last_action = time.time()
    print('  [MONITOR] ' + ticker + ' monitoring complete')

def main():
    global state
    state = load_state()
    now   = datetime.now(timezone(timedelta(hours=8)))
    print('')
    print('='*50)
    print(' SOLANA EXECUTOR v2.1 |  ' + now.strftime('%Y-%m-%d %H:%M'))
    print(' 0-ERROR | SAFETY | PRECISION')
    print('='*50)
    # ─── v3.2: Risk check ───
    risk_check = state.get("risk_check", {})
    freeze_until = risk_check.get("freeze_until")
    if freeze_until:
        try:
            freeze_dt = datetime.fromisoformat(freeze_until)
            if now < freeze_dt:
                remaining = (freeze_dt - now).total_seconds() / 60
                print(f"  [FROZEN] Trading frozen for {remaining:.0f}min")
                return
            else:
                risk_check["freeze_until"] = None
                risk_check["consecutive_sl"] = 0
                state["risk_check"] = risk_check
        except Exception:
            pass
    daily_pnl = state.get("daily_pnl", {})
    today_str = now.strftime("%Y-%m-%d")
    today_pnl = daily_pnl.get(today_str, 0)
    if today_pnl <= -MAX_DAILY_LOSS_PCT:
        print(f"  [RISK] Daily loss limit hit: {today_pnl*100:.1f}%")
        save_state(state)
        return

    usdt_bal = get_usdt_balance()
    print(' USDT Balance: $' + str(round(usdt_bal, 2)))
    sol_pos  = {ca: p for ca, p in state['positions'].items()
                if str(p.get('chain_id', '')) == SOL_CHAIN}
    sol_open = len(sol_pos)
    print(' Open: ' + str(sol_open) + '/' + str(MAX_POSITIONS))
    queue = []
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
            queue = json.load(f)
    print('')
    print('[ Positions ]')
    for ca, pos in list(sol_pos.items()):
        ticker = pos.get('ticker', '?')
        sig = next((s for s in queue
                    if s.get('ca', '').lower() == ca.lower()
                    and s.get('chain') == 'CT_501'), None)
        current_price = get_price_usd(ca) if not (sig and sig.get('currentPrice')) else sig['currentPrice']
        if current_price <= 0:
            current_price = pos.get('current_price', 0)
        update_position_pnl(ca, current_price)
        if check_position(ca):
            print('  ' + ticker + ' CLOSED')
            save_state(state)
    if sol_open < MAX_POSITIONS and usdt_bal >= MIN_INVEST_USD:
        print('')
        print('[ Signals ]')
        signals = sorted([s for s in queue if s.get('chain') == 'CT_501'],
                        key=lambda x: x.get('score', 0), reverse=True)
        for sig in signals:
            if usdt_bal < MIN_INVEST_USD or sol_open >= MAX_POSITIONS:
                break
            ca     = sig['ca']
            ticker = sig['ticker']
            score  = sig.get('score', 0)
            ep     = sig.get('currentPrice') or sig.get('alertPrice') or 0
            if ca in sol_pos or score < 28:
                continue
            cd = state.get('cooldowns', {}).get(ca)
            if cd:
                try:
                    if now < datetime.fromisoformat(cd):
                        print('  SKIP ' + ticker + ' (cooldown)')
                        continue
                except Exception:
                    pass
            if is_pumpfun_address(ca):
                print('  SKIP ' + ticker + ' (' + ca[:20] + '...) - pump.fun address (non-base58)')
                continue
            print('')
            print('  >>> ' + ticker + ' | score=' + str(score) + ' | ep=' + str(ep))
            to_amt, _, router = get_quote(SOL_USDT, ca, 5.0)
            if to_amt <= 0:
                print('      No liquidity (onchainos cant route), skipping')
                continue
            print('      Liquidity OK | Router: ' + (router[:60] if router else 'N/A'))
            invest = usdt_bal * (0.45 if score >= 50 else 0.3 if score >= 40 else 0.25)
            invest = max(min(invest, usdt_bal), MIN_INVEST_USD)
            to_amt2, _, _ = get_quote(SOL_USDT, ca, invest)
            if to_amt2 <= 0:
                print('      No quote at $' + str(round(invest,2)) + ', skipping')
                continue
            success, tx = buy_token(ca, ticker, invest, ep)
            if success:
                actual_ep = get_price_usd(ca)
                if actual_ep <= 0:
                    actual_ep = ep
                state['positions'][ca] = {
                    'chain': 'Solana', 'chain_id': SOL_CHAIN,
                    'ticker': ticker, 'ca': ca,
                    'entry_price': actual_ep,
                    'invest_amount': invest,
                    'amount': 0,
                    'sl_price': round(actual_ep * (1 + STOP_LOSS_PCT), 12),
                    'tp_price': round(actual_ep * (1 + TAKE_PROFIT_PCT), 12),
                    'pnl_pct': 0, 'pnl_usdt': 0,
                    'entry_time': now.isoformat(),
                    'sig_id': sig.get('sigId', ''),
                    'score': score,
                    'reasons': sig.get('reasons', []),
                    'partial_tp_10': False,
                    'partial_tp_15': False,
                    'breakeven_done': False,
                    'sold_ratio': float(sig.get('soldRatioPercent', 0)),
                    'sold_ratio_triggered': False,
                }
                usdt_bal -= invest
                sol_open += 1
                save_state(state)
    print('')
    print(' Done.')
    return 0

if __name__ == '__main__':
    sys.exit(main())



