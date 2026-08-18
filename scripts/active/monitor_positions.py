# -*- coding: utf-8 -*-
"""
monitor_positions.py - High-frequency position monitor (60s interval)
Only checks existing positions for SL/TP and signal decay.
Does NOT open new positions.
v2.1 - 0-error precision + safety
"""
import json, math, os, sys, time, subprocess
from datetime import datetime, timezone, timedelta

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from qclaw_trading_common import (  # noqa: E402
    locked_read_json,
    locked_write_json,
    okx_env_for_subprocess,
    signal_chain_is_solana,
    telegram_env,
    workspace_root,
)

DATA_DIR   = os.path.join(workspace_root(__file__), 'data')
STATE_FILE_BSC = os.path.join(DATA_DIR, 'smart-money-bsc-state.json')
STATE_FILE_SOL = os.path.join(DATA_DIR, 'smart-money-sol-state.json')
STATE_FILES = [STATE_FILE_BSC, STATE_FILE_SOL]  # monitor reads both separated state files
QUEUE_FILE = os.path.join(DATA_DIR, 'signal-queue.json')
RETRY_LOG  = os.path.join(DATA_DIR, 'retry-log.txt')
TRADE_LOG  = os.path.join(DATA_DIR, 'trade-log.json')
ONCHAINOS  = r'C:\Users\dell\.local\bin\onchainos.exe'
WALLET_ADDR = '77BP1JzBARGaQ8eJWj6B1RYvaB4zRxU7Nx7BDYdgLCAa'
SOL_USDT    = 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB'
def load_state():
    merged = {'positions': {}, 'cooldowns': {}}
    for sf in STATE_FILES:
        s = locked_read_json(sf, {'positions': {}, 'cooldowns': {}})
        merged['positions'].update(s.get('positions', {}))
        merged['cooldowns'].update(s.get('cooldowns', {}))
    return merged

def save_state(s):
    # Split positions by chain and write to correct state file
    bsc_pos = {ca: p for ca, p in s.get('positions', {}).items() if p.get('chain_id') == '56' or p.get('chain') == 'bsc'}
    sol_pos = {ca: p for ca, p in s.get('positions', {}).items() if p.get('chain_id') != '56' and p.get('chain') != 'bsc'}
    bsc_state = {'positions': bsc_pos, 'cooldowns': {}}
    sol_state = {'positions': sol_pos, 'cooldowns': {}}
    locked_write_json(STATE_FILE_BSC, bsc_state)
    locked_write_json(STATE_FILE_SOL, sol_state)

def notify(msg):
    TG_TOKEN, TG_CHAT_ID = telegram_env()
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
        try:
            with open(TRADE_LOG, 'r', encoding='utf-8') as f:
                log = json.load(f)
        except Exception:
            log = []
    log.append(entry)
    if len(log) > 5000:
        log = log[-5000:]
    with open(TRADE_LOG, 'w', encoding='utf-8') as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

OKX_ENV = okx_env_for_subprocess() or os.environ.copy()

def ocoin_run(args, timeout=30, retries=1):
    cmd = [ONCHAINOS] + args
    for attempt in range(max(1, retries)):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=timeout, encoding='utf-8', errors='replace',
                                    env=OKX_ENV)
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            code = result.returncode
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

def get_price_usd(ca):
    for attempt in range(3):
        out, err, code = ocoin_run([
            'swap', 'quote', '--chain', 'Solana',
            '--from', SOL_USDT, '--to', ca, '--readable-amount', '1.0'
        ], timeout=20)
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

def get_token_balance(ca):
    for attempt in range(3):
        out, err, code = ocoin_run(['wallet', 'balance'], timeout=20)
        if code == 0 and out:
            try:
                d = json.loads(out)
                details = d.get('data', {}).get('details', d.get('details', []))
                for detail in details:
                    for ta in detail.get('tokenAssets', []):
                        if str(ta.get('chainIndex', '')) != '501':
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
    return 0.0, 0, 6

def swap_execute(from_token, to_token, amount, slippage='2.0'):
    out, err, code = ocoin_run([
        'swap', 'execute',
        '--from', from_token, '--to', to_token,
        '--chain', 'Solana', '--wallet', WALLET_ADDR,
        '--slippage', slippage, '--readable-amount', str(amount),
    ], timeout=90)
    if code != 0:
        return False, err or out[:100]
    try:
        d = json.loads(out)
        if d.get('ok'):
            return True, d.get('data', {}).get('swapTxHash', 'unknown')
        return False, str(d.get('error', out[:100]))
    except Exception:
        return False, err or out[:100]

