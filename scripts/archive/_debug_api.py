import sys, requests
sys.stdout.reconfigure(encoding='utf-8')
API = 'https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai'
HEADERS = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
for cid, name in [(56,'BSC'),(501,'Solana')]:
    try:
        r = requests.get(API, params={'chainId': cid, 'pageSize': 3}, timeout=10, headers=HEADERS)
        d = r.json()
        print(f'{name}: status={r.status_code}')
        print(f'  code={d.get("code")} msg={d.get("message")}')
        print(f'  success={d.get("success")}')
        print(f'  data={d.get("data")}')
    except Exception as e:
        print(f'{name}: ERROR {e}')
