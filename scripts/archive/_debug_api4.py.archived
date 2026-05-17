import sys, json, urllib.request
sys.stdout.reconfigure(encoding='utf-8')

API = 'https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai'

body = json.dumps({'smartSignalType': '', 'page': 1, 'pageSize': 3, 'chainId': 'CT_501'}).encode()
headers = {'Content-Type': 'application/json', 'Accept-Encoding': 'identity',
           'User-Agent': 'binance-web3/1.1 (Skill)'}
req = urllib.request.Request(API, data=body, headers=headers, method='POST')
with urllib.request.urlopen(req, timeout=12) as resp:
    data = json.loads(resp.read().decode('utf-8'))

print('Top-level keys:', list(data.keys()))
d = data.get('data', [])
print('data type:', type(d).__name__, 'len:', len(d))
if d:
    print('\nFirst item keys:', list(d[0].keys()))
    print('\nFirst item:')
    print(json.dumps(d[0], indent=2, ensure_ascii=False))