def swap_execute_raw(from_token, to_token, amount_raw, slippage='2.0'):
    out, err, code = ocoin_run([
        'swap', 'execute',
        '--from', from_token, '--to', to_token,
        '--chain', 'Solana', '--wallet', WALLET_ADDR,
        '--slippage', slippage, '--amount', str(int(amount_raw)),
    ], timeout=90)
    if code != 0:
        return False, err or out[:100]
    try:
        d = json.loads(out)
        if d.get('ok'):
            return True, d.get('data', {}).get('swapTxHash', 'unknown')
        return False, str(d.get('error', out[:100]))
    except Exception:
        return False, err or out[:100]

def sell_token(ca, ticker, pct=1.0, reason=''):
    bal, raw_bal, dec = get_token_balance(ca)
    if bal <= 0:
        return False, 'no_balance'
    if pct >= 0.99:
        sell_raw = int(raw_bal * pct)
        if sell_raw <= 0:
            return False, 'zero'
        print('  >> SELL ' + ticker + ' | ALL (raw=' + str(sell_raw) + ') (' + reason + ')')
        for attempt in range(1, 4):
            success, tx = swap_execute_raw(ca, SOL_USDT, sell_raw, slippage='2.0')
            if success:
                print('     SUCCESS | TX: ' + tx)
                return True, tx
            print('     Attempt ' + str(attempt) + ' failed: ' + tx)
            ts = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
            with open(RETRY_LOG, 'a', encoding='utf-8') as f:
                f.write(f'[{ts}] SOL-MON | {ticker} | SELL_{reason} | {tx[:80]} | attempt #{attempt}\n')
            time.sleep(5)
    else:
        sell_amt = math.floor(bal * pct * (10 ** dec)) / (10 ** dec)
        if sell_amt <= 0:
            return False, 'zero'
        print('  >> SELL ' + ticker + ' | ' + str(sell_amt) + ' (' + reason + ')')
        for attempt in range(1, 4):
            success, tx = swap_execute(ca, SOL_USDT, sell_amt, slippage='2.0')
            if success:
                print('     SUCCESS | TX: ' + tx)
                return True, tx
            print('     Attempt ' + str(attempt) + ' failed: ' + tx)
            ts = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
            with open(RETRY_LOG, 'a', encoding='utf-8') as f:
                f.write(f'[{ts}] SOL-MON | {ticker} | SELL_{reason} | {tx[:80]} | attempt #{attempt}\n')
            time.sleep(5)
    notify('&#x1F6A8; <b>Monitor SELL FAILED</b>\n' + ticker + ' | ' + reason)
    return False, ''

def check_sl_tp(ca, pos):
    ticker   = pos.get('ticker', '?')
    cur_p    = float(pos.get('current_price', 0))
    ep       = float(pos.get('entry_price', 0))
    sl_price = float(pos.get('sl_price', 0))
    tp_price = float(pos.get('tp_price', 0))
    pnl_pct  = pos.get('pnl_pct', 0)
    now      = datetime.now(timezone(timedelta(hours=8)))

    if ep == 0:
        return False, ''

    if sl_price > 0 and cur_p <= sl_price:
        print('  [!] ' + ticker + ' SL HIT (' + str(round(pnl_pct*100,1)) + '%)')
        success, tx = sell_token(ca, ticker, 1.0, 'SL_HIT')
        if success:
            log_trade({'ts': now.isoformat(), 'chain': 'Solana', 'ticker': ticker, 'ca': ca,
                       'reason': 'SL_HIT', 'entry_price': ep, 'invest': pos.get('invest_amount', 0),
                       'pnl_pct': pnl_pct, 'pnl_usdt': pos.get('pnl_usdt', 0)})
        return success, 'SL_HIT'

    if tp_price > 0 and cur_p >= tp_price:
        print('  [!] ' + ticker + ' TP HIT (+' + str(round(pnl_pct*100,1)) + '%)')
        success, tx = sell_token(ca, ticker, 1.0, 'TP_HIT')
        if success:
            log_trade({'ts': now.isoformat(), 'chain': 'Solana', 'ticker': ticker, 'ca': ca,
                       'reason': 'TP_HIT', 'entry_price': ep, 'invest': pos.get('invest_amount', 0),
                       'pnl_pct': pnl_pct, 'pnl_usdt': pos.get('pnl_usdt', 0)})
        return success, 'TP_HIT'

    return False, ''

