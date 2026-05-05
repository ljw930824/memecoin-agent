"""
api_health_check.py - API 连通性健康检查
每5分钟由 Task Scheduler 调用
检测: Binance Smart Money API + onchainos + BAW CLI
异常时记录告警日志
"""
import sys, os, json, urllib.request, ssl, subprocess, time
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding='utf-8')

DATA_DIR = os.path.join(os.path.expanduser('~'), '.qclaw', 'workspace', 'data')
HEALTH_LOG = os.path.join(DATA_DIR, 'api-health.log')
ALERT_LOG = os.path.join(DATA_DIR, 'api-alerts.log')
os.makedirs(DATA_DIR, exist_ok=True)

BAW_CMD = os.path.expanduser("~\\AppData\\Roaming\\QClaw\\npm-global\\baw.cmd")
if not os.path.isfile(BAW_CMD):
    BAW_CMD = "baw"

now = datetime.now(timezone(timedelta(hours=8)))
ts = now.strftime('%Y-%m-%d %H:%M')
results = {}


def check_binance_api():
    try:
        ssl_ctx = ssl.create_default_context()
        url = 'https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai'
        body = json.dumps({'smartSignalType':'','page':1,'pageSize':5,'chainId':'56'}).encode('utf-8')
        req = urllib.request.Request(url, data=body, headers={'Content-Type':'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as r:
            d = json.loads(r.read().decode('utf-8'))
            code = d.get('code', '')
            items = d.get('data', []) if isinstance(d.get('data'), list) else []
            if code == '000000' or d.get('ok'):
                return True, f'{len(items)} signals'
            return False, f'code={code}'
    except Exception as e:
        return False, str(e)[:80]


_OKX_ENV = os.environ.copy()
_OKX_ENV['OKX_PROD_API_KEY'] = _OKX_ENV.get('OKX_PROD_API_KEY') or _OKX_ENV.get('OKX_API_KEY', '***REMOVED***')
_OKX_ENV['OKX_PROD_SECRET_KEY'] = _OKX_ENV.get('OKX_PROD_SECRET_KEY') or _OKX_ENV.get('OKX_SECRET_KEY', '***REMOVED***')
_OKX_ENV['OKX_PROD_PASSPHRASE'] = _OKX_ENV.get('OKX_PROD_PASSPHRASE') or _OKX_ENV.get('OKX_PASSPHRASE', '***REMOVED***')
_OKX_ENV['OKX_API_KEY'] = _OKX_ENV['OKX_PROD_API_KEY']
_OKX_ENV['OKX_SECRET_KEY'] = _OKX_ENV['OKX_PROD_SECRET_KEY']
_OKX_ENV['OKX_PASSPHRASE'] = _OKX_ENV['OKX_PROD_PASSPHRASE']

def check_onchainos():
    try:
        r = subprocess.run(
            ['onchainos', 'signal', 'list', '--chain', 'solana', '--limit', '3'],
            capture_output=True, text=True, timeout=15, encoding='utf-8',
            env=_OKX_ENV
        )
        if r.returncode == 0:
            try:
                d = json.loads(r.stdout)
                count = len(d.get('data', []))
                return True, f'{count} signals'
            except json.JSONDecodeError:
                return True, 'response OK (non-JSON)'
        return False, r.stderr[:80] if r.stderr else f'exit={r.returncode}'
    except Exception as e:
        return False, str(e)[:80]


def check_baw():
    try:
        r = subprocess.run(
            [BAW_CMD, 'wallet', 'status'],
            capture_output=True, text=True, timeout=15, encoding='utf-8'
        )
        if r.returncode == 0 and 'Logged in' in r.stdout:
            return True, 'Logged in'
        return False, r.stdout[:80] if r.stdout else f'exit={r.returncode}'
    except Exception as e:
        return False, str(e)[:80]


# Run checks
for name, fn in [('binance_api', check_binance_api), ('onchainos', check_onchainos), ('baw', check_baw)]:
    ok, detail = fn()
    results[name] = {'ok': ok, 'detail': detail}
    status = 'OK' if ok else 'FAIL'
    print(f'  [{status}] {name}: {detail}')

# Write health log
all_ok = all(r['ok'] for r in results.values())
log_line = f'[{ts}] {"ALL_OK" if all_ok else "ISSUE"} | ' + ' | '.join(f'{k}={v["detail"]}' for k, v in results.items())
with open(HEALTH_LOG, 'a', encoding='utf-8') as f:
    f.write(log_line + '\n')

# Alert on failure
if not all_ok:
    failed = [f'{k}: {v["detail"]}' for k, v in results.items() if not v['ok']]
    alert = f'[{ts}] API ALERT: {"; ".join(failed)}'
    print(f'  [ALERT] {alert}')
    with open(ALERT_LOG, 'a', encoding='utf-8') as f:
        f.write(alert + '\n')