def main():
    state = load_state()
    now   = datetime.now(timezone(timedelta(hours=8)))
    sol_pos = {ca: p for ca, p in state.get('positions', {}).items()
               if str(p.get('chain_id', '')) == '501'}
    if not sol_pos:
        print('[Monitor] No Solana positions.')
        return 0

    queue = []
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
            queue = json.load(f)

    print('')
    print('='*45)
    print(' MONITOR v2.1 | ' + now.strftime('%H:%M:%S') + ' | ' + str(len(sol_pos)) + ' pos')
    print('='*45)

    for ca, pos in list(sol_pos.items()):
        ticker = pos.get('ticker', '?')
        ep     = float(pos.get('entry_price', 0))
        score  = pos.get('score', 0)

        sig = next((s for s in queue
                    if s.get('ca', '').lower() == ca.lower()
                    and signal_chain_is_solana(s)), None)
        current_price = sig['currentPrice'] if sig else 0
        if not current_price or current_price <= 0:
            current_price = get_price_usd(ca)
        if not current_price or current_price <= 0:
            current_price = pos.get('current_price', 0)

        pnl_pct = (current_price - ep) / ep if ep > 0 else 0
        pos['pnl_pct'] = pnl_pct
        pos['current_price'] = current_price

        print('  ' + ticker + ' | $' + str(round(current_price, 10)) + ' | ' + str(round(pnl_pct*100,1)) + '%')

        closed, reason = check_sl_tp(ca, pos)
        if closed:
            del state['positions'][ca]
            state['cooldowns'][ca] = (now + timedelta(hours=12 if pnl_pct < 0 else 6)).isoformat()
            save_state(state)
            notify('&#x1F4C8; <b>' + ticker + ' ' + reason + '</b>\nP&L: ' + str(round(pnl_pct*100,1)) + '%')
            continue

        if pnl_pct >= 0.10 and not pos.get('partial_tp_10'):
            print('  [*] ' + ticker + ' +10% -> partial TP 50%')
            if sell_token(ca, ticker, 0.5, 'PARTIAL_TP10')[0]:
                pos['partial_tp_10'] = True
                pos['sl_price'] = max(float(pos['sl_price']), ep)
                pos['invest_amount'] = float(pos.get('invest_amount', 0)) * 0.5

        if pnl_pct >= 0.15 and not pos.get('partial_tp_15'):
            print('  [*] ' + ticker + ' +15% -> partial TP 25%')
            if sell_token(ca, ticker, 0.5, 'PARTIAL_TP15')[0]:
                pos['partial_tp_15'] = True
                pos['sl_price'] = max(float(pos['sl_price']), ep * 1.03)
                pos['invest_amount'] = float(pos.get('invest_amount', 0)) * 0.5

        if pnl_pct >= 0.08 and not pos.get('breakeven_done'):
            pos['sl_price'] = max(float(pos['sl_price']), ep)
            pos['breakeven_done'] = True

        if sig:
            current_score = sig.get('score', 0)
            drop = score - current_score
            if drop >= 35:
                print('  [!] Score dropped ' + str(drop) + ' -> FULL CLOSE')
                if sell_token(ca, ticker, 1.0, 'SCORE_DECAY_' + str(drop))[0]:
                    del state['positions'][ca]
                    state['cooldowns'][ca] = (now + timedelta(hours=12)).isoformat()
                    save_state(state)
                    notify('&#x1F6A8; <b>' + ticker + ' closed (score decay ' + str(drop) + ')</b>')
            elif drop >= 20:
                print('  [*] Score dropped ' + str(drop) + ' -> reduce 50%')
                if sell_token(ca, ticker, 0.5, 'SCORE_DECAY_' + str(drop))[0]:
                    pass

    save_state(state)
    print('='*45)
    return 0

if __name__ == '__main__':
    sys.exit(main())
